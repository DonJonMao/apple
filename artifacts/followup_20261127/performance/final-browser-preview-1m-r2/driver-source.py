"""Real browser fact/trend latency with independently cold week/month processes."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests/training"))
from followup_report_benchmark import manifest, validate_synthetic  # noqa: E402
from repair_preview_benchmark import fixture_copy  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def summarize(rows):
    out = {"n": len(rows), "samples": rows, "quantile_method": "nearest-rank"}
    for key in ("first_fact_ms", "facts_and_trend_ms", "interactive_ms"):
        values = sorted(row[key] for row in rows)
        out[key] = {"p50": values[math.ceil(len(values) * .5) - 1], "p95": values[math.ceil(len(values) * .95) - 1]}
    return out


def expected(database, page_type, period, cutoff):
    from healthzip.analytics.workspace_summary import workspace_summary
    from healthzip.analytics.workspaces import analyze_workspace
    from healthzip.db.repository import Repository
    from healthzip.ui.overview import _select_cards
    with closing(Repository(database)) as repo:
        if page_type == "preview":
            value = workspace_summary(repo, "总览", timezone_name="Asia/Shanghai", cutoff_time=cutoff, period=period)["periods"][0]
            cards = [{"label": label, "value": (f"{fact['value']:,.0f}" if fact.get("unit") in {"次", "场", "组"}
                     else f"{fact['value']:,.1f}") + " " + fact.get("unit", "")}
                     for label, fact in _select_cards(value["facts"])]
            return {"cards": cards, "window": value["window"], "conclusions": value.get("conclusions", [])[:3],
                    "trend": [(row["date"], row.get("completed_work_sets", row.get("work_sets", 0)))
                              for row in value.get("strength_daily", [])]}
        value = analyze_workspace(repo, "心率", period=period, cutoff_time=cutoff, timezone_name="Asia/Shanghai")
        cards, plots = [], []
        for metric, title, unit in (("STATE-RHR", "日静息心率", "bpm"), ("STATE-SDNN", "HRV（SDNN）", "ms")):
            for stream in value["workspace_scope"]["metrics"][metric].get("comparison", {}).get("streams", []):
                current = stream.get("current", {})
                number = current.get("value")
                shown = ("暂无完整日" if current.get("partial_daily_points") else "暂无记录") if number is None else f"{number:.1f} {unit}"
                cards.append({"label": title, "value": shown})
                traces = []
                for window, field, name in (("previous", "daily_points", "前期"),
                        ("current", "daily_points", "本期"), ("current", "partial_daily_points", "本期未完整日期")):
                    points = [p for p in stream.get(window, {}).get(field, []) if p.get("value") is not None]
                    if points:
                        traces.append({"name": name, "x": [p["date"] for p in points], "y": [p["value"] for p in points]})
                if traces:
                    plots.append(traces)
        return {"cards": cards, "plots": plots, "window": value["workspace_scope"].get("window")}


def run_process(args, folder, *, mode, period, warm_count):
    target, counts = fixture_copy(args.database, folder)
    app_root = folder / "bootstrap"
    app_root.mkdir()
    (app_root / "src").symlink_to(ROOT / "src", target_is_directory=True)
    (app_root / ".streamlit").symlink_to(ROOT / ".streamlit", target_is_directory=True)
    bootstrap = (
        "import runpy,importlib\nimport streamlit as st\nfrom datetime import datetime\n"
        "class RequestClock(datetime):\n"
        " @classmethod\n"
        " def now(cls,tz=None):\n"
        f"  value=datetime.fromisoformat({args.cutoff!r})\n"
        "  return value.astimezone(tz) if tz else value.replace(tzinfo=None)\n"
        "for module in ('healthzip.analytics.workspaces','healthzip.analytics.workspace_summary'):\n"
        " importlib.import_module(module).datetime=RequestClock\n"
        "if not st.session_state.get('_followup_clock_initialized'):\n"
        f" st.session_state['body_period']={'本周' if period == 'week' else '本月'!r}\n"
        f" st.session_state['review_period']={'本周' if period == 'week' else '本月'!r}\n"
        " st.session_state['body_section']='心率'\n"
        " st.session_state['_followup_clock_initialized']=True\n"
        f"runpy.run_path({str(ROOT / 'app.py')!r},run_name='__main__')\n")
    (app_root / "app.py").write_text(bootstrap)
    label = f"{mode}-{period}"
    phase_path = args.output / f"{label}.json"
    result = {**counts, "mode": mode, "period": period, "bootstrap": bootstrap, "warm_samples": []}
    result["original_database_bytes"] = args.database.stat().st_size
    result["backup_database_bytes_before"] = target.stat().st_size
    write(phase_path, result)
    page_type = args.page
    workspace, destination = ("review", "复盘") if page_type == "preview" else ("heart", "身体")
    start = time.perf_counter()
    with isolated_app(app_root, folder) as base, sync_playwright() as playwright:
        result["service_ready_ms"] = (time.perf_counter() - start) * 1000
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        result["browser"] = browser.version
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
        context.add_init_script("document.addEventListener('click',()=>{if(window.__followupArmed&&window.__followupClick==null)window.__followupClick=performance.now()},true)")
        page = context.new_page()
        seen = set()

        def arm():
            page.evaluate("()=>{window.__followupArmed=true;window.__followupClick=null}")

        def settings_ready():
            # Settings is outside app.py's measured analysis branch and has no
            # render marker. Require its real control and removal of old output.
            page.get_by_role("button", name="保存基础资料与目标", exact=True).wait_for(timeout=60000)
            page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
            page.locator("[data-hz-render]").wait_for(state="detached", timeout=30000)
            assert not page.locator(".js-plotly-plot").count(), "previous chart must be removed before the next timed click"
            page.wait_for_function("()=>!(window.__previousFactNodes??[]).some(e=>e.node.isConnected&&e.node.innerText===e.text)", timeout=30000)
            result.setdefault("settings_transitions", []).append({"prior_fact_output_removed_or_replaced": True,
                "remaining_settings_metrics": page.get_by_test_id("stMetric").all_text_contents()})

        def elapsed(started):
            value = page.evaluate("()=>window.__followupClick==null?null:performance.now()-window.__followupClick")
            return value if value is not None else (time.perf_counter() - started) * 1000

        def settle(started):
            page.wait_for_function("s=>{const e=document.querySelector('[data-hz-render]');return e&&e.dataset.workspace===s.workspace&&!s.seen.includes(e.dataset.hzRender)}",
                                   arg={"workspace": workspace, "seen": list(seen)}, timeout=90000)
            page.get_by_test_id("stMetric").first.wait_for(timeout=30000)
            page.wait_for_function("()=>[...document.querySelectorAll('[data-testid=stMetric]')].some(e=>e.querySelector('[data-testid=stMetricLabel]')?.innerText.trim()&&e.querySelector('[data-testid=stMetricValue]')?.innerText.trim())", timeout=30000)
            first = elapsed(started)
            page.wait_for_function("()=>[...document.querySelectorAll('.js-plotly-plot')].some(p=>p.data?.some(t=>t.x?.length&&t.y?.length))", timeout=30000)
            trend = elapsed(started)
            page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
            interactive = elapsed(started)
            assert not page.get_by_test_id("stException").count()
            snapshot = page.locator("[data-hz-render]").evaluate("e=>({...e.dataset})")
            assert snapshot["workspace"] == workspace and snapshot["hzRender"] not in seen
            seen.add(snapshot["hzRender"])
            assert page.get_by_role("radio", name="本周" if period == "week" else "本月", exact=True).is_checked()
            facts = page.get_by_test_id("stMetric").evaluate_all("es=>es.map(e=>({label:e.querySelector('[data-testid=stMetricLabel]')?.innerText,value:e.querySelector('[data-testid=stMetricValue]')?.innerText}))")
            plots = page.locator(".js-plotly-plot").evaluate_all("es=>es.map(e=>e.data.map(t=>({name:t.name,x:Array.from(t.x??[]),y:Array.from(t.y??[])})))")
            return {"first_fact_ms": first, "facts_and_trend_ms": trend, "interactive_ms": interactive,
                    "automation_to_settled_ms": (time.perf_counter() - started) * 1000,
                    "snapshot": snapshot, "selected_period": period, "facts": facts, "plots": plots}

        try:
            if mode == "new-process":
                started = time.perf_counter()
                page.goto(base + "/?workspace=" + workspace)
            else:
                page.goto(base + "/?workspace=settings")
                settings_ready()
                arm()
                started = time.perf_counter()
                page.get_by_role("radio", name=destination, exact=True).locator("xpath=ancestor::label[1]").click()
            result["cold"] = settle(started)
            write(phase_path, result)
            page.screenshot(path=str(args.output / f"{label}-cold.png"))
            for _ in range(warm_count):
                page.evaluate("()=>{window.__previousFactNodes=[...document.querySelectorAll('[data-testid=stMetric]')].map(node=>({node,text:node.innerText}))}")
                page.get_by_role("radio", name="设置", exact=True).locator("xpath=ancestor::label[1]").click()
                settings_ready()
                arm()
                started = time.perf_counter()
                page.get_by_role("radio", name=destination, exact=True).locator("xpath=ancestor::label[1]").click()
                result["warm_samples"].append(settle(started))
                write(phase_path, result)
        except Exception as exc:
            result["failure"] = str(exc)
            write(phase_path, result)
            page.screenshot(path=str(args.output / f"{label}-failure.png"), full_page=True)
            (args.output / f"{label}-failure.html").write_text(page.content())
            raise
        finally:
            browser.close()
    reference = expected(target, page_type, period, args.cutoff)
    for sample in [result["cold"], *result["warm_samples"]]:
        if page_type == "preview":
            assert sample["facts"] == reference["cards"], (sample["facts"], reference["cards"])
            if reference["trend"]:
                assert list(zip(sample["plots"][0][0]["x"], sample["plots"][0][0]["y"])) == reference["trend"]
        else:
            actual = [f for f in sample["facts"] if f["label"] in {"日静息心率", "HRV（SDNN）"}]
            assert actual == reference["cards"], (actual, reference["cards"])
            assert sample["plots"][:len(reference["plots"])] == reference["plots"]
    result["rendered_facts_and_trends_verified"] = True
    result["verified_plot_scope"] = "RHR and SDNN current/previous actual points" if page_type == "detail" else "selected-period actual strength trend"
    with closing(sqlite3.connect(target)) as connection:
        table = connection.execute("SELECT 1 FROM sqlite_master WHERE name='joint_period_report'").fetchone()
        after = connection.execute("SELECT count(*) FROM joint_period_report").fetchone()[0] if table else 0
    assert after == counts["full_report_count_before"]
    result["full_reports_generated"] = 0
    result["expected_normal_service"] = reference
    if warm_count:
        result["warm"] = summarize(result.pop("warm_samples"))
    result["complete"] = True
    write(phase_path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--page", choices=("detail", "preview"), required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warm", type=int, default=30)
    parser.add_argument("--concurrent-load", required=True)
    args = parser.parse_args()
    validate_synthetic(args.database)
    args.output.mkdir(parents=True, exist_ok=False)
    source = manifest()
    source[str(Path(__file__).relative_to(ROOT))] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    write(args.output / "source-manifest.json", source)
    report = {"page": args.page, "synthetic_only": True, "cutoff": args.cutoff,
              "platform": platform.platform(), "logical_cpu": os.cpu_count(),
              "memory": Path("/proc/meminfo").read_text().splitlines()[0],
              "initial_host_load": os.getloadavg(), "concurrent_load": args.concurrent_load,
              "os_cache_cleared": False, "external_model": "not called", "physical_safari": "not tested",
              "clock": "actual DOM click to new render identity + real values + plots; conservative stage completion",
              "cold_design": "each mode/range uses separate service process and original synthetic SQLite backup",
              "phases": []}
    write(args.output / "summary.json", report)
    temp = tempfile.mkdtemp(prefix="followup-pages-")
    report["retained_synthetic_workspace"] = temp
    write(args.output / "summary.json", report)
    try:
        for mode, period, count in (("new-process", "week", 0), ("running-process", "week", 0),
                                    ("running-process", "month", args.warm)):
            folder = Path(temp) / f"{mode}-{period}"
            try:
                phase = run_process(args, folder, mode=mode, period=period, warm_count=count)
            finally:
                log = folder / "synthetic-streamlit.log"
                if log.exists():
                    shutil.copyfile(log, args.output / f"{mode}-{period}-streamlit.txt")
            report["phases"].append(phase)
            write(args.output / "summary.json", report)
    except Exception as exc:
        report["failure"] = repr(exc)
        write(args.output / "summary.json", report)
        raise
    cold_boundary = "facts_and_trend_ms" if args.page == "detail" else "first_fact_ms"
    report["budgets"] = {"cold_completion_boundary": cold_boundary,
                         "running_week_le_3s": report["phases"][1]["cold"][cold_boundary] <= 3000,
                         "running_month_le_3s": report["phases"][2]["cold"][cold_boundary] <= 3000,
                         "warm_30_fact_trend_p95_le_1s": args.warm >= 30 and report["phases"][2]["warm"]["facts_and_trend_ms"]["p95"] <= 1000}
    report["final_host_load"] = os.getloadavg()
    report["source_changed"] = any(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest for path, digest in source.items())
    assert not report["source_changed"], "source changed during performance run"
    report["complete"] = True
    write(args.output / "summary.json", report)
    print(json.dumps(report["budgets"], indent=2))


if __name__ == "__main__":
    main()
