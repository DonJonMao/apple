"""Synthetic permission/provenance checks; scientific review uses the local HHS PDF."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.store import digest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("hhs_review", ROOT / "tools/v14_review_hhs_scope.py")
HHS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HHS)


@pytest.fixture
def reviewed_hhs(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    w.seed()
    w.seed_core()
    definition, claim, rule = HHS.explanation_contract()
    version = w.lib.record_version(
        definition["source_id"], b"Synthetic HHS contract fixture only", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": f"Synthetic region {i}", "locator": {"synthetic_region": i}} for i in range(11)],
        "synthetic-only")
    claim["evidence_links"][0].update(source_version_id=version)
    claim["evidence_links"][0]["span_ids"] = [version + f':s{r["span_index"]:05d}' for r in definition["reviewed_spans"]]
    for part, original in zip(claim["answer_task"]["answer_parts"], definition["answer_parts"]):
        part["span_ids"] = [version + f":s{i:05d}" for i in original["span_indices"]]
    review = {"reviewer": "Synthetic software test", "reviewer_kind": "synthetic_fixture",
              "reviewed_at": "2026-11-11T00:00:00Z", "content_checked": True,
              "application_checked": True, "rationale": "Fixture proves no scientific claim."}
    yield w, claim, rule, review
    w.close()


def test_hhs_explanation_never_grants_personal_candidate_authority(reviewed_hhs):
    w, claim, rule, review = reviewed_hhs
    w.review_claim(claim, review)
    w.review_rule(rule, review)
    assert w.core_status()["effective_explanation_rule_count"] == 1
    assert w.core_status()["effective_candidate_rule_count"] == 0
    for route in rule["routes"]:
        for capability in ("source_explanation", "trial_candidate", "plan_candidate"):
            assert not w.reviewed_principles(route, {"requested_capability": capability})["principles"]
    promoted = {**rule, "rule_version": "invalid", "requested_capability": "trial_candidate"}
    with pytest.raises(ValueError, match="candidate requires"):
        w.review_rule(promoted, review)


def test_hhs_exact_evidence_and_current_withdrawal_fail_closed(reviewed_hhs):
    w, claim, rule, review = reviewed_hhs
    invalid = copy.deepcopy(claim)
    invalid["evidence_links"][0]["source_id"] = "S1"
    with pytest.raises(ValueError, match="evidence version/source mismatch"):
        w.review_claim(invalid, review)
    invalid = copy.deepcopy(claim)
    invalid["answer_task"]["answer_parts"][-1]["span_ids"] = ["S1:unreviewed"]
    with pytest.raises(ValueError, match="each answer part requires exact reviewed evidence"):
        w.review_claim(invalid, review)
    w.review_claim(claim, review)
    w.review_rule(rule, review)
    frozen = HHS.existing_or_create_release(w, "hhs-release")
    w.core_state("claim", claim["claim_id"], claim["version"], "revoked",
                 actor="Synthetic test", rationale="Synthetic withdrawal")
    assert w.core_status()["effective_explanation_rule_count"] == 0
    assert HHS.existing_or_create_release(w, "hhs-release") == frozen


def test_hhs_rerun_reads_frozen_release_after_later_additions(reviewed_hhs):
    w, claim, rule, review = reviewed_hhs
    w.review_claim(claim, review)
    w.review_rule(rule, review)
    frozen = HHS.existing_or_create_release(w, "hhs-release")
    later = copy.deepcopy(claim)
    later["claim_id"] = "LATER-UNRELATED-CLAIM"
    w.review_claim(later, review)
    with pytest.raises(ValueError, match="core release immutable"):
        w.release_core("hhs-release")
    assert HHS.existing_or_create_release(w, "hhs-release") == frozen
    row = w.lib.theories.execute("SELECT manifest_json FROM core_release WHERE release_id='hhs-release'").fetchone()
    assert digest(row[0].encode()) == frozen["sha256"]


def test_hhs_public_projection_is_prose_free_and_immutable(tmp_path):
    source = "Synthetic body text from a source, not an original review summary. " * 8
    path = tmp_path / "public.json"
    for value in ({"body": source}, {"payload_json": json.dumps({"body": source})}):
        with pytest.raises(ValueError, match="public output contains source body"):
            HHS.write_public(path, value, [{"text": source}])
    HHS.write_public(path, {"hash": digest(source.encode()), "verified": True}, [{"text": source}])
    original_bytes = path.read_bytes()
    HHS.write_public(path, {"verified": True, "hash": digest(source.encode())}, [{"text": source}])
    assert path.read_bytes() == original_bytes
    with pytest.raises(ValueError, match="artifact immutable"):
        HHS.write_public(path, {"changed": True}, [{"text": source}])


def test_hhs_source_byte_change_is_rejected(reviewed_hhs):
    w, claim, _, _ = reviewed_hhs
    definition, _, _ = HHS.explanation_contract()
    definition["source_version_id"] = claim["evidence_links"][0]["source_version_id"]
    with pytest.raises(ValueError, match="HHS PDF bytes changed"):
        HHS.verify_source(w, definition)
