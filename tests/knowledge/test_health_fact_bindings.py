"""Independent adversarial facts, age applicability, and evidence lifecycle checks."""
import json
from copy import deepcopy

import pytest
from test_v15_retrieval import REVIEW

from healthzip.ai.client import (
    AIConfig,
    build_evidence_payload,
    explain_analysis,
    validate_ai_result,
)
from healthzip.knowledge import domains, vector_index
from healthzip.knowledge.acquisition import parse_jats
from healthzip.knowledge.health_facts import comparison_cards, public_method_needs
from healthzip.science import evaluate


def metric():
    result = evaluate('STATE-RHR', [], cutoff_time='2026-10-15T00:00:00+00:00',
                      window_start='2026-10-08T00:00:00+00:00', window_end='2026-10-15T00:00:00+00:00')
    current = {'start': '2026-10-08', 'end': '2026-10-15', 'timezone': 'UTC'}
    previous = {'start': '2026-10-01', 'end': '2026-10-08', 'timezone': 'UTC'}
    result['comparison'] = {'version': 'synthetic-independent-contract-2', 'windows': {'current': current, 'previous': previous},
        'streams': [{'fact_id': 'independent-fixture', 'current': {'window': current, 'value': 68, 'unit': 'bpm',
            'statistic_kind': 'median', 'recorded_days': 2, 'window_days': 7,
            'dates': ['2026-10-09', '2026-10-13'], 'missing_dates': ['2026-10-08']},
            'previous': {'window': previous, 'value': 62, 'unit': 'bpm', 'statistic_kind': 'median',
                'recorded_days': 7, 'window_days': 7, 'dates': ['2026-10-01']},
            'previous_change': {'absolute': 6, 'relative_percent': 100 * 6 / 62}, 'limitations': ['Coverage differs.']} ]}
    return result


def source(kb, *, age_condition=False):
    identity = 'measurement-fixture'
    kb.lib.seed({'sources': [{'source_id': identity, 'canonical_url': 'https://example.invalid/measurement',
                              'title': 'Independent synthetic method source', 'corpus_roles': ['research']}]}, {'cards': []})
    vid = kb.lib.record_version(identity, b'independent health source', 'fulltext', {}, {},
        {'index_allowed': True, 'license_id': 'CC0'}, 'matched',
        [{'text': 'Resting heart rate measurement protocol comparison with individual baseline.', 'locator': {'section': 'Methods'}}], 'fixture')
    sid = vid + ':s00000'
    kb.review_claim({'claim_id': identity, 'version': '1', 'statement': 'Recording conditions affect what comparisons represent.',
        'scope': {'explanation_purpose': 'measurement_context'}, 'limitations': ['No cause or threshold.'],
        'conditions': [{'field': 'age', 'op': 'range', 'min': 18, 'max': 60, 'origin': 'source_scope'}] if age_condition else [],
        'evidence_links': [{'source_id': identity, 'source_version_id': vid, 'span_ids': [sid]}]}, REVIEW)
    vector_index.register_spans(kb, vid, ['recovery', 'wearable'], assignment_status='content_checked')
    domains.link(kb, origin={'type': 'claim', 'id': identity, 'version': '1'}, relation='limits',
        target={'type': 'metric', 'id': 'STATE-RHR', 'version': domains.profile_version('STATE-RHR')}, span_ids=[sid],
        applicability={}, actor='Synthetic', rationale='Independent software fixture', evidence_types=['scope_limit'], review=REVIEW)


def answer_for(card):
    return {'summary': card['summary'], 'evidence_ids': [card['id']],
            'facts': [{'evidence_id': card['id'], **card['facts'][0]}],
            'limitations': card['limitations'], 'actions': card['allowed_actions']}


@pytest.mark.parametrize('field,incorrect', [('value', 62), ('unit', 'ms'), ('window', {'start': '2026-10-01'}),
    ('fact_id', 'other-window'), ('recorded_days', 0), ('dates', ['2026-10-08']), ('statistic_kind', 'mean')])
def test_same_id_binds_number_unit_window_coverage_and_actual_dates(field, incorrect):
    cards = comparison_cards(metric())
    payload = build_evidence_payload({'cards': cards})
    answer = answer_for(cards[0])
    assert validate_ai_result(answer, payload)['source'] == 'ai'
    answer['facts'][0][field] = incorrect
    with pytest.raises(ValueError, match='evidence validation'):
        validate_ai_result(answer, payload)


def test_model_cannot_relabel_supplied_day_as_missing_or_swap_direction():
    cards = comparison_cards(metric())
    payload = build_evidence_payload({'cards': cards})
    answer = answer_for(cards[0])
    answer['summary'] = '2026-10-09 没有记录。'
    with pytest.raises(ValueError):
        validate_ai_result(answer, payload)
    answer = answer_for(cards[-1])
    answer['facts'][0]['direction'] = 'decrease'
    with pytest.raises(ValueError):
        validate_ai_result(answer, payload)


@pytest.mark.parametrize('age,accepted', [(None, False), (34, True), (12, False), (74, False)])
def test_age_scope_is_matched_from_actual_age_without_default_adult(kb, age, accepted):
    source(kb, age_condition=True)
    response = kb.explain_metric('STATE-RHR', 'explain_metric', metric(),
        {} if age is None else {'age': age}, mode='lexical', candidate_scope='reviewed_metric')
    assert bool(response['measurement_explanations']) is accepted
    assert response['deterministic_observations'] and response['local_next_steps']
    assert not response['evidence_context']['capability_permissions']['source_explanation']
    assert not response['evidence_context']['capability_permissions']['candidate']


def test_unknown_protocol_allows_only_explicitly_reviewed_measurement_context(kb):
    source(kb)
    response = kb.explain_metric('STATE-RHR', 'explain_metric', metric(), {}, mode='lexical', candidate_scope='reviewed_metric')
    assert response['measurement_explanations'][0]['individual_cause_authority'] is False
    assert response['measurement_explanations'][0]['sources'][0]['canonical_url'].startswith('https://')
    assert response['explanation']['reason_code'] == 'network_disabled'
    assert not response['evidence_context']['capability_permissions']['source_explanation']
    assert len(response['deterministic_observations']) == 3


def test_retrieval_reuses_method_across_windows_and_rejects_revocation(kb):
    source(kb)
    first = kb.retrieve_for_metric('STATE-RHR', 'explain_metric', metric(), {}, mode='lexical', candidate_scope='reviewed_metric')
    other = deepcopy(metric())
    other['comparison']['streams'][0]['current']['value'] = 77
    second = kb.retrieve_for_metric('STATE-RHR', 'explain_metric', other,
        {'observed_dates': ['2026-10-14'], 'notes': 'PRIVATE-ONLY'}, mode='lexical', candidate_scope='reviewed_metric')
    assert second['retrieval_audit']['cache_hit']
    assert first['retrieval_audit']['audit_id'] != second['retrieval_audit']['audit_id']
    assert 'PRIVATE-ONLY' not in json.dumps(second)
    kb.core_state('claim', 'measurement-fixture', '1', 'revoked', actor='Synthetic', rationale='Withdrawal')
    revoked = kb.explain_metric('STATE-RHR', 'explain_metric', other, {}, mode='lexical', candidate_scope='reviewed_metric')
    assert not revoked['measurement_explanations']
    assert revoked['deterministic_observations']


def test_public_needs_are_generic_and_contain_no_private_values_or_dates():
    needs = ' '.join(public_method_needs(metric()))
    assert 'missing days' in needs
    assert '68' not in needs and '2026' not in needs


def test_failure_reason_is_local_and_observations_survive(monkeypatch):
    analysis = {'cards': comparison_cards(metric())}
    off = explain_analysis(analysis, allow_network=False)
    assert off['reason_code'] == 'network_disabled' and '68 bpm' in off['summary']
    monkeypatch.setattr('healthzip.ai.client.AIConfig.from_env', lambda: None)
    missing = explain_analysis(analysis, allow_network=True)
    assert missing['reason_code'] == 'not_configured' and '68 bpm' in missing['summary']
    def timeout(*args, **kwargs):
        raise TimeoutError('private transport detail')
    monkeypatch.setattr('healthzip.ai.client.urlopen', timeout)
    failed = explain_analysis(analysis, allow_network=True, config=AIConfig('https://example.invalid', 'test', 'test'))
    assert failed['reason_code'] == 'TimeoutError' and '68 bpm' in failed['summary']
    assert 'private transport detail' not in json.dumps(failed)


def test_jats_comments_are_removed_without_losing_parent_tail_or_scope():
    raw = b'<article><front><article-meta><title-group><article-title>Synthetic</article-title></title-group></article-meta></front><body><p>Before<!-- invisible --> after.</p></body></article>'
    _, spans, _ = parse_jats(raw)
    assert spans[0]['text'] == 'Before after.'


def test_invalid_number_falls_back_locally_with_specific_reason(monkeypatch):
    cards = comparison_cards(metric())
    answer = answer_for(cards[0])
    answer['facts'][0]['value'] = 999

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({'choices': [{'message': {'content': json.dumps(answer)}}]}).encode()

    monkeypatch.setattr('healthzip.ai.client.urlopen', lambda *args, **kwargs: Response())
    result = explain_analysis({'cards': cards}, allow_network=True, config=AIConfig('https://example.invalid', 'test', 'test'))
    assert result['reason_code'] == 'validation_failed'
    assert '68 bpm' in result['summary'] and '999' not in result['summary']


def test_no_matching_evidence_keeps_exact_observations(kb):
    result = kb.explain_metric('STATE-RHR', 'explain_metric', metric(), {}, mode='lexical', candidate_scope='reviewed_metric')
    assert result['evidence_context']['status'] == 'insufficient_evidence'
    assert result['deterministic_observations'][0]['facts'][0]['dates'] == ['2026-10-09', '2026-10-13']
    assert '68 bpm' in result['explanation']['summary']


def test_frozen_release_does_not_silently_acquire_new_measurement_claims(kb):
    from healthzip.knowledge.metric_retrieval import freeze_index
    freeze_index(kb, 'before-source')
    source(kb)
    result = kb.explain_metric('STATE-RHR', 'explain_metric', metric(), {}, release_id='before-source',
                               mode='lexical', candidate_scope='reviewed_metric')
    assert not result['measurement_explanations']
    assert result['deterministic_observations']


@pytest.mark.parametrize('protocol,expected', [('context:{"sampling_mode":"background"}', None),
    ('unknown', None), ('morning-protocol;context:{"sampling_mode":"active"}', 'morning-protocol'), (None, None)])
def test_grouping_context_never_claims_a_measurement_protocol(protocol, expected):
    from healthzip.workflows.evidence import local_context
    computed = metric()
    computed['comparison']['streams'][0]['protocol'] = ['synthetic', 'watch', protocol]
    assert local_context('STATE-RHR', computed, [], {'values': {}})['measurement_protocol'] == expected
