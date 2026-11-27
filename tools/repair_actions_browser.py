"""Real synthetic action selection, feedback, W4 and frozen-report interactions."""
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
LATER = "2026-09-17T12:00:00+00:00"


def prepare(db):
    from healthzip.db.repository import Repository
    with closing(Repository(db)) as repo:
        for identity, (day, value) in enumerate(((1, 57), (2, 58), (3, 89), (10, 62), (11, 64), (12, 63)), 1):
            at = f"2026-09-{day:02d}T08:00:00Z"
            payload = {"id": identity, "canonical_type": "resting_heart_rate_bpm", "raw_type": "HKQuantityTypeIdentifierRestingHeartRate",
                "normalized_value": value, "normalized_unit": "bpm", "raw_value": str(value), "raw_unit": "count/min",
                "source_name": "合成行动手表", "device": "Synthetic action device", "source_version": "fixture-1",
                "start_utc": at, "end_utc": at, "local_date": at[:10], "record_status": "active",
                "metadata_json": json.dumps({"protocol_id": "synthetic-morning", "posture": "seated"})}
            repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) VALUES('health_sample',?,?,?,'synthetic_browser')",
                (identity, at, json.dumps(payload)))
        repo.conn.commit()
    return {"health_records": 6, "dates": ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-10", "2026-09-11", "2026-09-12"],
            "values_bpm": [57, 58, 89, 62, 64, 63], "expected_period_medians": [58, 63], "expected_difference": 5,
            "result_injection": False, "external_calls": 0}


def run(output):
    from healthzip.analytics.body_metrics import analyze_questions
    from healthzip.analytics.body_questions import QUESTIONS
    from healthzip.db.repository import Repository
    from healthzip.workflows.actions import followup
    from healthzip.workflows.period_report import load_report

    output.mkdir(parents=True, exist_ok=True)
    if (output / "browser.json").exists():
        prior = json.loads((output / "browser.json").read_text())
        if prior.get("status") != "passed":
            (output / f"browser-failed-{len(list(output.glob('browser-failed-*.json'))) + 1}.json").write_text(json.dumps(prior, ensure_ascii=False, indent=2))
    result = {"data": "synthetic_only", "status": "running", "checks": {}, "errors": [],
              "clocks": [FIRST, LATER], "unverified": ["physical iPhone", "Safari", "mobile soft keyboard", "human validity", "independent expert review", "remote private model"]}
    result["source_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [ROOT / "src/healthzip/workflows/actions.py", ROOT / "src/healthzip/ui/action_page.py",
                  ROOT / "src/healthzip/ui/question_page.py", ROOT / "src/healthzip/workflows/period_report.py"]}
    with tempfile.TemporaryDirectory(prefix="hz-repair-actions-browser-") as temporary:
        folder = Path(temporary)
        db = folder / ".local/healthzip.sqlite3"
        result["fixture"] = prepare(db)
        clock = folder / "synthetic-clock.txt"
        clock.write_text(FIRST)
        wrapper = folder / "wrapper"
        wrapper.mkdir()
        (wrapper / "src").symlink_to(ROOT / "src", target_is_directory=True)
        (wrapper / ".streamlit").symlink_to(ROOT / ".streamlit", target_is_directory=True)
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
'''.replace("CLOCK", repr(str(clock))).replace("APP", repr(str(ROOT / "app.py"))))
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
                page.get_by_role("option", name=choice, exact=True).wait_for()
                control.press("ArrowDown")
                control.press("Enter")
                settle(page)

            def save(name, **details):
                assert not page.get_by_test_id("stException").count()
                result["checks"][name] = {"status": "passed", "rendered_text": text(), **details}
                (output / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
                print("PASS", name, flush=True)

            def capture(name, target=None):
                measurements = {}
                for width in (320, 375, 390, 430, 768, 1440):
                    page.set_viewport_size({"width": width, "height": 844 if width < 768 else 1000})
                    if target is None:
                        page.get_by_test_id("stMain").evaluate("el => el.scrollTo(0, 0)")
                    else:
                        target.scroll_into_view_if_needed()
                    page.wait_for_timeout(200)
                    measurements[str(width)] = geometry(page)
                    assert measurements[str(width)]["document"] <= width, measurements[str(width)]
                    assert measurements[str(width)]["main"] <= measurements[str(width)]["main_client"], measurements[str(width)]
                    page.screenshot(path=str(output / f"{name}-{width}.png"))
                page.set_viewport_size({"width": 1440, "height": 1000})
                settle(page)
                return measurements

            try:
                page.goto(base + "/?workspace=review")
                page.locator("[data-hz-render]").wait_for(state="attached", timeout=60000)
                settle(page)
                radio("问题分析")
                select("想了解的问题", QUESTIONS["W4"][0])
                page.get_by_text("选择行动并安排复评", exact=True).click()
                settle(page)
                assert "日静息心率：完整日代表值中位数" in text()
                assert "计划复评早于完整观察窗口结束" in text()
                save("read_definition_before_choice", geometry=capture("before-selection"))
                page.get_by_role("button", name="保存这项行动", exact=True).click()
                page.get_by_text("已保存行动和主要观察定义", exact=False).wait_for()
                with closing(Repository(db)) as repo:
                    action = dict(repo.one("SELECT * FROM review_action"))
                frozen_baseline = action["baseline_json"]
                definition = json.loads(action["definition_json"])
                assert definition["primary"]["metric"] == "resting_heart_rate_bpm"
                assert definition["baseline_primary"][0]["value"] == 58
                save("real_choice_freezes_defined_primary", definition=definition)
                clock.write_text(LATER)
                page.reload()
                page.locator("[data-hz-render]").wait_for(state="attached", timeout=60000)
                settle(page)
                radio("行动复评")
                page.get_by_role("button", name="查看后续同口径观察", exact=True).click()
                page.get_by_text("期间中位数：58", exact=False).wait_for(timeout=60000)
                assert "63" in text() and "+5" in text()
                save("real_followup_values", geometry=capture("action-observation"))
                select("实际执行情况", "部分执行")
                page.get_by_role("textbox", name="实际开始时间（可选）", exact=True).fill("2026-09-09T09:00:00Z")
                page.get_by_role("textbox", name="实际结束时间（可选）", exact=True).fill("2026-09-12T18:00:00Z")
                page.get_by_role("textbox", name="实际感受或未执行原因（可选）", exact=True).fill("合成浏览器：延迟开始，部分执行后停止")
                page.get_by_role("button", name="保存执行与复评", exact=True).click()
                page.get_by_text("执行情况和本次观察已追加保存", exact=False).wait_for()
                with closing(Repository(db)) as repo:
                    feedback = dict(repo.one("SELECT * FROM review_action_event"))
                    assert repo.one("SELECT baseline_json FROM review_action")[0] == frozen_baseline
                    assert feedback["status"] == "partial"
                    execution = json.loads(feedback["execution_json"])
                    assert execution["started_at"] == "2026-09-09T09:00:00+00:00"
                    expected = followup(repo, action["action_id"], cutoff_time=LATER)["review"]
                save("real_execution_input_frozen_baseline", event=feedback, review=expected)
                radio("问题分析")
                select("想了解的问题", QUESTIONS["W4"][0])
                page.get_by_text("实际延迟开始", exact=False).first.wait_for(timeout=60000)
                assert "部分执行" in text() and "58" in text() and "63" in text()
                save("W4_uses_primary_and_actual_execution", geometry=capture("W4-action"))
                radio("周月复盘")
                page.get_by_role("button", name="生成当前周期复盘", exact=True).click()
                page.get_by_text("完整本地复盘已保存", exact=False).wait_for(timeout=60000)
                settle(page)
                with closing(Repository(db)) as repo:
                    report_id = repo.one("SELECT report_id FROM joint_period_report ORDER BY rowid DESC LIMIT 1")[0]
                    report = load_report(repo, report_id)
                    current = report["current"]
                    w4 = analyze_questions(repo, window_start=current["window_start"], window_end=current["window_end"],
                        cutoff_time=current["cutoff_time"], timezone_name="UTC", question_ids=["W4"], period="week")[0]
                    saved = next(q for q in report["questions"] if q["id"] == "W4")
                    assert saved["action_reviews"] == w4["action_reviews"]
                    assert saved["action_reviews"][0]["primary_observations"][0]["difference"] == 5
                    assert saved["action_reviews"][0]["summary"] in report["markdown"]
                # Short readable reports show whole chapters without a selector.
                if page.get_by_role("combobox", name="报告章节", exact=True).count():
                    select("报告章节", "上次行动观察")
                action_heading = page.get_by_role("heading", name="上次行动观察", exact=True)
                action_heading.scroll_into_view_if_needed()
                page.get_by_text("实际延迟开始", exact=False).first.wait_for(timeout=30000)
                assert "58" in text() and "63" in text() and "部分执行" in text()
                save("report_freezes_exact_action_review", report_id=report_id,
                     action_review=saved["action_reviews"][0], geometry=capture("report-action", target=action_heading))
                assert not result["errors"], result["errors"]
                result["status"] = "passed"
            except Exception as exc:
                result["status"] = "failed"
                result["failure"] = repr(exc)
                result["last_page_text"] = text()
                page.screenshot(path=str(output / "failure.png"))
                raise
            finally:
                (output / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
                browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/repair_actions/browser")
    args = parser.parse_args()
    run(args.output.resolve())
