"""Per-object media rights, verified local blobs and public-only offline packages."""

from __future__ import annotations

import hashlib
import io
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from .catalog_import import encoded, now


def media_metadata(raw, kind, licenses):
    license_value = next((x for x in licenses if x["id"] == raw.get("license")), {})
    url = license_value.get("url", "")
    parsed = urlparse(url)
    allowed = parsed.netloc in {"creativecommons.org", "www.creativecommons.org"} and any(
        parsed.path.startswith(p)
        for p in (
            "/licenses/by-sa/3.0/",
            "/licenses/by-sa/4.0/",
            "/licenses/by/3.0/",
            "/licenses/by/4.0/",
            "/publicdomain/zero/1.0/",
        )
    )
    author = raw.get("license_author") or ", ".join(raw.get("author_history", [])) or "上游未署名"
    original = raw.get("license_object_url") or raw.get(kind) or ""
    metadata = {
        "media_id": f"wger.{kind}.{raw['id']}",
        "provider_media_id": raw["id"],
        "source_uuid": raw.get("exercise_uuid") or f"id:{raw['exercise']}",
        "media_type": kind,
        "original_url": raw.get(kind),
        "is_main": bool(raw.get("is_main")),
        "license": license_value or None,
        "license_scope": "individual_media_object" if allowed else "unknown",
        "author": author,
        "author_url": raw.get("license_author_url"),
        "original_work_url": original,
        "derivative_source_url": raw.get("license_derivative_source_url"),
        "attribution_text": f"{author} · wger · {license_value.get('short_name', '许可未知')} · {original}",
        "changes": "none; original bytes",
        "width": raw.get("width"),
        "height": raw.get("height"),
        "duration": raw.get("duration"),
        "upstream_size": raw.get("size"),
        "is_ai_generated": raw.get("is_ai_generated", False),
    }
    return metadata, allowed


def download(url):
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "wger.de"
        or not parsed.path.startswith("/media/")
    ):
        raise ValueError("仅下载官方媒体路径")
    request = urllib.request.Request(url, headers={"User-Agent": "HealthZIP-public-catalog/1.4"})
    with urllib.request.urlopen(request, timeout=90) as response:
        if response.status != 200:
            raise ValueError("媒体HTTP失败")
        raw = response.read(512 * 1024 * 1024 + 1)
        if len(raw) > 512 * 1024 * 1024:
            raise ValueError("媒体超过本地单文件下载上限")
        return raw, response.headers.get_content_type()


def resumable_download(url, root, *, opener=urllib.request.urlopen):
    """Resume only when the origin supplies a validator; partial bytes stay local."""
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "wger.de"
        or not parsed.path.startswith("/media/")
    ):
        raise ValueError("仅下载官方媒体路径")
    folder = Path(root) / "partial"
    folder.mkdir(exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()
    part, info = folder / (key + ".partial"), folder / (key + ".json")
    prior = json.loads(info.read_text()) if info.exists() else {}
    offset = part.stat().st_size if part.exists() and prior.get("validator") else 0
    if offset and offset == prior.get("expected_total"):
        return part.read_bytes(), prior["mime"], part, info
    headers = {"User-Agent": "HealthZIP-public-catalog/1.4"}
    if offset:
        headers.update({"Range": f"bytes={offset}-", "If-Range": prior["validator"]})
    request = urllib.request.Request(url, headers=headers)
    with opener(request, timeout=90) as response:
        if response.status == 206 and offset:
            if not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                raise ValueError("断点响应偏移不符")
            mode = "ab"
        elif response.status == 200:
            offset, mode = 0, "wb"
        else:
            raise ValueError("媒体HTTP状态不支持安全续传")
        validator = response.headers.get("ETag") or response.headers.get("Last-Modified")
        length = response.headers.get("Content-Length")
        info.write_text(
            encoded(
                {
                    "url": url,
                    "validator": validator,
                    "received_at": now(),
                    "expected_total": offset + int(length) if length else None,
                    "mime": response.headers.get_content_type(),
                }
            )
        )
        count = offset
        expected = response.headers.get("Content-Length")
        with part.open(mode) as handle:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > 512 * 1024 * 1024:
                    raise ValueError("媒体超过本地单文件下载上限")
                handle.write(chunk)
        if expected is not None and count - offset != int(expected):
            raise ValueError("媒体响应被截断，保留待续传文件")
        return part.read_bytes(), response.headers.get_content_type(), part, info


def validate_bytes(raw, kind, mime):
    if kind == "image":
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            actual_mime = Image.MIME.get(image.format)
            image.verify()
        if not actual_mime or not actual_mime.startswith("image/"):
            raise ValueError("图片类型未知")
        return {"mime": actual_mime, "width": width, "height": height, "size": len(raw)}
    if (
        len(raw) < 16
        or raw[4:8] != b"ftyp"
        or mime not in {"video/mp4", "video/quicktime", "application/octet-stream"}
    ):
        raise ValueError("视频容器损坏或类型不支持")
    # ISO BMFF/QuickTime atoms must consume all bytes; truncated bodies never become ready.
    import struct

    offset, has_movie, has_data = 0, False, False
    while offset < len(raw):
        if len(raw) - offset < 8:
            raise ValueError("视频块头不完整")
        size, atom = struct.unpack(">I4s", raw[offset : offset + 8])
        if size == 1:
            if len(raw) - offset < 16:
                raise ValueError("视频扩展块头不完整")
            size = struct.unpack(">Q", raw[offset + 8 : offset + 16])[0]
        if size == 0:
            size = len(raw) - offset
        if size < 8 or offset + size > len(raw):
            raise ValueError("视频块被截断")
        has_movie |= atom == b"moov"
        has_data |= atom == b"mdat"
        offset += size
    if not has_movie or not has_data:
        raise ValueError("视频缺少必要元数据或数据")
    return {"mime": "video/quicktime" if raw[8:12] == b"qt  " else "video/mp4", "size": len(raw)}


def fetch_media(repo, root, *, downloader=download, workers=4, limit=None, media_ids=None):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    rows = [
        dict(r)
        for r in repo.conn.execute(
            "SELECT * FROM catalog_media WHERE license_allowed=1 AND fetch_status!='withdrawn'"
        )
    ]
    if media_ids is not None:
        rows = [row for row in rows if row["media_id"] in media_ids]
    if limit is not None:
        rows = rows[:limit]

    def fetch(row):
        if row["fetch_status"] == "ready" and row["local_path"]:
            path = Path(row["local_path"])
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == row["blob_hash"]:
                return row["media_id"], None
        try:
            metadata = json.loads(row["metadata_json"])
            partial_files = None
            if downloader is download:
                raw, mime, part, info = resumable_download(metadata["original_url"], root)
                partial_files = (part, info)
            else:
                raw, mime = downloader(metadata["original_url"])
            try:
                verification = validate_bytes(raw, row["media_type"], mime)
            except Exception:
                if partial_files:
                    for partial in partial_files:
                        partial.unlink(missing_ok=True)
                raise
            sha = hashlib.sha256(raw).hexdigest()
            path = root / sha[:2] / sha
            path.parent.mkdir(exist_ok=True)
            temporary = path.with_name(path.name + "." + uuid4().hex + ".partial")
            temporary.write_bytes(raw)
            temporary.replace(path)
            if partial_files:
                for partial in partial_files:
                    partial.unlink(missing_ok=True)
            identity = hashlib.sha256(
                encoded({k: v for k, v in metadata.items() if k != "verified_file"}).encode()
            ).hexdigest()
            return row["media_id"], {
                "status": "ready",
                "hash": sha,
                "path": str(path),
                "verification": verification,
                "source_metadata_hash": identity,
            }
        except Exception as exc:
            return row["media_id"], {"status": "failed", "error": str(exc)[:500]}

    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(fetch, row) for row in rows]):
            mid, result = future.result()
            if result:
                if result["status"] == "ready":
                    current = repo.conn.execute(
                        "SELECT metadata_json,license_allowed FROM catalog_media WHERE media_id=?",
                        (mid,),
                    ).fetchone()
                    meta = json.loads(current["metadata_json"])
                    current_hash = hashlib.sha256(
                        encoded({k: v for k, v in meta.items() if k != "verified_file"}).encode()
                    ).hexdigest()
                    if (
                        not current["license_allowed"]
                        or current_hash != result["source_metadata_hash"]
                    ):
                        results.append(
                            {"media_id": mid, "status": "discarded_due_to_source_change"}
                        )
                        continue
                    meta["verified_file"] = result["verification"]
                    repo.conn.execute(
                        "UPDATE catalog_media SET fetch_status='ready',blob_hash=?,local_path=?,verified_at=?,metadata_json=?,error=NULL WHERE media_id=?",
                        (result["hash"], result["path"], now(), encoded(meta), mid),
                    )
                else:
                    repo.conn.execute(
                        "UPDATE catalog_media SET fetch_status='failed',error=?,verified_at=? WHERE media_id=?",
                        (result["error"], now(), mid),
                    )
                repo.conn.commit()
                results.append({"media_id": mid, **result})
    if results:
        repo.conn.execute(
            "INSERT INTO schema_meta(key,value) VALUES('catalog_data_version','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1"
        )
        repo.conn.commit()
    return {
        "checked": len(rows),
        "updated": len(results),
        "failed": [r for r in results if r["status"] == "failed"],
    }


def media_for(conn, exercise_id):
    rows = conn.execute(
        "SELECT DISTINCT m.* FROM catalog_media m JOIN catalog_source_mapping x ON x.provider='wger' AND x.source_uuid=m.source_uuid WHERE x.local_exercise_id=? AND x.relation='exact_identity' AND x.status='confirmed' ORDER BY m.media_type,m.media_id",
        (exercise_id,),
    )
    return [
        {
            **json.loads(r["metadata_json"]),
            "fetch_status": r["fetch_status"],
            "blob_hash": r["blob_hash"],
            "local_path": r["local_path"]
            if r["license_allowed"] and r["fetch_status"] == "ready"
            else None,
            "verified_at": r["verified_at"],
            "error": r["error"],
        }
        for r in rows
    ]


def local_media(conn, blob_hash):
    if len(blob_hash) != 64 or any(c not in "0123456789abcdef" for c in blob_hash):
        raise ValueError("媒体hash无效")
    row = conn.execute(
        "SELECT local_path,metadata_json FROM catalog_media WHERE blob_hash=? AND fetch_status='ready' AND license_allowed=1",
        (blob_hash,),
    ).fetchone()
    if not row or not Path(row["local_path"]).is_file():
        raise ValueError("媒体不可用")
    return Path(row["local_path"]), json.loads(row["metadata_json"]).get("verified_file", {}).get(
        "mime", "application/octet-stream"
    )


def reuse_media_cache(repo, source_repo):
    """Attach verified public blobs after matching this installation's current rights."""
    copied = 0
    for source in source_repo.conn.execute(
        "SELECT * FROM catalog_media WHERE fetch_status='ready' AND license_allowed=1"
    ):
        target = repo.conn.execute(
            "SELECT * FROM catalog_media WHERE media_id=? AND license_allowed=1 AND fetch_status!='withdrawn'",
            (source["media_id"],),
        ).fetchone()
        if not target:
            continue
        source_meta, target_meta = (
            json.loads(source["metadata_json"]),
            json.loads(target["metadata_json"]),
        )
        keys = ("source_uuid", "original_url", "license", "license_scope", "author", "changes")
        if any(source_meta.get(key) != target_meta.get(key) for key in keys):
            continue
        path = Path(source["local_path"])
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != source["blob_hash"]
        ):
            continue
        target_meta["verified_file"] = source_meta["verified_file"]
        repo.conn.execute(
            "UPDATE catalog_media SET metadata_json=?,fetch_status='ready',blob_hash=?,local_path=?,verified_at=?,error=NULL WHERE media_id=?",
            (
                encoded(target_meta),
                source["blob_hash"],
                source["local_path"],
                source["verified_at"],
                source["media_id"],
            ),
        )
        copied += 1
    if copied:
        repo.conn.execute(
            "INSERT INTO schema_meta(key,value) VALUES('catalog_data_version','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1"
        )
    repo.conn.commit()
    return {"attached_verified_media": copied}


def offline_package(repo, destination, *, include_media=True):
    from .catalog_import import public_catalog
    from .offline import recorder_html

    catalog = public_catalog(repo)
    media = []
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        archive.writestr("index.html", recorder_html(repo))
        for item in catalog["items"]:
            item["media"] = []
            for entry in media_for(repo.conn, item["exercise_id"]):
                clean = {k: v for k, v in entry.items() if k not in {"local_path", "error"}}
                if include_media and entry["local_path"]:
                    name = "media/" + entry["blob_hash"]
                    if name not in archive.namelist():
                        archive.write(entry["local_path"], name)
                    clean["package_path"] = name
                item["media"].append(clean)
                media.append(clean)
        archive.writestr("catalog.json", encoded(catalog))
        archive.writestr("media-attribution.json", encoded(media))
    return {
        "snapshot_id": catalog["snapshot_id"],
        "exercises": len(catalog["items"]),
        "media_included": sum(bool(x.get("package_path")) for x in media),
    }
