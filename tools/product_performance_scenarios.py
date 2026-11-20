"""Additional local backend lifecycle timings; no browser/network claims."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path("/tmp/healthzip-product-benchmark"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from healthzip.analytics.cache import clear
    from healthzip.analytics.workspaces import analyze_workspace
    from healthzip.db.repository import Repository

    worker = """import time,sys,json
started=time.perf_counter()
from healthzip.db.repository import Repository
from healthzip.analytics.workspaces import analyze_workspace
imported=time.perf_counter()
r=Repository(sys.argv[1]);opened=time.perf_counter()
v=analyze_workspace(r,'心率',period='30d');done=time.perf_counter()
print(json.dumps({'module_import_ms':(imported-started)*1000,'repository_open_ms':(opened-imported)*1000,'first_compute_ms':(done-opened)*1000,'process_body_ms':(done-started)*1000,'timings':v['workspace_scope'].get('timings_ms')}));r.close()
"""
    output = {"kind": "synthetic_backend_lifecycle_not_browser", "cohorts": []}
    for size in (100000, 1000000):
        path = args.directory / f"synthetic-{size}.sqlite3"
        if not path.exists():
            continue
        started = time.perf_counter()
        environment = {**os.environ, "PYTHONPATH": str(root / "src")}
        fresh = subprocess.run([sys.executable, "-c", worker, str(path)],
                               env=environment, check=True, text=True, capture_output=True)
        fresh_result = json.loads(fresh.stdout)
        fresh_result["subprocess_wall_ms"] = (time.perf_counter() - started) * 1000
        repo = Repository(path)
        clear()
        rows = []

        def run(label, page="心率"):
            count = 0

            def trace(sql):
                nonlocal count
                if sql.lstrip().upper().startswith(("SELECT", "WITH")):
                    count += 1

            repo.conn.set_trace_callback(trace)
            started = time.perf_counter()
            value = analyze_workspace(repo, page, period="30d")
            rows.append({"scenario": label, "milliseconds": (time.perf_counter() - started) * 1000,
                         "queries": count, "computed_cutoff": value["workspace_scope"]["cutoff_time"]})
            repo.conn.set_trace_callback(None)
            return value

        first = run("running_process_empty_cache")
        run("repeat_visit")
        run("visit_sleep", "睡眠")
        returned = run("return_from_sleep")
        assert returned == first
        module = importlib.import_module("healthzip.analytics.workspaces")
        original_datetime = module.datetime
        clock = datetime.now(timezone.utc) + timedelta(minutes=2)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock

        module.datetime = Clock
        try:
            across = run("cross_minute_same_committed_revision")
            assert across == first
        finally:
            module.datetime = original_datetime
        writer = Repository(path)
        writer.conn.execute("BEGIN IMMEDIATE")
        try:
            clear()
            run("empty_cache_while_other_connection_holds_write_transaction")
        finally:
            writer.conn.rollback()
            writer.close()
        before = run("before_other_process_import")
        importer = """import sys,time
from datetime import datetime,timezone,timedelta
from healthzip.db.repository import Repository
r=Repository(sys.argv[1]);now=datetime.now(timezone.utc);event=(now-timedelta(minutes=1)).isoformat()
r.insert_sample(1,{'fingerprint':'synthetic-performance-import-'+str(time.time_ns()),'raw_type':'resting_heart_rate_bpm','canonical_type':'resting_heart_rate_bpm','raw_value':'61','raw_unit':'bpm','normalized_value':61,'normalized_unit':'bpm','start_utc':event,'end_utc':event,'local_date':event[:10],'source_name':'Synthetic Watch','device':'synthetic','metadata_json':'{}','created_at':now.isoformat()});r.conn.commit();r.close()
"""
        subprocess.run([sys.executable, "-c", importer, str(path)], env=environment, check=True)
        after = run("after_other_process_import")
        assert before["workspace_scope"]["data_version"] != after["workspace_scope"]["data_version"]
        plans = []
        from healthzip.db.temporal_schema import CANONICAL_TYPE_SQL, EVENT_END_SQL
        for row in repo.rows(f"EXPLAIN QUERY PLAN SELECT DISTINCT record_id FROM source_revision INDEXED BY source_revision_type_window WHERE table_name='health_sample' AND {CANONICAL_TYPE_SQL} IN ('resting_heart_rate_bpm','hrv_sdnn_ms') AND {EVENT_END_SQL}>=julianday('2026-01-01')"):
            plans.append(row["detail"])
        output["cohorts"].append({"health_samples_before_scenario": size,
            "fresh_process": fresh_result, "scenarios": rows, "typed_query_plan": plans})
        repo.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        print(json.dumps({"size": size, "scenarios": rows}), flush=True)


if __name__ == "__main__":
    main()
