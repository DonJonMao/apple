"""Real app checks using synthetic health data and an explicit public library."""
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
from followup_history_interaction import READY, prepare  # noqa: E402
from health_change_browser import WRAPPER  # noqa: E402
from master_science_fixture import CUTOFF, create_master_science_fixture  # noqa: E402
from product_redesign_browser_check import geometry, settle  # noqa: E402
from repair_delivery_browser import Check  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402

from healthzip.analytics.body_questions import QUESTIONS  # noqa: E402
from healthzip.db.repository import Repository  # noqa: E402
from healthzip.workflows.period_report import load_report  # noqa: E402
from healthzip.workflows.report_objects import audit_bundle, reconstruct_report  # noqa: E402


def run(output, knowledge, *, report_only=False, content_gaps=False, empty_question_only=False):
    output.mkdir(parents=True, exist_ok=True)
    product_files = [ROOT / 'app.py', ROOT / '.streamlit/config.toml', *(ROOT / 'src/healthzip').rglob('*.py')]
    result = {"data": "synthetic_only", "knowledge": "explicit_public_library", "knowledge_path": str(knowledge),
              "content_gaps": content_gaps, "empty_question_only": empty_question_only, "checks": {}, "errors": [],
              "external_model_calls": 0, "physical_iPhone_Safari": "not_verified",
              "source_hashes": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in product_files}}
    (output / 'browser.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        result["browser"] = browser.version
        scenarios = ("missing",) if empty_question_only else (("data",) if report_only else ("data", "missing"))
        for scenario in scenarios:
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

                    def capture(topic, expected=(), *, focus=None):
                        text = check.text()
                        for value in expected:
                            assert value in text, (scenario, topic, value, text)
                        assert "Traceback" not in text
                        assert "下一步" in text or "记录" in text
                        dimensions = {}
                        for width in (390, 1440):
                            page.set_viewport_size({"width": width, "height": 844 if width == 390 else 1000})
                            if focus:
                                page.get_by_text(focus, exact=False).first.scroll_into_view_if_needed()
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

                    def choose(label, option):
                        selector = page.get_by_role('combobox', name=label, exact=True)
                        current = selector.input_value()
                        if current == option:
                            # A theme change can already select its first field.
                            # Keeping that exact value causes no product rerun.
                            result.setdefault('already_selected', []).append({
                                'scenario': scenario, 'label': label, 'value': current,
                                'render_id': check.identity(), 'selection_attempts': 0})
                            return
                        check.select(label, option)

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
                        selector = page.get_by_role('combobox', name='想了解的问题', exact=True)
                        # The question control has no enclosing details element.
                        # Otherwise use the already verified popup preparation:
                        # settle ancestor animations, scroll before opening, then
                        # wait for stable geometry. No retry or CSS modification.
                        ready = READY.replace("details?.open&&details.style.overflow!=='hidden'",
                                              "(!details||(details.open&&details.style.overflow!=='hidden'))")
                        preparation = [selector.evaluate(ready)]
                        selector.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
                        preparation.append(selector.evaluate(ready))
                        before = check.identity()
                        selector.click()
                        selector.press('Control+a')
                        selector.press_sequentially(QUESTIONS[qid][0])
                        option = page.get_by_role('option', name=QUESTIONS[qid][0], exact=True)
                        option.wait_for(state='visible', timeout=5000)
                        options = page.get_by_role('option').all_text_contents()
                        option.click(timeout=5000)
                        check.fresh(before)
                        assert selector.input_value() == QUESTIONS[qid][0]
                        result.setdefault('question_selections', []).append({'scenario': scenario, 'question': qid,
                            'attempts': 1, 'preparation': preparation, 'painted_options': options,
                            'before_render_id': before, 'after_render_id': check.identity()})

                    if empty_question_only:
                        open_route("review")
                        check.radio("问题分析")
                        select_question("W6")
                        observation = "所选期间尚无相关睡眠或生理记录，不能建立睡眠与 SDNN 对照。"
                        hint = "核对所选范围、记录来源及睡眠和 SDNN 是否已导入，再查看实际记录日期与共同记录日期。"
                        capture("joint-empty-state", (observation, hint, "下一步"), focus=observation)
                        sources("复评睡眠时长或分期变化前，核对设备版本")
                        assert "不能换成 Apple SDNN 每周至少记录几天的规则" in check.text()
                        capture("joint-sources", (observation, hint),
                                focus="复评睡眠时长或分期变化前，核对设备版本")
                        select_question("W5")
                        observation = "所选期间尚无体重、体组成或相关能量记录。"
                        hint = "核对所选范围和记录来源，在“身体 → 体重”查看已有值与实际日期；"
                        capture("weight-empty-state", (observation, hint, "设置 → 导入与同步"), focus=observation)
                        sources("如果体脂或去脂体重来自BIA")
                        capture("weight-sources", (observation, hint, "不是骨骼肌重量"),
                                focus="如果体脂或去脂体重来自BIA")
                    elif report_only:
                        open_route("review")
                    else:
                        open_route("heart")
                        page.get_by_role("button", name="切换主题或指标", exact=True).click()
                        choose("查看指标", "日静息心率")
                        page.keyboard.press("Escape")
                        sources("比较静息心率变化前，先核对同一来源")
                        capture("rhr", ("bpm", "日", "记录") if scenario == "data" else ("当前", "记录"))
                        page.get_by_role("button", name="切换主题或指标", exact=True).click()
                        choose("查看指标", "心率变异性 SDNN")
                        page.keyboard.press("Escape")
                        sources("HRV变化应与同日期的实际训练表现、疲劳和睡眠记录一起核对")
                        protocol = page.get_by_text("核对SDNN时，先确认来源使用的信号、指标和记录时段", exact=False).first
                        protocol.wait_for(timeout=45000)
                        assert "不把未知年龄当成人" in check.text()
                        if content_gaps:
                            assert "原始心搏间期中的缺口与整日没有 HRV 记录是不同问题" in check.text()
                            assert "SDNN与RMSSD使用不同的计算定义" in check.text()
                        capture("sdnn", ("ms", "SDNN") if scenario == "data" else ("SDNN", "记录"))
                        if scenario == "data":
                            targets = [("hrv-response", "HRV变化应与同日期的实际训练表现"),
                                       ("hrv-protocol", "核对SDNN时，先确认来源使用的信号")]
                            if content_gaps:
                                targets.extend([("hrv-missing", "原始心搏间期中的缺口与整日没有 HRV 记录是不同问题"),
                                                ("hrv-definition", "SDNN与RMSSD使用不同的计算定义")])
                            for label, statement in targets:
                                target = page.get_by_text(statement, exact=False).first
                                page.set_viewport_size({"width": 390, "height": 844})
                                target.scroll_into_view_if_needed()
                                settle(page)
                                page.screenshot(path=str(output / (label + "-390.png")))
                            page.set_viewport_size({"width": 1440, "height": 1000})
                        open_route("sleep")
                        page.get_by_role("button", name="切换主题或指标", exact=True).click()
                        choose("查看指标", "睡眠事件、时长与分期")
                        page.keyboard.press("Escape")
                        sources("复评睡眠时长或分期变化前，核对设备版本")
                        capture("sleep", ("小时", "记录") if scenario == "data" else ("记录",))
                        check.nav("复盘")
                        check.radio("问题分析")
                        select_question("W6")
                        sources("复评睡眠时长或分期变化前，核对设备版本")
                        page.get_by_text("HRV变化应与同日期的实际训练表现、疲劳和睡眠记录一起核对", exact=False).first.wait_for(timeout=45000)
                        if content_gaps:
                            assert "不能换成 Apple SDNN 每周至少记录几天的规则" in check.text()
                        capture("joint", ("睡眠与 SDNN", "下一步"))
                        if content_gaps:
                            select_question("W2")
                            sources("情境未知时，先补记测量时正在做什么")
                            capture("training-state", ("原始心搏间期中的缺口与整日没有 HRV 记录是不同问题",
                                                       "HRV变化应与同日期的实际训练表现"),
                                    focus="情境未知时，先补记测量时正在做什么")
                            select_question("W5")
                            sources("如果体脂或去脂体重来自BIA")
                            capture("weight-question", ("不是骨骼肌重量", "电极位置、姿势、近期运动和饮食"),
                                    focus="如果体脂或去脂体重来自BIA")
                        # A new real page request starts the default W1 view. The
                        # joint-page selection above remains a separate click test.
                        open_route("review")
                        check.radio("问题分析")
                        sources("训练组数描述完成的组，不能单独表示相等的训练刺激")
                        if content_gaps:
                            assert "群体重复次数表不能直接成为某个人的确定性负荷换算" in check.text()
                            assert "不能自动证明任意e1RM估计或个人训练任务拥有相同误差" in check.text()
                        capture("strength", ("同动作完成表现", "下一步"),
                                focus="不能自动证明任意e1RM估计或个人训练任务拥有相同误差" if content_gaps else None)
                        if content_gaps:
                            for key, label, statement in (
                                ("oxygen", "血氧饱和度", "平均偏差较小与单次读数一致性不是一回事"),
                                ("respiration", "呼吸率", "仍将呼吸率和腕温列为需要验证的指标"),
                                ("wrist", "睡眠腕温", "仍将呼吸率和腕温列为需要验证的指标"),
                            ):
                                open_route("sleep")
                                page.get_by_role("button", name="切换主题或指标", exact=True).click()
                                choose("身体主题", "夜间生理")
                                choose("查看指标", label)
                                page.keyboard.press("Escape")
                                sources(statement)
                                capture(key, (statement, "记录"), focus=statement)
                            for key, label in (("body-fat", "体脂比例"), ("lean-mass", "瘦体重")):
                                open_route("weight")
                                page.get_by_role("button", name="切换主题或指标", exact=True).click()
                                choose("查看指标", label)
                                page.keyboard.press("Escape")
                                sources("如果体脂或去脂体重来自BIA")
                                capture(key, ("不是骨骼肌重量", "不从本人的秤具结果推算水分变化量"),
                                        focus="去脂体重是包含体水分与骨矿物等成分")
                        open_route("cardio")
                        page.get_by_role("button", name="切换主题或指标", exact=True).click()
                        choose("身体主题", "活动与行动能力")
                        choose("查看指标", "六分钟步行距离")
                        page.keyboard.press("Escape")
                        sources()
                        capture("six-minute", ("500", "支持") if scenario == "data" else ("记录",))
                        if content_gaps:
                            page.get_by_role("button", name="切换主题或指标", exact=True).click()
                            choose("查看指标", "步数")
                            page.keyboard.press("Escape")
                            sources("这些研究没有覆盖久坐或坐着活动手臂的场景")
                            capture("steps", ("初代和Series 1", "个人步数变化的精度证明"),
                                    focus="这些研究没有覆盖久坐或坐着活动手臂的场景")
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
                        required = [("W2", "MASTER-HR-CONTEXT"), ("W3", "MASTER-ACTIVITY-GRADUAL"),
                                    ("W4", "MASTER-PROGRESSION-GOAL")]
                        if content_gaps:
                            required.extend([("W1", "V15-CLAIM-REPETITIONS-POPULATION-VARIATION"),
                                ("W1", "V15-CLAIM-MEASURED-ONE-RM-RELIABILITY-SCOPE"),
                                ("W1", "FOLLOWUP-SETS-NOT-STIMULUS"), ("W1", "MASTER-PROGRESSION-GOAL"),
                                ("W2", "HC-DAVIS-IBI-GAPS"), ("W6", "HC-DAVIS-IBI-GAPS"),
                                ("W6", "FOLLOWUP-SLEEP-EPISODE-COMPARABILITY"),
                                ("W5", "MASTER-BIA-CONDITIONS"), ("W5", "MASTER-FFM-NOT-MUSCLE")])
                        checks = []
                        for qid, cid in required:
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
                        history = page.get_by_role('combobox', name='历史复盘', exact=True)
                        if not history.is_visible():
                            page.get_by_text('已保存的复盘', exact=True).click()
                        preparation = prepare(history, True)
                        assert identity[:8] in history.input_value()
                        before = check.identity()
                        page.get_by_role('button', name='打开这份复盘', exact=True).click()
                        check.fresh(before)
                        page.get_by_role('button', name='返回当前周期复盘', exact=True).wait_for()
                        page.wait_for_function("id=>document.querySelector('[data-hz-report-id]')?.dataset.hzReportId===id",
                                               arg=identity, timeout=30000)
                        with page.expect_download() as historical_download:
                            page.get_by_role('button', name='下载这份复盘', exact=True).click()
                        historical_download.value.save_as(output / 'history-report.md')
                        assert (output / 'history-report.md').read_bytes() == (output / 'report.md').read_bytes()
                        capture('history', ('本期主要变化', '返回当前周期复盘'))
                        check.record('real-browser-history-open-download', report_id=identity,
                                     preparation=preparation, downloaded_bytes_equal=True, opening_attempts=1)
                        before = check.identity()
                        page.get_by_role('button', name='返回当前周期复盘', exact=True).click()
                        check.fresh(before)
                        page.get_by_role('button', name='返回当前周期复盘', exact=True).wait_for(state='hidden')
                        check.record('real-browser-history-return', report_id=identity, return_attempts=1)
                    page.close()
        browser.close()
    result["end_source_hashes"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in result["source_hashes"]}
    result["files_changed_during_run"] = [name for name, value in result["source_hashes"].items() if result["end_source_hashes"][name] != value]
    result['completed'] = True
    (output / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"checks": len(result["checks"]), "errors": result["errors"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path, required=True)
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--content-gaps", action="store_true")
    parser.add_argument("--empty-question-only", action="store_true")
    args = parser.parse_args()
    if args.report_only and args.empty_question_only:
        parser.error("--report-only and --empty-question-only are mutually exclusive")
    try:
        run(args.output.resolve(), args.knowledge.resolve(), report_only=args.report_only, content_gaps=args.content_gaps,
            empty_question_only=args.empty_question_only)
    except Exception as exc:
        receipt = args.output / 'browser.json'
        result = json.loads(receipt.read_text()) if receipt.exists() else {}
        result.update(completed=False, failure_type=type(exc).__name__, failure=str(exc))
        result['end_source_hashes'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                     for name in result.get('source_hashes', {})}
        result['files_changed_during_run'] = [name for name, value in result.get('source_hashes', {}).items()
                                            if result['end_source_hashes'][name] != value]
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'execution-failure.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        raise
