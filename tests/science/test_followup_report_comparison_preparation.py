"""Keep the prior comparison algorithm as an oracle for one-cutoff preparation."""
from collections import defaultdict
from copy import deepcopy
from unittest.mock import patch

import pytest

from healthzip.science import engine, reports
from healthzip.science.contracts import Window, instant, select_as_of


def prior_comparison(rows, window, *, previous=None, baseline_days=28, retrospective=False):
    """The unchanged pre-optimization algorithm: resolve all rows per window."""
    bounds = reports.comparison_windows(window, previous=previous, baseline_days=baseline_days)
    groups, units = defaultdict(dict), {}
    sleep = reports.visible_sleep_history(rows, window, retrospective=retrospective)
    for name, interval in bounds.items():
        if instant(interval["start"]) >= instant(interval["end"]):
            continue
        period = Window(interval["start"], interval["end"], window.cutoff_time, window.timezone)
        selected, _ = select_as_of(rows, period, retrospective=retrospective, overlap=True)
        facts = reports.derive_report_context(selected, period, sleep_rows=sleep)["daily_metric_facts"]
        for fact in facts:
            if fact.get("metric_id") not in {"STATE-RHR", "STATE-SDNN", "sleep_observed_minutes_by_wake_date"}:
                continue
            identity = fact["metric_id"] + ":" + str(fact.get("source_id"))
            groups[identity].setdefault(name, []).append(fact)
            units[identity] = fact.get("unit") or {"STATE-RHR": "bpm", "STATE-SDNN": "ms", "BODY-MASS-DAILY": "kg"}.get(fact["metric_id"])
    output = reports.comparison_from_daily({}, bounds, window.cutoff_time, None)
    output["statistic_kind"] = "median_of_daily_representatives"
    for identity, periods in groups.items():
        output["streams"].extend(reports.comparison_from_daily({identity: periods}, bounds, window.cutoff_time, units[identity])["streams"])
    return output


WINDOW = Window("2026-11-09T00:00:00+08:00", "2026-11-16T00:00:00+08:00",
                "2026-11-15T12:00:00+08:00", "Asia/Shanghai")


def sample(identity, day, value, **fields):
    stamp = f"2026-11-{day:02}T08:00:00+08:00"
    return {"id": identity, "canonical_type": "resting_heart_rate_bpm", "value": value, "unit": "bpm",
            "source_kind": "health_sample", "source_name": "Synthetic comparison watch",
            "device": "comparison-device", "event_start": stamp, "event_end": stamp,
            "available_at": stamp, **fields}


def point_ids(value, period="current"):
    return {identifier for stream in value["streams"] for identifier in stream[period]["source_record_ids"]}


def assert_equivalent(rows, window=WINDOW, **kwargs):
    original = deepcopy(rows)
    expected = prior_comparison(rows, window, **kwargs)
    actual = reports.report_comparison(rows, window, **kwargs)
    assert actual == expected
    assert rows == original
    return actual


def test_complete_rows_are_resolved_once_without_losing_support_windows():
    rows = [sample("earlier", 3, 60), sample("current", 10, 65),
            sample("other-type", 11, 22, canonical_type="body_mass_kg", unit="kg")]
    expected = prior_comparison(rows, WINDOW)
    with patch.object(reports, "select_as_of", wraps=select_as_of) as selected:
        actual = reports.report_comparison(rows, WINDOW)
    assert actual == expected
    complete_calls = [call for call in selected.call_args_list if call.args[0] is rows]
    assert len(complete_calls) == 1
    assert complete_calls[0].kwargs == {"retrospective": False, "overlap": True}
    stream = actual["streams"][0]
    assert stream["current"]["value"] == 65
    assert stream["previous"]["value"] == 60
    assert stream["previous_change"]["absolute"] == 5


@pytest.mark.parametrize("revision", ["cross_type", "tombstone", "future_event", "conflict", "outside_union", "late_revision"])
def test_revision_resolution_precedes_type_and_event_filtering(revision):
    old = sample("obsolete", 10, 777, source_record_id="same-logical-record")
    corrected = {**old, "id": "correction", "available_at": "2026-11-12T09:00:00+08:00"}
    corrected.update({
        "cross_type": {"canonical_type": "step_count", "value": 999, "unit": "count"},
        "tombstone": {"record_status": "deleted"},
        "future_event": {"event_start": "2026-12-01T08:00:00+08:00", "event_end": "2026-12-01T08:00:00+08:00"},
        "conflict": {"conflicted": True},
        "outside_union": {"event_start": "2025-01-01T08:00:00+08:00", "event_end": "2025-01-01T08:00:00+08:00"},
        "late_revision": {"available_at": "2026-11-18T08:00:00+08:00", "value": 999},
    }[revision])
    actual = assert_equivalent([sample("earlier", 2, 59), old, corrected, sample("retained", 11, 62)])
    assert ("obsolete" in point_ids(actual)) is (revision == "late_revision")
    assert "correction" not in point_ids(actual)
    assert "retained" in point_ids(actual)


@pytest.mark.parametrize("retrospective", [False, True])
def test_missing_ids_keep_original_positions_and_unknown_visibility(retrospective):
    rows = [sample("irrelevant", 2, 20, canonical_type="body_mass_kg", unit="kg"),
            sample("remove", 10, 61), sample("remove", 3, 58), sample("unknown", 11, 65, available_at=None)]
    rows[1].pop("id")
    rows[2].pop("id")
    actual = assert_equivalent(rows, retrospective=retrospective)
    assert "1" in point_ids(actual)
    assert "2" in point_ids(actual, "previous")
    assert ("unknown" in point_ids(actual)) is retrospective


@pytest.mark.parametrize("retrospective", [False, True])
def test_sleep_support_crosses_midnight_offset_transition_and_disjoint_previous(retrospective):
    window = Window("2026-11-01T00:00:00-04:00", "2026-11-03T00:00:00-05:00",
                    "2026-11-02T20:00:00-05:00", "America/New_York")
    previous = {"start": "2026-10-20T00:00:00-04:00", "end": "2026-10-22T00:00:00-04:00"}
    rows = [
        {"id": "before-midnight", "canonical_type": "sleep_stage", "stage": "core", "source_name": "Synthetic sleep",
         "event_start": "2026-10-31T22:00:00-04:00", "event_end": "2026-11-01T01:30:00-04:00",
         "available_at": "2026-11-01T08:00:00-05:00"},
        {"id": "offset-transition", "canonical_type": "sleep_stage", "stage": "deep", "source_name": "Synthetic sleep",
         "event_start": "2026-11-01T01:30:00-04:00", "event_end": "2026-11-01T06:00:00-05:00",
         "available_at": "2026-11-01T08:00:00-05:00"},
        {"id": "prior-sleep", "canonical_type": "sleep_stage", "stage": "asleep", "source_name": "Synthetic sleep",
         "event_start": "2026-10-19T22:00:00-04:00", "event_end": "2026-10-20T06:00:00-04:00",
         "available_at": "2026-10-20T08:00:00-04:00"},
        sample("rhr", 1, 64, event_start="2026-11-01T09:00:00-05:00", event_end="2026-11-01T09:00:00-05:00",
               available_at="2026-11-01T10:00:00-05:00"),
        sample("sdnn", 2, 34, canonical_type="hrv_sdnn_ms", unit="ms"),
    ]
    actual = assert_equivalent(rows, window, previous=previous, baseline_days=3, retrospective=retrospective)
    sleep = next(stream for stream in actual["streams"] if stream["metric_id"] == "sleep_observed_minutes_by_wake_date")
    assert sleep["current"]["value"] == 540
    assert sleep["previous"]["value"] == 480
    assert sleep["current"]["source_record_ids"] == ["before-midnight", "offset-transition"]
    assert sleep["current"]["partial_dates"] == ["2026-11-02"]


@pytest.mark.parametrize("rows", [[], [sample("outside", 1, 62)]])
def test_empty_and_zero_length_previous_preserve_output(rows):
    assert_equivalent(rows, previous={"start": WINDOW.start, "end": WINDOW.start})


def test_all_77_metric_values_match_prior_comparison(monkeypatch):
    from tests.science.test_contracts_and_strength import row

    rows = [sample("current", 10, 66), sample("earlier", 3, 60),
            sample("sdnn", 12, 32, canonical_type="hrv_sdnn_ms", unit="ms")]
    rows += [row(i, is_reference=False, equipment_instance_id=None,
                 performed_at="2026-11-10T08:00:00+08:00", event_end="2026-11-10T08:00:00+08:00",
                 available_at="2026-11-10T09:00:00+08:00") for i in range(1, 6)]
    kwargs = {"cutoff_time": WINDOW.cutoff_time, "window_start": WINDOW.start, "window_end": WINDOW.end,
              "context": {"timezone": WINDOW.timezone}}
    actual = engine.evaluate_all(rows, **kwargs)
    monkeypatch.setattr(engine, "report_comparison", prior_comparison)
    expected = engine.evaluate_all(rows, **kwargs)

    def without_clock(value):
        if isinstance(value, dict):
            return {key: without_clock(item) for key, item in value.items() if key != "computed_at"}
        if isinstance(value, list):
            return [without_clock(item) for item in value]
        return value

    assert len(actual) == 77
    assert without_clock(actual) == without_clock(expected)


def test_comparison_prepares_only_required_facts_and_preserves_other_report_domains():
    rows = [sample("rhr-previous-a", 3, 56), sample("rhr-previous-b", 4, 60),
            sample("rhr-current-a", 10, 64), sample("rhr-current-b", 11, 70),
            sample("rhr-current-c", 12, 66),
            sample("sdnn-previous", 3, 50, canonical_type="hrv_sdnn_ms", unit="ms"),
            sample("sdnn-current-a", 10, 20, canonical_type="hrv_sdnn_ms", unit="ms"),
            sample("sdnn-current-b", 11, 40, canonical_type="hrv_sdnn_ms", unit="ms"),
            sample("mass", 10, 71, canonical_type="body_mass_kg", unit="kg"),
            sample("symptom", 10, None, canonical_type=None, fatigue=3)]
    for identity, start, end in (
            ("sleep-previous", "2026-11-02T22:00:00+08:00", "2026-11-03T06:00:00+08:00"),
            ("sleep-current", "2026-11-09T23:00:00+08:00", "2026-11-10T06:00:00+08:00")):
        rows.append({"id": identity, "canonical_type": "sleep_stage", "stage": "asleep",
                     "source_name": "Synthetic comparison sleep", "event_start": start,
                     "event_end": end, "available_at": end})
    for identity, canonical, value in (("basal", "basal_energy_kcal", 1800),
                                       ("active", "active_energy_kcal", 300)):
        rows.append(sample(identity, 10, value, canonical_type=canonical, unit="kcal",
                           event_start="2026-11-10T00:00:00+08:00",
                           event_end="2026-11-11T00:00:00+08:00",
                           available_at="2026-11-11T01:00:00+08:00"))
    frozen = deepcopy(rows)
    expected = prior_comparison(rows, WINDOW)
    with patch.object(reports, "device_energy_days", wraps=reports.device_energy_days) as energy, \
            patch.object(reports, "daily_values", wraps=reports.daily_values) as daily:
        actual = reports.report_comparison(rows, WINDOW)
    assert actual == expected
    streams = {stream["metric_id"]: stream for stream in actual["streams"]}
    assert set(streams) == {"STATE-RHR", "STATE-SDNN", "sleep_observed_minutes_by_wake_date"}
    rhr, sdnn, sleep = (streams[key] for key in ("STATE-RHR", "STATE-SDNN", "sleep_observed_minutes_by_wake_date"))
    assert (rhr["current"]["value"], rhr["previous"]["value"], rhr["previous_change"]["absolute"]) == (66, 58, 8)
    assert set(rhr["current"]["source_record_ids"]) == {"rhr-current-a", "rhr-current-b", "rhr-current-c"}
    assert (sdnn["current"]["value"], sdnn["previous"]["value"], sdnn["previous_change"]["absolute"]) == (30, 50, -20)
    assert (sleep["current"]["value"], sleep["previous"]["value"]) == (420, 480)
    assert sleep["current"]["source_record_ids"] == ["sleep-current"]
    assert energy.call_count == 0
    assert {call.args[1] for call in daily.call_args_list} == {"resting_heart_rate_bpm", "hrv_sdnn_ms"}

    selected, _ = select_as_of(rows, WINDOW, overlap=True)
    full = reports.derive_report_context(selected, WINDOW)
    other = {fact["metric_id"]: fact for fact in full["daily_metric_facts"]
             if fact["metric_id"] in {"BODY-MASS-DAILY", "STATE-FATIGUE"}}
    assert other["BODY-MASS-DAILY"]["value"] == 71
    assert other["BODY-MASS-DAILY"]["source_record_ids"] == ["mass"]
    assert other["STATE-FATIGUE"]["value"] == 3
    assert other["STATE-FATIGUE"]["source_record_ids"] == ["symptom"]
    assert len(full["energy_days"]) == 1
    assert full["energy_days"][0]["complete"] is True
    assert full["energy_days"][0]["device_total_kcal"] == 2100
    assert set(full["energy_days"][0]["source_record_ids"]) == {"basal", "active"}
    assert rows == frozen
