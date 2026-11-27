"""Independent topic evidence contracts: real claims, links, retrieval, and failures."""
import json
from copy import deepcopy
from urllib.error import HTTPError

import pytest
from test_health_fact_bindings import answer_for, metric
from test_v15_retrieval import REVIEW

from healthzip.ai.client import AIConfig, explain_analysis
from healthzip.knowledge import domains, topics, vector_index
from healthzip.knowledge.health_facts import comparison_cards, measurement_explanations
from healthzip.knowledge.metric_retrieval import _retrieve_for_metric


def add_claim(kb, identity, topic, purposes, *, text=None, count=1, bind=True, conditions=None):
    kb.lib.seed({'sources': [{'source_id': identity, 'title': 'Synthetic ' + identity,
        'canonical_url': 'https://example.invalid/' + identity, 'corpus_roles': ['research']}]}, {'cards': []})
    content = text or 'Sleep measurement comparison protocol public evidence ' + identity
    vid = kb.lib.record_version(identity, (identity + content).encode(), 'fulltext', {}, {},
        {'index_allowed': True, 'license_id': 'CC0'}, 'matched',
        [{'text': content + ' part ' + str(i), 'section_path': 'Methods', 'locator': {'page': i + 3}}
         for i in range(count)], 'repair-independent-fixture')
    spans = [vid + f':s{i:05d}' for i in range(count)]
    kb.review_claim({'claim_id': identity, 'version': '1', 'statement': content,
        'scope': {'explanation_purpose': 'measurement_context' if 'measurement' in purposes else 'mechanism'},
        'limitations': ['Synthetic software scenario; no clinical authority.'], 'conditions': conditions or [],
        'evidence_links': [{'source_id': identity, 'source_version_id': vid, 'span_ids': spans}]}, REVIEW)
    vector_index.register_spans(kb, vid, ['wearable'], assignment_status='content_checked')
    if bind:
        domains.link(kb, origin={'type': 'claim', 'id': identity, 'version': '1'}, relation='applies_to',
            target={'type': 'metric', 'id': topic, 'version': domains.profile_version(topic)},
            span_ids=spans, applicability={}, actor='Synthetic', rationale='Independent exact topic use',
            evidence_types=purposes, review=REVIEW)
    return spans


def link(kb, left, right, relation, spans):
    domains.link(kb, origin={'type': 'claim', 'id': left, 'version': '1'}, relation=relation,
        target={'type': 'claim', 'id': right, 'version': '1'}, span_ids=spans,
        applicability={}, actor='Synthetic', rationale='Independent prerequisite/conflict fixture')


def test_t14_real_conflict_path_keeps_measurement_and_blocks_dependent_action(kb):
    topic = 'W6'
    a = add_claim(kb, 'mechanism-positive', topic, ['mechanism_or_exception'])
    b = add_claim(kb, 'mechanism-negative', topic, ['mechanism_or_exception'])
    measurement = add_claim(kb, 'independent-method', topic, ['measurement', 'comparison'])
    action = add_claim(kb, 'dependent-action', topic, ['action_or_reassessment'])
    independent = add_claim(kb, 'independent-check', topic, ['action_or_reassessment'])
    link(kb, 'mechanism-positive', 'mechanism-negative', 'conflicts_with', a + b)
    link(kb, 'mechanism-positive', 'dependent-action', 'required_by', a + action)
    answer = topics.question_sources(kb, topic)
    assert answer['status'] == 'partial_conflict'
    assert {i['claim_id'] for i in answer['items']} == {'independent-method', 'independent-check'}
    restricted = {i['claim_id']: i for i in answer['restricted_items']}
    assert set(restricted) == {'mechanism-positive', 'mechanism-negative', 'dependent-action'}
    assert all(not i['recommendation_allowed'] for i in restricted.values())
    assert restricted['dependent-action']['required_claim_refs'] == [
        {'claim_id': 'mechanism-positive', 'claim_version': '1'}]
    assert {s['span_id'] for i in answer['items'] for s in i['citations']} == set(measurement + independent)
    raw = _retrieve_for_metric(kb, topic, 'explain_metric', None, mode='lexical', k=6,
                               candidate_scope='reviewed_metric')
    assert [c['claim_id'] for c in measurement_explanations(raw)] == ['independent-method']
    assert raw['capability_permissions']['source_explanation'] is False


def test_conflict_on_prerequisite_without_direct_topic_edge_is_still_local(kb):
    topic = 'W2'
    a = add_claim(kb, 'premise-a', topic, [], bind=False)
    b = add_claim(kb, 'premise-b', topic, [], bind=False)
    action = add_claim(kb, 'action', topic, ['action_or_reassessment'])
    add_claim(kb, 'method', topic, ['measurement'])
    link(kb, 'premise-a', 'premise-b', 'conflicts_with', a + b)
    link(kb, 'premise-a', 'action', 'required_by', a + action)
    answer = topics.question_sources(kb, topic)
    assert [i['claim_id'] for i in answer['items']] == ['method']
    assert [i['claim_id'] for i in answer['restricted_items']] == ['action']


@pytest.mark.parametrize('topic', ['W2', 'W3', 'W4', 'BODY-OBS-oxygen_saturation_fraction'])
def test_t15_complete_action_group_recovered_with_bounded_local_pass(kb, topic):
    method = add_claim(kb, 'method-heavy', topic,
        ['measurement', 'comparison', 'mechanism_or_exception'],
        text='measurement method comparison change score error important missing observation ' * 6,
        count=6)
    action = add_claim(kb, 'recheck', topic, ['action_or_reassessment'],
        text='Keep a notebook of circumstances and repeat the assessment.', count=2)
    answer = topics.question_sources(kb, topic)
    assert {i['claim_id'] for i in answer['items']} == {'method-heavy', 'recheck'}
    assert {s['span_id'] for i in answer['items'] for s in i['citations']} == set(method + action)
    audit = answer['retrieval']
    assert audit['requested_k'] == 6 and audit['supplemental_remote_calls'] == 0
    assert audit['selected_unique_spans'] == 8 <= audit['maximum_unique_spans'] == 12
    assert audit['supplemental_pass']['requested_mode'] == 'lexical'
    assert audit['initial_missing_purposes'] == ['action_or_reassessment']
    assert audit['purpose_status']['action_or_reassessment'] == 'available'
    assert len(next(i for i in answer['items'] if i['claim_id'] == 'recheck')['citations']) == 2


def test_unrequested_use_does_not_trigger_supplement_and_missing_never_fills_by_label(kb):
    topic = 'W6'
    add_claim(kb, 'method', topic, ['measurement'])
    answer = topics.question_sources(kb, topic, required_purposes=['measurement'])
    assert answer['retrieval']['supplemental_pass'] is None
    answer = topics.question_sources(kb, topic)
    assert answer['retrieval']['purpose_status']['action_or_reassessment'] == 'no_current_applicable_reviewed_group'
    assert answer['retrieval']['supplemental_pass'] is None


def test_t16_unknown_population_excludes_adult_action_but_preserves_method(kb):
    topic = 'W3'
    add_claim(kb, 'method', topic, ['measurement'])
    add_claim(kb, 'adult-action', topic, ['action_or_reassessment'], conditions=[
        {'field': 'age', 'op': 'range', 'min': 18, 'max': 65, 'origin': 'source_scope'}])
    answer = topics.question_sources(kb, topic)
    assert [i['claim_id'] for i in answer['items']] == ['method']
    assert any(i['claim_id'] == 'adult-action' for i in answer['retrieval']['excluded'] if 'claim_id' in i)
    kb.core_state('claim', 'method', '1', 'revoked', actor='Synthetic', rationale='Current revocation')
    assert topics.question_sources(kb, topic)['items'] == []


class Response:
    def __init__(self, answer):
        self.answer = answer

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({'choices': [{'message': {'content': json.dumps(self.answer)}}]}).encode()


def test_t17_bad_paragraph_cannot_deny_supplied_fatigue(monkeypatch):
    cards = comparison_cards(metric())
    cards.append({'id': 'fatigue-20261013', 'title': 'Actual subjective record', 'status': 'computed_observation',
        'summary': '2026-10-13 已记录疲劳及训练后的不适。', 'facts': [],
        'limitations': ['仅记录背景，不确定因果。'], 'allowed_actions': ['核对对应训练与主观记录']})
    answer = answer_for(cards[0])
    answer['summary'] += '\n尚未提供任何疲劳记录。'
    monkeypatch.setattr('healthzip.ai.client.urlopen', lambda *a, **kw: Response(answer))
    result = explain_analysis({'cards': cards}, config=AIConfig('https://example.invalid', 'test', 'test'),
                              allow_network=True)
    assert result['reason_code'] == 'partial_validation'
    assert '68 bpm' in result['summary'] and '尚未提供' not in result['summary']
    assert cards[-1]['summary'] == '2026-10-13 已记录疲劳及训练后的不适。'


@pytest.mark.parametrize('failure,expected', [('timeout', 'TimeoutError'), ('service', 'HTTPError'),
    ('number', 'validation_failed'), ('date', 'validation_failed')])
def test_t18_transport_and_validation_reasons_remain_distinct_and_local(monkeypatch, failure, expected):
    cards = comparison_cards(metric())
    original = deepcopy(cards)
    answer = answer_for(cards[0])
    if failure == 'number':
        answer['facts'][0]['value'] = 123456
    if failure == 'date':
        answer['facts'][0]['dates'] = ['2026-08-31']
    def transport(*args, **kwargs):
        if failure == 'timeout':
            raise TimeoutError('private transport secret')
        if failure == 'service':
            raise HTTPError('https://private.invalid', 503, 'private service secret', {}, None)
        return Response(answer)
    monkeypatch.setattr('healthzip.ai.client.urlopen', transport)
    result = explain_analysis({'cards': cards}, config=AIConfig('https://example.invalid', 'test', 'test'),
                              allow_network=True)
    assert result['reason_code'] == expected
    assert '68 bpm' in result['summary'] and 'secret' not in json.dumps(result)
    assert cards == original


def test_evidence_export_freezes_full_text_and_exact_review_without_changing_default(kb):
    topic = 'W6'
    spans = add_claim(kb, 'method', topic, ['measurement'])
    ordinary = topics.question_sources(kb, topic)
    assert 'evidence_spans' not in ordinary and 'claim_reviews' not in ordinary
    frozen = topics.question_sources(kb, topic, include_evidence=True)
    assert {s['span_id'] for s in frozen['evidence_spans']} == set(spans)
    assert frozen['evidence_spans'][0]['content'].endswith('part 0')
    assert frozen['claim_reviews'][0]['review']['reviewer_kind'] == 'synthetic_fixture'
    saved = deepcopy(frozen)
    kb.core_state('claim', 'method', '1', 'revoked', actor='Synthetic', rationale='Retraction')
    assert topics.question_sources(kb, topic)['items'] == []
    assert frozen == saved


def test_transient_fallback_is_retryable_with_same_job_identity():
    from uuid import uuid4

    from healthzip.ui.health_explanation import _JOBS, _LOCK, submit_job
    key = 'repair-test:' + uuid4().hex
    try:
        failed = submit_job(key, lambda: {'status': 'ready', 'items': [
            {'explanation': {'source': 'local_fallback', 'reason_code': 'TimeoutError'}}]})
        assert failed.result(timeout=5)['status'] == 'ready'
        retried = submit_job(key, lambda: {'status': 'ready', 'items': [
            {'explanation': {'source': 'ai', 'summary': 'validated'}}]})
        assert retried is not failed
        assert retried.result(timeout=5)['items'][0]['explanation']['summary'] == 'validated'
        reused = submit_job(key, lambda: pytest.fail('successful answer should coalesce'))
        assert reused is retried
    finally:
        with _LOCK:
            _JOBS.pop(key, None)
