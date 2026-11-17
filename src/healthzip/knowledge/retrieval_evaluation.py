"""Frozen ID-based retrieval scoring; raw prose and historical scores are never rewritten."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from .store import digest, dumps, now

EVIDENCE_GROUP_VERSION = 'source-context-evidence-groups-1.5.0'


def _group_ranking(groups, returned):
    """Optional new-Gold units: exact same-source text in the same context.

    Alternative version/span IDs retain their exact provenance. They earn one
    relevance gain per group while duplicate returns still consume the budget.
    Legacy span-based Gold and its historical scores keep their original math.
    """
    if not isinstance(groups, list):
        raise ValueError('explicit_evidence_group_list_required')
    grades, alternatives = {}, {}
    for group in groups:
        identity = group.get('group_id') if isinstance(group, dict) else None
        if not isinstance(identity, str) or not identity or identity in grades:
            raise ValueError('unique_evidence_group_id_required')
        grade = group.get('grade')
        if type(grade) is not int or grade not in {2, 3}:
            raise ValueError('positive_gold_group_grade_required')
        members = group.get('alternatives')
        if not isinstance(members, list) or not members:
            raise ValueError('nonempty_exact_evidence_alternatives_required')
        signature = None
        for member in members:
            if not isinstance(member, dict) or any(not isinstance(member.get(key), str)
                    or not member[key] for key in ('source_id', 'source_version', 'span_id', 'text_hash', 'kind')):
                raise ValueError('exact_group_member_identity_required')
            if (len(member['text_hash']) != 64 or any(c not in '0123456789abcdef' for c in member['text_hash'])
                    or not isinstance(member.get('section_path'), str)):
                raise ValueError('exact_group_content_and_context_required')
            current = tuple(member[key] for key in ('source_id', 'text_hash', 'kind', 'section_path'))
            if signature is not None and current != signature:
                raise ValueError('group_requires_same_source_exact_text_kind_and_context')
            signature = current
            if member['span_id'] in alternatives:
                raise ValueError('span_must_belong_to_exactly_one_evidence_group')
            alternatives[member['span_id']] = (identity, member)
        grades[identity] = grade
    ranked, gains, seen = [], [], set()
    for span in returned:
        match = alternatives.get(span['span_id'])
        identity = None
        if match:
            proposed, member = match
            content_hash = digest(span['content'].encode()) if isinstance(span.get('content'), str) else span.get('input_content_hash')
            if (span.get('source_id') == member['source_id'] and span.get('source_version') == member['source_version']
                    and span.get('section_path') == member['section_path'] and content_hash == member['text_hash']
                    and span.get('input_content_hash', content_hash) == member['text_hash']
                    and span.get('kind', member['kind']) == member['kind']
                    and ('locator' not in member or span.get('locator') == member['locator'])):
                identity = proposed
        ranked.append(identity)
        gains.append(grades[identity] if identity is not None and identity not in seen else 0)
        if identity is not None:
            seen.add(identity)
    return grades, ranked, gains


def score_case(case, result, *, k=6):
    ranked = [s['span_id'] for s in result['evidence_spans'][:k]]
    if len(ranked) != len(set(ranked)):
        raise ValueError('duplicate_retrieved_span')
    grouped = 'gold_evidence_groups' in case
    if grouped:
        if case.get('evidence_unit_version') != EVIDENCE_GROUP_VERSION:
            raise ValueError('explicit_supported_evidence_group_version_required')
        grades, group_ids, gains = _group_ranking(case['gold_evidence_groups'], result['evidence_spans'][:k])
        gold = set(grades)
        hits = [int(gain > 0) for gain in gains]
        exact_accuracy = len({identity for identity in group_ids if identity is not None}) / len(gold) if gold else None
    else:
        gold = set(case['gold_span_ids'])
        grades = case.get('relevance_grades', {s: 1 for s in gold})
        hits = [int(s in gold) for s in ranked]
        gains = [grades.get(s, 0) for s in ranked]
    dcg = sum((2**grade-1) / math.log2(i+2) for i, grade in enumerate(gains))
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
    if not grouped:
        exact_accuracy = len(exact_pairs & returned_pairs)/len(exact_pairs) if exact_pairs else None
    conflicts = bool(case.get('expected_conflict'))
    abstention = result['status'] in {'insufficient_evidence', 'not_required_deterministic_computation'}
    return {'case_id': case['case_id'], 'evidence_recall_at_k': sum(hits)/len(gold) if gold else None,
        'evidence_precision_at_k': sum(hits)/len(ranked) if ranked else (1. if not gold else 0.),
        'mrr': next((1/(i+1) for i, hit in enumerate(hits) if hit), 0.) if gold else None,
        'ndcg_at_k': dcg/ideal if ideal else None,
        'claim_coverage': len(required_claims & returned_claims)/len(required_claims) if required_claims else None,
        'domain_routing_accuracy': float(required_domains <= requested_domains),
        'exact_source_span_accuracy': exact_accuracy,
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
