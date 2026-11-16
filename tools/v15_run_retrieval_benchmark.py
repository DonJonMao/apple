"""Run a frozen public/synthetic retrieval benchmark on a local knowledge snapshot.

A-D remove semantic applicability only, retaining source/rights/lifecycle checks;
E uses the production pipeline. A_filtered is an additional fair lexical
comparison with the same applicability policy as E. The bypass exists only in
this offline evaluator and must never run in an application server process.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import time
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

from healthzip.knowledge import KnowledgeWorkbench, domains
from healthzip.knowledge.model_services import load_services
from healthzip.knowledge.retrieval_evaluation import aggregate, evaluate_saved_rankings, score_case
from healthzip.knowledge.store import digest, dumps, now
from healthzip.science import evaluate

VARIANTS = {"A": ("lexical", False), "B": ("dense", False), "C": ("hybrid", False),
            "D": ("hybrid_rerank", False), "E": ("hybrid_rerank", True),
            "A_filtered": ("lexical", True)}


def run(root, gold_path, services_config, release_id, private_output, public_output):
    raw = Path(gold_path).read_bytes()
    gold = json.loads(raw)
    if (gold.get("schema") != "metric-retrieval-gold-1.5.0" or not gold.get("created_at")
            or not gold.get("annotator") or not gold.get("synthetic_context_only")
            or not all(c.get("synthetic_context") is True for c in gold["cases"])):
        raise ValueError("identified_frozen_public_synthetic_gold_required")
    freeze_path = Path(gold_path).with_name(Path(gold_path).stem + "-freeze.json")
    freeze = json.loads(freeze_path.read_text())
    if (freeze["gold_sha256"] != digest(raw) or freeze["production_profiles_sha256"] !=
            digest(dumps(domains.configuration()).encode())):
        raise ValueError("frozen_gold_or_retrieval_profile_changed")
    private = Path(private_output)
    private.mkdir(parents=True, exist_ok=True)
    w = KnowledgeWorkbench(root)
    try:
        services = load_services(w.root, config_path=services_config)
        identity = {"gold_sha256": digest(raw), "release_id": release_id,
                    "profile_sha256": digest(dumps(domains.configuration()).encode()),
                    "runner_sha256": digest(Path(__file__).read_bytes()),
                    "models": [provider.config.identity for provider in services],
                    "variants": VARIANTS}
        identity_path = private / "run-identity.json"
        if identity_path.exists():
            if json.loads(identity_path.read_text()) != json.loads(dumps(identity)):
                raise ValueError("resume_requires_same_frozen_run_identity")
        else:
            with identity_path.open("x") as stream:
                stream.write(dumps(identity) + "\n")
        experiments, filtered_rows, timings = {}, [], []
        for variant, (mode, applicability) in VARIANTS.items():
            outputs = {}
            for case in gold["cases"]:
                saved = private / (variant + "-" + case["case_id"] + ".json")
                if saved.exists():
                    record = json.loads(saved.read_text())
                    result = record["result"]
                else:
                    metric = evaluate(case["metric_id"], [], cutoff_time="2026-11-17T00:00:00+00:00",
                        window_start="2026-11-01T00:00:00+00:00", window_end="2026-11-17T00:00:00+00:00")
                    # Intentional experiment ablation, isolated to this offline process.
                    context = contextlib.nullcontext() if applicability else patch(
                        "healthzip.knowledge.metric_retrieval.context_match", return_value=(True, "evaluation_ablation"))
                    started = time.monotonic()
                    with context:
                        result = w.retrieve_for_metric(case["metric_id"], "explain_metric", metric,
                            case["context"], release_id, mode=mode, k=6, services=services)
                    record = {"created_at": now(), "variant": variant, "case_id": case["case_id"],
                              "elapsed_seconds": round(time.monotonic() - started, 6), "result": result}
                    with saved.open("x") as stream:
                        stream.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
                    print(variant, case["case_id"], result["status"], record["elapsed_seconds"], flush=True)
                outputs[case["case_id"]] = result
                timings.append({"variant": variant, "case_id": case["case_id"],
                                "elapsed_seconds": record["elapsed_seconds"]})
                if variant == "A_filtered":
                    filtered_rows.append(score_case(case, result))
            if variant != "A_filtered":
                experiments[variant] = outputs
        config = {"schema": "metric-hybrid-1.5.0", "k": 6, "rrf_constant": 60,
            "candidate_budget": 20, "reranker_input_utf8_bytes": 24000,
            "ablation": "A-D semantic applicability disabled; source rights and lifecycle always enforced",
            "A_filtered": "additional lexical reference with the identical applicability policy as E",
            "identity": identity, "gold_label_scope": gold.get("annotation_scope")}
        report = evaluate_saved_rankings(gold_path, experiments, public_output,
            model_identities=identity["models"], retrieval_config=config)
        extra = {"created_at": now(), "gold_sha256": digest(raw), "timings": timings,
                 "filtered_lexical_reference": {"overall": aggregate(filtered_rows), "cases": filtered_rows},
                 "latency_scope": "A,B,C,D,E,A_filtered sequential; query embeddings warm after B; one measurement per cell, not P95 or a latency ablation"}
        splits = {case["case_id"]: case.get("evaluation_split", "unspecified") for case in gold["cases"]}
        extra["by_annotation_split"] = {}
        for variant, records in [(key, value["cases"]) for key, value in report["experiments"].items()] + [("A_filtered", filtered_rows)]:
            groups = defaultdict(list)
            for row in records:
                groups[splits[row["case_id"]]].append(row)
            extra["by_annotation_split"][variant] = {split: aggregate(rows) for split, rows in groups.items()}
        with (Path(public_output) / "filtered-lexical-and-latency.json").open("x") as stream:
            stream.write(json.dumps(extra, ensure_ascii=False, indent=2) + "\n")
        return report
    finally:
        w.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "gold", "services-config", "release-id", "private-output", "public-output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    result = run(args.root, args.gold, args.services_config, args.release_id,
                 args.private_output, args.public_output)
    print(json.dumps({"gold_sha256": result["gold_sha256"], "experiments": list(result["experiments"])}))
