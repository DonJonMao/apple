"""The normal per-set editor preserves mode, plan history and optimistic edits."""
from contextlib import closing

import pytest
from streamlit.testing.v1 import AppTest

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService


def setup_app(tmp_path, monkeypatch, mode, target):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "synthetic-mode-target.sqlite3"
    with closing(Repository(path)) as repo:
        svc = TrainingService(repo)
        exercise = svc.create_exercise("Synthetic mode target", mode, "other", "external_total_kg")
        template = svc.create_template("Synthetic plan", [{"exercise_id": exercise["exercise_id"],
            "condition": {}, "targets": {"sets": [target]}}])
        session = svc.start_session(template_id=template["id"])
    app = AppTest.from_string(
        "from healthzip.db.repository import Repository\n"
        "from healthzip.ui.training_page import render_training\n"
        f"repo=Repository({str(path)!r})\nrender_training(repo)\nrepo.close()"
    ).run(timeout=30)
    assert not app.exception and not app.error
    return app, path, session, exercise


@pytest.mark.parametrize("mode,field,old,new", [("duration", "duration_s", 30, 45),
                                                ("distance", "distance_m", 20, 35)])
def test_mode_target_and_rest_save_reopen_and_template_keep_original(tmp_path, monkeypatch, mode, field, old, new):
    initial = {field: old, "rest_seconds": 180, "load_value": 20, "load_unit": "kg", "load_basis": "external_total_kg"}
    app, path, session, _ = setup_app(tmp_path, monkeypatch, mode, initial)
    row = session["sets"][0]
    prefix = "set_" + row["set_uuid"]
    assert prefix + "_target_low" not in {x.key for x in app.text_input}
    app.text_input(key=prefix + "_target_quantity").set_value(str(new))
    app.text_input(key=prefix + "_target_rest").set_value("0")
    app.text_input(key=prefix + "_target_load").set_value("25")
    app.button(key=prefix + "_target_save").click().run(timeout=30)
    assert not app.exception and not app.error
    with closing(Repository(path)) as repo:
        svc = TrainingService(repo)
        saved = svc.get_set(row["set_uuid"])
        assert saved["planned"][field] == new and saved["planned"]["rest_seconds"] == 0
        assert saved["planned"]["load_value"] == 25
        assert saved["planned"]["load_unit"] == "kg" and saved["planned"]["load_basis"] == "external_total_kg"
        assert saved[field] is None and saved["load_value"] is None
        assert saved["definition_version"] == row["definition_version"]
        assert svc.get_session(session["id"])["plan_snapshot"] == session["plan_snapshot"]
        effective = svc.current_targets(session["exercises"][0]["id"])
        assert effective["sets"][0]["target"] == saved["planned"]
        copied = svc.save_session_as_template(session["id"], "Synthetic edited plan")
        assert copied["items"][0]["targets"]["sets"][0] == saved["planned"]
    app.run(timeout=30)
    assert float(app.text_input(key=prefix + "_target_quantity").value) == new
    assert float(app.text_input(key=prefix + "_target_rest").value) == 0


def test_unknown_mode_target_stays_unknown_and_actual_edit_keeps_target_draft(tmp_path, monkeypatch):
    app, path, session, _ = setup_app(tmp_path, monkeypatch, "duration", {"duration_s": 30})
    identity = session["sets"][0]["set_uuid"]
    prefix = "set_" + identity
    app.text_input(key=prefix + "_target_quantity").set_value("45").run()
    app.text_input(key=prefix + "_duration_s").set_value("12").run()
    assert float(app.text_input(key=prefix + "_target_quantity").value) == 45
    app.text_input(key=prefix + "_target_quantity").set_value("")
    app.button(key=prefix + "_target_save").click().run(timeout=30)
    assert not app.exception and not app.error
    with closing(Repository(path)) as repo:
        saved = TrainingService(repo).get_set(identity)
        assert saved["duration_s"] == 12 and saved["completion_state"] == "draft"
        assert saved["planned"]["duration_s"] is None
        assert all(saved["planned"].get(k) is None for k in ("rest_seconds", "load_value", "load_unit", "load_basis"))


def test_dirty_mode_target_keeps_loaded_revision_on_external_edit(tmp_path, monkeypatch):
    app, path, session, _ = setup_app(tmp_path, monkeypatch, "distance", {"distance_m": 20})
    row = session["sets"][0]
    prefix = "set_" + row["set_uuid"]
    app.text_input(key=prefix + "_target_quantity").set_value("35").run()
    with closing(Repository(path)) as repo:
        svc = TrainingService(repo)
        svc.update_set_target(row["set_uuid"], {"distance_m": 25}, base_revision=row["revision"])
    app.run(timeout=30)
    assert float(app.text_input(key=prefix + "_target_quantity").value) == 35
    app.button(key=prefix + "_target_save").click().run(timeout=30)
    assert not app.exception
    assert any("冲突" in x.value or "另一处修改" in x.value for x in app.error)
    with closing(Repository(path)) as repo:
        svc = TrainingService(repo)
        assert svc.get_set(row["set_uuid"])["planned"]["distance_m"] == 25
        conflict = svc.list_conflicts()[0]
        assert conflict["proposed"]["planned"]["distance_m"] == 35


def test_frozen_definition_selects_editor_mode_after_catalog_change(tmp_path, monkeypatch):
    app, path, session, exercise = setup_app(tmp_path, monkeypatch, "duration", {"duration_s": 30})
    with closing(Repository(path)) as repo:
        TrainingService(repo).update_exercise(exercise["exercise_id"], {"recording_mode": "repetitions"}, base_revision=1)
    app.run(timeout=30)
    prefix = "set_" + session["sets"][0]["set_uuid"]
    app.text_input(key=prefix + "_target_quantity").set_value("50")
    app.button(key=prefix + "_target_save").click().run(timeout=30)
    assert not app.exception and not app.error
    with closing(Repository(path)) as repo:
        saved = TrainingService(repo).get_set(session["sets"][0]["set_uuid"])
        assert saved["planned"]["duration_s"] == 50 and saved["definition_version"] == 1


def test_repetition_target_keeps_keys_and_explicit_load_semantics(tmp_path, monkeypatch):
    original = {"reps_min": 8, "reps_max": 10, "rir": 2, "rest_seconds": 180}
    app, path, session, _ = setup_app(tmp_path, monkeypatch, "repetitions", original)
    row = session["sets"][0]
    prefix = "set_" + row["set_uuid"]
    app.text_input(key=prefix + "_target_low").set_value("6")
    app.text_input(key=prefix + "_target_high").set_value("8")
    app.text_input(key=prefix + "_target_load").set_value("0")
    app.selectbox(key=prefix + "_target_load_unit").set_value("level")
    app.selectbox(key=prefix + "_target_load_basis").set_value("assistance_setting")
    app.button(key=prefix + "_target_save").click().run(timeout=30)
    assert not app.exception and not app.error
    with closing(Repository(path)) as repo:
        saved = TrainingService(repo).get_set(row["set_uuid"])
        assert saved["planned"] == {**original, "reps_min": 6, "reps_max": 8,
                                    "load_value": 0, "load_unit": "level", "load_basis": "assistance_setting"}
        assert saved["reps"] is None and saved["load_value"] is None
