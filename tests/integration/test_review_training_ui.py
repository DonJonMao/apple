"""Actual persistent Streamlit controls reproduce review regressions."""

from healthzip.db.repository import Repository
from healthzip.training import TrainingService


def review_app(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "review-ui.sqlite3"
    repo = Repository(path)
    svc = TrainingService(repo)
    session = svc.start_session("合成双视图")
    instance = svc.add_exercise(session["id"], "psa.ex.smith_incline_press", {})
    row = svc.add_set(instance["id"], {"completion_state": "completed", "reps": 10})
    repo.close()
    script = (
        "from healthzip.db.repository import Repository\n"
        "from healthzip.ui.training_page import render_training\n"
        f"repo=Repository({str(path)!r})\nrender_training(repo)\nrepo.close()"
    )
    return AppTest.from_string(script).run(timeout=30), path, session, instance, row


def test_r04_clean_history_save_cannot_revert_current_view(tmp_path, monkeypatch):
    app, path, _, _, row = review_app(tmp_path, monkeypatch)
    identity = row["set_uuid"]
    assert app.text_input(key=f"history_{identity}_reps").value == "10"
    app.text_input(key=f"set_{identity}_reps").set_value("9").run()
    assert not app.exception
    repo = Repository(path)
    revision = TrainingService(repo).get_set(identity)["revision"]
    repo.close()
    app.run()
    app.button(key=f"history_{identity}_save_fields").click().run()
    assert not app.exception
    repo = Repository(path)
    saved = TrainingService(repo).get_set(identity)
    assert saved["reps"] == 9 and saved["revision"] == revision
    repo.close()


def test_r04_dirty_history_keeps_loaded_revision_and_reports_conflict(tmp_path, monkeypatch):
    app, path, _, _, row = review_app(tmp_path, monkeypatch)
    identity = row["set_uuid"]
    app.text_input(key=f"history_{identity}_note").set_value("历史视图尚未保存的备注").run()
    app.text_input(key=f"set_{identity}_reps").set_value("9").run()
    app.run()
    app.button(key=f"history_{identity}_save_fields").click().run()
    assert not app.exception
    repo = Repository(path)
    svc = TrainingService(repo)
    assert svc.get_set(identity)["reps"] == 9
    assert svc.list_conflicts(), "持久表单必须提交加载时版本，不能挪用新版本覆盖"
    assert svc.list_conflicts()[0]["proposed"] == {"quality_note": "历史视图尚未保存的备注"}
    repo.close()


def fill_reference_protocol(app, prefix, *, protocol_id="fixed_reference", version="1"):
    fields = {
        "id": protocol_id,
        "version": version,
        "policy": "first_work_set",
        "effort": "target_rir_2",
        "tempo": "2-0-1",
        "rest": "120_seconds_before_reference",
    }
    for key, value in fields.items():
        app.text_input(key=f"{prefix}_protocol_{key}").set_value(value)


def test_r02_structured_protocol_is_entered_through_condition_widgets(tmp_path, monkeypatch):
    app, path, _, instance, _ = review_app(tmp_path, monkeypatch)
    # Use the ordinary template form; execution conditions are intentionally immutable.
    app.text_input(key="template_name_None").set_value("结构化协议模板")
    app.text_input(key="template_selector_query").set_value("上斜史密斯").run()
    fill_reference_protocol(app, "template_condition")
    app.selectbox(key="template_condition_basis").set_value("unknown")
    app.text_input(key="template_condition_protocol").set_value("仅作为备注")
    app.button(key="template_save").click().run()
    assert not app.exception and not app.error
    repo = Repository(path)
    condition = TrainingService(repo).list_templates()[0]["items"][0]["condition"]
    assert isinstance(condition["reference_protocol"], dict)
    assert condition["reference_protocol"]["version"] == "1"
    assert condition["reference_protocol_note"] == "仅作为备注"
    repo.close()


def test_r02_three_sessions_from_page_produce_protocol_identified_trend(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from healthzip.analytics.v13 import analyze

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "protocol-ui.sqlite3"
    script = (
        "from healthzip.db.repository import Repository\n"
        "from healthzip.ui.training_page import render_training\n"
        f"repo=Repository({str(path)!r})\nrender_training(repo)\nrepo.close()"
    )
    app = AppTest.from_string(script).run(timeout=30)
    app.text_input(key="template_name_None").set_value("同协议观察")
    app.text_input(key="template_selector_query").set_value("上斜史密斯").run()
    app.text_input(key="template_condition_new_machine").set_value("合成设备")
    app.button(key="template_condition_add_machine").click().run()
    repo = Repository(path)
    machine = TrainingService(repo).list_equipment()[0]["id"]
    repo.close()
    app.selectbox(key="template_condition_instance").set_value(machine)
    app.selectbox(key="template_condition_basis").set_value("plates_per_side_kg")
    app.checkbox(key="template_condition_confirmed").check()
    app.checkbox(key="template_condition_symmetric").check()
    app.selectbox(key="template_condition_side").set_value("both")
    app.selectbox(key="template_condition_repmeaning").set_value("simultaneous")
    app.text_input(key="template_condition_rom").set_value("本次确认全幅")
    app.text_input(key="template_condition_settings").set_value("固定上斜角度")
    app.checkbox(key="template_condition_settings_ok").check()
    fill_reference_protocol(app, "template_condition")
    app.text_input(key="template_targets_low").set_value("6")
    app.text_input(key="template_targets_high").set_value("8")
    app.text_input(key="template_targets_rir").set_value("2")
    app.button(key="template_save").click().run()
    assert not app.exception and not app.error
    repo = Repository(path)
    plan_id = TrainingService(repo).list_templates()[0]["id"]
    repo.close()
    app.run()
    # A repetitions trend is one fixed-load task, not three different loads.
    for reps in (6, 7, 8):
        app.selectbox(key="start_template").set_value(plan_id)
        app.button(key="training_start").click().run()
        repo = Repository(path)
        service = TrainingService(repo)
        session = service.get_session(service.list_sessions()[0]["id"])
        row = session["sets"][0]
        repo.close()
        prefix = "set_" + row["set_uuid"]
        app.button(key=prefix + "_reference").click().run()
        app.text_input(key=prefix + "_load_value").set_value("30")
        app.text_input(key=prefix + "_reps").set_value(str(reps))
        app.text_input(key=prefix + "_rir").set_value("2")
        app.selectbox(key=prefix + "_quality").set_value("acceptable")
        app.button(key=prefix + "_completed").click().run()
        assert not app.exception and not app.error
        next(button for button in app.button if button.label == "结束训练并保存反馈").click().run()
        assert not app.exception and not app.error
    repo = Repository(path)
    result = analyze(repo)
    assert len(result["strength_tasks"]) == 1
    task = result["strength_tasks"][0]
    assert task["protocol_complete"] is True
    assert task["protocol"]["reference_protocol_id"] == "fixed_reference"
    assert task["protocol"]["reference_protocol_version"] == "1"
    assert task["metrics"]["STR-11"]["valid_n"] == 3
    assert task["metrics"]["STR-19"]["data_status"] == "valid"
    assert task["metrics"]["STR-19"]["value"]["slope_per_day"] is not None
    assert task["metrics"]["STR-19"]["value"]["interval"] is None
    repo.close()
