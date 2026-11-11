"""End-to-end invariants of real Repository-backed v1.3 training records."""

from datetime import datetime, timedelta, timezone

import pytest

from healthzip.db.repository import Repository
from healthzip.strength_log import append_quick_strength_set
from healthzip.training import TrainingError, TrainingService, load_change, load_semantics

SMITH = "psa.ex.smith_incline_press"


@pytest.fixture
def service(tmp_path):
    repo = Repository(tmp_path / "training.sqlite3")
    svc = TrainingService(repo)
    yield svc
    repo.close()


def condition(svc, *, equipment=None, basis="plates_per_side_kg"):
    equipment = equipment or svc.create_equipment("Synthetic Smith A", "smith")["id"]
    return {
        "equipment_instance_id": equipment,
        "load_basis": basis,
        "load_basis_confirmed": True,
        "settings_confirmed": True,
        "settings": {"bench_angle_degrees": 30, "rail_angle_degrees": 0},
        "side": "both",
        "repetition_semantics": "simultaneous",
        "rom_protocol": "user_confirmed_full",
        "symmetric_loading": True,
        "effective_bar_mass_kg": None,
    }


def session_with_exercise(svc, cond=None, *, when=None):
    session = svc.start_session("胸部训练", started_at=when)
    instance = svc.add_exercise(session["id"], SMITH, cond or condition(svc))
    return session, instance


def actual(load=30, reps=10, **extra):
    return {
        "completion_state": "completed",
        "load_value": load,
        "load_unit": "kg",
        "reps": reps,
        "rir": 2,
        "stop_reason": "plan_target",
        **extra,
    }


def test_required_chest_smith_plan_roundtrip_and_feedback(service):
    c = condition(service)
    template = service.create_template(
        "胸部计划",
        [
            {
                "exercise_id": SMITH,
                "condition": c,
                "targets": {
                    "sets": [
                        {
                            "set_type": "work",
                            "reps_min": 8,
                            "reps_max": 10,
                            "rir": 2,
                            "rest_seconds": 120,
                        }
                    ]
                },
            }
        ],
    )
    first = service.start_session(template_id=template["id"])
    planned = first["sets"][0]
    assert planned["reps"] is None and planned["completion_state"] == "draft"
    assert first["completed_sets"] == 0
    set1 = service.edit_set(
        planned["id"], actual(), base_revision=1, event_id="smith-first-completed"
    )
    end = service.end_session(
        first["id"],
        feedback={"notes": "已完成计划"},
        session_rpe=7,
        rpe_scale="cr10",
        duration_seconds=3600,
        duration_protocol="elapsed_wall_clock",
    )
    assert end["session_rpe"] == 7 and end["completed_sets"] == 1
    second = service.start_session(template_id=template["id"])
    previous = service.last_values(second["exercises"][0]["id"])
    assert previous["suggested_actual"]["load_value"] == "30"
    assert previous["suggested_actual"]["completion_state"] == "draft"
    assert service.get_session(second["id"])["completed_sets"] == 0
    # Plan change cannot alter the already frozen session snapshot.
    service.update_template(template["id"], "胸部计划更新", [], base_revision=1)
    assert service.get_session(first["id"])["plan_snapshot"]["version"] == 1
    second_set = service.edit_set(second["sets"][0]["id"], actual(32.5, 8), base_revision=1)
    delta = load_change(set1, second_set, c)
    assert delta["plates_total_change_kg"] == 5
    assert delta["external_total_change_kg"] is None
    assert delta["external_total_percent_change"] is None
    service.end_session(second["id"], feedback={"notes": "完成8次"})
    assert service.repo.count("strength_session") == 2
    assert service.repo.count("strength_set") == 2
    assert service.get_session(first["id"])["sets"][0]["load_basis"] == "plates_per_side_kg"


def test_same_day_distinct_sessions_identical_real_sets_and_retry(service):
    first, instance = session_with_exercise(service)
    a = service.add_set(instance["id"], actual(), event_id="real-set-1")
    b = service.add_set(instance["id"], actual(), event_id="real-set-2")
    retry = service.add_set(instance["id"], actual(), event_id="real-set-1")
    assert a["id"] != b["id"]
    assert retry["id"] == a["id"] and retry["replayed"]
    assert service.get_session(first["id"])["completed_sets"] == 2
    service.end_session(first["id"])
    assert service.add_set(instance["id"], actual(), event_id="real-set-1")["replayed"]
    second, _ = session_with_exercise(service)
    assert first["id"] != second["id"]
    with pytest.raises(TrainingError, match="event_id"):
        service.add_set(instance["id"], actual(32.5), event_id="real-set-1")


def test_draft_copy_zero_actual_rir_unknown_and_failures_kept(service):
    session, instance = session_with_exercise(service)
    draft = service.add_set(instance["id"], {"load_value": 30, "load_unit": "kg", "reps": 10})
    assert draft["weight_kg"] is None and draft["rir"] is None
    assert service.get_session(session["id"])["completed_sets"] == 0
    failed = service.add_set(
        instance["id"],
        {
            "completion_state": "aborted",
            "load_value": 35,
            "load_unit": "kg",
            "reps": 0,
            "stop_reason": "technical_limit",
        },
    )
    assert failed["reps"] == 0
    assert service.get_session(session["id"])["completed_sets"] == 0
    with pytest.raises(TrainingError, match="完成组"):
        service.add_set(instance["id"], actual(reps=0))


def test_restart_draft_outbox_retry_and_conflict_resolution(tmp_path):
    path = tmp_path / "offline.sqlite3"
    repo = Repository(path)
    svc = TrainingService(repo)
    session, instance = session_with_exercise(svc)
    draft = svc.add_set(instance["id"], {"load_value": 30, "load_unit": "kg", "reps": 10})
    svc.queue_event(
        "edit_set",
        {"set_id": draft["id"], "changes": actual(), "base_revision": 1},
        event_id="offline-complete",
    )
    repo.close()
    repo = Repository(path)
    svc = TrainingService(repo)
    assert svc.get_set(draft["id"])["completion_state"] == "draft"
    results = svc.replay_outbox()
    assert results[0]["status"] == "applied"
    assert svc.replay_outbox() == []
    assert svc.get_session(session["id"])["completed_sets"] == 1
    conflict = svc.edit_set(draft["id"], {"reps": 8}, base_revision=1, event_id="other-device-edit")
    assert conflict["status"] == "conflicted"
    assert svc.get_set(draft["id"])["reps"] == 10
    assert svc.list_conflicts()[0]["proposed"]["reps"] == 8
    resolved = svc.resolve_conflict(conflict["conflict_id"], choice="apply_proposed")
    assert resolved["reps"] == 8 and resolved["revision"] == 3
    assert svc.list_conflicts() == []
    repo.close()


def test_delete_undo_and_revision_do_not_rewrite_recommendation(service):
    session, instance = session_with_exercise(service)
    done = service.add_set(instance["id"], actual())
    candidate = {
        "candidate_id": "candidate-synthetic",
        "target_session": session["session_uuid"],
        "action_kind": "review_then_try",
        "proposed_change": {"reps": 10},
        "target_range": None,
        "reason_evidence_ids": ["synthetic_fact"],
        "eligibility": "requires_user_confirmation",
        "uncertainty": {"kind": "not_estimable"},
        "verification_protocol": "Warm up then reassess",
        "followup_window": "next_session",
        "rule_version": "synthetic-test-v1",
        "user_choice": None,
    }
    cutoff = datetime.now(timezone.utc).isoformat()
    frozen = service.record_recommendation(
        candidate,
        {"source_record_ids": [done["set_uuid"]], "reps": 10},
        cutoff_time=cutoff,
        theory_version="none_reviewed",
    )
    deletion = service.delete_set(done["id"], base_revision=1)
    assert service.get_session(session["id"])["completed_sets"] == 0
    restored = service.undo_event(deletion["event_id"], base_revision=2)
    assert restored["deleted_at"] is None and restored["revision"] == 3
    assert service.get_session(session["id"])["completed_sets"] == 1
    saved = service.list_recommendations()[0]
    assert saved["input_snapshot"] == frozen["input_snapshot"]
    assert saved["stale"] == 1
    assert service.pending_invalidations()
    service.recommendation_feedback(
        candidate["candidate_id"],
        user_choice="declined",
        execution_state="not_executed",
        nonexecution_reason="用户选择维持",
    )
    assert service.list_recommendations()[0]["feedback"][0]["user_choice"] == "declined"
    with pytest.raises(TrainingError, match="冻结"):
        service.record_recommendation(
            {**candidate, "proposed_change": {"reps": 8}},
            {},
            cutoff_time=cutoff,
            theory_version="none_reviewed",
        )


def test_snapshot_time_no_backfill_or_future_leakage(service):
    session, instance = session_with_exercise(service)
    cutoff = datetime.now(timezone.utc)
    backfill_time = (cutoff - timedelta(days=365)).isoformat()
    backfill = service.add_set(instance["id"], actual(ended_at=backfill_time))
    result = service.last_values(instance["id"], cutoff_time=cutoff.isoformat())
    assert result["status"] == "insufficient"
    assert service.history_as_of(cutoff_time=cutoff.isoformat()) == []
    after_first = datetime.now(timezone.utc).isoformat()
    service.edit_set(backfill["id"], {"reps": 8}, base_revision=1)
    historical = service.history_as_of(cutoff_time=after_first)
    assert len(historical) == 1 and historical[0]["reps"] == 10
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    service.add_set(instance["id"], actual(ended_at=future))
    assert len(service.history_as_of(cutoff_time=datetime.now(timezone.utc).isoformat())) == 1


def test_catalog_navigation_custom_and_identity_versions(service):
    assert len(service.search_exercises()) == 46
    assert service.search_exercises("史密斯上斜卧推")[0]["exercise_id"] == SMITH
    assert len(service.search_exercises(regions=["chest"], equipment=["smith"])) == 1
    service.favorite(SMITH)
    service.add_alias(SMITH, "我的胸推动作")
    assert service.search_exercises("我的胸推动作", view="favorites")[0]["exercise_id"] == SMITH
    custom = service.create_exercise(
        "我的等长支撑", "duration", "bodyweight", "bodyweight_no_external"
    )
    assert custom["scientific_review"]["status"] == "unreviewed"
    renamed = service.update_exercise(
        custom["exercise_id"], {"name_zh": "支撑改名"}, base_revision=1
    )
    assert renamed["exercise_id"] == custom["exercise_id"] and renamed["definition_version"] == 1
    assert renamed["revision"] == 2
    changed = service.update_exercise(
        custom["exercise_id"], {"recording_mode": "distance"}, base_revision=2
    )
    assert changed["definition_version"] == 2
    assert service.get_exercise(custom["exercise_id"], 1)["recording_mode"] == "duration"
    another = TrainingService(service.repo, user_id="different-local-profile")
    assert another.search_exercises(view="custom") == []
    assert another.search_exercises(view="favorites") == []
    with pytest.raises(TrainingError):
        another.get_exercise(custom["exercise_id"])


def test_custom_isometric_assisted_and_device_mismatch(service):
    custom = service.create_exercise(
        "自定义等长支撑", "duration", "bodyweight", "bodyweight_no_external"
    )
    eq = service.create_equipment("我的地垫", "bodyweight")
    c = condition(service, equipment=eq["id"], basis="bodyweight_no_external")
    session = service.start_session()
    instance = service.add_exercise(session["id"], custom["exercise_id"], c)
    done = service.add_set(instance["id"], {"completion_state": "completed", "duration_s": 60})
    assert done["duration_s"] == 60 and done["reps"] is None and done["weight_kg"] is None
    assert done["condition"]["measurement_mode"] == "duration"
    assisted = load_change(
        {"load_value": 30, "load_unit": "kg"},
        {"load_value": 25, "load_unit": "kg"},
        {"load_basis": "assistance_setting"},
    )
    assert assisted["task_direction"] == "harder"
    assert assisted["external_total_change_kg"] is None
    with pytest.raises(TrainingError, match="器械实例"):
        service.add_exercise(session["id"], SMITH, c)
    a, b = condition(service), condition(service)
    _, x = session_with_exercise(service, a)
    _, y = session_with_exercise(service, b)
    assert x["condition_key"] != y["condition_key"]


def test_unknown_condition_is_not_wildcard_and_load_basis_confirmed(service):
    session = service.start_session()
    unknown = service.add_exercise(session["id"], SMITH, {})
    assert unknown["condition_key"] is None
    assert service.last_values(unknown["id"])["reason"] == "comparability_unknown"
    with pytest.raises(TrainingError, match="确认"):
        service.add_exercise(session["id"], SMITH, {"load_basis": "plates_per_side_kg"})
    for definition in service.search_exercises():
        assert all(
            not item.get("quantitative_use_allowed")
            for item in definition.get("muscle_participation_proposals", [])
        )


def test_timer_persists_and_never_fabricates_actual_rest(service):
    session, instance = session_with_exercise(service)
    anchor = "2026-11-10T10:00:00+08:00"
    service.start_timer(session["id"], target_seconds=60, at=anchor)
    zero = service.timer_status(session["id"], as_of="2026-11-10T10:01:10+08:00")
    assert zero["remaining_seconds"] == 0 and zero["actual_rest_s"] is None
    service.rest_timer(session["id"], "pause", at="2026-11-10T10:01:10+08:00")
    assert (
        service.timer_status(session["id"], as_of="2026-11-10T11:01:10+08:00")["elapsed_seconds"]
        == 70
    )
    service.rest_timer(session["id"], "resume", at="2026-11-10T10:02:10+08:00")
    assert (
        service.timer_status(session["id"], as_of="2026-11-10T10:02:20+08:00")["elapsed_seconds"]
        == 80
    )
    done = service.add_set(instance["id"], actual())
    assert done["rest_actual_s"] is None
    assert service.timer_status(session["id"], as_of="2026-11-10T09:00:00+08:00")["clock_anomaly"]


def test_actual_rest_derived_from_real_event_endpoints(service):
    _, instance = session_with_exercise(service)
    service.add_set(
        instance["id"],
        actual(started_at="2026-11-10T10:00:00+08:00", ended_at="2026-11-10T10:00:40+08:00"),
    )
    second = service.add_set(
        instance["id"],
        actual(started_at="2026-11-10T10:02:40+08:00", ended_at="2026-11-10T10:03:20+08:00"),
    )
    assert second["rest_actual_s"] == 120


def test_number_and_scale_validation_and_no_rir_clipping(service):
    _, instance = session_with_exercise(service)
    assert service.add_set(instance["id"], actual(rir=20))["rir"] == 20
    for changes in (
        {"load_value": float("nan")},
        {"reps": -1},
        {"reps": 1.5},
        {"rpe": 8},
        {"rpe": 11, "rpe_scale": "cr10"},
    ):
        with pytest.raises((TrainingError, ValueError)):
            service.add_set(instance["id"], actual(**changes))
    row = service.add_set(instance["id"], actual(rir=None, rpe=8, rpe_scale="cr10"))
    assert row["rir"] is None and row["rpe"] == 8
    lb = load_semantics(100, "lb", "external_total_kg")
    assert lb["external_total_kg"] == pytest.approx(45.359237)
    assert load_semantics(30, "kg", "per_dumbbell_kg")["external_total_kg"] is None


def test_drop_superset_reference_and_template_copy_preserve_targets(service):
    c = condition(service)
    template = service.create_template(
        "原模板",
        [
            {
                "exercise_id": SMITH,
                "condition": c,
                "targets": {"sets": [{"reps_min": 8, "reps_max": 10, "rir": 2}]},
            }
        ],
    )
    copied = service.copy_template(template["id"], "复制模板")
    assert copied["id"] != template["id"] and copied["items"] == template["items"]
    session = service.start_session(template_id=template["id"])
    service.edit_set(session["sets"][0]["id"], {"reference_set": True}, base_revision=1)
    first = service.edit_set(
        session["sets"][0]["id"],
        actual(
            reps=7, rir=0, relation_kind="superset", relation_group_id="pair-a", reference_set=True
        ),
        base_revision=2,
    )
    second = service.add_set(
        session["exercises"][0]["id"],
        actual(
            25,
            10,
            relation_kind="drop",
            relation_group_id="drop-a",
            parent_set_uuid=first["set_uuid"],
        ),
    )
    assert second["parent_set_uuid"] == first["set_uuid"]
    saved = service.save_session_as_template(session["id"], "保存为模板")
    assert saved["items"][0]["targets"]["sets"][0]["rir"] == 2
    assert saved["items"][0]["targets"]["sets"][0]["reps_max"] == 10


def test_legacy_quick_request_identity_does_not_duplicate(service):
    args = {
        "session_key": "legacy-one-session",
        "session_date": "2026-11-10",
        "started_at": "",
        "exercise_name": "Synthetic bench",
        "weight_kg": 30,
        "reps": 10,
    }
    one = append_quick_strength_set(service.repo, **args, client_event_id="legacy-real-1")
    retry = append_quick_strength_set(service.repo, **args, client_event_id="legacy-real-1")
    two = append_quick_strength_set(service.repo, **args, client_event_id="legacy-real-2")
    assert one["set_id"] == retry["set_id"] != two["set_id"]
    assert not retry["set_inserted"]
    with pytest.raises(ValueError, match="different content"):
        append_quick_strength_set(
            service.repo, **{**args, "reps": 8}, client_event_id="legacy-real-1"
        )


def test_session_tombstone_time_replay_and_incomplete_denominator(service):
    session, instance = session_with_exercise(service)
    service.add_set(instance["id"], actual())
    service.add_set(
        instance["id"],
        {"completion_state": "aborted", "load_value": 40, "load_unit": "kg", "reps": 0},
    )
    service.add_set(instance["id"], {"load_value": 30, "load_unit": "kg", "reps": 10})
    before_delete = datetime.now(timezone.utc).isoformat()
    history = service.history_as_of(cutoff_time=before_delete, include_incomplete=True)
    assert {row["completion_state"] for row in history} == {"completed", "aborted", "draft"}
    assert len(service.history_as_of(cutoff_time=before_delete)) == 1
    deletion = service.delete_session(session["id"], base_revision=1)
    now = datetime.now(timezone.utc).isoformat()
    assert service.history_as_of(cutoff_time=now, include_incomplete=True) == []
    assert len(service.history_as_of(cutoff_time=before_delete)) == 1
    assert all(
        row["session_deleted_at"]
        for row in service.history_as_of(
            cutoff_time=now, include_incomplete=True, include_deleted=True
        )
    )
    service.undo_event(deletion["event_id"], base_revision=2)
    assert len(service.history_as_of(cutoff_time=datetime.now(timezone.utc).isoformat())) == 1


def test_template_generated_drafts_preserve_denominator_in_snapshot(service):
    c = condition(service)
    template = service.create_template(
        "三组模板",
        [
            {
                "exercise_id": SMITH,
                "condition": c,
                "targets": {"sets": [{"reps_min": 8, "reps_max": 10}] * 3},
            }
        ],
    )
    session = service.start_session(template_id=template["id"])
    snapshot = service.history_as_of(
        cutoff_time=datetime.now(timezone.utc).isoformat(), include_incomplete=True
    )
    assert len(snapshot) == 3 and all(r["completion_state"] == "draft" for r in snapshot)
    assert all(r["planned"]["reps_max"] == 10 for r in snapshot)
    service.edit_set(session["sets"][0]["id"], actual(quality_status="acceptable"), base_revision=1)
    snapshot = service.history_as_of(
        cutoff_time=datetime.now(timezone.utc).isoformat(), include_incomplete=True
    )
    assert len(snapshot) == 3 and sum(r["completion_state"] == "completed" for r in snapshot) == 1


def test_conflict_is_visible_at_cutoff_without_overwriting_confirmed_value(service):
    _, instance = session_with_exercise(service)
    done = service.add_set(instance["id"], actual())
    service.edit_set(done["id"], {"reps": 9}, base_revision=1)
    before_conflict = datetime.now(timezone.utc).isoformat()
    conflict = service.edit_set(done["id"], {"reps": 8}, base_revision=1)
    snapshot = service.history_as_of(cutoff_time=datetime.now(timezone.utc).isoformat())
    assert snapshot[0]["reps"] == 9 and snapshot[0]["conflicted"]
    assert not service.history_as_of(cutoff_time=before_conflict)[0]["conflicted"]
    service.resolve_conflict(conflict["conflict_id"], choice="keep_current")
    assert not service.history_as_of(cutoff_time=datetime.now(timezone.utc).isoformat())[0][
        "conflicted"
    ]


def test_targets_condition_and_reference_are_frozen_before_outcome(service):
    session, instance = session_with_exercise(service)
    row = service.add_set(instance["id"])
    prior = datetime.now(timezone.utc).isoformat()
    row = service.update_set_target(
        row["id"], {"reps_min": 8, "reps_max": 10, "rir": 2}, base_revision=row["revision"]
    )
    revised = {**instance["condition"], "rom_protocol": "user-confirmed-partial"}
    updated = service.update_condition(instance["id"], revised, base_revision=instance["revision"])
    row = service.get_set(row["id"])
    assert row["condition_key"] == updated["condition_key"] != instance["condition_key"]
    old = service.history_as_of(cutoff_time=prior, include_incomplete=True)[0]
    assert old["condition_key"] == instance["condition_key"] and old["planned"] == {}
    with pytest.raises(TrainingError, match="参考组必须"):
        service.edit_set(row["id"], actual(reference_set=True), base_revision=row["revision"])
    row = service.edit_set(row["id"], {"reference_set": True}, base_revision=row["revision"])
    declared = row["reference_declared_at"]
    row = service.edit_set(row["id"], actual(), base_revision=row["revision"])
    assert row["reference_declared_at"] == declared and row["reference_set"]
    with pytest.raises(TrainingError, match="目标不可事后重写"):
        service.update_set_target(row["id"], {"reps_max": 12}, base_revision=row["revision"])
    with pytest.raises(TrainingError, match="测量条件不可覆盖"):
        service.update_condition(
            instance["id"], instance["condition"], base_revision=updated["revision"]
        )
    later = service.add_set(instance["id"], actual())
    with pytest.raises(TrainingError, match="参考组必须"):
        service.edit_set(later["id"], {"reference_set": True}, base_revision=later["revision"])
    assert service.get_session(session["id"])["completed_sets"] == 2


def test_replacement_and_reorder_preserve_prior_facts_and_skip_unexecuted(service):
    session, instance = session_with_exercise(service)
    completed = service.add_set(instance["id"], actual())
    draft = service.add_set(instance["id"], planned={"reps_min": 8, "reps_max": 10})
    old_time = datetime.now(timezone.utc).isoformat()
    replacement = service.replace_exercise(
        instance["id"],
        SMITH,
        {**instance["condition"], "rom_protocol": "different"},
        reason="另一器械条件",
        targets={"sets": [{"reps_min": 6, "reps_max": 8}]},
        base_revision=instance["revision"],
        event_id="replace-once",
    )
    replay = service.replace_exercise(
        instance["id"],
        SMITH,
        {**instance["condition"], "rom_protocol": "different"},
        reason="另一器械条件",
        targets={"sets": [{"reps_min": 6, "reps_max": 8}]},
        base_revision=instance["revision"],
        event_id="replace-once",
    )
    assert replay["replayed"] and replay["id"] == replacement["id"]
    assert service.get_set(completed["id"])["condition_key"] == instance["condition_key"]
    assert service.get_set(draft["id"])["completion_state"] == "skipped"
    before = service.history_as_of(cutoff_time=old_time, include_incomplete=True)
    assert len(before) == 2 and {r["completion_state"] for r in before} == {"draft", "completed"}
    after = service.history_as_of(
        cutoff_time=datetime.now(timezone.utc).isoformat(), include_incomplete=True
    )
    assert len(after) == 3 and replacement["sets"][0]["completion_state"] == "draft"
    ordered = service.reorder_exercises(
        session["id"],
        [replacement["id"], instance["id"]],
        base_revision=service.get_session(session["id"])["revision"],
    )
    assert [x["id"] for x in ordered["exercises"]] == [replacement["id"], instance["id"]]
    assert service.get_set(completed["id"])["reps"] == 10


def test_recommendation_and_feedback_invalidate_reports_without_staling_themselves(service):
    from healthzip.analytics.v13 import analyze, persist

    session, _ = session_with_exercise(service)
    candidate = {
        "candidate_id": "cache-cycle",
        "target_session": session["session_uuid"],
        "action_kind": "collect_or_confirm_evidence",
        "proposed_change": {"load": None},
        "target_range": None,
        "reason_evidence_ids": [],
        "eligibility": ["insufficient_data"],
        "uncertainty": {"kind": "not_estimable"},
        "verification_protocol": "先补记录",
        "followup_window": "next_session",
        "rule_version": "synthetic-v1",
        "user_choice": None,
    }
    cutoff = datetime.now(timezone.utc).isoformat()
    first_run = persist(service.repo, analyze(service.repo))
    before = int(service.data_version())
    frozen = service.record_recommendation(
        candidate, {}, cutoff_time=cutoff, theory_version="none_reviewed"
    )
    assert int(service.data_version()) == before + 1
    assert service.repo.one("SELECT invalidated_at FROM analysis_run WHERE run_id=?", (first_run,))[
        0
    ]
    assert service.pending_invalidations()[-1]["entity_type"] == "recommendation"
    assert frozen["stale"] == 0 and frozen["data_version"] == str(before)
    repeat = service.record_recommendation(
        candidate, {}, cutoff_time=cutoff, theory_version="none_reviewed"
    )
    assert repeat == frozen and int(service.data_version()) == before + 1
    second_run = persist(service.repo, analyze(service.repo))
    service.recommendation_feedback(
        candidate["candidate_id"], user_choice="deferred", event_id="feedback-once"
    )
    assert int(service.data_version()) == before + 2
    assert service.repo.one(
        "SELECT invalidated_at FROM analysis_run WHERE run_id=?", (second_run,)
    )[0]
    assert service.pending_invalidations()[-1]["entity_type"] == "recommendation_feedback"
    assert service.list_recommendations()[0]["stale"] == 0
    service.recommendation_feedback(
        candidate["candidate_id"], user_choice="deferred", event_id="feedback-once"
    )
    assert int(service.data_version()) == before + 2


def test_legacy_raw_edit_delete_conflict_and_undo_preserve_unknowns(service, tmp_path):
    from healthzip.training.exchange import import_training

    path = tmp_path / "legacy.csv"
    path.write_text(
        "date,exercise_name,equipment,weight,reps,weight_unit,warmup\n2026-11-01,Legacy Bench,smith,30,10,kg,false\n"
    )
    import_training(service.repo, path)
    row = service.legacy_records()[0]
    assert row["session_id"] is None and row["completion_state"] is None
    edited = service.edit_legacy_set(
        row["id"],
        {"reps": 8, "weight_kg": 32.5},
        base_revision=row["revision"],
        event_id="legacy-edit",
    )
    assert edited["reps"] == 8 and edited["weight_kg"] == 32.5
    assert edited["catalog_id"] is None and edited["load_basis"] == "unknown"
    assert edited["completion_state"] is None and edited["ended_at"] is None
    conflicting = service.edit_legacy_set(row["id"], {"reps": 9}, base_revision=row["revision"])
    service.resolve_conflict(conflicting["conflict_id"], choice="apply_proposed")
    updated = service.get_set(row["id"])
    assert updated["reps"] == 9
    deletion = service.delete_set(row["id"], base_revision=updated["revision"])
    assert service.legacy_records() == [] and len(service.legacy_records(include_deleted=True)) == 1
    restored = service.undo_event(deletion["event_id"], base_revision=deletion["revision"])
    assert restored["deleted_at"] is None and service.legacy_records()[0]["reps"] == 9
    assert restored["load_basis"] == "unknown" and restored["condition"] is None


def test_persisted_outbox_stops_dependent_events_until_conflict_resolved(service):
    _, instance = session_with_exercise(service)
    original = service.add_set(instance["id"], actual())
    service.edit_set(original["id"], {"reps": 9}, base_revision=original["revision"])
    service.queue_event(
        "edit_set",
        {"set_id": original["id"], "changes": {"reps": 8}, "base_revision": original["revision"]},
        event_id="outbox-stale",
    )
    service.queue_event(
        "add_set",
        {"session_exercise_id": instance["id"], "actual": actual()},
        event_id="outbox-dependent",
    )
    first = service.replay_outbox()
    assert len(first) == 1 and first[0]["status"] == "conflicted"
    again = service.replay_outbox()
    assert len(again) == 1 and again[0]["status"] == "conflicted"
    assert service.repo.count("strength_set") == 1
    service.resolve_conflict(first[0]["result"]["conflict_id"], choice="keep_current")
    resumed = service.replay_outbox()
    assert len(resumed) == 1 and resumed[0]["status"] == "applied"
    assert service.repo.count("strength_set") == 2 and service.replay_outbox() == []
