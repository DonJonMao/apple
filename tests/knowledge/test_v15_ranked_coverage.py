"""A bounded model request must not silently discard the tail of fused evidence."""
import json

import pytest

from healthzip.knowledge import domains, metric_retrieval, vector_index
from healthzip.knowledge.model_services import (
    ModelUnavailable,
    RerankerProvider,
    ServiceConfig,
    rerank_windows,
)
from healthzip.science import evaluate

REVIEW = {"reviewer": "Coverage software fixture", "reviewer_kind": "synthetic_fixture",
          "reviewed_at": "2026-11-17", "rationale": "Synthetic candidate coverage only",
          "content_checked": True, "application_checked": True}


def test_tail_evidence_survives_model_budget_and_retains_complete_original_text(kb, monkeypatch):
    kb.lib.seed({"sources": [{"source_id": "coverage-fixture", "title": "Synthetic evidence coverage",
        "canonical_url": "https://example.invalid/coverage", "corpus_roles": ["research"]}]}, {"cards": []})
    texts = [("Synthetic original paragraph " + str(i) + " ") * 90 for i in range(20)]
    texts[-1] += " Specific measurement definition, assumptions and scope."
    vid = kb.lib.record_version("coverage-fixture", b"synthetic coverage fixture", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": text, "locator": {"page": i+1}} for i, text in enumerate(texts)], "fixture")
    ids = [vid + ":s" + str(i).zfill(5) for i in range(20)]
    kb.review_claim({"claim_id": "tail-definition", "version": "1",
        "statement": "Synthetic measurement definition and its assumptions.",
        "scope": {"synthetic": True}, "limitations": ["Software fixture only"], "conditions": [],
        "evidence_links": [{"source_id": "coverage-fixture", "source_version_id": vid, "span_ids": [ids[-1]]}]}, REVIEW)
    vector_index.register_spans(kb, vid, ["strength"], assignment_status="content_checked")
    domains.link(kb, origin={"type": "claim", "id": "tail-definition", "version": "1"}, relation="defines",
        target={"type": "metric", "id": "STR-12", "version": "metric-domains-1.5.0"}, span_ids=[ids[-1]],
        applicability={}, actor="Synthetic coverage", rationale="Synthetic explicit metric definition",
        evidence_types=domains.configuration()["profiles"]["STR-12"]["required_evidence_types"], review=REVIEW)
    # Control the upstream ordering to isolate resource-budget candidate loss.
    monkeypatch.setattr(metric_retrieval, "_lexical", lambda query, candidates: ids)
    monkeypatch.setattr(metric_retrieval, "_dense", lambda *args: (ids, 0))
    rank = RerankerProvider(ServiceConfig("https://example.invalid/rank", "fixture"))
    calls = []

    def rank_public_window(payload):
        public = json.loads(payload["messages"][1]["content"])
        assert "private fixture note" not in json.dumps(public)
        candidates = public["candidates"]
        for c in candidates:
            assert c["content"] == texts[ids.index(c["candidate_id"])]
        calls.append([c["candidate_id"] for c in candidates])
        ordered = sorted(candidates, key=lambda c: c["candidate_id"] != ids[-1])
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(
            {"ranking": [c["candidate_id"] for c in ordered]})}}]}

    monkeypatch.setattr(rank, "post", rank_public_window)
    metric = evaluate("STR-12", [], cutoff_time="2026-11-17T00:00:00+00:00",
        window_start="2026-11-01T00:00:00+00:00", window_end="2026-11-17T00:00:00+00:00")
    found = kb.retrieve_for_metric("STR-12", "strength", metric,
        {"measurement_protocol": "synthetic recorded protocol", "population": "adults", "note": "private fixture note"},
        mode="hybrid_rerank", services=(rank, rank), k=1)
    assert set().union(*map(set, calls)) == set(ids)
    assert found["evidence_spans"][0]["span_id"] == ids[-1]
    assert found["capability_permissions"]["source_explanation"] is True
    assert found["capability_permissions"]["candidate"] is False


def test_oversized_singleton_retains_position_and_reports_no_model_ranking():
    rows = [{"candidate_id": str(i), "content": "public original " * (2000 if i == 1 else 800)}
            for i in range(4)]
    calls = []

    class Reverse:
        def rerank(self, query, candidates):
            calls.extend(candidates)
            return [c["candidate_id"] for c in reversed(candidates)]

    ordered, audit = rerank_windows(Reverse(), "fixed public task", rows)
    assert set(ordered) == {"0", "1", "2", "3"} and ordered[1] == "1"
    assert {c["candidate_id"] for c in calls} == {"0", "2", "3"}
    assert audit["unranked_ids"] == ["1"] and audit["ranking_complete"] is False
    assert not audit["source_units_truncated"] and not audit["excluded_ids"]


def test_revocation_between_windows_stops_subsequent_network_submission():
    rows = [{"candidate_id": str(i), "content": "public original " * 800} for i in range(4)]
    calls, current = [], True

    class Revoke:
        def rerank(self, query, candidates):
            nonlocal current
            calls.append(candidates)
            current = False
            return [c["candidate_id"] for c in candidates]

    with pytest.raises(ModelUnavailable, match="reranker_candidate_invalidated"):
        rerank_windows(Revoke(), "fixed public task", rows, is_current=lambda candidate: current)
    assert len(calls) == 1


def test_failed_later_window_keeps_completed_and_attempted_window_audit():
    rows = [{"candidate_id": str(i), "content": "public original " * 800} for i in range(4)]
    audit, calls = {}, []

    class FailLater:
        def rerank(self, query, candidates):
            calls.append(candidates)
            if len(calls) == 2:
                raise ModelUnavailable("model_transport_or_json_error")
            return [c["candidate_id"] for c in candidates]

    with pytest.raises(ModelUnavailable, match="model_transport_or_json_error"):
        rerank_windows(FailLater(), "fixed public task", rows, audit=audit)
    assert [w["status"] for w in audit["windows"]] == ["ranked", "failed"]
    assert audit["failure_reason"] == "model_transport_or_json_error" and not audit["ranking_complete"]
    assert audit["submitted_candidates"] == len(calls[0])


def add_group(kb, *, count=3):
    """A metric definition needs multiple whole public paragraphs together."""
    kb.lib.seed({"sources": [{"source_id": "group-fixture", "title": "Synthetic grouped definition",
        "canonical_url": "https://example.invalid/group", "corpus_roles": ["research"]}]}, {"cards": []})
    vid = kb.lib.record_version("group-fixture", b"grouped synthetic fixture", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": f"Synthetic complete definition part {i}", "locator": {"page": i+1}}
         for i in range(count+5)], "fixture")
    ids = [vid + ":s" + str(i).zfill(5) for i in range(count+5)]
    group = [ids[0], *ids[-(count-1):]] if count > 1 else [ids[0]]
    kb.review_claim({"claim_id": "group-definition", "version": "1",
        "statement": "A synthetic definition depends on all its parts.",
        "scope": {"synthetic": True}, "limitations": ["Software fixture"], "conditions": [],
        "evidence_links": [{"source_id": "group-fixture", "source_version_id": vid, "span_ids": group}]}, REVIEW)
    vector_index.register_spans(kb, vid, ["strength"], assignment_status="content_checked")
    domains.link(kb, origin={"type": "claim", "id": "group-definition", "version": "1"}, relation="defines",
        target={"type": "metric", "id": "STR-12", "version": "metric-domains-1.5.0"}, span_ids=group,
        applicability={}, actor="Synthetic coverage", rationale="Whole synthetic definition",
        evidence_types=domains.configuration()["profiles"]["STR-12"]["required_evidence_types"], review=REVIEW)
    return ids, group


def metric_result():
    return evaluate("STR-12", [], cutoff_time="2026-11-17T00:00:00+00:00",
        window_start="2026-11-01T00:00:00+00:00", window_end="2026-11-17T00:00:00+00:00")


def test_complete_claim_selected_within_same_span_budget(kb, monkeypatch):
    ids, group = add_group(kb)
    monkeypatch.setattr(metric_retrieval, "_lexical", lambda query, candidates: ids)
    found = kb.retrieve_for_metric("STR-12", "strength", metric_result(),
        {"measurement_protocol": "synthetic", "population": "adults"}, mode="lexical", k=3)
    assert [c["span_id"] for c in found["evidence_spans"]] == group
    assert found["status"] == "evidence_context_supported"
    assert not found["capability_permissions"]["candidate"]
    assert found["retrieval_audit"]["evidence_selection"]["span_budget"] == 3


def test_incomplete_over_budget_or_unretrieved_groups_never_grant_authority(kb, monkeypatch):
    ids, group = add_group(kb)
    monkeypatch.setattr(metric_retrieval, "_lexical", lambda query, candidates: ids)
    answer = kb.retrieve_for_metric("STR-12", "strength", metric_result(),
        {"measurement_protocol": "synthetic", "population": "adults"}, mode="lexical", k=2)
    assert len(answer["evidence_spans"]) <= 2
    assert answer["status"] == "insufficient_evidence" and not answer["matched_claims"]
    monkeypatch.setattr(metric_retrieval, "_lexical", lambda query, candidates: [i for i in ids if i not in group])
    answer = kb.retrieve_for_metric("STR-12", "strength", metric_result(),
        {"measurement_protocol": "synthetic", "population": "adults"}, mode="lexical", k=3)
    assert answer["status"] == "insufficient_evidence" and not answer["matched_claims"]


@pytest.mark.parametrize("dependency_state", ["verified", "revoked", "cycle", "unknown_applicability", "mismatched_applicability"])
def test_explicit_claim_dependency_is_complete_current_and_acyclic(kb, monkeypatch, dependency_state):
    ids, group = add_group(kb, count=1)
    kb.review_claim({"claim_id": "supporting-definition", "version": "1",
        "statement": "Synthetic supporting measurement prerequisite.",
        "scope": {"synthetic": True, "protocol": "dependency-specific-protocol"}, "conditions": [],
        "limitations": ["Synthetic prerequisite-specific restriction"],
        "evidence_links": [{"source_id": "group-fixture", "source_version_id": kb.lib.span(ids[-1])["version_id"],
                            "span_ids": [ids[-1]]}]}, REVIEW)
    domains.link(kb, origin={"type": "claim", "id": "supporting-definition", "version": "1"},
        relation="required_by", target={"type": "claim", "id": "group-definition", "version": "1"},
        span_ids=[ids[0], ids[-1]],
        applicability={"population": "synthetic_specific_population"} if dependency_state.endswith("applicability") else {},
        actor="Synthetic", rationale="Explicit synthetic prerequisite")
    if dependency_state == "revoked":
        kb.core_state("claim", "supporting-definition", "1", "revoked", actor="Synthetic", rationale="Synthetic revoke")
    if dependency_state == "cycle":
        domains.link(kb, origin={"type": "claim", "id": "group-definition", "version": "1"},
            relation="required_by", target={"type": "claim", "id": "supporting-definition", "version": "1"},
            span_ids=[ids[0], ids[-1]], applicability={}, actor="Synthetic", rationale="Synthetic cycle")
    monkeypatch.setattr(metric_retrieval, "_lexical", lambda query, candidates: [ids[0]])
    context = {"measurement_protocol": "synthetic", "population": "adults"}
    if dependency_state == "unknown_applicability":
        context["population"] = "unknown"
    found = kb.retrieve_for_metric("STR-12", "strength", metric_result(), context, mode="lexical", k=2)
    if dependency_state == "verified":
        assert {s["span_id"] for s in found["evidence_spans"]} == {group[0], ids[-1]}
        assert found["status"] == "evidence_context_supported"
        assert found["matched_claims"][0]["required_claim_refs"] == [
            {"claim_id": "supporting-definition", "claim_version": "1"}]
        assert found["retrieval_audit"]["evidence_selection"]["dependency_expansion_ids"] == [ids[-1]]
        assert "Synthetic prerequisite-specific restriction" in found["matched_claims"][0]["limitations"]
        from healthzip.knowledge import product
        projected = []
        monkeypatch.setattr(product, "explain_analysis", lambda payload, **kwargs: projected.append(payload) or {})
        product.explain_metric(kb, "STR-12", "strength", metric_result(), context, mode="lexical", k=2)
        card = projected[0]["public_source_claims"][0]
        assert "dependency-specific-protocol" in card["summary"]
        assert "Synthetic prerequisite-specific restriction" in card["limitations"]
    elif dependency_state == "mismatched_applicability":
        assert found["status"] == "evidence_context_supported" and not found["matched_claims"][0]["required_claim_refs"]
    else:
        assert found["status"] == "insufficient_evidence" and not found["matched_claims"]
