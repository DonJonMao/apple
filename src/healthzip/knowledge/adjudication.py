"""Bind separate answer/evidence judgments to exact frozen questions and outputs."""

from __future__ import annotations

from .store import digest, dumps

VALIDATOR_VERSION = "claim-evidence-bundle-1.4.1"


def evidence_supports_relation(expected, judgments):
    """A direct relation may be accompanied by scope/limitation evidence.

    Qualifiers alone do not establish a positive or negative proposition, and
    an opposite, irrelevant or scope-mismatched span cannot be laundered by one
    otherwise supportive span in the bundle.
    """
    return (bool(judgments) and any(e.get("relation") == expected for e in judgments)
            and all(e.get("scope_matches") is True and e.get("relation") in {expected, "qualifies"} for e in judgments))


def annotation_identity(case_id, question, output):
    return {"case_id": case_id, "question_sha256": digest(question.encode()),
            "output_sha256": digest(dumps(output).encode()),
            "evidence_bundle_hash": output["evidence_bundle_hash"]}


def validate_annotation(annotation, case_id, question, output):
    errors = []
    expected = annotation_identity(case_id, question, output)
    for key, value in expected.items():
        if annotation.get(key) != value:
            errors.append("annotation_binding_mismatch:" + key)
    kind = {"independent_ai_review": "independent_ai", "independent_human_review": "independent_human"}.get(
        annotation.get("reviewer_kind"), annotation.get("reviewer_kind"))
    if kind not in {"independent_human", "independent_ai", "implementation_self_review", "synthetic_fixture"}:
        errors.append("reviewer_kind_required")
    if not annotation.get("reviewer") or not annotation.get("reviewed_at"):
        errors.append("identified_dated_reviewer_required")
    if kind in {"independent_human", "independent_ai"} and annotation.get("independent_of_implementation") is not True:
        errors.append("independence_declaration_required")
    judgment = annotation.get("answer_judgment", {})
    if judgment.get("decision") not in {"pass", "fail"} or not judgment.get("rationale"):
        errors.append("explicit_answer_judgment_and_rationale_required")
    for field in ("addresses_target", "scope_correct", "relation_supported"):
        if not isinstance(judgment.get(field), bool):
            errors.append("answer_dimension_required:" + field)
    if judgment.get("decision") == "pass" and not all(judgment.get(k) is True for k in ("addresses_target", "scope_correct", "relation_supported")):
        errors.append("passing_answer_conflicts_with_dimension_judgments")
    expected_evidence = {}
    for index, claim in enumerate(output.get("claims", [])):
        for citation in output.get("citations", []):
            if citation["theory_id"] != claim["theory_id"] or citation["theory_version"] != claim["theory_version"]:
                continue
            for sid in set(citation["span_ids"]) & set(claim["span_ids"]):
                expected_evidence[(index, sid, citation["source_version_id"])] = claim["evidence_relation"]
    judgments = annotation.get("evidence_judgments")
    if not isinstance(judgments, list):
        errors.append("separate_evidence_judgments_required")
        judgments = []
    seen = set()
    for evidence in judgments:
        key = (evidence.get("claim_index"), evidence.get("span_id"), evidence.get("source_version_id"))
        if key not in expected_evidence or key in seen:
            errors.append("evidence_judgment_not_bound_to_unique_cited_claim")
        seen.add(key)
        if (evidence.get("relation") not in {"supports", "refutes", "qualifies", "irrelevant", "insufficient"}
                or not isinstance(evidence.get("scope_matches"), bool) or not evidence.get("rationale")):
            errors.append("complete_evidence_relation_judgment_required")
    if set(expected_evidence) != seen:
        errors.append("cited_claim_evidence_judgment_coverage_incomplete")
    if judgment.get("decision") == "pass":
        for index, claim in enumerate(output.get("claims", [])):
            evidence = [e for e in judgments if e.get("claim_index") == index]
            if not evidence_supports_relation(claim["evidence_relation"], evidence):
                errors.append("passing_answer_conflicts_with_evidence_judgment")
    return {"validator_version": VALIDATOR_VERSION, "accepted": not errors, "errors": sorted(set(errors)), "reviewer_kind": kind,
            "decision": judgment.get("decision") if not errors else "pending",
            "human_semantic_denominator_increment": int(not errors and kind == "independent_human"),
            "ai_semantic_denominator_increment": int(not errors and kind == "independent_ai"),
            "limit": "Reviewer identity/independence are declared audit inputs; software cannot certify professional credentials."}


def score_frozen_annotations(frozen, annotations):
    """Score a frozen, separately reviewed packet without rerunning/tuning retrieval."""
    indexed = {a["case_id"]: a for a in annotations["annotations"]}
    counts = {"independent_human_reviewed": 0, "independent_human_pass": 0,
              "independent_ai_reviewed": 0, "independent_ai_pass": 0, "invalid_annotations": 0}
    results = []
    for case in frozen["cases"]:
        annotation = indexed.get(case["case_id"])
        if annotation is None:
            results.append({"case_id": case["case_id"], "status": "annotation_missing"})
            continue
        checked = validate_annotation(annotation, case["case_id"], case["question"], case["output"])
        counts["invalid_annotations"] += not checked["accepted"]
        for reviewer, key in (("independent_human", "human"), ("independent_ai", "ai")):
            increment = checked[key + "_semantic_denominator_increment"]
            counts[reviewer + "_reviewed"] += increment
            counts[reviewer + "_pass"] += increment and checked["decision"] == "pass"
        results.append({"case_id": case["case_id"], **checked})
    failed = any(case.get("decision") == "fail" for case in results)
    return {"validator_version": VALIDATOR_VERSION, "counts": counts, "cases": results, "evaluation_scope": frozen.get("data_kind"),
            "frozen_packet_sha256": digest(dumps(frozen).encode()),
            "frozen_packet_hash_scope": "canonical JSON; file-byte hash is recorded by the execution artifact",
            "release_gate": "failed_independent_review" if failed else "pending_independent_human_review",
            "scientific_validation": "Synthetic source/answer regressions; independent AI review is not independent human/domain-expert validation."}
