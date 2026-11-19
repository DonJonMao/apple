"""Visible everyday training controls use real services without a template."""

import socket
from contextlib import closing

from streamlit.testing.v1 import AppTest

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService


def open_training(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def deny_network(*args, **kwargs):
        raise AssertionError("Training UI must work without network access")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    path = tmp_path / "synthetic-training-entry.sqlite3"
    app = AppTest.from_string(
        "from healthzip.db.repository import Repository\n"
        "from healthzip.ui.training_page import render_training\n"
        f"repo = Repository({str(path)!r})\n"
        "try:\n    render_training(repo)\nfinally:\n    repo.close()\n",
        default_timeout=30,
    ).run()
    assert not app.exception and not app.error
    return app, path


def main_button_keys(app):
    """The daily entry and exit remain outside tabs and collapsed expanders."""
    return {child.key for child in app.main.children.values() if child.type == "button"}


def test_visible_new_training_select_exercise_record_actual_and_finish_without_template(tmp_path, monkeypatch):
    app, path = open_training(tmp_path, monkeypatch)
    assert app.button(key="training_start").label == "新增训练"
    assert "training_start" in main_button_keys(app)
    assert app.selectbox(key="start_template").value is None
    app.selectbox(key="current_training_region").set_value("chest")
    app.button(key="training_start").click().run()
    assert not app.exception and not app.error
    assert app.multiselect(key="session_selector_regions").value == ["chest"]
    app.text_input(key="session_selector_query").set_value("杠铃卧推").run()
    app.selectbox(key="session_selector_choice").set_value("psa.ex.barbell_bench_press")
    app.checkbox(key="session_condition_confirmed").check()
    app.button(key="training_add_exercise").click().run()
    assert not app.exception and not app.error, [error.value for error in app.error]

    session_id = app.session_state["resume_training"]
    with closing(Repository(path)) as repo:
        svc = TrainingService(repo)
        session = svc.get_session(session_id)
        assert session["template_id"] is None and not svc.list_templates()
        assert len(session["exercises"]) == 1 and not session["sets"]
        instance = session["exercises"][0]
        assert instance["catalog_id"] == "psa.ex.barbell_bench_press"
    add_key = "add_set_" + instance["id"]
    assert add_key in main_button_keys(app)
    app.button(key=add_key).click().run()
    assert not app.exception and not app.error
    with closing(Repository(path)) as repo:
        row = TrainingService(repo).get_session(session_id)["sets"][0]
        assert row["load_value"] is None and row["reps"] is None and row["rir"] is None
        assert not row.get("reference_set") and not row.get("reference_declared_at")

    prefix = "set_" + row["set_uuid"]
    assert app.text_input(key=prefix + "_load_value").value == ""
    assert app.text_input(key=prefix + "_reps").value == ""
    assert app.button(key=prefix + "_completed").label == "保存实际记录（确认完成）"
    app.button(key=prefix + "_in_progress").click().run()
    app.text_input(key=prefix + "_load_value").set_value("35").run()
    app.text_input(key=prefix + "_reps").set_value("9").run()
    # RIR and all plan fields stay unknown; neither is required for recording.
    app.button(key=prefix + "_completed").click().run()
    assert not app.exception and not app.error
    assert "training_end" in main_button_keys(app)
    app.button(key="training_end").click().run()
    assert not app.exception and not app.error
    assert "training_end" not in {button.key for button in app.button}

    with closing(Repository(path)) as repo:
        svc = TrainingService(repo)
        finished = svc.get_session(session_id)
        actual = svc.get_set(row["set_uuid"])
        assert finished["session_status"] == "completed" and finished["completed_sets"] == 1
        assert actual["completion_state"] == "completed"
        assert float(actual["load_value"]) == 35 and actual["reps"] == 9 and actual["rir"] is None
        assert actual["started_at"] and actual["ended_at"]
        assert not actual["planned"]
        assert not actual.get("reference_set") and not actual.get("reference_declared_at")
        assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
        assert repo.one("SELECT count(*) FROM training_recommendation")[0] == 0


def test_primary_finish_preserves_optional_feedback_and_rejects_invalid_duration(tmp_path, monkeypatch):
    app, path = open_training(tmp_path, monkeypatch)
    app.button(key="training_start").click().run()
    session_id = app.session_state["resume_training"]
    app.text_input(key="session_minutes").set_value("invalid")
    app.button(key="training_end").click().run()
    assert not app.exception and app.error
    with closing(Repository(path)) as repo:
        assert TrainingService(repo).get_session(session_id)["session_status"] == "in_progress"
    app.text_area(key="session_feedback").set_value("Synthetic optional session note")
    app.text_input(key="session_minutes").set_value("20")
    app.text_input(key="session_srpe").set_value("6")
    app.button(key="training_end").click().run()
    assert not app.exception and not app.error
    with closing(Repository(path)) as repo:
        session = TrainingService(repo).get_session(session_id)
        assert session["session_status"] == "completed"
        assert session["feedback"]["notes"] == "Synthetic optional session note"
        assert session["duration_seconds"] == 1200 and session["session_rpe"] == 6
