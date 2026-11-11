"""Reproduce nine separately scoped explanations from existing lawful full text.

No source acquisition, evaluator replay or old release reconstruction occurs here.
Default execution verifies source bytes and writes metadata; activation is explicit.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
from pathlib import Path

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.acquisition import parse_jats
from healthzip.knowledge.store import digest, dumps, now

ROOT = Path(__file__).resolve().parents[1]


def _tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HHS = _tool("v14_review_hhs_scope")
METHOD = _tool("v14_import_equivalence_source")


def explanation_contracts():
    definition = json.loads((ROOT / "src/healthzip/knowledge/data/source_explanations_1_4_6.json").read_text())
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
                "implementation_validation_refs": ["tests/unit/test_source_explanation_topics.py",
                                                   "src/healthzip/knowledge/core.py::core_principles"]}
        contracts.append((topic, claim, rule))
    tasks = [tuple(c[1]["answer_task"][key] for key in ("subject", "outcome", "requested_relation")) for c in contracts]
    if len(set(tasks)) != len(contracts):
        raise ValueError("each newly reviewed topic needs its own task contract")
    return definition, contracts


def verify_sources(w, definition):
    """Read raw bytes, reparse exact spans, check rights and retain source roles."""
    import pdfplumber

    metadata, all_spans = [], []
    for source_id, expected in definition["sources"].items():
        version = w.lib.sources.execute("SELECT * FROM version WHERE version_id=?",
                                       (expected["source_version_id"],)).fetchone()
        if not version or version["source_id"] != source_id:
            raise ValueError("reviewed source version missing")
        raw = (w.root / version["storage_uri"]).read_bytes()
        if digest(raw) != expected["raw_sha256"] or version["sha256"] != expected["raw_sha256"]:
            raise ValueError("reviewed source bytes changed")
        roles = w.lib.source(source_id)["manifest"]["corpus_roles"]
        if roles != expected["corpus_roles"]:
            raise ValueError("source corpus role changed")
        rights = json.loads(version["rights_json"])
        reparsed = {}
        if source_id == "M2":
            reviewed_raw, _, reviewed_rights, spans = METHOD.review_m2()
            METHOD.verify_stored_source(w, expected["source_version_id"], reviewed_raw, reviewed_rights, spans)
            reparsed = dict(enumerate(spans))
        elif source_id == "CORE-US-HHS-PAG-2":
            policy = w.root / "core_acquisition/hhs_rights.raw"
            if (digest(policy.read_bytes()) != expected["rights_evidence_sha256"]
                    or rights.get("rights_evidence_sha256") != expected["rights_evidence_sha256"]):
                raise ValueError("reviewed HHS rights evidence changed")
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                if len(pdf.pages) != 118:
                    raise ValueError("unexpected HHS PDF page count")
                for fragment in expected["reviewed_spans"]:
                    index = fragment["span_index"]
                    page_index = 54 + index if index < 11 else 75 + index
                    reparsed[index] = {"text": pdf.pages[page_index].extract_text() or "",
                                       "file_page_index": page_index}
        elif source_id == "S1":
            _, spans, _ = parse_jats(raw)
            reparsed = dict(enumerate(spans))
        locators = []
        for fragment in expected["reviewed_spans"]:
            index = fragment["span_index"]
            span = w.lib.span(expected["source_version_id"] + f":s{index:05d}")
            check = reparsed[index]
            if (not span or span["text_hash"] != fragment["text_hash"]
                    or digest(check["text"].encode()) != fragment["text_hash"]
                    or span["text"] != check["text"] or not w.lib.eligible(span, "fulltext")[0]):
                raise ValueError("exact source span changed or is ineligible")
            locator = json.loads(span["locator_json"])
            if "locator" in check and locator != check["locator"]:
                raise ValueError("reviewed source locator changed")
            if source_id == "CORE-US-HHS-PAG-2" and (
                    locator.get("file_page_index") != check["file_page_index"]
                    or locator.get("printed_page_label") != str(check["file_page_index"] + 1)):
                raise ValueError("reviewed HHS page locator changed")
            if source_id == "S1":
                table = json.loads(span["structured_json"])
                if (span["kind"] != "table" or locator.get("native_id") != "T2"
                        or table.get("rows") != check["structured"]["rows"]
                        or table.get("footnotes") != check["structured"]["footnotes"]
                        or table.get("numeric_review_status") != "pending"):
                    raise ValueError("reviewed nonnumeric S1 definition table changed")
            all_spans.append(span)
            locators.append({"span_id": span["span_id"], "text_hash": span["text_hash"], "locator": locator,
                             "kind": span["kind"], "numeric_parameter_authority": False})
        metadata.append({"source_id": source_id, "source_version_id": version["version_id"],
                         "raw_sha256": version["sha256"], "corpus_roles": roles,
                         "rights": {key: rights.get(key) for key in
                                    ("license_id", "license_url", "index_allowed", "declared_use", "rights_scope")},
                         "reviewed_locators": locators, "review_scope": expected["review_scope"],
                         "prior_contracts": expected["prior_contracts"],
                         "prior_coverage_limit": expected["prior_coverage_limit"],
                         "new_topic_count": sum(c["source_id"] == source_id for c in definition["claims"])})
    return metadata, all_spans


def review_record(w, table, field, identifier, version, rationale, *, application=False):
    row = w.lib.theories.execute(f"SELECT review_json FROM {table} WHERE {field}=? AND version=?",
                                (identifier, version)).fetchone()
    if row:
        return json.loads(row[0])
    return {"reviewer": "Codex source topic and application review", "reviewer_kind": "ai_assisted",
            "reviewed_at": now(), "independent_expert_validation": False,
            "application_checked" if application else "content_checked": True,
            "rationale": rationale + " Only source explanation is authorized; no personal numerical model or candidate authority."}


def protected_hashes():
    hashes = HHS.frozen_hashes()
    for name in ("release-1.4.5.json", "HHS_goal_scope_review.json", "hhs_goal_scope-1.4.5.json",
                 "hhs-scope-release-verification.json", "hhs-scope-contract-verification.xml"):
        path = ROOT / "artifacts/v14/knowledge" / name
        hashes[str(path.relative_to(ROOT))] = digest(path.read_bytes())
    return hashes


def verify_hashes(expected):
    # Hash only the original path set, so other workers may add new development
    # artifacts. Evaluation bodies are never parsed or used to author answers.
    if any(digest((ROOT / name).read_bytes()) != sha for name, sha in expected.items()):
        raise ValueError("previous release or frozen evaluation artifact changed")


def source_snapshot(w):
    return digest(dumps({table: [dict(r) for r in w.lib.sources.execute(f"SELECT * FROM {table} ORDER BY 1")]
                         for table in ("source", "version", "span")}).encode())


def activate(w, definition, contracts):
    row = w.lib.theories.execute("SELECT manifest_json,sha256 FROM core_release WHERE release_id=?",
                                (definition["previous_release_id"],)).fetchone()
    if not row or digest(row["manifest_json"].encode()) != row["sha256"]:
        raise ValueError("immutable previous release missing or corrupt")
    base = json.loads(row["manifest_json"])
    reviewed = []
    for topic, claim, rule in contracts:
        content = review_record(w, "source_claim", "claim_id", claim["claim_id"], claim["version"], topic["review_rationale"])
        application = review_record(w, "application_rule", "rule_id", rule["rule_id"], rule["rule_version"], topic["review_rationale"], application=True)
        w.review_claim(claim, content)
        w.review_rule(rule, application)
        reviewed.append({"claim": claim, "content_review": content, "rule": rule, "application_review": application})
    release = HHS.existing_or_create_release(w, definition["release_id"])
    for key in ("claims", "rules"):
        if len(release[key]) != len(base[key]) + len(contracts) or any(item not in release[key] for item in base[key]):
            raise ValueError("new release must preserve the complete previous membership and add only reviewed topics")
    new_rules = {rule["rule_id"] for _, _, rule in contracts}
    for route in {route for topic, _, _ in contracts for route in topic["routes"]}:
        if any(p["rule_id"] in new_rules for p in w.reviewed_principles(route, {"requested_capability": "source_explanation"})["principles"]):
            raise ValueError("source explanation acquired candidate authority")
    return release, reviewed, row["sha256"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-root", type=Path, default=ROOT / ".local/knowledge")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/v14/knowledge")
    parser.add_argument("--activate-explanations", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    definition, contracts = explanation_contracts()
    frozen = protected_hashes()
    report_path = args.output_dir / "source_topic_review-1.4.6.json"
    if report_path.exists():
        frozen = json.loads(report_path.read_text())["frozen_artifact_sha256"]
    verify_hashes(frozen)
    w = KnowledgeWorkbench(args.knowledge_root)
    try:
        before, source_before = HHS.snapshot(w), source_snapshot(w)
        metadata, spans = verify_sources(w, definition)
        report = {"version": definition["version"], "reviewer_kind": "ai_assisted", "sources": metadata,
                  "new_separate_topic_count": len(contracts), "independent_human_or_expert_reviews": 0,
                  "personal_calibration_supplied": False, "source_library_mutations": 0,
                  "scope": "Only the explicitly listed source topics are reviewed; acquired full text is not counted as complete topic coverage.",
                  "frozen_artifact_sha256": frozen}
        outputs = {report_path: report}
        if args.activate_explanations:
            release, reviewed, previous_sha = activate(w, definition, contracts)
            outputs[args.output_dir / "release-1.4.6.json"] = release
            outputs[args.output_dir / "source_explanations-1.4.6.json"] = {
                "release_id": release["release_id"], "release_sha256": release["sha256"],
                "previous_release_id": definition["previous_release_id"], "previous_release_sha256": previous_sha,
                "new_contracts": reviewed, "claims_in_release": len(release["claims"]),
                "rules_in_release": len(release["rules"]),
                "candidate_rule_count": len({r["rule_id"] for r in release["rules"]
                                             if json.loads(r["payload_json"])["requested_capability"] in {"plan_candidate", "trial_candidate"}}),
                "independent_human_or_expert_reviews": 0, "personal_calibration_supplied": False,
                "source_library_mutations": 0, "previous_members_unchanged": True}
        after = HHS.snapshot(w)
        if any(item not in after[table] for table, rows in before.items() for item in rows):
            raise ValueError("pre-existing immutable knowledge record changed")
        if source_snapshot(w) != source_before:
            raise ValueError("source library changed during explanation review")
        verify_hashes(frozen)
        for path, value in outputs.items():
            HHS.write_public(path, value, spans)
        print(json.dumps({"source_verified": True, "new_separate_topic_count": len(contracts),
                          "explanations_activated": args.activate_explanations,
                          "release_id": definition["release_id"] if args.activate_explanations else None,
                          "previous_release_and_evaluations_unchanged": True}))
    finally:
        w.close()


if __name__ == "__main__":
    main()
