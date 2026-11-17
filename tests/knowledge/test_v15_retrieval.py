"""Public synthetic fixtures test authority boundaries, not retrieval quality."""
import json

import pytest

from healthzip.knowledge import domains, metric_retrieval, vector_index
from healthzip.knowledge.model_services import (
    EmbeddingProvider,
    ModelUnavailable,
    RerankerProvider,
    ServiceConfig,
)
from healthzip.science import definitions, evaluate

CONTEXT = {"measurement_protocol": "explicit_test_protocol", "population": "adults"}
REVIEW = {"reviewer": "Synthetic test", "reviewer_kind": "synthetic_fixture",
          "reviewed_at": "2026-11-16", "rationale": "Synthetic software contract only",
          "content_checked": True, "application_checked": True}


def result(mid="STR-12"):
    return evaluate(mid, [], cutoff_time="2026-11-15T00:00:00+00:00",
                    window_start="2026-11-01T00:00:00+00:00", window_end="2026-11-15T00:00:00+00:00")



def add(w, identity="first", *, conditions=None, assigned=None, status="content_checked", mid="STR-12", bind=True, text=None):
    w.lib.seed({"sources": [{"source_id": identity, "canonical_url": "https://example.invalid/" + identity,
                              "title": "Synthetic evidence", "corpus_roles": ["research"]}]}, {"cards": []})
    text = text or domains.configuration()["profiles"][mid]["query"] + " Synthetic public evidence."
    vid = w.lib.record_version(identity, (identity + text).encode(), "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": text, "section_path": "Synthetic chapter", "locator": {"page": 1}}], "fixture-v15")
    sid = vid + ":s00000"
    w.review_claim({"claim_id": identity, "version": "1", "statement": text,
        "scope": {"population": "adults"}, "conditions": conditions or [], "limitations": ["Synthetic"],
        "evidence_links": [{"source_id": identity, "source_version_id": vid, "span_ids": [sid]}]}, REVIEW)
    vector_index.register_spans(w, vid, assigned or ["strength"], assignment_status=status)
    if bind:
        domains.link(w, origin={"type": "claim", "id": identity, "version": "1"}, relation="defines",
            target={"type": "metric", "id": mid, "version": "metric-domains-1.5.0"}, span_ids=[sid],
            applicability={"population": "adults"}, actor="Synthetic test", rationale="Synthetic binding",
            evidence_types=domains.configuration()["profiles"][mid]["required_evidence_types"], review=REVIEW)
    return vid, sid


class Embed(EmbeddingProvider):
    def __init__(self):
        super().__init__(ServiceConfig("https://example.invalid/embeddings", "synthetic", model_version="1"))
        self.calls = []

    def post(self, payload):
        self.calls.append(payload)
        return {"model": "synthetic", "data": [
            {"index": i, "embedding": [1., 0., 0.]} for i, _ in enumerate(payload["input"])]}


class Rank(RerankerProvider):
    def __init__(self):
        super().__init__(ServiceConfig("https://example.invalid/rank", "synthetic", model_version="1", provider="chat_listwise"))
        self.calls = []

    def post(self, payload):
        self.calls.append(payload)
        public = json.loads(payload["messages"][1]["content"])
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "ranking": [c["candidate_id"] for c in public["candidates"]]})}}]}


def test_profiles_cover_exact_registry_and_declared_domains():
    cfg = domains.configuration()
    assert set(cfg["profiles"]) == set(definitions()) and len(cfg["profiles"]) == 77
    assert len(cfg["functions"]) == 6 and len(cfg["domains"]) == 5
    for p in cfg["profiles"].values():
        assert set(p["required_domains"]) <= set(p["primary_domains"] + p["secondary_domains"])


def test_static_model_projection_and_incremental_cache(kb):
    add(kb)
    embed, rank = Embed(), Rank()
    first = vector_index.build_vectors(kb, embed)
    second = vector_index.build_vectors(kb, embed)
    assert first["generated"] == 1 and second["generated"] == 0 and second["reused_span_vectors"] == 1
    secret = "PRIVATE-NOTE-unique-person-9832"
    ctx = {**CONTEXT, "notes": secret, "user_id": secret, "health_values": {"mass": 91.234567}}
    found = metric_retrieval.retrieve_for_metric(kb, "STR-12", "strength", result(), ctx,
                                                services=(embed, rank))
    assert found["status"] == "evidence_context_supported"
    assert found["capability_permissions"]["source_explanation"] is True
    assert found["capability_permissions"]["candidate"] is False
    sent = json.dumps(embed.calls + rank.calls)
    assert secret not in sent and "91.234567" not in sent
    count = len(embed.calls)
    metric_retrieval.retrieve_for_metric(kb, "STR-12", "strength", result(), ctx, services=(embed, rank))
    assert len(embed.calls) == count  # Documents and static query both reused.
    persisted = kb.lib.sources.execute("SELECT payload_json FROM metric_retrieval_audit").fetchall()
    assert len(persisted) == 2 and secret not in str([tuple(r) for r in persisted])


def test_arithmetic_and_tenant_refusal_never_invoke_models(kb):
    class Forbidden:
        def __getattr__(self, key):
            pytest.fail("No model access is allowed")
    for mid, ctx, status in [("STR-01", {}, "not_required_deterministic_computation"),
                             ("STR-12", {"user_id": "a", "requested_other_user": "b"}, "insufficient_evidence")]:
        answer = metric_retrieval.retrieve_for_metric(kb, mid, "strength", result(mid), ctx,
                                                     services=(Forbidden(), Forbidden()))
        assert answer["status"] == status


def test_empty_historical_table_does_not_abort_index_or_enter_candidates(kb):
    add(kb)
    vid = kb.lib.record_version("first", b"empty historical table", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": "\n", "kind": "table", "locator": {"page": 2}}], "empty-table-fixture")
    vector_index.register_spans(kb, vid, ["strength"])
    provider = Embed()
    report = vector_index.build_vectors(kb, provider)
    assert report["generated"] == 1 and not report["failures"]
    assert {"span_id": vid + ":s00000", "reason": "empty_structured_unit"} in report["excluded"]
    candidates, _, excluded, _ = metric_retrieval.eligible_candidates(kb, ["strength"], CONTEXT, None)
    assert all(c["content"].strip() for c in candidates)
    assert {"span_id": vid + ":s00000", "reason": "empty_structured_unit"} in excluded
    assert kb.lib.span(vid + ":s00000")["text"] == "\n"


def test_parallel_model_requests_keep_all_sqlite_writes_on_caller_thread(kb, monkeypatch):
    import threading

    add(kb)
    vid = kb.lib.record_version("first", b"parallel index fixture", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": f"Unique public synthetic evidence {i}", "locator": {"page": i+2}} for i in range(6)], "parallel-fixture")
    vector_index.register_spans(kb, vid, ["strength"])
    barrier, lock = threading.Barrier(3), threading.Lock()
    active, maximum, calls = 0, 0, 0

    class Parallel(Embed):
        def post(self, payload):
            nonlocal active, maximum, calls
            with lock:
                active += 1
                maximum = max(maximum, active)
                calls += 1
                number = calls
            try:
                if number <= 3:
                    barrier.wait(timeout=5)
                return super().post(payload)
            finally:
                with lock:
                    active -= 1

    caller, saved_threads = threading.get_ident(), []
    original = vector_index.save_vectors

    def checked_save(*args, **kwargs):
        saved_threads.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(vector_index, "save_vectors", checked_save)
    report = vector_index.build_vectors(kb, Parallel(), batch_size=1, workers=3)
    assert report["generated"] == 7 and not report["failures"]
    assert maximum == 3 and len(saved_threads) == 7 and set(saved_threads) == {caller}
    assert report["request_workers"] == 3


def test_parallel_index_failure_preserves_resumable_committed_progress(kb):
    add(kb)
    vid = kb.lib.record_version("first", b"parallel failure fixture", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": t, "locator": {"page": i+2}} for i, t in enumerate(["unique good", "unique bad", "unique later"])],
        "parallel-failure-fixture")
    vector_index.register_spans(kb, vid, ["strength"])

    class Failing(Embed):
        def embed_documents(self, documents):
            if "unique bad" in documents:
                raise ModelUnavailable("synthetic_batch_failure")
            return super().embed_documents(documents)

    first = vector_index.build_vectors(kb, Failing(), batch_size=1, workers=3)
    assert first["failures"] and first["generated"] > 0
    second = vector_index.build_vectors(kb, Embed(), batch_size=1, workers=3)
    assert not second["failures"] and first["generated"] + second["generated"] == 4
    assert second["reused_span_vectors"] == first["generated"]


def test_rejected_applicability_cannot_reenter_as_raw_evidence(kb):
    add(kb, conditions=[{"field": "population", "op": "eq", "value": "trained_adults", "origin": "source_scope"}])
    found = metric_retrieval.retrieve_for_metric(kb, "STR-12", "strength", result(), CONTEXT, mode="lexical")
    assert not found["evidence_spans"]
    assert "claim_rejected_no_background_bypass" in str(found["retrieval_audit"]["excluded"])


@pytest.mark.parametrize("action", ["withdrawn", "corrected_pending_review", "revoked", "rights"])
def test_current_lifecycle_overrides_frozen_membership(kb, action):
    _, sid = add(kb)
    metric_retrieval.freeze_index(kb, "frozen")
    if action in {"withdrawn", "corrected_pending_review"}:
        kb.lib.update_state("first", action, "Synthetic lifecycle test")
    elif action == "revoked":
        kb.core_state("claim", "first", "1", "revoked", actor="Synthetic", rationale="Synthetic")
    else:
        with kb.lib.sources:
            kb.lib.sources.execute("UPDATE span SET scope_rights_json=? WHERE span_id=?", ('{"index_allowed":false}', sid))
    found = metric_retrieval.retrieve_for_metric(kb, "STR-12", "strength", result(), CONTEXT, "frozen", mode="lexical")
    assert found["status"] == "insufficient_evidence" and not found["evidence_spans"]


def test_index_release_does_not_acquire_later_spans(kb):
    add(kb)
    metric_retrieval.freeze_index(kb, "frozen")
    _, later = add(kb, "later")
    answer = metric_retrieval.retrieve_for_metric(kb, "STR-12", "strength", result(), CONTEXT, "frozen", mode="lexical")
    assert later not in {s["span_id"] for s in answer["evidence_spans"]}
    with pytest.raises(ValueError, match="immutable_index"):
        metric_retrieval.freeze_index(kb, "frozen")


def test_domain_and_required_evidence_completeness_block_authority(kb):
    add(kb, assigned=["physiology", "wearable"], mid="ENERGY-DEVICE-TOTAL")
    found = metric_retrieval.retrieve_for_metric(kb, "ENERGY-DEVICE-TOTAL", "metabolic", result("ENERGY-DEVICE-TOTAL"),
                                                CONTEXT, mode="lexical")
    assert found["matched_claims"] and found["status"] == "insufficient_evidence"
    assert "missing_required_domain:cardiometabolic" in found["limitations"]


def test_provisional_assignment_cannot_grant_authority(kb):
    add(kb, status="provisional")
    found = metric_retrieval.retrieve_for_metric(kb, "STR-12", "strength", result(), CONTEXT, mode="lexical")
    assert found["evidence_spans"] and not found["matched_claims"]


def test_edge_evidence_cannot_be_borrowed_from_unrelated_claim(kb):
    add(kb)
    _, other = add(kb, "other")
    with pytest.raises(ValueError, match="bind_each_claim"):
        domains.link(kb, origin={"type": "claim", "id": "first", "version": "1"}, relation="defines",
            target={"type": "metric", "id": "STR-12", "version": "metric-domains-1.5.0"}, span_ids=[other],
            applicability={}, actor="Synthetic", rationale="invalid", evidence_types=["scope_limit"], review=REVIEW)


def test_wrong_fixed_analysis_task_rejected(kb):
    with pytest.raises(ValueError, match="not_declared"):
        metric_retrieval.retrieve_for_metric(kb, "STR-12", "cycle", result())


def test_rrf_uses_ranks_and_rejects_duplicates():
    assert metric_retrieval.reciprocal_rank_fusion([["a", "b"], ["b", "c"]]) == ["b", "a", "c"]
    with pytest.raises(ValueError):
        metric_retrieval.reciprocal_rank_fusion([["a", "a"]])


def test_unavailable_models_report_lexical_degradation(kb):
    add(kb)
    embed = EmbeddingProvider(ServiceConfig("https://example.invalid/embeddings", "no-consent"))
    rank = RerankerProvider(ServiceConfig("https://example.invalid/rank", "no-consent"))
    found = metric_retrieval.retrieve_for_metric(kb, "STR-12", "strength", result(), CONTEXT, services=(embed, rank))
    assert found["evidence_spans"] and found["retrieval_audit"]["retrieval_degraded"]
    assert all(span["kind"] == kb.lib.span(span["span_id"])["kind"] for span in found["evidence_spans"])
    assert found["retrieval_audit"]["degradation_reasons"] == ["public_evidence_network_consent_required"] * 2


def test_migration_and_index_mutations_preserve_outer_rollback(kb):
    vid, _ = add(kb, bind=False)
    for conn in (kb.lib.sources, kb.lib.theories):
        conn.execute("BEGIN")
    domains.ensure_schema(kb)
    domains.assign(kb, object_type="source_version", object_id="first", object_version=vid,
                   domains=["strength"], status="provisional", actor="Synthetic", rationale="Synthetic")
    embed = Embed()
    vector_index.ensure_schema(kb)
    vector_index.save_vectors(kb, embed, ["fixture"], [[1., 0.]], "document")
    vector_index.register_spans(kb, vid, ["strength"], assignment_status="content_checked")
    for conn in (kb.lib.sources, kb.lib.theories):
        assert conn.in_transaction
        conn.rollback()
    assert not kb.lib.theories.execute("SELECT name FROM sqlite_master WHERE name='knowledge_domain_assignment'").fetchall()
    # Table creation itself rolled back, rather than committing the caller.
    assert not kb.lib.sources.execute("SELECT name FROM sqlite_master WHERE name='retrieval_vector'").fetchall() or not kb.lib.sources.execute("SELECT * FROM retrieval_vector").fetchall()


def test_cache_model_identity_and_dimension_isolation(kb):
    vector_index.ensure_schema(kb)
    provider = Embed()
    vector_index.save_vectors(kb, provider, ["same"], [[1., 0.]], "document")
    with pytest.raises(ModelUnavailable, match="dimension_changed"):
        vector_index.save_vectors(kb, provider, ["new"], [[1., 0., 0.]], "document")
    provider.config.model_version = "2"
    assert vector_index.cached(kb, provider, "same", "document") is None
    vector_index.save_vectors(kb, provider, ["same"], [[1., 0., 0.]], "document")
    assert len(vector_index.cached(kb, provider, "same", "document")) == 3


@pytest.mark.parametrize("data", [
    [{"index": 0, "embedding": [float("nan")]}],
    [{"index": True, "embedding": [1.]}],
    [{"index": 0, "embedding": [0., 0.]}],
    [{"index": 3, "embedding": [1., 0.]}],
])
def test_malformed_embedding_response_refused(monkeypatch, data):
    provider = Embed()
    monkeypatch.setattr(provider, "post", lambda payload: {"data": data})
    with pytest.raises(ModelUnavailable):
        provider.embed_documents(["public fixture"])


@pytest.mark.parametrize("ranking", [["invented"], [{"id": "a"}], ["a", "a"], []])
def test_reranker_must_return_exact_id_permutation(monkeypatch, ranking):
    rank = Rank()
    monkeypatch.setattr(rank, "post", lambda payload: {"choices": [{"finish_reason": "stop",
        "message": {"content": json.dumps({"ranking": ranking})}}]})
    with pytest.raises(ModelUnavailable):
        rank.rerank("public", [{"candidate_id": "a", "content": "public"}, {"candidate_id": "b", "content": "public"}])


def test_append_only_domain_review_does_not_rewrite_frozen_assignment(kb):
    _, sid = add(kb, status="provisional")
    metric_retrieval.freeze_index(kb, "before-review")
    vector_index.review_unit_domains(kb, [sid], ["strength"], REVIEW)
    current = kb.retrieve_for_metric("STR-12", "strength", result(), CONTEXT, mode="lexical")
    frozen = kb.retrieve_for_metric("STR-12", "strength", result(), CONTEXT, "before-review", mode="lexical")
    assert current["capability_permissions"]["source_explanation"] is True
    assert frozen["capability_permissions"]["source_explanation"] is False
    original = kb.lib.sources.execute("SELECT assignment_status FROM retrieval_unit WHERE span_id=?", (sid,)).fetchone()[0]
    assert original == "provisional"


def test_metric_edge_applicability_is_enforced_separately(kb):
    add(kb)
    answer = kb.retrieve_for_metric("STR-12", "strength", result(),
        {**CONTEXT, "population": "trained_adults"}, mode="lexical")
    assert answer["evidence_spans"] and not answer["matched_claims"]
    assert not answer["capability_permissions"]["source_explanation"]


def test_conflict_is_screened_before_display_budget(kb):
    _, first = add(kb, "a")
    _, second = add(kb, "z")
    domains.link(kb, origin={"type": "claim", "id": "a", "version": "1"}, relation="conflicts_with",
        target={"type": "claim", "id": "z", "version": "1"}, span_ids=[first, second],
        applicability={"population": "adults"}, actor="Synthetic", rationale="Synthetic conflict")
    answer = kb.retrieve_for_metric("STR-12", "strength", result(), CONTEXT, mode="lexical", k=1)
    assert len(answer['evidence_spans']) == 1 and answer['conflicts']
    assert not answer["capability_permissions"]["source_explanation"]


def test_frozen_bindings_still_observe_new_current_conflict_notices(kb):
    _, first = add(kb, "a")
    _, second = add(kb, "z")
    metric_retrieval.freeze_index(kb, "before-conflict")
    domains.link(kb, origin={"type": "claim", "id": "a", "version": "1"}, relation="conflicts_with",
        target={"type": "claim", "id": "z", "version": "1"}, span_ids=[first, second],
        applicability={}, actor="Synthetic", rationale="Synthetic conflict")
    frozen = kb.retrieve_for_metric("STR-12", "strength", result(), CONTEXT, "before-conflict", mode="lexical")
    assert frozen['conflicts'] and frozen['status'] == 'insufficient_evidence'
    # Scientific lifecycle is still current, even though relation membership is frozen.
    kb.core_state("claim", "a", "1", "revoked", actor="Synthetic", rationale="Synthetic")
    withdrawn = kb.retrieve_for_metric("STR-12", "strength", result(), CONTEXT, "before-conflict", mode="lexical")
    assert all(c['claim_id'] != 'a' for c in withdrawn['matched_claims'])


def test_missing_evidence_type_cannot_be_hidden_by_matching_primary_domain(kb):
    _, sid = add(kb, bind=False)
    domains.link(kb, origin={"type": "claim", "id": "first", "version": "1"}, relation="limits",
        target={"type": "metric", "id": "STR-12", "version": "metric-domains-1.5.0"}, span_ids=[sid],
        applicability={}, actor="Synthetic", rationale="Only a limitation was reviewed",
        evidence_types=["scope_limit"], review=REVIEW)
    answer = kb.retrieve_for_metric("STR-12", "strength", result(), CONTEXT, mode="lexical")
    assert answer['matched_claims'] and answer['status'] == 'insufficient_evidence'
    assert 'missing_evidence_type:measurement_definition' in answer['limitations']


def test_noncommercial_evidence_cannot_enter_commercial_ranking(kb):
    _, sid = add(kb)
    with kb.lib.sources:
        kb.lib.sources.execute('UPDATE span SET scope_rights_json=? WHERE span_id=?',
            (json.dumps({'index_allowed': True, 'noncommercial_only': True}), sid))
    answer = kb.retrieve_for_metric("STR-12", "strength", result(), {**CONTEXT, 'usage_scope': 'commercial'}, mode='lexical')
    assert not answer['evidence_spans']
    assert 'noncommercial_scope_required' in str(answer['retrieval_audit']['excluded'])


def test_product_explanation_passes_reviewed_claims_only(kb):
    add(kb)
    supported = kb.explain_metric("STR-12", "strength", result(), CONTEXT)
    assert 'claim:first:1' in supported['explanation']['evidence_ids']
    insufficient = kb.explain_metric("STR-12", "strength", result(), {})
    assert not any(e.startswith('claim:') for e in insufficient['explanation']['evidence_ids'])
    assert '知识证据不足' in str(insufficient['explanation']['limitations'])


def test_reranker_budget_uses_whole_public_units_without_private_projection():
    from healthzip.knowledge.model_services import fitting_reranker_prefix
    candidates = [{'candidate_id': str(i), 'content': 'x'*10000, 'private_note': 'must stay local'} for i in range(3)]
    bounded = fitting_reranker_prefix('public fixed task', candidates)
    assert len(bounded) == 2
    rank = Rank()
    assert rank.rerank('public fixed task', bounded) == ['0', '1']
    payload = json.loads(rank.calls[0]['messages'][1]['content'])
    assert all(len(c['content']) == 10000 for c in payload['candidates'])
    assert 'private_note' not in json.dumps(payload)


def test_indexing_releases_bulk_read_cursor_before_per_span_work(kb, monkeypatch):
    import sqlite3
    add(kb, 'a')
    add(kb, 'b')
    original = kb.lib.span
    writes = []

    def span_and_concurrent_writer(sid, **kwargs):
        value = original(sid, **kwargs)
        # A live bulk cursor would retain a read lock and block this commit.
        with sqlite3.connect(kb.root / 'sources.sqlite3', timeout=.1) as other:
            other.execute('UPDATE source SET updated_at=updated_at WHERE source_id=?', (value['source_id'],))
        writes.append(sid)
        return value

    monkeypatch.setattr(kb.lib, 'span', span_and_concurrent_writer)
    report = vector_index.build_vectors(kb, Embed())
    assert report['generated'] == 1  # Identical public text is deduplicated.
    assert len(writes) == 2


def test_narrow_span_read_preserves_provenance_rights_and_eligibility(kb):
    kb.lib.seed({'sources': [{'source_id': 'metadata', 'canonical_url': 'https://example.invalid/meta'}]}, {'cards': []})
    vid = kb.lib.record_version('metadata', b'fixture', 'fulltext', {}, {'large_report': 'x'*1000000},
        {'index_allowed': True, 'license_id': 'CC0'}, 'matched',
        [{'text': 'Public synthetic paragraph', 'locator': {'page': 1}}], 'fixture')
    sid = vid + ':s00000'
    complete = kb.lib.span(sid)
    narrow = kb.lib.span(sid, include_metadata=False)
    assert len(complete['metadata_json']) > 1000000 and narrow['metadata_json'] == '{}'
    assert {k: v for k, v in complete.items() if k != 'metadata_json'} == {k: v for k, v in narrow.items() if k != 'metadata_json'}
    assert kb.lib.eligible(complete, 'fulltext') == kb.lib.eligible(narrow, 'fulltext')


@pytest.mark.parametrize('action', ['claim', 'source'])
def test_revocation_during_remote_ranking_cannot_restore_authority(kb, action):
    add(kb)
    embed = Embed()
    vector_index.build_vectors(kb, embed)

    class RevokeRank(Rank):
        def post(self, payload):
            if action == 'claim':
                kb.core_state('claim', 'first', '1', 'revoked', actor='Synthetic', rationale='Synthetic concurrent change')
            else:
                kb.lib.update_state('first', 'withdrawn', 'Synthetic concurrent source notice')
            return super().post(payload)

    answer = kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, services=(embed, RevokeRank()))
    assert not answer['evidence_spans'] and not answer['capability_permissions']['source_explanation']
    assert 'invalidated_after_candidate_filter' in str(answer['retrieval_audit']['excluded'])
