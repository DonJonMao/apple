"""Repository events, not present-day objects, define a historical decision."""
from datetime import datetime, timezone

import pytest

from healthzip.advice import build_advice_context
from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService


def make_target(tmp_path):
    repo = Repository(tmp_path / "time.sqlite3")
    svc = TrainingService(repo)
    equipment = svc.create_equipment("Time fixture", "barbell")
    condition = {"equipment_instance_id": equipment["id"], "load_basis": "external_total_kg",
                 "load_basis_confirmed": True, "side": "both", "repetition_semantics": "simultaneous",
                 "rom_protocol": "full", "settings_confirmed": True, "settings": {"grip": "A"}}
    session = svc.start_session("Time fixture")
    instance = svc.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
    target = svc.add_set(instance["id"], planned={"reps_min": 8, "reps_max": 12, "rir": 2})
    return repo, svc, session, instance, target


def test_later_goal_and_condition_do_not_enter_prior_advice(tmp_path):
    repo, svc, session, instance, target = make_target(tmp_path)
    cutoff = datetime.now(timezone.utc).isoformat()
    args = (repo, session["id"], instance["id"], target["set_uuid"], [40, 45], "double_progression")
    before = build_advice_context(*args, cutoff_time=cutoff)
    svc.update_set_target(target["set_uuid"], {"reps_min": 3, "reps_max": 5, "rir": 4},
                          base_revision=target["revision"])
    svc.update_condition(instance["id"], {**instance["condition"], "settings": {"grip": "B"}},
                         base_revision=instance["revision"])
    replay = build_advice_context(*args, cutoff_time=cutoff)
    assert replay["selected_target"] == before["selected_target"]
    assert replay["effective_targets"] == before["effective_targets"]
    assert replay["instance"]["condition"] == before["instance"]["condition"]
    current = build_advice_context(*args)
    assert current["selected_target"]["target"]["reps_max"] == 5
    assert current["instance"]["condition"]["settings"] == {"grip": "B"}
    repo.close()


def test_target_not_yet_available_cannot_be_borrowed_from_today(tmp_path):
    repo, svc, session, instance, target = make_target(tmp_path)
    with pytest.raises(ValueError, match="截止|可见|存在"):
        build_advice_context(repo, session["id"], instance["id"], target["set_uuid"], [],
                             "double_progression", cutoff_time="2000-01-01T00:00:00+00:00")
    repo.close()
