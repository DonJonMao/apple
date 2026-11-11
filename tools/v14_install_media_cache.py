"""Attach public verified media without initializing or querying private data.

SQLite's backup API copies the existing database, including committed WAL pages,
before installation. SQL authorizers restrict both connections to public catalog
tables; only catalog_media and schema_meta may be written on the target.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from healthzip.training.catalog_media import reuse_media_cache

PROTECTED_TABLES = {
    "catalog_source_record": "provider,source_uuid,snapshot_id",
    "catalog_source_mapping": "provider,source_uuid,local_exercise_id",
    "catalog_localization": "local_exercise_id,locale,translation_version",
    "catalog_presentation": "local_exercise_id,presentation_version",
    "catalog_snapshot": "snapshot_id",
}


def catalog_authorizer(*, writable=False):
    """Deny private reads, private writes, DDL, PRAGMAs and attached databases."""

    def authorize(action, first, second, database, trigger):
        if trigger is not None or database not in {None, "main"}:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ:
            allowed = first.startswith("catalog_") or first in {"schema_meta", "sqlite_master"}
            return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY
        if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
            allowed = writable and first in {"catalog_media", "schema_meta"}
            return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_OK if second == "count" else sqlite3.SQLITE_DENY
        if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_TRANSACTION}:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    return authorize


def connect_catalog(path, *, writable=False):
    """Open an existing database directly; never run Repository migrations."""
    uri = Path(path).resolve().as_uri() + ("?mode=rw" if writable else "?mode=ro")
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.set_authorizer(catalog_authorizer(writable=writable))
    return conn


def backup_database(conn, folder):
    """Create a new owner-only backup; no SQL reads of private tables occur."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = folder / f"v14-before-media-cache-{stamp}-{uuid4().hex}.sqlite3"
    path.touch(mode=0o600, exist_ok=False)
    backup = sqlite3.connect(path)
    try:
        backup.set_authorizer(catalog_authorizer())
        conn.backup(backup)
    finally:
        backup.close()
    return path


def protected_fingerprints(conn):
    result = {}
    for table, ordering in PROTECTED_TABLES.items():
        digest = hashlib.sha256()
        count = 0
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY {ordering}"):
            raw = json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode()
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
            count += 1
        result[table] = {"rows": count, "sha256": digest.hexdigest()}
    return result


def media_counts(conn):
    return [
        {"media_type": row[0], "fetch_status": row[1], "count": row[2]}
        for row in conn.execute(
            "SELECT media_type,fetch_status,COUNT(*) FROM catalog_media "
            "GROUP BY media_type,fetch_status ORDER BY media_type,fetch_status"
        )
    ]


def install_media_cache(source_path, target_path, backup_folder):
    source = connect_catalog(source_path)
    target = connect_catalog(target_path, writable=True)
    try:
        before = protected_fingerprints(target)
        before_counts = media_counts(target)
        source_counts = media_counts(source)
        backup_database(target, backup_folder)
        result = reuse_media_cache(SimpleNamespace(conn=target), SimpleNamespace(conn=source))
        if protected_fingerprints(target) != before:
            raise RuntimeError("Public catalog definitions changed during media installation")
        return {
            "status": "passed",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "backup_created": True,
            "backup_method": "SQLite backup API; includes committed WAL pages",
            "private_SQL_read_denied": True,
            "private_SQL_write_denied": True,
            "sql_policy": {
                "read": ["catalog_*", "schema_meta", "sqlite_master"],
                "write": ["catalog_media", "schema_meta"],
                "ddl_and_attached_databases_denied": True,
                "source_connection_read_only": True,
            },
            "repository_initialization_used": False,
            "public_definitions_and_translations_unchanged": True,
            "protected_public_tables_checked": list(PROTECTED_TABLES),
            "source_media_counts": source_counts,
            "target_media_counts_before": before_counts,
            "target_media_counts_after": media_counts(target),
            **result,
            "private_content_not_exported": True,
            "limitation": "Private rows were not queried or hashed; preservation is enforced "
            "by SQL authorization. Existing initial-install evidence is historical.",
        }
    finally:
        source.close()
        target.close()


def write_report(output, update):
    """Preserve the initial installation evidence and append the current update."""
    output = Path(output)
    report = json.loads(output.read_text()) if output.exists() else {}
    report["media_cache_update"] = update
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=".local/catalog/catalog.sqlite3")
    parser.add_argument("--db", default=".local/healthzip.sqlite3")
    parser.add_argument("--backup-dir", default=".local/backups")
    parser.add_argument("--output", default="artifacts/v14/catalog/default-install.json")
    args = parser.parse_args()
    try:
        update = install_media_cache(args.source, args.db, args.backup_dir)
        write_report(args.output, update)
    except (OSError, sqlite3.Error, ValueError, KeyError, RuntimeError) as error:
        # Do not emit database paths, SQL parameters or possible private values.
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        raise SystemExit(1) from None
    print(json.dumps(update, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
