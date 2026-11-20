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

WRAPPER = '''import os
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
def forbidden_network(*args, **kwargs):
    with Path("network-attempts.txt").open("a") as stream:
        stream.write("attempt\\n")
    raise AssertionError("No model network request is authorized by this synthetic scenario")
client.urlopen = forbidden_network
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
    return module._browser_original_reviewed(*args, **kwargs)
module._reviewed_explanation = controlled
runpy.run_path({app!r}, run_name="__main__")
'''


def choose_period(page, label):
    page.get_by_role("radio", name=label, exact=True).locator("xpath=ancestor::label[1]").click()
    settle(page)


def screenshot(page, path):
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="查阅依据并解释变化", exact=True).scroll_into_view_if_needed()
    page.wait_for_timeout(150)
    page.screenshot(path=str(path))
    page.set_viewport_size({"width": 1440, "height": 1000})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"data": "synthetic_only", "kind": "real_chromium_streamlit",
              "injection": "temporary wrapper delays or raises only in the explanation worker",
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
        (wrapper / "app.py").write_text(WRAPPER.format(app=str(ROOT / "app.py")))
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
            factual = page.get_by_test_id("stMetricValue").all_text_contents()
            assert len(factual) == 2 and page.get_by_test_id("stPlotlyChart").count() == 2
            began = time.perf_counter()
            page.get_by_role("button", name="查阅依据并解释变化", exact=True).click()
            pending = page.get_by_text("正在读取依据；你可以继续浏览和记录。", exact=True)
            pending.wait_for(timeout=5000)
            feedback_ms = (time.perf_counter() - began) * 1000
            assert page.get_by_test_id("stMetricValue").all_text_contents() == factual
            assert page.get_by_test_id("stPlotlyChart").count() == 2
            screenshot(page, output / "explanation-pending-mobile.png")
            page.get_by_test_id("stMain").evaluate("e=>e.scrollTo(0,0)")
            began = time.perf_counter()
            navigate(page, "睡眠")
            navigation_ms = (time.perf_counter() - began) * 1000
            assert page.get_by_test_id("stMetric").count() >= 2
            assert navigation_ms < 3000
            navigate(page, "心率")
            page.get_by_text("本次解释未完成。记录和图表不受影响，可以重试。", exact=True).wait_for(timeout=15000)
            screenshot(page, output / "explanation-timeout-mobile.png")
            report["checks"]["slow_worker"] = {"status": "passed", "injected_delay_seconds": 8,
                "local_feedback_ms": feedback_ms, "navigate_while_pending_ms": navigation_ms,
                "cards_unchanged": True, "actual_timeout_then_retry_visible": True}

            (folder / "scenario.txt").write_text("failure")
            choose_period(page, "本周")
            page.get_by_role("button", name="查阅依据并解释变化", exact=True).click()
            failed = page.get_by_text("本次解释未完成。记录和图表不受影响，可以重试。", exact=True)
            failed.wait_for(timeout=5000)
            before = (folder / "worker-calls.txt").read_text().count("failure")
            page.get_by_role("button", name="查阅依据并解释变化", exact=True).click()
            failed.wait_for(timeout=5000)
            page.wait_for_timeout(1000)
            assert (folder / "worker-calls.txt").read_text().count("failure") == before + 1
            assert page.get_by_test_id("stMetric").count() == 2
            screenshot(page, output / "explanation-failure-mobile.png")
            report["checks"]["failure_retry"] = {"status": "passed", "worker_retry_count": 1,
                                                    "cards_preserved": True}

            (folder / "scenario.txt").write_text("unauthorized")
            choose_period(page, "本月")
            page.get_by_role("button", name="查阅依据并解释变化", exact=True).click()
            page.get_by_text("当前缺少通过审核且适用的完整依据", exact=False).wait_for(timeout=15000)
            assert not (folder / "network-attempts.txt").exists()
            screenshot(page, output / "explanation-no-authorization-mobile.png")
            report["checks"]["unauthorized"] = {"status": "passed", "real_local_knowledge_lookup": True,
                "model_config": "synthetic endpoint configured", "model_http_attempts": 0,
                "insufficient_reviewed_evidence_is_not_success": True}

            (folder / "scenario.txt").write_text("not_configured")
            navigate(page, "设置")
            page.get_by_text("尚未配置模型服务", exact=False).wait_for()
            page.get_by_role("checkbox", name="允许将解释所需的最小结构化摘要发送到已配置模型服务").locator("xpath=ancestor::label[1]").click()
            settle(page)
            navigate(page, "心率")
            choose_period(page, "近30天")
            page.get_by_role("button", name="查阅依据并解释变化", exact=True).click()
            page.get_by_text("当前缺少通过审核且适用的完整依据", exact=False).wait_for(timeout=15000)
            assert not (folder / "network-attempts.txt").exists()
            navigate(page, "设置")
            assert page.get_by_role("checkbox", name="允许将解释所需的最小结构化摘要发送到已配置模型服务").is_checked()
            report["checks"]["unconfigured"] = {"status": "passed", "real_local_knowledge_lookup": True,
                "model_http_attempts": 0, "consent_persists_across_navigation": True}
            assert not report["errors"] and not external
            report["external_browser_requests"] = 0
            report["status"] = "passed"
            context.close()
            browser.close()
    (output / "explanation-browser-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
