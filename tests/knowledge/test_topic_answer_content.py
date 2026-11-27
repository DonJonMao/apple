"""An answered purpose is not an answered scoped question; budgets and gates remain."""
import json
from copy import deepcopy

import pytest

from healthzip.knowledge import KnowledgeWorkbench, domains, topics
from tests.integration.test_followup_report_evidence import REVIEW, claim, edge

TOPIC = 'BODY-OBS-hrv_sdnn_ms'
NEED = 'hrv_direction_and_training_response'


@pytest.fixture
def library(tmp_path):
    kb = KnowledgeWorkbench(tmp_path / 'public-synthetic', environment_kind='synthetic_test')
    yield kb
    kb.close()


def bind(kb, identity, sid, *, scope=None, complete=True, need_id=NEED):
    need = topics.ANSWER_NEEDS[need_id]
    binding = {key: deepcopy(need[key]) for key in ('question', 'target_claim')}
    binding.update(relation='supports', rationale='Synthetic content check with exact original evidence',
                   answer_complete=complete, target_coverage_complete=True)
    return domains.link(kb, origin={'type': 'claim', 'id': identity, 'version': '1'}, relation='applies_to',
        target={'type': 'metric', 'id': TOPIC, 'version': domains.profile_version(TOPIC)}, span_ids=[sid],
        applicability=scope or {}, actor='Synthetic', rationale='Exact question within the already reviewed metric use',
        evidence_types=['mechanism_or_exception', 'action_or_reassessment'], review=REVIEW, answer_bindings=[binding])


def fixture_claims(kb, **kwargs):
    claim(kb, 'a-general-method', topics.PURPOSES, topic=TOPIC)
    claim(kb, 'b-other-method', topics.PURPOSES, topic=TOPIC)
    sid = claim(kb, 'z-specific-answer', ['mechanism_or_exception', 'action_or_reassessment'], topic=TOPIC)
    bind(kb, 'z-specific-answer', sid, **kwargs)
    return sid


def test_content_gap_is_recalled_when_all_purpose_tags_were_already_present(library):
    fixture_claims(library)
    result = topics.question_sources(library, TOPIC, k=2, include_evidence=True)
    audit = result['retrieval']
    assert audit['initial_missing_purposes'] == []
    assert NEED in audit['initial_missing_answers']
    assert audit['supplemental_pass']['answer_needs']['reason'] == 'missing_reviewed_answer_target'
    assert audit['supplemental_pass']['requested_k'] == 2
    assert audit['selected_unique_spans'] <= audit['maximum_unique_spans'] == 4
    assert audit['supplemental_remote_calls'] == 0
    assert audit['answer_status'][NEED]['status'] == 'available'
    selected = [i for i in result['items'] if i['claim_id'] == 'z-specific-answer']
    assert len(selected) == 1  # Two immutable application edges do not duplicate prose.
    assert selected[0]['citations'] and selected[0]['limitations']
    assert len(result['evidence_spans']) == len({s['span_id'] for s in result['evidence_spans']})


@pytest.mark.parametrize('options', [{'scope': {'device': 'other-device'}}, {'complete': False}])
def test_inapplicable_or_incomplete_binding_does_not_claim_an_answer(library, options):
    fixture_claims(library, **options)
    result = topics.question_sources(library, TOPIC, k=2, context={'device': 'actual-device'})
    assert result['retrieval']['answer_status'][NEED]['status'] == 'no_current_applicable_reviewed_answer'
    assert result['retrieval']['supplemental_pass'] is None
    assert result['items']  # Independent methods still answer their real uses.


def test_conflicted_specific_answer_is_local_and_keeps_the_independent_method(library):
    sid = fixture_claims(library)
    rival = claim(library, 'rival', [], bind=False)
    edge(library, 'z-specific-answer', 'rival', 'conflicts_with', [sid, rival])
    result = topics.question_sources(library, TOPIC, k=2)
    assert result['retrieval']['answer_status'][NEED]['status'] == 'locally_conflicted'
    assert any(i['claim_id'] == 'a-general-method' for i in result['items'])
    assert any(i['claim_id'] == 'z-specific-answer' for i in result['restricted_items'])


@pytest.mark.parametrize('gate', ['revoked', 'source_withdrawn', 'rights'])
def test_content_recall_never_bypasses_current_authority_or_rights(library, gate):
    sid = fixture_claims(library)
    if gate == 'revoked':
        with library.lib.theories:
            library.lib.theories.execute("UPDATE source_claim SET status='revoked' WHERE claim_id='z-specific-answer'")
    elif gate == 'source_withdrawn':
        library.lib.update_state('z-specific-answer', 'withdrawn', 'Synthetic withdrawal')
    else:
        with library.lib.sources:
            library.lib.sources.execute('UPDATE version SET rights_json=? WHERE version_id=?',
                (json.dumps({'license_id': 'CC-BY-NC', 'index_allowed': True}), sid.rsplit(':s', 1)[0]))
    result = topics.question_sources(library, TOPIC, k=2, context={'usage_scope': 'commercial'})
    assert result['retrieval']['answer_status'][NEED]['status'] == 'no_current_applicable_reviewed_answer'
    assert all(i['claim_id'] != 'z-specific-answer' for i in result['items'])
    assert result['items']


def test_unrelated_topic_and_measurement_only_answer_do_not_trigger_the_content_pass(library):
    fixture_claims(library)
    result = topics.question_sources(library, TOPIC, k=2, required_purposes=['measurement'])
    assert NEED not in result['retrieval']['answer_status']
    assert result['retrieval']['supplemental_pass'] is None
    assert topics.question_sources(library, 'W1')['retrieval']['answer_status'] == {}


def test_two_substantive_answers_share_one_supplement_budget(library):
    fixture_claims(library)
    device = claim(library, 'z-protocol-answer', ['measurement', 'comparison'], topic=TOPIC)
    bind(library, 'z-protocol-answer', device, need_id='wearable_hrv_protocol_transfer')
    result = topics.question_sources(library, TOPIC, k=2)
    audit = result['retrieval']
    assert all(answer['status'] == 'available' for answer in audit['answer_status'].values())
    assert audit['selected_unique_spans'] == audit['maximum_unique_spans'] == 4
    assert audit['supplemental_pass']['requested_k'] == 2
    assert set(audit['supplemental_pass']['answer_needs']['ids']) == set(topics.ANSWER_NEEDS)


def test_complete_required_premises_are_not_cut_to_fit_an_answer(library):
    sid = fixture_claims(library)
    p = claim(library, 'prerequisite-one', [], bind=False)
    q = claim(library, 'prerequisite-two', [], bind=False)
    edge(library, 'prerequisite-one', 'z-specific-answer', 'required_by', [p, sid])
    edge(library, 'prerequisite-two', 'z-specific-answer', 'required_by', [q, sid])
    result = topics.question_sources(library, TOPIC, k=2)
    assert result['retrieval']['answer_status'][NEED]['status'] == 'complete_group_budget_or_rank'
    assert all(i['claim_id'] != 'z-specific-answer' for i in result['items'])
    assert result['items']
