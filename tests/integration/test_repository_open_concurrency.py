"""Real SQLite connections preserve readers and serialize only migrations."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest

from healthzip.db.repository import REPOSITORY_MIGRATION_REVISION, Repository


def test_current_repository_opens_and_reads_while_another_connection_is_writing(tmp_path):
    path = tmp_path / "synthetic.sqlite3"
    writer = Repository(path)
    writer.conn.execute("BEGIN IMMEDIATE")
    writer.conn.execute("INSERT INTO schema_meta VALUES('synthetic_uncommitted','pending')")
    try:
        reader = Repository(path, timeout=0.05)
        try:
            assert not reader.conn.in_transaction
            assert reader.conn.total_changes == 0
            assert reader.one("SELECT value FROM schema_meta WHERE key='synthetic_uncommitted'") is None
            assert reader.one("SELECT healthzip_instant_us('1970-01-01T00:00:01Z')")[0] == 1000000
            assert writer.conn.in_transaction
        finally:
            reader.close()
    finally:
        writer.conn.rollback()
        writer.close()


def test_existing_v5_without_revision_gets_atomic_compatibility_migration(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.sqlite3"
    repo = Repository(path)
    repo.conn.execute("DELETE FROM schema_meta WHERE key='repository_migration_revision'")
    repo.conn.commit()
    repo.close()
    migrate = Repository._migrate_schema

    def interrupted(self):
        migrate(self)
        raise KeyboardInterrupt("synthetic migration cancellation")

    with monkeypatch.context() as patch:
        patch.setattr(Repository, "_migrate_schema", interrupted)
        with pytest.raises(KeyboardInterrupt):
            Repository(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == "5"
        assert conn.execute("SELECT value FROM schema_meta WHERE key='repository_migration_revision'").fetchone() is None
    repo = Repository(path)
    assert repo.one("SELECT value FROM schema_meta WHERE key='repository_migration_revision'")[0] == str(REPOSITORY_MIGRATION_REVISION)
    repo.close()


@pytest.mark.parametrize("key,value", [("schema_version", "99"), ("repository_migration_revision", "99")])
def test_newer_database_is_rejected_without_waiting_for_a_writer(tmp_path, key, value):
    path = tmp_path / "synthetic.sqlite3"
    writer = Repository(path)
    writer.conn.execute("UPDATE schema_meta SET value=? WHERE key=?", (value, key))
    writer.conn.commit()
    writer.conn.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(ValueError, match="newer"):
            Repository(path, timeout=0.05)
        assert writer.conn.in_transaction
        assert writer.one("SELECT value FROM schema_meta WHERE key=?", (key,))[0] == value
    finally:
        writer.conn.rollback()
        writer.close()


def test_concurrent_old_openers_recheck_after_waiting_for_migration_lock(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.sqlite3"
    initial = Repository(path)
    initial.conn.execute("DELETE FROM schema_meta WHERE key='repository_migration_revision'")
    initial.conn.commit()
    initial.close()
    writer = sqlite3.connect(path)
    writer.execute("BEGIN IMMEDIATE")
    original_connect = sqlite3.connect
    waiting = Event()
    guard = Lock()
    statements = []
    attempts = 0

    def trace(sql):
        nonlocal attempts
        with guard:
            statements.append(sql)
            if sql == "BEGIN IMMEDIATE":
                attempts += 1
                if attempts == 2:
                    waiting.set()

    def connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(trace)
        return conn

    def open_repository():
        repo = Repository(path, timeout=3)
        try:
            assert not repo.conn.in_transaction
            return repo.one("SELECT value FROM schema_meta WHERE key='repository_migration_revision'")[0]
        finally:
            repo.close()

    monkeypatch.setattr(sqlite3, "connect", connect)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(open_repository) for _ in range(2)]
            try:
                assert waiting.wait(2), "Both readers must inspect the old state before lock release"
            finally:
                writer.rollback()
            assert [future.result(timeout=4) for future in futures] == [str(REPOSITORY_MIGRATION_REVISION)] * 2
    finally:
        writer.close()
    marker_writes = [sql for sql in statements if sql.startswith("INSERT OR REPLACE")
                     and "repository_migration_revision" in sql]
    assert len(marker_writes) == 1


def test_cancelled_repository_transaction_rolls_back_and_releases_writer(tmp_path):
    repo = Repository(tmp_path / "synthetic.sqlite3")
    try:
        with pytest.raises(KeyboardInterrupt):
            with repo.transaction():
                repo.conn.execute("INSERT INTO schema_meta VALUES('synthetic_cancelled','pending')")
                raise KeyboardInterrupt("synthetic rerun")
        assert not repo.conn.in_transaction
        assert repo.one("SELECT value FROM schema_meta WHERE key='synthetic_cancelled'") is None
    finally:
        repo.close()
