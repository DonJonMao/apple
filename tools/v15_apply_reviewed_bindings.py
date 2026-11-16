"""Apply an explicitly authored, hash-pinned local review packet, preserving history.

The packet is not an automatic scientific reviewer. Each content and application
decision must already identify its reviewer and exact source evidence. Full text
and private database backups remain local; the public receipt contains IDs only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from healthzip.knowledge import KnowledgeWorkbench, domains, vector_index
from healthzip.knowledge.core import _review, _spans
from healthzip.knowledge.store import digest, dumps, now


def apply_packet(root, packet_path, output, backup_dir):
    raw = Path(packet_path).read_bytes()
    packet = json.loads(raw)
    if packet.get("schema") != "reviewed-metric-bindings-1.5.0" or not packet.get("created_at"):
        raise ValueError("dated_explicit_review_packet_required")
    output, backup = Path(output), Path(backup_dir)
    if output.exists() or backup.exists():
        raise ValueError("new_receipt_and_backup_paths_required")
    w = KnowledgeWorkbench(root)
    try:
        domains.ensure_schema(w)
        vector_index.ensure_schema(w)
        # Validate the entire packet before adding any scientific rows.
        for item in packet["claims"]:
            claim = item["claim"]
            _review(item["review"])
            _review(item.get("domain_review", item["review"]))
            evidence = _spans(w, claim["evidence_links"], numeric=claim.get("numeric", False))
            expected = item["exact_text_hashes"]
            if {e["span_id"]: e["text_hash"] for e in evidence} != expected:
                raise ValueError("reviewed_evidence_content_changed")
            for e in evidence:
                if not w.lib.sources.execute("SELECT 1 FROM retrieval_unit WHERE span_id=?",
                                             (e["span_id"],)).fetchone():
                    raise ValueError("register_source_units_before_applying_scientific_packet")
            if not item["domains"] or not set(item["domains"]) <= domains.DOMAIN_IDS:
                raise ValueError("reviewed_domains_required")
            old = w.lib.theories.execute(
                "SELECT payload_json,review_json FROM source_claim WHERE claim_id=? AND version=?",
                (claim["claim_id"], claim["version"])).fetchone()
            if old and tuple(old) != (dumps(claim), dumps(item["review"])):
                raise ValueError("existing_claim_and_review_must_be_reused_exactly")
            for binding in item["bindings"]:
                _review(binding["review"], application=True)
                allowed = domains.configuration()["profiles"][binding["metric_id"]]["required_evidence_types"]
                if not binding["evidence_types"] or not set(binding["evidence_types"]) <= set(allowed):
                    raise ValueError("binding_must_not_invent_profile_evidence_types")
        backup.mkdir(parents=True)
        for name, conn in (("sources", w.lib.sources), ("theories", w.lib.theories)):
            with sqlite3.connect(backup / (name + ".sqlite3")) as target:
                conn.backup(target)
        receipt = {"schema": "reviewed-binding-receipt-1.5.0", "created_at": now(),
                   "review_packet_sha256": digest(raw), "claims": [],
                   "independent_expert_validation": False, "candidate_authority_granted": False}
        for item in packet["claims"]:
            claim, review = item["claim"], item["review"]
            w.review_claim(claim, review)
            span_ids = list(item["exact_text_hashes"])
            # Appended reviews do not rewrite the initial provisional assignment.
            domain_review = item.get("domain_review", review)
            vector_index.review_unit_domains(w, span_ids, item["domains"], domain_review)
            existing_domains = {d["domain_id"] for d in domains.object_domains(
                w, "claim", claim["claim_id"], claim["version"])}
            new_domains = set(item["domains"]) - existing_domains
            if new_domains:
                domains.assign(w, object_type="claim", object_id=claim["claim_id"],
                               object_version=claim["version"], domains=new_domains,
                               status="content_checked", actor=domain_review["reviewer"],
                               rationale=domain_review["rationale"])
            edges = []
            for binding in item["bindings"]:
                edges.append({"metric_id": binding["metric_id"], "evidence_types": binding["evidence_types"],
                    "edge_id": domains.link(w,
                        origin={"type": "claim", "id": claim["claim_id"], "version": claim["version"]},
                        relation=binding["relation"], target={"type": "metric", "id": binding["metric_id"],
                            "version": domains.configuration()["schema_version"]}, span_ids=span_ids,
                        applicability=binding["applicability"], actor=binding["review"]["reviewer"],
                        rationale=binding["review"]["rationale"], evidence_types=binding["evidence_types"],
                        review=binding["review"])})
            receipt["claims"].append({"claim_id": claim["claim_id"], "claim_version": claim["version"],
                "reviewer_kind": review["reviewer_kind"], "reviewed_at": review["reviewed_at"],
                "domains": item["domains"], "exact_evidence": [
                    {"span_id": sid, "text_hash": h} for sid, h in item["exact_text_hashes"].items()],
                "claim_sha256": digest(dumps(claim).encode()), "bindings": edges,
                "scope": claim["scope"], "limitations": claim["limitations"]})
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x") as stream:
            stream.write(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        return receipt
    finally:
        w.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--backup-dir", required=True)
    args = parser.parse_args()
    result = apply_packet(args.root, args.packet, args.output, args.backup_dir)
    print(json.dumps({"claims": len(result["claims"]), "candidate_authority_granted": False}))
