"""Bounded rule-policy tests; fixtures do not grant real scientific authority."""

import json
from pathlib import Path

import pytest

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.core import POLICY, RECORD_POLICY


@pytest.fixture
def library(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    w.seed()
    yield w
    w.close()


def record_rule(capability="description"):
    return {"rule_id": "SYNTH-RECORD", "rule_version": "1", "requested_capability": capability,
        "capability_policy_version": RECORD_POLICY["version"], "evidence_basis": "product_record_contract",
        "record_contract": {"executor": "synthetic exact record count", "missing_policy": "unknown_not_zero"},
        "conditions": [{"field": "as_of", "op": "present", "origin": "measurement_contract"}],
        "claim_refs": [], "permitted_actions": [], "application_logic": "Count explicit synthetic records only.",
        "limits": ["No empirical scientific authority or candidate permissions."],
        "implementation_validation_refs": ["tests/unit/test_v14_knowledge_coverage.py"]}


def review():
    return {"reviewer": "Synthetic record fixture", "reviewer_kind": "synthetic_fixture",
        "reviewed_at": "2026-11-11T00:00:00Z", "rationale": "Software policy test only", "application_checked": True}


def test_record_policy_does_not_require_unread_scientific_claim_or_grant_actions(library):
    rule = record_rule()
    library.review_rule(rule, review())
    status = library.core_status()
    assert status["effective_record_rule_count"] == 1
    assert status["effective_candidate_rule_count"] == 0
    assert not library.reviewed_principles("progression", {"as_of": "2026-11-11"})["principles"]
    release = library.release_core("synthetic-record-release")
    assert RECORD_POLICY["version"] in release["additional_policies"]
    for patch in ({"permitted_actions": ["double_progression"]}, {"requested_capability": "trial_candidate"}, {"record_contract": {}}):
        with pytest.raises(ValueError):
            library.review_rule({**rule, "rule_version": "2", **patch}, review())


def test_explanation_rule_never_becomes_candidate_authority(library):
    raw = b"Synthetic source explains a scope only."
    version = library.lib.record_version("S5", raw, "fulltext", {}, {}, {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": raw.decode(), "locator": {"synthetic_line": 1}}], "synthetic-only")
    claim = {"claim_id": "SYNTH-SCOPE", "version": "1", "statement": raw.decode(), "scope": {"population": "synthetic"},
        "limitations": ["Synthetic only"], "evidence_links": [{"source_id": "S5", "source_version_id": version, "span_ids": [version + ":s00000"]}]}
    library.review_claim(claim, {**review(), "content_checked": True})
    rule = {**record_rule(), "rule_id": "SYNTH-EXPLANATION", "requested_capability": "source_explanation",
        "capability_policy_version": POLICY["version"], "claim_refs": [{"claim_id": "SYNTH-SCOPE", "version": "1"}]}
    library.review_rule(rule, review())
    assert library.core_status()["effective_explanation_rule_count"] == 1
    assert not library.reviewed_principles("progression", {"as_of": "2026-11-11"})["principles"]
    library.core_state("claim", "SYNTH-SCOPE", "1", "revoked", actor="Synthetic reviewer", rationale="Synthetic withdrawal")
    assert library.core_status()["effective_explanation_rule_count"] == 0


def test_record_policy_cannot_be_declared_under_scientific_trial_policy(library):
    with pytest.raises(ValueError, match="unsupported capability"):
        library.review_rule({**record_rule(), "capability_policy_version": POLICY["version"]}, review())
    library.environment_kind = "production"
    with pytest.raises(ValueError, match="synthetic_rule_not_production_authority"):
        library.review_rule(record_rule(), review())


def test_extension_claims_are_bound_to_exact_read_versions_and_individual_parts():
    value = json.loads((Path(__file__).parents[2] / "src/healthzip/knowledge/data/core_extension.json").read_text())
    assert len(value["claims"]) == 11
    for claim in value["claims"]:
        assert len(claim["answer_parts"]) >= 2
        for source, spans in claim["source_spans"].items():
            assert source in value["sources"] and spans
            assert len(value["sources"][source]["sha256"]) == 64
        for part in claim["answer_parts"]:
            for source, spans in part.get("source_spans", claim["source_spans"]).items():
                assert set(spans) <= set(claim["source_spans"][source])
