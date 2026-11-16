"""The actual page must collect the protocol needed by its reviewed evidence."""

import json

from streamlit.testing.v1 import AppTest

from healthzip.knowledge import KnowledgeWorkbench, domains, vector_index
from healthzip.ui import metric_evidence


def test_session_rpe_page_keeps_unknown_scope_and_accepts_explicit_recorded_protocol(kb, monkeypatch):
    kb.lib.seed({"sources": [{"source_id": "ui-fixture", "canonical_url": "https://example.invalid/srpe-ui",
                              "title": "Synthetic session-RPE source", "corpus_roles": ["research"]}]}, {"cards": []})
    vid = kb.lib.record_version("ui-fixture", b"synthetic page contract", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": domains.configuration()["profiles"]["LOAD-SRPE"]["query"], "locator": {"page": 1}}], "fixture")
    sid = vid + ":s00000"
    review = {"reviewer": "UI synthetic fixture", "reviewer_kind": "synthetic_fixture", "reviewed_at": "2026-11-17",
              "rationale": "Synthetic UI contract only", "content_checked": True, "application_checked": True}
    conditions = [{"field": field, "op": "eq", "value": value, "origin": "measurement_contract"}
        for field, value in [("population", "adult_athletes"), ("srpe_scale", "Foster_modified_CR10"),
                             ("srpe_collection", "retrospective_after_session")]]
    kb.review_claim({"claim_id": "ui-srpe", "version": "1", "statement": "Synthetic whole-session explanation.",
        "scope": {"fixture": True}, "limitations": ["Synthetic only"], "conditions": conditions,
        "evidence_links": [{"source_id": "ui-fixture", "source_version_id": vid, "span_ids": [sid]}]}, review)
    vector_index.register_spans(kb, vid, ["recovery"], assignment_status="content_checked")
    domains.link(kb, origin={"type": "claim", "id": "ui-srpe", "version": "1"}, relation="defines",
        target={"type": "metric", "id": "LOAD-SRPE", "version": "metric-domains-1.5.0"}, span_ids=[sid],
        applicability={}, actor="Synthetic UI", rationale="Synthetic source binding",
        evidence_types=domains.configuration()["profiles"]["LOAD-SRPE"]["required_evidence_types"], review=review)
    monkeypatch.setattr(metric_evidence, "KnowledgeWorkbench",
                        lambda root: KnowledgeWorkbench(kb.root, environment_kind="synthetic_test"))
    app = AppTest.from_string('''from healthzip.science import evaluate
from healthzip.ui.metric_evidence import render_metric_evidence
metric = evaluate("LOAD-SRPE", [], cutoff_time="2026-11-17T00:00:00+00:00",
    window_start="2026-11-01T00:00:00+00:00", window_end="2026-11-17T00:00:00+00:00")
render_metric_evidence({"LOAD-SRPE": metric})
''').run(timeout=30)
    app.selectbox(key="metric_evidence_function").select("recovery").run()
    app.button(key="metric_evidence_run").click().run()
    assert not app.exception
    assert json.loads(app.json[-1].value)["permissions"]["source_explanation"] is False
    app.selectbox(key="metric_evidence_population").select("adult_athletes")
    app.text_input(key="metric_evidence_protocol").input("Synthetic recorded same protocol")
    app.selectbox(key="metric_evidence_srpe_scale").select("Foster_modified_CR10")
    app.selectbox(key="metric_evidence_srpe_collection").select("retrospective_after_session")
    app.button(key="metric_evidence_run").click().run()
    assert not app.exception
    assert json.loads(app.json[-1].value)["permissions"]["source_explanation"] is True
