import sqlite3

import pytest

from healthzip.training import migrate_training


def legacy_connection(version=2):
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
    CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    INSERT INTO schema_meta VALUES('schema_version','2');
    CREATE TABLE strength_session(id INTEGER PRIMARY KEY,session_date TEXT);
    CREATE TABLE strength_set(id INTEGER PRIMARY KEY,session_id INTEGER,weight_kg REAL,
      side TEXT,equipment TEXT,range_of_motion TEXT,set_number INTEGER);
    INSERT INTO strength_session VALUES(7,'2026-01-01');
    INSERT INTO strength_set VALUES(19,7,30,'','','',1);
    """)
    conn.execute("UPDATE schema_meta SET value=? WHERE key='schema_version'", (str(version),))
    conn.commit()
    return conn


@pytest.mark.parametrize("version", [1, 2])
def test_v2_additive_unknown_preservation_and_rerun(version):
    conn = legacy_connection(version)
    migrate_training(conn)
    row = conn.execute(
        "SELECT id,session_id,weight_kg,side,equipment,range_of_motion,load_basis,catalog_id,completion_state,legacy_raw_value,available_at FROM strength_set"
    ).fetchone()
    assert row == (19, 7, 30.0, "", "", "", "unknown", None, None, "30.0", None)
    migrate_training(conn)
    assert conn.execute("SELECT COUNT(*) FROM strength_set").fetchone()[0] == 1
    assert (
        conn.execute(
            "SELECT value FROM schema_meta WHERE key='training_schema_version'"
        ).fetchone()[0]
        == "3"
    )


def test_interrupted_migration_rolls_back_every_added_column_and_reruns():
    conn = legacy_connection()
    original = [tuple(r) for r in conn.execute("PRAGMA table_info(strength_session)")]

    def interrupt(step):
        if step == "strength_set":
            raise RuntimeError("synthetic interruption")

    with pytest.raises(RuntimeError, match="interruption"):
        migrate_training(conn, checkpoint=interrupt)
    assert [tuple(r) for r in conn.execute("PRAGMA table_info(strength_session)")] == original
    assert conn.execute("SELECT id,weight_kg FROM strength_set").fetchone() == (19, 30.0)
    migrate_training(conn)
    assert conn.execute("SELECT load_basis FROM strength_set").fetchone()[0] == "unknown"


def test_outer_transaction_can_rollback_whole_upgrade():
    conn = legacy_connection()
    conn.execute("BEGIN")
    migrate_training(conn)
    conn.rollback()
    assert "load_basis" not in {r[1] for r in conn.execute("PRAGMA table_info(strength_set)")}


def test_online_backup_and_non_destructive_restore(tmp_path):
    from healthzip.db.repository import Repository
    from healthzip.training.backup import backup_database, restore_database

    repo = Repository(tmp_path / "source.sqlite3")
    repo.conn.execute("INSERT INTO schema_meta(key,value) VALUES('synthetic_backup_marker','kept')")
    repo.conn.commit()
    backup = backup_database(repo, tmp_path / "backup.sqlite3")
    restored = restore_database(backup, tmp_path / "restored.sqlite3")
    with sqlite3.connect(restored) as conn:
        assert (
            conn.execute(
                "SELECT value FROM schema_meta WHERE key='synthetic_backup_marker'"
            ).fetchone()[0]
            == "kept"
        )
    with pytest.raises(FileExistsError):
        restore_database(backup, tmp_path / "source.sqlite3")
    with pytest.raises(FileExistsError):
        backup_database(repo, backup)
    repo.close()
