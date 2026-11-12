"""Append bounded practical explanations without changing prior releases or candidates.

Default verification opens both knowledge databases read-only. Activation is an
explicit separate option. Published material contains locators, hashes and original
summaries, never held source prose or independent-validation claims.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.store import Libraries, digest, dumps

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("completion", ROOT / "tools/v14_complete_source_explanations.py")
COMPLETION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPLETION)
DEEPEN, TOPICS = COMPLETION.DEEPEN, COMPLETION.TOPICS
TEST = "tests/unit/test_practical_explanation_contracts.py"


def definition():
    return json.loads((ROOT / "src/healthzip/knowledge/data/practical_source_explanations_1_4_14.json").read_text())


def new_rules(data):
    rules = COMPLETION.new_rules(data)
    for rule in rules:
        rule["implementation_validation_refs"] = [TEST, "src/healthzip/knowledge/core.py::core_principles"]
    return rules


def validate_contracts(previous, data):
    if previous["release_id"] != data["previous_release_id"]:
        raise ValueError("exact previous release required")
    old_claims = {(r["claim_id"], r["version"]): json.loads(r["payload_json"]) for r in previous["claims"]}
    old_targets = {tuple(claim.get("answer_task", {}).get(k) for k in
                         ("subject", "outcome", "requested_relation")) for claim in old_claims.values()}
    tasks = []
    for item in data["claims"] + data["claim_revisions"]:
        claim, review = item["claim"], item.get("numeric_explanation_review", {})
        task = claim["answer_task"]
        if claim["version"] != data["version"] or claim.get("supersedes"):
            raise ValueError("only append-only explanations allowed")
        # This release explicitly reviews prose quantities, including S1's
        # general group comparisons. It grants no numerical action permission.
        sources = {link["source_id"] for link in claim["evidence_links"]}
        if (claim.get("numeric") is not True or len(sources) != 1
                or sources - {"S1", "CORE-US-HHS-PAG-2"}
                or review.get("source_id") not in sources
                or review.get("kind") != "reported_general_source_quantity"
                or review.get("personal_parameter_authorized") is not False
                or review.get("candidate_action_authorized") is not False
                or claim["scope"].get("individual_inference") != "not_authorized"):
            raise ValueError("reviewed general numerical explanation scope required")
        if "S1" in sources and (claim["scope"].get("population") != "healthy_adults"
                                or claim["scope"].get("aggregation") != "group_evidence"):
            raise ValueError("S1 quantities require healthy-adult group-evidence scope")
        if "CORE-US-HHS-PAG-2" in sources:
            scope = claim["scope"]
            if not ((scope.get("population") == "adults" and scope.get("age_range") == [18, 64]
                     and scope.get("goal") == "public_health")
                    or (scope.get("population") == "adults_18_through_64"
                        and scope.get("age_range", [18, 64]) == [18, 64]
                        and scope.get("goal") == "general_health")):
                raise ValueError("HHS Chapter 4 quantities require the reviewed adult health scope")
        target = tuple(task[k] for k in ("subject", "outcome", "requested_relation"))
        if item in data["claim_revisions"]:
            ref = item["replaces"]
            old = old_claims.get((ref["claim_id"], ref["version"]))
            if (not old or claim.get("answer_revision_of") != ref or claim["claim_id"] != ref["claim_id"]
                    or target != tuple(old["answer_task"][k] for k in ("subject", "outcome", "requested_relation"))):
                raise ValueError("exact same-target claim predecessor required")
        elif any(cid == claim["claim_id"] for cid, _ in old_claims) or claim.get("answer_revision_of"):
            raise ValueError("new topic identity must be new")
        elif target in old_targets:
            raise ValueError("new topic must not duplicate a previous answer target")
        tasks.append(target)
    if len(tasks) != len(set(tasks)):
        raise ValueError("duplicate answer target")
    added = new_rules(data)
    rules = added + DEEPEN.revised_rules(previous, data)
    old_rule_ids = {row["rule_id"] for row in previous["rules"]}
    if any(rule["rule_id"] in old_rule_ids for rule in added):
        raise ValueError("new explanation rule identity must be new")
    if len({rule["rule_id"] for rule in rules}) != len(rules):
        raise ValueError("duplicate rule identity")
    if any(rule["requested_capability"] != "source_explanation" or rule["permitted_actions"]
           or rule.get("numeric_provenance") for rule in rules):
        raise ValueError("source prose quantities cannot grant candidate or parameter authority")
    return rules


verify_sources = COMPLETION.verify_sources
candidate_records = COMPLETION.candidate_records


@contextmanager
def readonly_workbench(root):
    """Reuse source eligibility reads without constructors that migrate databases."""
    root = Path(root).resolve()
    lib = Libraries.__new__(Libraries)
    lib.root = root
    lib.sources = sqlite3.connect((root / "sources.sqlite3").as_uri() + "?mode=ro", uri=True)
    try:
        lib.theories = sqlite3.connect((root / "theories.sqlite3").as_uri() + "?mode=ro", uri=True)
        try:
            for connection in (lib.sources, lib.theories):
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
            yield SimpleNamespace(root=root, lib=lib)
        finally:
            lib.theories.close()
    finally:
        lib.sources.close()


def previous_release(w, data):
    row = w.lib.theories.execute("SELECT manifest_json,sha256 FROM core_release WHERE release_id=?",
                                 (data["previous_release_id"],)).fetchone()
    if not row or digest(row[0].encode()) != row[1] or row[1] != data["previous_release_sha256"]:
        raise ValueError("previous release missing, changed or corrupt")
    return {"release_id": data["previous_release_id"], **json.loads(row[0])}


class _TransactionView:
    """Keep nested review helpers' connection contexts inside one transaction."""

    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@contextmanager
def atomic_theory_append(w):
    connection = w.lib.theories
    if connection.in_transaction:
        raise ValueError("activation requires a clean theory transaction")
    connection.execute("BEGIN IMMEDIATE")
    w.lib.theories = _TransactionView(connection)
    try:
        yield
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        w.lib.theories = connection


def activate(w, data):
    with atomic_theory_append(w):
        return _activate(w, data)


def _activate(w, data):
    previous = previous_release(w, data)
    rules = validate_contracts(previous, data)
    old_rows, source_before = TOPICS.HHS.snapshot(w), TOPICS.source_snapshot(w)
    additions = {"claims": {(item["claim"]["claim_id"], item["claim"]["version"])
                            for item in data["claims"] + data["claim_revisions"]},
                 "rules": {(rule["rule_id"], rule["rule_version"]) for rule in rules}}
    for key, table, identifier, status in (("claims", "source_claim", "claim_id", "verified"),
                                           ("rules", "application_rule", "rule_id", "active")):
        current = [dict(row) for row in w.lib.theories.execute(f"SELECT * FROM {table} WHERE status=?", (status,))]
        allowed = {(row[identifier], row["version"]) for row in previous[key]} | additions[key]
        if (any(row not in current for row in previous[key])
                or any((row[identifier], row["version"]) not in allowed for row in current)):
            raise ValueError("live knowledge membership differs from the frozen predecessor")
    claims, applications = [], []
    for item in data["claims"] + data["claim_revisions"]:
        claim = item["claim"]
        review = COMPLETION.review_record(w, "source_claim", "claim_id", claim["claim_id"], claim["version"], item["review_rationale"])
        w.review_claim(claim, review)
        claims.append({"claim": claim, "content_review": review})
    for rule in rules:
        review = COMPLETION.review_record(w, "application_rule", "rule_id", rule["rule_id"], rule["rule_version"],
            "Only general source explanations; preserve exact candidate dependencies and every prior member.", application=True)
        w.review_rule(rule, review)
        applications.append({"rule": rule, "application_review": review})
    release = TOPICS.HHS.existing_or_create_release(w, data["release_id"])
    for key, added in (("claims", len(claims)), ("rules", len(rules))):
        if len(release[key]) != len(previous[key]) + added or any(row not in release[key] for row in previous[key]):
            raise ValueError("previous release membership or reviews changed")
    if candidate_records(release) != candidate_records(previous):
        raise ValueError("candidate rule or exact claim dependency changed")
    after = TOPICS.HHS.snapshot(w)
    if any(row not in after[table] for table, rows in old_rows.items() for row in rows):
        raise ValueError("prior knowledge row changed")
    if TOPICS.source_snapshot(w) != source_before:
        raise ValueError("source library changed")
    added_ids = {rule["rule_id"] for rule in rules}
    for route in {route for rule in rules for route in rule["routes"]}:
        if any(p["rule_id"] in added_ids for p in w.reviewed_principles(route, {"requested_capability": "source_explanation"})["principles"]):
            raise ValueError("source explanation acquired numerical candidate authority")
    return release, claims, applications, previous


def protected_hashes():
    paths = set((ROOT / "artifacts/v14/knowledge").glob("*"))
    paths.update((ROOT / "src/healthzip/knowledge/data").glob("*.json"))
    for directory in (ROOT / ".local").glob("v14-knowledge-independent-round*"):
        paths.update(directory / name for name in (
            "source_packet.json", "cases.json", "freeze_receipt.json", "outputs.raw.json",
            "outputs.sha256", "judgments.json", "judgments_receipt.json", "code_identity.json"))
    return {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted(paths)
            if p.is_file() and "1.4.14" not in p.name and "1_4_14" not in p.name
            and p.name != "publication_audit.json" and not p.name.startswith("current-chapter-coverage")}


def run(w, data, *, activate_explanations=False):
    """Verify first, then optionally append; caller controls writable access."""
    before, source_before = TOPICS.HHS.snapshot(w), TOPICS.source_snapshot(w)
    previous = previous_release(w, data)
    validate_contracts(previous, data)
    sources, spans = verify_sources(w, data)
    result = {"version": data["version"], "reviewer_kind": "ai_assisted",
              "review_identity": data["review_identity"], "sources": sources,
              "previous_release_id": data["previous_release_id"],
              "previous_release_sha256": data["previous_release_sha256"],
              "source_library_mutations": 0, "independent_ai_denominator": 0,
              "independent_human_or_expert_denominator": 0}
    outputs = {f"practical-source-explanations-review-{data['version']}.json": result}
    if activate_explanations:
        release, claims, rules, previous = activate(w, data)
        outputs[f"release-{data['version']}.json"] = release
        outputs[f"practical-source-explanations-{data['version']}.json"] = {
            "release_id": release["release_id"], "release_sha256": release["sha256"],
            "previous_release_sha256": data["previous_release_sha256"], "claims": claims, "rules": rules,
            "independent_ai_denominator": 0, "independent_human_or_expert_denominator": 0}
        outputs[f"practical-source-explanations-release-verification-{data['version']}.json"] = {
            **result, "release_id": release["release_id"], "release_sha256": release["sha256"],
            "claim_versions": len(release["claims"]), "rule_versions": len(release["rules"]),
            "distinct_claims": len({r["claim_id"] for r in release["claims"]}),
            "distinct_rules": len({r["rule_id"] for r in release["rules"]}),
            "old_members_and_reviews_unchanged": True, "candidate_rules_and_dependencies_unchanged": True,
            "candidate_rules": len(candidate_records(release)["rules"]),
            "candidate_records_sha256": digest(dumps(candidate_records(previous)).encode()),
            "source_library_sha256": source_before,
            "validation_identity": "implementation-author software/source verification; not independent evaluation"}
    after = TOPICS.HHS.snapshot(w)
    if any(row not in after[table] for table, rows in before.items() for row in rows) or TOPICS.source_snapshot(w) != source_before:
        raise ValueError("existing knowledge or source rows changed")
    return outputs, spans


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-root", type=Path, default=ROOT / ".local/knowledge")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/v14/knowledge")
    parser.add_argument("--activate-explanations", action="store_true")
    args = parser.parse_args()
    data = definition()
    report = args.output_dir / f"practical-source-explanations-review-{data['version']}.json"
    protected = json.loads(report.read_text())["protected_artifact_sha256"] if report.exists() else protected_hashes()
    TOPICS.verify_hashes(protected)
    if args.activate_explanations:
        w = KnowledgeWorkbench(args.knowledge_root)
        try:
            outputs, spans = run(w, data, activate_explanations=True)
        finally:
            w.close()
    else:
        with readonly_workbench(args.knowledge_root) as w:
            outputs, spans = run(w, data)
    TOPICS.verify_hashes(protected)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in outputs.items():
        if name.startswith("practical-source-explanations-review-") or name.startswith("practical-source-explanations-release-verification-"):
            value["protected_artifact_sha256"] = protected
        TOPICS.HHS.write_public(args.output_dir / name, value, spans)
    print(json.dumps({"sources_verified": True, "activated": args.activate_explanations,
                      "protected_files": len(protected), "release_id": data["release_id"]}))


if __name__ == "__main__":
    main()
