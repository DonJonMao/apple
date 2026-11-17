"""New Gold may recognize exact revision alternatives without inflating recall."""
from copy import deepcopy

import pytest

from healthzip.knowledge.retrieval_evaluation import EVIDENCE_GROUP_VERSION, score_case
from healthzip.knowledge.store import digest


def member(span_id, text='Synthetic complete passage', **changes):
    return {'span_id': span_id, 'source_id': 'same-work', 'source_version': span_id.split(':')[0],
            'text_hash': digest(text.encode()), 'kind': 'paragraph', 'section_path': 'Methods', **changes}


def returned(value, text='Synthetic complete passage', **changes):
    return {**value, 'input_content_hash': value['text_hash'], 'content': text, **changes}


def fixture():
    first, alternative = member('v1:1'), member('v2:1')
    other = member('v1:2', 'A different whole passage')
    case = {'case_id': 'grouped', 'required_domains': ['strength'], 'expected_abstention': False,
            'evidence_unit_version': EVIDENCE_GROUP_VERSION,
            'gold_evidence_groups': [
                {'group_id': 'one', 'grade': 3, 'alternatives': [first, alternative]},
                {'group_id': 'two', 'grade': 2, 'alternatives': [other]}]}
    result = {'evidence_spans': [], 'matched_claims': [], 'requested_domains': ['strength'],
              'conflicts': [], 'status': 'evidence_context_supported',
              'retrieval_audit': {'retrieval_degraded': False}}
    return case, result, first, alternative, other


def test_exact_revision_alternatives_earn_one_gain_and_still_consume_k():
    case, result, first, alternative, other = fixture()
    result['evidence_spans'] = [returned(first), returned(alternative), returned(other, 'A different whole passage')]
    score = score_case(case, result, k=3)
    assert score['evidence_recall_at_k'] == score['exact_source_span_accuracy'] == 1
    assert score['evidence_precision_at_k'] == pytest.approx(2/3)
    assert score['mrr'] == 1
    assert 0 < score['ndcg_at_k'] < 1
    limited = score_case(case, result, k=2)
    assert limited['evidence_recall_at_k'] == .5 and limited['evidence_precision_at_k'] == .5
    result['evidence_spans'] = [returned(alternative), returned(other, 'A different whole passage')]
    assert score_case(case, result, k=2)['ndcg_at_k'] == 1


@pytest.mark.parametrize('changes', [
    {'source_id': 'different-work'}, {'source_version': 'unknown-version'},
    {'section_path': 'Different context'}, {'input_content_hash': '0' * 64},
    {'content': 'Truncated or changed passage'}, {'kind': 'table'},
])
def test_matching_span_id_cannot_hide_wrong_version_content_or_context(changes):
    case, result, first, _, _ = fixture()
    result['evidence_spans'] = [returned(first, **changes)]
    score = score_case(case, result)
    assert score['evidence_recall_at_k'] == score['exact_source_span_accuracy'] == 0


def test_explicit_gold_locator_must_match_even_when_ids_and_content_are_correct():
    case, result, first, *_ = fixture()
    first['locator'] = {'page': 7, 'paragraph': 3}
    result['evidence_spans'] = [returned(first)]
    assert score_case(case, result)['exact_source_span_accuracy'] == .5
    result['evidence_spans'][0]['locator'] = {'page': 17, 'paragraph': 3}
    assert score_case(case, result)['exact_source_span_accuracy'] == 0
    result['evidence_spans'][0].pop('locator')
    assert score_case(case, result)['exact_source_span_accuracy'] == 0


@pytest.mark.parametrize('changes', [
    {'source_id': 'different-work'}, {'kind': 'table'}, {'section_path': 'Abstract'},
    {'text_hash': '0' * 64},
])
def test_different_work_text_kind_or_context_cannot_be_declared_equivalent(changes):
    case, result, *_ = fixture()
    case['gold_evidence_groups'][0]['alternatives'][1].update(changes)
    with pytest.raises(ValueError, match='same_source_exact_text_kind_and_context'):
        score_case(case, result)


def test_group_ids_and_membership_cannot_double_the_gold_denominator():
    case, result, first, *_ = fixture()
    duplicate = deepcopy(case['gold_evidence_groups'][0])
    case['gold_evidence_groups'].append(duplicate)
    with pytest.raises(ValueError, match='unique_evidence_group_id'):
        score_case(case, result)
    duplicate['group_id'] = 'third'
    with pytest.raises(ValueError, match='exactly_one_evidence_group'):
        score_case(case, result)
    duplicate['alternatives'] = []
    with pytest.raises(ValueError, match='nonempty_exact_evidence_alternatives'):
        score_case(case, result)


def test_legacy_span_gold_keeps_its_original_denominator_and_scores():
    _, result, first, alternative, other = fixture()
    old = {'case_id': 'legacy', 'required_domains': ['strength'], 'expected_abstention': False,
           'gold_span_ids': [first['span_id'], alternative['span_id'], other['span_id']]}
    result['evidence_spans'] = [returned(first), returned(alternative)]
    score = score_case(old, result, k=2)
    assert score['evidence_recall_at_k'] == pytest.approx(2/3)
    assert score['evidence_precision_at_k'] == 1 and score['ndcg_at_k'] == 1


@pytest.mark.parametrize('version', [None, 'future-unknown-semantics'])
def test_new_gold_must_explicitly_pin_supported_group_semantics(version):
    case, result, *_ = fixture()
    case['evidence_unit_version'] = version
    with pytest.raises(ValueError, match='explicit_supported_evidence_group_version'):
        score_case(case, result)
