"""Exercise progress, actual goal-stop and within-session rest evidence in the full app."""
import json
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright
from product_redesign_training_browser import RedesignCheck
from strength_workbench_browser_check import isolated_app

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService


def fixture(path):
    with closing(Repository(path)) as repo:
        svc = TrainingService(repo)
        station = svc.create_equipment("合成史密斯架", svc.get_exercise("psa.ex.smith_incline_press")["equipment_type"])
        condition = {"equipment_instance_id": station["id"], "load_basis": "plates_per_side_kg",
                     "load_basis_confirmed": True, "side": "bilateral", "repetition_semantics": "full_repetitions",
                     "rom_protocol": "固定活动范围", "settings": {}, "settings_confirmed": True}
        for offset, count in ((4, 10), (1, 8)):
            start = datetime.now(timezone.utc) - timedelta(days=offset)
            session = svc.start_session(f"合成推举训练 · {offset} 天前", started_at=start.isoformat())
            item = svc.add_exercise(session["id"], "psa.ex.smith_incline_press", condition)
            for index in range(2):
                end = start + timedelta(minutes=2 + 4 * index)
                svc.add_set(item["id"], {"load_value": 30, "load_unit": "kg", "completion_state": "completed",
                    "rir": None, "reps": 10 if index == 0 else count,
                    "stop_reason": "plan_target" if index == 0 else "unknown",
                    "rest_recorded_s": 90 if offset == 1 and index else 180, "rest_recorded_method": "stopwatch",
                    "started_at": (end - timedelta(seconds=30)).isoformat(), "ended_at": end.isoformat()})
            svc.end_session(session["id"], ended_at=(start + timedelta(minutes=15)).isoformat())
        return session["id"]


def main():
    root = Path(__file__).resolve().parents[2]
    out = root / "artifacts/master_redesign/training"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="training-progress-") as tmp:
        folder = Path(tmp)
        db = folder / ".local/healthzip.sqlite3"
        db.parent.mkdir()
        identity = fixture(db)
        with isolated_app(root, folder) as base, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(base + "/?workspace=strength")
            check = RedesignCheck(page, db, out)
            check.wait(lambda: check.testid("strength-home").is_visible(), timeout=60000)
            stored = check.service_read(lambda svc: svc.get_session(identity))
            page.get_by_role("radio", name="动作进展", exact=True).locator("xpath=ancestor::label[1]").click()
            page.get_by_text("且均记录达到目标后停止", exact=False).wait_for()
            page.get_by_text("180 → 90 秒", exact=False).wait_for()
            page.get_by_text("按上次比较场次的休息方式计时", exact=False).wait_for()
            page.get_by_role("heading", name="动作进展").scroll_into_view_if_needed()
            page.screenshot(path=str(out / "exercise-progress-mobile.png"))
            page.get_by_role("button", name="打开本次原始训练").click()
            check.wait(lambda: check.testid("training-detail").is_visible(), timeout=60000)
            assert check.row(stored["sets"][0]["set_uuid"]).locator('[data-field="rir"]').input_value() == ""
            check.passed("D14_D15", load_per_side_kg=30, first_reps=[10, 10], later_reps=[10, 8],
                         later_rest_seconds=[180, 90], actual_rir=None, returned_to_original_record=True)
            (out / "exercise-progress.json").write_text(json.dumps(check.results, indent=2))
            browser.close()


if __name__ == "__main__":
    main()
