"""Explicit offline Chromium checks using a local public package and synthetic training.

Run with --package <existing public catalog ZIP> --output <local diagnostic directory>.
No network downloads or production database access are performed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import tempfile
from pathlib import Path
from zipfile import ZipFile

from playwright.sync_api import sync_playwright

from healthzip.db.repository import Repository
from healthzip.training.offline import apply_event_batch, browser_bootstrap, recorder_html
from healthzip.training.service import TrainingService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report, errors, requests = {}, [], []
    with ZipFile(args.package) as archive:
        shipped = archive.read("index.html").decode()
        snapshot_line = re.search(r"const CATALOG_SNAPSHOT=(.*);\n", shipped).group(0)
        current = recorder_html().decode()
        seed_match = re.search(r"const PUBLIC_CATALOG=(.*);\n", current)
        public_keys = json.loads(seed_match.group(1))[0].keys()
        catalog = json.loads(archive.read("catalog.json"))
        public_items = [
            {**{key: item.get(key) for key in public_keys}, "media": item.get("media", [])}
            for item in catalog["items"]
        ]
        payload = json.dumps(public_items, ensure_ascii=False).replace("<", "\\u003c")
        current = current.replace(seed_match.group(0), "const PUBLIC_CATALOG=" + payload + ";\n")
        current = current.replace(re.search(r"const CATALOG_SNAPSHOT=(.*);\n", current).group(0), snapshot_line)
        page_path = output / "current-public.html"
        page_path.write_text(current)
        media = {m["media_id"]: m for x in catalog["items"] for m in x.get("media", [])}
        for identity in ("wger.video.21", "wger.video.7"):
            entry = media[identity]
            target = output / entry["package_path"]
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(archive.read(entry["package_path"]))

    with tempfile.TemporaryDirectory(prefix="synthetic-", dir=output) as temporary:
        repo = Repository(Path(temporary) / "synthetic.sqlite3")
        svc = TrainingService(repo)
        custom = svc.create_exercise("合成旧名称", "duration", "dumbbell", "per_dumbbell_kg")
        old = svc.create_template("A旧模板", [{
            "exercise_id": custom["exercise_id"],
            "condition": {"load_basis": "per_dumbbell_kg", "load_basis_confirmed": True},
            "targets": {"sets": [{"duration_s": 30}]},
        }])
        svc.update_exercise(custom["exercise_id"], {"name_zh": "合成新名称"}, base_revision=1)
        svc.create_template("B新模板", [{"exercise_id": custom["exercise_id"]}])
        svc.update_exercise(custom["exercise_id"], {"recording_mode": "distance"}, base_revision=2)
        svc.add_alias("psa.ex.plank", "合成私人别名唯一标记")
        bootstrap = browser_bootstrap(repo)
        synthetic_path = output / "current-synthetic.html"
        synthetic_path.write_bytes(recorder_html(repo))

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])

            def page_for(path):
                context = browser.new_context(accept_downloads=True)
                context.set_offline(True)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: requests.append(request.url)
                        if request.url.startswith(("http:", "https:")) else None)
                page.goto(path.as_uri())
                return context, page

            context, page = page_for(page_path)
            expected = page.evaluate("JSON.stringify(state.catalog.map(compactExercise))")
            descriptions = page.evaluate("state.catalog.filter(x=>x.description).length")
            assert descriptions > 0
            page.get_by_role("button", name="开始新训练", exact=True).click()
            assert page.evaluate("Boolean(localStorage.getItem(KEY))")
            storage_bytes = page.evaluate("localStorage.getItem(KEY).length*2")
            page.reload()
            assert page.evaluate("JSON.stringify(state.catalog.map(compactExercise))") == expected
            assert page.evaluate("state.catalog.filter(x=>x.description).length") == descriptions
            assert "本机存储失败" not in page.locator("#notice").inner_text()
            report["complete_catalog_restart"] = {
                "items": page.evaluate("state.catalog.length"),
                "descriptions_before": descriptions, "descriptions_after": descriptions,
                "all_persisted_catalog_fields_match": True,
                "local_storage_utf16_bytes_with_training_draft": storage_bytes,
                "quota_error": False,
                "chinese_name_status_counts": page.evaluate("""Object.fromEntries(
                    ['draft','upstream_unreviewed','existing_project_label'].map(s=>
                    [s,state.catalog.filter(x=>x.names?.['zh-CN']?.review_status===s).length]))"""),
            }
            page.locator("#connection").evaluate("e=>e.open=true")
            with page.expect_download() as downloaded:
                page.locator("#download").click()
            exported = output / "exported-public.html"
            downloaded.value.save_as(exported)
            exported_context, exported_page = page_for(exported)
            assert exported_page.evaluate("state.catalog.filter(x=>x.description).length") == descriptions
            exported_context.close()

            report["media"] = {}
            for identity in ("wger.video.21", "wger.video.7"):
                entry = media[identity]
                page.evaluate("""async entry=>{
                    let panel=document.querySelector('#mediaProbe');
                    if(!panel){panel=document.createElement('section');panel.id='mediaProbe';document.body.append(panel)}
                    await showCatalogDetail(panel,{name_en:'Actual public source video',media:[entry]});
                }""", entry)
                page.wait_for_function("""(()=>{
                    const panel=document.querySelector('#mediaProbe'),video=panel.querySelector('video');
                    return (video?.readyState>=2&&video.videoWidth>0)||!!panel.querySelector('a[download]');
                })()""")
                video = page.locator("#mediaProbe video")
                fact = {"media_id": identity}
                if video.count():
                    video.evaluate("v=>{v.muted=true;return v.play()}")
                    page.wait_for_function("document.querySelector('#mediaProbe video').currentTime>0.1")
                    fact.update(video.evaluate("v=>({width:v.videoWidth,height:v.videoHeight,current_time:v.currentTime})"))
                else:
                    assert identity == "wger.video.7"
                    assert "当前浏览器无法显示此视频的画面" in page.locator("#mediaProbe").inner_text()
                    with page.expect_download() as original:
                        page.locator("#mediaProbe a[download]").click()
                    original_path = original.value.path()
                    assert hashlib.sha256(Path(original_path).read_bytes()).hexdigest() == entry["blob_hash"]
                    fact.update(unavailable_picture_message=True, original_download_sha256_matches=True)
                report["media"][identity] = fact
            entry = dict(media["wger.video.21"])
            original_bytes = (output / entry["package_path"]).read_bytes()
            entry["package_path"] = "data:video/mp4;base64," + base64.b64encode(original_bytes).decode()
            page.evaluate("""async entry=>await showCatalogDetail(document.querySelector('#mediaProbe'),
                {name_en:'Actual H.264 data URL',media:[entry]})""", entry)
            page.wait_for_function("document.querySelector('#mediaProbe video')?.videoWidth>0")
            report["data_url_h264_dimensions"] = page.locator("#mediaProbe video").evaluate(
                "v=>[v.videoWidth,v.videoHeight]"
            )
            context.close()

            context, page = page_for(synthetic_path)
            page.evaluate("""data=>{
                for(const key of ['catalog','catalog_snapshot_id','catalog_public_ids','catalog_definitions',
                    'templates','equipment'])state[key]=data[key];
                persist();render();
            }""", bootstrap)
            page.locator("#template").select_option(old["id"])
            page.get_by_role("button", name="开始新训练", exact=True).click()
            assert page.evaluate("current().exercises[0].exercise.name_zh") == "合成旧名称"
            row = page.locator("section.set").first
            row.get_by_label("持续秒数", exact=True).fill("30")
            row.get_by_label("重量 / 刻度", exact=True).fill("12")
            row.get_by_role("button", name="确认完成", exact=True).click()
            page.reload()
            assert page.evaluate("current().exercises[0].exercise.name_zh") == "合成旧名称"
            events = page.evaluate("state.outbox")
            first = apply_event_batch(repo, events)
            assert all(x["status"] == "applied" for x in first["results"])
            again = apply_event_batch(repo, events)
            assert all(x["result"]["replayed"] for x in again["results"])
            saved = svc.get_session(page.evaluate("current().uuid"))["exercises"][0]
            assert saved["exercise"] == old["items"][0]["exercise_snapshot"]
            assert saved["condition"]["load_basis"] == "per_dumbbell_kg"
            assert saved["sets"][0]["duration_s"] == 30
            assert saved["sets"][0]["load_value"] == "12"
            assert len(saved["sets"]) == 1
            report["template_offline_replay"] = {
                "name": saved["exercise"]["name_zh"],
                "definition_version": saved["exercise"]["definition_version"],
                "recording_mode": saved["exercise"]["recording_mode"],
                "load_basis": saved["condition"]["load_basis"],
                "actual_duration_s": 30, "actual_load_value": saved["sets"][0]["load_value"],
                "replayed_without_duplicate_sets": True,
            }
            page.locator("#active details").first.evaluate("e=>e.open=true")
            page.get_by_label("搜索动作 / 别名", exact=True).fill("合成私人别名唯一标记")
            assert page.get_by_label("动作", exact=True).locator('option[value="psa.ex.plank"]').count() == 1
            report["private_alias_search_after_restart"] = "psa.ex.plank"
            page.locator("#connection").evaluate("e=>e.open=true")
            with page.expect_download() as downloaded:
                page.locator("#download").click()
            exported = output / "exported-synthetic-public.html"
            downloaded.value.save_as(exported)
            assert "合成私人别名唯一标记" not in exported.read_text()
            assert "合成旧名称" not in exported.read_text()
            assert "合成新名称" not in exported.read_text()
            report["private_alias_and_custom_omitted_from_public_html"] = True
            context.close()
            report["browser"] = browser.version
            browser.close()
        repo.close()
    assert not errors and not requests
    report.update(status="passed", http_requests=requests, page_errors=errors, synthetic_training_only=True)
    (output / "browser-after.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
