"""Real Chromium acceptance on a temporary copy of a public catalog database."""

import base64
import json
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from healthzip.db.repository import Repository
from healthzip.sync_server import HealthZipHTTPServer
from healthzip.training.offline import recorder_html
from healthzip.training.service import TrainingService


def main():
    output = Path("artifacts/v14/catalog").resolve()
    output.mkdir(parents=True, exist_ok=True)
    public_repo = Repository(".local/catalog/catalog.sqlite3")
    if public_repo.conn.execute("SELECT COUNT(*) FROM strength_session").fetchone()[0]:
        raise ValueError("Browser evidence requires the dedicated public catalog database")
    with tempfile.TemporaryDirectory(prefix="v14-catalog-browser-") as folder:
        folder = Path(folder)
        repo = Repository(folder / "synthetic.sqlite3")
        public_repo.conn.backup(repo.conn)
        public_repo.close()
        svc = TrainingService(repo)
        public_count = len(svc.search_exercises())
        custom = svc.create_exercise("合成旧版时长动作", "duration", "bodyweight", "unknown")
        template = svc.create_template(
            "旧版时长模板",
            [{"exercise_id": custom["exercise_id"], "targets": {"sets": [{"duration_s": 30}]}}],
        )
        svc.update_exercise(custom["exercise_id"], {"recording_mode": "distance"}, base_revision=1)
        html = folder / "index.html"
        html.write_bytes(recorder_html(repo))
        assert "合成旧版时长动作" not in html.read_text()
        repo.close()
        server = HealthZipHTTPServer(
            ("127.0.0.1", 0), folder / "synthetic.sqlite3", "synthetic-catalog-token", 1024 * 1024
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
                context = browser.new_context(viewport={"width": 430, "height": 930})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(html.as_uri())
                assert page.evaluate("state.catalog.length") == public_count
                page.locator("#connection").evaluate("e=>e.open=true")
                page.locator("#base").fill(f"http://127.0.0.1:{server.server_address[1]}")
                page.locator("#token").fill("synthetic-catalog-token")
                page.get_by_role("button", name="连接并缓存目录", exact=True).click()
                page.wait_for_function(
                    "document.querySelector('#notice').textContent.includes('已缓存在这台设备')"
                )
                page.locator("#template").select_option(template["id"])
                context.set_offline(True)
                page.get_by_role("button", name="开始新训练", exact=True).click()
                row = page.locator("section.set").first
                row.get_by_label("持续秒数", exact=True).fill("30")
                row.get_by_role("button", name="确认完成", exact=True).click()
                page.reload()
                assert (
                    page.locator("section.set")
                    .first.get_by_label("持续秒数", exact=True)
                    .input_value()
                    == "30"
                )
                assert page.evaluate("current().exercises[0].exercise.definition_version") == 1
                context.set_offline(False)
                page.locator("#connection").evaluate("e=>e.open=true")
                page.get_by_role("button", name="同步待发送记录", exact=True).click()
                page.wait_for_function("state.outbox.length===0")
                page.locator("#template").select_option("")
                page.locator("#sessionName").fill("公开目录离线验收")
                page.get_by_role("button", name="开始新训练", exact=True).click()
                page.locator("#active details").first.evaluate("e=>e.open=true")
                page.get_by_label("搜索动作 / 别名", exact=True).fill("psa.ex.plank")
                page.get_by_label("动作", exact=True).select_option("psa.ex.plank")
                page.get_by_role("button", name="缓存此动作示范", exact=True).click()
                page.wait_for_function(
                    "document.querySelector('#notice').textContent.includes('媒体缓存完成')",
                    timeout=60000,
                )
                context.set_offline(True)
                page.reload()
                page.locator("#active details").first.evaluate("e=>e.open=true")
                page.get_by_label("搜索动作 / 别名", exact=True).fill("psa.ex.plank")
                page.get_by_label("动作", exact=True).select_option("psa.ex.plank")
                page.wait_for_function(
                    "[...document.querySelectorAll('#active img')].some(x=>x.complete&&x.naturalWidth>0)"
                )
                page.locator("#active img").first.scroll_into_view_if_needed()
                font = Path("/tmp/NotoSansCJKsc-Regular.otf")
                if font.exists():
                    data = base64.b64encode(font.read_bytes()).decode()
                    page.add_style_tag(
                        content="@font-face{font-family:EvidenceCJK;src:url(data:font/otf;base64,"
                        + data
                        + ")}body,input,button,select{font-family:EvidenceCJK,system-ui}"
                    )
                    page.evaluate("document.fonts.ready")
                page.screenshot(path=str(output / "offline-catalog.png"))
                context.set_offline(False)
                page.get_by_label("搜索动作 / 别名", exact=True).fill("psa.ex.barbell_bench_press")
                page.get_by_label("动作", exact=True).select_option("psa.ex.barbell_bench_press")
                page.get_by_role("button", name="缓存此动作示范", exact=True).click()
                page.wait_for_function(
                    "document.querySelector('#notice').textContent.includes('媒体缓存完成')",
                    timeout=60000,
                )
                context.set_offline(True)
                page.reload()
                page.locator("#active details").first.evaluate("e=>e.open=true")
                page.get_by_label("搜索动作 / 别名", exact=True).fill("psa.ex.barbell_bench_press")
                page.get_by_label("动作", exact=True).select_option("psa.ex.barbell_bench_press")
                page.wait_for_function(
                    "[...document.querySelectorAll('#active video')].some(x=>x.readyState>=2&&x.videoWidth>0)",
                    timeout=30000,
                )
                video = page.locator("#active video").first
                video.evaluate("v=>{v.muted=true;return v.play()}")
                page.wait_for_function("document.querySelector('#active video').currentTime>0.1")
                video_fact = video.evaluate(
                    "v=>({width:v.videoWidth,height:v.videoHeight,duration:v.duration,current_time:v.currentTime})"
                )
                media_states = page.evaluate("""async()=>{
                    const result={};
                    for(const status of ['none','pending','failed','license_unknown','withdrawn']){
                        const panel=document.createElement('section');
                        await showCatalogDetail(panel,{name_en:'Synthetic media state',media:status==='none'?[]:[
                            {media_type:'image',fetch_status:status,attribution_text:'Synthetic Test Author'}
                        ]});
                        result[status]=panel.textContent;
                    }
                    return result;
                }""")
                for state, message in {
                    "none": "暂无动作示范",
                    "pending": "尚未下载",
                    "failed": "下载失败",
                    "license_unknown": "媒体许可不明",
                    "withdrawn": "来源或许可已撤回",
                }.items():
                    assert message in media_states[state]
                report = {
                    "status": "passed",
                    "public_exercises": public_count,
                    "offline_restart_keeps_full_catalog": page.evaluate("state.catalog.length")
                    >= public_count,
                    "cached_media_opens_offline": True,
                    "h264_video_plays_offline": video_fact,
                    "old_template_definition_version": 1,
                    "old_template_duration_seconds": 30,
                    "private_custom_not_in_public_html": True,
                    "local_storage_bytes": page.evaluate("localStorage.getItem(KEY).length*2"),
                    "page_errors": errors,
                    "synthetic_training_only": True,
                    "distinct_chinese_media_states": media_states,
                }
                assert not errors
                (output / "offline-browser.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n"
                )
                print(json.dumps(report, ensure_ascii=False))
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
