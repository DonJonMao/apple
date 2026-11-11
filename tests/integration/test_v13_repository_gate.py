import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from healthzip.db.backup import backup_database, restore_database
from healthzip.db.repository import Repository


def test_repository_outer_migration_rolls_back_all_added_tables(tmp_path, monkeypatch):
    path = tmp_path / "v1.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT); INSERT INTO schema_meta VALUES('schema_version','1');")
    conn.close()
    def fail(conn):
        raise RuntimeError("simulated interruption after training DDL")
    with monkeypatch.context() as patch:
        patch.setattr("healthzip.db.temporal_schema.migrate_temporal", fail)
        with pytest.raises(RuntimeError):
            Repository(path)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == "1"
    assert [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")] == ["schema_meta"]
    conn.close()
    repo = Repository(path)
    assert repo.one("SELECT value FROM schema_meta WHERE key='schema_version'")[0] == "4"
    repo.close()


def test_backup_restores_committed_wal_and_refuses_overwrite(tmp_path):
    path, backup, restored = [tmp_path / name for name in ("original.sqlite3", "backup.sqlite3", "restored.sqlite3")]
    repo = Repository(path)
    repo.conn.execute("INSERT INTO schema_meta VALUES('synthetic_test_value','saved')")
    repo.conn.commit()
    backup_database(path, backup)
    restore_database(backup, restored)
    copy = Repository(restored)
    assert copy.one("SELECT value FROM schema_meta WHERE key='synthetic_test_value'")[0] == "saved"
    with pytest.raises(FileExistsError):
        restore_database(backup, path)
    copy.close()
    repo.close()


def test_newer_database_not_downgraded(tmp_path):
    path = tmp_path / "future.sqlite3"
    repo = Repository(path)
    repo.conn.execute("UPDATE schema_meta SET value='99' WHERE key='schema_version'")
    repo.conn.commit()
    repo.close()
    with pytest.raises(ValueError, match="newer"):
        Repository(path)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == "99"
    conn.close()


def test_legacy_health_baseline_visible_after_migration_never_backdated(tmp_path):
    from healthzip.db.repository import SCHEMA
    from healthzip.db.temporal_schema import samples_as_of
    path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO import_batch(id,file_sha256,imported_at,status) VALUES(1,'legacy','2019-01-01T00:00:00Z','completed')")
    conn.execute("INSERT INTO health_sample(import_batch_id,fingerprint,raw_type,canonical_type,normalized_value,start_utc,end_utc,created_at) VALUES(1,'legacy','HKQuantityTypeIdentifierRestingHeartRate','resting_heart_rate_bpm',60,'2019-01-01T00:00:00Z','2019-01-01T00:00:00Z','2019-01-01T00:00:00Z')")
    conn.commit()
    conn.close()
    repo = Repository(path)
    assert samples_as_of(repo, "2020-01-01T00:00:00Z") == []
    cutoff = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    rows = samples_as_of(repo, cutoff)
    assert rows[0]["normalized_value"] == 60
    assert rows[0]["temporal_provenance"] == "observed_at_migration_historical_visibility_unknown"
    count = repo.one("SELECT COUNT(*) FROM source_revision")[0]
    repo.close()
    repo = Repository(path)
    assert repo.one("SELECT COUNT(*) FROM source_revision")[0] == count
    repo.close()
