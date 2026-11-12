"""Append source explanation revisions; preserve every prior review and candidate.

Requires the already held licensed sources. No download, source mutation, model
parameter activation or independent-evaluation rerun occurs here.
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
from healthzip.knowledge.documents import parse_pdf
from healthzip.knowledge.store import digest

ROOT = Path(__file__).resolve().parents[1]


def tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOPICS = tool("v14_expand_source_explanations")


def definition(path=None):
    return json.loads((path or ROOT / "src/healthzip/knowledge/data/detailed_explanations_1_4_10.json").read_text())


def revised_rules(previous, data):
    if "rule_revisions" in data:
        replacements = {(item["replaces"]["claim_id"], item["replaces"]["version"]): item["claim"]["version"]
                        for item in data["claim_revisions"]}
        rules = []
        for item in data["rule_revisions"]:
            ref = item["replaces"]
            old = next((json.loads(row["payload_json"]) for row in previous["rules"]
                        if row["rule_id"] == ref["rule_id"] and row["version"] == ref["version"]), None)
            if not old or old["requested_capability"] != "source_explanation" or old["permitted_actions"]:
                raise ValueError("exact previous explanation rule required")
            expected = copy.deepcopy(old)
            expected.pop("supersedes", None)
            expected.setdefault("numeric_provenance", [])
            expected["rule_version"] = data["version"]
            expected["claim_refs"] = [{**c, "version": replacements.get((c["claim_id"], c["version"]), c["version"])}
                                      for c in expected["claim_refs"]]
            if expected != item["rule"] or expected["numeric_provenance"]:
                raise ValueError("explicit rule revision changed more than frozen dependencies")
            rules.append(expected)
        if len({r["rule_id"] for r in rules}) != len(rules):
            raise ValueError("duplicate rule revision")
        return rules
    rules = []
    for item in data["claim_revisions"]:
        claim = item["claim"]
        found = [json.loads(row["payload_json"]) for row in previous["rules"]
                 if json.loads(row["payload_json"]).get("requested_capability") == "source_explanation"
                 and item["replaces"] in json.loads(row["payload_json"]).get("claim_refs", [])]
        if len(found) != 1:
            raise ValueError("exact previous explanation rule required")
        rule = copy.deepcopy(found[0])
        # The predecessor may carry a historical supersession command. The new
        # version must not replay that command or change any existing status.
        rule.pop("supersedes", None)
        rule.setdefault("numeric_provenance", [])
        references = [{"claim_id": claim["claim_id"], "version": claim["version"]} if ref == item["replaces"] else ref
                      for ref in rule["claim_refs"]]
        rule.update(rule_version=data["version"], claim_refs=references,
                    limits=list(dict.fromkeys([*rule["limits"], *claim["limitations"]])), implementation_validation_refs=[
                        "tests/unit/test_detailed_explanation_revisions.py", "src/healthzip/knowledge/core.py::core_principles"])
        if rule.get("supersedes") or rule["permitted_actions"] or rule.get("numeric_provenance"):
            raise ValueError("explanation revision must not activate numerical authority")
        rules.append(rule)
    return rules


def verify_sources(w, data):
    import pdfplumber

    metadata, spans = [], []
    for source_id, expected in data["sources"].items():
        row = w.lib.sources.execute("SELECT * FROM version WHERE version_id=?", (expected["source_version_id"],)).fetchone()
        if not row or row["source_id"] != source_id:
            raise ValueError("source identity missing")
        raw = (w.root / row["storage_uri"]).read_bytes()
        if digest(raw) != expected["raw_sha256"] or row["sha256"] != expected["raw_sha256"]:
            raise ValueError("source bytes changed")
        if w.lib.source(source_id)["manifest"]["corpus_roles"] != expected["corpus_roles"]:
            raise ValueError("source role changed")
        rights = json.loads(row["rights_json"])
        if source_id == "N1":
            reviewer = tool("v14_review_regression_covariance")
            original, _, _ = reviewer.explanation_contract()
            reviewer.verify_source(w, original)
            _, parsed = parse_pdf(raw)
        elif source_id == "M2":
            raw_checked, _, rights_checked, parsed = TOPICS.METHOD.review_m2()
            TOPICS.METHOD.verify_stored_source(w, expected["source_version_id"], raw_checked, rights_checked, parsed)
        elif source_id == "S1":
            _, parsed, _ = parse_jats(raw)
        elif source_id == "CORE-US-HHS-PAG-2":
            evidence = w.root / "core_acquisition/hhs_rights.raw"
            if (digest(evidence.read_bytes()) != rights.get("rights_evidence_sha256")
                    or rights.get("license_id") != "US-HHS-public-domain-text"):
                raise ValueError("HHS rights evidence changed")
            parsed = {}
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                for item in expected["reviewed_spans"]:
                    parsed[int(item["span_id"].rsplit(":s", 1)[1])] = {
                        "text": pdf.pages[item["locator"]["file_page_index"]].extract_text() or ""}
        else:
            raise ValueError("unsupported source review")
        for item in expected["reviewed_spans"]:
            span = w.lib.span(item["span_id"])
            index = int(item["span_id"].rsplit(":s", 1)[1])
            if (not span or span["version_id"] != expected["source_version_id"]
                    or span["text_hash"] != item["text_hash"] or json.loads(span["locator_json"]) != item["locator"]
                    or digest(parsed[index]["text"].encode()) != item["text_hash"]
                    or span["text"] != parsed[index]["text"] or not w.lib.eligible(span, "fulltext")[0]):
                raise ValueError("reviewed span/locator/eligibility changed")
            if "locator" in parsed[index] and parsed[index]["locator"] != item["locator"]:
                raise ValueError("reparsed locator changed")
            spans.append(span)
        metadata.append({**expected, "source_id": source_id, "rights": {key: rights.get(key) for key in
                         ("license_id", "license_url", "index_allowed", "rights_scope")}})
    known = {span["span_id"] for span in spans}
    for item in data["claim_revisions"]:
        for part in item["claim"]["answer_task"]["answer_parts"]:
            if not part["span_ids"] or not set(part["span_ids"]) <= known:
                raise ValueError("answer part outside reviewed source span set")
    return metadata, spans


def protected_hashes(data):
    public = ROOT / "artifacts/v14/knowledge"
    old = json.loads((public / data.get("previous_verification_artifact", "refined-explanations-release-verification-1.4.9.json")).read_text())
    hashes = dict(old["protected_artifact_sha256"])
    paths = [*public.glob("independent*"), *public.glob("*1.4.9*"),
             ROOT / "src/healthzip/knowledge/data/refined_explanations_1_4_9.json"]
    if data["version"] != "1.4.10":
        paths += [*public.glob("*1.4.10*"), ROOT / "src/healthzip/knowledge/data/detailed_explanations_1_4_10.json"]
        paths += [ROOT / ".local/v14-knowledge-round5-development" / name for name in
                  ("language-1.4.10-outputs.raw.json", "development-judgments.json")]
    paths += [ROOT / ".local/v14-knowledge-independent-round5" / name for name in (
        "cases.json", "freeze_receipt.json", "outputs.raw.json", "judgments.json", "judgments_receipt.json",
        "source_packet.json", "code_identity.json")]
    for path in paths:
        if path.is_file():
            hashes.setdefault(str(path.relative_to(ROOT)), digest(path.read_bytes()))
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-root", type=Path, default=ROOT / ".local/knowledge")
    parser.add_argument("--activate-revisions", action="store_true")
    parser.add_argument("--definition", type=Path)
    args = parser.parse_args()
    data = definition(args.definition)
    out = ROOT / "artifacts/v14/knowledge"
    report_path = out / f"detailed-explanations-review-{data['version']}.json"
    protected = json.loads(report_path.read_text())["protected_artifact_sha256"] if report_path.exists() else protected_hashes(data)
    TOPICS.verify_hashes(protected)
    w = KnowledgeWorkbench(args.knowledge_root)
    try:
        before, source_before = TOPICS.HHS.snapshot(w), TOPICS.source_snapshot(w)
        sources, spans = verify_sources(w, data)
        outputs = {report_path: {"version": data["version"], "reviewer_kind": "ai_assisted", "sources": sources,
            "source_library_mutations": 0, "protected_artifact_sha256": protected,
            "independent_ai_denominator": 0, "independent_human_or_expert_denominator": 0}}
        if args.activate_revisions:
            row = w.lib.theories.execute("SELECT manifest_json,sha256 FROM core_release WHERE release_id=?",
                                         (data["previous_release_id"],)).fetchone()
            if not row or digest(row[0].encode()) != row[1]:
                raise ValueError("previous release missing or corrupt")
            previous = json.loads(row[0])
            records, rule_records = [], []
            rules = revised_rules(previous, data)
            for item in data["claim_revisions"]:
                claim, old = item["claim"], item["replaces"]
                if (claim.get("answer_revision_of") != old or claim["claim_id"] != old["claim_id"]
                        or not any(c["claim_id"] == old["claim_id"] and c["version"] == old["version"] for c in previous["claims"])):
                    raise ValueError("exact previous same-claim dependency required")
                review = TOPICS.review_record(w, "source_claim", "claim_id", claim["claim_id"], claim["version"], item["review_rationale"])
                w.review_claim(claim, review)
                records.append({"claim": claim, "content_review": review})
            for index, rule in enumerate(rules):
                rationale = ("Only replace explicitly reviewed claim versions; retain all other rule fields and permissions."
                             if "rule_revisions" in data else data["claim_revisions"][index]["review_rationale"])
                application = TOPICS.review_record(w, "application_rule", "rule_id", rule["rule_id"], rule["rule_version"],
                                                   rationale, application=True)
                w.review_rule(rule, application)
                rule_records.append({"rule": rule, "application_review": application})
                if "rule_revisions" not in data:
                    records[index].update(rule=rule, application_review=application)
            release = TOPICS.HHS.existing_or_create_release(w, data["release_id"])
            for kind in ("claims", "rules"):
                added = len(records) if kind == "claims" else len(rules)
                if len(release[kind]) != len(previous[kind]) + added or any(item not in release[kind] for item in previous[kind]):
                    raise ValueError("old release members changed")
            def candidates(value):
                return [x for x in value["rules"] if json.loads(x["payload_json"])["requested_capability"] in {"plan_candidate", "trial_candidate"}]
            if candidates(previous) != candidates(release):
                raise ValueError("candidate authority changed")
            outputs[out / f"release-{data['version']}.json"] = release
            detail = {"release_id": release["release_id"],
                "release_sha256": release["sha256"], "previous_release_sha256": row[1], "revisions": records,
                "old_members_and_reviews_unchanged": True, "candidate_rules_unchanged": True,
                "independent_ai_denominator": 0, "independent_human_or_expert_denominator": 0}
            if "rule_revisions" in data:
                detail["rule_revisions"] = rule_records
            outputs[out / f"detailed-explanations-{data['version']}.json"] = detail
        after = TOPICS.HHS.snapshot(w)
        if any(item not in after[table] for table, rows in before.items() for item in rows) or TOPICS.source_snapshot(w) != source_before:
            raise ValueError("existing knowledge/source data changed")
        TOPICS.verify_hashes(protected)
        for path, value in outputs.items():
            TOPICS.HHS.write_public(path, value, spans)
        print(json.dumps({"sources_verified": True, "activated": args.activate_revisions,
                          "new_claim_versions": len(data["claim_revisions"]), "protected_files": len(protected)}))
    finally:
        w.close()


if __name__ == "__main__":
    main()
