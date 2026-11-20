"""Additional real-service checks for redesigned lifecycle and optional jobs."""
from contextlib import closing
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService
from healthzip.ui.training_bridge import build_snapshot, handle_command


def send(repo, state, action, **payload):
    return handle_command(repo, {"id": str(uuid4()), "action": action, "payload": payload}, state)


def setup_session(repo):
    state = {"timezone_name": "Asia/Shanghai", "window_days": 30}
    session = send(repo, state, "start_session")["data"]
    result = send(repo, state, "add_exercises", session_id=session["id"], base_revision=session["revision"],
                 exercises=[{"exercise_id": "psa.ex.barbell_bench_press"}, {"exercise_id": "psa.ex.plank"}])
    return state, result["data"]


def test_direct_title_reorder_idempotence_and_deleted_drafts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        state, session = setup_session(repo)
        assert "训练" in session["name"] and "月" in session["name"] and ":" in session["name"]
        ids = [item["id"] for item in session["exercises"]]
        command = {"id": str(uuid4()), "action": "reorder_exercises", "payload": {
            "session_id": session["id"], "base_revision": session["revision"], "instance_ids": ids[::-1]}}
        saved = handle_command(repo, command, state)
        assert saved["status"] == "saved"
        replay = handle_command(repo, command, state)
        assert replay["replayed"]
        svc = TrainingService(repo)
        actual = svc.get_session(session["id"])
        assert [row["id"] for row in actual["exercises"]] == ids[::-1]
        assert [row["position"] for row in actual["exercises"]] == [0, 1]
        row = actual["exercises"][0]["sets"][0]
        deleted = send(repo, state, "delete_set", set_id=row["set_uuid"], base_revision=row["revision"])
        assert deleted["status"] == "saved"
        assert svc.get_set(row["set_uuid"])["deleted_at"]
        snapshot = build_snapshot(repo, state)
        tombstone = next(item for inst in snapshot["session"]["exercises"] for item in inst["sets"] if item["set_uuid"] == row["set_uuid"])
        assert tombstone["deleted_at"]


def test_bodyweight_assistance_duration_distance_and_historical_draft(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        svc = TrainingService(repo)
        state = {}
        for mode, basis, actual in (
            ("repetitions", "bodyweight_no_external", {"reps": 8, "rir": 0}),
            ("repetitions", "assistance_setting", {"load_value": 0, "load_unit": "level", "reps": 8, "rir": 0}),
            ("duration", "bodyweight_no_external", {"duration_s": 32.5}),
            ("distance", "added_load_kg", {"distance_m": 50.5, "load_value": 12.5, "load_unit": "kg"}),
        ):
            exercise = svc.create_exercise("Synthetic mode", mode, "other", basis)
            session = svc.start_session("Synthetic modes")
            instance = svc.add_exercise(session["id"], exercise["exercise_id"],
                                        {"load_basis": basis, "load_basis_confirmed": True})
            row = svc.add_set(instance["id"], {})
            saved = send(repo, state, "save_set", set_id=row["set_uuid"], base_revision=row["revision"], changes=actual, complete=True)
            assert saved["status"] == "saved", saved
            stored = svc.get_set(row["set_uuid"])
            assert stored["condition"]["load_basis"] == basis
            assert all(stored[key] == value for key, value in actual.items() if key != "load_value")
            draft = svc.add_set(instance["id"], {})
            svc.end_session(session["id"])
            refused = send(repo, state, "save_set", set_id=draft["set_uuid"], base_revision=1, changes=actual)
            assert refused["status"] == "error"
            corrected = send(repo, state, "save_set", set_id=draft["set_uuid"], base_revision=1, changes=actual, correction=True)
            assert corrected["status"] == "saved"
            assert svc.get_set(draft["set_uuid"])["completion_state"] == "draft"


def test_slow_optional_advice_does_not_block_real_set_save(tmp_path, monkeypatch):
    from healthzip.training import current
    from healthzip.ui.training_workbench import _collect_advice, _start_advice

    monkeypatch.chdir(tmp_path)
    entered, release = Event(), Event()

    def slow_advice(repo, instance_id, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"groups": [], "created_at": "synthetic", "instance_id": instance_id}

    monkeypatch.setattr(current, "current_advice", slow_advice)
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        state, session = setup_session(repo)
        instance = session["exercises"][0]
        row = instance["sets"][0]
        command = {"id": str(uuid4()), "action": "advice", "payload": {"instance_id": instance["id"]}}
        try:
            response = _start_advice(repo, command, state)
            assert response["status"] == "saved" and response["data"]["queued"]
            assert entered.wait(2)
            started = monotonic()
            saved = send(repo, state, "save_set", set_id=row["set_uuid"], base_revision=row["revision"],
                         changes={"reps": 8, "rir": 0}, complete=True)
            assert saved["status"] == "saved" and monotonic() - started < 1
            assert not state["advice_job"]["future"].done()
        finally:
            release.set()
        deadline = monotonic() + 5
        while state.get("advice_job") and monotonic() < deadline:
            _collect_advice(state)
            sleep(.01)
        assert state["advice_job_public"]["status"] == "ready"
        # Data changed during computation: the old explanation is never tagged fresh.
        assert state["advice_stale"] is True


def test_catalog_metadata_aliases_and_external_preference_invalidation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "synthetic.sqlite3"
    with closing(Repository(path)) as repo:
        svc = TrainingService(repo)
        state = {}
        identity = "psa.ex.barbell_bench_press"
        svc.add_alias(identity, "Synthetic Alias")
        svc.favorite(identity)
        catalog = send(repo, state, "catalog", query="alias")["data"]
        assert identity in [item["exercise_id"] for item in catalog["items"]]
        item = next(row for row in catalog["search_index"] if row["exercise_id"] == identity)
        assert "synthetic alias" in item["search_terms"] and item["favorite"]
        assert not item["media"] and item["thumbnail"] is None
        assert build_snapshot(repo, state)["catalog"]
        with closing(Repository(path)) as other:
            other_svc = TrainingService(other)
            other_svc.favorite(identity, False)
            other_svc.add_alias(identity, "External Alias")
        assert build_snapshot(repo, state)["catalog"] is None
        refreshed = send(repo, state, "catalog", query="External Alias")["data"]
        assert refreshed["items"][0]["exercise_id"] == identity
        assert refreshed["items"][0]["favorite"] is False
