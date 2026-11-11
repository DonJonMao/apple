"""Separate software checks, evidence retrieval and human semantic adjudication."""

from __future__ import annotations

import json
import math
from pathlib import Path

from .retrieval import validate_answer
from .store import digest, dumps, now


def proportion(numerator: int, denominator: int) -> dict:
    if not denominator:
        return {"numerator": numerator, "denominator": 0, "value": None, "interval": None, "reason": "no_eligible_observations"}
    p = numerator / denominator
    z = 1.959963984540054
    center = (p + z * z / (2 * denominator)) / (1 + z * z / denominator)
    half = z * math.sqrt(p * (1 - p) / denominator + z * z / (4 * denominator ** 2)) / (1 + z * z / denominator)
    return {"numerator": numerator, "denominator": denominator, "value": p,
            "interval": {"kind": "Wilson_binomial_95_percent_descriptive", "low": max(0, center - half), "high": min(1, center + half),
                         "limitation": "purposive case set; interval is descriptive, not population safety guarantee"}}


def evaluate(workbench, cases_path, *, split="visible_development", annotations_path=None, k=6,
             metric_provider=None) -> dict:
    path = Path(cases_path)
    raw = path.read_bytes()
    dataset = json.loads(raw)
    cases = dataset["cases"]
    annotations = {}
    if annotations_path:
        annotations = {x["case_id"]: x for x in json.loads(Path(annotations_path).read_text())["annotations"]}
    counts = {"schema_pass": 0, "citation_valid": 0, "citation_total": 0, "gold_recalled": 0,
              "gold_total": 0, "gold_available": 0, "answer_with_evidence": 0, "abstentions": 0,
              "semantic_pass": 0, "semantic_reviewed": 0, "route_pass": 0,
              "positive_cases": 0, "positive_abstentions": 0, "unsupported_numeric_actions": 0}
    records = []
    for case in cases:
        metrics = metric_provider(case) if metric_provider else []
        result = workbench.query(case["query_zh"], context=case.get("input_context", {}), personal_metrics=metrics, k=k)
        required = case.get("required_output_fields", ["observations", "answer", "limits", "citations", "status"])
        schema_errors = ["missing_field:" + x for x in required if x not in result]
        counts["schema_pass"] += not schema_errors
        found_routes = {x["route"] for x in result["routes"]}
        route_ok = set(case.get("expected_routes", [case.get("route", "strength")])) <= found_routes
        counts["route_pass"] += route_ok
        source_ids = {x["source_id"] for x in result["citations"]}
        groups = case.get("gold_evidence_groups", [[x] for x in case.get("gold_source_ids", [])])
        recalled = sum(bool(set(group) & source_ids) for group in groups)
        available = 0
        for group in groups:
            active_sources = set()
            for r in workbench.lib.theories.execute("SELECT review_json FROM theory WHERE status='approved'"):
                review = json.loads(r[0])
                for link in review.get("evidence_links", []):
                    if all(workbench.lib.span(sid) and workbench.lib.eligible(workbench.lib.span(sid))[0] for sid in link["span_ids"]):
                        active_sources.add(link["source_id"])
            available += bool(active_sources.intersection(group))
        counts["gold_recalled"] += recalled
        counts["gold_total"] += len(groups)
        counts["gold_available"] += available
        validation = validate_answer(workbench, result, result)
        counts["citation_total"] += len(result["citations"])
        counts["citation_valid"] += len(result["citations"]) if not validation else 0
        counts["answer_with_evidence"] += bool(result["citations"])
        counts["abstentions"] += result["status"] == "insufficient_evidence"
        counts["unsupported_numeric_actions"] += bool(result.get("numeric_actions"))
        if case.get("case_type") == "positive":
            counts["positive_cases"] += 1
            counts["positive_abstentions"] += result["status"] == "insufficient_evidence"
        adjudication = annotations.get(case["case_id"])
        semantic = "pending_independent_semantic_adjudication"
        if adjudication and adjudication.get("reviewer") and adjudication.get("rationale"):
            # Bind review to actual output; stale annotations are never reused for changed answers.
            if adjudication.get("output_sha256") == digest(dumps(result).encode()):
                semantic = adjudication.get("decision", "pending")
                counts["semantic_reviewed"] += semantic in {"pass", "fail"}
                counts["semantic_pass"] += semantic == "pass"
        records.append({"case_id": case["case_id"], "case_type": case.get("case_type"), "expected_outcome": case.get("expected_outcome"),
                        "actual_status": result["status"], "schema_errors": schema_errors, "citation_errors": validation,
                        "route_match": route_ok, "required_gold_groups": groups, "recalled_groups": recalled,
                        "reviewed_gold_groups_available": available, "semantic_adjudication": semantic,
                        "output_sha256": digest(dumps(result).encode()), "output": result})
    return {"evaluation_version": "rag-eval-1.3.0", "run_at": now(), "split": split,
            "dataset_path": str(path), "dataset_sha256": digest(raw), "case_count": len(cases), "k": k,
            "metric_provider": getattr(metric_provider, '__module__', None),
            "counts": counts, "schema_pass_rate": proportion(counts["schema_pass"], len(cases)),
            "citation_locatability": proportion(counts["citation_valid"], counts["citation_total"]),
            "gold_group_recall_all_candidates": proportion(counts["gold_recalled"], counts["gold_total"]),
            "gold_group_corpus_coverage": proportion(counts["gold_available"], counts["gold_total"]),
            "semantic_support_rate": proportion(counts["semantic_pass"], counts["semantic_reviewed"]),
            "positive_abstention_rate": proportion(counts["positive_abstentions"], counts["positive_cases"]),
            "corpus_status": workbench.status(), "cases": records,
            "release_gate": "pending_corpus_and_semantic_review" if counts["semantic_reviewed"] < len(cases) else "inspect_case_failures",
            "limits": ["Visible development cases are regression examples, not an independent test set.",
                       "Keyword presence is not used as semantic correctness scoring.",
                       "Zero emitted citations does not establish citation quality.",
                       "No intervention effectiveness or personal scientific validity is inferred.",
                       dataset.get("independence_note", "Source-family independence requires a separately curated holdout.")]}
