"""Local scientific evaluation entry points; uses only supplied/ synthetic data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import evaluate_all
from .prediction import forward_evaluate
from .research import calibrate


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="HealthZIP v1.3 scientific validation tools")
    commands = parser.add_subparsers(dest="command", required=True)
    sim = commands.add_parser("calibrate", help="Run reproducible simulation-only calibration")
    sim.add_argument("--output", default=".local/science-evaluation")
    sim.add_argument("--seed", type=int, default=1300)
    sim.add_argument("--repetitions", type=int, default=300)
    evaluate = commands.add_parser("evaluate", help="Evaluate all registered metrics from a local JSON snapshot")
    evaluate.add_argument("snapshot")
    evaluate.add_argument("--output", required=True)
    forward = commands.add_parser("forward-evaluate", help="Evaluate B0/B1 against a locked local split")
    forward.add_argument("snapshot")
    forward.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.command == "calibrate":
        output = calibrate(args.output, seed=args.seed, repetitions=args.repetitions)
        print(json.dumps({"status": output["scope_status"], "artifact_ids": [a["artifact_id"] for a in output["artifacts"]],
                          "manifest": str(Path(args.output) / "calibration_manifest.json")}, ensure_ascii=False))
    else:
        snapshot = json.loads(Path(args.snapshot).read_text("utf-8"))
        if args.command == "evaluate":
            output = evaluate_all(**snapshot)
        else:
            output = forward_evaluate(snapshot["observations"], split=snapshot["split"], feature=snapshot["feature"])
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
