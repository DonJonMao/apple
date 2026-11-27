"""Measure real Streamlit/Chromium page stages against a supplied synthetic database."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests/training"))
from strength_workbench_browser_check import isolated_app  # noqa: E402


def percentile(rows, key, q):
    values = sorted(row[key] for row in rows)
    return values[min(len(values) - 1, round((len(values) - 1) * q))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cutoff", required=True)
    args = parser.parse_args()
    database = Path(args.database).resolve()
    if not database.name.startswith("synthetic-"):
        raise ValueError("This acceptance tool only accepts explicitly synthetic fixtures")
    report = {"data": "synthetic_only", "transport": "same-host HTTP and Streamlit WebSocket",
              "remote_phone_network": "not_tested", "platform": platform.platform(),
              "cpu_count": os.cpu_count(), "python": platform.python_version(),
              "sqlite": sqlite3.sqlite_version, "os_cache_cleared": False,
              "analysis_cutoff": args.cutoff, "load_average_start": os.getloadavg(),
              "host_memory_kib": next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:')),
              "source_sha256": {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
                  'app.py', 'src/healthzip/ui/health_comparison.py', 'src/healthzip/ui/body_pages.py',
                  'src/healthzip/analytics/workspaces.py', 'tools/repair_page_benchmark.py')},
              "concurrent_load": "other acceptance processes may run; not an exclusive host", "database_bytes": database.stat().st_size}
    with tempfile.TemporaryDirectory(prefix="healthzip-page-benchmark-") as temporary:
        folder = Path(temporary)
        target = folder / ".local/healthzip.sqlite3"
        target.parent.mkdir(parents=True)
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as source, sqlite3.connect(target) as dest:
            source.backup(dest)
            report["health_sample_count"] = dest.execute("SELECT count(*) FROM health_sample").fetchone()[0]
            report["training_set_count"] = dest.execute("SELECT count(*) FROM strength_set").fetchone()[0]
        start = time.perf_counter()
        app_root = folder/'bootstrap'
        app_root.mkdir()
        (app_root/'src').symlink_to(ROOT/'src', target_is_directory=True)
        (app_root/'.streamlit').symlink_to(ROOT/'.streamlit', target_is_directory=True)
        (app_root/'app.py').write_text(
            'import importlib, runpy\nfrom datetime import datetime\n'
            'class FixedRequestClock(datetime):\n'
            '    @classmethod\n'
            '    def now(cls, tz=None):\n'
            f'        value = datetime.fromisoformat({args.cutoff!r})\n'
            '        return value.astimezone(tz) if tz else value.replace(tzinfo=None)\n'
            "for name in ('healthzip.analytics.workspaces','healthzip.analytics.workspace_summary'):\n"
            '    importlib.import_module(name).datetime = FixedRequestClock\n'
            f'runpy.run_path({str(ROOT/"app.py")!r},run_name="__main__")\n')
        with isolated_app(app_root, folder) as base, sync_playwright() as p:
            report["service_ready_ms"] = (time.perf_counter() - start) * 1000
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            report["browser"] = browser.version
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            context.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
            context.add_init_script("""document.addEventListener('click', () => {
                if(window.__benchmarkArmed && window.__benchmarkClick == null)
                    window.__benchmarkClick = performance.now();
            }, true);""")
            page = context.new_page()
            seen = set()
            def arm():
                page.evaluate("() => {window.__benchmarkArmed=true;window.__benchmarkClick=null;}")
            def since_click(fallback):
                value = page.evaluate("() => window.__benchmarkClick == null ? null : performance.now()-window.__benchmarkClick")
                return fallback if value is None else value
            def finish(started, marker=None, *, require_new_snapshot=False):
                page.wait_for_function("s => {const e=document.querySelector('[data-hz-render]');return e && e.dataset.workspace==='heart' && e.dataset.hzRender!==s.old && !s.seen.includes(e.dataset.hzRender)}", arg={'old': marker, 'seen': list(seen)}, timeout=60000)
                page.get_by_test_id("stMetricLabel").filter(has_text="静息心率").first.wait_for(timeout=30000)
                fact = since_click((time.perf_counter() - started) * 1000)
                page.get_by_test_id("stPlotlyChart").first.wait_for(timeout=30000)
                page.wait_for_function("() => [...document.querySelectorAll('.js-plotly-plot')].some(p=>p.data?.some(t=>t.x?.length&&t.y?.length))", timeout=30000)
                trend = since_click((time.perf_counter() - started) * 1000)
                page.wait_for_function("old => {const e=document.querySelector('[data-hz-render]');return e && e.dataset.workspace==='heart' && e.dataset.hzRender!==old}", arg=marker, timeout=30000)
                page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
                automation = (time.perf_counter() - started) * 1000
                interactive = since_click(automation)
                server = float(page.locator('[data-hz-render]').get_attribute('data-server-ms'))
                snapshot = page.locator('[data-hz-render]').evaluate('e=>({...e.dataset})')
                seen.add(snapshot['hzRender'])
                facts = page.get_by_test_id('stMetric').evaluate_all("els=>els.map(e=>({label:e.querySelector('[data-testid=stMetricLabel]')?.innerText,value:e.querySelector('[data-testid=stMetricValue]')?.innerText}))")
                plots = page.locator('.js-plotly-plot').evaluate_all("els=>els.map(e=>e.data.map(t=>({name:t.name,x:Array.from(t.x??[]),y:Array.from(t.y??[])})))")
                selected = next(label for label in ('本周','本月','近30天') if page.get_by_role('radio',name=label,exact=True).is_checked())
                assert not page.get_by_test_id('stException').count()
                return {"first_fact_ms": fact, "facts_and_trend_ms": trend,
                        "full_interaction_ms": interactive, "server_page_ms": server,
                        "automation_request_to_settled_ms": automation,
                        'completed_snapshot': snapshot, 'actual_facts': facts, 'actual_plots': plots,
                        'selected_range': selected}
            started = time.perf_counter()
            page.goto(base + "/?workspace=heart")
            report["first_open_new_process"] = finish(started)
            # Cold page facts in an already started process: each selected range
            # is new; the separate backend benchmark measures cleared identical keys.
            cold = []
            for label in ("本周", "本月"):
                old = page.locator('[data-hz-render]').get_attribute('data-hz-render')
                arm()
                started = time.perf_counter()
                page.get_by_role('radio', name=label, exact=True).locator('xpath=ancestor::label[1]').click()
                cold.append(finish(started, old, require_new_snapshot=True))
            report["running_process_new_range_cold"] = cold
            rows = []
            for _ in range(30):
                page.get_by_role('radio', name='总览', exact=True).locator('xpath=ancestor::label[1]').click()
                page.wait_for_function("() => document.querySelector('[data-hz-render]')?.dataset.workspace==='overview'")
                page.get_by_test_id('stStatusWidget').wait_for(state='hidden')
                old = page.locator('[data-hz-render]').get_attribute('data-hz-render')
                arm()
                started = time.perf_counter()
                page.get_by_role('radio', name='身体', exact=True).locator('xpath=ancestor::label[1]').click()
                rows.append(finish(started, old, require_new_snapshot=True))
            report["warm_return"] = {"n": len(rows), "samples": rows,
                **{key: {"p50": percentile(rows, key, .5), "p95": percentile(rows, key, .95)} for key in rows[0] if isinstance(rows[0][key], (int,float))}}
            report["initial_navigation_network_ms"] = page.evaluate("""() => {
                const n=performance.getEntriesByType('navigation')[0];return {
                    response:n.responseEnd-n.requestStart,document:n.domContentLoadedEventEnd-n.startTime};
            }""")
            report["network_limit"] = "Warm navigation uses multiplexed WebSocket; network, Streamlit queue, serialization and paint residual is included end-to-end and not attributed to pure network."
            report["measurement_clock"] = "Fact/trend timings wait for the new completed page snapshot (conservative upper bound, excludes stale prior DOM). Navigation samples start at the actual captured DOM click event. Automation command-to-settled is separate and includes Playwright actionability waiting. First open starts before page.goto."
            report["budget_met"] = {"warm_p95_800ms": report['warm_return']['facts_and_trend_ms']['p95'] <= 800,
                "warm_p95_1000ms": report['warm_return']['facts_and_trend_ms']['p95'] <= 1000,
                "running_cold_3s": max(row['full_interaction_ms'] for row in cold) <= 3000}
            context.close()
            browser.close()
        from healthzip.analytics.workspaces import analyze_workspace
        from healthzip.db.repository import Repository
        repo = Repository(target)
        expected = {}
        try:
            for label, period in (('本周','week'),('本月','month'),('近30天','30d')):
                view = analyze_workspace(repo, '心率', period=period, cutoff_time=args.cutoff, timezone_name='Asia/Shanghai')
                cards, plots = [], []
                for mid, title, unit in (('STATE-RHR','日静息心率','bpm'),('STATE-SDNN','HRV（SDNN）','ms')):
                    for stream in view['workspace_scope']['metrics'][mid].get('comparison',{}).get('streams',[]):
                        current = stream.get('current',{})
                        value = current.get('value')
                        shown = ('暂无完整日' if current.get('partial_daily_points') else '暂无记录') if value is None else f'{value:.1f} {unit}'
                        cards.append({'label':title,'value':shown})
                        traces = []
                        for window, field, name in (('previous','daily_points','前期'),('current','daily_points','本期'),('current','partial_daily_points','本期未完整日期')):
                            points = [p for p in stream.get(window,{}).get(field,[]) if p.get('value') is not None]
                            if points:
                                traces.append({'name':name,'x':[p['date'] for p in points],'y':[p['value'] for p in points]})
                        if traces:
                            plots.append(traces)
                expected[label] = {'cards':cards,'plots':plots,'window':view['workspace_scope'].get('window')}
            for sample in [report['first_open_new_process'], *cold, *rows]:
                correct = expected[sample['selected_range']]
                actual = [card for card in sample['actual_facts'] if card['label'] in {'日静息心率','HRV（SDNN）'}]
                assert actual == correct['cards'], (actual,correct['cards'])
                assert sample['actual_plots'][:len(correct['plots'])] == correct['plots']
            report['rendered_values_and_plot_arrays_verified'] = True
            report['expected_normal_analysis'] = expected
        finally:
            repo.close()
    report['load_average_end'] = os.getloadavg()
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"health_sample_count":report['health_sample_count'],"first":report['first_open_new_process'],
                      "warm":{key:value for key,value in report['warm_return'].items() if key!='samples'},
                      "budget_met":report['budget_met']},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
