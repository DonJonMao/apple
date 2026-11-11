"""Build and verify public offline packages from one frozen catalog snapshot."""

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from zipfile import ZipFile

from healthzip.db.repository import Repository
from healthzip.training.catalog_import import now
from healthzip.training.catalog_media import offline_package


def sha256(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".local/catalog/catalog.sqlite3")
    parser.add_argument("--root", default=".local/catalog")
    parser.add_argument("--output", default="artifacts/v14/catalog/offline-package.json")
    args = parser.parse_args()
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    report = {"packages": []}
    with tempfile.TemporaryDirectory(prefix="catalog-package-", dir=root) as folder:
        frozen = Path(folder) / "catalog.sqlite3"
        with sqlite3.connect(f"file:{Path(args.db).resolve()}?mode=ro", uri=True) as original:
            with sqlite3.connect(frozen) as copied:
                original.backup(copied)
        repo = Repository(frozen)
        try:
            pending = repo.conn.execute(
                "SELECT COUNT(*) FROM catalog_media WHERE fetch_status!='ready'"
            ).fetchone()[0]
            ready = dict(repo.conn.execute(
                "SELECT media_type,COUNT(*) FROM catalog_media WHERE fetch_status='ready' "
                "GROUP BY media_type"
            ))
            candidates = []
            for name, include_media in [("HealthZIP-catalog-offline", True),
                                        ("HealthZIP-catalog-text-only", False)]:
                candidate = Path(folder) / (name + ".zip")
                result = offline_package(repo, candidate, include_media=include_media)
                with ZipFile(candidate) as archive:
                    assert archive.testzip() is None
                    catalog = json.loads(archive.read("catalog.json"))
                    entries = [entry for item in catalog["items"] for entry in item["media"]]
                    included = [entry for entry in entries if entry.get("package_path")]
                    assert all(entry["fetch_status"] == "ready" for entry in included)
                    assert all(entry["package_path"] in archive.namelist() for entry in included)
                    for member in archive.namelist():
                        if member.startswith("media/"):
                            with archive.open(member) as stream:
                                assert sha256(stream) == member[6:]
                    count = sum(name.startswith("media/") for name in archive.namelist())
                with candidate.open("rb") as stream:
                    sha = sha256(stream)
                result.update({
                    "filename": name + ".zip", "text_only": not include_media,
                    "format": "ZIP with complete public catalog and per-object attribution",
                    "bytes": candidate.stat().st_size, "sha256": sha,
                    "unique_media_files": count, "corrupt_member": None,
                    "all_referenced_package_paths_exist": True,
                    "all_packaged_media_sha256_match": True, "private_data_included": False,
                    "pending_media_count": pending, "catalog_ready_media": ready,
                    "created_at": now(), "recovery_evidence": "cache-recovery.json",
                    "remote_whole_file_checksum_verified_for_recovered_blobs": False,
                })
                report["packages"].append(result)
                candidates.append((candidate, root / (name + ".zip")))
            # Every candidate passes full CRC and SHA256 checks before publication.
            for candidate, final in candidates:
                candidate.replace(final)
            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps(report, ensure_ascii=False), flush=True)
        finally:
            repo.close()


if __name__ == "__main__":
    main()
