"""Repository-backed prerequisites reach actual retrieval and current revocation."""
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_v15_retrieval import add

from healthzip.db.repository import Repository
from healthzip.knowledge import KnowledgeWorkbench, metric_retrieval
from healthzip.training.service import TrainingService
from healthzip.workflows import (
    WorkflowRequest,
    check_current_use,
    load_run,
    run_workflow,
    save_context,
)


@pytest.mark.parametrize("scale,timing,expected", [
    ("Foster_modified_CR10", "after", True), ("cr10", "after", False),
    ("Foster_modified_CR10", None, False), ("Foster_modified_CR10", "before", False),
])
def test_saved_session_prerequisites_and_revocation(kb, tmp_path, monkeypatch, scale, timing, expected):
    import healthzip.knowledge
    conditions = [{"field": key, "op": "eq", "value": value, "origin": "measurement_contract"}
        for key, value in (("srpe_scale", "Foster_modified_CR10"), ("srpe_collection", "retrospective_after_session"))]
    add(kb, identity="session-scope", mid="LOAD-SRPE-AU", assigned=["recovery"], conditions=conditions)
    metric_retrieval.freeze_index(kb, "synthetic-workflow")
    # This override exists solely inside the isolated synthetic test. The normal
    # workflow has no client switch that can declare a production review valid.
    monkeypatch.setattr(healthzip.knowledge, "KnowledgeWorkbench", lambda root: KnowledgeWorkbench(root, environment_kind="synthetic_test"))
    repo = Repository(tmp_path / "private.sqlite3")
    svc = TrainingService(repo)
    end = datetime.now(timezone.utc) - timedelta(hours=1)
    session = svc.start_session("PRIVATE-NOTE-DO-NOT-QUERY", started_at=(end-timedelta(minutes=50)).isoformat())
    collected = (end + timedelta(minutes=15 if timing == "after" else -15)).isoformat() if timing else None
    svc.end_session(session["id"], ended_at=end.isoformat(), session_rpe=6, rpe_scale=scale,
        rpe_collected_at=collected, duration_seconds=3000, duration_protocol="user_elapsed_including_rest")
    context_id = save_context(repo, {"population": "adults"})
    request = WorkflowRequest("W2", context_id=context_id, release_id="synthetic-workflow")
    run = run_workflow(repo, request, knowledge_root=kb.root)
    query = next(q for q in run["knowledge"]["queries"] if q["metric_id"] == "LOAD-SRPE-AU")
    assert query.get("permissions", {}).get("source_explanation") is expected, query
    assert query["permissions"]["candidate"] is False
    assert query["audit"]["private_context_sent"] is False
    assert query["audit"]["personal_metric_values_sent"] is False
    assert query["audit"]["query_form"]["form_id"] == "en"
    assert len(run["knowledge"]["queries"]) <= 2
    assert "PRIVATE-NOTE-DO-NOT-QUERY" not in json.dumps(run["knowledge"])
    assert any(f["metric_id"] == "LOAD-SRPE-AU" for f in run["facts"])
    if expected:
        kb.core_state("claim", "session-scope", "1", "revoked", actor="Synthetic", rationale="Synthetic revoked dependency")
        decision = check_current_use(repo, run["run_id"], knowledge_root=kb.root)
        assert "source_use_dependencies_changed" in decision["reason_codes"]
        assert load_run(repo, run["run_id"]) == run
    repo.close()


@pytest.mark.parametrize("metric_id,canonical", [("STATE-RHR", "resting_heart_rate_bpm"), ("STATE-SDNN", "hrv_sdnn_ms")])
def test_selected_longitudinal_outcome_uses_its_own_source_and_current_check(kb, tmp_path, monkeypatch, metric_id, canonical):
    import healthzip.knowledge
    from healthzip.knowledge.domains import configuration
    from healthzip.workflows import load_analysis
    helpers = runpy.run_path(str(Path(__file__).parents[1] / "integration/test_analysis_observation_flows.py"))
    profile = configuration()["profiles"][metric_id]
    add(kb, identity="selected-outcome", mid=metric_id, assigned=profile["required_domains"],
        text="Synthetic software fixture: resting heart rate RHR and SDNN measurement protocol uncertainty and scope limitations; no individual recovery or candidate authority.")
    metric_retrieval.freeze_index(kb, "selected-outcome-release")
    monkeypatch.setattr(healthzip.knowledge, "KnowledgeWorkbench", lambda root: KnowledgeWorkbench(root, environment_kind="synthetic_test"))
    repo = Repository(tmp_path / "selected.sqlite3")
    bid = helpers["batch"](repo)
    now = datetime.now(timezone.utc)
    for days, value in ((4, 60), (2, 62)):
        helpers["sample"](repo, bid, str(days), canonical, value, (now-timedelta(days=days)).isoformat())
    repo.conn.commit()
    context_id = save_context(repo, {"population": "adults"})
    run = run_workflow(repo, WorkflowRequest("W4", result_metric_id=metric_id, context_id=context_id, release_id="selected-outcome-release"), knowledge_root=kb.root)
    assert [q["metric_id"] for q in run["knowledge"]["queries"]] == [metric_id]
    query = run["knowledge"]["queries"][0]
    assert query["permissions"]["source_explanation"] is True, json.dumps(query, ensure_ascii=False)
    assert query["permissions"]["candidate"] is False
    assert query["audit"]["retrieval_degraded"] is False
    metric = load_analysis(repo, run["run_id"])["metrics"][metric_id]
    assert [p["value"] for points in metric["value"].values() for p in points] == [60, 62]
    assert check_current_use(repo, run["run_id"], knowledge_root=kb.root)["status"] == "current"
    kb.core_state("claim", "selected-outcome", "1", "revoked", actor="Synthetic", rationale="Synthetic revocation")
    assert "source_use_dependencies_changed" in check_current_use(repo, run["run_id"], knowledge_root=kb.root)["reason_codes"]
    assert load_run(repo, run["run_id"]) == run
    repo.close()
