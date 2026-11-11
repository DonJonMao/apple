"""Unknown current observation times must survive the real advice adapter."""
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from healthzip.advice import build_advice_context, current_use_status, freeze_candidate
from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_v14_advice_flow.py")))


def _freeze(repo, svc, instance, strategy):
    effective = svc.current_targets(instance["id"])
    return freeze_candidate(
        repo, svc, svc.get_session(instance["session_id"]),
        svc.get_session_exercise(instance["id"]), effective,
        effective["sets"][0], [50, 52.5, 55], strategy,
    )


@pytest.mark.parametrize("strategy,state", [
    ("double_progression", "in_progress"),
    ("heavier_lower_reps", "completed"),
    ("repetition_progression", "aborted"),
])
@pytest.mark.parametrize("pain", [True, False])
def test_missing_current_times_are_not_an_empty_observation_set(tmp_path, monkeypatch, strategy, state, pain):
    repo, svc, instance, original = HELPERS["_clean_candidate"](tmp_path, monkeypatch, strategy)
    try:
        observation = svc.add_set(instance["id"], {
            "completion_state": state, "reps": 4,
            "started_at": None, "ended_at": None, "pain_flag": pain,
            "quality_status": "technique_limited" if pain else "acceptable",
            "stop_reason": "pain" if pain else "target_rir",
        })
        # Adding a completed row normally leaves missing endpoints unknown;
        # the adapter must not invent a set time from its enclosing session.
        assert observation["started_at"] is None and observation["ended_at"] is None
        advice = build_advice_context(repo, instance["session_id"], instance["id"], None, [], strategy)
        assert observation["set_uuid"] in advice["context"]["current_session_record_ids"]
        assert advice["context"]["current_session_observations"][0]["event_end"] is None
        # Select the original planned target, not the extra actual observation.
        effective = svc.current_targets(instance["id"])
        saved = freeze_candidate(repo, svc, advice["session"], advice["instance"], effective,
                                 effective["sets"][0], [50, 52.5, 55], strategy)
        assert saved["candidate"]["proposed_change"]["load"] is None
        applicability = saved["input_snapshot"]["metric_result"]["candidate_applicability"]
        assert applicability["applicable"] is not True
        assert "current_observation_time_or_availability_unknown" in applicability["reason_codes"]
        assert observation["set_uuid"] in saved["input_snapshot"]["unknown_current_observation_ids"]
        assert observation["set_uuid"] not in saved["input_snapshot"]["source_record_ids"]
        assert current_use_status(repo, saved)["status"] == "review_required"
        assert current_use_status(repo, original)["status"] == "review_required"
        frozen_original = next(r for r in svc.list_recommendations() if r["candidate_id"] == original["candidate_id"])
        assert frozen_original["candidate"] == original["candidate"]
        assert frozen_original["input_snapshot"] == original["input_snapshot"]
    finally:
        repo.close()


def test_explicit_future_current_observation_does_not_enter_present_candidate(tmp_path, monkeypatch):
    repo, svc, instance, _ = HELPERS["_clean_candidate"](tmp_path, monkeypatch)
    try:
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        observation = svc.add_set(instance["id"], {
            "completion_state": "in_progress", "started_at": future,
            "pain_flag": True, "quality_status": "technique_limited", "stop_reason": "pain",
        })
        result = _freeze(repo, svc, instance, "double_progression")
        assert observation["set_uuid"] not in result["input_snapshot"]["source_record_ids"]
        assert result["input_snapshot"]["advice_context"]["current_session_record_ids"] == []
        assert result["candidate"]["proposed_change"]["load"] == 52.5
    finally:
        repo.close()


def test_missing_historical_end_time_cannot_crash_or_supply_a_reference(tmp_path, monkeypatch):
    repo, svc, instance, original = HELPERS["_clean_candidate"](tmp_path, monkeypatch)
    try:
        reference = svc.get_set(original["input_snapshot"]["reference_set_id"])
        svc.edit_set(reference["id"], {"ended_at": None}, base_revision=reference["revision"])
        result = _freeze(repo, svc, instance, "double_progression")
        assert result["candidate"]["proposed_change"]["load"] is None
        assert reference["set_uuid"] not in result["input_snapshot"]["source_record_ids"]
        applicability = result["input_snapshot"]["metric_result"]["candidate_applicability"]
        assert "reference_missing" in applicability["reason_codes"]
        assert svc.get_set(reference["set_uuid"])["ended_at"] is None
    finally:
        repo.close()


def test_ui_cleared_time_keeps_current_pain_in_frozen_candidate_evidence(tmp_path, monkeypatch):
    repo, svc, instance, original = HELPERS["_clean_candidate"](tmp_path, monkeypatch)
    row = svc.get_session_exercise(instance["id"])["sets"][0]
    path = repo.path
    repo.close()
    app = HELPERS["HELPERS"]["open_app"](path)
    key = "set_" + row["set_uuid"]
    app.button(key=key + "_in_progress").click().run(timeout=30)
    app.selectbox(key=key + "_pain").set_value(True)
    app.selectbox(key=key + "_quality").set_value("technique_limited")
    app.selectbox(key=key + "_stop").set_value("pain")
    app.text_input(key=key + "_start").set_value("")
    app.button(key=key + "_save_fields").click().run(timeout=30)
    app.selectbox(key="candidate_target_" + instance["id"]).set_value(row["set_uuid"])
    app.text_input(key="loads_" + instance["id"]).set_value("50,52.5,55")
    app.button(key="candidate_" + instance["id"]).click().run(timeout=30)
    assert not app.exception and not app.error
    repo = Repository(path)
    try:
        svc = TrainingService(repo)
        observation = svc.get_set(row["set_uuid"])
        saved = svc.list_recommendations()[0]
        assert observation["pain_flag"] == 1 and observation["started_at"] is None
        assert saved["candidate_id"] != original["candidate_id"]
        assert saved["candidate"]["proposed_change"]["load"] is None
        assert row["set_uuid"] in saved["input_snapshot"]["advice_context"]["current_session_record_ids"]
        assert "current_observation_time_or_availability_unknown" in saved["candidate"]["eligibility"]
    finally:
        repo.close()
