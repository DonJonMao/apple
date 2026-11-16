"""The product entry point keeps computation, retrieval and explanation separate."""
from __future__ import annotations

from healthzip.ai.client import explain_analysis

from .store import dumps


def explain_metric(w, metric_id, analysis_task, metric_result, context=None, release_id=None, *,
                   mode='lexical', k=6, services=None, allow_explanation_network=False, ai_config=None):
    evidence = w.retrieve_for_metric(metric_id, analysis_task, metric_result, context, release_id,
                                    mode=mode, k=k, services=services)
    cards = []
    if evidence['capability_permissions']['source_explanation']:
        for claim in evidence['matched_claims']:
            cards.append({'id': 'claim:' + claim['claim_id'] + ':' + claim['claim_version'],
                'title': '来源一般解释', 'status': 'reviewed_source_explanation',
                'summary': '来源一般解释：' + ' '.join(claim['statements'])
                    + ' 适用范围：' + dumps(claim['scope']),
                'facts': [], 'limitations': [*claim['limitations'],
                    '来源一般解释不证明个人效果，也不授予个人数值处方。'],
                'allowed_actions': ['查看原文与适用范围'],
                'source_feature_ids': claim['evidence_span_ids']})
    explanation = explain_analysis({'metrics': [metric_result], 'public_source_claims': cards},
        config=ai_config, allow_network=allow_explanation_network)
    if evidence['status'] == 'insufficient_evidence':
        explanation['limitations'] = list(dict.fromkeys([
            *explanation['limitations'], '知识证据不足，当前只解释确定性计算结果。']))
    return {'metric_id': metric_id, 'analysis_task': analysis_task,
            'evidence_context': evidence, 'explanation': explanation}
