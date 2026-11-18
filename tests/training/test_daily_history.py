"""Daily lifetime history uses actual sessions and ordinary, unselected sets."""
from datetime import datetime, timezone

import pytest

from healthzip.db.repository import Repository
from healthzip.strength_log import save_strength_log
from healthzip.training.daily_history import select_daily_history
from healthzip.training.service import TrainingService

EXERCISE = "psa.ex.smith_incline_press"
CONDITION = {"equipment_instance_id": "synthetic-smith", "load_basis": "external_total_kg",
             "load_basis_confirmed": True, "side": "bilateral", "repetition_semantics": "full_repetitions",
             "rom_protocol": "synthetic-full-rom", "settings": {"bench": 30}, "settings_confirmed": True}


@pytest.fixture
def service(tmp_path):
    repo = Repository(tmp_path / "synthetic-daily-history.sqlite3")
    svc = TrainingService(repo)
    for identity in ("synthetic-smith", "synthetic-other-smith"):
        svc.create_equipment(identity, "smith", equipment_id=identity)
    yield svc
    repo.close()


def cutoff():
    return datetime.now(timezone.utc).isoformat()


def session(service, day, *, condition=None, exercise=EXERCISE):
    parent = service.start_session("Synthetic daily history", started_at=day + "T09:00:00+00:00")
    item = service.add_exercise(parent["id"], exercise, CONDITION if condition is None else condition)
    return parent, item


def record(service, item, day, load, reps, rir=None, *, minute=1, state="completed", **extra):
    return service.add_set(item["id"], {"completion_state": state, "load_value": load, "load_unit": "kg",
        "reps": reps, "rir": rir, "quality_status": "acceptable", "pain_flag": False,
        "started_at": f"{day}T09:{minute:02}:00+00:00", "ended_at": f"{day}T09:{minute:02}:30+00:00", **extra})


def history(service, item):
    return select_daily_history(service, item, cutoff_time=cutoff())


def test_ordinary_mixed_sets_latest_session_all_records_and_scopes(service):
    parent, old = session(service, "2025-01-01")
    actuals = [record(service, old, "2025-01-01", 55, 10, 2),
               record(service, old, "2025-01-01", 55, 9, 1, minute=3),
               record(service, old, "2025-01-01", 50, 11, 2, minute=5)]
    service.end_session(parent["id"])
    _, current = session(service, "2026-01-01")
    result = history(service, current)
    assert result["status"] == "history_available"
    assert result["latest_session"]["id"] == parent["id"]
    assert result["latest_session"]["days_since"] > 365
    assert [(float(r["load_value"]), r["reps"], r["rir"]) for r in result["records"]] == [(55, 10, 2), (55, 9, 1), (50, 11, 2)]
    assert [r["set_uuid"] for r in result["records"]] == [r["set_uuid"] for r in actuals]
    assert all(not r["reference_set"] and not r["reference_declared_at"] for r in result["records"])
    assert result["comparable_set_uuids"] == [r["set_uuid"] for r in actuals]
    assert len(result["selection"]["task_mapping"]) == 3
    assert "historical_performance_is_observation_not_current_capacity" in result["limitations"]


@pytest.mark.parametrize("reference", [True, False, None])
def test_reference_identity_does_not_control_daily_fact_selection(service, reference):
    _, old = session(service, "2026-01-01")
    draft = service.add_set(old["id"], {"reference_set": reference})
    service.edit_set(draft["id"], {"completion_state": "completed", "reps": 8, "load_value": 40,
        "load_unit": "kg", "started_at": "2026-01-01T09:00:30+00:00", "ended_at": "2026-01-01T09:01:00+00:00"},
        base_revision=draft["revision"])
    _, current = session(service, "2026-01-02")
    result = history(service, current)
    assert result["latest_session"]["id"] == old["session_id"]
    assert result["comparable_set_uuids"] == [draft["set_uuid"]]
    assert result["records"][0]["reps"] == 8


def test_latest_decline_failed_session_pain_and_unknown_rir_never_fall_back(service):
    _, good = session(service, "2026-01-01")
    record(service, good, "2026-01-01", 55, 12, 2)
    recent_parent, recent = session(service, "2026-01-10")
    failed = record(service, recent, "2026-01-10", 50, 0, state="aborted", pain_flag=True,
                    quality_status="technique_limited", stop_reason="pain")
    _, current = session(service, "2026-01-11")
    result = history(service, current)
    assert result["latest_session"]["id"] == recent_parent["id"]
    assert [r["set_uuid"] for r in result["records"]] == [failed["set_uuid"]]
    assert result["records"][0]["completion_state"] == "aborted"
    assert result["records"][0]["pain_flag"] == 1
    assert result["records"][0]["rir"] is None
    assert "latest_session_not_completed" in result["limitations"]


def test_drafts_not_actual_current_session_excluded_and_same_day_other_session_kept(service):
    parent, old = session(service, "2026-01-01")
    actual = record(service, old, "2026-01-01", 40, 8)
    _, later_draft = session(service, "2026-01-01")
    service.add_set(later_draft["id"], planned={"reps_min": 8, "reps_max": 12})
    _, current = session(service, "2026-01-01")
    record(service, current, "2026-01-01", 60, 20, minute=9)
    result = history(service, current)
    assert result["latest_session"]["id"] == parent["id"]
    assert [r["set_uuid"] for r in result["records"]] == [actual["set_uuid"]]


def test_duplicate_instances_original_order_and_research_mapping_survive(service):
    parent, first = session(service, "2026-01-01")
    a = record(service, first, "2026-01-01", 40, 8)
    second = service.add_exercise(parent["id"], EXERCISE, CONDITION, position=4)
    b = record(service, second, "2026-01-01", 35, 9, minute=4)
    _, current = session(service, "2026-01-02")
    service.add_set(current["id"])
    service.add_set(current["id"])
    service.reorder_exercises(current["session_id"], [current["id"]], base_revision=service.get_session(current["session_id"])["revision"])
    result = history(service, current)
    assert [r["set_uuid"] for r in result["records"]] == [a["set_uuid"], b["set_uuid"]]
    assert [r["session_exercise_id"] for r in result["records"]] == [first["id"], second["id"]]
    assert all(r["daily_comparability"]["strict_task_id"] for r in result["records"])
    assert result["comparable_set_uuids"] == [a["set_uuid"], b["set_uuid"]]


@pytest.mark.parametrize("changed", [{"rom_protocol": "synthetic-partial"},
    {"side": "left"}, {"equipment_instance_id": "synthetic-other-smith"},
    {"load_basis": "plates_per_side_kg"}, {"settings": {"bench": 45}}])
def test_latest_incompatible_conditions_preserved_without_older_favorable_fallback(service, changed):
    _, good = session(service, "2026-01-01")
    record(service, good, "2026-01-01", 55, 12)
    parent, recent = session(service, "2026-01-03", condition={**CONDITION, **changed})
    actual = record(service, recent, "2026-01-03", 40, 8)
    _, current = session(service, "2026-01-04")
    result = history(service, current)
    assert result["status"] == "history_not_comparable"
    assert result["latest_session"]["id"] == parent["id"]
    assert [r["set_uuid"] for r in result["records"]] == [actual["set_uuid"]]
    assert result["comparable_set_uuids"] == []


def test_protocol_change_does_not_remove_daily_history_but_strict_identity_differs(service):
    protocol = {"protocol_id": "synthetic-first-work-set", "version": "1", "reference_policy_id": "first-work-set",
                "effort_protocol": "rir", "tempo": "controlled", "rest_protocol": "recorded"}
    _, old = session(service, "2026-01-01", condition={**CONDITION, "reference_protocol": protocol})
    actual = record(service, old, "2026-01-01", 40, 8)
    _, current = session(service, "2026-01-02")
    result = history(service, current)
    comparison = result["records"][0]["daily_comparability"]
    assert comparison["comparable"]
    assert comparison["strict_task_id"] != comparison["current_strict_task_id"]
    assert result["records"][0]["set_uuid"] == actual["set_uuid"]


def test_late_entry_occurrence_not_import_order_and_original_cutoff_is_frozen(service):
    parent, newer = session(service, "2026-01-10")
    actual = record(service, newer, "2026-01-10", 40, 8)
    _, current = session(service, "2026-01-11")
    before = cutoff()
    old_parent, imported = session(service, "2025-01-01")
    record(service, imported, "2025-01-01", 90, 20)
    result = history(service, current)
    assert result["latest_session"]["id"] == parent["id"]
    frozen = select_daily_history(service, current, cutoff_time=before)
    assert frozen["latest_session"]["id"] == parent["id"]
    assert old_parent["id"] not in frozen["selection"]["candidate_sessions"]
    assert frozen["records"][0]["set_uuid"] == actual["set_uuid"]


def test_correction_deletion_undo_reselect_without_rewriting_frozen_history(service):
    parent, old = session(service, "2026-01-01")
    record(service, old, "2026-01-01", 40, 8)
    newer_parent, newer = session(service, "2026-01-10")
    actual = record(service, newer, "2026-01-10", 35, 7)
    _, current = session(service, "2026-01-11")
    frozen_cutoff = cutoff()
    original = select_daily_history(service, current, cutoff_time=frozen_cutoff)
    deletion = service.delete_session(newer_parent["id"], base_revision=service.get_session(newer_parent["id"])["revision"], event_id="synthetic-delete-latest")
    fallback = history(service, current)
    assert fallback["latest_session"]["id"] == parent["id"]
    assert fallback["selection"]["deleted_history"][0]["session_id"] == newer_parent["id"]
    assert select_daily_history(service, current, cutoff_time=frozen_cutoff) == original
    service.undo_event("synthetic-delete-latest", base_revision=deletion["revision"])
    restored = history(service, current)
    assert restored["latest_session"]["id"] == newer_parent["id"]
    assert [r["set_uuid"] for r in restored["records"]] == [actual["set_uuid"]]
    row = service.get_set(actual["id"])
    service.edit_set(row["id"], {"started_at": "2024-01-01T09:01:00+00:00", "ended_at": "2024-01-01T09:01:30+00:00"}, base_revision=row["revision"])
    assert history(service, current)["latest_session"]["id"] == parent["id"]


def test_no_history_new_action_and_missing_data_keep_free_records(service):
    _, old = session(service, "2026-01-01")
    record(service, old, "2026-01-01", 40, 8)
    _, current = session(service, "2026-01-02", exercise="psa.ex.smith_squat")
    result = history(service, current)
    assert result["status"] == "no_history" and result["records"] == []
    actual = record(service, current, "2026-01-02", 20, 6)
    _, following = session(service, "2026-01-03", exercise="psa.ex.smith_squat")
    assert history(service, following)["records"][0]["set_uuid"] == actual["set_uuid"]


def test_missing_set_time_retains_known_session_date_and_limits(service):
    parent, old = session(service, "2025-01-01", condition={})
    actual = service.add_set(old["id"], {"completion_state": "completed", "reps": 8,
        "load_value": 40, "load_unit": "kg", "started_at": None, "ended_at": None})
    _, current = session(service, "2026-01-01")
    result = history(service, current)
    assert result["latest_session"]["id"] == parent["id"]
    row = result["records"][0]
    assert row["set_uuid"] == actual["set_uuid"]
    assert row["ended_at"] is None and row["started_at"] is None
    assert row["daily_occurrence_time_source"] == "session_started_at"
    assert row["daily_fact_limitations"] == ["set_occurrence_time_unknown"]


def test_missing_conditions_do_not_hide_actuals_or_fill_rir_and_plan(service):
    parent, old = session(service, "2026-01-01", condition={})
    actual = record(service, old, "2026-01-01", 40, 8)
    _, current = session(service, "2026-01-02")
    result = history(service, current)
    assert result["status"] == "history_not_comparable"
    assert result["latest_session"]["id"] == parent["id"]
    assert result["records"][0]["set_uuid"] == actual["set_uuid"]
    assert result["records"][0]["rir"] is None
    assert result["records"][0]["planned"] == {}
    assert "daily_missing_load_basis" in result["records"][0]["daily_comparability"]["reason_codes"]


def test_full_record_states_and_later_group_revision_change_hash(service):
    _, old = session(service, "2026-01-01")
    first = record(service, old, "2026-01-01", 55, 10, 2)
    warmup = record(service, old, "2026-01-01", 20, 10, minute=2, set_type="warmup")
    later = record(service, old, "2026-01-01", 50, 8, 1, minute=3)
    skipped = service.add_set(old["id"], {"completion_state": "skipped"})
    removed = record(service, old, "2026-01-01", 50, 7, minute=4)
    service.delete_set(removed["id"], base_revision=removed["revision"])
    _, current = session(service, "2026-01-02")
    original = history(service, current)
    assert [r["set_uuid"] for r in original["records"]] == [r["set_uuid"] for r in (first, warmup, later, skipped, removed)]
    assert original["records"][1]["set_type"] == "warmup"
    assert original["records"][3]["completion_state"] == "skipped"
    assert original["records"][4]["deleted_at"]
    service.edit_set(later["id"], {"quality_status": "technique_limited", "pain_flag": True}, base_revision=later["revision"])
    updated = history(service, current)
    assert updated["records"][0] == original["records"][0]
    assert updated["selection_hash"] != original["selection_hash"]
    assert updated["records"][2]["pain_flag"] == 1
    assert history(service, current)["selection_hash"] == updated["selection_hash"]


def test_equal_actual_times_keep_session_ambiguity_without_best_performance_selection(service):
    for load in (30, 60):
        _, old = session(service, "2026-01-01")
        record(service, old, "2026-01-01", load, 8)
    _, current = session(service, "2026-01-02")
    result = history(service, current)
    assert result["status"] == "history_time_ambiguous"
    assert result["latest_session"] is None
    assert len(result["selection"]["tied_latest_session_ids"]) == 2
    assert len(result["older_sessions"]) == 2


def test_legacy_exact_identity_preserves_unknown_inventory_without_name_matching(service):
    save_strength_log(service.repo, session_date="2024-01-01", started_at="", name="Synthetic legacy",
        notes="", sets=[{"exercise_id": EXERCISE, "exercise_name": "Synthetic old name", "weight_kg": 40, "reps": 8}])
    _, current = session(service, "2026-01-02")
    result = history(service, current)
    assert result["status"] == "history_visibility_unknown"
    assert result["records"] == []
    assert result["unresolved_inventory"][0]["exercise_id"] == EXERCISE
    assert result["unresolved_inventory"][0]["daily_comparability"]["comparable"] is False
    assert result["unresolved_inventory"][0]["available_at"] is None


def test_unknown_occurrence_cannot_authorize_claim_of_unique_latest(service):
    parent, known = session(service, "2025-01-01")
    visible = record(service, known, "2025-01-01", 40, 10, 2)
    unknown_parent, unknown = session(service, "2026-01-01")
    untimed = service.add_set(unknown["id"], {"completion_state": "completed", "reps": 8,
        "load_value": 40, "load_unit": "kg", "pain_flag": True, "quality_status": "acceptable",
        "started_at": None, "ended_at": None})
    service.update_session(unknown_parent["id"], {"started_at": None},
                           base_revision=service.get_session(unknown_parent["id"])["revision"])
    _, current = session(service, "2026-01-02")
    result = history(service, current)
    assert result["status"] == "history_time_ambiguous"
    assert result["latest_known_time_only"]
    assert result["latest_session"]["id"] == parent["id"]
    assert result["latest_session"]["latest_known_time_only"]
    assert result["records"][0]["set_uuid"] == visible["set_uuid"]
    assert [r["set_uuid"] for r in result["unranked_records"]] == [untimed["set_uuid"]]
    assert result["unranked_records"][0]["pain_flag"]
