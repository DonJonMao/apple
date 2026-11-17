"""W1 required case through real training, persisted analysis and normal controls.

The temporary permission fixture verifies software only; no production claims
or private records are used. Dates, plan and equipment choices are explicit.
"""
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from healthzip.advice import current_use_status, freeze_candidate
from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService
from healthzip.workflows import load_analysis, load_run

PAGE = runpy.run_path(str(Path(__file__).with_name("test_analysis_workflow_page.py")))
TRAINING = runpy.run_path(str(Path(__file__).with_name("test_review_candidate_flow.py")))


def history(tmp_path, monkeypatch, *, exercise="psa.ex.smith_incline_press",
            basis="plates_per_side_kg", load=30, equipment="smith", approved=True):
    import healthzip.training.service as training_module
    monkeypatch.chdir(tmp_path)
    if approved:
        TRAINING["synthetic_authority"](tmp_path / ".local/knowledge", basis)
    repo = Repository(tmp_path / "w1.sqlite3")
    svc = TrainingService(repo)
    machine = svc.create_equipment("Synthetic station", equipment)
    condition = {"equipment_instance_id": machine["id"], "load_basis": basis,
        "load_basis_confirmed": True, "side": "both", "repetition_semantics": "simultaneous",
        "rom_protocol": "user-full", "settings": {"position": "fixed"}, "settings_confirmed": True,
        "symmetric_loading": True,
        "reference_protocol": {"protocol_id": "synthetic-reference", "version": "1",
            "reference_policy_id": "first-work-set", "effort_protocol": "rir-2",
            "tempo": "controlled", "rest_protocol": "180-sec"}}
    original_timestamp = training_module.timestamp
    ids = []
    for days, reps in zip((26, 22, 18, 14, 10, 6), (10, 10, 9, 10, 10, 10), strict=True):
        clock = datetime.now(timezone.utc) - timedelta(days=days)
        with monkeypatch.context() as patch:
            patch.setattr(training_module, "timestamp", lambda value=None: original_timestamp(value) if value else clock.isoformat())
            session = svc.start_session("Synthetic prior")
            instance = svc.add_exercise(session["id"], exercise, condition)
            row = svc.add_set(instance["id"], {"reference_set": True}, planned={"reps_min": 8, "reps_max": 12, "rir": 2})
            clock += timedelta(seconds=1)
            row = svc.edit_set(row["id"], {"completion_state": "in_progress", "started_at": clock.isoformat()}, base_revision=row["revision"])
            clock += timedelta(seconds=30)
            row = svc.edit_set(row["id"], {"completion_state": "completed", "ended_at": clock.isoformat(),
                "load_value": load, "load_unit": "kg", "reps": reps, "rir": 2, "pain_flag": False,
                "quality_status": "acceptable", "stop_reason": "target_rir"}, base_revision=row["revision"])
            ids.append(row["set_uuid"])
            svc.end_session(session["id"])
    session = svc.start_session("Synthetic next trial")
    instance = svc.add_exercise(session["id"], exercise, condition)
    target = svc.add_set(instance["id"], planned={"reps_min": 8, "reps_max": 12, "rir": 2})
    return repo, svc, instance, target, ids


def latest_run(repo):
    return json.loads(repo.one("SELECT result_json FROM workflow_run ORDER BY created_at DESC LIMIT 1")[0])


def test_smith_trial_normal_page_choice_execution_and_review(tmp_path, monkeypatch):
    repo, svc, instance, target, ids = history(tmp_path, monkeypatch)
    path = repo.path
    repo.close()
    app = PAGE["open_workflow"](path)
    app.button(key="workflow_run").click().run(timeout=30)
    assert not app.exception and not app.error
    repo = Repository(path)
    first = latest_run(repo)
    metrics = load_analysis(repo, first["run_id"])["metrics"]
    assert [row["reps"] for row in metrics["STR-11"]["value"]] == [10, 10, 9, 10, 10, 10]
    review = first["supplements"]["long_term_review"]
    assert review["start_long_term_review"] is True
    assert review["series"][0]["rir_used_n"] == 5
    assert first["nodes"][3]["branch"] == "long_term_review"
    repo.close()
    key = "workflow_" + instance["id"]
    app.text_input(key="loads_" + key).set_value("30,32.5,35")
    app.button(key="candidate_" + key).click().run(timeout=30)
    assert not app.exception and not app.error
    repo = Repository(path)
    normal = TrainingService(repo).list_recommendations()[0]
    assert normal["candidate"]["proposed_change"]["load"] is None
    repo.close()
    app.selectbox(key="strategy_" + key).set_value("heavier_lower_reps")
    app.button(key="candidate_" + key).click().run(timeout=30)
    assert not app.exception and not app.error
    repo = Repository(path)
    svc = TrainingService(repo)
    trial = svc.list_recommendations()[0]
    cid = trial["candidate_id"]
    candidate = trial["candidate"]
    assert candidate["proposed_change"]["load"] == 32.5
    assert candidate["target_range"] == {"reps_min": 8, "reps_max": 8, "rir_min": 2, "rir_max": 2}
    changes = candidate["proposed_change"]["changes"]
    assert changes["plate_total_change_kg"] == 5
    assert changes["total_load_change_kg"] is None
    assert changes["total_load_change_percent"] is None
    assert set(ids) <= set(trial["input_snapshot"]["source_record_ids"])
    assert trial["feedback"] == []
    from healthzip.advice import candidate_basis
    basis = candidate_basis(trial)
    assert basis["strategy_basis"] and basis["strategy_basis"][0]["source_spans"]
    assert basis["numeric_origins"][1]["origin"] == "沿用用户已确认计划的次数下限"
    assert latest_run(repo)["candidate_ids"] == [cid]
    assert load_run(repo, first["run_id"]) == first
    repo.close()

    app.selectbox(key="workflow_choice_" + cid).set_value("accepted")
    app.button(key="workflow_feedback_" + cid).click().run(timeout=30)
    assert not app.exception and not app.error
    # Actual recording and completion use the normal training controls.
    training = TRAINING["open_app"](path)
    actual = TRAINING["finish_reference"](training, path, instance, 32.5, 8)
    next(button for button in training.button if button.label == "结束训练并保存反馈").click().run()
    assert not training.exception and not training.error
    app.run(timeout=30)
    app.selectbox(key="workflow_execution_" + cid).set_value("executed")
    app.multiselect(key="workflow_actual_records_" + cid).set_value([actual])
    app.button(key="workflow_feedback_" + cid).click().run(timeout=30)
    assert not app.exception and not app.error
    repo = Repository(path)
    final = latest_run(repo)
    outcomes = load_analysis(repo, final["run_id"])["metrics"]["STR-27"]["value"]
    assert next(row for row in outcomes if row["recommendation_id"] == cid)["short_term_success"] is True
    saved = next(row for row in TrainingService(repo).list_recommendations() if row["candidate_id"] == cid)
    assert saved["candidate"] == candidate
    assert saved["input_snapshot"] == trial["input_snapshot"]
    assert load_run(repo, first["run_id"]) == first
    repo.close()


def test_existing_rir_improvement_is_used_instead_of_called_missing(tmp_path, monkeypatch):
    from healthzip.workflows import WorkflowRequest, run_workflow
    repo, svc, instance, target, ids = history(tmp_path, monkeypatch, approved=False)
    actual = svc.get_set(ids[-1])
    svc.edit_set(actual["id"], {"rir": 3}, base_revision=actual["revision"])
    result = run_workflow(repo, WorkflowRequest("W1", session_id=instance["session_id"],
        session_exercise_id=instance["id"], selected_set_uuid=target["set_uuid"]), knowledge_root=tmp_path / "missing")
    series = result["supplements"]["long_term_review"]["series"][0]
    assert series["comparisons"][-1]["rir_change"] == 1
    assert series["comparisons"][-1]["repetitions_change"] == 0
    assert series["status"] == "recorded_improvement_present"
    assert series["start_long_term_review"] is False
    repo.close()


@pytest.mark.parametrize("approved", [True, False])
def test_other_exercise_equipment_step_and_new_pain(tmp_path, monkeypatch, approved):
    repo, svc, instance, target, ids = history(tmp_path, monkeypatch,
        exercise="psa.ex.barbell_bench_press", basis="external_total_kg", load=60,
        equipment="barbell", approved=approved)
    effective = svc.current_targets(instance["id"])
    trial = freeze_candidate(repo, svc, svc.get_session(instance["session_id"]), instance,
        effective, effective["sets"][0], [60, 65, 70], "heavier_lower_reps")
    assert trial["candidate"]["proposed_change"]["load"] == (65 if approved else None)
    if approved:
        svc.add_set(instance["id"], {"completion_state": "in_progress", "started_at": datetime.now(timezone.utc).isoformat(),
                                   "pain_flag": True, "load_unit": "kg"})
        assert current_use_status(repo, trial)["status"] == "review_required"
        assert svc.list_recommendations()[0]["input_snapshot"] == trial["input_snapshot"]
    repo.close()
