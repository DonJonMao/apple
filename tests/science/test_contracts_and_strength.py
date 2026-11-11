from datetime import datetime, timedelta, timezone

import pytest

from healthzip.science import (
    ParameterRegistry,
    definitions,
    evaluate,
    evaluate_all,
    validate_result,
)
from healthzip.science.contracts import Window, select_as_of
from healthzip.science.formulas import e1rm
from healthzip.science.semantics import comparable, load_change, load_components
from healthzip.science.statistics import linear_trend

START = "2026-08-01T00:00:00+00:00"
END = "2026-12-01T00:00:00+00:00"
CUTOFF = "2026-11-11T12:00:00+00:00"


def row(index=1, **values):
    moment = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(days=index * 2)
    return {"id": f"set-{index}", "set_id": f"set-{index}", "session_id": f"session-{index}",
            "user_id": "synthetic", "exercise_id": "bench", "definition_version": 1,
            "equipment_instance_id": "bar-1", "load_basis": "external_total_kg",
            "load_basis_confirmed": True, "load_value": 60, "load_unit": "kg",
            "measurement_mode": "repetitions", "side": "bilateral", "repetition_semantics": "both_together",
            "rom_protocol": "full_declared", "settings": {}, "settings_confirmed": True,
            "reference_protocol": "first_work_set", "reference_policy_id": "first-work-v1",
            "set_position": 1, "effort_protocol": "target-rir-2", "tempo": "controlled", "rest_protocol": "user-180s",
            "role": "work", "status": "completed", "reps": 10, "rir": 2, "stop_reason": "target_rir_stop",
            "is_reference": True, "reference_declared_at": "2026-08-01T00:00:00+00:00", "quality_status": "acceptable", "event_end": moment.isoformat(),
            "available_at": moment.isoformat(), "_event_end": moment.isoformat(), **values}


def run(metric, rows=None, context=None, **kwargs):
    return evaluate(metric, rows or [], cutoff_time=kwargs.get("cutoff_time", CUTOFF),
                    window_start=kwargs.get("window_start", START), window_end=kwargs.get("window_end", END),
                    context=context or {})


@pytest.mark.parametrize("metric_id", list(definitions()))
def test_every_registered_metric_has_executable_contract_on_empty_data(metric_id):
    value = run(metric_id)
    validate_result(value)
    assert value["metric_id"] == metric_id
    assert value["evidence_status"] not in {"predictive_validated_for_scope", "intervention_validated_for_scope"}


def test_contract_separates_scenario_probability_and_validation():
    value = run("STR-01", [row()])
    value["uncertainty"] = {"kind": "scenario_range", "lower": 1, "upper": 2, "level": .95, "assumptions": []}
    with pytest.raises(ValueError, match="scenario"):
        validate_result(value)
    value["uncertainty"]["level"] = None
    value["evidence_status"] = "predictive_validated_for_scope"
    with pytest.raises(ValueError, match="real_validation"):
        validate_result(value)


def test_asof_revision_available_at_deleted_and_unknown_are_distinct():
    original = row(1, source_record_id="uuid", available_at="2026-10-03T10:00:00+00:00")
    future = row(2, source_record_id="uuid", event_end=original["event_end"], available_at="2026-10-03T15:00:00+00:00", reps=99)
    unknown = row(3, available_at=None)
    window = Window(START, END, "2026-10-03T12:00:00+00:00")
    selected, excluded = select_as_of([original, future, unknown], window)
    assert [r["reps"] for r in selected] == [10]
    assert "available_after_cutoff" in {e["reason"] for e in excluded}
    tombstone = {**future, "id": "delete", "record_status": "deleted"}
    selected, _ = select_as_of([original, tombstone], Window(START, END, CUTOFF))
    assert selected == []


def test_revision_order_compares_instants_across_timezone_offsets():
    earlier = row(1, source_record_id="uuid", available_at="2026-10-03T12:00:00+08:00", reps=8)
    later = row(2, source_record_id="uuid", available_at="2026-10-03T06:00:00+00:00", reps=10,
                event_end=earlier["event_end"])
    selected, _ = select_as_of([earlier, later], Window(START, END, CUTOFF))
    assert [r["reps"] for r in selected] == [10]


@pytest.mark.parametrize("case_id", ["STR-01-T01", "STR-01-T02", "STR-01-T03"])
def test_work_set_structure_and_retries(case_id):
    records = [row(i) for i in range(1, 4)]
    if case_id.endswith("T01"):
        records += [row(4, role="warmup"), row(5, role="warmup")]
        value = run("STR-01", records)["value"]
        assert value["completed_work_parent_sets"] == 3 and value["warmup_sets"] == 2
    elif case_id.endswith("T02"):
        records = [row(i, parent_set_id="drop", session_id="one", set_structure="drop") for i in range(1, 4)]
        value = run("STR-01", records)["value"]
        assert value["completed_work_parent_sets"] == 1 and value["segments"] == 3
    else:
        assert run("STR-01", [row(), row()])["value"]["completed_work_parent_sets"] == 1
    assert run("STR-01")["value"] is None


def test_isometric_and_side_observations_keep_original_units():
    hold = run("STR-02", [row(measurement_mode="duration", duration_s=60, reps=None)])["value"][0]
    assert hold["duration_s"] == 60 and hold["reps"] is None
    sides = run("STR-02", [row(1, side="left"), row(2, side="right")])["value"]
    assert [(s["side"], s["reps"]) for s in sides] == [("left", 10), ("right", 10)]


def test_plate_load_and_assistance_semantics():
    a = row(load_basis="plates_per_side_kg", load_value=30, symmetric_loading=True, effective_bar_mass_kg=None)
    b = {**a, "load_value": 32.5}
    components = load_components(a)
    assert components["plate_total_kg"] == 60 and components["total_load_kg"] is None
    change = load_change(a, b)
    assert change["plate_total_change_kg"] == 5 and change["total_load_change_percent"] is None
    assisted = row(load_basis="assistance_setting", load_value=40)
    change = load_change(assisted, {**assisted, "load_value": 35})
    assert change["entered_change"] == -5 and change["direction"] == "harder"
    assert comparable(a, {**a, "side": "left"})[0] is False
    assert comparable(a, {**a, "rom_protocol": "partial"})[0] is False
    assert comparable(a, {**a, "load_basis": "unknown"})[0] is False


def test_volume_is_exact_bookkeeping_and_missing_part_is_visible():
    records = [row(i) for i in range(1, 4)]
    result = run("STR-04", records)
    assert sum(g["sum_kg_reps"] for g in result["value"]["groups"]) == 1800
    records[-1]["reps"] = None
    result = run("STR-04", records)
    assert sum(g["sum_kg_reps"] for g in result["value"]["groups"]) == 1200
    assert result["valid_n"] == 2 and result["total_n"] == 3


def test_muscle_mapping_requires_review_and_direct_indirect_stay_separate():
    assert run("STR-05", [row()])["value"] is None
    context = {"muscle_mappings": {"bench": {"review_status": "approved", "version": "1", "direct": ["chest"], "indirect": ["triceps"]}}}
    assert run("STR-05", [row()], context)["value"]["groups"][0]["muscle"] == "chest"
    assert run("STR-06", [row()], context)["value"]["groups"][0]["muscle"] == "triceps"


def test_plan_unknown_denominator_and_extra_sets():
    context = {"plan_snapshot": {"sets": [{"id": str(i)} for i in range(3)]}}
    records = [row(1, planned_set_id="0"), row(2, planned_set_id="1")]
    output = run("STR-09", records, context)
    assert output["value"]["completed_fraction_of_plan"] == 2 / 3
    assert output["value"]["unknown"] == 1 and output["data_status"] == "partial"
    records.append(row(3, planned_set_id="2", status="skipped"))
    assert run("STR-09", records, context)["value"]["unknown"] == 0
    assert run("STR-09", records)["data_status"] == "not_applicable"


def test_reference_not_hindsight_best_and_effort_not_repetitions():
    records = [row(1, is_reference=False, reps=20)]
    assert run("STR-11", records)["value"] is None
    a, b = row(1, rir=2), row(2, rir=4)
    result = run("STR-14", [a, b])["value"]
    assert result["delta_rir"] == 2 and result["effort_direction"] == "easier_reported"
    assert b["reps"] == 10
    assert run("STR-12", [a, {**b, "reps": 11}])["value"]["delta_reps"] == 1
    assert run("STR-10", [row(rir=None, rpe=8, scale_type="session_rpe")])["value"][0]["rir"] is None


def test_within_session_repetition_series_not_fatigue_diagnosis():
    records = [row(i, session_id="one", set_position=i, reps=reps) for i, reps in enumerate((10, 8, 7), 1)]
    result = run("STR-15", records)["value"]
    assert [v["delta_reps"] for v in result] == [0, -2, -3]


def test_formula_versions_domain_missing_rir_and_no_clipping():
    domain = {"min_reps": 2, "max_reps": 12, "max_rir": 3, "scope_id": "synthetic-research"}
    a = e1rm(60, 10, formula_id="epley_n3_0.0333", domain=domain, load_basis="external_total_kg")
    b = e1rm(60, 10, formula_id="epley_r_over_30", domain=domain, load_basis="external_total_kg")
    assert a["value"] == pytest.approx(79.98) and b["value"] == 80
    assert a["formula_id"] != b["formula_id"]
    assert e1rm(60, 20, domain=domain, load_basis="external_total_kg")["value"] is None
    assert e1rm(60, 10, formula_id="epley_rir_over_30", rir=None, domain=domain, load_basis="external_total_kg")["value"] is None
    assert e1rm(30, 10, domain=domain, load_basis="plates_per_side_kg")["value"] is None
    assert e1rm(60, 1, domain=domain, load_basis="external_total_kg", measured_maximum=True)["value"] is None


def test_real_time_regression_and_zero_error_do_not_imply_plateau():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def observations(days, values):
        return [{"session_id": str(i), "event_end": (base + timedelta(days=d)).isoformat(), "value": v} for i, (d, v) in enumerate(zip(days, values))]
    a = linear_trend(observations([0, 7, 21], [10, 11, 12]))
    b = linear_trend(observations([0, 7, 14], [10, 11, 12]))
    assert a["slope_per_day"] != b["slope_per_day"]
    assert linear_trend(observations([0, 7, 14], [10, 10, 10]))["interval"] is None
    context = {"practical_equivalence": {"lower_magnitude": 1, "upper_magnitude": 1, "declared_before": START}, "measurement_sd": 1}
    output = run("STR-22", [row(1, stop_reason="planned_stop", rir=None), row(2, stop_reason="planned_stop", rir=None)], context)
    assert output["value"]["classification"] == "opportunity_unchecked"
    output = run("STR-22", [row(1), row(2), row(3)], context)
    assert output["value"]["classification"] == "uncertain"
    assert "target_calibration_missing_or_scope_mismatch" in output["reason_codes"]


def test_registry_versions_error_budget_and_simulation_gate(tmp_path):
    registry = ParameterRegistry(str(tmp_path / "registry.db"))
    registry.register_family("family", .05, {"declared_before": START, "metrics": ["STR-22"], "scope": "all actions"})
    first = registry.allocate_look("family", "same-data", "STR-22")
    assert all(registry.allocate_look("family", "same-data", "STR-22") == first for _ in range(10))
    allocated = [first] + [registry.allocate_look("family", str(i), "STR-22") for i in range(100)]
    assert sum(v["alpha_look"] for v in allocated) < .05
    with pytest.raises(ValueError, match="immutable"):
        registry.register_family("family", .1, {"declared_before": START})
    registry.close()


def reviewed_principle():
    return {"id": "synthetic-reviewed-principle", "version": "1", "review_status": "approved",
            "reviewer": "synthetic-test-reviewer", "reviewed_at": START, "capability": "progression_candidate",
            "evidence_spans": ["synthetic-source:section-1"], "rights_verified": True, "scope_matches": True}


def test_candidate_uses_plan_equipment_and_review_not_readiness_multiplier():
    history = row(load_basis="plates_per_side_kg", load_value=30, symmetric_loading=True)
    context = {"progression_plan": {"rep_upper": 10, "target_rir_min": 1, "target_rir_max": 3,
                                    "available_loads": [30, 32.5, 35], "next_target_reps": 8}}
    assert run("STR-25", [history], context)["value"]["next_load"] is None
    context["reviewed_principles"] = [reviewed_principle()]
    result = run("STR-25", [history], context)["value"]
    assert result["next_load"] == 32.5 and result["changes"]["plate_total_change_kg"] == 5
    assert result["expected_success"] is None
    context["sleep_hours"] = 1
    assert run("STR-25", [history], context)["value"]["next_load"] == 32.5
    assisted = row(load_basis="assistance_setting", load_value=40)
    context["progression_plan"]["available_loads"] = [30, 35, 40, 45]
    assert run("STR-25", [assisted], context)["value"]["next_load"] == 35
    context["allowed_trial_actions"] = ["heavier_lower_reps"]
    trial = run("STR-26", [assisted], context)["value"]["task_trial"]
    assert trial["load_value"] == 35 and trial["changes"]["direction"] == "harder"


def test_followup_targets_are_frozen_and_unknowns_keep_denominators():
    context = {"recommendation_outcomes": [{"recommendation_id": str(i), "event_end": "2026-10-10T12:00:00+00:00", "available_at": "2026-10-10T12:01:00+00:00", "adoption": "adopted" if i < 3 else "not_adopted" if i < 5 else None,
                                            "execution_state": "executed" if i < 5 else "unknown",
                                            "frozen_targets": {"load": {"min": 32.5, "max": 32.5}, "reps": {"min": 8, "max": 8}},
                                            "actual": {"load": 30, "reps": 10} if i < 5 else {}, "quality_comparable": True} for i in range(10)]}
    value = run("STR-28", context=context)["value"]
    assert value["adoption_numerator"] == 3 and value["adoption_denominator"] == 5 and value["unanswered"] == 5
    assert value["success_numerator"] == 0 and value["missing_outcomes"] == 5


def test_nonexecution_and_unknown_execution_cannot_count_success():
    rows = [{"recommendation_id": str(i), "event_end": "2026-10-10T12:00:00+00:00",
             "available_at": "2026-10-10T12:01:00+00:00", "execution_state": state,
             "frozen_targets": {"reps": {"min": 8, "max": 8}}, "actual": {"reps": 8},
             "quality_comparable": True, "adoption": "adopted"}
            for i, state in enumerate(("executed", "not_executed", "unknown", "partially_executed", None))]
    context = {"recommendation_outcomes": rows}
    detail = run("STR-27", context=context)["value"]
    assert [item["short_term_success"] for item in detail] == [True, None, None, None, None]
    summary = run("STR-28", context=context)["value"]
    assert summary["success_numerator"] == 1 and summary["success_denominator"] == 1
    assert summary["missing_outcomes"] == 4 and summary["adoption_denominator"] == 5


def test_full_metric_execution_uses_one_schema_for_nonempty_mixed_input():
    outputs = evaluate_all([row(), {"id": "rhr", "record_kind": "health_sample", "canonical_type": "resting_heart_rate_bpm",
                                    "normalized_value": 60, "event_end": "2026-10-01T08:00:00+00:00", "available_at": "2026-10-01T09:00:00+00:00"}],
                           cutoff_time=CUTOFF, window_start=START, window_end=END)
    assert len(outputs) == 77
    assert outputs["STR-01"]["value"]["completed_work_parent_sets"] == 1
    assert outputs["STATE-RHR"]["value"]
