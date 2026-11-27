"""Matched synthetic report direct/worker diagnostic, with subphase and stack evidence.

Each invocation backs up an identified fixture to a new workspace. Instrumentation
is observational and timings are diagnostic, never acceptance or P95 samples.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import importlib
import json
import os
import platform
import resource
import sqlite3
import sys
import threading
import time
import traceback
from contextlib import closing
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--knowledge-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("direct", "worker"), required=True)
    parser.add_argument("--cutoff", default="2026-11-21T16:00:00+00:00")
    args = parser.parse_args()
    source = args.source_root.resolve()
    workspace = args.workspace.resolve()
    output = args.output.resolve()
    knowledge = args.knowledge_root.resolve()
    assert not workspace.exists(), "preserve previous diagnostic workspaces"
    with closing(sqlite3.connect(args.fixture.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        markers = conn.execute("SELECT file_sha256 FROM import_batch").fetchall()
        assert markers == [("synthetic-100000",)] or markers == [("synthetic-1000000",)]
        workspace.joinpath(".local").mkdir(parents=True)
        database = workspace / ".local/healthzip.sqlite3"
        with closing(sqlite3.connect(database)) as target:
            conn.backup(target)
    workspace.joinpath(".local/knowledge").symlink_to(knowledge, target_is_directory=True)
    output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(source / "src"))
    os.chdir(workspace)
    from healthzip.analytics.cache import clear
    from healthzip.db.repository import Repository
    from healthzip.knowledge.revisions import knowledge_authority_clock
    from healthzip.workflows import period_report

    assert Path(period_report.__file__).resolve().is_relative_to(source)
    hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (source / "src").rglob("*.py")}
    before = knowledge_authority_clock(knowledge)
    receipt = {"diagnostic_only": True, "mode": args.mode, "source_root": str(source),
               "source_hashes": hashes, "fixture": str(args.fixture), "marker": markers,
               "workspace": str(workspace), "knowledge_root": str(knowledge), "cutoff": args.cutoff,
               "python": platform.python_version(), "platform": platform.platform(),
               "logical_cpus": os.cpu_count(), "initial_load": os.getloadavg(),
               "os_cache": "retained", "remote_model": "none", "stages": [],
               "instrumentation": "subphase wrappers and Python thread stacks every 30s; no cProfile",
               "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "complete": False, "status": "running"}
    (output / "driver-source.py").write_bytes(Path(__file__).read_bytes())
    (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    started = time.perf_counter()
    with (output / "events.jsonl").open("w") as events, (output / "stacks.txt").open("w") as stacks:
        def event(name, **fields):
            value = {"elapsed_s": time.perf_counter() - started, "event": name, **fields}
            events.write(json.dumps(value, ensure_ascii=False) + "\n")
            events.flush()
            print(json.dumps(value, ensure_ascii=False), flush=True)

        def instrument(module, name):
            original = getattr(module, name)

            @functools.wraps(original)
            def measured(*values, **fields):
                label = module.__name__ + "." + name
                extra = {"question": values[0]} if name == "_render_question" else {}
                begin = time.perf_counter()
                event(label + ":start", **extra)
                try:
                    return original(*values, **fields)
                finally:
                    event(label + ":end", seconds=time.perf_counter() - begin, **extra)

            setattr(module, name, measured)

        for module_name, names in {
            "healthzip.workflows.period_report": ("period_facts", "period_questions", "review_analysis", "persist"),
            "healthzip.analytics.body_metrics": ("analyze_questions",),
            "healthzip.analytics.body_questions": ("_training", "_strength_rows", "_render_question"),
            "healthzip.workflows.longitudinal": ("ordinary_review",),
            "healthzip.knowledge.topics": ("question_sources",),
        }.items():
            module = importlib.import_module(module_name)
            for name in names:
                instrument(module, name)
        clear()
        stopped = threading.Event()

        def sample_stacks():
            while not stopped.wait(30):
                stacks.write(f"Elapsed {time.perf_counter()-started:.3f}s\n")
                for identity, frame in sys._current_frames().items():
                    stacks.write(f"Thread {identity}\n" + "".join(traceback.format_stack(frame)))
                stacks.flush()

        sampler = threading.Thread(target=sample_stacks, daemon=True)
        sampler.start()
        try:
            if args.mode == "direct":
                with closing(Repository(database)) as repo:
                    report = period_report.create_report(repo, {
                        "cutoff_time": args.cutoff, "timezone": "Asia/Shanghai", "selection_context": {}},
                        period="week", knowledge_root=knowledge, progress=lambda stage: event("stage", stage=stage))
            else:
                from healthzip.ui.health_explanation import _JOBS, _LOCK
                from healthzip.ui.report_jobs import report_progress, submit_report
                key = submit_report(database, cutoff_time=args.cutoff, timezone_name="Asia/Shanghai",
                                    period="week", context_id=None, revision="matched-diagnostic", attempt=0)
                with _LOCK:
                    future = _JOBS[key][1]
                prior = None
                while not future.done():
                    stage = report_progress(key)
                    if stage != prior:
                        event("stage", stage=stage)
                        prior = stage
                    time.sleep(.25)
                report = future.result()
            receipt.update(complete=True, report_id=report["report_id"],
                           report_cutoff=report["cutoff_time"],
                           markdown_sha256=hashlib.sha256(report["markdown"].encode()).hexdigest())
        except BaseException as exc:
            receipt.update(complete=False, error=repr(exc))
            raise
        finally:
            stopped.set()
            sampler.join(timeout=5)
            receipt["status"] = "finished"
            receipt.update(elapsed_s=time.perf_counter() - started,
                           peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                           final_load=os.getloadavg(), knowledge_unchanged=before == knowledge_authority_clock(knowledge),
                           source_changes=[name for name, digest in hashes.items()
                                           if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest])
            (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
