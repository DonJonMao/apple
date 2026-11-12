"""Session details stay local while additive indexes preserve existing records."""

import pytest

from healthzip.db.repository import Repository
from healthzip.training import TrainingError, TrainingService
from healthzip.training.schema import migrate_training

INDEX_NAMES = {
    "idx_training_set_session_exercise",
    "idx_training_set_session",
    "idx_training_exercise_session",
}
EXERCISE = "psa.ex.barbell_bench_press"


@pytest.fixture
def service(tmp_path):
    repo = Repository(tmp_path / "synthetic-session-details.sqlite3")
    yield TrainingService(repo)
    repo.close()


def populated_session(service, name="Synthetic session"):
    template = service.create_template(name, [{
        "exercise_id": EXERCISE,
        "condition": {},
        "targets": {"sets": [{"reps_min": 6, "reps_max": 8}]},
    }])
    session = service.start_session(name, template_id=template["id"])
    return session, session["exercises"][0]


def raw_rows(conn):
    tables = (
        "strength_session", "training_session_exercise", "strength_set",
        "training_template", "training_template_version", "training_event",
        "training_invalidation", "schema_meta",
    )
    result = {
        table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in tables
    }
    result["training_event_set_candidate"] = [tuple(row) for row in conn.execute(
        "SELECT * FROM training_event_set_candidate ORDER BY event_id,slot"
    )]
    return result


def installed_indexes(conn):
    return INDEX_NAMES.intersection(row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ))


def drop_indexes(conn):
    for name in INDEX_NAMES:
        conn.execute("DROP INDEX IF EXISTS " + name)
    conn.commit()


def measured_steps(conn, operation):
    steps = 0

    def progress():
        nonlocal steps
        steps += 1
        return 0

    conn.set_progress_handler(progress, 1)
    try:
        result = operation()
    finally:
        conn.set_progress_handler(None, 0)
    return result, steps


def test_current_database_upgrade_is_atomic_idempotent_and_preserves_raw_rows(service):
    session, instance = populated_session(service)
    service.add_set(instance["id"], {"reps": 7}, planned={"reps_min": 5})
    before_detail = service.get_session(session["id"])
    drop_indexes(service.conn)
    markers = dict(service.conn.execute(
        "SELECT key,value FROM schema_meta WHERE key IN "
        "('training_event_query_projection','training_last_values_projection')"
    ))
    assert markers == {
        "training_event_query_projection": "1", "training_last_values_projection": "1",
    }
    before = raw_rows(service.conn)

    def interrupted(stage):
        if stage == "complete":
            raise RuntimeError("synthetic session-index interruption")

    with pytest.raises(RuntimeError, match="synthetic session-index interruption"):
        migrate_training(service.conn, checkpoint=interrupted)
    assert installed_indexes(service.conn) == set()
    assert raw_rows(service.conn) == before

    for _ in range(2):
        migrate_training(service.conn)
        assert installed_indexes(service.conn) == INDEX_NAMES
        assert raw_rows(service.conn) == before
        assert service.get_session(session["id"]) == before_detail


def test_session_indexes_participate_in_the_callers_transaction(service):
    populated_session(service)
    drop_indexes(service.conn)
    before = raw_rows(service.conn)
    service.conn.execute("BEGIN")
    migrate_training(service.conn)
    assert installed_indexes(service.conn) == INDEX_NAMES
    service.conn.rollback()
    assert installed_indexes(service.conn) == set()
    assert raw_rows(service.conn) == before


def test_service_detail_reads_do_not_scan_unrelated_sessions(service):
    session, instance = populated_session(service)
    service.add_set(instance["id"], {"set_number": 3})
    reads = (
        lambda: service.get_session(session["id"]),
        lambda: service.get_session_exercise(instance["id"]),
        lambda: service.current_targets(instance["id"]),
    )
    before = [measured_steps(service.conn, read) for read in reads]
    for number in range(120):
        unrelated = service.start_session(f"Synthetic unrelated {number}")
        other_instance = service.add_exercise(unrelated["id"], EXERCISE, {})
        service.add_set(other_instance["id"], {})
    for read, (expected, initial_steps) in zip(reads, before):
        result, steps = measured_steps(service.conn, read)
        assert result == expected
        assert steps <= initial_steps + 200, {"before": initial_steps, "after": steps}
    assert service.count_sessions() == 121
    assert service.conn.execute("SELECT COUNT(*) FROM strength_set").fetchone()[0] == 122


def test_session_and_exercise_order_and_user_scope_survive_upgrade(service):
    session = service.start_session("Synthetic ordered session")
    instances = [service.add_exercise(session["id"], EXERCISE, {}, position=position,
        session_exercise_id=identity) for identity, position in (
            ("synthetic-z", 2), ("synthetic-b", 1), ("synthetic-a", 1),
        )]
    added = [service.add_set(instances[0]["id"], {"set_number": number})
             for number in (3, 1, 1)]
    other = TrainingService(service.repo, user_id="synthetic-other")
    other_session, other_instance = populated_session(other, "Synthetic other user")
    other.add_set(other_instance["id"], {"set_number": 1})
    drop_indexes(service.conn)
    before = service.get_session(session["id"])
    expected_sets = [added[1]["id"], added[2]["id"], added[0]["id"]]
    assert [row["id"] for row in before["exercises"]] == [
        "synthetic-a", "synthetic-b", "synthetic-z",
    ]
    assert [row["id"] for row in before["sets"]] == expected_sets
    migrate_training(service.conn)
    assert service.get_session(session["id"]) == before
    assert [row["id"] for row in service.get_session_exercise(instances[0]["id"])["sets"]] == expected_sets
    for owner, foreign_session, foreign_instance in (
        (service, other_session, other_instance), (other, session, instances[0]),
    ):
        with pytest.raises(TrainingError):
            owner.get_session(foreign_session["id"])
        with pytest.raises(TrainingError):
            owner.get_session_exercise(foreign_instance["id"])


def test_equal_start_rest_predecessor_is_unchanged_after_session_index_upgrade(service):
    drop_indexes(service.conn)
    session = service.start_session("Synthetic simultaneous starts")
    instance = service.add_exercise(session["id"], EXERCISE, {})
    first = service.add_set(instance["id"], {
        "completion_state": "completed", "reps": 8, "set_number": 2,
        "started_at": "2026-01-01T10:00:00+00:00",
        "ended_at": "2026-01-01T10:01:00+00:00",
    })
    service.add_set(instance["id"], {
        "completion_state": "completed", "reps": 8, "set_number": 1,
        "started_at": "2026-01-01T10:00:00+00:00",
        "ended_at": "2026-01-01T10:02:00+00:00",
    })
    last = service.add_set(instance["id"], {
        "completion_state": "completed", "reps": 8, "set_number": 3,
        "started_at": "2026-01-01T10:03:00+00:00",
        "ended_at": "2026-01-01T10:04:00+00:00",
    })
    before = service.get_set(last["id"])
    assert before["rest_actual_s"] == 120
    assert before["rest_derivation"]["previous_set_uuid"] == first["set_uuid"]
    previous_event = service.conn.execute("SELECT MAX(rowid) FROM training_event").fetchone()[0]
    migrate_training(service.conn)
    # Adding a draft invokes the real rest recomputation without changing endpoints.
    service.add_set(instance["id"], {"set_number": 4})
    assert service.get_set(last["id"]) == before
    assert [row[0] for row in service.conn.execute(
        "SELECT action FROM training_event WHERE rowid>? ORDER BY rowid", (previous_event,)
    )] == ["add_set"]
