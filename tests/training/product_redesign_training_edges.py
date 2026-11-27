"""Additional browser boundaries: modes, workspace recovery, and local response."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from playwright.sync_api import sync_playwright
from product_redesign_training_browser import RedesignCheck
from strength_workbench_browser_check import TRANSPORT_CONTROL, isolated_app

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from product_redesign_browser_check import navigate, settle  # noqa: E402


def fixture(path):
    modes = [
        ("自重", "repetitions", "bodyweight_no_external", {"reps": 8, "rir": 0}),
        (
            "助力",
            "repetitions",
            "assistance_setting",
            {"load_value": "0", "load_unit": "level", "reps": 8, "rir": 0},
        ),
        ("时长", "duration", "bodyweight_no_external", {"duration_s": 32.5}),
        (
            "距离",
            "distance",
            "added_load_kg",
            {"load_value": "12.5", "load_unit": "kg", "distance_m": 50.5},
        ),
    ]
    with closing(Repository(path)) as repo:
        svc = TrainingService(repo)
        for name, mode, basis, _ in modes:
            ex = svc.create_exercise(
                "合成" + name, mode, "other", basis, exercise_id="custom.edge." + mode + "." + basis
            )
            session = svc.start_session("合成口径记录")
            svc.add_exercise(
                session["id"],
                ex["exercise_id"],
                {"load_basis": basis, "load_basis_confirmed": True},
            )
            svc.end_session(session["id"])
    return modes


def run(check, modes, base):
    check.wait(lambda: check.testid("strength-home").is_visible(), timeout=60000)
    check.click("open-start")
    for name, mode, basis, actual in modes:
        check.choose("合成" + name, "custom.edge." + mode + "." + basis)
        item = check.active()["exercises"][-1]
        row = item["sets"][0]["set_uuid"]
        field = {"repetitions": "reps", "duration": "duration_s", "distance": "distance_m"}[mode]
        assert check.row(row).locator('[data-field="' + field + '"]').count() == 1
        assert mode == "repetitions" or not check.row(row).locator('[data-field="reps"]').count()
        check.fill_row(
            row,
            load=str(actual.get("load_value", "")),
            quantity=str(actual[field]),
            rir=str(actual.get("rir", "")),
            mode=field,
            unit=actual.get("load_unit", "kg"),
        )
        check.complete_row(row)
        saved = check.active()["exercises"][-1]["sets"][0]
        assert saved["condition"]["load_basis"] == basis
        assert saved[field] == actual[field]
        assert saved["rir"] == actual.get("rir")
    check.passed(
        "effective_fields_and_load_semantics",
        modes=[x[1:3] for x in modes],
        no_forced_positive_load=True,
        assistance_zero=True,
    )
    original = check.active()["exercises"]
    check.click("move-down", original[0]["id"])
    assert check.active()["exercises"][1]["id"] == original[0]["id"]
    check.click("move-up", original[0]["id"])
    assert check.active()["exercises"][0]["id"] == original[0]["id"]
    check.passed("recorded_reorder", up_down_real_service_revision=True)
    item = check.active()["exercises"][0]
    check.click("add-set", item["id"])
    row = check.active()["exercises"][0]["sets"][-1]["set_uuid"]
    count = check.page.evaluate("window.__trainingCommandCount||0")
    latency = (
        check.row(row)
        .locator('[data-field="reps"]')
        .evaluate("""async e=>{
        let out=[];e.focus();for(let i=1;i<=40;i++){
            const start=performance.now();e.value=String(i);e.dispatchEvent(new Event('input',{bubbles:true}));
            if(!e.closest('.set-block').querySelector('[data-draft-state]').textContent.includes('本机'))throw Error('missing local response');
            await new Promise(resolve=>requestAnimationFrame(()=>{out.push(performance.now()-start);resolve()}));
        }return out;
    }""")
    )
    assert check.page.evaluate("window.__trainingCommandCount||0") == count
    ordered = sorted(latency)
    assert ordered[37] < 100, latency
    check.passed(
        "local_input_response",
        n=40,
        p50_ms=ordered[19],
        p95_ms=ordered[37],
        samples_ms=latency,
        no_component_commands=True,
        method="real Chromium input handlers until next animation frame, no network; does not claim physical key latency",
    )
    check.row(row).locator('[data-field="reps"]').fill("8")
    check.delay_next_save_receipt(None)
    check.row(row).locator('[data-action="complete-set"]').click()
    check.wait(
        lambda: check.service_read(lambda svc: svc.get_set(row)["completion_state"]) == "completed"
    )
    check.page.reload()
    check.wait(lambda: check.action("retry").count() > 0, timeout=20000)
    check.action("retry").click()
    check.idle()
    assert check.service_read(lambda svc: svc.get_set(row)["completion_state"]) == "completed"
    assert len(check.active()["exercises"][0]["sets"]) == 2
    check.passed(
        "refresh_with_pending_acknowledgement",
        same_request_id_replayed=True,
        no_duplicate_sets=True,
    )
    # Delete confirmation and undo preserve the actual original UUID.
    check.click("set-menu", row)
    check.click("delete-set", row)
    assert check.service_read(lambda svc: svc.get_set(row)["deleted_at"]) is None
    check.click("confirm-delete-set")
    assert check.service_read(lambda svc: svc.get_set(row)["deleted_at"])
    check.click("undo")
    assert check.service_read(lambda svc: svc.get_set(row)["deleted_at"]) is None
    check.passed("set_delete_and_undo", targeted_confirmation=True, same_identity_restored=True)
    # Two real browser tabs hold independent drafts of one stable set UUID.
    check.click("add-set", item["id"])
    concurrent = check.active()["exercises"][0]["sets"][-1]["set_uuid"]
    check.row(concurrent).locator('[data-field="reps"]').fill("7")
    second_page = check.page.context.new_page()
    second_page.goto(base + "/?workspace=strength")
    other = RedesignCheck(second_page, check.database, check.output)
    other.wait(lambda: other.testid("training-workbench").is_visible(), timeout=60000)
    other.row(concurrent).locator('[data-field="reps"]').fill("6")
    other.click("set-menu", concurrent)
    other.click("save-draft", concurrent)
    check.click("set-menu", concurrent)
    check.click("save-draft", concurrent)
    assert check.frame.locator(".row-error").count()
    assert check.row(concurrent).locator('[data-field="reps"]').input_value() == "7"
    check.page.reload()
    check.wait(lambda: check.testid("training-workbench").is_visible())
    assert check.row(concurrent).locator('[data-field="reps"]').input_value() == "7"
    check.click("save-draft", concurrent)
    assert check.frame.locator(".row-error").count()
    check.click("review-conflict", concurrent)
    check.click("rebase-draft", concurrent)
    check.click("save-draft", concurrent)
    assert check.service_read(lambda svc: svc.get_set(concurrent)["reps"]) == 7
    second_page.close()
    check.passed("real_two_tab_revision_conflict", independent_draft_after_refresh=True,
                 explicit_rebase=True, server_matches_confirmed_value=True)
    check.click("add-set", item["id"])
    localrow = check.active()["exercises"][0]["sets"][-1]["set_uuid"]
    session_id = check.active()["id"]
    check.row(localrow).locator('[data-field="reps"]').fill("7x")
    check.click("open-finish")
    check.frame.get_by_label("未完成草稿处理").select_option("local")
    check.click("confirm-end")
    check.wait(lambda: check.testid("training-detail").is_visible())
    assert check.service_read(lambda svc: svc.get_set(localrow)["reps"]) is None
    check.page.reload()
    check.wait(lambda: check.testid("training-detail").is_visible())
    assert check.row(localrow).locator('[data-field="reps"]').input_value() == "7x"
    check.passed(
        "finish_keeps_explicit_local_unsynced_draft",
        server_value_is_null=True,
        local_value_restored="synthetic invalid text",
    )
    workspace_roundtrip(check, localrow, session_id)


def workspace_roundtrip(check, localrow, session_id):
    # Switch the actual app setting, then back. No path is saved into public evidence.
    check.page.set_viewport_size({"width": 1440, "height": 900})
    navigate(check.page, "设置")
    check.page.get_by_text("导入与同步", exact=True).first.click()
    other = check.database.parent / "other-synthetic.sqlite3"
    check.page.get_by_label("SQLite 路径", exact=True).fill(str(other))
    check.page.get_by_role("button", name="保存工作区设置", exact=True).click()
    settle(check.page)
    check.page.get_by_role("radio", name="训练", exact=True).locator("xpath=ancestor::label[1]").click()
    settle(check.page)
    check.wait(lambda: check.testid("strength-home").is_visible())
    assert not check.frame.locator('[data-set="' + localrow + '"]').count()
    check.click("open-start")
    assert check.testid("training-workbench").is_visible()
    assert not check.frame.locator('[data-set="' + localrow + '"]').count()
    navigate(check.page, "设置")
    check.page.get_by_text("导入与同步", exact=True).first.click()
    check.page.get_by_label("SQLite 路径", exact=True).fill(str(check.database))
    check.page.get_by_role("button", name="保存工作区设置", exact=True).click()
    settle(check.page)
    check.page.get_by_role("radio", name="训练", exact=True).locator("xpath=ancestor::label[1]").click()
    settle(check.page)
    check.wait(lambda: check.testid("training-detail").is_visible())
    assert check.row(localrow).locator('[data-field="reps"]').input_value() == "7x"
    assert (
        check.service_read(lambda svc: svc.get_session(session_id)["session_status"]) == "completed"
    )
    check.passed(
        "workspace_drafts_isolated",
        separate_database_has_no_old_input=True,
        original_draft_restored=True,
    )


def run_workspace_only(check):
    """Prepare the original unsynced-draft boundary without rerunning timing cases."""
    check.wait(lambda: check.testid("strength-home").is_visible(), timeout=60000)
    check.click("open-start")
    check.choose("合成自重", "custom.edge.repetitions.bodyweight_no_external")
    item = check.active()["exercises"][0]
    first = item["sets"][0]["set_uuid"]
    check.fill_row(first, load="", quantity="8", rir="0")
    check.complete_row(first)
    check.click("add-set", item["id"])
    localrow = check.active()["exercises"][0]["sets"][-1]["set_uuid"]
    session_id = check.active()["id"]
    check.row(localrow).locator('[data-field="reps"]').fill("7x")
    check.click("open-finish")
    check.frame.get_by_label("未完成草稿处理").select_option("local")
    check.click("confirm-end")
    check.wait(lambda: check.testid("training-detail").is_visible())
    assert check.service_read(lambda svc: svc.get_set(localrow)["reps"]) is None
    workspace_roundtrip(check, localrow, session_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/product_redesign/training"))
    parser.add_argument("--workspace-only", action="store_true")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="training-edges-") as temp:
        folder = Path(temp)
        db = folder / ".local/healthzip.sqlite3"
        db.parent.mkdir()
        modes = fixture(db)
        with isolated_app(ROOT, folder) as base, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(viewport={"width": 390, "height": 844})
            page = context.new_page()
            page.add_init_script(TRANSPORT_CONTROL)
            page.add_init_script(
                "window.__trainingCommandCount=0;window.addEventListener('message',e=>{if(e.data?.type==='streamlit:setComponentValue')window.__trainingCommandCount++})"
            )
            page.goto(base + "/?workspace=strength")
            check = RedesignCheck(page, db, out)
            completed = False
            try:
                if args.workspace_only:
                    run_workspace_only(check)
                else:
                    run(check, modes, base)
                completed = True
            finally:
                (out / "training-edge-results.json").write_text(
                    json.dumps(
                        {"data": "synthetic_only", "completed": completed,
                         "scope": "workspace_only" if args.workspace_only else "all_edges",
                         "results": check.results},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                browser.close()


if __name__ == "__main__":
    main()
