"""Behavioral regressions for the six reviewed workflow integration defects."""
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from healthzip.advice import freeze_candidate
from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService
from healthzip.workflows import (
    WorkflowRequest,
    check_current_use,
    load_analysis,
    load_run,
    run_workflow,
)
from healthzip.workflows.reports import markdown, review_analysis

W1 = runpy.run_path(str(Path(__file__).with_name("test_analysis_w1_flow.py")))
OBS = runpy.run_path(str(Path(__file__).with_name("test_analysis_observation_flows.py")))


def record(svc, monkeypatch, instance, *, days, reps=10, equipment=None, exercise=None):
    import healthzip.training.service as training_module
    condition = dict(instance["condition"])
    if equipment:
        condition["equipment_instance_id"] = equipment
    clock = datetime.now(timezone.utc) - timedelta(days=days)
    original = training_module.timestamp
    with monkeypatch.context() as patch:
        patch.setattr(training_module, "timestamp", lambda value=None: original(value) if value else clock.isoformat())
        session = svc.start_session("Synthetic review regression")
        target = svc.add_exercise(session["id"], exercise or instance["catalog_id"], condition)
        row = svc.add_set(target["id"], {"reference_set": True}, planned={"reps_min": 8, "reps_max": 12, "rir": 2})
        clock += timedelta(seconds=1)
        row = svc.edit_set(row["id"], {"completion_state": "in_progress", "started_at": clock.isoformat()}, base_revision=row["revision"])
        clock += timedelta(seconds=30)
        row = svc.edit_set(row["id"], {"completion_state": "completed", "ended_at": clock.isoformat(),
            "load_value": 30, "load_unit": "kg", "reps": reps, "rir": 2, "pain_flag": False,
            "quality_status": "acceptable", "stop_reason": "target_rir"}, base_revision=row["revision"])
        svc.end_session(session["id"])
    return target, row


def freeze(repo, svc, instance):
    effective = svc.current_targets(instance["id"])
    return freeze_candidate(repo, svc, svc.get_session(instance["session_id"]), instance,
        effective, effective["sets"][0], [30, 32.5, 35], "heavier_lower_reps")


@pytest.mark.parametrize("variant", ["single", "equipment", "exercise"])
def test_w2_and_calendar_reports_handle_real_task_shapes(tmp_path, monkeypatch, variant):
    repo, svc, instance, _, ids = W1["history"](tmp_path, monkeypatch, approved=False)
    if variant != "single":
        equipment = svc.create_equipment("Synthetic second station", "smith")["id"] if variant == "equipment" else None
        record(svc, monkeypatch, instance, days=8, equipment=equipment,
            exercise="psa.ex.smith_squat" if variant == "exercise" else None)
    analysis = analyze(repo)
    assert len(analysis["strength_tasks"]) == (1 if variant == "single" else 2)
    w2 = run_workflow(repo, WorkflowRequest("W2"), knowledge_root=tmp_path / "missing")
    assert any(f["metric_id"] == "STR-11" for f in w2["facts"])
    points = w2["supplements"]["strength_points"]
    assert len(points) == (6 if variant == "single" else 7)
    assert len({p["task_id"] for p in points}) == (1 if variant == "single" else 2)
    for period in ("week", "month"):
        runs = review_analysis(repo, analysis, period=period, include_background=True, knowledge_root=tmp_path / "missing")
        assert {r["workflow_id"] for r in runs} >= {"W2", "W3", "W5"}
    repo.close()


def test_context_withdrawn_during_retrieval_refuses_freeze_without_orphans(tmp_path, monkeypatch):
    from healthzip.workflows import evidence, save_context
    from healthzip.workflows.storage import withdraw_context
    repo, svc, instance, _, ids = W1["history"](tmp_path, monkeypatch, approved=False)
    cid = save_context(repo, {"population": "adults"})
    original = evidence.retrieve

    def withdraw(*args, **kwargs):
        answer = original(*args, **kwargs)
        other = Repository(repo.path)
        withdraw_context(other, cid)
        other.close()
        return answer

    monkeypatch.setattr(evidence, "retrieve", withdraw)
    with pytest.raises(ValueError, match="concurrent"):
        run_workflow(repo, WorkflowRequest("W1", context_id=cid,
            session_id=instance["session_id"], session_exercise_id=instance["id"]), knowledge_root=tmp_path / "missing")
    assert repo.one("SELECT count(*) FROM workflow_run")[0] == 0
    assert repo.one("SELECT count(*) FROM analysis_run")[0] == 0
    repo.close()


def test_candidate_default_review_does_not_replace_recent_scope_with_history_search(tmp_path, monkeypatch):
    repo, svc, instance, target, ids = W1["history"](tmp_path, monkeypatch)
    record(svc, monkeypatch, instance, days=300, reps=8)
    current = run_workflow(repo, WorkflowRequest("W1", session_id=instance["session_id"], session_exercise_id=instance["id"]), knowledge_root=tmp_path / "missing")
    assert current["nodes"][2]["long_term_review_trigger"] is True
    candidate = freeze(repo, svc, instance)
    saved = load_run(repo, candidate["input_snapshot"]["analysis_review"]["run_id"])
    assert saved["request"]["window_days"] == current["request"]["window_days"]
    assert saved["nodes"][2]["long_term_review_trigger"] is True
    assert len(saved["supplements"]["pretraining_contexts"]) == 6
    for ctx in saved["supplements"]["pretraining_contexts"]:
        assert ctx["metrics"]["STATE-RHR"]["value"] is None
    year = run_workflow(repo, WorkflowRequest("W1", window_days=365, session_id=instance["session_id"], session_exercise_id=instance["id"]), knowledge_root=tmp_path / "missing")
    assert year["nodes"][2]["long_term_review_trigger"] is False
    assert freeze(repo, svc, instance)["candidate_id"] == candidate["candidate_id"]
    assert len(svc.list_recommendations()) == 1
    repo.close()


@pytest.mark.parametrize("period", ["week", "month"])
@pytest.mark.parametrize("variant", ["equipment", "exercise", "no_history"])
def test_current_period_new_tasks_are_included_without_invented_history(tmp_path, monkeypatch, period, variant):
    repo, svc, instance, _, ids = W1["history"](tmp_path, monkeypatch, approved=False)
    equipment = svc.create_equipment("Synthetic new station", "smith")["id"]
    new, row = record(svc, monkeypatch, instance, days=0.1, equipment=equipment,
        exercise="psa.ex.smith_squat" if variant == "exercise" else None)
    if variant == "no_history":
        for identity in ids:
            old = svc.get_set(identity)
            svc.delete_set(old["id"], base_revision=old["revision"])
    analysis = analyze(repo)
    expected = next(t for t in analysis["strength_tasks"] if t["condition_key"] == new["condition_key"])
    runs = review_analysis(repo, analysis, period=period, knowledge_root=tmp_path / "missing")
    matches = [r for r in runs if r["request"]["task_id"] == expected["task_id"]]
    assert len(matches) == 1
    selected = matches[0]
    assert all(p["metric"] is None for p in selected["supplements"]["calendar_comparison"]["periods"])
    partial = selected["supplements"]["partial_current_period"]["metric"]
    assert [r["reps"] for r in partial["value"]] == [10]
    assert str(row["set_uuid"]) in json.dumps(partial["source_record_ids"])
    assert not selected["nodes"][2]["long_term_review_trigger"]
    repo.close()


def test_w3_download_contains_frozen_observations_and_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Repository(tmp_path / "observations.sqlite3")
    bid = OBS["batch"](repo)
    for key, day, value in (("a", 4, 40), ("b", 2, 42)):
        OBS["sample"](repo, bid, key, "vo2_max_ml_kg_min", value, (datetime.now(timezone.utc)-timedelta(days=day)).isoformat())
    repo.conn.commit()
    run = run_workflow(repo, WorkflowRequest("W3"), knowledge_root=tmp_path / "missing")
    assert run["supplements"]["vo2_segments"][0]["recorded_difference"] == 2
    report = "\n".join(markdown([run], repo=repo))
    assert "40" in report and "42" in report and "变化 2" in report
    assert load_analysis(repo, run["run_id"])["observations"]["OBS-VO2-REPORTED"]["unit"] in report and "样本" in report
    assert "Synthetic source" in report
    OBS["sample"](repo, bid, "new", "vo2_max_ml_kg_min", 80, (datetime.now(timezone.utc)-timedelta(days=1)).isoformat())
    repo.conn.commit()
    assert "\n".join(markdown([run], repo=repo)) == report
    repo.close()


def test_w5_download_complete_day_values_and_frozen_coverage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Repository(tmp_path / "energy.sqlite3")
    bid = OBS["batch"](repo)
    for day in (10, 12, 14, 15):
        for kind, amount in (("basal", 1500), ("active", 500)):
            OBS["sample"](repo, bid, f"{kind}{day}", kind + "_energy_kcal", amount,
                f"2026-11-{day}T00:00:00+00:00", f"2026-11-{day+1}T00:00:00+00:00")
    OBS["visible"](repo)
    run = run_workflow(repo, WorkflowRequest("W5", cutoff_time=OBS["CUTOFF"], timezone="UTC", window_days=7), knowledge_root=tmp_path / "missing")
    report = "\n".join(markdown([run], repo=repo))
    assert "完整能量日覆盖 4/7" in report and "完整日平均 2000 kcal/日" in report
    assert "1500" in report and "500" in report
    assert "基础" in report and "活动" in report and "缺日不填零" in report
    repo.close()


@pytest.mark.parametrize("days", [14, 45, 365])
def test_candidate_reuse_runs_selected_scope_without_rewriting_candidate(tmp_path, monkeypatch, days):
    repo, svc, instance, target, ids = W1["history"](tmp_path, monkeypatch)
    record(svc, monkeypatch, instance, days=300, reps=8)
    original = freeze(repo, svc, instance)
    effective = svc.current_targets(instance["id"])
    request = WorkflowRequest("W1", window_days=days, timezone="UTC")
    repeated = freeze_candidate(repo, svc, svc.get_session(instance["session_id"]), instance,
        effective, effective["sets"][0], [30, 32.5, 35], "heavier_lower_reps", review_request=request)
    assert original["input_snapshot"] == repeated["input_snapshot"]
    assert original["candidate_id"] == repeated["candidate_id"]
    current = load_run(repo, repeated["current_analysis_review"]["run_id"])
    assert current["request"]["window_days"] == days
    assert current["request"]["timezone"] == "UTC"
    assert current["parent_run_id"] == original["input_snapshot"]["analysis_review"]["run_id"]
    assert current["nodes"][2]["long_term_review_trigger"] is (days != 365)
    assert current["request"]["candidate_id"] == original["candidate_id"]
    assert len(svc.list_recommendations()) == 1
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


@pytest.mark.parametrize("stage", ["retrieval", "before_freeze"])
@pytest.mark.parametrize("mutation", ["edit", "delete", "late_import", "unrelated", "none"])
def test_interleaved_real_revision_never_saves_old_facts_with_new_current_dependencies(tmp_path, monkeypatch, mutation, stage):
    from healthzip.workflows import evidence
    from healthzip.workflows import service as workflow_service
    repo, svc, instance, _, ids = W1["history"](tmp_path, monkeypatch, approved=False)
    request = WorkflowRequest("W1", session_id=instance["session_id"], session_exercise_id=instance["id"], mode="retrospective")
    original = evidence.retrieve if stage == "retrieval" else workflow_service.dependency_inputs
    applied = False
    calls = 0

    def interleaved(*args, **kwargs):
        nonlocal applied, calls
        answer = original(*args, **kwargs)
        calls += 1
        if applied or (stage == "before_freeze" and calls < 2):
            return answer
        applied = True
        other = Repository(repo.path)
        service = TrainingService(other)
        row = service.get_set(ids[-1])
        if mutation == "edit":
            service.edit_set(row["id"], {"reps": 12}, base_revision=row["revision"])
        elif mutation == "delete":
            service.delete_set(row["id"], base_revision=row["revision"])
        elif mutation == "late_import":
            bid = OBS["batch"](other)
            OBS["sample"](other, bid, "late-rhr", "resting_heart_rate_bpm", 65, (datetime.now(timezone.utc)-timedelta(days=2)).isoformat())
            other.conn.commit()
        elif mutation == "unrelated":
            service.start_session("Unrelated draft without observations")
        other.close()
        return answer

    monkeypatch.setattr(evidence if stage == "retrieval" else workflow_service,
                        "retrieve" if stage == "retrieval" else "dependency_inputs", interleaved)
    try:
        run = run_workflow(repo, request, knowledge_root=tmp_path / "missing")
    except ValueError as exc:
        assert mutation not in {"none", "unrelated"}
        assert "concurrent" in str(exc)
        assert repo.one("SELECT count(*) FROM workflow_run")[0] == 0
        assert repo.one("SELECT count(*) FROM analysis_run")[0] == 0
    else:
        state = check_current_use(repo, run["run_id"], knowledge_root=tmp_path / "missing")
        metrics = load_analysis(repo, run["run_id"])["metrics"]
        if state["status"] == "current":
            if mutation == "edit":
                assert metrics["STR-11"]["value"][-1]["reps"] == 12
            elif mutation == "delete":
                assert len(metrics["STR-11"]["value"]) == 5
            elif mutation == "late_import":
                assert metrics["STATE-RHR"]["value"] is not None
        if mutation in {"none", "unrelated"}:
            assert state["status"] == "current"
        assert load_run(repo, run["run_id"]) == run
    repo.close()


@pytest.mark.parametrize("period", ["week", "month"])
def test_candidate_from_calendar_trend_uses_current_action_window(tmp_path, monkeypatch, period):
    repo, svc, instance, target, ids = W1["history"](tmp_path, monkeypatch)
    effective = svc.current_targets(instance["id"])
    cutoff = datetime.now(timezone.utc).isoformat()
    request = WorkflowRequest("W4", cutoff_time=cutoff, period=period, timezone="UTC")
    candidate = freeze_candidate(repo, svc, svc.get_session(instance["session_id"]), instance,
        effective, effective["sets"][0], [30, 32.5, 35], "heavier_lower_reps", review_request=request)
    run = load_run(repo, candidate["input_snapshot"]["analysis_review"]["run_id"])
    analysis = load_analysis(repo, run["run_id"])
    assert datetime.fromisoformat(analysis["window_start"]) == datetime.fromisoformat(analysis["cutoff_time"])-timedelta(days=30)
    assert analysis["window_end"] == run["request"]["cutoff_time"]
    assert run["request"]["cutoff_time"] >= cutoff
    repo.close()


def test_withdrawn_explanation_context_does_not_revoke_independent_action_rules(tmp_path, monkeypatch):
    from healthzip.advice import current_use_status
    from healthzip.workflows import save_context
    from healthzip.workflows.storage import withdraw_context
    repo, svc, instance, target, ids = W1["history"](tmp_path, monkeypatch)
    cid = save_context(repo, {"population": "adults"})
    effective = svc.current_targets(instance["id"])
    candidate = freeze_candidate(repo, svc, svc.get_session(instance["session_id"]), instance,
        effective, effective["sets"][0], [30, 32.5, 35], "heavier_lower_reps",
        review_request=WorkflowRequest("W1", context_id=cid))
    assert candidate["candidate"]["proposed_change"]["load"] == 32.5
    withdraw_context(repo, cid)
    reviewed = candidate["input_snapshot"]["analysis_review"]["run_id"]
    assert check_current_use(repo, reviewed, knowledge_root=tmp_path / "missing")["status"] == "needs_review"
    # Numerical authority has its own actual profile/record/rule dependencies;
    # a source-explanation declaration must not become an extra action rule.
    assert current_use_status(repo, candidate)["status"] == "active"
    repo.close()
