"""Real health-page RAG results after cache expiry, audit writes and revocation.

All health facts and reviewed source claims are synthetic. Only a cache expiry
and the documented synthetic knowledge environment are injected; retrieval,
permission checks, fragments, navigation and rendered results are real.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tests/training"), str(ROOT / "tools")]
from product_redesign_browser_check import navigate, settle  # noqa: E402
from product_redesign_fixture import create_product_fixture  # noqa: E402
from strength_workbench_browser_check import isolated_app, product_source_hashes  # noqa: E402

from healthzip.analytics.workspaces import analyze_workspace  # noqa: E402
from healthzip.db.repository import Repository  # noqa: E402
from healthzip.knowledge import KnowledgeWorkbench, domains  # noqa: E402
from healthzip.ui.health_explanation import knowledge_clock  # noqa: E402
from healthzip.workflows.storage import save_context  # noqa: E402
from tests.knowledge.test_v15_retrieval import add  # noqa: E402

HEART_CLAIM = "合成已审核静息心率依据：测量条件一致时再比较变化。"
WRAPPER = '''import os
import runpy
from pathlib import Path
import streamlit as st
import healthzip.knowledge as knowledge
from healthzip.ai import client
from healthzip.analytics import cache
if not hasattr(knowledge, "_rag_browser_original"):
    knowledge._rag_browser_original = knowledge.KnowledgeWorkbench
knowledge.KnowledgeWorkbench = lambda root: knowledge._rag_browser_original(root, environment_kind="synthetic_test")
for key in ("HEALTHZIP_AI_API_KEY", "HEALTHZIP_AI_BASE_URL", "HEALTHZIP_AI_MODEL"):
    os.environ.pop(key, None)
def forbid_model(*args, **kwargs):
    Path("model-attempts.txt").write_text("unexpected")
    raise AssertionError("No model request belongs to this synthetic local retrieval check")
client.urlopen = forbid_model
st.session_state.setdefault("analysis_contexts", {{str(Path(".local/healthzip.sqlite3").resolve()): Path("context.txt").read_text()}})
expiry = Path("expire-cache-once.txt")
if expiry.exists():
    workspace = expiry.read_text()
    with cache._LOCK:
        for identity, (created, value) in list(cache._RESULTS.items()):
            if isinstance(value, dict) and value.get("workspace_scope", {{}}).get("workspace") == workspace:
                cache._RESULTS[identity] = (created - 3600, value)
    expiry.unlink()
runpy.run_path({app!r}, run_name="__main__")
'''


def capture(page, path):
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_text("依据查询结果", exact=True).evaluate("element => element.scrollIntoView({block: 'start'})")
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
              "checks": {}, "errors": [], "real_mobile_safari_keyboard": "not_verified"}
    with tempfile.TemporaryDirectory(prefix="healthzip-rag-result-") as temporary:
        folder = Path(temporary)
        database = folder / ".local/healthzip.sqlite3"
        create_product_fixture(database)
        repo = Repository(database)
        repo.conn.execute("UPDATE health_sample SET metadata_json=?",
                          ('{"protocol_id":"synthetic-recorded-protocol"}',))
        repo.conn.commit()
        context = save_context(repo, {"population": "adults"})
        repo.close()
        (folder / "context.txt").write_text(context)
        library = folder / ".local/knowledge"
        kb = KnowledgeWorkbench(library, environment_kind="synthetic_test")
        for mid, claim in (("STATE-RHR", HEART_CLAIM), ("STATE-SDNN", "合成已审核HRV依据：SDNN保持原测量口径。"),
                           ("STATE-SLEEP-24H", "合成睡眠来源：过去24小时的已观察睡眠不等于完整夜间睡眠。")):
            profile = domains.configuration()["profiles"][mid]
            add(kb, "synthetic-" + mid, mid=mid, assigned=profile["required_domains"],
                text=profile["query"] + " " + claim)
        for connection in (kb.lib.sources, kb.lib.theories):
            connection.execute("PRAGMA journal_mode=WAL")
        kb.close()
        wrapper = folder / "wrapper"
        wrapper.mkdir()
        (wrapper / "src").symlink_to(ROOT / "src", target_is_directory=True)
        (wrapper / ".streamlit").mkdir()
        (wrapper / ".streamlit/config.toml").write_bytes((ROOT / ".streamlit/config.toml").read_bytes())
        (wrapper / "app.py").write_text(WRAPPER.format(app=str(ROOT / "app.py")))
        with isolated_app(wrapper, folder) as base, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            report["browser"] = browser.version
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            external = []

            def route_request(route):
                if route.request.url.startswith(base + "/"):
                    route.continue_()
                else:
                    external.append("blocked_external_request")
                    route.abort()

            page.route("http**/*", route_request)
            page.on("pageerror", lambda error: report["errors"].append(str(error)))
            page.goto(base + "/?workspace=heart")
            settle(page)
            button = page.get_by_role("button", name="查阅依据并解释变化", exact=True)
            button.wait_for()
            (folder / "expire-cache-once.txt").write_text("心率")
            button.click()
            page.get_by_text(HEART_CLAIM, exact=False).first.wait_for(timeout=15000)
            assert not page.get_by_text("范围或记录已更新，旧解释不再用于本期数据。", exact=True).count()
            assert page.get_by_text("依据查询结果", exact=True).is_visible()
            capture(page, output / "heart-rag-result-mobile.png")
            report["checks"]["heart_expired_fact_cache_then_real_supported_result"] = "passed"

            navigate(page, "睡眠")
            assert not page.get_by_text("范围或记录已更新，旧解释不再用于本期数据。", exact=True).count()
            (folder / "expire-cache-once.txt").write_text("睡眠")
            page.get_by_role("button", name="查阅依据并解释变化", exact=True).click()
            page.get_by_text("依据查询结果", exact=True).wait_for(timeout=15000)
            assert not page.get_by_text("范围或记录已更新，旧解释不再用于本期数据。", exact=True).count()
            page.get_by_text("尚未确认测量方法与协议", exact=False).wait_for()
            capture(page, output / "sleep-rag-missing-protocol-mobile.png")
            report["checks"]["sleep_expired_fact_cache_then_actionable_result"] = "passed"

            token = knowledge_clock(library)
            repo = Repository(database)
            metric = analyze_workspace(repo, "心率")["workspace_scope"]["metrics"]["STATE-RHR"]
            repo.close()
            kb = KnowledgeWorkbench(library, environment_kind="synthetic_test")
            response = kb.explain_metric("STATE-RHR", "explain_metric", metric,
                                        {"population": "adults", "measurement_protocol": "synthetic-recorded-protocol"},
                                        mode="lexical", candidate_scope="reviewed_metric", allow_explanation_network=False)
            assert response["evidence_context"]["capability_permissions"]["source_explanation"]
            kb.close()
            assert knowledge_clock(library) == token
            navigate(page, "心率")
            page.get_by_text(HEART_CLAIM, exact=False).first.wait_for()
            assert not page.get_by_text("依据已有更新", exact=False).count()
            report["checks"]["independent_audit_and_wal_close_keep_result"] = "passed"
            report["checks"]["heart_sleep_request_state_isolated"] = "passed"

            kb = KnowledgeWorkbench(library, environment_kind="synthetic_test")
            kb.core_state("claim", "synthetic-STATE-RHR", "1", "revoked",
                          actor="Synthetic browser check", rationale="Real lifecycle regression")
            kb.close()
            navigate(page, "睡眠")
            navigate(page, "心率")
            page.get_by_text("依据已有更新", exact=False).wait_for()
            assert not page.get_by_text(HEART_CLAIM, exact=False).count()
            report["checks"]["real_revocation_hides_old_claim"] = "passed"
            assert not (folder / "model-attempts.txt").exists()
            assert not report["errors"] and not external
            report["model_http_attempts"] = 0
            report["external_browser_requests"] = 0
            report["source_sha256"] = product_source_hashes(ROOT, extra=("src/healthzip/knowledge/revisions.py",))
            report["status"] = "passed"
            browser.close()
    (output / "rag-result-browser-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "checks": report["checks"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
