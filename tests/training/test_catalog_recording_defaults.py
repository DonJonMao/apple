"""Default current catalog entries without rewriting historical definitions."""

import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_v14_catalog import snapshot, source

from healthzip.db.repository import Repository
from healthzip.training import catalog_import
from healthzip.training.catalog_import import (
    DEFAULT_RECORDING_MODE_BASIS,
    publish_snapshot,
)
from healthzip.training.service import TRAINING_INITIALIZATION_KEY, TrainingService
from healthzip.ui.training_bridge import build_snapshot, handle_command

LEGACY_ID = "catalog.wger.synthetic-default"
SECOND_ID = "catalog.wger.synthetic-default-second"


def command(action, **payload):
    return {"id": str(uuid4()), "action": action, "payload": payload}


def install_legacy_catalog(repo):
    """Represent an installed pre-default directory using only synthetic rows."""
    svc = TrainingService(repo)
    for identity, name, mode, owner in (
        (LEGACY_ID, "合成旧目录划船", "unknown", "public"),
        (SECOND_ID, "合成旧目录推举", "unknown", "public"),
        ("catalog.wger.synthetic-duration", "合成计时目录", "duration", "public"),
        ("catalog.wger.synthetic-distance", "合成距离目录", "distance", "public"),
        ("custom.synthetic-legacy-unknown", "合成私人未定义", "unknown", "local"),
    ):
        definition = {"exercise_id": identity, "definition_version": 1, "name_zh": name,
            "recording_mode": mode, "mode_basis": "requires_user_confirmation" if mode == "unknown" else "catalog_mapping_review",
            "equipment_type": "other", "default_load_basis": "unknown", "requires_load_basis_confirmation": True,
            "display_regions": ["back"], "source": {"provider": "synthetic", "source_uuid": identity},
            "scientific_review": {"status": "unreviewed", "source_ids": []}}
        repo.conn.execute("INSERT INTO exercise_catalog(exercise_id,definition_version,owner_id,name,definition_json,custom,created_at) VALUES(?,1,?,?,?,?,?)",
            (identity, owner, name, json.dumps(definition, ensure_ascii=False), int(owner != "public"), "2026-01-01T00:00:00+00:00"))
    repo.conn.commit()
    return svc


def mark_previous_initialization(repo):
    row = repo.conn.execute("SELECT value FROM schema_meta WHERE key=?", (TRAINING_INITIALIZATION_KEY,)).fetchone()
    marker = "training-service-init-v1:" + row[0].split(":", 1)[1]
    repo.conn.execute("UPDATE schema_meta SET value=? WHERE key=?", (marker, TRAINING_INITIALIZATION_KEY))
    repo.conn.commit()
    return marker


def test_new_source_catalog_adds_directly_with_unconfirmed_load_and_actual_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        publish_snapshot(repo, snapshot(tmp_path))
        svc, state = TrainingService(repo), {}
        identity = "catalog.wger.synthetic-row"
        item = svc.get_exercise(identity)
        assert item["recording_mode"] == "repetitions"
        assert item["mode_basis"] == DEFAULT_RECORDING_MODE_BASIS
        assert item["default_load_basis"] == "unknown" and item["requires_load_basis_confirmation"]
        session = handle_command(repo, command("start_session"), state)["data"]
        add = command("add_exercises", session_id=session["id"], base_revision=session["revision"], exercises=[{"exercise_id": identity}])
        response = handle_command(repo, add, state)
        assert response["status"] == "saved", response
        instance = response["data"]["exercises"][0]
        assert instance["catalog_id"] == identity
        assert instance["condition"]["measurement_mode"] == "repetitions"
        assert instance["condition"]["load_basis"] == "unknown"
        assert not instance["condition"].get("load_basis_confirmed")
        row = instance["sets"][0]
        saved = handle_command(repo, command("save_set", set_id=row["set_uuid"], base_revision=row["revision"],
            changes={"load_value": "32.5", "load_unit": "kg", "reps": 8, "rir": 0}, complete=True), state)
        assert saved["status"] == "saved", saved
        actual = svc.get_set(row["set_uuid"])
        assert (actual["load_value"], actual["reps"], actual["rir"]) == ("32.5", 8, 0)
        assert actual["load_basis"] == "unknown" and actual["condition_key"] is None
        assert handle_command(repo, add, state)["replayed"]
        assert len(svc.get_session(session["id"])["exercises"]) == 1


def test_existing_catalog_upgrade_is_versioned_preserves_history_and_retries_failed_add(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "synthetic.sqlite3"
    with closing(Repository(path)) as repo:
        svc = install_legacy_catalog(repo)
        history = svc.start_session("合成历史")
        for suffix, field in (("duration", "duration_s"), ("distance", "distance_m")):
            instance = svc.add_exercise(history["id"], "catalog.wger.synthetic-" + suffix, {})
            svc.add_set(instance["id"], {field: 30, "completion_state": "completed"})
        svc.end_session(history["id"])
        state = {}
        session = handle_command(repo, command("start_session"), state)["data"]
        add = command("add_exercises", session_id=session["id"], base_revision=session["revision"], exercises=[{"exercise_id": LEGACY_ID}])
        assert handle_command(repo, add, state)["status"] == "error"
        handle_command(repo, command("catalog", query="合成旧目录"), state)
        assert state["catalog"]["items"][0]["recording_mode"] == "unknown"
        tables = ("training_session_exercise", "strength_set", "training_event", "training_template_version")
        before = {table: list(map(tuple, repo.conn.execute("SELECT * FROM " + table))) for table in tables}
        old_definition = repo.conn.execute("SELECT definition_json FROM exercise_catalog WHERE exercise_id=?", (LEGACY_ID,)).fetchone()[0]
        mark_previous_initialization(repo)
        upgraded = TrainingService(repo)
        item = upgraded.get_exercise(LEGACY_ID)
        assert item["definition_version"] == 2 and item["recording_mode"] == "repetitions"
        assert item["mode_basis"] == DEFAULT_RECORDING_MODE_BASIS
        assert item["default_load_basis"] == "unknown" and item["scientific_review"]["status"] == "unreviewed"
        assert upgraded.get_exercise(LEGACY_ID, 1)["recording_mode"] == "unknown"
        assert repo.conn.execute("SELECT definition_json FROM exercise_catalog WHERE exercise_id=? AND definition_version=1", (LEGACY_ID,)).fetchone()[0] == old_definition
        assert before == {table: list(map(tuple, repo.conn.execute("SELECT * FROM " + table))) for table in tables}
        for suffix in ("duration", "distance"):
            known = upgraded.get_exercise("catalog.wger.synthetic-" + suffix)
            assert known["recording_mode"] == suffix and known["definition_version"] == 1
        private = upgraded.get_exercise("custom.synthetic-legacy-unknown")
        assert private["recording_mode"] == "unknown" and private["definition_version"] == 1
        assert build_snapshot(repo, state)["catalog"] is None
        retried = handle_command(repo, add, state)
        assert retried["status"] == "saved", retried
        assert retried["data"]["exercises"][0]["definition_version"] == 2
        writes = repo.conn.total_changes
        with closing(sqlite3.connect(path)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            repo.conn.execute("PRAGMA busy_timeout=50")
            TrainingService(repo)
            assert repo.conn.total_changes == writes
            writer.rollback()
        assert repo.conn.execute("SELECT COUNT(*) FROM exercise_catalog WHERE exercise_id=?", (LEGACY_ID,)).fetchone()[0] == 2


def test_catalog_default_upgrade_failure_rolls_back_versions_and_marker(tmp_path, monkeypatch):
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        install_legacy_catalog(repo)
        marker = mark_previous_initialization(repo)
        original = catalog_import.migrate_default_recording_modes
        def interrupted(conn):
            original(conn)
            raise RuntimeError("synthetic default-mode upgrade interruption")
        monkeypatch.setattr(catalog_import, "migrate_default_recording_modes", interrupted)
        with pytest.raises(RuntimeError, match="upgrade interruption"):
            TrainingService(repo)
        assert repo.conn.execute("SELECT value FROM schema_meta WHERE key=?", (TRAINING_INITIALIZATION_KEY,)).fetchone()[0] == marker
        assert repo.conn.execute("SELECT COUNT(*) FROM exercise_catalog WHERE exercise_id=?", (LEGACY_ID,)).fetchone()[0] == 1
        assert not repo.conn.execute("SELECT value FROM schema_meta WHERE key='catalog_data_version'").fetchone()
        monkeypatch.setattr(catalog_import, "migrate_default_recording_modes", original)
        assert TrainingService(repo).get_exercise(LEGACY_ID)["recording_mode"] == "repetitions"


@pytest.mark.parametrize("mode", ["duration", "distance"])
def test_reimport_keeps_explicit_mode_when_source_has_no_measurement_semantics(tmp_path, mode):
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        publish_snapshot(repo, snapshot(tmp_path))
        svc = TrainingService(repo)
        identity = "catalog.wger.synthetic-row"
        definition = svc.get_exercise(identity)
        definition.update(definition_version=2, recording_mode=mode, mode_basis="catalog_mapping_review")
        repo.conn.execute("INSERT INTO exercise_catalog(exercise_id,definition_version,owner_id,name,definition_json,created_at) VALUES(?,2,'public',?,?,?)",
            (identity, definition["name"], json.dumps(definition), "2026-01-02T00:00:00+00:00"))
        repo.conn.commit()
        session = svc.start_session("合成已明确方式")
        old = svc.add_exercise(session["id"], identity, {})
        frozen = old["definition_snapshot"]
        publish_snapshot(repo, snapshot(tmp_path, [source(equipment="Barbell")], suffix="changed"))
        latest = svc.get_exercise(identity)
        assert latest["definition_version"] == 3 and latest["recording_mode"] == mode
        assert latest["mode_basis"] == "catalog_mapping_review"
        assert svc.get_session_exercise(old["id"])["definition_snapshot"] == frozen
