"""Frozen ID-based retrieval scoring; raw prose and historical scores are never rewritten."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from .store import digest, dumps, now


def score_case(case, result, *, k=6):
    gold = set(case['gold_span_ids'])
    ranked = [s['span_id'] for s in result['evidence_spans'][:k]]
    if len(ranked) != len(set(ranked)):
        raise ValueError('duplicate_retrieved_span')
    grades = case.get('relevance_grades', {s: 1 for s in gold})
    hits = [int(s in gold) for s in ranked]
    dcg = sum((2**grades.get(s, 0)-1) / math.log2(i+2) for i, s in enumerate(ranked))
    ideal = sum((2**grade-1) / math.log2(i+2) for i, grade in
                enumerate(sorted(grades.values(), reverse=True)[:k]))
    required_claims = {(c['claim_id'], c['claim_version']) for c in case.get('required_claims', [])}
    returned_claims = {(c['claim_id'], c['claim_version']) for c in result['matched_claims']}
    required_domains = set(case['required_domains'])
    requested_domains = set(result['requested_domains'])
    invalid = set(case.get('invalid_span_ids', []))
    inapplicable = set(case.get('inapplicable_span_ids', []))
    exact_pairs = {(e['source_id'], e['source_version'], e['span_id']) for e in case.get('gold_evidence', [])}
    returned_pairs = {(e['source_id'], e['source_version'], e['span_id']) for e in result['evidence_spans'][:k]}
    conflicts = bool(case.get('expected_conflict'))
    abstention = result['status'] in {'insufficient_evidence', 'not_required_deterministic_computation'}
    return {'case_id': case['case_id'], 'evidence_recall_at_k': sum(hits)/len(gold) if gold else None,
        'evidence_precision_at_k': sum(hits)/len(ranked) if ranked else (1. if not gold else 0.),
        'mrr': next((1/(i+1) for i, hit in enumerate(hits) if hit), 0.) if gold else None,
        'ndcg_at_k': dcg/ideal if ideal else None,
        'claim_coverage': len(required_claims & returned_claims)/len(required_claims) if required_claims else None,
        'domain_routing_accuracy': float(required_domains <= requested_domains),
        'exact_source_span_accuracy': len(exact_pairs & returned_pairs)/len(exact_pairs) if exact_pairs else None,
        'applicability_error_rate': len(set(ranked) & inapplicable)/len(ranked) if ranked else 0.,
        'invalid_evidence_admission_rate': len(set(ranked) & invalid)/len(ranked) if ranked else 0.,
        'conflict_detection_recall': float(bool(result['conflicts'])) if conflicts else None,
        'abstention_accuracy': float(abstention == case['expected_abstention']),
        'retrieval_degraded': result['retrieval_audit']['retrieval_degraded'],
        'ranked_span_ids': ranked, 'status': result['status'], 'domains': sorted(required_domains)}


def aggregate(rows):
    metrics = [key for key in rows[0] if key not in {'case_id', 'ranked_span_ids', 'status', 'domains', 'retrieval_degraded'}] if rows else []
    result = {'case_count': len(rows), 'degraded_case_count': sum(r['retrieval_degraded'] for r in rows)}
    for name in metrics:
        values = [row[name] for row in rows if row[name] is not None]
        result[name] = {'value': sum(values)/len(values) if values else None, 'denominator': len(values)}
    return result


def evaluate_saved_rankings(gold_path, experiments, output_dir, *, model_identities, retrieval_config):
    """Each experiment must contain results for exactly the frozen Gold case IDs.

    A–E runners are supplied separately so this scorer cannot secretly alter
    filtering, queries, model versions or relevance labels to improve a score.
    """
    raw = Path(gold_path).read_bytes()
    gold = json.loads(raw)
    if gold.get('schema') != 'metric-retrieval-gold-1.5.0' or not gold.get('annotator') or not gold.get('created_at'):
        raise ValueError('identified_dated_frozen_gold_required')
    if set(experiments) != {'A', 'B', 'C', 'D', 'E'}:
        raise ValueError('five_explicit_experiment_outputs_required')
    cases = {case['case_id']: case for case in gold['cases']}
    if len(cases) != len(gold['cases']):
        raise ValueError('duplicate_gold_case')
    report = {'schema': 'metric-retrieval-evaluation-1.5.0', 'created_at': now(), 'gold_sha256': digest(raw),
        'annotator': gold['annotator'], 'dataset_identity': gold.get('dataset_identity'),
        'model_identities': model_identities, 'retrieval_config': retrieval_config,
        'scientific_or_candidate_authority_granted': False, 'experiments': {}}
    for variant, outputs in experiments.items():
        if set(outputs) != set(cases):
            raise ValueError('experiment_case_set_must_equal_frozen_gold')
        rows = [score_case(case, outputs[identity]) for identity, case in cases.items()]
        groups = defaultdict(list)
        for row in rows:
            for domain in row['domains']:
                groups[domain].append(row)
            if len(row['domains']) > 1:
                groups['cross_domain'].append(row)
        report['experiments'][variant] = {'overall': aggregate(rows),
            'by_domain': {group: aggregate(members) for group, members in sorted(groups.items())}, 'cases': rows,
            'output_sha256': digest(dumps(outputs).encode())}
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    # An existing run is immutable, including failed or disappointing scores.
    with (output / 'evaluation.json').open('x') as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report
