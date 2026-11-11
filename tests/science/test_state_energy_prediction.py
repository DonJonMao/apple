
import pytest

from healthzip.science import evaluate
from healthzip.science.energy import hall_chow
from healthzip.science.prediction import forward_evaluate, paired_errors
from healthzip.science.research import prediction_fixture, simulate_energy, simulate_trends


def run(metric, rows=None, context=None, *, start="2026-11-01T00:00:00+00:00", end="2026-11-08T00:00:00+00:00", cutoff="2026-11-08T00:00:00+00:00"):
    return evaluate(metric, rows or [], cutoff_time=cutoff, window_start=start, window_end=end, context=context or {})


def sleep(identifier, stage, start, end, **extra):
    return {"id": identifier, "record_kind": "health_sample", "canonical_type": "sleep_stage", "stage": stage,
            "event_start": start, "event_end": end, "available_at": end,
            "source_name": "synthetic_watch", "device_id": "watch1", "protocol_id": "sleep-v1", **extra}


def test_inbed_generic_overlap_stage_conflict_and_explicit_episode():
    start, end = "2026-11-02T22:00:00+00:00", "2026-11-03T06:00:00+00:00"
    rows = [sleep("bed", "inBed", start, end), sleep("sleep", "asleep", "2026-11-02T23:00:00+00:00", end),
            sleep("core", "core", "2026-11-02T23:00:00+00:00", "2026-11-03T02:00:00+00:00")]
    value = run("STATE-SLEEP-MAIN", rows, {"main_sleep_episode": {"start": start, "end": end, "complete": True}})
    assert value["value"]["observed_minutes"] == 420
    assert value["data_status"] == "valid"
    stages = run("STATE-SLEEP-STAGE", rows)["value"]
    assert stages["stage_minutes"] == {"core": 180}
    assert stages["annotation_coverage"] is None
    rows.append(sleep("deep", "deep", "2026-11-03T00:00:00+00:00", "2026-11-03T01:00:00+00:00"))
    assert run("STATE-SLEEP-STAGE", rows)["data_status"] == "conflicted"


def test_dst_elapsed_time_and_last_24_hours_clip():
    rows = [sleep("dst", "asleep", "2026-11-01T00:00:00-04:00", "2026-11-01T08:00:00-05:00")]
    result = run("STATE-SLEEP-MAIN", rows, {"timezone": "America/New_York", "main_sleep_episode": {
        "start": rows[0]["event_start"], "end": rows[0]["event_end"], "attribution_date": "2026-11-01"}})
    assert result["value"]["observed_minutes"] == 540
    rows = [sleep("main", "asleep", "2026-11-06T23:00:00+00:00", "2026-11-07T06:00:00+00:00"),
            sleep("nap", "asleep", "2026-11-07T14:00:00+00:00", "2026-11-07T14:30:00+00:00")]
    assert run("STATE-SLEEP-24H", rows)["value"]["observed_minutes"] == 390
    narrow = run("STATE-SLEEP-24H", rows, start="2026-11-07T23:00:00+00:00")
    assert narrow["value"]["observed_minutes"] == 390
    assert narrow["window"]["start"] == "2026-11-07T00:00:00+00:00"
    assert narrow["source_record_ids"] == ["main", "nap"]


def test_sleep_coverage_elapsed_dates_and_source_choice():
    rows = [sleep(str(day), "asleep", f"2026-11-0{day}T00:00:00+00:00", f"2026-11-0{day}T07:00:00+00:00") for day in (1, 3, 5)]
    out = run("STATE-SLEEP-COVERAGE", rows)
    assert out["value"]["fraction"] == 3 / 7
    assert "record_coverage_not_wear_time_or_complete_nights" in out["reason_codes"]
    rows.append({**rows[0], "id": "other", "source_name": "other_watch"})
    assert run("STATE-SLEEP-MAIN", rows, {"main_sleep_episode": {
        "start": rows[0]["event_start"], "end": rows[0]["event_end"]}})["data_status"] == "incompatible"


def test_circular_midpoint_and_no_future_sleep():
    episodes = [{"start": "2026-11-01T22:00:00+00:00", "end": "2026-11-02T00:00:00+00:00"},
                {"start": "2026-11-02T00:00:00+00:00", "end": "2026-11-02T02:00:00+00:00"}]
    output = run("STATE-SLEEP-TIMING", context={"sleep_episodes": episodes})
    hour = output["value"]["circular_midpoint_hour"]
    assert min(abs(hour), abs(hour - 24)) < 1e-9
    future = sleep("future", "asleep", "2026-11-07T23:00:00+00:00", "2026-11-08T07:00:00+00:00")
    assert run("STATE-SLEEP-MAIN", [future])["value"] is None


def test_sdnn_not_rmssd_and_rhr_not_any_heart_rate():
    row = {"id": "heart", "canonical_type": "heart_rate_bpm", "normalized_value": 70,
           "event_end": "2026-11-03T08:00:00+00:00", "available_at": "2026-11-03T08:01:00+00:00"}
    assert run("STATE-RHR", [row])["value"] is None
    row["canonical_type"] = "hrv_rmssd_ms"
    assert run("STATE-SDNN", [row])["value"] is None
    output = run("STATE-SDNN", context={"clean_nn_intervals_ms": [1000, 1020, 980], "artifact_cleaning_protocol": "synthetic-clean-v1"})
    assert output["value"]["SDNN_ms"] == 20


def test_daily_equal_weight_baseline_excludes_current_and_mad_zero():
    baseline = [{"value": value, "event_end": f"2026-11-0{day}T08:00:00+00:00", "available_at": f"2026-11-0{day}T08:01:00+00:00", "protocol_id": "same"}
                for day, value in ((1, 60), (2, 60), (3, 100))]
    current = {"value": 100, "event_end": "2026-11-03T08:00:00+00:00", "available_at": "2026-11-03T08:01:00+00:00", "protocol_id": "same"}
    result = run("STATE-DEVIATION", context={"baseline_daily": baseline, "current_observation": current})
    assert result["value"]["median"] == 60
    assert result["value"]["absolute_deviation"] == 40
    assert result["value"]["robust_z"] is None
    current["protocol_id"] = "new_device_protocol"
    assert run("STATE-DEVIATION", context={"baseline_daily": baseline, "current_observation": current})["data_status"] == "incompatible"


def test_session_rpe_is_not_set_median_and_preserves_collection_delay():
    session = {"session_id": "s1", "started_at": "2026-11-03T10:00:00+00:00", "ended_at": "2026-11-03T11:30:00+00:00",
               "available_at": "2026-11-03T11:45:00+00:00", "session_rpe": 6, "srpe_protocol": "explicit_whole_session_v1",
               "duration_protocol": "elapsed_including_set_rest", "srpe_collected_at": "2026-11-03T11:45:00+00:00"}
    result = run("LOAD-SRPE-AU", context={"sessions": [session]})["value"][0]
    assert result["AU"] == 540 and result["actual_collection_delay_minutes"] == 15
    assert run("LOAD-SRPE-AU", context={"sessions": [session]}, cutoff="2026-11-03T10:00:00+00:00")["value"] is None
    session["session_rpe"] = None
    assert run("LOAD-SRPE-AU", context={"sessions": [session]})["value"][0]["AU"] is None


def energy_row(identifier, kind, value, **extra):
    return {"id": identifier, "canonical_type": kind, "normalized_value": value, "normalized_unit": "kcal",
            "event_start": "2026-11-02T00:00:00+00:00", "event_end": "2026-11-03T00:00:00+00:00",
            "available_at": "2026-11-03T01:00:00+00:00", "source_name": "watch", "device_id": "w1", "protocol_id": "day", **extra}


def test_device_energy_no_workout_doublecount_no_tef_or_missing_zero():
    rows = [energy_row("basal", "basal_energy_kcal", 1600), energy_row("active", "active_energy_kcal", 600),
            energy_row("workout", "workout_energy_kcal", 400)]
    result = run("ENERGY-DEVICE-TOTAL", rows)
    assert result["value"][0]["device_total_kcal"] == 2200
    assert run("ENERGY-DEVICE-TOTAL", rows[:1])["value"] is None
    rows.append(energy_row("overlap", "active_energy_kcal", 200, event_start="2026-11-02T12:00:00+00:00"))
    assert run("ENERGY-ACTIVE", rows)["data_status"] == "conflicted"


def test_energy_boundary_no_uniform_rate_assumption_and_nonidentifiable_intake():
    row = energy_row("cross", "active_energy_kcal", 600, event_start="2026-10-31T23:00:00+00:00")
    output = run("ENERGY-ACTIVE", [row])
    assert output["value"]["unknown_or_boundary_ids"] == ["cross"]
    assert run("ENERGY-IDENTIFIABILITY")["data_status"] == "not_identifiable"
    assert run("ENERGY-NET-STORAGE")["value"] is None
    assert run("ENERGY-ABSOLUTE-INTAKE")["value"] is None


def test_mass_trend_uses_true_days_and_never_creates_calories():
    rows = [{"id": str(i), "canonical_type": "body_mass_kg", "normalized_value": 80 - i, "source_name": "synthetic_scale",
             "event_end": f"2026-11-{1 + 3*i:02d}T08:00:00+00:00", "available_at": f"2026-11-{1 + 3*i:02d}T08:00:00+00:00"} for i in range(3)]
    trend = run("BODY-MASS-TREND", rows)["value"][0]
    assert trend["kg_per_week"] == pytest.approx(-7/3)
    assert trend["span_days"] == 6
    assert run("ENERGY-NET-STORAGE", rows)["value"] is None


def parameters():
    return {"parameter_set_id": "reproduction", "model": "hall_chow_2011_replication", "rho": 9100, "epsilon": 22, "provenance": "E2"}


def test_hall_chow_minus_499_and_minus_44_are_not_net_storage():
    baseline = {"baseline_id": "known-initial-equilibrium", "equilibrium_confirmed": True, "W0": 90}
    result = hall_chow([0, 40], [90, 88], baseline=baseline, parameters=parameters())
    assert result["delta_intake_kcal_day"] == pytest.approx(-499)
    plateau = hall_chow([0, 40], [88, 88], baseline=baseline, parameters=parameters())
    assert plateau["delta_intake_kcal_day"] == pytest.approx(-44)
    assert plateau["evidence_status"] == "research_only"
    assert hall_chow([0, 40], [90, 88], baseline={}, parameters=parameters())["delta_intake_kcal_day"] is None
    wrong = {**parameters(), "model": "personal_calibrated"}
    assert hall_chow([0, 40], [90, 88], baseline=baseline, parameters=wrong)["delta_intake_kcal_day"] is None


def test_energy_covariance_requires_joint_baseline_and_more_error_never_narrows():
    import numpy as np

    baseline = {"baseline_id": "same-data", "equilibrium_confirmed": True, "W0": 90, "same_sample_baseline": True}
    sigma = np.eye(3) * .1
    missing = hall_chow([0, 9, 40], [90, 89.55, 88], baseline=baseline, parameters=parameters(), covariance=sigma, baseline_variance=.1)
    assert missing["variance"] is None
    base = hall_chow([0, 9, 40], [90, 89.55, 88], baseline=baseline, parameters=parameters(), covariance=sigma, baseline_variance=.1, baseline_covariance=sigma[:,0])
    more = hall_chow([0, 9, 40], [90, 89.55, 88], baseline=baseline, parameters=parameters(), covariance=sigma, baseline_variance=.1, baseline_covariance=sigma[:,0], parameter_covariance=[[10000, 0], [0, 4]])
    assert more["variance"] >= base["variance"]


def test_absolute_energy_scenario_has_no_confidence_level():
    scenario = {"device_total": 2500, "bias_lower": -300, "bias_upper": 300, "storage_lower": 0, "storage_upper": 0,
                "provenance": "explicit synthetic scenario, Q not inferred from stable mass"}
    output = run("ENERGY-ABSOLUTE-INTAKE", context={"energy_scenario": scenario})
    assert output["value"]["scenario_lower"] == 2200 and output["value"]["scenario_upper"] == 2800
    assert output["uncertainty"]["kind"] == "scenario_range" and output["uncertainty"]["level"] is None


def test_temporal_b0_b1_same_batch_and_current_srpe_leakage_excluded():
    rows = prediction_fixture(seed=8, users=1, exposures=45)
    for row in rows:
        row["features"]["sleep_hours"]["available_at"] = row["available_at"]  # Deliberate post-outcome leak.
    split = {"registered_at": "2025-12-01T00:00:00+00:00", "train_end": "2026-03-01T00:00:00+00:00",
             "validation_end": "2026-04-01T00:00:00+00:00", "test_end": "2026-06-01T00:00:00+00:00"}
    output = forward_evaluate(rows, split=split, feature="sleep_hours")
    assert output["test_predictions"]
    assert all(p["fallback"] and p["B0"] == p["B1"] for p in output["test_predictions"])
    assert output["release_choice"] == "B0"
    for prediction in output["test_predictions"]:
        assert prediction["session_id"] not in prediction["training_session_ids"]


def test_paired_prediction_denominator_and_interval_coverage():
    pairs = [{"actual": 10, "B0": 8, "B1": 9}, {"actual": 8, "B0": 8, "B1": 9}, {"actual": 7, "B0": 6, "B1": None}]
    result = paired_errors(pairs)
    assert result["n_pairs"] == 2 and result["excluded_n"] == 1
    assert result["delta_MAE"] == 0
    output = run("PRED-INTERVAL", context={"interval_predictions": [{"actual": 10, "lower": 9, "upper": 11, "nominal_level": .95},
                                                                      {"actual": 8, "lower": 9, "upper": 11, "nominal_level": .95}]})
    assert output["value"]["coverage"] == .5 and output["value"]["mean_width"] == 2


def test_reproducible_simulation_reports_conditional_failures():
    trend = simulate_trends(seed=33, repetitions=30)
    assert trend["failure_return_verified"]
    assert all(s["scope_status"] == "simulation_only" for s in trend["scenarios"].values())
    energy = simulate_energy(seed=44, repetitions=1500)
    assert energy["scope_status"] == "simulation_only"
    assert energy["empirical_variance"] == pytest.approx(energy["analytic_variance"], rel=.12)
    assert .91 < energy["empirical_coverage"] < .98


def test_cross_user_holdout_never_fits_held_out_outcomes():
    rows = prediction_fixture(seed=92, users=3, exposures=45, state_effect=2)
    split = {"registered_at": "2025-12-01T00:00:00+00:00", "train_end": "2026-03-01T00:00:00+00:00",
             "validation_end": "2026-04-01T00:00:00+00:00", "test_end": "2026-06-01T00:00:00+00:00", "heldout_users": ["u2"]}
    output = forward_evaluate(rows, split=split, feature="sleep_hours")
    holdout = [p for p in output["test_predictions"] if p["user_id"] == "u2"]
    assert holdout and all(p["training_user_ids"] == ["u0", "u1"] for p in holdout)
    assert all(not any(identity.startswith("u2-") for identity in p["training_session_ids"]) for p in holdout)
    assert any(not p["fallback"] for p in holdout)


def test_report_derives_sleep_subjective_and_complete_energy_from_raw_snapshot():
    rows = [sleep("sleep", "asleep", "2026-11-02T23:00:00+00:00", "2026-11-03T06:00:00+00:00"),
            {"id": "fatigue", "record_kind": "subjective_log", "fatigue": 3, "scale_version": "questionnaire-v1",
             "event_end": "2026-11-03T08:00:00+00:00", "available_at": "2026-11-03T08:01:00+00:00"},
            energy_row("basal", "basal_energy_kcal", 1600), energy_row("active", "active_energy_kcal", 600)]
    report = run("REPORT-STATE-SUMMARY", rows)
    state = report["value"]
    assert {value["metric_id"] for value in state} == {"sleep_observed_minutes_by_wake_date", "STATE-FATIGUE"}
    sleep_value = next(value for value in state if value["series_id"] == "observed_sleep_by_wake_date")
    assert sleep_value["median"] == 420
    fact = next(fact for fact in report["daily_facts"] if fact.get("series_id") == "observed_sleep_by_wake_date")
    assert fact["value"] == 420 and fact["unit"] == "min" and fact["source_record_ids"] == ["sleep"]
    assert fact["date"] == "2026-11-03" and fact["episode_complete"] is False
    energy = run("REPORT-ENERGY-SUMMARY", rows)["value"]
    assert energy["known_complete_day_energy_sum"] == 2200 and energy["valid_complete_days"] == 1
    assert energy["extrapolated_period_total"] is None


def test_report_context_is_not_future_or_unknown_availability_backdoor():
    facts = [{"metric_id": "STATE-RHR", "date": "2026-11-03", "value": 60,
              "event_end": "2026-11-03T08:00:00+00:00", "available_at": "2026-11-09T08:00:00+00:00"}]
    result = run("REPORT-STATE-SUMMARY", context={"daily_metric_facts": facts})
    assert result["value"] is None
    assert result["daily_facts"] == []
    assert any(e["reason"] == "available_after_cutoff" for e in result["exclusions"])
    facts[0].pop("available_at")
    assert run("REPORT-STATE-SUMMARY", context={"daily_metric_facts": facts})["value"] is None


def test_report_baseline_is_separate_from_display_window_and_excludes_current_day():
    rows = [{"id": str(day), "canonical_type": "resting_heart_rate_bpm", "normalized_value": value,
             "source_name": "synthetic_watch", "protocol_id": "rhr-v1", "event_end": f"2026-11-0{day}T08:00:00+00:00", "available_at": f"2026-11-0{day}T09:00:00+00:00"}
            for day, value in ((1, 50), (2, 52), (3, 100))]
    output = run("STATE-DEVIATION", rows, {"baseline_window": {"start": "2026-11-01T00:00:00+00:00", "end": "2026-11-04T00:00:00+00:00"}},
                 start="2026-11-03T00:00:00+00:00")
    value = output["value"]["streams"][0]
    assert value["baseline_median"] == 51 and value["current_daily_value"] == 100
    assert value["baseline_daily_n"] == 2 and output["window"]["start"] != value["reference_window"]["start"]


def test_reported_session_duration_and_conflicts_preserve_state():
    session = {"session_id": "s1", "started_at": "2026-11-03T10:00:00+00:00", "ended_at": "2026-11-03T10:01:00+00:00",
               "available_at": "2026-11-03T11:45:00+00:00", "session_rpe": 6, "srpe_protocol": "declared_0_10_whole_session",
               "duration_seconds": 5400, "duration_protocol": "user_elapsed_including_rest"}
    assert run("LOAD-SRPE-AU", context={"sessions": [session]})["value"][0]["AU"] == 540
    row = {"id": "rhr-conflict", "canonical_type": "resting_heart_rate_bpm", "normalized_value": 80, "conflicted": True,
           "event_end": "2026-11-03T08:00:00+00:00", "available_at": "2026-11-03T08:00:00+00:00"}
    assert run("STATE-RHR", [row])["data_status"] == "conflicted"
    assert run("ENERGY-BASAL", [row])["data_status"] == "insufficient"
