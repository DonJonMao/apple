"""Synthetic authority checks; actual N1 reading is a separate implementer review."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from healthzip.knowledge import KnowledgeWorkbench

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("n1_review", ROOT / "tools/v14_review_regression_covariance.py")
N1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(N1)


@pytest.fixture
def n1_library(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    w.seed()
    w.seed_core()
    definition, claim, rule = N1.explanation_contract()
    maximum = max(row["span_index"] for row in definition["reviewed_spans"])
    spans = [{"text": f"Synthetic method evidence line {i}; no scientific authority.",
              "locator": {"synthetic_line": i}} for i in range(maximum + 1)]
    version = w.lib.record_version("N1", b"Synthetic N1", "fulltext", {}, {},
                                  {"index_allowed": True, "license_id": "CC0"}, "matched", spans, "synthetic-only")
    for part, original in zip(claim["answer_task"]["answer_parts"], definition["answer_parts"], strict=True):
        part["span_ids"] = [version + f":s{i:05d}" for i in original["span_indices"]]
    claim["evidence_links"][0].update(source_version_id=version,
        span_ids=sorted({sid for part in claim["answer_task"]["answer_parts"] for sid in part["span_ids"]}))
    review = {"reviewer": "Synthetic software test", "reviewer_kind": "synthetic_fixture",
              "reviewed_at": "2026-11-11T00:00:00+00:00", "content_checked": True,
              "application_checked": True, "rationale": "Software authority checks only."}
    yield w, definition, claim, rule, review
    w.close()


def test_n1_scope_has_no_personal_model_or_candidate_authority(n1_library):
    w, definition, claim, rule, review = n1_library
    w.review_claim(claim, review)
    w.review_rule(rule, review)
    assert w.core_status()["effective_explanation_rule_count"] == 1
    assert w.core_status()["effective_candidate_rule_count"] == 0
    assert rule["permitted_actions"] == [] and rule["numeric_provenance"] == []
    assert claim["numeric"] is False
    assert claim["scope"]["individual_inference"] == "not_authorized"
    assert w.lib.source("N1")["manifest"]["corpus_roles"] == ["research"]
    assert tuple(claim["answer_task"][key] for key in ("subject", "outcome", "requested_relation")) == (
        "statistical_inference", "regression_covariance_scope", "scope")
    for route in definition["routes"]:
        assert not w.reviewed_principles(route, {"requested_capability": "source_explanation"})["principles"]
    with pytest.raises(ValueError, match="candidate requires"):
        w.review_rule({**rule, "rule_version": "invalid", "requested_capability": "trial_candidate"}, review)


def test_n1_evidence_retains_complete_contiguous_paragraphs_and_exact_source(n1_library):
    w, definition, claim, _, _ = n1_library
    groups = {group["group_id"]: group["span_indices"] for group in definition["reviewed_evidence_groups"]}
    for indices in groups.values():
        assert indices == list(range(min(indices), max(indices) + 1))
    for part, original in zip(claim["answer_task"]["answer_parts"], definition["answer_parts"], strict=True):
        assert set(original["span_indices"]) == {i for group in original["evidence_groups"] for i in groups[group]}
        assert all(w.lib.span(sid)["source_id"] == "N1" for sid in part["span_ids"])
    assert claim["answer_task"]["answer_parts"][-1]["evidence_relation"] == "qualifies"
    assert set(claim["answer_task"]["required_answer_parts"]) == {
        "model_and_covariance_assumptions", "hc_hac_distinction", "hac_configuration_scope", "finite_sample_and_personal_limits"}


def test_wrong_source_or_unbound_part_cannot_authorize_n1(n1_library):
    w, _, claim, _, review = n1_library
    wrong = copy.deepcopy(claim)
    wrong["evidence_links"][0]["source_id"] = "M2"
    with pytest.raises(ValueError, match="evidence version/source mismatch"):
        w.review_claim(wrong, review)
    missing = copy.deepcopy(claim)
    missing["answer_task"]["answer_parts"][0]["span_ids"] = ["missing:span"]
    with pytest.raises(ValueError, match="each answer part requires exact reviewed evidence"):
        w.review_claim(missing, review)


def test_release_preserves_previous_members_is_idempotent_and_respects_withdrawal(n1_library):
    w, definition, claim, rule, review = n1_library
    previous_claim = copy.deepcopy(claim)
    previous_claim.update(claim_id="SYNTHETIC-PREVIOUS-CLAIM", version="previous")
    w.review_claim(previous_claim, review)
    previous = w.release_core(definition["previous_release_id"])
    contracts = [(definition, claim, rule)]
    release, _, previous_sha = N1.TOPICS.activate(w, definition, contracts)
    assert len(release["claims"]) == 2 and len(release["rules"]) == 1
    assert all(row in release["claims"] for row in previous["claims"])
    assert previous_sha == previous["sha256"]
    assert N1.TOPICS.activate(w, definition, contracts)[0] == release
    row = w.lib.theories.execute("SELECT manifest_json,sha256 FROM core_release WHERE release_id=?",
                                (definition["previous_release_id"],)).fetchone()
    assert json.loads(row["manifest_json"])["claims"] == previous["claims"]
    assert row["sha256"] == previous_sha
    w.core_state("claim", claim["claim_id"], claim["version"], "revoked",
                 actor="Synthetic test", rationale="Withdrawal remains effective")
    assert w.core_status()["effective_explanation_rule_count"] == 0
    assert N1.TOPICS.HHS.existing_or_create_release(w, definition["release_id"]) == release
    with pytest.raises(ValueError, match="claim_missing_or_not_current"):
        w.review_rule({**rule, "rule_version": "after-withdrawal"}, review)


def test_changed_n1_source_bytes_are_rejected(n1_library):
    w, definition, claim, _, _ = n1_library
    definition["source_version_id"] = claim["evidence_links"][0]["source_version_id"]
    with pytest.raises(ValueError, match="reviewed N1 PDF bytes changed"):
        N1.verify_source(w, definition)


def test_rendered_n1_answer_preserves_the_reviewed_qualifier_relation(n1_library):
    w, _, claim, rule, review = n1_library
    w.review_claim(claim, review)
    w.review_rule(rule, review)
    result = w.query("What is the difference between HC and HAC standard errors?", "plateau")
    assert result["answer_status"] == "answered_with_support"
    assert [part["evidence_relation"] for part in result["claims"]] == ["supports", "supports", "supports", "qualifies"]
    assert not result["numeric_actions"]
    personal = w.query("Choose the HAC bandwidth for my training data.", "plateau")
    assert personal["answer_status"] == "partially_answered"
    assert "statistical_calculation" in {part["part_id"] for part in personal["support_assessment"]["uncovered_parts"]}
    core_only = w.query("What is the difference between HC and HAC standard errors?", "plateau", context={"corpus_roles": ["core"]})
    assert not core_only["claims"]


@pytest.mark.parametrize("where", ["task", "part"])
def test_unknown_evidence_relation_is_rejected_before_claim_publication(n1_library, where):
    w, _, claim, _, review = n1_library
    invalid = copy.deepcopy(claim)
    target = invalid["answer_task"] if where == "task" else invalid["answer_task"]["answer_parts"][0]
    target["evidence_relation"] = "unknown_relation"
    with pytest.raises(ValueError, match="evidence relation"):
        w.review_claim(invalid, review)
