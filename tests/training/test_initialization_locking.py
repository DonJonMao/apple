"""Warm training connections remain readers while cold initialization is atomic."""

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from healthzip.db.repository import Repository
from healthzip.training import TrainingService
from healthzip.training import service as service_module
from healthzip.training.service import TRAINING_INITIALIZATION_KEY


def marker(conn):
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key=?", (TRAINING_INITIALIZATION_KEY,)
    ).fetchone()
    return row[0] if row else None


def test_warm_constructor_reads_while_another_connection_holds_writer_lock(tmp_path):
    path = tmp_path / "synthetic-warm-lock.sqlite3"
    repo = Repository(path)
    TrainingService(repo)
    writer = sqlite3.connect(path)
    repo.conn.execute("PRAGMA busy_timeout=50")
    before = repo.conn.total_changes
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO schema_meta VALUES('synthetic_pending_writer','1')")
        service = TrainingService(repo)
        assert service.data_version() == "0"
        assert repo.conn.execute("SELECT COUNT(*) FROM exercise_catalog").fetchone()[0] == 46
        assert repo.conn.total_changes == before
        assert not repo.conn.in_transaction
        assert not repo.conn.execute(
            "SELECT 1 FROM schema_meta WHERE key='synthetic_pending_writer'"
        ).fetchone()
    finally:
        writer.rollback()
        writer.close()
        repo.close()


def test_warm_constructor_registers_functions_for_real_training_event_triggers(tmp_path):
    repo = Repository(tmp_path / "synthetic-warm-functions.sqlite3")
    try:
        TrainingService(repo)
        repo.conn.create_function("healthzip_instant_us", 1, None)
        service = TrainingService(repo)
        equipment = service.create_equipment("Synthetic station", "barbell")
        condition = {"equipment_instance_id": equipment["id"], "load_basis": "external_total_kg",
            "load_basis_confirmed": True, "settings_confirmed": True, "settings": {},
            "side": "both", "repetition_semantics": "simultaneous", "rom_protocol": "declared_full"}
        when = "2026-01-01T08:00:00+00:00"
        session = service.start_session("Synthetic trigger check", started_at=when)
        instance = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
        saved = service.add_set(instance["id"], {"completion_state": "completed",
            "load_value": 40, "load_unit": "kg", "reps": 8,
            "started_at": when, "ended_at": when})
        candidate = repo.conn.execute(
            "SELECT candidate_instant_us FROM training_event_set_candidate WHERE set_uuid=?",
            (saved["set_uuid"],),
        ).fetchone()
        assert candidate is not None and candidate[0] == 1767254400000000
    finally:
        repo.close()


def test_missing_initialization_marker_repairs_seed_without_overwriting_existing_rows(tmp_path):
    repo = Repository(tmp_path / "synthetic-missing-marker.sqlite3")
    try:
        TrainingService(repo)
        identities = [row[0] for row in repo.conn.execute(
            "SELECT exercise_id FROM exercise_catalog ORDER BY exercise_id LIMIT 2"
        )]
        repo.conn.execute("DELETE FROM exercise_catalog WHERE exercise_id=?", (identities[0],))
        repo.conn.execute("UPDATE exercise_catalog SET name='Synthetic edited label' WHERE exercise_id=?",
            (identities[1],))
        repo.conn.execute("DELETE FROM schema_meta WHERE key=?", (TRAINING_INITIALIZATION_KEY,))
        repo.conn.commit()
        TrainingService(repo)
        assert marker(repo.conn)
        assert repo.conn.execute("SELECT COUNT(*) FROM exercise_catalog").fetchone()[0] == 46
        assert repo.conn.execute("SELECT name FROM exercise_catalog WHERE exercise_id=?",
            (identities[1],)).fetchone()[0] == "Synthetic edited label"
    finally:
        repo.close()


def test_actual_seed_bytes_change_invalidates_initialization(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "synthetic-seed-revision.sqlite3")
    try:
        TrainingService(repo)
        original = marker(repo.conn)
        seed_path = Path(service_module.__file__).with_name("exercise_catalog_seed.json")
        seed = json.loads(seed_path.read_bytes())
        seed["exercises"].append({**seed["exercises"][0],
            "exercise_id": "synthetic.changed_seed", "name_zh": "Synthetic seed revision"})
        replacement = json.dumps(seed).encode()
        read_bytes = Path.read_bytes

        def revised_bytes(path):
            return replacement if path == seed_path else read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", revised_bytes)
        TrainingService(repo)
        assert marker(repo.conn) != original
        assert marker(repo.conn).endswith(hashlib.sha256(replacement).hexdigest())
        assert repo.conn.execute(
            "SELECT name FROM exercise_catalog WHERE exercise_id='synthetic.changed_seed'"
        ).fetchone()[0] == "Synthetic seed revision"
    finally:
        repo.close()


@pytest.mark.parametrize("warm", [False, True])
def test_initialization_never_commits_a_callers_pending_transaction(tmp_path, warm):
    path = tmp_path / "synthetic-outer-transaction.sqlite3"
    repo = Repository(path)
    if warm:
        TrainingService(repo)
    existing_marker = marker(repo.conn)
    try:
        repo.conn.execute("INSERT INTO schema_meta VALUES('synthetic_caller_pending','1')")
        TrainingService(repo)
        assert repo.conn.in_transaction
        observer = sqlite3.connect(path)
        try:
            assert not observer.execute(
                "SELECT 1 FROM schema_meta WHERE key='synthetic_caller_pending'"
            ).fetchone()
            assert marker(observer) == existing_marker
        finally:
            observer.close()
        repo.conn.rollback()
        assert not repo.conn.execute(
            "SELECT 1 FROM schema_meta WHERE key='synthetic_caller_pending'"
        ).fetchone()
        assert marker(repo.conn) == existing_marker
    finally:
        repo.close()


@pytest.mark.parametrize("outer", [False, True])
def test_cold_initialization_interruption_rolls_back_only_its_own_changes(tmp_path, monkeypatch, outer):
    repo = Repository(tmp_path / "synthetic-interrupted-init.sqlite3")
    original = TrainingService._seed_catalog

    def interrupted(service, seed=None):
        original(service, seed)
        raise KeyboardInterrupt("synthetic initialization interruption")

    monkeypatch.setattr(TrainingService, "_seed_catalog", interrupted)
    try:
        if outer:
            repo.conn.execute("INSERT INTO schema_meta VALUES('synthetic_caller_pending','1')")
        with pytest.raises(KeyboardInterrupt, match="synthetic initialization interruption"):
            TrainingService(repo)
        assert repo.conn.in_transaction is outer
        assert bool(repo.conn.execute(
            "SELECT 1 FROM schema_meta WHERE key='synthetic_caller_pending'"
        ).fetchone()) is outer
        assert repo.conn.execute("SELECT COUNT(*) FROM exercise_catalog").fetchone()[0] == 0
        assert marker(repo.conn) is None
    finally:
        repo.close()


def test_concurrent_cold_initializers_recheck_markers_after_the_writer_lock(tmp_path, monkeypatch):
    path = tmp_path / "synthetic-concurrent-init.sqlite3"
    repo = Repository(path)
    repo.close()
    first_has_lock = threading.Event()
    second_begin = threading.Event()
    calls, errors = [], []
    original_seed = TrainingService._seed_catalog
    original_migration = service_module.migrate_training

    def counted_migration(conn):
        calls.append(threading.current_thread().name)
        original_migration(conn)

    def held_seed(service, seed=None):
        if threading.current_thread().name == "synthetic-first":
            first_has_lock.set()
            if not second_begin.wait(5):
                raise RuntimeError("second initializer never attempted its write lock")
        original_seed(service, seed)

    monkeypatch.setattr(service_module, "migrate_training", counted_migration)
    monkeypatch.setattr(TrainingService, "_seed_catalog", held_seed)

    def initialize(second=False):
        conn = sqlite3.connect(path, timeout=10)
        if second:
            conn.set_trace_callback(lambda sql: second_begin.set() if sql == "BEGIN IMMEDIATE" else None)
        try:
            TrainingService(SimpleNamespace(conn=conn))
        except BaseException as error:
            errors.append(error)
        finally:
            conn.close()

    first = threading.Thread(target=initialize, name="synthetic-first")
    second = threading.Thread(target=initialize, args=(True,), name="synthetic-second")
    first.start()
    assert first_has_lock.wait(5)
    second.start()
    first.join(10)
    second.join(10)
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    assert second_begin.is_set()
    assert calls == ["synthetic-first"]
    conn = sqlite3.connect(path)
    try:
        assert marker(conn)
        assert conn.execute("SELECT COUNT(*) FROM exercise_catalog").fetchone()[0] == 46
    finally:
        conn.close()
