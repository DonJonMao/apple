"""Compare only report_comparison, using deterministic in-memory synthetic rows.

This is a stage diagnostic, not an original 100k/1m fixture or R06 acceptance run.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import resource
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from time import perf_counter

from healthzip.science import reports
from healthzip.science.contracts import Window


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def fixture():
    rows = []
    origin = datetime.fromisoformat("2026-10-12T00:00:00+08:00")
    for day in range(35):
        start = origin + timedelta(days=day)
        for slot in range(48):
            left, right = start + timedelta(minutes=slot * 30), start + timedelta(minutes=(slot + 1) * 30)
            for canonical, amount in (("basal_energy_kcal", 38), ("active_energy_kcal", 5 + slot % 7)):
                rows.append({"id": f"{canonical}-{day}-{slot}", "canonical_type": canonical,
                             "event_start": left.isoformat(), "event_end": right.isoformat(),
                             "available_at": (right + timedelta(minutes=1)).isoformat(),
                             "value": amount, "unit": "kcal", "source_name": "Synthetic phase watch"})
        event = (start + timedelta(hours=8)).isoformat()
        for canonical, unit, value in (("resting_heart_rate_bpm", "bpm", 60 + day % 9),
                                        ("hrv_sdnn_ms", "ms", 25 + day % 13)):
            rows.append({"id": f"{canonical}-{day}", "canonical_type": canonical,
                         "event_start": event, "event_end": event, "available_at": event,
                         "value": value, "unit": unit, "source_name": "Synthetic phase watch"})
        rows.append({"id": f"sleep-{day}", "canonical_type": "sleep_stage", "stage": "asleep",
                     "event_start": (start - timedelta(hours=2)).isoformat(),
                     "event_end": (start + timedelta(hours=6)).isoformat(), "available_at": event,
                     "source_name": "Synthetic phase sleep"})
    for index in range(10_000):
        event = "2026-11-10T09:00:00+08:00"
        rows.append({"id": f"ordinary-{index}", "record_kind": "strength_set",
                     "event_start": event, "event_end": event, "available_at": event,
                     "is_reference": False, "condition_key": None})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("healthzip.science._comparison_before", args.before_source)
    before = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(before)
    rows = fixture()
    original_hash = digest(rows)
    window = Window("2026-11-09T00:00:00+08:00", "2026-11-16T00:00:00+08:00",
                    "2026-11-15T12:00:00+08:00", "Asia/Shanghai")
    calculations = {"before": before.report_comparison, "after": reports.report_comparison}
    samples = []
    expected_hash = None
    for pair in range(3):
        order = ("before", "after") if pair % 2 == 0 else ("after", "before")
        for name in order:
            started = perf_counter()
            value = calculations[name](rows, window)
            elapsed = perf_counter() - started
            output_hash = digest(value)
            if expected_hash is None:
                expected_hash = output_hash
            assert output_hash == expected_hash
            samples.append({"pair": pair + 1, "variant": name, "elapsed_s": elapsed,
                            "output_sha256": output_hash})
    assert digest(rows) == original_hash
    result = {
        "scope": "report_comparison_only_in_memory_synthetic_diagnostic_not_R06_acceptance",
        "source_files": {"before": {"path": str(args.before_source),
                                    "sha256": hashlib.sha256(args.before_source.read_bytes()).hexdigest()},
                         "after": {"path": str(Path(reports.__file__)),
                                   "sha256": hashlib.sha256(Path(reports.__file__).read_bytes()).hexdigest()}},
        "fixture": {"rows": len(rows), "sha256": original_hash,
                    "domains": dict(Counter(row.get("canonical_type", "strength_set") for row in rows)),
                    "window": window.as_dict(), "original_rows_unchanged": True},
        "machine": {"platform": platform.platform(), "logical_cpus": os.cpu_count(),
                    "load_average_at_end": os.getloadavg(),
                    "process_peak_rss_kib_includes_both_variants": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
        "samples": samples,
        "median_s": {name: median(item["elapsed_s"] for item in samples if item["variant"] == name)
                     for name in calculations},
        "complete_outputs_equal": True,
        "interpretation": "Paired single-stage times are not full report time, cold latency or P95; original pressure fixtures remain unchanged.",
    }
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"median_s": result["median_s"], "equal": True, "rows": len(rows)}))


if __name__ == "__main__":
    main()
