"""Small paired STR-11 prototype-copy benchmark; no database or pressure run."""
from __future__ import annotations

import cProfile
import gc
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from collections import Counter
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from healthzip.science import engine  # noqa: E402
from healthzip.science.contracts import canonical_hash, select_as_of  # noqa: E402
from healthzip.science.semantics import flatten_record  # noqa: E402
from tests.science.test_contracts_and_strength import row  # noqa: E402
from tests.science.test_followup_reference_batch import WINDOW, calculated  # noqa: E402


def main():
    output = Path(__file__).resolve().parent
    assert not (output / "receipt.json").exists(), "Preserve previous benchmark results"
    files = [ROOT / "src/healthzip/science/engine.py", ROOT / "tests/science/test_followup_reference_batch.py",
             output / "baseline-engine-excerpt.py", Path(__file__)]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    context = {"timezone": "UTC", "comparison_pair": [row(8, available_at="2026-12-01T00:00:00Z")]}
    bounded = engine._bounded_context(context, WINDOW)
    records, _ = select_as_of([flatten_record(row(i, is_reference=False, equipment_instance_id=None, rir=None))
                              for i in (1, 2, 3)], WINDOW)
    prototype = calculated(records[:1], context)
    namespace = dict(vars(engine))
    exec((output / "baseline-engine-excerpt.py").read_text(), namespace)
    baseline = namespace["_ordinary_reference_result"]
    templates = {"no_designated_reference": prototype}
    assert baseline(records, WINDOW, context, bounded, templates) == engine._ordinary_reference_result(
        records, WINDOW, context, bounded, templates)
    assert engine._clone_ordinary_reference_result(prototype) == deepcopy(prototype)
    original_hash = canonical_hash(prototype)
    types = Counter()

    def walk(value):
        types[type(value).__name__] += 1
        if isinstance(value, dict):
            for key, item in value.items():
                walk(key)
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(prototype)
    result = {"diagnostic_only": True, "performance_acceptance": False, "synthetic_only": True,
              "source_hashes": hashes, "python": platform.python_version(), "platform": platform.platform(),
              "logical_cpus": os.cpu_count(), "initial_load": os.getloadavg(),
              "gc_enabled": gc.isenabled(), "gc_thresholds": gc.get_threshold(),
              "prototype_field_count": len(prototype), "prototype_types": dict(types),
              "prototype_sha256": original_hash, "context": context, "rounds": 9,
              "order": "baseline/optimized and optimized/baseline alternate by round",
              "stages": {}, "profile": {}}
    calls = {
        "clone": {"baseline": lambda: deepcopy(prototype),
                  "optimized": lambda: engine._clone_ordinary_reference_result(prototype)},
        "ordinary_reference_helper": {
            "baseline": lambda: baseline(records, WINDOW, context, bounded, templates),
            "optimized": lambda: engine._ordinary_reference_result(records, WINDOW, context, bounded, templates)},
    }
    for stage, variants in calls.items():
        count = 5000 if stage == "clone" else 2000
        samples = {"baseline": [], "optimized": []}
        for index in range(9):
            order = ("baseline", "optimized") if index % 2 == 0 else ("optimized", "baseline")
            for name in order:
                method = variants[name]
                started = time.perf_counter()
                for _ in range(count):
                    method()
                samples[name].append(time.perf_counter() - started)
        medians = {name: statistics.median(values) for name, values in samples.items()}
        result["stages"][stage] = {"calls_per_sample": count, "seconds": samples, "median_seconds": medians,
                                   "median_speedup": medians["baseline"] / medians["optimized"]}
    for name, method in calls["clone"].items():
        profile = cProfile.Profile()
        profile.enable()
        for _ in range(2000):
            method()
        profile.disable()
        profile.dump_stats(str(output / f"clone-{name}.prof"))
        result["profile"][name] = [{"name": str(item.code), "calls": item.callcount,
                                    "recursive_calls": item.reccallcount, "total_seconds": item.totaltime}
                                   for item in profile.getstats()
                                   if hasattr(item.code, "co_name") and item.code.co_name in {
                                       "deepcopy", "_clone_ordinary_reference_result"}]
    result.update(prototype_unchanged=canonical_hash(prototype) == original_hash,
                  source_unchanged=all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
                                       for name, digest in hashes.items()), final_load=os.getloadavg(),
                  gc_enabled_after=gc.isenabled())
    assert result["prototype_unchanged"] and result["source_unchanged"] and result["gc_enabled_after"]
    (output / "receipt.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"stages": result["stages"], "profile": result["profile"],
                      "prototype_unchanged": result["prototype_unchanged"]}, indent=2))


if __name__ == "__main__":
    main()
