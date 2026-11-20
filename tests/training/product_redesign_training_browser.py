"""Real Chromium/full app acceptance for the redesigned training flow.

All fixtures, recordings and screenshots are synthetic. Device widths and a
reduced viewport exercise layout; they do not claim physical Safari keyboard QA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from strength_browser_fixture import create_fixture
from strength_workbench_browser_check import TRANSPORT_CONTROL, BrowserCheck, isolated_app


def percentile(values, fraction):
    return sorted(values)[min(len(values) - 1, int(len(values) * fraction))]


class RedesignCheck(BrowserCheck):
    def screenshot(self, name, *, full_page=False):
        self.frame.locator(".shell").screenshot(path=str(self.output / name))

    def geometry(self, view):
        evidence = []
        for width in (320, 375, 390, 430, 768, 1440):
            self.page.set_viewport_size({"width": width, "height": 844})
            self.page.wait_for_timeout(100)
            dimensions = self.frame.evaluate("""() => ({viewport:innerWidth,
                width:document.documentElement.scrollWidth, height:innerHeight,
                content:document.querySelector('#app').getBoundingClientRect().height,
                scroll: [...document.querySelectorAll('.shell,.scroll,.catalog-list,.history-card')]
                    .map(e=>({height:e.clientHeight,content:e.scrollHeight,
                         overflow:getComputedStyle(e).overflowY})),
                inputs:[...document.querySelectorAll('input[data-set]')]
                    .map(e=>({font:parseFloat(getComputedStyle(e).fontSize),right:e.getBoundingClientRect().right})),
                icons:[...document.querySelectorAll('.notice svg')]
                    .map(e=>({w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height}))})""")
            assert dimensions["width"] <= dimensions["viewport"] + 1, dimensions
            assert dimensions["content"] <= dimensions["height"] + 1, dimensions
            assert all(x["overflow"] not in ("scroll", "auto") for x in dimensions["scroll"]), (
                dimensions
            )
            assert all(
                x["font"] >= 16 and x["right"] <= dimensions["viewport"] + 1
                for x in dimensions["inputs"]
            ), dimensions
            assert all(0 < x["w"] <= 20 and 0 < x["h"] <= 20 for x in dimensions["icons"]), (
                dimensions
            )
            evidence.append({"width": width, **dimensions})
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.passed("geometry_" + view, measurements=evidence)

    def choose(self, query, identity):
        self.click("open-catalog")
        self.frame.get_by_label("搜索动作").fill(query)
        self.wait(lambda: self.action("catalog-select", identity).count() > 0)
        self.idle()
        start = time.perf_counter()
        self.click("catalog-select", identity)
        self.wait(lambda: self.testid("training-workbench").is_visible())
        return (time.perf_counter() - start) * 1000

    def run(self):
        self.geometry("home")
        self.screenshot("training-home-mobile.png")
        self.click("open-start")
        self.wait(lambda: self.testid("training-workbench").is_visible())
        assert not self.frame.locator('[data-local="start.name"]').count()
        self.passed("A09_direct_start", generated_name=self.active()["name"])
        self.click("open-catalog")
        self.geometry("picker")
        self.frame.get_by_label("搜索动作").fill("卧推")
        self.wait(lambda: self.action("catalog-select", "psa.ex.smith_incline_press").count())
        self.idle()
        self.screenshot("training-picker-mobile.png")
        self.click("catalog-select", "psa.ex.smith_incline_press")
        active = self.active()
        identity = active["id"]
        first = active["exercises"][0]
        row = first["sets"][0]["set_uuid"]
        self.fill_row(row, load="32.5", quantity="8", rir="0")
        self.click("open-catalog")
        self.frame.get_by_label("搜索动作").fill("never-a-synthetic-match")
        self.click("close-catalog")
        self.page.wait_for_timeout(400)
        assert self.testid("training-workbench").is_visible()
        assert len(self.active()["exercises"]) == 1
        assert self.row(row).locator('[data-field="rir"]').input_value() == "0"
        self.page.reload()
        self.wait(lambda: self.testid("training-workbench").is_visible())
        assert self.row(row).locator('[data-field="load_value"]').input_value() == "32.5"
        self.passed(
            "A10_A11_A12_A14_picker_and_refresh",
            one_selection_immediate_return=True,
            cancel_has_no_mutation=True,
            decimal_and_zero_preserved=True,
            reload_draft=True,
        )
        self.choose("平板", "psa.ex.barbell_bench_press")
        second = self.active()["exercises"][1]
        secondrow = second["sets"][0]["set_uuid"]
        assert self.row(row).locator('[data-field="rir"]').input_value() == "0"
        self.geometry("active_training")
        self.screenshot("training-active-mobile.png")
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.screenshot("training-active-desktop.png")
        self.page.set_viewport_size({"width": 390, "height": 844})
        # A real receipt is delayed while the user edits another retained node.
        self.delay_next_save_receipt(800)
        self.row(row).locator('[data-action="complete-set"]').click()
        self.fill_row(secondrow, load="20", quantity="9", rir="0")
        self.row(secondrow).locator('[data-field="reps"]').focus()
        self.frame.evaluate("window.__inputIdentity = document.activeElement")
        self.idle()
        assert self.frame.evaluate("window.__inputIdentity === document.activeElement")
        assert self.frame.evaluate("window.__inputIdentity.isConnected")
        assert self.row(secondrow).locator('[data-field="reps"]').input_value() == "9"
        self.passed("A15_receipt_preserves_dom_focus_and_new_input", real_receipt_delayed_ms=800)
        # Invalid completion leaves every field intact and emits a local error.
        self.row(secondrow).locator('[data-field="reps"]').fill("8.5")
        self.complete_row(secondrow)
        assert self.frame.locator(".row-error").count()
        assert self.row(secondrow).locator('[data-field="reps"]').input_value() == "8.5"
        self.screenshot("training-validation-mobile.png")
        self.row(secondrow).locator('[data-field="reps"]').fill("9")
        self.complete_row(secondrow)
        self.click("copy-last", second["id"])
        copied = self.active()["exercises"][1]["sets"][-1]
        assert (
            copied["reps"] == 9 and copied["rir"] is None and copied["completion_state"] == "draft"
        )
        self.passed("A13_copy_is_draft", no_actual_rir_or_completion_copied=True)
        # Dropped acknowledgement: retry SAME business id, one saved row.
        retryrow = copied["set_uuid"]
        self.fill_row(retryrow, load="20", quantity="8", rir="1")
        self.delay_next_save_receipt(None)
        self.row(retryrow).locator('[data-action="complete-set"]').click()
        self.wait(lambda: self.action("retry").count() > 0, timeout=15000)
        self.screenshot("training-timeout-mobile.png")
        self.geometry("pending_timeout")
        # Keep dropping the original receipt through the resize checks. Release
        # only on the actual retry click, so an unrelated parent rerender cannot
        # deliver the old acknowledgement before the user retries.
        self.action("retry").evaluate("e=>e.addEventListener('click',()=>{window.__transportTestGate=null},{capture:true,once:true})")
        self.action("retry").click()
        self.idle()
        assert self.active()["completed_sets"] == 3
        assert len(self.active()["exercises"][1]["sets"]) == 2
        self.passed("A14_A17_lost_ack_idempotent_retry", completed_sets=3)
        # Another writer changes a real revision while this browser has a draft.
        self.click("add-set", second["id"])
        conflictrow = self.active()["exercises"][1]["sets"][-1]
        self.fill_row(conflictrow["set_uuid"], load="20", quantity="7", rir="")
        self.service_read(
            lambda svc: svc.edit_set(
                conflictrow["set_uuid"], {"reps": 6}, base_revision=conflictrow["revision"]
            )
        )
        self.click("set-menu", conflictrow["set_uuid"])
        self.click("save-draft", conflictrow["set_uuid"])
        assert self.frame.locator(".row-error").count()
        assert self.row(conflictrow["set_uuid"]).locator('[data-field="reps"]').input_value() == "7"
        self.click("review-conflict", conflictrow["set_uuid"])
        self.click("rebase-draft", conflictrow["set_uuid"])
        self.click("save-draft", conflictrow["set_uuid"])
        self.passed("A15_real_revision_conflict", local_value_preserved=True, explicit_rebase=True)
        # User-entered drafts are saved as drafts before ending.
        self.row(conflictrow["set_uuid"]).locator('[data-field="reps"]').fill("5")
        self.click("open-finish")
        self.screenshot("training-finish-mobile.png")
        self.click("confirm-end")
        self.wait(lambda: self.testid("training-detail").is_visible())
        ended = self.service_read(lambda svc: svc.get_session(identity))
        assert ended["session_status"] == "completed" and ended["completed_sets"] == 3
        assert ended["exercises"][1]["sets"][-1]["reps"] == 5
        assert ended["exercises"][1]["sets"][-1]["completion_state"] == "draft"
        assert self.frame.get_by_role("button", name="未完成草稿第3组", exact=True).count()
        self.screenshot("training-history-mobile.png")
        self.geometry("history")
        self.passed("A13_ended_draft_is_not_actual", completed_sets=3, saved_unfinished_reps=5)
        # Exercise history is a normal, growing document too.
        self.click("history", first["id"])
        self.geometry("exercise_history")
        self.click("history-back")
        self.click("home")
        self.click("open-start")
        timings = []
        for index in range(30):
            timings.append(self.choose("平板", "psa.ex.barbell_bench_press"))
            if index < 10:
                inst = self.active()["exercises"][-1]
                for _ in range(2):
                    self.click("add-set", inst["id"])
        self.geometry("long_training")
        assert len(self.active()["exercises"]) == 30
        assert all(len(item["sets"]) == 3 for item in self.active()["exercises"][:10])
        self.action("open-catalog").last.scroll_into_view_if_needed()
        assert self.action("open-catalog").last.is_visible()
        last = self.active()["exercises"][-1]["sets"][0]["set_uuid"]
        self.row(last).locator('[data-field="load_value"]').focus()
        self.page.set_viewport_size({"width": 390, "height": 430})
        self.row(last).locator('[data-field="load_value"]').fill("10.5")
        assert self.row(last).locator('[data-action="complete-set"]').is_visible()
        self.passed(
            "A16_A18_long_training",
            exercises=30,
            first_ten_sets_each=3,
            shortened_viewport_height=430,
            physical_keyboard_tested=False,
        )
        self.click("open-catalog")
        self.click("close-catalog")
        self.page.wait_for_timeout(200)
        bounds = self.action("open-catalog").bounding_box()
        assert bounds and 0 <= bounds["y"] < 430, bounds
        assert self.row(last).locator('[data-field="load_value"]').input_value() == "10.5"
        self.passed("cancel_picker_restores_long_training_position", add_entry_in_view=True,
                    existing_input_preserved=True)
        self.passed(
            "picker_end_to_end_performance",
            n=len(timings),
            environment="localhost Chromium synthetic",
            p50_ms=statistics.median(timings),
            p95_ms=percentile(timings, 0.95),
            samples_ms=timings,
            definition="click selected action through durable backend acknowledgement and returned editable training view",
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/product_redesign/training"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    out = args.output.resolve()
    root = Path(__file__).resolve().parents[2]
    source_names = ["src/healthzip/ui/training_workbench.py", "src/healthzip/ui/training_bridge.py",
                    "src/healthzip/training/service.py", "src/healthzip/training/sequence_review.py"]
    source_names += [str(path.relative_to(root)) for path in (root / "src/healthzip/ui/strength_component").glob("*") if path.is_file()]
    source_hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in source_names}
    with tempfile.TemporaryDirectory(prefix="product-training-") as temp:
        folder = Path(temp)
        database = folder / ".local/healthzip.sqlite3"
        database.parent.mkdir()
        create_fixture(database)
        with isolated_app(root, folder) as base, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(
                viewport={"width": 390, "height": 844},
                record_video_dir=str(out / "video"),
                record_video_size={"width": 390, "height": 844},
            )
            context.add_init_script(TRANSPORT_CONTROL)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/?workspace=strength")
            check = RedesignCheck(page, database, out)
            completed = False
            try:
                check.wait(lambda: check.testid("strength-home").is_visible(), timeout=60000)
                check.run()
                assert not errors, errors
                completed = True
            finally:
                video = page.video
                context.close()
                (out / "training-browser-results.json").write_text(
                    json.dumps(
                        {
                            "data": "synthetic_only",
                            "results": check.results,
                            "browser_errors": errors,
                            "physical_safari_tested": False,
                            "completed": completed,
                            "source_hashes": source_hashes,
                            "video": str(Path(video.path()).relative_to(out)) if video else None,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                browser.close()


if __name__ == "__main__":
    main()
