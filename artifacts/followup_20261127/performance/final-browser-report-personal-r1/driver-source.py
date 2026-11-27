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
from followup_page_benchmark import summarize  # noqa: E402
from followup_report_benchmark import manifest, shared_knowledge, validate_synthetic  # noqa: E402
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
            page.evaluate("""()=>{window.__reportArmed=true;window.__reportClick=null;
                window.__oldReportPlots=new Set(document.querySelectorAll('.js-plotly-plot'));
                window.__oldReportRender=document.querySelector('[data-hz-render]')?.dataset.hzRender;}""")

        def elapsed():
            return page.evaluate("()=>performance.now()-window.__reportClick")

        def settle(previous=None, requested=None):
            page.wait_for_function("previous=>{const es=[...document.querySelectorAll('[data-hz-report-id]')];return es.length===1&&es[0].dataset.hzReportId!==previous}",
                arg=previous, timeout=600000 if phase_name == "generation" else 90000)
            report_id = page.locator("[data-hz-report-id]").get_attribute("data-hz-report-id")
            assert requested is None or report_id == requested, {"requested_report": requested, "opened_report": report_id}
            page.get_by_role("heading", name="本期主要变化", exact=True).wait_for(timeout=30000)
            stored, preview, markdown = frozen(database, report_id)
            reading = preview["reading_view"]
            findings = reading.get("findings", [])
            assert findings
            # Read only the frozen small object. The lookup/driver overhead is
            # conservatively included; no old conclusion can end this stage.
            page.wait_for_function("s=>document.querySelector('[data-hz-report-id]')?.dataset.hzReportId===s.id&&document.querySelector('[data-testid=stMain]')?.innerText.includes(s.finding)",
                                   arg={"id": report_id, "finding": findings[0].replace("**", "")}, timeout=30000)
            first = elapsed()
            page.wait_for_function("()=>[...document.querySelectorAll('.js-plotly-plot')].some(e=>!window.__oldReportPlots.has(e)&&e.data?.some(t=>t.x?.length&&t.y?.length))", timeout=30000)
            trend = elapsed()
            page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
            page.wait_for_function("()=>{const e=document.querySelector('[data-hz-render]');return e&&e.dataset.workspace==='review'&&e.dataset.hzRender!==window.__oldReportRender}", timeout=30000)
            interactive = elapsed()
            assert page.locator("[data-hz-report-id]").get_attribute("data-reading-view") == reading["version"]
            assert not page.get_by_test_id("stException").count()
            body = page.get_by_test_id("stMain").inner_text()
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
                      "render_identity": page.locator("[data-hz-render]").get_attribute("data-hz-render"),
                      "new_plot_dom_verified": True,
                      "one_reading_path": True, "selected_period": stored["period"]}
            result["samples"].append(sample)
            write(output, result)
            return report_id

        try:
            page.goto(base + "/?workspace=review")
            page.get_by_role("button", name="生成当前周期复盘", exact=True).wait_for(timeout=90000)
            page.wait_for_function("()=>document.querySelector('[data-hz-render]')?.dataset.workspace==='review'", timeout=90000)
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
                        previous_render = page.locator("[data-hz-render]").get_attribute("data-hz-render")
                        page.get_by_role("button", name="返回当前周期复盘", exact=True).click()
                        page.get_by_role("button", name="生成当前周期复盘", exact=True).wait_for()
                        page.locator("[data-hz-report-id]").wait_for(state="detached", timeout=30000)
                        page.wait_for_function("old=>{const e=document.querySelector('[data-hz-render]');return e&&e.dataset.workspace==='review'&&e.dataset.hzRender!==old}", arg=previous_render, timeout=30000)
                        page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
                    expander = page.get_by_text("已保存的复盘", exact=True)
                    if not page.get_by_role("button", name="打开这份复盘", exact=True).is_visible():
                        expander.click()
                    chooser = page.get_by_role("combobox", name="历史复盘", exact=True)
                    chooser.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
                    # The expander and scroll animation must settle before
                    # typing; this preparation is outside the timed Open click.
                    page.wait_for_timeout(300)
                    # A repeated identical search string need not dispatch a
                    # React change. Real keyboard navigation opens the complete
                    # version list without relying on mutable search state.
                    chooser.click()
                    chooser.press("Escape")
                    chooser.press("ArrowDown")
                    page.get_by_role("option").nth(index % 2).click()
                    page.wait_for_timeout(300)
                    page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
                    with closing(sqlite3.connect(database)) as connection:
                        rows = connection.execute("SELECT report_id FROM joint_period_report WHERE user_id='local' ORDER BY created_at DESC LIMIT 30").fetchall()
                    requested = rows[index % 2][0]
                    result.setdefault("history_selections", []).append({"index": index % 2, "requested_report_id": requested,
                        "shown_label": chooser.input_value(), "render_before_open": page.locator("[data-hz-render]").get_attribute("data-hz-render")})
                    write(output, result)
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
            result["layout_checks"] = []
            for width in (320, 375, 390, 430, 768, 1440):
                page.set_viewport_size({"width": width, "height": 844 if width < 768 else 1000})
                page.get_by_test_id("stMain").evaluate("e=>e.scrollTo(0,0)")
                # Wait two actual paint frames after responsive layout changes.
                page.evaluate("()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
                finding = page.get_by_text(result["samples"][-1]["first_finding"].replace("**", ""), exact=True).first
                box = finding.bounding_box()
                dimensions = page.evaluate("()=>({width:innerWidth,height:innerHeight,document:document.documentElement.scrollWidth,body:document.body.scrollWidth,main:document.querySelector('[data-testid=stMain]').scrollWidth})")
                check = {"width": width, "dimensions": dimensions, "first_finding_box": box,
                         "no_page_horizontal_overflow": max(dimensions[k] for k in ("document", "body", "main")) <= width + 2,
                         "complete_first_finding_in_viewport": bool(box and box["y"] >= 0 and box["y"] + box["height"] <= dimensions["height"])}
                result["layout_checks"].append(check)
                page.screenshot(path=str(args.output / f"{phase_name}-{width}.png"))
                write(output, result)
            result["layout_pass"] = all(row["no_page_horizontal_overflow"] for row in result["layout_checks"]) and next(
                row["complete_first_finding_in_viewport"] for row in result["layout_checks"] if row["width"] == 390)
            # Reading evidence is outside every latency sample. Preserve the
            # real next steps, current restriction and selectable frozen version
            # instead of relying only on screenshots of the page opening.
            result["reading_captures"] = []
            for width in (390, 1440):
                page.set_viewport_size({"width": width, "height": 844 if width == 390 else 1000})

                def capture(section, locator):
                    if section == "history-versions":
                        locator.scroll_into_view_if_needed()
                    else:
                        locator.evaluate("e=>e.scrollIntoView({block:'start',behavior:'instant'})")
                    page.evaluate("()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
                    filename = f"{phase_name}-{width}-{section}.png"
                    page.screenshot(path=str(args.output / filename))
                    identity = page.locator("[data-hz-report-id]").get_attribute("data-hz-report-id")
                    assert identity == result["samples"][-1]["report_id"]
                    content = locator.locator("xpath=ancestor::*[@data-testid='stMarkdownContainer'][1]") if section == "next-steps" else locator
                    result["reading_captures"].append({"section": section, "width": width, "screenshot": filename,
                        "report_id": identity, "visible_section_text": content.inner_text(), "box": locator.bounding_box()})

                capture("next-steps", page.get_by_role("heading", name="下一步", exact=True).first)
                restrictions = page.get_by_test_id("stAlert").filter(has_text="这份历史报告")
                if restrictions.count():
                    capture("current-sources", restrictions.first)
                else:
                    result["reading_captures"].append({"section": "current-sources", "width": width,
                        "visible_restriction_alerts": 0, "report_id": result["samples"][-1]["report_id"]})
                selector = page.get_by_role("combobox", name="历史复盘", exact=True)
                if not selector.is_visible():
                    page.get_by_text("已保存的复盘", exact=True).click()
                selector.scroll_into_view_if_needed()
                selector.click()
                selector.press("Escape")
                selector.press("ArrowDown")
                page.get_by_role("option").first.wait_for()
                labels = page.get_by_role("option").all_text_contents()
                assert len(labels) == len(set(labels)), "visible frozen-version labels must be distinct"
                capture("history-versions", page.get_by_role("listbox"))
                result["reading_captures"][-1].update(selected_label=selector.input_value(), option_labels=labels)
                selector.press("Escape")
                write(output, result)
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
            (args.output / f"{phase_name}-failure.html").write_text(page.content())
            raise
        finally:
            browser.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--knowledge-root", type=Path)
    parser.add_argument("--shared-knowledge-root", type=Path)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cutoff", default="2026-11-22T00:00:00+08:00")
    parser.add_argument("--warm", type=int, default=30)
    parser.add_argument("--concurrent-load", required=True)
    args = parser.parse_args()
    if not (args.knowledge_root or args.shared_knowledge_root):
        parser.error("provide --knowledge-root or --shared-knowledge-root")
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
    temporary = tempfile.mkdtemp(prefix="followup-report-browser-")
    result["retained_synthetic_workspace"] = temporary
    write(args.output / "summary.json", result)
    try:
        folder = Path(temporary)
        database, counts = fixture_copy(args.database, folder)
        result["counts"] = counts
        knowledge = folder / ".local/knowledge"
        if args.shared_knowledge_root:
            result["shared_knowledge_root"] = str(args.shared_knowledge_root.resolve())
            result["shared_knowledge_authority_before"] = shared_knowledge(args.shared_knowledge_root, prepare=True)
            knowledge.symlink_to(args.shared_knowledge_root.resolve(), target_is_directory=True)
        else:
            knowledge.mkdir()
            for name in ("sources.sqlite3", "theories.sqlite3"):
                with closing(sqlite3.connect((args.knowledge_root / name).resolve().as_uri() + "?mode=ro", uri=True)) as original:
                    with closing(sqlite3.connect(knowledge / name)) as copied:
                        original.backup(copied)
        write(args.output / "summary.json", result)
        for phase_name in ("generation", "reopen"):
            try:
                result["phases"].append(phase(args, folder, database, phase_name))
            finally:
                log = folder / "synthetic-streamlit.log"
                if log.exists():
                    shutil.copyfile(log, args.output / f"{phase_name}-streamlit.txt")
            write(args.output / "summary.json", result)
    except Exception as exc:
        result["failure"] = repr(exc)
        write(args.output / "summary.json", result)
        raise
    finally:
        if args.shared_knowledge_root and result.get("shared_knowledge_authority_before"):
            result["shared_knowledge_authority_after"] = shared_knowledge(args.shared_knowledge_root)
            result["shared_knowledge_authority_unchanged"] = result["shared_knowledge_authority_before"] == result["shared_knowledge_authority_after"]
            write(args.output / "summary.json", result)
    if args.shared_knowledge_root:
        assert result["shared_knowledge_authority_unchanged"], "shared public authority changed during measurement"
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
