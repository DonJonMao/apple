"""Resume only audit export from an already-generated synthetic report store."""
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import tempfile
import time
from contextlib import closing
from pathlib import Path

from healthzip.db.repository import Repository
from healthzip.workflows.period_report import load_report
from healthzip.workflows.report_objects import audit_bundle, reconstruct_report


def run(database, output):
    with closing(Repository(database)) as repo:
        batches = repo.rows("SELECT file_sha256 FROM import_batch")
        assert len(batches) == 1 and batches[0][0] in {
            "synthetic-100000", "synthetic-1000000", "synthetic-personal-two-years-27112026"}
        identity = repo.one("SELECT report_id FROM joint_period_report ORDER BY created_at DESC LIMIT 1")[0]
        start = time.perf_counter()
        bundle = audit_bundle(repo, identity)
        assembled = time.perf_counter()
        encoded = json.dumps(bundle, ensure_ascii=False).encode()
        with tempfile.TemporaryDirectory(prefix="hz-repair-audit-") as temporary:
            path = Path(temporary) / "frozen-audit.json"
            path.write_bytes(encoded)
            elapsed = time.perf_counter()-start
            result = {"data": "synthetic_only", "scope": "Separate export process; existing frozen report, no new analysis",
                "seconds": elapsed, "assemble_s": assembled-start,
                "serialize_and_write_s": time.perf_counter()-assembled,
                "utf8_bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest(),
                "export_process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "report_id": identity, "explicit_reports": repo.one("SELECT count(*) FROM joint_period_report")[0],
                "content_objects": len(bundle["content_objects"]), "workflow_objects": len(bundle["workflow_runs"]),
                "analysis_objects": len(bundle["analysis_objects"])}
        del encoded
        sizes = {}
        for label, table, column, id_column, ids in (
            ("content_objects", "report_content_object", "payload_json", "object_id", list(bundle["content_objects"])),
            ("workflow_objects", "workflow_run", "result_json", "run_id", list(bundle["workflow_runs"])),
            ("analysis_objects", "analysis_run", "result_json", "run_id", list(bundle["analysis_objects"])),
        ):
            sizes[label] = repo.one(f"SELECT COALESCE(SUM(length(CAST({column} AS BLOB))),0) FROM {table} "
                f"WHERE {id_column} IN (SELECT value FROM json_each(?))", (json.dumps(ids),))[0]
        result["referenced_unique_frozen_bytes"] = {**sizes, "total": sum(sizes.values())}
        # No original library, current observation reads or online source is
        # used to reconstruct this bundle. Compare the entire public payload.
        restored = reconstruct_report(bundle)
        assert restored == load_report(repo, identity)
        result["offline_reconstruction_exactly_matches_public_report"] = True
        result["global_metric_count"] = len(restored["current"]["metrics"])
        result["task_count"] = len(restored["current"]["strength_tasks"])
        result["task_source_ids"] = len({s for t in restored["current"]["strength_tasks"] for s in t["source_record_ids"]})
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.database, args.output)
