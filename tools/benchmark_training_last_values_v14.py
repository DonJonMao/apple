"""Measure the real last-values button on a complete isolated synthetic history.

Example (the prepare phase makes a full SQLite backup, never a sample):
    python tools/benchmark_training_last_values_v14.py prepare --output-dir .local/last-values
    python tools/benchmark_training_last_values_v14.py baseline --output-dir .local/last-values
    python tools/benchmark_training_last_values_v14.py indexed --output-dir .local/last-values

Optional profile/indexed_profile phases instrument each Streamlit script thread
pass. Their overhead is reported separately and is not a latency budget result.
The baseline removes only the three session-detail indexes in the isolated copy
and temporarily omits their CREATE statements in this process, preserving all
other current behavior. No product source or historical benchmark is modified.
"""
from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import pstats
import runpy
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path()
DATABASE = Path()
SOURCE = ROOT / ".local/training-history-benchmark/stage1-million-consistent.sqlite3"
sys.path.insert(0, str(ROOT / "src"))
TABLES = ("training_event", "strength_session", "strength_set", "training_session_exercise", "training_invalidation")
INDEXES = {
    "idx_training_set_session_exercise": "strength_set(session_exercise_id,user_id,set_number,id)",
    "idx_training_set_session": "strength_set(session_id,user_id,condition_key,id)",
    "idx_training_exercise_session": "training_session_exercise(session_id,user_id,position,id)",
}


def save(name, value):
    (FOLDER / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def counts(conn):
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    from healthzip.db.repository import Repository

    assert not DATABASE.exists(), "Preparation may not replace an existing diagnostic database"
    protected = [ROOT / "tools/benchmark_training_history_v14.py", ROOT / "artifacts/v14/performance/training-stage3-final-1.4.4.json"]
    manifest = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "source": str(SOURCE), "database": str(DATABASE),
                "protected_sha256": {str(p.relative_to(ROOT)): sha(p) for p in protected}}
    before = time.perf_counter()
    source = sqlite3.connect(f"file:{SOURCE}?mode=ro", uri=True)
    source.execute("PRAGMA query_only=ON")
    manifest["source_counts"] = counts(source)
    assert source.execute("SELECT COUNT(*) FROM health_sample").fetchone()[0] == 0
    assert source.execute("SELECT COUNT(*) FROM strength_session WHERE name!='Synthetic event-history benchmark'").fetchone()[0] == 0
    assert manifest["source_counts"]["training_event"] == 1000011
    assert manifest["source_counts"]["strength_set"] == 100001
    target = sqlite3.connect(DATABASE)
    source.backup(target)
    target.close()
    source.close()
    manifest["full_backup_seconds"] = time.perf_counter() - before
    print(json.dumps({"phase": "full_backup_complete", "seconds": manifest["full_backup_seconds"]}), flush=True)
    before = time.perf_counter()
    repo = Repository(DATABASE)
    manifest["necessary_current_migration_seconds"] = time.perf_counter() - before
    manifest["prepared_counts"] = counts(repo.conn)
    assert manifest["source_counts"] == manifest["prepared_counts"]
    repo.close()
    save("preparation.json", manifest)
    print(json.dumps(manifest), flush=True)


def profile_app(label, folder):
    """Called inside the Streamlit script thread, once for each actual rerender."""
    global FOLDER
    FOLDER = Path(folder)
    sql = defaultdict(lambda: {"calls": 0, "seconds": 0.0})

    class Cursor(sqlite3.Cursor):
        statement = ""

        def measure(self, operation, *args):
            start = time.perf_counter()
            try:
                return operation(*args)
            finally:
                item = sql[self.statement]
                item["calls"] += 1
                item["seconds"] += time.perf_counter() - start

        def execute(self, statement, parameters=()):
            self.statement = " ".join(statement.split())
            return self.measure(super().execute, statement, parameters)

        def fetchone(self):
            return self.measure(super().fetchone)

        def fetchall(self):
            return self.measure(super().fetchall)

        def fetchmany(self, size=None):
            return self.measure(super().fetchmany, *(() if size is None else (size,)))

        def __next__(self):
            return self.measure(super().__next__)

    class Connection(sqlite3.Connection):
        def cursor(self, factory=Cursor):
            return super().cursor(factory)

        def execute(self, statement, parameters=()):
            return self.cursor().execute(statement, parameters)

    connect = sqlite3.connect

    def timed_connect(*args, **kwargs):
        kwargs.setdefault("factory", Connection)
        return connect(*args, **kwargs)

    stamp = str(time.time_ns())
    profiler = cProfile.Profile()
    started = time.perf_counter()
    try:
        with patch.object(sqlite3, "connect", timed_connect):
            profiler.enable()
            runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
    finally:
        profiler.disable()
        profiler.dump_stats(str(FOLDER / f"{label}-{stamp}.pstats"))
        stats = pstats.Stats(profiler)
        ranked = sorted(stats.stats.items(), key=lambda pair: pair[1][3], reverse=True)
        save(f"{label}-{stamp}.json", {
            "elapsed_seconds": time.perf_counter() - started,
            "functions": [{"file": key[0], "line": key[1], "name": key[2], "primitive_calls": val[0], "calls": val[1], "self_seconds": val[2], "cumulative_seconds": val[3]} for key, val in ranked[:100]],
            "sql": sorted(({"sql": key, **val} for key, val in sql.items()), key=lambda item: item["seconds"], reverse=True),
        })


def measure(label, profiled=False):
    from streamlit.testing.v1 import AppTest

    import healthzip.config as configuration
    from healthzip.db.repository import Repository
    from healthzip.training.service import TrainingService

    assert not (FOLDER / (label + "-result.json")).exists(), "Use a new --label to preserve previous measurements"
    before_migration = query_plans()
    start = time.perf_counter()
    repo = Repository(DATABASE)
    reopen_seconds = time.perf_counter() - start
    svc = TrainingService(repo)
    condition = svc.get_session_exercise("synthetic-current-exercise")["condition"]
    target = svc.start_session("Synthetic diagnostic active " + label,
        session_id="synthetic-diagnostic-session-" + label, event_id="synthetic-diagnostic-start-" + label)
    instance = svc.add_exercise(target["id"], "psa.ex.barbell_bench_press", condition,
        session_exercise_id="synthetic-diagnostic-exercise-" + label, event_id="synthetic-diagnostic-exercise-event-" + label)
    configuration.DEFAULT_DB_PATH = DATABASE
    files = ("app.py", "src/healthzip/training/schema.py", "src/healthzip/training/service.py", "src/healthzip/training/history_candidates.py", "src/healthzip/ui/training_page.py", "src/healthzip/db/repository.py")
    result = {"source_sha256": {name: sha(ROOT / name) for name in files},
              "repository_open_seconds_not_in_ui_time": reopen_seconds,
              "query_plans_before_open": before_migration, "query_plans_after_open": query_plans(),
              "label": label, "profiled": profiled, "target_session": target["id"], "target_exercise": instance["id"], "counts_before_click": counts(repo.conn)}
    start = time.perf_counter()
    previous = svc.last_values(instance["id"])
    result["last_values_seconds"] = time.perf_counter() - start
    assert previous["source_set_id"] == "synthetic-current-set"
    if profiled:
        wrapper = f"import sys\nsys.path.insert(0, {str(ROOT / 'tools')!r})\nfrom benchmark_training_last_values_v14 import profile_app\nprofile_app({label!r}, {str(FOLDER)!r})\n"
        app = AppTest.from_string(wrapper)
    else:
        app = AppTest.from_file(str(ROOT / "app.py"))
    for phase, action in (
        ("initial_overview", lambda: app.run(timeout=180)),
        ("strength_restore", lambda: app.radio(key="main_workspace").set_value("力量").run(timeout=180)),
        ("copy_last_values", lambda: app.button(key="last_" + instance["id"]).click().run(timeout=180)),
    ):
        print(json.dumps({"label": label, "phase": phase}), flush=True)
        started = time.perf_counter()
        action()
        result[phase + "_seconds"] = time.perf_counter() - started
        assert not app.exception and not app.error, [item.value for item in app.exception] + [item.value for item in app.error]
        if phase == "strength_restore":
            assert app.selectbox(key="resume_training").value == target["id"]
    drafts = svc.get_session_exercise(instance["id"])["sets"]
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft["completion_state"] == "draft" and draft["reps"] == 8 and float(draft["load_value"]) == 40
    assert draft["started_at"] is None and draft["ended_at"] is None
    assert svc.last_values(instance["id"])["source_set_id"] == "synthetic-current-set"
    result["draft"] = {key: draft[key] for key in ("set_uuid", "completion_state", "reps", "load_value", "load_unit", "started_at", "ended_at")}
    result["counts_after_click"] = counts(repo.conn)
    result["exactly_one_new_draft"] = result["counts_after_click"]["strength_set"] == result["counts_before_click"]["strength_set"] + 1
    result["source_set_after_click"] = svc.last_values(instance["id"])["source_set_id"]
    result["copy_under_two_seconds"] = result["copy_last_values_seconds"] <= 2
    repo.close()
    save(label + "-result.json", result)
    print(json.dumps(result), flush=True)


def query_plans():
    conn = sqlite3.connect(DATABASE)
    queries = {
        "exercise_sets": ("SELECT * FROM strength_set WHERE session_exercise_id=? AND user_id=? ORDER BY set_number,id", ("synthetic-current-exercise", "local")),
        "session_sets": ("SELECT * FROM strength_set WHERE session_id=? AND user_id=? ORDER BY set_number,id", (100001, "local")),
        "session_exercises": ("SELECT id FROM training_session_exercise WHERE session_id=? AND user_id=? ORDER BY position,id", (100001, "local")),
        "next_set_number": ("SELECT MAX(set_number) FROM strength_set WHERE session_exercise_id=?", ("synthetic-current-exercise",)),
    }
    result = {key: {"sql": sql, "query_plan": [list(row) for row in conn.execute("EXPLAIN QUERY PLAN " + sql, args)]} for key, (sql, args) in queries.items()}
    for key, (sql, args) in queries.items():
        before = time.perf_counter()
        rows = conn.execute(sql, args).fetchall()
        result[key].update(seconds=time.perf_counter() - before, rows=len(rows))
    conn.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "baseline", "profile", "indexed", "indexed_profile"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=SOURCE,
                        help="Retained synthetic million-event database, opened read-only for prepare")
    parser.add_argument("--label", help="Unique result label; existing results are never overwritten")
    args = parser.parse_args()
    FOLDER = args.output_dir.resolve()
    FOLDER.mkdir(parents=True, exist_ok=True)
    DATABASE = FOLDER / "synthetic-million.sqlite3"
    SOURCE = args.source.resolve()
    assert DATABASE != SOURCE
    label = args.label or args.phase
    assert label and all(char.isalnum() or char in "-_" for char in label)
    if args.phase == "prepare":
        prepare()
    else:
        assert DATABASE.is_file() and (FOLDER / "preparation.json").is_file(), "Run prepare first"
        if args.phase in {"baseline", "profile"}:
            from healthzip.training import schema

            assert not (FOLDER / (label + "-result.json")).exists()
            conn = sqlite3.connect(DATABASE)
            for name in INDEXES:
                conn.execute("DROP INDEX IF EXISTS " + name)
            conn.commit()
            conn.close()
            statements = [sql for sql in schema.STATEMENTS
                          if not any(name in sql for name in INDEXES)]
            with patch.object(schema, "STATEMENTS", statements):
                measure(label, profiled=args.phase == "profile")
        else:
            measure(label, profiled=args.phase == "indexed_profile")
