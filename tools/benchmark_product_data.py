"""Reproducible synthetic health-page backend benchmark (never a UI latency claim).

Use --code-root with an archived checkout to measure the same fixture on a baseline.
The databases remain outside the repository; JSON contains timings and counts only.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--code-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--directory", type=Path, default=Path("/tmp/healthzip-product-benchmark"))
    parser.add_argument("--samples", type=int, nargs="+", default=[100_000, 1_000_000])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cold-runs", type=int, default=5)
    args = parser.parse_args()
    sys.path.insert(0, str(args.code_root / "src"))
    from healthzip.analytics.cache import clear
    from healthzip.analytics.workspaces import analyze_workspace
    from healthzip.db.repository import Repository
    from healthzip.training.service import TrainingService

    args.directory.mkdir(parents=True, exist_ok=True)
    result = {"kind": "synthetic_backend_not_browser", "environment": {
        "platform": platform.platform(), "python": platform.python_version(),
        "cpu_count": os.cpu_count(), "mode": "local Python + SQLite WAL; no model or network",
        "memory_total_kib": next((line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                                  if line.startswith("MemTotal:")), None)}, "cohorts": []}
    for size in args.samples:
        path = args.directory / f"synthetic-{size}.sqlite3"
        started = time.perf_counter()
        repo = Repository(path)
        migration_ms = (time.perf_counter() - started) * 1000
        service = TrainingService(repo)
        if not repo.one("SELECT count(*) FROM health_sample")[0]:
            batch = repo.create_batch(file_sha256=f"synthetic-{size}", file_name="synthetic", file_size=0, xml_member_path="")
            end = datetime.now(timezone.utc) - timedelta(hours=1)
            # Common high-frequency streams dominate; sparse daily metrics stay realistic.
            counts = Counter()
            started = time.perf_counter()
            for index in range(size):
                slot = index % 1000
                if slot == 0:
                    canonical, value, unit = "resting_heart_rate_bpm", 60 + index % 7, "bpm"
                elif slot == 1:
                    canonical, value, unit = "hrv_sdnn_ms", 35 + index % 9, "ms"
                elif slot == 2:
                    canonical, value, unit = "body_mass_kg", 72 + (index % 13) / 10, "kg"
                elif slot == 3:
                    canonical, value, unit = "vo2_max_ml_kg_min", 42 + index % 4, "mL/kg/min"
                elif slot < 10:
                    canonical, value, unit = "sleep_stage", None, "category"
                elif slot < 510:
                    canonical, value, unit = "heart_rate_bpm", 70 + index % 90, "bpm"
                elif slot < 810:
                    canonical, value, unit = "step_count", index % 50, "count"
                else:
                    canonical, value, unit = "active_energy_kcal", index % 8, "kcal"
                # Interleaving time avoids putting a stream at only one end of the year.
                observed = end - timedelta(seconds=((index * 7919) % size) * 365 * 86400 / size)
                first = observed - timedelta(minutes=30) if canonical == "sleep_stage" else observed
                repo.insert_sample(batch, {"fingerprint": f"synthetic-{index}", "raw_type": canonical,
                    "canonical_type": canonical, "raw_value": str(value) if value is not None else None,
                    "raw_unit": unit, "normalized_value": value, "normalized_unit": unit,
                    "category_value": "HKCategoryValueSleepAnalysisAsleepCore" if canonical == "sleep_stage" else None,
                    "start_utc": first.isoformat(), "end_utc": observed.isoformat(),
                    "local_date": observed.date().isoformat(), "source_name": "Synthetic Watch",
                    "device": "synthetic", "metadata_json": '{"protocol_id":"synthetic"}',
                    "created_at": end.isoformat()})
                counts[canonical] += 1
                if index % 10000 == 0:
                    repo.conn.commit()
            repo.conn.commit()
            fixture_seconds = time.perf_counter() - started
            # 100 sessions x 100 real event-backed completed sets; not an import speed test.
            for session_index in range(100):
                session = service.start_session("Synthetic benchmark", started_at=end.isoformat())
                exercise = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", {})
                for set_index in range(100):
                    service.add_set(exercise["id"], actual={"load_value": 32.5, "load_unit": "kg",
                        "reps": 8, "rir": 0, "completion_state": "completed", "ended_at": end.isoformat()})
                service.end_session(session["id"], ended_at=end.isoformat())
            metadata = {"type_counts": dict(counts), "span_days": 365,
                        "fixture_generation_seconds": fixture_seconds}
            path.with_suffix(".json").write_text(json.dumps(metadata))
        else:
            metadata = json.loads(path.with_suffix(".json").read_text())
        cutoff = datetime.now(timezone.utc).isoformat()
        sql_counts = Counter()
        repo.conn.set_trace_callback(lambda sql: sql_counts.update([sql.lstrip().split(None, 1)[0].upper()]))

        def run():
            sql_counts.clear()
            started = time.perf_counter()
            value = analyze_workspace(repo, "心率 / HRV", cutoff_time=cutoff)
            return {"milliseconds": (time.perf_counter() - started) * 1000,
                    "statements": dict(sql_counts),
                    "returned_records": value["workspace_scope"]["query_plan"].get("source_rows_returned"),
                    "stages": value["workspace_scope"].get("timings_ms")}

        cold = []
        for _ in range(args.cold_runs):
            clear()
            cold.append(run())
        hot = [run() for _ in range(30)]

        def stats(rows):
            values = sorted(row["milliseconds"] for row in rows)
            return {"samples": len(values), "p50_ms": median(values),
                    "p95_ms": values[min(len(values) - 1, int(len(values) * .95))], "runs": rows}

        repo.conn.set_trace_callback(None)
        repo.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        result["cohorts"].append({"health_samples": size,
            "training_sets": repo.one("SELECT count(*) FROM strength_set")[0],
            "database_bytes": path.stat().st_size, "open_or_migration_ms": migration_ms,
            **metadata, "cold_definition": "running process, clear bounded result cache; OS cache remains warm",
            "hot_definition": "same process, cutoff, committed revision and page; 30 repeats",
            "cold": stats(cold), "hot": stats(hot)})
        repo.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({"samples": size, "cold_ms": result["cohorts"][-1]["cold"]["p95_ms"],
                          "hot_ms": result["cohorts"][-1]["hot"]["p95_ms"]}), flush=True)


if __name__ == "__main__":
    main()
