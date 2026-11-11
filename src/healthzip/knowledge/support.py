"""Explicit question/claim/scope bindings separate retrieval from answer support.

Lexical ranking discovers reading material. It supplies no entailment verdict.
Supported answers require a reviewed relation to a resolved target proposition.
Unresolved free text remains a search, with its evidence gap visible.
"""

from __future__ import annotations

from .store import digest, dumps

RELATIONS = {"supports", "refutes", "qualifies"}


def normalized_question(value):
    return " ".join(str(value).strip().lower().split()).rstrip("?？。")


def validate_bindings(claim):
    for binding in claim.get("answer_bindings", []):
        target = binding.get("target_claim", {})
        if (not isinstance(target.get("proposition"), str) or not target["proposition"].strip()
                or not isinstance(target.get("scope"), dict) or not target["scope"]
                or binding.get("relation") not in RELATIONS or not binding.get("rationale")
                or not isinstance(binding.get("question"), str) or not binding["question"].strip()):
            raise ValueError("answer binding requires question, scoped target proposition, evidence relation and rationale")


def target_key(target):
    return dumps({"proposition": normalized_question(target["proposition"]), "scope": target["scope"]})


def assess_support(question, context, candidates, *, required_parts=(), displayed=None):
    from .retrieval import _context_match

    supplied = context.get("target_claims")
    targets = {}
    if supplied is not None:
        if not isinstance(supplied, list) or not supplied:
            raise ValueError("target_claims must contain scoped propositions")
        for target in supplied:
            if not isinstance(target, dict) or not target.get("proposition") or not isinstance(target.get("scope"), dict) or not target["scope"]:
                raise ValueError("target proposition and explicit scope are required")
            targets[target_key(target)] = target
        origin = "explicit_user_target_claims"
    else:
        for candidate in candidates:
            for claim in candidate["review"]["claims"]:
                for binding in claim.get("answer_bindings", []):
                    if normalized_question(binding["question"]) == normalized_question(question):
                        targets[target_key(binding["target_claim"])] = binding["target_claim"]
        normalized = any(c.get("resolved_task") and c["exact_reviewed_question"] for c in candidates)
        origin = "normalized_claim_task" if normalized else "exact_reviewed_question_binding" if targets else "unresolved_free_text_search"
    judgments, selected = [], []
    for key, target in targets.items():
        matches, rejected = [], []
        for candidate in candidates:
            for claim in candidate["review"]["claims"]:
                for binding in claim.get("answer_bindings", []):
                    if target_key(binding["target_claim"]) != key:
                        continue
                    matched, reason = _context_match(binding.get("required_context", {}), context)
                    if not matched:
                        rejected.append(reason)
                        continue
                    matches.append((candidate, claim, binding))
        relations = {binding["relation"] for _, _, binding in matches}
        conflict = "supports" in relations and "refutes" in relations
        complete_qualification = matches and all(binding.get("answer_complete") is True for _, _, binding in matches)
        incomplete_target = any(binding.get("target_coverage_complete") is False for _, _, binding in matches)
        verdict = "conflicting_relations" if conflict else "incomplete_target_coverage" if incomplete_target else "qualified_only" if relations == {"qualifies"} and not complete_qualification else "supported_answer_relation" if matches else "no_reviewed_relation"
        judgments.append({"target_claim": target, "verdict": verdict, "relations": sorted(relations),
                          "excluded_reasons": rejected, "review_basis": "explicit_reviewed_claim_bindings_not_lexical_score"})
        if matches and not conflict:
            selected.extend(matches)
    complete = bool(judgments) and all(x["verdict"] == "supported_answer_relation" for x in judgments)
    conflict = any(x["verdict"] == "conflicting_relations" for x in judgments)
    all_selected = selected
    if displayed is not None:
        selected = [s for s in selected if (s[0]["theory_id"], s[0]["theory_version"]) in displayed]
    covered, uncovered = [], []
    # Legacy exact-question reviews explicitly bind the whole question. Core
    # semantic tasks bind individual requested parts; absent parts must stay in
    # the denominator even if no source claim exists for them.
    composition = supplied is None and (not targets or any(b.get("requested_part_ids") for _, _, b in all_selected))
    if composition:
        for part in required_parts:
            matches = [b for _, _, b in selected if part["part_id"] in b.get("requested_part_ids", [])
                       and b.get("answer_complete") is True and b.get("target_coverage_complete") is not False]
            if matches:
                covered.append(part)
            else:
                omitted = any(part["part_id"] in b.get("requested_part_ids", []) for _, _, b in all_selected)
                uncovered.append({**part, "reason": part.get("reason") or (
                    "display_budget_omitted_supported_part" if omitted else "no_eligible_complete_answer_relation")})
        complete = complete and bool(covered) and not uncovered
    # A display resource budget cannot turn an unseen supported target into a
    # complete rendered answer, including legacy explicitly reviewed targets.
    rendered_keys = {target_key(b["target_claim"]) for _, _, b in selected}
    complete = complete and all(target_key(x["target_claim"]) in rendered_keys for x in judgments)
    status = ("conflicting_evidence" if conflict else "evidence_supported" if complete
              else "partial_answer_support" if selected else "related_material_only" if candidates else "insufficient_evidence")
    return {"status": status, "target_resolution": origin, "targets": judgments,
            "covered_parts": covered, "uncovered_parts": uncovered,
            "independent_semantic_validation": "pending; reviewed bindings do not constitute independent human adjudication",
            "contract_sha256": digest(dumps(list(targets.values())).encode())}, selected
