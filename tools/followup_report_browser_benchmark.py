"""Real explicit report generation and historical reopening in Chromium.

The report ID, frozen findings, plotted values and download bytes are checked.
Generation and reopening use separate app processes and the same synthetic copy.
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
from contextlib import closing
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests/training"))
from followup_page_benchmark import summarize  # noqa: E402
from followup_report_benchmark import manifest, validate_synthetic  # noqa: E402
from repair_preview_benchmark import fixture_copy  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def frozen(database, report_id):
    with closing(sqlite3.connect(database)) as connection:
        row = connection.execute("SELECT payload_json,markdown FROM joint_period_report WHERE report_id=?", (report_id,)).fetchone()
        assert row is not None
        stored = json.loads(row[0])
        preview = json.loads(connection.execute("SELECT payload_json FROM report_content_object WHERE object_id=?", (stored["reading_ref"],)).fetchone()[0])
        return stored, preview, row[1]


def phase(args, folder, database, phase_name):
    source_root = args.source_root.resolve()
    app_root = folder / "bootstrap"
    app_root.mkdir(exist_ok=True)
    if not (app_root / "src").exists():
        (app_root / "src").symlink_to(source_root / "src", target_is_directory=True)
        (app_root / ".streamlit").symlink_to(source_root / ".streamlit", target_is_directory=True)
    (app_root / "app.py").write_text(
        "import runpy,importlib\nimport streamlit as st\nfrom datetime import datetime\n"
        "class RequestClock(datetime):\n @classmethod\n def now(cls,tz=None):\n"
        f"  value=datetime.fromisoformat({args.cutoff!r})\n"
        "  return value.astimezone(tz) if tz else value.replace(tzinfo=None)\n"
        "for module in ('healthzip.analytics.workspaces','healthzip.analytics.workspace_summary'):\n"
        " importlib.import_module(module).datetime=RequestClock\n"
        "st.session_state.setdefault('review_period','本周')\n"
        f"runpy.run_path({str(source_root / 'app.py')!r},run_name='__main__')\n")
    result = {"phase": phase_name, "samples": [], "service_clock": args.cutoff}
    output = args.output / f"{phase_name}.json"
    write(output, result)
    started_service = time.perf_counter()
    with isolated_app(app_root, folder) as base, sync_playwright() as playwright:
        result["service_ready_ms"] = (time.perf_counter() - started_service) * 1000
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        context.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
        context.add_init_script("document.addEventListener('click',()=>{if(window.__reportArmed&&window.__reportClick==null)window.__reportClick=performance.now()},true)")
        page = context.new_page()
        generated = []

        def arm():
            page.evaluate("()=>{window.__reportArmed=true;window.__reportClick=null}")

        def elapsed():
            return page.evaluate("()=>performance.now()-window.__reportClick")

        def settle(previous=None, requested=None):
            page.wait_for_function("s=>{const es=[...document.querySelectorAll('[data-hz-report-id]')];return es.length===1&&es[0].dataset.hzReportId!==s.previous&&(!s.requested||es[0].dataset.hzReportId===s.requested)}",
                arg={"previous": previous, "requested": requested}, timeout=600000)
            report_id = page.locator("[data-hz-report-id]").get_attribute("data-hz-report-id")
            page.get_by_role("heading", name="本期主要变化", exact=True).wait_for(timeout=30000)
            first = elapsed()
            page.wait_for_function("()=>[...document.querySelectorAll('.js-plotly-plot')].some(e=>e.data?.some(t=>t.x?.length&&t.y?.length))", timeout=30000)
            trend = elapsed()
            page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
            interactive = elapsed()
            stored, preview, markdown = frozen(database, report_id)
            reading = preview["reading_view"]
            assert page.locator("[data-hz-report-id]").get_attribute("data-reading-view") == reading["version"]
            assert not page.get_by_test_id("stException").count()
            body = page.get_by_test_id("stMain").inner_text()
            findings = reading.get("findings", [])
            assert findings and findings[0].replace("**", "") in body
            assert page.get_by_role("heading", name="本期主要变化", exact=True).count() == 1
            assert not page.get_by_text("生成复盘后，这份阅读内容会补充", exact=False).count()
            plots = page.locator(".js-plotly-plot").evaluate_all("es=>es.map(e=>e.data.map(t=>({name:t.name,x:Array.from(t.x??[]),y:Array.from(t.y??[])})))")
            assert len(plots) == 1, "generated/history reader must show one selected frozen chart"
            chart = reading["charts"][0]
            stream = chart["comparison"]["streams"][0]
            expected = []
            for section, field, name in (("previous", "daily_points", "前期"), ("current", "daily_points", "本期"),
                                         ("current", "partial_daily_points", "本期未完整日期")):
                points = [p for p in stream.get(section, {}).get(field, []) if p.get("value") is not None]
                if points:
                    expected.append({"name": name, "x": [p["date"] for p in points],
                                     "y": [p["value"] / chart["scale"] for p in points]})
            assert plots[0] == expected, (plots, expected)
            sample = {"report_id": report_id, "first_fact_ms": first, "facts_and_trend_ms": trend,
                      "interactive_ms": interactive, "first_finding": findings[0], "actual_plots": plots,
                      "reading_view_version": reading["version"], "content_ref": stored["content_ref"],
                      "reading_ref": stored["reading_ref"], "markdown_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
                      "one_reading_path": True, "selected_period": stored["period"]}
            result["samples"].append(sample)
            write(output, result)
            return report_id

        try:
            page.goto(base + "/?workspace=review")
            page.get_by_role("button", name="生成当前周期复盘", exact=True).wait_for(timeout=90000)
            page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
            for index in range(args.warm + 1):
                if phase_name == "generation":
                    previous = generated[-1] if generated else None
                    arm()
                    page.get_by_role("button", name="生成当前周期复盘", exact=True).click()
                    identity = settle(previous=previous)
                    assert identity not in generated
                    generated.append(identity)
                else:
                    if index:
                        page.get_by_role("button", name="返回当前周期复盘", exact=True).click()
                        page.get_by_role("button", name="生成当前周期复盘", exact=True).wait_for()
                    expander = page.get_by_text("已保存的复盘", exact=True)
                    if not page.get_by_role("button", name="打开这份复盘", exact=True).is_visible():
                        expander.click()
                    chooser = page.get_by_role("combobox", name="历史复盘", exact=True)
                    chooser.click()
                    page.get_by_role("option").nth(index % 2).click()
                    page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
                    with closing(sqlite3.connect(database)) as connection:
                        rows = connection.execute("SELECT report_id FROM joint_period_report WHERE user_id='local' ORDER BY created_at DESC LIMIT 30").fetchall()
                    requested = rows[index % 2][0]
                    arm()
                    page.get_by_role("button", name="打开这份复盘", exact=True).click()
                    identity = settle(requested=requested)
                if index in (0, args.warm):
                    page.screenshot(path=str(args.output / f"{phase_name}-{index:02}-1440.png"))
            if phase_name == "generation":
                with closing(sqlite3.connect(database)) as connection:
                    found = {r[0] for r in connection.execute("SELECT report_id FROM joint_period_report")}
                assert set(generated) <= found and len(generated) == args.warm + 1
                result["distinct_new_report_ids"] = generated
            download_name = "下载身体与力量联合报告" if phase_name == "generation" else "下载这份复盘"
            with page.expect_download() as download:
                page.get_by_role("button", name=download_name, exact=True).click()
            text = Path(download.value.path()).read_bytes()
            assert hashlib.sha256(text).hexdigest() == result["samples"][-1]["markdown_sha256"]
            result["download_frozen_markdown_exact"] = True
            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_test_id("stMain").evaluate("e=>e.scrollTo(0,0)")
            page.screenshot(path=str(args.output / f"{phase_name}-390.png"))
            result["warm"] = summarize(result["samples"][1:])
            limit = 3000 if phase_name == "generation" else 1000
            result["budgets"] = {
                "cold_interactive_within_budget": result["samples"][0]["interactive_ms"] <= (15000 if phase_name == "generation" else 3000),
                "warm_30_p95_within_budget": args.warm >= 30 and result["warm"]["interactive_ms"]["p95"] <= limit,
                "cold_limit_ms": 15000 if phase_name == "generation" else 3000,
                "warm_limit_ms": limit,
            }
            result["complete"] = True
            write(output, result)
        except Exception as exc:
            result["failure"] = str(exc)
            write(output, result)
            page.screenshot(path=str(args.output / f"{phase_name}-failure.png"), full_page=True)
            raise
        finally:
            browser.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--knowledge-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cutoff", default="2026-11-22T00:00:00+08:00")
    parser.add_argument("--warm", type=int, default=30)
    parser.add_argument("--concurrent-load", required=True)
    args = parser.parse_args()
    validate_synthetic(args.database)
    args.output.mkdir(parents=True, exist_ok=False)
    source = manifest()
    write(args.output / "source-manifest.json", source)
    implementation = [p for p in (args.source_root / "src").rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    implementation += [args.source_root / "app.py", args.source_root / ".streamlit/config.toml"]
    measured = {str(p.relative_to(args.source_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in implementation}
    write(args.output / "measured-source-manifest.json", measured)
    result = {"synthetic_only": True, "platform": platform.platform(), "logical_cpu": os.cpu_count(),
              "concurrent_load": args.concurrent_load, "source_root": str(args.source_root),
              "initial_host_load": os.getloadavg(), "physical_safari": "not tested", "os_cache_cleared": False,
              "clock": "actual DOM generate/open click to new frozen report identity, main finding, real chart and interactive UI",
              "phases": []}
    with tempfile.TemporaryDirectory(prefix="followup-report-browser-") as temporary:
        folder = Path(temporary)
        database, counts = fixture_copy(args.database, folder)
        result["counts"] = counts
        knowledge = folder / ".local/knowledge"
        knowledge.mkdir()
        for name in ("sources.sqlite3", "theories.sqlite3"):
            with closing(sqlite3.connect((args.knowledge_root / name).resolve().as_uri() + "?mode=ro", uri=True)) as original:
                with closing(sqlite3.connect(knowledge / name)) as copied:
                    original.backup(copied)
        for phase_name in ("generation", "reopen"):
            result["phases"].append(phase(args, folder, database, phase_name))
            write(args.output / "summary.json", result)
    result["source_changed"] = source != manifest()
    result["measured_source_changed"] = any(hashlib.sha256((args.source_root / name).read_bytes()).hexdigest() != digest
                                           for name, digest in measured.items())
    assert not result["measured_source_changed"]
    if args.source_root.resolve() == ROOT:
        assert not result["source_changed"], "source changed during acceptance"
    result["complete"] = True
    result["final_host_load"] = os.getloadavg()
    write(args.output / "summary.json", result)


if __name__ == "__main__":
    main()
