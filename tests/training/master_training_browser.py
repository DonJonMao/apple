"""Capture the same synthetic session before/after the redesign and verify revisions."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright
from product_redesign_training_browser import RedesignCheck
from strength_browser_fixture import create_fixture
from strength_workbench_browser_check import isolated_app


def capture(check, before, sockets):
    check.wait(lambda: check.testid("strength-home").is_visible(), timeout=60000)
    check.screenshot("home.png")
    check.click("open-start")
    check.choose("卧推", "psa.ex.smith_incline_press")
    session = check.active()
    instance = session["exercises"][0]
    row = instance["sets"][0]["set_uuid"]
    check.fill_row(row, load="32.5", quantity="8", rir="0")
    check.click("set-menu", row)
    check.screenshot("set-options.png")
    check.click("open-finish")
    check.screenshot("finish.png")
    if before:
        return
    check.click("workbench")
    menu = check.row(row)
    menu.get_by_label("停止原因（可选）").select_option("technical_limit")
    menu.get_by_label("组类型").select_option("assessment")
    check.complete_row(row)
    check.click("copy-last", instance["id"])
    actual, copy = check.active()["exercises"][0]["sets"]
    assert actual["stop_reason"] == "technical_limit" and actual["set_type"] == "assessment"
    assert copy["completion_state"] == "draft" and copy["rir"] is None and not copy["stop_reason"]
    check.passed("optional_set_context_saved_without_copying_facts")
    check.click("home")
    check.testid("continue-training").click()
    check.wait(lambda: check.testid("training-workbench").is_visible())
    assert check.active()["id"] == session["id"]
    check.click("open-finish")
    check.frame.get_by_label("未完成草稿处理").select_option("discard")
    check.click("confirm-end")
    check.wait(lambda: check.testid("training-detail").is_visible())
    stored = check.service_read(lambda svc: svc.get_session(session["id"]))
    assert stored["completed_sets"] == 1
    assert next(r for r in stored["sets"] if r["set_uuid"] == copy["set_uuid"])["deleted_at"]
    check.passed("reviewed_discard_keeps_actual_and_tombstones_only_drafts")
    check.click("set-menu", row)
    check.click("edit-completed", row)
    check.row(row).locator('[data-field="reps"]').fill("9")
    check.complete_row(row)
    assert check.service_read(lambda svc: svc.get_set(row)["reps"]) == 9
    check.click("set-menu", row)
    check.click("delete-set", row)
    check.click("confirm-delete-set")
    assert check.service_read(lambda svc: svc.get_session(session["id"])["completed_sets"]) == 0
    check.click("undo")
    assert check.service_read(lambda svc: svc.get_session(session["id"])["completed_sets"]) == 1
    check.screenshot("corrected-history.png")
    check.page.screenshot(path=str(check.output / "history-with-navigation.png"))
    check.click("home")
    check.click("open-start")
    check.choose("平板", "psa.ex.barbell_bench_press")
    offline_row = check.active()["exercises"][0]["sets"][0]["set_uuid"]
    check.row(offline_row).locator('[data-field="reps"]').fill("7")
    assert sockets
    check.page.context.set_offline(True)
    for socket in sockets:
        socket.close(code=1001, reason="synthetic temporary disconnect")
    try:
        assert not check.page.evaluate("navigator.onLine")
        check.row(offline_row).locator('[data-field="reps"]').fill("8", timeout=3000)
        assert "本机" in check.row(offline_row).locator("[data-draft-state]").inner_text()
        assert check.service_read(lambda svc: svc.get_set(offline_row)["reps"]) is None
    finally:
        check.page.context.set_offline(False)
    check.page.reload()
    check.wait(lambda: check.testid("training-workbench").is_visible(), timeout=60000)
    assert check.row(offline_row).locator('[data-field="reps"]').input_value() == "8"
    check.complete_row(offline_row)
    assert check.service_read(lambda svc: svc.get_set(offline_row)["reps"]) == 8
    check.passed("browser_disconnect_draft_recovers_after_reconnection", browser_offline=True,
                 closed_websocket=True, server_reps_while_disconnected=None, restored_reps=8)
    check.passed("history_correct_delete_undo", reps_after_correction=9, counts=[1, 0, 1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--before", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="healthzip-training-capture-") as tmp:
        folder = Path(tmp)
        database = folder / ".local/healthzip.sqlite3"
        database.parent.mkdir()
        create_fixture(database)
        with isolated_app(args.root, folder) as base, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 390, "height": 844})
            sockets = []
            if not args.before:
                def forward(ws):
                    ws.connect_to_server()
                    sockets.append(ws)
                page.route_web_socket("**/_stcore/stream", forward)
            page.goto(base + "/?workspace=strength")
            check = RedesignCheck(page, database, args.output)
            try:
                capture(check, args.before, sockets)
            finally:
                (args.output / "captures.json").write_text(json.dumps({
                    "data": "synthetic_only", "browser": browser.version, "viewport": [390, 844],
                    "checks": check.results, "stage": "before" if args.before else "after",
                }, ensure_ascii=False, indent=2))
                browser.close()


if __name__ == "__main__":
    main()
