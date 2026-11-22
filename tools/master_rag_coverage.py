"""Evaluate current local retrieval on the actual public corpus, without health records."""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.revisions import knowledge_authority_clock
from healthzip.knowledge.store import now
from healthzip.knowledge.topics import TOPICS, question_sources
from healthzip.science.body_catalog import METRIC_CATALOG

# Fixed use targets; these are software/known-source recall cases, not independent expert gold.
EXPECTED = {
    'W1': 'V15-CLAIM-LOAD-REPETITION-COMPARISON-IDENTITY', 'W2': 'HC-CARTER-HRV-USE',
    'W3': 'V15-CLAIM-WATCH-VO2-MEASUREMENT-LIMITS', 'W4': 'MASTER-DE-VET',
    'W5': 'V15-CLAIM-BODY-MASS-SCALE-METHOD-IDENTITY', 'W6': 'HC-ROBBINS-SLEEP-COVERAGE',
    'W7': 'MASTER-ACTIVITY-OPPORTUNITY', 'W8': 'MASTER-CYCLE-PERFORMANCE',
    'BODY-OBS-oxygen_saturation_fraction': 'MASTER-OXYGEN',
    'BODY-OBS-environmental_audio_dba': 'MASTER-NOISE',
}


def run(root, output):
    w = KnowledgeWorkbench(root)
    rows = []
    try:
        before = knowledge_authority_clock(w.root)
        for topic in TOPICS:
            t = time.perf_counter()
            result = question_sources(w, topic)
            claims = [x['claim_id'] for x in result['items']]
            purposes = sorted({p for x in result['items'] for p in x['purposes']})
            field = bool(result['field_definitions'])
            rows.append({'topic': topic, 'catalog': result['catalog'], 'status': result['status'],
                         'seconds': round(time.perf_counter()-t, 4), 'claims': claims,
                         'citations': list({s['span_id']: s for x in result['items'] for s in x['citations']}.values()),
                         'original_field_reference': result['field_definitions'],
                         'purpose_checks': {'definition': 'official_field_reference' if field else 'no_field_reference',
                            'measurement': 'measurement' in purposes, 'comparison': 'comparison' in purposes,
                            'mechanism_or_exception': 'mechanism_or_exception' in purposes,
                            'action_or_reassessment': 'action_or_reassessment' in purposes,
                            'applicability': 'source_specific_limits_attached' if result['items'] else 'missing'},
                         'expected_claim': EXPECTED.get(topic),
                         'expected_claim_found': EXPECTED[topic] in claims if topic in EXPECTED else None})
        after = knowledge_authority_clock(w.root)
        checks = [r['expected_claim_found'] for r in rows if r['expected_claim']]
        report = {'evaluated_at': now(), 'mode': 'lexical', 'k': 6, 'source_snapshot_stable': before == after,
                  'known_source_recall_at_six': {'hits': sum(checks), 'cases': len(checks)},
                  'question_count': len(rows), 'questions_with_reviewed_explanations': sum(bool(r['claims']) for r in rows),
                  'questions_with_official_definition_link': sum(bool(r['original_field_reference']) for r in rows),
                  'questions_with_all_four_purposes': sum(all(r['purpose_checks'][key] for key in
                      ('measurement', 'comparison', 'mechanism_or_exception', 'action_or_reassessment')) for r in rows),
                  'body_catalog_exactly_covered': set(METRIC_CATALOG) == {
                      topic.removeprefix('BODY-OBS-') for topic in TOPICS if topic.startswith('BODY-OBS-')},
                  'rows': rows}
        Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        labels = {'measurement': '测量', 'comparison': '比较', 'mechanism_or_exception': '机制/反例',
                  'action_or_reassessment': '行动/复评'}
        csv_rows = []
        for row in rows:
            field = row['topic'].removeprefix('BODY-OBS-')
            checks = row['purpose_checks']
            missing = [label for key, label in labels.items() if not checks[key]]
            csv_rows.append({'topic': row['topic'], 'field': METRIC_CATALOG.get(field, {}).get('title', row['topic']),
                'definition': '官方入口' if row['original_field_reference'] else '未取得/非字段',
                **{label: '有受限用途' if checks[key] else '缺' for key, label in labels.items()},
                '适用范围': '随主张限制' if row['claims'] else '缺', 'claims': ','.join(row['claims']),
                'missing': ','.join(missing) or '仅用途标签齐全，尚需独立完整度评审'})
        with Path(output).with_name('field-six-question-matrix.csv').open('w') as stream:
            writer = csv.DictWriter(stream, fieldnames=csv_rows[0])
            writer.writeheader()
            writer.writerows(csv_rows)
        print({k: v for k,v in report.items() if k != 'rows'})
    finally:
        w.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.local/knowledge')
    parser.add_argument('--output', default='artifacts/master_redesign/knowledge/topic-coverage.json')
    args = parser.parse_args()
    run(args.root, args.output)
