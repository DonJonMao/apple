import hashlib
import json

import pytest

from healthzip.db.repository import Repository
from healthzip.training import TrainingService
from healthzip.training.exchange import export_training, import_training, preview_import


def fixture(svc):
    equipment = svc.create_equipment("合成史密斯", "smith")
    condition = {
        "equipment_instance_id": equipment["id"],
        "load_basis": "plates_per_side_kg",
        "load_basis_confirmed": True,
        "settings_confirmed": True,
        "side": "both",
        "repetition_semantics": "simultaneous",
        "rom_protocol": "full",
        "settings": {"bench_angle": 30},
        "symmetric_loading": True,
    }
    plan = svc.create_template(
        "合成胸计划",
        [
            {
                "exercise_id": "psa.ex.smith_incline_press",
                "condition": condition,
                "targets": {"sets": [{"reps_min": 8, "reps_max": 10, "rir": 2}]},
            }
        ],
    )
    session = svc.start_session(template_id=plan["id"])
    row = svc.edit_set(
        session["sets"][0]["id"],
        {
            "completion_state": "completed",
            "load_value": 30,
            "load_unit": "kg",
            "reps": 10,
            "rir": 2,
            "stop_reason": "plan_target",
        },
        base_revision=1,
    )
    svc.end_session(
        session["id"],
        session_rpe=7,
        rpe_scale="cr10",
        duration_seconds=3600,
        duration_protocol="elapsed",
    )
    return session, row


@pytest.mark.parametrize("format", ["json", "csv"])
def test_exchange_roundtrip_and_repeated_import(tmp_path, format):
    source = Repository(tmp_path / "source.sqlite3")
    svc = TrainingService(source)
    session, row = fixture(svc)
    path = export_training(source, tmp_path / f"export.{format}", format=format)
    preview = preview_import(path)
    assert preview["sets"] == 1 and preview["load_bases"] == ["plates_per_side_kg"]
    assert preview["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert preview["sample_rows"][0]["set_uuid"] == row["set_uuid"]
    target = Repository(tmp_path / "target.sqlite3")
    first = import_training(target, path)
    assert first["new"] == 1 and first["invalid"] == 0, first
    again = import_training(target, path)
    assert again["duplicate"] == 1 and again["new"] == 0, again
    restored = TrainingService(target).get_session(session["session_uuid"])
    actual = restored["sets"][0]
    assert (actual["load_value"], actual["reps"], actual["rir"], actual["stop_reason"]) == (
        "30",
        10,
        2,
        "plan_target",
    )
    assert actual["condition"]["load_basis"] == "plates_per_side_kg"
    assert restored["session_rpe"] == 7 and restored["plan_snapshot"]["items"]
    assert actual["available_at"] >= row["available_at"]
    assert target.one("SELECT raw_json FROM training_import_record") is not None
    target.close()
    source.close()


def test_source_revision_update_then_local_conflict_preserves_null(tmp_path):
    source = Repository(tmp_path / "source.sqlite3")
    svc = TrainingService(source)
    _, row = fixture(svc)
    path = tmp_path / "exchange.json"
    export_training(source, path)
    target = Repository(tmp_path / "target.sqlite3")
    local = TrainingService(target)
    assert import_training(target, path)["new"] == 1
    svc.edit_set(row["id"], {"reps": 8, "rir": None}, base_revision=row["revision"])
    export_training(source, path)
    updated = import_training(target, path)
    assert updated["updated"] == 1 and updated["invalid"] == 0, updated
    present = local.get_set(row["set_uuid"])
    assert present["reps"] == 8 and present["rir"] is None
    local.edit_set(present["id"], {"reps": 9}, base_revision=present["revision"])
    original = svc.get_set(row["id"])
    svc.edit_set(row["id"], {"reps": 7}, base_revision=original["revision"])
    export_training(source, path)
    conflict = import_training(target, path)
    assert conflict["conflicted"] == 1 and local.get_set(row["set_uuid"])["reps"] == 9
    assert local.list_conflicts()
    source.close()
    target.close()


def test_self_import_and_old_csv_unknown_semantics(tmp_path):
    repo = Repository(tmp_path / "same.sqlite3")
    svc = TrainingService(repo)
    fixture(svc)
    path = export_training(repo, tmp_path / "same.json")
    result = import_training(repo, path)
    assert result["duplicate"] == 1 and repo.count("strength_set") == 1, result
    old = tmp_path / "old.csv"
    old.write_text(
        "date,exercise_name,equipment,weight,reps,weight_unit,warmup\n2026-11-01,Test Bench,smith,30,10,kg,false\n"
    )
    assert preview_import(old)["load_basis"] == "unknown"
    result = import_training(repo, old)
    assert result["inserted"] == 1
    legacy = repo.one("SELECT * FROM strength_set WHERE exercise_name='Test Bench'")
    assert legacy["load_basis"] == "unknown" and legacy["catalog_id"] is None
    assert import_training(repo, old)["inserted"] == 0
    repo.close()


def test_deleted_source_tombstone_and_full_legacy_json_preservation(tmp_path):
    source = Repository(tmp_path / "source.sqlite3")
    svc = TrainingService(source)
    _, row = fixture(svc)
    path = export_training(source, tmp_path / "export.json")
    target = Repository(tmp_path / "target.sqlite3")
    import_training(target, path)
    svc.delete_set(row["id"], base_revision=row["revision"])
    export_training(source, path)
    result = import_training(target, path)
    assert result["deleted"] == 1 and TrainingService(target).get_set(row["set_uuid"])["deleted_at"]
    source.close()
    target.close()


@pytest.mark.parametrize("choice,expected", [("keep_current", 9), ("apply_proposed", 7)])
def test_resolved_source_conflict_is_not_reopened_on_reimport(tmp_path, choice, expected):
    source = Repository(tmp_path / "source.sqlite3")
    svc = TrainingService(source)
    _, row = fixture(svc)
    path = export_training(source, tmp_path / "export.json")
    target = Repository(tmp_path / "target.sqlite3")
    local = TrainingService(target)
    import_training(target, path)
    existing = local.get_set(row["set_uuid"])
    local.edit_set(existing["id"], {"reps": 9}, base_revision=existing["revision"])
    svc.edit_set(row["id"], {"reps": 7}, base_revision=row["revision"])
    export_training(source, path)
    assert import_training(target, path)["conflicted"] == 1
    assert import_training(target, path)["conflicted"] == 1
    assert len(local.list_conflicts()) == 1
    local.resolve_conflict(local.list_conflicts()[0]["id"], choice=choice)
    replay = import_training(target, path)
    assert replay["duplicate"] == 1 and replay["conflicted"] == 0, replay
    assert local.get_set(row["set_uuid"])["reps"] == expected
    assert local.list_conflicts() == []
    source.close()
    target.close()


def test_source_can_restore_deleted_row_and_revert_to_earlier_values(tmp_path):
    source = Repository(tmp_path / "source.sqlite3")
    svc = TrainingService(source)
    _, row = fixture(svc)
    path = export_training(source, tmp_path / "export.json")
    target = Repository(tmp_path / "target.sqlite3")
    import_training(target, path)
    edited = svc.edit_set(row["id"], {"reps": 8}, base_revision=row["revision"])
    export_training(source, path)
    assert import_training(target, path)["updated"] == 1
    reverted = svc.edit_set(row["id"], {"reps": 10}, base_revision=edited["revision"])
    export_training(source, path)
    assert import_training(target, path)["updated"] == 1
    assert TrainingService(target).get_set(row["set_uuid"])["reps"] == 10
    deleted = svc.delete_set(row["id"], base_revision=reverted["revision"])
    export_training(source, path)
    assert import_training(target, path)["deleted"] == 1
    svc.undo_event(deleted["event_id"], base_revision=deleted["revision"])
    export_training(source, path)
    result = import_training(target, path)
    assert result["updated"] == 1 and result["invalid"] == 0, result
    assert TrainingService(target).get_set(row["set_uuid"])["deleted_at"] is None
    source.close()
    target.close()


def test_source_delete_conflict_decision_includes_tombstone(tmp_path):
    source = Repository(tmp_path / "source.sqlite3")
    svc = TrainingService(source)
    _, row = fixture(svc)
    path = export_training(source, tmp_path / "export.json")
    target = Repository(tmp_path / "target.sqlite3")
    local = TrainingService(target)
    import_training(target, path)
    current = local.get_set(row["set_uuid"])
    local.edit_set(current["id"], {"notes": "本地更正"}, base_revision=current["revision"])
    svc.delete_set(row["id"], base_revision=row["revision"])
    export_training(source, path)
    assert import_training(target, path)["conflicted"] == 1
    assert local.get_set(row["set_uuid"])["deleted_at"] is None
    local.resolve_conflict(local.list_conflicts()[0]["id"], choice="apply_proposed")
    assert local.get_set(row["set_uuid"])["deleted_at"]
    assert import_training(target, path)["duplicate"] == 1
    source.close()
    target.close()


def test_invalid_session_rolls_back_partial_rows_and_counts(tmp_path):
    source = Repository(tmp_path / "source.sqlite3")
    svc = TrainingService(source)
    session, _ = fixture(svc)
    svc.add_set(
        session["exercises"][0]["id"],
        {"completion_state": "completed", "reps": 8},
        allow_completed_session=True,
    )
    path = export_training(source, tmp_path / "invalid.json")
    data = json.loads(path.read_text())
    data["sessions"][0]["exercises"][0]["sets"][1]["reps"] = -1
    path.write_text(json.dumps(data))
    target = Repository(tmp_path / "target.sqlite3")
    result = import_training(target, path)
    assert result["invalid"] == 1 and result["new"] == 0, result
    assert target.count("strength_session") == target.count("strength_set") == 0
    assert target.one("SELECT COUNT(*) FROM training_import_record")[0] == 0
    source.close()
    target.close()


def test_single_session_export_restores_dependencies_and_custom_definition(tmp_path):
    source = Repository(tmp_path / "source.sqlite3")
    svc = TrainingService(source)
    machine = svc.create_equipment("测试器械", "machine")
    definition = svc.create_exercise(
        "私人动作",
        recording_mode="repetitions",
        equipment_type="machine",
        load_basis="machine_setting",
    )
    session = svc.start_session()
    instance = svc.add_exercise(
        session["id"],
        definition["exercise_id"],
        {
            "equipment_instance_id": machine["id"],
            "load_basis": "machine_setting",
            "load_basis_confirmed": True,
        },
    )
    svc.add_set(
        instance["id"],
        {"completion_state": "completed", "load_value": 5, "load_unit": "level", "reps": 10},
    )
    path = tmp_path / "single.json"
    path.write_text(json.dumps(svc.export_session(session["id"])))
    target = Repository(tmp_path / "target.sqlite3")
    result = import_training(target, path)
    assert result["new"] == 1 and result["invalid"] == 0, result
    restored = TrainingService(target)
    assert restored.get_equipment(machine["id"])["label"] == "测试器械"
    assert restored.get_exercise(definition["exercise_id"])["custom"]
    assert restored.get_session(session["session_uuid"])["completed_sets"] == 1
    source.close()
    target.close()


def test_legacy_json_roundtrip_keeps_unknown_measurement_and_raw_fingerprint(tmp_path):
    source = Repository(tmp_path / "source.sqlite3")
    csv = tmp_path / "legacy.csv"
    csv.write_text(
        "date,exercise_name,equipment,weight,reps,weight_unit,warmup\n2026-11-01,Synthetic Bench,smith,30,10,kg,false\n"
    )
    import_training(source, csv)
    before = dict(source.one("SELECT * FROM strength_set"))
    path = export_training(source, tmp_path / "legacy.json")
    assert preview_import(path)["legacy_unassigned_sets"] == 1
    target = Repository(tmp_path / "target.sqlite3")
    result = import_training(target, path)
    assert result["new"] == 1
    assert import_training(target, path)["duplicate"] == 1
    after = dict(target.one("SELECT * FROM strength_set"))
    assert after["fingerprint"] == before["fingerprint"]
    assert after["weight_kg"] == before["weight_kg"] and after["load_basis"] == "unknown"
    assert after["session_id"] is None
    source.close()
    target.close()


def test_csv_roundtrip_retains_empty_sessions_and_unstarted_exercises(tmp_path):
    source = Repository(tmp_path / "source.sqlite3")
    svc = TrainingService(source)
    empty = svc.start_session("空训练")
    with_exercise = svc.start_session("未开始动作")
    svc.add_exercise(with_exercise["id"], "psa.ex.smith_incline_press", {})
    path = export_training(source, tmp_path / "empty.csv")
    assert preview_import(path)["sessions"] == 2 and preview_import(path)["sets"] == 0
    target = Repository(tmp_path / "target.sqlite3")
    assert import_training(target, path)["invalid"] == 0
    local = TrainingService(target)
    assert local.get_session(empty["session_uuid"])["exercises"] == []
    assert len(local.get_session(with_exercise["session_uuid"])["exercises"]) == 1
    source.close()
    target.close()


@pytest.mark.parametrize(
    "content",
    [[], {"schema_version": "1.3.0", "format": "healthzip.training.bundle", "sessions": "invalid"}],
)
def test_malformed_import_has_clear_validation_error(tmp_path, content):
    from healthzip.training import TrainingError

    path = tmp_path / "bad.json"
    path.write_text(json.dumps(content))
    with pytest.raises(TrainingError, match="字段或结构无效|必须是对象列表"):
        preview_import(path)
