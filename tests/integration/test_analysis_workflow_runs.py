"""Actual SQLite/analytics workflows: identity, provenance, partial facts and time."""
from datetime import datetime, timedelta, timezone
from zipfile import ZipFile

import pytest

from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.science import definitions
from healthzip.training.service import TrainingService
from healthzip.workflows import (
    WorkflowRequest,
    check_current_use,
    load_analysis,
    load_run,
    resume_workflow,
    run_workflow,
    save_context,
)
from healthzip.workflows.evidence import local_context


def test_five_repository_workflows_keep_snapshots_and_reuse_identical_run(tmp_path):
    repo = Repository(tmp_path / "workflows.sqlite3")
    cutoff = datetime.now(timezone.utc).isoformat()
    for wid in ("W1", "W2", "W3", "W4", "W5"):
        request = WorkflowRequest(wid, cutoff_time=cutoff)
        first = run_workflow(repo, request, knowledge_root=tmp_path / "missing")
        assert first == run_workflow(repo, request, knowledge_root=tmp_path / "missing")
        assert first == load_run(repo, first["run_id"])
        assert [node["node_id"] for node in first["nodes"]] == [f"S{i}" for i in range(7)]
        assert first["nodes"][4]["truth"] is None
        frozen = load_analysis(repo, first["run_id"])
        assert "OBS-CYCLE-RECORDS" not in frozen["observations"]
        assert all(m["cutoff_time"] == cutoff for m in frozen["metrics"].values())
    assert repo.one("SELECT count(*) FROM workflow_run")[0] == 5
    assert len(definitions()) == 77
    repo.close()


def test_forged_results_and_conditions_are_not_workflow_inputs(tmp_path):
    repo = Repository(tmp_path / "boundary.sqlite3")
    with pytest.raises(TypeError):
        WorkflowRequest("W1", metric_result={"metric_id": "STR-10", "value": [{"rir": 2}]})
    with pytest.raises(TypeError):
        run_workflow(repo, {"workflow_id": "W1", "metric_result": {"value": 2}})
    for fields in ({"metric_evidence": {"direct_rir_only": True}}, {"reviewed_principles": []},
                   {"interpretation_setting": "clinical_investigation"}, {"srpe_scale": "Foster_modified_CR10"}):
        with pytest.raises(ValueError, match="unsupported_workflow_context_fields"):
            save_context(repo, fields)
    repo.close()


def test_declaration_time_and_successor_do_not_rewrite_old_run(tmp_path):
    repo = Repository(tmp_path / "resume.sqlite3")
    first = run_workflow(repo, WorkflowRequest("W2"), knowledge_root=tmp_path / "missing")
    context_id = save_context(repo, {"population": "adult_athletes"})
    with pytest.raises(ValueError, match="not_available"):
        run_workflow(repo, WorkflowRequest("W2", cutoff_time=first["request"]["cutoff_time"], context_id=context_id))
    successor = resume_workflow(repo, first["run_id"], context_id=context_id, knowledge_root=tmp_path / "missing")
    assert successor["parent_run_id"] == first["run_id"]
    assert successor["run_id"] != first["run_id"]
    assert load_run(repo, first["run_id"]) == first
    repo.close()


def test_observed_three_hours_remains_a_fact_without_recovery_classification(tmp_path):
    repo = Repository(tmp_path / "sleep.sqlite3")
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=1)
    end = cutoff - timedelta(hours=4)
    archive_path = tmp_path / "sleep.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("export.xml", '<HealthData><Record type="HKCategoryTypeIdentifierSleepAnalysis" '
            'value="HKCategoryValueSleepAnalysisAsleep" sourceName="Synthetic Watch" '
            f'startDate="{(end-timedelta(hours=3)).isoformat()}" endDate="{end.isoformat()}"/></HealthData>')
    assert import_apple_zip(archive_path, repo).status == "completed"
    result = run_workflow(repo, WorkflowRequest("W2", cutoff_time=cutoff.isoformat()), knowledge_root=tmp_path / "missing")
    metric = load_analysis(repo, result["run_id"])["metrics"]["STATE-SLEEP-24H"]
    assert metric["value"]["observed_minutes"] == 180
    assert metric["data_status"] == "partial"
    assert any(f["metric_id"] == "STATE-SLEEP-24H" for f in result["facts"])
    assert result["candidate_ids"] == []
    assert result["nodes"][3]["truth"] is None
    repo.close()


@pytest.mark.parametrize("scale,timing,expected", [
    ("Foster_modified_CR10", "after", True), ("cr10", "after", False),
    ("Foster_modified_CR10", None, False), ("Foster_modified_CR10", "before", False),
])
def test_srpe_conditions_come_from_saved_session_not_page_claims(tmp_path, scale, timing, expected):
    from healthzip.analytics.v13 import analyze
    repo = Repository(tmp_path / "srpe.sqlite3")
    svc = TrainingService(repo)
    now = datetime.now(timezone.utc)
    end = now - timedelta(hours=1)
    session = svc.start_session("sRPE fixture", started_at=(end-timedelta(minutes=60)).isoformat())
    collected = (end + timedelta(minutes=15 if timing == "after" else -15)).isoformat() if timing else None
    svc.end_session(session["id"], ended_at=end.isoformat(), session_rpe=6, rpe_scale=scale,
        rpe_collected_at=collected, duration_seconds=3600, duration_protocol="user_elapsed_including_rest")
    context_id = save_context(repo, {"population": "adult_athletes"})
    cutoff = datetime.now(timezone.utc).isoformat()
    analysis = analyze(repo, cutoff_time=cutoff, use_cache=False)
    sessions = svc.sessions_as_of(cutoff_time=cutoff)
    context = local_context("LOAD-SRPE-AU", analysis["metrics"]["LOAD-SRPE-AU"], sessions,
                            {"values": {"population": "adult_athletes"}, "context_id": context_id})
    assert (context["srpe_scale"] == "Foster_modified_CR10" and
            context["srpe_collection"] == "retrospective_after_session") is expected
    # Later edits to notes must not become a new collection time.
    row = svc.get_session(session["id"])
    svc.update_session(session["id"], {"notes": "Later note"}, base_revision=row["revision"])
    assert svc.get_session(session["id"])["session_rpe_collected_at"] == collected
    repo.close()


def test_workflow_current_use_tracks_revisions_not_unrelated_training(tmp_path, monkeypatch):
    import runpy
    from pathlib import Path
    fixture = runpy.run_path(str(Path(__file__).with_name("test_analysis_w1_flow.py")))["history"]
    repo, svc, instance, target, ids = fixture(tmp_path, monkeypatch, approved=False)
    request = WorkflowRequest("W1", cutoff_time=datetime.now(timezone.utc).isoformat(),
        session_id=instance["session_id"], session_exercise_id=instance["id"], selected_set_uuid=target["set_uuid"])
    first = run_workflow(repo, request, knowledge_root=tmp_path / "missing")
    assert check_current_use(repo, first["run_id"], knowledge_root=tmp_path / "missing")["status"] == "current"
    other = svc.start_session("Unrelated")
    svc.add_exercise(other["id"], "psa.ex.goblet_squat", {})
    assert check_current_use(repo, first["run_id"], knowledge_root=tmp_path / "missing")["status"] == "current"
    assert run_workflow(repo, request, knowledge_root=tmp_path / "missing")["run_id"] == first["run_id"]
    actual = svc.get_set(ids[-1])
    svc.edit_set(actual["id"], {"reps": 11}, base_revision=actual["revision"])
    state = check_current_use(repo, first["run_id"], knowledge_root=tmp_path / "missing")
    assert state["status"] == "needs_review"
    assert state["reason_codes"] == ["relevant_records_or_targets_changed"]
    assert load_run(repo, first["run_id"]) == first
    successor = resume_workflow(repo, first["run_id"], knowledge_root=tmp_path / "missing")
    assert successor["parent_run_id"] == first["run_id"]
    assert load_analysis(repo, successor["run_id"])["metrics"]["STR-11"]["value"][-1]["reps"] == 11
    repo.close()


@pytest.mark.parametrize("score", [8, 16])
def test_borg_session_score_is_preserved_but_not_CR10_load(tmp_path, score):
    repo = Repository(tmp_path / "borg.sqlite3")
    svc = TrainingService(repo)
    end = datetime.now(timezone.utc) - timedelta(hours=1)
    session = svc.start_session("Borg fixture", started_at=(end-timedelta(minutes=50)).isoformat())
    svc.end_session(session["id"], ended_at=end.isoformat(), session_rpe=score, rpe_scale="borg6_20",
        rpe_collected_at=(end+timedelta(minutes=15)).isoformat(),
        duration_seconds=3000, duration_protocol="user_elapsed_including_rest")
    result = run_workflow(repo, WorkflowRequest("W2"), knowledge_root=tmp_path / "missing")
    metrics = load_analysis(repo, result["run_id"])["metrics"]
    assert metrics["LOAD-SRPE"]["value"][0]["session_rpe"] == score
    assert metrics["LOAD-SRPE"]["value"][0]["recorded_scale_range"] == [6, 20]
    assert metrics["LOAD-SRPE-AU"]["value"][0]["AU"] is None
    assert metrics["LOAD-SRPE-AU"]["data_status"] == "insufficient"
    repo.close()


def test_workflow_atomic_failure_has_no_orphan_analysis(tmp_path):
    import sqlite3
    repo = Repository(tmp_path / "rollback.sqlite3")
    repo.conn.execute("CREATE TRIGGER synthetic_abort BEFORE INSERT ON workflow_run BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
        run_workflow(repo, WorkflowRequest("W3"), knowledge_root=tmp_path / "missing")
    assert repo.one("SELECT count(*) FROM workflow_run")[0] == 0
    assert repo.one("SELECT count(*) FROM analysis_run")[0] == 0
    assert not repo.conn.in_transaction
    repo.close()


def test_concurrent_fixed_request_returns_one_run_and_snapshot(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    path = tmp_path / "concurrent.sqlite3"
    Repository(path).close()
    barrier = Barrier(3)
    request = WorkflowRequest("W3", cutoff_time=datetime.now(timezone.utc).isoformat())

    def submit(_):
        repo = Repository(path)
        barrier.wait(timeout=10)
        try:
            return run_workflow(repo, request, knowledge_root=tmp_path / "missing")["run_id"]
        finally:
            repo.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(submit, range(3)))
    assert len(set(ids)) == 1
    repo = Repository(path)
    assert repo.one("SELECT count(*) FROM workflow_run")[0] == 1
    assert repo.one("SELECT count(*) FROM analysis_run")[0] == 1
    repo.close()
