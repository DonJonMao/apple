"""Sleep contexts obey the same visible-revision and half-open time contract."""
from datetime import datetime, timedelta

import pytest

from healthzip.science import evaluate
from healthzip.science.contracts import Window, select_as_of

START = "2026-11-01T00:00:00+00:00"
END = "2026-11-08T00:00:00+00:00"


def episode(**changes):
    return {"id": "synthetic-episode", "source_record_id": "synthetic-episode",
            "start": "2026-11-02T23:00:00+00:00", "end": "2026-11-03T07:00:00+00:00",
            "available_at": "2026-11-03T08:00:00+00:00", **changes}


def timing(episodes, **context):
    return evaluate("STATE-SLEEP-TIMING", [], cutoff_time=END, window_start=START,
                    window_end=END, context={"sleep_episodes": episodes, **context})


@pytest.mark.parametrize("changes,reason", [
    ({"start": "2020-01-01T23:00:00+00:00", "end": "2020-01-02T07:00:00+00:00"}, "outside_window"),
    ({"start": "2026-11-07T23:00:00+00:00", "end": END}, "outside_window"),
    ({"available_at": "2027-01-01T00:00:00+00:00"}, "available_after_cutoff"),
    ({"available_at": None}, "available_at_unknown"),
])
def test_timing_rejects_unavailable_or_outside_episodes(changes, reason):
    result = timing([episode(**changes)])
    assert result["value"] is None
    assert result["data_status"] == "insufficient"
    assert any(item.get("context") == "sleep_episodes" and item["reason"] == reason
               for item in result["exclusions"])


def test_timing_unknown_availability_requires_explicit_retrospective_mode():
    result = timing([episode(available_at=None)], retrospective=True)
    assert result["value"]["circular_midpoint_hour"] == 3
    assert "retrospective_snapshot_not_prospective" in result["reason_codes"]
    assert result["source_record_ids"] == ["synthetic-episode"]
    assert result["count_domain"] == "sleep_episodes" and result["valid_n"] == 1
    assert timing([episode(end=None)], retrospective=True)["value"] is None


@pytest.mark.parametrize("start,end,zone,midpoint", [
    ("2026-11-01T00:00:00-04:00", "2026-11-01T08:00:00-05:00", "America/New_York", 3.5),
    ("2026-11-02T23:30:00+08:00", "2026-11-03T07:30:00+08:00", "Asia/Shanghai", 3.5),
])
def test_timing_keeps_original_endpoints_and_actual_time_midpoint(start, end, zone, midpoint):
    result = timing([episode(start=start, end=end, timezone=zone)])
    point = result["value"]["episodes"][0]
    assert point["local_hour"] == midpoint
    assert point["recorded_start"] == start and point["recorded_end"] == end
    assert point["available_at"] == "2026-11-03T08:00:00+00:00"
    assert result["source_record_ids"] == ["synthetic-episode"]
    assert result["value"]["window_membership"] == "episode_end_in_half_open_window"


def test_timing_revisions_do_not_revive_an_old_in_window_episode():
    original = episode()
    moved = episode(id="revision-2", start="2026-10-30T23:00:00+00:00",
                    end="2026-10-31T07:00:00+00:00", available_at="2026-11-04T00:00:00+00:00")
    assert timing([original, moved])["value"] is None


def test_sleep_stage_annotations_use_the_declared_episode_support():
    rows = []
    for day in (2, 3):
        rows.append({"id": f"synthetic-stage-{day}", "canonical_type": "sleep_stage",
                     "stage": "deep", "source_name": "synthetic-watch",
                     "event_start": f"2026-11-0{day}T00:00:00+00:00",
                     "event_end": f"2026-11-0{day}T08:00:00+00:00",
                     "available_at": f"2026-11-0{day}T08:01:00+00:00"})
    result = evaluate("STATE-SLEEP-STAGE", rows, cutoff_time=END, window_start=START,
                      window_end=END, context={"main_sleep_episode": {
                          "start": rows[1]["event_start"], "end": rows[1]["event_end"],
                          "available_at": rows[1]["available_at"], "complete": True}})
    assert result["value"]["stage_minutes"] == {"deep": 480}
    assert result["value"]["annotation_coverage"] == 1
    assert result["data_status"] == "valid"


@pytest.mark.parametrize("revision", [
    {"event_end": "2027-01-01T00:00:00+00:00"},
    {"event_end": None},
    {"record_status": "deleted", "event_end": None},
])
def test_visible_revision_invalidates_older_record_before_event_filter(revision):
    original = {"id": "original", "source_record_id": "logical-sample",
                "event_end": "2026-11-03T07:00:00+00:00", "available_at": "2026-11-03T08:00:00+00:00"}
    changed = {**original, "id": "revision", "available_at": "2026-11-04T08:00:00+00:00", **revision}
    selected, _ = select_as_of([original, changed], Window(START, END, END))
    assert selected == []
    # A correction learned after the decision cannot invalidate its old fact.
    selected, _ = select_as_of([original, {**changed, "available_at": (
        datetime.fromisoformat(END) + timedelta(seconds=1)).isoformat()}], Window(START, END, END))
    assert [row["id"] for row in selected] == ["original"]
