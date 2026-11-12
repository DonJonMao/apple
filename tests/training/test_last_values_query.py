"""Exact last-value lookup retains all history while replaying only candidates."""

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from healthzip.db.repository import Repository
from healthzip.training import TrainingService
from healthzip.training import service as service_module
from healthzip.training.schema import migrate_training
from healthzip.training.semantics import timestamp


@pytest.fixture
def history(tmp_path, monkeypatch):
    clock = [datetime(2026, 1, 1, 8, tzinfo=timezone.utc)]
    monkeypatch.setattr(service_module, "timestamp", lambda value=None:
        timestamp(value) if value is not None else clock[0].isoformat())
    repo = Repository(tmp_path / "synthetic-last-values.sqlite3")
    service = TrainingService(repo)
    equipment = service.create_equipment("Synthetic barbell", "barbell")
    condition = {"equipment_instance_id": equipment["id"], "load_basis": "external_total_kg",
        "load_basis_confirmed": True, "settings_confirmed": True, "settings": {},
        "side": "both", "repetition_semantics": "simultaneous", "rom_protocol": "declared_full"}

    def at(day):
        clock[0] = datetime(2026, 1, 1, 8, tzinfo=timezone.utc) + timedelta(days=day)
        return clock[0].isoformat()

    def add(day, *, completed=True, reps=6, supplied_condition=None, identity=None):
        when = at(day)
        session = service.start_session("Synthetic query", started_at=when)
        instance = service.add_exercise(session["id"], "psa.ex.barbell_bench_press",
            supplied_condition or condition)
        row = service.add_set(instance["id"], {"completion_state": "completed" if completed else "draft",
            "load_value": 40, "load_unit": "kg", "reps": reps,
            **({"started_at": when, "ended_at": when} if completed else {})}, set_id=identity)
        return session, instance, row

    yield service, at, add, condition
    repo.close()


def original_choice(service, instance_id, cutoff):
    """Full-history replay, independent of candidate selection and early stopping."""
    instance = service.get_session_exercise(instance_id)
    rows = service.history_as_of(cutoff_time=cutoff, condition_key=instance["condition_key"],
        _events=service.audit_events())
    return next((row for row in reversed(rows)
                 if row["session_id"] != instance["session_id"] and not row["conflicted"]), None)


def assert_choice(service, instance, cutoff, expected):
    old = original_choice(service, instance["id"], cutoff)
    assert (old or {}).get("set_uuid") == expected
    result = service.last_values(instance["id"], cutoff_time=cutoff)
    assert result.get("source_set_id") == expected
    assert result["status"] == ("available" if expected else "insufficient")
    return result


def test_same_condition_history_does_not_decode_all_old_events(history, monkeypatch):
    service, at, add, _ = history
    old_events = set()
    for day in range(100):
        add(day)
    old_events.update(row[0] for row in service.conn.execute("SELECT event_id FROM training_event"))
    _, _, latest = add(200)
    # Many revisions of the latest candidate must still be replayed only once.
    for number in range(70):
        latest = service.edit_set(latest["id"], {"notes": str(number)}, base_revision=latest["revision"])
    _, current, _ = add(201, completed=False)
    decoded = []
    original = service_module._decode

    def counted(row):
        if row is not None and "after_json" in row.keys():
            decoded.append(row["event_id"])
        return original(row)

    monkeypatch.setattr(service_module, "_decode", counted)
    result = service.last_values(current["id"], cutoff_time=at(202))
    assert result["source_set_id"] == latest["set_uuid"]
    assert not old_events.intersection(decoded)
    assert len(decoded) == len(set(decoded))


def test_more_than_one_batch_of_invalid_candidates_never_truncates_history(history):
    service, at, add, _ = history
    _, _, first = add(0)
    for day in range(1, 80):
        session, _, _ = add(day)
        service.delete_session(session["id"], base_revision=service.get_session(session["id"])["revision"])
    _, current, _ = add(81, completed=False)
    assert_choice(service, current, at(82), first["set_uuid"])


def test_candidate_moved_older_requires_continuing_and_preserves_old_cutoff(history, monkeypatch):
    service, at, add, _ = history
    _, _, middle = add(10)
    _, _, moved = add(20)
    for number in range(70):
        moved = service.edit_set(moved["id"], {"notes": str(number)}, base_revision=moved["revision"])
    past = at(25)
    earlier = at(2)
    at(30)
    service.edit_set(moved["id"], {"started_at": earlier, "ended_at": earlier}, base_revision=moved["revision"])
    _, current, _ = add(40, completed=False)
    assert_choice(service, current, past, moved["set_uuid"])
    decoded = Counter()
    original = service_module._decode

    def counted(row):
        if row is not None and "after_json" in row.keys():
            decoded[row["event_id"]] += 1
        return original(row)

    monkeypatch.setattr(service_module, "_decode", counted)
    result = service.last_values(current["id"], cutoff_time=at(41))
    assert result["source_set_id"] == middle["set_uuid"]
    assert max(decoded.values()) == 1


@pytest.mark.parametrize("kind", ["set", "session"])
def test_parent_or_set_deletion_and_undo_do_not_rewrite_past(history, kind):
    service, at, add, _ = history
    _, _, first = add(1)
    session, _, latest = add(2)
    before = at(3)
    at(4)
    target = latest if kind == "set" else service.get_session(session["id"])
    removed = getattr(service, "delete_" + kind)(target["id"], base_revision=target["revision"])
    during = at(5)
    at(6)
    target = getattr(service, "get_" + kind)(target["id"])
    service.undo_event(removed["event_id"], base_revision=target["revision"])
    _, current, _ = add(7, completed=False)
    assert_choice(service, current, before, latest["set_uuid"])
    assert_choice(service, current, during, first["set_uuid"])
    assert_choice(service, current, at(8), latest["set_uuid"])


@pytest.mark.parametrize("decision", ["keep_current", "apply_proposed"])
def test_conflicts_and_explicit_decisions_remain_cutoff_safe(history, decision):
    service, at, add, _ = history
    _, _, first = add(1)
    _, _, latest = add(2)
    before = at(3)
    at(4)
    conflict = service.edit_set(latest["id"], {"reps": 9}, base_revision=0)
    during = at(5)
    at(6)
    service.resolve_conflict(conflict["conflict_id"], choice=decision)
    _, current, _ = add(7, completed=False)
    assert_choice(service, current, before, latest["set_uuid"])
    assert_choice(service, current, during, first["set_uuid"])
    result = assert_choice(service, current, at(8), latest["set_uuid"])
    assert result["suggested_actual"]["reps"] == (9 if decision == "apply_proposed" else 6)


@pytest.mark.parametrize("entity_type", ["session", "session_exercise"])
def test_nested_completed_snapshots_nominate_candidates_without_independent_set_event(history, entity_type):
    service, at, add, _ = history
    session, instance, row = add(1)
    # Synthetic audit graph exercises both replay-supported nested snapshot forms.
    service.conn.execute("DELETE FROM training_event WHERE entity_type='set' AND entity_id=?", (row["set_uuid"],))
    at(2)
    after = (service.get_session(session["id"]) if entity_type == "session"
             else service.get_session_exercise(instance["id"]))
    service._mutate("synthetic_nested_snapshot", entity_type,
        session["session_uuid"] if entity_type == "session" else instance["id"], {},
        lambda old, eid, now: after)
    _, current, _ = add(3, completed=False)
    assert_choice(service, current, at(4), row["set_uuid"])


def test_nested_condition_revision_and_historical_cutoff(history):
    service, at, add, condition = history
    _, _, fallback = add(1)
    _, source, row = add(2)
    before = at(3)
    changed = {**condition, "rom_protocol": "other_declared_protocol"}
    _, changed_instance, _ = add(4, completed=False, supplied_condition=changed)
    nested = service.get_session_exercise(source["id"])
    nested["condition_key"] = changed_instance["condition_key"]
    nested["sets"] = [{**row, "condition_key": changed_instance["condition_key"],
        "condition": changed_instance["condition"]}]
    at(5)
    service._mutate("synthetic_nested_condition_revision", "session_exercise", source["id"], {},
        lambda old, eid, now: nested)
    _, original_instance, _ = add(6, completed=False)
    assert_choice(service, original_instance, before, row["set_uuid"])
    assert_choice(service, changed_instance, before, None)
    assert_choice(service, original_instance, at(7), fallback["set_uuid"])
    assert_choice(service, changed_instance, at(7), row["set_uuid"])


def test_projection_tracks_update_delete_and_transaction_rollback(history):
    service, at, add, _ = history
    _, _, row = add(1)
    _, current, _ = add(3, completed=False)
    original = dict(service.conn.execute("SELECT * FROM training_event WHERE event_id=?", (row["event_id"],)).fetchone())
    future = at(10)
    service.conn.execute("SAVEPOINT synthetic_projection_update")
    service.conn.execute("UPDATE training_event SET recorded_at=? WHERE event_id=?", (future, row["event_id"]))
    assert_choice(service, current, at(4), None)
    service.conn.execute("ROLLBACK TO synthetic_projection_update")
    service.conn.execute("RELEASE synthetic_projection_update")
    assert dict(service.conn.execute("SELECT * FROM training_event WHERE event_id=?", (row["event_id"],)).fetchone()) == original
    assert_choice(service, current, at(4), row["set_uuid"])
    after = json.loads(original["after_json"])
    after.update(started_at=future, ended_at=future)
    service.conn.execute("UPDATE training_event SET after_json=? WHERE event_id=?", (json.dumps(after), row["event_id"]))
    assert_choice(service, current, at(4), None)
    service.conn.execute("DELETE FROM training_event WHERE event_id=?", (row["event_id"],))
    assert service.conn.execute("SELECT COUNT(*) FROM training_event_set_candidate WHERE event_id=?", (row["event_id"],)).fetchone()[0] == 0


def test_projection_upgrade_is_atomic_and_preserves_original_event_bytes(history):
    service, _, add, _ = history
    add(1)
    event_bytes = [tuple(row) for row in service.conn.execute("SELECT * FROM training_event ORDER BY rowid")]
    candidates = [tuple(row) for row in service.conn.execute("SELECT * FROM training_event_set_candidate ORDER BY event_id,slot")]
    for operation in ("insert", "update", "delete"):
        service.conn.execute("DROP TRIGGER training_event_candidates_" + operation)
    service.conn.execute("DROP TABLE training_event_set_candidate")
    service.conn.execute("DELETE FROM schema_meta WHERE key='training_last_values_projection'")

    def interrupted(stage):
        if stage == "complete":
            raise RuntimeError("synthetic migration interruption")

    with pytest.raises(RuntimeError, match="synthetic migration interruption"):
        migrate_training(service.conn, checkpoint=interrupted)
    assert not service.conn.execute("SELECT 1 FROM sqlite_master WHERE name='training_event_set_candidate'").fetchone()
    migrate_training(service.conn)
    assert [tuple(row) for row in service.conn.execute("SELECT * FROM training_event ORDER BY rowid")] == event_bytes
    assert [tuple(row) for row in service.conn.execute("SELECT * FROM training_event_set_candidate ORDER BY event_id,slot")] == candidates
    migrate_training(service.conn)
    assert [tuple(row) for row in service.conn.execute("SELECT * FROM training_event_set_candidate ORDER BY event_id,slot")] == candidates


def test_candidate_projection_keeps_users_separate(history):
    service, at, add, _ = history
    _, _, row = add(1)
    _, current, _ = add(3, completed=False)
    other = TrainingService(service.repo, user_id="synthetic-other")
    at(4)
    other._mutate("synthetic_other_user_snapshot", "set", "other-set", {},
        lambda old, eid, now: {**row, "set_uuid": "other-set", "reps": 99,
            "ended_at": now, "started_at": now})
    assert_choice(service, current, at(5), row["set_uuid"])


def test_exact_microsecond_visibility_and_true_offset_order(history):
    service, at, add, _ = history
    _, _, first = add(1)
    _, _, latest = add(2)
    recorded = at(4).replace("+00:00", ".000001+00:00")
    service.conn.execute("UPDATE training_event SET recorded_at=? WHERE event_id=?", (recorded, latest["event_id"]))
    _, current, _ = add(5, completed=False)
    assert_choice(service, current, at(4), first["set_uuid"])
    assert_choice(service, current, recorded, latest["set_uuid"])
    # 12:00+08 is 04:00 UTC, before 05:00 UTC regardless of the text ordering.
    for row, endpoint in ((first, "2026-01-02T12:00:00+08:00"), (latest, "2026-01-02T05:00:00+00:00")):
        event = service.conn.execute("SELECT after_json FROM training_event WHERE event_id=?", (row["event_id"],)).fetchone()
        value = json.loads(event[0])
        value.update(started_at=endpoint, ended_at=endpoint)
        service.conn.execute("UPDATE training_event SET after_json=? WHERE event_id=?", (json.dumps(value), row["event_id"]))
    assert_choice(service, current, at(6), latest["set_uuid"])


def test_equal_offset_instants_use_uuid_tie_break_and_keep_microseconds(history):
    service, at, add, _ = history
    _, _, first = add(1, identity="z-synthetic-first")
    _, _, second = add(1, identity="a-synthetic-second")
    _, current, _ = add(3, completed=False)
    for row, endpoint in ((first, "2026-01-02T12:00:00.000001+08:00"),
                          (second, "2026-01-02T04:00:00.000001+00:00")):
        event = service.conn.execute("SELECT after_json FROM training_event WHERE event_id=?", (row["event_id"],)).fetchone()
        value = json.loads(event[0])
        value.update(started_at=endpoint, ended_at=endpoint)
        service.conn.execute("UPDATE training_event SET after_json=? WHERE event_id=?", (json.dumps(value), row["event_id"]))
    candidates = service.conn.execute("SELECT candidate_time,candidate_instant_us FROM training_event_set_candidate ORDER BY set_uuid").fetchall()
    assert candidates[0][0] != candidates[1][0]
    assert candidates[0][1] == candidates[1][1]
    assert_choice(service, current, at(4), first["set_uuid"])
    event = service.conn.execute("SELECT after_json FROM training_event WHERE event_id=?", (second["event_id"],)).fetchone()
    value = json.loads(event[0])
    value.update(started_at="2026-01-02T04:00:00.000002+00:00", ended_at="2026-01-02T04:00:00.000002+00:00")
    service.conn.execute("UPDATE training_event SET after_json=? WHERE event_id=?", (json.dumps(value), second["event_id"]))
    assert_choice(service, current, at(4), second["set_uuid"])


def test_warm_repository_connection_registers_projection_function_without_service(history):
    service, at, add, _ = history
    _, _, row = add(1)
    service.conn.commit()
    second = Repository(service.repo.path)
    try:
        when = at(4)
        second.conn.execute("UPDATE training_event SET recorded_at=? WHERE event_id=?", (when, row["event_id"]))
        second.conn.commit()
        projected = service.conn.execute("SELECT recorded_at,recorded_instant_us FROM training_event_set_candidate WHERE event_id=?", (row["event_id"],)).fetchone()
        assert projected[0] == when
        assert projected[1] == second.conn.execute("SELECT healthzip_instant_us(?)", (when,)).fetchone()[0]
    finally:
        second.close()


def test_automatic_cutoff_can_make_previously_recorded_future_set_eligible(history):
    service, at, add, _ = history
    _, _, future = add(10)
    service.conn.execute("UPDATE training_event SET recorded_at=?", (at(1),))
    _, current, _ = add(3, completed=False)
    at(5)
    assert service.last_values(current["id"])["status"] == "insufficient"
    at(11)
    assert service.last_values(current["id"])["source_set_id"] == future["set_uuid"]
