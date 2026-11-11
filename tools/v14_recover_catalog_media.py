"""Recover unreceipted public blobs using local integrity and origin fingerprints.

This does not claim a remote whole-file checksum: Caddy's ETag is opaque. Each
receipt records exactly which remote ranges were compared with the local blob.
Only explicitly invoked runs access the public wger media origin.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import urllib.request
from pathlib import Path

from healthzip.db.repository import Repository
from healthzip.training.catalog_import import now
from healthzip.training.catalog_media import fetch_media, validate_bytes


def fingerprints(raw):
    size = len(raw)
    width = min(65536, size)
    ranges = {(0, width - 1), (size // 2, min(size - 1, size // 2 + width - 1)),
              (size - width, size - 1)}
    offset = 0
    while offset < size:
        length, atom = struct.unpack(">I4s", raw[offset:offset + 8])
        if length == 1:
            length = struct.unpack(">Q", raw[offset + 8:offset + 16])[0]
        if length == 0:
            length = size - offset
        if atom == b"moov":
            ranges.add((offset, offset + length - 1))
        offset += length
    return sorted(ranges)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".local/catalog/catalog.sqlite3")
    parser.add_argument("--root", default=".local/catalog/blobs")
    parser.add_argument("--output", default="artifacts/v14/catalog/cache-recovery.json")
    args = parser.parse_args()
    repo = Repository(args.db)
    root = Path(args.root)
    receipt_root = root.parent / "recovery-receipts"
    receipt_root.mkdir(exist_ok=True)
    rows = [dict(row) for row in repo.conn.execute(
        "SELECT * FROM catalog_media WHERE media_type='video' AND license_allowed=1 "
        "AND fetch_status NOT IN ('ready','withdrawn')"
    )]
    all_rows = [dict(row) for row in repo.conn.execute(
        "SELECT * FROM catalog_media WHERE media_type='video'"
    )]
    known = {row[0] for row in repo.conn.execute(
        "SELECT blob_hash FROM catalog_media WHERE fetch_status='ready'"
    )}
    blobs = [path for path in root.glob('*/*')
             if path.is_file() and len(path.name) == 64 and path.name not in known]
    selected = {}
    for row in rows:
        metadata = json.loads(row["metadata_json"])
        size = metadata["upstream_size"]
        matches = [p for p in blobs if p.stat().st_size == size]
        size_identities = [r for r in all_rows
                           if json.loads(r["metadata_json"])["upstream_size"] == size]
        if len(matches) == 1 and len(size_identities) == 1:
            selected[metadata["original_url"]] = (row, matches[0])

    def recover(url):
        row, path = selected[url]
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if sha != path.name:
            raise ValueError("existing blob hash mismatch")
        metadata = json.loads(row["metadata_json"])
        verification = validate_bytes(raw, "video", "application/octet-stream")
        headers = {"User-Agent": "HealthZIP-public-catalog/1.4"}
        request = urllib.request.Request(url, headers=headers, method="HEAD")
        with urllib.request.urlopen(request, timeout=90) as response:
            if response.status != 200 or int(response.headers["Content-Length"]) != len(raw):
                raise ValueError("origin size changed")
            validator = response.headers.get("ETag")
            content_md5 = response.headers.get("Content-MD5")
            digest = response.headers.get("Digest")
            modified = response.headers.get("Last-Modified")
        if not validator or validator.startswith("W/"):
            raise ValueError("origin does not supply a strong validator")
        compared = []
        for start, end in fingerprints(raw):
            request = urllib.request.Request(url, headers={
                **headers, "Range": f"bytes={start}-{end}", "If-Range": validator,
            })
            with urllib.request.urlopen(request, timeout=90) as response:
                if (response.status != 206
                        or response.headers.get("ETag") != validator
                        or response.headers.get("Content-Range") != f"bytes {start}-{end}/{len(raw)}"):
                    raise ValueError("origin range or validator changed")
                sample = response.read(end - start + 2)
            if sample != raw[start:end + 1]:
                raise ValueError("origin fingerprint mismatch")
            compared.append({"start": start, "end": end, "bytes": len(sample),
                             "sha256": hashlib.sha256(sample).hexdigest()})
        receipt = {
            "media_id": row["media_id"], "source_url": url,
            "source_uuid": metadata["source_uuid"], "snapshot_id": row["snapshot_id"],
            "checked_at": now(), "local_sha256": sha, "size": len(raw),
            "local_container_verification": verification,
            "origin_head": {"status": 200, "etag": validator, "last_modified": modified,
                            "content_length": len(raw), "content_md5": content_md5,
                            "digest": digest},
            "origin_ranges": compared,
            "recovery_basis": ["unique_size_in_full_source_snapshot",
                               "local_full_sha256_matches_content_address",
                               "complete_local_container",
                               "origin_first_middle_last_64KiB_and_complete_moov_match",
                               "same_strong_origin_validator_for_every_range"],
            "remote_whole_file_checksum_verified": False,
            "limitation": "Opaque origin ETag is not a content checksum. Remote equality "
                          "was checked for recorded ranges and complete moov, not all bytes. "
                          "The local whole-file SHA256 and container were verified.",
        }
        (receipt_root / (row["media_id"] + ".json")).write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps({"recovered_identity": row["media_id"], "bytes": len(raw)},
                         ensure_ascii=False), flush=True)
        return raw, verification["mime"]

    try:
        result = fetch_media(repo, root, downloader=recover, workers=2,
                             media_ids={row["media_id"] for row, _ in selected.values()})
        receipts = [json.loads(p.read_text()) for p in sorted(receipt_root.glob('*.json'))]
        report = {"checked_at": now(), "result": result, "recovered_receipts": receipts,
                  "recovered_bytes": sum(row["size"] for row in receipts),
                  "remote_whole_file_checksum_verified": False}
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"result": result, "recovered_bytes": report["recovered_bytes"]},
                         ensure_ascii=False), flush=True)
    finally:
        repo.close()


if __name__ == "__main__":
    main()
