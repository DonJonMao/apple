"""Synthetic order/comparability review; never a validation of fatigue causality."""
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest

from healthzip.db.repository import Repository
from healthzip.training.sequence_review import review_sequence
from healthzip.training.service import TrainingService


@pytest.fixture
def sequence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        svc = TrainingService(repo)
        machine = svc.create_equipment("Synthetic stable station", "machine")
        condition = {"equipment_instance_id": machine["id"], "load_basis": "plates_per_side_kg",
            "load_basis_confirmed": True, "side": "bilateral", "repetition_semantics": "full_repetitions",
            "rom_protocol": "synthetic-full", "settings": {}, "settings_confirmed": True,
            "reference_protocol": {"protocol_id": "synthetic-order", "version": "1",
                "reference_policy_id": "synthetic-first", "effort_protocol": "direct-rir",
                "tempo": "controlled", "rest_protocol": "recorded-180s"}}
        lead = svc.create_exercise("合成上斜卧推", "repetitions", "machine", "plates_per_side_kg",
                                   exercise_id="custom.sequence-incline")["exercise_id"]
        target = svc.create_exercise("合成夹胸", "repetitions", "machine", "plates_per_side_kg",
                                     exercise_id="custom.sequence-fly")["exercise_id"]
        now = datetime.now(timezone.utc) - timedelta(hours=2)
        sessions = []
        for offset, leading_count, target_reps in ((4, 2, (12, 10)), (1, 3, (10, 8))):
            at = now - timedelta(days=offset)
            session = svc.start_session("Synthetic sequence", started_at=at.isoformat())
            for exercise, reps in ((lead, [8] * leading_count), (target, target_reps)):
                item = svc.add_exercise(session["id"], exercise, condition)
                for index, count in enumerate(reps):
                    started = at + timedelta(minutes=(0 if exercise == lead else 20) + index * 4)
                    svc.add_set(item["id"], {"completion_state": "completed", "load_value": 32.5,
                        "load_unit": "kg", "reps": count, "rir": 0, "rest_recorded_s": 180,
                        "rest_recorded_method": "manual", "quality_status": "acceptable", "pain_flag": False,
                        "started_at": started.isoformat(), "ended_at": (started + timedelta(minutes=1)).isoformat()})
            svc.end_session(session["id"], ended_at=(at + timedelta(minutes=40)).isoformat())
            sessions.append(session["id"])
        yield repo, svc, sessions, lead, target


def test_actual_order_same_load_rir_zero_and_no_tonnage_cause(sequence):
    repo, svc, sessions, lead, target = sequence
    before = repo.conn.total_changes
    result = review_sequence(svc, sessions[1], sessions[0], lead, target)
    assert repo.conn.total_changes == before
    assert result["order"]["preceding_before_target"] == [True, True]
    assert result["order"]["changed"] is False
    assert [pair["reps_change"] for pair in result["comparisons"]] == [-2, -2]
    assert all(pair["current_rir"] == 0 for pair in result["comparisons"])
    assert len(result["preceding"]["previous"]) == 2 and len(result["preceding"]["current"]) == 3
    assert all(row["load_basis"] == "plates_per_side_kg" for row in result["target"]["current"])
    assert result["session_gap_hours"] == 72
    assert not result["possible_explanations"] and not result["evidence"]["claims"]
    assert any("睡眠" in text for text in result["missing"])
    assert result["identity"] == "descriptive_record_review_not_causal_confirmation"


def test_changed_order_and_load_do_not_create_same_weight_decline(sequence):
    _, svc, sessions, lead, target = sequence
    session = svc.get_session(sessions[1])
    svc.reorder_exercises(session["id"], [x["id"] for x in reversed(session["exercises"])],
                          base_revision=session["revision"])
    target_item = next(x for x in session["exercises"] if x["catalog_id"] == target)
    for row in target_item["sets"]:
        svc.edit_set(row["set_uuid"], {"load_value": 35}, base_revision=row["revision"])
    result = review_sequence(svc, sessions[1], sessions[0], lead, target)
    assert result["order"]["changed"] and result["order"]["preceding_before_target"] == [True, False]
    assert all(pair["reps_change"] is None for pair in result["comparisons"])
    assert any("位置改变" in text for text in result["missing"])


def test_frozen_or_fabricated_permission_never_authorizes_explanation(sequence):
    _, svc, sessions, lead, target = sequence
    result = review_sequence(svc, sessions[1], sessions[0], lead, target, knowledge={
        "queries": [{"metric_id": "STR-15", "permissions": {"source_explanation": True},
                     "claims": [{"claim_id": "stale", "statements": ["fatigue"]}]}]})
    assert not result["possible_explanations"]
    assert result["evidence"]["current_checked"] is False


def test_real_metric_and_missing_library_keep_facts(sequence):
    _, svc, sessions, lead, target = sequence
    result = review_sequence(svc, sessions[1], sessions[0], lead, target, include_evidence=True)
    assert result["evidence"]["status"] == "source_unavailable"
    assert result["evidence"]["metric_result"]["metric_id"] == "STR-15"
    assert result["evidence"]["metric_result"]["value"] is not None
    assert result["comparisons"][0]["reps_change"] == -2


def test_current_reviewed_source_is_used_and_revocation_is_rechecked(sequence, tmp_path, monkeypatch):
    import healthzip.knowledge as knowledge
    from healthzip.knowledge import metric_retrieval
    from healthzip.workflows.storage import save_context
    from tests.knowledge.test_v15_retrieval import add

    repo, svc, sessions, lead, target = sequence
    cls = knowledge.KnowledgeWorkbench
    # Same real service and permission checks; only choose its documented
    # synthetic environment for synthetic reviewers. Production never receives it.
    monkeypatch.setattr(knowledge, "KnowledgeWorkbench", lambda root: cls(root, environment_kind="synthetic_test"))
    root = tmp_path / "kb"
    kb = cls(root, environment_kind="synthetic_test")
    try:
        add(kb, "synthetic-sequence-source", mid="STR-15", text=(
            "Within session fatigue repeated sets performance. Fatigue, rest and pacing are "
            "possible factors in repetition changes. Exercise order and preceding exercise work must be checked; an observed sequence does not identify causation. "
            "Synthetic software fixture only, not scientific review."))
        metric_retrieval.freeze_index(kb, "synthetic-order-release")
        context_id = save_context(repo, {"population": "adults"})
        first = review_sequence(svc, sessions[1], sessions[0], lead, target,
            include_evidence=True, knowledge_root=root, context_id=context_id)
        assert first["evidence"]["current_checked"], first["evidence"]
        assert first["evidence"]["source_explanation"], first["evidence"]
        assert first["possible_explanations"][0]["claim_id"] == "synthetic-sequence-source"
        assert "不证明" in first["possible_explanations"][0]["text"]
        assert first["evidence"]["spans"][0]["source_id"] == "synthetic-sequence-source"
        kb.core_state("claim", "synthetic-sequence-source", "1", "revoked", actor="Synthetic", rationale="Synthetic lifecycle test")
        second = review_sequence(svc, sessions[1], sessions[0], lead, target,
            knowledge=first["evidence"], include_evidence=True, knowledge_root=root, context_id=context_id)
        assert not second["possible_explanations"]
        assert second["comparisons"][0]["reps_change"] == -2
    finally:
        kb.close()


def test_target_stop_missing_rir_and_shorter_rest_are_descriptive(sequence):
    from healthzip.training.sequence_review import compare_work_sets

    _, svc, sessions, _, target = sequence
    observations = []
    for i, session_id in enumerate(sessions):
        inst = next(e for e in svc.get_session(session_id)["exercises"] if e["catalog_id"] == target)
        for index, row in enumerate(inst["sets"]):
            values = {"load_value": "30.0" if i else "30", "rir": None,
                      "rest_recorded_s": 90 if i and index else 180,
                      "reps": 10 if index == 0 or i == 0 else 8,
                      "stop_reason": "plan_target" if index == 0 else "unknown"}
            svc.edit_set(row["set_uuid"], values, base_revision=row["revision"])
        observations.append(svc.get_session_exercise(inst["id"])["sets"])
    result = compare_work_sets(*observations)
    assert [p["reps_change"] for p in result["comparisons"]] == [0, -2]
    assert result["comparisons"][0]["rir_change"] is None
    assert any("达到目标后停止" in s for s in result["observations"])
    assert any("180 → 90 秒" in s for s in result["observations"])
    assert len(result["next_steps"]) == 2
    # Missing or duplicate ordinals never promote an unmatched later survivor to the first set.
    sparse = compare_work_sets(observations[0], observations[1][1:])
    assert sparse["unmatched_previous"] and not sparse["observations"]
    different = [{**r, "condition": {**r["condition"], "side": "left"}} for r in observations[1]]
    assert not compare_work_sets(observations[0], different)["observations"]
