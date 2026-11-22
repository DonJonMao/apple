"""Append-only visibility for older, alternate observation representations.

Calendar dates have a noon-UTC index anchor only. Consumers must reconstruct
their local date and never present this anchor as a measurement timestamp.
"""

TABLES = {
    "workout_statistic": ("statistic_start", "statistic_end"),
    "workout_event": ("event_date", "event_date"),
    "activity_summary": ("summary_date", "summary_date"),
    "nutrition_day": ("day", "day"),
    "cycle_event": ("event_date", "event_date"),
}
DATE_TABLES = {"activity_summary", "nutrition_day", "cycle_event"}


def migrate_observation_ledger(conn):
    if conn.execute(
        "SELECT 1 FROM schema_meta WHERE key='alternate_observation_ledger' AND value='1'"
    ).fetchone():
        return
    for table, (first, last) in TABLES.items():
        columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if "record_status" not in columns:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN record_status TEXT NOT NULL DEFAULT 'active'"
            )
        if table == "activity_summary" and "metadata_json" not in columns:
            conn.execute(
                "ALTER TABLE activity_summary ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
            )
        columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]

        def payload(prefix, *, deleted=False):
            pairs = [f"'{key}',{prefix}.\"{key}\"" for key in columns]
            if table in DATE_TABLES:
                anchor = f"{prefix}.\"{last}\" || 'T12:00:00+00:00'"
                pairs += [f"'observed_at',{anchor}", "'event_time_precision','calendar_day'"]
            else:
                pairs += [f"'start_utc',{prefix}.\"{first}\"", f"'end_utc',{prefix}.\"{last}\""]
            value = "json_object(" + ",".join(pairs) + ")"
            return f"json_set({value},'$.record_status','deleted')" if deleted else value

        conn.execute(
            f"""INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance)
            SELECT ?,src.id,strftime('%Y-%m-%dT%H:%M:%fZ','now'),{payload("src")},
                   'observed_at_migration_historical_visibility_unknown'
            FROM {table} AS src WHERE NOT EXISTS (
                SELECT 1 FROM source_revision r WHERE r.table_name=? AND r.record_id=src.id)""",
            (table, table),
        )
        for operation in ("INSERT", "UPDATE", "DELETE"):
            prefix = "OLD" if operation == "DELETE" else "NEW"
            conn.execute(f"""CREATE TRIGGER ledger_{table}_{operation.lower()} AFTER {operation} ON {table}
                BEGIN
                  INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance)
                  VALUES('{table}',{prefix}.id,strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                    {payload(prefix, deleted=operation == "DELETE")},'locally_observed');
                  UPDATE analysis_run SET invalidated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE invalidated_at IS NULL;
                END""")
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('alternate_observation_ledger','1')"
    )
