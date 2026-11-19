"""Run the complete app.py strength UI with Chromium and synthetic data only.

Usage (Playwright + Chromium are development-only prerequisites):
  PYTHONPATH=src python tests/training/strength_workbench_browser_check.py \
      --output artifacts/strength_workbench

The app runs in a fresh temporary cwd. Neither its default SQLite database nor
its knowledge directory can resolve to the production .local directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright
from strength_browser_fixture import create_fixture

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService

TRANSPORT_CONTROL = """(() => {
    const add = window.addEventListener;
    window.addEventListener = function(type, listener, options) {
        if (type !== 'message' || typeof listener !== 'function')
            return add.call(this, type, listener, options);
        const guarded = function(event) {
            const gate = window.__transportTestGate;
            const receipt = event.data?.args?.receipt;
            const pending = document.querySelector('#app')?.dataset.pendingId;
            if (gate && event.source === parent && event.data?.type === 'streamlit:render' &&
                receipt?.action === 'save_set' && receipt.id === pending) {
                if (!gate.targetId) {
                    gate.targetId = receipt.id;
                    window.__transportTestDroppedId = receipt.id;
                    if (gate.delay != null) setTimeout(() => {
                        if (window.__transportTestGate === gate) window.__transportTestGate = null;
                        listener.call(window, event);
                    }, gate.delay);
                }
                return;
            }
            return listener.call(this, event);
        };
        return add.call(this, type, guarded, options);
    };
})();"""


@contextmanager
def isolated_app(root, folder):
    """Start the real entrypoint; logs and database stay in temporary storage."""
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        port = connection.getsockname()[1]
    environment = {**os.environ, "PYTHONPATH": str(root / "src")}
    command = [
        sys.executable, "-m", "streamlit", "run", str(root / "app.py"),
        "--server.address", "127.0.0.1", "--server.port", str(port),
        "--server.headless", "true", "--browser.gatherUsageStats", "false",
        "--server.fileWatcherType", "none",
    ]
    with (folder / "synthetic-streamlit.log").open("w") as log:
        process = subprocess.Popen(command, cwd=folder, env=environment, stdout=log, stderr=log)
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(200):
                if process.poll() is not None:
                    raise RuntimeError("Synthetic Streamlit exited before becoming ready")
                try:
                    with urllib.request.urlopen(base + "/_stcore/health", timeout=0.5) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Synthetic Streamlit did not become ready")
            yield base
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


class BrowserCheck:
    def __init__(self, page, database, output):
        self.page = page
        self.database = database
        self.output = output
        self.results = {}

    @property
    def frame(self):
        for frame in self.page.frames:
            if frame.locator("#app").count() and "healthzip_strength_workbench" in frame.url:
                return frame
        raise AssertionError("The real strength component iframe is not mounted")

    def wait(self, predicate, message="strength component state", timeout=20000):
        deadline = time.monotonic() + timeout / 1000
        last = None
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return
            except Exception as error:
                last = error
            self.page.wait_for_timeout(75)
        raise AssertionError(f"Timed out waiting for {message}; last error: {last}")

    def testid(self, name):
        return self.frame.get_by_test_id(name)

    def button(self, name):
        return self.frame.get_by_role("button", name=name, exact=True)

    def action(self, name, identity=None):
        selector = f'[data-action="{name}"]'
        if identity is not None:
            selector += f'[data-id="{identity}"]'
        return self.frame.locator(selector)

    def idle(self):
        self.wait(lambda: self.frame.locator("#app").get_attribute("data-pending-id") == "",
                  "backend acknowledgement")

    def click(self, name, identity=None):
        self.idle()
        self.action(name, identity).first.click()
        self.idle()

    def service_read(self, function):
        with closing(Repository(self.database)) as repo:
            return function(TrainingService(repo))

    def active(self):
        return self.service_read(lambda svc: svc.get_session(svc.list_sessions(active_only=True)[-1]["id"]))

    def screenshot(self, name, *, full_page=False):
        self.close_mobile_sidebar()
        self.page.screenshot(path=str(self.output / name), full_page=full_page)

    def close_mobile_sidebar(self):
        if self.page.viewport_size["width"] > 600:
            return
        sidebar = self.page.get_by_test_id("stSidebar")
        box = sidebar.bounding_box() if sidebar.count() else None
        button = self.page.get_by_role("button", name="Collapse sidebar", exact=True)
        if box and box["x"] >= -1 and button.count():
            button.click(force=True)
            self.page.wait_for_timeout(350)

    def passed(self, name, **evidence):
        self.results[name] = {"status": "passed", **evidence}
        print("PASS " + name, flush=True)

    def row(self, identity):
        return self.testid("set-row-" + identity)

    def fill_row(self, identity, *, load="", quantity="", rir="", mode="reps", unit="kg"):
        row = self.row(identity)
        row.locator('[data-field="load_value"]').fill(load)
        row.locator(f'[data-field="{mode}"]').fill(quantity)
        row.locator('[data-field="rir"]').fill(rir)
        if load:
            row.locator('[data-field="load_unit"]').select_option(unit)

    def delay_next_save_receipt(self, delay_ms):
        """Delay one real transport receipt; Python validation/write still run.

        A None delay drops one delivery, allowing the visible same-ID retry.
        Neither the command nor the real backend response is fabricated.
        """
        self.frame.evaluate("delay => {window.__transportTestGate = {delay};}", delay_ms)

    def complete_row(self, identity):
        self.row(identity).locator('[data-action="complete-set"]').click()
        self.idle()

    def open_strength(self, base):
        self.page.goto(base)
        self.page.get_by_role("radio", name="力量", exact=True).check(force=True)
        self.wait(lambda: self.testid("strength-home").is_visible(), "strength home")

    def assert_widths(self, label):
        values = []
        for width in (320, 375, 390, 430, 1440):
            self.page.set_viewport_size({"width": width, "height": 900 if width > 600 else 844})
            self.page.wait_for_timeout(150)
            dimensions = self.frame.evaluate("""() => ({
                viewport: innerWidth, document: document.documentElement.scrollWidth,
                body: document.body.scrollWidth,
                bad: [...document.querySelectorAll('input,button,.exercise-card,.set-main,.footer')]
                    .filter(e => !e.closest('.region-scroll,.selected-list'))
                    .filter(e => e.getBoundingClientRect().left < -1 ||
                       e.getBoundingClientRect().right > innerWidth + 1)
                    .map(e => ({tag:e.tagName, name:e.getAttribute('aria-label'),
                        left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}))
            })""")
            assert dimensions["document"] <= dimensions["viewport"], dimensions
            assert dimensions["body"] <= dimensions["viewport"], dimensions
            assert not dimensions["bad"], dimensions
            values.append({"width": width, **dimensions})
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.wait_for_timeout(350)
        self.close_mobile_sidebar()
        self.passed("responsive_" + label, widths=values)

    def run_primary(self, manifest):
        """Visible clicks/inputs only; database reads verify committed facts."""
        self.screenshot("01-home-calendar-mobile.png")
        first_day = self.frame.locator(f'[data-date="{manifest["month"]}-01"]')
        assert "61场训练" in first_day.get_attribute("aria-label")
        first_day.click()
        self.idle()
        assert self.frame.locator(".session-card").count() == 61
        initial_month = manifest["month"]
        for _ in range(12 - int(initial_month[-2:]) + 1):
            self.click("next-month")
        assert f"{int(initial_month[:4]) + 1} 年 1 月" in self.frame.locator(".calendar-heading").inner_text()
        for _ in range(12 - int(initial_month[-2:]) + 1):
            self.click("prev-month")
        self.frame.locator(f'[data-date="{initial_month}-01"]').click()
        self.idle()
        # Explicitly select an earlier date before starting today's training.
        self.passed("11_calendar", month_sessions=63, same_day_independent_sessions=61,
                    deleted_excluded=True, utc_month_boundary_included=True, cross_year_navigation=True)
        self.assert_widths("home")
        self.testid("start-training").click()
        self.wait(lambda: self.testid("start-free-training").is_visible(), "free start panel")
        self.screenshot("02-start-empty-mobile.png")
        self.button("胸").click()
        self.testid("start-free-training").click()
        self.wait(lambda: self.testid("catalog-search").is_visible(), "automatic action picker")
        session = self.active()
        assert session["template_id"] is None
        assert datetime.fromisoformat(session["started_at"]).date() == datetime.now().date()
        self.testid("catalog-search").fill("杠铃卧推")
        self.wait(lambda: self.frame.locator(".catalog-card").count() == 1, "catalog alias result")
        self.frame.locator(".catalog-card").get_by_role("button", name="添加", exact=True).click()
        self.screenshot("03-catalog-selected-mobile.png")
        self.button("关闭动作选择").click()
        assert not self.active()["exercises"]
        self.testid("add-exercises").click()
        self.idle()
        self.testid("catalog-search").fill("杠铃卧推")
        self.wait(lambda: self.frame.locator(".catalog-card").count() == 1, "catalog search again")
        self.frame.locator(".catalog-card").get_by_role("button", name="添加", exact=True).click()
        self.testid("catalog-confirm").click()
        self.wait(lambda: self.frame.locator(".exercise-card").count() == 1, "saved exercise card")
        session = self.active()
        assert len(session["exercises"]) == 1 and len(session["sets"]) == 1
        draft = session["sets"][0]
        assert all(draft.get(key) is None for key in ("load_value", "reps", "rir", "started_at", "ended_at"))
        assert not draft.get("reference_set") and not draft.get("reference_declared_at")
        assert draft["completion_state"] == "draft" and session["completed_sets"] == 0
        self.fill_row(draft["set_uuid"], load="32.5", quantity="8")
        self.screenshot("04-compact-set-input-mobile.png")
        self.complete_row(draft["set_uuid"])
        self.wait(lambda: self.active()["completed_sets"] == 1, "committed ordinary completed set")
        actual = self.active()["sets"][0]
        assert float(actual["load_value"]) == 32.5 and actual["reps"] == 8 and actual["rir"] is None
        assert actual["started_at"] is None and actual["ended_at"]
        assert not actual.get("reference_set") and not actual.get("reference_declared_at")
        self.passed("01_free_training", empty_draft=True, decimal_load=32.5, rir=None,
                    fabricated_start=False, template=False, reference=False)
        self.screenshot("05-completed-set-mobile.png")
        self.assert_widths("compact_set")
        self.page.set_viewport_size({"width": 1440, "height": 1000})
        self.page.wait_for_timeout(500)
        self.screenshot("07-workbench-desktop.png")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.run_set_lifecycle(session["id"], draft["set_uuid"])

    def run_set_lifecycle(self, session_id, identity):
        instance_id = self.active()["exercises"][0]["id"]
        original = self.service_read(lambda svc: svc.get_set(identity))
        # A completed button cannot create another fact or move the finish anchor.
        self.row(identity).locator('[data-action="completed-noop"]').dblclick()
        unchanged = self.service_read(lambda svc: svc.get_set(identity))
        assert unchanged["revision"] == original["revision"] and unchanged["ended_at"] == original["ended_at"]
        for rir in ("0", "2"):
            self.click("add-set", instance_id)
            row = self.active()["sets"][-1]
            self.fill_row(row["set_uuid"], load="33.75", quantity="9", rir=rir)
            self.complete_row(row["set_uuid"])
            actual = self.service_read(lambda svc: svc.get_set(row["set_uuid"]))
            assert actual["rir"] == int(rir)
        self.passed("04_numeric_reps", rir_values=[None, 0, 2], decimal_loads=[32.5, 33.75])
        self.click("set-menu", identity)
        self.click("edit-completed", identity)
        self.row(identity).locator('[data-field="reps"]').fill("10")
        self.complete_row(identity)
        corrected = self.service_read(lambda svc: svc.get_set(identity))
        assert corrected["reps"] == 10 and corrected["ended_at"] == original["ended_at"]
        assert self.active()["completed_sets"] == 3
        self.click("add-set", instance_id)
        draft = self.active()["sets"][-1]
        self.fill_row(draft["set_uuid"], load="34.25", quantity="7")
        self.click("set-menu", draft["set_uuid"])
        self.delay_next_save_receipt(1400)
        self.action("save-draft", draft["set_uuid"]).click()
        self.row(draft["set_uuid"]).locator('[data-field="reps"]').fill("6")
        self.idle()
        stored = self.service_read(lambda svc: svc.get_set(draft["set_uuid"]))
        assert float(stored["load_value"]) == 34.25 and stored["completion_state"] == "draft" and stored["reps"] == 7
        assert self.row(draft["set_uuid"]).locator('[data-field="reps"]').input_value() == "6"
        assert "输入待保存" in self.row(draft["set_uuid"]).inner_text()
        self.click("set-menu", draft["set_uuid"])
        self.delay_next_save_receipt(None)
        self.action("save-draft", draft["set_uuid"]).click()
        self.wait(lambda: self.service_read(lambda svc: svc.get_set(draft["set_uuid"]))["reps"] == 6,
                  "real save before dropped receipt")
        pending_id = self.frame.locator("#app").get_attribute("data-pending-id")
        self.wait(lambda: self.action("retry").is_visible(), "visible same-request retry", timeout=15000)
        assert self.frame.evaluate("() => window.__transportTestDroppedId") == pending_id
        self.frame.evaluate("() => {window.__transportTestGate = null;}")
        self.action("retry").click()
        self.idle()
        assert self.frame.locator("#app").get_attribute("data-last-receipt-id") == pending_id
        assert self.service_read(lambda svc: svc.get_set(draft["set_uuid"]))["reps"] == 6
        self.page.reload()
        if self.page.get_by_role("radio", name="力量", exact=True).is_visible():
            self.page.get_by_role("radio", name="力量", exact=True).check(force=True)
        self.wait(lambda: self.testid("training-workbench").is_visible(), "restored saved draft")
        self.idle()
        assert self.row(draft["set_uuid"]).locator('[data-field="load_value"]').input_value() == "34.25"
        # Current row keeps unsaved input while entering and leaving history.
        self.row(draft["set_uuid"]).locator('[data-field="reps"]').fill("6")
        self.click("history", instance_id)
        assert self.frame.locator(".history-row").count() == 3
        assert "55 kg × 10 次" in self.frame.locator(".history-card").inner_text()
        self.click("history-back")
        assert self.row(draft["set_uuid"]).locator('[data-field="reps"]').input_value() == "6"
        self.passed("05_draft_and_correction", draft_refresh=True, history_preserves_unsaved=True,
                    correction_same_fact=True, original_end_preserved=True,
                    new_input_during_real_receipt_delay_preserved=True)
        self.click("history", instance_id)
        self.action("copy-history").first.click()
        self.idle()
        copied = self.active()["sets"][-1]
        assert copied["completion_state"] == "draft" and copied["rir"] is None
        assert all(copied.get(key) is None for key in ("started_at", "ended_at", "pain_flag", "quality_status"))
        assert not copied.get("reference_set")
        self.click("advice", instance_id)
        self.click("history-back")
        assert self.active()["completed_sets"] == 3
        self.passed("07_history_and_advice", latest_all_three=True, copy_only_draft=True,
                    advice_does_not_change_actual=True)
        # Concurrent write after the browser captured its revision.
        row = self.active()["sets"][-1]
        self.fill_row(row["set_uuid"], load="40.5", quantity="8", rir="2")
        self.service_read(lambda svc: svc.edit_set(row["set_uuid"], {
            "reps": 11, "pain_flag": True, "quality_status": "technique_limited",
            "quality_note": "合成技术限制", "notes": "合成高级字段保留",
        }, base_revision=row["revision"]))
        self.complete_row(row["set_uuid"])
        assert self.frame.locator("#app").get_attribute("data-last-receipt-status") == "conflicted"
        assert self.row(row["set_uuid"]).locator('[data-field="reps"]').input_value() == "8"
        assert self.service_read(lambda svc: svc.get_set(row["set_uuid"]))["reps"] == 11
        self.click("review-conflict", row["set_uuid"])
        assert self.row(row["set_uuid"]).locator(".conflict-panel").is_visible()
        self.screenshot("11-concurrent-review-mobile.png")
        self.click("rebase-draft", row["set_uuid"])
        self.click("set-menu", row["set_uuid"])
        self.click("save-draft", row["set_uuid"])
        merged = self.service_read(lambda svc: svc.get_set(row["set_uuid"]))
        assert merged["reps"] == 8 and merged["completion_state"] == "draft"
        assert merged["pain_flag"] == 1 and merged["quality_status"] == "technique_limited"
        assert merged["quality_note"] == "合成技术限制" and merged["notes"] == "合成高级字段保留"
        assert "有不适记录" in self.row(row["set_uuid"]).inner_text()
        self.passed("06_conflict_and_duplicate", completed_double_click_noop=True,
                    stale_revision_preserves_input=True, server_value_not_overwritten=True,
                    lost_real_receipt_same_id_retry=True, explicit_review_rebase_save=True,
                    latest_advanced_fields_preserved=True)
        # Delete a completed group, then restore it through the real event path.
        self.click("set-menu", identity)
        self.click("delete-set", identity)
        self.click("confirm-delete-set")
        assert self.active()["completed_sets"] == 2
        self.click("undo")
        assert self.active()["completed_sets"] == 3
        self.passed("08_set_delete_undo", counts=[3, 2, 3])
        self.click("workout-more")
        self.click("rest")
        self.click("timer-start")
        timer = self.active()["rest_timer"]
        assert timer["target_seconds"] is None
        self.click("timer-pause")
        self.click("timer-resume")
        self.frame.get_by_label("延长休息秒数").fill("12")
        self.click("timer-extend")
        self.click("timer-skip")
        self.click("workbench")
        assert all(row.get("started_at") is None for row in self.active()["sets"])
        before = self.service_read(lambda svc: len(svc.audit_events()))
        self.page.wait_for_timeout(2150)
        after = self.service_read(lambda svc: len(svc.audit_events()))
        assert before == after
        self.click("notes")
        self.frame.get_by_label("训练备注", exact=True).fill("合成训练中备注")
        self.click("save-notes")
        assert self.service_read(lambda svc: svc.get_session(session_id))["notes"] == "合成训练中备注"
        self.click("home")
        assert self.service_read(lambda svc: svc.get_session(session_id))["session_status"] == "in_progress"
        self.testid("continue-training").click()
        self.idle()
        self.click("open-finish")
        assert self.testid("finish-summary").locator("strong").all_text_contents() == ["3", "1", "2"]
        self.frame.get_by_label("结束训练备注").fill("合成可选结束反馈")
        self.frame.get_by_label("整场sRPE").fill("6")
        self.frame.get_by_label("整场实际时长").fill("20.5")
        self.screenshot("06-end-summary-mobile.png")
        self.click("confirm-end")
        ended = self.service_read(lambda svc: svc.get_session(session_id))
        assert ended["session_status"] == "completed" and ended["completed_sets"] == 3
        assert ended["duration_seconds"] == 1230 and ended["session_rpe"] == 6
        assert ended["feedback"]["notes"] == "合成可选结束反馈"
        assert self.frame.get_by_text("合成可选结束反馈", exact=True).is_visible()
        assert sum(row["completion_state"] == "draft" for row in ended["sets"]) == 2
        self.passed("09_time_and_finish", per_second_database_writes=0, fabricated_starts=0,
                    return_keeps_training_active=True, unfinished_drafts_preserved=2,
                    duration_seconds=1230, session_rpe=6, target_not_invented=True,
                    mid_session_note_updated_at_finish_visible=True)

    def search_catalog(self, identity):
        self.testid("catalog-search").fill(identity)
        self.page.wait_for_timeout(450)  # The production search intentionally debounces 350 ms.
        self.idle()
        self.wait(lambda: self.testid("catalog-item-" + identity).is_visible(), "requested catalog result")

    def run_batch_and_cards(self, manifest):
        self.click("home")
        self.testid("start-training").click()
        self.testid("start-free-training").click()
        self.wait(lambda: self.testid("catalog-search").is_visible(), "second free picker")
        self.idle()
        self.click("catalog-region", "")
        ordered = [manifest["catalog_ids"][index] for index in (3, 0, 4, 2, 1, 5)]
        for identity in ordered:
            self.search_catalog(identity)
            if identity == manifest["catalog_ids"][5]:
                media = self.testid("catalog-item-" + identity).locator("img.thumbnail")
                assert media.count() == 1
                media.evaluate("image => {image.src = 'data:image/png;base64,aW52YWxpZA==';}")
                self.wait(lambda: self.testid("catalog-item-" + identity).locator(".failure-image").is_visible(),
                          "real image decoding failure fallback")
            self.click("catalog-select", identity)
        selected = self.frame.locator(".selected-list li").all_text_contents()
        assert len(selected) == 6
        self.testid("catalog-search").fill("")
        self.page.wait_for_timeout(450)
        self.idle()
        self.assert_widths("catalog")
        self.screenshot("08-catalog-multiselect-mobile.png")
        self.click("catalog-confirm")
        session = self.active()
        assert [item["catalog_id"] for item in session["exercises"]] == ordered
        assert all(len(item["sets"]) == 1 for item in session["exercises"])
        self.passed("02_batch_actions", ordered_six=True, cancellation_no_write=True,
                    accidental_duplicate_instances=0, selected_across_search=True)
        for item in session["exercises"]:
            if self.testid("exercise-card-" + item["id"]).locator(".card-body").count() == 0:
                self.click("toggle-card", item["id"])
            self.click("add-set", item["id"])
            self.click("add-set", item["id"])
            assert self.frame.locator(".card-body").count() == 1
            assert self.frame.locator(".set-main").count() == 3
        session = self.active()
        assert [len(item["sets"]) for item in session["exercises"]] == [3] * 6
        last = session["exercises"][-1]
        self.fill_row(last["sets"][0]["set_uuid"], load="12.75", quantity="8", unit="level")
        first = session["exercises"][0]
        self.click("toggle-card", first["id"])
        self.click("toggle-card", last["id"])
        assert self.row(last["sets"][0]["set_uuid"]).locator('[data-field="load_value"]').input_value() == "12.75"
        self.frame.locator(".scroll").evaluate("element => {element.scrollTop = 0;}")
        self.screenshot("09-six-exercise-cards-mobile.png")
        self.assert_widths("six_cards")
        self.page.set_viewport_size({"width": 1440, "height": 1000})
        self.page.wait_for_timeout(500)
        self.frame.locator(".scroll").evaluate("element => {element.scrollTop = 0;}")
        self.screenshot("10-six-cards-desktop.png")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.passed("03_six_by_three", actions=6, rows_per_action=3, expanded=1,
                    total_visible_main_rows=3, switching_keeps_unsaved=True)
        # Record each actual measurement mode in the exact same compact editor.
        for index, (field, quantity, load, unit) in enumerate((
            ("duration_s", "33.5", "", "kg"),
            ("reps", "8", "20.75", "kg"),
            ("distance_m", "24.75", "12.5", "kg"),
        )):
            item = session["exercises"][index]
            if self.testid("exercise-card-" + item["id"]).locator(".card-body").count() == 0:
                self.click("toggle-card", item["id"])
            row = item["sets"][0]
            self.fill_row(row["set_uuid"], load=load, quantity=quantity,
                          mode=field, unit=unit, rir="0" if index == 1 else "")
            self.complete_row(row["set_uuid"])
            actual = self.service_read(lambda svc: svc.get_set(row["set_uuid"]))
            assert actual[field] == float(quantity)
        self.passed("04_three_measurement_modes", repetitions=8, duration_s=33.5, distance_m=24.75)
        # Very old same-action facts remain visible; no best-set substitution.
        older = session["exercises"][4]
        self.click("toggle-card", older["id"])
        self.click("history", older["id"])
        assert "12.5 kg × 9 次" in self.frame.locator(".history-card").inner_text()
        self.click("history-back")
        novice = session["exercises"][2]
        self.click("toggle-card", novice["id"])
        self.click("history", novice["id"])
        assert "首次记录" in self.frame.locator(".empty").inner_text()
        self.click("history-back")
        self.passed("07_old_and_first_history", old_days=480, first_record_explicit=True)
        # Directory empty states and a legitimate repeated exercise use real UI.
        self.click("open-catalog")
        self.testid("catalog-search").fill("不存在的合成动作零结果")
        self.page.wait_for_timeout(450)
        self.idle()
        assert "没有找到匹配动作" in self.frame.locator(".empty").inner_text()
        self.search_catalog(ordered[1])
        assert self.testid("catalog-item-" + ordered[1]).get_by_role("button", name="再次添加此动作", exact=True).is_visible()
        self.click("catalog-select", ordered[1])
        self.click("catalog-confirm")
        assert len(self.active()["exercises"]) == 7
        self.passed("10_directory_empty_and_media", no_results=True, neutral_media_placeholders=True,
                    real_image_decode_failure_fallback=True,
                    long_chinese_name_readable=True, explicit_repeated_action=True)
        # End this synthetic session, delete the real whole session and undo.
        self.click("open-finish")
        self.click("confirm-end")
        self.click("session-more")
        self.click("delete-session")
        self.click("confirm-delete-session")
        deleted = self.service_read(lambda svc: svc.get_session(session["id"]))
        assert deleted["deleted_at"] and deleted["completed_sets"] == 0
        self.click("undo")
        restored = self.service_read(lambda svc: svc.get_session(session["id"]))
        assert restored["deleted_at"] is None and restored["completed_sets"] == 3
        self.passed("08_session_delete_undo", counts=[3, 0, 3])

    def run_existing_plan(self, manifest):
        self.testid("start-training").click()
        self.frame.locator("summary").filter(has_text="使用已有计划").click()
        self.frame.get_by_label("已有计划", exact=True).select_option(manifest["template_id"])
        self.testid("start-free-training").click()
        self.wait(lambda: self.testid("training-workbench").is_visible(), "planned workbench")
        self.idle()
        session = self.active()
        assert session["template_id"] == manifest["template_id"]
        assert len(session["exercises"]) == 6 and all(len(x["sets"]) == 3 for x in session["exercises"])
        labels = self.frame.locator(".exercise-caption").all_text_contents()
        assert any("自重" in label for label in labels)
        assert any("助力大小" in label for label in labels)
        assert any("每只哑铃" in label for label in labels)
        assert all(not row.get("reference_set") for row in session["sets"])
        self.passed("04_known_load_conventions_and_template", template_does_not_duplicate_drafts=True,
                    bodyweight=True, assistance=True, per_dumbbell=True)
        self.click("open-finish")
        self.click("confirm-end")
        # This real navigation returns to the existing application's overview.
        self.click("home")
        self.action("health-overview").click()
        self.wait(lambda: self.page.get_by_role("heading", name="数据总览", exact=True).is_visible(),
                  "return to health overview")
        self.passed("workspace_return", actual_overview_navigation=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--chromium", help="Optional local Chromium executable")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    source_names = ["app.py", "src/healthzip/ui/training_page.py",
                    "src/healthzip/ui/training_bridge.py", "src/healthzip/ui/training_workbench.py",
                    "src/healthzip/training/service.py",
                    "src/healthzip/ui/strength_component/index.html",
                    "src/healthzip/ui/strength_component/workbench.js",
                    "src/healthzip/ui/strength_component/workbench.css"]
    source_hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in source_names}
    report = {"data": "synthetic_only", "entrypoint": "app.py", "results": {},
              "checked_at": datetime.now(timezone.utc).isoformat(),
              "tested_source_sha256": source_hashes}
    errors, external = [], []
    with tempfile.TemporaryDirectory(prefix="synthetic-strength-workbench-") as temporary:
        folder = Path(temporary)
        database = folder / ".local" / "healthzip.sqlite3"
        manifest = create_fixture(database)
        with isolated_app(root, folder) as base, sync_playwright() as playwright:
            options = {"headless": True, "args": ["--no-sandbox"]}
            if args.chromium:
                options["executable_path"] = args.chromium
            browser = playwright.chromium.launch(**options)
            report["browser"] = browser.version
            context = browser.new_context(viewport={"width": 390, "height": 844})

            def local_only(route):
                if route.request.url.startswith(base + "/"):
                    route.continue_()
                else:
                    external.append(route.request.url)
                    route.abort()

            context.route("http**/*", local_only)
            page = context.new_page()
            page.add_init_script(TRANSPORT_CONTROL)
            page.on("pageerror", lambda error: errors.append(str(error)))
            check = BrowserCheck(page, database, output)
            try:
                check.open_strength(base)
                check.run_primary(manifest)
                check.run_batch_and_cards(manifest)
                check.run_existing_plan(manifest)
                assert not errors and not external, {"page_errors": errors, "external_requests": external}
                assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
                           for name, digest in source_hashes.items()), "Product source changed during browser run"
                report["sources_unchanged_during_run"] = True
                report["status"] = "passed"
                (output / "failure.png").unlink(missing_ok=True)
            except Exception as error:
                report["status"] = "failed"
                report["error"] = str(error)
                try:
                    report["transport_debug"] = check.frame.evaluate("() => ({observed:window.__transportObserved,dropped:window.__transportTestDroppedId,pending:document.querySelector('#app').dataset.pendingId})")
                except Exception:
                    pass
                page.screenshot(path=str(output / "failure.png"), full_page=True)
                raise
            finally:
                report["results"] = check.results
                report["page_errors"] = errors
                report["external_requests"] = external
                report["real_iphone_keyboard"] = "not_verified"
                (output / "browser-results.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                context.close()
                browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
