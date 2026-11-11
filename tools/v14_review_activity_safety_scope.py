"""Verify HHS cross-chapter age scope and publish one explanation-only contract.

Uses existing source bytes and exact spans. Previous releases and frozen evidence
remain unchanged; no personal inference or training-candidate authority is added.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.store import digest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("source_topics", ROOT / "tools/v14_expand_source_explanations.py")
TOPICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOPICS)


def explanation_contracts():
    definition = json.loads((ROOT / "src/healthzip/knowledge/data/activity_safety_scope_1_4_8.json").read_text())
    contracts = []
    for topic in definition["claims"]:
        source = definition["sources"][topic["source_id"]]
        version = source["source_version_id"]
        reviewed = {item["span_index"] for item in source["reviewed_spans"]}
        parts = []
        for part in topic["answer_parts"]:
            if not set(part["span_indices"]) <= reviewed:
                raise ValueError("topic references a span outside its source review")
            parts.append({"part_id": part["part_id"], "text": part["text"],
                          "span_ids": [version + f":s{i:05d}" for i in part["span_indices"]],
                          "evidence_relation": part["evidence_relation"]})
        limits = [*definition["shared_limitations"], *source["limitations"]]
        claim = {"claim_id": topic["claim_id"], "version": definition["version"],
                 "statement": "\n".join(part["text"] for part in parts), "scope": topic["scope"],
                 "limitations": limits, "numeric": False,
                 "evidence_links": [{"source_id": topic["source_id"], "source_version_id": version,
                                     "span_ids": sorted({sid for part in parts for sid in part["span_ids"]})}],
                 "answer_task": {**{k: topic[k] for k in ("subject", "outcome", "requested_relation")},
                                 "evidence_relation": "supports", "answer_complete": True,
                                 "required_answer_parts": [part["part_id"] for part in parts],
                                 "routes": topic["routes"], "answer_parts": parts}}
        rule = {"rule_id": topic["claim_id"].replace("CORE-CLAIM-", "RULE-") + "-EXPLANATION",
                "rule_version": definition["version"], "requested_capability": "source_explanation",
                "capability_policy_version": "personal-trial-policy-1.4.0",
                "claim_refs": [{"claim_id": claim["claim_id"], "version": claim["version"]}],
                "routes": topic["routes"], "permitted_actions": [], "numeric_provenance": [],
                "conditions": [{"field": "requested_capability", "op": "eq",
                                "value": "source_explanation", "origin": "product_scope"}],
                "coverage_scope": topic["outcome"],
                "application_logic": "仅解释明确匹配的来源主题与范围；保持出处、每段证据和限制，不据此计算个人模型、选择个人参数或产生训练候选。",
                "limits": limits,
                "forbidden": ["numeric_training_candidate", "individual_equivalence_inference",
                              "individual_prediction", "causal_effect", "automatic_clinical_prescription"],
                "implementation_validation_refs": ["tests/unit/test_activity_safety_scope_contract.py",
                                                   "src/healthzip/knowledge/core.py::core_principles"]}
        contracts.append((topic, claim, rule))
    tasks = [tuple(c[1]["answer_task"][key] for key in ("subject", "outcome", "requested_relation")) for c in contracts]
    if len(set(tasks)) != len(contracts):
        raise ValueError("each newly reviewed topic needs its own task contract")
    return definition, contracts


def protected_hashes():
    public = ROOT / "artifacts/v14/knowledge"
    previous = json.loads((public / "regression-covariance-release-verification-1.4.7.json").read_text())
    hashes = dict(previous["protected_artifact_sha256"])
    for name in ("release-1.4.7.json", "regression-covariance-review-1.4.7.json",
                 "regression-covariance-explanation-1.4.7.json", "regression-covariance-verification-1.4.7.xml",
                 "regression-covariance-release-verification-1.4.7.json",
                 "regression-covariance-integration-development-1.4.7.json",
                 "regression-covariance-integration-development-replay-1.4.7.json",
                 "method-explanation-feature-map-1.4.7.json", "source_rule_feature_matrix.csv"):
        path = public / name
        hashes[str(path.relative_to(ROOT))] = digest(path.read_bytes())
    path = ROOT / "src/healthzip/knowledge/data/regression_covariance_1_4_7.json"
    hashes[str(path.relative_to(ROOT))] = digest(path.read_bytes())
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-root", type=Path, default=ROOT / ".local/knowledge")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/v14/knowledge")
    parser.add_argument("--activate-explanation", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    definition, contracts = explanation_contracts()
    if len(contracts) != 1:
        raise ValueError("one separate safety-scope explanation required")
    report_path = args.output_dir / "activity-safety-scope-review-1.4.8.json"
    frozen = (json.loads(report_path.read_text())["protected_artifact_sha256"]
              if report_path.exists() else protected_hashes())
    TOPICS.verify_hashes(frozen)
    w = KnowledgeWorkbench(args.knowledge_root)
    try:
        source_before, before = TOPICS.source_snapshot(w), TOPICS.HHS.snapshot(w)
        sources, spans = TOPICS.verify_sources(w, definition)
        outputs = {report_path: {
            "version": definition["version"], "reviewer_kind": "ai_assisted", "sources": sources,
            "functional_gap": "Chapter 4 adult scope does not answer Chapter 7 safety-guidance age scope. Most, rather than all, advice applies to all ages; specific age and condition guidance remains.",
            "new_topic_count": 1, "independent_ai_denominator": 0, "independent_human_or_expert_denominator": 0,
            "personal_calibration_supplied": False, "source_library_mutations": 0,
            "protected_artifact_sha256": frozen,
            "evaluation_boundary": "The frozen independent round-four questions, outputs and initial judgments were not read or modified by this tool."}}
        if args.activate_explanation:
            release, reviewed, previous_sha = TOPICS.activate(w, definition, contracts)
            outputs[args.output_dir / "release-1.4.8.json"] = release
            outputs[args.output_dir / "activity-safety-scope-explanation-1.4.8.json"] = {
                "release_id": release["release_id"], "release_sha256": release["sha256"],
                "previous_release_id": definition["previous_release_id"], "previous_release_sha256": previous_sha,
                "new_contracts": reviewed, "claims_in_release": len(release["claims"]),
                "rules_in_release": len(release["rules"]), "previous_members_unchanged": True,
                "independent_ai_denominator": 0, "independent_human_or_expert_denominator": 0,
                "personal_calibration_supplied": False, "source_library_mutations": 0}
        after = TOPICS.HHS.snapshot(w)
        if any(row not in after[table] for table, rows in before.items() for row in rows):
            raise ValueError("pre-existing immutable knowledge record changed")
        if TOPICS.source_snapshot(w) != source_before:
            raise ValueError("source library changed during safety-scope review")
        TOPICS.verify_hashes(frozen)
        for path, value in outputs.items():
            TOPICS.HHS.write_public(path, value, spans)
        print(json.dumps({"source_verified": True, "explanation_activated": args.activate_explanation,
                          "release_id": definition["release_id"] if args.activate_explanation else None,
                          "protected_file_count": len(frozen), "protected_files_unchanged": True,
                          "source_library_unchanged": True}))
    finally:
        w.close()


if __name__ == "__main__":
    main()
