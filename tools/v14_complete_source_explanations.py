"""Append three source topics and two answer revisions after frozen Round 6.

Existing source data, reviews, release members and candidate dependencies are
immutable. This is implementation-author AI-assisted review, not independent
scientific validation. Default execution verifies original source bytes only.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.store import digest, dumps

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("deepen", ROOT / "tools/v14_deepen_source_explanations.py")
DEEPEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEEPEN)
TOPICS = DEEPEN.TOPICS
TEST = "tests/unit/test_completion_explanation_contracts.py"


def definition():
    return json.loads((ROOT / "src/healthzip/knowledge/data/completion_explanations_1_4_12.json").read_text())


def new_rules(data):
    rules = []
    for item in data["claims"]:
        claim, task = item["claim"], item["claim"]["answer_task"]
        rules.append({
            "rule_id": claim["claim_id"].replace("CORE-CLAIM-", "RULE-") + "-EXPLANATION",
            "rule_version": data["version"], "requested_capability": "source_explanation",
            "capability_policy_version": "personal-trial-policy-1.4.0",
            "claim_refs": [{"claim_id": claim["claim_id"], "version": claim["version"]}],
            "routes": task["routes"], "permitted_actions": [], "numeric_provenance": [],
            "conditions": [{"field": "requested_capability", "op": "eq",
                            "value": "source_explanation", "origin": "product_scope"}],
            "coverage_scope": task["outcome"],
            "application_logic": "仅解释明确匹配的来源主题与范围；一般指南数值保留人群与目标语境，不据此选择个人参数或产生训练候选。",
            "limits": claim["limitations"],
            "forbidden": ["numeric_training_candidate", "personal_parameter_selection",
                          "individual_equivalence_inference", "individual_prediction", "causal_effect",
                          "automatic_clinical_prescription"],
            "implementation_validation_refs": [TEST, "src/healthzip/knowledge/core.py::core_principles"],
        })
    return rules


def validate_contracts(previous, data):
    if previous["release_id"] != data["previous_release_id"]:
        raise ValueError("exact previous release required")
    existing_claims = {(r["claim_id"], r["version"]): json.loads(r["payload_json"]) for r in previous["claims"]}
    tasks = []
    for item in data["claims"] + data["claim_revisions"]:
        claim = item["claim"]
        task = claim["answer_task"]
        if claim["version"] != data["version"] or claim.get("supersedes"):
            raise ValueError("only append-only explanations allowed")
        if claim.get("numeric") and any(link["source_id"] != "CORE-US-HHS-PAG-2" for link in claim["evidence_links"]):
            raise ValueError("only reviewed HHS public-health quantities are authorized here")
        target = tuple(task[k] for k in ("subject", "outcome", "requested_relation"))
        if item in data["claim_revisions"]:
            ref = item["replaces"]
            old = existing_claims.get((ref["claim_id"], ref["version"]))
            if (not old or claim.get("answer_revision_of") != ref or claim["claim_id"] != ref["claim_id"]
                    or target != tuple(old["answer_task"][k] for k in ("subject", "outcome", "requested_relation"))):
                raise ValueError("exact same-target claim predecessor required")
        elif any(cid == claim["claim_id"] for cid, _ in existing_claims) or claim.get("answer_revision_of"):
            raise ValueError("new topic identity must be new")
        tasks.append(target)
    if len(tasks) != len(set(tasks)):
        raise ValueError("duplicate answer target")
    rules = new_rules(data) + DEEPEN.revised_rules(previous, data)
    prior_rule_ids = {r["rule_id"] for r in previous["rules"]}
    if any(rule["rule_id"] in prior_rule_ids for rule in new_rules(data)):
        raise ValueError("new explanation rule identity must be new")
    if len({rule["rule_id"] for rule in rules}) != len(rules):
        raise ValueError("duplicate rule identity")
    return rules


def verify_sources(w, data):
    review = copy.deepcopy(data)
    review["claim_revisions"] += review["claims"]
    return DEEPEN.verify_sources(w, review)


def protected_hashes():
    # Freeze the existing paths only: other agents may append new development
    # artifacts, but must never rewrite historical evidence to improve scores.
    paths = set((ROOT / "artifacts/v14/knowledge").rglob("*"))
    paths.update((ROOT / "src/healthzip/knowledge/data").glob("*.json"))
    for directory in (ROOT / ".local").glob("v14-knowledge-*"):
        paths.update(directory.rglob("*"))
    paths = {p for p in paths if p.is_file() and "__pycache__" not in p.parts
             and p.suffix not in {".sqlite", ".db", ".pyc"}
             and not p.name.endswith(("-wal", "-shm"))
             and "1.4.12" not in p.name and "1_4_12" not in p.name
             and p.name != "publication_audit.json"
             and not p.name.startswith("current-chapter-coverage")}
    return {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted(paths)}


def candidate_records(release):
    rules = [r for r in release["rules"] if json.loads(r["payload_json"])["requested_capability"]
             in {"plan_candidate", "trial_candidate"}]
    refs = {(c["claim_id"], c["version"]) for r in rules for c in json.loads(r["payload_json"])["claim_refs"]}
    return {"rules": rules, "claims": [c for c in release["claims"] if (c["claim_id"], c["version"]) in refs]}


def review_record(w, table, field, identifier, version, rationale, *, application=False):
    review = TOPICS.review_record(w, table, field, identifier, version, rationale, application=application)
    # New identity truthfully identifies the same implementation author. Never
    # rewrite a persisted review on an idempotent activation.
    exists = w.lib.theories.execute(f"SELECT 1 FROM {table} WHERE {field}=? AND version=?", (identifier, version)).fetchone()
    if not exists:
        review["reviewer"] = "Codex AI-assisted implementation author; source explanation review"
    return review


def activate(w, data):
    row = w.lib.theories.execute("SELECT manifest_json,sha256 FROM core_release WHERE release_id=?",
                                 (data["previous_release_id"],)).fetchone()
    if not row or digest(row[0].encode()) != row[1] or row[1] != data["previous_release_sha256"]:
        raise ValueError("previous release missing, changed or corrupt")
    previous = {"release_id": data["previous_release_id"], **json.loads(row[0])}
    rules = validate_contracts(previous, data)
    records, rule_records = [], []
    for item in data["claims"] + data["claim_revisions"]:
        claim = item["claim"]
        review = review_record(w, "source_claim", "claim_id", claim["claim_id"], claim["version"], item["review_rationale"])
        w.review_claim(claim, review)
        records.append({"claim": claim, "content_review": review})
    for rule in rules:
        review = review_record(w, "application_rule", "rule_id", rule["rule_id"], rule["rule_version"],
                               "General source explanation only; retain frozen candidate dependencies and permissions.", application=True)
        w.review_rule(rule, review)
        rule_records.append({"rule": rule, "application_review": review})
    release = TOPICS.HHS.existing_or_create_release(w, data["release_id"])
    for key, added in (("claims", len(records)), ("rules", len(rules))):
        if len(release[key]) != len(previous[key]) + added or any(r not in release[key] for r in previous[key]):
            raise ValueError("previous release membership or review changed")
    if candidate_records(previous) != candidate_records(release):
        raise ValueError("candidate rule or dependency changed")
    new_ids = {r["rule_id"] for r in rules}
    for route in {route for r in rules for route in r["routes"]}:
        if any(p["rule_id"] in new_ids for p in w.reviewed_principles(route, {"requested_capability": "source_explanation"})["principles"]):
            raise ValueError("explanation acquired numerical candidate authority")
    return release, records, rule_records, previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-root", type=Path, default=ROOT / ".local/knowledge")
    parser.add_argument("--activate-explanations", action="store_true")
    args = parser.parse_args()
    data, out = definition(), ROOT / "artifacts/v14/knowledge"
    report_path = out / "completion-explanations-review-1.4.12.json"
    protected = json.loads(report_path.read_text())["protected_artifact_sha256"] if report_path.exists() else protected_hashes()
    TOPICS.verify_hashes(protected)
    w = KnowledgeWorkbench(args.knowledge_root)
    try:
        before, source_before = TOPICS.HHS.snapshot(w), TOPICS.source_snapshot(w)
        sources, spans = verify_sources(w, data)
        report = {"version": data["version"], "reviewer_kind": "ai_assisted",
                  "review_identity": data["review_identity"], "sources": sources,
                  "protected_artifact_sha256": protected, "source_library_mutations": 0,
                  "independent_ai_denominator": 0, "independent_human_or_expert_denominator": 0}
        outputs = {report_path: report}
        if args.activate_explanations:
            release, claims, rules, previous = activate(w, data)
            outputs[out / "release-1.4.12.json"] = release
            outputs[out / "completion-explanations-1.4.12.json"] = {
                "release_id": release["release_id"], "release_sha256": release["sha256"],
                "previous_release_sha256": data["previous_release_sha256"],
                "claims": claims, "rules": rules, "independent_ai_denominator": 0,
                "independent_human_or_expert_denominator": 0}
            outputs[out / "completion-explanations-release-verification-1.4.12.json"] = {
                **report, "release_id": release["release_id"], "release_sha256": release["sha256"],
                "previous_release_sha256": data["previous_release_sha256"],
                "claim_versions": len(release["claims"]), "rule_versions": len(release["rules"]),
                "distinct_claims": len({r["claim_id"] for r in release["claims"]}),
                "distinct_rules": len({r["rule_id"] for r in release["rules"]}),
                "old_members_and_reviews_unchanged": True, "candidate_rules_and_dependencies_unchanged": True,
                "candidate_rules": len(candidate_records(release)["rules"]),
                "candidate_records_sha256": digest(dumps(candidate_records(previous)).encode()),
                "source_library_sha256": source_before,
                "validation_identity": "implementation-author software and source verification; not independent evaluation"}
        after = TOPICS.HHS.snapshot(w)
        if any(r not in after[table] for table, rows in before.items() for r in rows):
            raise ValueError("existing knowledge data changed")
        if TOPICS.source_snapshot(w) != source_before:
            raise ValueError("source library changed")
        TOPICS.verify_hashes(protected)
        for path, value in outputs.items():
            TOPICS.HHS.write_public(path, value, spans)
        print(json.dumps({"sources_verified": True, "activated": args.activate_explanations,
                          "protected_files": len(protected), "release_id": data["release_id"],
                          "release_sha256": release["sha256"] if args.activate_explanations else None}))
    finally:
        w.close()


if __name__ == "__main__":
    main()
