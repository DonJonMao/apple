"""Ordinary-report navigation preserves physical identity and frozen results."""
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from healthzip.analytics.v13 import analyze
from healthzip.training.current import current_advice
from healthzip.workflows import WorkflowRequest, load_analysis, load_run, run_workflow
from healthzip.workflows.reports import markdown

PAGE = runpy.run_path(str(Path(__file__).with_name("test_daily_training_page.py")))


def ordinary_reports(repo, instance):
    tasks = sorted((task for task in analyze(repo)["strength_tasks"]
                    if task["exercise_id"] == instance["catalog_id"]),
                   key=lambda task: task["protocol"]["set_position"])
    return [run_workflow(repo, WorkflowRequest("W4", task_id=task["task_id"])) for task in tasks]


def assert_no_feedback(repo):
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    assert repo.one("SELECT count(*) FROM training_recommendation")[0] == 0


def test_ordinary_report_positions_link_same_pending_advice_without_changing_reports(tmp_path, monkeypatch):
    repo, svc, instance, rows, previous, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    reports = ordinary_reports(repo, instance)
    assert [report["task_selection"]["protocol"]["set_position"] for report in reports] == [1, 2, 3]
    snapshots = [load_analysis(repo, report["run_id"]) for report in reports]
    texts = ["\n".join(markdown([report], repo=repo)) for report in reports]
    first = current_advice(repo, instance["id"], source_report_id=reports[0]["run_id"])
    mapping = first["source_report_mapping"]
    assert mapping["version"] == "daily-report-navigation-1.0.0"
    assert mapping["source_task_id"] == reports[0]["task_selection"]["task_id"]
    assert mapping["source_condition_key"] == mapping["current_condition_key"] == instance["condition_key"]
    assert first["task_id"] not in {report["task_selection"]["task_id"] for report in reports}
    assert first["daily_history"]["latest_session"]["id"] == previous["id"]
    assert set(first["daily_decisions"]["input_record_ids"]) == {row["set_uuid"] for row in rows}
    for report, snapshot, text in zip(reports, snapshots, texts):
        assert current_advice(repo, instance["id"], source_report_id=report["run_id"]) == first
        assert load_run(repo, report["run_id"]) == report
        assert load_analysis(repo, report["run_id"]) == snapshot
        assert "\n".join(markdown([report], repo=repo)) == text
    assert repo.one("SELECT count(*) FROM current_training_advice")[0] == 1
    links = repo.rows("SELECT report_run_id FROM current_advice_report_link WHERE advice_id=?", (first["advice_id"],))
    assert {row["report_run_id"] for row in links} == {report["run_id"] for report in reports}
    assert all(not svc.get_set(row["set_uuid"])["reference_set"] for row in rows)
    assert_no_feedback(repo)
    repo.close()


@pytest.mark.parametrize("mutation", ["exercise", "equipment", "rom", "side", "load_basis", "unknown"])
def test_ordinary_report_navigation_rejects_other_action_or_condition(tmp_path, monkeypatch, mutation):
    repo, svc, instance, _, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    report = ordinary_reports(repo, instance)[0]
    condition = dict(instance["condition"])
    if mutation == "exercise":
        instance = svc.add_exercise(instance["session_id"], "psa.ex.barbell_bent_over_row", condition)
        svc.add_set(instance["id"])
    else:
        if mutation == "equipment":
            condition["equipment_instance_id"] = svc.create_equipment("Other synthetic bar", "barbell")["id"]
        elif mutation == "rom":
            condition["rom_protocol"] = "other-recorded-ROM"
        elif mutation == "side":
            condition["side"] = "left"
        elif mutation == "load_basis":
            condition["load_basis"] = "plates_per_side_kg"
        else:
            condition["equipment_instance_id"] = None
        instance = svc.update_condition(instance["id"], condition, base_revision=instance["revision"])
    with pytest.raises(ValueError, match="^source_report_task_mismatch$"):
        current_advice(repo, instance["id"], source_report_id=report["run_id"])
    assert repo.one("SELECT count(*) FROM current_advice_report_link")[0] == 0
    assert load_run(repo, report["run_id"]) == report
    assert_no_feedback(repo)
    repo.close()


def test_ordinary_report_navigation_rejects_changed_definition_version(tmp_path, monkeypatch):
    import healthzip.training.service as module

    repo, svc, ordinary, _, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch, history=False)
    exercise = svc.create_exercise("Synthetic versioned press", "repetitions", "barbell", "external_total_kg")
    historical = datetime.now(timezone.utc) - timedelta(days=6)
    original = module.timestamp
    with monkeypatch.context() as patch:
        patch.setattr(module, "timestamp", lambda value=None: original(value) if value else historical.isoformat())
        session = svc.start_session("Synthetic definition-one actual")
        previous = svc.add_exercise(session["id"], exercise["exercise_id"], ordinary["condition"])
        svc.add_set(previous["id"], {"completion_state": "completed", "load_value": 55, "load_unit": "kg",
            "reps": 10, "rir": 2, "started_at": historical.isoformat(),
            "ended_at": (historical + timedelta(seconds=30)).isoformat()})
        svc.end_session(session["id"])
    report = ordinary_reports(repo, previous)[0]
    updated = svc.update_exercise(exercise["exercise_id"], {"default_load_basis": "plates_per_side_kg"},
                                  base_revision=exercise["revision"])
    assert updated["definition_version"] == previous["definition_version"] + 1
    session = svc.start_session("Synthetic definition-two current")
    current = svc.add_exercise(session["id"], exercise["exercise_id"], previous["condition"])
    svc.add_set(current["id"])
    assert current["condition"]["load_basis"] == previous["condition"]["load_basis"]
    with pytest.raises(ValueError, match="^source_report_task_mismatch$"):
        current_advice(repo, current["id"], source_report_id=report["run_id"])
    assert load_run(repo, report["run_id"]) == report
    assert_no_feedback(repo)
    repo.close()


def test_real_app_ordinary_w4_report_navigates_to_current_training(tmp_path, monkeypatch):
    repo, _, instance, rows, previous, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    app = PAGE["HELP"]["open_app"](repo.path)
    app.selectbox(key="workflow_kind").select("W4").run()
    app.selectbox(key="workflow_outcome").select("STR-11").run()
    third_task = next(task for task in analyze(repo)["strength_tasks"] if task["protocol"]["set_position"] == 3)
    app.selectbox(key="workflow_long_task").select(third_task["task_id"])
    app.button(key="workflow_run").click().run()
    assert not app.exception and not app.error
    key = "workflow_run_" + str(repo.path.resolve()) + "_W4"
    report = load_run(repo, app.session_state[key])
    app.selectbox(key="workflow_action_target").select(instance["id"]).run()
    assert not app.exception and not app.error
    text = PAGE["page_text"](app)
    assert "本次训练建议与实际记录" in text and "最近一次这个动作的实际记录" in text
    advice = json.loads(repo.one("SELECT a.payload_json FROM current_training_advice a "
        "JOIN current_advice_report_link l ON l.advice_id=a.advice_id "
        "WHERE l.report_run_id=? AND a.session_exercise_id=?", (report["run_id"], instance["id"]))[0])
    assert advice["daily_history"]["latest_session"]["id"] == previous["id"]
    assert set(advice["daily_decisions"]["input_record_ids"]) == {row["set_uuid"] for row in rows}
    assert report["task_selection"]["protocol"]["set_position"] == 3
    assert load_run(repo, report["run_id"]) == report
    assert_no_feedback(repo)
    repo.close()
