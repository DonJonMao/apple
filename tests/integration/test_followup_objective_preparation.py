"""Historical objective views do not decode today's discarded training rows."""
from datetime import datetime, timezone

import pytest

from healthzip.science import evaluate
from healthzip.training import current
from healthzip.training.service import TrainingError, TrainingService
from tests.integration.test_current_training_flow import current_advice, finish, fixture


def without_clocks(value):
    if isinstance(value, dict):
        return {key: without_clocks(item) for key, item in value.items() if key != "computed_at"}
    if isinstance(value, list):
        return [without_clocks(item) for item in value]
    return value


def test_historical_comparison_uses_only_replay_and_equivalent_metrics(tmp_path, monkeypatch):
    repo, svc, instance, target, _ = fixture(tmp_path, monkeypatch)
    advice = current_advice(repo, instance["id"])
    completed = finish(svc, target, load=34, reps=12)
    svc.end_session(instance["session_id"])
    cutoff = datetime.now(timezone.utc).isoformat()
    svc.edit_set(completed["id"], {"reps": 3}, base_revision=completed["revision"])
    real_subset = current.evaluate_subset
    groups = []

    def verify_subset(ids, records, **kwargs):
        actual = real_subset(ids, records, **kwargs)
        expected = {mid: evaluate(mid, records, **kwargs) for mid in ids}
        assert without_clocks(actual) == without_clocks(expected)
        groups.append(tuple(ids))
        return actual

    with monkeypatch.context() as patch:
        patch.setattr(current, "evaluate_subset", verify_subset)
        patch.setattr(TrainingService, "get_session", lambda *a, **kw: pytest.fail("decoded today's session"))
        patch.setattr(TrainingService, "get_session_exercise", lambda *a, **kw: pytest.fail("decoded today's sets"))
        result = current.objective_comparison(repo, instance["id"], cutoff_time=cutoff)
    assert result["rows"][0]["actual"]["reps"] == 12
    assert result["rows"][0]["advice_id"] == advice["advice_id"]
    assert ("STR-01", "STR-02", "STR-03", "STR-09", "STR-10") in groups
    assert ("STR-12", "STR-13", "STR-14") in groups
    assert current.objective_comparison(repo, instance["id"], cutoff_time=cutoff) == result
    assert svc.get_set(completed["id"])["reps"] == 3
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


def test_historical_parent_lookup_keeps_workspace_user_scope(tmp_path, monkeypatch):
    repo, _, instance, _, _ = fixture(tmp_path, monkeypatch)
    cutoff = datetime.now(timezone.utc).isoformat()
    repo.conn.execute("UPDATE training_session_exercise SET user_id='other' WHERE id=?", (instance["id"],))
    repo.conn.commit()
    with pytest.raises(TrainingError, match="找不到"):
        current.objective_comparison(repo, instance["id"], cutoff_time=cutoff)
    assert repo.one("SELECT count(*) FROM training_objective_comparison")[0] == 0
    repo.close()
