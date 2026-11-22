"""Real local app acceptance of the master redesign using synthetic records."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tests/training"), str(ROOT / "tools")]
from health_change_browser import WRAPPER  # noqa: E402
from master_science_fixture import CUTOFF, create_master_science_fixture  # noqa: E402
from product_redesign_browser_check import geometry, settle  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402


def run(output, knowledge):
    output.mkdir(parents=True, exist_ok=True)
    result = {"data": "synthetic_only", "checks": {}, "errors": [], "external_model_calls": 0,
              "device": "headless Chromium desktop/mobile viewport; physical phone and Safari untested"}
    with tempfile.TemporaryDirectory(prefix="hz-master-ui-") as tmp:
        folder = Path(tmp)
        db = folder / ".local/healthzip.sqlite3"
        result["fixture"] = create_master_science_fixture(db)
        if knowledge:
            dest = folder / ".local/knowledge"
            dest.mkdir()
            for name in ("sources.sqlite3", "theories.sqlite3"):
                with sqlite3.connect((knowledge / name).as_uri()+"?mode=ro", uri=True) as source, sqlite3.connect(dest / name) as target:
                    source.backup(target)
        wrapper = folder / "wrapper"
        wrapper.mkdir()
        (wrapper / "src").symlink_to(ROOT / "src", target_is_directory=True)
        (wrapper / ".streamlit").symlink_to(ROOT / ".streamlit", target_is_directory=True)
        (wrapper / "app.py").write_text(WRAPPER.format(cutoff=CUTOFF, app=str(ROOT / "app.py")))
        with isolated_app(wrapper, folder) as base, sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            result["browser"] = browser.version
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base+"/") else route.abort())
            page.on("pageerror", lambda exc: result["errors"].append(str(exc)))

            def text():
                assert page.get_by_test_id("stException").count() == 0, page.get_by_test_id("stException").all_text_contents()
                return page.get_by_test_id("stMain").inner_text()

            def radio(name):
                page.get_by_role("radio", name=name, exact=True).locator("xpath=ancestor::label[1]").click()
                settle(page)

            def select(label, option):
                page.get_by_role("combobox", name=label, exact=True).click()
                page.get_by_role("option", name=option, exact=True).click()
                settle(page)

            def record(name, **details):
                result["checks"][name] = {"status": "passed", **details}
                (output / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
                print("PASS", name, flush=True)

            def capture(name):
                dimensions = {}
                for width in (320, 375, 390, 430, 768, 1440):
                    page.set_viewport_size({"width": width, "height": 1000 if width >= 768 else 844})
                    page.wait_for_timeout(120)
                    page.get_by_test_id("stMain").evaluate("el => el.scrollTo(0, 0)")
                    dim = geometry(page)
                    assert dim["document"] <= dim["viewport"] and dim["main"] <= dim["main_client"], dim
                    dimensions[str(width)] = dim
                    if width in (390, 1440):
                        page.screenshot(path=str(output / (name+f"-{width}.png")))
                record(name+"_six_widths", geometry=dimensions)

            page.goto(base+"/?workspace=heart")
            page.locator("[data-hz-render]").wait_for(state="attached", timeout=60000)
            settle(page)
            assert page.get_by_role("radio", name="身体", exact=True).is_checked()
            assert page.get_by_role("radio", name="力量", exact=True).count() == 0
            assert "64.0 bpm" in text() and "高 5.0 bpm" in text()
            capture("heart")
            radio("长期")
            page.get_by_role("button", name="切换主题或指标", exact=True).click()
            select("查看指标", "日静息心率")
            page.keyboard.press("Escape")
            page.get_by_text("计算趋势", exact=False).first.wait_for(timeout=45000)
            contents = text()
            assert "-0.026" in contents and "斜率区间" in contents, contents
            assert page.get_by_test_id("stPlotlyChart").count() >= 1
            plots = page.locator(".js-plotly-plot").evaluate_all("els => els.map(el => el.data?.map(t => ({name:t.name,x:t.x,y:t.y})))")
            assert any(trace.get("name") == "计算条件均值" for chart in plots if chart for trace in chart)
            record("D23_formal_long_term_page", rendered_text=contents, plots=plots)
            capture("long-term")
            page.get_by_text("长期范围设置", exact=True).click()
            page.get_by_role("spinbutton", name="长期范围（天）", exact=True).fill("1")
            page.get_by_role("spinbutton", name="长期范围（天）", exact=True).press("Enter")
            page.get_by_text("本范围保留观察点和描述性变化。", exact=False).first.wait_for(timeout=45000)
            assert page.get_by_test_id("stPlotlyChart").count() >= 1
            record("D23_sparse_local_fallback", rendered_text=text())
            capture("sparse-long-term")
            page.get_by_role("spinbutton", name="长期范围（天）", exact=True).fill("365")
            page.get_by_role("spinbutton", name="长期范围（天）", exact=True).press("Enter")
            page.get_by_text("计算趋势", exact=False).first.wait_for(timeout=45000)
            page.get_by_text("长期范围设置", exact=True).click()
            radio("复盘")
            radio("问题分析")
            select("想了解的问题", "睡眠时长与随后同条件 SDNN 有怎样的关系？")
            page.get_by_text("同条件记录的估计关联", exact=False).first.wait_for(timeout=60000)
            contents = text()
            assert "+2.92" in contents and "区间" in contents, contents
            assert "实际日期" in contents and "下一步" in contents
            record("D23_formal_association_page", rendered_text=contents)
            capture("joint-association")
            page.get_by_text("选择行动并安排复评", exact=True).click()
            page.get_by_role("button", name="保存这项行动", exact=True).click()
            settle(page)
            page.get_by_text("已保存行动", exact=False).wait_for(timeout=30000)
            assert "已保存行动" in text()
            with sqlite3.connect(db) as conn:
                baseline = conn.execute("SELECT baseline_json FROM review_action").fetchone()[0]
                assert json.loads(baseline)["id"] == "W6"
            radio("行动复评")
            select("实际执行情况", "部分执行")
            page.get_by_role("textbox", name="实际感受或未执行原因（可选）").fill("合成行动反馈：已按记录条件执行一部分")
            page.get_by_role("button", name="保存执行与复评", exact=True).click()
            page.get_by_text("执行情况和本次观察已保存", exact=False).wait_for(timeout=30000)
            settle(page)
            with sqlite3.connect(db) as conn:
                row = conn.execute("SELECT status,notes FROM review_action_event").fetchone()
                assert row[0] == "partial" and "合成行动反馈" in row[1]
                assert conn.execute("SELECT baseline_json FROM review_action").fetchone()[0] == baseline
            record("action_choice_execution_and_frozen_baseline")
            capture("action-followup")
            radio("周月复盘")
            started = time.perf_counter()
            page.get_by_role("button", name="生成当前周期复盘", exact=True).click()
            page.get_by_text("可以切页", exact=False).wait_for(timeout=30000)
            record("report_visible_progress", elapsed_seconds=time.perf_counter()-started)
            radio("身体")
            page.get_by_text("下一步", exact=True).wait_for(timeout=45000)
            assert "下一步" in text()
            radio("复盘")
            page.get_by_role("button", name="下载身体与力量联合报告", exact=True).wait_for(timeout=240000)
            settle(page)
            contents = text()
            assert "完整本地复盘已保存" in contents
            with sqlite3.connect(db) as conn:
                saved = conn.execute("SELECT count(*),max(markdown) FROM joint_period_report").fetchone()
                assert saved[0] == 1 and "本阶段训练发生了什么" in saved[1]
            record("complete_report_after_navigation", elapsed_seconds=time.perf_counter()-started,
                   report_count=saved[0], markdown_chars=len(saved[1]))
            capture("completed-report")
            radio("设置")
            radio("基础资料")
            assert "身高" in text() and "体重" in text()
            capture("basic-profile")
            assert not result["errors"], result["errors"]
            browser.close()
    result["status"] = "passed"
    (output / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/master_redesign/pages/acceptance")
    parser.add_argument("--knowledge", type=Path)
    args = parser.parse_args()
    run(args.output, args.knowledge.resolve() if args.knowledge else None)
