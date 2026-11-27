"""Read-only byte accounting of a retained synthetic completed benchmark copy."""
import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path


def references(value):
    if isinstance(value, dict):
        if set(value) == {"$frozen_object"}:
            yield value["$frozen_object"]
        else:
            for child in value.values():
                yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    assert not args.output.exists(), "Keep prior byte accounting"
    with closing(sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        marker = connection.execute("SELECT file_sha256 FROM import_batch").fetchall()
        assert len(marker) == 1 and marker[0][0] in {
            "synthetic-100000", "synthetic-1000000", "synthetic-personal-two-years-27112026"}
        objects = {identity: {"kind": kind, "json": payload, "bytes": size}
                   for identity, kind, payload, size in connection.execute(
                       "SELECT object_id,kind,payload_json,length(CAST(payload_json AS BLOB)) FROM report_content_object")}

        def closure(identities):
            found, pending = set(), list(identities)
            while pending:
                identity = pending.pop()
                if identity in found:
                    continue
                found.add(identity)
                pending.extend(references(json.loads(objects[identity]["json"])))
            return found

        def sizes(identities):
            result = defaultdict(lambda: {"objects": 0, "utf8_bytes": 0})
            for identity in identities:
                item = objects[identity]
                result[item["kind"]]["objects"] += 1
                result[item["kind"]]["utf8_bytes"] += item["bytes"]
            return dict(sorted(result.items()))

        report_roots = set()
        reports = list(connection.execute("SELECT payload_json FROM joint_period_report"))
        for (encoded,) in reports:
            manifest = json.loads(encoded)
            report_roots.update(references(manifest))
            report_roots.update(manifest[key] for key in ("content_ref", "reading_ref") if manifest.get(key))
        report_objects = closure(report_roots)
        workflows, workflow_roots = [], set()
        for identity, encoded in connection.execute("SELECT run_id,result_json FROM workflow_run ORDER BY run_id"):
            stored = json.loads(encoded)
            workflow_roots.update(references(stored))
            inline_bytes = len(encoded.encode())
            row = {"run_id": identity, "storage_format": stored.get("storage_format", "legacy_inline"),
                   "compact_utf8_bytes": inline_bytes}
            if stored.get("storage_format") == "workflow-training-references-1":
                ordinary_ref = stored["supplements"]["ordinary_training"]["$frozen_object"]
                ordinary = json.loads(objects[ordinary_ref]["json"])
                series_refs = ordinary.get("series", [])
                row.update(ordinary_root=ordinary_ref, series_entries=len(series_refs),
                           distinct_series_objects=len({ref["$frozen_object"] for ref in series_refs}),
                           ordinary_record_count=ordinary.get("record_count"))
                if "series" in ordinary:
                    ordinary["series"] = [json.loads(objects[ref["$frozen_object"]]["json"]) for ref in series_refs]
                expanded = {key: value for key, value in stored.items() if key != "storage_format"}
                expanded["supplements"] = {**stored["supplements"], "ordinary_training": ordinary}
                inline_bytes = len(json.dumps(expanded, ensure_ascii=False, sort_keys=True, allow_nan=False).encode())
            row["equivalent_legacy_inline_utf8_bytes"] = inline_bytes
            workflows.append(row)
        workflow_objects = closure(workflow_roots)
        exclusive = workflow_objects - report_objects
        compact = sum(row["compact_utf8_bytes"] for row in workflows)
        inline = sum(row["equivalent_legacy_inline_utf8_bytes"] for row in workflows)
        all_object_bytes = sum(item["bytes"] for item in objects.values())
        exclusive_bytes = sum(objects[identity]["bytes"] for identity in exclusive)
        conservative_net = inline - compact - sum(objects[identity]["bytes"] for identity in workflow_objects)
        result = {
            "label": args.label, "database": str(args.database), "synthetic_marker": marker,
            "read_only": True, "source_prose_exported": False, "workflow_rows": workflows,
            "workflow_result_json_utf8_bytes": compact, "equivalent_inline_workflow_utf8_bytes": inline,
            "all_content_objects_by_kind": sizes(objects), "workflow_referenced_objects_by_kind": sizes(workflow_objects),
            "report_shared_workflow_objects_by_kind": sizes(workflow_objects & report_objects),
            "workflow_only_objects_by_kind": sizes(exclusive), "report_count": len(reports),
            "actual_workflow_and_content_utf8_bytes": compact + all_object_bytes,
            "same_results_inline_counterfactual_utf8_bytes": inline + all_object_bytes - exclusive_bytes,
            "net_utf8_bytes_saved": inline - compact - exclusive_bytes,
            "conservative_saving_charging_all_workflow_objects": conservative_net,
            "counterfactual": "Expand these same final workflows using the previous strict sorted stdlib JSON options; retain every report-reachable and other existing content object, omit only objects referenced exclusively by compact workflows.",
            "scope": "UTF-8 payload bytes, not SQLite allocated pages/WAL/RSS or runtime; unchanged analysis rows cancel on both sides. No original fixture or historical report is rewritten.",
            "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("label", "workflow_result_json_utf8_bytes",
        "equivalent_inline_workflow_utf8_bytes", "net_utf8_bytes_saved", "conservative_saving_charging_all_workflow_objects")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
