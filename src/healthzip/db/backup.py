"""SQLite online backup and atomic non-overwriting restore for private data."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def backup_database(source, destination):
    """Copy committed SQLite state; accept a path or the existing Repository.

    Reserve the destination atomically. Never replace an existing backup, even
    when another process creates it between validation and opening the file.
    """
    path = Path(destination).expanduser().resolve()
    connection = getattr(source, "conn", None)
    own_connection = connection is None
    if own_connection:
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        connection = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
    elif connection.in_transaction:
        raise ValueError("Complete the current transaction before making a backup")
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("source_integrity_failed")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb"):
            pass
        try:
            with sqlite3.connect(str(path)) as target:
                connection.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("backup_integrity_failed")
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path
    finally:
        if own_connection:
            connection.close()


def restore_database(backup, destination):
    """Restore to a new path; never replace a potentially running database."""
    return backup_database(backup, destination)
