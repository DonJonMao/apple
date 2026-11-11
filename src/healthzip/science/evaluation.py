"""Denominator-explicit quality metrics; unknown adjudication never means pass."""

from __future__ import annotations

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from .contracts import Window, result


def ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None}


def sufficient_recall(case: dict) -> dict:
    retrieved = set(case.get("retrieved_unit_ids", []))
    groups = case.get("gold_groups", {})
    hits = {key: any(set(support) <= retrieved for support in alternatives)
            for key, alternatives in groups.items()}
    plans = []
    for index, bundle in enumerate(case.get("sufficient_bundles", [])):
        found = sum(hits.get(group, False) for group in bundle)
        plans.append({"bundle_id": index, "hits": found, "required": len(bundle),
                      "recall": found / len(bundle) if bundle else None,
                      "complete": bool(bundle) and found == len(bundle)})
    eligible = [p for p in plans if p["required"]]
    best = max(eligible, key=lambda p: p["recall"]) if eligible else None
    return {"query_id": case.get("query_id"), "group_hits": hits, "bundles": plans,
            "group_recall": best["recall"] if best else None,
            "best_bundle_id": best["bundle_id"] if best else None,
            "sufficient_bundle_hit": any(p["complete"] for p in eligible) if eligible else None}


def quality_metric(metric_id: str, rows: list[dict], window: Window, context: dict) -> dict:
    code = int(metric_id.split("-")[1])
    def emit(value, count=0, valid=None, reasons=None):
        return result(metric_id, window, value, data_status="valid" if count else "insufficient",
                      evidence_status="definition_based", valid_n=count if valid is None else valid,
                      total_n=count, count_domain="evaluation_units", reasons=reasons or [])
    if code == 1:
        cases = context.get("retrieval_cases", [])
        cases = [c for c in cases if c.get("gold_review_status") == "approved"]
        values = [sufficient_recall(c) for c in cases]
        judged = [v for v in values if v["group_recall"] is not None]
        return emit({"queries": values,
                     "macro_group_recall": sum(v["group_recall"] for v in judged) / len(judged) if judged else None,
                     "bundle_hit": ratio(sum(v["sufficient_bundle_hit"] for v in judged), len(judged)),
                     "unreviewed_gold_cases": len(context.get("retrieval_cases", [])) - len(cases)}, len(values),
                    reasons=["finite_retrieval_budget_required", "gold_review_separate_from_model_output"])
    if code == 2:
        cases = context.get("retrieval_precision_cases", [])
        values = []
        for case in cases:
            raw = case.get("units", [])
            unique = {u["unit_id"]: u for u in raw}
            labels = Counter(u.get("relevance", "unjudged") for u in unique.values())
            n = len(unique)
            values.append({"query_id": case.get("query_id"), "counts": dict(labels),
                           "precision_lower": ratio(labels["relevant"], n),
                           "precision_upper": ratio(labels["relevant"] + labels["unjudged"], n),
                           "judgment_coverage": ratio(n - labels["unjudged"], n),
                           "duplicate_fraction": ratio(len(raw) - n, len(raw))})
        den = sum(v["precision_lower"]["denominator"] for v in values)
        num = sum(v["precision_lower"]["numerator"] for v in values)
        scored = [v["precision_lower"]["rate"] for v in values if v["precision_lower"]["rate"] is not None]
        return emit({"queries": values, "micro_precision_lower": ratio(num, den),
                     "macro_precision_lower": sum(scored) / len(scored) if scored else None}, len(cases))
    if code == 3:
        raw_citations = context.get("citations", [])
        citations = list({(c.get("claim_id"), c.get("source_version_id"), tuple(c.get("span_ids", []))): c
                          for c in raw_citations}.values())
        locatable = [c for c in citations if c.get("span_ids") and c.get("hash_verified") and c.get("locator_in_bounds") and c.get("version_resolved")]
        judged = [c for c in citations if c.get("support_label") in {"supported", "partial", "contradicts", "irrelevant", "unverifiable"}]
        return emit({"rendered_citation_count": len(raw_citations), "unique_citation_associations": len(citations),
                     "location_rate": ratio(len(locatable), len(citations)),
                     "support_precision": ratio(sum(c.get("support_label") == "supported" for c in judged), len(judged)),
                     "judgment_coverage": ratio(len(judged), len(citations)),
                     "support_labels": dict(Counter(c.get("support_label", "unjudged") for c in citations))}, len(citations))
    if code == 4:
        claims = [c for c in context.get("claims", []) if c.get("requires_support")]
        supported = [c for c in claims if c.get("support_label") == "supported" and c.get("provenance_verified")]
        unknown = sum(c.get("support_label", "unjudged") == "unjudged" for c in claims)
        return emit({"claim_support": ratio(len(supported), len(claims)),
                     "claim_support_kind": "observed_lower_bound" if unknown else "fully_judged",
                     "claim_support_upper_bound": ratio(len(supported) + unknown, len(claims)),
                     "reviewer_denominators": dict(Counter(c.get("reviewer_kind", "controlled_fixture_or_unspecified") for c in claims)),
                     "independent_answer_reviews": dict(Counter(a.get("reviewer_kind", "unjudged") for a in context.get("semantic_adjudications", []) if a.get("accepted"))),
                     "labels": dict(Counter(c.get("support_label", "unjudged") for c in claims)),
                     "intent_coverage": context.get("intent_coverage")}, len(claims))
    if code == 5:
        claims = [c for c in context.get("claims", []) if c.get("applicability_required")]
        errors = [c for c in claims if c.get("applicability_errors")]
        unjudged = sum(c.get("applicability_review") != "completed" for c in claims)
        unknown_without_observed_error = sum(c.get("applicability_review") != "completed" and not c.get("applicability_errors") for c in claims)
        return emit({"applicability_error_rate": ratio(len(errors), len(claims)), "unjudged": unjudged,
                     "error_rate_kind": "observed_lower_bound" if unjudged else "fully_judged",
                     "error_rate_upper_bound": ratio(len(errors) + unknown_without_observed_error, len(claims)),
                     "error_types": dict(Counter(reason for c in errors for reason in c["applicability_errors"]))}, len(claims),
                    reasons=["unknown_is_not_scope_match"])
    if code == 6:
        claims = context.get("claims", [])
        numeric = [c for c in claims if c.get("claim_type") == "numeric"]
        causal = [c for c in claims if c.get("claim_type") == "causal"]
        bad_numeric = [c for c in numeric if c.get("numeric_support") == "unsupported"]
        bad_causal = [c for c in causal if c.get("causal_support") == "unsupported"]
        return emit({"unsupported_numeric": ratio(len(bad_numeric), len(numeric)),
                     "causal_overreach": ratio(len(bad_causal), len(causal)),
                     "unjudged_numeric": sum(c.get("numeric_support") not in {"supported", "unsupported"} for c in numeric),
                     "unjudged_causal": sum(c.get("causal_support") not in {"supported", "unsupported"} for c in causal),
                     "any_violation_answer_count": len({c.get("answer_id") for c in bad_numeric + bad_causal})}, len(claims))
    if code == 7:
        intents = context.get("intents", [])
        answerable = [i for i in intents if i.get("evidence_state") == "sufficient"]
        insufficient = [i for i in intents if i.get("evidence_state") == "insufficient"]
        unscorable = [i for i in intents if i.get("label", "unscorable") == "unscorable"]
        return emit({"overanswer": ratio(sum(i.get("label") == "overanswer" for i in insufficient), len(insufficient)),
                     "underanswer": ratio(sum(i.get("label") == "underanswer" for i in answerable), len(answerable)),
                     "rate_kind": "observed_lower_bound" if unscorable else "fully_judged",
                     "overanswer_upper_bound": ratio(sum(i.get("label", "unscorable") in {"overanswer", "unscorable"} for i in insufficient), len(insufficient)),
                     "underanswer_upper_bound": ratio(sum(i.get("label", "unscorable") in {"underanswer", "unscorable"} for i in answerable), len(answerable)),
                     "unscorable_intents": len(unscorable),
                     "labels": dict(Counter(i.get("label", "unscorable") for i in intents)),
                     "answerable_intents": len(answerable), "insufficient_intents": len(insufficient)}, len(intents))
    if code == 8:
        requests = {r["request_id"]: r for r in context.get("requests", []) if r.get("eligible")}
        traced = [r for r in requests.values() if r.get("trace_complete")]
        fallback = [r for r in traced if r.get("fallback_events")]
        completable = [r for r in fallback if r.get("allowed_subtask_exists")]
        return emit({"fallback_requests": ratio(len(fallback), len(requests)),
                     "fallback_rate_kind": "exact_observed_trace" if len(traced) == len(requests) else "observed_lower_bound_incomplete_trace",
                     "fallback_upper_bound": ratio(len(fallback) + len(requests) - len(traced), len(requests)),
                     "trace_coverage": ratio(len(traced), len(requests)),
                     "fallback_completion": ratio(sum(r.get("fallback_completed") is True for r in completable), len(completable)),
                     "event_count": sum(len(r["fallback_events"]) for r in fallback),
                     "reason_request_counts": dict(Counter(reason for r in fallback for reason in {e["reason"] for e in r["fallback_events"]})),
                     "incident_clusters": len({r.get("service_incident_id") for r in fallback if r.get("service_incident_id")})}, len(requests))
    if code == 9:
        sources = context.get("acquisition_manifest", [])
        targets = [s for s in sources if s.get("target_material_type") == "fulltext"]
        def fetched(s):
            return s.get("fetch_status") == "fulltext_saved" and bool(s.get("raw_sha256")) and s.get("bytes", 0) > 0 and s.get("identity_review") == "verified" and s.get("rights_status") == "permitted"
        retrievable = [s for s in targets if s.get("rights_status") == "permitted" and s.get("retrievable")]
        cards = context.get("theory_manifest", [])
        reviewed = [c for c in cards if c.get("review_decision") in {"approved", "rejected"} and c.get("review_reason") and c.get("independent_reviewer")]
        ready = [c for c in cards if c.get("review_decision") == "approved" and c.get("evidence_links_valid") and c.get("rights_valid") and c.get("scope_valid") and c.get("validation_gate_passed")]
        claims = context.get("feature_claim_requirements", [])
        return emit({"overall_fulltext_acquisition": ratio(sum(bool(fetched(s)) for s in targets), len(targets)),
                     "content_review_completion": ratio(sum(bool(c.get("content_reviewed")) for c in cards), len(cards)),
                     "reviewer_kind_counts": dict(Counter(c.get("reviewer_kind") or "unknown" for c in cards)),
                     "licensed_retrievable_fetch": ratio(sum(bool(fetched(s)) for s in retrievable), len(retrievable)),
                     "theory_review_completion": ratio(len(reviewed), len(cards)), "theory_activation_ready": ratio(len(ready), len(cards)),
                     "feature_claim_coverage": ratio(sum(c.get("satisfied_by_active_card") is True for c in claims), len(claims)),
                     "source_states": dict(Counter(s.get("fetch_status", "not_fetched") for s in targets))}, len(sources) + len(cards) + len(claims))
    if code == 10:
        requests = context.get("access_requests", [])
        checked = [r for r in requests if r.get("trace_complete")]
        violations = [r for r in checked if r.get("actual_violations")]
        opportunities = [a for r in requests for a in r.get("authorization_opportunities", [])]
        return emit({"request_violation_rate": ratio(len(violations), len(requests)),
                     "decision_violation_rate": ratio(sum(a.get("violated") is True for a in opportunities), len(opportunities)),
                     "blocked_attempts": sum(r.get("blocked_attempts", 0) for r in checked),
                     "unverifiable_guard_gap": len(requests) - len(checked),
                     "attack_families": sorted({r["attack_family"] for r in requests if r.get("attack_family")}),
                     "release_gate_passed": bool(requests) and len(checked) == len(requests) and not violations}, len(requests))
    if code == 11:
        claims = context.get("numeric_claims", [])
        checked, issues = 0, []
        for claim in claims:
            expected = claim.get("reference")
            actual = claim.get("actual", {})
            if expected is None:
                issues.append({"id": claim.get("id"), "reason": "reference_unavailable"})
                continue
            checked += 1
            keys = ("unit", "load_basis", "formula_id", "formula_version", "direction", "window", "estimate_identity", "interval_kind")
            if any(expected.get(k) != actual.get(k) for k in keys):
                issues.append({"id": claim.get("id"), "reason": "semantic_mismatch"})
                continue
            if expected.get("value") is None or actual.get("value") is None:
                if expected.get("value") != actual.get("value"):
                    issues.append({"id": claim.get("id"), "reason": "unknown_changed_to_number"})
                continue
            places = claim.get("decimal_places")
            a, b = Decimal(str(actual["value"])), Decimal(str(expected["value"]))
            if places is not None:
                quantizer = Decimal(1).scaleb(-int(places))
                a, b = a.quantize(quantizer, rounding=ROUND_HALF_UP), b.quantize(quantizer, rounding=ROUND_HALF_UP)
            if a != b:
                issues.append({"id": claim.get("id"), "reason": "numeric_mismatch"})
        mismatched = sum(i["reason"] != "reference_unavailable" for i in issues)
        return emit({"numeric_consistency": ratio(checked - mismatched, checked),
                     "reference_coverage": ratio(checked, len(claims)), "issues": issues}, len(claims))
    if code == 12:
        sources = context.get("source_versions", [])
        active = [s for s in sources if s.get("active")]
        identity = [s for s in sources if s.get("identity_review") == "verified" and not s.get("identity_conflict")]
        compliant = [s for s in active if s in identity and s.get("rights_for_declared_use") is True and s.get("status_checked_at") and not s.get("retracted") and not s.get("correction_pending_review")]
        return emit({"identity_verified": ratio(len(identity), len(sources)), "active_material_compliance": ratio(len(compliant), len(active)),
                     "noncompliant_active_ids": [s.get("source_version_id") for s in active if s not in compliant],
                     "release_gate_passed": bool(sources) and len(active) == len(compliant)}, len(sources))
    raise ValueError("unknown_quality_metric")
