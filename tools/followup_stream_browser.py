"""Real report selection for same-source/device streams; synthetic records only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "tests"), str(ROOT / "tests/training")]
from followup_history_interaction import PAINTED, READY, prepare  # noqa: E402
from health_change_browser import WRAPPER  # noqa: E402
from product_redesign_browser_check import geometry, settle  # noqa: E402
from repair_delivery_browser import Check  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402

from healthzip.db.repository import Repository  # noqa: E402
from healthzip.workflows.period_report import load_report  # noqa: E402

CUTOFF = "2026-11-22T00:00:00+08:00"


def fixture(path):
    repo = Repository(path)
    start = datetime.fromisoformat("2026-11-09T08:00:00+08:00")
    for day in range(13):
        at = (start + timedelta(days=day)).isoformat()
        for group, protocol in enumerate(("固定晨间", None)):
            value = (59.5 if group == 0 else 60.0) if day < 7 else (62.5 if group == 0 else 61.0)
            row = {"id": day * 2 + group + 1, "canonical_type": "resting_heart_rate_bpm",
                   "raw_type": "resting_heart_rate_bpm", "raw_value": str(value), "normalized_value": value,
                   "raw_unit": "count/min", "normalized_unit": "count/min", "source_name": "合成协议手表",
                   "device": "synthetic-watch", "source_version": None, "start_utc": at, "end_utc": at,
                   "metadata_json": json.dumps({"protocol_id": protocol}), "record_status": "active"}
            repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,"
                "temporal_provenance) VALUES('health_sample',?,?,?,'synthetic')", (row["id"], at, json.dumps(row)))
    repo.conn.commit()
    repo.close()
    return {"records": 26, "days": 13, "same_timestamp_each_day": True,
            "source_and_device_equal": True, "protocols": ["固定晨间", None], "current_values": [62.5, 61.0]}


def legacy_report(path, knowledge, code, output):
    """Run the actual frozen source in a separate interpreter, never relabel new code."""
    script = '''import hashlib,json,sys
from pathlib import Path
from healthzip.db.repository import Repository
from healthzip.workflows import period_report
from healthzip.workflows.period_report import create_report
repo=Repository(Path(sys.argv[1]))
report=create_report(repo,{'cutoff_time':sys.argv[3],'timezone':'Asia/Shanghai'},period='week',knowledge_root=Path(sys.argv[2]))
digest=lambda value:hashlib.sha256(value.encode()).hexdigest()
payload,markdown=repo.one('SELECT payload_json,markdown FROM joint_period_report WHERE report_id=?',(report['report_id'],))
result={'report_id':report['report_id'],'version':report['version'],'executed_module':period_report.__file__,
        'payload_sha256':digest(payload),'markdown_sha256':digest(markdown),
        'objects':{r[0]:digest(r[1]) for r in repo.rows('SELECT object_id,payload_json FROM report_content_object')}}
Path(sys.argv[4]).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\\n')
Path(sys.argv[5]).write_text(markdown)
repo.close()
'''
    legacy_files = ["src/healthzip/analytics/health_context.py", "src/healthzip/workflows/period_report.py",
                    "src/healthzip/workflows/report_objects.py"]
    source_hashes = {name: hashlib.sha256((code / name).read_bytes()).hexdigest() for name in legacy_files}
    env = {**os.environ, "PYTHONPATH": str(code / "src")}
    process = subprocess.run([sys.executable, "-c", script, str(path), str(knowledge), CUTOFF,
                              str(output / "legacy-before.json"), str(output / "legacy-report.md")],
                             cwd=path.parent.parent, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (output / "legacy-generation.log").write_text(process.stdout)
    if process.returncode:
        raise RuntimeError("legacy_source_generation_failed")
    result = json.loads((output / "legacy-before.json").read_text())
    assert Path(result["executed_module"]).resolve().is_relative_to(code / "src")
    assert source_hashes == {name: hashlib.sha256((code / name).read_bytes()).hexdigest() for name in legacy_files}
    result.update(source_root=str(code), source_hashes=source_hashes)
    (output / "legacy-before.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def run(output, knowledge, legacy_source, *, legacy_menu_only=False):
    output.mkdir(parents=True, exist_ok=True)
    files = [ROOT / "app.py", ROOT / ".streamlit/config.toml", *(ROOT / "src/healthzip").rglob("*.py")]
    result = {"data": "synthetic_only", "checks": {}, "errors": [], "external_model_calls": 0,
              "legacy_menu_only": legacy_menu_only,
              "physical_iPhone_Safari": "not_verified", "completed": False,
              "source_hashes": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    receipt = output / "browser.json"
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    try:
        with tempfile.TemporaryDirectory(prefix="hz-stream-labels-") as temporary:
            folder = Path(temporary)
            path = folder / ".local/healthzip.sqlite3"
            path.parent.mkdir()
            result["fixture"] = fixture(path)
            (folder / ".local/knowledge").symlink_to(knowledge, target_is_directory=True)
            result["legacy_source"] = str(legacy_source)
            legacy = legacy_report(path, knowledge, legacy_source, output)
            assert legacy["version"] == "joint-period-report-3.0.1"
            result["legacy_report_id"] = legacy["report_id"]
            wrapper = folder / "wrapper"
            wrapper.mkdir()
            (wrapper / "src").symlink_to(ROOT / "src", target_is_directory=True)
            (wrapper / ".streamlit").symlink_to(ROOT / ".streamlit", target_is_directory=True)
            (wrapper / "app.py").write_text(WRAPPER.format(cutoff=CUTOFF, app=str(ROOT / "app.py")))
            with isolated_app(wrapper, folder) as base, sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
                result["browser"] = browser.version
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
                page.on("pageerror", lambda error: result["errors"].append(str(error)))
                check = Check(page, output, result)

                def capture(name, target=None):
                    dimensions = {}
                    for width in (320, 375, 390, 430, 768, 1440):
                        page.set_viewport_size({"width": width, "height": 844 if width == 390 else 1000})
                        if target:
                            target.evaluate("e=>e.scrollIntoView({block:'start',behavior:'instant'})")
                        else:
                            page.get_by_test_id("stMain").evaluate("e=>e.scrollTo(0,0)")
                        settle(page)
                        dimensions[str(width)] = geometry(page)
                        assert dimensions[str(width)]["document"] <= width
                        assert dimensions[str(width)]["main"] <= dimensions[str(width)]["main_client"]
                        if target:
                            dimensions[str(width)]["focused_bounds"] = target.bounding_box()
                            if name == "first-complete-finding":
                                box = dimensions[str(width)]["focused_bounds"]
                                assert box and box["y"] >= -1 and box["y"] + box["height"] <= page.viewport_size["height"]
                        page.screenshot(path=str(output / f"{name}-{width}.png"))
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    check.record(name, geometry=dimensions)

                ready = READY.replace("details?.open&&details.style.overflow!=='hidden'",
                                      "(!details||(details.open&&details.style.overflow!=='hidden'))")

                def capture_menu(name, control):
                    page.set_viewport_size({"width": 390, "height": 844})
                    control.evaluate(ready)
                    control.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
                    control.evaluate(ready)
                    control.click()
                    options = page.get_by_role("option")
                    options.first.wait_for(state="visible")
                    page.wait_for_function(PAINTED, arg=control.element_handle(), timeout=3000)
                    labels = options.all_text_contents()
                    assert len(labels) == len(set(labels)) == 2
                    dimensions = geometry(page)
                    assert dimensions["document"] <= 390 and dimensions["main"] <= dimensions["main_client"]
                    page.screenshot(path=str(output / f"{name}-390.png"))
                    assert control.evaluate(PAINTED)
                    check.record(name, options=labels, geometry=dimensions,
                                 option_bounds=[options.nth(i).bounding_box() for i in range(options.count())],
                                 painted_before_and_after_screenshot=True)
                    page.keyboard.press("Escape")
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    return labels


                page.goto(base + "/?workspace=review")
                page.locator("[data-hz-render]").wait_for(state="attached", timeout=60000)
                settle(page)
                check.radio("周月复盘")
                if legacy_menu_only:
                    history = page.get_by_role("combobox", name="历史复盘", exact=True)
                    if not history.is_visible():
                        page.get_by_text("已保存的复盘", exact=True).click()
                    prepare(history, True)
                    check.click("打开这份复盘")
                    repo = Repository(path)
                    frozen = load_report(repo, legacy["report_id"])
                    streams = frozen["reading_view"]["charts"][0]["comparison"]["streams"]
                    assert all("display_label" not in stream for stream in streams)
                    selector = page.get_by_role("combobox", name="查看本期趋势", exact=True)
                    options = capture_menu("legacy-menu-painted", selector)
                    assert any(option.startswith("协议：固定晨间") for option in options)
                    assert any(option.startswith("协议未记录") for option in options)
                    before_chart = page.locator("[data-hz-report-chart]").get_attribute("data-hz-report-chart")
                    target = next(stream for stream in streams if stream["fact_id"] != before_chart)
                    prefix = "协议：固定晨间" if target["protocol"][2] else "协议未记录"
                    label = next(option for option in options if option.startswith(prefix))
                    page.set_viewport_size({"width": 390, "height": 844})
                    selector.evaluate(ready)
                    selector.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
                    selector.evaluate(ready)
                    selector.click()
                    page.wait_for_function(PAINTED, arg=selector.element_handle(), timeout=3000)
                    page.get_by_role("option", name=label, exact=True).click()
                    page.wait_for_function("id=>document.querySelector('[data-hz-report-chart]')?.dataset.hzReportChart===id",
                                           arg=target["fact_id"])
                    page.wait_for_function("v=>{const p=document.querySelector('.js-plotly-plot');const t=p?.data?.find(x=>x.name==='本期');return t?.y?.length&&t.y.every(x=>x===v)}",
                                           arg=target["current"]["value"])
                    settle(page)
                    page.screenshot(path=str(output / "legacy-selected-other-390.png"))
                    check.record("legacy-select-other-real-group", before_chart_id=before_chart,
                                 selected_fact_id=target["fact_id"], selected_protocol=target["protocol"],
                                 selected_value=target["current"]["value"], opening_attempts=1)
                    with page.expect_download() as historical:
                        page.get_by_role("button", name="下载这份复盘", exact=True).click()
                    historical.value.save_as(output / "legacy-history-report.md")
                    assert (output / "legacy-history-report.md").read_bytes() == (output / "legacy-report.md").read_bytes()
                    assert load_report(repo, legacy["report_id"]) == frozen
                    payload, markdown = repo.one("SELECT payload_json,markdown FROM joint_period_report WHERE report_id=?", (legacy["report_id"],))
                    assert hashlib.sha256(payload.encode()).hexdigest() == legacy["payload_sha256"]
                    assert hashlib.sha256(markdown.encode()).hexdigest() == legacy["markdown_sha256"]
                    objects = {row[0]: hashlib.sha256(row[1].encode()).hexdigest() for row in repo.rows("SELECT object_id,payload_json FROM report_content_object")}
                    assert {identity: objects[identity] for identity in legacy["objects"]} == legacy["objects"]
                    check.record("legacy-menu-bytes-preserved", report_id=legacy["report_id"], frozen_object_count=len(legacy["objects"]))
                    repo.close()
                    browser.close()
                    result["completed"] = True
                    return
                check.click("生成当前周期复盘")
                page.get_by_role("button", name="下载身体与力量联合报告", exact=True).wait_for(timeout=120000)
                with page.expect_download() as downloaded:
                    page.get_by_role("button", name="下载身体与力量联合报告", exact=True).click()
                downloaded.value.save_as(output / "report.md")
                repo = Repository(path)
                report_id = repo.one("SELECT report_id FROM joint_period_report ORDER BY rowid DESC LIMIT 1")[0]
                report = load_report(repo, report_id)
                body = (output / "report.md").read_text()
                assert report["markdown"] == body and report["version"] == "joint-period-report-3.0.2"
                chart = next(c for c in report["reading_view"]["charts"] if c["metric_id"] == "STATE-RHR")
                streams = chart["comparison"]["streams"]
                assert len(streams) == len({s["display_label"] for s in streams}) == 2
                assert {s["current"]["value"] for s in streams} == {61.0, 62.5}
                assert all(s["display_label"] in body for s in streams)
                assert "协议：固定晨间" in body and "协议未记录" in body
                result["frozen_streams"] = [{k: s[k] for k in ("protocol", "stream_id", "fact_id", "display_label")}
                                            | {"current_value": s["current"]["value"]} for s in streams]
                capture("report-page-top")
                first = page.get_by_text(report["reading_view"]["findings"][0], exact=False).first
                capture("first-complete-finding", first)
                selector = page.get_by_role("combobox", name="查看本期趋势", exact=True)
                navigation_options = capture_menu("trend-menu", selector)
                assert any(option.startswith("协议：固定晨间") for option in navigation_options)
                assert any(option.startswith("协议未记录") for option in navigation_options)
                for stream in streams:
                    label = next(option for option in navigation_options if stream["display_label"] in option)
                    before = check.identity()
                    before_chart = page.locator("[data-hz-report-chart]").get_attribute("data-hz-report-chart")
                    if selector.input_value() != label:
                        selector.evaluate(ready)
                        selector.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
                        selector.evaluate(ready)
                        selector.click()
                        selector.press("Control+a")
                        selector.press_sequentially(label)
                        page.get_by_role("option", name=label, exact=True).click()
                        page.wait_for_function("id=>document.querySelector('[data-hz-report-chart]')?.dataset.hzReportChart===id",
                                               arg=stream["fact_id"])
                        settle(page)
                    assert selector.input_value() == label
                    expected = stream["current"]["value"]
                    page.wait_for_function("v=>{const p=document.querySelector('.js-plotly-plot');const t=p?.data?.find(x=>x.name==='本期');return t?.y?.length&&t.y.every(x=>x===v)}", arg=expected)
                    plot = page.locator(".js-plotly-plot").first.evaluate("e=>e.data.map(t=>({name:t.name,x:t.x,y:t.y}))")
                    result.setdefault("selections", []).append({"label": label, "protocol": stream["protocol"],
                        "before_render_id": before, "after_render_id": check.identity(), "plot": plot,
                        "before_chart_id": before_chart,
                        "after_chart_id": page.locator("[data-hz-report-chart]").get_attribute("data-hz-report-chart"),
                        "render_scope": "completed_report_fragment"})
                    capture("selected-" + ("known" if stream["protocol"][2] else "unknown"), selector)
                history = page.get_by_role("combobox", name="历史复盘", exact=True)
                if not history.is_visible():
                    page.get_by_text("已保存的复盘", exact=True).click()
                prepare(history, True)
                if report_id[:8] not in history.input_value():
                    before = check.identity()
                    history.click()
                    page.get_by_role("option").filter(has_text=report_id[:8]).click()
                    check.fresh(before)
                check.click("打开这份复盘")
                with page.expect_download() as historical:
                    page.get_by_role("button", name="下载这份复盘", exact=True).click()
                historical.value.save_as(output / "history-report.md")
                assert (output / "history-report.md").read_bytes() == (output / "report.md").read_bytes()
                assert load_report(repo, report_id) == report
                check.record("history-download-unchanged", report_id=report_id, markdown_bytes=len(body.encode()))
                check.click("返回当前周期复盘")
                history = page.get_by_role("combobox", name="历史复盘", exact=True)
                if not history.is_visible():
                    page.get_by_text("已保存的复盘", exact=True).click()
                prepare(history, True)
                before = check.identity()
                history.click()
                old_option = page.get_by_role("option").filter(has_text=legacy["report_id"][:8])
                old_option.click()
                check.fresh(before)
                check.click("打开这份复盘")
                with page.expect_download() as old_download:
                    page.get_by_role("button", name="下载这份复盘", exact=True).click()
                old_download.value.save_as(output / "legacy-history-report.md")
                assert (output / "legacy-history-report.md").read_bytes() == (output / "legacy-report.md").read_bytes()
                assert "历史正文保持生成时的原文" in check.text()
                old_frozen = load_report(repo, legacy["report_id"])
                old_streams = old_frozen["reading_view"]["charts"][0]["comparison"]["streams"]
                assert all("display_label" not in stream for stream in old_streams)
                selector = page.get_by_role("combobox", name="查看本期趋势", exact=True)
                selector.evaluate(ready)
                selector.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
                selector.evaluate(ready)
                selector.click()
                old_options = page.get_by_role("option").all_text_contents()
                assert len(old_options) == len(set(old_options)) == 2
                page.keyboard.press("Escape")
                capture_menu("legacy-trend-menu", selector)
                capture("legacy-navigation", selector)
                payload, markdown = repo.one("SELECT payload_json,markdown FROM joint_period_report WHERE report_id=?", (legacy["report_id"],))
                assert hashlib.sha256(payload.encode()).hexdigest() == legacy["payload_sha256"]
                assert hashlib.sha256(markdown.encode()).hexdigest() == legacy["markdown_sha256"]
                objects = {row[0]: hashlib.sha256(row[1].encode()).hexdigest() for row in repo.rows("SELECT object_id,payload_json FROM report_content_object")}
                assert {identity: objects[identity] for identity in legacy["objects"]} == legacy["objects"]
                check.record("actual-r5-legacy-bytes-preserved", report_id=legacy["report_id"],
                             navigation_options=old_options, frozen_object_count=len(legacy["objects"]))
                (output / "page.txt").write_text(check.text())
                repo.close()
                browser.close()
        result["completed"] = True
    except Exception as exc:
        result.update(failure_type=type(exc).__name__, failure=str(exc))
        raise
    finally:
        result["end_source_hashes"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in result["source_hashes"]}
        result["files_changed_during_run"] = [name for name, digest in result["source_hashes"].items() if result["end_source_hashes"][name] != digest]
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path, required=True)
    parser.add_argument("--legacy-source", type=Path, required=True)
    parser.add_argument("--legacy-menu-only", action="store_true")
    args = parser.parse_args()
    run(args.output.resolve(), args.knowledge.resolve(), args.legacy_source.resolve(), legacy_menu_only=args.legacy_menu_only)
