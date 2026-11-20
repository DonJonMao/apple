"""Equal factual metrics cannot share private request state across workspaces."""
import time

from streamlit.testing.v1 import AppTest

from healthzip.ui.health_explanation import job_result


def _app(root, workspace):
    app = AppTest.from_string("""
import streamlit as st
from healthzip.ui.health_explanation import render_metric_request
render_metric_request({"metric_id": "BODY-MASS-DAILY", "value": None},
    task="explain_metric", context={}, mode="lexical", candidate_scope="reviewed_metric",
    allow_network=False, key="metric_evidence_job", root=st.session_state["library"],
    workspace=st.session_state["workspace"])
""")
    app.session_state["library"] = str(root)
    app.session_state["workspace"] = workspace
    return app.run()


def _request(app):
    app.button(key="metric_evidence_run").click().run()
    assert not app.exception
    key = app.session_state["metric_evidence_job"]["key"]
    deadline = time.monotonic() + 3
    while job_result(key)["status"] == "pending" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert job_result(key)["status"] == "ready"
    app.run()
    assert any("尚未配置本地知识库" in row.value for row in app.caption)
    return key


def test_switch_workspace_does_not_reuse_equal_metric_request(tmp_path):
    app = _app(tmp_path / "missing-library", str(tmp_path / "a.sqlite3"))
    first = _request(app)
    app.session_state["workspace"] = str(tmp_path / "b.sqlite3")
    app.run()
    assert not app.exception
    assert not any("尚未配置本地知识库" in row.value for row in app.caption)
    assert any("已改变" in row.value for row in app.caption)
    assert _request(app) != first


def test_standalone_metric_requests_are_isolated_between_browser_sessions(tmp_path):
    first = _request(_app(tmp_path / "missing-library", None))
    second = _request(_app(tmp_path / "missing-library", None))
    assert second != first
