"""Thirty cold/warm page fact samples on unchanged synthetic fixture backups.

These are backend timings, never substituted for browser completion timings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path

from healthzip.analytics.cache import clear
from healthzip.analytics.workspace_summary import workspace_summary
from healthzip.analytics.workspaces import analyze_workspace
from healthzip.db.repository import Repository


def sample(compute):
    start = time.perf_counter()
    value = compute()
    milliseconds = (time.perf_counter() - start) * 1000
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    return {'milliseconds': milliseconds, 'returned_json_bytes': len(content),
            'result_sha256': hashlib.sha256(content).hexdigest(),
            'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}, value


def describe(rows):
    values = sorted(row['milliseconds'] for row in rows)
    return {'n': len(rows), 'p50_ms': statistics.median(values),
            'p95_ms': values[min(len(values)-1, int(len(values)*.95))], 'samples': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--cutoff', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--page', choices=('review_preview', 'health_detail'))
    parser.add_argument('--period', choices=('week', 'month'))
    parser.add_argument('--expected-training-in-range', type=int, default=10000)
    args = parser.parse_args()
    if not args.database.name.startswith('synthetic-'):
        raise ValueError('synthetic_only')
    report = {'kind': 'backend_fact_return_not_browser_or_report', 'data': 'original_synthetic_backup',
              'database_bytes': args.database.stat().st_size, 'analysis_cutoff': args.cutoff,
              'source_sha256': {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in
                  map(Path, ('src/healthzip/analytics/workspace_summary.py', 'src/healthzip/analytics/workspaces.py',
                             'src/healthzip/training/service.py', 'tools/repair_pages_backend.py'))},
              'cold_definition': 'running process; clear all bounded analytic result caches before each sample; OS cache retained',
              'hot_definition': 'same committed revision/range/cutoff, no clear, 30 repeats',
              'environment': {'cpu_count': os.cpu_count(), 'platform': platform.platform(),
                'memory_total_kib': next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:')),
                'load_average_start': os.getloadavg(), 'concurrent_load': 'shared host; process log recorded separately'},
              'cohorts': []}
    with tempfile.TemporaryDirectory(prefix='hz-repair-pages-backend-') as temp:
        target = Path(temp)/'synthetic.sqlite3'
        with sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro',uri=True) as source, sqlite3.connect(target) as dest:
            source.backup(dest)
        repo = Repository(target)
        try:
            report['health_sample_count'] = repo.one('SELECT count(*) FROM health_sample')[0]
            report['training_set_count'] = repo.one('SELECT count(*) FROM strength_set')[0]
            for page in (args.page,) if args.page else ('review_preview','health_detail'):
                for period in (args.period,) if args.period else ('week','month'):
                    def compute():
                        if page == 'review_preview':
                            return workspace_summary(repo, '总览', cutoff_time=args.cutoff, period=period)
                        return analyze_workspace(repo, '心率', cutoff_time=args.cutoff, period=period)
                    cold = []
                    for _ in range(30):
                        clear()
                        row, value = sample(compute)
                        cold.append(row)
                    hot = [sample(compute)[0] for _ in range(30)]
                    identity = {'periods': [p['period'] for p in value.get('periods',[])],
                        'query_plan': value.get('query_plan') or value.get('workspace_scope',{}).get('query_plan')}
                    if page == 'review_preview':
                        assert identity['periods'] == [period]
                        identity['completed_source_group_count'] = next(
                            fact['value'] for fact in value['periods'][0]['facts'] if fact['label']=='已完成实际组')
                        assert identity['completed_source_group_count'] == args.expected_training_in_range
                    entry = {'page': page, 'period': period, 'cold': describe(cold), 'hot': describe(hot),
                             'actual_returned_identity': identity,
                             'cold_backend_3s': max(row['milliseconds'] for row in cold) <= 3000,
                             'hot_backend_1s': describe(hot)['p95_ms'] <= 1000}
                    report['cohorts'].append(entry)
                    args.output.parent.mkdir(parents=True,exist_ok=True)
                    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
                    print(json.dumps({'page':page,'period':period,'cold_p95_ms':entry['cold']['p95_ms'],
                        'hot_p95_ms':entry['hot']['p95_ms']},ensure_ascii=False),flush=True)
        finally:
            repo.close()
    report['environment']['load_average_end'] = os.getloadavg()
    report['peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    main()
