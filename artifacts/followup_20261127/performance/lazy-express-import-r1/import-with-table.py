"""Extend the paired import diagnostic through real Streamlit table conversion.

Usage: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python <this-file>
Output is written once beside this script. No application or database opens.
"""
import hashlib
import importlib.util
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

folder = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('import_diagnostic', folder / 'import-diagnostic.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if len(sys.argv) > 1:
    row = module.sample(Path(sys.argv[1]))
    started = time.perf_counter()
    from streamlit.dataframe_util import convert_anything_to_arrow_bytes
    payload = convert_anything_to_arrow_bytes([{'日期': '2026-11-17', '数值': 62.0},
                                              {'日期': '2026-11-20', '数值': 61.0}])
    row.update(table_conversion_seconds=time.perf_counter() - started,
               table_arrow_sha256=hashlib.sha256(payload).hexdigest())
    row['import_charts_table_seconds'] = row['import_and_two_charts_seconds'] + row['table_conversion_seconds']
    print(json.dumps(row))
else:
    paths = {'baseline': folder / 'body-pages-before.py', 'candidate': Path('src/healthzip/ui/body_pages.py')}
    rows = []
    for variant in ('baseline', 'candidate', 'candidate', 'baseline'):
        completed = subprocess.run([sys.executable, __file__, str(paths[variant])],
            text=True, capture_output=True, check=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        rows.append({'variant': variant, **json.loads(completed.stdout)})
    assert all(row['figure_json_sha256'] == rows[0]['figure_json_sha256']
               and row['table_arrow_sha256'] == rows[0]['table_arrow_sha256'] for row in rows)
    result = {'kind': 'light_paired_import_chart_and_table_diagnostic', 'samples': rows,
        'figures_and_table_identical': True,
        'median_import_charts_table_seconds': {v: statistics.median(r['import_charts_table_seconds']
            for r in rows if r['variant'] == v) for v in paths},
        'limitations': ['Two samples per variant, shared host; not browser/P95 acceptance.',
            'Includes actual Plotly figure serialization and Streamlit list-to-Arrow table conversion.',
            'Excludes SQL, analysis, Streamlit render/transport and frontend drawing; no app preloading is introduced.'],
        'private_health_opened': False, 'external_calls': 0}
    with (folder / 'import-chart-table.json').open('x') as output:
        output.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result['median_import_charts_table_seconds']))
