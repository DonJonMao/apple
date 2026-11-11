"""Candidate handles and explicit modifications cannot bypass current facts."""
import runpy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from healthzip.advice import (
    build_advice_context,
    current_use_status,
    modify_candidate,
    save_profile,
)

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_v14_advice_flow.py")))


def test_old_candidate_handle_cannot_bypass_corrected_reference(tmp_path, monkeypatch):
    repo, svc, _, record = HELPERS["_clean_candidate"](tmp_path, monkeypatch)
    reference = svc.get_set(record["input_snapshot"]["reference_set_id"])
    svc.edit_set(reference["id"], {"reps": 5}, base_revision=reference["revision"])
    assert record["stale"] == 0  # caller retained its pre-correction handle
    assert current_use_status(repo, record)["status"] == "review_required"
    with pytest.raises(ValueError, match="重新核对"):
        modify_candidate(repo, record, 55, {"reps_min": 7, "reps_max": 8, "rir_min": 2, "rir_max": 2})
    assert len(svc.list_recommendations()) == 1
    repo.close()


def test_profile_revision_is_selected_at_actual_cutoff(tmp_path, monkeypatch):
    repo, _, instance, _ = HELPERS["_clean_candidate"](tmp_path, monkeypatch)
    earlier = save_profile(repo, {"age": 32, "training_goal": "strength"})
    cutoff = datetime.now(timezone.utc).isoformat()
    save_profile(repo, {"age": 17, "health_scope": "clinical_or_rehabilitation"})
    context = build_advice_context(repo, instance["session_id"], instance["id"], None, [], "double_progression", cutoff_time=cutoff)["context"]
    assert context["age"] == 32 and context["profile_revision"] == earlier["revision"]
    assert "health_scope" not in context
    repo.close()


@pytest.mark.parametrize("load,target", [
    (55, {"rir_min": 2, "rir_max": 2}),
    (55, {"reps_min": 0, "reps_max": 0, "rir_min": 2, "rir_max": 2}),
    (55, {"reps_min": 7, "reps_max": 999, "rir_min": 2, "rir_max": 2}),
    (55, {"reps_min": 7, "reps_max": 8, "rir_min": 2, "rir_max": 99}),
    (50, {"reps_min": 7, "reps_max": 8, "rir_min": 2, "rir_max": 2}),
])
def test_modification_preserves_endpoint_plan_and_strategy(tmp_path, monkeypatch, load, target):
    repo, svc, _, record = HELPERS["_clean_candidate"](tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        modify_candidate(repo, record, load, target)
    assert len(svc.list_recommendations()) == 1
    repo.close()


def test_repetition_choice_cannot_silently_change_load(tmp_path, monkeypatch):
    repo, _, _, record = HELPERS["_clean_candidate"](tmp_path, monkeypatch, "repetition_progression")
    target = {"reps_min": 13, "reps_max": 15, "rir_min": 2, "rir_max": 2}
    with pytest.raises(ValueError, match="保持参考负荷"):
        modify_candidate(repo, record, 52.5, target)
    modified = modify_candidate(repo, record, 50, target)
    assert modified["candidate"]["proposed_change"]["load"] == 50
    assert modified["input_snapshot"]["choice_validation"]["within_confirmed_plan"]
    assert modified["candidate"]["proposed_change"]["changes"]["entered_change"] == 0
    repo.close()
