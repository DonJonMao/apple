"""Daily all-group history through the complete app.py, using ordinary records.

Authority is an existing isolated software-only fixture. No reference button,
reference flag or adoption/execution feedback participates in this main path.
"""
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from healthzip.db.repository import Repository
from healthzip.training.current import current_advice, save_equipment_loads
from healthzip.training.service import TrainingService
from healthzip.workflows.period_report import load_report
from tests.app_navigation import go, legacy_analysis

HELP = runpy.run_path(str(Path(__file__).with_name("test_workflow_four_repairs.py")))
REVIEW = runpy.run_path(str(Path(__file__).with_name("test_review_candidate_flow.py")))
UI = runpy.run_path(str(Path(__file__).resolve().parents[1] / "strength_ui_harness.py"))
ACCEPTANCE = runpy.run_path(str(Path(__file__).with_name("test_current_training_acceptance.py")))


def ordinary_setup(tmp_path, monkeypatch, *, age=6, history=True, planned=True, actions=None):
    import healthzip.training.service as module

    monkeypatch.chdir(tmp_path)
    REVIEW["synthetic_authority"](tmp_path / ".local/knowledge", "external_total_kg", actions=actions)
    repo = Repository(tmp_path / "daily-page.sqlite3")
    svc = TrainingService(repo)
    machine = svc.create_equipment("Synthetic fixed station", "barbell")
    condition = {"equipment_instance_id": machine["id"], "load_basis": "external_total_kg",
                 "load_basis_confirmed": True, "side": "both", "repetition_semantics": "simultaneous",
                 "rom_protocol": "synthetic-full-range", "settings": {"position": "fixed"},
                 "settings_confirmed": True}
    target = {"reps_min": 8, "reps_max": 12, "rir": 2} if planned else {}
    template = svc.create_template("Synthetic ordinary plan", [{
        "exercise_id": "psa.ex.barbell_bench_press", "condition": condition,
        "targets": {"sets": [target]}}]) if planned else None
    rows, previous = [], None
    if history:
        original = module.timestamp
        historical = datetime.now(timezone.utc) - timedelta(days=age)
        with monkeypatch.context() as patch:
            patch.setattr(module, "timestamp", lambda value=None: original(value) if value else historical.isoformat())
            previous = svc.start_session("Synthetic ordinary multiset")
            instance = svc.add_exercise(previous["id"], "psa.ex.barbell_bench_press", condition)
            for index, (load, reps, rir) in enumerate(((55, 10, 2), (55, 9, 1), (50, 11, 2))):
                start = historical + timedelta(minutes=index + 1)
                row = svc.add_set(instance["id"], {"completion_state": "completed", "load_value": load,
                    "load_unit": "kg", "reps": reps, "rir": rir, "quality_status": "acceptable",
                    "pain_flag": False, "stop_reason": "target_rir", "started_at": start.isoformat(),
                    "ended_at": (start + timedelta(seconds=30)).isoformat()})
                rows.append(row)
            svc.end_session(previous["id"])
    session = svc.start_session("Synthetic next ordinary", template_id=template["id"] if template else None)
    if template:
        current = svc.get_session(session["id"])["exercises"][0]
    else:
        current = svc.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
        svc.add_set(current["id"])
        current = svc.get_session_exercise(current["id"])
    save_equipment_loads(repo, current["id"], [50, 55, 60, 65], load_unit="kg")
    assert all(not r.get("reference_set") and not r.get("reference_declared_at") for r in rows)
    assert all(not r.get("reference_set") for r in current["sets"])
    return repo, svc, current, rows, previous, template


def latest(repo, instance):
    row = repo.one("SELECT payload_json FROM current_training_advice WHERE session_exercise_id=? "
                   "ORDER BY created_at DESC LIMIT 1", (instance["id"],))
    return json.loads(row[0])


def page_text(app):
    return "\n".join(str(e.value) for kind in ("markdown", "caption", "info", "warning")
                     for e in getattr(app, kind))


def test_real_app_ordinary_all_groups_free_record_next_training_and_reports(tmp_path, monkeypatch):
    import streamlit as st

    repo, svc, instance, rows, previous, template = ordinary_setup(tmp_path, monkeypatch)
    ACCEPTANCE["body"](repo)
    downloads = {}
    original_download = st.download_button

    def capture(label, data, **kwargs):
        downloads[label] = data
        return original_download(label, data, **kwargs)

    monkeypatch.setattr(st, "download_button", capture)
    UI["install"](monkeypatch)
    app = HELP["open_app"](repo.path)
    go(app, "力量")
    assert not app.exception and not app.error
    assert UI["send"](app, "session", {"session_id": instance["session_id"]})["status"] == "saved"
    assert UI["send"](app, "advice", {"instance_id": instance["id"]})["status"] == "saved"
    before = latest(repo, instance)
    assert before["daily_history"]["latest_session"]["id"] == previous["id"]
    assert {r["set_uuid"] for r in before["daily_history"]["records"]} == {r["set_uuid"] for r in rows}
    assert set(before["daily_decisions"]["input_record_ids"]) == {r["set_uuid"] for r in rows}
    shown = UI["snapshot"](app)["advice"]
    assert [(float(row["load_value"]), row["reps"]) for row in shown["daily_history"]["records"]] == [(55, 10), (55, 9), (50, 11)]
    assert shown["body"]["metrics"]["STATE-SLEEP-24H"]["value"]["observed_minutes"] == 420
    assert "Synthetic watch" in json.dumps(shown)
    assert before["reference_record"] is None
    assert all(option["basis"]["scope"] == "one_optional_set_trial_not_all_sets"
               for group in before["groups"] for option in group["options"] if option["load"] is not None)
    # Use normal actual controls, with no reference or feedback interaction.
    UI["legacy"](app, "set_details", set_id=instance["sets"][0]["set_uuid"])
    REVIEW["finish_reference"](app, repo.path, instance, 55, 12, reference=False)
    assert not app.exception and not app.error
    actual = svc.get_set(instance["sets"][0]["set_uuid"])
    assert not actual["reference_set"] and not actual["reference_declared_at"]
    current_session = svc.get_session(instance["session_id"])
    assert UI["send"](app, "end_session", {"session_id": current_session["id"], "base_revision": current_session["revision"]})["status"] == "saved"
    started = UI["send"](app, "start_session", {"template_id": template["id"]})
    assert started["status"] == "saved"
    assert not app.exception and not app.error
    next_instance = svc.get_session(started["data"]["id"])["exercises"][0]
    assert UI["send"](app, "advice", {"instance_id": next_instance["id"]})["status"] == "saved"
    after = latest(repo, next_instance)
    assert after["daily_history"]["latest_session"]["id"] == instance["session_id"]
    assert [r["set_uuid"] for r in after["daily_history"]["records"]] == [actual["set_uuid"]]
    trial = next(option for group in after["groups"] for option in group["options"]
                 if option["strategy"] == "heavier_lower_reps" and option["load"] is not None)
    assert (trial["load"], trial["reps"], trial["rir"]) == (60, 8, 2)
    assert trial["basis"]["source_set_id"] == actual["set_uuid"]
    assert trial["basis"]["repetitions_origin"] == "沿用用户计划次数下限"
    assert trial["basis"]["rules"]
    go(app, "复盘")
    legacy_analysis(app, "报告")
    app.button(key="review_compute").click().run()
    for label in ("本周", "本月"):
        next(selector for selector in app.selectbox if selector.label == "报告范围").select(label)
        next(button for button in app.button if button.label == "生成 Markdown 报告").click().run()
        assert not app.exception and not app.error
        exported = downloads["下载身体与力量联合报告"]
        assert "Synthetic watch" in exported and "7.0 小时睡眠" in exported
        assert "## 下一步" in exported
        saved = json.loads(repo.one("SELECT payload_json FROM joint_period_report ORDER BY created_at DESC LIMIT 1")[0])
        frozen = load_report(repo, saved["report_id"])
        assert frozen["markdown"] == exported
        # Readable hours do not replace the frozen original minutes or source.
        assert frozen["current"]["metrics"]["STATE-SLEEP-24H"]["value"]["observed_minutes"] == 420
        sleep_question = next(q for q in frozen["questions"] if q["id"] == "W6")
        sleep_row = next(row for row in sleep_question["rows"] if row.get("metric") == "sleep_stage")
        assert sleep_row["source"] == "Synthetic watch" and sleep_row["trajectory_last_value"] == 420
        performance = next(q for q in frozen["questions"] if q["id"] == "W1")
        points = [point for series in performance["ordinary_training"]["series"] for point in series["points"]]
        recorded = next(point for point in points if point["record_id"] == actual["set_uuid"])
        assert recorded["recorded_load"] == actual["load_value"]
        assert (float(recorded["recorded_load"]), recorded["recorded_unit"], recorded["reps"]) == (55, "kg", 12)
        assert not any(point["reference_set"] for point in points)
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    assert repo.one("SELECT count(*) FROM training_recommendation")[0] == 0
    repo.close()


@pytest.mark.parametrize("history,age", [(True, 500), (False, 0)])
def test_real_app_old_history_and_new_action_need_no_reference_or_plan(tmp_path, monkeypatch, history, age):
    repo, svc, instance, rows, previous, _ = ordinary_setup(tmp_path, monkeypatch, age=age, history=history, planned=False)
    UI["install"](monkeypatch)
    app = HELP["open_app"](repo.path)
    go(app, "力量")
    assert not app.exception and not app.error
    assert UI["send"](app, "session", {"session_id": instance["session_id"]})["status"] == "saved"
    assert UI["send"](app, "advice", {"instance_id": instance["id"]})["status"] == "saved"
    advice = latest(repo, instance)
    assert not svc.list_templates()
    assert svc.get_session(instance["session_id"])["template_id"] is None
    shown = UI["snapshot"](app)["advice"]["daily_history"]
    if history:
        assert advice["daily_history"]["latest_session"]["id"] == previous["id"]
        assert {r["set_uuid"] for r in advice["daily_history"]["records"]} == {r["set_uuid"] for r in rows}
        assert shown["records"][0]["started_at"][:10] == rows[0]["started_at"][:10]
        assert "historical_performance_is_observation_not_current_capacity" in shown["limitations"]
    else:
        assert not advice["daily_history"]["records"]
        assert shown["status"] == "no_history"
    assert not any(option["load"] is not None for group in advice["groups"] for option in group["options"])
    UI["legacy"](app, "set_details", set_id=instance["sets"][0]["set_uuid"])
    REVIEW["finish_reference"](app, repo.path, instance, 50, 8, reference=False)
    assert not app.exception and not app.error
    actual = svc.get_set(instance["sets"][0]["id"])
    assert actual["reps"] == 8 and not actual["reference_set"]
    svc.end_session(instance["session_id"])
    next_session = svc.start_session("Synthetic after ordinary unplanned")
    next_instance = svc.add_exercise(next_session["id"], instance["catalog_id"], instance["condition"])
    svc.add_set(next_instance["id"])
    following = current_advice(repo, next_instance["id"])
    assert following["daily_history"]["latest_session"]["id"] == instance["session_id"]
    assert [r["set_uuid"] for r in following["daily_history"]["records"]] == [actual["set_uuid"]]
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


def test_real_app_equipment_unit_is_explicit_unknown_and_mismatch_do_not_license_numbers(tmp_path, monkeypatch):
    repo, svc, instance, rows, _, _ = ordinary_setup(tmp_path, monkeypatch,
        actions=["double_progression", "heavier_lower_reps", "repetition_progression"])
    save_equipment_loads(repo, instance["id"], [50, 55, 60, 65], load_unit=None)
    UI["install"](monkeypatch)
    app = HELP["open_app"](repo.path)
    go(app, "力量")
    assert not app.exception and not app.error
    UI["legacy"](app, "recommendations", instance_id=instance["id"])
    assert app.selectbox(key="current_load_unit_" + instance["id"]).value is None
    unknown = latest(repo, instance)
    assert not any(option["load"] is not None for group in unknown["groups"] for option in group["options"]
                   if option["strategy"] in {"double_progression", "heavier_lower_reps"})
    repetitions = [option for group in unknown["groups"] for option in group["options"]
                   if option["strategy"] == "repetition_progression" and option["load"] is not None]
    assert [(option["load"], option["reps"]) for option in repetitions] == [(55, 12), (55, 12), (50, 12)]
    app.selectbox(key="current_load_unit_" + instance["id"]).set_value("kg")
    app.button(key="current_loads_save_" + instance["id"]).click().run()
    assert not app.exception and not app.error
    known = latest(repo, instance)
    assert any(option["load"] == 60 for group in known["groups"] for option in group["options"])
    app.selectbox(key="current_load_unit_" + instance["id"]).set_value("lb")
    app.button(key="current_loads_save_" + instance["id"]).click().run()
    assert not app.exception and not app.error
    mismatched = latest(repo, instance)
    assert mismatched["settings"]["load_unit"] == "lb"
    assert not any(option["load"] is not None for group in mismatched["groups"] for option in group["options"]
                   if option["strategy"] in {"double_progression", "heavier_lower_reps"})
    assert [(option["load"], option["reps"]) for group in mismatched["groups"] for option in group["options"]
            if option["strategy"] == "repetition_progression" and option["load"] is not None] == [(55, 12), (55, 12), (50, 12)]
    assert [row["set_uuid"] for row in mismatched["daily_history"]["records"]] == [row["set_uuid"] for row in rows]
    assert all(not svc.get_set(row["id"])["reference_set"] for row in rows)
    repo.close()
