"""Executable accounting cases, not substitute human semantic adjudication.

The provided labels are controlled synthetic ground truth. These tests verify
denominators and gates; corpus relevance/support judgments remain separate work.
"""

import copy
import json
from pathlib import Path

import pytest

from healthzip.science import evaluate

CATALOG = Path(__file__).resolve().parents[2] / "specs/v1.3/Codex_Execution_Pack_v1.3/metric_acceptance_catalog.json"
CASES = [c for c in json.loads(CATALOG.read_text())["cases"] if c["metric_id"].startswith("QAL-")]


def metric(identity, context):
    return evaluate(identity, [], cutoff_time="2026-11-11T00:00:00+00:00",
                    window_start="2026-11-01T00:00:00+00:00", window_end="2026-11-12T00:00:00+00:00", context=context)["value"]


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_quality_catalog_accounting(case):
    identity = case["metric_id"]
    code = int(identity.split("-")[1])
    number = int(case["case_id"].rsplit("T", 1)[1])
    if code == 1:
        item = {"query_id": "synthetic", "gold_review_status": "approved", "gold_version": "fixture-1",
                "gold_groups": {"A": [["a"]], "B": [["b"]], "C": [["c"]]},
                "sufficient_bundles": [["A", "B"], ["C"]], "retrieved_unit_ids": ["c"]}
        expected = 1
        if number == 2:
            item.update(sufficient_bundles=[["A", "B"]], retrieved_unit_ids=["a"] * 10)
            expected = .5
        elif number == 3:
            item.update(gold_groups={"XY": [["x", "y"]]}, sufficient_bundles=[["XY"]], retrieved_unit_ids=["x"] * 5)
            expected = 0
        elif number == 4:
            item["retrieved_unit_ids"] = []
            expected = 0
        output = metric(identity, {"retrieval_cases": [item]})
        assert output["macro_group_recall"] == expected
        assert output["queries"][0]["sufficient_bundle_hit"] == (expected == 1)
        if number == 4:
            item["sufficient_bundles"] = []
            assert metric(identity, {"retrieval_cases": [item]})["macro_group_recall"] is None
        if number == 5:
            before = copy.deepcopy(item)
            before["sufficient_bundles"] = [["A", "B"]]
            assert metric(identity, {"retrieval_cases": [before]})["macro_group_recall"] == 0
            item["gold_version"] = "fixture-2"
            output = metric(identity, {"retrieval_cases": [item, {**item, "query_id": "second-system"}]})
            assert len(output["queries"]) == 2 and all(q["group_recall"] == 1 for q in output["queries"])
    elif code == 2:
        units = [{"unit_id": "A", "relevance": "relevant"}] * 3 + [{"unit_id": "B", "relevance": "irrelevant"}]
        if number == 2:
            units = []
        elif number == 3:
            units = [{"unit_id": "refutation", "relevance": "relevant", "direction": "contradicts_preference"}]
        elif number == 4:
            units = [{"unit_id": str(i), "relevance": label} for i, label in enumerate(["relevant", "relevant", "irrelevant", "unjudged"])]
        output = metric(identity, {"retrieval_precision_cases": [{"query_id": "q", "units": units}]})["queries"][0]
        if number == 1:
            assert output["precision_lower"]["rate"] == .5 and output["duplicate_fraction"]["rate"] == .5
        elif number == 2:
            assert output["precision_lower"]["rate"] is None
        elif number == 3:
            assert output["precision_lower"]["rate"] == 1
        else:
            assert output["precision_lower"]["rate"] == .5 and output["precision_upper"]["rate"] == .75
    elif code == 3:
        citation = {"claim_id": "c1", "source_version_id": "s-v1", "span_ids": ["s1"], "hash_verified": True,
                    "locator_in_bounds": True, "version_resolved": True, "support_label": "supported"}
        citations = [citation]
        if number == 1:
            citation["span_ids"] = []
        elif number == 2:
            citation["support_label"] = "contradicts"
        elif number == 3:
            citations *= 3
        elif number == 4:
            citations = []
        elif number == 5:
            citation["span_ids"] = ["s1", "s2"]
        output = metric(identity, {"citations": citations})
        if number == 1:
            assert output["location_rate"]["rate"] == 0
        elif number == 2:
            assert output["location_rate"]["rate"] == 1 and output["support_precision"]["rate"] == 0
        elif number == 3:
            assert output["unique_citation_associations"] == 1 and output["rendered_citation_count"] == 3
        elif number == 4:
            assert output["location_rate"]["rate"] is None
            claims = [{"requires_support": True, "support_label": "unverifiable"} for _ in range(5)]
            assert metric("QAL-04", {"claims": claims})["claim_support"]["denominator"] == 5
        else:
            assert output["support_precision"]["rate"] == 1
    elif code == 4:
        claims = [{"requires_support": True, "support_label": "supported", "provenance_verified": True,
                   "provenance_kind": "record_and_calculation"}]
        if number == 2:
            claims[0]["support_label"] = "partial"
        elif number == 3:
            claims += [{"requires_support": True, "support_label": "contradicts", "claim_type": "prescription"}]
        elif number == 4:
            claims = []
        elif number == 5:
            claims[0]["recognized_evidence_bundles"] = [["A", "B"], ["C"]]
        output = metric(identity, {"claims": claims})
        assert output["claim_support"]["rate"] == {1: 1, 2: 0, 3: .5, 4: None, 5: 1}[number]
        if number == 4:
            out = metric("QAL-07", {"intents": [{"evidence_state": "sufficient", "label": "underanswer"}]})
            assert out["underanswer"]["rate"] == 1
    elif code == 5:
        reasons = {1: ["metric_identity", "protocol"], 2: [], 3: ["exercise_equipment"], 4: ["population", "protocol"]}[number]
        output = metric(identity, {"claims": [{"applicability_required": True, "applicability_review": "completed", "applicability_errors": reasons}]})
        assert output["applicability_error_rate"]["numerator"] == int(bool(reasons))
        assert sum(output["error_types"].values()) == len(reasons)
    elif code == 6:
        kind = "causal" if number == 4 else "numeric"
        label = "supported" if number in {2, 5} else "unsupported"
        claim = {"answer_id": "a", "claim_type": kind, kind + "_support": label,
                 "meaning": {1: "readiness factor 0.95", 2: "equipment-based trial, not guaranteed", 3: "population error as individual interval", 4: "adoption proves causality", 5: "user-entered rep target"}[number]}
        output = metric(identity, {"claims": [claim]})
        assert output["any_violation_answer_count"] == int(label == "unsupported")
        assert output["causal_overreach" if kind == "causal" else "unsupported_numeric"]["numerator"] == int(label == "unsupported")
    elif code == 7:
        intents = [{"evidence_state": "insufficient", "label": "overanswer"}]
        if number == 2:
            intents = [{"evidence_state": "sufficient", "label": "underanswer"}]
        elif number == 3:
            intents = [{"evidence_state": state, "label": "correct_boundary"} for state in ("sufficient", "insufficient")]
        elif number == 5:
            intents = [{"evidence_state": "insufficient", "label": "other_task_failure"}]
        output = metric(identity, {"intents": intents})
        if number in {1, 4}:
            assert output["overanswer"]["rate"] == 1 and output["underanswer"]["rate"] is None
        elif number == 2:
            assert output["underanswer"]["rate"] == 1
        elif number == 3:
            assert output["labels"]["correct_boundary"] == 2
        else:
            assert output["labels"]["other_task_failure"] == 1
    elif code == 8:
        request = {"request_id": "r", "eligible": True, "trace_complete": True, "allowed_subtask_exists": True,
                   "fallback_events": [{"reason": "timeout"}, {"reason": "provider_error"}], "fallback_completed": True}
        requests = [request]
        if number == 2:
            request["fallback_events"] = [{"reason": "calculation_not_validated"}]
        elif number == 3:
            requests = [{**request, "request_id": str(i), "service_incident_id": "one-outage"} for i in range(100)]
        elif number == 4:
            requests = [{**request, "request_id": str(i), "trace_complete": i < 8} for i in range(10)]
        output = metric(identity, {"requests": requests})
        if number == 1:
            assert output["fallback_requests"]["numerator"] == 1 and output["event_count"] == 2
        elif number == 2:
            assert output["reason_request_counts"] == {"calculation_not_validated": 1}
        elif number == 3:
            assert output["incident_clusters"] == 1
        else:
            assert output["trace_coverage"]["rate"] == .8
    elif code == 9:
        context = {}
        if number in {1, 4, 5}:
            sources = [{"target_material_type": "fulltext", "fetch_status": "fulltext_saved" if i < 18 else "not_fetched",
                        "rights_status": "permitted" if i < 20 else "unknown", "retrievable": i < 20,
                        "raw_sha256": "test-bytes-hash" if i < 18 else None, "bytes": 100 if i < 18 else 0,
                        "identity_review": "verified"} for i in range(29)]
            if number in {4, 5}:
                for source in sources:
                    source["fetch_status"] = "abstract_only" if number == 4 else "not_fetched"
            context["acquisition_manifest"] = sources
        elif number == 2:
            context["theory_manifest"] = [{"review_decision": "approved" if i < 3 else "rejected" if i < 5 else "pending",
                                            "review_reason": "synthetic review", "independent_reviewer": "fixture-reviewer",
                                            "evidence_links_valid": True, "rights_valid": True, "scope_valid": True, "validation_gate_passed": True} for i in range(10)]
        else:
            context["feature_claim_requirements"] = [{"satisfied_by_active_card": i < 6} for i in range(10)]
            context["theory_manifest"] = [{"review_decision": "pending"} for _ in range(100)]
        output = metric(identity, context)
        if number == 1:
            assert output["overall_fulltext_acquisition"]["rate"] == 18 / 29
            assert output["licensed_retrievable_fetch"]["rate"] == 18 / 20
        elif number == 2:
            assert output["theory_review_completion"]["rate"] == .5 and output["theory_activation_ready"]["rate"] == .3
        elif number == 3:
            assert output["feature_claim_coverage"]["rate"] == .6
        else:
            assert output["overall_fulltext_acquisition"]["numerator"] == 0
    elif code == 10:
        request = {"request_id": "r", "trace_complete": True, "actual_violations": ["private_read_wrong_owner"] if number == 1 else [],
                   "blocked_attempts": 1 if number in {2, 4, 5} else 0,
                   "authorization_opportunities": [{"violated": number == 1}], "attack_family": "cross-owner"}
        requests = [request] if number != 5 else [{**request, "request_id": str(i)} for i in range(1000)]
        output = metric(identity, {"access_requests": requests})
        assert output["release_gate_passed"] == (number != 1)
        if number == 5:
            assert output["attack_families"] == ["cross-owner"]
        elif number == 4:
            assert output["blocked_attempts"] == 1 and output["request_violation_rate"]["numerator"] == 0
    elif code == 11:
        expected = {"value": 1800, "unit": "kg*reps"}
        actual = dict(expected)
        places = None
        if number == 1:
            actual["unit"] = "joules"
        elif number == 2:
            expected = {"value": 5, "unit": "kg", "load_basis": "plates_total"}
            actual = dict(expected)
        elif number == 3:
            expected = {"value": 79.98, "unit": "kg", "formula_id": "epley_n3_0.0333"}
            actual = {"value": 80, "unit": "kg", "formula_id": "epley_r_over_30"}
        elif number == 4:
            expected, actual, places = {"value": 79.98}, {"value": 80.0}, 1
        else:
            expected = {"value": 3.2, "estimate_identity": "group_mean"}
            actual = {"value": 3.2, "estimate_identity": "personal_95_percent_half_width"}
        output = metric(identity, {"numeric_claims": [{"id": "c", "reference": expected, "actual": actual, "decimal_places": places}]})
        assert output["numeric_consistency"]["rate"] == (1 if number in {2, 4} else 0)
    elif code == 12:
        source = {"source_version_id": "source-v1", "identity_review": "verified", "active": True,
                  "rights_for_declared_use": True, "status_checked_at": "2026-11-01", "retracted": False}
        sources = [source]
        if number == 1:
            source["identity_conflict"] = True
        elif number == 2:
            source["rights_for_declared_use"] = False
        elif number == 3:
            source["retracted"] = True
        elif number == 4:
            sources.append({**source, "source_version_id": "source-accepted-v2"})
        elif number == 5:
            source["update_relation"] = "superseded_by_2026_guideline"
        else:
            sources = [{**source, "source_version_id": str(i)} for i in range(1000)] + [{**source, "source_version_id": "unauthorized", "rights_for_declared_use": False}]
        output = metric(identity, {"source_versions": sources})
        assert output["release_gate_passed"] == (number in {4, 5})
        if number == 4:
            assert output["identity_verified"]["denominator"] == 2
        if number == 6:
            assert output["noncompliant_active_ids"] == ["unauthorized"]
