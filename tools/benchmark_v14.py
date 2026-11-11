"""Synthetic full-history benchmark; never reads or uploads a personal export."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from zipfile import ZIP_DEFLATED, ZipFile


def worker(count):
    from healthzip.analytics import all_analysis
    from healthzip.analytics.cache import clear
    from healthzip.analytics.v13 import analyze
    from healthzip.db.repository import Repository
    from healthzip.importers.apple_xml import import_apple_zip
    from healthzip.quality import inventory

    repository_root = Path(__file__).resolve().parents[1]
    measured_files = [*repository_root.glob("src/healthzip/analytics/*.py"),
                      repository_root / "src/healthzip/db/temporal_schema.py", repository_root / "src/healthzip/db/repository.py",
                      repository_root / "src/healthzip/importers/apple_xml.py", repository_root / "src/healthzip/normalize/__init__.py",
                      repository_root / "src/healthzip/quality/coverage.py", repository_root / "app.py"]
    source_hashes = {str(path.relative_to(repository_root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in measured_files}

    with tempfile.TemporaryDirectory(prefix="healthzip-synthetic-scale-") as tmp:
        root = Path(tmp)
        archive = root / "synthetic.zip"
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zipped:
            with zipped.open("export.xml", "w") as stream:
                stream.write(b"<HealthData>")
                for index in range(count):
                    at = (start + timedelta(minutes=index)).strftime("%Y-%m-%d %H:%M:%S +0000")
                    stream.write((f'<Record type="HKQuantityTypeIdentifierRestingHeartRate" unit="count/min" value="60" '
                                  f'sourceName="Synthetic Scale Test" startDate="{at}" endDate="{at}">'
                                  '<MetadataEntry key="HKWasUserEntered" value="0"/></Record>').encode())
                stream.write(b"</HealthData>")
        repo = Repository(root / "synthetic.sqlite3")
        before = time.perf_counter()
        imported = import_apple_zip(archive, repo)
        import_seconds = time.perf_counter() - before
        assert imported.records_inserted == count
        rows_returned = []
        original = repo.rows

        def measured(sql, args=()):
            rows = original(sql, args)
            if "source_revision" in sql and "payload_json" in sql:
                rows_returned.append(len(rows))
            return rows

        repo.rows = measured
        cutoff = datetime.now(timezone.utc).isoformat()
        clear()
        before = time.perf_counter()
        first = analyze(repo, 30, cutoff_time=cutoff)
        first_seconds = time.perf_counter() - before
        first_payload_rows = sum(rows_returned)
        assert first_payload_rows == 0 and first["metrics"]["STATE-RHR"]["value"] is None
        repeats = []
        for _ in range(10):
            before = time.perf_counter()
            again = analyze(repo, 30, cutoff_time=cutoff)
            repeats.append(time.perf_counter() - before)
            assert again == first
        before = time.perf_counter()
        all_analysis(repo, 30)
        inventory(repo)
        page_first = time.perf_counter() - before
        page_times = []
        for _ in range(10):
            before = time.perf_counter()
            all_analysis(repo, 30)
            inventory(repo)
            page_times.append(time.perf_counter() - before)
        from streamlit.testing.v1 import AppTest

        import healthzip.config as configuration
        configuration.DEFAULT_DB_PATH = root / "synthetic.sqlite3"
        before = time.perf_counter()
        app = AppTest.from_file(str(repository_root / "app.py")).run(timeout=90)
        ui_first = time.perf_counter() - before
        assert not app.exception
        ui_times = []
        for label in ("心率 / HRV", "睡眠", "体重 / 有氧", "报告", "数据质量") * 2:
            before = time.perf_counter()
            app.radio(key="main_workspace").set_value(label).run(timeout=90)
            ui_times.append(time.perf_counter() - before)
            assert not app.exception and not app.error, [x.value for x in app.error]
        total = repo.count("health_sample")
        repo.close()
        before = time.perf_counter()
        reopened = Repository(root / "synthetic.sqlite3")
        reopen_seconds = time.perf_counter() - before
        assert reopened.count("health_sample") == total
        reopened.close()
        return {"records": count, "preserved_records": total, "data_kind": "synthetic",
                "all_events_outside_30_day_window": True, "import_seconds": import_seconds,
                "first_analysis_seconds": first_seconds, "repeat_analysis_median_seconds": median(repeats),
                "repeat_analysis_seconds": repeats, "first_analysis_payload_rows": first_payload_rows,
                "page_data_first_seconds": page_first, "page_data_repeat_seconds": page_times,
                "page_data_cached_p95_seconds": sorted(page_times)[-1],
                "streamlit_first_seconds": ui_first, "streamlit_page_change_seconds": ui_times,
                "streamlit_cached_page_change_p95_seconds": sorted(ui_times)[-1],
                "reopen_migration_seconds": reopen_seconds,
                "maxrss_kib_whole_worker_including_generation_import": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "page_scope": "real app.py Streamlit AppTest navigation and page data calls",
                "source_file_sha256_at_worker_start": source_hashes,
                "product_budget_seconds": 2, "budget_kind": "product_parameter",
                "cached_page_data_budget_met": max(page_times) <= 2,
                "cached_streamlit_budget_met": max(ui_times) <= 2}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=int)
    parser.add_argument("--counts", default="10000,100000,1000000")
    parser.add_argument("--output", default="artifacts/v14/performance/scale-results.json")
    args = parser.parse_args()
    if args.worker is not None:
        print(json.dumps(worker(args.worker)))
        return
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"run_at": datetime.now(timezone.utc).isoformat(), "hardware": {
        "machine": platform.machine(), "system": platform.system(), "python": platform.python_version(),
        "logical_cpu_count": os.cpu_count(), "available_cpu_count": len(os.sched_getaffinity(0)),
        "host_reported_memory_bytes": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")},
        "environment_note": "Shared execution host; other integration work may run concurrently. Not the user's private target device.",
        "private_export_tested": False, "results": []}
    for count in map(int, args.counts.split(",")):
        result = subprocess.run([sys.executable, __file__, "--worker", str(count)], check=True,
                                capture_output=True, text=True)
        item = json.loads(result.stdout)
        payload["results"].append(item)
        output.write_text(json.dumps(payload, indent=2) + "\n")
        print(json.dumps(item), flush=True)


if __name__ == "__main__":
    main()
