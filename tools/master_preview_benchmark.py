"""Real Chromium period-preview timings; only read-only synthetic source backups.

Cold week/month use separate processes because workspace_summary computes both
periods together. A temporary monthly bootstrap selects a UI radio default once;
it does not alter product code, data, calculations, clocks, or caches.
"""
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
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests/training"))
from strength_workbench_browser_check import isolated_app  # noqa: E402

TIMINGS = ("first_fact_ms", "facts_and_trend_ms", "full_interaction_ms", "server_page_ms",
           "automation_request_to_settled_ms")
NEW_REVIEW = """state => {const e=document.querySelector('[data-hz-render]');
return e && e.dataset.workspace==='review' && e.dataset.hzRender!==state.old && !state.seen.includes(e.dataset.hzRender);}"""


def percentile(rows, key, q):
    values = sorted(row[key] for row in rows)
    return values[min(len(values)-1, round((len(values)-1)*q))]


def fixture_copy(database, folder):
    target = folder / ".local/healthzip.sqlite3"
    target.parent.mkdir(parents=True)
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as source, sqlite3.connect(target) as dest:
        source.backup(dest)
        counts = {"health_sample_count": dest.execute("SELECT count(*) FROM health_sample").fetchone()[0],
                  "training_set_count": dest.execute("SELECT count(*) FROM strength_set").fetchone()[0],
                  "full_report_count_before": dest.execute("SELECT count(*) FROM joint_period_report").fetchone()[0] if dest.execute("SELECT 1 FROM sqlite_master WHERE name='joint_period_report'").fetchone() else 0}
    return target, counts


def run_process(database, folder, *, mode, period, warm_samples):
    target, counts = fixture_copy(database, folder)
    app_root = ROOT
    bootstrap = None
    if period == "month":
        app_root = folder / "bootstrap"
        app_root.mkdir()
        (app_root / "src").symlink_to(ROOT / "src", target_is_directory=True)
        (app_root / ".streamlit").symlink_to(ROOT / ".streamlit", target_is_directory=True)
        bootstrap = ("import runpy\nimport streamlit as st\n"
                     "if not st.session_state.get('_preview_benchmark_initialized'):\n"
                     "    st.session_state['review_period'] = '本月'\n"
                     "    st.session_state['_preview_benchmark_initialized'] = True\n"
                     f"runpy.run_path({str(ROOT / 'app.py')!r}, run_name='__main__')\n")
        (app_root / "app.py").write_text(bootstrap)
    report = {**counts, "mode": mode, "requested_initial_period": period,
              "monthly_bootstrap": bootstrap, "cold_summary_cache": True}
    started_service = time.perf_counter()
    with isolated_app(app_root, folder) as base, sync_playwright() as playwright:
        report["service_ready_ms"] = (time.perf_counter()-started_service)*1000
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        report["browser"] = browser.version
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
        context.add_init_script("""document.addEventListener('click', () => {
            if(window.__previewArmed && window.__previewClick == null)
                window.__previewClick=performance.now();},true);""")
        page = context.new_page()
        seen_review_markers = set()

        def checked_period():
            week = page.get_by_role("radio", name="本周", exact=True).is_checked()
            month = page.get_by_role("radio", name="本月", exact=True).is_checked()
            assert week != month, {"week_checked": week, "month_checked": month}
            return "week" if week else "month"

        def selected_snapshot(workspace):
            snapshot = page.locator("[data-hz-render]").evaluate("e=>({...e.dataset})")
            assert snapshot["workspace"] == workspace
            return snapshot

        def choose_period(label, workspace):
            old = page.locator("[data-hz-render]").get_attribute("data-hz-render")
            page.get_by_role("radio", name=label, exact=True).locator("xpath=ancestor::label[1]").click()
            page.wait_for_function("s=>{const e=document.querySelector('[data-hz-render]');return e&&e.dataset.workspace===s.workspace&&e.dataset.hzRender!==s.old}", arg={"workspace": workspace, "old": old}, timeout=60000)
            page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
            assert checked_period() == ("week" if label == "本周" else "month")
            return selected_snapshot(workspace)

        def arm():
            page.evaluate("() => {window.__previewArmed=true;window.__previewClick=null;}")

        def elapsed(started):
            value = page.evaluate("() => window.__previewClick == null ? null : performance.now()-window.__previewClick")
            return (time.perf_counter()-started)*1000 if value is None else value

        def settle(started, old=None):
            # Never time stale facts/plots from the last page or last period.
            page.wait_for_function(NEW_REVIEW, arg={"old": old, "seen": list(seen_review_markers)}, timeout=90000)
            page.get_by_test_id("stMetricLabel").filter(has_text="完成训练").first.wait_for(timeout=30000)
            fact = elapsed(started)
            page.get_by_test_id("stPlotlyChart").first.wait_for(timeout=30000)
            page.wait_for_function("() => [...document.querySelectorAll('.js-plotly-plot')].some(p=>p.data?.some(t=>t.x?.length&&t.y?.length))", timeout=30000)
            trend = elapsed(started)
            page.get_by_role("button", name="生成当前周期复盘", exact=True).wait_for(timeout=30000)
            page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
            full = elapsed(started)
            settled_automation = (time.perf_counter()-started)*1000
            snapshot = page.locator("[data-hz-render]").evaluate("e=>({...e.dataset})")
            assert snapshot["workspace"] == "review" and snapshot["hzRender"] != old
            actual = page.get_by_test_id("stMetric").evaluate_all("els=>els.map(e=>({label:e.querySelector('[data-testid=stMetricLabel]')?.innerText,value:e.querySelector('[data-testid=stMetricValue]')?.innerText}))")
            plot = page.locator(".js-plotly-plot").first.evaluate("e=>e.data.map(t=>({type:t.type,x:Array.from(t.x),y:Array.from(t.y)}))")
            selected = checked_period()
            seen_review_markers.add(snapshot["hzRender"])
            assert actual and plot and any(len(t["y"]) for t in plot)
            assert not page.get_by_test_id("stException").count()
            assert page.get_by_text("上方为本地事实预览。", exact=False).is_visible()
            return {"first_fact_ms": fact, "facts_and_trend_ms": trend,
                    "full_interaction_ms": full, "server_page_ms": float(snapshot["serverMs"]),
                    "automation_request_to_settled_ms": settled_automation,
                    "selected_period": selected, "completed_snapshot": snapshot,
                    "actual_facts": actual, "actual_trend": plot}

        if mode == "new_process":
            started = time.perf_counter()
            page.goto(base + "/?workspace=review")
            report["cold"] = settle(started)
        else:
            # Settings initializes the actual app/Repository, never summary facts.
            page.goto(base + "/?workspace=settings")
            page.get_by_role("button", name="保存基础资料与目标", exact=True).wait_for(timeout=60000)
            page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
            assert not page.get_by_test_id("stPlotlyChart").count()
            arm()
            started = time.perf_counter()
            page.get_by_role("radio", name="复盘", exact=True).locator("xpath=ancestor::label[1]").click()
            report["cold"] = settle(started)
        assert report["cold"]["selected_period"] == period
        rows = []
        if warm_samples:
            # Warm trials must reflect actual user selection, independent of
            # the cold-month bootstrap's initial session-state assignment.
            selection = [choose_period("本周", "review"), choose_period("本月", "review")]
            report["warm_user_period_selection"] = {"actions": ["本周", "本月"], "completed_snapshots": selection}
        for index in range(warm_samples):
            assert checked_period() == "month"
            departure = selected_snapshot("review")
            old = page.locator("[data-hz-render]").get_attribute("data-hz-render")
            page.get_by_role("radio", name="总览", exact=True).locator("xpath=ancestor::label[1]").click()
            page.wait_for_function("old=>{const e=document.querySelector('[data-hz-render]');return e&&e.dataset.workspace==='overview'&&e.dataset.hzRender!==old}", arg=old, timeout=60000)
            page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
            if index == 0:
                choose_period("本月", "overview")
            assert checked_period() == "month"
            overview = selected_snapshot("overview")
            overview_facts = page.get_by_test_id("stMetric").evaluate_all("els=>els.map(e=>({label:e.querySelector('[data-testid=stMetricLabel]')?.innerText,value:e.querySelector('[data-testid=stMetricValue]')?.innerText}))")
            old = overview["hzRender"]
            arm()
            started = time.perf_counter()
            page.get_by_role("radio", name="复盘", exact=True).locator("xpath=ancestor::label[1]").click()
            sample = settle(started, old)
            assert sample["selected_period"] == "month"
            sample["actual_navigation"] = {"departure_review": departure, "visited_overview": overview,
                "overview_period": "month", "overview_facts": overview_facts,
                "returned_review": sample["completed_snapshot"], "selected_period_preserved": True}
            rows.append(sample)
        report["warm_samples"] = rows
        context.close()
        browser.close()
    # Confirm actual rendered numbers/trend against normal local summary output
    # after timed browser work. This cannot warm the separate app process.
    from healthzip.analytics.workspace_summary import workspace_summary
    from healthzip.db.repository import Repository
    from healthzip.ui.overview import _select_cards
    repo = Repository(target)
    try:
        summary = workspace_summary(repo, "总览", timezone_name="Asia/Shanghai")
        expected = {}
        for item in summary["periods"]:
            facts = [{"label": title, "value": (f"{fact['value']:,.0f}" if fact.get("unit") in {"次", "场", "组"} else f"{fact['value']:,.1f}") + " " + fact.get("unit", "")}
                     for title, fact in _select_cards(item["facts"])]
            expected[item["period"]] = {"window": item["window"], "facts": facts,
                "strength_trend": [(r["date"], r.get("completed_work_sets", r.get("work_sets", 0))) for r in item.get("strength_daily", [])]}
        for sample in [report["cold"], *rows]:
            correct = expected[sample["selected_period"]]
            assert sample["actual_facts"] == correct["facts"], (sample["actual_facts"], correct)
            if sample.get("actual_navigation"):
                assert sample["actual_navigation"]["overview_facts"] == expected["month"]["facts"]
            if correct["strength_trend"]:
                actual_trend = list(zip(sample["actual_trend"][0]["x"], sample["actual_trend"][0]["y"]))
                assert actual_trend == correct["strength_trend"], (actual_trend, correct)
        report["rendered_values_verified"] = True
        report["expected_normal_summary"] = expected
        report["full_report_count_after"] = repo.one("SELECT count(*) FROM joint_period_report")[0] if repo.one("SELECT 1 FROM sqlite_master WHERE name='joint_period_report'") else 0
        report["full_reports_generated"] = report["full_report_count_after"] - report["full_report_count_before"]
        assert report["full_reports_generated"] == 0
    finally:
        repo.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    database = Path(args.database).resolve()
    if not database.name.startswith("synthetic-"):
        raise ValueError("Only explicitly synthetic fixtures are accepted")
    report = {"data": "synthetic_only", "database": str(database), "database_bytes": database.stat().st_size,
              "generated_at": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
              "cpu_count": os.cpu_count(), "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
              "transport": "same-host HTTP and Streamlit WebSocket", "remote_phone_network": "not_tested",
              "os_cache_cleared": False, "concurrent_load": "Other acceptance processes may run; not an exclusive host",
              "measurement_clock": "All fact/trend stages first wait for a new completed data-hz-render with workspace=review; conservative upper bounds exclude stale prior DOM. Click samples start at captured DOM click; first open starts before page.goto. Full report generation is never invoked.",
              "cold_design": "Three separate processes/backups: direct preview in a new process; running app initialized on settings then first week preview; running app initialized on settings then first month preview. Summary computes both periods, so each running cold period uses a separate app. Month bootstrap only initializes its UI radio once for the cold measurement. Before warm trials the real UI is clicked week then month; overview is independently selected to month once. Every warm trial verifies actual departure and distinct new overview/review completion markers, exactly one checked period radio, preserved month selection, and actual facts in both destinations.",
              "source_sha256": {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
                  "app.py", "src/healthzip/ui/review_page.py", "src/healthzip/ui/overview.py", "src/healthzip/ui/navigation.py",
                  "src/healthzip/analytics/workspace_summary.py", "tools/master_preview_benchmark.py")}}
    with tempfile.TemporaryDirectory(prefix="healthzip-preview-benchmark-") as temporary:
        folder = Path(temporary)
        reports = []
        for index, (mode, period, count) in enumerate((("new_process", "week", 0), ("running_process", "week", 0), ("running_process", "month", 30))):
            reports.append(run_process(database, folder / str(index), mode=mode, period=period, warm_samples=count))
        report.update({key: reports[0][key] for key in ("health_sample_count", "training_set_count", "browser")})
        report["first_open_new_process"] = reports[0]
        report["running_process_cold"] = {"week": reports[1], "month": reports[2]}
        rows = reports[2].pop("warm_samples")
        report["warm_return"] = {"n":len(rows), "samples":rows,
            **{key: {"p50":percentile(rows,key,.5), "p95":percentile(rows,key,.95)} for key in TIMINGS}}
        report["budget_met"] = {"running_cold_first_fact_3s": all(r["cold"]["first_fact_ms"] <= 3000 for r in reports[1:]),
            "new_process_first_fact_3s": reports[0]["cold"]["first_fact_ms"] <= 3000,
            "warm_fact_trend_p95_800ms": report["warm_return"]["facts_and_trend_ms"]["p95"] <= 800,
            "warm_fact_trend_p95_1000ms": report["warm_return"]["facts_and_trend_ms"]["p95"] <= 1000}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"counts": [report["health_sample_count"],report["training_set_count"]],
        "first":report["first_open_new_process"]["cold"],
        "running_cold":{key:value["cold"] for key,value in report["running_process_cold"].items()},
        "warm":{key:value for key,value in report["warm_return"].items() if key!="samples"},
        "budget_met":report["budget_met"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
