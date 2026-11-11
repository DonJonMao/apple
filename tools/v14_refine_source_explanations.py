"""Publish two immutable answer revisions while preserving candidate dependencies.

Old claim/rule rows, reviews and releases remain unchanged. The new complete
snapshot includes old dependencies and explicit answer_revision_of links.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import io
import json
from pathlib import Path

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.acquisition import parse_jats
from healthzip.knowledge.store import digest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("source_topics", ROOT / "tools/v14_expand_source_explanations.py")
TOPICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOPICS)
SAFETY_RULE = "RULE-HHS-ACTIVITY-SAFETY-SCOPE-EXPLANATION"


def definition():
    return json.loads((ROOT / "src/healthzip/knowledge/data/refined_explanations_1_4_9.json").read_text())


def revised_rule(previous, claim):
    row = next(row for row in previous["rules"] if row["rule_id"] == SAFETY_RULE and row["version"] == "1.4.8")
    rule = copy.deepcopy(json.loads(row["payload_json"]))
    rule.update(rule_version="1.4.9", claim_refs=[{"claim_id": claim["claim_id"], "version": claim["version"]}],
                limits=claim["limitations"],
                application_logic="仅解释HHS第7章多数安全建议的跨年龄范围及特定人群限定；第4章成人范围由独立合同回答。不产生个人参数、候选或临床权限。",
                implementation_validation_refs=["tests/unit/test_refined_explanation_contracts.py",
                                                "src/healthzip/knowledge/core.py::core_principles"])
    if rule.get("supersedes") or rule["permitted_actions"] or rule["requested_capability"] != "source_explanation":
        raise ValueError("answer revision must not mutate old rule state or candidate authority")
    return rule


def verify_sources(w, data):
    import pdfplumber

    report, all_spans = [], []
    for source_id, expected in data["sources"].items():
        row = w.lib.sources.execute("SELECT * FROM version WHERE version_id=?",
                                   (expected["source_version_id"],)).fetchone()
        if not row or row["source_id"] != source_id:
            raise ValueError("reviewed source identity/version missing")
        raw = (w.root / row["storage_uri"]).read_bytes()
        if digest(raw) != expected["raw_sha256"] or row["sha256"] != expected["raw_sha256"]:
            raise ValueError("reviewed source bytes changed")
        if w.lib.source(source_id)["manifest"]["corpus_roles"] != ["core"]:
            raise ValueError("reviewed core role changed")
        rights = json.loads(row["rights_json"])
        reparsed = {}
        if source_id == "CORE-US-HHS-PAG-2":
            evidence = w.root / "core_acquisition/hhs_rights.raw"
            if (digest(evidence.read_bytes()) != expected["rights_evidence_sha256"]
                    or rights.get("rights_evidence_sha256") != expected["rights_evidence_sha256"]
                    or rights.get("license_id") != "US-HHS-public-domain-text"):
                raise ValueError("reviewed HHS rights evidence changed")
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                if len(pdf.pages) != 118:
                    raise ValueError("unexpected HHS PDF page count")
                reparsed[12] = {"text": pdf.pages[87].extract_text(), "file_page_index": 87}
        elif source_id == "S1":
            _, spans, _ = parse_jats(raw)
            reparsed = dict(enumerate(spans))
        locations = []
        for fragment in expected["reviewed_spans"]:
            span = w.lib.span(fragment["span_id"])
            index = int(fragment["span_id"].rsplit(":s", 1)[1])
            check = reparsed[index]
            if (not span or span["version_id"] != expected["source_version_id"]
                    or span["text_hash"] != fragment["text_hash"]
                    or digest(check["text"].encode()) != fragment["text_hash"]
                    or span["text"] != check["text"] or not w.lib.eligible(span, "fulltext")[0]):
                raise ValueError("reviewed source span changed or is ineligible")
            locator = json.loads(span["locator_json"])
            if source_id == "S1" and (locator != check["locator"] or span["kind"] != "paragraph"):
                raise ValueError("reviewed S1 paragraph locator changed")
            if source_id == "CORE-US-HHS-PAG-2" and (
                    locator.get("chapter_id") != "7" or locator.get("file_page_index") != 87
                    or locator.get("printed_page_label") != "88"):
                raise ValueError("reviewed HHS Chapter 7 locator changed")
            effective_rights = json.loads(span["rights_json"])
            locations.append({"span_id": span["span_id"], "text_hash": span["text_hash"], "locator": locator,
                              "rights": {key: effective_rights.get(key) for key in
                                         ("license_id", "license_url", "index_allowed", "rights_scope", "declared_use")}})
            all_spans.append(span)
        report.append({"source_id": source_id, "source_version_id": row["version_id"],
                       "raw_sha256": row["sha256"], "corpus_roles": ["core"], "reviewed_locators": locations,
                       "identity_basis": "Exact-version matched status or identity_matched review, checked by Libraries.eligible."})
    return report, all_spans


def activate(w, data):
    row = w.lib.theories.execute("SELECT manifest_json,sha256 FROM core_release WHERE release_id=?",
                                (data["previous_release_id"],)).fetchone()
    if not row or digest(row["manifest_json"].encode()) != row["sha256"]:
        raise ValueError("immutable previous release missing or corrupt")
    previous = json.loads(row["manifest_json"])
    records = []
    for item in data["claim_revisions"]:
        claim = item["claim"]
        old_ref = claim["answer_revision_of"]
        if old_ref != item["replaces"] or old_ref["claim_id"] != claim["claim_id"]:
            raise ValueError("answer revision requires the exact previous same-claim reference")
        if not any(c["claim_id"] == old_ref["claim_id"] and c["version"] == old_ref["version"]
                   for c in previous["claims"]):
            raise ValueError("answer revision predecessor is outside the previous release")
        review = TOPICS.review_record(w, "source_claim", "claim_id", claim["claim_id"], claim["version"],
                                      item["review_rationale"])
        w.review_claim(claim, review)
        records.append({"claim": claim, "content_review": review})
    safety = next(item["claim"] for item in data["claim_revisions"] if item["claim"]["answer_task"]["outcome"] == "activity_safety_scope")
    rule = revised_rule(previous, safety)
    application = TOPICS.review_record(w, "application_rule", "rule_id", rule["rule_id"], rule["rule_version"],
                                      "Chapter 7 explanation only; immutable old rule and candidate dependencies remain unchanged.",
                                      application=True)
    w.review_rule(rule, application)
    release = TOPICS.HHS.existing_or_create_release(w, data["release_id"])
    for kind, increase in (("claims", 2), ("rules", 1)):
        if len(release[kind]) != len(previous[kind]) + increase or any(item not in release[kind] for item in previous[kind]):
            raise ValueError("revision release must retain every previous member verbatim")
    old_candidates = [row for row in previous["rules"] if json.loads(row["payload_json"])["requested_capability"] in {"plan_candidate", "trial_candidate"}]
    current_candidates = [row for row in release["rules"] if json.loads(row["payload_json"])["requested_capability"] in {"plan_candidate", "trial_candidate"}]
    if current_candidates != old_candidates:
        raise ValueError("candidate rules or their frozen dependencies changed")
    return release, {"claim_revisions": records, "rule_revision": {"rule": rule, "application_review": application}}, row["sha256"]


def protected_hashes():
    public = ROOT / "artifacts/v14/knowledge"
    old = json.loads((public / "activity-safety-scope-release-verification-1.4.8.json").read_text())
    hashes = dict(old["protected_artifact_sha256"])
    for name in ("release-1.4.8.json", "activity-safety-scope-review-1.4.8.json", "activity-safety-scope-explanation-1.4.8.json",
                 "activity-safety-scope-verification-1.4.8.xml", "activity-safety-scope-release-verification-1.4.8.json"):
        path = public / name
        hashes[str(path.relative_to(ROOT))] = digest(path.read_bytes())
    path = ROOT / "src/healthzip/knowledge/data/activity_safety_scope_1_4_8.json"
    hashes[str(path.relative_to(ROOT))] = digest(path.read_bytes())
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-root", type=Path, default=ROOT / ".local/knowledge")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/v14/knowledge")
    parser.add_argument("--activate-revisions", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    data = definition()
    review_path = args.output_dir / "refined-explanations-review-1.4.9.json"
    frozen = (json.loads(review_path.read_text())["protected_artifact_sha256"]
              if review_path.exists() else protected_hashes())
    TOPICS.verify_hashes(frozen)
    w = KnowledgeWorkbench(args.knowledge_root)
    try:
        source_before, before = TOPICS.source_snapshot(w), TOPICS.HHS.snapshot(w)
        sources, spans = verify_sources(w, data)
        outputs = {review_path: {"version": data["version"], "sources": sources,
                   "reviewer_kind": "ai_assisted", "new_claim_versions": 2, "new_rule_versions": 1,
                   "source_library_mutations": 0, "independent_ai_denominator": 0,
                   "independent_human_or_expert_denominator": 0, "protected_artifact_sha256": frozen}}
        if args.activate_revisions:
            release, records, previous_sha = activate(w, data)
            outputs[args.output_dir / "release-1.4.9.json"] = release
            outputs[args.output_dir / "refined-explanations-1.4.9.json"] = {
                "release_id": release["release_id"], "release_sha256": release["sha256"],
                "previous_release_id": data["previous_release_id"], "previous_release_sha256": previous_sha,
                **records, "old_members_and_reviews_unchanged": True, "candidate_rules_unchanged": True,
                "claims_version_count": len(release["claims"]), "rules_version_count": len(release["rules"]),
                "distinct_claim_count": len({row["claim_id"] for row in release["claims"]}),
                "distinct_rule_count": len({row["rule_id"] for row in release["rules"]}),
                "independent_ai_denominator": 0, "independent_human_or_expert_denominator": 0,
                "personal_calibration_supplied": False}
        after = TOPICS.HHS.snapshot(w)
        if any(item not in after[table] for table, rows in before.items() for item in rows):
            raise ValueError("old immutable knowledge row or status changed")
        if TOPICS.source_snapshot(w) != source_before:
            raise ValueError("source library changed")
        TOPICS.verify_hashes(frozen)
        for path, value in outputs.items():
            TOPICS.HHS.write_public(path, value, spans)
        print(json.dumps({"source_verified": True, "revisions_activated": args.activate_revisions,
                          "release_id": data["release_id"] if args.activate_revisions else None,
                          "protected_file_count": len(frozen), "source_library_unchanged": True}))
    finally:
        w.close()


if __name__ == "__main__":
    main()
