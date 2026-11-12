"""Derived historical candidates for exact, progressively bounded lookups."""

from datetime import datetime, timezone

from .semantics import timestamp


def _instant_microseconds(value):
    """Exact UTC key for accepted ISO timestamps; retain original text separately."""
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_required")
    difference = parsed.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return ((difference.days * 86400 + difference.seconds) * 1000000
            + difference.microseconds)


def _last_values_candidate_insert(event, source=""):
    """Project immutable snapshot scalars; the authoritative replay stays unchanged."""
    return f"""INSERT OR REPLACE INTO training_event_set_candidate(
        event_id,slot,user_id,session_id,set_uuid,condition_key,candidate_time,recorded_at,
        candidate_instant_us,recorded_instant_us)
        SELECT {event}.event_id,CAST(snapshot.key AS INTEGER),{event}.user_id,
            json_extract(snapshot.value,'$.session_id'),
            json_extract(snapshot.value,'$.set_uuid'),
            json_extract(snapshot.value,'$.condition_key'),
            COALESCE(NULLIF(json_extract(snapshot.value,'$.ended_at'),''),
                     NULLIF(json_extract(snapshot.value,'$.started_at'),'')),
            {event}.recorded_at,
            healthzip_instant_us(COALESCE(NULLIF(json_extract(snapshot.value,'$.ended_at'),''),
                                         NULLIF(json_extract(snapshot.value,'$.started_at'),''))),
            healthzip_instant_us({event}.recorded_at)
        FROM {source}json_each(CASE
            WHEN {event}.entity_type='set' THEN json_array(json({event}.after_json))
            WHEN {event}.entity_type IN ('session','session_exercise')
                THEN COALESCE(json_extract({event}.after_json,'$.sets'),'[]')
            ELSE '[]' END) snapshot
        WHERE {event}.status='applied'
            AND json_extract(snapshot.value,'$.completion_state')='completed'
            AND NULLIF(json_extract(snapshot.value,'$.deleted_at'),'') IS NULL
            AND json_extract(snapshot.value,'$.session_id') IS NOT NULL
            AND json_extract(snapshot.value,'$.set_uuid') IS NOT NULL
            AND json_extract(snapshot.value,'$.condition_key') IS NOT NULL
            AND COALESCE(NULLIF(json_extract(snapshot.value,'$.ended_at'),''),
                         NULLIF(json_extract(snapshot.value,'$.started_at'),'')) IS NOT NULL"""


def migrate_history_candidates(conn):
    # Repository and direct TrainingService/migrate_training callers all pass
    # here on every connection, including a warm database with an existing marker.
    conn.create_function("healthzip_instant_us", 1, _instant_microseconds, deterministic=True)
    marker = conn.execute(
        "SELECT value FROM schema_meta WHERE key='training_last_values_projection'"
    ).fetchone()
    if marker and marker[0] == "1":
        return
    conn.execute("""CREATE TABLE IF NOT EXISTS training_event_set_candidate(
        event_id TEXT NOT NULL,slot INTEGER NOT NULL,user_id TEXT NOT NULL,
        session_id INTEGER NOT NULL,set_uuid TEXT NOT NULL,condition_key TEXT NOT NULL,
        candidate_time TEXT NOT NULL,recorded_at TEXT NOT NULL,
        candidate_instant_us INTEGER NOT NULL,recorded_instant_us INTEGER NOT NULL,
        PRIMARY KEY(event_id,slot)) WITHOUT ROWID""")
    # This table contains only disposable query metadata. Original event bytes
    # are neither changed nor removed, and SQL backfill does not decode in Python.
    conn.execute("DELETE FROM training_event_set_candidate")
    conn.execute(_last_values_candidate_insert("event", "training_event event CROSS JOIN "))
    conn.execute("""CREATE INDEX IF NOT EXISTS training_last_values_candidates
        ON training_event_set_candidate(user_id,condition_key,candidate_instant_us DESC,
                                        set_uuid DESC,event_id DESC,slot DESC)""")
    for operation in ("INSERT", "UPDATE", "DELETE"):
        name = "training_event_candidates_" + operation.lower()
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
        statements = []
        if operation in {"UPDATE", "DELETE"}:
            statements.append("DELETE FROM training_event_set_candidate WHERE event_id=OLD.event_id")
        if operation in {"INSERT", "UPDATE"}:
            statements.append(_last_values_candidate_insert("NEW"))
        conn.execute(f"CREATE TRIGGER {name} AFTER {operation} ON training_event BEGIN "
                     + ";".join(statements) + "; END")
    conn.execute("INSERT OR REPLACE INTO schema_meta(key,value) "
                 "VALUES('training_last_values_projection','1')")


def latest_values_as_of(service, condition_key, excluded_session_id, cutoff_time):
    """Find the exact latest eligible group without a fixed history horizon.

    Every replayable completed snapshot has a scalar candidate. Candidate
    ranks are therefore upper bounds for unseen final states, even when a
    later revision moves, deletes, or changes the condition of a set.
    """
    cutoff = timestamp(cutoff_time)
    cutoff_us = _instant_microseconds(cutoff)
    batch_size = 64  # Query batch size, never a limit on historical support.
    cursor, best, seen_sessions = None, None, set()

    def rank(row):
        return _instant_microseconds(row.get("ended_at") or row.get("started_at")), row["set_uuid"]

    while True:
        sql = ("SELECT * FROM training_event_set_candidate WHERE user_id=? "
               "AND condition_key=? AND candidate_instant_us<=? "
               "AND recorded_instant_us<=? AND session_id!=?")
        args = [service.user_id, condition_key, cutoff_us, cutoff_us, excluded_session_id]
        if cursor is not None:
            sql += " AND (candidate_instant_us,set_uuid,event_id,slot)<(?,?,?,?)"
            args.extend(cursor)
        sql += " ORDER BY candidate_instant_us DESC,set_uuid DESC,event_id DESC,slot DESC LIMIT ?"
        candidates = list(service.conn.execute(sql, (*args, batch_size)))
        if not candidates:
            return best
        session_ids = {item["session_id"] for item in candidates
                       if item["session_id"] not in seen_sessions}
        if session_ids:
            events = service.events_as_of(cutoff_time=cutoff, _session_ids=session_ids)
            rows = service.history_as_of(cutoff_time=cutoff,
                condition_key=condition_key, _events=events)
            for row in rows:
                if (row["session_id"] != excluded_session_id and not row.get("conflicted")
                        and (best is None or rank(row) > rank(best))):
                    best = row
            seen_sessions.update(session_ids)
        last = candidates[-1]
        # A returned state can be older than its nominating revision. Keep
        # paging until no unseen candidate can rank above the current best.
        if (len(candidates) < batch_size
                or best is not None and rank(best) >= (last["candidate_instant_us"], last["set_uuid"])):
            return best
        cursor = tuple(last[key] for key in ("candidate_instant_us", "set_uuid", "event_id", "slot"))

