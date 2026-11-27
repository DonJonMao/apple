"""R03 real action selection, same-day estimate review, feedback and frozen report."""
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

FIRST = "2026-09-07T12:00:00+00:00"
LATER = "2026-09-14T12:00:00+00:00"


def prepare(db):
    from healthzip.db.repository import Repository
    from tests.integration.test_followup_action_observation_units import estimate
    with closing(Repository(db)) as repo:
        estimate(repo, 1, "2026-09-06T09:00:00Z", 420,
                 support=("2026-08-09T00:00:00Z", "2026-09-06T00:00:00Z"))
        estimate(repo, 2, "2026-09-14T09:00:00Z", 445,
                 support=("2026-08-17T00:00:00Z", "2026-09-14T00:00:00Z"),
                 published="2026-09-14T09:00:00Z")
    return {"records": 2, "source": "Synthetic handset", "values_m": [420, 445],
            "support_relation": "crosses_start", "followup_record_is_same_day": True}


def run(output, app_root, before=False):
    from healthzip.analytics.body_metrics import analyze_questions
    from healthzip.analytics.body_questions import QUESTIONS
    from healthzip.db.repository import Repository
    from healthzip.workflows.actions import followup
    from healthzip.workflows.period_report import load_report
    from healthzip.workflows.report_objects import read_question

    output.mkdir(parents=True, exist_ok=False)
    result = {"data": "synthetic_only", "external_model_calls": 0, "status": "running",
              "checks": {}, "errors": [], "before_reproduction": before,
              "unverified": ["physical iPhone", "Safari", "mobile soft keyboard", "human validity", "independent expert review"],
              "source_sha256": {str(p.relative_to(app_root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (app_root / "src").rglob("*.py")}}
    with tempfile.TemporaryDirectory(prefix="hz-followup-actions-") as temporary:
        folder = Path(temporary)
        db = folder / ".local/healthzip.sqlite3"
        result["fixture"] = prepare(db)
        clock = folder / "request-clock.txt"
        clock.write_text(FIRST)
        wrapper = folder / "wrapper"
        wrapper.mkdir()
        (wrapper / "src").symlink_to(app_root / "src", target_is_directory=True)
        (wrapper / ".streamlit").symlink_to(app_root / ".streamlit", target_is_directory=True)
        (wrapper / "app.py").write_text('''import importlib, os, runpy
from datetime import datetime
from pathlib import Path
import streamlit as st
class FixedRequestClock(datetime):
    @classmethod
    def now(cls, tz=None):
        value = datetime.fromisoformat(Path(CLOCK).read_text())
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)
for name in ("healthzip.analytics.workspaces", "healthzip.analytics.workspace_summary", "healthzip.analytics.v13",
             "healthzip.analytics.core", "healthzip.ui.body_workspace", "healthzip.ui.question_page",
             "healthzip.ui.action_page", "healthzip.workflows.actions"):
    importlib.import_module(name).datetime = FixedRequestClock
for key in ("HEALTHZIP_AI_API_KEY", "HEALTHZIP_AI_BASE_URL"):
    os.environ.pop(key, None)
st.session_state.setdefault("body_period", "自定义")
st.session_state.setdefault("analysis_window_days", 7)
st.session_state.setdefault("analysis_timezone", "UTC")
runpy.run_path(APP, run_name="__main__")
'''.replace("CLOCK", repr(str(clock))).replace("APP", repr(str(app_root / "app.py"))))
        with isolated_app(wrapper, folder) as base, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            result["browser"] = browser.version
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
            page.on("pageerror", lambda error: result["errors"].append(str(error)))

            def text():
                return page.get_by_test_id("stMain").inner_text()

            def radio(name):
                page.get_by_role("radio", name=name, exact=True).locator("xpath=ancestor::label[1]").click()
                settle(page)

            def select(label, choice):
                control = page.get_by_role("combobox", name=label, exact=True)
                control.scroll_into_view_if_needed()
                control.click()
                control.fill(choice)
                page.get_by_role("option", name=choice, exact=True).click()
                settle(page)

            def save(name, **details):
                assert not page.get_by_test_id("stException").count()
                result["checks"][name] = {"rendered_text": text(), **details}
                (output / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
                print("PASS", name, flush=True)

            def capture(name, locator):
                dimensions = {}
                for width in (320, 375, 390, 430, 768, 1440):
                    page.set_viewport_size({"width": width, "height": 844 if width < 768 else 1000})
                    locator.evaluate("el => el.scrollIntoView({block: 'center', inline: 'nearest'})")
                    page.wait_for_timeout(150)
                    dimensions[str(width)] = geometry(page)
                    assert dimensions[str(width)]["document"] <= width
                    assert dimensions[str(width)]["main"] <= dimensions[str(width)]["main_client"]
                    page.screenshot(path=str(output / f"{name}-{width}.png"))
                page.set_viewport_size({"width": 1440, "height": 1000})
                settle(page)
                return dimensions

            try:
                page.goto(base + "/?workspace=review")
                page.locator("[data-hz-render]").wait_for(state="attached", timeout=60000)
                settle(page)
                radio("问题分析")
                select("想了解的问题", QUESTIONS["W7"][0])
                page.get_by_text("选择行动并安排复评", exact=True).click()
                settle(page)
                label = ("六分钟步行距离：完整日代表值中位数" if before else
                         "六分钟步行距离：来源估计点与支持窗口（不作为独立每日测量）")
                select("主要看什么", label)
                save("definition_before_save", geometry=capture("definition", page.get_by_text("主要观察：" + label, exact=True)))
                page.get_by_role("button", name="保存这项行动", exact=True).click()
                page.get_by_text("已保存行动和主要观察定义", exact=False).wait_for()
                with closing(Repository(db)) as repo:
                    action = dict(repo.one("SELECT * FROM review_action"))
                result["action_id"] = action["action_id"]
                definition_bytes = action["definition_json"]
                clock.write_text(LATER)
                page.reload()
                page.locator("[data-hz-render]").wait_for(state="attached", timeout=60000)
                settle(page)
                radio("行动复评")
                page.get_by_role("button", name="查看后续同口径观察", exact=True).click()
                marker = page.get_by_text("现在观察到的主要结果", exact=True)
                marker.wait_for(timeout=60000)
                if before:
                    page.get_by_text("期间中位数：420.0 m → 未知", exact=True).wait_for()
                    assert "跨越开始时点" not in text()
                    save("reproduced_same_day_estimate_lost_support", geometry=capture("estimate-before", page.get_by_text("期间中位数：420.0 m → 未知", exact=True)))
                    result["status"] = "reproduced"
                    return
                page.get_by_text("窗口内末次来源估计：420.0 m → 445.0 m", exact=True).wait_for()
                assert "跨越开始时点" in text()
                assert "不能据此判断这次行动的效果" in text()
                assert "1 条明确提供发布时间" in text()
                save("same_day_estimate_and_support_visible", geometry=capture("estimate-review", page.get_by_text("窗口内末次来源估计：420.0 m → 445.0 m", exact=True)))
                page.get_by_text("这一观察的实际记录", exact=True).first.click()
                page.get_by_test_id("stDataFrame").first.wait_for()
                save("support_records_expand", geometry=capture("estimate-records", page.get_by_test_id("stDataFrame").last))
                select("实际执行情况", "部分执行")
                page.get_by_role("textbox", name="实际开始时间（可选）", exact=True).fill("2026-09-10 09:00")
                page.get_by_role("textbox", name="实际结束时间（可选）", exact=True).fill("2026-09-13 18:00")
                page.get_by_role("textbox", name="实际感受或未执行原因（可选）", exact=True).fill("合成浏览器：延迟开始，部分执行后停止")
                page.get_by_role("button", name="保存执行与复评", exact=True).click()
                page.get_by_text("执行情况和本次观察已追加保存", exact=False).wait_for()
                with closing(Repository(db)) as repo:
                    expected = followup(repo, action["action_id"], cutoff_time=LATER)["review"]
                    assert repo.one("SELECT definition_json FROM review_action")[0] == definition_bytes
                    assert expected["execution_status"] == "partial"
                radio("问题分析")
                select("想了解的问题", QUESTIONS["W4"][0])
                page.get_by_text("不能据此判断这次行动的效果", exact=False).first.wait_for(timeout=60000)
                assert "445.0 m" in text()
                save("W4_same_action_result", review=expected)
                radio("周月复盘")
                page.get_by_role("button", name="生成当前周期复盘", exact=True).click()
                page.get_by_text("完整本地复盘已保存", exact=False).wait_for(timeout=120000)
                settle(page)
                with closing(Repository(db)) as repo:
                    report_id = repo.one("SELECT report_id FROM joint_period_report ORDER BY rowid DESC LIMIT 1")[0]
                    report = load_report(repo, report_id)
                    w4 = read_question(repo, next(q for q in report["questions"] if q["id"] == "W4"))
                    current = report["reading_view"]["window"]
                    direct = analyze_questions(repo, window_start=current["start"], window_end=current["end"],
                        cutoff_time=current["cutoff_time"], timezone_name="UTC", question_ids=["W4"], period="week")[0]
                    assert w4["action_reviews"] == direct["action_reviews"]
                    assert w4["action_reviews"][0]["primary_observations"][0]["value"] == 445
                    assert w4["action_reviews"][0]["summary"] in report["markdown"]
                    assert load_report(repo, report_id)["markdown"] == report["markdown"]
                save("frozen_report_same_result_and_reopen", report_id=report_id, review=w4["action_reviews"][0])
                assert not result["errors"]
                result["status"] = "passed"
            except Exception as exc:
                result["status"] = "failed"
                result["failure"] = repr(exc)
                result["last_page_text"] = text()
                page.screenshot(path=str(output / "failure.png"))
                raise
            finally:
                result["source_sha256_after"] = {str(p.relative_to(app_root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                                  for p in (app_root / "src").rglob("*.py")}
                result["source_files_changed_during_run"] = [key for key, value in result["source_sha256"].items()
                    if result["source_sha256_after"].get(key) != value]
                (output / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
                if (folder / "synthetic-streamlit.log").exists():
                    (output / "streamlit.txt").write_bytes((folder / "synthetic-streamlit.log").read_bytes())
                browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--app-root", type=Path, default=ROOT)
    parser.add_argument("--before", action="store_true")
    args = parser.parse_args()
    run(args.output, args.app_root, args.before)
