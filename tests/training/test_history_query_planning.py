"""Training query plans retain revision semantics without decoding old payloads."""

from datetime import datetime, timedelta, timezone

import pytest

from healthzip.analytics.v13 import snapshot
from healthzip.db.repository import Repository
from healthzip.training import TrainingService
from healthzip.training import service as service_module


@pytest.fixture
def service(tmp_path):
    repo = Repository(tmp_path / "synthetic-history-query.sqlite3")
    value = TrainingService(repo)
    yield value
    repo.close()


def add_session(service, when, *, template=False):
    condition = {"load_basis": "external_total_kg", "load_basis_confirmed": True}
    template_id = None
    if template:
        template_id = service.create_template("Synthetic frozen plan", [{
            "exercise_id": "psa.ex.barbell_bench_press", "condition": condition,
            "targets": {"sets": [{"reps_min": 5, "reps_max": 8}]},
        }])["id"]
    session = service.start_session("Synthetic session", started_at=when, template_id=template_id)
    if template:
        instance = session["exercises"][0]
        row = session["sets"][0]
    else:
        instance = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
        row = service.add_set(instance["id"], {})
    actual = {"completion_state": "completed", "started_at": when, "ended_at": when,
              "load_value": 40, "load_unit": "kg", "reps": 6}
    row = service.edit_set(row["id"], actual, base_revision=row["revision"])
    return session, instance, row


def bounds():
    now = datetime.now(timezone.utc)
    return {"window_start": (now - timedelta(days=7)).isoformat(),
            "window_end": (now + timedelta(days=1)).isoformat()}


def test_default_snapshot_does_not_decode_window_external_training_history(service, monkeypatch):
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    old_event_ids = set()
    for _ in range(12):
        add_session(service, old, template=True)
    old_event_ids.update(row[0] for row in service.conn.execute("SELECT event_id FROM training_event"))
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    current, _, row = add_session(service, recent, template=True)
    decoded = []
    original = service_module._decode

    def counted(value):
        if value is not None and "entity_type" in value.keys():
            decoded.append(value["event_id"])
        return original(value)

    monkeypatch.setattr(service_module, "_decode", counted)
    records, context = snapshot(service.repo, (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(), **bounds())
    assert not old_event_ids.intersection(decoded), "Window-external training events must stay in SQLite"
    assert len(decoded) == len(set(decoded)), "One snapshot must not decode the same event for sets, sessions and plans"
    assert [x["set_uuid"] for x in records if x["record_kind"] == "strength_set"] == [row["set_uuid"]]
    assert context["session_plans"][0]["session_id"] == current["id"]
    assert context["session_plans"][0]["sets"][0]["targets"]["reps_min"] == 5


def test_window_lookup_resolves_all_visible_revisions_before_membership(service):
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    _, _, row = add_session(service, old)
    before_move = row["available_at"]
    moved = service.edit_set(row["id"], {"started_at": recent, "ended_at": recent}, base_revision=row["revision"])
    during = moved["available_at"]
    assert service.history_as_of(cutoff_time=before_move, **bounds()) == []
    assert [x["set_uuid"] for x in service.history_as_of(cutoff_time=during, **bounds())] == [row["set_uuid"]]
    outside = service.edit_set(row["id"], {"started_at": old, "ended_at": old}, base_revision=moved["revision"])
    assert service.history_as_of(cutoff_time=outside["available_at"], **bounds()) == []
    assert service.history_as_of(cutoff_time=during, **bounds())[0]["ended_at"] == recent


def test_scoped_replay_preserves_conflicts_session_tombstone_and_undo(service):
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    session, _, row = add_session(service, recent)
    conflict = service.edit_set(row["id"], {"reps": 8}, base_revision=0)
    conflicting_cutoff = datetime.now(timezone.utc).isoformat()
    assert service.history_as_of(cutoff_time=conflicting_cutoff, **bounds())[0]["conflicted"]
    service.resolve_conflict(conflict["conflict_id"], choice="keep_current")
    resolved_cutoff = datetime.now(timezone.utc).isoformat()
    assert not service.history_as_of(cutoff_time=resolved_cutoff, **bounds())[0]["conflicted"]
    deleted = service.delete_session(session["id"], base_revision=service.get_session(session["id"])["revision"])
    assert service.history_as_of(cutoff_time=datetime.now(timezone.utc).isoformat(), **bounds()) == []
    assert service.history_as_of(cutoff_time=conflicting_cutoff, **bounds())[0]["conflicted"]
    service.undo_event(deleted["event_id"], base_revision=service.get_session(session["id"])["revision"])
    assert service.history_as_of(cutoff_time=datetime.now(timezone.utc).isoformat(), **bounds())[0]["set_uuid"] == row["set_uuid"]


def test_session_start_outside_window_cannot_hide_cross_window_completion(service):
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    session, _, row = add_session(service, old, template=True)
    service.edit_set(row["id"], {"ended_at": recent}, base_revision=row["revision"])
    records, context = snapshot(service.repo, datetime.now(timezone.utc).isoformat(), **bounds())
    assert [x["set_uuid"] for x in records if x["record_kind"] == "strength_set"] == [row["set_uuid"]]
    assert context["sessions"][0]["id"] == session["id"]
    assert context["session_plans"][0]["sets"][0]["id"] == row["set_uuid"]


def test_query_padding_does_not_relax_microsecond_window_or_cutoff(service):
    when = "2020-01-01T12:00:00.000001+00:00"
    _, _, row = add_session(service, when)
    service.conn.execute("UPDATE training_event SET recorded_at='2020-01-02T00:00:00.000001+00:00'")
    assert service.history_as_of(cutoff_time="2020-01-02T00:00:00+00:00", window_start="2020-01-01T12:00:00+00:00", window_end="2020-01-01T12:00:01+00:00") == []
    included = service.history_as_of(cutoff_time="2020-01-02T00:00:00.000001+00:00", window_start="2020-01-01T12:00:00+00:00", window_end="2020-01-01T12:00:00.000002+00:00")
    assert included[0]["set_uuid"] == row["set_uuid"]
    assert service.history_as_of(cutoff_time="2020-01-02T00:00:00.000001+00:00", window_start="2020-01-01T20:00:00+08:00", window_end="2020-01-01T20:00:00.000001+08:00") == []


def test_future_movement_cannot_nominate_old_session_for_past_snapshot(service):
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    _, _, row = add_session(service, old)
    cutoff = datetime.now(timezone.utc).isoformat()
    window = bounds()
    before_rows, before_context = snapshot(service.repo, cutoff, **window)
    service.edit_set(row["id"], {"started_at": recent, "ended_at": recent}, base_revision=row["revision"])
    after_rows, after_context = snapshot(service.repo, cutoff, **window)
    assert before_rows == after_rows == []
    for key in ("sessions", "session_plans", "recommendation_outcomes", "query_plan"):
        assert before_context[key] == after_context[key]


@pytest.mark.parametrize("start,end", [("2020-01-02T12:00:00Z", "2020-01-04T00:00:00Z"),
                                      ("2020-01-01T00:00:00Z", "2020-01-04T00:00:00Z")])
def test_snapshot_keeps_interval_support_for_science_to_determine_membership(service, start, end):
    session = service.start_session("Synthetic duration", started_at=start)
    exercise = service.create_exercise("Synthetic timed hold", "duration", "bodyweight", "bodyweight_no_external")
    instance = service.add_exercise(session["id"], exercise["exercise_id"], {"load_basis": "bodyweight_no_external", "load_basis_confirmed": True})
    row = service.add_set(instance["id"], {"completion_state": "completed", "duration_s": 60,
        "started_at": start, "ended_at": end})
    cutoff = datetime.now(timezone.utc).isoformat()
    full, _ = snapshot(service.repo, cutoff)
    scoped, _ = snapshot(service.repo, cutoff, window_start="2020-01-02T00:00:00Z", window_end="2020-01-03T00:00:00Z")
    assert [x for x in scoped if x.get("set_uuid") == row["set_uuid"]] == [x for x in full if x.get("set_uuid") == row["set_uuid"]]


def test_replay_orders_recorded_offsets_by_instant_then_event_order(service):
    when = "2020-01-01T00:00:00+00:00"
    _, _, row = add_session(service, when)
    service.conn.execute("UPDATE training_event SET recorded_at='2020-01-02T00:00:00+00:00'")
    first = service.edit_set(row["id"], {"reps": 7}, base_revision=row["revision"])
    second = service.edit_set(row["id"], {"reps": 8}, base_revision=first["revision"])
    service.conn.execute("UPDATE training_event SET recorded_at='2020-01-02T12:00:00+08:00' WHERE event_id=?", (first["event_id"],))
    service.conn.execute("UPDATE training_event SET recorded_at='2020-01-02T05:00:00+00:00' WHERE event_id=?", (second["event_id"],))
    result = service.history_as_of(cutoff_time="2020-01-02T06:00:00Z", window_start="2020-01-01T00:00:00Z", window_end="2020-01-02T00:00:00Z")
    assert result[0]["reps"] == 8
