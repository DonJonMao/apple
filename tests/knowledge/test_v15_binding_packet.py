"""Review-packet replay must preserve exact evidence and immutable history."""

import json
import runpy
from pathlib import Path

import pytest

from healthzip.knowledge import domains, metric_retrieval, vector_index
from healthzip.science import observations

apply_packet = runpy.run_path(str(Path(__file__).parents[2] / "tools/v15_apply_reviewed_bindings.py"))["apply_packet"]


def packet_fixture(kb, tmp_path, *, text='A synthetic statement for replay validation.'):
    kb.lib.seed({"sources": [{"source_id": "fixture", "canonical_url": "https://example.invalid/review-packet",
                              "title": "Public synthetic source", "corpus_roles": ["research"]}]}, {"cards": []})
    vid = kb.lib.record_version("fixture", b"synthetic review packet", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": text, "locator": {"page": 1}}], "fixture")
    sid = vid + ":s00000"
    vector_index.register_spans(kb, vid, ["strength"])
    review = {"reviewer": "Synthetic packet test", "reviewer_kind": "ai_assisted", "reviewed_at": "2026-11-17",
              "rationale": "Software fixture only, no real scientific authority.", "content_checked": True,
              "application_checked": True, "independent_expert_validation": False}
    packet = {"schema": "reviewed-metric-bindings-1.5.0", "created_at": "2026-11-17", "claims": [{
        "claim": {"claim_id": "fixture-claim", "version": "1", "statement": "Synthetic statement.",
                  "scope": {"fixture": True}, "limitations": ["Synthetic only."],
                  "evidence_links": [{"source_id": "fixture", "source_version_id": vid, "span_ids": [sid]}]},
        "review": review, "domains": ["strength"], "exact_text_hashes": {sid: kb.lib.span(sid)["text_hash"]},
        "bindings": [{"metric_id": "STR-12", "relation": "limits", "evidence_types": ["scope_limit"],
                      "applicability": {}, "review": review}]}]}
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(packet))
    return path, packet, sid


def test_packet_hash_mismatch_rejects_before_any_scientific_write(kb, tmp_path):
    path, packet, sid = packet_fixture(kb, tmp_path)
    packet["claims"][0]["exact_text_hashes"][sid] = "wrong"
    path.write_text(json.dumps(packet))
    backup, output = tmp_path / "backup", tmp_path / "receipt.json"
    with pytest.raises(ValueError, match="evidence_content_changed"):
        apply_packet(kb.root, path, output, backup)
    assert not backup.exists() and not output.exists()
    assert not kb.lib.theories.execute("SELECT 1 FROM source_claim WHERE claim_id='fixture-claim'").fetchone()


def test_packet_keeps_provisional_history_and_adds_traceable_review(kb, tmp_path):
    path, packet, sid = packet_fixture(kb, tmp_path)
    original = dict(kb.lib.sources.execute("SELECT * FROM retrieval_unit WHERE span_id=?", (sid,)).fetchone())
    receipt = apply_packet(kb.root, path, tmp_path / "receipt.json", tmp_path / "backup")
    assert dict(kb.lib.sources.execute("SELECT * FROM retrieval_unit WHERE span_id=?", (sid,)).fetchone()) == original
    assert kb.lib.sources.execute("SELECT COUNT(*) FROM retrieval_unit_domain_review WHERE span_id=?", (sid,)).fetchone()[0] == 1
    assert receipt["claims"][0]["bindings"][0]["evidence_types"] == ["scope_limit"]
    assert receipt["candidate_authority_granted"] is False
    packet["claims"][0]["claim"]["statement"] = "Attempted silent rewrite."
    path.write_text(json.dumps(packet))
    with pytest.raises(ValueError, match="existing_claim_and_review_must_be_reused_exactly"):
        apply_packet(kb.root, path, tmp_path / "new-receipt.json", tmp_path / "new-backup")
    assert not (tmp_path / "new-backup").exists()


def test_unregistered_source_is_detected_before_claim_creation(kb, tmp_path):
    path, _, sid = packet_fixture(kb, tmp_path)
    with kb.lib.sources:
        kb.lib.sources.execute("DELETE FROM retrieval_unit WHERE span_id=?", (sid,))
    with pytest.raises(ValueError, match="register_source_units_before"):
        apply_packet(kb.root, path, tmp_path / "receipt.json", tmp_path / "backup")
    assert not kb.lib.theories.execute("SELECT 1 FROM source_claim WHERE claim_id='fixture-claim'").fetchone()


def test_observation_binding_uses_its_explicit_profile_without_bypassing_missing_evidence(kb, tmp_path):
    path, packet, _ = packet_fixture(kb, tmp_path, text='Synthetic VO2max measurement protocol scope.')
    packet['claims'][0]['domains'] = ['wearable', 'cardiometabolic']
    binding = packet['claims'][0]['bindings'][0]
    binding.update(metric_id='OBS-VO2-REPORTED', evidence_types=['measurement_method_scope'])
    path.write_text(json.dumps(packet))
    apply_packet(kb.root, path, tmp_path / 'receipt.json', tmp_path / 'backup')
    row = kb.lib.theories.execute("SELECT to_id,to_version FROM knowledge_evidence_edge WHERE to_type='metric'").fetchone()
    assert tuple(row) == ('OBS-VO2-REPORTED', domains.profile_version('OBS-VO2-REPORTED'))
    metric_retrieval.freeze_index(kb, 'with-observation-binding')
    manifest = json.loads(kb.lib.sources.execute("SELECT manifest_json FROM index_release WHERE release_id='with-observation-binding'").fetchone()[0])
    assert 'observation_profile_sha256' in manifest
    computed = observations.evaluate('OBS-VO2-REPORTED', [], cutoff_time='2026-11-17T00:00:00+00:00',
        window_start='2026-11-01T00:00:00+00:00', window_end='2026-11-17T00:00:00+00:00')
    found = kb.retrieve_for_metric('OBS-VO2-REPORTED', 'cardiorespiratory', computed,
        {'population': 'adults', 'measurement_protocol': 'synthetic'}, mode='lexical')
    assert found['status'] == 'insufficient_evidence'
    assert 'missing_evidence_type:reported_vo2_interpretation_limits' in found['limitations']
    assert not found['capability_permissions']['candidate']
