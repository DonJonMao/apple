"""Freeze public code and run every discovered pytest file in isolated shards."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_files():
    paths = [ROOT / "app.py", ROOT / "pyproject.toml", ROOT / ".streamlit/config.toml"]
    for folder in ("src", "tests", "tools"):
        paths.extend(p for p in (ROOT / folder).rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"})
    return sorted(set(paths))


def digest(paths):
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def run(output, shards):
    output.mkdir(parents=True, exist_ok=True)
    python = ROOT / ".venv/bin/python"
    paths = source_files()
    manifest = digest(paths)
    (output / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with tempfile.TemporaryDirectory(prefix="hz-master-regression-") as temporary:
        base = Path(temporary)
        frozen = base / "frozen"
        frozen.mkdir()
        tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
        copied = {ROOT / name for name in tracked if name and (ROOT / name).is_file()}
        copied.update(paths)
        for source in sorted(copied):
            relative = source.relative_to(ROOT)
            if relative.parts[0] in {".local", ".env", ".venv", ".git"}:
                raise ValueError("Private runtime files must not enter a regression snapshot")
            target = frozen / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        env = {**os.environ, "PYTHONPATH": "src:.", "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false"}
        discovery = subprocess.run([str(python), "-m", "pytest", "--collect-only", "-q"],
                                   cwd=frozen, env=env, capture_output=True, text=True)
        (output / "discovery.txt").write_text(discovery.stdout + discovery.stderr)
        if discovery.returncode:
            raise RuntimeError("pytest discovery failed; see discovery.txt")
        nodes = [line.strip() for line in discovery.stdout.splitlines() if line.startswith("tests/") and "::" in line]
        files = sorted({node.split("::", 1)[0] for node in nodes})
        if not files:
            raise RuntimeError("No pytest files discovered")
        weights = {}
        for old in (ROOT / "artifacts/product_redesign/validation").glob("final-shard-*.json"):
            for case in json.loads(old.read_text()).get("test_cases", []):
                filename = case["name"].split("::", 1)[0].replace(".", "/") + ".py"
                weights[filename] = weights.get(filename, 0) + case["seconds"]
        assignments, loads = [[] for _ in range(shards)], [0.0] * shards
        for filename in sorted(files, key=lambda name: weights.get(name, 3), reverse=True):
            index = min(range(shards), key=lambda i: loads[i])
            assignments[index].append(filename)
            loads[index] += weights.get(filename, 3)
        (output / "assignments.json").write_text(json.dumps(assignments, indent=2) + "\n")

        def shard(index):
            folder = base / f"shard-{index}"
            shutil.copytree(frozen, folder)
            command = [str(python), "-m", "pytest", "-q", *assignments[index],
                       "--junitxml", str(output / f"shard-{index}.xml")]
            started = time.perf_counter()
            with (output / f"shard-{index}.log").open("w") as log:
                process = subprocess.run(command, cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT)
            elapsed = time.perf_counter() - started
            tree = ET.parse(output / f"shard-{index}.xml")
            cases = []
            for case in tree.iter("testcase"):
                state = next((state for state in ("failure", "error", "skipped") if case.find(state) is not None), "passed")
                cases.append({"name": case.get("classname") + "::" + case.get("name"),
                              "seconds": float(case.get("time", "0")), "status": state})
            result = {"shard": index, "exit_code": process.returncode, "seconds": elapsed,
                      "test_files": assignments[index], "test_cases": cases}
            (output / f"shard-{index}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(f"shard {index}: {len(cases)} cases, exit {process.returncode}, {elapsed:.1f}s", flush=True)
            return result

        with ThreadPoolExecutor(max_workers=shards) as pool:
            results = list(pool.map(shard, range(shards)))
    current = digest(source_files())
    changed = [name for name in sorted(set(manifest) | set(current)) if current.get(name) != manifest.get(name)]
    cases = [case for result in results for case in result["test_cases"]]
    counts = {state: sum(case["status"] == state for case in cases) for state in ("passed", "failure", "error", "skipped")}
    matched_count = len(cases) == len(nodes)
    report = {"data": "synthetic_only; public tracked resources and code, no .local copied",
              "status": "passed" if all(result["exit_code"] == 0 for result in results) and not changed and matched_count else "needs_review",
              "tests_discovered": len(nodes), "test_files": len(files), "tests_executed": len(cases),
              "counts": counts, "discovery_count_matches": matched_count, "source_changes_during_run": changed,
              "execution": "Every discovered file exactly once, isolated directories/processes; historical timings used only for balancing",
              "shards": [{key: value for key, value in result.items() if key not in {"test_cases", "test_files"}} for result in results]}
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/master_redesign/validation/final")
    parser.add_argument("--shards", type=int, default=4, choices=range(1, 5))
    args = parser.parse_args()
    raise SystemExit(run(args.output.resolve(), args.shards))
