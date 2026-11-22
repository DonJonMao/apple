"""Independent synthetic local RAG acceptance and public evidence timings.

No real health database or external model is read/called. This measures the
retrieval/binding/local-answer path, not the accuracy of an untested remote model.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from healthzip.ai.client import build_evidence_payload, validate_ai_result
from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.health_facts import comparison_cards
from healthzip.knowledge.store import now
from healthzip.science import evaluate


def run(root, output, repeats=30):
    w = KnowledgeWorkbench(root)
    rows = []
    start = datetime(2026, 9, 8, tzinfo=timezone.utc)
    reference = [54, 55, 56, 57] * 7
    current = [60, 62, 59, 64, 61, 63, 58, 65]
    for i, value in enumerate(reference + current):
        date = start - timedelta(days=28) + timedelta(days=i, hours=8)
        rows.append({'id': f'synthetic-independent-{i}', 'canonical_type': 'resting_heart_rate_bpm',
            'value': value, 'unit': 'bpm', 'source_name': 'Synthetic Independent Watch', 'device': 'synthetic',
            'event_start': date.isoformat(), 'event_end': date.isoformat(), 'available_at': date.isoformat()})
    end = start + timedelta(days=len(current))
    metric = evaluate('STATE-RHR', rows, cutoff_time=end.isoformat(), window_start=start.isoformat(),
                      window_end=end.isoformat(), context={'timezone': 'UTC'})
    checked = metric['comparison']['streams'][0]
    facts = {
        'current_value': checked['current']['value'] == statistics.median(current),
        'reference_value': checked['reference']['value'] == statistics.median(reference),
        'direction_and_difference': checked['reference_change']['absolute'] == statistics.median(current) - statistics.median(reference),
        'current_coverage': (checked['current']['recorded_days'], checked['current']['window_days']) == (8, 8),
        'reference_coverage': (checked['reference']['recorded_days'], checked['reference']['window_days']) == (28, 28),
        'prior_reference_end': checked['reference']['window']['end'] == start.isoformat(),
    }
    cards = comparison_cards(metric)
    payload = build_evidence_payload({'cards': cards})
    card = cards[0]
    valid = {'summary': card['summary'], 'evidence_ids': [card['id']], 'facts': [dict(evidence_id=card['id'], **card['facts'][0])],
             'limitations': card['limitations'], 'actions': card['allowed_actions']}
    acceptance = validate_ai_result(valid, payload)['source'] == 'ai'
    mutations = [('value', 999), ('unit', 'ms'), ('recorded_days', 0), ('dates', []),
                 ('window', {'start': '2099-01-01'}), ('fact_id', 'wrong-person-period')]
    rejected = []
    for field, changed in mutations:
        candidate = json.loads(json.dumps(valid))
        candidate['facts'][0][field] = changed
        try:
            validate_ai_result(candidate, payload)
            rejected.append(False)
        except ValueError:
            rejected.append(True)
    duration = []
    answers = []
    for _ in range(repeats + 1):
        began = time.perf_counter()
        answer = w.explain_metric('STATE-RHR', 'explain_metric', metric, {}, mode='lexical', candidate_scope='reviewed_metric')
        duration.append(time.perf_counter() - began)
        answers.append(answer)
    answer = answers[-1]
    used = answer['measurement_explanations']
    useful = {
        'specific_observation': bool(answer['deterministic_observations']) and '61.5 bpm' in answer['deterministic_observations'][0]['summary'],
        'applicable_measurement_explanation': any(x['allowed_use'] == 'measurement_context_only' for x in used),
        'specific_record_check': bool(answer['local_next_steps']),
        'original_source_entry': any(s.get('canonical_url', '').startswith('https://') for x in used for s in x['sources']),
        'unknown_age_not_defaulted': not answer['evidence_context']['capability_permissions']['source_explanation'],
    }
    result = {'created_at': now(), 'input': 'independent synthetic September data, no real records',
        'external_model_calls': 0, 'remote_model_accuracy': 'not_evaluated', 'fixed_statistic_checks': facts,
        'fact_numeric_error_count': sum(not passed for passed in facts.values()), 'fact_checks_denominator': len(facts),
        'valid_bound_answer_accepted': acceptance, 'adversarial_mutations': len(mutations),
        'adversarial_mutations_rejected': sum(rejected), 'usefulness': useful,
        'evidence_match': [{'claim_id': x['claim_id'], 'source_ids': x['source_ids'], 'purpose': x['allowed_use']} for x in used],
        'timing': {'repetitions_hot': repeats, 'cold_local_full_answer_seconds': duration[0],
            'hot_local_full_answer_median_seconds': statistics.median(duration[1:]),
            'hot_local_full_answer_p95_seconds': sorted(duration[1:])[max(0, int(.95 * repeats + .999999) - 1)],
            'all_hot_cache_hits': all(a['evidence_context']['retrieval_audit'].get('cache_hit') for a in answers[1:]),
            'scope': 'public retrieval + deterministic explanation, excludes page render and external model'},
        'passed': all(facts.values()) and acceptance and all(rejected) and all(useful.values())}
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    w.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', default='.local/knowledge')
    p.add_argument('--output', default='artifacts/health_comparison/rag-acceptance.json')
    args = p.parse_args()
    if not run(args.root, args.output)['passed']:
        raise SystemExit(1)
