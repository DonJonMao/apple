"""Private source revision ledger and immutable analysis snapshots."""

from __future__ import annotations

import sqlite3


def migrate_temporal(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS source_revision (
        revision_id INTEGER PRIMARY KEY, table_name TEXT NOT NULL, record_id INTEGER NOT NULL,
        available_at TEXT NOT NULL, payload_json TEXT NOT NULL, temporal_provenance TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS source_revision_lookup ON source_revision(table_name,record_id,available_at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS analysis_run (
        run_id TEXT PRIMARY KEY, cutoff_time TEXT NOT NULL, computed_at TEXT NOT NULL,
        algorithm_version TEXT NOT NULL, data_hash TEXT NOT NULL, result_json TEXT NOT NULL,
        invalidated_at TEXT)""")
    for table in ("health_sample", "workout", "subjective_log", "body_measurement"):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name in ("available_at", "invalidated_at", "temporal_provenance"):
            if name not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} TEXT")
        if table == "subjective_log":
            existing = {row[1] for row in conn.execute("PRAGMA table_info(subjective_log)")}
            for name in ("observed_at", "scale_version", "anchors", "muscle", "side", "pain", "location", "movement_impact"):
                if name not in existing:
                    conn.execute(f"ALTER TABLE subjective_log ADD COLUMN {name} TEXT")
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
        # A migrated record with no historical visibility remains unknown. Do
        # not fabricate a prior available_at from its physiological timestamp.
        conn.execute(f"UPDATE {table} SET temporal_provenance='legacy_visibility_unknown' WHERE temporal_provenance IS NULL")
        # Existing exports are visible now, although their availability before
        # this migration is unknown. A migration-time baseline keeps them in
        # current descriptive views without backdating them into past decisions.
        initial_pairs = ",".join(f"'{key}',source_row.\"{key}\"" for key in columns)
        conn.execute(f"""INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance)
            SELECT ?,source_row.id,strftime('%Y-%m-%dT%H:%M:%fZ','now'),json_object({initial_pairs}),
                   'observed_at_migration_historical_visibility_unknown'
            FROM {table} AS source_row
            WHERE NOT EXISTS (SELECT 1 FROM source_revision r WHERE r.table_name=? AND r.record_id=source_row.id)
            """, (table, table))
        pairs = ",".join(f"'{key}',NEW.\"{key}\"" for key in columns)
        for operation in ("INSERT", "UPDATE"):
            name = f"ledger_{table}_{operation.lower()}"
            conn.execute(f"DROP TRIGGER IF EXISTS {name}")
            # Table changes are internal constants, never imported identifiers.
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS {name} AFTER {operation} ON {table}
                BEGIN
                  INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance)
                  VALUES('{table}',NEW.id,strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                         json_object({pairs}),'locally_observed');
                  UPDATE analysis_run SET invalidated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                    WHERE invalidated_at IS NULL;
                END""")


def samples_as_of(repo, cutoff_time: str, table: str = "health_sample") -> list[dict]:
    """Return versions actually seen by this installation at the given cutoff."""
    import json

    if table not in {"health_sample", "workout", "subjective_log", "body_measurement"}:
        raise ValueError("unsupported_source_table")
    rows = repo.rows(
        "SELECT * FROM source_revision WHERE revision_id IN ("
        "SELECT MAX(revision_id) FROM source_revision WHERE table_name=? "
        "AND julianday(available_at)<=julianday(?) GROUP BY record_id)", (table, cutoff_time))
    output = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        if payload.get("record_status", "active") != "active":
            continue
        payload["available_at"] = row["available_at"]
        payload["temporal_provenance"] = row["temporal_provenance"]
        output.append(payload)
    return output
