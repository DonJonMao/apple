"""Append provisional v1.5 routing metadata; never change legacy review/authority rows."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from healthzip.knowledge import KnowledgeWorkbench, domains, vector_index
from healthzip.knowledge.core import _claim


def migrate(w):
    counts = defaultdict(int)
    versions = defaultdict(set)
    claim_domains = {}
    for row in w.lib.theories.execute(
        "SELECT claim_id,version,payload_json FROM source_claim ORDER BY claim_id,version"
    ).fetchall():
        claim = json.loads(row["payload_json"])
        subject = claim.get("answer_task", {}).get("subject")
        proposed = (
            ["strength", "wearable"]
            if subject == "statistical_inference"
            else ["cardiometabolic", "strength"]
            if subject == "physical_activity"
            else ["strength"]
        )
        domains.assign(
            w,
            object_type="claim",
            object_id=row["claim_id"],
            object_version=row["version"],
            domains=proposed,
            status="provisional",
            actor="Codex legacy product-routing migration",
            rationale="Proposal from existing declared answer-task subject; preserves content review and grants no application or candidate permission.",
        )
        claim_domains[(row["claim_id"], row["version"])] = set(proposed)
        counts["legacy_claim_versions_tagged"] += 1
        try:
            _, _, evidence = _claim(w, {"claim_id": row["claim_id"], "version": row["version"]})
        except ValueError:
            continue
        for span in evidence:
            versions[(span["source_id"], span["source_version_id"])].update(proposed)
    for (sid, vid), proposed in versions.items():
        domains.assign(
            w,
            object_type="source_version",
            object_id=sid,
            object_version=vid,
            domains=sorted(proposed),
            status="provisional",
            actor="Codex legacy product-routing migration",
            rationale="Proposal from already bound claim subjects, not a blanket review of this source.",
        )
        # Register only an unregistered version, retaining immutable pre-existing assignments.
        if not w.lib.sources.execute(
            "SELECT 1 FROM retrieval_unit u JOIN span s ON s.span_id=u.span_id WHERE s.version_id=?",
            (vid,),
        ).fetchone():
            counts["legacy_units_registered"] += vector_index.register_spans(
                w, vid, sorted(proposed)
            )
        counts["legacy_source_versions_tagged"] += 1
    for row in w.lib.theories.execute(
        "SELECT rule_id,version,payload_json FROM application_rule"
    ).fetchall():
        rule = json.loads(row["payload_json"])
        proposed = set()
        for ref in rule.get("claim_refs", []):
            proposed.update(claim_domains.get((ref["claim_id"], ref["version"]), set()))
        if not proposed:
            proposed = {"strength"}
        domains.assign(
            w,
            object_type="rule",
            object_id=row["rule_id"],
            object_version=row["version"],
            domains=sorted(proposed),
            status="provisional",
            actor="Codex legacy product-routing migration",
            rationale="Proposal from existing claim_refs or training product scope. Original rule status and permissions are unchanged; claim_refs remain the dependency contract.",
        )
        counts["legacy_rule_versions_tagged"] += 1
    for mid, profile in domains.configuration()["profiles"].items():
        proposed = profile["primary_domains"] + profile["secondary_domains"]
        if not proposed:
            continue
        domains.assign(
            w,
            object_type="metric",
            object_id=mid,
            object_version=domains.configuration()["schema_version"],
            domains=proposed,
            status="provisional",
            actor="Codex fixed metric routing configuration",
            rationale="Explicit product routing configuration, not scientific application review.",
        )
        counts["metric_profiles_with_domain_tags"] += 1
    report = {
        "counts": dict(counts),
        "all_assignments": "provisional",
        "existing_reviews_or_permissions_modified": False,
        "new_scientific_claims_or_rules_approved": 0,
        "mapping_basis": "existing declared subjects and claim_refs; not keyword inference from health data",
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".local/knowledge")
    parser.add_argument("--output")
    args = parser.parse_args()
    target = Path(args.output) if args.output else None
    if target and target.exists():
        raise ValueError("migration_report_exists_use_a_new_report_path")
    w = KnowledgeWorkbench(args.root)
    try:
        report = migrate(w)
    finally:
        w.close()
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if target:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x") as handle:
            handle.write(serialized)
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
