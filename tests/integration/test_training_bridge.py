"""Real service commands for the compact workbench, with isolated synthetic data."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService
from healthzip.ui.training_bridge import build_snapshot, calendar_sessions, handle_command


@pytest.fixture
def workbench(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Repository(tmp_path / "synthetic.sqlite3")
    yield repo, TrainingService(repo), {}
    repo.close()


def send(workbench, action, **payload):
    repo, _, state = workbench
    return handle_command(repo, {"id": str(uuid4()), "action": action, "payload": payload}, state)


def start(workbench, exercise="psa.ex.barbell_bench_press"):
    result = send(workbench, "start_session", name="合成训练")
    assert result["status"] == "saved", result
    session = result["data"]
    result = send(workbench, "add_exercises", session_id=session["session_uuid"],
                  base_revision=session["revision"], exercises=[{"exercise_id": exercise}])
    assert result["status"] == "saved", result
    session = result["data"]
    return session, session["exercises"][0], session["exercises"][0]["sets"][0]


def test_start_today_independent_of_selected_past_date_and_blank_group(workbench):
    repo, svc, state = workbench
    state["selected_date"] = "2001-02-03"
    session, instance, row = start(workbench)
    assert datetime.fromisoformat(session["started_at"]).date() == datetime.now(timezone.utc).date()
    assert instance["condition"]["load_basis"] == "unknown"
    assert not instance["condition"].get("load_basis_confirmed")
    assert all(row.get(key) is None for key in ("load_value", "reps", "duration_s", "distance_m", "rir", "started_at", "ended_at"))
    assert row["completion_state"] == "draft"
    assert not row.get("reference_set") and not row.get("reference_declared_at")
    assert svc.get_session(session["id"])["completed_sets"] == 0
    snapshot = build_snapshot(repo, state)
    assert str(repo.path) not in snapshot["db_scope"]
    assert snapshot["session"]["session_uuid"] == session["session_uuid"]


def test_batch_order_atomicity_lost_response_retry_and_explicit_repeat(workbench):
    repo, svc, state = workbench
    session = send(workbench, "start_session")["data"]
    choices = ["psa.ex.barbell_bench_press", "psa.ex.dumbbell_incline_press", "psa.ex.plank"]
    # Invalid last item rolls back all prior selections and their blank groups.
    failed = send(workbench, "add_exercises", session_id=session["id"], base_revision=1,
                  exercises=[{"exercise_id": choices[0]}, {"exercise_id": "missing.synthetic"}])
    assert failed["status"] == "error"
    assert not svc.get_session(session["id"])["exercises"]
    command = {"id": str(uuid4()), "action": "add_exercises", "payload": {
        "session_id": session["id"], "base_revision": 1,
        "exercises": [{"exercise_id": item} for item in choices]}}
    saved = handle_command(repo, command, state)
    assert saved["status"] == "saved", saved
    retry = handle_command(repo, command, {})  # Entire browser session was recreated.
    assert retry["status"] == "saved" and retry["replayed"]
    actual = svc.get_session(session["id"])
    assert [item["catalog_id"] for item in actual["exercises"]] == choices
    assert [len(item["sets"]) for item in actual["exercises"]] == [1, 1, 1]
    assert actual["revision"] == 2
    denied = send(workbench, "add_exercises", session_id=session["id"], base_revision=2,
                  exercises=[{"exercise_id": choices[0]}])
    assert denied["status"] == "error"
    repeated = send(workbench, "add_exercises", session_id=session["id"], base_revision=2,
                    exercises=[{"exercise_id": choices[0], "allow_repeat": True}])
    assert repeated["status"] == "saved"
    assert len(svc.get_session(session["id"])["exercises"]) == 4
    # Every child in this atomic batch has the operation's single visibility time.
    batch_event = next(event for event in svc.audit_events(actual["session_uuid"])
                       if event["action"] == "add_exercises" and event["status"] == "applied")
    after = batch_event["after"]
    assert all(row["available_at"] == batch_event["recorded_at"] for row in after["sets"])


@pytest.mark.parametrize("rir", [None, 0, 2])
def test_main_row_decimal_rir_preserves_advanced_and_completion_time(workbench, rir):
    repo, svc, state = workbench
    session, _, row = start(workbench)
    advanced = {"pain_flag": True, "quality_status": "technique_limited", "quality_note": "合成限制",
                "notes": "合成备注", "set_type": "warmup", "stop_reason": "technical_limit",
                "rir_qualifier": "at_least", "rpe": 7, "rpe_scale": "cr10"}
    row = svc.edit_set(row["set_uuid"], advanced, base_revision=row["revision"])
    command = {"id": str(uuid4()), "action": "save_set", "payload": {
        "set_id": row["set_uuid"], "base_revision": row["revision"], "complete": True,
        "changes": {"load_value": "20.75", "load_unit": "kg", "reps": "8", "rir": rir}}}
    result = handle_command(repo, command, state)
    assert result["status"] == "saved", result
    saved = svc.get_set(row["set_uuid"])
    assert float(saved["load_value"]) == 20.75 and saved["reps"] == 8 and saved["rir"] == rir
    assert all(saved[key] == value for key, value in advanced.items())
    assert saved["started_at"] is None and saved["rest_recorded_s"] is None
    ended = saved["ended_at"]
    assert ended
    assert handle_command(repo, command, {})["replayed"]
    # A separately delivered second completion is also read-only.
    again = send(workbench, "save_set", **command["payload"])
    assert again["status"] == "saved" and again["data"]["already_completed"]
    assert svc.get_set(row["set_uuid"])["ended_at"] == ended
    corrected = send(workbench, "save_set", set_id=row["set_uuid"], base_revision=saved["revision"],
                     correction=True, changes={"reps": 9})
    assert corrected["status"] == "saved"
    assert svc.get_set(row["set_uuid"])["ended_at"] == ended
    assert svc.get_session(session["id"])["completed_sets"] == 1


@pytest.mark.parametrize("exercise,field,value", [
    ("psa.ex.plank", "duration_s", "33.5"),
    ("psa.ex.farmer_carry", "distance_m", "24.75"),
])
def test_duration_and_distance_recording(workbench, exercise, field, value):
    _, svc, _ = workbench
    _, _, row = start(workbench, exercise)
    result = send(workbench, "save_set", set_id=row["set_uuid"], base_revision=1, complete=True,
                  changes={field: value, "rir": None})
    assert result["status"] == "saved", result
    actual = svc.get_set(row["set_uuid"])
    assert actual[field] == float(value) and actual["reps"] is None


def test_copy_drafts_strip_effort_quality_times_and_reference(workbench):
    _, svc, _ = workbench
    _, instance, row = start(workbench)
    row = svc.edit_set(row["set_uuid"], {"load_value": 12.5, "load_unit": "kg", "reps": 10,
        "rir": 0, "pain_flag": True, "quality_status": "technique_limited", "completion_state": "completed",
        "body_mass_kg": 80, "added_load_kg": 5, "assistance_value": 7},
        base_revision=row["revision"])
    result = send(workbench, "add_set", instance_id=instance["id"], base_revision=instance["revision"],
                  copy_from_set_id=row["set_uuid"])
    assert result["status"] == "saved", result
    copied = result["data"]
    assert float(copied["load_value"]) == 12.5 and copied["reps"] == 10
    assert copied["completion_state"] == "draft" and not copied.get("reference_set")
    assert all(copied.get(key) is None for key in ("rir", "rpe", "pain_flag", "quality_status",
        "started_at", "ended_at", "body_mass_kg", "added_load_kg", "assistance_value"))
    blank = send(workbench, "add_set", instance_id=instance["id"], base_revision=instance["revision"])["data"]
    assert blank["load_value"] is None and blank["reps"] is None


def test_stale_revision_conflict_and_failed_input_never_overwrite(workbench):
    _, svc, _ = workbench
    _, _, row = start(workbench)
    svc.edit_set(row["set_uuid"], {"reps": 11}, base_revision=row["revision"])
    conflict = send(workbench, "save_set", set_id=row["set_uuid"], base_revision=1,
                    changes={"reps": 8, "load_value": 22.5, "load_unit": "kg"})
    assert conflict["status"] == "conflicted"
    assert conflict["data"]["proposed"]["reps"] == 8
    assert svc.get_set(row["set_uuid"])["reps"] == 11
    assert svc.list_conflicts()
    bad = send(workbench, "save_set", set_id=row["set_uuid"], base_revision=2,
               complete=True, changes={"reps": "8.5", "rir": 0})
    assert bad["status"] == "error" and "次数" in bad["message"]
    assert svc.get_set(row["set_uuid"])["reps"] == 11


def test_end_summary_drafts_preserved_optional_feedback_and_retry(workbench):
    repo, svc, state = workbench
    session, instance, row = start(workbench)
    send(workbench, "save_set", set_id=row["set_uuid"], base_revision=1, complete=True, changes={"reps": 8})
    send(workbench, "add_set", instance_id=instance["id"], base_revision=instance["revision"])
    current = svc.get_session(session["id"])
    current = svc.update_session(current["id"], {"session_rpe": 4, "session_rpe_scale": "cr10",
        "duration_seconds": 1234, "duration_protocol": "user_elapsed_including_rest",
        "feedback": {"notes": "合成整场记录"}}, base_revision=current["revision"])
    command = {"id": str(uuid4()), "action": "end_session", "payload": {
        "session_id": session["id"], "base_revision": current["revision"]}}
    result = handle_command(repo, command, state)
    assert result["status"] == "saved", result
    ended = svc.get_session(session["id"])
    assert ended["completed_sets"] == 1 and ended["sets"][1]["completion_state"] == "draft"
    assert ended["session_rpe"] == 4 and ended["duration_seconds"] == 1234
    assert ended["feedback"]["notes"] == "合成整场记录"
    assert handle_command(repo, command, {})["replayed"]
    again = send(workbench, "end_session", **command["payload"])
    assert again["status"] == "saved"
    assert svc.get_session(session["id"])["ended_at"] == ended["ended_at"]


def test_calendar_all_month_timezone_boundaries_deletion_and_external_change(workbench):
    repo, svc, state = workbench
    for index in range(55):
        svc.start_session(f"合成会话 {index}", started_at="2025-12-15T12:00:00+08:00")
    outside = svc.start_session("合成UTC月底", started_at="2025-12-31T16:30:00+00:00")
    inside = svc.start_session("合成UTC月初", started_at="2025-11-30T16:30:00+00:00")
    svc.start_session("合成跨年", started_at="2026-01-01T00:30:00+08:00")
    rows = calendar_sessions(svc, "2025-12", "Asia/Shanghai")
    assert len(rows) == 56
    assert inside["session_uuid"] in {row["session_uuid"] for row in rows}
    assert outside["session_uuid"] not in {row["session_uuid"] for row in rows}
    assert len(calendar_sessions(svc, "2026-01", "Asia/Shanghai")) == 2
    state["month"] = "2025-12"
    assert len(build_snapshot(repo, state)["calendar"]) == 56
    deleted = svc.delete_session(inside["id"], base_revision=inside["revision"])
    assert len(build_snapshot(repo, state)["calendar"]) == 55
    svc.undo_event(deleted["event_id"], base_revision=deleted["revision"])
    assert len(build_snapshot(repo, state)["calendar"]) == 56


def test_timer_retry_does_not_restart_and_delete_undo_recount(workbench):
    repo, svc, state = workbench
    session, _, row = start(workbench)
    send(workbench, "save_set", set_id=row["set_uuid"], base_revision=1, complete=True, changes={"reps": 8})
    current = svc.get_session(session["id"])
    command = {"id": str(uuid4()), "action": "timer", "payload": {
        "session_id": session["id"], "base_revision": current["revision"], "action": "start"}}
    first = handle_command(repo, command, state)
    retry = handle_command(repo, command, {})
    assert retry["replayed"] and first["data"]["anchor_at"] == retry["data"]["anchor_at"]
    assert first["data"]["target_seconds"] is None
    actual = svc.get_set(row["set_uuid"])
    deleted = send(workbench, "delete_set", set_id=row["set_uuid"], base_revision=actual["revision"])
    assert deleted["status"] == "saved"
    assert svc.get_session(session["id"])["completed_sets"] == 0
    undone = send(workbench, "undo", event_id=deleted["event_id"], base_revision=deleted["data"]["revision"])
    assert undone["status"] == "saved"
    assert svc.get_session(session["id"])["completed_sets"] == 1


def test_latest_history_all_sets_and_unknown_history_do_not_need_advice(workbench):
    _, svc, _ = workbench
    previous = svc.start_session("合成旧训练", started_at=(datetime.now(timezone.utc) - timedelta(days=480)).isoformat())
    prior = svc.add_exercise(previous["id"], "psa.ex.barbell_bench_press", {})
    for index, (load, reps, rir) in enumerate(((55, 10, 2), (55, 9, 1), (50, 11, 2))):
        occurred = datetime.now(timezone.utc) - timedelta(days=480, minutes=10-index)
        svc.add_set(prior["id"], {"load_value": load, "load_unit": "kg", "reps": reps,
            "rir": rir, "completion_state": "completed", "ended_at": occurred.isoformat()})
    svc.end_session(previous["id"])
    _, instance, _ = start(workbench)
    history = send(workbench, "history", instance_id=instance["id"])
    assert history["status"] == "saved", history
    assert history["data"]["latest_session"]["id"] == previous["id"]
    assert [row["reps"] for row in history["data"]["records"]] == [10, 9, 11]
    assert all(not row.get("reference_set") for row in history["data"]["records"])
    source = history["data"]["records"][0]
    copied = send(workbench, "copy_history", instance_id=instance["id"], base_revision=1, source_set_id=source["set_uuid"])
    assert copied["status"] == "saved", copied
    assert copied["data"]["rir"] is None and copied["data"]["completion_state"] == "draft"


def test_completed_new_request_with_different_values_is_conflict_not_success(workbench):
    _, svc, _ = workbench
    _, _, row = start(workbench)
    completed = send(workbench, "save_set", set_id=row["set_uuid"], base_revision=1,
                     complete=True, changes={"reps": 8, "rir": 0})
    assert completed["status"] == "saved"
    actual = svc.get_set(row["set_uuid"])
    same = send(workbench, "save_set", set_id=row["set_uuid"], base_revision=1,
                complete=True, changes={"reps": "8", "rir": "0"})
    assert same["status"] == "saved" and same["data"]["already_completed"]
    different = send(workbench, "save_set", set_id=row["set_uuid"], base_revision=1,
                     complete=True, changes={"reps": "10", "rir": None})
    assert different["status"] == "conflicted"
    assert different["data"]["proposed"] == {"reps": "10", "rir": None}
    assert different["data"]["current_revision"] == actual["revision"]
    assert svc.get_set(row["set_uuid"])["ended_at"] == actual["ended_at"]
    assert svc.get_set(row["set_uuid"])["reps"] == 8


def test_calendar_counts_share_read_snapshot_during_external_commit(workbench, monkeypatch):
    import healthzip.ui.training_bridge as bridge

    repo, svc, _ = workbench
    first, _, row = start(workbench)
    send(workbench, "save_set", set_id=row["set_uuid"], base_revision=1, complete=True, changes={"reps": 8})
    second = svc.start_session("合成另一场")
    other_instance = svc.add_exercise(second["id"], "psa.ex.plank", {})
    other_row = svc.add_set(other_instance["id"], {"completion_state": "completed", "duration_s": 30})
    other = Repository(repo.path)
    writer = TrainingService(other)
    original = bridge._summary
    fired = False

    def interleave(service, source, zone):
        nonlocal fired
        if not fired:
            fired = True
            writer.delete_set(other_row["set_uuid"], base_revision=other_row["revision"])
        return original(service, source, zone)

    monkeypatch.setattr(bridge, "_summary", interleave)
    month = datetime.fromisoformat(first["started_at"]).astimezone(bridge.ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")
    consistent = calendar_sessions(svc, month)
    assert fired and [entry["completed_sets"] for entry in consistent] == [1, 1]
    assert not repo.conn.in_transaction
    current = calendar_sessions(svc, month)
    assert [entry["completed_sets"] for entry in current] == [1, 0]
    other.close()


@pytest.mark.parametrize("change", ["source", "profile", "settings", "knowledge"])
def test_advice_dependencies_mark_frozen_panel_stale_without_recalculation(workbench, monkeypatch, change):
    import healthzip.ui.training_bridge as bridge
    from healthzip.training.current import save_equipment_loads

    repo, svc, state = workbench
    _, instance, _ = start(workbench)
    build_snapshot(repo, state)
    frozen = {"instance_id": instance["id"], "advice_id": "synthetic-frozen", "groups": [],
              "created_at": datetime.now(timezone.utc).isoformat()}
    state["advice"] = frozen
    state["advice_dependencies"] = bridge._advice_dependencies(svc, state, instance["id"])
    before = build_snapshot(repo, state)
    assert not before["advice"]["stale"]
    if change in {"source", "profile"}:
        key = "source_data_version" if change == "source" else "advice_profile_version"
        repo.conn.execute("INSERT INTO schema_meta(key,value) VALUES(?,?) "
                          "ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1", (key, "1"))
        repo.conn.commit()
    elif change == "settings":
        save_equipment_loads(repo, instance["id"], [20, 22.5], load_unit="kg")
    else:
        folder = bridge.Path(".local/knowledge")
        folder.mkdir(parents=True)
        (folder / "theories.sqlite3").write_bytes(b"synthetic generation marker")
    import healthzip.training.current as current
    monkeypatch.setattr(current, "current_advice", lambda *a, **k: pytest.fail("panel refresh recalculated advice"))
    after = build_snapshot(repo, state)
    assert after["advice"]["stale"] and "重新核对" in after["advice"]["stale_message"]
    assert after["advice"]["created_at"] == frozen["created_at"]
    assert state["advice"] == frozen


def test_abort_session_uses_real_service_and_keeps_draft(workbench):
    _, svc, _ = workbench
    session, _, row = start(workbench)
    result = send(workbench, "abort_session", session_id=session["id"], base_revision=session["revision"])
    assert result["status"] == "saved", result
    actual = svc.get_session(session["id"])
    assert actual["session_status"] == "aborted" and actual["ended_at"]
    assert svc.get_set(row["set_uuid"])["completion_state"] == "draft"
    assert actual["completed_sets"] == 0


def test_legacy_feedback_note_and_explicit_clear_stay_in_sync(workbench):
    _, svc, _ = workbench
    session, _, _ = start(workbench)
    current = svc.update_session(session["id"], {"feedback": {"notes": "旧整场备注", "other": "保留"}},
                                 base_revision=session["revision"])
    assert current["notes"] == ""
    edited = send(workbench, "update_session", session_id=session["id"], base_revision=current["revision"],
                  changes={"notes": "新整场备注"})
    assert edited["status"] == "saved", edited
    actual = svc.get_session(session["id"])
    assert actual["notes"] == actual["feedback"]["notes"] == "新整场备注"
    assert actual["feedback"]["other"] == "保留"
    cleared = send(workbench, "update_session", session_id=session["id"], base_revision=actual["revision"],
                   changes={"notes": ""})
    assert cleared["status"] == "saved", cleared
    actual = svc.get_session(session["id"])
    assert actual["notes"] == actual["feedback"]["notes"] == ""
    assert actual["feedback"]["other"] == "保留"


@pytest.mark.parametrize("explicit", [False, True])
def test_ending_preserves_legacy_feedback_or_explicitly_edits_note_in_one_event(workbench, explicit):
    repo, svc, state = workbench
    session, _, _ = start(workbench)
    current = svc.update_session(session["id"], {"feedback": {"notes": "旧整场备注", "other": "保留"}},
                                 base_revision=session["revision"])
    payload = {"session_id": session["id"], "base_revision": current["revision"]}
    if explicit:
        payload["notes"] = "结束摘要新备注"
    command = {"id": str(uuid4()), "action": "end_session", "payload": payload}
    result = handle_command(repo, command, state)
    assert result["status"] == "saved", result
    actual = svc.get_session(session["id"])
    assert actual["feedback"]["notes"] == ("结束摘要新备注" if explicit else "旧整场备注")
    assert actual["notes"] == ("结束摘要新备注" if explicit else "")
    assert actual["feedback"]["other"] == "保留"
    assert actual["revision"] == current["revision"] + 1
    assert handle_command(repo, command, {})["replayed"]
    assert svc.get_session(session["id"])["ended_at"] == actual["ended_at"]


def test_service_end_note_is_same_event_and_idempotent(workbench):
    _, svc, _ = workbench
    session, _, _ = start(workbench)
    event = str(uuid4())
    first = svc.end_session(session["id"], notes="同事件备注", feedback={"notes": "同事件备注"},
                            base_revision=session["revision"], event_id=event)
    retry = svc.end_session(session["id"], notes="同事件备注", feedback={"notes": "同事件备注"},
                            base_revision=session["revision"], event_id=event)
    assert retry["replayed"] and retry["ended_at"] == first["ended_at"]
    assert retry["revision"] == first["revision"]
    with pytest.raises(ValueError, match="不同"):
        svc.end_session(session["id"], notes="不同备注", feedback={"notes": "同事件备注"},
                        base_revision=session["revision"], event_id=event)
    with pytest.raises(ValueError, match="不同"):
        svc.end_session(session["id"], feedback={"notes": "同事件备注"},
                        base_revision=session["revision"], event_id=event)


def _synthetic_media(repo, exercise_id, metadata, *, path=None, digest=None):
    """Inject only optional public-asset state, never bypass training events."""
    repo.conn.execute("INSERT INTO catalog_source_mapping VALUES(?,?,?,?,?,?)",
        ("wger", "synthetic-workbench-media", exercise_id, "exact_identity", "confirmed", "{}"))
    repo.conn.execute("INSERT INTO catalog_media VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("synthetic-workbench-image", "synthetic-workbench-media", "synthetic-snapshot", "image",
         metadata, 1, "ready", digest, str(path) if path else None, None, None))
    repo.conn.commit()


def test_corrupt_optional_media_metadata_does_not_block_catalog_or_recording(workbench):
    from healthzip.training.catalog_media import media_for

    repo, svc, state = workbench
    session, instance, row = start(workbench)
    _synthetic_media(repo, instance["catalog_id"], "{invalid synthetic metadata")
    with pytest.raises(json.JSONDecodeError):
        media_for(repo.conn, instance["catalog_id"])
    snapshot = build_snapshot(repo, state)
    assert snapshot["session"]["exercises"][0]["thumbnail"] is None
    catalog = send(workbench, "catalog", query="杠铃卧推")
    assert catalog["status"] == "saved" and catalog["data"]["items"]
    assert catalog["data"]["items"][0]["thumbnail"] is None
    result = send(workbench, "save_set", set_id=row["set_uuid"], base_revision=row["revision"],
                  complete=True, changes={"reps": 8, "rir": None})
    assert result["status"] == "saved", result
    assert svc.get_session(session["id"])["completed_sets"] == 1
    assert build_snapshot(repo, state)["session"]["completed_sets"] == 1


def test_real_pillow_preview_guard_does_not_block_recording(workbench, monkeypatch):
    from PIL import Image

    repo, svc, state = workbench
    session, instance, row = start(workbench)
    path = repo.path.parent / "synthetic-verified-image.png"
    Image.new("RGB", (4, 4), "gray").save(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    _synthetic_media(repo, instance["catalog_id"], json.dumps({"media_type": "image",
        "author": "Synthetic Test Author", "attribution_text": "Synthetic Test Author · CC0",
        "license": {"short_name": "CC0"}, "verified_file": {"mime": "image/png"}}),
        path=path, digest=digest)
    # A local asset may become invalid after prior verification, or the image
    # decoder may enforce a different safety limit. Trigger its real exception
    # with a tiny harmless synthetic file, without mocking rendering/service.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 2)
    with pytest.raises(Image.DecompressionBombError):
        Image.open(path)
    snapshot = build_snapshot(repo, state)
    shown = snapshot["session"]["exercises"][0]
    assert shown["thumbnail"] is None and not shown["media"][0]["available"]
    assert shown["media"][0]["author"] == "Synthetic Test Author"
    result = send(workbench, "save_set", set_id=row["set_uuid"], base_revision=row["revision"],
                  complete=True, changes={"reps": 8, "rir": 0})
    assert result["status"] == "saved", result
    assert svc.get_session(session["id"])["completed_sets"] == 1
    assert build_snapshot(repo, state)["session"]["completed_sets"] == 1
