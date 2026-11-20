"""Actual old unknown catalog entries are directly usable after upgrade."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from contextlib import closing
from pathlib import Path

from playwright.sync_api import sync_playwright
from product_redesign_training_browser import RedesignCheck
from strength_workbench_browser_check import isolated_app
from test_catalog_recording_defaults import (
    LEGACY_ID,
    SECOND_ID,
    install_legacy_catalog,
    mark_previous_initialization,
)
from test_v14_catalog import snapshot, source

from healthzip.db.repository import Repository
from healthzip.training.catalog_import import DEFAULT_RECORDING_MODE_BASIS, publish_snapshot

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/catalog_recording_defaults"))
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="catalog-default-browser-") as temp:
        folder = Path(temp)
        database = folder / ".local/healthzip.sqlite3"
        database.parent.mkdir()
        new_identity = "catalog.wger.synthetic-new-default"
        with closing(Repository(database)) as repo:
            install_legacy_catalog(repo)
            publish_snapshot(repo, snapshot(folder, [source(name="Synthetic New Catalog", uuid="synthetic-new-default")]))
            # Publishing replaces the source inventory. Keep the synthetic
            # installed rows active, exactly as before an application upgrade.
            repo.conn.execute("UPDATE exercise_catalog SET active=1 WHERE exercise_id IN (?,?,?,?)",
                (LEGACY_ID, SECOND_ID, "catalog.wger.synthetic-duration", "catalog.wger.synthetic-distance"))
            repo.conn.commit()
            mark_previous_initialization(repo)
            assert all(json.loads(row[0])["recording_mode"] == "unknown" for row in repo.conn.execute(
                "SELECT definition_json FROM exercise_catalog WHERE exercise_id IN (?,?)", (LEGACY_ID, SECOND_ID)))
        with isolated_app(ROOT, folder) as base, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/?workspace=strength")
            check = RedesignCheck(page, database, output)
            check.wait(lambda: check.testid("strength-home").is_visible(), timeout=60000)
            check.click("open-start")
            session_id = check.active()["id"]
            check.choose("合成旧目录划船", LEGACY_ID)
            first = check.active()["exercises"][0]
            row = first["sets"][0]["set_uuid"]
            assert first["definition_version"] == 2
            assert first["exercise"]["recording_mode"] == "repetitions"
            assert first["exercise"]["mode_basis"] == DEFAULT_RECORDING_MODE_BASIS
            assert first["condition"]["load_basis"] == "unknown"
            assert not first["condition"].get("load_basis_confirmed")
            check.fill_row(row, load="32.5", quantity="8", rir="0")
            check.choose("合成旧目录推举", SECOND_ID)
            assert check.active()["id"] == session_id
            for field, value in (("load_value", "32.5"), ("reps", "8"), ("rir", "0")):
                assert check.row(row).locator(f'[data-field="{field}"]').input_value() == value
            check.passed("installed_unknown_catalog_add_input_add", original_mode="unknown",
                current_mode="repetitions", current_definition_version=2, same_session=True,
                decimal_reps_and_zero_preserved=True, load_basis_still_unknown=True)
            check.complete_row(row)
            actual = check.service_read(lambda svc: svc.get_set(row))
            assert (actual["load_value"], actual["reps"], actual["rir"]) == ("32.5", 8, 0)
            assert actual["completion_state"] == "completed" and actual["load_basis"] == "unknown"
            check.passed("actual_save_after_default", no_personal_definition_step=True,
                         actual_load="32.5", actual_reps=8, actual_rir=0)
            check.choose("Synthetic New Catalog", new_identity)
            latest = check.active()["exercises"][-1]
            assert latest["definition_version"] == 1
            assert latest["exercise"]["recording_mode"] == "repetitions"
            check.passed("newly_imported_catalog_direct_add", default_basis=latest["exercise"]["mode_basis"])
            for query, identity, field in (("合成计时目录", "catalog.wger.synthetic-duration", "duration_s"),
                                           ("合成距离目录", "catalog.wger.synthetic-distance", "distance_m")):
                check.choose(query, identity)
                latest = check.active()["exercises"][-1]
                original_row = latest["sets"][0]["set_uuid"]
                assert latest["definition_version"] == 1
                assert check.row(original_row).locator(f'[data-field="{field}"]').count() == 1
                assert check.row(original_row).locator('[data-field="reps"]').count() == 0
            check.passed("existing_duration_distance_unchanged", effective_original_fields=True)
            assert not errors
            assert "尚未核对" not in check.frame.locator('[data-testid="operation-status"]').inner_text()
            check.frame.locator(f'[data-testid="exercise-card-{first["id"]}"]').screenshot(path=str(output / "default-repetitions-mobile.png"))
            source_paths = ["src/healthzip/training/catalog_import.py", "src/healthzip/training/service.py",
                            "src/healthzip/training/catalog.schema.json", "src/healthzip/ui/strength_component/workbench.js"]
            report = {"data": "synthetic_only", "kind": "real_chromium_full_streamlit_app",
                "browser": browser.version, "results": check.results, "browser_errors": errors,
                "physical_safari_tested": False,
                "source_hashes": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_paths}}
            (output / "browser-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            browser.close()


if __name__ == "__main__":
    main()
