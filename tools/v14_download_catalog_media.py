"""Continue public media downloads, preserving valid partial files across runs.

Run explicitly; this accesses only public wger media. A filesystem lock prevents
duplicate workers. The local run receipt records a PID, not proof of liveness.
"""

import argparse
import fcntl
import json
import os
from pathlib import Path

from healthzip.db.repository import Repository
from healthzip.training.catalog_import import now
from healthzip.training.catalog_media import fetch_media


def emit(event):
    print(json.dumps({"time": now(), **event}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".local/catalog/catalog.sqlite3")
    parser.add_argument("--root", default=".local/catalog/blobs")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    with (root.parent / "media-download.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        repo = Repository(args.db)
        try:
            pending = [dict(row) for row in repo.conn.execute(
                "SELECT media_id,metadata_json FROM catalog_media WHERE license_allowed=1 "
                "AND fetch_status NOT IN ('ready','withdrawn')"
            )]
            ordered = sorted(pending, key=lambda r: json.loads(r["metadata_json"]).get("upstream_size") or 0)
            emit({"event": "started", "pid": os.getpid(), "workers": args.workers,
                  "remaining_objects": len(ordered),
                  "order": [r["media_id"] for r in ordered]})

            def progress(result):
                emit({"event": "media_result", "media_id": result["media_id"],
                      "status": result["status"], "sha256": result.get("hash"),
                      "bytes": result.get("verification", {}).get("size"),
                      "error": result.get("error")})

            result = fetch_media(repo, root, workers=args.workers,
                                 media_ids={r["media_id"] for r in pending}, progress=progress)
            emit({"event": "finished", **result})
        finally:
            repo.close()


if __name__ == "__main__":
    main()
