"""Profile only cold period_facts against frozen r3 and an identified synthetic backup."""
from __future__ import annotations

import cProfile
import gc
import hashlib
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


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = Path(__file__).resolve().parent
    source = Path("/tmp/healthzip-followup-final-source-r3")
    fixture = Path("/tmp/healthzip-product-benchmark/synthetic-100000.sqlite3")
    workspace = Path("/home/sn_maozhifang/healthzip-followup-validation-tmp/period-facts-profile-r1")
    cutoff = "2026-11-21T16:00:00+00:00"
    assert not workspace.exists(), "Preserve prior diagnostic workspaces."
    assert not (output / "receipt.json").exists(), "Preserve prior results."
    workspace.joinpath(".local").mkdir(parents=True)
    database = workspace / ".local/healthzip.sqlite3"
    with closing(sqlite3.connect(fixture.as_uri() + "?mode=ro", uri=True)) as origin:
        marker = origin.execute("SELECT file_sha256 FROM import_batch").fetchall()
        assert marker == [("synthetic-100000",)]
        counts = {table: origin.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("health_sample", "strength_set", "strength_session")}
        with closing(sqlite3.connect(database)) as target:
            origin.backup(target)
    hashes = {str(path.relative_to(source)): digest(path) for path in (source / "src").rglob("*.py")}
    sys.path.insert(0, str(source / "src"))
    os.chdir(workspace)
    from healthzip.analytics.cache import clear
    from healthzip.db.repository import Repository
    from healthzip.science.contracts import canonical_hash
    from healthzip.training.service import TrainingService
    from healthzip.workflows import report_inputs

    assert Path(report_inputs.__file__).resolve().is_relative_to(source)
    receipt = {"diagnostic_only": True, "complete": False, "source_root": str(source),
               "source_hashes": hashes, "fixture": str(fixture), "synthetic_marker": marker,
               "counts": counts, "workspace": str(workspace), "cutoff": cutoff,
               "timezone": "Asia/Shanghai", "period": "week", "context": {},
               "retrospective": False, "ordinary_task_metrics": ["STR-11"],
               "python": platform.python_version(), "platform": platform.platform(),
               "logical_cpus": os.cpu_count(), "initial_load": os.getloadavg(),
               "gc_enabled": gc.isenabled(), "gc_thresholds": gc.get_threshold(),
               "driver_sha256": digest(Path(__file__)), "os_cache": "retained",
               "instrumentation": "cProfile of period_facts only inside shared_report_inputs; no report generation",
               "remote_model": "none", "performance_acceptance": False}
    (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    profiler = cProfile.Profile()
    with closing(Repository(database)) as repo:
        TrainingService(repo)
        clear()
        try:
            with report_inputs.shared_report_inputs(repo):
                started = time.perf_counter()
                value = profiler.runcall(report_inputs.period_facts, repo, cutoff_time=cutoff,
                                         timezone_name="Asia/Shanghai", period="week", context={},
                                         retrospective=False)
                elapsed = time.perf_counter() - started
            receipt.update(complete=True, elapsed_s=elapsed, metric_count=len(value["metrics"]),
                           metric_ids=sorted(value["metrics"]),
                           strength_task_count=len(value["strength_tasks"]),
                           data_hash=value["data_hash"], window_start=value["window_start"],
                           window_end=value["window_end"], result_sha256=canonical_hash(value))
            with (output / "task-identities.json").open("w") as handle:
                json.dump([{key: task.get(key) for key in ("task_id", "task_key", "record_ids", "reference_selected")}
                           for task in value["strength_tasks"]], handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            receipt["task_identities_sha256"] = digest(output / "task-identities.json")
        except BaseException as exc:
            receipt["error"] = repr(exc)
            raise
        finally:
            profiler.dump_stats(str(output / "period-facts.prof"))
            stats = pstats.Stats(profiler)
            entries = []
            for function, values in stats.stats.items():
                primitive_calls, total_calls, self_s, cumulative_s, callers = values
                entries.append({"file": function[0], "line": function[1], "function": function[2],
                                "primitive_calls": primitive_calls, "total_calls": total_calls,
                                "self_s": self_s, "cumulative_s": cumulative_s,
                                "callers": [{"file": caller[0], "line": caller[1], "function": caller[2],
                                             "stats": list(details) if isinstance(details, tuple) else details}
                                            for caller, details in callers.items()]})
            entries.sort(key=lambda item: item["cumulative_s"], reverse=True)
            (output / "hotspots.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
            receipt.update(peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                           final_load=os.getloadavg(), gc_enabled_after=gc.isenabled(),
                           source_changes=[name for name, sha in hashes.items() if digest(source / name) != sha],
                           profile_sha256=digest(output / "period-facts.prof"),
                           hotspots_sha256=digest(output / "hotspots.json"))
            (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in receipt.items() if key != "source_hashes"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
