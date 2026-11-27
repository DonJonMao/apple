"""Real claim/edge paths, complete answer evidence and immutable historical uses."""

import json
from copy import deepcopy

import pytest

from healthzip.knowledge import KnowledgeWorkbench, domains, topics, vector_index
from healthzip.knowledge.revisions import knowledge_authority_clock, prepare_retrieval_revisions
from healthzip.workflows.period_report import render_report
from healthzip.workflows.reports import current_report_source_status

REVIEW = {"reviewer": "Synthetic followup evidence scenario", "reviewer_kind": "synthetic_fixture",
          "reviewed_at": "2026-09-15", "rationale": "Software scenario, not scientific authority",
          "content_checked": True, "application_checked": True}


@pytest.fixture
def library(tmp_path, monkeypatch):
    original = KnowledgeWorkbench
    monkeypatch.setattr("healthzip.knowledge.KnowledgeWorkbench", lambda *a, **kw:
        original(*a, **{**kw, "environment_kind": "synthetic_test"}))
    kb = original(tmp_path / "kb", environment_kind="synthetic_test")
    yield kb
    kb.close()


def claim(kb, identity, purposes, *, version="1", topic="W4", conditions=None, bind=True):
    kb.lib.seed({"sources": [{"source_id": identity, "title": "Synthetic original " + identity,
        "canonical_url": "https://example.invalid/" + identity, "corpus_roles": ["research"]}]}, {"cards": []})
    text = topics.profile(topic)["query"] + " Synthetic original " + identity + " " + version
    vid = kb.lib.record_version(identity, text.encode(), "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": text, "section_path": "Independent methods", "locator": {"page": 4}}], "followup-fixture")
    sid = vid + ":s00000"
    kb.review_claim({"claim_id": identity, "version": version,
        "statement": "Synthetic applicable explanation " + identity + ".",
        "scope": {"explanation_purpose": "measurement_context"}, "conditions": conditions or [],
        "limitations": ["Only this synthetic protocol; not a clinical conclusion."],
        "evidence_links": [{"source_id": identity, "source_version_id": vid, "span_ids": [sid]}]}, REVIEW)
    vector_index.register_spans(kb, vid, ["wearable"], assignment_status="content_checked")
    if bind:
        domains.link(kb, origin={"type": "claim", "id": identity, "version": version}, relation="applies_to",
            target={"type": "metric", "id": topic, "version": domains.profile_version(topic)}, span_ids=[sid],
            applicability={}, actor="Synthetic", rationale="Exact tested topic use", evidence_types=purposes, review=REVIEW)
    prepare_retrieval_revisions(kb)
    return sid


def edge(kb, left, right, relation, spans, *, scope=None, left_version="1", right_version="1"):
    return domains.link(kb, origin={"type": "claim", "id": left, "version": left_version}, relation=relation,
        target={"type": "claim", "id": right, "version": right_version}, span_ids=spans,
        applicability=scope or {}, actor="Synthetic", rationale="Independent exact edge scenario")


def question(kb, *, context=None):
    return {"id": "W4", "title": "Synthetic actual followup", "report_status": "available",
            "observation": "Synthetic fact: 64 bpm with seven recorded days.", "steps": ["Check this recorded protocol."],
            "rows": [], "evidence": topics.question_sources(kb, "W4", context=context, include_evidence=True)}


def historical(q):
    return {"period": "week", "version": "synthetic-report", "analysis_run_id": "synthetic-facts",
            "questions": [q], "current": {"window_start": "2026-09-07T00:00:00Z",
        "cutoff_time": "2026-09-14T00:00:00Z", "timezone": "UTC", "strength_tasks": []}}


def statuses(kb, report):
    result = current_report_source_status(report, knowledge_root=kb.lib.root)
    return result, {i["claim_id"]: i for i in result["items"]}


def test_real_retrieval_third_action_and_all_orderings_reach_readable_body(library):
    claim(library, "method", ["measurement"])
    claim(library, "compare", ["comparison", "mechanism_or_exception"])
    action_span = claim(library, "action", ["action_or_reassessment"])
    q = question(library)
    assert {i["claim_id"] for i in q["evidence"]["items"]} == {"method", "compare", "action"}
    original = deepcopy(q)
    from itertools import permutations
    bodies = []
    for order in permutations(q["evidence"]["items"]):
        candidate = deepcopy(q)
        candidate["evidence"]["items"] = list(order)
        body = render_report(None, historical(candidate), runs=[])
        for item in order:
            assert item["statement"] in body
            assert item["limitations"][0] in body
            assert item["citations"][0]["url"] in body
        bodies.append(body)
    assert len(set(bodies)) == 1
    assert action_span in {s["span_id"] for s in q["evidence"]["evidence_spans"]}
    assert q == original


def test_repeated_claim_and_original_are_printed_once_without_discarding_other_actions(library):
    claim(library, "method", ["measurement", "comparison"])
    claim(library, "first-action", ["action_or_reassessment"])
    claim(library, "different-action", ["action_or_reassessment"])
    q = question(library)
    report = historical(q)
    report["questions"].append({**deepcopy(q), "id": "W2", "title": "Second answer using the same method"})
    body = render_report(None, report, runs=[])
    for item in q["evidence"]["items"]:
        assert body.count(item["statement"]) == 1
        assert body.count(item["citations"][0]["url"]) == 1
    assert "见前文说明" in body


def test_different_reviewed_uses_of_one_original_keep_statements_and_one_source_link(library):
    sid = claim(library, "original", ["measurement", "comparison"])
    payload = json.loads(library.lib.theories.execute(
        "SELECT payload_json FROM source_claim WHERE claim_id='original'").fetchone()[0])
    payload.update(claim_id="second-use", statement="Synthetic second action from the same original.")
    library.review_claim(payload, REVIEW)
    domains.link(library, origin={"type": "claim", "id": "second-use", "version": "1"}, relation="applies_to",
        target={"type": "metric", "id": "W4", "version": domains.profile_version("W4")}, span_ids=[sid],
        applicability={}, actor="Synthetic", rationale="Second independent reviewed use of the same original",
        evidence_types=["action_or_reassessment"], review=REVIEW)
    q = question(library)
    assert {i["claim_id"] for i in q["evidence"]["items"]} == {"original", "second-use"}
    body = render_report(None, historical(q), runs=[])
    assert body.count("https://example.invalid/original") == 1
    assert all(item["statement"] in body for item in q["evidence"]["items"])
    assert "- 原文：见来源〔1〕" in body


def test_new_exact_conflict_restricts_only_affected_frozen_claim_and_keeps_bytes(library):
    first = claim(library, "disputed", ["mechanism_or_exception"])
    other = claim(library, "counterclaim", [], bind=False)
    claim(library, "independent", ["measurement", "comparison"])
    report = historical(question(library))
    frozen = deepcopy(report)
    assert statuses(library, report)[0]["status"] == "current"
    before_clock = knowledge_authority_clock(library.lib.root)
    identity = edge(library, "disputed", "counterclaim", "conflicts_with", [first, other])
    assert knowledge_authority_clock(library.lib.root) != before_clock
    result, items = statuses(library, report)
    assert result["status"] == "restricted"
    assert items["disputed"]["status"] == "conflicted"
    assert items["disputed"]["conflicts"][0]["edge_id"] == identity
    assert items["independent"]["status"] == "verified"
    assert report == frozen


def test_new_conflict_on_required_premise_blocks_action_not_independent_method(library):
    premise = claim(library, "premise", [], bind=False)
    rival = claim(library, "rival", [], bind=False)
    action = claim(library, "action", ["action_or_reassessment"])
    claim(library, "independent", ["measurement", "comparison"])
    edge(library, "premise", "action", "required_by", [premise, action])
    report = historical(question(library))
    frozen = deepcopy(report)
    assert statuses(library, report)[0]["status"] == "current"
    edge(library, "premise", "rival", "conflicts_with", [premise, rival])
    result, items = statuses(library, report)
    assert result["status"] == "restricted"
    assert items["action"]["status"] == "dependent_restriction"
    assert items["action"]["dependencies"][0]["claim_id"] == "premise"
    assert items["action"]["dependencies"][0]["status"] == "conflicted"
    assert items["independent"]["status"] == "verified"
    assert report == frozen


@pytest.mark.parametrize("context, expected", [({"device": "A"}, "conflicted"),
    ({"device": "B"}, "verified"), ({}, "scope_unverified")])
def test_current_conflict_scope_uses_frozen_context_not_assumed_population(library, context, expected):
    a = claim(library, "method", ["measurement", "comparison"])
    b = claim(library, "rival", [], bind=False)
    report = historical(question(library, context=context))
    edge(library, "method", "rival", "conflicts_with", [a, b], scope={"device": "A"})
    _, items = statuses(library, report)
    assert items["method"]["status"] == expected
    assert items["method"]["applicability_context"] == context


def test_conflict_on_another_version_does_not_restrict_the_frozen_version(library):
    claim(library, "method", ["measurement", "comparison"])
    report = historical(question(library))
    newer = claim(library, "method", [], version="2", bind=False)
    rival = claim(library, "rival", [], bind=False)
    edge(library, "method", "rival", "conflicts_with", [newer, rival], left_version="2")
    assert statuses(library, report)[0]["status"] == "current"


def test_unreachable_acquisition_is_not_withdrawal_but_missing_version_is_unknown(library):
    claim(library, "method", ["measurement", "comparison"])
    report = historical(question(library))
    with library.lib.sources:
        library.lib.sources.execute("UPDATE source SET acquisition_state='temporarily_unavailable' WHERE source_id='method'")
    assert statuses(library, report)[0]["status"] == "current"
    report["questions"][0]["evidence"] = {"items": [{"claim_id": "not-in-current-library", "version": "old"}]}
    _, items = statuses(library, report)
    assert items["not-in-current-library"]["status"] == "missing"
    assert "撤销" not in items["not-in-current-library"]["label"]


def test_unavailable_service_does_not_claim_current_or_withdrawn(library, monkeypatch):
    import sqlite3
    claim(library, "method", ["measurement", "comparison"])
    report = historical(question(library))
    frozen = json.dumps(report, sort_keys=True)
    def unavailable(*_args, **_kwargs):
        raise sqlite3.OperationalError("Synthetic service outage")
    monkeypatch.setattr("healthzip.knowledge.KnowledgeWorkbench", unavailable)
    result = current_report_source_status(report, knowledge_root=library.lib.root)
    assert result["status"] == "unavailable" and result["items"] == []
    assert json.dumps(report, sort_keys=True) == frozen


def test_real_create_retrieve_freeze_reopen_audit_and_current_annotation(library, tmp_path):
    from contextlib import closing

    from healthzip.db.repository import Repository
    from healthzip.workflows.period_report import create_report, load_report
    from healthzip.workflows.report_objects import audit_bundle, reconstruct_report
    from tests.integration.test_report_repair_contract import CUTOFF, independent_records

    premise = claim(library, "premise", [], bind=False)
    rival = claim(library, "rival", [], bind=False)
    action = claim(library, "action", ["action_or_reassessment"])
    claim(library, "independent", ["measurement", "comparison"])
    edge(library, "premise", "action", "required_by", [premise, action])
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        independent_records(repo)
        report = create_report(repo, {"cutoff_time": CUTOFF, "timezone": "Asia/Shanghai"},
                               period="week", knowledge_root=library.lib.root, include_details=True)
        q = next(q for q in report["questions"] if q["id"] == "W4")
        item = next(i for i in q["evidence"]["items"] if i["claim_id"] == "action")
        assert q["fact_id"] and q["rows"] and q["steps"]
        assert item["statement"] in report["markdown"]
        assert item["limitations"][0] in report["markdown"]
        assert item["citations"][0]["url"] in report["markdown"]
        assert load_report(repo, report["report_id"], include_details=True) == report
        assert reconstruct_report(json.loads(json.dumps(audit_bundle(repo, report["report_id"])))) == report
        compact = load_report(repo, report["report_id"])
        queries = []
        repo.conn.set_trace_callback(queries.append)
        assert current_report_source_status(compact, knowledge_root=library.lib.root, repo=repo)["status"] == "current"
        repo.conn.set_trace_callback(None)
        assert not any("FROM workflow_run" in sql or "FROM analysis_run" in sql for sql in queries)
        edge(library, "premise", "rival", "conflicts_with", [premise, rival])
        assert statuses(library, compact)[1]["action"]["status"] == "dependent_restriction"
        assert statuses(library, compact)[1]["independent"]["status"] == "verified"
        assert load_report(repo, report["report_id"], include_details=True) == report


def test_current_status_retains_usage_rights_gate(library):
    sid = claim(library, "method", ["measurement"])
    report = historical(question(library))
    report["questions"][0]["evidence"]["applicability_context"] = {"usage_scope": "commercial"}
    with library.lib.sources:
        library.lib.sources.execute("UPDATE version SET rights_json=? WHERE version_id=?",
            (json.dumps({"index_allowed": True, "license_id": "CC-BY-NC"}), sid.rsplit(":s", 1)[0]))
    result, items = statuses(library, report)
    assert result["status"] == "restricted"
    assert items["method"]["reason"] == "noncommercial_scope_required"
