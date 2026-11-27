"""Real synthetic topic eligibility, report reading and frozen download checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tests/training"), str(ROOT / "tools")]
from product_redesign_browser_check import geometry, settle  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402

from healthzip.analytics.body_questions import QUESTIONS  # noqa: E402
from healthzip.db.repository import Repository  # noqa: E402
from healthzip.ui.preferences import save_preferences  # noqa: E402
from healthzip.workflows.period_report import load_report  # noqa: E402
from tests.integration.test_followup_topic_applicability import END, record  # noqa: E402
from tests.integration.test_report_repair_contract import independent_records  # noqa: E402


def sources():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT / "src").rglob("*.py")}


def run(output, cases):
    output.mkdir(parents=True, exist_ok=False)
    result = {"status": "running", "data": "synthetic_only", "external_model_calls": 0,
              "source_before": sources(), "checks": {}, "unverified": ["physical phone", "Safari", "soft keyboard"]}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        result["browser"] = browser.version
        for case in cases:
            with tempfile.TemporaryDirectory(prefix="hz-followup-topics-") as folder:
                folder = Path(folder)
                db = folder / ".local/healthzip.sqlite3"
                with closing(Repository(db)) as repo:
                    if case == "fatigue":
                        record(repo, "fatigue", 7, table="subjective_log")
                    elif case == "steps":
                        record(repo, "steps", 2310)
                    elif case == "event":
                        record(repo, "high_hr_event", None)
                    elif case == "cycle_record":
                        record(repo, "menstrual_flow", None)
                    elif case == "rich":
                        independent_records(repo)
                    save_preferences(db, cycle_enabled=case == "cycle_enabled")
                wrapper = folder / "wrapper"
                wrapper.mkdir()
                (wrapper / "src").symlink_to(ROOT / "src", target_is_directory=True)
                (wrapper / ".streamlit").symlink_to(ROOT / ".streamlit", target_is_directory=True)
                (wrapper / "app.py").write_text('''import importlib, os, runpy
from datetime import datetime
import streamlit as st
class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        value = datetime.fromisoformat(CUTOFF)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)
for name in ("healthzip.analytics.workspaces", "healthzip.analytics.workspace_summary", "healthzip.analytics.v13",
             "healthzip.analytics.core", "healthzip.ui.body_workspace", "healthzip.ui.question_page"):
    importlib.import_module(name).datetime = FixedClock
for key in ("HEALTHZIP_AI_API_KEY", "HEALTHZIP_AI_BASE_URL"):
    os.environ.pop(key, None)
st.session_state.setdefault("body_period", "本周")
st.session_state.setdefault("analysis_timezone", "Asia/Shanghai")
runpy.run_path(APP, run_name="__main__")
'''.replace("CUTOFF", repr(END)).replace("APP", repr(str(ROOT / "app.py"))))
                with isolated_app(wrapper, folder) as base:
                    page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
                    page.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    entry = result["checks"][case] = {"status": "running"}

                    def text():
                        assert not page.get_by_test_id("stException").count(), page.get_by_test_id("stException").all_text_contents()
                        return page.get_by_test_id("stMain").inner_text()

                    def radio(name):
                        control = page.get_by_role("radio", name=name, exact=True)
                        if control.is_checked():
                            settle(page)
                            return
                        old = page.locator("[data-hz-render]").get_attribute("data-hz-render")
                        control.locator("xpath=ancestor::label[1]").click()
                        page.wait_for_function("old=>{const e=document.querySelector('[data-hz-render]');return e&&e.dataset.hzRender!==old}", arg=old)
                        settle(page)

                    def select(qid):
                        control = page.get_by_role("combobox", name="想了解的问题", exact=True)
                        if control.input_value() == QUESTIONS[qid][0]:
                            settle(page)
                            return
                        old = page.locator("[data-hz-question]").get_attribute("data-hz-question")
                        control.click()
                        page.get_by_role("option", name=QUESTIONS[qid][0], exact=True).click()
                        page.wait_for_function("old=>{const e=document.querySelector('[data-hz-question]');return e&&e.dataset.hzQuestion!==old}", arg=old)
                        settle(page)

                    def capture(name):
                        widths = {}
                        for width in (320, 375, 390, 430, 768, 1440):
                            page.set_viewport_size({"width": width, "height": 844 if width < 768 else 1000})
                            page.get_by_test_id("stMain").evaluate("e=>e.scrollTo(0,0)")
                            page.wait_for_timeout(180)
                            widths[str(width)] = geometry(page)
                            assert widths[str(width)]["document"] <= width
                            assert widths[str(width)]["main"] <= widths[str(width)]["main_client"]
                            if "report" in name or "reopened" in name:
                                finding = page.get_by_test_id("stMarkdownContainer").filter(
                                    has=page.get_by_role("heading", name="本期主要变化", exact=True)).locator("li").first
                                box = finding.bounding_box()
                                widths[str(width)]["first_finding"] = {"text": finding.inner_text(), "box": box}
                                if width in (390, 1440):
                                    assert box and box["y"] >= 0 and box["y"] + box["height"] <= page.viewport_size["height"], box
                            page.screenshot(path=str(output / f"{name}-{width}.png"))
                        page.set_viewport_size({"width": 1440, "height": 1000})
                        return widths

                    try:
                        page.goto(base + "/?workspace=review")
                        page.locator("[data-hz-render]").wait_for(state="attached", timeout=60000)
                        settle(page)
                        radio("问题分析")
                        qid = {"fatigue": "W2", "steps": "W7", "event": "E", "cycle_record": "W8",
                               "cycle_enabled": "W8", "cycle_disabled": "W2", "rich": "W4"}[case]
                        if case == "cycle_disabled":
                            page.get_by_role("combobox", name="想了解的问题", exact=True).click()
                            assert not page.get_by_role("option", name=QUESTIONS["W8"][0], exact=True).count()
                            page.keyboard.press("Escape")
                        select(qid)
                        body = text()
                        if case == "fatigue":
                            assert "疲劳 7" in body and "尚无同期训练、睡眠或心率记录" in body
                            select("E")
                            assert "未提供相关设备事件" in text() and "核对原通知" not in text()
                            assert not page.get_by_text("选择行动并安排复评", exact=True).count()
                            select("W2")
                        elif case == "steps":
                            assert "2,310" in body and "缺少" in body and "步速" in body
                        elif case == "event":
                            assert "2024-09-10" in body and "合成来源" in body and "health_sample:1" in body
                        elif case == "cycle_enabled":
                            assert "已开启" in body and "尚无相关周期记录" in body
                        elif case == "cycle_record":
                            assert "本期已记录 1 条，最近一次是 2024-09-10 的经期流量日志" in body
                            assert "不按日历推测相位" in body
                        entry["question_text"] = text()
                        entry["question_geometry"] = capture(case + "-question")
                        radio("周月复盘")
                        page.get_by_role("button", name="生成当前周期复盘", exact=True).click()
                        page.locator("[data-hz-report-id]").wait_for(state="attached", timeout=120000)
                        settle(page)
                        rid = page.locator("[data-hz-report-id]").get_attribute("data-hz-report-id")
                        with closing(Repository(db)) as repo:
                            report = load_report(repo, rid)
                        if case == "fatigue":
                            assert "疲劳 7" in report["markdown"]
                            assert all(QUESTIONS[k][0] not in report["markdown"] for k in ("W7", "W8", "E"))
                            assert "核对原通知" not in text()
                        assert page.get_by_role("heading", name="本期主要变化", exact=True).count() == 1
                        entry["report_text"] = text()
                        entry["report_id"] = rid
                        entry["topic_states"] = {q["id"]: q["topic_status"] for q in report["questions"]}
                        entry["report_geometry"] = capture(case + "-report")
                        with page.expect_download() as download:
                            page.get_by_role("button", name="下载身体与力量联合报告", exact=True).click()
                        content = Path(download.value.path()).read_bytes()
                        assert content == report["markdown"].encode()
                        entry["download_sha256"] = hashlib.sha256(content).hexdigest()
                        if case == "rich":
                            assert all(v in report["markdown"] for v in ("62.3 bpm", "80.0 bpm", "独立合成甲", "独立合成乙"))
                            assert "T00:00:00+08:00" not in report["markdown"]
                            page.get_by_role("button", name="生成当前周期复盘", exact=True).click()
                            page.wait_for_function("old=>{const e=document.querySelector('[data-hz-report-id]');return e&&e.dataset.hzReportId!==old}", arg=rid, timeout=120000)
                            second = page.locator("[data-hz-report-id]").get_attribute("data-hz-report-id")
                            entry["second_explicit_report_id"] = second
                            assert second != rid
                            page.get_by_text("已保存的复盘", exact=True).click()
                            page.get_by_role("button", name="打开这份复盘", exact=True).click()
                            page.get_by_role("button", name="返回当前周期复盘", exact=True).wait_for(timeout=60000)
                            assert not page.get_by_role("button", name="生成当前周期复盘", exact=True).count()
                            assert page.get_by_role("heading", name="本期主要变化", exact=True).count() == 1
                            entry["reopened_geometry"] = capture("rich-reopened")
                        assert not errors
                        entry["status"] = "passed"
                        print("PASS", case, flush=True)
                    except Exception as exc:
                        entry.update(status="failed", failure=repr(exc), last_text=page.get_by_test_id("stMain").inner_text())
                        page.screenshot(path=str(output / (case + "-failure.png")))
                        result["status"] = "failed"
                        raise
                    finally:
                        entry["errors"] = errors
                        result["source_after"] = sources()
                        (output / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
                        page.close()
        browser.close()
    result["status"] = "passed"
    result["source_changes"] = [p for p, digest in result["source_before"].items() if sources().get(p) != digest]
    (output / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", default=["fatigue", "steps", "event", "cycle_disabled", "cycle_enabled", "cycle_record", "rich"])
    args = parser.parse_args()
    run(args.output, args.cases)
