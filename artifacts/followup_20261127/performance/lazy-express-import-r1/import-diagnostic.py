"""Light import/serialization diagnostic; no app, browser or database is opened.

Run from repository root with PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:
  .venv/bin/python artifacts/followup_20261127/performance/lazy-express-import-r1/import-diagnostic.py \
    --baseline artifacts/followup_20261127/performance/lazy-express-import-r1/body-pages-before.py \
    --candidate src/healthzip/ui/body_pages.py --output /tmp/lazy-express-receipt.json

Both variants load the app's common overview and theme imports first, then the
exact supplied body_pages source using the same in-memory loader. Two synthetic
comparison figures are serialized through the same Plotly APIs Streamlit uses.
This is not a browser latency or product performance acceptance result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path


def sample(path):
    import importlib
    import resource
    import time
    import types

    import healthzip.ui.overview  # noqa: F401
    from healthzip.ui import theme

    # Avoid a bare Streamlit UI call; retain the actual template construction.
    theme.st.markdown = lambda *_a, **_k: None
    theme.apply_theme()
    loaded_before = set(sys.modules)
    source = path.read_text()
    started = time.perf_counter()
    module = types.ModuleType('healthzip.ui.body_pages')
    module.__package__ = 'healthzip.ui'
    module.__file__ = str(path.resolve())
    sys.modules[module.__name__] = module
    exec(compile(source, str(path), 'exec'), module.__dict__)
    importlib.import_module('healthzip.ui.body_workspace')
    imported_at = time.perf_counter()
    modules_after_import = set(sys.modules)
    from healthzip.ui import health_comparison
    payload_hashes = []

    def serialize(figure, **_kwargs):
        import plotly.io
        import plotly.tools
        value = plotly.tools.return_figure_from_figure_or_data(figure, validate_figure=True)
        payload = plotly.io.to_json(value, validate=False)
        payload_hashes.append(hashlib.sha256(payload.encode()).hexdigest())

    health_comparison.st.plotly_chart = serialize
    for title, unit, number in [('日静息心率', 'bpm', 62), ('HRV（SDNN）', 'ms', 39)]:
        stream = {'previous': {'daily_points': [
            {'date': '2026-11-09', 'value': number + 3, 'n': 2},
            {'date': '2026-11-12', 'value': number + 2, 'n': 1}]},
            'current': {'window': {'start': '2026-11-16', 'end': '2026-11-23'}, 'daily_points': [
                {'date': '2026-11-17', 'value': number, 'n': 3},
                {'date': '2026-11-20', 'value': number - 1, 'n': 2}]}}
        health_comparison._chart(stream, title, unit, 1, title)
    ended = time.perf_counter()
    return {'source': str(path), 'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'route_import_seconds': imported_at - started, 'two_charts_serialization_seconds': ended - imported_at,
        'import_and_two_charts_seconds': ended - started,
        'new_modules_at_import': len(modules_after_import - loaded_before),
        'express_loaded_at_import': 'plotly.express' in modules_after_import,
        'pandas_loaded_at_import': 'pandas' in modules_after_import,
        'numpy_loaded_at_import': 'numpy' in modules_after_import,
        'express_loaded_after_charts': 'plotly.express' in sys.modules,
        'pandas_loaded_after_charts': 'pandas' in sys.modules,
        'numpy_loaded_after_charts': 'numpy' in sys.modules,
        'figure_json_sha256': payload_hashes,
        'process_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'host_load': os.getloadavg()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.sample:
        print(json.dumps(sample(args.sample)))
        return
    results = []
    for label in ('baseline', 'candidate', 'candidate', 'baseline'):
        completed = subprocess.run([sys.executable, __file__, '--sample', str(getattr(args, label))],
            check=True, text=True, capture_output=True,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        results.append({'variant': label, **json.loads(completed.stdout)})
    same_figures = all(row['figure_json_sha256'] == results[0]['figure_json_sha256'] for row in results)
    assert same_figures
    receipt = {'kind': 'light_import_and_synthetic_chart_serialization_diagnostic', 'samples': results,
        'same_figure_json_before_after': same_figures,
        'median_seconds': {label: {key: statistics.median(row[key] for row in results if row['variant'] == label)
            for key in ('route_import_seconds', 'two_charts_serialization_seconds', 'import_and_two_charts_seconds')}
            for label in ('baseline', 'candidate')},
        'limitations': ['Two samples per variant; descriptive diagnostic, not P95 or browser acceptance.',
            'Shared host load uncontrolled; root was running a separate 100k cProfile task.',
            'Common app imports and theme setup precede both measurements, matching route import ordering.',
            'No database/scientific analysis, Streamlit rendering or frontend/network time is included.',
            'No product timing boundary, completion marker, trend, caching layer or preload was changed.'],
        'private_health_opened': False, 'external_calls': 0}
    with args.output.open('x') as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(receipt['median_seconds']))


if __name__ == '__main__':
    main()
