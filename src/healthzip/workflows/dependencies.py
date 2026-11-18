"""Relevant current-use dependencies; historical runs themselves never change."""
from datetime import datetime, timezone

from healthzip.analytics.v13 import snapshot
from healthzip.science.contracts import canonical_hash, instant
from healthzip.training.service import TrainingService

SOURCE_TYPES = {
    "W1": {"body_mass_kg", "resting_heart_rate_bpm", "hrv_sdnn_ms", "sleep_stage"},
    "W2": {"resting_heart_rate_bpm", "hrv_sdnn_ms", "sleep_stage"},
    "W3": {"vo2_max_ml_kg_min", "resting_heart_rate_bpm", "hrv_sdnn_ms"},
    "W4": {"body_mass_kg", "resting_heart_rate_bpm", "hrv_sdnn_ms", "sleep_stage"},
    "W5": {"body_mass_kg", "basal_energy_kcal", "active_energy_kcal"},
}


def input_version(repo, context_id):
    """Monotone input clocks; output/audit writes do not change these clocks."""
    versions = dict(repo.conn.execute("SELECT key,value FROM schema_meta WHERE key IN "
        "('training_data_version','source_data_version','advice_profile_version','catalog_data_version')"))
    if context_id:
        versions["context"] = canonical_hash([tuple(row) for row in repo.conn.execute(
            "SELECT * FROM workflow_context_revision WHERE context_id=?", (context_id,))])
        versions["context_events"] = canonical_hash([tuple(row) for row in repo.conn.execute(
            "SELECT * FROM workflow_context_event WHERE context_id=? ORDER BY recorded_at,event_id", (context_id,))])
    return versions


def inputs(repo, request, analysis, *, visible_at=None, selected_task=None):
    """Recheck a fixed event window with original or current visibility.

    New late records and revisions in the relevant window are dependencies too.
    The moving current clock and unrelated DB version are not dependencies.
    """
    cutoff = visible_at or request["cutoff_time"]
    start = analysis.get("dependency_window_start", analysis["window_start"])
    if request["workflow_id"] == "W4" and request.get("period"):
        from .calendar import completed_periods
        start = min(start, completed_periods(request["cutoff_time"], request["timezone"], request["period"])[0][0], key=instant)
    end = min(instant(analysis.get("dependency_window_end", analysis["window_end"])), instant(request["cutoff_time"])).isoformat()
    wid = request["workflow_id"]
    selected_type = {"STATE-RHR": "resting_heart_rate_bpm", "STATE-SDNN": "hrv_sdnn_ms", "BODY-MASS-DAILY": "body_mass_kg"}.get(
        request.get("result_metric_id") or ("STR-11" if request.get("task_id") else "BODY-MASS-DAILY")) if wid == "W4" else None
    source_types = {selected_type} if selected_type else SOURCE_TYPES[wid]
    records, inherited = snapshot(repo, cutoff, window_start=start, window_end=end,
        canonical_types=sorted(source_types))
    task = selected_task or analysis.get("task_selection") or {}
    exercise_id = task.get("exercise_id")
    selected_instance = None
    service = TrainingService(repo)
    if request.get("session_exercise_id"):
        try:
            session = service.session_as_of(request["session_id"], cutoff_time=cutoff)
            instance = next((r for r in session["exercises"] if r["id"] == request["session_exercise_id"]), None)
            if instance:
                exercise_id = instance["catalog_id"]
                selected_instance = {"condition": instance["condition"],
                    "targets": service.targets_from_instance(instance),
                    "deleted_at": instance.get("deleted_at"), "replaced_by": instance.get("replaced_by_instance_id")}
        except ValueError:
            selected_instance = {"unavailable": True}
    relevant, sessions = {}, set()
    for row in records:
        kind = row.get("record_kind")
        if kind == "strength_set":
            if wid not in {"W1", "W2", "W4"} or selected_type:
                continue
            if exercise_id and row.get("catalog_id", row.get("exercise_id")) != exercise_id:
                continue
            sessions.add(row.get("session_id"))
        elif kind == "subjective_log":
            if wid not in {"W1", "W2", "W4"} or selected_type:
                continue
        elif row.get("canonical_type") not in source_types:
            continue
        relevant[str(row["id"])] = canonical_hash(row)
    outcomes = inherited.get("recommendation_outcomes", []) if wid in {"W1", "W4"} and not selected_type else []
    if request.get("task_id"):
        outcomes = [r for r in outcomes if r.get("task_id") == request["task_id"]]
    return {"version": "workflow-dependencies-1.6.0", "record_hashes": relevant,
        "selected_instance": selected_instance,
        "session_hashes": {str(s["session_id"]): canonical_hash(s) for s in inherited.get("sessions", [])
                           if wid == "W2" or s["session_id"] in sessions},
        "outcome_hashes": {r["recommendation_id"]: canonical_hash(r) for r in outcomes}}


def check_current_use(repo, run_id, *, knowledge_root=".local/knowledge"):
    """Append a current-use receipt; never rewrite a frozen conclusion."""
    import json
    import sqlite3

    from . import evidence
    from .storage import context_as_of, load_analysis, load_run

    run = load_run(repo, run_id)
    analysis = load_analysis(repo, run_id)
    now = datetime.now(timezone.utc).isoformat()
    current = inputs(repo, run["request"], analysis, visible_at=now)
    reasons = []
    if current != run["dependencies"]:
        reasons.append("relevant_records_or_targets_changed")
    try:
        declaration = context_as_of(repo, run["context_id"], now, "prospective")
    except ValueError as exc:
        if str(exc) != "workflow_context_withdrawn_or_superseded":
            raise
        reasons.append("workflow_context_withdrawn_or_superseded")
        declaration = {"context_id": None, "values": {}, "recorded_at": None}
    check_failed = False
    try:
        knowledge = evidence.retrieve(run["workflow_id"], {**analysis["metrics"], **analysis["observations"]},
            TrainingService(repo).sessions_as_of(cutoff_time=now), declaration,
            root=knowledge_root, release_id=run["knowledge"].get("release_id"),
            background_metrics=evidence.background_inputs(run["supplements"].get("pretraining_contexts", [])),
            result_metric_id=run["request"].get("result_metric_id") or ("STR-11" if run["request"].get("task_id") else "BODY-MASS-DAILY"))
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        check_failed = True
        knowledge = {"status": "service_failure", "queries": [], "reason_codes": [type(exc).__name__]}
        reasons.append("current_use_check_service_failure")
    if not check_failed and evidence.identity(knowledge) != evidence.identity(run["knowledge"]):
        reasons.append("source_use_dependencies_changed")
    candidates = []
    if run["candidate_ids"]:
        from healthzip.advice import current_use_status
        for cid in run["candidate_ids"]:
            state = current_use_status(repo, {"candidate_id": cid})
            candidates.append({"candidate_id": cid, **state})
            if state["status"] != "active":
                reasons.append("candidate_requires_current_review")
    decision = {"status": "check_failed" if check_failed else "needs_review" if reasons else "current", "reason_codes": sorted(set(reasons)),
        "run_id": run_id, "candidate_checks": candidates, "dependency_hash": canonical_hash(current),
        "knowledge_hash": canonical_hash(evidence.identity(knowledge))}
    signature = canonical_hash(decision)
    repo.conn.execute("INSERT OR IGNORE INTO workflow_use_check VALUES(?,?,?,?)",
        (run_id, signature, json.dumps(decision, ensure_ascii=False, sort_keys=True), now))
    repo.conn.commit()
    return decision
