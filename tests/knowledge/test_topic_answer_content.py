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


def bind(kb, identity, sid, *, scope=None, complete=True, need_id=NEED, topic=TOPIC):
    need = topics.ANSWER_NEEDS[need_id]
    binding = {key: deepcopy(need[key]) for key in ('question', 'target_claim')}
    binding.update(relation='supports', rationale='Synthetic content check with exact original evidence',
                   answer_complete=complete, target_coverage_complete=True)
    return domains.link(kb, origin={'type': 'claim', 'id': identity, 'version': '1'}, relation='applies_to',
        target={'type': 'metric', 'id': topic, 'version': domains.profile_version(topic)}, span_ids=[sid],
        applicability=scope or {}, actor='Synthetic', rationale='Exact question within the already reviewed metric use',
        evidence_types=need['purposes'], review=REVIEW, answer_bindings=[binding])


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
    assert topics.question_sources(library, 'W8')['retrieval']['answer_status'] == {}


def test_two_substantive_answers_share_one_supplement_budget(library):
    fixture_claims(library)
    device = claim(library, 'z-protocol-answer', ['measurement', 'comparison'], topic=TOPIC)
    bind(library, 'z-protocol-answer', device, need_id='wearable_hrv_protocol_transfer')
    result = topics.question_sources(library, TOPIC, k=2)
    audit = result['retrieval']
    expected = {NEED, 'wearable_hrv_protocol_transfer'}
    assert all(audit['answer_status'][key]['status'] == 'available' for key in expected)
    assert audit['selected_unique_spans'] == audit['maximum_unique_spans'] == 4
    assert audit['supplemental_pass']['requested_k'] == 2
    assert set(audit['supplemental_pass']['answer_needs']['ids']) == expected


@pytest.mark.parametrize('need_id', [
    'hrv_missing_observation_unit', 'repetition_load_population_transfer',
    'measured_estimated_1rm_reliability', 'watch_oxygen_agreement_scope',
    'watch_steps_validation_scope', 'watch_night_vital_validation_scope',
])
def test_specific_measurement_answers_do_not_hide_behind_generic_purpose_coverage(library, need_id):
    need = topics.ANSWER_NEEDS[need_id]
    topic = need['topics'][0]
    claim(library, 'a-general-method', topics.PURPOSES, topic=topic)
    claim(library, 'b-general-method', topics.PURPOSES, topic=topic)
    sid = claim(library, 'z-source-specific-limit', need['purposes'], topic=topic)
    bind(library, 'z-source-specific-limit', sid, need_id=need_id, topic=topic)
    result = topics.question_sources(library, topic, k=2, include_evidence=True)
    audit = result['retrieval']
    assert audit['initial_missing_purposes'] == []
    assert need_id in audit['initial_missing_answers']
    assert audit['answer_status'][need_id]['status'] == 'available'
    assert audit['selected_unique_spans'] <= audit['maximum_unique_spans'] == 4
    assert audit['supplemental_remote_calls'] == 0
    chosen = next(item for item in result['items'] if item['claim_id'] == 'z-source-specific-limit')
    assert chosen['citations'][0]['span_id'] == sid
    assert chosen['limitations'] and chosen['scope']
    assert topics.question_sources(library, 'W8')['items'] == []


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


@pytest.mark.parametrize('topic, sizes', [
    (TOPIC, {'hrv_metric_and_recording_identity': 2, 'hrv_direction_and_training_response': 3,
             'wearable_hrv_protocol_transfer': 3, 'hrv_missing_observation_unit': 3}),
    ('W2', {'training_state_measurement_context': 2, 'hrv_direction_and_training_response': 3,
            'hrv_missing_observation_unit': 3}),
])
def test_saturated_groups_preserve_specific_definition_action_and_new_answers_in_body(library, topic, sizes):
    from healthzip.workflows.period_report import render_report
    from tests.integration.test_followup_report_evidence import historical

    # Two attractive general groups can otherwise consume all six first-pass
    # spans, leaving too little room for distinct content and its prerequisites.
    for identity in ['a-general', 'b-general']:
        sid = claim(library, identity, topics.PURPOSES, topic=topic)
        for n in range(2):
            predecessor = identity + '-premise-' + str(n)
            p = claim(library, predecessor, [], bind=False, topic=topic)
            edge(library, predecessor, identity, 'required_by', [p, sid])
    expected_spans = set()
    for need, count in sizes.items():
        identity = 'z-' + need
        sid = claim(library, identity, topics.ANSWER_NEEDS[need]['purposes'], topic=topic)
        expected_spans.add(sid)
        bind(library, identity, sid, need_id=need, topic=topic)
        for n in range(count - 1):
            predecessor = identity + '-premise-' + str(n)
            p = claim(library, predecessor, [], bind=False, topic=topic)
            expected_spans.add(p)
            edge(library, predecessor, identity, 'required_by', [p, sid])
    evidence = topics.question_sources(library, topic, include_evidence=True)
    audit = evidence['retrieval']
    assert all(audit['answer_status'][key]['status'] == 'available' for key in sizes)
    assert audit['requested_k'] == audit['supplemental_pass']['requested_k'] == 6
    assert audit['selected_unique_spans'] <= audit['maximum_unique_spans'] == 12
    assert audit['supplemental_remote_calls'] == 0
    assert expected_spans <= {s['span_id'] for s in evidence['evidence_spans']}
    report = historical({'id': topic, 'title': 'Synthetic content scenario', 'report_status': 'available',
                         'observation': 'Synthetic fact: 64 bpm, seven recorded days.',
                         'rows': [], 'steps': ['Check actual posture.'], 'evidence': evidence})
    frozen = deepcopy(report)
    body = render_report(None, report, runs=[])
    assert report == frozen
    assert 'Synthetic fact: 64 bpm, seven recorded days.' in body
    assert 'Check actual posture.' in body
    for item in evidence['items']:
        assert item['statement'] in body
        assert all(limit in body for limit in item['limitations'])
        assert all(citation['url'] in body for citation in item['citations'])
