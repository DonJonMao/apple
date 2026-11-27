"""Paired copy/decoder-gate diagnostic on an already frozen synthetic report."""
import ast
import copy
import gc
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path('/home/sn_maozhifang/apple')
SOURCE = Path('/home/sn_maozhifang/healthzip-followup-validation-tmp/source-64cdd53-profile-r1')
DATABASE = Path('/tmp/healthzip-followup-64cdd53-profile-r1/synthetic.sqlite3')
OUTPUT = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE / 'src'))
from healthzip.db.repository import Repository
from healthzip.workflows.period_report import _fast_json_compatible as original_gate
from healthzip.workflows.period_report import load_report


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not (OUTPUT / 'paired-receipt.json').exists(), 'Preserve prior samples'
    source_paths = ['src/healthzip/copying.py', 'src/healthzip/analytics/cache.py',
                    'src/healthzip/science/engine.py', 'src/healthzip/workflows/period_report.py']
    hashes = {p: digest(ROOT / p) for p in source_paths}
    spec = importlib.util.spec_from_file_location('current_copying', ROOT / source_paths[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tree = ast.parse((ROOT / source_paths[-1]).read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_fast_json_compatible')
    namespace = {'math': math}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / source_paths[-1]), 'exec'), namespace)
    current_gate = namespace['_fast_json_compatible']
    repo = Repository(DATABASE)
    try:
        assert [tuple(r) for r in repo.rows('SELECT file_sha256 FROM import_batch')] == [('synthetic-100000',)]
        row = repo.one('SELECT report_id,payload_json,markdown FROM joint_period_report ORDER BY created_at LIMIT 1')
        frozen_bytes = hashlib.sha256((row[1] + '\0' + row[2]).encode()).hexdigest()
        report = load_report(repo, row[0], include_details=True)
        questions = report['questions']
        before = hashlib.sha256(json.dumps(questions, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        record_ids = {p['record_id'] for q in questions for group in q.get('ordinary_training', {}).get('series', []) for p in group.get('points', [])}
        samples = []
        for round_id in range(3):
            order = [('original', copy.deepcopy), ('current', module.isolated_copy)]
            if round_id % 2:
                order.reverse()
            for name, clone in order:
                started = time.perf_counter()
                value = clone(questions)
                elapsed = time.perf_counter() - started
                assert value == questions
                shared_pairs = [(i, j) for i, q in enumerate(questions) for j, r in enumerate(questions[:i])
                                if q.get('ordinary_training') and q.get('ordinary_training') is r.get('ordinary_training')]
                for i, j in shared_pairs:
                    assert value[i]['ordinary_training'] is value[j]['ordinary_training']
                    assert value[i]['ordinary_training'] is not questions[i]['ordinary_training']
                value[0]['consumer_only'] = ['independent']
                assert 'consumer_only' not in questions[0]
                samples.append({'stage': 'copy_questions', 'round': round_id, 'implementation': name, 'seconds': elapsed,
                                'exact_equal_before_mutation': True, 'shared_training_pairs': shared_pairs})
                del value
        for round_id in range(3):
            order = [('original', original_gate), ('current', current_gate)]
            if round_id % 2:
                order.reverse()
            for name, gate in order:
                started = time.perf_counter()
                compatible = gate(report)
                elapsed = time.perf_counter() - started
                assert compatible is True
                samples.append({'stage': 'full_report_decoder_gate', 'round': round_id, 'implementation': name,
                                'seconds': elapsed, 'compatible': compatible})
        after = hashlib.sha256(json.dumps(questions, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        row_after = repo.one('SELECT payload_json,markdown FROM joint_period_report WHERE report_id=?', (row[0],))
        assert hashlib.sha256((row_after[0] + '\0' + row_after[1]).encode()).hexdigest() == frozen_bytes
        assert before == after
        medians = {stage: {name: statistics.median(s['seconds'] for s in samples if s['stage'] == stage and s['implementation'] == name)
                          for name in ('original', 'current')} for stage in ('copy_questions', 'full_report_decoder_gate')}
        receipt = {'diagnostic_only': True, 'full_report_performance_acceptance': False, 'fixture': 'synthetic-100000',
                   'source_commit': '64cdd53ea83ce31730aaa00fee6b1571a2fc8979', 'source_root': str(SOURCE),
                   'current_hashes': hashes, 'driver_sha256': digest(Path(__file__)), 'database': str(DATABASE),
                   'report_id': row[0], 'metric_count': len(report['current']['metrics']),
                   'task_count': len(report['current']['strength_tasks']), 'ordinary_record_ids': len(record_ids),
                   'question_content_hash': before, 'input_unchanged': before == after, 'frozen_row_bytes_unchanged': True,
                   'gc_enabled': gc.isenabled(), 'host_load': os.getloadavg(), 'samples': samples, 'medians_s': medians,
                   'source_unchanged': all(digest(ROOT / p) == h for p, h in hashes.items()),
                   'scope': 'Only copies and numeric decoder eligibility on same frozen data; no new report, browser, audit export or P95 claim.'}
        (OUTPUT / 'paired-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'medians_s': medians, 'metric_count': receipt['metric_count'], 'task_count': receipt['task_count'], 'source_unchanged': receipt['source_unchanged']}), flush=True)
    finally:
        repo.close()


if __name__ == '__main__':
    main()
