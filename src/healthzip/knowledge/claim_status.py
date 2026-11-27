"""Current, local annotations for exact frozen claim versions and their premises."""

from __future__ import annotations

import json

from .applicability import context_match
from .core import _claim
from .metric_retrieval import _edge_current
from .rights import usage_rejection


def _current_claim(w, reference, context):
    claim, review, spans = _claim(w, reference)
    for evidence in spans:
        span = w.lib.span(evidence["span_id"], include_metadata=False)
        rejection = usage_rejection(json.loads(span["rights_json"]), context.get("usage_scope", "local_noncommercial"))
        if rejection:
            raise ValueError(rejection)
    return claim, review, spans


def frozen_claim_references(questions=(), runs=()):
    """Small immutable-use manifest, collected while generation already has runs."""
    refs = {}

    def add(item, context, question_id=None):
        identity, version = item.get("claim_id"), item.get("version") or item.get("claim_version")
        if not identity or not version:
            return
        key = (identity, version, json.dumps(context, sort_keys=True))
        ref = refs.setdefault(key, {"claim_id": identity, "version": version,
            "applicability_context": context, "question_ids": [], "required_claim_refs": []})
        if question_id and question_id not in ref["question_ids"]:
            ref["question_ids"].append(question_id)
        for dependency in item.get("required_claim_refs", []):
            if dependency not in ref["required_claim_refs"]:
                ref["required_claim_refs"].append(dependency)

    for question in questions:
        evidence = question.get("evidence") or {}
        context = evidence.get("applicability_context") or {}
        for item in [*evidence.get("items", []), *evidence.get("restricted_items", []),
                     *evidence.get("claim_reviews", [])]:
            add(item, context, question.get("id"))
    for run in runs:
        for query in run.get("knowledge", {}).get("queries", []):
            for item in query.get("claims", []):
                add(item, query.get("applicability_context") or {})
    # Return JSON values, not aliases into the report's mutable assembly inputs.
    return json.loads(json.dumps([refs[key] for key in sorted(refs)]))


def current_claim_status(w, reference, *, context=None, memo=None, path=()):
    """Inspect only this claim's indexed edges; never replace historical evidence.

    A scope mismatch is irrelevant to this use. An unknown scope is not proof
    that a newly disputed premise is irrelevant, and is reported separately.
    """
    context = context or {}
    memo = {} if memo is None else memo
    if reference in memo:
        return memo[reference]
    result = {"claim_id": reference[0], "version": reference[1], "status": "verified",
              "reason": None, "conflicts": [], "dependencies": [], "scope_checks": []}
    if reference in path:
        return {**result, "status": "needs_review", "reason": "cyclic_required_claims"}
    row = w.lib.theories.execute(
        "SELECT status FROM source_claim WHERE claim_id=? AND version=?", reference).fetchone()
    if not row or row["status"] != "verified":
        result["status"] = row["status"] if row else "missing"
        memo[reference] = result
        return result
    try:
        claim, _, _ = _current_claim(w, {"claim_id": reference[0], "version": reference[1]}, context)
    except ValueError as exc:
        reason = str(exc)
        result.update(status="source_withdrawn" if reason == "withdrawn" else "needs_review", reason=reason)
        memo[reference] = result
        return result
    matched, reason = context_match(claim.get("conditions", []), context)
    if not matched:
        result.update(status="scope_unverified", reason=reason)
    incoming = w.lib.theories.execute("""SELECT * FROM knowledge_evidence_edge
        WHERE relation='required_by' AND to_type='claim' AND to_id=? AND to_version=?
        ORDER BY edge_id""", reference).fetchall()
    for edge in incoming:
        payload = json.loads(edge["payload_json"])
        matched, reason = context_match(payload["applicability"], context)
        if not matched and reason.startswith("scope_mismatch:"):
            continue
        if not matched:
            result["scope_checks"].append({"edge_id": edge["edge_id"], "reason": reason})
            continue
        if edge["from_type"] != "claim" or not _edge_current(w, payload):
            result.update(status="needs_review", reason="required_relation_evidence_unavailable")
            continue
        required = current_claim_status(w, (edge["from_id"], edge["from_version"]),
                                        context=context, memo=memo, path=(*path, reference))
        result["dependencies"].append(required)
    conflicts = w.lib.theories.execute("""SELECT * FROM knowledge_evidence_edge
        WHERE relation='conflicts_with' AND
          ((from_type='claim' AND from_id=? AND from_version=?) OR
           (to_type='claim' AND to_id=? AND to_version=?)) ORDER BY edge_id""",
        (*reference, *reference)).fetchall()
    for edge in conflicts:
        payload = json.loads(edge["payload_json"])
        if payload["origin"]["type"] != "claim" or payload["target"]["type"] != "claim":
            continue
        matched, reason = context_match(payload["applicability"], context)
        if not matched and reason.startswith("scope_mismatch:"):
            continue
        if not matched:
            result["scope_checks"].append({"edge_id": edge["edge_id"], "reason": reason})
            continue
        if not _edge_current(w, payload):
            # An unavailable conflict source is not proof of resolution.
            result["scope_checks"].append({"edge_id": edge["edge_id"],
                                          "reason": "conflict_evidence_unavailable"})
            continue
        eligible = True
        for endpoint in (payload["origin"], payload["target"]):
            try:
                other, _, _ = _current_claim(w, {"claim_id": endpoint["id"], "version": endpoint["version"]}, context)
                matched, reason = context_match(other.get("conditions", []), context)
                if not matched:
                    eligible = False
                    if not reason.startswith("scope_mismatch:"):
                        result["scope_checks"].append({"edge_id": edge["edge_id"], "reason": reason})
            except ValueError:
                eligible = False
        if eligible:
            result["conflicts"].append({"edge_id": edge["edge_id"], **payload})
    disputed_dependencies = [item for item in result["dependencies"] if item["status"] != "verified"]
    if result["conflicts"]:
        result.update(status="conflicted", reason="current_exact_claim_conflict")
    elif disputed_dependencies:
        result.update(status="dependent_restriction", reason="required_claim_not_current")
    elif result["scope_checks"] and result["status"] == "verified":
        result.update(status="scope_unverified", reason="current_relation_scope_unverified")
    memo[reference] = result
    return result
