"""Adapt actual retrieval/annotation/source traces into the single QAL executor."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .adjudication import evidence_supports_relation, validate_annotation
from .store import digest


def quality_context(w, cases, annotations=None):
    annotations = annotations or {}
    context = {key: [] for key in ("retrieval_cases", "retrieval_precision_cases", "citations", "claims", "intents", "requests",
        "acquisition_manifest", "theory_manifest", "feature_claim_requirements", "access_requests", "numeric_claims", "source_versions")}
    adjudications = []
    for case in cases:
        output = case["output"]
        cid = case["case_id"]
        question = case.get("question", case.get("query_zh", ""))
        annotation = annotations.get(cid)
        checked = validate_annotation(annotation, cid, question, output) if annotation else None
        trusted = annotation if checked and checked["accepted"] else None
        if checked:
            adjudications.append({"case_id": cid, **checked})
        groups = case.get("gold_groups")
        if groups is None:
            groups = {f"group-{i}": [[sid] for sid in alternatives] for i, alternatives in enumerate(case.get("gold_evidence_groups", case.get("required_gold_groups", [])))}
        context["retrieval_cases"].append({"query_id": cid, "gold_review_status": case.get("gold_review_status", "unreviewed"),
            "gold_groups": groups, "sufficient_bundles": case.get("sufficient_bundles", [list(groups)] if groups else []),
            "retrieved_unit_ids": sorted({unit for candidate in output.get("retrieval", {}).get("candidates", [])
                for span in candidate["spans"] for unit in (span["source_id"], span["version_id"], span["span_id"])}),
            "conflict_screen": output.get("support_assessment", {}).get("conflict_screen")})
        evidence = trusted.get("evidence_judgments", []) if trusted else []
        judged = {(e["claim_index"], e["span_id"], e["source_version_id"]): e for e in evidence}
        units = []
        for candidate in output.get("retrieval", {}).get("candidates", []):
            for span in candidate["spans"]:
                label = next((e["relation"] for e in evidence if e["span_id"] == span["span_id"]), None)
                units.append({"unit_id": span["span_id"], "relevance": "unjudged" if label is None else "irrelevant" if label == "irrelevant" else "relevant"})
        context["retrieval_precision_cases"].append({"query_id": cid, "units": units, "cluster_id": case.get("source_family", cid)})
        for index, claim in enumerate(output.get("claims", [])):
            reviews = [e for (i, _, _), e in judged.items() if i == index]
            supported = evidence_supports_relation(claim["evidence_relation"], reviews)
            context["claims"].append({"answer_id": cid, "claim_id": f"{cid}:{index}", "requires_support": True,
                "support_label": "supported" if supported else "unjudged" if not reviews else "unsupported",
                "provenance_verified": all(w.lib.span(sid) and w.lib.eligible(w.lib.span(sid))[0] for sid in claim["span_ids"]),
                "reviewer_kind": checked["reviewer_kind"] if trusted else "unjudged", "applicability_required": True,
                "applicability_review": "completed" if reviews else "pending",
                "applicability_errors": ["scope_mismatch"] if any(not e["scope_matches"] for e in reviews) else []})
        for citation in output.get("citations", []):
            spans = [w.lib.span(sid) for sid in citation["span_ids"]]
            for index, claim in enumerate(output.get("claims", [])):
                overlap = set(claim["span_ids"]) & set(citation["span_ids"])
                if not overlap:
                    continue
                labels = [judged[(index, sid, citation["source_version_id"])] for sid in overlap if (index, sid, citation["source_version_id"]) in judged]
                label = "supported" if len(labels) == len(overlap) and evidence_supports_relation(claim["evidence_relation"], labels) else "unjudged" if not labels else "irrelevant" if any(not x["scope_matches"] or x["relation"] == "irrelevant" for x in labels) else "partial" if all(x["relation"] == "qualifies" for x in labels) else "contradicts"
                context["citations"].append({"claim_id": f"{cid}:{index}", "source_version_id": citation["source_version_id"], "span_ids": sorted(overlap),
                    "hash_verified": all(s and digest(s["text"].encode()) == s["text_hash"] for s in spans),
                    "locator_in_bounds": all(s and bool(json.loads(s["locator_json"])) for s in spans),
                    "version_resolved": all(s and s["version_id"] == citation["source_version_id"] and w.lib.eligible(s)[0] for s in spans), "support_label": label})
        answer = trusted["answer_judgment"] if trusted else {}
        sufficient = case.get("evidence_state", "unjudged")
        label = "unscorable"
        if trusted:
            if answer["decision"] == "pass":
                label = "correct_boundary"
            elif output.get("claims") and (not answer["scope_correct"] or not answer["relation_supported"]):
                label = "overanswer" if sufficient == "insufficient" else "wrong_target"
            elif sufficient == "sufficient" and not answer["addresses_target"]:
                label = "underanswer"
            else:
                # An insufficient task can still be answered badly without
                # overclaiming, e.g. omitting its applicable subtask or reason.
                label = "incomplete_boundary_or_partial_answer"
        context["intents"].append({"intent_id": cid, "evidence_state": sufficient, "label": label})
        fallback = output["status"] in {"insufficient_evidence", "related_material_only", "conflicting_evidence"}
        context["requests"].append({"request_id": cid, "eligible": True, "trace_complete": True,
            "fallback_events": [{"reason": output["status"]}] if fallback else [], "allowed_subtask_exists": bool(output.get("observations")),
            "fallback_completed": bool(output.get("observations"))})
        # Independent numerical references and access traces must come from the
        # evaluator/authorized executor. Absence is an empty denominator, not pass.
        context["numeric_claims"].extend(case.get("numeric_claims", []))
        context["access_requests"].extend(case.get("access_requests", []))
    for row in w.lib.sources.execute("SELECT source_id FROM source"):
        sid = row[0]
        versions = w.lib.sources.execute("SELECT * FROM version WHERE source_id=? AND material_type='fulltext'", (sid,)).fetchall()
        eligible = []
        for version in versions:
            spans = [w.lib.span(s[0]) for s in w.lib.sources.execute("SELECT span_id FROM span WHERE version_id=?", (version["version_id"],))]
            usable = any(w.lib.eligible(s)[0] for s in spans)
            if usable:
                eligible.append(version)
            source = w.lib.source(sid)
            context["source_versions"].append({"source_version_id": version["version_id"], "active": usable,
                "identity_review": "verified" if version["identity_status"] == "matched" or usable else "pending",
                "rights_for_declared_use": usable, "status_checked_at": source["updated_at"],
                "retracted": source["scientific_state"] == "withdrawn", "correction_pending_review": source["scientific_state"] == "corrected_pending_review" and not usable})
        best = (eligible or versions or [None])[-1]
        context["acquisition_manifest"].append({"source_id": sid, "target_material_type": "fulltext",
            "fetch_status": "fulltext_saved" if versions else "not_fetched", "raw_sha256": best["sha256"] if best else None,
            "bytes": best["byte_length"] if best else 0, "identity_review": "verified" if eligible else "pending",
            "rights_status": "permitted" if eligible else "pending", "retrievable": bool(eligible)})
    for row in w.lib.theories.execute("SELECT * FROM theory"):
        review = json.loads(row["review_json"])
        active = row["status"] == "approved" and all(w.lib.span(sid) and w.lib.eligible(w.lib.span(sid))[0] for link in review.get("evidence_links", []) for sid in link["span_ids"])
        context["theory_manifest"].append({"theory_id": row["theory_id"], "review_decision": row["status"], "review_reason": review.get("rationale"),
            "reviewer_kind": review.get("reviewer_kind"), "independent_reviewer": None, "content_reviewed": bool(review),
            "evidence_links_valid": active, "rights_valid": active, "scope_valid": active, "validation_gate_passed": active})
    from .core import _claim
    for row in w.lib.theories.execute("SELECT * FROM source_claim"):
        review = json.loads(row["review_json"])
        try:
            _claim(w, {"claim_id": row["claim_id"], "version": row["version"]})
            active = True
        except ValueError:
            active = False
        context["theory_manifest"].append({"theory_id": row["claim_id"], "review_decision": "approved" if active else "pending",
            "review_reason": review.get("rationale"), "reviewer_kind": review["reviewer_kind"], "independent_reviewer": None,
            "content_reviewed": review.get("content_checked"), "evidence_links_valid": active, "rights_valid": active,
            "scope_valid": active, "validation_gate_passed": active, "capability": "source_explanation_only"})
    from .core import RECORD_POLICY
    by_rule = {}
    record_rules = {}
    for rule in w.core_status()["rules"]:
        target = record_rules if rule["capability"] in RECORD_POLICY["capabilities"] else by_rule
        target[rule["rule_id"]] = target.get(rule["rule_id"], False) or rule["effective"]
    context["feature_claim_requirements"] = [{"rule_id": key, "satisfied_by_active_card": value} for key, value in by_rule.items()]
    context["feature_record_requirements"] = [{"rule_id": key, "satisfied_by_record_contract": value} for key, value in record_rules.items()]
    context["semantic_adjudications"] = adjudications
    context["intent_coverage"] = {"independently_reviewed": sum(x["accepted"] for x in adjudications), "total": len(cases)}
    return context


def run_quality(w, cases, annotations=None):
    from healthzip.science import evaluate
    context = quality_context(w, cases, annotations)
    end = datetime.now(timezone.utc)
    results = [evaluate(f"QAL-{code:02d}", [], cutoff_time=end.isoformat(), window_start=(end - timedelta(days=1)).isoformat(), window_end=end.isoformat(), context=context) for code in range(1, 13)]
    return {"contract": "actual_knowledge_traces_to_unified_QAL_1.4", "metrics": results,
            "annotation_counts": {kind: sum(x["accepted"] and x["reviewer_kind"] == kind for x in context["semantic_adjudications"]) for kind in ("independent_human", "independent_ai")},
            "limits": ["Unjudged source/answer labels remain unknown; no synthetic or AI review is counted as independent human validation.", "Quality counts do not establish individual training effectiveness."]}
