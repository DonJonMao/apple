"""Real app checks for six core topics, with data and without data; public backup only."""
from __future__ import annotations

import argparse
import hashlib
import json
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
from repair_delivery_browser import Check  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402

from healthzip.analytics.body_questions import QUESTIONS  # noqa: E402
from healthzip.db.repository import Repository  # noqa: E402
from healthzip.workflows.period_report import load_report  # noqa: E402
from healthzip.workflows.report_objects import audit_bundle, reconstruct_report  # noqa: E402


def run(output, knowledge, *, report_only=False):
    output.mkdir(parents=True, exist_ok=True)
    result = {"data": "synthetic_only", "knowledge": "public_backup", "checks": {}, "errors": [],
              "external_model_calls": 0, "physical_iPhone_Safari": "not_verified",
              "source_hashes": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in (ROOT / "src/healthzip").rglob("*.py")}}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        result["browser"] = browser.version
        for scenario in (("data",) if report_only else ("data", "missing")):
            with tempfile.TemporaryDirectory(prefix="hz-followup-knowledge-") as temp:
                folder = Path(temp)
                path = folder / ".local/healthzip.sqlite3"
                path.parent.mkdir()
                if scenario == "data":
                    result["fixture"] = create_master_science_fixture(path)
                else:
                    Repository(path).close()
                (folder / ".local/knowledge").symlink_to(knowledge, target_is_directory=True)
                wrapper = folder / "wrapper"
                wrapper.mkdir()
                (wrapper / "src").symlink_to(ROOT / "src", target_is_directory=True)
                (wrapper / ".streamlit").symlink_to(ROOT / ".streamlit", target_is_directory=True)
                (wrapper / "app.py").write_text(WRAPPER.format(cutoff=CUTOFF, app=str(ROOT / "app.py")))
                with isolated_app(wrapper, folder) as base:
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    page.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
                    page.on("pageerror", lambda exc: result["errors"].append(str(exc)))
                    check = Check(page, output, result)

                    def capture(topic, expected=()):
                        text = check.text()
                        for value in expected:
                            assert value in text, (scenario, topic, value, text)
                        assert "Traceback" not in text
                        assert "下一步" in text or "记录" in text
                        dimensions = {}
                        for width in (390, 1440):
                            page.set_viewport_size({"width": width, "height": 844 if width == 390 else 1000})
                            settle(page)
                            dim = geometry(page)
                            assert dim["document"] <= dim["viewport"] and dim["main"] <= dim["main_client"], dim
                            dimensions[str(width)] = dim
                            page.screenshot(path=str(output / f"{scenario}-{topic}-{width}.png"))
                        page.set_viewport_size({"width": 1440, "height": 1000})
                        key = scenario + "-" + topic
                        (output / (key + ".txt")).write_text(text)
                        check.record(key, rendered_text=text, geometry=dimensions)

                    def open_route(route):
                        page.goto(base + "/?workspace=" + route)
                        page.locator("[data-hz-render]").wait_for(state="attached", timeout=60000)
                        settle(page)

                    def sources(statement=None):
                        summary = page.get_by_text("依据与原文", exact=True).last
                        if not summary.locator("xpath=ancestor::details[1]").evaluate("e=>e.open"):
                            summary.click()
                        page.get_by_role("button", name="查阅本题依据", exact=True).click()
                        settle(page)
                        if statement:
                            page.get_by_text(statement, exact=False).first.wait_for(timeout=45000)
                        assert page.get_by_role("link").filter(has_text="Heart Rate").count() or page.get_by_role("link").count()

                    def select_question(qid):
                        before = check.identity()
                        selector = page.get_by_role("combobox", name="想了解的问题", exact=True)
                        selector.fill(QUESTIONS[qid][0])
                        page.get_by_role("option", name=QUESTIONS[qid][0], exact=True).click()
                        check.fresh(before)

                    if report_only:
                        open_route("review")
                    else:
                        open_route("heart")
                        page.get_by_role("button", name="切换主题或指标", exact=True).click()
                        check.select("查看指标", "日静息心率")
                        page.keyboard.press("Escape")
                        sources("比较静息心率变化前，先核对同一来源")
                        capture("rhr", ("bpm", "日", "记录") if scenario == "data" else ("当前", "记录"))
                        page.get_by_role("button", name="切换主题或指标", exact=True).click()
                        check.select("查看指标", "心率变异性 SDNN")
                        page.keyboard.press("Escape")
                        sources()
                        capture("sdnn", ("ms", "SDNN") if scenario == "data" else ("SDNN", "记录"))
                        open_route("sleep")
                        page.get_by_role("button", name="切换主题或指标", exact=True).click()
                        check.select("查看指标", "睡眠事件、时长与分期")
                        page.keyboard.press("Escape")
                        sources("复评睡眠时长或分期变化前，核对设备版本")
                        capture("sleep", ("小时", "记录") if scenario == "data" else ("记录",))
                        check.nav("复盘")
                        check.radio("问题分析")
                        select_question("W6")
                        sources("复评睡眠时长或分期变化前，核对设备版本")
                        capture("joint", ("睡眠与 SDNN", "下一步"))
                        # A new real page request starts the default W1 view. The
                        # joint-page selection above remains a separate click test.
                        open_route("review")
                        check.radio("问题分析")
                        sources("训练组数描述完成的组，不能单独表示相等的训练刺激")
                        capture("strength", ("同动作完成表现", "下一步"))
                        open_route("cardio")
                        page.get_by_role("button", name="切换主题或指标", exact=True).click()
                        check.select("身体主题", "活动与行动能力")
                        check.select("查看指标", "六分钟步行距离")
                        page.keyboard.press("Escape")
                        sources()
                        capture("six-minute", ("500", "支持") if scenario == "data" else ("记录",))
                    if scenario == "data":
                        check.nav("复盘")
                        check.radio("周月复盘")
                        before = check.identity()
                        started = time.perf_counter()
                        page.get_by_role("button", name="生成当前周期复盘", exact=True).click()
                        check.fresh(before)
                        page.get_by_role("button", name="下载身体与力量联合报告", exact=True).wait_for(timeout=120000)
                        settle(page)
                        elapsed = time.perf_counter() - started
                        with page.expect_download() as download:
                            page.get_by_role("button", name="下载身体与力量联合报告", exact=True).click()
                        download.value.save_as(output / "report.md")
                        body = (output / "report.md").read_text()
                        repo = Repository(path)
                        identity = repo.one("SELECT report_id FROM joint_period_report ORDER BY rowid DESC LIMIT 1")[0]
                        report = load_report(repo, identity, include_details=True)
                        assert report["markdown"] == body
                        required = {"W2": "MASTER-HR-CONTEXT", "W3": "MASTER-ACTIVITY-GRADUAL", "W4": "MASTER-PROGRESSION-GOAL"}
                        checks = []
                        for qid, cid in required.items():
                            q = next(q for q in report["questions"] if q["id"] == qid)
                            item = next(i for i in q["evidence"]["items"] if i["claim_id"] == cid)
                            assert q["rows"] and item["statement"] in body
                            assert all(limit in body for limit in item["limitations"])
                            assert all(c["url"] in body for c in item["citations"])
                            checks.append({"question": qid, "fact_id": q["fact_id"], "claim": item})
                        bundle = audit_bundle(repo, identity)
                        assert reconstruct_report(json.loads(json.dumps(bundle))) == report
                        repo.close()
                        check.record("real-report-actions-freeze-reopen-audit", ui_seconds=elapsed, report_id=identity,
                            markdown_bytes=len(body.encode()), actual_frozen_uses=checks, audit_reconstructed=True)
                        capture("report", ("本期主要变化", "下一步"))
                        action = page.get_by_text("如果希望增加活动，先选择与当前能力和目标相符的活动", exact=False).first
                        action.scroll_into_view_if_needed()
                        for width in (390, 1440):
                            page.set_viewport_size({"width": width, "height": 844 if width == 390 else 1000})
                            action.scroll_into_view_if_needed()
                            settle(page)
                            page.screenshot(path=str(output / f"report-action-{width}.png"))
                    page.close()
        browser.close()
    result["end_source_hashes"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in result["source_hashes"]}
    result["files_changed_during_run"] = [name for name, value in result["source_hashes"].items() if result["end_source_hashes"][name] != value]
    (output / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"checks": len(result["checks"]), "errors": result["errors"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path, required=True)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    run(args.output.resolve(), args.knowledge.resolve(), report_only=args.report_only)
