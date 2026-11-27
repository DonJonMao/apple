"""Three alternating stage pairs on an actual synthetic frozen workflow.

These are diagnostic medians, not whole-report acceptance or P95 samples.
The input is reconstructed from the immutable c71358d profile's frozen bytes;
its complete hash must equal the workflow's persisted input_hash.
"""
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone
from unittest.mock import patch

ROOT = Path('/home/sn_maozhifang/apple')
BASE = Path('/home/sn_maozhifang/healthzip-followup-validation-tmp/source-c71358d-profile-r1')
DATABASE = Path('/tmp/healthzip-followup-c71358d-profile-r1/synthetic.sqlite3')
OUTPUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from healthzip.db.repository import Repository
from healthzip.workflows import contracts, evidence, report_objects
from healthzip.workflows.storage import report_context


def old_module(name):
    path = BASE / f'src/healthzip/workflows/{name}.py'
    spec = importlib.util.spec_from_file_location(f'baseline_{name}', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    old_contracts, old_objects = old_module('contracts'), old_module('report_objects')
    source_files = ('src/healthzip/workflows/contracts.py', 'src/healthzip/workflows/report_objects.py')
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_files}
    with closing(sqlite3.connect(DATABASE.as_uri() + '?mode=ro', uri=True)) as conn:
        assert conn.execute('SELECT file_sha256 FROM import_batch').fetchall() == [('synthetic-100000',)]
    with closing(Repository(DATABASE)) as repo:
        row = repo.one("SELECT result_json FROM workflow_run WHERE workflow_id='W4' ORDER BY created_at LIMIT 1")
        run = report_objects.read_workflow(repo, json.loads(row[0]))
        snapshot = json.loads(repo.one('SELECT result_json FROM analysis_run WHERE run_id=?', (run['analysis_run_id'],))[0])
        declaration = report_context(repo, run['context_id'], run['request']['cutoff_time'], run['request']['mode'])
    payload = dict(request=run['request'], version=run['workflow_version'], snapshot=snapshot,
                   knowledge=evidence.identity(run['knowledge']), declaration=declaration,
                   dependencies=run['dependencies'], supplements=run['supplements'],
                   candidate_bases=run['linked_candidate_bases'])
    expected = old_contracts.workflow_input_hash(payload)
    assert expected == run['input_hash'] == contracts.workflow_input_hash(payload)
    ordinary = run['supplements']['ordinary_training']
    assert len(ordinary['series']) == ordinary['record_count'] == 10000
    input_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    input_digest = hashlib.sha256(input_bytes).hexdigest()
    receipt = {'diagnostic_only': True, 'fixture': 'synthetic-100000', 'profile_database': str(DATABASE),
               'workflow_id': run['run_id'], 'input_hash_matches_frozen_run': True,
               'source_hashes': hashes, 'input_bytes': len(input_bytes), 'input_sha256': input_digest,
               'ordinary_series': len(ordinary['series']), 'ordinary_records': ordinary['record_count'],
               'initial_load': os.getloadavg(), 'gc_enabled': gc.isenabled(), 'samples': [],
               'boundary': 'Rehydrated real workflow has no runtime alias sharing. Stage pairs only; not report/P95.',
               'concurrent_load': 'No root performance job; collaborator lightweight tests may overlap; external host load uncontrolled.'}
    del input_bytes
    workspace = Path(tempfile.mkdtemp(prefix='hz-freeze-stage-r11-'))
    receipt['temporary_workspace'] = str(workspace)

    class FixedClock:
        @staticmethod
        def now(zone):
            return datetime(2026, 11, 27, tzinfo=timezone.utc)

    with closing(Repository(workspace / 'synthetic-stage.sqlite3')) as repo:
        baseline_rows = [tuple(row) for row in repo.rows('SELECT * FROM report_content_object ORDER BY object_id')]
        expected_rows, expected_references = None, None
        for pair in range(3):
            for version in (('old', 'new') if pair % 2 == 0 else ('new', 'old')):
                module = old_contracts if version == 'old' else contracts
                started = time.perf_counter()
                actual = module.workflow_input_hash(payload)
                seconds = time.perf_counter() - started
                assert actual == expected
                receipt['samples'].append(dict(stage='workflow-input-hash', pair=pair, version=version, seconds=seconds))
                module = old_objects if version == 'old' else report_objects
                repo.conn.execute('SAVEPOINT stage')
                with patch.object(module, 'datetime', FixedClock):
                    started = time.perf_counter()
                    references = module._save_training(repo, ordinary)
                    seconds = time.perf_counter() - started
                rows = [tuple(row) for row in repo.rows('SELECT * FROM report_content_object ORDER BY object_id')]
                if expected_rows is None:
                    expected_rows, expected_references = rows, references
                assert rows == expected_rows and references == expected_references
                assert len(rows) == 10002
                repo.conn.execute('ROLLBACK TO stage')
                repo.conn.execute('RELEASE stage')
                assert [tuple(row) for row in repo.rows('SELECT * FROM report_content_object ORDER BY object_id')] == baseline_rows
                receipt['samples'].append(dict(stage='save-ordinary-training', pair=pair, version=version, seconds=seconds))
                (OUTPUT / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
                print(pair, version, flush=True)
    assert hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest() == input_digest
    assert hashes == {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_files}
    receipt.update(input_unchanged=True, exact_object_rows_and_reference_order_equal=True, source_unchanged=True,
                   median_s={stage: {version: statistics.median(r['seconds'] for r in receipt['samples']
                       if r['stage'] == stage and r['version'] == version) for version in ('old', 'new')}
                       for stage in ('workflow-input-hash', 'save-ordinary-training')}, complete=True)
    (OUTPUT / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
