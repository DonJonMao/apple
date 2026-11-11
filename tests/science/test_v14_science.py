"""v1.4 counterexamples. Synthetic software checks, never scientific validation."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from test_contracts_and_strength import CUTOFF, END, START, row, run

from healthzip.science import evaluate_all
from healthzip.science.registry import calibration_matches


def sleep_record(identity, start, end, stage="asleep", source="watch"):
    return {"id": identity, "record_kind": "health_sample", "canonical_type": "sleep_stage", "stage": stage,
            "source_name": source, "event_start": start, "event_end": end, "available_at": end}


@pytest.mark.parametrize("zone,day", [("UTC", "2026-03-08"), ("Asia/Shanghai", "2026-03-08"),
                                    ("America/New_York", "2026-03-08"), ("America/New_York", "2026-11-01")])
@pytest.mark.parametrize("epsilon", [-1, 0, 1])
def test_f02_sleep_coverage_uses_clipped_half_open_local_dates(zone, day, epsilon):
    start = datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(zone))
    end = start + timedelta(days=1)
    # A record ending just after the window is visible at the later cutoff but
    # only its support inside the requested window contributes to coverage.
    cutoff = end + timedelta(seconds=1)
    records = [sleep_record("morning", (start+timedelta(hours=1)).isoformat(), (start+timedelta(hours=6)).isoformat()),
               sleep_record("late", (start+timedelta(hours=23)).isoformat(), (end+timedelta(microseconds=epsilon)).isoformat())]
    metrics = evaluate_all(records, window_start=start.isoformat(), window_end=end.isoformat(),
                           cutoff_time=cutoff.isoformat(), context={"timezone": zone})
    metric = metrics["STATE-SLEEP-COVERAGE"]
    assert metric["value"]["recorded_dates"] == metric["value"]["elapsed_dates"] == 1
    assert metric["value"]["fraction"] == 1
    assert metrics["STR-01"]["metric_id"] == "STR-01"


def test_f09_irrelevant_inbed_source_does_not_block_asleep_observation():
    watch = sleep_record("watch", "2026-11-10T23:00:00Z", "2026-11-11T06:00:00Z")
    phone = sleep_record("phone", "2026-11-10T22:00:00Z", "2026-11-11T06:00:00Z", "in_bed", "iphone")
    value = run("STATE-SLEEP-24H", [watch, phone])
    assert value["value"]["observed_minutes"] == 420
    assert run("STATE-SLEEP-24H", [watch])["value"] == value["value"]
    second = {**watch, "id": "other", "source_name": "another_watch"}
    assert run("STATE-SLEEP-24H", [watch, second])["data_status"] == "incompatible"


def principle_context():
    # Explicit isolated rule shape only. This is not a published real approval.
    return {"allowed_trial_actions": ["heavier_lower_reps", "maintain_and_collect_reference"],
            "progression_plan": {"available_loads": [50, 52.5], "next_target_reps": 6,
                                 "rep_upper": 12, "target_rir_min": 1, "target_rir_max": 3},
            "reviewed_principles": [{"id": "synthetic-rule-shape", "version": "1", "review_status": "approved",
                "reviewer": "isolated_test", "reviewed_at": START, "capability": "progression_candidate",
                "permitted_actions": ["double_progression", "heavier_lower_reps"],
                "scope_matches": True, "rights_verified": True, "evidence_spans": ["synthetic"]}]}


@pytest.mark.parametrize("changes", [{"pain_flag": True}, {"stop_reason": "pain"},
    {"quality_status": "technique_limited"}, {"pain_flag": None}, {"quality_status": None}, {"stop_reason": None}])
@pytest.mark.parametrize("metric_id", ["STR-25", "STR-26"])
def test_f04_restricted_or_unknown_reference_cannot_license_harder_task(changes, metric_id):
    value = run(metric_id, [row(load_value=50, reps=12, pain_flag=False, **changes) if "pain_flag" not in changes
                           else row(load_value=50, reps=12, **changes)], principle_context())
    assert not (value.get("value") or {}).get("next_load")
    assert not (value.get("value") or {}).get("task_trial")
    assert value["candidate_applicability"]["applicable"] is not True


def test_f03_current_nonreference_observation_vetoes_good_historical_baseline():
    previous = row(load_value=50, reps=12, pain_flag=False)
    current = row(2, is_reference=False, pain_flag=True, stop_reason="pain", quality_status="technique_limited")
    value = run("STR-26", [previous], {**principle_context(), "current_session_observations": [current]})
    assert not (value.get("value") or {}).get("task_trial")
    assert value["candidate_applicability"]["current_session_record_ids"] == [current["id"]]


def test_f03_current_unknown_observation_timestamp_cannot_disappear_as_empty_normal_context():
    previous = row(load_value=50, reps=12, pain_flag=False)
    current = row(2, is_reference=False, pain_flag=True, event_end=None, _event_end=None)
    value = run("STR-26", [previous], {**principle_context(), "current_session_observations": [current]})
    assert not (value.get("value") or {}).get("task_trial")
    assert value["candidate_applicability"]["applicable"] is None
    assert "current_observation_time_or_availability_unknown" in value["candidate_applicability"]["reason_codes"]


def test_f07_multiple_loads_preserve_separate_descriptive_series():
    records = [row(index+1, load_value=load, reps=reps) for index, (load, reps) in
               enumerate([(30, 10), (30, 12), (30, 11), (32.5, 8), (32.5, 10), (32.5, 9)])]
    output = evaluate_all(records, cutoff_time=CUTOFF, window_start=START, window_end=END)
    tasks = output["STR-19"]["task_results"]
    assert len(tasks) == 1
    series = tasks[0]["metric"]["series_results"]
    assert len(series) == 2 and len({s["outcome_series_id"] for s in series}) == 2
    assert {s["normalized_load"] for s in series} == {30, 32.5}
    assert all(s["metric"]["value"]["n"] == 3 and s["metric"]["value"]["interval"] is None for s in series)
    alone = run("STR-19", records[3:])
    current = next(s for s in series if s["normalized_load"] == 32.5)
    assert current["metric"]["value"]["slope_per_day"] == alone["value"]["slope_per_day"]
    assert run("STR-13", [records[0], records[4]])["value"]["total_load_change_kg"] == 2.5


def test_f08_scope_subset_cannot_broaden_calibration_and_audit_fields_do_not_narrow_it():
    required = {"exercise": "bench", "population": "trained_adults", "outcome": "repetitions", "reference": "reference_v1"}
    artifact = {"scope_status": "validated_for_scope", "data_kind": "real", "independent_holdout": True,
                "metric_ids": ["STR-22"], "model_version": "synthetic-shape-only", "scope": required,
                "required_scope": list(required)}
    assert not calibration_matches(artifact, metric_id="STR-22", scope={"population": "trained_adults"})
    assert not calibration_matches(artifact, metric_id="STR-22", scope={**required, "exercise": "squat"})
    assert calibration_matches(artifact, metric_id="STR-22", scope={**required, "audit_id": "extra"})


def test_f08_str22_rejects_same_equivalence_unit_mismatch_as_str21():
    context = {"practical_equivalence": {"unit": "kg", "lower_magnitude": 1, "upper_magnitude": 2, "declared_before": START}}
    for metric in ("STR-21", "STR-22"):
        with pytest.raises(ValueError, match="practical_equivalence_unit_mismatch"):
            run(metric, [row(i) for i in range(1, 4)], context)


def test_f02_one_metric_failure_does_not_abort_independent_analysis(monkeypatch):
    import healthzip.science.engine as engine
    original = engine.state_metric
    def failing(metric_id, *args, **kwargs):
        if metric_id == "STATE-SLEEP-COVERAGE":
            raise ValueError("synthetic_contract_failure")
        return original(metric_id, *args, **kwargs)
    monkeypatch.setattr(engine, "state_metric", failing)
    metrics = evaluate_all([], cutoff_time=CUTOFF, window_start=START, window_end=END)
    assert metrics["STATE-SLEEP-COVERAGE"]["data_status"] == "not_applicable"
    assert "metric_execution_failed" in metrics["STATE-SLEEP-COVERAGE"]["reason_codes"]
    assert metrics["STR-01"]["metric_id"] == "STR-01"


def test_f01_legacy_unverified_normalized_number_is_reprocessed_only_from_known_raw_unit():
    base = {"id": "legacy", "canonical_type": "hrv_sdnn_ms", "event_end": "2026-10-03T08:00:00Z",
            "available_at": "2026-10-03T08:01:00Z", "source_name": "watch", "normalized_value": .05,
            "normalized_unit": "ms", "unit_status": "unit_unverified", "raw_value": ".05", "raw_unit": "s"}
    value = run("STATE-SDNN", [base])
    assert next(iter(value["value"].values()))[0]["value"] == 50
    assert run("STATE-SDNN", [{**base, "raw_unit": "unknown"}])["data_status"] == "insufficient"


def test_f07_exposure_layers_and_training_frequency_include_ordinary_sessions():
    rows = [row(1, load_value=30), row(2, load_value=32.5), row(3, load_value=30),
            row(4, is_reference=False, reference_protocol=None)]
    exposures = run("STR-07", rows)["value"]
    assert sorted(item["sessions"] for item in exposures["outcome_series_exposures"]) == [1, 2]
    frequency = run("STR-08", rows)["value"]
    assert frequency["recorded_training_sessions"] == 4
    assert frequency["comparable_reference_sessions"] == 3
    assert len(frequency["recorded_without_eligible_reference_session_ids"]) == 1
    assert run("STR-08", [rows[0]])["value"]["recorded_frequency_per_week"] is None


def test_f07_intervening_load_does_not_hide_same_load_raw_change():
    rows = [row(1, load_value=30, reps=10), row(2, load_value=30, reps=12), row(3, load_value=32.5, reps=8)]
    comparison = run("STR-12", rows)["value"]
    assert comparison["delta_reps"] == 2
    assert comparison["current_id"] == rows[1]["id"]


def test_f07_equivalent_exact_mass_units_share_series_without_losing_raw_values():
    rows = [row(1, load_value=45.359237, load_unit="kg"), row(2, load_value=100, load_unit="lb"),
            row(3, load_value=45.359237, load_unit="kg")]
    value = run("STR-19", rows)
    assert len(value["series_results"]) == 1
    assert value["value"]["n"] == 3
    assert len(value["source_record_ids"]) == 3


def test_f07_series_receipt_cannot_be_reused_for_another_load_or_cutoff(tmp_path):
    from healthzip.science import ParameterRegistry
    records = [row(index+1, load_value=load, reps=reps) for index, (load, reps) in
               enumerate([(30, 10), (30, 12), (30, 11), (32.5, 8), (32.5, 10), (32.5, 9)])]
    results = run("STR-20", records, {"data_version": "v14"})["series_results"]
    first, second = results
    path = str(tmp_path / "registry.sqlite3")
    registry = ParameterRegistry(path)
    registry.register_family("v14", .05, {"declared_before": START, "metrics": ["STR-20"]})
    allocation = registry.allocate_look("v14", first["data_snapshot_hash"], "STR-20", data_version="v14",
        task_id=first["task_id"], outcome_series_id=first["outcome_series_id"], cutoff_time=CUTOFF)
    context = {"data_version": "v14", "outcome_series_id": first["outcome_series_id"],
               "look_allocation": allocation, "look_registry_path": path}
    assert run("STR-20", records, context)["value"]["level"] == .975
    assert run("STR-20", records, {**context, "outcome_series_id": second["outcome_series_id"]})["value"] is None
    assert run("STR-20", records, context, cutoff_time="2026-11-11T12:01:00Z")["value"] is None
    registry.close()


def test_f08_actual_task_scope_wins_over_contradictory_caller_labels():
    from healthzip.science.registry import task_calibration_scope
    scope = task_calibration_scope(row(exercise_id="squat"), {"scope": {"exercise": "bench", "unit": "lb", "outcome": "kg"}})
    assert scope["exercise"] == "squat" and scope["unit"] == "kg" and scope["outcome"] == "repetitions"


def test_f01_missing_or_unknown_units_never_enter_daily_baselines():
    records = [{"id": str(i), "canonical_type": "resting_heart_rate_bpm", "normalized_value": 50+i,
                "source_name": "synthetic_watch", "protocol_id": "known", "event_end": f"2026-10-0{i+1}T08:00:00Z",
                "available_at": f"2026-10-0{i+1}T08:01:00Z", "normalized_unit": unit}
               for i, unit in enumerate((None, "unrecognized", "count/min"))]
    metric = run("STATE-REFERENCE-MEDIAN", records)
    assert metric["value"]["streams"][0]["baseline_daily_n"] == 0
    assert len([e for e in metric["exclusions"] if e["reason"] == "numeric_value_or_unit_unverified"]) == 2


def test_f01_registry_and_runtime_agree_cumulative_energy_is_kcal():
    from healthzip.science import definitions
    for metric_id in ("ENERGY-BASAL", "ENERGY-ACTIVE", "ENERGY-DEVICE-TOTAL"):
        assert definitions()[metric_id]["unit"] == run(metric_id)["unit"] == "kcal"


def test_metric_matrix_retest_requires_same_task_and_reports_zero_error_limit():
    from healthzip.science.statistics import typical_error
    design = {"independent_repeats": True, "equal_variance": True, "no_systematic_change": True,
              "same_task_protocol_confirmed": True, "task_id": "test", "protocol_id": "repeat-v1", "unit": "repetitions"}
    incompatible = [{"first": 10, "second": 10, "first_record": row(1, load_value=30), "second_record": row(2, load_value=32.5)}] * 3
    assert typical_error(incompatible, design)["value"] is None
    zero = typical_error([{"first": 10, "second": 10}] * 3, design)
    assert zero["value"]["TE"] == 0
    assert "zero_observed_repeat_variability_not_proof_of_zero_measurement_error" in zero["reason_codes"]


def test_metric_matrix_relative_strength_requires_verified_mass_and_numerator_unit():
    context = {"strength_numerator": 80, "strength_numerator_unit": "kg", "complete_load_known": True,
               "strength_numerator_identity": "observed_load", "body_mass_kg": 80}
    assert run("STR-30", context=context)["value"] is None
    mass = {"id": "scale", "canonical_type": "body_mass_kg", "raw_value": "176.36980974790205", "raw_unit": "lb",
            "event_end": "2026-10-04T08:00:00Z", "available_at": "2026-10-04T08:01:00Z", "source_name": "synthetic_scale"}
    good = run("STR-30", context={**context, "body_mass_observation": mass})
    assert good["value"]["ratio"] == pytest.approx(1)
    assert good["value"]["body_mass_record_id"] == "scale"
    assert run("STR-30", context={**context, "body_mass_observation": {**mass, "raw_unit": "unknown"}})["value"] is None


def test_metric_matrix_independent_flags_do_not_establish_energy_identifiability():
    value = run("ENERGY-IDENTIFIABILITY", context={"independent_constraints": {"intake_baseline": True}})
    assert value["value"]["identified"] is False
    assert value["data_status"] == "not_identifiable"


def test_metric_matrix_each_energy_scenario_bound_must_be_ordered():
    with pytest.raises(ValueError, match="energy_scenario_bounds_reversed"):
        run("ENERGY-ABSOLUTE-INTAKE", context={"energy_scenario": {"device_total": 2200,
            "bias_lower": 20, "bias_upper": 10, "storage_lower": 0, "storage_upper": 100, "provenance": "synthetic scenario"}})


def test_metric_matrix_elapsed_and_pause_adjusted_duration_are_distinct():
    session = {"session_id": "duration", "started_at": "2026-10-04T23:30:00Z", "ended_at": "2026-10-05T00:30:00Z",
               "available_at": "2026-10-05T00:31:00Z", "duration_protocol": "elapsed_including_set_rest",
               "pauses": [{"start": "2026-10-04T23:40:00Z", "end": "2026-10-04T23:50:00Z"},
                          {"start": "2026-10-04T23:45:00Z", "end": "2026-10-05T00:00:00Z"}]}
    assert run("LOAD-DURATION", context={"sessions": [session]})["value"][0]["duration_minutes"] == 60
    adjusted = {**session, "duration_protocol": "elapsed_minus_pauses"}
    assert run("LOAD-DURATION", context={"sessions": [adjusted]})["value"][0]["duration_minutes"] == 40
    conflict = {**session, "duration_seconds": 3000}
    assert run("LOAD-DURATION", context={"sessions": [conflict]})["value"][0]["duration_minutes"] is None


def test_metric_matrix_followup_strata_keep_unknown_and_unique_candidate_denominators():
    base = {"event_end": "2026-10-05T12:00:00Z", "available_at": "2026-10-05T12:01:00Z",
            "adoption": "adopted", "execution_state": "executed", "quality_comparable": True,
            "frozen_targets": {"reps": {"min": 8, "max": 8}}, "actual": {"reps": 8}}
    outcomes = [{**base, "recommendation_id": "one", "strategy": "heavier_lower_reps", "task_id": "bench", "rule_versions": ["guide-v1"]},
                {**base, "recommendation_id": "two", "strategy": "repetition_progression", "task_id": "bench", "quality_comparable": None}]
    value = run("STR-28", context={"recommendation_outcomes": [*outcomes, outcomes[0]]})["value"]
    assert value["adoption_denominator"] == 2 and value["success_denominator"] == 1
    assert len(value["strata"]) == 2
    assert sum(item["counts"]["missing_outcomes"] for item in value["strata"]) == 1


@pytest.mark.parametrize("metric", ["STR-25", "STR-26"])
def test_candidate_requires_specific_rule_action_permission(metric):
    context = principle_context()
    context["reviewed_principles"][0]["permitted_actions"] = ["repetition_progression"]
    value = run(metric, [row(load_value=50, reps=12, pain_flag=False)], context)["value"]
    assert not value.get("next_load") and not value.get("task_trial")
    context["reviewed_principles"][0].pop("permitted_actions")
    value = run(metric, [row(load_value=50, reps=12, pain_flag=False)], context)["value"]
    assert not value.get("next_load") and not value.get("task_trial")


@pytest.mark.parametrize("upper", [12, None, 10, 9, 12.5])
def test_repetition_trial_uses_only_explicit_higher_user_upper_target(upper):
    context = principle_context()
    context["reviewed_principles"][0]["permitted_actions"] = ["repetition_progression"]
    context["allowed_trial_actions"] = ["repetition_progression"]
    context["progression_plan"] = {"rep_upper": upper}
    metric = run("STR-26", [row(load_value=50, reps=10, pain_flag=False)], context)
    trial = metric["value"]["task_trial"]
    if upper == 12:
        assert trial["load_value"] == 50 and trial["reps_target"] == 12
        assert trial["load_unit"] == "kg" and trial["expected_success"] is None
        assert trial["numeric_provenance"]["load_value"]["kind"] == "observed"
        assert trial["numeric_provenance"]["reps_target"]["kind"] == "user_target"
    else:
        assert trial is None
        assert metric["data_status"] != "valid"


@pytest.mark.parametrize("pain", [True, None])
def test_repetition_trial_current_symptoms_or_unknown_block_numeric_target(pain):
    context = principle_context()
    context["reviewed_principles"][0]["permitted_actions"] = ["repetition_progression"]
    context["allowed_trial_actions"] = ["repetition_progression"]
    context["progression_plan"] = {"rep_upper": 12}
    context["current_session_observations"] = [row(2, is_reference=False, pain_flag=pain)]
    metric = run("STR-26", [row(load_value=50, reps=10, pain_flag=False)], context)
    assert metric["value"]["task_trial"] is None


@pytest.mark.parametrize("changes", [
    {"rep_upper": None}, {"rep_upper": 0}, {"rep_upper": 12.5}, {"rep_upper": True},
    {"rep_upper": float("inf")}, {"next_target_reps": None}, {"next_target_reps": 0},
    {"next_target_reps": 6.5}, {"next_target_reps": 13},
    {"target_rir_min": None}, {"target_rir_max": None},
    {"target_rir_min": -1}, {"target_rir_max": 11}, {"target_rir_min": 4},
    {"target_rir_min": float("nan")}, {"target_rir_max": True},
    {"available_loads": None}, {"available_loads": "50,52.5"},
    {"available_loads": [50, -1, 52.5]}, {"available_loads": [50, None, 52.5]},
])
def test_double_progression_partial_or_invalid_plan_has_no_numeric_task(changes):
    context = principle_context()
    context["progression_plan"].update(changes)
    metric = run("STR-25", [row(load_value=50, reps=12, pain_flag=False)], context)
    assert metric["data_status"] == "insufficient"
    assert not (metric["value"] or {}).get("next_load")
    assert metric["reason_codes"]


@pytest.mark.parametrize("action", ["heavier_lower_reps", "repetition_progression"])
@pytest.mark.parametrize("rir", [(None, None), (None, 2), (2, None), (-1, 2), (2, 11), (3, 2), (2, 2)])
def test_optional_trial_rir_preserves_unknown_and_blocks_invalid_effort_target(action, rir):
    context = principle_context()
    context["reviewed_principles"][0]["permitted_actions"] = [action]
    context["allowed_trial_actions"] = [action]
    context["progression_plan"].update(target_rir_min=rir[0], target_rir_max=rir[1])
    metric = run("STR-26", [row(load_value=50, reps=10, pain_flag=False)], context)
    trial = (metric["value"] or {}).get("task_trial")
    if rir == (None, None):
        assert trial["load_value"] is not None and trial["reps_target"] > 0
        assert trial["target_rir_range"] is None
        assert trial["effort_target_status"] == "unspecified"
        assert "target_rir_unspecified_not_effort_matched" in metric["reason_codes"]
    elif rir == (2, 2):
        assert trial["target_rir_range"] == {"min": 2, "max": 2}
        assert trial["effort_target_status"] == "user_specified"
    else:
        assert trial is None and metric["data_status"] == "insufficient"


def test_period_coverage_preserves_source_protocol_denominators_without_double_counting_dates():
    records = []
    for day, sources in ((1, ["watch-A"]), (2, ["watch-B"]), (3, ["watch-A", "watch-B"])):
        for source in sources:
            records.append({"id": f"{day}-{source}", "canonical_type": "resting_heart_rate_bpm",
                "raw_value": "55", "raw_unit": "count/min", "source_name": source, "protocol_id": "resting-v1",
                "event_end": f"2026-11-{day:02}T08:00:00Z", "available_at": f"2026-11-{day:02}T08:01:00Z"})
    metric = run("REPORT-PERIOD-COVERAGE", records, window_start="2026-11-01T00:00:00Z", window_end="2026-11-04T00:00:00Z")
    total = metric["value"]["daily_coverage"]
    assert total[0]["numerator"] == total[0]["denominator"] == 3
    streams = metric["value"]["daily_stream_coverage"]
    assert len(streams) == 2
    assert {s["numerator"] for s in streams} == {2}
    assert {s["denominator"] for s in streams} == {3}
    assert len({s["source_id"] for s in streams}) == 2
    assert all(s["protocol_id"] and len(s["recorded_local_dates"]) == 2 for s in streams)
    assert metric["value"]["missing_date_interpretation"] == "no_valid_record_not_absence_of_event"


@pytest.mark.parametrize("first_load,second_load,expected_n", [(30, 30, 1), (45.359237, 100, 2)])
def test_within_session_repetition_change_uses_actual_mass_not_equal_unit_labels(first_load, second_load, expected_n):
    metric = run("STR-15", [row(1, session_id="one", set_position=1, load_value=first_load, load_unit="kg", reps=10),
                           row(2, session_id="one", set_position=2, load_value=second_load, load_unit="lb", reps=8)])
    assert len(metric["value"]) == expected_n
    if expected_n == 1:
        assert metric["value"][0]["delta_reps"] == 0
        assert metric["comparison_exclusions"] == [{"set_id": "set-2", "reason": "within_session_load_changed_or_unknown"}]
    else:
        assert metric["value"][1]["delta_reps"] == -2
        assert metric["comparison_exclusions"] == []


def frozen_mapping(version="1", direct=None, indirect=None, **changes):
    return {"mapping_id": "synthetic-bench-map", "version": version, "review_status": "approved",
            "exercise_id": "bench", "definition_version": 1,
            "direct": ["chest"] if direct is None else direct,
            "indirect": ["triceps"] if indirect is None else indirect,
            "reviewer": "SYNTHETIC reviewer for software checks", "reviewed_at": START, "frozen_at": START,
            "evidence_refs": ["synthetic-mapping-span"], **changes}


def test_muscle_counts_consume_frozen_mapping_versions_and_ignore_live_context():
    old = row(1, reviewed_anatomy_snapshot=frozen_mapping())
    current = row(2, reviewed_anatomy_snapshot=frozen_mapping("2", direct=["triceps"], indirect=[]))
    context = {"muscle_mappings": {"bench": frozen_mapping("99", direct=["unsupported-live-change"])}}
    result = run("STR-05", [old, current], context)
    groups = result["value"]["groups"]
    assert {(g["muscle"], g["mapping_version"], g["sets"]) for g in groups} == {("chest", "1", 1), ("triceps", "2", 1)}
    assert all(g["mapping_id"] == "synthetic-bench-map" and g["evidence_refs"] for g in groups)
    assert len(result["value"]["mapping_bindings"]) == 2
    assert run("STR-06", [old, current], context)["value"]["groups"][0]["sets"] == 1
    missing = run("STR-05", [row()], context)
    assert missing["value"] is None
    assert "frozen_muscle_mapping_required" in missing["reason_codes"]


@pytest.mark.parametrize("changes", [
    {"review_status": "pending"}, {"exercise_id": "squat"}, {"definition_version": 99},
    {"evidence_refs": []}, {"evidence_refs": [1]}, {"reviewer": None}, {"direct": "chest"},
    {"reviewed_at": "2026-08-01"}, {"reviewed_at": "2026-08-02T00:00:00Z"},
    {"frozen_at": "2027-01-01T00:00:00Z"},
])
def test_invalid_or_late_mapping_snapshot_stays_unknown(changes):
    metric = run("STR-05", [row(reviewed_anatomy_snapshot=frozen_mapping(**changes))])
    assert metric["value"] is None and metric["valid_n"] == 0


def test_same_mapping_version_cannot_have_contradictory_frozen_content():
    metric = run("STR-05", [row(1, reviewed_anatomy_snapshot=frozen_mapping()),
                           row(2, reviewed_anatomy_snapshot=frozen_mapping(direct=["triceps"]))])
    assert metric["value"] is None
    assert "frozen_mapping_version_content_conflict" in metric["reason_codes"]
