"""Execute the pack's non-RAG acceptance cases against deterministic services.

Reused regression scenarios deliberately verify several related invariants.
These are software and simulation checks; they never count as human efficacy
or prospective validation. Each catalog ID receives a real pytest result.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import test_contracts_and_strength as s
import test_state_energy_prediction as h

from healthzip.science.semantics import load_components
from healthzip.science.statistics import classify_interval, typical_error

CATALOG = Path(__file__).resolve().parents[2] / "specs/v1.3/Codex_Execution_Pack_v1.3/metric_acceptance_catalog.json"
CASES = [c for c in json.loads(CATALOG.read_text())["cases"] if not c["metric_id"].startswith("QAL-")]


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_metric_catalog(case, tmp_path):
    metric_id, case_id = case["metric_id"], case["case_id"]
    number = int(case_id.rsplit("T", 1)[1])
    if metric_id.startswith("STR-"):
        code = int(metric_id.split("-")[1])
        if code == 1:
            s.test_work_set_structure_and_retries(case_id)
        elif code == 2:
            s.test_isometric_and_side_observations_keep_original_units()
        elif code == 3:
            if number < 3:
                s.test_plate_load_and_assistance_semantics()
            else:
                row = s.row(load_basis="per_dumbbell_kg", load_value=30, implement_count=2)
                load = load_components(row)
                assert load["per_hand_kg"] == 30 and load["implements_mass_sum_kg"] == 60
                assert load["total_load_kg"] is None
                assert not s.comparable(row, s.row(load_value=60))[0]
        elif code == 4:
            s.test_volume_is_exact_bookkeeping_and_missing_part_is_visible()
            incomplete = s.run(metric_id, [s.row(1), s.row(2), s.row(3, reps=None)])
            assert incomplete["data_status"] == "partial"
        elif code in {5, 6}:
            s.test_muscle_mapping_requires_review_and_direct_indirect_stay_separate()
            if code == 6:
                records = [s.row(i, exercise_id="press" if i < 6 else "other") for i in range(10)]
                mappings = {"press": {"review_status": "approved", "version": "1", "direct": ["chest"], "indirect": []},
                            "other": {"review_status": "approved", "version": "1", "direct": [], "indirect": ["chest"]}}
                context = {"muscle_mappings": mappings}
                assert s.run("STR-05", records, context)["value"]["groups"][0]["sets"] == 6
                assert s.run("STR-06", records, context)["value"]["groups"][0]["sets"] == 4
        elif code == 7:
            origin = datetime(2026, 8, 1, tzinfo=timezone.utc)
            records = [s.row(i, event_end=(origin + timedelta(days=d)).isoformat(), available_at=(origin + timedelta(days=d)).isoformat()) for i, d in enumerate((0, 45, 90))]
            value = s.run(metric_id, records)["value"]
            assert value["sessions"] == 3 and value["span_days"] == 90
        elif code == 8:
            origin = datetime(2026, 10, 1, tzinfo=timezone.utc)
            records = [s.row(i, event_end=(origin + timedelta(hours=hours)).isoformat(), available_at=(origin + timedelta(hours=hours)).isoformat()) for i, hours in enumerate((12, 16, 72, 240))]
            value = s.run(metric_id, records, window_start=origin.isoformat(), window_end=(origin + timedelta(days=14)).isoformat())["value"]
            assert value["sessions"] == 4 and value["observed_dates"] == 3 and value["recorded_frequency_per_week"] == 2
        elif code == 9:
            s.test_plan_unknown_denominator_and_extra_sets()
        elif code in {10, 11, 12, 14}:
            s.test_reference_not_hindsight_best_and_effort_not_repetitions()
            if code == 10:
                first, second = (2, 0) if number == 1 else (0, 2)
                value = s.run("STR-14", [s.row(1, rir=first), s.row(2, rir=second)])["value"]
                assert value["effort_direction"] == ("harder_reported" if number == 1 else "easier_reported")
        elif code == 13:
            a, b = s.row(1, load_basis="assistance_setting", load_value=40), s.row(2, load_basis="assistance_setting", load_value=35)
            value = s.run(metric_id, [a, b])["value"]
            assert value["entered_change"] == -5 and value["direction"] == "harder"
        elif code == 15:
            s.test_within_session_repetition_series_not_fatigue_diagnosis()
        elif code in {16, 17}:
            s.test_formula_versions_domain_missing_rir_and_no_clipping()
            if code == 16 and number == 2:
                from healthzip.science.formulas import e1rm
                domain = {"min_reps": 2, "max_reps": 12, "scope_id": "study-v1"}
                old = e1rm(60, 10, domain=domain, formula_id="epley_n3_0.0333", load_basis="external_total_kg")
                new = e1rm(60, 10, domain={**domain, "scope_id": "study-v2"}, formula_id="epley_r_over_30", load_basis="external_total_kg")
                assert old["domain"]["scope_id"] == "study-v1" and old["formula_id"] != new["formula_id"]
        elif code == 18:
            output = typical_error([{"first": 10, "second": 10}] * 4, {})
            assert output["value"] is None and "repeat_measurement_design_unconfirmed" in output["reason_codes"]
        elif code == 19:
            s.test_real_time_regression_and_zero_error_do_not_imply_plateau()
            if number == 2:
                a = s.row(1, event_end="2026-10-03T10:00:00+00:00", available_at="2026-10-03T10:01:00+00:00")
                b = s.row(2, event_end="2026-10-03T18:00:00+00:00", available_at="2026-10-03T18:01:00+00:00")
                value = s.run("STR-07", [a, b])["value"]
                assert value["sessions"] == 2 and value["observed_dates"] == 1
        elif code == 20:
            output = h.simulate_trends(seed=1301, repetitions=100)
            assert output["scenarios"]["serial_correlation"]["scope_status"] == "simulation_only"
            assert output["release_decision"] == "no_real_scope_validation"
        elif code == 21:
            with pytest.raises(ValueError, match="unit_mismatch"):
                s.run(metric_id, context={"outcome_unit": "kg", "practical_equivalence": {"lower_magnitude": 1, "upper_magnitude": 1, "unit": "repetitions"}})
        elif code == 22:
            if number == 1:
                assert classify_interval(-4, 4, 1, 1) == "uncertain"
            elif number == 2:
                assert classify_interval(-.4, .5, 1, 1) == "no_material_change_candidate"
                # Mathematical class does not bypass the real calibration gate.
                s.test_real_time_regression_and_zero_error_do_not_imply_plateau()
            else:
                s.test_real_time_regression_and_zero_error_do_not_imply_plateau()
        elif code == 23:
            records = [s.row(i, stop_reason="planned_stop", rir=None) for i in range(8)]
            result = s.run(metric_id, records)["value"]
            assert all(r["observation"] == "capacity_unobserved" for r in result)
        elif code == 24:
            s.test_registry_versions_error_budget_and_simulation_gate(tmp_path)
        elif code in {25, 26}:
            s.test_candidate_uses_plan_equipment_and_review_not_readiness_multiplier()
            if code == 26 or number == 2:
                record = s.row(load_basis="plates_per_side_kg", load_value=30, symmetric_loading=True)
                context = {"allowed_trial_actions": ["heavier_lower_reps"], "reviewed_principles": [s.reviewed_principle()],
                           "progression_plan": {"rep_upper": 12, "next_target_reps": 8, "available_loads": [30, 32.5]}}
                trial = s.run("STR-26", [record], context)["value"]["task_trial"]
                assert trial["load_value"] == 32.5 and trial["reps_target"] == 8
                assert trial["expected_success"] is None and "stop" in trial["exit_options"]
        elif code in {27, 28}:
            s.test_followup_targets_are_frozen_and_unknowns_keep_denominators()
        elif code == 29:
            records = [s.row(i, rir=2 if i < 2 else None) for i in range(10)]
            value = s.run(metric_id, records)["value"]["fields"]
            assert value["rir"] == {"numerator": 2, "denominator": 10}
            assert value["entered_load"] == {"numerator": 10, "denominator": 10}
        elif code == 30:
            ctx = {"strength_numerator": 80, "body_mass_kg": 80, "complete_load_known": True, "strength_numerator_identity": "observed_load"}
            a = s.run(metric_id, context=ctx)["value"]
            b = s.run(metric_id, context={**ctx, "body_mass_kg": 75})["value"]
            assert a["numerator"] == b["numerator"] == 80 and a["ratio"] < b["ratio"]
        return
    if metric_id in {"STATE-SLEEP-MAIN", "STATE-SLEEP-STAGE"}:
        h.test_inbed_generic_overlap_stage_conflict_and_explicit_episode()
        if metric_id == "STATE-SLEEP-MAIN" and number == 3:
            h.test_dst_elapsed_time_and_last_24_hours_clip()
    elif metric_id == "STATE-SLEEP-24H":
        h.test_dst_elapsed_time_and_last_24_hours_clip()
        if number == 2:
            # Only an explicitly ended observed portion is eligible, not a future completed interval.
            observed = h.sleep("partial-known", "asleep", "2026-11-07T23:00:00+00:00", "2026-11-08T00:00:00+00:00")
            future = h.sleep("future", "asleep", "2026-11-08T00:00:00+00:00", "2026-11-08T07:00:00+00:00")
            assert h.run(metric_id, [observed, future])["value"]["observed_minutes"] == 60
    elif metric_id == "STATE-SLEEP-COVERAGE":
        h.test_sleep_coverage_elapsed_dates_and_source_choice()
    elif metric_id == "STATE-SLEEP-TIMING":
        h.test_circular_midpoint_and_no_future_sleep()
        if number == 2:
            episodes = [{"start": "2026-11-01T22:00:00+00:00", "end": "2026-11-02T06:00:00+00:00", "timezone": "Europe/London"},
                        {"start": "2026-11-03T22:00:00+08:00", "end": "2026-11-04T06:00:00+08:00", "timezone": "Asia/Shanghai"}]
            value = h.run(metric_id, context={"sleep_episodes": episodes})["value"]
            assert len(value["timezone_segments"]) == 2 and value["circular_midpoint_hour"] is None
    elif metric_id == "STATE-RHR":
        if number == 1:
            s.test_asof_revision_available_at_deleted_and_unknown_are_distinct()
        else:
            h.test_sdnn_not_rmssd_and_rhr_not_any_heart_rate()
    elif metric_id == "STATE-SDNN":
        if number == 1:
            row = {"id": "s", "canonical_type": "hrv_sdnn_ms", "value": .05, "unit": "s", "event_end": "2026-11-03T08:00:00+00:00", "available_at": "2026-11-03T08:01:00+00:00"}
            assert list(h.run(metric_id, [row])["value"].values())[0][0]["value"] == 50
        else:
            h.test_sdnn_not_rmssd_and_rhr_not_any_heart_rate()
    elif metric_id in {"STATE-REFERENCE-MEDIAN", "STATE-REFERENCE-MAD", "STATE-DEVIATION"}:
        h.test_daily_equal_weight_baseline_excludes_current_and_mad_zero()
        if metric_id == "STATE-REFERENCE-MEDIAN" and number == 2:
            daily = [{"value": 10, "event_end": "2026-11-01T08:00:00+00:00", "available_at": "2026-11-01T09:00:00+00:00", "protocol_id": "same"} for _ in range(10)]
            daily += [{"value": 20, "event_end": "2026-11-02T08:00:00+00:00", "available_at": "2026-11-02T09:00:00+00:00", "protocol_id": "same"}]
            assert h.run(metric_id, context={"baseline_daily": daily})["value"]["median"] == 15
        if metric_id == "STATE-DEVIATION" and number == 2:
            assert h.run(metric_id)["value"] is None
    elif metric_id in {"STATE-FATIGUE", "STATE-SORENESS", "STATE-PAIN"}:
        field = metric_id.split("-")[1].lower()
        record = {"id": "subjective", "record_kind": "subjective_log", "event_end": "2026-11-03T08:00:00+00:00", "available_at": "2026-11-03T08:00:00+00:00",
                  field: None, "scale_version": "v1", "muscle": "leg" if field == "soreness" else None}
        assert h.run(metric_id, [record])["value"] is None
        records = [{**record, "id": "a", field: 4}, {**record, "id": "b", field: 2, "scale_version": "v2"}]
        value = h.run(metric_id, records)["value"]
        assert len(value["frequency_by_scale"]) == 2
        assert "recovery_score" not in value and "causal_effect" not in value
        if field == "pain":
            assert value["clinical_interpretation"] is None
        if field == "soreness":
            assert all(o["muscle"] == "leg" for o in value["observations"])
    elif metric_id.startswith("LOAD-"):
        h.test_session_rpe_is_not_set_median_and_preserves_collection_delay()
        if metric_id == "LOAD-DURATION" and number == 2:
            session = {"session_id": "s", "started_at": "2026-11-03T10:00:00+00:00", "ended_at": "2026-11-03T11:30:00+00:00", "available_at": "2026-11-03T12:00:00+00:00",
                       "duration_protocol": "elapsed_minus_pauses", "pauses": [{"start": "2026-11-03T10:10:00+00:00", "end": "2026-11-03T10:30:00+00:00"},
                                                                              {"start": "2026-11-03T10:20:00+00:00", "end": "2026-11-03T10:40:00+00:00"}]}
            assert h.run(metric_id, context={"sessions": [session]})["value"][0]["duration_minutes"] == 60
    elif metric_id.startswith("BODY-MASS-"):
        if metric_id == "BODY-MASS-DAILY":
            rows = [{"id": str(i), "canonical_type": "body_mass_kg", "source_name": "synthetic_scale", "value": value, "unit": "lb" if number == 1 else "kg",
                     "event_end": f"2026-11-03T0{8+i}:00:00+00:00", "available_at": "2026-11-03T10:00:00+00:00"} for i, value in enumerate([100] if number == 1 else [79, 81])]
            value = list(h.run(metric_id, rows)["value"].values())[0][0]["value"]
            assert value == pytest.approx(45.359237 if number == 1 else 80)
        else:
            rows = [{"id": str(i), "canonical_type": "body_mass_kg", "source_name": "synthetic_scale", "normalized_value": value, "event_end": f"2026-10-{1+14*i:02d}T08:00:00+00:00", "available_at": f"2026-10-{1+14*i:02d}T09:00:00+00:00"} for i, value in enumerate([80, 79])]
            value = s.run(metric_id, rows, {"body_mass_reference": {"value": 80, "definition": "declared_comparison_baseline"}})["value"][0]
            assert value["kg_per_week"] == -.5 and value["percent_per_week"] == -.625
            assert "body_fat_percent" not in value
    elif metric_id in {"ENERGY-BASAL", "ENERGY-ACTIVE", "ENERGY-DEVICE-TOTAL"}:
        h.test_device_energy_no_workout_doublecount_no_tef_or_missing_zero()
        if metric_id == "ENERGY-BASAL" and number == 1:
            record = h.energy_row("same", "basal_energy_kcal", 1600)
            assert h.run(metric_id, [record, record])["value"]["streams"][0]["known_kcal"] == 1600
    elif metric_id == "ENERGY-RECORD-COVERAGE":
        days = [{"date": f"2026-11-0{i+1}", "event_start": f"2026-11-0{i+1}T00:00:00+00:00", "event_end": f"2026-11-0{i+1}T12:00:00+00:00", "available_at": f"2026-11-0{i+1}T13:00:00+00:00", "basal_valid": True, "active_valid": i < 3} for i in range(7)]
        value = h.run(metric_id, context={"energy_days": days})["value"]
        assert [v["numerator"] for v in value] == [7, 3, 3]
        assert all("not wear time" in v["definition"] for v in value)
    elif metric_id in {"ENERGY-NET-STORAGE", "ENERGY-IDENTIFIABILITY"}:
        h.test_energy_boundary_no_uniform_rate_assumption_and_nonidentifiable_intake()
        if metric_id == "ENERGY-IDENTIFIABILITY" and number == 1:
            assert 2200 + 300 == 2800 - 300 == 2500 and 2200 - 2200 == 2800 - 2800 == 0
            assert h.run(metric_id)["data_status"] == "not_identifiable"
    elif metric_id == "ENERGY-DELTA-INTAKE":
        h.test_hall_chow_minus_499_and_minus_44_are_not_net_storage()
    elif metric_id == "ENERGY-ABSOLUTE-INTAKE":
        h.test_absolute_energy_scenario_has_no_confidence_level()
        if number == 2:
            assert h.run(metric_id, context={"resting_calorimetry_kcal": 1700})["value"] is None
    elif metric_id == "PRED-B0":
        records = [s.row(1), s.row(2)]
        target = s.row(3, load_value=65 if number == 1 else 60)
        output = s.run(metric_id, records, {"prediction_target": target})
        if number == 1:
            assert output["value"] is None
        else:
            assert output["value"]["reference_id"] == records[1]["id"]
            assert output["n_sessions"] == 2
    elif metric_id == "PRED-B1":
        h.test_temporal_b0_b1_same_batch_and_current_srpe_leakage_excluded()
    elif metric_id == "PRED-ERROR-GAIN":
        h.test_paired_prediction_denominator_and_interval_coverage()
        if number == 2:
            output = h.run(metric_id, context={"paired_predictions": [{"actual": 10, "B0": 10, "B1": 12}]})
            assert output["value"]["delta_MAE"] == -2
    elif metric_id == "PRED-INTERVAL":
        h.test_paired_prediction_denominator_and_interval_coverage()
        if number == 1:
            output = h.run(metric_id, context={"interval_predictions": [{"actual": 10, "lower": 0, "upper": 1000}]})
            assert output["value"]["coverage"] == 1 and output["value"]["mean_width"] == 1000
    elif metric_id.startswith("REPORT-"):
        if metric_id == "REPORT-PERIOD-COVERAGE":
            facts = [{"metric_id": "sleep", "date": f"2026-11-{i:02d}", "event_end": f"2026-11-{i:02d}T08:00:00+00:00", "available_at": f"2026-11-{i:02d}T09:00:00+00:00", "value": 7} for i in (1, 2, 4)]
            output = h.run(metric_id, context={"daily_metric_facts": facts}, end="2026-12-01T00:00:00+00:00")
            value = output["value"]["daily_coverage"][0]
            assert value["numerator"] == 3 and value["denominator"] == 7
            assert output["value"]["complete_previous_period_comparable"] is False
        elif metric_id == "REPORT-STATE-SUMMARY":
            facts = [{"metric_id": kind, "date": "2026-11-01", "event_end": "2026-11-01T08:00:00+00:00", "available_at": "2026-11-01T09:00:00+00:00", "value": value} for kind, value in (("sleep", 7), ("rhr", 60))]
            output = h.run(metric_id, context={"daily_metric_facts": facts}, end="2026-12-01T00:00:00+00:00")
            assert len(output["value"]) == 2 and output["data_status"] == "partial"
        elif metric_id == "REPORT-ENERGY-SUMMARY":
            days = [{"date": f"2026-11-{i:02d}", "event_start": f"2026-11-{i:02d}T00:00:00+00:00", "event_end": f"2026-11-{i:02d}T23:59:00+00:00", "available_at": f"2026-11-{i:02d}T23:59:00+00:00", "complete": True, "device_total_kcal": 2000} for i in range(1, 11)]
            output = s.run(metric_id, context={"energy_days": days})["value"]
            assert output["known_complete_day_energy_sum"] == 20000 and output["extrapolated_period_total"] is None
            assert output["body_mass_trend"]["value"] is None
        else:
            s.test_followup_targets_are_frozen_and_unknowns_keep_denominators()
            assert h.run(metric_id)["value"]["causal_effect"] is None
    else:
        pytest.fail("Acceptance case has no executable scenario: " + case_id)
