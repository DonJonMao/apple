import pytest

from healthzip.knowledge.retrieval_evaluation import score_case


def test_metrics_score_exact_evidence_and_preserve_actual_denominators():
    case = {'case_id': 'public', 'gold_span_ids': ['a', 'b'], 'required_claims': [{'claim_id': 'c', 'claim_version': '1'}],
        'required_domains': ['wearable', 'recovery'], 'invalid_span_ids': ['invalid'],
        'inapplicable_span_ids': ['wrong_scope'], 'expected_abstention': True, 'expected_conflict': True,
        'gold_evidence': [{'source_id': 's', 'source_version': 'v', 'span_id': 'a'}]}
    result = {'evidence_spans': [{'source_id': 's', 'source_version': 'wrong', 'span_id': 'a'},
        {'source_id': 's', 'source_version': 'v', 'span_id': 'invalid'}], 'matched_claims': [],
        'requested_domains': ['wearable'], 'conflicts': [], 'status': 'insufficient_evidence',
        'retrieval_audit': {'retrieval_degraded': True}}
    score = score_case(case, result)
    assert score['evidence_recall_at_k'] == score['evidence_precision_at_k'] == .5
    assert score['mrr'] == 1 and score['exact_source_span_accuracy'] == 0
    assert score['claim_coverage'] == score['domain_routing_accuracy'] == 0
    assert score['invalid_evidence_admission_rate'] == .5 and score['conflict_detection_recall'] == 0
    assert score['abstention_accuracy'] == 1
    assert 0 < score['ndcg_at_k'] < 1


def test_empty_gold_does_not_invent_successful_recall_denominators():
    case = {'case_id': 'negative', 'gold_span_ids': [], 'required_domains': [], 'expected_abstention': True}
    result = {'evidence_spans': [], 'matched_claims': [], 'requested_domains': [], 'conflicts': [],
              'status': 'insufficient_evidence', 'retrieval_audit': {'retrieval_degraded': False}}
    score = score_case(case, result)
    assert score['evidence_recall_at_k'] is None and score['claim_coverage'] is None
    assert score['abstention_accuracy'] == 1
    result['evidence_spans'] = [{'source_id': 's', 'source_version': 'v', 'span_id': 'a'}]*2
    with pytest.raises(ValueError, match='duplicate'):
        score_case(case, result)
