"""Verify held N1 prose and add one bounded regression-covariance explanation.

The source library, previous releases and frozen evaluation artifacts are immutable.
No formula, parameter, personal calibration or model-inference authority is added.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from lxml import html

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.documents import parse_pdf
from healthzip.knowledge.store import digest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("source_topics", ROOT / "tools/v14_expand_source_explanations.py")
TOPICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOPICS)


def explanation_contract():
    definition = json.loads((ROOT / "src/healthzip/knowledge/data/regression_covariance_1_4_7.json").read_text())
    version = definition["source_version_id"]
    reviewed = {row["span_index"] for row in definition["reviewed_spans"]}
    groups = {row["group_id"]: row["span_indices"] for row in definition["reviewed_evidence_groups"]}
    parts = []
    for part in definition["answer_parts"]:
        grouped = {i for group in part["evidence_groups"] for i in groups[group]}
        if set(part["span_indices"]) != grouped or not grouped <= reviewed:
            raise ValueError("answer part must retain complete reviewed paragraph groups")
        parts.append({"part_id": part["part_id"], "text": part["text"],
                      "span_ids": [version + f":s{i:05d}" for i in part["span_indices"]],
                      "evidence_relation": part["evidence_relation"]})
    claim = {"claim_id": definition["claim_id"], "version": definition["version"],
             "statement": "\n".join(part["text"] for part in parts), "scope": definition["scope"],
             "limitations": definition["limitations"], "numeric": False,
             "evidence_links": [{"source_id": definition["source_id"], "source_version_id": version,
                                 "span_ids": sorted({sid for part in parts for sid in part["span_ids"]})}],
             "answer_task": {**{key: definition[key] for key in ("subject", "outcome", "requested_relation")},
                             "evidence_relation": "supports", "answer_complete": True,
                             "required_answer_parts": [part["part_id"] for part in parts],
                             "routes": definition["routes"], "answer_parts": parts}}
    rule = {"rule_id": "RULE-N1-REGRESSION-COVARIANCE-EXPLANATION", "rule_version": definition["version"],
            "requested_capability": "source_explanation", "capability_policy_version": "personal-trial-policy-1.4.0",
            "claim_refs": [{"claim_id": claim["claim_id"], "version": claim["version"]}],
            "routes": definition["routes"], "permitted_actions": [], "numeric_provenance": [],
            "conditions": [{"field": "requested_capability", "op": "eq", "value": "source_explanation",
                            "origin": "product_scope"}],
            "coverage_scope": definition["outcome"],
            "application_logic": "仅解释N1中HC/HAC的处理对象、模型与依赖条件及配置范围；不执行回归、不选择个人参数、不提供重测误差或平台期结论。",
            "limits": definition["limitations"],
            "forbidden": ["numeric_training_candidate", "personal_parameter_selection", "individual_equivalence_inference",
                          "individual_plateau_inference", "individual_prediction", "causal_effect"],
            "implementation_validation_refs": ["tests/unit/test_regression_covariance_contract.py",
                                               "src/healthzip/knowledge/core.py::core_principles"]}
    return definition, claim, rule


def verify_source(w, definition):
    version = w.lib.sources.execute("SELECT * FROM version WHERE version_id=?",
                                   (definition["source_version_id"],)).fetchone()
    if not version or version["source_id"] != "N1" or version["identity_status"] != "matched":
        raise ValueError("reviewed N1 identity/version missing")
    raw = (w.root / version["storage_uri"]).read_bytes()
    if digest(raw) != definition["raw_sha256"] or version["sha256"] != definition["raw_sha256"]:
        raise ValueError("reviewed N1 PDF bytes changed")
    rights = json.loads(version["rights_json"])
    license_page = (w.root / "method_discovery_round2/N1.raw").read_bytes()
    if (digest(license_page) != definition["rights_evidence_sha256"]
            or rights.get("rights_evidence_sha256") != definition["rights_evidence_sha256"]
            or rights.get("license_id") != "CC-BY-3.0" or not rights.get("index_allowed")):
        raise ValueError("reviewed N1 license evidence changed")
    page = html.fromstring(license_page)
    if len(page.xpath('//*[@id="jss-copyright"]//a[@href="http://creativecommons.org/licenses/by/3.0/"]')) != 1:
        raise ValueError("N1 article license declaration missing")
    if w.lib.source("N1")["manifest"]["corpus_roles"] != ["research"]:
        raise ValueError("N1 must retain research role")
    metadata, reparsed = parse_pdf(raw)
    if metadata["page_count"] != 17 or len(reparsed) != 745:
        raise ValueError("N1 exact stored parse changed")
    spans, locations = [], []
    for expected in definition["reviewed_spans"]:
        index = expected["span_index"]
        span = w.lib.span(definition["source_version_id"] + f":s{index:05d}")
        parsed = reparsed[index]
        if (not span or span["text_hash"] != expected["text_hash"]
                or digest(parsed["text"].encode()) != expected["text_hash"]
                or span["text"] != parsed["text"]
                or json.loads(span["locator_json"]) != parsed["locator"]
                or not w.lib.eligible(span, "fulltext")[0]):
            raise ValueError("reviewed N1 paragraph span/locator changed or is ineligible")
        spans.append(span)
        locations.append({"span_id": span["span_id"], "text_hash": span["text_hash"],
                          "locator": parsed["locator"], "numeric_parameter_authority": False})
    return spans, {"source_id": "N1", "source_version_id": version["version_id"],
                   "raw_sha256": version["sha256"], "corpus_roles": ["research"],
                   "rights": {key: rights.get(key) for key in
                              ("license_id", "license_url", "index_allowed", "rights_scope", "attribution")},
                   "rights_evidence_sha256": definition["rights_evidence_sha256"],
                   "reviewed_locators": locations, "reviewed_evidence_groups": definition["reviewed_evidence_groups"],
                   "read_file_page_indices": definition["read_file_page_indices"],
                   "review_rationale": definition["review_rationale"],
                   "formula_transcription_verified": False, "numeric_table_parameters_activated": False}


def protected_hashes():
    public = ROOT / "artifacts/v14/knowledge"
    # Use the already frozen path set. Do not inspect new independent packets
    # being authored concurrently, and do not consume their questions or answers.
    baseline = json.loads((public / "source-topics-release-verification-1.4.6.json").read_text())
    hashes = dict(baseline["protected_artifact_sha256"])
    for name in ("release-1.4.6.json", "source_topic_review-1.4.6.json", "source_explanations-1.4.6.json",
                 "source-topics-verification-1.4.6.xml", "source-topics-release-verification-1.4.6.json",
                 "source-topic-contract-audit-1.4.6.json", "source-topics-development-cases-1.4.6.json",
                 "source-topics-development-outputs-1.4.6.json", "source-topics-development-results-1.4.6.json",
                 "source-topics-development-replay-1.4.6.json", "N1_method_review.json", "method_source_round2.json"):
        path = public / name
        hashes[str(path.relative_to(ROOT))] = digest(path.read_bytes())
    path = ROOT / "src/healthzip/knowledge/data/source_explanations_1_4_6.json"
    hashes[str(path.relative_to(ROOT))] = digest(path.read_bytes())
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-root", type=Path, default=ROOT / ".local/knowledge")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/v14/knowledge")
    parser.add_argument("--activate-explanation", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    definition, claim, rule = explanation_contract()
    report_path = args.output_dir / "regression-covariance-review-1.4.7.json"
    frozen = (json.loads(report_path.read_text())["protected_artifact_sha256"]
              if report_path.exists() else protected_hashes())
    TOPICS.verify_hashes(frozen)
    w = KnowledgeWorkbench(args.knowledge_root)
    try:
        source_before, before = TOPICS.source_snapshot(w), TOPICS.HHS.snapshot(w)
        spans, source = verify_source(w, definition)
        report = {"version": definition["version"], "reviewer_kind": "ai_assisted", "source": source,
                  "functional_gap": definition["functional_gap"], "new_topic_count": 1,
                  "independent_ai_denominator": 0, "independent_human_or_expert_denominator": 0,
                  "personal_calibration_supplied": False, "source_library_mutations": 0,
                  "protected_artifact_sha256": frozen}
        outputs = {report_path: report}
        if args.activate_explanation:
            release, reviewed, previous_sha = TOPICS.activate(w, definition, [(definition, claim, rule)])
            outputs[args.output_dir / "release-1.4.7.json"] = release
            outputs[args.output_dir / "regression-covariance-explanation-1.4.7.json"] = {
                "release_id": release["release_id"], "release_sha256": release["sha256"],
                "previous_release_id": definition["previous_release_id"], "previous_release_sha256": previous_sha,
                "new_contracts": reviewed, "claims_in_release": len(release["claims"]),
                "rules_in_release": len(release["rules"]), "previous_members_unchanged": True,
                "independent_ai_denominator": 0, "independent_human_or_expert_denominator": 0,
                "personal_calibration_supplied": False, "source_library_mutations": 0}
        after = TOPICS.HHS.snapshot(w)
        if any(item not in after[table] for table, rows in before.items() for item in rows):
            raise ValueError("pre-existing immutable knowledge record changed")
        if TOPICS.source_snapshot(w) != source_before:
            raise ValueError("source library changed during N1 explanation review")
        TOPICS.verify_hashes(frozen)
        # N1 was parsed into short PDF lines. Check joined paragraph prose too.
        by_index = {int(span["span_id"].rsplit(":s", 1)[1]): span for span in spans}
        guards = spans + [{"text": " ".join(by_index[i]["text"] for i in group["span_indices"])}
                          for group in definition["reviewed_evidence_groups"]]
        for path, value in outputs.items():
            TOPICS.HHS.write_public(path, value, guards)
        print(json.dumps({"source_verified": True, "explanation_activated": args.activate_explanation,
                          "release_id": definition["release_id"] if args.activate_explanation else None,
                          "protected_file_count": len(frozen), "protected_files_unchanged": True,
                          "source_library_unchanged": True}))
    finally:
        w.close()


if __name__ == "__main__":
    main()
