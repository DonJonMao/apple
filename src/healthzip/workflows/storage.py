"""Additive workflow references alongside the existing analysis/feedback stores."""
import json
from datetime import datetime, timezone

from healthzip.science.contracts import canonical_hash, instant
from healthzip.training.semantics import numeric


def migrate_workflows(conn):
    for sql in (
        """CREATE TABLE IF NOT EXISTS workflow_context_revision (
            context_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, payload_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS workflow_run (
            run_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, workflow_id TEXT NOT NULL,
            workflow_version TEXT NOT NULL, parent_run_id TEXT REFERENCES workflow_run(run_id),
            analysis_run_id TEXT NOT NULL REFERENCES analysis_run(run_id),
            request_json TEXT NOT NULL, input_hash TEXT NOT NULL, result_json TEXT NOT NULL,
            created_at TEXT NOT NULL, UNIQUE(user_id,workflow_id,input_hash))""",
        """CREATE TABLE IF NOT EXISTS workflow_use_check (
            run_id TEXT NOT NULL REFERENCES workflow_run(run_id), signature TEXT NOT NULL,
            result_json TEXT NOT NULL, checked_at TEXT NOT NULL, PRIMARY KEY(run_id,signature))""",
        """CREATE TABLE IF NOT EXISTS workflow_context_event (
            event_id TEXT PRIMARY KEY, context_id TEXT NOT NULL REFERENCES workflow_context_revision(context_id),
            kind TEXT NOT NULL, replacement_id TEXT, recorded_at TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS workflow_history ON workflow_run(user_id,workflow_id,created_at DESC)",
        """CREATE TABLE IF NOT EXISTS joint_period_report (
            report_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL, markdown TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS review_action (
            action_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, question_id TEXT NOT NULL,
            selected_at TEXT NOT NULL, review_due TEXT NOT NULL, action_text TEXT NOT NULL,
            baseline_json TEXT NOT NULL, source_filter_json TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS review_action_event (
            event_id TEXT PRIMARY KEY, action_id TEXT NOT NULL REFERENCES review_action(action_id),
            recorded_at TEXT NOT NULL, status TEXT NOT NULL, notes TEXT NOT NULL,
            result_json TEXT, UNIQUE(action_id,event_id))""",
        "CREATE INDEX IF NOT EXISTS review_action_due ON review_action(user_id,review_due)",
    ):
        conn.execute(sql)
    conn.execute("INSERT OR IGNORE INTO schema_meta(key,value) VALUES('workflow_context_version','0')")
    for table in ("workflow_context_revision", "workflow_context_event"):
        conn.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_version AFTER INSERT ON {table} BEGIN
            UPDATE schema_meta SET value=CAST(value AS INTEGER)+1 WHERE key='workflow_context_version'; END""")


CONTEXT_FIELDS = {"population", "available_loads", "allowed_strategies", "session_exercise_id",
                  "primary_sleep_stream", "reference_selection", "sleep_selection", "followup_window"}


def save_context(repo, values, *, replaces_context_id=None):
    """Persist a small explicit declaration, without conferring evidence authority."""
    if not isinstance(values, dict) or set(values) - CONTEXT_FIELDS:
        raise ValueError("unsupported_workflow_context_fields")
    payload = json.loads(json.dumps(values, allow_nan=False))
    population = payload.get("population")
    if population not in {None, "unknown", "adults", "healthy_adults", "trained_adults", "adult_athletes"}:
        raise ValueError("unknown_population_declaration")
    if "available_loads" in payload:
        loads = payload["available_loads"]
        if not isinstance(loads, list) or any(isinstance(v, bool) for v in loads):
            raise ValueError("equipment_load_list_required")
        loads = [numeric(v, "器械档位") for v in loads]
        if any(v is None or v < 0 for v in loads):
            raise ValueError("nonnegative_known_equipment_loads_required")
        payload["available_loads"] = sorted(set(loads))
        from healthzip.training.service import TrainingService
        instance = TrainingService(repo).get_session_exercise(payload.get("session_exercise_id"))
        payload["equipment_condition_key"] = instance.get("condition_key")
        payload["equipment_condition_hash"] = canonical_hash(instance["condition"])
    strategies = payload.get("allowed_strategies", [])
    if not isinstance(strategies, list) or set(strategies) - {"double_progression", "heavier_lower_reps", "repetition_progression"}:
        raise ValueError("unsupported_user_strategy")
    identity = canonical_hash({"user_id": "local", "payload": payload})
    if replaces_context_id and not repo.conn.execute(
            "SELECT 1 FROM workflow_context_revision WHERE context_id=? AND user_id='local'", (replaces_context_id,)).fetchone():
        raise ValueError("workflow_context_not_found_in_local_scope")
    if repo.conn.execute("SELECT 1 FROM workflow_context_event WHERE context_id=?", (identity,)).fetchone():
        # Reconfirmation is a new declaration; never resurrect a retired version.
        identity = canonical_hash({"payload": payload, "reconfirmed_at": datetime.now(timezone.utc).isoformat()})
    repo.conn.execute("INSERT OR IGNORE INTO workflow_context_revision VALUES(?,?,?,?)",
        (identity, "local", json.dumps(payload, ensure_ascii=False, sort_keys=True), datetime.now(timezone.utc).isoformat()))
    if replaces_context_id and replaces_context_id != identity:
        _context_event(repo, replaces_context_id, "superseded", identity)
    repo.conn.commit()
    return identity


def _context_event(repo, context_id, kind, replacement_id=None):
    if not repo.conn.execute("SELECT 1 FROM workflow_context_revision WHERE context_id=? AND user_id='local'", (context_id,)).fetchone():
        raise ValueError("workflow_context_not_found_in_local_scope")
    identity = canonical_hash([context_id, kind, replacement_id])
    repo.conn.execute("INSERT OR IGNORE INTO workflow_context_event VALUES(?,?,?,?,?)",
        (identity, context_id, kind, replacement_id, datetime.now(timezone.utc).isoformat()))


def withdraw_context(repo, context_id):
    _context_event(repo, context_id, "withdrawn")
    repo.conn.commit()


def context_as_of(repo, context_id, cutoff_time, mode):
    if context_id is None:
        return {"context_id": None, "values": {}, "recorded_at": None}
    row = repo.conn.execute("SELECT * FROM workflow_context_revision WHERE context_id=? AND user_id='local'", (context_id,)).fetchone()
    if row is None:
        raise ValueError("workflow_context_not_found_in_local_scope")
    if mode == "prospective" and instant(row["recorded_at"]) > instant(cutoff_time):
        raise ValueError("context_not_available_at_cutoff")
    visible_at = instant(cutoff_time) if mode == "prospective" else datetime.now(timezone.utc)
    if any(instant(event[0]) <= visible_at for event in repo.conn.execute(
            "SELECT recorded_at FROM workflow_context_event WHERE context_id=?", (context_id,))):
        raise ValueError("workflow_context_withdrawn_or_superseded")
    return {"context_id": context_id, "values": json.loads(row["payload_json"]), "recorded_at": row["recorded_at"],
            "provenance": "explicit_user_declaration_not_professional_verification"}


def current_context_problem(repo, context_id):
    """A selected declaration may expire; callers can still present raw facts.

    Keep the selected ID and explicit reason. Never substitute another version
    or turn an invalid declaration into an unknown declaration.
    """
    try:
        context_as_of(repo, context_id, datetime.now(timezone.utc).isoformat(), "prospective")
    except ValueError as exc:
        if str(exc) not in {"workflow_context_withdrawn_or_superseded", "workflow_context_not_found_in_local_scope"}:
            raise
        return str(exc)
    return None


def report_context(repo, context_id, cutoff_time, mode):
    """Explicit restricted declaration, preserving identity and retirement history.

    Retired values cannot authorize claims. Independent measurement-derived
    conditions still go through the normal evidence gate, with no blanket ban.
    """
    try:
        problem = current_context_problem(repo, context_id)
        if problem:
            raise ValueError(problem)
        return context_as_of(repo, context_id, cutoff_time, mode)
    except ValueError as exc:
        if str(exc) not in {"workflow_context_withdrawn_or_superseded",
                            "workflow_context_not_found_in_local_scope", "context_not_available_at_cutoff"}:
            raise
        row = repo.conn.execute("SELECT * FROM workflow_context_revision WHERE context_id=? AND user_id='local'",
                                (context_id,)).fetchone()
        events = [dict(r) for r in repo.conn.execute(
            "SELECT * FROM workflow_context_event WHERE context_id=? ORDER BY recorded_at,event_id", (context_id,))]
        return {"context_id": context_id, "values": {},
                "recorded_at": row["recorded_at"] if row else None,
                "status": "restricted_requires_reconfirmation", "reason": str(exc),
                "historical_values": json.loads(row["payload_json"]) if row else None,
                "lifecycle_events": events,
                "limitation": "所选声明已失效或在截止时点不可用。记录事实保留；依赖该声明的解释需重新确认。独立依据按各自条件核对。"}


def load_run(repo, run_id):
    row = repo.conn.execute("SELECT result_json FROM workflow_run WHERE run_id=? AND user_id='local'", (run_id,)).fetchone()
    if row is None:
        raise ValueError("workflow_run_not_found_in_local_scope")
    return json.loads(row[0])


def load_analysis(repo, run_id):
    row = repo.conn.execute("""SELECT a.result_json FROM analysis_run a JOIN workflow_run w
        ON w.analysis_run_id=a.run_id WHERE w.run_id=? AND w.user_id='local'""", (run_id,)).fetchone()
    if row is None:
        raise ValueError("workflow_snapshot_not_found")
    return json.loads(row[0])
