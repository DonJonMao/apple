"""Reported RIR evidence and manuscript citations keep their actual identities."""
import json

import pytest
from test_v15_retrieval import CONTEXT, add

from healthzip.knowledge import metric_retrieval, vector_index
from healthzip.science import evaluate


def computed(rows):
    return evaluate('STR-10', [
        {'id': f'synthetic-{i}', 'event_end': '2026-11-10T10:00:00+00:00',
         'available_at': '2026-11-10T10:01:00+00:00', **row} for i, row in enumerate(rows)],
        cutoff_time='2026-11-15T00:00:00+00:00', window_start='2026-11-01T00:00:00+00:00',
        window_end='2026-11-15T00:00:00+00:00')


@pytest.mark.parametrize('rows,supported', [
    ([{'rir': 2}], True),
    ([{'rir': 0, 'rpe': 8, 'scale_type': 'rir_based_rpe_6_10'}], True),
    ([{'rir': None, 'rpe': 8, 'scale_type': 'rir_based_rpe_6_10'}], False),
    ([{'rpe': 8, 'scale_type': 'cr10'}], False),
    ([{'rir': 2}, {'rpe': 8, 'scale_type': 'rir_based_rpe_6_10'}], False),
    ([{'rir_interval': {'lower': 3, 'upper': None}}], False),
    ([{'rir': float('nan')}], False),
    ([], False),
])
def test_computed_record_identity_controls_claim_eligibility_before_models(kb, rows, supported):
    add(kb, mid='STR-10', conditions=[{'field': 'metric_evidence.direct_rir_only',
        'op': 'eq', 'value': True, 'origin': 'measurement_contract'}])
    context = {**CONTEXT, 'metric_evidence': {'direct_rir_only': True}}

    class Forbidden:
        def __getattr__(self, key):
            pytest.fail('Rejected RIR identity must not invoke models')

    response = kb.retrieve_for_metric('STR-10', 'strength', computed(rows), context,
        mode='lexical' if supported else 'hybrid_rerank', candidate_scope='reviewed_metric',
        services=(Forbidden(), Forbidden()))
    assert response['capability_permissions']['source_explanation'] is supported
    assert response['status'] == ('evidence_context_supported' if supported else 'insufficient_evidence')
    assert not response['capability_permissions']['candidate']
    assert context['metric_evidence'] == {'direct_rir_only': True}
    assert response['retrieval_audit']['metric_evidence_context_version'] == metric_retrieval.METRIC_EVIDENCE_CONTEXT_VERSION


@pytest.mark.parametrize('value,expected', [
    ({'rir_before': 2, 'rir_after': 3}, True),
    ({'rir_before': 2, 'rir_after': None}, False),
    ({'rir_before': True, 'rir_after': 3}, False),
    ({'rir_before': 2, 'rir_after': float('inf')}, False),
    ({'rir_before': 2, 'rir_after': 3, 'comparison_series': [
        {'value': {'rir_before': 1, 'rir_after': 2}}, {'value': None}]}, False),
    ({'rir_before': 2, 'rir_after': 3, 'comparison_series': [
        {'value': {'rir_before': 1, 'rir_after': 2}}]}, True),
    (None, False),
])
def test_all_displayed_rir_comparisons_require_observed_values(value, expected):
    assert metric_retrieval._direct_rir_only('STR-14', value) is expected


def test_preprint_and_published_versions_keep_separate_citations_in_frozen_index(kb):
    kb.lib.seed({'sources': [{'source_id': 'manuscript', 'title': 'Synthetic published work',
        'year': 2022, 'canonical_url': 'https://example.invalid/published',
        'corpus_roles': ['research']}]}, {'cards': []})
    version_ids = []
    for name, metadata in [
        ('preprint', {'bibliographic_version': {'title': 'Synthetic author manuscript', 'year': 2021,
            'canonical_url': 'https://example.invalid/preprint', 'publication_stage': 'author_preprint',
            'version_label': 'preprint v1; file v4', 'unrelated_private_key': 'must stay local'}}),
        ('published', {}),
        ('malformed', {'bibliographic_version': 'not a citation object'}),
    ]:
        vid = kb.lib.record_version('manuscript', name.encode(), 'fulltext', {}, metadata,
            {'index_allowed': True, 'license_id': 'CC0'}, 'matched',
            [{'text': name + ' synthetic public text', 'locator': {'page': 1}}], 'fixture')
        vector_index.register_spans(kb, vid, ['strength'])
        version_ids.append(vid)
    metric_retrieval.freeze_index(kb, 'version-citation-freeze')
    candidates, _, _, _ = metric_retrieval.eligible_candidates(kb, ['strength'], CONTEXT, 'version-citation-freeze')
    citations = {c['source_version']: c['source_metadata'] for c in candidates}
    preprint = citations[version_ids[0]]
    assert preprint['year'] == 2021 and preprint['publication_stage'] == 'author_preprint'
    assert preprint['canonical_url'] == 'https://example.invalid/preprint'
    assert preprint['canonical_work_url'] == 'https://example.invalid/published'
    for vid in version_ids[1:]:
        assert citations[vid]['year'] == 2022
        assert citations[vid]['canonical_url'] == 'https://example.invalid/published'
        assert 'publication_stage' not in citations[vid]
    assert 'must stay local' not in json.dumps(candidates)
    assert kb.lib.source('manuscript')['manifest']['year'] == 2022


def test_frozen_computed_identity_semantics_cannot_silently_change(kb, monkeypatch):
    metric_retrieval.freeze_index(kb, 'computed-identity-freeze')
    monkeypatch.setattr(metric_retrieval, 'METRIC_EVIDENCE_CONTEXT_VERSION', 'changed')
    with pytest.raises(ValueError, match='frozen_metric_evidence_context_changed'):
        kb.retrieve_for_metric('STR-10', 'strength', computed([{'rir': 2}]), CONTEXT,
            'computed-identity-freeze', mode='lexical')
