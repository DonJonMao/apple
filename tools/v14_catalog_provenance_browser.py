"""Check public name provenance through offline display, restart and HTML export."""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from healthzip.training.catalog_terms import CHINESE_NAME_STATUS_LABELS
from healthzip.training.offline import recorder_html


def main():
    cases = [
        ("draft", "project_translation"),
        ("upstream_unreviewed", "upstream"),
        ("existing_project_label", "project_seed"),
    ]
    items = [
        {
            "exercise_id": "synthetic." + status,
            "definition_version": 1,
            "name_zh": "合成动作 " + str(index),
            "name_en": "Synthetic public name " + str(index),
            "recording_mode": "unknown",
            "equipment_type": "other",
            "default_load_basis": "unknown",
            "source": {"provider": "wger"},
            "names": {"zh-CN": {"origin": origin, "review_status": status}},
            "media": [],
        }
        for index, (status, origin) in enumerate(cases)
    ]
    with tempfile.TemporaryDirectory(prefix="catalog-provenance-") as folder:
        folder = Path(folder)
        html = recorder_html().decode()
        start, end = html.index("const PUBLIC_CATALOG="), html.index("const CATALOG_SNAPSHOT=")
        html = html[:start] + "const PUBLIC_CATALOG=" + json.dumps(items) + ";\n" + html[end:]
        path = folder / "index.html"
        path.write_text(html)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(offline=True)
            page = context.new_page()
            errors, requests = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "request",
                lambda request: (
                    requests.append(request.url) if request.url.startswith("http") else None
                ),
            )
            page.goto(path.as_uri())

            def check_details():
                rendered = page.evaluate("""async()=>{
                    const result={};
                    for(const item of state.catalog){
                        const panel=document.createElement('section');
                        await showCatalogDetail(panel,item);
                        result[item.names['zh-CN'].review_status]=panel.textContent;
                    }
                    return result;
                }""")
                for status, _ in cases:
                    assert CHINESE_NAME_STATUS_LABELS[status] in rendered[status]
                return rendered

            initial = check_details()
            page.evaluate("persist()")
            page.reload()
            restarted = check_details()
            page.locator("#connection").evaluate("node=>node.open=true")
            with page.expect_download() as download:
                page.locator("#download").click()
            exported = folder / "exported.html"
            download.value.save_as(exported)
            context.close()
            context = browser.new_context(offline=True)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "request",
                lambda request: (
                    requests.append(request.url) if request.url.startswith("http") else None
                ),
            )
            page.goto(exported.as_uri())
            standalone = check_details()
            page.evaluate("""async()=>{
                const hash='f'.repeat(64);
                await cachedMedia(hash,new Blob(['invalid video'],{type:'video/mp4'}));
                const panel=document.createElement('section');panel.id='video-fallback';document.body.append(panel);
                await showCatalogDetail(panel,{name_en:'Synthetic unplayable video',media:[{
                    media_type:'video',fetch_status:'ready',blob_hash:hash,attribution_text:'Synthetic fixture'
                }]});
            }""")
            page.wait_for_function(
                "document.querySelector('#video-fallback').textContent.includes('当前浏览器无法播放此视频')"
            )
            fallback = page.locator("#video-fallback").inner_text()
            assert "格式或编码" in fallback and "原文件" in fallback
            assert not errors and not requests
            report = {
                "status": "passed",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "scope": "Synthetic public catalog only; no database or source video changes",
                "initial_details": initial,
                "offline_restart_details": restarted,
                "standalone_html_details": standalone,
                "unplayable_video_fallback": fallback,
                "hevc_playback_verified": False,
                "http_requests": len(requests),
                "page_errors": errors,
            }
            browser.close()
    output = Path("artifacts/v14/catalog/offline-name-status-after.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
