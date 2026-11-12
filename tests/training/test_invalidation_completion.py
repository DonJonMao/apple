"""Complete only the pending invalidations covered by one analysis receipt."""

import pytest

from healthzip.db.repository import Repository
from healthzip.training import TrainingService
from healthzip.training.schema import migrate_training


@pytest.fixture
def invalidations(tmp_path):
    repo = Repository(tmp_path / "synthetic-invalidation-completion.sqlite3")
    service = TrainingService(repo)
    service.start_session("Synthetic previously analyzed session")
    old_id = service.pending_invalidations()[-1]["id"]
    service.mark_recomputed("synthetic-old-analysis", old_id)
    other = TrainingService(repo, user_id="synthetic-other-user")
    other.start_session("Synthetic other user's session")
    other_id = other.pending_invalidations()[-1]["id"]
    service.start_session("Synthetic pending session")
    through_id = service.pending_invalidations()[-1]["id"]
    service.start_session("Synthetic later pending session")
    later_id = service.pending_invalidations()[-1]["id"]
    yield service, old_id, other_id, through_id, later_id
    repo.close()


def rows(service):
    return {row["id"]: dict(row) for row in service.conn.execute("SELECT * FROM training_invalidation ORDER BY id")}


def test_completion_preserves_old_receipts_other_users_and_later_pending(invalidations):
    service, old_id, other_id, through_id, later_id = invalidations
    before = rows(service)
    changes_before = service.conn.total_changes
    service.mark_recomputed("synthetic-current-analysis", through_id)
    after = rows(service)
    assert after[old_id] == before[old_id], "Completed historical analysis versions must not be rewritten"
    assert after[other_id] == before[other_id]
    assert after[later_id] == before[later_id]
    assert after[through_id] == {**before[through_id], "status": "recomputed", "analysis_version": "synthetic-current-analysis"}
    assert service.conn.total_changes - changes_before == 1
    assert [row["id"] for row in service.pending_invalidations()] == [later_id]


def test_repeating_completion_does_not_write_completed_history(invalidations):
    service, _, _, through_id, _ = invalidations
    service.mark_recomputed("synthetic-first-receipt", through_id)
    before = rows(service)
    changes_before = service.conn.total_changes
    service.mark_recomputed("synthetic-later-analysis", through_id)
    assert rows(service) == before
    assert service.conn.total_changes == changes_before


def test_pending_index_upgrade_preserves_rows_and_serves_read_and_completion(invalidations):
    service, _, _, through_id, _ = invalidations
    service.conn.execute("DROP INDEX IF EXISTS training_invalidation_pending")
    before = rows(service)
    migrate_training(service.conn)
    assert rows(service) == before
    statements = [
        ("SELECT * FROM training_invalidation WHERE user_id=? AND status='pending' ORDER BY id", (service.user_id,)),
        ("UPDATE training_invalidation SET status='recomputed',analysis_version=? "
         "WHERE user_id=? AND status='pending' AND id<=?", ("synthetic-new", service.user_id, through_id)),
    ]
    for sql, arguments in statements:
        plan = [row[3] for row in service.conn.execute("EXPLAIN QUERY PLAN " + sql, arguments)]
        assert any("training_invalidation_pending" in detail for detail in plan), plan
    migrate_training(service.conn)
    assert rows(service) == before


def test_completion_participates_in_the_callers_transaction(invalidations):
    service, _, _, through_id, _ = invalidations
    before = rows(service)
    with pytest.raises(RuntimeError, match="synthetic outer rollback"):
        with service._transaction():
            service.mark_recomputed("synthetic-rolled-back-analysis", through_id)
            assert rows(service)[through_id]["status"] == "recomputed"
            raise RuntimeError("synthetic outer rollback")
    assert rows(service) == before
