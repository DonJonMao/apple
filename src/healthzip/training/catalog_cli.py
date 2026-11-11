"""Explicit networking and publication commands: python -m healthzip.training.catalog_cli."""

import argparse
import json

from healthzip.db.repository import Repository

from .catalog_import import (
    coverage,
    diff_snapshots,
    fetch_snapshot,
    publish_snapshot,
    validate_snapshot,
)
from .catalog_media import fetch_media, offline_package


def main():
    parser = argparse.ArgumentParser(description="HealthZIP 本地公共动作目录")
    parser.add_argument(
        "action", choices=["fetch", "validate", "publish", "coverage", "diff", "media", "offline"]
    )
    parser.add_argument("--snapshot")
    parser.add_argument("--previous")
    parser.add_argument("--db", default=".local/healthzip.sqlite3")
    parser.add_argument("--root", default=".local/catalog")
    parser.add_argument("--output", default=".local/catalog/HealthZIP-catalog-offline.zip")
    parser.add_argument("--text-only", action="store_true")
    args = parser.parse_args()
    if args.action == "fetch":
        result = {"snapshot_path": str(fetch_snapshot(args.root + "/snapshots"))}
    elif args.action == "validate":
        result = validate_snapshot(args.snapshot)[0]
    elif args.action == "diff":
        result = diff_snapshots(args.previous, args.snapshot)
    else:
        repo = Repository(args.db)
        try:
            if args.action == "publish":
                result = publish_snapshot(repo, args.snapshot)
            elif args.action == "media":
                result = fetch_media(repo, args.root + "/blobs")
            elif args.action == "offline":
                result = offline_package(repo, args.output, include_media=not args.text_only)
            else:
                result = coverage(repo)
        finally:
            repo.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
