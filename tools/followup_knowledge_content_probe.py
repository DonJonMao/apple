"""Probe retained public evidence on a small complete reviewed-candidate projection.

The original databases are opened read-only. This is a lexical correctness probe,
not a whole-corpus backup, dense retrieval evaluation or performance fixture.
Original prose remains in the temporary local SQLite; artifacts contain derived
statements and provenance only. No health database, app or network is opened.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

from followup_knowledge_content_gaps import READINGS, apply, audit, version
from followup_knowledge_install import compare_rows

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.revisions import knowledge_authority_clock
from healthzip.knowledge.topics import ANSWER_NEEDS, question_sources
from healthzip.workflows.period_report import render_report


def readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def project(root, destination):
    destination.mkdir(parents=True, exist_ok=False)
    receipt = []
    with readonly(root / 'theories.sqlite3') as original, sqlite3.connect(destination / 'theories.sqlite3') as copied:
        original.backup(copied)
        spans = {sid for row in original.execute('SELECT payload_json FROM source_claim')
                 for ref in json.loads(row[0]).get('evidence_links', []) for sid in ref['span_ids']}
    spans.update(f'{version(r)}:s{n:05d}' for r in READINGS.values() for n in r['paragraphs'])
    selected = json.dumps(sorted(spans))
    with readonly(root / 'sources.sqlite3') as original, sqlite3.connect(destination / 'sources.sqlite3') as copied:
        schema = list(original.execute('SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL'))
        for kind, _, sql in schema:
            if kind == 'table':
                copied.execute(sql)
        for kind, table, _ in schema:
            if kind != 'table':
                continue
            where, params = '', ()
            if table in {'span', 'retrieval_unit', 'retrieval_unit_domain_review', 'retrieval_projection_set'}:
                where, params = ' WHERE span_id IN (SELECT value FROM json_each(?))', (selected,)
            elif table == 'retrieval_parent_section':
                where = ' WHERE parent_id IN (SELECT parent_id FROM retrieval_unit WHERE span_id IN (SELECT value FROM json_each(?)))'
                params = (selected,)
            elif table in {'retrieval_vector', 'metric_retrieval_audit'}:
                where = ' WHERE 0'
            quoted = '"' + table.replace('"', '""') + '"'
            rows = list(original.execute('SELECT rowid,* FROM ' + quoted + where, params))
            if rows:
                copied.executemany('INSERT INTO ' + quoted + ' VALUES(' + ','.join('?' for _ in rows[0][1:]) + ')',
                                   [r[1:] for r in rows])
            receipt.append({'table': table, 'copied_rows': len(rows), 'selection': where or 'all'})
        for kind, _, sql in schema:
            if kind != 'table':
                copied.execute(sql)
    return {'kind': 'complete_reviewed_candidate_projection', 'all_claim_versions_and_edges': True,
            'all_claim_linked_spans': len(spans), 'no_vectors_or_previous_audits': True, 'tables': receipt}


def probe(root, output):
    output.mkdir(parents=True, exist_ok=False)
    original_clock = knowledge_authority_clock(root)
    with tempfile.TemporaryDirectory(prefix='healthzip-public-content-') as temporary:
        copied = Path(temporary) / 'projection'
        receipt = project(root, copied)
        baseline = Path(temporary) / 'baseline'
        baseline.mkdir()
        for name in ['sources.sqlite3', 'theories.sqlite3']:
            with readonly(copied / name) as before, sqlite3.connect(baseline / name) as backup:
                before.backup(backup)
        w = KnowledgeWorkbench(copied)
        try:
            audit(w, output / 'before', [])
            applied = apply(w)
            audit(w, output / 'after', applied)
            installed_clock = knowledge_authority_clock(copied)
            second = apply(w)
            receipt['idempotent_reapply'] = second == applied and installed_clock == knowledge_authority_clock(copied)
            receipt['projected_old_rows'] = compare_rows(baseline, copied)
            checks = []
            for topic in sorted({t for spec in ANSWER_NEEDS.values() for t in spec['topics']} | {'W3', 'W4'}):
                evidence = question_sources(w, topic, include_evidence=True)
                q = {'id': topic, 'title': 'Public evidence probe ' + topic, 'report_status': 'available',
                     'observation': '公开来源内容检查；不包含个人记录。', 'rows': [], 'steps': [], 'evidence': evidence}
                report = {'period': 'week', 'version': 'public-content-probe', 'analysis_run_id': 'no-health-records',
                          'questions': [q], 'current': {'window_start': '2026-11-16T00:00:00Z',
                          'cutoff_time': '2026-11-23T00:00:00Z', 'timezone': 'UTC', 'strength_tasks': []}}
                frozen = json.dumps(report, sort_keys=True)
                body = render_report(None, report, runs=[])
                (output / (topic + '.md')).write_text(body)
                checks.append({'topic': topic, 'frozen_unchanged': frozen == json.dumps(report, sort_keys=True),
                    'answer_status': evidence['retrieval']['answer_status'],
                    'unique_spans': evidence['retrieval']['selected_unique_spans'],
                    'items': [{'claim_id': item['claim_id'], 'statement_present': item['statement'] in body,
                        'all_limits_present': all(limit in body for limit in item['limitations']),
                        'all_urls_present': all(c['url'] in body for c in item['citations'])} for item in evidence['items']]})
            receipt.update(original_authority_unchanged=original_clock == knowledge_authority_clock(root),
                           original_authority=original_clock, body_checks=checks, private_health_opened=False,
                           external_calls=0, browser_validation=False, full_report_generation=False)
            receipt['all_projected_old_content_unchanged'] = all(
                row['all_old_rows_identical'] for row in receipt['projected_old_rows'] if row['protected_content'])
            (output / 'probe.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps(receipt['body_checks'], ensure_ascii=False, indent=2))
        finally:
            w.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    probe(args.root, args.output)
