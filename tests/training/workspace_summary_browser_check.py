"""Capture the real app's body summaries and shared navigation offline.

Run with the same development Playwright/Chromium prerequisites as the strength
browser check. Every record and screenshot is synthetic; production is unused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright
from strength_workbench_browser_check import BrowserCheck, isolated_app

from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.training.service import TrainingService


def create_body_fixture(database):
    database.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    recent = now - timedelta(minutes=1)
    earlier = now.replace(day=1, hour=10, minute=0, second=0, microsecond=0)
    if earlier >= recent:
        earlier = recent - timedelta(days=1)
    root = Element("HealthData")
    for at, heart, hrv, hours in ((earlier, 70, 30, 6), (recent, 60, 50, 7.5)):
        for kind, value, unit, start in (
            ("HKQuantityTypeIdentifierRestingHeartRate", heart, "count/min", at),
            ("HKQuantityTypeIdentifierHeartRateVariabilitySDNN", hrv, "ms", at),
            ("HKCategoryTypeIdentifierSleepAnalysis", "HKCategoryValueSleepAnalysisAsleepCore",
             None, at - timedelta(hours=hours)),
        ):
            attributes = {
                "type": kind, "sourceName": "合成摘要手表", "sourceVersion": "synthetic-1",
                "device": "synthetic-summary-device", "value": str(value),
                "startDate": start.strftime("%Y-%m-%d %H:%M:%S %z"),
                "endDate": at.strftime("%Y-%m-%d %H:%M:%S %z"),
                "creationDate": at.strftime("%Y-%m-%d %H:%M:%S %z"),
            }
            if unit:
                attributes["unit"] = unit
            SubElement(root, "Record", attributes)
    archive = database.parent / "synthetic-body-summary.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as zipped:
        zipped.writestr("export.xml", tostring(root))
    with closing(Repository(database)) as repo:
        imported = import_apple_zip(archive, repo)
        assert imported.status == "completed" and imported.records_inserted == 6
        TrainingService(repo)
    return {"recent": recent.isoformat(), "earlier": earlier.isoformat()}


def training_counts(database):
    with closing(Repository(database)) as repo:
        return {name: repo.one(f"SELECT count(*) FROM {name}")[0]
                for name in ("strength_session", "strength_set", "training_event", "analysis_run", "workflow_run")}


def settled(page):
    page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=20000)
    page.wait_for_timeout(350)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    sources = ["app.py", "src/healthzip/analytics/workspace_summary.py",
               "src/healthzip/ui/workspace_summary.py", "src/healthzip/ui/body_pages.py",
               "src/healthzip/ui/training_workbench.py", "src/healthzip/ui/training_bridge.py",
               "src/healthzip/ui/strength_component/workbench.js",
               "src/healthzip/ui/strength_component/workbench.css"]
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources}
    report = {"data": "synthetic_only", "entrypoint": "app.py", "tested_source_sha256": hashes,
              "checked_at": datetime.now(timezone.utc).isoformat(), "results": {}}
    external, errors = [], []
    with tempfile.TemporaryDirectory(prefix="synthetic-workspace-summary-") as temporary:
        folder = Path(temporary)
        database = folder / ".local/healthzip.sqlite3"
        report["fixture"] = create_body_fixture(database)
        before = training_counts(database)
        with isolated_app(root, folder) as base, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
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
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base)
            page.get_by_role("heading", name="训练与健康记录", exact=True).wait_for()
            for workspace in ("睡眠", "心率 / HRV", "力量"):
                page.get_by_role("radio", name=workspace, exact=True).locator("xpath=ancestor::label[1]").click()
                if workspace != "力量":
                    heading = "睡眠记录" if workspace == "睡眠" else "心率与 HRV 记录"
                    page.get_by_role("heading", name=heading, exact=True).wait_for()
                summary = page.get_by_text("当前数据分析", exact=True)
                summary.wait_for()
                # The actual st.radio remains in the outer app's main region.
                assert page.get_by_test_id("stMain").get_by_role("radio", name="力量", exact=True).is_visible()
                if workspace != "力量":
                    page.get_by_text("合成摘要手表", exact=False).first.wait_for()
                    for label, key in (("本周", "week"), ("本月", "month")):
                        page.get_by_role("radio", name=label, exact=True).locator("xpath=ancestor::label[1]").click()
                        page.get_by_text(label + "：", exact=False).first.wait_for()
                        settled(page)
                        text = page.get_by_test_id("stMain").inner_text()
                        assert "平均" in text and "合成摘要手表" in text
                        assert "synthetic-summary-device" not in text
                        dimensions = page.evaluate("() => ({viewport:innerWidth, document:document.documentElement.scrollWidth})")
                        assert dimensions["document"] <= dimensions["viewport"], dimensions
                        stem = "sleep" if workspace == "睡眠" else "heart"
                        if workspace == "睡眠":
                            page.screenshot(path=str(output / f"{stem}-{key}-summary-mobile.png"))
                        report["results"][f"{stem}_{key}"] = {"status": "passed", "outer_width": dimensions}
                else:
                    check = BrowserCheck(page, database, output)
                    check.wait(lambda: check.testid("strength-home").is_visible(), "strength home after main navigation")
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    check.wait(lambda: check.frame.evaluate("innerWidth") >= 760, "desktop component resize")
                    settled(page)
                    page.screenshot(path=str(output / "strength-unified-navigation-desktop.png"))
                    report["results"]["strength_navigation"] = {"status": "passed", "main_workspace_radio": True}
            after = training_counts(database)
            assert before == after, {"before": before, "after": after}
            assert not errors and not external, {"page_errors": errors, "external_requests": external}
            assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == value
                       for name, value in hashes.items()), "Product source changed during browser run"
            report.update(status="passed", page_errors=errors, external_requests=external,
                          training_counts_before=before, training_counts_after=after,
                          sources_unchanged_during_run=True, real_iphone_keyboard="not_verified")
            (output / "summary-browser-results.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            context.close()
            browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
