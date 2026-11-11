"""Frozen query membership never overrides current evidence validity."""

import json

import pytest

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.tasks import core_candidates

QUESTION = "Synthetic repetition progression explanation"
CONTEXT = {"question_contract": {"subject": "resistance_training", "outcome": "progression",
                                 "requested_relation": "explanation"}}


@pytest.fixture
def library(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    w.seed()
    yield w
    w.close()


def source(w):
    raw = b"Synthetic repetition progression explanation; no scientific authority."
    version = w.lib.record_version(
        "S5", raw, "fulltext", {}, {}, {"index_allowed": True, "license_id": "CC0"},
        "matched", [{"text": raw.decode(), "locator": {"synthetic_line": 1}}], "synthetic-release")
    return {"source_id": "S5", "source_version_id": version, "span_ids": [version + ":s00000"]}


def add_core(w, claim_id="SYNTH-CORE", version="1"):
    link = source(w)
    claim = {"claim_id": claim_id, "version": version, "statement": QUESTION,
             "scope": {"population": "synthetic"}, "limitations": ["Synthetic fixture only"],
             "evidence_links": [link], "answer_task": {**CONTEXT["question_contract"],
                 "routes": ["progression"], "evidence_relation": "supports",
                 "answer_parts": [{"part_id": "explanation", "text": QUESTION,
                                   "span_ids": link["span_ids"]}]}}
    w.review_claim(claim, {"reviewer": "Synthetic fixture", "reviewer_kind": "synthetic_fixture",
                          "reviewed_at": "2026-11-11T00:00:00Z", "content_checked": True,
                          "rationale": "Software release membership test only"})


def add_legacy(w, theory_id="SYNTH-LEGACY"):
    link = source(w)
    w.lib.seed({"sources": []}, {"cards": [{"theory_id": theory_id, "version": "1",
                                             "title": QUESTION, "domains": ["progression"]}]})
    w.review_theory(theory_id, "1", reviewer="Synthetic fixture", reviewer_kind="synthetic_fixture",
                    rationale="Software release membership test only", applicability={"required": {}, "scope": "synthetic"},
                    evidence_links=[link], claims=[{"text": QUESTION, "span_ids": link["span_ids"],
                        "support_rationale": "Synthetic assertion", "answer_bindings": [{"question": QUESTION,
                            "target_claim": {"proposition": QUESTION, "scope": {"population": "synthetic"}},
                            "relation": "supports", "rationale": "Synthetic relation"}]}])


def query(w, release_id=None):
    return w.query(QUESTION, "progression", CONTEXT, k=20, release_id=release_id)["retrieval"]


def refs(result):
    return {(c["theory_id"], c["theory_version"]) for c in result["candidates"]}


def test_core_release_excludes_later_claim_versions_and_all_unfrozen_legacy(library):
    add_core(library)
    library.release_core("core-only")
    add_core(library, version="2")
    add_core(library, "SYNTH-LATER-CORE")
    add_legacy(library)
    assert len(refs(query(library))) == 4
    result = query(library, "core-only")
    assert refs(result) == {("SYNTH-CORE", "1")}
    assert result["release_scope"]["core_claims"] == "frozen_snapshot"
    assert result["release_scope"]["legacy_theories"] == "excluded_no_snapshot"


def test_legacy_release_excludes_later_core_and_legacy_claims(library):
    add_legacy(library)
    library.release("legacy-only")
    add_core(library)
    add_legacy(library, "SYNTH-LATER-LEGACY")
    result = query(library, "legacy-only")
    assert refs(result) == {("SYNTH-LEGACY", "1")}
    assert result["release_scope"]["core_claims"] == "excluded_no_snapshot"
    assert result["release_scope"]["legacy_theories"] == "frozen_snapshot"


def test_same_release_id_combines_only_the_two_recorded_snapshots(library):
    add_core(library)
    add_legacy(library)
    library.release_core("combined")
    library.release("combined")
    add_core(library, "SYNTH-LATER-CORE")
    add_legacy(library, "SYNTH-LATER-LEGACY")
    result = query(library, "combined")
    assert refs(result) == {("SYNTH-CORE", "1"), ("SYNTH-LEGACY", "1")}
    assert result["release_scope"]["core_claims"] == result["release_scope"]["legacy_theories"] == "frozen_snapshot"


@pytest.mark.parametrize("invalidation", ["claim_revoked", "source_corrected", "source_withdrawn"])
def test_frozen_core_membership_cannot_revive_currently_invalid_evidence(library, invalidation):
    add_core(library)
    frozen = library.release_core("before-invalidation")
    assert refs(query(library, "before-invalidation")) == {("SYNTH-CORE", "1")}
    if invalidation == "claim_revoked":
        library.core_state("claim", "SYNTH-CORE", "1", "revoked", actor="Synthetic reviewer", rationale="Synthetic withdrawal")
    else:
        library.lib.update_state("S5", "withdrawn" if invalidation == "source_withdrawn" else "corrected_pending_review", "Synthetic notice")
    result = query(library, "before-invalidation")
    assert not result["candidates"]
    assert result["release_scope"]["current_validity_checks"] is True
    unchanged = library.lib.theories.execute("SELECT manifest_json FROM core_release WHERE release_id='before-invalidation'").fetchone()[0]
    assert json.loads(unchanged)["claims"] == frozen["claims"]


def test_unknown_release_is_rejected_and_empty_core_filter_means_no_claims(library):
    add_core(library)
    with pytest.raises(ValueError, match="^unknown release$"):
        query(library, "does-not-exist")
    assert core_candidates(library, QUESTION, CONTEXT, {"core", "research"}, allowed_refs=set()) == ([], [])
    selected, _ = core_candidates(library, QUESTION, CONTEXT, {"core", "research"}, allowed_refs={("SYNTH-CORE", "1")})
    assert {c["theory_id"] for c in selected} == {"SYNTH-CORE"}
