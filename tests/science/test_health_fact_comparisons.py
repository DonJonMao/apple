"""Independent synthetic acceptance of completed-day comparisons and sleep events."""
from datetime import datetime, timedelta

import pytest

from healthzip.science import evaluate

START = "2026-11-01T00:00:00+00:00"
END = "2026-11-08T00:00:00+00:00"


def sample(day, value, *, canonical="resting_heart_rate_bpm", **extra):
    at = f"{day}T08:00:00+00:00"
    return {"id": f"{day}:{value}", "canonical_type": canonical, "value": value,
            "unit": "ms" if canonical == "hrv_sdnn_ms" else "bpm", "source_name": "Synthetic Watch",
            "device": "synthetic-device", "event_start": at, "event_end": at, "available_at": at, **extra}


def calculate(rows, identity="STATE-RHR", start=START, end=END, **context):
    return evaluate(identity, rows, cutoff_time=end, window_start=start, window_end=end,
                    context={"timezone": "UTC", **context})


def dates(start, count):
    return [(datetime.fromisoformat(start) + timedelta(days=i)).date().isoformat() for i in range(count)]


def test_rhr_seven_complete_days_and_strictly_prior_28_day_reference():
    rows = [sample(day, 59) for day in dates("2026-10-04", 28)]
    rows += [sample(day, 64) for day in dates("2026-11-01", 7)]
    metric = calculate(rows)
    stream = metric["comparison"]["streams"][0]
    assert stream["current"]["value"] == 64
    assert stream["reference"]["value"] == 59
    assert stream["reference_change"]["absolute"] == 5
    assert (stream["current"]["recorded_days"], stream["current"]["window_days"]) == (7, 7)
    assert (stream["reference"]["recorded_days"], stream["reference"]["window_days"]) == (28, 28)
    assert stream["reference"]["window"]["end"] == START
    assert stream["current"]["statistic_kind"] == "median"
    assert "mean" not in stream["current"]
    assert metric["algorithm_version"] == "daily-physiology-2.0.0"


def test_dense_sdnn_day_does_not_outvote_sparse_day_or_primary_flag():
    dense = [sample("2026-11-01", 10, canonical="hrv_sdnn_ms", id=f"dense-{i}") for i in range(19)]
    dense += [sample("2026-11-01", 300, canonical="hrv_sdnn_ms", is_primary=True)]
    rows = dense + [sample("2026-11-02", 50, canonical="hrv_sdnn_ms")]
    metric = calculate(rows, "STATE-SDNN")
    assert [p["value"] for p in next(iter(metric["value"].values()))] == [10, 50]
    stream = metric["comparison"]["streams"][0]
    assert stream["current"]["value"] == 30
    assert [p["n"] for p in stream["current"]["daily_points"]] == [20, 1]
    assert stream["current"]["raw_record_count"] == 21


def test_partial_days_visible_but_not_part_of_completed_day_comparison():
    rows = [sample("2026-11-01", 60), sample("2026-11-02", 80)]
    metric = calculate(rows, end="2026-11-02T12:00:00+00:00")
    assert len(next(iter(metric["value"].values()))) == 2
    summary = metric["comparison"]["streams"][0]["current"]
    assert summary["value"] == 60 and summary["window_days"] == 1
    assert [point["value"] for point in summary["partial_daily_points"]] == [80]
    assert "2026-11-02" not in summary["missing_dates"]


def test_protocol_context_device_and_metric_identity_are_not_pooled():
    rows = [sample("2026-11-01", value, canonical="hrv_sdnn_ms", **details) for value, details in [
        (10, {"sampling_mode": "background"}), (20, {"sampling_mode": "active"}),
        (30, {"sampling_mode": "active", "device": "changed"}),
        (999, {"metric_identity": "RMSSD"}), (888, {"metadata_json": '{"metric_identity":"rmssd"}'}),
    ]]
    metric = calculate(rows, "STATE-SDNN")
    assert sorted(point["value"] for values in metric["value"].values() for point in values) == [10, 20, 30]
    assert len(metric["comparison"]["streams"]) == 3
    assert sum(item["reason"] == "SDNN_identifier_conflicts_with_recorded_metric_identity" for item in metric["exclusions"]) == 2
    assert all(p["observations"][0]["conditions"]["posture"]["value"] is None for values in metric["value"].values() for p in values)


def test_sparse_periods_show_real_coverage_and_weekday_composition():
    rows = [sample(day, 60) for day in dates("2026-10-04", 20)] + [sample("2026-11-01", 63), sample("2026-11-07", 65)]
    stream = calculate(rows)["comparison"]["streams"][0]
    assert stream["current"]["recorded_days"] == 2 and stream["reference"]["recorded_days"] == 20
    assert stream["current"]["value"] == 64
    assert len(stream["current"]["missing_dates"]) == 5
    assert any("星期组成" in message for message in stream["limitations"])


def test_revision_replay_uses_visibility_and_keeps_frozen_identity():
    old = sample("2026-11-01", 60, source_record_id="logical")
    new = {**old, "id": "revision", "value": 70, "available_at": "2026-11-04T00:00:00+00:00"}
    before = calculate([old, new], end="2026-11-03T00:00:00+00:00")
    now = calculate([old, new])
    assert next(iter(before["value"].values()))[0]["value"] == 60
    assert next(iter(now["value"].values()))[0]["value"] == 70
    assert next(iter(before["value"].values()))[0]["value"] == 60
    assert before["comparison"]["streams"][0]["fact_id"] != now["comparison"]["streams"][0]["fact_id"]


def sleep(identity, start, end, stage="asleep", source="Synthetic Watch"):
    return {"id": identity, "canonical_type": "sleep_stage", "stage": stage, "source_name": source,
            "event_start": start, "event_end": end, "available_at": end}


def test_connected_stage_segments_cross_midnight_once_without_parent():
    rows = [sleep("core", "2026-10-31T22:00:00Z", "2026-10-31T23:30:00Z", "core"),
            sleep("deep", "2026-10-31T23:30:00Z", "2026-11-01T02:00:00Z", "deep"),
            sleep("rem", "2026-11-01T02:00:00Z", "2026-11-01T06:00:00Z", "rem")]
    result = calculate(rows, "REPORT-STATE-SUMMARY")
    facts = result["daily_facts"]
    assert len(facts) == 1 and facts[0]["date"] == "2026-11-01" and facts[0]["value"] == 480
    assert facts[0]["episodes"][0]["classification"] == "unclassified"
    assert facts[0]["episodes"][0]["actual_wake_time"] is None
    assert facts[0]["episodes"][0]["stage_coverage"] == 1


def test_parent_child_overlap_awake_conflict_and_sources_stay_auditable():
    rows = [sleep("parent", "2026-11-01T22:00:00Z", "2026-11-02T06:00:00Z"),
            sleep("child", "2026-11-01T23:00:00Z", "2026-11-02T02:00:00Z", "deep"),
            sleep("awake", "2026-11-02T01:00:00Z", "2026-11-02T01:30:00Z", "awake"),
            sleep("other", "2026-11-02T00:00:00Z", "2026-11-02T05:00:00Z", source="Other")]
    facts = calculate(rows, "REPORT-STATE-SUMMARY")["daily_facts"]
    first = next(f for f in facts if "Synthetic" in f["source_id"])
    assert first["value"] == 450
    event = first["episodes"][0]
    assert event["stage_minutes"]["deep"] == 150 and event["stage_coverage"] == pytest.approx(1/3)
    assert event["conflicts"] and event["source_conflicts"]
    assert len(facts) == 2


def test_dst_elapsed_duration_and_absent_stages_are_not_missing_sleep():
    rows = [sleep("dst", "2026-11-01T00:00:00-04:00", "2026-11-01T08:00:00-05:00")]
    result = calculate(rows, "REPORT-STATE-SUMMARY", timezone="America/New_York")
    fact = result["daily_facts"][0]
    assert fact["value"] == 540
    assert fact["episodes"][0]["stage_minutes"] == {}
    assert fact["episodes"][0]["unknown_stage_minutes"] == 540
    assert fact["episodes"][0]["episode_complete"] is False


def test_current_sdnn_zero_reference_does_not_produce_percentage_or_z():
    rows = [sample("2026-10-30", 0, canonical="hrv_sdnn_ms"), sample("2026-11-01", 10, canonical="hrv_sdnn_ms")]
    stream = calculate(rows, "STATE-SDNN")["comparison"]["streams"][0]
    assert stream["reference_change"] == {"absolute": 10, "relative_percent": None}


def test_body_mass_keeps_its_established_period_statistic():
    rows = [sample(f"2026-11-0{i}", value, canonical="body_mass_kg", unit="kg")
            for i, value in enumerate((60, 60, 90), start=1)]
    result = calculate(rows, "REPORT-STATE-SUMMARY")
    weight = next(item for item in result["value"] if item["metric_id"] == "BODY-MASS-DAILY")
    assert weight["mean"] == 70 and weight["statistic_kind"] == "mean"
    assert "median" not in weight
    assert not any(item.get("metric_id") == "BODY-MASS-DAILY" for item in result["comparison"]["streams"])


def test_original_source_offsets_preserved_without_changing_import_fingerprint():
    import json

    from healthzip.importers.apple_xml import _record_data

    attrs = {"type": "HKQuantityTypeIdentifierHeartRateVariabilitySDNN", "value": "32", "unit": "ms",
             "startDate": "2026-11-01 01:50:00 -0400", "endDate": "2026-11-01 01:05:00 -0500",
             "sourceName": "Synthetic Watch"}
    row, error = _record_data(attrs, False)
    assert error is None
    assert row["fingerprint"] == "88ec684da1e2cddb5c4eb693a601dc5ed50ef3898e4a0aedd6f3ac82e07b068b"
    raw = json.loads(row["metadata_json"])["original_timestamps"]
    assert raw["start"] == attrs["startDate"] and raw["end"] == attrs["endDate"]
    row.update(id="time-offset", available_at=END)
    metric = calculate([row], "STATE-SDNN")
    observation = next(iter(metric["value"].values()))[0]["observations"][0]
    assert observation["start_offset_minutes"] == -240
    assert observation["end_offset_minutes"] == -300
    assert observation["original_end"] == attrs["endDate"]


def test_unknown_original_end_offset_is_not_fabricated_from_utc():
    metric = calculate([sample("2026-11-01", 33, canonical="hrv_sdnn_ms")], "STATE-SDNN")
    observation = next(iter(metric["value"].values()))[0]["observations"][0]
    assert observation["original_end"] is None and observation["end_offset_minutes"] is None


def test_dst_complete_calendar_day_is_not_forced_to_24_hours():
    start, end = "2026-11-01T00:00:00-04:00", "2026-11-02T00:00:00-05:00"
    row = sample("2026-11-01", 62, event_end="2026-11-01T08:00:00-05:00", available_at="2026-11-01T09:00:00-05:00")
    summary = calculate([row], start=start, end=end, timezone="America/New_York")["comparison"]["streams"][0]["current"]
    assert summary["window_days"] == summary["recorded_days"] == 1
    assert summary["complete_window"] == {"start": start, "end": end, "timezone": "America/New_York", "closure": "[start,end)"}


def test_partial_overlapping_sleep_sources_never_form_composite_night():
    rows = [sleep("first", "2026-11-01T22:00:00Z", "2026-11-02T03:00:00Z"),
            sleep("second", "2026-11-02T02:00:00Z", "2026-11-02T07:00:00Z", source="Other")]
    facts = calculate(rows, "REPORT-STATE-SUMMARY")["daily_facts"]
    assert sorted(point["value"] for point in facts) == [300, 300]
    assert all(point["episodes"][0]["source_conflicts"] for point in facts)
    assert all(point["episodes"][0]["episode_complete"] is False for point in facts)
    assert not any(point["value"] == 540 for point in facts)


def test_stage_overlap_stays_unassigned_and_does_not_reduce_total_sleep():
    rows = [sleep("total", "2026-11-01T22:00:00Z", "2026-11-02T06:00:00Z"),
            sleep("core", "2026-11-01T22:00:00Z", "2026-11-02T02:00:00Z", "core"),
            sleep("deep", "2026-11-02T01:00:00Z", "2026-11-02T03:00:00Z", "deep")]
    event = calculate(rows, "REPORT-STATE-SUMMARY")["daily_facts"][0]["episodes"][0]
    assert event["value"] == 480
    assert event["stage_minutes"] == {"core": 180, "deep": 60}
    assert event["stage_coverage"] == 0.5
    assert event["unknown_stage_minutes"] == 240
    assert event["conflicts"][0]["kind"] == "stage_overlap"


def test_calendar_report_and_detail_share_previous_period_bounds(tmp_path):
    from healthzip.analytics.v13 import analyze
    from healthzip.analytics.workspaces import analyze_workspace
    from healthzip.db.repository import Repository

    repo = Repository(tmp_path / "synthetic-calendar-consistency.sqlite3")
    try:
        for period in ("week", "month"):
            cutoff = "2026-11-18T12:00:00+00:00"
            report = analyze(repo, cutoff_time=cutoff, timezone_name="UTC", period=period, use_cache=False)
            page = analyze_workspace(repo, "心率", cutoff_time=cutoff, timezone_name="UTC", period=period)
            first = report["metrics"]["STATE-RHR"]["comparison"]["windows"]
            second = page["workspace_scope"]["metrics"]["STATE-RHR"]["comparison"]["windows"]
            assert first["previous"] == second["previous"]
            assert first["reference"] == second["reference"]
    finally:
        repo.close()
