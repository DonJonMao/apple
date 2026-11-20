"""Completed real retrieval survives storage bookkeeping but not revocation."""
from functools import partial

import pytest
from streamlit.testing.v1 import AppTest
from test_v15_source_observation_entry import BOUNDS, insert_samples, seed_evidence

from healthzip.analytics.workspaces import analyze_workspace
from healthzip.db.repository import Repository
from healthzip.knowledge import KnowledgeWorkbench
from healthzip.ui import health_explanation


def _view(path):
    repo = Repository(path)
    try:
        insert_samples(repo)
        return analyze_workspace(repo, "有氧", cutoff_time=BOUNDS["cutoff_time"],
                                 timezone_name="UTC")
    finally:
        repo.close()


def _app(root, view):
    app = AppTest.from_string("""import streamlit as st
from healthzip.ui.health_explanation import render_health_explanation
render_health_explanation(st.session_state["view"], workspace="synthetic-workspace",
    context={"population": "adults", "measurement_protocol": "synthetic"},
    allow_network=False, root=st.session_state["knowledge"])
""")
    app.session_state["view"] = view
    app.session_state["knowledge"] = str(root)
    return app.run()


def _request(app):
    app.button(key="health_explanation_run").click().run()
    assert not app.exception
    state = app.session_state.to_dict()
    request = next(value for key, value in state.items()
                   if key.startswith("health_explanation_job_") and not key.endswith(":requested"))
    result = health_explanation._JOBS[request["key"]][1].result(timeout=10)
    assert result["status"] == "ready"
    assert result["items"][0]["evidence_context"]["capability_permissions"]["source_explanation"]
    return result


@pytest.mark.parametrize("journal", ["DELETE", "WAL"])
def test_success_survives_worker_close_and_other_retrieval_audit(tmp_path, monkeypatch, journal):
    root = tmp_path / "knowledge"
    kb = KnowledgeWorkbench(root, environment_kind="synthetic_test")
    seed_evidence(kb, "OBS-VO2-REPORTED")
    for connection in (kb.lib.sources, kb.lib.theories):
        connection.execute("PRAGMA journal_mode=" + journal)
    kb.close()
    monkeypatch.setattr("healthzip.knowledge.KnowledgeWorkbench",
                        partial(KnowledgeWorkbench, environment_kind="synthetic_test"))
    view = _view(tmp_path / "synthetic.sqlite3")
    app = _app(root, view)
    result = _request(app)
    token = health_explanation.knowledge_clock(root)
    assert result["knowledge_clock"] == token
    app.run()
    assert any("Synthetic observation scope only." in row.value for row in app.markdown)
    # Another request commits a retrieval audit. It is not a source/review edit.
    second = health_explanation._reviewed_explanation(view["workspace_scope"]["metrics"],
        {"population": "adults", "measurement_protocol": "synthetic"}, False, root)
    assert second["items"][0]["evidence_context"]["capability_permissions"]["source_explanation"]
    assert health_explanation.knowledge_clock(root) == token
    app.run()
    assert not app.exception
    assert any("Synthetic observation scope only." in row.value for row in app.markdown)
    assert not any("依据已有更新" in row.value for row in app.caption)


def test_real_claim_revocation_hides_old_result_and_rechecks_permission(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    kb = KnowledgeWorkbench(root, environment_kind="synthetic_test")
    seed_evidence(kb, "OBS-VO2-REPORTED")
    kb.close()
    monkeypatch.setattr("healthzip.knowledge.KnowledgeWorkbench",
                        partial(KnowledgeWorkbench, environment_kind="synthetic_test"))
    app = _app(root, _view(tmp_path / "synthetic.sqlite3"))
    _request(app)
    app.run()
    assert any("Synthetic observation scope only." in row.value for row in app.markdown)
    old = health_explanation.knowledge_clock(root)
    kb = KnowledgeWorkbench(root, environment_kind="synthetic_test")
    kb.core_state("claim", "OBS-VO2-REPORTED", "1", "revoked",
                  actor="Synthetic test", rationale="Synthetic withdrawal")
    kb.close()
    assert health_explanation.knowledge_clock(root) != old
    app.run()
    assert not any("Synthetic observation scope only." in row.value for row in app.markdown)
    assert any("依据已有更新" in row.value for row in app.caption)
    app.button(key="health_explanation_run").click().run()
    selected = next(value for key, value in app.session_state.items()
                    if key.startswith("health_explanation_job_") and not key.endswith(":requested"))
    refreshed = health_explanation._JOBS[selected["key"]][1].result(timeout=10)
    assert refreshed["items"][0]["evidence_context"]["capability_permissions"]["source_explanation"] is False
    app.run()
    assert not app.exception
    assert not any("Synthetic observation scope only." in row.value for row in app.markdown)
