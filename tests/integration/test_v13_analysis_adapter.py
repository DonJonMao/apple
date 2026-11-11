from datetime import datetime, timezone

from healthzip.analytics.v13 import _outcome, analyze, persist
from healthzip.db.repository import Repository
from healthzip.state_log import save_state
from healthzip.training.service import TrainingService


def test_actual_training_rows_feed_metric_report_and_invalidation(tmp_path):
    repo = Repository(tmp_path / "adapter.sqlite3")
    svc = TrainingService(repo)
    item = svc.search_exercises("上斜史密斯")[0]
    machine = svc.create_equipment("test", "smith")
    condition = {"equipment_instance_id": machine["id"], "load_basis": "plates_per_side_kg",
                 "load_basis_confirmed": True, "side": "both", "repetition_semantics": "simultaneous",
                 "rom_protocol": "user_declared", "settings": {"angle": 30}, "settings_confirmed": True,
                 "symmetric_loading": True}
    session = svc.start_session("synthetic")
    exercise = svc.add_exercise(session["id"], item["exercise_id"], condition)
    first = svc.add_set(exercise["id"], {"load_unit": "kg"})
    first = svc.edit_set(first["id"], {"reference_set": True}, base_revision=first["revision"])
    completed = svc.edit_set(first["id"], {"completion_state": "completed", "load_value": "30", "reps": 10,
                "rir": 2, "quality_status": "acceptable", "stop_reason": "plan_target", "ended_at": datetime.now(timezone.utc).isoformat()}, base_revision=first["revision"])
    svc.add_set(exercise["id"], {"load_value": "30", "load_unit": "kg", "reps": 0,
                "completion_state": "aborted", "ended_at": datetime.now(timezone.utc).isoformat()})
    save_state(repo, fatigue=2, soreness=1, pain="denied")
    result = analyze(repo)
    assert len(result["metrics"]) == 77
    counts = result["metrics"]["STR-01"]["value"]
    assert counts["completed_work_parent_sets"] == 1
    assert counts["failed_attempts"] == 1
    assert result["metrics"]["STATE-FATIGUE"]["value"] is not None
    assert result["metrics"]["ENERGY-ABSOLUTE-INTAKE"]["data_status"] == "not_identifiable"
    run = persist(repo, result)
    assert repo.one("SELECT invalidated_at FROM analysis_run WHERE run_id=?", (run,))[0] is None
    svc.edit_set(completed["id"], {"reps": 8}, base_revision=completed["revision"])
    assert repo.one("SELECT invalidated_at FROM analysis_run WHERE run_id=?", (run,))[0] is not None
    historical = analyze(repo, cutoff_time=result["cutoff_time"])
    old = historical["metrics"]["STR-02"]["value"]
    assert any(x["reps"] == 10 for x in old)
    pending = svc.pending_invalidations()
    assert pending
    persist(repo, historical)
    assert svc.pending_invalidations() == pending
    repo.close()


def test_frozen_template_denominator_counts_independent_sessions(tmp_path):
    repo = Repository(tmp_path / "plans.sqlite3")
    svc = TrainingService(repo)
    exercise = svc.search_exercises("上斜史密斯")[0]
    template = svc.create_template("synthetic", [{"exercise_id": exercise["exercise_id"],
        "condition": {}, "targets": {"sets": [{"reps_min": 8, "reps_max": 10}, {"reps_min": 8, "reps_max": 10}]}}])
    first = svc.start_session(template_id=template["id"])
    second = svc.start_session(template_id=template["id"])
    row = first["sets"][0]
    svc.edit_set(row["set_uuid"], {"completion_state": "completed", "reps": 8}, base_revision=row["revision"])
    result = analyze(repo)["metrics"]["STR-09"]
    assert result["value"]["planned"] == 4
    assert result["value"]["completed"] == 1
    assert result["value"]["unknown"] == 3
    assert first["id"] != second["id"]
    repo.close()


def test_recommendation_success_requires_frozen_load_and_semantics():
    from healthzip.science import evaluate
    timestamp = "2026-11-11T08:00:00+00:00"
    recommendation = {"candidate_id": "test", "created_at": "2026-11-11T07:59:30+00:00", "cutoff_time": "2026-11-11T07:59:00+00:00",
        "candidate": {"target_session": "session", "action_kind": "double_progression_candidate", "proposed_change": {
            "load": 32.5, "load_unit": "kg", "load_basis": "plates_per_side_kg"},
            "target_range": {"reps_min": 8, "reps_max": 8, "rir_min": 2, "rir_max": 2}},
        "input_snapshot": {"condition": {"condition_key": "same"}, "session_exercise_id": "action"}}
    feedback = {"user_choice": "accepted", "execution_state": "executed", "actual_record_ids": ["set"],
                "recorded_at": timestamp, "occurred_at": timestamp}
    actual = {"set_uuid": "set", "condition_key": "same", "load_value": "30", "load_unit": "kg",
              "load_basis": "plates_per_side_kg", "measurement_mode": "repetitions", "set_type": "work", "reps": 8, "rir": 2, "quality_status": "acceptable", "completion_state": "completed",
              "session_uuid": "session", "session_id": 1, "session_exercise_id": "action", "reference_set": True,
              "reference_declared_at": "2026-11-11T07:59:40+00:00", "started_at": "2026-11-11T07:59:45+00:00", "ended_at": timestamp}
    def success(row, feedback_override=None):
        metric = evaluate("STR-27", [], cutoff_time="2026-11-11T09:00:00+00:00",
                          window_start="2026-11-11T00:00:00+00:00", window_end="2026-11-12T00:00:00+00:00",
                          context={"recommendation_outcomes": [_outcome(recommendation, feedback_override or feedback, [row])]})
        return metric["value"][0]["short_term_success"]
    assert success(actual) is False
    assert success({**actual, "load_value": "32.5"}) is True
    assert success({**actual, "load_value": "32.5", "load_basis": "external_total_kg"}) is False
    assert success({**actual, "load_value": "32.5", "rir": None}) is None
    for state in ("unknown", "not_executed", "partially_executed"):
        assert success({**actual, "load_value": "32.5"}, {**feedback, "execution_state": state}) is None
    for wrong in ({"session_uuid": "other"}, {"session_exercise_id": "other"},
                  {"started_at": "2026-11-10T08:00:00+00:00"}, {"reference_set": False},
                  {"started_at": "2026-11-11T07:59:20+00:00"}, {"reference_declared_at": timestamp},
                  {"conflicted": True}, {"deleted_at": timestamp}, {"set_type": "warmup"}):
        assert success({**actual, "load_value": "32.5", **wrong}) is None
