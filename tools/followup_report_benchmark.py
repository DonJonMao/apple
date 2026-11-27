"""Complete report generation, ordinary reading and audit acceptance.

Every phase runs in a separate process against one private copy of an identified
synthetic fixture. Report generation freezes a new identity on every request.
No timings here are described as browser/physical-device measurements.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import os
import platform
import resource
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = {"synthetic-100000", "synthetic-1000000", "synthetic-personal-two-years-27112026"}
RAW_TABLES = ("health_sample", "source_revision", "strength_session", "strength_set",
              "training_event", "training_session_exercise", "subjective_log", "body_measurement")


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def manifest():
    paths = [ROOT / "app.py", ROOT / "pyproject.toml", ROOT / "uv.lock", ROOT / ".streamlit/config.toml"]
    paths += [ROOT / path for path in ("tools/followup_report_benchmark.py",
        "tools/followup_page_benchmark.py", "tools/followup_report_browser_benchmark.py",
        "tools/repair_preview_benchmark.py", "tools/repair_measure_run.py",
        "tests/training/strength_workbench_browser_check.py", "tests/training/strength_browser_fixture.py")]
    paths += [p for p in (ROOT / "src").rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def raw_identity(connection):
    result = {}
    for table in RAW_TABLES:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            continue
        digest, count = hashlib.sha256(), 0
        # SQLite's stable rowid order does not reinterpret timestamps/conditions.
        for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid"):
            digest.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode())
            digest.update(b"\n")
            count += 1
        result[table] = {"rows": count, "sha256": digest.hexdigest()}
    return result


def validate_synthetic(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        batches = connection.execute("SELECT file_sha256 FROM import_batch").fetchall()
        assert len(batches) == 1 and batches[0][0] in SYNTHETIC
        return batches[0][0]


def shared_knowledge(path, *, prepare=False):
    """Explicitly reuse only a temporary public copy, never the user's library."""
    path = path.resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    assert path != temporary and path.is_relative_to(temporary), "shared public knowledge must be a dedicated temporary directory"
    for name in ("sources.sqlite3", "theories.sqlite3"):
        source = path / name
        assert source.is_file() and source.resolve().is_relative_to(temporary), "both shared databases must be temporary copies"
    from healthzip.knowledge.revisions import knowledge_authority_clock, prepare_retrieval_revisions
    if prepare:
        from healthzip.knowledge.workbench import KnowledgeWorkbench
        with closing(KnowledgeWorkbench(path)) as workbench:
            prepare_retrieval_revisions(workbench)
    identity = json.loads(json.dumps(knowledge_authority_clock(path)))
    assert not any("uninitialized" in row or "unavailable" in row for row in identity[2:]), "shared authority tracking must be initialized"
    return identity


def percentiles(samples):
    values = sorted(row["seconds"] for row in samples)
    return {"n": len(values), "p50_s": values[math.ceil(len(values) * .5) - 1],
            "p95_s": values[math.ceil(len(values) * .95) - 1], "method": "nearest-rank"}


def worker(args):
    from healthzip.analytics.cache import clear
    from healthzip.db.repository import Repository
    from healthzip.workflows.period_report import create_report, load_report
    from healthzip.workflows.report_objects import audit_bundle, reconstruct_report

    source_before = manifest()
    result = {"phase": args.worker_phase, "synthetic_fixture": validate_synthetic(args.database),
              "source_manifest": f"{args.worker_phase}-source.json", "samples": [],
              "cutoff": args.cutoff, "period": args.period, "timezone": "Asia/Shanghai",
              "interface": "backend complete service call; browser timings are separate",
              "initial_host_load": os.getloadavg(), "concurrent_load": args.concurrent_load,
              "instrumentation": "perf_counter only; no cProfile", "os_cache": "retained"}
    destination = args.output / f"{args.worker_phase}.json"
    write(args.output / result["source_manifest"], source_before)
    write(destination, result)
    clear()
    with closing(Repository(args.database)) as repo:
        def measure(label, function, *, save_stages=False):
            stages = []
            start = time.perf_counter()

            def progress(stage):
                stages.append({"stage": stage, "elapsed_s": time.perf_counter() - start})
                if save_stages:
                    result["active"] = {"label": label, "stages": stages}
                    write(destination, result)
                    print(label, stages[-1], flush=True)

            value = function(progress)
            sample = {"label": label, "seconds": time.perf_counter() - start,
                      "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
            if save_stages:
                sample["stages"] = stages
            result["samples"].append(sample)
            result.pop("active", None)
            write(destination, result)
            print(label, sample["seconds"], flush=True)
            return value, sample

        details_option = {"include_details": True} if "include_details" in inspect.signature(load_report).parameters else {}
        summary_option = {"include_details": False} if details_option else {}
        if args.worker_phase == "generation":
            fields = {"cutoff_time": args.cutoff, "timezone": "Asia/Shanghai", "selection_context": {}}
            initial = repo.one("SELECT count(*) FROM joint_period_report")[0] if repo.one(
                "SELECT 1 FROM sqlite_master WHERE name='joint_period_report'") else 0
            ids = []
            for index in range(args.warm + 1):
                report, sample = measure("cold" if index == 0 else f"warm-{index:02}",
                    lambda progress: create_report(repo, fields, period=args.period,
                        knowledge_root=args.knowledge_root, progress=progress), save_stages=index == 0)
                identity = report["report_id"]
                assert identity not in ids and report["markdown"] and report["cutoff_time"] == args.cutoff
                ids.append(identity)
                # Small manifest verification is outside the timed service call.
                saved = repo.one("SELECT payload_json,markdown FROM joint_period_report WHERE report_id=?", (identity,))
                assert saved and saved[1] == report["markdown"]
                payload = json.loads(saved[0])
                sample.update(report_id=identity, markdown_utf8_bytes=len(saved[1].encode()),
                              manifest_utf8_bytes=len(saved[0].encode()),
                              storage_format=payload.get("storage_format"),
                              content_ref=payload.get("content_ref"), reading_ref=payload.get("reading_ref"),
                              reading_view=report.get("reading_view"),
                              current_full_analysis_returned="current" in report)
                del report
                write(destination, result)
            assert repo.one("SELECT count(*) FROM joint_period_report")[0] - initial == len(ids)
            result["new_explicit_report_ids"] = ids
            result["warm"] = percentiles(result["samples"][1:])
            result["budgets"] = {"cold_le_15s": result["samples"][0]["seconds"] <= 15,
                                 "warm_30_p95_le_3s": args.warm >= 30 and result["warm"]["p95_s"] <= 3}
        elif args.worker_phase == "read":
            identity = repo.one("SELECT report_id FROM joint_period_report ORDER BY created_at DESC LIMIT 1")[0]
            result["report_id"] = identity
            # Trace reads, never query values; ordinary opening must not touch full analyses.
            queries = []
            repo.conn.set_trace_callback(queries.append)
            for index in range(args.warm + 1):
                queries.clear()
                report, sample = measure("cold" if index == 0 else f"warm-{index:02}",
                    lambda progress: load_report(repo, identity, **summary_option))
                assert report["report_id"] == identity and report["markdown"]
                sample.update(reading_view_version=(report.get("reading_view") or {}).get("version"),
                              full_analysis_returned="current" in report,
                              query_count=len(queries),
                              full_analysis_read=any("FROM analysis_run" in q or "FROM workflow_run" in q for q in queries))
                if summary_option:
                    assert not sample["full_analysis_returned"] and not sample["full_analysis_read"]
                if index == 0:
                    result["cold_queries"] = list(queries)
                    result["reading_payload_utf8_bytes"] = len(json.dumps(report, ensure_ascii=False).encode())
                if index != args.warm:
                    del report
                write(destination, result)
            repo.conn.set_trace_callback(None)
            result["warm"] = percentiles(result["samples"][1:])
            result["budgets"] = {"cold_le_3s": result["samples"][0]["seconds"] <= 3,
                                 "warm_30_p95_le_1s": args.warm >= 30 and result["warm"]["p95_s"] <= 1}
            if summary_option:
                from healthzip.workflows.report_objects import read_question
                question = next(q for q in report["questions"] if q["id"] == "W6")
                queries.clear()
                repo.conn.set_trace_callback(queries.append)
                detail, sample = measure("one-question-W6", lambda progress: read_question(repo, question))
                repo.conn.set_trace_callback(None)
                assert detail["id"] == question["id"]
                sample.update(question_id=detail["id"], fact_id=detail.get("fact_id"), queries=list(queries))
                assert not any("FROM analysis_run" in q or "FROM workflow_run" in q for q in queries)
        else:
            identity = repo.one("SELECT report_id FROM joint_period_report ORDER BY created_at DESC LIMIT 1")[0]
            result["report_id"] = identity
            export_path = args.database.parent / "audit.json"

            def export(progress):
                progress("assemble_frozen_objects")
                bundle = audit_bundle(repo, identity)
                progress("serialize_and_write")
                # Match the current UI's actual stdlib string serializer. File
                # writing is included; remote/browser transfer is measured apart.
                export_path.write_bytes(json.dumps(bundle, ensure_ascii=False).encode())
                return bundle

            bundle, sample = measure("export", export, save_stages=True)
            sample["export_bytes"] = export_path.stat().st_size
            sample["object_counts"] = {key: len(bundle[key]) for key in
                                      ("content_objects", "workflow_runs", "analysis_objects")}
            unique_sizes = {}
            for label, table, column, id_column, ids in (
                ("content", "report_content_object", "payload_json", "object_id", list(bundle["content_objects"])),
                ("workflow", "workflow_run", "result_json", "run_id", list(bundle["workflow_runs"])),
                ("analysis", "analysis_run", "result_json", "run_id", list(bundle["analysis_objects"])),
            ):
                unique_sizes[label] = repo.one(f"SELECT COALESCE(SUM(length(CAST({column} AS BLOB))),0) FROM {table} "
                    f"WHERE {id_column} IN (SELECT value FROM json_each(?))", (json.dumps(ids),))[0]
            result["referenced_unique_bytes"] = {**unique_sizes, "total": sum(unique_sizes.values())}
            del bundle

            def offline(progress):
                # Deserialize the actual exported file, not the in-memory bundle.
                with export_path.open() as exported:
                    payload = json.load(exported)
                return reconstruct_report(payload)

            restored, _ = measure("offline_reconstruction", offline)
            frozen = load_report(repo, identity, **details_option)
            assert restored == frozen
            result["offline_reconstruction_exact"] = True
            current = restored["current"]
            assert len(current["metrics"]) == 77
            actual = {source for task in current["strength_tasks"] for source in task.get("source_record_ids", [])}
            # All these immutable fixtures use latest current rows; temporal
            # semantics are separately tested with actual revisions by the suite.
            source_rows = repo.rows(
                "SELECT set_uuid,condition_key FROM strength_set WHERE completion_state IN ('completed','aborted','in_progress') "
                "AND deleted_at IS NULL AND julianday(COALESCE(ended_at,started_at))>=julianday(?) "
                "AND julianday(COALESCE(ended_at,started_at))<julianday(?) "
                "AND julianday(COALESCE(ended_at,started_at))<=julianday(?) "
                "AND julianday(available_at)<=julianday(?)",
                (current["window_start"], current["window_end"], current["cutoff_time"], current["cutoff_time"]))
            expected = {"strength_set:" + row[0] for row in source_rows}
            assert actual == expected, (len(actual), len(expected))
            unknown = {"strength_set:" + row[0] for row in source_rows if row[1] is None}
            unknown_tasks = [task for task in current["strength_tasks"]
                             if unknown.intersection(task.get("source_record_ids", []))]
            for task in unknown_tasks:
                assert task.get("condition_key") is None and not task.get("protocol_complete")
                assert task.get("source_record_ids") == ["strength_set:" + task["unknown_condition_record_id"]]
            assert len(unknown_tasks) == len(unknown), "unknown conditions must retain separate record identities"
            if result["synthetic_fixture"] in {"synthetic-100000", "synthetic-1000000"}:
                assert len(actual) == 10000
            result["integrity"] = {"global_metrics": len(current["metrics"]),
                                   "task_count": len(current["strength_tasks"]),
                                   "all_period_source_groups_preserved": len(actual),
                                   "unknown_condition_records_kept_separate": len(unknown),
                                   "source_group_ids_sha256": hashlib.sha256("\n".join(sorted(actual)).encode()).hexdigest(),
                                   "all_raw_tables_after": raw_identity(repo.conn)}
            result["audit_path"] = str(export_path)
        result["complete"] = True
        result["final_host_load"] = os.getloadavg()
        result["source_changed"] = source_before != manifest()
        assert not result["source_changed"], "product source changed during performance run"
        write(destination, result)


def controller(args):
    from repair_measure_run import processes

    assert args.output and not args.output.exists(), "use a new evidence directory"
    args.output.mkdir(parents=True)
    fixture = validate_synthetic(args.synthetic)
    source_before = manifest()
    write(args.output / "source-manifest.json", source_before)
    workspace = Path(tempfile.mkdtemp(prefix="healthzip-followup-report-"))
    database = workspace / "synthetic.sqlite3"
    knowledge = args.shared_knowledge_root.resolve() if args.shared_knowledge_root else workspace / "knowledge"
    copies = [(args.synthetic, database)]
    if not args.shared_knowledge_root:
        knowledge.mkdir()
        copies += [(args.knowledge_root / name, knowledge / name) for name in ("sources.sqlite3", "theories.sqlite3")]
    for original, target in copies:
        with closing(sqlite3.connect(original.resolve().as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(target)) as dest:
                source.backup(dest)
    with closing(sqlite3.connect(database)) as conn:
        before = raw_identity(conn)
    result = {"fixture": fixture, "source": str(args.synthetic), "workspace": str(workspace),
              "original_database_bytes": args.synthetic.stat().st_size,
              "backup_database_bytes_before": database.stat().st_size,
              "data": "synthetic_only", "before_raw_tables": before, "phases": [],
              "platform": platform.platform(), "cpu_count": os.cpu_count(),
              "memory": Path("/proc/meminfo").read_text().splitlines()[0],
              "concurrent_load": args.concurrent_load, "os_cache_cleared": False,
              "remote_model": "not configured in isolated benchmark", "physical_device": "shared host"}
    if args.shared_knowledge_root:
        result["shared_knowledge_root"] = str(knowledge)
        result["shared_knowledge_authority_before"] = shared_knowledge(knowledge, prepare=True)
        result["shared_knowledge_preparation"] = "public schema/revision tracking prepared once before timed phases; only sequential use permitted"
    write(args.output / "receipt.json", result)
    for phase in ("generation", "read", "audit"):
        command = [sys.executable, str(Path(__file__).resolve()), "--worker-phase", phase,
                   "--database", str(database), "--knowledge-root", str(knowledge),
                   "--output", str(args.output.resolve()), "--cutoff", args.cutoff,
                   "--period", args.period, "--warm", str(args.warm), "--concurrent-load", args.concurrent_load]
        started = time.perf_counter()
        samples = []
        with (args.output / f"{phase}-command.txt").open("w") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
            while process.poll() is None:
                rows = list(processes(process.pid).values())
                samples.append({"seconds": time.perf_counter() - started,
                                "rss_kib": sum(row["rss_kib"] for row in rows),
                                "cpu_seconds": sum(row["cpu_seconds"] for row in rows),
                                "host_load": os.getloadavg()})
                time.sleep(.1)
        record = {"phase": phase, "exit_code": process.returncode,
                  "wall_seconds": time.perf_counter() - started,
                  "peak_tree_rss_kib": max((row["rss_kib"] for row in samples), default=0), "samples": samples}
        write(args.output / f"{phase}-resources.json", record)
        result["phases"].append({k: v for k, v in record.items() if k != "samples"})
        if args.shared_knowledge_root:
            result["shared_knowledge_authority_after"] = shared_knowledge(knowledge)
            result["shared_knowledge_authority_unchanged"] = result["shared_knowledge_authority_before"] == result["shared_knowledge_authority_after"]
        write(args.output / "receipt.json", result)
        if process.returncode:
            raise RuntimeError(f"{phase} failed; preserve {args.output / (phase + '-command.txt')}")
        if args.shared_knowledge_root:
            assert result["shared_knowledge_authority_unchanged"], "shared public authority changed during measurement"
    with closing(sqlite3.connect(database)) as conn:
        after = raw_identity(conn)
    assert before == after, "raw source tables changed"
    assert source_before == manifest(), "source changed between measured phases"
    result["raw_source_tables_unchanged"] = True
    result["source_unchanged_across_all_phases"] = True
    result["complete"] = True
    write(args.output / "receipt.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--knowledge-root", type=Path)
    parser.add_argument("--shared-knowledge-root", type=Path,
                        help="reuse one dedicated /tmp public copy sequentially; record unchanged source/review authority")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cutoff", default="2026-11-22T00:00:00+08:00")
    parser.add_argument("--period", choices=("week", "month"), default="week")
    parser.add_argument("--warm", type=int, default=30)
    parser.add_argument("--concurrent-load", required=True)
    parser.add_argument("--worker-phase", choices=("generation", "read", "audit"))
    arguments = parser.parse_args()
    if not (arguments.knowledge_root or arguments.shared_knowledge_root):
        parser.error("provide --knowledge-root or --shared-knowledge-root")
    worker(arguments) if arguments.worker_phase else controller(arguments)
