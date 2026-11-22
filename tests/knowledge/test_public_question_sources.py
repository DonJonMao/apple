"""Public question retrieval retains actual evidence and lifecycle boundaries."""
import json

from test_v15_retrieval import REVIEW, Embed, Rank

from healthzip.knowledge import domains, topics, vector_index


def install(kb):
    source = {'source_id': 'public-method-fixture', 'title': 'Synthetic public method',
              'canonical_url': 'https://example.invalid/public-method', 'corpus_roles': ['research']}
    kb.lib.seed({'sources': [source]}, {'cards': []})
    vid = kb.lib.record_version(source['source_id'], b'public method original', 'fulltext', {}, {},
        {'index_allowed': True, 'license_id': 'CC0'}, 'matched',
        [{'text': 'Heart rate measurement comparison context posture activity.',
          'section_path': 'Methods', 'locator': {'page': 2}}], 'synthetic-public-question')
    sid = vid + ':s00000'
    kb.review_claim({'claim_id': 'public-method-fixture', 'version': '1',
        'statement': 'Compare recordings with their measurement context.', 'conditions': [],
        'scope': {'explanation_purpose': 'measurement_context'}, 'limitations': ['No personal diagnosis.'],
        'evidence_links': [{'source_id': source['source_id'], 'source_version_id': vid, 'span_ids': [sid]}]}, REVIEW)
    vector_index.register_spans(kb, vid, ['wearable'], assignment_status='content_checked')
    topic = 'BODY-OBS-heart_rate_bpm'
    domains.link(kb, origin={'type': 'claim', 'id': source['source_id'], 'version': '1'}, relation='limits',
        target={'type': 'metric', 'id': topic, 'version': domains.profile_version(topic)},
        span_ids=[sid], applicability={}, actor='Synthetic test', rationale='Public method question',
        evidence_types=['measurement', 'comparison'], review=REVIEW)
    return topic, vid


def test_public_question_needs_no_personal_metric_and_preserves_exact_original(kb):
    topic, vid = install(kb)
    answer = topics.question_sources(kb, topic)
    assert answer['status'] == 'available'
    item = answer['items'][0]
    assert item['limitations'] == ['No personal diagnosis.']
    citation = item['citations'][0]
    assert citation['version'] == vid and citation['locator'] == {'page': 2}
    assert citation['url'] == 'https://example.invalid/public-method'
    assert answer['scientific_authority'] == 'general_source_context'
    kb.core_state('claim', 'public-method-fixture', '1', 'revoked', actor='Test', rationale='Withdrawn')
    assert topics.question_sources(kb, topic)['items'] == []


def test_public_models_receive_only_public_question_and_original(kb):
    topic, _ = install(kb)
    embed, rank = Embed(), Rank()
    vector_index.build_vectors(kb, embed)
    answer = topics.question_sources(kb, topic, mode='hybrid_rerank', services=(embed, rank),
        context={'notes': 'PRIVATE-CONTEXT-9137', 'weight': 83.125})
    assert answer['items'] and rank.calls
    sent = json.dumps(embed.calls + rank.calls)
    assert 'PRIVATE-CONTEXT-9137' not in sent and '83.125' not in sent
    assert answer['retrieval']['personal_metric_values_sent'] is False


def test_definition_link_is_version_pinned_and_removed_on_retraction(kb, monkeypatch):
    topic, vid = install(kb)
    version = kb.lib.sources.execute('SELECT sha256 FROM version WHERE version_id=?', (vid,)).fetchone()
    original = {'source_id': 'public-method-fixture', 'version': vid, 'sha256': version[0],
                'url': 'https://example.invalid/definition', 'symbol': 'heartRate'}
    monkeypatch.setattr(topics, '_official_definitions', lambda: {'heart_rate_bpm': original})
    assert topics.question_sources(kb, topic)['field_definitions'] == [original]
    kb.lib.sources.execute("UPDATE source SET scientific_state='retracted' WHERE source_id=?", ('public-method-fixture',))
    kb.lib.sources.commit()
    assert topics.question_sources(kb, topic)['field_definitions'] == []

