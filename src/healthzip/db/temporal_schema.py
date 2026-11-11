"""Private source revision ledger and immutable analysis snapshots."""

from __future__ import annotations

import sqlite3

EVENT_END_SQL = "julianday(COALESCE(json_extract(payload_json,'$.end_utc'),json_extract(payload_json,'$.measured_at'),json_extract(payload_json,'$.observed_at')))"
EVENT_START_SQL = "julianday(COALESCE(json_extract(payload_json,'$.start_utc'),json_extract(payload_json,'$.end_utc'),json_extract(payload_json,'$.measured_at'),json_extract(payload_json,'$.observed_at')))"
QUERY_PROJECTION_VERSION = "4.3"


def migrate_temporal(conn: sqlite3.Connection) -> None:
    marker = conn.execute("SELECT value FROM schema_meta WHERE key='temporal_query_projection'").fetchone()
    if marker and marker[0] == QUERY_PROJECTION_VERSION:
        return
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

    # Index expressions project immutable payloads inside SQLite. They remain
    # correct for old revisions and explicit availability corrections alike.
    conn.execute("DROP INDEX IF EXISTS source_revision_event_window")
    conn.execute(f"CREATE INDEX source_revision_event_window ON source_revision(table_name,{EVENT_END_SQL},{EVENT_START_SQL})")
    conn.execute("CREATE INDEX IF NOT EXISTS source_revision_record_versions ON source_revision(table_name,record_id,revision_id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS analysis_run_invalidation ON analysis_run(invalidated_at)")
    for table, field in (("health_sample", "end_utc"), ("workout", "end_utc"),
                         ("body_measurement", "measured_at"), ("subjective_log", "observed_at")):
        conn.execute(f"CREATE INDEX IF NOT EXISTS current_{table}_support ON {table}(julianday({field}))")
    conn.execute("INSERT OR IGNORE INTO schema_meta(key,value) VALUES('source_data_version','0')")
    for operation in ("INSERT", "UPDATE", "DELETE"):
        conn.execute(f"""CREATE TRIGGER IF NOT EXISTS source_version_{operation.lower()}
            AFTER {operation} ON source_revision BEGIN
            UPDATE schema_meta SET value=CAST(value AS INTEGER)+1 WHERE key='source_data_version';
            END""")
    conn.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('temporal_query_projection',?)", (QUERY_PROJECTION_VERSION,))


def samples_as_of(repo, cutoff_time: str, table: str = "health_sample", *,
                  window_start=None, window_end=None, canonical_types=None) -> list[dict]:
    """Read latest visible revisions of window candidates, then filter support.

    Candidate IDs may be found by any revision's support, but all their visible
    revisions are resolved before event filtering. A newer out-of-window version
    or tombstone therefore cannot resurrect an older in-window value. SQLite's
    coarse Julian index only narrows candidates; exact microseconds are checked
    after revision selection, including availability at the cutoff.
    """
    import json
    from datetime import datetime

    def when(value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("query_time_requires_timezone")
        return parsed

    if table not in {"health_sample", "workout", "subjective_log", "body_measurement"}:
        raise ValueError("unsupported_source_table")
    cutoff = when(cutoff_time)
    if bool(window_start) != bool(window_end):
        raise ValueError("query_window_requires_both_bounds")
    start, end = (when(window_start), when(window_end)) if window_start else (None, None)
    if start is not None and start >= end:
        raise ValueError("query_window_must_be_positive")
    clauses = ["table_name=?"]
    args = [table]
    if start is not None:
        # 1 ms padding compensates only SQLite date-index precision, never a
        # physiological tolerance or a relaxation of the actual half-open window.
        clauses.extend((f"{EVENT_END_SQL}>=julianday(?)-0.001/86400",
                        f"{EVENT_START_SQL}<=julianday(?)+0.001/86400"))
        args.extend((window_start, window_end))
    if canonical_types:
        clauses.append("json_extract(payload_json,'$.canonical_type') IN (" + ",".join("?" for _ in canonical_types) + ")")
        args.extend(canonical_types)
    candidate = "SELECT DISTINCT record_id FROM source_revision WHERE " + " AND ".join(clauses)
    rows = repo.rows("SELECT revision_id,record_id,available_at,payload_json,temporal_provenance FROM source_revision "
                     "WHERE table_name=? AND record_id IN (" + candidate + ") "
                     "AND julianday(available_at)<=julianday(?)+0.001/86400 ORDER BY record_id,revision_id DESC",
                     (table, *args, cutoff_time))
    output = []
    seen = set()
    for row in rows:
        if when(row["available_at"]) > cutoff or row["record_id"] in seen:
            continue
        seen.add(row["record_id"])
        payload = json.loads(row["payload_json"])
        if payload.get("record_status", "active") != "active":
            continue
        if canonical_types and payload.get("canonical_type") not in canonical_types:
            continue
        if start is not None:
            event_end = payload.get("end_utc") or payload.get("measured_at") or payload.get("observed_at")
            event_start = payload.get("start_utc") or event_end
            if not event_end:
                continue
            first, last = when(event_start), when(event_end)
            if not (start <= last < end or (last > start and first < end)):
                continue
        payload["available_at"] = row["available_at"]
        payload["temporal_provenance"] = row["temporal_provenance"]
        output.append(payload)
    return output


def current_source_rows(repo, table, *, window_start=None, window_end=None, canonical_types=None):
    """Explicit retrospective view of current facts, with the same window plan."""
    fields = {"health_sample": ("start_utc", "end_utc"), "workout": ("start_utc", "end_utc"),
              "body_measurement": ("measured_at", "measured_at"), "subjective_log": ("observed_at", "observed_at")}
    if table not in fields:
        raise ValueError("unsupported_source_table")
    start_field, end_field = fields[table]
    clauses, args = [], []
    if window_start and window_end:
        clauses += [f"julianday({end_field})>=julianday(?)-0.001/86400",
                    f"julianday(COALESCE({start_field},{end_field}))<=julianday(?)+0.001/86400"]
        args.extend((window_start, window_end))
    if canonical_types:
        clauses.append("canonical_type IN (" + ",".join("?" for _ in canonical_types) + ")")
        args.extend(canonical_types)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return [dict(r) for r in repo.rows(f"SELECT * FROM {table}" + where, tuple(args))]
