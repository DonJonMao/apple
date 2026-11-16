"""Explicit reviewed-metric scope separates source reading from inference evidence."""
import json

import pytest
from test_v15_ranked_coverage import add_group, metric_result
from test_v15_retrieval import CONTEXT, REVIEW, Embed, Rank, add, result

from healthzip.knowledge import domains, metric_retrieval, vector_index
from healthzip.knowledge.store import digest, dumps


@pytest.mark.parametrize('mode', sorted(metric_retrieval.MODES))
def test_no_complete_metric_binding_never_invokes_models(kb, mode):
    add(kb, bind=False)

    class Forbidden:
        def __getattr__(self, key):
            pytest.fail('Unbound reading material must not trigger public evidence models')

    answer = kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, mode=mode,
        candidate_scope='reviewed_metric', services=(Forbidden(), Forbidden()))
    assert answer['status'] == 'insufficient_evidence' and not answer['evidence_spans']
    assert answer['limitations'] == ['no_complete_reviewed_metric_group']
    assert answer['retrieval_audit']['metric_candidate_scope']['background_candidates_excluded'] == 1
    assert not answer['capability_permissions']['candidate']


def test_reviewed_groups_are_ranked_before_unbound_background_can_consume_budget(kb, monkeypatch):
    ids, group = add_group(kb)
    # Twenty-one other same-domain documents precede every reviewed group anchor.
    for index in range(21):
        _, sid = add(kb, f'background{index:02}', bind=False)
        ids.insert(0, sid)
    monkeypatch.setattr(metric_retrieval, '_lexical',
        lambda query, candidates: [sid for sid in ids if sid in {c['span_id'] for c in candidates}])
    baseline = kb.retrieve_for_metric('STR-12', 'strength', metric_result(), CONTEXT, mode='lexical', k=3)
    scoped = kb.retrieve_for_metric('STR-12', 'strength', metric_result(), CONTEXT,
        mode='lexical', k=3, candidate_scope='reviewed_metric')
    assert baseline['status'] == 'insufficient_evidence'
    assert {s['span_id'] for s in scoped['evidence_spans']} == set(group)
    assert scoped['status'] == 'evidence_context_supported'
    assert scoped['retrieval_audit']['evidence_selection']['span_budget'] == 3
    assert scoped['retrieval_audit']['eligible_candidate_count'] == 3
    too_small = kb.retrieve_for_metric('STR-12', 'strength', metric_result(), CONTEXT,
        mode='lexical', k=2, candidate_scope='reviewed_metric')
    assert too_small['status'] == 'insufficient_evidence' and not too_small['matched_claims']
    assert len(too_small['evidence_spans']) <= 2
    assert not scoped['capability_permissions']['candidate']
    assert baseline['query_id'] != scoped['query_id']
    assert baseline['query_id'] == digest(dumps(['STR-12', 'strength', domains.profile_version('STR-12'), None]).encode())


def test_public_models_receive_only_scoped_evidence_and_fixed_queries(kb):
    _, bound = add(kb, 'bound')
    _, unbound = add(kb, 'unbound', bind=False)
    embed, rank = Embed(), Rank()
    vector_index.build_vectors(kb, embed)
    embed.calls.clear()
    response = kb.explain_metric('STR-12', 'strength', result(),
        {**CONTEXT, 'notes': 'PRIVATE-SCOPE-34923', 'health_values': [349.23987]},
        candidate_scope='reviewed_metric', mode='hybrid_rerank', services=(embed, rank))
    found = response['evidence_context']
    assert found['status'] == 'evidence_context_supported'
    sent = json.loads(rank.calls[0]['messages'][1]['content'])
    assert {c['candidate_id'] for c in sent['candidates']} == {bound}
    assert unbound not in json.dumps(rank.calls)
    assert 'PRIVATE-SCOPE-34923' not in json.dumps(embed.calls + rank.calls)
    assert '349.23987' not in json.dumps(embed.calls + rank.calls)
    assert response['explanation']['source'] == 'local_fallback'


@pytest.mark.parametrize('state', ['revoked', 'unknown_claim_condition', 'provisional_unit', 'edge_mismatch'])
def test_scope_cannot_restore_rejected_or_unreviewed_inference(kb, state):
    add(kb, conditions=[{'field': 'protocol', 'op': 'eq', 'value': 'exact', 'origin': 'measurement_contract'}]
        if state == 'unknown_claim_condition' else None,
        status='provisional' if state == 'provisional_unit' else 'content_checked')
    if state == 'revoked':
        kb.core_state('claim', 'first', '1', 'revoked', actor='Synthetic', rationale='Synthetic revocation')
    context = {**CONTEXT, 'population': 'trained_adults'} if state == 'edge_mismatch' else CONTEXT
    answer = kb.retrieve_for_metric('STR-12', 'strength', result(), context,
        mode='lexical', candidate_scope='reviewed_metric')
    assert answer['status'] == 'insufficient_evidence'
    assert not answer['matched_claims'] and not answer['capability_permissions']['source_explanation']


def test_scoped_candidate_filter_keeps_conflicts_with_nonselected_claims(kb):
    _, first = add(kb, 'a')
    _, other = add(kb, 'z', bind=False)
    domains.link(kb, origin={'type': 'claim', 'id': 'a', 'version': '1'}, relation='conflicts_with',
        target={'type': 'claim', 'id': 'z', 'version': '1'}, span_ids=[first, other],
        applicability={}, actor='Synthetic', rationale='Synthetic conflict')
    answer = kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT,
        mode='lexical', k=1, candidate_scope='reviewed_metric')
    assert [s['span_id'] for s in answer['evidence_spans']] == [first]
    assert answer['conflicts'] and answer['status'] == 'insufficient_evidence'


@pytest.mark.parametrize('state', ['verified', 'revoked', 'unknown_applicability'])
def test_scope_closes_explicit_prerequisites_without_relaxing_eligibility(kb, monkeypatch, state):
    ids, group = add_group(kb, count=1)
    kb.review_claim({'claim_id': 'prerequisite', 'version': '1', 'statement': 'Synthetic prerequisite.',
        'scope': {'synthetic': True}, 'conditions': [], 'limitations': ['Prerequisite restriction'],
        'evidence_links': [{'source_id': 'group-fixture', 'source_version_id': kb.lib.span(ids[-1])['version_id'],
                            'span_ids': [ids[-1]]}]}, REVIEW)
    domains.link(kb, origin={'type': 'claim', 'id': 'prerequisite', 'version': '1'}, relation='required_by',
        target={'type': 'claim', 'id': 'group-definition', 'version': '1'}, span_ids=[ids[0], ids[-1]],
        applicability={'protocol': 'required'} if state == 'unknown_applicability' else {},
        actor='Synthetic', rationale='Explicit synthetic prerequisite')
    if state == 'revoked':
        kb.core_state('claim', 'prerequisite', '1', 'revoked', actor='Synthetic', rationale='Synthetic revocation')
    monkeypatch.setattr(metric_retrieval, '_lexical', lambda query, candidates: [c['span_id'] for c in candidates])
    answer = kb.retrieve_for_metric('STR-12', 'strength', metric_result(), CONTEXT,
        mode='lexical', k=2, candidate_scope='reviewed_metric')
    if state == 'verified':
        assert {s['span_id'] for s in answer['evidence_spans']} == {group[0], ids[-1]}
        assert answer['status'] == 'evidence_context_supported'
        assert 'Prerequisite restriction' in answer['matched_claims'][0]['limitations']
    else:
        assert answer['status'] == 'insufficient_evidence' and not answer['matched_claims']


def test_new_scope_requires_explicit_frozen_identity_and_rejects_drift(kb, monkeypatch):
    add(kb)
    metric_retrieval.freeze_index(kb, 'new')
    manifest = json.loads(kb.lib.sources.execute("SELECT manifest_json FROM index_release WHERE release_id='new'").fetchone()[0])
    assert manifest.pop('candidate_scope_version') == metric_retrieval.CANDIDATE_SCOPE_VERSION
    old = dumps(manifest)
    with kb.lib.sources:
        kb.lib.sources.execute('INSERT INTO index_release VALUES(?,?,?,?)', ('old', old, digest(old.encode()), '2026-11-17'))
    default = kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, 'old', mode='lexical')
    assert default['status'] == 'evidence_context_supported'
    with pytest.raises(ValueError, match='frozen_release_does_not_pin_candidate_scope'):
        kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, 'old', mode='lexical', candidate_scope='reviewed_metric')
    current = kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, 'new', mode='lexical', candidate_scope='reviewed_metric')
    assert current['status'] == 'evidence_context_supported'
    with pytest.raises(ValueError, match='unknown_metric_candidate_scope'):
        kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, candidate_scope='PRIVATE free text')
    monkeypatch.setattr(metric_retrieval, 'CANDIDATE_SCOPE_VERSION', 'changed')
    with pytest.raises(ValueError, match='frozen_candidate_scope_configuration_changed'):
        kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, 'new', mode='lexical')
