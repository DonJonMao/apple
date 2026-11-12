"""Additive, atomic v1.3 training migration on the existing private database.

No historic weight is reinterpreted as a known load convention.  Executing DDL
one statement at a time (rather than executescript) preserves the savepoint and
lets the Repository's outer migration transaction roll the entire upgrade back.
"""

from __future__ import annotations

import sqlite3
from typing import Callable, Optional

from .history_candidates import migrate_history_candidates

TRAINING_SCHEMA_VERSION = 3

# Immutable event payloads retain their original text. These expressions only
# narrow candidate sessions; Python still resolves exact availability and the
# latest visible revisions before testing final window membership.
EVENT_SESSION_SQL = "CASE WHEN entity_type='session' THEN json_extract(after_json,'$.id') ELSE json_extract(after_json,'$.session_id') END"
EVENT_END_SQL = "julianday(COALESCE(json_extract(after_json,'$.ended_at'),json_extract(after_json,'$.started_at')))"
EVENT_START_SQL = "julianday(COALESCE(json_extract(after_json,'$.started_at'),json_extract(after_json,'$.ended_at')))"
EVENT_QUERY_PROJECTION = "1"

ADDITIONS = {
    "strength_session": {
        "session_uuid": "TEXT",
        "user_id": "TEXT NOT NULL DEFAULT 'local'",
        "revision": "INTEGER NOT NULL DEFAULT 1",
        "session_status": "TEXT",
        "template_id": "TEXT",
        "template_version": "INTEGER",
        "plan_snapshot_json": "TEXT",
        "ended_at": "TEXT",
        "recorded_at": "TEXT",
        "available_at": "TEXT",
        "feedback_json": "TEXT",
        "session_rpe": "REAL",
        "session_rpe_scale": "TEXT",
        "duration_seconds": "REAL",
        "duration_protocol": "TEXT",
        "deleted_at": "TEXT",
    },
    "strength_set": {
        "set_uuid": "TEXT",
        "user_id": "TEXT NOT NULL DEFAULT 'local'",
        "revision": "INTEGER NOT NULL DEFAULT 1",
        "catalog_id": "TEXT",
        "definition_version": "INTEGER",
        "catalog_mapping_status": "TEXT NOT NULL DEFAULT 'unmapped'",
        "session_exercise_id": "TEXT",
        "condition_json": "TEXT",
        "condition_key": "TEXT",
        "comparability_status": "TEXT",
        "planned_json": "TEXT",
        "completion_state": "TEXT",
        "set_type": "TEXT",
        "load_value": "TEXT",
        "load_unit": "TEXT",
        "load_basis": "TEXT NOT NULL DEFAULT 'unknown'",
        "legacy_raw_value": "TEXT",
        "body_mass_kg": "REAL",
        "added_load_kg": "REAL",
        "assistance_value": "REAL",
        "duration_s": "REAL",
        "distance_m": "REAL",
        "rir_qualifier": "TEXT",
        "rpe_scale": "TEXT",
        "stop_reason": "TEXT",
        "repetition_semantics": "TEXT",
        "rest_actual_s": "REAL",
        "rest_derivation_json": "TEXT",
        "rest_recorded_s": "REAL",
        "rest_recorded_method": "TEXT",
        "ended_at": "TEXT",
        "recorded_at": "TEXT",
        "available_at": "TEXT",
        "source_method": "TEXT",
        "source_record_id": "TEXT",
        "pain_flag": "INTEGER",
        "quality_note": "TEXT",
        "quality_status": "TEXT",
        "relation_kind": "TEXT",
        "relation_group_id": "TEXT",
        "parent_set_uuid": "TEXT",
        "reference_set": "INTEGER",
        "reference_declared_at": "TEXT",
        "deleted_at": "TEXT",
    },
}

STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS exercise_catalog (
        exercise_id TEXT NOT NULL, definition_version INTEGER NOT NULL,
        owner_id TEXT NOT NULL, name TEXT NOT NULL, definition_json TEXT NOT NULL,
        custom INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(exercise_id,definition_version))""",
    """CREATE TABLE IF NOT EXISTS exercise_alias (
        user_id TEXT NOT NULL, exercise_id TEXT NOT NULL, alias TEXT NOT NULL,
        PRIMARY KEY(user_id,exercise_id,alias))""",
    """CREATE TABLE IF NOT EXISTS exercise_preference (
        user_id TEXT NOT NULL, exercise_id TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0,
        last_used_at TEXT, PRIMARY KEY(user_id,exercise_id))""",
    """CREATE TABLE IF NOT EXISTS equipment_instance (
        id TEXT PRIMARY KEY,user_id TEXT NOT NULL,label TEXT NOT NULL,
        equipment_type TEXT NOT NULL,configuration_json TEXT NOT NULL,revision INTEGER NOT NULL,
        created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS training_template (
        id TEXT PRIMARY KEY,user_id TEXT NOT NULL,name TEXT NOT NULL,
        current_version INTEGER NOT NULL,created_at TEXT NOT NULL,deleted_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS training_template_version (
        template_id TEXT NOT NULL,version INTEGER NOT NULL,name TEXT NOT NULL,
        items_json TEXT NOT NULL,created_at TEXT NOT NULL,
        PRIMARY KEY(template_id,version))""",
    """CREATE TABLE IF NOT EXISTS training_session_exercise (
        id TEXT PRIMARY KEY,session_id INTEGER NOT NULL,user_id TEXT NOT NULL,
        position INTEGER NOT NULL,catalog_id TEXT NOT NULL,definition_version INTEGER NOT NULL,
        condition_json TEXT NOT NULL,condition_key TEXT,comparability_status TEXT NOT NULL,
        planned_json TEXT NOT NULL,replaced_from_exercise_id TEXT,replacement_reason TEXT,
        revision INTEGER NOT NULL DEFAULT 1,deleted_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS training_event (
        event_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,device_id TEXT NOT NULL,
        entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,action TEXT NOT NULL,
        base_revision INTEGER,payload_hash TEXT NOT NULL,payload_json TEXT NOT NULL,
        occurred_at TEXT NOT NULL,recorded_at TEXT NOT NULL,status TEXT NOT NULL,
        before_json TEXT,after_json TEXT,result_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS training_conflict (
        id TEXT PRIMARY KEY,user_id TEXT NOT NULL,event_id TEXT NOT NULL,
        entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,base_revision INTEGER,
        current_revision INTEGER,current_json TEXT NOT NULL,proposed_json TEXT NOT NULL,
        created_at TEXT NOT NULL,resolved_by_event_id TEXT)""",
    """CREATE TABLE IF NOT EXISTS training_outbox (
        event_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,operation TEXT NOT NULL,
        arguments_json TEXT NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,created_at TEXT NOT NULL,result_json TEXT)""",
    """CREATE TABLE IF NOT EXISTS training_rest_timer (
        session_id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,anchor_at TEXT NOT NULL,
        target_seconds REAL,paused_at TEXT,accumulated_seconds REAL NOT NULL DEFAULT 0,
        state TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1)""",
    """CREATE TABLE IF NOT EXISTS training_recommendation (
        candidate_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,target_session TEXT,
        cutoff_time TEXT NOT NULL,data_version TEXT NOT NULL,theory_version TEXT NOT NULL,
        rule_version TEXT NOT NULL,input_snapshot_json TEXT NOT NULL,
        candidate_json TEXT NOT NULL,created_at TEXT NOT NULL,stale INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS training_recommendation_feedback (
        event_id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL,user_id TEXT NOT NULL,
        user_choice TEXT,execution_state TEXT,nonexecution_reason TEXT,
        actual_record_ids_json TEXT NOT NULL,outcome_json TEXT NOT NULL,
        occurred_at TEXT NOT NULL,recorded_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS training_invalidation (
        id INTEGER PRIMARY KEY,event_id TEXT NOT NULL,user_id TEXT NOT NULL,
        entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,affected_from TEXT,
        created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',analysis_version TEXT)""",
    """CREATE TABLE IF NOT EXISTS exercise_mapping (
        id TEXT PRIMARY KEY,user_id TEXT NOT NULL,from_exercise TEXT NOT NULL,
        to_exercise TEXT NOT NULL,differences_json TEXT NOT NULL,confirmed INTEGER NOT NULL,
        created_at TEXT NOT NULL,revoked_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS training_import_record (
        source_name TEXT NOT NULL,source_uuid TEXT NOT NULL,source_revision INTEGER,
        payload_hash TEXT NOT NULL,local_uuid TEXT NOT NULL,local_revision INTEGER NOT NULL,
        raw_json TEXT NOT NULL,imported_at TEXT NOT NULL,
        PRIMARY KEY(source_name,source_uuid))""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_training_session_uuid ON strength_session(session_uuid)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_training_set_uuid ON strength_set(set_uuid)",
    "CREATE INDEX IF NOT EXISTS idx_training_session_user ON strength_session(user_id,session_date)",
    """CREATE INDEX IF NOT EXISTS idx_training_active_session
        ON strength_session(user_id,session_date DESC,id DESC)
        WHERE deleted_at IS NULL AND session_status IN ('draft','in_progress','paused')""",
    "CREATE INDEX IF NOT EXISTS idx_training_set_condition ON strength_set(user_id,condition_key)",
    "CREATE INDEX IF NOT EXISTS idx_training_event_entity ON training_event(user_id,entity_type,entity_id)",
    "CREATE INDEX IF NOT EXISTS training_event_recent ON training_event(user_id,recorded_at DESC)",
    "CREATE INDEX IF NOT EXISTS training_invalidation_pending ON training_invalidation(user_id,id) WHERE status='pending'",
]


def migrate_training(
    conn: sqlite3.Connection, *, checkpoint: Optional[Callable[[str], None]] = None
) -> None:
    """Upgrade existing strength tables without commits or data reinterpretation.

    ``checkpoint`` enables a real interruption test; raising from it rolls all
    changes back, including ALTER TABLE, without disturbing an outer transaction.
    """
    conn.execute("SAVEPOINT healthzip_training_v3")
    try:
        for table, additions in ADDITIONS.items():
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if not existing:
                raise ValueError(f"Missing legacy table: {table}; initialize Repository first")
            for name, declaration in additions.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
            if checkpoint:
                checkpoint(table)
        for statement in STATEMENTS:
            conn.execute(statement)
        projection = conn.execute(
            "SELECT value FROM schema_meta WHERE key='training_event_query_projection'"
        ).fetchone()
        if not projection or projection[0] != EVENT_QUERY_PROJECTION:
            conn.execute(f"CREATE INDEX IF NOT EXISTS training_event_support ON training_event(user_id,{EVENT_END_SQL},{EVENT_START_SQL})")
            conn.execute(f"CREATE INDEX IF NOT EXISTS training_event_session_versions ON training_event(user_id,({EVENT_SESSION_SQL}),recorded_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS training_conflict_event ON training_conflict(user_id,event_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS training_recommendation_created ON training_recommendation(user_id,julianday(created_at))")
            conn.execute("CREATE INDEX IF NOT EXISTS training_recommendation_followup ON training_recommendation(user_id,julianday(json_extract(candidate_json,'$.followup_window.end')),julianday(json_extract(candidate_json,'$.followup_window.start')))")
            conn.execute("CREATE INDEX IF NOT EXISTS training_feedback_support ON training_recommendation_feedback(user_id,julianday(occurred_at),candidate_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS training_feedback_candidate ON training_recommendation_feedback(user_id,candidate_id,recorded_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS training_unprojected_legacy ON strength_set(user_id) WHERE legacy_raw_value IS NULL AND set_uuid IS NULL")
            conn.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('training_event_query_projection',?)", (EVENT_QUERY_PROJECTION,))
        migrate_history_candidates(conn)
        catalog_columns = {row[1] for row in conn.execute("PRAGMA table_info(exercise_catalog)")}
        if "revision" not in catalog_columns:
            conn.execute(
                "ALTER TABLE exercise_catalog ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
            )
        exercise_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(training_session_exercise)")
        }
        if "replaced_by_instance_id" not in exercise_columns:
            conn.execute(
                "ALTER TABLE training_session_exercise ADD COLUMN replaced_by_instance_id TEXT"
            )
        # Preserve historic raw values and identifiers; only NULLs are filled.
        conn.execute(
            "UPDATE strength_set SET legacy_raw_value=CAST(weight_kg AS TEXT) "
            "WHERE legacy_raw_value IS NULL AND set_uuid IS NULL"
        )
        conn.execute(
            "INSERT INTO schema_meta(key,value) VALUES('training_schema_version','3') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )
        if checkpoint:
            checkpoint("complete")
        conn.execute("RELEASE SAVEPOINT healthzip_training_v3")
    except BaseException:
        conn.execute("ROLLBACK TO SAVEPOINT healthzip_training_v3")
        conn.execute("RELEASE SAVEPOINT healthzip_training_v3")
        raise
