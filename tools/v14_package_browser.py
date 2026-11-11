"""Play the shipped catalog ZIP directly from file URLs in offline Chromium."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

from playwright.sync_api import sync_playwright


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sample_entries(path):
    """Read actual ISO BMFF sample-entry types from the packaged video's stsd."""
    raw = Path(path).read_bytes()
    entries = []

    def atoms(start, end):
        while start < end:
            size, kind = struct.unpack(">I4s", raw[start:start + 8])
            header = 8
            if size == 1:
                size = struct.unpack(">Q", raw[start + 8:start + 16])[0]
                header = 16
            if size == 0:
                size = end - start
            assert size >= header and start + size <= end
            body = start + header
            if kind in {b"moov", b"trak", b"mdia", b"minf", b"stbl"}:
                atoms(body, start + size)
            elif kind == b"stsd":
                count = struct.unpack(">I", raw[body + 4:body + 8])[0]
                position = body + 8
                for _ in range(count):
                    length, codec = struct.unpack(">I4s", raw[position:position + 8])
                    assert length >= 8 and position + length <= start + size
                    entries.append(codec.decode("ascii"))
                    position += length
            start += size

    atoms(0, len(raw))
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", default=".local/catalog/HealthZIP-catalog-offline.zip")
    parser.add_argument("--manifest", default="artifacts/v14/catalog/offline-package.json")
    parser.add_argument("--output", default="artifacts/v14/catalog/offline-package-browser.json")
    args = parser.parse_args()
    package = Path(args.package)
    package_hash = sha256_file(package)
    manifest = json.loads(Path(args.manifest).read_text())
    expected = next(row for row in manifest["packages"] if row["filename"] == package.name)
    assert package_hash == expected["sha256"]
    assert package.stat().st_size == expected["bytes"]
    with tempfile.TemporaryDirectory(prefix="v14-package-browser-") as temporary:
        root = Path(temporary)
        with ZipFile(package) as archive:
            members = archive.infolist()
            assert len({item.filename for item in members}) == len(members)
            assert sum(item.file_size for item in members) < 10 * 1024**3
            for item in members:
                assert item.filename in {"index.html", "catalog.json", "media-attribution.json"} or (
                    re.fullmatch(r"media/[a-f0-9]{64}", item.filename)
                )
            archive.extractall(root)
        catalog = json.loads((root / "catalog.json").read_text())
        assert len(catalog["items"]) == expected["exercises"]
        by_id = {item["exercise_id"]: item for item in catalog["items"]}
        video_meta = next(item for item in by_id["psa.ex.barbell_bench_press"]["media"]
                          if item["media_id"] == "wger.video.21")
        image_meta = next(item for item in by_id["psa.ex.plank"]["media"]
                          if item["media_id"] == "wger.image.346")
        codecs = sample_entries(root / video_meta["package_path"])
        assert "avc1" in codecs
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                context = browser.new_context(viewport={"width": 430, "height": 930})
                context.set_offline(True)
                page = context.new_page()
                errors, network_requests = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: network_requests.append(request.url)
                        if request.url.startswith(("http:", "https:")) else None)
                page.goto((root / "index.html").as_uri())
                assert page.evaluate("localStorage.length") == 0
                assert page.evaluate("state.catalog.length") == expected["exercises"]
                page.locator("#sessionName").fill("合成离线包播放验收")
                page.get_by_role("button", name="开始新训练", exact=True).click()
                page.locator("#active details").first.evaluate("element=>element.open=true")
                search = page.get_by_label("搜索动作 / 别名", exact=True)
                select = page.get_by_label("动作", exact=True)
                search.fill("psa.ex.plank")
                select.select_option("psa.ex.plank")
                image_selector = f'#active img[src="{image_meta["package_path"]}"]'
                page.wait_for_function(
                    "selector=>{const image=document.querySelector(selector);"
                    "return image?.complete&&image.naturalWidth>0}", arg=image_selector,
                )
                picture = page.locator(image_selector).first
                assert picture.evaluate("image=>image.currentSrc") == (
                    root / image_meta["package_path"]
                ).as_uri()
                image_fact = picture.evaluate(
                    "image=>({width:image.naturalWidth,height:image.naturalHeight})"
                )
                search.fill("psa.ex.barbell_bench_press")
                select.select_option("psa.ex.barbell_bench_press")
                video_selector = f'#active video[src="{video_meta["package_path"]}"]'
                page.wait_for_function(
                    "selector=>{const video=document.querySelector(selector);"
                    "return video?.readyState>=2&&video.videoWidth>0}",
                    arg=video_selector, timeout=30000,
                )
                video = page.locator(video_selector)
                assert video.evaluate("video=>video.currentSrc") == (
                    root / video_meta["package_path"]
                ).as_uri()
                assert page.evaluate("async hash=>Boolean(await cachedMedia(hash))",
                                     video_meta["blob_hash"]) is False
                video.evaluate("video=>{video.muted=true;return video.play()}")
                page.wait_for_function(
                    "selector=>document.querySelector(selector).currentTime>0.1",
                    arg=video_selector,
                )
                video_fact = video.evaluate(
                    "video=>({width:video.videoWidth,height:video.videoHeight,"
                    "duration:video.duration,current_time:video.currentTime})"
                )
                assert not errors and not network_requests
                report = {
                    "status": "passed",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "package_filename": package.name,
                    "package_sha256": package_hash,
                    "package_bytes": package.stat().st_size,
                    "package_manifest_matches": True,
                    "snapshot_id": catalog["snapshot_id"],
                    "public_exercises": page.evaluate("state.catalog.length"),
                    "package_ready_media": expected["catalog_ready_media"],
                    "fresh_browser_context": True,
                    "offline_before_navigation": True,
                    "http_request_count": len(network_requests),
                    "media_source_protocol": "file:",
                    "video_source_matches_package_file": True,
                    "video_present_in_indexeddb": False,
                    "image": {"media_id": image_meta["media_id"],
                              "package_path": image_meta["package_path"], **image_fact},
                    "video": {"media_id": video_meta["media_id"],
                              "package_path": video_meta["package_path"],
                              "sample_entries": codecs, "codec": "H.264", **video_fact},
                    "page_errors": errors,
                    "synthetic_training_only": True,
                    "limitation": "Verifies this packaged H.264 video; HEVC playback support "
                    "is not established by this acceptance.",
                }
            finally:
                browser.close()
    assert not root.exists()
    report["temporary_extraction_cleaned"] = True
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
