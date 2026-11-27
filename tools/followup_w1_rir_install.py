"""Append two conditional W1 uses of retained RIR claims; preserve old authority.

Only the public library is opened. Exact passage/content reviews are reused;
these new application reviews authorize definitions and limits, never personal
accuracy, RPE conversion, a failure test or a training prescription.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from healthzip.knowledge import KnowledgeWorkbench, domains
from healthzip.knowledge.core import _claim, _spans
from healthzip.knowledge.revisions import knowledge_authority_clock, prepare_retrieval_revisions
from healthzip.knowledge.topics import ANSWER_NEEDS

VERSION = 'followup-w1-rir-2026-11-27.1'
SOURCE_VERSION = 'S4:fulltext:3546044b0345c1da95c5:pdf-structure-1.5.1-reviewed-passages-1'
CONDITION = {'field': 'metric_evidence.direct_rir_only', 'op': 'eq', 'value': True,
             'origin': 'measurement_contract'}
USES = [
    ('V15-CLAIM-RIR-PREPRINT-DEFINITION', [0, 1], 'direct_rir_definition'),
    ('V15-CLAIM-RIR-PREPRINT-METHOD-LIMITS', [2, 3, 4, 5], 'direct_rir_prediction_limits'),
]
REVIEW = {'reviewer': 'Codex retained RIR passage W1 application review, 2026-11-27',
    'reviewer_kind': 'ai_assisted', 'reviewed_at': '2026-11-27',
    'content_checked': True, 'application_checked': True, 'independent_expert_validation': False,
    'rationale': 'Rechecked all six retained 2021 author-preprint units. W1 uses only definitions and method limits '
                 'when all actual ordinary sets have directly recorded exact RIR. Population and endpoints are '
                 'not presumed to match the study; no accuracy, conversion, correction, test or prescription is licensed.'}


def preflight(w):
    checked = []
    for identity, numbers, need_id in USES:
        spans = [f'{SOURCE_VERSION}:s{n:05d}' for n in numbers]
        refs = [{'source_id': 'S4', 'source_version_id': SOURCE_VERSION, 'span_ids': spans}]
        payload, review, _ = _claim(w, {'claim_id': identity, 'version': '1.5.0'})
        _spans(w, refs)
        if payload['evidence_links'] != refs or payload.get('conditions') != [CONDITION]:
            raise ValueError('original_rir_claim_contract_changed:' + identity)
        if payload.get('scope', {}).get('inference') != 'direct_reported_RIR_source_definition_and_method_limits_only':
            raise ValueError('original_rir_use_changed:' + identity)
        checked.append((identity, spans, need_id, review))
    return checked


def apply(w):
    checked = preflight(w)
    applied = []
    for identity, spans, need_id, old_review in checked:
        need = ANSWER_NEEDS[need_id]
        binding = {key: need[key] for key in ('question', 'target_claim', 'required_context')}
        binding.update(relation='supports', answer_complete=True, target_coverage_complete=True,
            rationale='All original definition or method/limitation passages are retained together; direct exact RIR only.')
        edge = domains.link(w, origin={'type': 'claim', 'id': identity, 'version': '1.5.0'},
            relation='applies_to', target={'type': 'metric', 'id': 'W1', 'version': domains.profile_version('W1')},
            span_ids=spans, applicability={'metric_evidence.direct_rir_only': True},
            actor=REVIEW['reviewer'], rationale=REVIEW['rationale'], evidence_types=need['purposes'],
            review=REVIEW, answer_bindings=[binding])
        applied.append({'claim_id': identity, 'claim_version': '1.5.0', 'edge_id': edge,
                        'original_content_review_reused': old_review, 'new_application_review': REVIEW,
                        'span_ids': spans, 'grants_capability': False})
    prepare_retrieval_revisions(w)
    return applied


def run(root, backup, output):
    from followup_knowledge_install import compare_rows
    if root.resolve() == backup.resolve():
        raise ValueError('independent_sqlite_backup_required')
    output.mkdir(parents=True, exist_ok=False)
    before = compare_rows(backup, root)
    w = KnowledgeWorkbench(root)
    try:
        clock = knowledge_authority_clock(root)
        applied = apply(w)
        installed_clock = knowledge_authority_clock(root)
        changes = w.lib.theories.total_changes
        repeated = apply(w)
        idempotent = repeated == applied and changes == w.lib.theories.total_changes and installed_clock == knowledge_authority_clock(root)
    finally:
        w.close()
    after = compare_rows(backup, root)
    receipt = {'version': VERSION, 'public_library': str(root.resolve()), 'sqlite_backup': str(backup.resolve()),
        'before': before, 'after': after, 'applied': applied, 'idempotent': idempotent,
        'authority_before': clock, 'authority_after': installed_clock,
        'old_content_unchanged': all(row['all_old_rows_identical'] for row in after if row['protected_content']),
        'private_health_opened': False, 'external_calls': 0}
    (output / 'installation.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    if not idempotent:
        raise AssertionError('repeated_install_mutated_authority')
    print(json.dumps({'old_content_unchanged': receipt['old_content_unchanged'], 'new_edges': len(applied),
                      'idempotent': idempotent}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--backup', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    run(args.root, args.backup, args.output)
