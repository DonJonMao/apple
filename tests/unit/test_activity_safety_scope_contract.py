"""Synthetic contract checks; source reading and independent assessment are separate."""

import copy
import importlib.util
from pathlib import Path

import pytest

from healthzip.knowledge import KnowledgeWorkbench

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("safety_review", ROOT / "tools/v14_review_activity_safety_scope.py")
SAFETY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAFETY)


@pytest.fixture
def safety_library(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    w.seed()
    w.seed_core()
    definition, contracts = SAFETY.explanation_contracts()
    version = w.lib.record_version(
        "CORE-US-HHS-PAG-2", b"Synthetic HHS scope", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": f"Synthetic HHS page region {i}; no scientific authority.",
          "locator": {"synthetic_page": i}} for i in range(13)], "synthetic-only")

    def bind(topic, claim):
        for part, original in zip(claim["answer_task"]["answer_parts"], topic["answer_parts"], strict=True):
            part["span_ids"] = [version + f":s{i:05d}" for i in original["span_indices"]]
        claim["evidence_links"][0].update(source_version_id=version,
            span_ids=sorted({sid for part in claim["answer_task"]["answer_parts"] for sid in part["span_ids"]}))

    for topic, claim, _ in contracts:
        bind(topic, claim)
    adult = next(c for c in SAFETY.TOPICS.explanation_contracts()[1] if c[0]["outcome"] == "adult_guideline_scope")
    bind(adult[0], adult[1])
    review = {"reviewer": "Synthetic software test", "reviewer_kind": "synthetic_fixture",
              "reviewed_at": "2026-11-11T00:00:00+00:00", "content_checked": True,
              "application_checked": True, "rationale": "Software authority and scope separation only."}
    yield w, definition, contracts, adult, review
    w.close()


def query_scope(w, outcome, release_id=None):
    return w.query("解释明确选择的来源范围。", route="strength", release_id=release_id,
                   context={"corpus_roles": ["core"], "question_contract": {
                       "subject": "physical_activity", "outcome": outcome, "requested_relation": "scope",
                       "user_confirmed": True}, "source_constraints": {"source_ids": ["CORE-US-HHS-PAG-2"]}})


def test_cross_chapter_scope_is_separate_and_keeps_its_qualification(safety_library):
    w, _, contracts, adult, review = safety_library
    for _, claim, rule in [adult, *contracts]:
        w.review_claim(claim, review)
        w.review_rule(rule, review)
    safety = query_scope(w, "activity_safety_scope")
    assert safety["answer_status"] == "answered_with_support"
    assert {c["theory_id"] for c in safety["claims"]} == {contracts[0][1]["claim_id"]}
    assert [c["evidence_relation"] for c in safety["claims"]] == ["supports", "qualifies"]
    assert not safety["numeric_actions"]
    adult_answer = query_scope(w, "adult_guideline_scope")
    assert adult_answer["answer_status"] == "answered_with_support"
    assert {c["theory_id"] for c in adult_answer["claims"]} == {adult[1]["claim_id"]}


def test_safety_scope_never_acquires_candidate_or_clinical_authority(safety_library):
    w, _, contracts, _, review = safety_library
    topic, claim, rule = contracts[0]
    w.review_claim(claim, review)
    w.review_rule(rule, review)
    assert w.core_status()["effective_explanation_rule_count"] == 1
    assert w.core_status()["effective_candidate_rule_count"] == 0
    assert claim["numeric"] is False
    assert not rule["permitted_actions"] and not rule["numeric_provenance"]
    assert "automatic_clinical_prescription" in rule["forbidden"]
    for route in topic["routes"]:
        assert not w.reviewed_principles(route, {"requested_capability": "source_explanation"})["principles"]
    with pytest.raises(ValueError, match="candidate requires"):
        w.review_rule({**rule, "rule_version": "invalid", "requested_capability": "trial_candidate"}, review)


def test_old_release_cannot_gain_new_safety_answer_and_new_release_is_idempotent(safety_library):
    w, definition, contracts, adult, review = safety_library
    w.review_claim(adult[1], review)
    w.review_rule(adult[2], review)
    previous = w.release_core(definition["previous_release_id"])
    release, _, previous_sha = SAFETY.TOPICS.activate(w, definition, contracts)
    assert previous_sha == previous["sha256"]
    for kind in ["claims", "rules"]:
        assert len(release[kind]) == len(previous[kind]) + 1
        assert all(row in release[kind] for row in previous[kind])
    assert SAFETY.TOPICS.activate(w, definition, contracts)[0] == release
    old_answer = query_scope(w, "activity_safety_scope", definition["previous_release_id"])
    assert old_answer["answer_status"] == "missing_answer_relation"
    assert not old_answer["claims"]
    assert query_scope(w, "activity_safety_scope", definition["release_id"])["answer_status"] == "answered_with_support"


def test_exact_source_binding_and_current_claim_remain_required(safety_library):
    w, _, contracts, _, review = safety_library
    _, claim, rule = contracts[0]
    wrong = copy.deepcopy(claim)
    wrong["evidence_links"][0]["source_id"] = "N1"
    with pytest.raises(ValueError, match="evidence version/source mismatch"):
        w.review_claim(wrong, review)
    w.review_claim(claim, review)
    w.review_rule(rule, review)
    w.core_state("claim", claim["claim_id"], claim["version"], "revoked",
                 actor="Synthetic test", rationale="Scope claim withdrawn")
    assert w.core_status()["effective_explanation_rule_count"] == 0
    assert not query_scope(w, "activity_safety_scope")["claims"]


def test_changed_hhs_source_bytes_are_rejected(safety_library):
    w, definition, contracts, _, _ = safety_library
    definition["sources"]["CORE-US-HHS-PAG-2"]["source_version_id"] = contracts[0][1]["evidence_links"][0]["source_version_id"]
    with pytest.raises(ValueError, match="reviewed source bytes changed"):
        SAFETY.TOPICS.verify_sources(w, definition)
