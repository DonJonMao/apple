"""Small synthetic computation diagnostic; no database or report/P95 claim."""
import argparse
import cProfile
import gzip
import hashlib
import json
import pstats
import time
from pathlib import Path

from healthzip.science import evaluate_all
from healthzip.science.semantics import flatten_record
from tests.science.test_contracts_and_strength import CUTOFF, END, START, row


def stable(value):
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items() if key != "computed_at"}
    if isinstance(value, list):
        return [stable(item) for item in value]
    return value


parser = argparse.ArgumentParser()
parser.add_argument("label")
args = parser.parse_args()
out = Path(__file__).resolve().parent
root = out.parents[2]
ordinary = [row(1, id=f"ordinary-{i}", set_id=f"ordinary-{i}", session_id=f"session-{i//4}",
                is_reference=False, equipment_instance_id=None) for i in range(1000)]
mixed = [row(i) for i in range(1, 13)] + [
    row(14, load_basis="assistance_setting", load_value=40),
    row(15, load_basis="per_dumbbell_kg", implement_count=2),
    row(16, load_basis="plates_per_side_kg", effective_bar_mass_kg=20, symmetric_loading=True),
    row(17, load_basis="unknown", load_basis_confirmed=False),
    row(18, equipment_instance_id=None, is_reference=False),
    row(19, equipment_instance_id=None, is_reference=False, rir=0),
    row(20, record_status="deleted"), row(21, conflicted=True),
    row(22, available_at=None), row(23, available_at="2026-12-15T00:00:00Z"),
    row(24, actual_json=json.dumps({"load_value": 35, "rir": 3, "rir_qualifier": "at_least"})),
]
fixtures = {"empty": [], "ordinary-1000": ordinary, "mixed-references-and-visibility": mixed}
report = {"scope": "Synthetic evaluate_all microdiagnostic, 77 metrics; not full report performance",
          "source": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in [*(root / "src/healthzip/science").glob("*.py"), root / "src/healthzip/analytics/v13.py"]},
          "fixtures": []}
for name, records in fixtures.items():
    profile = cProfile.Profile()
    start = time.perf_counter()
    profile.enable()
    result = evaluate_all(records, cutoff_time=CUTOFF, window_start=START, window_end=END,
                          context={"reference_inventory": [flatten_record(r) for r in records]})
    profile.disable()
    elapsed = time.perf_counter() - start
    encoded = json.dumps(stable(result), sort_keys=True, ensure_ascii=False).encode()
    (out / f"{args.label}-{name}.json.gz").write_bytes(gzip.compress(encoded, mtime=0))
    profile.dump_stats(str(out / f"{args.label}-{name}.prof"))
    hotspots = [{"file": file.rsplit("/healthzip/", 1)[-1], "line": line, "function": function,
                 "calls": values[1], "self_seconds": values[2], "cumulative_seconds": values[3]}
                for (file, line, function), values in sorted(pstats.Stats(profile).stats.items(),
                       key=lambda pair: pair[1][3], reverse=True)[:50]]
    report["fixtures"].append({"name": name, "records": len(records), "metrics": len(result),
        "profiled_seconds": elapsed, "scientific_sha256": hashlib.sha256(encoded).hexdigest(),
        "serialized_bytes": len(encoded), "hotspots": hotspots})
(out / f"{args.label}.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps([{k: v for k, v in item.items() if k != "hotspots"} for item in report["fixtures"]], indent=2))
