"""Isolated-source four-path report diagnostic; never opens private databases.

Use a copied, identified synthetic SQLite workspace. cProfile timings are
diagnostic, not acceptance/P95. Run generation, read and audit in separate
processes so their memory peaks and cold reads remain distinguishable.
"""
from __future__ import annotations

import argparse
import cProfile
import hashlib
import inspect
import json
import os
import platform
import pstats
import resource
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path


def encode(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--knowledge-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("generation", "read", "audit"), required=True)
    parser.add_argument("--cutoff", default="2026-11-22T00:00:00+08:00")
    parser.add_argument("--concurrent-load", required=True)
    parser.add_argument("--audit-serialization", choices=("string", "stream"), default="string")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source_root = args.source_root.resolve()
    sys.path.insert(0, str(source_root / "src"))
    from healthzip.analytics.cache import clear
    from healthzip.db.repository import Repository
    from healthzip.workflows.period_report import create_report, load_report
    from healthzip.workflows.report_objects import audit_bundle, reconstruct_report

    assert Path(inspect.getfile(create_report)).resolve().is_relative_to(source_root)
    assert args.database.resolve().is_relative_to(Path("/tmp")), "isolated synthetic copy required"
    with closing(sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        batches = connection.execute("SELECT file_sha256 FROM import_batch").fetchall()
        assert len(batches) == 1 and batches[0][0] in {
            "synthetic-100000", "synthetic-1000000", "synthetic-personal-two-years-27112026"}
    hashes = {str(p.relative_to(source_root)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (source_root / "src").rglob("*.py")}
    (args.output / f"{args.phase}-source-manifest.json").write_text(encode(hashes))
    output = {
        "diagnostic_only": True, "instrumentation": "cProfile enabled; no P95 claim",
        "source_root": str(source_root), "source_manifest": f"{args.phase}-source-manifest.json",
        "profiler_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "archive_identity": json.loads((source_root / "archive-identity.json").read_text())
            if (source_root / "archive-identity.json").exists() else None,
        "synthetic_fixture": batches[0][0], "cutoff": args.cutoff,
        "phase": args.phase, "concurrent_load": args.concurrent_load,
        "audit_serialization": args.audit_serialization,
        "platform": platform.platform(), "logical_cpu": os.cpu_count(),
        "memory": Path("/proc/meminfo").read_text().splitlines()[0],
        "python": platform.python_version(), "initial_host_load": os.getloadavg(),
        "os_file_cache": "retained", "remote_model": "not used", "runs": [],
    }
    destination = args.output / f"{args.phase}.json"
    destination.write_text(encode(output))
    clear()
    with closing(Repository(args.database)) as repo:
        output["sizes"] = {table: repo.one(f"SELECT count(*) FROM {table}")[0] for table in
                           ("health_sample", "source_revision", "strength_session", "strength_set", "training_event")}
        observed = {"queries": 0, "json_bytes": 0, "tables": {}}
        original_one = repo.one

        def one(sql, *params, **kwargs):
            result = original_one(sql, *params, **kwargs)
            if result is not None and ("payload_json" in sql or "result_json" in sql):
                values = list(result)
                size = sum(len(value.encode()) for value in values if isinstance(value, str))
                table = next((t for t in ("report_content_object", "analysis_run", "workflow_run", "joint_period_report")
                              if t in sql), "other")
                observed["queries"] += 1
                observed["json_bytes"] += size
                observed["tables"][table] = observed["tables"].get(table, 0) + size
            return result

        repo.one = one

        def timed(label, operation):
            observed.update(queries=0, json_bytes=0, tables={})
            stages = []
            start = time.perf_counter()

            def progress(stage):
                item = {"stage": stage, "elapsed_s": time.perf_counter() - start}
                stages.append(item)
                output["active"] = {"label": label, **item}
                destination.write_text(encode(output))
                print(label, item, flush=True)

            profile = cProfile.Profile()
            profile.enable()
            try:
                result = operation(progress)
            finally:
                profile.disable()
                elapsed = time.perf_counter() - start
                profile.dump_stats(str(args.output / f"{label}.prof"))
                stats = pstats.Stats(profile)
                ranked = sorted(stats.stats.items(), key=lambda pair: pair[1][3], reverse=True)[:60]
                (args.output / f"{label}-hotspots.json").write_text(encode([
                    {"file": file, "line": line, "function": function,
                     "primitive_calls": values[0], "calls": values[1],
                     "self_s": values[2], "cumulative_s": values[3]}
                    for (file, line, function), values in ranked]))
                output["runs"].append({"label": label, "seconds": elapsed, "stages": stages,
                    "repo_one_json_reads": dict(observed),
                    "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
                output.pop("active", None)
                destination.write_text(encode(output))
                print(label, "finished", elapsed, flush=True)
            return result

        if args.phase == "generation":
            fields = {"cutoff_time": args.cutoff, "timezone": "Asia/Shanghai", "selection_context": {}}
            ids = []
            for label in ("cold-generation", "hot-generation"):
                report = timed(label, lambda progress: create_report(repo, fields, period="week",
                               knowledge_root=args.knowledge_root, progress=progress))
                assert report["markdown"] and report["cutoff_time"] == args.cutoff
                ids.append(report["report_id"])
                output["runs"][-1].update(report_id=report["report_id"],
                    markdown_utf8_bytes=len(report["markdown"].encode()),
                    public_top_level_keys=list(report))
                if "current" in report:
                    current = report["current"]
                    assert len(current["metrics"]) == 77
                    tasks = current["strength_tasks"]
                    source_ids = {identity for task in tasks for identity in task.get("source_record_ids", [])}
                    if output["sizes"]["strength_set"] == 10000:
                        assert len(tasks) == 10000 and len(source_ids) == 10000
                    output["runs"][-1].update(task_count=len(tasks), task_source_ids=len(source_ids))
                del report
            assert len(set(ids)) == 2
            output["distinct_explicit_report_ids"] = ids
        else:
            report_id = repo.one("SELECT report_id FROM joint_period_report ORDER BY created_at DESC LIMIT 1")[0]
            output["report_id"] = report_id
            if args.phase == "read":
                for label in ("cold-open", "hot-open"):
                    options = {"include_details": False} if "include_details" in inspect.signature(load_report).parameters else {}
                    report = timed(label, lambda progress: load_report(repo, report_id, **options))
                    assert report["report_id"] == report_id and report["markdown"]
                    output["runs"][-1]["public_top_level_keys"] = list(report)
                    output["runs"][-1]["markdown_utf8_bytes"] = len(report["markdown"].encode())
                    del report
            else:
                export_path = args.database.parent / f"{args.database.stem}-audit.json"

                def export(progress):
                    progress("读取冻结对象")
                    bundle = audit_bundle(repo, report_id)
                    progress("序列化并写入离线包")
                    if args.audit_serialization == "stream":
                        with export_path.open("w") as target:
                            json.dump(bundle, target, ensure_ascii=False)
                    else:
                        export_path.write_bytes(json.dumps(bundle, ensure_ascii=False).encode())
                    return bundle

                bundle = timed("audit-export", export)
                output["audit_utf8_bytes"] = export_path.stat().st_size
                output["unique_objects"] = {key: len(bundle[key]) for key in
                    ("content_objects", "workflow_runs", "analysis_objects")}
                sizes = {}
                for label, table, column, id_column, ids in (
                    ("content_objects", "report_content_object", "payload_json", "object_id", list(bundle["content_objects"])),
                    ("workflow_objects", "workflow_run", "result_json", "run_id", list(bundle["workflow_runs"])),
                    ("analysis_objects", "analysis_run", "result_json", "run_id", list(bundle["analysis_objects"])),
                ):
                    sizes[label] = repo.one(f"SELECT COALESCE(SUM(length(CAST({column} AS BLOB))),0) FROM {table} "
                        f"WHERE {id_column} IN (SELECT value FROM json_each(?))", (json.dumps(ids),))[0]
                output["unique_frozen_bytes"] = {**sizes, "total": sum(sizes.values())}
                restored = timed("audit-offline-reconstruction", lambda progress: reconstruct_report(bundle))
                options = {"include_details": True} if "include_details" in inspect.signature(load_report).parameters else {}
                assert restored == load_report(repo, report_id, **options)
                output["offline_reconstruction_matches_frozen_report"] = True
                output["audit_file"] = str(export_path)
        output["complete"] = True
        output["final_host_load"] = os.getloadavg()
        output["source_changes_during_run"] = [name for name, digest in hashes.items()
            if hashlib.sha256((source_root / name).read_bytes()).hexdigest() != digest]
        destination.write_text(encode(output))


if __name__ == "__main__":
    main()
