"""One instrumented synthetic heart path; nested stages intentionally overlap."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.code_root / "src"))
    import healthzip.analytics.v13 as v13
    import healthzip.analytics.workspaces as workspaces
    from healthzip.analytics.cache import clear
    from healthzip.db.repository import Repository
    from healthzip.training.service import TrainingService

    stages = {}

    def wrap(target, name, label):
        original = getattr(target, name)

        def measured(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                stage = stages.setdefault(label, {"calls": 0, "milliseconds": 0})
                stage["calls"] += 1
                stage["milliseconds"] += (time.perf_counter() - started) * 1000

        setattr(target, name, measured)

    if hasattr(workspaces, "snapshot"):
        wrap(workspaces, "snapshot", "generic_snapshot")
    else:
        wrap(workspaces, "_body_snapshot", "body_snapshot")
    wrap(v13, "samples_as_of", "generic_source_queries_and_decode")
    wrap(workspaces, "samples_as_of", "body_source_queries_and_decode")
    wrap(workspaces, "evaluate", "scientific_evaluation")
    for name in ("list_recommendations", "events_as_of", "history_as_of"):
        wrap(TrainingService, name, "training_" + name)
    started = time.perf_counter()
    repo = Repository(args.database)
    opened = time.perf_counter()
    statements = []
    repo.conn.set_trace_callback(lambda sql: statements.append(sql.lstrip().split(None, 1)[0].upper()))
    clear()
    result = workspaces.analyze_workspace(repo, "心率 / HRV")
    computed = time.perf_counter()
    payload = json.dumps(result, ensure_ascii=False)
    encoded = time.perf_counter()
    from collections import Counter
    output = {"kind": "synthetic_instrumented_backend_nested_stages", "repository_open_ms": (opened-started)*1000,
        "server_compute_ms": (computed-opened)*1000, "result_serialization_ms": (encoded-computed)*1000,
        "serialized_result_bytes": len(payload.encode()), "stages": stages, "statements": dict(Counter(statements)),
        "model_and_rag_calls": 0, "browser_render_and_transport": "measured separately by browser acceptance"}
    repo.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2))
    print(json.dumps(output), flush=True)


if __name__ == "__main__":
    main()
