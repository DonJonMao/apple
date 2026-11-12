"""Explicit Chromium UI, local REST sync and retry checks for private definitions."""

from __future__ import annotations

import argparse
import json
import tempfile
import threading
from contextlib import closing
from pathlib import Path

from playwright.sync_api import sync_playwright

from healthzip.db.repository import Repository
from healthzip.sync_server import HealthZipHTTPServer
from healthzip.training.offline import recorder_html
from healthzip.training.service import TrainingService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    requests, errors, report = [], [], {}
    unknown_id = "catalog.wger.synthetic-offline-unknown"
    with tempfile.TemporaryDirectory(prefix="synthetic-", dir=output) as temporary:
        database = Path(temporary) / "synthetic.sqlite3"
        repo = Repository(database)
        TrainingService(repo)
        unknown = {
            "exercise_id": unknown_id, "definition_version": 1,
            "name_zh": "合成来源待确认动作", "recording_mode": "unknown",
            "equipment_type": "other", "default_load_basis": "unknown",
            "display_regions": ["legs"], "movement_patterns": ["hinge"],
            "source": {"provider": "wger", "source_uuid": "synthetic-offline-unknown"},
            "scientific_review": {"status": "synthetic_source_marker_do_not_inherit"},
            "reviewed_anatomy": {"synthetic_marker": "do_not_inherit"},
        }
        repo.conn.execute(
            "INSERT INTO exercise_catalog(exercise_id,definition_version,owner_id,name,definition_json,created_at) "
            "VALUES(?,1,'public',?,?,?)",
            (unknown_id, unknown["name_zh"], json.dumps(unknown), "2026-11-12T01:00:00+00:00"),
        )
        repo.conn.commit()
        html = output / "offline-custom.html"
        html.write_bytes(recorder_html(repo))
        repo.close()
        server = HealthZipHTTPServer(("127.0.0.1", 0), database, "synthetic-token", 1024 * 1024)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
                context = browser.new_context(accept_downloads=True)
                context.route("http**/*", lambda route: route.continue_()
                              if route.request.url.startswith(base + "/") else route.abort())
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: requests.append(request.url)
                        if request.url.startswith(("http:", "https:")) else None)
                page.goto(html.as_uri())
                page.locator("#connection").evaluate("element=>element.open=true")
                page.locator("#base").fill(base)
                page.locator("#token").fill("synthetic-token")
                page.locator("#connect").click()
                page.wait_for_function("document.querySelector('#notice').textContent.includes('已缓存在这台设备')")
                page.get_by_role("button", name="开始新训练", exact=True).click()
                session_id = page.evaluate("current().uuid")
                events = []
                cases = [
                    {"name": "合成私人搬运动作", "source": "custom", "mode": "distance",
                     "equipment": "dumbbell", "basis": "per_dumbbell_kg", "side": "left",
                     "regions": ["arms", "whole_body"], "patterns": ["carry", "single_leg"],
                     "notes": "合成单侧搬运变式", "measure_label": "距离米", "quantity": "20"},
                    {"name": "合成私人平板变式", "source": "psa.ex.plank", "mode": "duration",
                     "equipment": "bodyweight", "basis": "bodyweight_no_external", "side": "right",
                     "regions": ["core", "arms"], "patterns": ["isometric", "anti_rotation"],
                     "notes": "合成右侧支撑变式", "measure_label": "持续秒数", "quantity": "30"},
                    {"name": "合成私人确认定义", "source": unknown_id, "mode": "repetitions",
                     "equipment": "dumbbell", "basis": "per_dumbbell_kg", "side": "alternating",
                     "regions": ["legs", "glutes"], "patterns": ["hinge", "hip_extension"],
                     "notes": "合成来源已由用户确认记录方式", "measure_label": "实际次数", "quantity": "8"},
                ]
                saved_ids = []
                for index, case in enumerate(cases):
                    context.set_offline(True)
                    page.locator("#active details").first.evaluate("element=>element.open=true")
                    page.get_by_label("搜索动作 / 别名", exact=True).fill(case["source"])
                    page.get_by_label("动作", exact=True).select_option(case["source"])
                    if case["source"] == "psa.ex.plank":
                        page.get_by_label("复制为我的动作变式", exact=True).check()
                    if case["source"] == unknown_id:
                        pending = page.evaluate("state.outbox.length")
                        page.get_by_role("button", name="加入本次训练", exact=True).click()
                        assert page.evaluate("state.outbox.length") == pending
                        assert "明确选择记录模式" in page.locator("#notice").inner_text()
                    page.get_by_label("自定义动作名称（选自定义时填写）", exact=True).fill(case["name"])
                    page.get_by_label("记录模式", exact=True).select_option(case["mode"])
                    page.get_by_label("自定义器械类型", exact=True).select_option(case["equipment"])
                    page.get_by_label("自定义动作部位（可多选）", exact=True).select_option(case["regions"])
                    page.get_by_label("自定义动作模式（可多选）", exact=True).select_option(case["patterns"])
                    page.get_by_label("动作变式说明", exact=True).fill(case["notes"])
                    page.get_by_label("重量口径", exact=True).select_option(case["basis"])
                    page.get_by_label("侧别", exact=True).select_option(case["side"])
                    if index == 0:
                        pending = page.evaluate("state.outbox.length")
                        page.get_by_role("button", name="加入本次训练", exact=True).click()
                        assert page.evaluate("state.outbox.length") == pending
                        assert "请确认负荷口径" in page.locator("#notice").inner_text()
                    page.get_by_label("我确认上述重量口径", exact=True).check()
                    page.get_by_role("button", name="加入本次训练", exact=True).click()
                    row = page.locator("section.set").last
                    row.get_by_label(case["measure_label"], exact=True).fill(case["quantity"])
                    if case["equipment"] == "dumbbell":
                        row.get_by_label("重量 / 刻度", exact=True).fill("12")
                    row.get_by_role("button", name="确认完成", exact=True).click()
                    identity = page.evaluate("current().exercises.at(-1).exercise.exercise_id")
                    saved_ids.append(identity)
                    events.extend(page.evaluate("state.outbox"))
                    page.reload()
                    local = page.evaluate("id=>state.catalog.find(x=>x.exercise_id===id)", identity)
                    assert set(local["display_regions"]) == set(case["regions"])
                    assert set(local["movement_patterns"]) == set(case["patterns"])
                    assert local["side"] == case["side"] and local["variant_notes"] == case["notes"]
                    context.set_offline(False)
                    page.locator("#connection").evaluate("element=>element.open=true")
                    # Refresh the server's catalog before syncing this locally created definition.
                    page.locator("#connect").click()
                    page.wait_for_function("document.querySelector('#notice').textContent.includes('已缓存在这台设备')")
                    page.reload()
                    assert page.evaluate("id=>state.catalog.some(x=>x.exercise_id===id)", identity)
                    assert not page.evaluate("id=>state.catalog_public_ids.includes(id)", identity)
                    page.locator("#active details").first.evaluate("element=>element.open=true")
                    page.get_by_label("搜索动作 / 别名", exact=True).fill(case["name"])
                    assert page.get_by_label("动作", exact=True).locator(
                        f'option[value="{identity}"]'
                    ).count() == 1
                    page.locator("#connection").evaluate("element=>element.open=true")
                    page.locator("#sync").click()
                    page.wait_for_function("state.outbox.length===0")
                    with closing(Repository(database)) as check:
                        definition = TrainingService(check).get_exercise(identity)
                        assert set(definition["display_regions"]) == set(case["regions"])
                        assert set(definition["movement_patterns"]) == set(case["patterns"])
                        assert definition["side"] == case["side"]
                        assert definition["variant_notes"] == case["notes"]
                        assert definition["recording_mode"] == case["mode"]
                        assert definition["equipment_type"] == case["equipment"]
                        assert definition["default_load_basis"] == case["basis"]
                        assert definition["scientific_review"] == {"status": "unreviewed", "source_ids": []}
                        assert definition["muscle_participation_proposals"] == []
                        assert not definition.get("reviewed_anatomy")
                        if case["source"] == "custom":
                            assert definition["derived_from"] is None
                        else:
                            assert definition["derived_from"]["exercise_id"] == case["source"]
                            assert definition["derived_from"]["definition_version"] == 1
                    report[case["source"]] = {
                        "mode": case["mode"], "regions": sorted(case["regions"]),
                        "movement_patterns": sorted(case["patterns"]), "side": case["side"],
                        "variant_notes_preserved": True, "derived_from_preserved": True,
                        "scientific_review_inherited": False, "pending_catalog_survives_reconnect": True,
                    }
                page.evaluate("events=>{state.outbox=events;persist();render()}", events)
                page.locator("#connection").evaluate("element=>element.open=true")
                page.locator("#sync").click()
                page.wait_for_function("state.outbox.length===0")
                with closing(Repository(database)) as check:
                    svc = TrainingService(check)
                    session = svc.get_session(session_id)
                    assert len(session["exercises"]) == len(cases)
                    assert sum(len(x["sets"]) for x in session["exercises"]) == len(cases)
                    assert session["completed_sets"] == len(cases)
                    assert len(svc.search_exercises(view="custom")) == len(cases)
                page.locator("#connect").click()
                page.wait_for_function("document.querySelector('#notice').textContent.includes('已缓存在这台设备')")
                page.reload()
                assert all(page.evaluate("id=>state.catalog.some(x=>x.exercise_id===id)", identity)
                           for identity in saved_ids)
                page.locator("#connection").evaluate("element=>element.open=true")
                with page.expect_download() as download:
                    page.locator("#download").click()
                exported = output / "exported-public.html"
                download.value.save_as(exported)
                assert all(case["name"] not in exported.read_text() for case in cases)
                assert all(case["notes"] not in exported.read_text() for case in cases)
                report.update(
                    status="passed", synthetic_training_only=True, ui_local_rest_sync=True,
                    retries_without_duplicate_definitions_or_sets=True,
                    private_definitions_not_in_public_html=True,
                    private_notes_not_in_public_html=True,
                    pending_private_definitions_searchable_after_reconnect=True,
                    invalid_mode_or_unconfirmed_basis_creates_no_event=True,
                    browser=browser.version,
                )
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    assert not errors and all(url.startswith(base + "/") for url in requests)
    report.update(local_http_request_count=len(requests), external_http_request_count=0, page_errors=errors)
    (output / "browser-custom-after.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
