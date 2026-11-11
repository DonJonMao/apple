"""Executable browser acceptance: disconnected refresh, replay and lost response.

Run with Playwright + Chromium installed (not part of minimal runtime):
PYTHONPATH=src python tests/training/offline_browser_check.py
The database, token and all records are synthetic and temporary.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
from contextlib import redirect_stdout
from pathlib import Path

from playwright.sync_api import sync_playwright

from healthzip.db.repository import Repository
from healthzip.sync_server import HealthZipHTTPServer
from healthzip.training import TrainingService
from healthzip.training.offline import recorder_html


def run() -> dict:
    with tempfile.TemporaryDirectory(prefix="healthzip-offline-browser-") as directory:
        folder = Path(directory)
        repo = Repository(folder / "synthetic.sqlite3")
        svc = TrainingService(repo)
        equipment = svc.create_equipment("合成史密斯 A", "smith")
        condition = {
            "equipment_instance_id": equipment["id"],
            "load_basis": "plates_per_side_kg",
            "load_basis_confirmed": True,
            "settings_confirmed": True,
            "settings": {"bench_angle": 30},
            "side": "both",
            "repetition_semantics": "simultaneous",
            "rom_protocol": "synthetic-full",
            "symmetric_loading": True,
            "effective_bar_mass_kg": None,
        }
        template = svc.create_template(
            "离线胸部计划",
            [
                {
                    "exercise_id": "psa.ex.smith_incline_press",
                    "condition": condition,
                    "targets": {"sets": [{"set_type": "work", "reps_min": 8, "reps_max": 10}]},
                }
            ],
        )
        repo.close()
        html = folder / "HealthZIP-offline.html"
        html.write_bytes(recorder_html())
        server = HealthZipHTTPServer(
            ("127.0.0.1", 0), folder / "synthetic.sqlite3", "synthetic-browser-token", 1024 * 1024
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
                context = browser.new_context(viewport={"width": 390, "height": 844})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(html.as_uri())
                page.locator("#connection").evaluate("(element)=>element.open=true")
                page.locator("#base").fill(f"http://127.0.0.1:{server.server_address[1]}")
                page.locator("#token").fill("synthetic-browser-token")
                page.get_by_role("button", name="连接并缓存目录", exact=True).click()
                page.wait_for_function(
                    "document.querySelector('#notice').textContent.includes('已缓存在这台设备')"
                )
                context.set_offline(True)
                page.locator("#template").select_option(template["id"])
                page.get_by_role("button", name="开始新训练", exact=True).click()
                first = page.locator("section.set").first
                first.get_by_role("button", name="预先指定参考组", exact=True).click()
                first = page.locator("section.set").first
                first.get_by_label("重量 / 刻度", exact=True).fill("30")
                first.get_by_label("实际次数", exact=True).fill("10")
                first.get_by_label("实际 RIR（未知留空）", exact=True).fill("2")
                first.get_by_label("停止原因", exact=True).select_option("plan_target")
                first.get_by_role("button", name="确认完成", exact=True).click()
                first = page.locator("section.set").first
                first.get_by_role("button", name="复制为新组草稿", exact=True).click()
                second = page.locator("section.set").nth(1)
                second.get_by_role("button", name="确认完成", exact=True).click()
                assert page.locator("section.set").count() == 2
                queued_before = page.evaluate(
                    "JSON.parse(localStorage.getItem('healthzip.training.offline.v1.3')).outbox.length"
                )
                page.reload()
                page.locator("#connection").evaluate("(element)=>element.open=true")
                assert page.locator("section.set").count() == 2
                assert (
                    page.locator("section.set")
                    .first.get_by_label("重量 / 刻度", exact=True)
                    .input_value()
                    == "30"
                )
                assert (
                    page.evaluate(
                        "JSON.parse(localStorage.getItem('healthzip.training.offline.v1.3')).outbox.length"
                    )
                    == queued_before
                )
                context.set_offline(False)
                # Deliver first event but deliberately lose its HTTP reply.
                intercepted = []

                def lose_first_response(route):
                    response = route.fetch()
                    assert response.status == 200
                    intercepted.append(True)
                    route.abort("failed")

                context.route("**/v1/training/events", lose_first_response)
                page.get_by_role("button", name="同步待发送记录", exact=True).click()
                page.wait_for_function(
                    "document.querySelector('#notice').textContent.includes('同步未完成')"
                )
                assert intercepted
                assert (
                    page.evaluate(
                        "JSON.parse(localStorage.getItem('healthzip.training.offline.v1.3')).outbox.length"
                    )
                    == queued_before
                )
                context.unroute("**/v1/training/events", lose_first_response)
                page.reload()
                page.locator("#connection").evaluate("(element)=>element.open=true")
                page.get_by_role("button", name="同步待发送记录", exact=True).click()
                page.wait_for_function(
                    "JSON.parse(localStorage.getItem('healthzip.training.offline.v1.3')).outbox.length===0"
                )
                assert errors == [], errors
                browser.close()
            repo = Repository(folder / "synthetic.sqlite3")
            svc = TrainingService(repo)
            sessions = svc.list_sessions()
            assert len(sessions) == 1
            session = svc.get_session(sessions[0]["id"])
            assert session["completed_sets"] == 2 and len(session["sets"]) == 2
            assert all(row["load_value"] == "30" and row["reps"] == 10 for row in session["sets"])
            assert session["sets"][0]["set_uuid"] != session["sets"][1]["set_uuid"]
            assert session["sets"][0]["reference_declared_at"]
            assert session["template_version"] == 1
            slots = session["plan_snapshot"]["client_plan_slots"]
            assert len(slots) == 1 and slots[0]["set_uuid"] == session["sets"][0]["set_uuid"]
            result = {
                "status": "passed",
                "viewport": "390x844",
                "standalone_file_refresh_while_offline": True,
                "lost_response_retry_idempotent": True,
                "completed_real_sets": 2,
                "identical_real_sets_preserved": True,
                "template_snapshot_version": 1,
                "frozen_planned_sets": len(slots),
                "page_errors": errors,
                "data": "synthetic_only",
            }
            repo.close()
            return result
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    with redirect_stdout(sys.stderr):
        result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
