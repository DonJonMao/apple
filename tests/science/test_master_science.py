"""Independent expected values and production ZIP/as-of/MetricResult paths."""

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

import pytest

from healthzip.analytics.body_metrics import (
    METRIC_CATALOG,
    analyze_body_metric,
    analyze_questions,
    change_layers,
)
from healthzip.analytics.body_questions import sleep_training_pairs
from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.normalize import TYPE_MAP, normalize_value
from healthzip.science.calendar_trend import fit_daily
from healthzip.science.contracts import Window, instant, validate_result
from healthzip.science.sleep_regularity import sleep_regularity
from tests.master_science_fixture import CUTOFF, RANGE_START, create_master_science_fixture

KW = dict(window_start=RANGE_START, window_end=CUTOFF, cutoff_time=CUTOFF)


@pytest.fixture(scope="module")
def observed(tmp_path_factory):
    db = tmp_path_factory.mktemp("body-science") / "synthetic.sqlite3"
    receipt = create_master_science_fixture(db)
    assert receipt["records_seen"] == receipt["records_inserted"] and receipt["import_errors"] == 0
    repo = Repository(db)
    yield repo
    repo.close()


@pytest.mark.parametrize("key", list(METRIC_CATALOG))
def test_supported_fields_from_streaming_zip_reach_local_details(observed, key):
    m = analyze_body_metric(observed, key, **KW)
    validate_result(m)
    assert m["valid_n"] > 0
    assert set(m["capabilities"]) == {
        "generated_by_device",
        "exported",
        "parse",
        "calculate",
        "interpret",
        "display",
    }
    assert m["scope"]["field"] == key
    assert any(
        any(p["source_record_ids"] and p["observed_at"] and p["sample_count"] for p in s["points"])
        for s in m["value"]["streams"]
    )


def test_acoustic_energy_standing_units_and_low_frequency_support(observed):
    def read(k):
        return analyze_body_metric(observed, k, **KW)["value"]["streams"][0]

    assert read("environmental_audio_dba")["points"][0]["value"] == pytest.approx(
        10 * math.log10((10**7 + 10**8) / 2)
    )
    assert read("headphone_audio_dba")["points"][0]["value"] == 73
    assert read("stand_hour")["current"]["recorded_total"] == 1
    assert read("stand_minutes")["current"]["recorded_total"] == 7
    assert read("physical_effort_met")["current"]["value"] == 3.2
    six = read("six_minute_walk_m")["points"]
    assert len(six) == 2 and six[1]["estimate_support"]["overlaps_prior_window"]
    assert six[1]["estimate_support"]["upper_limit_m"] == 500
    assert six[1]["estimate_support"]["at_reportable_limit"] is True
    assert read("heart_rate_recovery_1m")["current"]["unit"] == "count"
    assert (
        normalize_value("HKQuantityTypeIdentifierHeartRateRecoveryOneMinute", 19, "count/min")[0]
        is None
    )


def test_body_temperature_and_oxygen_are_sparse_observations(observed):
    for k, value in (
        ("oxygen_saturation_fraction", 0.97),
        ("sleeping_wrist_temperature_c", 35.6),
        ("sleep_breathing_disturbances", 3),
    ):
        s = analyze_body_metric(observed, k, **KW)["value"]["streams"][0]
        assert len(s["points"]) == 1 and s["current"]["value"] == value
        if k != "sleep_breathing_disturbances":
            assert s["points"][0]["observations"][0]["sleep_episode_ids"]


def test_real_formal_estimators_and_local_fallback(observed):
    m = analyze_body_metric(observed, "resting_heart_rate_bpm", with_model=True, **KW)["value"][
        "streams"
    ]
    trend = next(s["trend"] for s in m if s["source"] == "合成长时段手表")
    assert trend["status"] == "estimated" and trend["slope_per_day"] == pytest.approx(
        -0.023, abs=0.008
    )
    assert trend["diagnostics"]["max_gap_days"] == 2
    assert trend["diagnostics"]["example_gap_transitions"]["2"] == pytest.approx(trend["rho"] ** 2)
    assert len(trend["fitted_points"]) == 2 and trend["interval"][0] < -0.023 < trend["interval"][1]
    questions = analyze_questions(observed, **KW)
    assert {q["id"] for q in questions} == {"W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8", "E"}
    assert all(q["steps"] and q["fact_id"] and q["analysis_version"] for q in questions)
    by_id = {q["id"]: q for q in questions}
    activity = {r["metric"]: r for r in by_id["W7"]["rows"] if r.get("metric") in {"steps", "walking_speed_m_s"}}
    assert activity["steps"]["value"] == 2000 and activity["walking_speed_m_s"]["value"] == 1.2
    assert "中位数" in by_id["W7"]["observation"]
    assert all(row["category"] or (row["unit"] == "count" and row["value"] >= 0)
               for row in by_id["E"]["rows"] if row["type"] == "event")
    assert "疲劳 7" in by_id["W2"]["observation"]
    by_source = analyze_questions(
        observed, source_filter=["合成长时段手表"], question_ids=["W6"], **KW
    )[0]
    a = by_source["association"]
    assert a["status"] == "estimated" and a["coefficient"] == pytest.approx(3.1, abs=0.4)
    assert a["interval"][0] < 3.1 < a["interval"][1] and len(a["pairs"]) == 118
    assert all(instant(p["sdnn_first"]) >= instant(p["sleep_end"]) for p in a["pairs"])
    assert {model["status"] for model in by_id["W6"]["association"]["groups"]} == {
        "descriptive_only",
        "estimated",
    }


def test_almost_constant_or_shared_calendar_trend_factors_not_identifiable():
    start = datetime(2025, 5, 1)
    for fx in (lambda i: 7.0 + (0.00001 if i % 2 else 0), lambda i: 6 + i * 0.03):
        points = [
            {
                "date": (start + timedelta(days=i)).date().isoformat(),
                "value": 50 + i * 0.7,
                "sleep_hours": fx(i),
            }
            for i in range(84)
        ]
        assert fit_daily(points, "ms", factor="sleep_hours")["status"] == "descriptive_only"


def test_order_specific_sleep_training_pairs_include_unmatched():
    def episode(a, b, identity):
        return {
            "event_start": "2026-07-" + a + "Z",
            "event_end": "2026-07-" + b + "Z",
            "episode_id": identity,
            "value": 60,
            "protocol": ["S"],
        }

    episodes = [
        episode("05T23:00", "06T07:00", "night"),
        episode("06T12:00", "06T13:00", "afternoon"),
        episode("06T23:00", "07T07:00", "following_night"),
    ]
    sessions = [
        {"id": 1, "started_at": "2026-07-06T08:00Z", "ended_at": "2026-07-06T09:00Z"},
        {"id": 2, "started_at": "2026-07-06T17:00Z", "ended_at": "2026-07-06T18:00Z"},
        {"id": 3, "started_at": "2026-07-20T10:00Z"},
    ]
    p = sleep_training_pairs(
        episodes, sessions, start=instant("2026-07-01T00:00Z"), end=instant("2026-08-01T00:00Z")
    )
    assert [[e["episode_id"] for e in r["matches"]] for r in p["before_training"]] == [
        ["night"],
        ["night", "afternoon"],
        [],
    ]
    assert [[e["episode_id"] for e in r["matches"]] for r in p["after_training"]] == [
        ["afternoon", "following_night"],
        ["following_night"],
        [],
    ]
    assert p["after_training"][-1]["unmatched_reason"] == "训练结束时间未知"


def test_sri_observed_states_and_midnight_circular_time():
    win = Window("2026-07-01T00:00Z", "2026-07-03T00:00Z", "2026-07-03T00:00Z")

    def row(d, h0, h1, category):
        a = instant("2026-07-01T00:00Z") + timedelta(days=d, hours=h0)
        b = a + timedelta(hours=h1 - h0)
        return {
            "event_start": a.isoformat(),
            "event_end": b.isoformat(),
            "category_value": category,
            "source_name": "S",
            "canonical_type": "sleep_stage",
        }

    sleep = [row(d, 0, 8, "asleep") for d in range(2)]
    awake = [row(d, 8, 24, "awake") for d in range(2)]
    episodes = [
        {"intervals": [{"start": t}], "protocol": ["S", None, None, None]}
        for t in ("2026-07-01T23:50Z", "2026-07-02T00:10Z")
    ]
    part = next(iter(sleep_regularity(sleep, episodes, win).values()))
    assert part["paired_minutes"] == 480 and part["unpaired_minutes"] == 960 and part["sri"] is None
    assert (
        min(
            part["observed_start_circular_mean_minutes"],
            1440 - part["observed_start_circular_mean_minutes"],
        )
        < 1e-6
    )
    full = next(iter(sleep_regularity(sleep + awake, episodes, win).values()))
    assert full["sri"] == 100 and full["paired_minutes"] == 1440


def test_historical_range_error_and_goal_are_independent():
    ref = {"quartiles": [58, 60, 63]}
    value = change_layers(4, ref, current=62, identity="A", unit="bpm")
    assert (
        value["within_reference_iqr"]
        and value["exceeds_repeatability_limit"] is None
        and value["meets_independent_goal_magnitude"] is None
    )
    common = {"identity": "A", "unit": "bpm"}
    error = {
        **common,
        "source": "synthetic matched repeat study",
        "threshold": 3,
        "basis": "matched_repeat_measurements",
    }
    target = {
        **common,
        "source": "independent synthetic goal",
        "threshold": 5,
        "basis": "prespecified_goal_scale",
    }
    a = change_layers(4, ref, current=62, measurement=error, goal=target, **common)
    assert (
        a["exceeds_repeatability_limit"] is True and a["meets_independent_goal_magnitude"] is False
    )
    assert (
        change_layers(4, ref, measurement={**error, "identity": "different device"}, **common)[
            "exceeds_repeatability_limit"
        ]
        is None
    )


def test_newly_supported_type_backfilled_only_from_supplied_same_zip(tmp_path, monkeypatch):
    raw = "HKQuantityTypeIdentifierWalkingSpeed"
    z = Path(tmp_path) / "synthetic.zip"
    rec = '<Record type="{}" value="{}" unit="{}" startDate="2026-11-13T00:00Z" endDate="2026-11-13T00:00Z" sourceName="S"/>'
    with ZipFile(z, "w") as f:
        f.writestr(
            "apple_health_export/export.xml",
            "<HealthData>"
            + rec.format(raw, 1, "m/s")
            + rec.format("HKQuantityTypeIdentifierStepCount", 30, "count")
            + "</HealthData>",
        )
    r = Repository(tmp_path / "db")
    with monkeypatch.context() as m:
        m.delitem(TYPE_MAP, raw)
        first = import_apple_zip(z, r)
        assert first.records_inserted == 1
    second = import_apple_zip(z, r)
    assert second.records_inserted == 1 and second.records_seen == 1
    assert import_apple_zip(z, r).status == "already_imported" and r.count("health_sample") == 2
    assert json.loads(
        r.one("SELECT unknown_type_counts_json FROM import_batch WHERE id=?", (first.batch_id,))[0]
    ) == {raw: 1}
    r.close()


def test_absent_import_unknown_and_explicit_feature_disabled(tmp_path):
    r = Repository(tmp_path / "db")
    assert (
        analyze_body_metric(r, "high_hr_event", **KW)["availability"]
        == "no_visible_import_or_record"
    )
    ctx = {"source": "synthetic capability declaration", "status": "feature_disabled"}
    assert (
        analyze_body_metric(r, "high_hr_event", availability_context=ctx, **KW)["availability"]
        == "feature_disabled"
    )
    r.close()


def test_ratio_and_recorded_meal_do_not_become_independent_strength_or_total_intake(observed):
    q = analyze_questions(observed, question_ids=["W5"], **KW)[0]
    ratios = [r for r in q["rows"] if r["type"] == "relative_load" and r["position"] == 1]
    a, b = ratios[0], ratios[-1]
    assert b["load_kg"] == a["load_kg"] == 40 and a["reps"] == b["reps"] == 8
    assert b["mass_kg"] < a["mass_kg"] and b["load_per_kg"] > a["load_per_kg"]
    assert all(instant(r["mass_measured_at"]) <= instant(r["date"]) for r in ratios)
    meal = analyze_body_metric(observed, "dietary_energy_kcal", **KW)["value"]["streams"][0]
    assert meal["current"]["recorded_total"] == 350 and meal["current"]["recorded_days"] == 1
    assert meal["current"]["calendar_coverage_proves_measurement_coverage"] is False


def test_non_linear_and_state_only_unmeasured_sleep_have_local_fallback():
    first = datetime(2026, 1, 1)
    series = [
        {"date": (first + timedelta(days=i)).date().isoformat(), "value": i**2 + (i % 3)}
        for i in range(100)
    ]
    assert fit_daily(series, "bpm")["status"] == "descriptive_only"


def test_same_length_week_and_month_comparisons_keep_period_identity(observed):
    for period, first, expected in [
        ("week", "2026-11-16T00:00:00+08:00", "2026-11-09"),
        ("month", "2026-11-01T00:00:00+08:00", "2026-10-01"),
    ]:
        m = analyze_body_metric(
            observed,
            "steps",
            window_start=first,
            window_end=CUTOFF,
            cutoff_time=CUTOFF,
            period=period,
        )
        assert m["scope"]["period"] == period and m["scope"]["bounds"]["previous"][
            "start"
        ].startswith(expected)
