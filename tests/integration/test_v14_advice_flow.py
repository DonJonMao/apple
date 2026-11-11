"""v1.4 advice must consume actual current facts from the visible form."""
import runpy
from datetime import datetime, timezone
from pathlib import Path

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_review_candidate_flow.py")))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _reference(svc, instance, *, pain=False):
    row = svc.add_set(instance["id"], {"reference_set": True})
    row = svc.edit_set(row["id"], {"completion_state": "in_progress", "started_at": _now()}, base_revision=row["revision"])
    return svc.edit_set(row["id"], {"completion_state": "completed", "ended_at": _now(),
        "load_value": 50, "load_unit": "kg", "reps": 4 if pain else 12, "rir": 2,
        "pain_flag": pain, "quality_status": "technique_limited" if pain else "acceptable",
        "stop_reason": "pain" if pain else "target_rir"}, base_revision=row["revision"])


def test_f03_current_pain_remains_in_frozen_evidence_and_blocks_upgrade(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    HELPERS["synthetic_authority"](tmp_path / ".local/knowledge", "external_total_kg")
    path = tmp_path / "synthetic-advice.sqlite3"
    repo = Repository(path)
    svc = TrainingService(repo)
    equipment = svc.create_equipment("Synthetic station", "barbell")
    condition = {"equipment_instance_id": equipment["id"], "load_basis": "external_total_kg", "load_basis_confirmed": True,
        "side": "both", "repetition_semantics": "simultaneous", "rom_protocol": "full",
        "settings_confirmed": True, "settings": {"grip": "fixed"},
        "reference_protocol": {"protocol_id": "synthetic", "version": "1", "reference_policy_id": "first-work",
        "effort_protocol": "rir-2", "tempo": "controlled", "rest_protocol": "180-sec"}}
    prior = svc.start_session("prior")
    baseline = _reference(svc, svc.add_exercise(prior["id"], "psa.ex.barbell_bench_press", condition))
    svc.end_session(prior["id"])
    session = svc.start_session("current")
    instance = svc.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
    limited = _reference(svc, instance, pain=True)
    target = svc.add_set(instance["id"], planned={"reps_min": 6, "reps_max": 8, "rir": 2})
    repo.close()
    app = HELPERS["open_app"](path)
    app.selectbox(key="candidate_target_" + instance["id"]).set_value(target["set_uuid"])
    app.text_input(key="loads_" + instance["id"]).set_value("50,52.5,55")
    app.button(key="candidate_" + instance["id"]).click().run(timeout=30)
    assert not app.exception and not app.error
    repo = Repository(path)
    record = TrainingService(repo).list_recommendations()[0]
    assert record["candidate"]["proposed_change"]["load"] is None
    frozen = record["input_snapshot"]
    assert baseline["set_uuid"] in frozen["source_record_ids"]
    assert limited["set_uuid"] in frozen["source_record_ids"]
    assert frozen["advice_context"]["current_session_record_ids"] == [limited["set_uuid"]]
    assert any("pain" in reason for reason in record["candidate"]["eligibility"])
    repo.close()


def _clean_candidate(tmp_path, monkeypatch, strategy="double_progression"):
    from healthzip.advice import freeze_candidate

    monkeypatch.chdir(tmp_path)
    HELPERS["synthetic_authority"](tmp_path / ".local/knowledge", "external_total_kg", [strategy])
    repo = Repository(tmp_path / "synthetic-lifecycle.sqlite3")
    svc = TrainingService(repo)
    equipment = svc.create_equipment("Synthetic station", "barbell")
    condition = {"equipment_instance_id": equipment["id"], "load_basis": "external_total_kg", "load_basis_confirmed": True,
        "side": "both", "repetition_semantics": "simultaneous", "rom_protocol": "full",
        "settings_confirmed": True, "settings": {"grip": "fixed"},
        "reference_protocol": {"protocol_id": "synthetic", "version": "1", "reference_policy_id": "first-work",
        "effort_protocol": "rir-2", "tempo": "controlled", "rest_protocol": "180-sec"}}
    prior = svc.start_session("prior")
    _reference(svc, svc.add_exercise(prior["id"], "psa.ex.barbell_bench_press", condition))
    svc.end_session(prior["id"])
    session = svc.start_session("current")
    instance = svc.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
    svc.add_set(instance["id"], planned={"reps_min": 6, "reps_max": 16 if strategy == "repetition_progression" else 8, "rir": 2})
    targets = svc.current_targets(instance["id"])
    record = freeze_candidate(repo, svc, session, instance, targets, targets["sets"][0], [50, 52.5, 55], strategy)
    assert record["candidate"]["proposed_change"]["load"] == (50 if strategy == "repetition_progression" else 52.5)
    return repo, svc, instance, record


def test_new_symptom_changes_current_use_without_rewriting_frozen_task(tmp_path, monkeypatch):
    from healthzip.advice import current_use_status

    repo, svc, instance, record = _clean_candidate(tmp_path, monkeypatch)
    assert current_use_status(repo, record)["status"] == "active"
    _reference(svc, instance, pain=True)
    refreshed = svc.list_recommendations()[0]
    first = current_use_status(repo, refreshed)
    second = current_use_status(repo, refreshed)
    assert first == second and first["status"] == "review_required"
    assert "pain_reported" in first["reason_codes"]
    assert refreshed["candidate"] == record["candidate"] and refreshed["input_snapshot"] == record["input_snapshot"]
    assert repo.one("SELECT COUNT(*) FROM recommendation_use_event")[0] == 2
    repo.close()


def test_modified_choice_checks_equipment_and_preserves_original_task(tmp_path, monkeypatch):
    import pytest

    from healthzip.advice import modify_candidate

    repo, svc, instance, record = _clean_candidate(tmp_path, monkeypatch)
    target = {"reps_min": 7, "reps_max": 8, "rir_min": 2, "rir_max": 2}
    with pytest.raises(ValueError, match="器械"):
        modify_candidate(repo, record, 54, target)
    assert len(svc.list_recommendations()) == 1
    changed = modify_candidate(repo, record, 55, target)
    assert changed["candidate"]["parent_candidate_id"] == record["candidate_id"]
    assert changed["candidate"]["proposed_change"]["load"] == 55
    assert changed["candidate"]["target_range"] == target
    original = next(r for r in svc.list_recommendations() if r["candidate_id"] == record["candidate_id"])
    assert original["candidate"] == record["candidate"]
    assert svc.current_targets(instance["id"])["sets"][0]["target"]["reps_min"] == 6
    repo.close()


def test_partial_visible_targets_freeze_missing_conditions_without_crashing(tmp_path, monkeypatch):
    repo, svc, instance, original = _clean_candidate(tmp_path, monkeypatch)
    target_id = svc.current_targets(instance["id"])["sets"][0]["set_uuid"]
    path = repo.path
    repo.close()
    app = HELPERS["open_app"](path)
    prefix = "set_" + target_id
    # Clear each target through the actual saved UI form. Every partial shape
    # must retain the missing fact rather than crash or freeze an incomplete load task.
    for missing in ("high", "rir", "low"):
        for field, value in (("low", "6"), ("high", "8"), ("rir", "2")):
            app.text_input(key=prefix + "_target_" + field).set_value("" if field == missing else value)
        app.button(key=prefix + "_target_save").click().run(timeout=30)
        assert not app.exception and not app.error
        app.selectbox(key="candidate_target_" + instance["id"]).set_value(target_id)
        app.text_input(key="loads_" + instance["id"]).set_value("50,52.5,55")
        app.button(key="candidate_" + instance["id"]).click().run(timeout=30)
        assert not app.exception and not app.error
        repo = Repository(path)
        records = TrainingService(repo).list_recommendations()
        saved = records[0]
        assert saved["candidate_id"] != original["candidate_id"]
        assert saved["candidate"]["proposed_change"]["load"] is None
        assert saved["input_snapshot"]["metric_result"]["data_status"] == "insufficient"
        assert saved["input_snapshot"]["selected_target"]["target"][
            {"high": "reps_max", "low": "reps_min", "rir": "rir"}[missing]
        ] is None
        repo.close()
