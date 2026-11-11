"""Answer revisions preserve frozen answers and exact candidate dependencies."""

import copy

import pytest

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.core import POLICY, core_state


@pytest.fixture
def revisions(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    w.seed()
    w.seed_core()
    version = w.lib.record_version("S5", b"Synthetic revision fixture", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": "Synthetic source; not scientific evidence.", "locator": {"line": 1}}], "synthetic")
    spans = [version + ":s00000"]
    old = {"claim_id": "SYNTH-REVISION", "version": "1", "statement": "Synthetic old answer",
        "scope": {"population": "synthetic"}, "limitations": ["Synthetic only"],
        "evidence_links": [{"source_id": "S5", "source_version_id": version, "span_ids": spans}],
        "answer_task": {"subject": "resistance_training", "outcome": "progression_options", "requested_relation": "options",
                        "answer_parts": [{"text": "Synthetic old answer", "span_ids": spans}]}}
    review = {"reviewer": "Synthetic fixture", "reviewer_kind": "synthetic_fixture", "reviewed_at": "2026-11-11T00:00:00Z",
              "content_checked": True, "application_checked": True, "rationale": "Software version semantics only"}
    w.review_claim(old, review)
    rule = {"rule_id": "SYNTH-RULE", "rule_version": "1", "requested_capability": "plan_candidate",
            "capability_policy_version": POLICY["version"], "claim_refs": [{"claim_id": old["claim_id"], "version": "1"}],
            "conditions": [{"field": "age", "op": "range", "min": 18, "origin": "source_scope"}],
            "permitted_actions": ["double_progression"], "numeric_provenance": {"load": "equipment_constraint"},
            "application_logic": "Synthetic only", "limits": ["No real effects"], "exit_conditions": ["user stops"],
            "followup": "Synthetic observation", "implementation_validation_refs": ["tests/unit/test_answer_revision_selection.py"]}
    w.review_rule(rule, review)
    w.release_core("before")
    new = copy.deepcopy(old)
    new.update(version="2", answer_revision_of={"claim_id": old["claim_id"], "version": "1"})
    new["statement"] = new["answer_task"]["answer_parts"][0]["text"] = "Synthetic revised answer"
    yield w, old, new, review
    w.close()


def query(w, release_id=None):
    return w.query("训练进阶有哪些选项？", route="progression", release_id=release_id)


def test_current_answer_uses_revision_while_frozen_answer_and_candidate_keep_exact_old_ref(revisions):
    w, old, new, review = revisions
    w.review_claim(new, review)
    release = w.release_core("after")
    assert len(release["claims"]) == 2 and len(release["rules"]) == 1
    for selected in (None, "after"):
        answer = query(w, selected)
        assert answer["answer_status"] == "answered_with_support"
        assert {c["theory_version"] for c in answer["claims"]} == {"2"}
        principles = w.reviewed_principles("progression", {"age": 30}, selected)["principles"]
        assert len(principles) == 1
        assert principles[0]["claim_refs"][0]["version"] == "1"
    assert {c["theory_version"] for c in query(w, "before")["claims"]} == {"1"}
    assert w.lib.theories.execute("SELECT status FROM source_claim WHERE claim_id=? AND version='1'", (old["claim_id"],)).fetchone()[0] == "verified"


def test_revoked_revision_does_not_silently_restore_old_current_answer(revisions):
    w, _, new, review = revisions
    w.review_claim(new, review)
    w.release_core("after")
    core_state(w, "claim", new["claim_id"], "2", "revoked", actor="Synthetic fixture", rationale="Test revocation")
    assert not query(w)["claims"]
    assert not query(w, "after")["claims"]
    assert query(w, "before")["claims"]
    assert w.reviewed_principles("progression", {"age": 30})["principles"]


@pytest.mark.parametrize("change", ["other_claim", "missing_version", "same_version", "different_target"])
def test_revision_requires_an_existing_same_claim_and_same_answer_target(revisions, change):
    w, _, new, review = revisions
    if change == "other_claim":
        new["answer_revision_of"]["claim_id"] = "OTHER"
    elif change == "missing_version":
        new["answer_revision_of"]["version"] = "404"
    elif change == "same_version":
        new["answer_revision_of"]["version"] = "2"
    else:
        new["answer_task"]["outcome"] = "frequency"
    with pytest.raises(ValueError, match="answer revision"):
        w.review_claim(new, review)
