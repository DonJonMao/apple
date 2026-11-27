"""Install reviewed public additions after a SQLite backup; verify every old row.

Only sources.sqlite3/theories.sqlite3 are opened. Existing original content,
rights, reviews, releases and scientific states must remain byte-for-byte equal.
Authority revision counters are expected administrative changes, reported apart.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sqlite3
from pathlib import Path

from followup_knowledge_audit import CLAIMS, READINGS, apply, audit, version

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.core import _spans

DATABASES = ('sources.sqlite3', 'theories.sqlite3')


def readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def compare_rows(baseline, current):
    results = []
    for name in DATABASES:
        before, after = readonly(baseline / name), readonly(current / name)
        try:
            tables = [row[0] for row in before.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            for table in tables:
                quoted = '"' + table.replace('"', '""') + '"'
                columns = [r[1] for r in before.execute('PRAGMA table_info(' + quoted + ')')]
                after_columns = [r[1] for r in after.execute('PRAGMA table_info(' + quoted + ')')]
                if columns != after_columns:
                    raise ValueError('existing_public_table_schema_changed:' + table)
                old_rows = before.execute('SELECT rowid,* FROM ' + quoted + ' ORDER BY rowid')
                new_rows = iter(after.execute('SELECT rowid,* FROM ' + quoted + ' ORDER BY rowid'))
                new = next(new_rows, None)
                old_hash, retained_hash = hashlib.sha256(), hashlib.sha256()
                count, differences = 0, []
                for old in old_rows:
                    count += 1
                    encoded = pickle.dumps(old, protocol=4)
                    old_hash.update(hashlib.sha256(encoded).digest())
                    while new is not None and new[0] < old[0]:
                        new = next(new_rows, None)
                    if new is None or new[0] != old[0]:
                        differences.append({'rowid': old[0], 'change': 'missing'})
                        continue
                    retained_hash.update(hashlib.sha256(pickle.dumps(new, protocol=4)).digest())
                    if old != new:
                        change = {'rowid': old[0], 'change': 'modified'}
                        if table == 'knowledge_authority_revision':
                            change.update(before=dict(zip(columns, old[1:])), after=dict(zip(columns, new[1:])))
                        differences.append(change)
                protected = table != 'knowledge_authority_revision'
                result = {'database': name, 'table': table, 'before_rows': count,
                    'after_rows': after.execute('SELECT COUNT(*) FROM ' + quoted).fetchone()[0],
                    'before_rows_sha256': old_hash.hexdigest(), 'retained_rows_sha256': retained_hash.hexdigest(),
                    'all_old_rows_identical': not differences, 'protected_content': protected, 'differences': differences}
                results.append(result)
                if protected and differences:
                    raise ValueError('existing_public_rows_changed:' + name + ':' + table)
        finally:
            before.close()
            after.close()
    return results


def run(root, baseline, output, *, install):
    output.mkdir(parents=True, exist_ok=True)
    if root.resolve() == baseline.resolve():
        raise ValueError('independent_sqlite_backup_required')
    before = compare_rows(baseline, root)
    w = KnowledgeWorkbench(root)
    try:
        # Verify all exact sources/versions/rights before any claim is added.
        for spec in CLAIMS:
            entry = READINGS[spec['reading']]
            vid = version(entry)
            _spans(w, [{'source_id': entry['source'], 'source_version_id': vid,
                        'span_ids': [f'{vid}:s{n:05d}' for n in spec['spans']]}])
        applied = apply(w) if install else []
        audit(w, output / 'installed', applied)
    finally:
        w.close()
    after = compare_rows(baseline, root)
    receipt = {'root': str(root.resolve()), 'sqlite_backup': str(baseline.resolve()), 'private_health_opened': False,
        'installed': install, 'existing_content_rights_reviews_releases_preserved': all(
            row['all_old_rows_identical'] for row in after if row['protected_content']),
        'administrative_clock_changes': [row for row in after if not row['protected_content']],
        'before': before, 'after': after, 'external_model_calls': 0}
    (output / 'installation-preservation.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'installed': install, 'protected_tables': sum(r['protected_content'] for r in after),
        'existing_rows': sum(r['before_rows'] for r in after),
        'all_existing_content_unchanged': receipt['existing_content_rights_reviews_releases_preserved']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(args.root, args.baseline, args.output, install=args.apply)
