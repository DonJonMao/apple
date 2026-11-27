"""Actual DOM and full-app calendar acceptance; all records are synthetic.

The before mode deliberately fails on the shipping calendar defect and keeps
its screenshot/receipt. The after mode uses the same assertions plus real
TrainingService records and durable edit/navigation checks.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import re
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests/training"))

from playwright.sync_api import sync_playwright  # noqa: E402
from product_redesign_training_browser import RedesignCheck  # noqa: E402
from strength_workbench_browser_check import (  # noqa: E402
    TRANSPORT_CONTROL,
    isolated_app,
)

from healthzip.db.repository import Repository  # noqa: E402
from healthzip.training.service import TrainingService  # noqa: E402


def source_identity():
    names = ["src/healthzip/ui/strength_component/workbench.js",
             "src/healthzip/ui/strength_component/workbench.css",
             "src/healthzip/ui/training_bridge.py",
             "src/healthzip/ui/training_workbench.py",
             "src/healthzip/training/service.py", "tools/followup_calendar_browser.py"]
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in names if (ROOT / name).exists()}


def fixture(database):
    today = datetime.now(ZoneInfo("Asia/Shanghai"))
    rows = []
    with closing(Repository(database)) as repo:
        svc = TrainingService(repo)
        for index, day in enumerate((3, 11, 23), 1):
            at = today.replace(day=day, hour=9, minute=0, second=0, microsecond=0)
            session = svc.start_session(f"合成日历第 {index} 场", started_at=at.isoformat())
            exercise = svc.add_exercise(session["id"], "psa.ex.barbell_bench_press", {})
            set_ids = []
            for number in range(index):
                row = svc.add_set(exercise["id"], {
                    "completion_state": "completed", "load_value": 30 + index,
                    "load_unit": "kg", "reps": 8 + number, "rir": 0,
                    "ended_at": (at + timedelta(minutes=number + 1)).isoformat(),
                })
                set_ids.append(row["set_uuid"])
            svc.end_session(session["id"], ended_at=(at + timedelta(minutes=20)).isoformat())
            rows.append({"date": at.date().isoformat(), "session_id": session["id"],
                         "name": session["name"], "completed_sets": index,
                         "set_ids": set_ids})
    return {"today": today.date().isoformat(), "month": today.strftime("%Y-%m"), "rows": rows}


class CalendarCheck(RedesignCheck):
    def dates(self, stage, month=None):
        title = self.frame.locator(".calendar-heading h2").inner_text()
        year, number = map(int, re.findall(r"\d+", title))
        actual_month = f"{year}-{number:02}"
        if month:
            assert actual_month == month, (actual_month, month)
        days = calendar.monthrange(year, number)[1]
        expected = [f"{actual_month}-{d:02}" for d in range(1, days + 1)]
        result = self.frame.locator(".calendar-grid").evaluate("""grid => ({
            dates:[...grid.querySelectorAll('[data-date]')].map(e=>e.dataset.date),
            labels:[...grid.querySelectorAll('[data-date] > span:first-child')].map(e=>e.textContent),
            weekdays:[...grid.querySelectorAll('.weekday')].map(e=>e.textContent),
            leading:[...grid.children].slice(7).findIndex(e=>e.matches('[data-date]')),
            selected:[...grid.querySelectorAll('[aria-pressed=true]')].map(e=>e.dataset.date),
            positions:[...grid.querySelectorAll('[data-date]')].map(e=>({date:e.dataset.date,
                x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,
                width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}))
        })""")
        self.results[stage] = {"month": actual_month, **result}
        assert result["dates"] == expected, result
        assert result["labels"] == [str(d) for d in range(1, days + 1)]
        assert result["weekdays"] == list("一二三四五六日")
        assert result["leading"] == calendar.monthrange(year, number)[0]
        assert all(p["width"] > 0 and p["height"] > 0 for p in result["positions"])
        assert all(a["y"] <= b["y"] and (a["y"] < b["y"] or a["x"] < b["x"])
                   for a, b in zip(result["positions"], result["positions"][1:]))
        self.keys(stage)
        return result

    def keys(self, stage):
        source = (ROOT / "src/healthzip/ui/strength_component/workbench.js").read_text()
        function = source[source.index("  function nodeKey("):source.index("  function patchNode(")]
        duplicate = self.frame.evaluate("""source => {
            const key = new Function(source+';return nodeKey;')();
            return [...document.querySelectorAll('#app *')].flatMap(parent=>{
                const keys=[...parent.children].map(key).filter(Boolean);
                return keys.filter((value,index)=>keys.indexOf(value)!==index)
                    .map(value=>({parent:parent.className,key:value}));
            });
        }""", function)
        self.results[stage]["duplicate_sibling_keys"] = duplicate
        assert not duplicate, duplicate

    def current_month(self):
        year, month = map(int, re.findall(r"\d+", self.frame.locator(".calendar-heading h2").inner_text()))
        return year * 12 + month - 1

    def month(self, month):
        year, number = map(int, month.split("-"))
        target = year * 12 + number - 1
        while self.current_month() != target:
            self.click("next-month" if self.current_month() < target else "prev-month")
        self.dates("month_" + month, month)

    def run_calendar(self, manifest, before):
        # Capturing before the first assertion preserves even an initial-render collapse.
        self.screenshot("calendar-initial-390.png")
        self.dates("initial", manifest["month"])
        day = self.frame.locator(f'[data-date="{manifest["today"]}"]')
        day.focus()
        self.frame.evaluate("window.__calendarFocus = document.activeElement")
        # Native keyboard activation exercises the real calendar command and receipt.
        day.press("Enter")
        self.idle()
        self.screenshot("calendar-rerender-390.png")
        self.dates("same_month_rerender", manifest["month"])
        assert self.frame.evaluate("window.__calendarFocus===document.activeElement && window.__calendarFocus.isConnected")
        if before:
            return
        self.passed("calendar_keyboard_focus_retained")
        for width in (390, 1440):
            self.page.set_viewport_size({"width": width, "height": 900 if width > 600 else 844})
            for row in manifest["rows"]:
                self.frame.locator(f'[data-date="{row["date"]}"]').click()
                self.idle()
                state = self.dates(f"date_{width}_{row['date']}", manifest["month"])
                assert state["selected"] == [row["date"]]
                card = self.testid(f"session-card-{row['session_id']}")
                assert row["name"] in card.inner_text()
                assert f"{row['completed_sets']} 组完成" in card.inner_text()
                card.locator('[data-action="open-session"]').click()
                self.idle()
                self.wait(lambda: self.testid("training-detail").is_visible())
                assert self.frame.locator(".topbar h1").inner_text() == row["name"]
                ids = self.frame.locator("[data-set-id]").evaluate_all("es=>es.map(e=>e.dataset.setId)")
                assert ids == row["set_ids"], (ids, row)
                assert self.frame.locator('[data-state-label="已完成"]').count() == row["completed_sets"]
                self.results[f"opened_{width}_{row['date']}"] = {"status": "passed", **row, "rendered_set_ids": ids}
                self.screenshot(f"training-{row['date']}-{width}.png")
                self.click("home")
                self.dates(f"back_{width}_{row['date']}", manifest["month"])
            self.screenshot(f"calendar-complete-{width}.png")
        # Concrete calendar months span every month length and different first weekdays.
        for month in ("2026-02", "2024-02", "2026-11", "2026-12"):
            self.month(month)
            self.click("next-month")
            self.click("prev-month")
            self.dates("repeat_" + month, month)
            self.screenshot("calendar-" + month + ".png")
        self.click("today")
        self.dates("today", manifest["month"])
        self.page.reload()
        self.wait(lambda: self.testid("strength-home").is_visible(), timeout=60000)
        self.dates("refresh", manifest["month"])
        self.geometry("calendar")
        self.click("open-start")
        session = self.active()
        self.choose("平板", "psa.ex.barbell_bench_press")
        first = self.active()["exercises"][0]["sets"][0]["set_uuid"]
        self.fill_row(first, load="32.5", quantity="8", rir="0")
        self.choose("侧平举", "psa.ex.dumbbell_lateral_raise")
        second = self.active()["exercises"][1]["sets"][0]["set_uuid"]
        self.fill_row(second, load="5", quantity="10", rir="0")
        self.page.reload()
        self.wait(lambda: self.testid("training-workbench").is_visible(), timeout=60000)
        assert self.active()["id"] == session["id"]
        assert self.row(first).locator('[data-field="load_value"]').input_value() == "32.5"
        assert self.row(first).locator('[data-field="rir"]').input_value() == "0"
        self.click("open-catalog")
        self.results["catalog_controls"] = {}
        self.keys("catalog_controls")
        assert self.action("close-catalog").count() == 2
        self.frame.get_by_label("搜索动作").fill("平板")
        self.page.wait_for_timeout(250)
        self.keys("catalog_controls")
        assert self.action("close-catalog").count() == 2
        self.click("close-catalog")
        self.delay_next_save_receipt(800)
        self.row(first).locator('[data-action="complete-set"]').click()
        field = self.row(second).locator('[data-field="reps"]')
        field.fill("11")
        field.focus()
        self.frame.evaluate("window.__inputFocus=document.activeElement")
        self.idle()
        assert self.frame.evaluate("window.__inputFocus===document.activeElement && window.__inputFocus.isConnected")
        assert field.input_value() == "11"
        self.complete_row(second)
        self.click("home")
        self.dates("active_return_calendar", manifest["month"])
        self.click("open-session", session["id"])
        self.click("open-finish")
        self.click("confirm-end")
        self.wait(lambda: self.testid("training-detail").is_visible())
        saved = self.service_read(lambda svc: svc.get_session(session["id"]))
        assert saved["session_status"] == "completed" and saved["completed_sets"] == 2
        assert [item["sets"][0]["rir"] for item in saved["exercises"]] == [0, 0]
        assert [item["sets"][0]["reps"] for item in saved["exercises"]] == [8, 11]
        self.passed("training_input_navigation_receipt_and_end", session_id=session["id"],
                    rir=[0, 0], reps=[8, 11], focus_preserved=True, refresh_draft=True)
        self.screenshot("new-training-ended.png")
        self.click("home")
        self.dates("ended_return_calendar", manifest["month"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--before", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    out = args.output.resolve()
    hashes = source_identity()
    with tempfile.TemporaryDirectory(prefix="followup-calendar-") as temp:
        folder = Path(temp)
        database = folder / ".local/healthzip.sqlite3"
        database.parent.mkdir()
        manifest = fixture(database)
        with isolated_app(ROOT, folder) as base, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(viewport={"width": 390, "height": 844})
            context.add_init_script(TRANSPORT_CONTROL)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/?workspace=strength")
            check = CalendarCheck(page, database, out)
            completed = False
            failure = None
            try:
                check.wait(lambda: check.testid("strength-home").is_visible(), timeout=60000)
                check.run_calendar(manifest, args.before)
                assert not errors, errors
                completed = True
            except Exception as exc:
                failure = str(exc)
                page.screenshot(path=str(out / "failure.png"), full_page=True)
                raise
            finally:
                (out / "browser.json").write_text(json.dumps({
                    "synthetic_only": True, "fixture": manifest, "completed": completed,
                    "failure": failure, "results": check.results, "browser_errors": errors,
                    "source_before": hashes, "source_after": source_identity(),
                    "physical_safari_tested": False,
                }, ensure_ascii=False, indent=2))
                (out / "streamlit.log").write_bytes((folder / "synthetic-streamlit.log").read_bytes())
                browser.close()


if __name__ == "__main__":
    main()
