"""Reproduce bounded public-topic retrieval and conservative six-question content gaps.

Run only against a public knowledge backup. No health workspace or model is opened.
Purpose labels are reported separately from content completeness.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.core import _claim
from healthzip.knowledge.revisions import knowledge_authority_clock, prepare_retrieval_revisions
from healthzip.knowledge.store import now
from healthzip.knowledge.topics import TOPICS, question_sources

# These entries describe passages read in this repair, not new permission grants.
READINGS = {
    'HC-CARTER-HRV-USE': ('human cardiovascular methods; ECG and wearable PPG',
        'recording segment; time, posture, respiration and context',
        '方法段和可穿戴用途段支持记录条件及用途效度的区别；不能由可测量推定恢复判断有效。',
        ['measurement', 'comparison', 'mechanism_or_exception']),
    'HC-SDNN-CONTEXT': ('strength and conditioning methodological review',
        'HRV recording segment, duration and metric identity',
        '核对SDNN/RMSSD区别及采样长度、时段和情境；文中实验时长不转为个人阈值。',
        ['measurement', 'comparison']),
    'HC-QUER-PERSONAL-REFERENCE': ('adult sustained-wear Fitbit observational cohort',
        'manufacturer proprietary daily RHR; retrospective days',
        '研究使用Fitbit每日专有算法；个人内比较概念可读，不验证Apple RHR算法或个体报警线。',
        ['comparison', 'mechanism_or_exception']),
    'HC-ROBBINS-SLEEP-COVERAGE': ('35 healthy adults; one scheduled inpatient PSG night',
        'sleep epochs and scheduled nighttime episode; models studied only',
        '核对TST定义、缺失epoch处理和单夜限制；本产品不采用缺失即清醒插补。',
        ['measurement', 'comparison', 'mechanism_or_exception']),
    'MASTER-DE-VET': ('health status questionnaires; measurement-method paper',
        'measurement change score, repeatability and importance',
        '测量误差与本人重要变化是不同问题；未取得当前设备误差时不移植MDC数值。',
        ['comparison']),
    'MASTER-HR-CONTEXT': ('ambulatory psychophysiological methods',
        'posture/activity strata in ambulatory HR/HRV recordings',
        '先核对实际姿势与活动条件，再查看同录背景关联；不推断未记录疲劳。',
        ['measurement', 'comparison', 'mechanism_or_exception', 'action_or_reassessment']),
    'MASTER-OXYGEN-FOLLOWUP': ('FDA pulse-oximeter consumer guidance',
        'individual reading with time and symptoms; finger-device instructions not wrist validation',
        '读数连同日期时间和症状保存供复核；不由腕上单点诊断低氧或设报警线。',
        ['action_or_reassessment']),
    'MASTER-ACTIVITY-GRADUAL': ('HHS physical activity guidance chapter 7; age-general safety principles',
        'actual activity frequency/duration and tolerance; no fixed dose imported',
        '当前能力和目标下逐步活动，复评实际频次时长与耐受；不制定个人周增比例。',
        ['action_or_reassessment']),
    'MASTER-PROGRESSION-GOAL': ('healthy-adult resistance-training position stand',
        'training task and stated goal, load/repetitions and experience',
        '维持和继续进阶目标不同；只采用任务及目标核对，不默认成年或给负荷处方。',
        ['mechanism_or_exception', 'action_or_reassessment']),
}
QUESTIONS = {
    '是什么': None, '怎样测': 'measurement', '怎样比较': 'comparison',
    '为什么变化': 'mechanism_or_exception', '能做什么': 'action_or_reassessment', '适用于谁': 'applicability',
}


def run(root, output):
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    w = KnowledgeWorkbench(root)
    try:
        prepare_retrieval_revisions(w)
        before = knowledge_authority_clock(root)
        rows, matrix, readings = [], [], []
        for identity, (population, unit, note, uses) in READINGS.items():
            versions = w.lib.theories.execute('SELECT version FROM source_claim WHERE claim_id=? ORDER BY version DESC',
                                              (identity,)).fetchall()
            for version in versions:
                try:
                    claim, review, evidence = _claim(w, {'claim_id': identity, 'version': version[0]})
                    break
                except ValueError:
                    continue
            else:
                continue
            references = []
            for span in evidence:
                raw = w.lib.span(span['span_id'], include_metadata=False)
                source = w.lib.source(span['source_id'])['manifest']
                references.append({'source_id': span['source_id'], 'version': raw['version_id'],
                    'span_id': span['span_id'], 'text_hash': raw['text_hash'],
                    'locator': json.loads(raw['locator_json']), 'url': source.get('canonical_url')})
            readings.append({'claim_id': identity, 'version': version[0], 'population': population,
                'device_protocol_observation_unit': unit, 'checked_content': note,
                'not_inferred': claim['limitations'], 'checked_uses': uses, 'references': references,
                'existing_review': review, 'repair_reading_kind': 'AI_assisted_cited_passages_rechecked',
                'entire_publication_reread_this_round': False, 'new_scientific_authority_granted': False})
        for topic in TOPICS:
            result = question_sources(w, topic)
            items = result['items']
            row = {'topic': topic, 'status': result['status'],
                'items': [{key: item[key] for key in ('claim_id', 'version', 'scope', 'purposes', 'citations', 'reviewer_kind')}
                          for item in items],
                'field_definitions': result['field_definitions'],
                'restricted_claim_refs': [{'claim_id': item['claim_id'], 'version': item['version']}
                                          for item in result['restricted_items']],
                'retrieval': result['retrieval']}
            rows.append(row)
            for question, purpose in QUESTIONS.items():
                relevant = [i for i in items if purpose in i['purposes']] if purpose != 'applicability' else items
                checked = [i for i in relevant if i['claim_id'] in READINGS and
                           (purpose == 'applicability' or purpose in READINGS[i['claim_id']][3])]
                if purpose is None:
                    state = '尚待核验' if result['field_definitions'] else '不适用' if topic in {'W1','W2','W3','W4','W5','W6','W7','W8','E'} else '尚待核验'
                    note = '官方字段入口及已取得原件不等于已审阅、索引和页面使用的定义正文；设备验证另缺。'
                elif checked:
                    state = '仅通用方法'
                    note = '本轮已逐段核对所列受限方法或日志复评；未验证当前个人/设备/协议，不计为六问充分。'
                elif relevant:
                    state = '尚待核验'
                    note = '有既有AI审核及实际召回，但本轮未完成该问的内容充分性逐项复核。'
                else:
                    state = '尚待核验'
                    note = '当前没有适用且召回的审核组；不能仅凭未命中断言文献不存在。'
                matrix.append({'topic': topic, 'question': question, 'status': state, 'note': note,
                    'claim_refs': json.dumps([[i['claim_id'], i['version']] for i in relevant], ensure_ascii=False),
                    'acquisition': 'exact_version_retained' if relevant or result['field_definitions'] else 'not_established_for_this_use',
                    'reading': 'cited_passages_rechecked' if checked else 'not_rechecked_this_round',
                    'review': 'existing_AI_assisted_not_independent_expert' if relevant else 'no_applicable_reviewed_group',
                    'index': 'eligible_lexical_units' if relevant else 'not_established_for_this_use',
                    'retrieval': 'actual_current_result' if relevant else 'not_returned',
                    'page_use': 'backend_payload_ready_real_page_receipt_separate',
                    'current_device_validation': 'not_established'})
        report = {'evaluated_at': now(), 'public_corpus_only': True, 'mode': 'lexical',
            'initial_budget': 6, 'supplement_budget': 6, 'maximum_supplemental_passes': 1,
            'supplemental_remote_calls': 0, 'source_snapshot_stable': before == knowledge_authority_clock(root),
            'coverage_semantics': 'purpose_recall_is_not_six_question_content_completion',
            'independent_expert_review': False, 'private_remote_model_evaluation': 'not_authorized_or_run',
            'rows': rows}
        (target / 'retrieval-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        (target / 'passage-reading-notes.json').write_text(json.dumps(readings, ensure_ascii=False, indent=2)+'\n')
        with (target / 'six-question-content-matrix.csv').open('w') as stream:
            writer = csv.DictWriter(stream, fieldnames=matrix[0])
            writer.writeheader()
            writer.writerows(matrix)
        print(json.dumps({'topics': len(rows), 'six_question_rows': len(matrix), 'rechecked_claim_uses': len(readings),
            'stable': report['source_snapshot_stable'], 'supplemented_topics': sum(bool(r['retrieval']['supplemental_pass']) for r in rows)}))
    finally:
        w.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--output', default='artifacts/repair_knowledge')
    args = parser.parse_args()
    run(args.root, args.output)
