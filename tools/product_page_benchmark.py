"""Measure real Streamlit/Chromium page stages against a supplied synthetic database."""
from __future__ import annotations

import argparse
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
    args = parser.parse_args()
    database = Path(args.database).resolve()
    if not database.name.startswith("synthetic-"):
        raise ValueError("This acceptance tool only accepts explicitly synthetic fixtures")
    report = {"data": "synthetic_only", "transport": "same-host HTTP and Streamlit WebSocket",
              "remote_phone_network": "not_tested", "platform": platform.platform(),
              "cpu_count": os.cpu_count(), "database_bytes": database.stat().st_size}
    with tempfile.TemporaryDirectory(prefix="healthzip-page-benchmark-") as temporary:
        folder = Path(temporary)
        target = folder / ".local/healthzip.sqlite3"
        target.parent.mkdir(parents=True)
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as source, sqlite3.connect(target) as dest:
            source.backup(dest)
            report["health_sample_count"] = dest.execute("SELECT count(*) FROM health_sample").fetchone()[0]
            report["training_set_count"] = dest.execute("SELECT count(*) FROM strength_set").fetchone()[0]
        start = time.perf_counter()
        with isolated_app(ROOT, folder) as base, sync_playwright() as p:
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
            def arm():
                page.evaluate("() => {window.__benchmarkArmed=true;window.__benchmarkClick=null;}")
            def since_click(fallback):
                value = page.evaluate("() => window.__benchmarkClick == null ? null : performance.now()-window.__benchmarkClick")
                return fallback if value is None else value
            def finish(started, marker=None, *, require_new_snapshot=False):
                if require_new_snapshot:
                    page.wait_for_function("old => {const e=document.querySelector('[data-hz-render]');return e && e.dataset.workspace==='heart' && e.dataset.hzRender!==old}", arg=marker, timeout=30000)
                page.get_by_test_id("stMetricLabel").filter(has_text="静息心率").first.wait_for(timeout=30000)
                fact = since_click((time.perf_counter() - started) * 1000)
                page.locator('[data-testid="stPlotlyChart"] .ytitle').filter(has_text="静息心率").first.wait_for(timeout=30000)
                trend = since_click((time.perf_counter() - started) * 1000)
                page.wait_for_function("old => {const e=document.querySelector('[data-hz-render]');return e && e.dataset.workspace==='heart' && e.dataset.hzRender!==old}", arg=marker, timeout=30000)
                page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
                automation = (time.perf_counter() - started) * 1000
                interactive = since_click(automation)
                server = float(page.locator('[data-hz-render]').get_attribute('data-server-ms'))
                return {"first_fact_ms": fact, "facts_and_trend_ms": trend,
                        "full_interaction_ms": interactive, "server_page_ms": server,
                        "automation_request_to_settled_ms": automation}
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
                page.get_by_role('radio', name='体重', exact=True).locator('xpath=ancestor::label[1]').click()
                page.wait_for_function("() => document.querySelector('[data-hz-render]')?.dataset.workspace==='weight'")
                page.get_by_test_id('stStatusWidget').wait_for(state='hidden')
                old = page.locator('[data-hz-render]').get_attribute('data-hz-render')
                arm()
                started = time.perf_counter()
                page.get_by_role('radio', name='心率', exact=True).locator('xpath=ancestor::label[1]').click()
                rows.append(finish(started, old))
            report["warm_return"] = {"n": len(rows), "samples": rows,
                **{key: {"p50": percentile(rows, key, .5), "p95": percentile(rows, key, .95)} for key in rows[0]}}
            report["initial_navigation_network_ms"] = page.evaluate("""() => {
                const n=performance.getEntriesByType('navigation')[0];return {
                    response:n.responseEnd-n.requestStart,document:n.domContentLoadedEventEnd-n.startTime};
            }""")
            report["network_limit"] = "Warm navigation uses multiplexed WebSocket; network, Streamlit queue, serialization and paint residual is included end-to-end and not attributed to pure network."
            report["measurement_clock"] = "Navigation samples start at the actual captured DOM click event. Automation command-to-settled is separate and includes Playwright actionability waiting. First open starts before page.goto."
            report["budget_met"] = {"warm_p95_800ms": report['warm_return']['facts_and_trend_ms']['p95'] <= 800,
                "running_cold_3s": max(row['full_interaction_ms'] for row in cold) <= 3000}
            context.close()
            browser.close()
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"health_sample_count":report['health_sample_count'],"first":report['first_open_new_process'],
                      "warm":{key:value for key,value in report['warm_return'].items() if key!='samples'},
                      "budget_met":report['budget_met']},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
