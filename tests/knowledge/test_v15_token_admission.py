"""A byte resource bound must not masquerade as the serving model's token limit."""
from dataclasses import replace

import pytest

from healthzip.knowledge import vector_index
from healthzip.knowledge.model_services import EmbeddingProvider, ModelUnavailable, ServiceConfig

PUBLIC = "Synthetic public original paragraph with full measurement context. " * 100


class TokenEmbedding(EmbeddingProvider):
    def __init__(self, *, count=1200):
        super().__init__(ServiceConfig("https://example.invalid/v1/embeddings", "fixture",
            deployment_revision="synthetic-1", tokenizer_endpoint="https://example.invalid/tokenize",
            context_window_tokens=4096))
        self.count, self.token_calls, self.embedding_calls = count, [], []

    def _post_payload(self, payload, *, endpoint=None):
        assert endpoint == self.config.tokenizer_endpoint
        self.token_calls.append(payload)
        return {"count": self.count, "max_model_len": 4096, "tokens": [1] * self.count}

    def post(self, payload):
        self.embedding_calls.append(payload)
        return {"model": "fixture", "data": [
            {"index": i, "embedding": [1., 0., 0.]} for i in range(len(payload['input']))]}


def add_long_paragraph(kb):
    kb.lib.seed({"sources": [{"source_id": "token-fixture", "title": "Synthetic long original",
        "canonical_url": "https://example.invalid/evidence", "corpus_roles": ["research"]}]}, {"cards": []})
    vid = kb.lib.record_version("token-fixture", b"synthetic original", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": PUBLIC, "locator": {"page": 1}}], "fixture")
    vector_index.register_spans(kb, vid, ["strength"])
    return vid + ":s00000"


def test_long_whole_unit_is_counted_once_embedded_without_truncation_and_incrementally_reused(kb):
    sid = add_long_paragraph(kb)
    provider = TokenEmbedding()
    original_identity = provider.config.model_key
    report = vector_index.build_vectors(kb, provider)
    assert report['generated'] == 1 and not report['failures'] and not report['excluded']
    assert report['whole_unit_token_admissions'][0]['token_count'] == 1200
    assert provider.token_calls == [{"model": "fixture", "prompt": PUBLIC, "add_special_tokens": True}]
    assert provider.embedding_calls[0]['input'] == [PUBLIC]
    assert provider.embedding_calls[0]['truncate_prompt_tokens'] is None
    assert kb.lib.span(sid)['text'] == PUBLIC
    assert vector_index.build_vectors(kb, provider)['reused_span_vectors'] == 1
    # Admission does not change the embedding operation or invalidate prior content vectors.
    provider.config = replace(provider.config, tokenizer_endpoint=None, context_window_tokens=None)
    assert provider.config.model_key == original_identity
    assert vector_index.build_vectors(kb, provider)['reused_span_vectors'] == 1
    assert len(provider.token_calls) == 1 and len(provider.embedding_calls) == 1


def test_truly_over_context_unit_is_explicitly_excluded_without_embedding(kb):
    sid = add_long_paragraph(kb)
    provider = TokenEmbedding(count=4097)
    report = vector_index.build_vectors(kb, provider)
    assert report['generated'] == 0 and not provider.embedding_calls
    assert report['excluded'] == [{"span_id": sid, "reason": "structured_unit_exceeds_model_token_budget"}]
    assert kb.lib.span(sid)['text'] == PUBLIC


@pytest.mark.parametrize("response", [
    {"count": 10, "max_model_len": 4096, "tokens": [1]},
    {"count": 1, "max_model_len": 2048, "tokens": [1]},
    {"count": 1, "max_model_len": 4096, "tokens": [True]},
])
def test_invalid_token_counts_or_changed_context_never_admit_long_text(response, monkeypatch):
    provider = TokenEmbedding()
    monkeypatch.setattr(provider, '_post_payload', lambda *args, **kwargs: response)
    with pytest.raises(ModelUnavailable, match="tokenizer_count_or_context_identity_invalid"):
        provider.embed_documents([PUBLIC])
    assert not provider.embedding_calls


def test_tokenizer_failure_records_indexing_failure_and_keeps_original(kb, monkeypatch):
    sid = add_long_paragraph(kb)
    provider = TokenEmbedding()

    def fail(*args, **kwargs):
        raise ModelUnavailable('model_transport_or_json_error')

    monkeypatch.setattr(provider, '_post_payload', fail)
    report = vector_index.build_vectors(kb, provider)
    assert report['retrieval_degraded'] and report['generated'] == 0
    assert report['failures'][0]['stage'] == 'input_admission'
    assert kb.lib.span(sid)['text'] == PUBLIC and not provider.embedding_calls


def test_tokenizer_requires_same_origin_and_explicit_network_consent(monkeypatch):
    with pytest.raises(ValueError, match="same_origin_tokenizer"):
        ServiceConfig('https://example.invalid/v1/embeddings', 'fixture',
            tokenizer_endpoint='https://elsewhere.invalid/tokenize', context_window_tokens=4096)
    with pytest.raises(ValueError, match="same_origin_tokenizer"):
        ServiceConfig('https://example.invalid/v1/embeddings', 'fixture', context_window_tokens=4096)
    config = TokenEmbedding().config
    provider = EmbeddingProvider(config)
    with pytest.raises(ModelUnavailable, match="public_evidence_network_consent_required"):
        provider.embed_documents([PUBLIC])


def test_shorter_declared_context_counts_even_short_byte_inputs():
    provider = TokenEmbedding(count=1)
    provider.config = replace(provider.config, context_window_tokens=2)
    # The synthetic server still advertises 4096: an unverified smaller window must fail closed.
    with pytest.raises(ModelUnavailable, match="tokenizer_count_or_context_identity_invalid"):
        provider.embed_documents(['short'])
