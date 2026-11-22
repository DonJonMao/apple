"""Measure the real selection round trip on copies of benchmark_product_data fixtures."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sqlite3
import statistics
import tempfile
import time
from contextlib import closing
from pathlib import Path

from playwright.sync_api import sync_playwright
from product_redesign_training_browser import RedesignCheck, percentile
from strength_workbench_browser_check import isolated_app


def measure(source, size, root):
    with tempfile.TemporaryDirectory(prefix="training-scale-") as tmp:
        folder = Path(tmp)
        database = folder / ".local/healthzip.sqlite3"
        database.parent.mkdir()
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            batch = src.execute("SELECT DISTINCT file_sha256 FROM import_batch").fetchall()
            assert batch == [(f"synthetic-{size}",)], "Use the benchmark_product_data synthetic fixture"
            with closing(sqlite3.connect(database)) as dst:
                src.backup(dst)
                counts = {table: dst.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                          for table in ("health_sample", "strength_set", "strength_session", "exercise_catalog")}
                extra_imports = dst.execute("SELECT COUNT(*) FROM health_sample WHERE "
                                            "fingerprint LIKE 'synthetic-performance-import-%'").fetchone()[0]
        assert counts["health_sample"] == size + extra_imports and counts["strength_set"] == 10_000, counts
        initial_bytes = database.stat().st_size
        t0 = time.perf_counter()
        with isolated_app(root, folder) as base, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 390, "height": 844})
            open_at = time.perf_counter()
            page.goto(base + "/?workspace=strength")
            check = RedesignCheck(page, database, folder)
            check.wait(lambda: check.testid("strength-home").is_visible(), timeout=60000)
            ready = time.perf_counter()
            check.click("open-start")
            times = []
            for _ in range(30):
                times.append(check.choose("平板", "psa.ex.barbell_bench_press"))
            assert len(check.active()["exercises"]) == 30
            return {"counts_before": counts, "database_bytes_before": initial_bytes,
                    "browser": browser.version, "viewport": [390, 844],
                    "cold_n": 1, "process_launch_to_first_page_ms": 1000 * (ready - t0),
                    "navigation_to_first_page_ms": 1000 * (ready - open_at),
                    "selection_n": len(times), "selection_ms": times,
                    "selection_p50_ms": statistics.median(times),
                    "selection_p95_ms": percentile(times, .95)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", default=[100_000, 1_000_000])
    args = parser.parse_args()
    report = {"data": "synthetic_only", "platform": platform.platform(),
              "python": platform.python_version(), "logical_cpus": os.cpu_count(),
              "mem_total": Path("/proc/meminfo").read_text().splitlines()[0],
              "method": "localhost Chromium; click result to durable receipt and editable view, including Playwright checks. Repeated selection grows to 30 distinct instances. OS caches retained. Shared host.",
              "sizes": {}}
    root = Path(__file__).resolve().parents[2]
    for size in args.sizes:
        record = measure((args.directory / f"synthetic-{size}.sqlite3").resolve(), size, root)
        report["sizes"][size] = record
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(size, record["selection_p50_ms"], record["selection_p95_ms"], flush=True)


if __name__ == "__main__":
    main()
