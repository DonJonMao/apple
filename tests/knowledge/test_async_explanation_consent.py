"""Real retrieval and loopback HTTP prove settings withdrawal prevents sending."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import pytest
from streamlit.testing.v1 import AppTest
from test_v15_source_observation_entry import seed_evidence

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.ui import health_explanation


@pytest.fixture
def synthetic_model(monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            cards = json.loads(payload["messages"][1]["content"])
            card = next(item for item in cards if item.get("allowed_actions"))
            content = {"summary": card["summary"], "evidence_ids": [card["id"]],
                "limitations": [], "allowed_actions": card["allowed_actions"]}
            body = json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HEALTHZIP_AI_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("HEALTHZIP_AI_MODEL", "synthetic-loopback")
    monkeypatch.setenv("HEALTHZIP_AI_API_KEY", "synthetic-not-a-secret")
    try:
        yield requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("withdrawal", ["none", "revoke", "revoke_then_allow"])
def test_settings_withdrawal_during_real_retrieval_prevents_first_model_request(
        kb, tmp_path, monkeypatch, synthetic_model, withdrawal):
    seed_evidence(kb, "OBS-VO2-REPORTED")
    entered, release = Event(), Event()
    original = KnowledgeWorkbench.retrieve_for_metric

    def delayed_retrieval(self, *args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(KnowledgeWorkbench, "retrieve_for_metric", delayed_retrieval)
    monkeypatch.setattr("healthzip.knowledge.KnowledgeWorkbench",
        lambda root: KnowledgeWorkbench(root, environment_kind="synthetic_test"))
    app = AppTest.from_string(f'''import streamlit as st
from healthzip.ui.settings_page import render_settings
from healthzip.ui.health_explanation import render_metric_request
from healthzip.science.observations import evaluate
st.session_state.setdefault("database_path", {str(tmp_path / 'synthetic.sqlite3')!r})
st.session_state.setdefault("health_explanation_network_consent", True)
render_settings()
metric = evaluate("OBS-VO2-REPORTED", [], cutoff_time="2026-11-17T00:00:00+00:00",
    window_start="2026-11-01T00:00:00+00:00", window_end="2026-11-17T00:00:00+00:00")
render_metric_request(metric, task="cardiorespiratory", context={{"population":"adults", "measurement_protocol":"synthetic"}},
    mode="lexical", candidate_scope="reviewed_metric", allow_network=st.session_state["health_explanation_network_consent"],
    key="synthetic_consent_job", root={str(kb.root)!r}, workspace=st.session_state["database_path"])
''').run(timeout=30)
    assert not app.exception
    app.button(key="metric_evidence_run").click().run(timeout=30)
    assert not app.exception and entered.wait(2)
    request = app.session_state["synthetic_consent_job"]
    future = health_explanation._JOBS[request["key"]][1]
    try:
        assert synthetic_model == []
        if withdrawal != "none":
            app.checkbox(key="_setting_network_consent").uncheck().run(timeout=30)
            assert not app.exception
            if withdrawal == "revoke_then_allow":
                app.checkbox(key="_setting_network_consent").check().run(timeout=30)
                assert not app.exception
    finally:
        release.set()
    result = future.result(timeout=15)
    assert result["items"][0]["evidence_context"]["capability_permissions"]["source_explanation"]
    if withdrawal == "none":
        assert synthetic_model, "Positive control must actually reach the loopback model."
        assert result["items"][0]["explanation"]["source"] == "ai"
    else:
        assert synthetic_model == []
        assert result["items"][0]["explanation"]["source"] == "local_fallback"
