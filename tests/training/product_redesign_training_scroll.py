"""Real parent-scroll verification after asynchronous iframe height changes."""

from __future__ import annotations

import json
import tempfile
from contextlib import closing
from pathlib import Path

from playwright.sync_api import sync_playwright
from product_redesign_training_browser import RedesignCheck
from strength_workbench_browser_check import isolated_app

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/product_redesign/training"


def main():
    with tempfile.TemporaryDirectory(prefix="training-scroll-") as temp:
        folder = Path(temp)
        database = folder / ".local/healthzip.sqlite3"
        database.parent.mkdir()
        with closing(Repository(database)) as repo:
            svc = TrainingService(repo)
            session = svc.start_session("合成长列表定位")
            for _ in range(30):
                item = svc.add_exercise(session["id"], "psa.ex.barbell_bench_press", {})
                svc.add_set(item["id"], {})
        with isolated_app(ROOT, folder) as base, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 390, "height": 430})
            page.goto(base + "/?workspace=strength")
            check = RedesignCheck(page, database, OUT)
            check.wait(lambda: check.testid("strength-home").is_visible(), timeout=60000)
            check.testid("continue-training").click()
            check.wait(lambda: check.testid("training-workbench").is_visible())
            check.idle()
            check.click("open-catalog")
            check.click("close-catalog")
            check.wait(lambda: 0 <= check.action("open-catalog").bounding_box()["y"] < 430)
            cancel_bounds = check.action("open-catalog").bounding_box()
            check.click("add-set", item["id"])
            latest = check.active()["exercises"][-1]["sets"][-1]["set_uuid"]
            field = check.row(latest).locator('[data-field="load_value"]')
            check.wait(lambda: 0 <= field.bounding_box()["y"] < 430)
            assert field.evaluate("e=>e===document.activeElement")
            result = {"data": "synthetic_only", "exercises": 30, "viewport": {"width": 390, "height": 430}, "checks": {"cancel_returns_to_original_add_entry": True, "add_set_waits_for_parent_height_then_focuses_visible_field": True}, "cancel_bounds": cancel_bounds, "added_field_bounds": field.bounding_box(), "physical_keyboard_tested": False}
            (OUT / "training-scroll-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps(result, ensure_ascii=False))
            browser.close()


if __name__ == "__main__":
    main()
