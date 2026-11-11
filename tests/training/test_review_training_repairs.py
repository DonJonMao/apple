"""Review reproductions against real storage; no hidden scientific assumptions."""

from datetime import datetime, timezone

import pytest

from healthzip.db.repository import Repository
from healthzip.training import TrainingService


@pytest.fixture
def service(tmp_path):
    repo = Repository(tmp_path / "review.sqlite3")
    yield TrainingService(repo)
    repo.close()


@pytest.mark.parametrize("from_template", [False, True])
def test_r07_current_explicit_targets_feed_saved_template_and_keep_original(service, from_template):
    exercise = "psa.ex.smith_incline_press"
    original = {"sets": [{"reps_min": 10, "reps_max": 12, "rir": 3}]} if from_template else {}
    if from_template:
        template = service.create_template(
            "原计划", [{"exercise_id": exercise, "condition": {}, "targets": original}]
        )
        session = service.start_session(template_id=template["id"])
        instance = session["exercises"][0]
        row = session["sets"][0]
    else:
        session = service.start_session()
        instance = service.add_exercise(session["id"], exercise, {})
        row = service.add_set(instance["id"])
    service.update_set_target(
        row["id"], {"reps_min": 6, "reps_max": 8, "rir": 2}, base_revision=row["revision"]
    )
    saved = service.save_session_as_template(session["id"], "使用当前明确目标")
    assert saved["items"][0]["targets"]["sets"][0]["reps_max"] == 8
    current = service.current_targets(instance["id"])
    assert current["sets"][0]["target"]["rir"] == 2
    assert current["original_targets"] == original
    assert current["revision"]
    if from_template:
        assert (
            service.get_session(session["id"])["plan_snapshot"]["items"][0]["targets"]["sets"][0][
                "reps_max"
            ]
            == 12
        )


def test_r09_neighbor_endpoint_edit_rederives_rest_and_missing_start_clears(service):
    session = service.start_session()
    exercise = service.add_exercise(session["id"], "psa.ex.smith_incline_press", {})
    first = service.add_set(
        exercise["id"],
        {
            "completion_state": "completed",
            "reps": 10,
            "started_at": "2026-11-10T10:00:00+08:00",
            "ended_at": "2026-11-10T10:01:00+08:00",
        },
    )
    second = service.add_set(
        exercise["id"],
        {
            "completion_state": "completed",
            "reps": 10,
            "started_at": "2026-11-10T10:03:00+08:00",
            "ended_at": "2026-11-10T10:04:00+08:00",
        },
    )
    assert second["rest_actual_s"] == 120
    prior_cutoff = datetime.now(timezone.utc).isoformat()
    service.edit_set(
        first["id"], {"ended_at": "2026-11-10T10:02:00+08:00"}, base_revision=first["revision"]
    )
    revised = service.get_set(second["id"])
    assert revised["rest_actual_s"] == 60
    before = next(
        r for r in service.history_as_of(cutoff_time=prior_cutoff) if r["id"] == second["id"]
    )
    assert before["rest_actual_s"] == 120
    service.edit_set(second["id"], {"started_at": None}, base_revision=revised["revision"])
    assert service.get_set(second["id"])["rest_actual_s"] is None


def test_r09_clearing_prior_end_does_not_invent_a_new_endpoint(service):
    session = service.start_session()
    instance = service.add_exercise(session["id"], "psa.ex.smith_incline_press", {})
    first = service.add_set(
        instance["id"],
        {
            "completion_state": "completed",
            "reps": 8,
            "started_at": "2026-11-10T10:00:00+08:00",
            "ended_at": "2026-11-10T10:01:00+08:00",
        },
    )
    second = service.add_set(
        instance["id"],
        {
            "completion_state": "completed",
            "reps": 8,
            "started_at": "2026-11-10T10:03:00+08:00",
            "ended_at": "2026-11-10T10:04:00+08:00",
        },
    )
    service.edit_set(first["id"], {"ended_at": None}, base_revision=first["revision"])
    assert service.get_set(first["id"])["ended_at"] is None
    assert service.get_set(second["id"])["rest_actual_s"] is None


def test_r09_user_rest_is_separate_from_derivation_and_deletion_rechecks_neighbor(service):
    session = service.start_session()
    instance = service.add_exercise(session["id"], "psa.ex.smith_incline_press", {})
    first = service.add_set(
        instance["id"],
        {
            "completion_state": "completed",
            "reps": 8,
            "started_at": "2026-11-10T10:00:00+08:00",
            "ended_at": "2026-11-10T10:01:00+08:00",
        },
    )
    second = service.add_set(
        instance["id"],
        {
            "completion_state": "completed",
            "reps": 8,
            "started_at": "2026-11-10T10:03:00+08:00",
            "ended_at": "2026-11-10T10:04:00+08:00",
            "rest_recorded_s": 115,
            "rest_recorded_method": "stopwatch",
        },
    )
    assert second["rest_actual_s"] == 120 and second["rest_recorded_s"] == 115
    assert second["rest_derivation"]["previous_set_uuid"] == first["set_uuid"]
    deletion = service.delete_set(first["id"], base_revision=first["revision"])
    after = service.get_set(second["id"])
    assert after["rest_actual_s"] is None and after["rest_recorded_s"] == 115
    service.undo_event(deletion["event_id"], base_revision=deletion["revision"])
    assert service.get_set(second["id"])["rest_actual_s"] == 120
    assert service.get_set(second["id"])["rest_recorded_method"] == "stopwatch"


def test_r07_target_version_changes_only_with_target_content(service):
    session = service.start_session()
    instance = service.add_exercise(session["id"], "psa.ex.smith_incline_press", {})
    row = service.add_set(instance["id"], planned={"reps_min": 6, "reps_max": 8})
    original = service.current_targets(instance["id"])
    changed = service.edit_set(row["id"], {"reps": 7}, base_revision=row["revision"])
    assert service.current_targets(instance["id"])["revision"] == original["revision"]
    service.update_set_target(
        row["id"], {"reps_min": 8, "reps_max": 10}, base_revision=changed["revision"]
    )
    assert service.current_targets(instance["id"])["revision"] != original["revision"]


def test_r09_csv_roundtrip_preserves_user_rest_and_missing_endpoint(service, tmp_path):
    from healthzip.training.exchange import export_training, import_training

    session = service.start_session()
    instance = service.add_exercise(session["id"], "psa.ex.smith_incline_press", {})
    row = service.add_set(
        instance["id"],
        {
            "completion_state": "completed",
            "reps": 8,
            "rest_recorded_s": 115,
            "rest_recorded_method": "stopwatch",
            "ended_at": None,
        },
    )
    assert row["rest_actual_s"] is None
    path = export_training(service.repo, tmp_path / "rest.csv")
    target = Repository(tmp_path / "rest-import.sqlite3")
    result = import_training(target, path)
    assert result["new"] == 1 and result["invalid"] == 0
    restored = TrainingService(target).get_set(row["set_uuid"])
    assert restored["rest_recorded_s"] == 115 and restored["rest_recorded_method"] == "stopwatch"
    assert restored["started_at"] is None and restored["rest_actual_s"] is None
    assert restored["ended_at"] is None
    assert restored["rest_derivation"]["reason"] == "missing_current_start"
    target.close()


def test_r07_skipped_execution_does_not_erase_explicit_plan(service):
    session = service.start_session()
    instance = service.add_exercise(session["id"], "psa.ex.smith_incline_press", {})
    row = service.add_set(instance["id"], planned={"reps_min": 6, "reps_max": 8, "rir": 2})
    original = service.current_targets(instance["id"])
    service.edit_set(row["id"], {"completion_state": "skipped"}, base_revision=row["revision"])
    current = service.current_targets(instance["id"])
    assert current["revision"] == original["revision"]
    assert current["sets"][0]["completion_state"] == "skipped"
    saved = service.save_session_as_template(session["id"], "保留跳过组目标")
    assert saved["items"][0]["targets"]["sets"][0]["reps_max"] == 8


def test_r09_derived_rest_does_not_resolve_an_unrelated_user_conflict(service):
    session = service.start_session()
    instance = service.add_exercise(session["id"], "psa.ex.smith_incline_press", {})
    first = service.add_set(
        instance["id"],
        {
            "completion_state": "completed",
            "reps": 8,
            "started_at": "2026-11-10T10:00:00+08:00",
            "ended_at": "2026-11-10T10:01:00+08:00",
        },
    )
    second = service.add_set(
        instance["id"],
        {
            "completion_state": "completed",
            "reps": 8,
            "started_at": "2026-11-10T10:03:00+08:00",
            "ended_at": "2026-11-10T10:04:00+08:00",
        },
    )
    service.edit_set(second["id"], {"reps": 9}, base_revision=second["revision"])
    conflict = service.edit_set(second["id"], {"reps": 7}, base_revision=second["revision"])
    service.edit_set(
        first["id"], {"ended_at": "2026-11-10T10:02:00+08:00"}, base_revision=first["revision"]
    )
    cutoff = datetime.now(timezone.utc).isoformat()
    observed = next(
        row for row in service.history_as_of(cutoff_time=cutoff) if row["id"] == second["id"]
    )
    assert observed["rest_actual_s"] == 60 and observed["conflicted"]
    service.resolve_conflict(conflict["conflict_id"], choice="apply_proposed")
    current = next(
        row
        for row in service.history_as_of(cutoff_time=datetime.now(timezone.utc).isoformat())
        if row["id"] == second["id"]
    )
    assert current["reps"] == 7 and not current["conflicted"]
    historical = next(
        row for row in service.history_as_of(cutoff_time=cutoff) if row["id"] == second["id"]
    )
    assert historical["conflicted"]
