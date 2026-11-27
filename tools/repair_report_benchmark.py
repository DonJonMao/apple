"""End-to-end cold and repeated explicit report generation, using synthetic records."""

import argparse
import hashlib
import inspect
import json
import os
import platform
import resource
import signal
import sqlite3
import statistics
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

from healthzip.analytics.cache import clear
from healthzip.db.repository import Repository
from healthzip.workflows.period_report import create_report
from healthzip.workflows.report_objects import audit_bundle, reconstruct_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-root", type=Path, required=True)
    parser.add_argument("--synthetic", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warm", type=int, default=30)
    parser.add_argument("--period", choices=("week", "month"), default="week")
    parser.add_argument("--max-seconds", type=float, default=0, help="Bound each run; retain incomplete phase evidence on timeout")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from health_change_fixture import CUTOFF, create_health_change_fixture

    with tempfile.TemporaryDirectory(prefix="hz-report-scale-") as temporary:
        path = Path(temporary) / "synthetic.sqlite3"
        if args.synthetic:
            with closing(sqlite3.connect(args.synthetic.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                batches = source.execute("SELECT file_sha256 FROM import_batch").fetchall()
                assert len(batches) == 1 and batches[0][0] in {"synthetic-100000", "synthetic-1000000", "synthetic-personal-two-years-27112026"}
                with closing(sqlite3.connect(path)) as dest:
                    source.backup(dest)
        else:
            create_health_change_fixture(path)
        stages = []
        start = None
        output = None

        def progress(stage):
            if start:
                elapsed = time.perf_counter() - start
                stages.append({"begin_s": elapsed, "stage": stage})
                print(f"{elapsed:.3f} {stage}", flush=True)
                if output is not None:
                    output["active_run"] = {"elapsed_s": elapsed, "stages": stages}
                    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2))

        clear()
        with closing(Repository(path)) as repo:
            counts = {key: repo.one(f"SELECT COUNT(*) FROM {key}")[0] for key in
                      ("health_sample", "source_revision", "strength_session", "strength_set", "training_event")}
            output = {"kind": "complete_local_report_no_remote_model", "data": "synthetic_only",
                      "method": "fresh process and copied synthetic workspace; includes all local retrieval, verification, report rendering and freezing. OS cache retained on shared host.",
                      "period": args.period, "cutoff": CUTOFF, "sizes": counts, "database_bytes": path.stat().st_size,
                      "platform": platform.platform(), "logical_cpu": os.cpu_count(), "python": platform.python_version(),
                      "host_mem": Path("/proc/meminfo").read_text().splitlines()[0],
                      "knowledge": "frozen copy of the same public Sources and Theories libraries",
                      "period_report_source_sha256": hashlib.sha256(Path(inspect.getfile(create_report)).read_bytes()).hexdigest(),
                      "report_json_decoder": getattr(getattr(sys.modules[create_report.__module__], "orjson", None), "__version__", "stdlib"),
                      "cold_runs": [], "warm_runs_seconds": []}
            from master_regression import digest, source_files
            output["source_before"] = digest(source_files())
            output["concurrent_load"] = "No other HealthZIP performance/full-suite work scheduled; shared host load is uncontrolled"
            output["initial_loadavg"] = list(os.getloadavg())
            fields = {"cutoff_time": CUTOFF, "timezone": "Asia/Shanghai", "selection_context": {}}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2))
            def timed_out(signum, frame):
                raise TimeoutError("complete_report_run_time_limit")
            signal.signal(signal.SIGALRM, timed_out)
            for i in range(1 + args.warm):
                stages = []
                start = time.perf_counter()
                if args.max_seconds:
                    signal.setitimer(signal.ITIMER_REAL, args.max_seconds)
                try:
                    call = {"period": args.period, "knowledge_root": args.knowledge_root}
                    if "progress" in inspect.signature(create_report).parameters:
                        call["progress"] = progress
                    report = create_report(repo, fields, **call)
                except (TimeoutError, KeyboardInterrupt, ValueError) as exc:
                    output["incomplete_run"] = {"run": i, "seconds": time.perf_counter()-start,
                        "stages": stages, "reason": type(exc).__name__ + ":" + str(exc), "complete_report_delivered": False}
                    output["max_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2))
                    return
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                elapsed = time.perf_counter() - start
                assert report["markdown"] and report["cutoff_time"] == CUTOFF
                assert len(report["current"]["metrics"]) == 77
                if counts["strength_set"] == 10000:
                    assert len(report["current"]["strength_tasks"]) == 10000
                    assert len({source for task in report["current"]["strength_tasks"] for source in task.get("source_record_ids", [])}) == 10000
                assert {q["id"] for q in report["questions"]} == {"W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8", "E"}
                last_report_id = report["report_id"]
                if i:
                    output["warm_runs_seconds"].append(elapsed)
                else:
                    byte_sizes = repo.one("SELECT length(CAST(payload_json AS BLOB)),length(CAST(markdown AS BLOB)) "
                        "FROM joint_period_report WHERE report_id=?", (report["report_id"],))
                    output["cold_runs"].append({"seconds": elapsed, "stages": stages,
                        "markdown_chars": len(report["markdown"]), "current_runs": len(report["workflow_run_ids"]),
                        "frozen_payload_bytes": byte_sizes[0], "markdown_utf8_bytes": byte_sizes[1],
                        "previous_runs": len(report["historical_run_ids"]),
                        "global_metric_count": len(report["current"]["metrics"]),
                        "task_count": len(report["current"]["strength_tasks"]),
                        "task_metric_results": sum(len(t["metrics"]) for t in report["current"]["strength_tasks"]),
                        "task_source_ids": len({source for t in report["current"]["strength_tasks"] for source in t.get("source_record_ids", [])})})
                output.pop("active_run", None)
                output["max_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                del report
                vals = output["warm_runs_seconds"]
                if vals:
                    output["hot_p50_s"] = statistics.median(vals)
                    output["hot_p95_s"] = sorted(vals)[min(len(vals)-1, int(len(vals)*.95))]
                args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2))
                print("finished", i, elapsed, flush=True)
            output["readable_generation_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            export_start = time.perf_counter()
            bundle = audit_bundle(repo, last_report_id)
            assembled = time.perf_counter()
            encoded = json.dumps(bundle, ensure_ascii=False).encode()
            export_path = Path(temporary) / "frozen-audit.json"
            export_path.write_bytes(encoded)
            export_end = time.perf_counter()
            output["audit_export"] = {"seconds": export_end-export_start,
                "assemble_s": assembled-export_start, "serialize_and_write_s": export_end-assembled,
                "utf8_bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest(),
                "content_objects": len(bundle["content_objects"]), "workflow_objects": len(bundle["workflow_runs"]),
                "analysis_objects": len(bundle["analysis_objects"]),
                "peak_rss_kib_including_generation": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
            del encoded
            unique_sizes = {}
            for label, table, column, id_column, ids in (
                ("content_objects", "report_content_object", "payload_json", "object_id", list(bundle["content_objects"])),
                ("workflow_objects", "workflow_run", "result_json", "run_id", list(bundle["workflow_runs"])),
                ("analysis_objects", "analysis_run", "result_json", "run_id", list(bundle["analysis_objects"])),
            ):
                unique_sizes[label] = repo.one(f"SELECT COALESCE(SUM(length(CAST({column} AS BLOB))),0) FROM {table} WHERE {id_column} IN (SELECT value FROM json_each(?))", (json.dumps(ids),))[0]
            output["referenced_unique_frozen_bytes"] = {**unique_sizes, "total": sum(unique_sizes.values()),
                "scope": "All frozen objects required by the last report, once each; manifest and readable Markdown reported separately. Not the entire database size."}
            from healthzip.workflows.period_report import load_report
            restored = reconstruct_report(bundle)
            assert restored == load_report(repo, last_report_id)
            output["audit_export"]["offline_reconstruction_exactly_matches_public_report"] = True
            output["distinct_explicit_reports"] = repo.one("SELECT count(*) FROM joint_period_report")[0]
            output["budget_results"] = {"cold_le_15s": output["cold_runs"][0]["seconds"] <= 15,
                "hot_30_p95_le_3s": len(output["warm_runs_seconds"]) >= 30 and output["hot_p95_s"] <= 3}
            output["source_changes_during_run"] = [name for name, value in digest(source_files()).items()
                if output["source_before"].get(name) != value]
            output["final_loadavg"] = list(os.getloadavg())
            args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2))
            print("complete", output["budget_results"], output["audit_export"], flush=True)


if __name__ == "__main__":
    main()
