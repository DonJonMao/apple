"""The training history's latest thirty audit rows use a bounded index prefix."""

from datetime import datetime, timedelta, timezone

import pytest

from healthzip.db.repository import Repository
from healthzip.training import TrainingService
from healthzip.training import service as service_module
from healthzip.training.schema import migrate_training
from healthzip.training.semantics import timestamp

RECENT_SQL = "SELECT * FROM training_event WHERE user_id=? ORDER BY recorded_at DESC LIMIT 30"


@pytest.fixture
def event_history(tmp_path, monkeypatch):
    clock = [datetime(2020, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(service_module, "timestamp", lambda value=None:
        timestamp(value) if value is not None else clock[0].isoformat())
    repo = Repository(tmp_path / "synthetic-recent-events.sqlite3")
    services = [TrainingService(repo, user_id=user) for user in ("local", "synthetic-other")]
    for number in range(600):
        for offset, service in enumerate(services):
            clock[0] = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=number * 2 + offset)
            service.create_equipment("Synthetic recent audit station", "barbell",
                equipment_id=f"synthetic-equipment-{offset}-{number}",
                event_id=f"synthetic-event-{offset}-{number}")
    yield repo
    repo.close()


def event_bytes(repo):
    return [tuple(row) for row in repo.conn.execute("SELECT * FROM training_event ORDER BY rowid")]


def test_recent_query_preserves_exact_results_for_distinct_timestamps(event_history):
    repo = event_history
    before = event_bytes(repo)
    original = [dict(row) for row in repo.conn.execute("SELECT * FROM training_event")]
    for user in ("local", "synthetic-other"):
        expected = sorted((row for row in original if row["user_id"] == user),
            key=lambda row: row["recorded_at"], reverse=True)[:30]
        assert [dict(row) for row in repo.conn.execute(RECENT_SQL, (user,))] == expected
    assert event_bytes(repo) == before


def test_recent_query_uses_index_prefix_without_full_history_sort(event_history):
    repo = event_history
    steps = 0

    def progress():
        nonlocal steps
        steps += 1
        return 0

    repo.conn.set_progress_handler(progress, 1)
    try:
        rows = list(repo.conn.execute(RECENT_SQL, ("local",)))
    finally:
        repo.conn.set_progress_handler(None, 0)
    plan = [row[3] for row in repo.conn.execute("EXPLAIN QUERY PLAN " + RECENT_SQL, ("local",))]
    assert len(rows) == 30
    assert steps < 2000, {"vm_steps": steps, "query_plan": plan}
    assert any("training_event_recent" in detail for detail in plan), plan
    assert not any("TEMP B-TREE" in detail for detail in plan), plan


def test_recent_index_upgrade_is_atomic_and_preserves_original_event_bytes(event_history):
    repo = event_history
    repo.conn.execute("DROP INDEX IF EXISTS training_event_recent")
    before = event_bytes(repo)

    def interrupted(stage):
        if stage == "complete":
            raise RuntimeError("synthetic recent-index interruption")

    with pytest.raises(RuntimeError, match="synthetic recent-index interruption"):
        migrate_training(repo.conn, checkpoint=interrupted)
    assert not repo.conn.execute("SELECT 1 FROM sqlite_master WHERE name='training_event_recent'").fetchone()
    assert event_bytes(repo) == before
    migrate_training(repo.conn)
    assert repo.conn.execute("SELECT 1 FROM sqlite_master WHERE name='training_event_recent'").fetchone()
    assert event_bytes(repo) == before
    migrate_training(repo.conn)
    assert event_bytes(repo) == before


def test_equal_timestamp_boundary_preserves_the_declared_order_and_user_scope(event_history):
    repo = event_history
    tied_ids = {f"synthetic-event-0-{number}" for number in range(560, 600)}
    repo.conn.executemany("UPDATE training_event SET recorded_at=? WHERE event_id=?",
        [("2026-01-01T00:00:00+00:00", identity) for identity in tied_ids])
    repo.conn.execute("UPDATE training_event SET recorded_at=? WHERE user_id=?",
        ("2027-01-01T00:00:00+00:00", "synthetic-other"))
    rows = list(repo.conn.execute(RECENT_SQL, ("local",)))
    assert len(rows) == len({row["event_id"] for row in rows}) == 30
    assert {row["event_id"] for row in rows} <= tied_ids
    assert {row["user_id"] for row in rows} == {"local"}
    assert {row["recorded_at"] for row in rows} == {"2026-01-01T00:00:00+00:00"}
    # This SQL never declared a tie breaker; no particular tied UUID subset is
    # promised by the performance-only index change.
