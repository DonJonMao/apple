"""Refresh/retry identity is distinct from actual set identity."""
import runpy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from healthzip.advice import freeze_candidate
from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_v14_advice_flow.py")))


def freeze(repo, svc, instance):
    session = svc.get_session(instance["session_id"])
    targets = svc.current_targets(instance["id"])
    return freeze_candidate(repo, svc, session, instance, targets, targets["sets"][0],
                            [50, 52.5, 55], "double_progression")


def test_repeated_request_reuses_candidate_without_new_business_writes(tmp_path, monkeypatch):
    repo, svc, instance, original = HELPERS["_clean_candidate"](tmp_path, monkeypatch)
    version = svc.data_version()
    repeated = freeze(repo, svc, instance)
    assert repeated["candidate_id"] == original["candidate_id"]
    assert repeated["input_snapshot"] == original["input_snapshot"]
    assert svc.data_version() == version
    assert len(svc.list_recommendations()) == 1
    # Unrelated training is not a new intent, and identical sets are not deduped.
    other = svc.start_session("Unrelated")
    ex = svc.add_exercise(other["id"], "psa.ex.barbell_bench_press", instance["condition"])
    a = svc.add_set(ex["id"], planned={"reps_min": 6, "reps_max": 8})
    b = svc.add_set(ex["id"], planned={"reps_min": 6, "reps_max": 8})
    assert a["set_uuid"] != b["set_uuid"]
    assert len(svc.get_session_exercise(ex["id"])["sets"]) == 2
    assert freeze(repo, svc, instance)["candidate_id"] == original["candidate_id"]
    from healthzip.advice import current_use_status
    assert current_use_status(repo, original)["status"] == "active"
    repo.close()


def test_concurrent_new_request_has_one_candidate_and_one_identity(tmp_path, monkeypatch):
    repo, svc, instance, original = HELPERS["_clean_candidate"](tmp_path, monkeypatch)
    target = svc.get_session_exercise(instance["id"])["sets"][0]
    svc.update_set_target(target["id"], {"reps_min": 7, "reps_max": 9, "rir": 2},
                          base_revision=target["revision"])
    path = repo.path
    repo.close()

    barrier = Barrier(3)

    def request(_):
        connection = Repository(path)
        service = TrainingService(connection)
        barrier.wait(timeout=10)
        try:
            return freeze(connection, service, service.get_session_exercise(instance["id"]))["candidate_id"]
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        identities = list(pool.map(request, range(3)))
    assert len(set(identities)) == 1 and identities[0] != original["candidate_id"]
    repo = Repository(path)
    assert repo.one("SELECT count(*) FROM training_recommendation")[0] == 2
    assert repo.one("SELECT count(*) FROM recommendation_request")[0] == 2
    repo.close()


def test_deleted_session_limits_current_use_preserving_snapshot(tmp_path, monkeypatch):
    from healthzip.advice import current_use_status
    repo, svc, instance, original = HELPERS["_clean_candidate"](tmp_path, monkeypatch)
    session = svc.get_session(instance["session_id"])
    svc.delete_session(session["id"], base_revision=session["revision"])
    state = current_use_status(repo, original)
    assert state["status"] == "review_required"
    assert "selected_task_no_longer_available" in state["reason_codes"]
    assert svc.list_recommendations()[0]["input_snapshot"] == original["input_snapshot"]
    repo.close()


def test_modification_and_feedback_retries_are_idempotent(tmp_path, monkeypatch):
    from healthzip.advice import modify_candidate
    repo, svc, instance, original = HELPERS["_clean_candidate"](tmp_path, monkeypatch)
    target = {"reps_min": 7, "reps_max": 8, "rir_min": 2, "rir_max": 2}
    modified = modify_candidate(repo, original, 55, target)
    assert modify_candidate(repo, original, 55, target)["candidate_id"] == modified["candidate_id"]
    assert len(svc.list_recommendations()) == 2
    for choice in ("accepted", "declined", "accepted"):
        svc.recommendation_feedback(modified["candidate_id"], user_choice=choice)
        svc.recommendation_feedback(modified["candidate_id"], user_choice=choice)
    feedback = next(r for r in svc.list_recommendations() if r["candidate_id"] == modified["candidate_id"])["feedback"]
    assert [r["user_choice"] for r in feedback] == ["accepted", "declined", "accepted"]
    repo.close()


def test_concurrent_identical_feedback_writes_one_event(tmp_path, monkeypatch):
    repo, svc, instance, original = HELPERS["_clean_candidate"](tmp_path, monkeypatch)
    path = repo.path
    repo.close()
    barrier = Barrier(3)

    def submit(_):
        connection = Repository(path)
        service = TrainingService(connection)
        barrier.wait(timeout=10)
        try:
            return service.recommendation_feedback(original["candidate_id"], user_choice="accepted")
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(submit, range(3)))
    repo = Repository(path)
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 1
    repo.close()
