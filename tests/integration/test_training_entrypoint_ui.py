"""Real application command path; browser suite verifies the component controls."""

import runpy
import socket
from contextlib import closing
from pathlib import Path

from streamlit.testing.v1 import AppTest

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService

UI = runpy.run_path(str(Path(__file__).parents[1] / "strength_ui_harness.py"))


def open_training(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    UI["install"](monkeypatch)

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


def test_visible_new_training_select_exercise_record_actual_and_finish_without_template(tmp_path, monkeypatch):
    app, path = open_training(tmp_path, monkeypatch)
    assert not UI["snapshot"](app)["active_sessions"]
    # No legacy forms or eagerly rendered management panels on the home page.
    assert not app.text_input and not app.tabs
    UI["send"](app, "start_session", {"name": ""})
    session = UI["snapshot"](app)["session"]
    UI["send"](app, "catalog", {"query": "杠铃卧推", "regions": ["chest"]})
    assert "psa.ex.barbell_bench_press" in {
        item["exercise_id"] for item in UI["snapshot"](app)["catalog"]["items"]}
    ack = UI["send"](app, "add_exercises", {"session_id": session["session_uuid"],
        "base_revision": session["revision"], "exercises": ["psa.ex.barbell_bench_press"]})
    assert ack["status"] == "saved"
    session = UI["snapshot"](app)["session"]
    assert session["template_id"] is None and len(session["exercises"]) == 1
    assert len(session["sets"]) == 1  # Freely added actions create one blank draft.
    row = session["sets"][0]
    assert all(row[field] is None for field in ("load_value", "reps", "rir"))
    assert row["completion_state"] == "draft" and not row.get("reference_set")
    assert not row.get("reference_declared_at") and session["completed_sets"] == 0
    ack = UI["send"](app, "save_set", {"set_id": row["set_uuid"], "base_revision": row["revision"],
        "changes": {"load_value": "35.5", "load_unit": "kg", "reps": "9", "rir": None}, "complete": True})
    assert ack["status"] == "saved"
    session = UI["snapshot"](app)["session"]
    ack = UI["send"](app, "end_session", {"session_id": session["session_uuid"], "base_revision": session["revision"]})
    assert ack["status"] == "saved"
    with closing(Repository(path)) as repo:
        svc = TrainingService(repo)
        finished = svc.get_session(session["id"])
        actual = svc.get_set(row["set_uuid"])
        assert finished["session_status"] == "completed" and finished["completed_sets"] == 1
        assert actual["completion_state"] == "completed"
        assert float(actual["load_value"]) == 35.5 and actual["reps"] == 9 and actual["rir"] is None
        assert actual["started_at"] is None and actual["ended_at"]  # No fabricated set start.
        assert not actual["planned"] and not actual.get("reference_set")
        assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
        assert repo.one("SELECT count(*) FROM training_recommendation")[0] == 0


def test_primary_finish_preserves_optional_feedback_and_rejects_invalid_duration(tmp_path, monkeypatch):
    app, path = open_training(tmp_path, monkeypatch)
    UI["send"](app, "start_session")
    session = UI["snapshot"](app)["session"]
    payload = {"session_id": session["session_uuid"], "base_revision": session["revision"]}
    assert UI["send"](app, "end_session", {**payload, "duration_minutes": "invalid"})["status"] == "error"
    with closing(Repository(path)) as repo:
        assert TrainingService(repo).get_session(session["id"])["session_status"] == "in_progress"
    assert UI["send"](app, "end_session", {**payload, "notes": "Synthetic optional session note",
        "duration_minutes": "20", "session_rpe": "6", "rpe_scale": "cr10"})["status"] == "saved"
    with closing(Repository(path)) as repo:
        finished = TrainingService(repo).get_session(session["id"])
        assert finished["session_status"] == "completed"
        assert finished["feedback"]["notes"] == "Synthetic optional session note"
        assert finished["duration_seconds"] == 1200 and finished["session_rpe"] == 6
