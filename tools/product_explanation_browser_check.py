"""Real Chromium/Streamlit checks of independently delayed and failed explanations.

The temporary wrapper injects failures only into the explanation worker. It runs
real app.py, real synthetic facts, actual fragments/navigation and the real local
knowledge/AI path for unconfigured and unauthorized cases. No health data or
service endpoint from the user's workspace is used.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "tests/training"), str(ROOT / "tools")]
from product_redesign_browser_check import navigate, settle  # noqa: E402
from product_redesign_fixture import create_product_fixture  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402

WRAPPER = '''import json
import os
import runpy
import time
from pathlib import Path
import healthzip.ui.health_explanation as module
from healthzip.ai import client
scenario = Path("scenario.txt").read_text().strip()
if scenario == "not_configured":
    for key in ("HEALTHZIP_AI_API_KEY", "HEALTHZIP_AI_BASE_URL", "HEALTHZIP_AI_MODEL"):
        os.environ.pop(key, None)
else:
    os.environ.update(HEALTHZIP_AI_API_KEY="synthetic-test-key",
        HEALTHZIP_AI_BASE_URL="https://example.invalid/synthetic-explanation",
        HEALTHZIP_AI_MODEL="synthetic-test-model")
def transport(request, **kwargs):
    if Path("scenario.txt").read_text().strip() == "invalid_number":
        cards = json.loads(json.loads(request.data)["messages"][1]["content"])
        pairs = [(card, fact) for card in cards if card.get("allowed_actions")
                 for fact in card.get("facts", [])
                 if isinstance(fact.get("value"), (int, float)) and not isinstance(fact.get("value"), bool)]
        card, fact = next(((card, fact) for card, fact in pairs if fact.get("unit") in {"bpm", "ms"}), pairs[0])
        answer = {"summary": card["summary"], "evidence_ids": [card["id"]],
            "facts": [{**fact, "evidence_id": card["id"]}], "limitations": [],
            "allowed_actions": card["allowed_actions"][:1]}
        # The unmodified control must pass the same production verifier. Only
        # the returned numeric fact changes; prompt, claims and validation stay real.
        client.validate_ai_result(answer, {"evidence": cards})
        expected = answer["facts"][0]["value"]
        answer["facts"][0]["value"] = 999999
        with Path("transport-response-receipts.jsonl").open("a") as stream:
            stream.write(json.dumps({"scenario": "invalid_number", "control_valid": True,
                "metric": fact["metric"], "expected_value": expected, "returned_value": 999999}) + "\\n")
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps({"choices": [{"message": {"content": json.dumps(answer)}}]}).encode()
        return Response()
    with Path("network-attempts.txt").open("a") as stream:
        stream.write("attempt\\n")
    raise AssertionError("No model network request is authorized by this synthetic scenario")
client.urlopen = transport
if not hasattr(module, "_browser_original_reviewed"):
    module._browser_original_reviewed = module._reviewed_explanation

def controlled(*args, **kwargs):
    scenario = Path("scenario.txt").read_text().strip()
    with Path("worker-calls.txt").open("a") as stream:
        stream.write(scenario + "\\n")
    if scenario == "slow":
        time.sleep(8)
        raise TimeoutError("Synthetic controlled explanation timeout")
    if scenario == "failure":
        raise RuntimeError("Synthetic controlled explanation failure")
    result = module._browser_original_reviewed(*args, **kwargs)
    with Path("reason-code-receipts.jsonl").open("a") as stream:
        stream.write(json.dumps({"scenario": scenario, "items": [{"metric_id": item["metric_id"],
            "reason_code": item.get("explanation", {}).get("reason_code"),
            "source": item.get("explanation", {}).get("source"),
            "evidence_status": item.get("evidence_context", {}).get("status")}
            for item in result.get("items", [])]}) + "\\n")
    return result
module._reviewed_explanation = controlled
runpy.run_path({app!r}, run_name="__main__")
'''


def choose_period(page, label):
    old = page.locator("[data-hz-render]").get_attribute("data-hz-render")
    page.get_by_role("radio", name=label, exact=True).locator("xpath=ancestor::label[1]").click()
    page.wait_for_function("old=>document.querySelector('[data-hz-render]')?.dataset.hzRender!==old", arg=old)
    settle(page)


def screenshot(page, path):
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="查阅依据并解释变化", exact=True).scroll_into_view_if_needed()
    page.wait_for_timeout(150)
    page.screenshot(path=str(path))
    page.set_viewport_size({"width": 1440, "height": 1000})
    settle(page)


def factual_snapshot(page):
    """Compare actual visible cards and plotted facts, not just element counts."""
    cards = page.get_by_test_id("stMetric").all_text_contents()
    assert len(cards) == 6, cards
    assert sum("bpm" in card for card in cards) == 3, cards
    assert sum("ms" in card for card in cards) == 3, cards
    plots = page.locator(".js-plotly-plot").evaluate_all("""plots=>plots.map(plot=>(plot.data||[]).map(trace=>({
        name:trace.name,x:trace.x,y:trace.y,customdata:trace.customdata})))""")
    assert len(plots) == 2 and all(plots), plots
    return {"cards": cards, "plot_facts": plots}


def receipts(folder, name):
    path = folder / name
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"data": "synthetic_only", "kind": "real_chromium_streamlit",
              "injection": "worker-only delay/error; invalid-number scenario modifies only mock HTTP response, preserving real verifier",
              "real_mobile_safari_keyboard": "not_verified", "checks": {}, "errors": []}
    with tempfile.TemporaryDirectory(prefix="healthzip-explanation-browser-") as temporary:
        folder = Path(temporary)
        create_product_fixture(folder / ".local/healthzip.sqlite3")
        from healthzip.knowledge import KnowledgeWorkbench
        kb = KnowledgeWorkbench(folder / ".local/knowledge", environment_kind="synthetic_test")
        kb.close()
        wrapper = folder / "wrapper"
        wrapper.mkdir()
        (wrapper / "src").symlink_to(ROOT / "src", target_is_directory=True)
        (wrapper / ".streamlit").mkdir()
        (wrapper / ".streamlit/config.toml").write_bytes((ROOT / ".streamlit/config.toml").read_bytes())
        (wrapper / "app.py").write_text(WRAPPER.replace("{app!r}", repr(str(ROOT / "app.py"))))
        (folder / "scenario.txt").write_text("slow")
        with isolated_app(wrapper, folder) as base, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            report["browser"] = browser.version
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            external = []
            def route_request(route):
                if route.request.url.startswith(base + "/"):
                    route.continue_()
                else:
                    external.append("blocked_external_request")
                    route.abort()
            context.route("http**/*", route_request)
            page = context.new_page()
            page.on("pageerror", lambda error: report["errors"].append(str(error)))
            page.goto(base)
            page.get_by_role("radio", name="总览", exact=True).wait_for()
            settle(page)
            navigate(page, "心率")
            factual = factual_snapshot(page)
            began = time.perf_counter()
            page.get_by_role("button", name="查阅依据并解释变化", exact=True).click()
            pending = page.get_by_text("正在读取依据；你可以继续浏览和记录。", exact=True)
            pending.wait_for(timeout=5000)
            feedback_ms = (time.perf_counter() - began) * 1000
            assert factual_snapshot(page) == factual
            screenshot(page, output / "explanation-pending-mobile.png")
            page.get_by_test_id("stMain").evaluate("e=>e.scrollTo(0,0)")
            began = time.perf_counter()
            navigate(page, "睡眠")
            navigation_ms = (time.perf_counter() - began) * 1000
            assert page.get_by_test_id("stMetric").count() >= 2
            assert navigation_ms < 3000
            navigate(page, "心率")
            page.get_by_text("依据检索超时。记录和图表不受影响，可以重试。", exact=True).wait_for(timeout=15000)
            assert factual_snapshot(page) == factual
            screenshot(page, output / "explanation-timeout-mobile.png")
            report["checks"]["slow_worker"] = {"status": "passed", "injected_delay_seconds": 8,
                "local_feedback_ms": feedback_ms, "navigate_while_pending_ms": navigation_ms,
                "cards_unchanged": True, "actual_timeout_then_retry_visible": True}

            (folder / "scenario.txt").write_text("failure")
            choose_period(page, "本周")
            failure_facts = factual_snapshot(page)
            page.get_by_role("button", name="查阅依据并解释变化", exact=True).click()
            failed = page.get_by_text("本次解释未完成。记录和图表不受影响，可以重试。", exact=True)
            try:
                failed.wait_for(timeout=15000)
            except Exception:
                (output / "failure-debug.txt").write_text(page.get_by_test_id("stMain").inner_text())
                (output / "failure-workers.txt").write_text((folder / "worker-calls.txt").read_text())
                raise
            before = (folder / "worker-calls.txt").read_text().count("failure")
            page.get_by_role("button", name="查阅依据并解释变化", exact=True).click()
            failed.wait_for(timeout=5000)
            page.wait_for_timeout(1000)
            assert (folder / "worker-calls.txt").read_text().count("failure") == before + 1
            assert factual_snapshot(page) == failure_facts
            screenshot(page, output / "explanation-failure-mobile.png")
            report["checks"]["failure_retry"] = {"status": "passed", "worker_retry_count": 1,
                                                    "cards_preserved": True}

            (folder / "scenario.txt").write_text("unauthorized")
            choose_period(page, "本月")
            unauthorized_facts = factual_snapshot(page)
            page.get_by_role("button", name="查阅依据并解释变化", exact=True).click()
            page.get_by_text("当前缺少通过审核且适用的完整依据", exact=False).wait_for(timeout=15000)
            assert not (folder / "network-attempts.txt").exists()
            assert factual_snapshot(page) == unauthorized_facts
            unauthorized = [item for row in receipts(folder, "reason-code-receipts.jsonl")
                            if row["scenario"] == "unauthorized" for item in row["items"]]
            assert unauthorized and all(item["reason_code"] == "network_disabled" for item in unauthorized)
            assert all(item["evidence_status"] == "insufficient_evidence" for item in unauthorized)
            screenshot(page, output / "explanation-no-authorization-mobile.png")
            report["checks"]["unauthorized"] = {"status": "passed", "real_local_knowledge_lookup": True,
                "model_config": "synthetic endpoint configured", "model_http_attempts": 0,
                "insufficient_reviewed_evidence_is_not_success": True}
            report["checks"]["no_applicable_evidence"] = {"status": "passed",
                "real_empty_reviewed_corpus": True, "evidence_status": "insufficient_evidence",
                "actual_cards_and_plot_facts_unchanged": True}

            (folder / "scenario.txt").write_text("not_configured")
            navigate(page, "设置")
            page.get_by_text("尚未配置模型服务", exact=False).wait_for()
            page.get_by_role("checkbox", name="允许将解释所需的最小结构化摘要发送到已配置模型服务").locator("xpath=ancestor::label[1]").click()
            settle(page)
            navigate(page, "心率")
            choose_period(page, "近30天")
            unconfigured_facts = factual_snapshot(page)
            page.get_by_role("button", name="查阅依据并解释变化", exact=True).click()
            page.get_by_text("当前缺少通过审核且适用的完整依据", exact=False).wait_for(timeout=15000)
            assert not (folder / "network-attempts.txt").exists()
            assert factual_snapshot(page) == unconfigured_facts
            navigate(page, "设置")
            assert page.get_by_role("checkbox", name="允许将解释所需的最小结构化摘要发送到已配置模型服务").is_checked()
            report["checks"]["unconfigured"] = {"status": "passed", "real_local_knowledge_lookup": True,
                "model_http_attempts": 0, "consent_persists_across_navigation": True}

            (folder / "scenario.txt").write_text("invalid_number")
            navigate(page, "心率")
            choose_period(page, "本周")
            invalid_facts = factual_snapshot(page)
            page.get_by_role("button", name="查阅依据并解释变化", exact=True).click()
            page.get_by_text("模型返回的事实或引用未通过核验，已保留本地观察；本次模型解释暂不可用。", exact=True).first.wait_for(timeout=15000)
            settle(page)
            assert factual_snapshot(page) == invalid_facts
            assert "999999" not in page.get_by_test_id("stMain").inner_text()
            invalid_results = [item for row in receipts(folder, "reason-code-receipts.jsonl")
                               if row["scenario"] == "invalid_number" for item in row["items"]]
            injected = receipts(folder, "transport-response-receipts.jsonl")
            assert injected and all(item["control_valid"] for item in injected)
            assert invalid_results and all(item["reason_code"] == "validation_failed" and
                                            item["source"] == "local_fallback" for item in invalid_results)
            assert not (folder / "network-attempts.txt").exists()
            screenshot(page, output / "explanation-invalid-number-mobile.png")
            report["checks"]["invalid_number"] = {"status": "passed",
                "real_model_validator": True, "injected_transport_responses": injected,
                "results": invalid_results, "invalid_number_not_rendered": True,
                "actual_cards_and_plot_facts_unchanged": True, "external_model_http_requests": 0}
            assert not report["errors"] and not external
            report["external_browser_requests"] = 0
            report["status"] = "passed"
            context.close()
            browser.close()
    (output / "explanation-browser-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
