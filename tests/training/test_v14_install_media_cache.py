"""Synthetic verification of the restricted media-cache installation tool."""

import hashlib
import json
import runpy
import sqlite3
from pathlib import Path

import pytest

HELPERS = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "tools" / "v14_install_media_cache.py")
)


def test_authorizer_denies_private_reads_writes_and_schema_changes():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE private_record(secret TEXT);"
        "INSERT INTO private_record VALUES('synthetic private value');"
        "CREATE TABLE catalog_media(media_id TEXT);"
        "CREATE TABLE schema_meta(key TEXT,value TEXT);"
        "CREATE VIEW catalog_leak AS SELECT secret FROM private_record;"
    )
    conn.set_authorizer(HELPERS["catalog_authorizer"](writable=True))
    for statement in (
        "SELECT * FROM private_record",
        "SELECT COUNT(*) FROM private_record",
        "SELECT * FROM catalog_leak",
        "UPDATE private_record SET secret='changed'",
        "DELETE FROM private_record",
        "INSERT INTO private_record VALUES('new')",
        "ALTER TABLE catalog_media ADD COLUMN unexpected TEXT",
        "CREATE TABLE catalog_unexpected(value TEXT)",
        "PRAGMA writable_schema=ON",
        "ATTACH DATABASE ':memory:' AS other",
        "SELECT load_extension('synthetic')",
    ):
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
    conn.execute("INSERT INTO catalog_media VALUES('synthetic-image')")
    assert conn.execute("SELECT COUNT(*) FROM catalog_media").fetchone()[0] == 1
    conn.close()


def prepare_catalog(path, media_path, *, ready):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.executescript(
        "CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT);"
        "INSERT INTO schema_meta VALUES('schema_version','4');"
        "CREATE TABLE private_record(secret TEXT);"
        "INSERT INTO private_record VALUES('synthetic committed WAL value');"
        "CREATE TABLE catalog_source_record(provider TEXT,source_uuid TEXT,snapshot_id TEXT);"
        "INSERT INTO catalog_source_record VALUES('synthetic','uuid','snapshot');"
        "CREATE TABLE catalog_source_mapping(provider TEXT,source_uuid TEXT,local_exercise_id TEXT);"
        "INSERT INTO catalog_source_mapping VALUES('synthetic','uuid','exercise');"
        "CREATE TABLE catalog_localization(local_exercise_id TEXT,locale TEXT,"
        "translation_version INTEGER,content TEXT);"
        "INSERT INTO catalog_localization VALUES('exercise','zh',1,'合成翻译');"
        "CREATE TABLE catalog_presentation(local_exercise_id TEXT,presentation_version INTEGER);"
        "INSERT INTO catalog_presentation VALUES('exercise',1);"
        "CREATE TABLE catalog_snapshot(snapshot_id TEXT);"
        "INSERT INTO catalog_snapshot VALUES('snapshot');"
        "CREATE TABLE catalog_media(media_id TEXT PRIMARY KEY,media_type TEXT,metadata_json TEXT,"
        "license_allowed INTEGER,fetch_status TEXT,blob_hash TEXT,local_path TEXT,"
        "verified_at TEXT,error TEXT);"
    )
    metadata = {"source_uuid": "uuid", "original_url": "https://wger.de/media/synthetic.png",
                "license": "synthetic allowed license", "license_scope": "individual_media_object",
                "author": "Synthetic Author", "changes": "none"}
    if ready:
        metadata["verified_file"] = {"mime": "image/png", "size": media_path.stat().st_size}
    digest = hashlib.sha256(media_path.read_bytes()).hexdigest()
    conn.execute(
        "INSERT INTO catalog_media VALUES(?,?,?,?,?,?,?,?,?)",
        ("synthetic.image", "image", json.dumps(metadata), 1, "ready" if ready else "pending",
         digest if ready else None, str(media_path) if ready else None, "synthetic-time", None),
    )
    conn.commit()
    return conn


def test_install_preserves_definitions_and_backup_contains_committed_wal(tmp_path):
    blob = tmp_path / "synthetic-blob"
    blob.write_bytes(b"synthetic cached public media")
    source_path, target_path = tmp_path / "source.sqlite3", tmp_path / "target.sqlite3"
    source = prepare_catalog(source_path, blob, ready=True)
    target = prepare_catalog(target_path, blob, ready=False)
    assert Path(str(target_path) + "-wal").stat().st_size > 0
    try:
        report = HELPERS["install_media_cache"](source_path, target_path, tmp_path / "backups")
        assert report["attached_verified_media"] == 1
        assert report["public_definitions_and_translations_unchanged"] is True
        assert report["private_SQL_read_denied"] is True
        assert report["target_media_counts_after"] == [
            {"media_type": "image", "fetch_status": "ready", "count": 1}
        ]
        assert target.execute("SELECT secret FROM private_record").fetchone()[0] == (
            "synthetic committed WAL value"
        )
        backups = list((tmp_path / "backups").glob("*.sqlite3"))
        assert len(backups) == 1
        backup = sqlite3.connect(backups[0])
        try:
            assert backup.execute("SELECT secret FROM private_record").fetchone()[0] == (
                "synthetic committed WAL value"
            )
            assert backup.execute("SELECT fetch_status FROM catalog_media").fetchone()[0] == "pending"
        finally:
            backup.close()
        with pytest.raises(sqlite3.DatabaseError):
            restricted_source = HELPERS["connect_catalog"](source_path)
            try:
                restricted_source.execute("UPDATE catalog_media SET fetch_status='pending'")
            finally:
                restricted_source.close()
        output = tmp_path / "report.json"
        original = {"status": "passed", "method": "historical initial installation"}
        output.write_text(json.dumps(original))
        HELPERS["write_report"](output, report)
        saved = json.loads(output.read_text())
        assert {key: saved[key] for key in original} == original
        assert saved["media_cache_update"] == report
        assert "synthetic committed WAL value" not in output.read_text()
        assert str(tmp_path) not in output.read_text()
    finally:
        source.close()
        target.close()
