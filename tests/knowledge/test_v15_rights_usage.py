"""Usage gates consume actual scoped license grants, including historical JATS."""
import json

import pytest
from lxml import etree
from test_v15_retrieval import CONTEXT, Embed, Rank, add, result

from healthzip.knowledge import domains, metric_retrieval, rights, vector_index


def grant(label='by-nc-nd'):
    # The parser used by existing real JATS records does not add the later flag.
    article = etree.fromstring((
        '<article><front><article-meta><permissions><license>'
        f'https://creativecommons.org/licenses/{label}/4.0/'
        '</license></permissions></article-meta></front></article>').encode())
    parsed = rights.rights_from_xml(article)
    assert 'noncommercial_only' not in parsed and parsed['index_allowed']
    return parsed


def set_grant(kb, sid, value):
    with kb.lib.sources:
        kb.lib.sources.execute('UPDATE span SET scope_rights_json=? WHERE span_id=?',
                               (json.dumps(value), sid))


@pytest.mark.parametrize('label', ['by-nc', 'by-nc-sa', 'by-nc-nd'])
@pytest.mark.parametrize('scope', ['all', 'reviewed_metric'])
def test_historical_nc_grants_never_reach_models_in_commercial_context(kb, label, scope):
    _, sid = add(kb)
    set_grant(kb, sid, grant(label))
    metric_retrieval.freeze_index(kb, 'frozen-before-usage-fix')

    class Forbidden:
        def __getattr__(self, key):
            pytest.fail('No embedding or reranking of ineligible licensed content')

    denied = kb.retrieve_for_metric('STR-12', 'strength', result(),
        {**CONTEXT, 'usage_scope': 'commercial'}, 'frozen-before-usage-fix',
        mode='hybrid_rerank', candidate_scope=scope, services=(Forbidden(), Forbidden()))
    assert denied['status'] == 'insufficient_evidence'
    assert not denied['evidence_spans'] and not denied['matched_claims']
    assert 'noncommercial_scope_required' in str(denied['retrieval_audit']['excluded'])
    assert denied['retrieval_audit']['rights_usage_policy_version'] == rights.USAGE_POLICY_VERSION
    local = kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT,
        'frozen-before-usage-fix', mode='lexical', candidate_scope=scope)
    assert local['status'] == 'evidence_context_supported'
    assert local['evidence_spans'][0]['rights_status']['noncommercial_only'] is True


def test_component_nc_overrides_permissive_article_and_false_convenience_flag(kb):
    _, sid = add(kb)  # Version-level CC0 grant.
    scoped = {**grant(), 'noncommercial_only': False}
    set_grant(kb, sid, scoped)
    denied = kb.retrieve_for_metric('STR-12', 'strength', result(),
        {**CONTEXT, 'usage_scope': 'commercial'}, mode='lexical')
    assert not denied['evidence_spans']
    assert rights.noncommercial_only(scoped)


@pytest.mark.parametrize('value', [
    {'license_id': 'CC-BY-NC-ND-4.0'},
    {'license_id': 'CC BY NC 4.0'},
    {'license_candidates': ['CC-BY-NC']},
    {'license_url': 'https://creativecommons.org/licenses/by-nc-sa/4.0/'},
    {'license_id': 'CC-BY', 'license_candidates': ['CC-BY-NC'], 'noncommercial_only': False},
])
def test_nc_declarations_cannot_be_relaxed_by_missing_or_inconsistent_flags(value):
    assert rights.usage_rejection(value, 'commercial') == 'noncommercial_scope_required'
    assert rights.usage_rejection(value) is None


@pytest.mark.parametrize('value', [
    {'license_id': 'CC0'}, {'license_id': 'CC-BY-4.0'},
    {'license_id': 'CC-BY-SA'}, {'license_id': 'CC-BY-ND'},
    {'license_id': 'US-government-work', 'noncommercial_only': False},
])
def test_explicit_broader_grants_remain_available(value):
    assert rights.usage_rejection(value, 'commercial') is None


def test_local_text_mining_permission_does_not_invent_commercial_clearance(kb):
    _, sid = add(kb)
    set_grant(kb, sid, {'index_allowed': True, 'license_id': 'PMC-explicit-text-mining-notice'})
    denied = kb.retrieve_for_metric('STR-12', 'strength', result(),
        {**CONTEXT, 'usage_scope': 'commercial'}, mode='lexical')
    assert not denied['evidence_spans']
    assert 'usage_scope_not_cleared' in str(denied['retrieval_audit']['excluded'])
    assert kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT)['evidence_spans']


def test_grant_changed_during_remote_ranking_is_rechecked_before_return(kb):
    _, sid = add(kb)
    embed = Embed()
    vector_index.build_vectors(kb, embed)

    class RestrictDuringRanking(Rank):
        def post(self, payload):
            response = super().post(payload)
            set_grant(kb, sid, grant())
            return response

    denied = kb.retrieve_for_metric('STR-12', 'strength', result(),
        {**CONTEXT, 'usage_scope': 'commercial'}, mode='hybrid_rerank',
        services=(embed, RestrictDuringRanking()))
    assert denied['status'] == 'insufficient_evidence'
    assert not denied['evidence_spans'] and not denied['matched_claims']


def test_commercial_conflict_screen_does_not_use_excluded_nc_claim(kb):
    _, first = add(kb, 'allowed')
    _, other = add(kb, 'nc', bind=False)
    set_grant(kb, other, grant())
    domains.link(kb, origin={'type': 'claim', 'id': 'allowed', 'version': '1'}, relation='conflicts_with',
        target={'type': 'claim', 'id': 'nc', 'version': '1'}, span_ids=[first, other],
        applicability={}, actor='Synthetic', rationale='Synthetic rights-isolated conflict')
    local = kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, mode='lexical')
    assert local['conflicts'] and local['status'] == 'insufficient_evidence'
    commercial = kb.retrieve_for_metric('STR-12', 'strength', result(),
        {**CONTEXT, 'usage_scope': 'commercial'}, mode='lexical')
    assert not commercial['conflicts'] and commercial['status'] == 'evidence_context_supported'
    assert other not in json.dumps(commercial['evidence_spans'])


def test_nc_prerequisite_cannot_be_bypassed_by_permissive_dependent_claim(kb):
    _, direct = add(kb, 'allowed')
    _, prerequisite = add(kb, 'required-nc', bind=False)
    set_grant(kb, prerequisite, grant())
    domains.link(kb, origin={'type': 'claim', 'id': 'required-nc', 'version': '1'}, relation='required_by',
        target={'type': 'claim', 'id': 'allowed', 'version': '1'}, span_ids=[direct, prerequisite],
        applicability={}, actor='Synthetic', rationale='Synthetic explicit dependency')
    denied = kb.retrieve_for_metric('STR-12', 'strength', result(),
        {**CONTEXT, 'usage_scope': 'commercial'}, mode='lexical', candidate_scope='reviewed_metric')
    assert denied['status'] == 'insufficient_evidence' and not denied['matched_claims']
    assert not denied['evidence_spans']
