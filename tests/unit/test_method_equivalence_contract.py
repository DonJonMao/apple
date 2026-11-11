"""Software permission and provenance checks; synthetic prose is no scientific review."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.store import digest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("method_import", ROOT / "tools/v14_import_equivalence_source.py")
METHOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(METHOD)


@pytest.fixture
def reviewed_method(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    w.seed()
    w.seed_core()
    raw = b"Synthetic equivalence provenance and policy fixture only."
    version = w.lib.record_version(
        "M2", raw, "fulltext", {}, {}, {"index_allowed": True, "license_id": "CC0"},
        "matched", [{"text": f"Synthetic method region {i}", "locator": {"synthetic_region": i}}
                    for i in range(6)], "synthetic-only")
    definition, claim, rule = METHOD.explanation_contract()
    claim["evidence_links"][0].update(source_version_id=version,
                                      span_ids=[version + f":s{i:05d}" for i in range(6)])
    for part, original in zip(claim["answer_task"]["answer_parts"], definition["answer_parts"]):
        part["span_ids"] = [version + f":s{i:05d}" for i in original["span_indices"]]
    review = {"reviewer": "Synthetic software test", "reviewer_kind": "synthetic_fixture",
              "reviewed_at": "2026-11-11T00:00:00Z", "content_checked": True,
              "application_checked": True, "rationale": "Fixture proves no scientific claim."}
    yield w, claim, rule, review
    w.close()


def test_method_explanation_without_personal_calibration_preserves_candidate_boundary(reviewed_method):
    w, claim, rule, review = reviewed_method
    w.review_claim(claim, review)
    w.review_rule(rule, review)
    assert w.lib.source("M2")["manifest"]["corpus_roles"] == ["research"]
    assert w.core_status()["effective_explanation_rule_count"] == 1
    assert w.core_status()["effective_candidate_rule_count"] == 0
    for route in ("progression", "plateau", "personalization"):
        assert not w.reviewed_principles(route, {"requested_capability": "source_explanation"})["principles"]
    elevated = {**rule, "rule_version": "2", "requested_capability": "trial_candidate"}
    with pytest.raises(ValueError, match="candidate requires"):
        w.review_rule(elevated, review)


def test_method_release_is_additive_and_exact_parts_fail_closed(reviewed_method):
    w, claim, rule, review = reviewed_method
    previous = w.release_core("before-method")
    w.review_claim(claim, review)
    w.review_rule(rule, review)
    after = w.release_core("after-method")
    assert len(after["claims"]) == 1 and len(after["rules"]) == 1
    row = w.lib.theories.execute("SELECT manifest_json,sha256 FROM core_release WHERE release_id='before-method'").fetchone()
    assert json.loads(row["manifest_json"])["claims"] == previous["claims"] == []
    assert row["sha256"] == previous["sha256"]
    with pytest.raises(ValueError, match="core release immutable"):
        w.release_core("before-method")
    invalid = copy.deepcopy(claim)
    invalid["version"] = "invalid"
    invalid["answer_task"]["answer_parts"][0]["span_ids"] = ["unreviewed-region"]
    with pytest.raises(ValueError, match="each answer part requires exact reviewed evidence"):
        w.review_claim(invalid, review)
    w.core_state("claim", claim["claim_id"], claim["version"], "revoked", actor="Synthetic test", rationale="Synthetic withdrawal")
    assert w.core_status()["effective_explanation_rule_count"] == 0


def test_reviewed_byte_guard_rejects_changed_source(tmp_path, monkeypatch):
    monkeypatch.setattr(METHOD, "CACHE", tmp_path)
    (tmp_path / "reviewed.raw").write_bytes(b"changed")
    with pytest.raises(ValueError, match="reviewed bytes changed"):
        METHOD.checked_bytes("reviewed.raw", digest(b"original"))


def test_method_reactivation_reads_immutable_release_after_later_claims(reviewed_method):
    w, claim, rule, review = reviewed_method
    w.review_claim(claim, review)
    w.review_rule(rule, review)
    previous = METHOD.existing_or_create_release(w, "method-release")
    later = copy.deepcopy(claim)
    later["claim_id"] = "LATER-HHS-SCOPE-FIXTURE"
    w.review_claim(later, review)
    with pytest.raises(ValueError, match="core release immutable"):
        w.release_core("method-release")
    assert METHOD.existing_or_create_release(w, "method-release") == previous


def test_public_projection_rejects_nested_body_text_and_keeps_hashes():
    source = "Synthetic source\nbody for projection isolation. " * 8
    spans = [{"text": source}]
    for payload in ({"nested": [{"body": source}]}, {"payload_json": json.dumps({"body": source})}):
        with pytest.raises(ValueError, match="public output contains source body"):
            METHOD.assert_public_projection(payload, spans)
    METHOD.assert_public_projection({"text_hash": digest(source.encode()), "summary": "Original paraphrase."}, spans)


def test_method_rerun_preserves_public_bytes_and_original_audit_boundary(tmp_path):
    path = tmp_path / "method_explanation-1.4.4.json"
    original = {"frozen_artifact_sha256": {"original.json": "old-sha"}, "reviewed": True}
    METHOD.write(path, original)
    before = path.read_bytes()
    current = {"original.json": "old-sha", "later-development.json": "new-sha"}
    retained = METHOD.report_frozen_hashes(path, current)
    assert retained == original["frozen_artifact_sha256"]
    METHOD.write(path, {"reviewed": True, "frozen_artifact_sha256": retained})
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="original method audit changed"):
        METHOD.report_frozen_hashes(path, {"original.json": "changed-sha"})
    with pytest.raises(ValueError, match="published method artifact immutable"):
        METHOD.write(path, {"different": True})
