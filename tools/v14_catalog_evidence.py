"""Export public catalog acquisition/rights evidence, never private training tables."""

import argparse
import json
from pathlib import Path

from jsonschema import validate

from healthzip.db.repository import Repository
from healthzip.training.catalog_import import coverage, digest, public_catalog, validate_snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=".local/catalog/catalog.sqlite3")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output", default="artifacts/v14/catalog")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    manifest, objects = validate_snapshot(args.snapshot)
    repo = Repository(args.db)
    report = coverage(repo)
    items = public_catalog(repo)["items"]
    schema = json.loads(Path("src/healthzip/training/catalog.schema.json").read_text())
    checked = 0
    for item in items:
        if item.get("source", {}).get("provider") == "wger":
            validate(item, schema)
            checked += 1
    media = []
    for row in repo.conn.execute("SELECT * FROM catalog_media ORDER BY media_id"):
        meta = json.loads(row["metadata_json"])
        media.append(
            {
                **meta,
                "snapshot_id": row["snapshot_id"],
                "fetch_status": row["fetch_status"],
                "local_blob_sha256": row["blob_hash"],
                "license_allowed": bool(row["license_allowed"]),
                "verified_at": row["verified_at"],
                "error": row["error"],
            }
        )
    languages = {x["id"]: x["short_name"] for x in objects["language"]}
    report["raw_upstream_chinese_translations"] = sum(
        languages[x["language"]].startswith("zh") for x in objects["exercise-translation"]
    )
    report["page_count"] = sum(len(x["pages"]) for x in manifest["endpoints"].values())
    report["manifest_sha256"] = digest(manifest)
    report["schema_validation"] = {"validated_source_exercises": checked, "failures": 0}
    report["downloaded_bytes"] = sum(
        x.get("verified_file", {}).get("size", 0) for x in media if x["fetch_status"] == "ready"
    )
    products = {
        "manifest.json": manifest,
        "coverage.json": report,
        "media-manifest.json": media,
        "chinese-names.json": [
            {
                "exercise_id": x["exercise_id"],
                "names": x.get("names"),
                "source_uuid": x.get("source", {}).get("source_uuid"),
            }
            for x in items
            if x.get("source")
        ],
        "legacy-46-mapping.json": json.loads(
            Path("src/healthzip/training/catalog_legacy_mapping.json").read_text()
        ),
    }
    for name, value in products.items():
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    repo.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
