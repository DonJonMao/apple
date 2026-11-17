"""Request-local scan reuse preserves per-component rights and live revocation."""
import sqlite3

import pytest

from healthzip.knowledge import metric_retrieval, vector_index


def source_with_units(kb):
    kb.lib.seed({"sources": [{"source_id": "scan", "canonical_url": "https://example.invalid/scan",
        "title": "Synthetic scan", "corpus_roles": ["research"]}]}, {"cards": []})
    version = kb.lib.record_version("scan", b"synthetic scan", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": "Synthetic unit one"}, {"text": "Synthetic unit two"},
         {"text": "Synthetic restricted component", "rights": {"index_allowed": False}}], "fixture")
    vector_index.register_spans(kb, version, ["strength"], assignment_status="content_checked")
    return [version + f":s{i:05d}" for i in range(3)]


def test_shared_version_does_not_share_component_permission(kb):
    ids = source_with_units(kb)
    candidates, _, excluded, _ = metric_retrieval.eligible_candidates(kb, ["strength"], {}, None)
    assert [c["span_id"] for c in candidates] == ids[:2]
    assert {"span_id": ids[2], "reason": "rights_not_cleared"} in excluded


def test_reviewed_prefilter_preserves_complete_group_results(kb, monkeypatch):
    from test_v15_ranked_coverage import add_group, metric_result
    from test_v15_retrieval import CONTEXT

    unrelated = source_with_units(kb)
    add_group(kb)
    original = metric_retrieval.eligible_candidates
    reads = []
    read = kb.lib.span

    def record_read(identity, **kwargs):
        reads.append(identity)
        return read(identity, **kwargs)

    monkeypatch.setattr(kb.lib, "span", record_read)
    fast = kb.retrieve_for_metric("STR-12", "strength", metric_result(), CONTEXT,
        mode="lexical", candidate_scope="reviewed_metric", k=3)
    assert not set(reads) & set(unrelated)
    monkeypatch.setattr(metric_retrieval, "eligible_candidates",
        lambda *args, **kwargs: original(*args, reviewed_only=False))
    full = kb.retrieve_for_metric("STR-12", "strength", metric_result(), CONTEXT,
        mode="lexical", candidate_scope="reviewed_metric", k=3)
    for field in ("status", "matched_claims", "evidence_spans", "conflicts", "capability_permissions", "limitations"):
        assert fast[field] == full[field]
    assert fast["retrieval_audit"]["candidate_ids_sha256"] == full["retrieval_audit"]["candidate_ids_sha256"]


@pytest.mark.parametrize("other_connection", [False, True])
def test_revocation_during_scan_invalidates_reuse(kb, monkeypatch, other_connection):
    ids = source_with_units(kb)
    original = kb.lib.span

    def read(identity, **kwargs):
        if identity == ids[1]:
            db = sqlite3.connect(kb.root / "sources.sqlite3") if other_connection else kb.lib.sources
            with db:
                db.execute("UPDATE source SET scientific_state='withdrawn',scientific_epoch=scientific_epoch+1 WHERE source_id='scan'")
            if other_connection:
                db.close()
        return original(identity, **kwargs)

    monkeypatch.setattr(kb.lib, "span", read)
    candidates, _, excluded, _ = metric_retrieval.eligible_candidates(kb, ["strength"], {}, None)
    assert [c["span_id"] for c in candidates] == ids[:1]
    assert {"span_id": ids[1], "reason": "withdrawn"} in excluded
    assert not metric_retrieval._still_current(kb, candidates[0], {})
