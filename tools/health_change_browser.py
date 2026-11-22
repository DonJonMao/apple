"""Fixed synthetic acceptance through the real app, with a frozen request clock."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "tests/training"), str(ROOT / "tools")]
from health_change_fixture import CUTOFF, create_health_change_fixture  # noqa: E402
from product_redesign_browser_check import geometry, navigate, settle  # noqa: E402
from strength_workbench_browser_check import isolated_app, product_source_hashes  # noqa: E402

WRAPPER = '''import importlib
import os
import runpy
from datetime import datetime
import streamlit as st
class FixedRequestClock(datetime):
    @classmethod
    def now(cls, tz=None):
        value = datetime.fromisoformat({cutoff!r})
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)
for name in ("healthzip.analytics.workspaces", "healthzip.analytics.workspace_summary",
             "healthzip.analytics.v13", "healthzip.analytics.core"):
    importlib.import_module(name).datetime = FixedRequestClock
for key in ("HEALTHZIP_AI_API_KEY", "HEALTHZIP_AI_BASE_URL"):
    os.environ.pop(key, None)
st.session_state.setdefault("body_period", "自定义")
st.session_state.setdefault("analysis_window_days", 7)
runpy.run_path({app!r}, run_name="__main__")
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-root", type=Path, default=ROOT)
    parser.add_argument("--phase", choices=("before", "after"), default="after")
    parser.add_argument("--knowledge", type=Path)
    args = parser.parse_args()
    output, code = args.output.resolve(), args.code_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"data": "synthetic_only", "phase": args.phase, "checks": {}, "errors": [],
              "clock": "fixed analysis request cutoff; real SQLite, calculations, Streamlit and Chromium",
              "external_model": "not_authorized_not_called"}
    with tempfile.TemporaryDirectory(prefix="synthetic-health-change-browser-") as temporary:
        folder = Path(temporary)
        report["fixture"] = create_health_change_fixture(folder / ".local/healthzip.sqlite3")
        if args.knowledge:
            dest = folder / ".local/knowledge"
            dest.mkdir(parents=True)
            for name in ("sources.sqlite3", "theories.sqlite3"):
                with sqlite3.connect((args.knowledge / name).resolve().as_uri() + "?mode=ro", uri=True) as source:
                    with sqlite3.connect(dest / name) as target:
                        source.backup(target)
            report["knowledge"] = "read-only backup of public corpus; health fixture stays separate"
        wrapper = folder / "wrapper"
        wrapper.mkdir()
        (wrapper / "src").symlink_to(code / "src", target_is_directory=True)
        (wrapper / ".streamlit").mkdir()
        (wrapper / ".streamlit/config.toml").write_bytes((code / ".streamlit/config.toml").read_bytes())
        (wrapper / "app.py").write_text(WRAPPER.format(cutoff=CUTOFF, app=str(code / "app.py")))
        with isolated_app(wrapper, folder) as base, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            report["browser"] = browser.version
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
            page.on("pageerror", lambda error: report["errors"].append(str(error)))

            def capture(name, *, region=None, mobile_height=844):
                for width in (1440, 390):
                    page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else mobile_height})
                    page.wait_for_timeout(150)
                    dimensions = geometry(page)
                    assert dimensions["document"] <= dimensions["viewport"], dimensions
                    assert dimensions["main"] <= dimensions["main_client"], dimensions
                    if region is None:
                        page.get_by_test_id("stMain").evaluate("e=>e.scrollTo(0,0)")
                    else:
                        region.evaluate("e=>e.scrollIntoView({block:'start'})")
                    page.wait_for_timeout(150)
                    page.screenshot(path=str(output / f"{name}-{width}.png"), full_page=region is None)
                    report["checks"][name + "_" + str(width)] = dimensions
                page.set_viewport_size({"width": 1440, "height": 1000})

            start = time.perf_counter()
            page.goto(base + "/?workspace=heart")
            page.get_by_test_id("stMetric").first.wait_for(timeout=30000)
            settle(page)
            report["cold_first_page_ms"] = (time.perf_counter() - start) * 1000
            heart = page.get_by_test_id("stMain").inner_text()
            if args.phase == "after":
                for text in ("64.0 bpm", "59.0 bpm", "高 5.0 bpm", "记录 7/7 天", "记录 28/28 天", "2026-10-18", "2026-11-14", "SDNN", "30.0 ms"):
                    assert text in heart, text
                report["checks"]["rhr_exact_reference_and_coverage"] = "passed"
            capture("heart-sdnn")
            if args.phase == "before":
                capture("sdnn", region=page.get_by_text("HRV（SDNN）趋势", exact=True))
            if args.phase == "after":
                capture("sdnn", region=page.get_by_text(re.compile(r"HRV（SDNN）日代表值的中位数")).first)
            if args.phase == "after" and args.knowledge:
                started = time.perf_counter()
                page.get_by_role("button", name="查阅依据并解释变化", exact=True).click()
                page.get_by_text("依据查询结果", exact=True).wait_for(timeout=60000)
                settle(page)
                report["complete_local_explanation_ms"] = (time.perf_counter() - started) * 1000
                text = page.get_by_test_id("stMain").inner_text()
                assert "这类记录怎样理解" in text, text[-6000:]
                report["checks"]["actual_public_source_local_explanation"] = "passed"
                capture("heart-explanation")
                capture("source-explanation", region=page.get_by_text("这类记录怎样理解", exact=True).first)
                print("PASS public source explanation", flush=True)
            navigate(page, "睡眠")
            sleep = page.get_by_test_id("stMain").inner_text()
            if args.phase == "after":
                assert "6.0 小时" in sleep and "8.0 小时" in sleep
                assert "低 2.0 小时" in sleep
                report["checks"]["sleep_parent_child_duration"] = "passed"
            capture("sleep")
            if args.phase == "after":
                page.get_by_role("radio", name="截止前24小时", exact=True).locator("xpath=ancestor::label[1]").click()
                page.get_by_text("截止前24小时已记录睡眠 5.0 小时", exact=False).wait_for(timeout=15000)
                settle(page)
                capture("sleep-24h")
                page.get_by_role("radio", name="已声明主睡眠（冻结）", exact=True).locator("xpath=ancestor::label[1]").click()
                page.get_by_text("尚无此工作区已保存的主睡眠声明", exact=False).wait_for(timeout=15000)
                settle(page)
                page.get_by_role("radio", name="所选时期逐日总量", exact=True).locator("xpath=ancestor::label[1]").click()
                page.get_by_text("6.0 小时", exact=True).first.wait_for(timeout=15000)
                settle(page)
                report["checks"]["sleep_scope_switch_and_unknown_main"] = "passed"
                print("PASS sleep scopes", flush=True)
            navigate(page, "复盘")
            page.get_by_role("button", name="更新分析", exact=True).click()
            page.get_by_role("button", name="生成当前周期复盘", exact=True).wait_for(timeout=60000)
            settle(page)
            if args.phase == "after":
                current_text = page.get_by_test_id("stMain").inner_text()
                assert "2026-11-20" in current_text and "疲劳" in current_text and "下一步" in current_text
                capture("joint-context-next", mobile_height=1100,
                        region=page.get_by_text("同一时间窗内的身体与训练记录", exact=True).first)
                report["checks"]["joint_before_report_recorded_context_and_next_steps"] = "passed"
                report_started = time.perf_counter()
                page.get_by_role("button", name="生成当前周期复盘", exact=True).click()
                page.get_by_role("button", name="下载身体与力量联合报告", exact=True).wait_for(timeout=180000)
                settle(page)
                report["explicit_week_report_ms"] = (time.perf_counter()-report_started)*1000
                text = page.get_by_test_id("stMain").inner_text()
                (output / "joint-rendered.txt").write_text(text)
                capture("joint")
                assert "同一时间窗内的身体与训练记录" in text
                assert "2026-11-20" in text and "训练" in text
                report["checks"]["joint_dates_recorded_training_fatigue"] = "passed"
            capture("joint")
            if args.phase == "after":
                capture("weekly-report")
                report["checks"]["actual_week_report_generation"] = "passed"
            report.update(status="passed", source_sha256=product_source_hashes(code))
            assert not report["errors"], report["errors"]
            browser.close()
    (output / "browser-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "checks": list(report["checks"]), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
