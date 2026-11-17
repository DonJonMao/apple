"""Read-only trace from previously reviewed problem units to production uses.

No source prose, scientific promotion, changed lifecycle or evaluation rerun.
"""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SOURCES = {"N1", "E8", "R2b", "R3b", "R6", "V15-QUER-RHR-2020", "V15-AWHS-CYCLE-VARIATION-2023"}
TARGETED_GROUPS = {
    "E8_rate_sign_inconsistency": ["G00239", "G00240"],
    "R2b_volume_direction_inconsistency": ["G00994"],
    "planned_perceived_intensity_is_not_adoption_or_followup": ["G01241"],
    "hrv_context_is_not_performance_equivalence": ["G01014"],
    "rhr_subgroup_mean_is_not_future_performance": ["G01660"],
}


def audit(root, pool_path):
    pool_bytes = Path(pool_path).read_bytes()
    pool = json.loads(pool_bytes)
    source = sqlite3.connect(f"file:{Path(root) / 'sources.sqlite3'}?mode=ro", uri=True)
    theory = sqlite3.connect(f"file:{Path(root) / 'theories.sqlite3'}?mode=ro", uri=True)
    source.row_factory = theory.row_factory = sqlite3.Row
    try:
        claims, edges, rules = [], [], []
        all_rules = [dict(row) for row in theory.execute("SELECT * FROM application_rule")]
        for row in theory.execute("SELECT * FROM source_claim ORDER BY claim_id,version"):
            payload = json.loads(row["payload_json"])
            links = [link for link in payload.get("evidence_links", []) if link["source_id"] in SOURCES]
            if not links:
                continue
            references = []
            for link in links:
                for sid in link["span_ids"]:
                    span = source.execute("SELECT version_id,text_hash,kind,section_path,locator_json FROM span WHERE span_id=?", (sid,)).fetchone()
                    references.append({"source_id": link["source_id"], "source_version": link["source_version_id"],
                        "span_id": sid, "exists_at_exact_version": bool(span and span["version_id"] == link["source_version_id"]),
                        "text_hash": span["text_hash"] if span else None,
                        "kind": span["kind"] if span else None, "locator": json.loads(span["locator_json"]) if span else None})
            claims.append({"claim_id": row["claim_id"], "version": row["version"], "status": row["status"],
                "payload_sha256": hashlib.sha256(row["payload_json"].encode()).hexdigest(),
                "scope": payload.get("scope"), "conditions": payload.get("conditions", []), "references": references})
            for edge in theory.execute("SELECT * FROM knowledge_evidence_edge WHERE from_id=? AND from_version=?", (row["claim_id"], row["version"])):
                detail = json.loads(edge["payload_json"])
                edges.append({key: edge[key] for key in ("edge_id", "from_id", "from_version", "relation", "to_type", "to_id", "to_version")} |
                    {"grants_capability": detail.get("grants_capability"), "evidence_types": detail.get("evidence_types"),
                     "evidence": detail.get("evidence", [])})
            for rule in all_rules:
                detail = json.loads(rule["payload_json"])
                if {"claim_id": row["claim_id"], "version": row["version"]} in detail.get("claim_refs", []):
                    rules.append({"rule_id": rule["rule_id"], "version": rule["version"], "status": rule["status"],
                        "claim_refs": detail["claim_refs"], "capability": detail.get("requested_capability"),
                        "permitted_actions": detail.get("permitted_actions", []), "forbidden": detail.get("forbidden", []),
                        "payload_sha256": hashlib.sha256(rule["payload_json"].encode()).hexdigest()})
        issues = []
        by_group = {g["group_id"]: g for g in pool["groups"]}
        for issue, ids in TARGETED_GROUPS.items():
            exact = [alternative for gid in ids for alternative in by_group[gid]["alternatives"]]
            sids = {ref["span_id"] for ref in exact}
            direct = [{"claim_id": c["claim_id"], "version": c["version"]} for c in claims
                      if sids & {ref["span_id"] for ref in c["references"]}]
            issues.append({"issue": issue, "group_ids": ids, "exact_units": exact, "direct_claim_refs": direct})
        releases = []
        for row in theory.execute("SELECT release_id,manifest_json,sha256 FROM core_release ORDER BY created_at"):
            manifest = json.loads(row["manifest_json"])
            members = [{"claim_id": c["claim_id"], "version": c["version"]} for c in manifest["claims"]
                       if any(c["claim_id"] == item["claim_id"] and c["version"] == item["version"] for item in claims)]
            if members:
                releases.append({"release_id": row["release_id"], "sha256": row["sha256"], "claim_members": members})
        return {"schema": "analysis-core-dependency-trace-1", "created_at": datetime.now(timezone.utc).isoformat(),
            "pool_sha256": hashlib.sha256(pool_bytes).hexdigest(), "sources_in_scope": sorted(SOURCES),
            "claims": claims, "metric_edges": edges, "rules": rules, "releases": releases, "specific_issues": issues,
            "read_only": True, "new_permissions": False, "annotation_grades_used_as_authority": False,
            "scope": "stored_dependencies_not_proof_of_scientific_sufficiency_or_full_runtime_validation"}
    finally:
        source.close()
        theory.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-root", required=True)
    parser.add_argument("--source-pool", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = audit(args.knowledge_root, args.source_pool)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"claims": len(report["claims"]), "edges": len(report["metric_edges"]),
                      "rules": len(report["rules"]), "issues": len(report["specific_issues"])}))


if __name__ == "__main__":
    main()
