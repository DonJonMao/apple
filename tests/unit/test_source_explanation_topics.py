"""Synthetic authority/lifecycle tests, separate from actual source-content review."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from healthzip.knowledge import KnowledgeWorkbench

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("topic_review", ROOT / "tools/v14_expand_source_explanations.py")
TOPICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOPICS)


@pytest.fixture
def topic_library(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    w.seed()
    w.seed_core()
    definition, contracts = TOPICS.explanation_contracts()
    versions = {}
    for source_id, source in definition["sources"].items():
        maximum = max(row["span_index"] for row in source["reviewed_spans"])
        spans = [{"kind": "table" if source_id == "S1" and i == 13 else "paragraph",
                  "text": f"Synthetic {source_id} evidence region {i}; no scientific authority.",
                  "locator": {"synthetic_region": i}, "structured": {"numeric_review_status": "pending"}}
                 for i in range(maximum + 1)]
        versions[source_id] = w.lib.record_version(
            source_id, ("Synthetic " + source_id).encode(), "fulltext", {}, {},
            {"index_allowed": True, "license_id": "CC0"}, "matched", spans, "synthetic-only")
    for topic, claim, rule in contracts:
        version = versions[topic["source_id"]]
        for part, original in zip(claim["answer_task"]["answer_parts"], topic["answer_parts"]):
            part["span_ids"] = [version + f":s{i:05d}" for i in original["span_indices"]]
        claim["evidence_links"][0].update(source_version_id=version,
            span_ids=sorted({sid for part in claim["answer_task"]["answer_parts"] for sid in part["span_ids"]}))
    review = {"reviewer": "Synthetic software check", "reviewer_kind": "synthetic_fixture",
              "reviewed_at": "2026-11-11T00:00:00+00:00", "content_checked": True,
              "application_checked": True, "rationale": "Software behavior only; not content validation."}
    yield w, definition, contracts, review
    w.close()


@pytest.mark.parametrize("index", range(9))
def test_each_topic_is_explanation_only_without_candidate_actions(topic_library, index):
    w, _, contracts, review = topic_library
    topic, claim, rule = contracts[index]
    w.review_claim(claim, review)
    w.review_rule(rule, review)
    assert w.core_status()["effective_explanation_rule_count"] == 1
    assert w.core_status()["effective_candidate_rule_count"] == 0
    for route in topic["routes"]:
        assert not w.reviewed_principles(route, {"requested_capability": "source_explanation"})["principles"]
    elevated = {**rule, "rule_version": "invalid", "requested_capability": "trial_candidate"}
    with pytest.raises(ValueError, match="candidate requires"):
        w.review_rule(elevated, review)


def test_separate_topics_retain_source_identity_and_corpus_partition(topic_library):
    w, _, contracts, _ = topic_library
    tasks = {(c["answer_task"]["subject"], c["answer_task"]["outcome"], c["answer_task"]["requested_relation"])
             for _, c, _ in contracts}
    assert len(tasks) == 9
    assert {task[1] for task in tasks}.isdisjoint({"practical_equivalence", "gradual_progression", "failure_necessity"})
    for topic, claim, _ in contracts:
        link = claim["evidence_links"][0]
        assert link["source_id"] == topic["source_id"]
        assert all(w.lib.span(sid)["source_id"] == topic["source_id"]
                   for part in claim["answer_task"]["answer_parts"] for sid in part["span_ids"])
    assert w.lib.source("M2")["manifest"]["corpus_roles"] == ["research"]
    assert w.lib.source("CORE-US-HHS-PAG-2")["manifest"]["corpus_roles"] == ["core"]


def test_wrong_source_and_unreviewed_part_cannot_authorize_topic(topic_library):
    w, _, contracts, review = topic_library
    claim = copy.deepcopy(contracts[0][1])
    claim["evidence_links"][0]["source_id"] = "S1"
    with pytest.raises(ValueError, match="evidence version/source mismatch"):
        w.review_claim(claim, review)
    claim = copy.deepcopy(contracts[0][1])
    claim["answer_task"]["answer_parts"][0]["span_ids"] = contracts[-1][1]["evidence_links"][0]["span_ids"]
    with pytest.raises(ValueError, match="each answer part requires exact reviewed evidence"):
        w.review_claim(claim, review)


def test_definition_table_does_not_acquire_numeric_parameter_authority(topic_library):
    w, _, contracts, review = topic_library
    claim = copy.deepcopy(contracts[-1][1])
    w.review_claim(claim, review)
    claim["version"] = "numeric-promotion"
    claim["numeric"] = True
    with pytest.raises(ValueError, match="table cells/units/footnotes require complete numeric review"):
        w.review_claim(claim, review)


def test_activation_is_additive_immutable_and_idempotent(topic_library):
    w, definition, contracts, review = topic_library
    old_claim = copy.deepcopy(contracts[0][1])
    old_claim.update(claim_id="SYNTHETIC-PREVIOUS-CLAIM", version="previous")
    w.review_claim(old_claim, review)
    previous = w.release_core(definition["previous_release_id"])
    first, _, previous_sha = TOPICS.activate(w, definition, contracts)
    assert previous_sha == previous["sha256"]
    assert len(first["claims"]) == 10 and len(first["rules"]) == 9
    assert all(item in first["claims"] for item in previous["claims"])
    assert TOPICS.activate(w, definition, contracts)[0] == first
    stored = w.lib.theories.execute("SELECT manifest_json,sha256 FROM core_release WHERE release_id=?",
                                   (definition["previous_release_id"],)).fetchone()
    assert json.loads(stored["manifest_json"])["claims"] == previous["claims"]
    assert stored["sha256"] == previous["sha256"]
    claim = contracts[0][1]
    w.core_state("claim", claim["claim_id"], claim["version"], "revoked",
                 actor="Synthetic test", rationale="Withdrawal must remain effective")
    assert w.core_status()["effective_explanation_rule_count"] == 8
    assert TOPICS.HHS.existing_or_create_release(w, definition["release_id"]) == first
    with pytest.raises(ValueError, match="claim_missing_or_not_current"):
        w.review_rule({**contracts[0][2], "rule_version": "after-withdrawal"}, review)


def test_changed_reviewed_source_bytes_are_rejected(topic_library):
    w, definition, contracts, _ = topic_library
    for topic, claim, _ in contracts:
        definition["sources"][topic["source_id"]]["source_version_id"] = claim["evidence_links"][0]["source_version_id"]
    with pytest.raises(ValueError, match="reviewed source bytes changed"):
        TOPICS.verify_sources(w, definition)
