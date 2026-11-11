"""Synthetic revision/lifecycle checks, separate from original source reading."""

import copy
import importlib.util
from pathlib import Path

import pytest

from healthzip.knowledge import KnowledgeWorkbench

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("refinements", ROOT / "tools/v14_refine_source_explanations.py")
REFINED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REFINED)


@pytest.fixture
def revised_library(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    w.seed()
    w.seed_core()
    data = REFINED.definition()
    versions = {}
    for source_id, maximum in [("CORE-US-HHS-PAG-2", 12), ("S1", 74)]:
        versions[source_id] = w.lib.record_version(
            source_id, ("Synthetic " + source_id).encode(), "fulltext", {}, {},
            {"index_allowed": True, "license_id": "CC0"}, "matched",
            [{"text": f"Synthetic evidence {source_id} {i}; no scientific authority.",
              "locator": {"chapter_id": "7" if i == 12 else "4", "synthetic_region": i}}
             for i in range(maximum + 1)], "synthetic-only")

    def bind(claim):
        source_id = claim["evidence_links"][0]["source_id"]
        version = versions[source_id]
        for part in claim["answer_task"]["answer_parts"]:
            part["span_ids"] = [version + ":s" + sid.rsplit(":s", 1)[1] for sid in part["span_ids"]]
        claim["evidence_links"][0].update(source_version_id=version,
            span_ids=sorted({sid for part in claim["answer_task"]["answer_parts"] for sid in part["span_ids"]}))

    safety_tool = REFINED.TOPICS._tool("v14_review_activity_safety_scope")
    _, safety_contracts = safety_tool.explanation_contracts()
    _, old_safety, safety_rule = safety_contracts[0]
    old_progression = copy.deepcopy(next(item["claim"] for item in data["claim_revisions"]
                                         if item["claim"]["claim_id"] == "CORE-CLAIM-PROGRESSION"))
    old_progression["version"] = "1.4.3"
    old_progression.pop("answer_revision_of")
    old_progression["statement"] = "Synthetic prior progression summary."
    old_progression["answer_task"]["answer_parts"] = [{
        "part_id": "progression_options", "text": old_progression["statement"],
        "span_ids": old_progression["evidence_links"][0]["span_ids"], "evidence_relation": "supports"}]
    old_progression["answer_task"]["required_answer_parts"] = ["progression_options"]
    review = {"reviewer": "Synthetic software test", "reviewer_kind": "synthetic_fixture",
              "reviewed_at": "2026-11-11T00:00:00+00:00", "content_checked": True,
              "application_checked": True, "rationale": "Software revision and dependency checks only."}
    for claim in [old_safety, old_progression]:
        bind(claim)
        w.review_claim(claim, review)
    w.review_rule(safety_rule, review)
    candidate = {"rule_id": "SYNTHETIC-FROZEN-CANDIDATE", "rule_version": "1.4.3",
                 "requested_capability": "trial_candidate", "capability_policy_version": "personal-trial-policy-1.4.0",
                 "claim_refs": [{"claim_id": old_progression["claim_id"], "version": "1.4.3"}],
                 "routes": ["strength"], "permitted_actions": ["repetition_trial"],
                 "numeric_provenance": [{"field": "target_reps", "origin": "user_plan"}],
                 "conditions": [{"field": "requested_capability", "op": "eq", "value": "trial_candidate",
                                 "origin": "product_scope"}], "application_logic": "Synthetic task from user plan.",
                 "limits": ["Synthetic authority test only."], "exit_conditions": ["Stop on task completion."],
                 "followup": {"record": "actual execution"}, "implementation_validation_refs": [__file__]}
    w.review_rule(candidate, review)
    previous = w.release_core(data["previous_release_id"])
    for item in data["claim_revisions"]:
        bind(item["claim"])
    yield w, data, previous, candidate
    w.close()


def selected_query(w, outcome, *, release_id=None, chapter=None):
    context = {"question_contract": {
        "subject": "physical_activity" if outcome == "activity_safety_scope" else "resistance_training",
        "outcome": outcome, "requested_relation": "scope" if outcome == "activity_safety_scope" else "options",
        "user_confirmed": True}, "corpus_roles": ["core"]}
    if chapter:
        context["source_constraints"] = {"source_ids": ["CORE-US-HHS-PAG-2"], "chapter_id": chapter}
    return w.query("解释明确选择的主题。", route="strength", context=context, release_id=release_id)


def test_complete_snapshot_retains_old_rows_and_candidate_dependencies(revised_library):
    w, data, previous, candidate = revised_library
    before = REFINED.TOPICS.HHS.snapshot(w)
    release, _, old_sha = REFINED.activate(w, data)
    assert old_sha == previous["sha256"]
    assert len(release["claims"]) == 4 and len({c["claim_id"] for c in release["claims"]}) == 2
    assert len(release["rules"]) == 3 and len({r["rule_id"] for r in release["rules"]}) == 2
    for kind in ["claims", "rules"]:
        assert all(row in release[kind] for row in previous[kind])
    after = REFINED.TOPICS.HHS.snapshot(w)
    assert all(row in after[table] for table, rows in before.items() for row in rows)
    principles = w.reviewed_principles("strength", {"requested_capability": "trial_candidate"})["principles"]
    assert len(principles) == 1
    assert principles[0]["rule_id"] == candidate["rule_id"]
    assert principles[0]["claim_refs"][0]["version"] == "1.4.3"
    assert REFINED.activate(w, data)[0] == release


def test_revised_safety_scope_answers_chapter_seven_without_chapter_four(revised_library):
    w, data, _, _ = revised_library
    REFINED.activate(w, data)
    current = selected_query(w, "activity_safety_scope", release_id=data["release_id"], chapter="7")
    assert current["answer_status"] == "answered_with_support"
    assert {c["theory_version"] for c in current["claims"]} == {"1.4.9"}
    assert [c["evidence_relation"] for c in current["claims"]] == ["supports", "qualifies"]
    assert all(sid.endswith(":s00012") for c in current["citations"] for sid in c["span_ids"])
    old = selected_query(w, "activity_safety_scope", release_id=data["previous_release_id"])
    assert {c["theory_version"] for c in old["claims"]} == {"1.4.8"}
    assert not current["numeric_actions"]


def test_progression_revision_changes_answers_without_changing_old_release(revised_library):
    w, data, _, _ = revised_library
    REFINED.activate(w, data)
    current = selected_query(w, "progression_options", release_id=data["release_id"])
    assert current["answer_status"] == "answered_with_support"
    assert {c["theory_version"] for c in current["claims"]} == {"1.4.9"}
    assert [c["evidence_relation"] for c in current["claims"]] == ["supports", "qualifies"]
    old = selected_query(w, "progression_options", release_id=data["previous_release_id"])
    assert {c["theory_version"] for c in old["claims"]} == {"1.4.3"}
    assert not current["numeric_actions"]


def test_revoking_revision_cannot_silently_restore_old_current_answer(revised_library):
    w, data, _, _ = revised_library
    REFINED.activate(w, data)
    w.core_state("claim", "CORE-CLAIM-PROGRESSION", "1.4.9", "revoked",
                 actor="Synthetic test", rationale="Revised answer withdrawn")
    assert not selected_query(w, "progression_options")["claims"]
    assert {c["theory_version"] for c in selected_query(
        w, "progression_options", release_id=data["previous_release_id"])["claims"]} == {"1.4.3"}
    assert w.core_status()["effective_candidate_rule_count"] == 1


def test_changed_original_source_bytes_reject_revision_review(revised_library):
    w, data, _, _ = revised_library
    for item in data["claim_revisions"]:
        link = item["claim"]["evidence_links"][0]
        data["sources"][link["source_id"]]["source_version_id"] = link["source_version_id"]
    with pytest.raises(ValueError, match="reviewed source bytes changed"):
        REFINED.verify_sources(w, data)
