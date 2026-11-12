"""Frozen duration/distance plan endpoints remain separate from completed groups."""

from contextlib import closing
from datetime import datetime, timezone

import pytest
from streamlit.testing.v1 import AppTest

from healthzip.analytics.v13 import analyze, snapshot
from healthzip.db.repository import Repository
from healthzip.science import evaluate
from healthzip.training.service import TrainingService

MODES = [("duration", "duration_s", "时长（秒）"), ("distance", "distance_m", "距离（米）")]


def metric(mode, field, target, actual, *, actual_mode=None, state="completed", target_present=True, plan_changes=None):
    row = {"id": "actual", "planned_set_id": "planned", "session_id": "session", "record_kind": "strength_set",
           "completion_state": state, "set_type": "work", "measurement_mode": actual_mode or mode,
           field: actual, "event_end": "2026-11-10T08:01:00Z", "available_at": "2026-11-10T08:02:00Z"}
    plan = {"id": "planned", "measurement_mode": mode, "targets": {field: target} if target_present else {},
            **(plan_changes or {})}
    return evaluate("STR-09", [row], cutoff_time="2026-11-12T00:00:00Z",
                    window_start="2026-11-09T00:00:00Z", window_end="2026-11-12T00:00:00Z",
                    context={"plan_snapshot": {"sets": [plan]}})


@pytest.mark.parametrize("mode,field,label", MODES)
@pytest.mark.parametrize("actual,status", [(12, "not_met"), (30, "met"), (40, "not_met"), (0, "not_met"), (None, "unknown")])
def test_exact_mode_target_is_not_reinterpreted_as_a_minimum(mode, field, label, actual, status):
    value = metric(mode, field, 30, actual)["value"]
    endpoint = value["target_attainment"][field]
    observation = endpoint["observations"][0]
    assert observation["status"] == status
    assert observation["target"] == {"min": 30, "max": 30}
    assert observation["actual"] == {"lower": actual, "upper": actual}
    assert endpoint["target_n"] == 1 and endpoint["planned_n"] == 1
    assert endpoint[status + "_n"] == 1
    assert value["completed"] == (1 if actual is not None and actual > 0 else 0)


@pytest.mark.parametrize("mode,field,label", MODES)
def test_missing_mode_target_and_explicit_zero_remain_distinct(mode, field, label):
    for present in (False, True):
        endpoint = metric(mode, field, None, 12, target_present=present)["value"]["target_attainment"][field]
        assert endpoint["no_target_n"] == 1 and endpoint["target_n"] == 0
    zero = metric(mode, field, 0, 0)["value"]
    assert zero["target_attainment"][field]["met_n"] == 1
    assert zero["completed"] == 0


@pytest.mark.parametrize("mode,field,label", MODES)
@pytest.mark.parametrize("actual_mode", ["repetitions", "unknown"])
def test_matching_number_in_an_incompatible_or_unknown_actual_mode_is_not_a_match(mode, field, label, actual_mode):
    endpoint = metric(mode, field, 30, 30, actual_mode=actual_mode)["value"]["target_attainment"][field]
    assert endpoint["unknown_n"] == 1
    assert endpoint["observations"][0]["observed_match"] is None
    assert "actual_measurement_mode_incompatible_or_unknown" in endpoint["observations"][0]["reason_codes"]


@pytest.mark.parametrize("mode,field,label", MODES)
@pytest.mark.parametrize("planned_mode", ["repetitions", "unknown", None])
def test_original_mode_is_required_and_is_not_inferred_from_a_target_key(mode, field, label, planned_mode):
    value = metric(mode, field, 30, 30, plan_changes={"measurement_mode": planned_mode})["value"]
    endpoint = value["target_attainment"][field]
    assert value["completed"] == 1
    assert endpoint["unknown_n"] == 1 and endpoint["target_n"] == 1
    observation = endpoint["observations"][0]
    assert observation["observed_match"] is None
    assert "original_target_measurement_mode_incompatible_or_unknown" in observation["reason_codes"]


@pytest.mark.parametrize("mode,field,label", MODES)
def test_unregistered_range_keys_do_not_create_a_mode_target_contract(mode, field, label):
    value = metric(mode, field, None, 30,
                   plan_changes={"targets": {field + "_min": 20, field + "_max": 40}})["value"]
    endpoint = value["target_attainment"][field]
    assert endpoint["no_target_n"] == 1 and endpoint["target_n"] == 0
    assert endpoint["observations"][0]["target"] == {"min": None, "max": None}


@pytest.mark.parametrize("mode,field,label", MODES)
@pytest.mark.parametrize("state,status", [("draft", "unknown"), ("in_progress", "unknown"), ("aborted", "met"), ("skipped", "not_met")])
def test_mode_endpoint_and_group_execution_states_remain_separate(mode, field, label, state, status):
    value = metric(mode, field, 30, 30, state=state)["value"]
    assert value["completed"] == 0
    assert value["target_attainment"][field]["observations"][0]["status"] == status


@pytest.mark.parametrize("mode,field,label", MODES)
def test_offline_plan_slots_keep_frozen_mode_after_definition_revision(tmp_path, mode, field, label):
    with closing(Repository(tmp_path / "synthetic-offline-mode.sqlite3")) as repo:
        svc = TrainingService(repo)
        exercise = svc.create_exercise("Synthetic offline mode", mode, "other", "external_total_kg")
        template = svc.create_template("Synthetic offline plan", [{"exercise_id": exercise["exercise_id"],
            "condition": {}, "targets": {"sets": [{field: 30}]}}])
        slot = {"set_uuid": "synthetic-offline-set", "session_exercise_id": "synthetic-offline-exercise",
                "exercise_id": exercise["exercise_id"], "targets": template["items"][0]["targets"]["sets"][0]}
        svc.start_session(template_id=template["id"], populate_template=False, client_plan_slots=[slot])
        svc.update_exercise(exercise["exercise_id"], {"recording_mode": "repetitions"}, base_revision=1)
        _, context = snapshot(repo, datetime.now(timezone.utc).isoformat(), include_sources=False)
        plan = context["session_plans"][0]["sets"][0]
        assert plan["measurement_mode"] == mode and plan["definition_version"] == 1
        result = analyze(repo, use_cache=False)["metrics"]["STR-09"]["value"]
        endpoint = result["target_attainment"][field]
        assert endpoint["unknown_n"] == 1 and endpoint["observations"][0]["target"] == {"min": 30, "max": 30}


@pytest.mark.parametrize("mode,field,label", MODES)
def test_normal_template_set_editor_and_week_month_report_keep_original_mode_target(tmp_path, monkeypatch, mode, field, label):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "synthetic-normal-mode.sqlite3"
    with closing(Repository(path)) as repo:
        exercise = TrainingService(repo).create_exercise("Synthetic audit mode", mode, "other", "external_total_kg")
    app = AppTest.from_string(
        "from healthzip.db.repository import Repository\n"
        "from healthzip.ui.training_page import render_training\n"
        f"repo=Repository({str(path)!r})\nrender_training(repo)\nrepo.close()"
    ).run(timeout=30)
    app.text_input(key="template_selector_query").set_value(exercise["name"]).run(timeout=30)
    app.checkbox(key="template_condition_confirmed").check()
    app.text_input(key="template_name_None").set_value("Synthetic mode plan")
    app.number_input(key="template_targets_count").set_value(3)
    app.text_input(key="template_targets_quantity").set_value("30")
    app.button(key="template_save").click().run(timeout=30)
    assert not app.exception and not app.error, [error.value for error in app.error]
    with closing(Repository(path)) as repo:
        template = TrainingService(repo).list_templates()[0]
    app.selectbox(key="start_template").set_value(template["id"])
    app.button(key="training_start").click().run(timeout=30)
    assert not app.exception and not app.error
    with closing(Repository(path)) as repo:
        svc = TrainingService(repo)
        session = svc.get_session(svc.list_sessions()[0]["id"])
    first = "set_" + session["sets"][0]["set_uuid"]
    app.text_input(key=first + "_target_quantity").set_value("12")
    app.button(key=first + "_target_save").click().run(timeout=30)
    for row, actual in zip(session["sets"], (12, 30, 40)):
        prefix = "set_" + row["set_uuid"]
        app.button(key=prefix + "_in_progress").click().run(timeout=30)
        app.text_input(key=prefix + "_" + field).set_value(str(actual)).run(timeout=30)
        app.button(key=prefix + "_completed").click().run(timeout=30)
        assert not app.exception and not app.error
    next(button for button in app.button if button.label == "结束训练并保存反馈").click().run(timeout=30)
    assert not app.exception and not app.error
    cutoff = datetime.now(timezone.utc).isoformat()
    with closing(Repository(path)) as repo:
        svc = TrainingService(repo)
        assert svc.current_targets(session["exercises"][0]["id"])["sets"][0]["target"][field] == 12
        _, context = snapshot(repo, cutoff, include_sources=False)
        assert all(item["measurement_mode"] == mode for item in context["session_plans"][0]["sets"])
        assert context["session_plans"][0]["sets"][0]["targets"][field] == 30
        result = analyze(repo, cutoff_time=cutoff, use_cache=False)
        endpoint = result["metrics"]["STR-09"]["value"]["target_attainment"][field]
        assert (endpoint["met_n"], endpoint["not_met_n"], endpoint["unknown_n"]) == (1, 2, 0)
    report = AppTest.from_string(
        "from healthzip.db.repository import Repository\n"
        "from healthzip.analytics.v13 import analyze\n"
        "from healthzip.ui.analysis_page import render_analysis\n"
        f"repo=Repository({str(path)!r})\n"
        f"render_analysis(repo, {{'v13': analyze(repo, cutoff_time={cutoff!r}, timezone_name='UTC')}})\nrepo.close()"
    ).run(timeout=30)
    for period in ("本周", "本月"):
        next(widget for widget in report.selectbox if widget.label == "复盘周期").set_value(period)
        next(button for button in report.button if button.label == "生成当前周期复盘").click().run(timeout=30)
        assert not report.exception and not report.error
        section = next(widget for widget in report.expander if widget.label == "本周 / 本月复盘")
        table = next(widget.value for widget in section.dataframe if "目标项" in widget.value.columns).set_index("目标项")
        assert table.loc[label, "有明确目标组数"] == 3
        assert table.loc[label, "已满足"] == 1 and table.loc[label, "未满足"] == 2
        completion = next(widget.value for widget in section.dataframe if "原计划组数" in widget.value.columns)
        assert completion.iloc[0]["已完成占原计划"] == 1
