"""Current-session business versions over the existing advice/workflow core.

Automatic association is objective identity/time linkage, never a user feedback
event. Immutable suggestions, plans and actual revisions remain separate.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo

from healthzip.advice import build_advice_context
from healthzip.analytics.v13 import snapshot
from healthzip.science.contracts import canonical_hash, instant
from healthzip.science.engine import evaluate_subset
from healthzip.training.semantics import numeric
from healthzip.training.service import TrainingError, TrainingService
from healthzip.workflows import WorkflowRequest, run_workflow
from healthzip.workflows.dependencies import input_version

VERSION = "current-training-2.0.0"
STRATEGIES = ("double_progression", "heavier_lower_reps", "repetition_progression")
_KNOWLEDGE_SIGNATURES = OrderedDict()
_KNOWLEDGE_SIGNATURE_LOCK = RLock()


def _link_report(repo, advice_id, source_report_id):
    if source_report_id:
        repo.conn.execute("INSERT OR IGNORE INTO current_advice_report_link VALUES(?,?,?)",
            (advice_id, source_report_id, datetime.now(timezone.utc).isoformat()))
        repo.conn.commit()


def knowledge_signature(root):
    """Reuse the exact legacy content digest while tracked inputs are unchanged.

    Reports/candidates retain the same signature bytes as before. Audit writes
    cannot expire this cache; review/revocation changes do. Untracked legacy or
    incomplete trigger installations always use the full read-only calculation.
    """
    from healthzip.knowledge.revisions import knowledge_authority_clock

    before = knowledge_authority_clock(root)
    tracked = all(len(entry) >= 3 and isinstance(entry[2], tuple) for entry in before[2:])
    if not tracked:
        return _knowledge_signature_uncached(root)
    key = json.dumps(before, sort_keys=True)
    with _KNOWLEDGE_SIGNATURE_LOCK:
        if key in _KNOWLEDGE_SIGNATURES:
            value = _KNOWLEDGE_SIGNATURES[key]
            _KNOWLEDGE_SIGNATURES.move_to_end(key)
            if knowledge_authority_clock(root) == before:
                return value
        value = _knowledge_signature_uncached(root)
        if knowledge_authority_clock(root) == before:
            _KNOWLEDGE_SIGNATURES[key] = value
            while len(_KNOWLEDGE_SIGNATURES) > 8:
                _KNOWLEDGE_SIGNATURES.popitem(last=False)
            return value
        raise RuntimeError("knowledge_inputs_changed_retry_required")


def _knowledge_signature_uncached(root):
    """Fingerprint authority inputs, excluding retrieval/audit output writes.

    No corpus expansion, retrieval or review is performed. Only digests leave
    the public stores; full source text is never saved in private advice.
    """
    tables = {
        "sources.sqlite3": ("source", "version", "span", "source_review", "source_version_clearance",
                            "scientific_notice", "parse_supersession", "index_release", "retrieval_unit_domain_review"),
        "theories.sqlite3": ("theory", "theory_lifecycle", "theory_release", "source_claim",
                             "application_rule", "core_lifecycle", "core_release",
                             "knowledge_domain_assignment", "knowledge_evidence_edge"),
    }
    digest = hashlib.sha256()
    for filename, names in tables.items():
        path = Path(root) / filename
        digest.update(filename.encode())
        if not path.is_file():
            digest.update(b"missing")
            continue
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name in names:
                if name in present:
                    digest.update(name.encode())
                    for row in conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid'):
                        digest.update(json.dumps(row, ensure_ascii=False, default=str).encode())
        finally:
            conn.close()
    return digest.hexdigest()


def save_equipment_loads(repo, instance_id, loads, *, load_unit=None):
    """Persist a user's actual settings for this physical condition, not a rule."""
    svc = TrainingService(repo)
    instance = svc.get_session_exercise(instance_id)
    if not isinstance(loads, list) or any(isinstance(v, bool) for v in loads):
        raise ValueError("器械档位须为非负有限数字列表")
    values = [numeric(v, "器械档位") for v in loads]
    if any(v is None or v < 0 for v in values):
        raise ValueError("器械档位须为非负有限数字列表")
    if load_unit not in {None, "kg", "lb", "level", "stack_level"}:
        raise ValueError("器械档位单位须为 kg/lb/level/stack_level 或未知")
    condition = canonical_hash(instance["condition"])
    payload = {"available_loads": sorted(set(values)), "load_unit": load_unit,
               "load_basis": instance["condition"].get("load_basis"),
               "condition": instance["condition"], "provenance": "user_confirmed_equipment_settings"}
    if equipment_loads(repo, instance) == payload:
        return payload
    created = datetime.now(timezone.utc).isoformat()
    identity = canonical_hash([condition, payload, created])
    repo.conn.execute("INSERT INTO training_advice_equipment VALUES(?,?,?,?,?)",
        (identity, svc.user_id, condition, json.dumps(payload, ensure_ascii=False), created))
    repo.conn.commit()
    return payload


def equipment_loads(repo, instance):
    row = repo.conn.execute("SELECT payload_json FROM training_advice_equipment WHERE user_id='local' AND condition_hash=? "
                           "ORDER BY created_at DESC LIMIT 1", (canonical_hash(instance["condition"]),)).fetchone()
    if row:
        return json.loads(row[0])
    identity = instance["condition"].get("equipment_instance_id")
    equipment = TrainingService(repo).get_equipment(identity) if identity else {}
    config = equipment.get("configuration", {})
    known = config.get("step_basis") == instance["condition"].get("load_basis") and bool(config.get("step_source"))
    return {"available_loads": config.get("available_loads", []) if known else [],
            "load_unit": config.get("step_unit") if known else None,
            "provenance": config.get("step_source") if known else None, "equipment_id": identity,
            "load_basis": instance["condition"].get("load_basis")}


def _session_state(session):
    return {k: session.get(k) for k in ("id", "session_uuid", "revision", "session_status",
        "deleted_at", "started_at", "ended_at", "available_at")}


def _instance_state(instance):
    # Only authoritative training fields, shared by live and event-replayed rows.
    return {**{k: instance.get(k) for k in ("id", "session_id", "revision", "condition", "planned",
        "catalog_id", "definition_version", "deleted_at", "replaced_by_instance_id")},
        "sets": [{k: s.get(k) for k in ("set_uuid", "revision", "completion_state", "deleted_at",
            "started_at", "ended_at", "planned", "reference_set", "reference_declared_at",
            "reference_selection")} for s in instance["sets"]]}


def _recent_related_training(svc, instance, cutoff, window_days):
    """Recent region facts are background, never a cross-exercise load basis."""
    regions = set(instance["exercise"].get("display_regions") or [])
    catalog = {r["exercise_id"]: r for r in svc.search_exercises()}
    start = (instant(cutoff) - timedelta(days=window_days)).isoformat()
    rows = svc.history_as_of(cutoff_time=cutoff, window_start=start, window_end=cutoff,
                            include_incomplete=True)
    result = []
    for row in rows:
        exercise = catalog.get(row.get("catalog_id", row.get("exercise_id")), {})
        if row.get("session_id") == instance["session_id"]:
            continue
        if not regions.intersection(exercise.get("display_regions") or []):
            continue
        if row.get("completion_state") not in {"completed", "aborted", "failed", "in_progress"}:
            continue
        result.append({"session_id": row["session_id"], "occurred_at": row.get("ended_at") or row.get("started_at"),
            "exercise_name": exercise.get("name") or row.get("exercise_name"), "record": row,
            "purpose": "recent_same_region_context_no_load_conversion"})
    return result


def _validate_freeze(repo, svc, advice, revision, context_id, settings, knowledge_root, knowledge):
    instance = svc.get_session_exercise(advice["instance"]["id"])
    session = svc.get_session(instance["session_id"])
    if (input_version(repo, context_id) != revision
            or _instance_state(instance) != _instance_state(advice["instance"])
            or _session_state(session) != _session_state(advice["session"])
            or session.get("session_status") not in {"draft", "in_progress", "paused"}
            or session.get("deleted_at") or instance.get("deleted_at") or instance.get("replaced_by_instance_id")
            or equipment_loads(repo, instance) != settings
            or knowledge_signature(knowledge_root) != knowledge):
        raise ValueError("concurrent_current_advice_inputs_changed_retry_required")


def current_advice(repo, instance_id, *, context_id=None, window_days=30, baseline_days=28,
                   timezone_name="Asia/Shanghai", knowledge_root=".local/knowledge", source_report_id=None):
    """Generate once per relevant input version; cached rerenders do no retrieval."""
    svc = TrainingService(repo)
    if repo.conn.in_transaction:
        raise ValueError("save_pending_edits_before_current_advice")
    revision = input_version(repo, context_id)
    cutoff = datetime.now(timezone.utc).isoformat()
    # This lookup supplies only the immutable parent identity. All business
    # fields below come from the single cutoff-visible AdviceContext instance.
    identity = svc.get_session_exercise(instance_id)
    visible_session = svc.session_as_of(identity["session_id"], cutoff_time=cutoff, include_deleted=True)
    if visible_session.get("deleted_at") or visible_session.get("session_status") not in {"draft", "in_progress", "paused"}:
        raise ValueError("current_training_session_ended:" + str(visible_session.get("session_status")))
    advice = build_advice_context(repo, identity["session_id"], instance_id, None, [], None,
        cutoff_time=cutoff, timezone_name=timezone_name, generation_origin="automatic_training")
    instance = advice["instance"]
    if instance.get("deleted_at") or instance.get("replaced_by_instance_id"):
        raise ValueError("selected_training_instance_unavailable")
    source_report_mapping = None
    if source_report_id:
        from healthzip.workflows import load_run
        source = load_run(repo, source_report_id)
        selected_task = source.get("task_selection") or {}
        # A report is navigation, not a research input or an action authority.
        # Preserve its strict task ID while checking the actual condition; set
        # position cannot create a reference prerequisite for ordinary records.
        if (selected_task.get("exercise_id") != instance["catalog_id"]
                or not selected_task.get("condition_key")
                or selected_task["condition_key"] != instance["condition"].get("condition_key")):
            raise ValueError("source_report_task_mismatch")
        source_report_mapping = {"version": "daily-report-navigation-1.0.0",
            "purpose": "same_condition_navigation_only_no_research_or_numeric_permission_transfer",
            "source_task_id": selected_task.get("task_id"), "source_condition_key": selected_task["condition_key"],
            "current_condition_key": instance["condition"]["condition_key"]}
    from healthzip.science.semantics import analysis_task
    from healthzip.training.daily_history import select_daily_history
    history = select_daily_history(svc, instance, cutoff_time=cutoff)
    # Daily matching never borrows a historical reference's strict task identity.
    task = analysis_task({**instance["condition"], "set_number": None})
    advice["records"] = history["records"]
    advice["context"].update(task_id=task["task_id"], protocol=task["protocol"],
        outcome_series_id=None, baseline_record_ids=[r["set_uuid"] for r in history["records"]],
        history_purpose="daily_latest_session", history_match_version=history["match_version"])
    current_observations = {r["set_uuid"]: r for r in advice["context"]["current_session_observations"]}
    for observed in svc.history_as_of(cutoff_time=cutoff, include_incomplete=True):
        if (observed.get("session_id") == instance["session_id"]
                and observed.get("catalog_id", observed.get("exercise_id")) == instance["catalog_id"]
                and (observed.get("completion_state") in {"completed", "aborted", "failed", "in_progress"}
                     or observed.get("started_at") or observed.get("ended_at"))):
            current_observations[observed["set_uuid"]] = observed
    advice["context"]["current_session_observations"] = list(current_observations.values())
    advice["context"]["current_session_record_ids"] = list(current_observations)
    settings = equipment_loads(repo, instance)
    records, _ = snapshot(repo, cutoff, window_start=(instant(cutoff)-timedelta(days=baseline_days)).isoformat(),
        window_end=cutoff, canonical_types=["sleep_stage", "resting_heart_rate_bpm", "hrv_sdnn_ms", "body_mass_kg"])
    background = [r for r in records if r.get("record_kind") != "strength_set"]
    from healthzip.db.temporal_schema import samples_as_of
    from healthzip.training.daily_decisions import latest_symptom_reports
    # Categorical symptom state has no product-defined expiry. Its latest
    # dated reports are independent of metric/display lookback windows.
    symptom_reports = latest_symptom_reports([{**r, "id": "subjective_log:" + str(r["id"]),
        "record_kind": "subjective_log"} for r in samples_as_of(repo, cutoff, "subjective_log")
        if r.get("observed_at") and instant(r["observed_at"]) <= instant(cutoff)])
    recent_training = _recent_related_training(svc, instance, cutoff, window_days)
    knowledge = knowledge_signature(knowledge_root)
    # Relative age and cutoff are presentation facts, not a new observation.
    history_dependency = {**history, "latest_session": {k: v for k, v in (history.get("latest_session") or {}).items()
        if k != "days_since"}, "selection": {k: v for k, v in history.get("selection", {}).items() if k != "cutoff_time"}}
    history_dependency.pop("selection_hash", None)
    current_context = {k: v for k, v in advice["context"].items()
                       if k in {"profile_revision", "profile_provenance", "task_id", "protocol", "current_session_observations"}}
    signature = canonical_hash({"version": VERSION, "instance": instance, "session": _session_state(advice["session"]), "history": history_dependency,
        "body": background, "symptom_reports": symptom_reports,
        "recent_training": recent_training, "context": current_context, "settings": settings, "context_id": context_id,
        "context_revision": {k: v for k, v in revision.items() if k.startswith("context")},
        "window_days": window_days, "baseline_days": baseline_days, "timezone": timezone_name,
        # Rolling body windows are recomputed at their actual cutoff whenever
        # observations exist; record IDs alone cannot validate moving windows.
        "body_window_cutoff": cutoff if background else None,
        "date": instant(cutoff).astimezone(ZoneInfo(timezone_name)).date().isoformat(), "knowledge": knowledge})
    row = repo.conn.execute("SELECT payload_json FROM current_training_advice WHERE user_id='local' "
                           "AND session_exercise_id=? AND input_hash=?", (instance_id, signature)).fetchone()
    if row:
        repo.conn.execute("BEGIN IMMEDIATE")
        try:
            _validate_freeze(repo, svc, advice, revision, context_id, settings, knowledge_root, knowledge)
            repo.conn.commit()
        except BaseException:
            repo.conn.rollback()
            raise
        saved = json.loads(row[0])
        _link_report(repo, saved["advice_id"], source_report_id)
        return saved
    review = run_workflow(repo, WorkflowRequest("W1", cutoff_time=cutoff, timezone=timezone_name,
        window_days=window_days, baseline_days=baseline_days, session_id=instance["session_id"],
        session_exercise_id=instance_id, context_id=context_id, context_policy="preserve_facts"), knowledge_root=knowledge_root)
    if review["knowledge"]["status"] == "service_failure":
        raise RuntimeError("资料服务暂未完成，建议等待重新计算")
    advice["context"].update(body_context=review["supplements"].get("current_body_context"),
                             recent_related_training=recent_training,
                             body_observations=symptom_reports, equipment_load_unit=settings.get("load_unit"),
                             body_action_scopes=instance["exercise"].get("display_regions") or [])
    # A historical report is a navigation reference only. Its cutoff, selected
    # declaration and comparison windows never replace this current request.
    from healthzip.knowledge import KnowledgeWorkbench
    authorities = {}
    if all((Path(knowledge_root)/n).is_file() for n in ("sources.sqlite3", "theories.sqlite3")):
        workbench = KnowledgeWorkbench(knowledge_root)
        try:
            for strategy in STRATEGIES:
                authorities[strategy] = workbench.reviewed_principles("progression", {**advice["context"],
                    "strategy": strategy, "available_loads": settings["available_loads"]})
        finally:
            workbench.close()
    from healthzip.training.daily_decisions import decisions, option
    targets = advice["effective_targets"]["sets"]
    remaining = {s["set_uuid"] for s in instance["sets"] if s.get("completion_state") == "draft"
        and not s.get("deleted_at") and not s.get("started_at") and not s.get("ended_at")
        and advice["session"].get("session_status") in {"draft", "in_progress", "paused"}}
    groups = []
    for selected in targets:
        if selected["set_uuid"] in remaining:
            groups.append({"set_uuid": selected["set_uuid"], "original_target": selected,
                "options": [option(record, history, selected["target"], settings["available_loads"], strategy,
                    authorities.get(strategy, {"principles": [], "excluded": [{"reason": "local_knowledge_store_missing"}]}),
                    advice["context"], target_set_uuid=selected["set_uuid"])
                    for record in history["records"] or [None] for strategy in STRATEGIES]})
    payload = {"advice_id": canonical_hash([instance_id, signature]), "version": VERSION, "created_at": cutoff,
        "generation_origin": "automatic_training", "user_choice": None, "input_hash": signature,
        "session_id": instance["session_id"], "session_uuid": advice["session"]["session_uuid"],
        "session_exercise_id": instance_id, "task_id": advice["context"]["task_id"], "condition": instance["condition"],
        "exercise_name": instance["exercise"]["name"], "target_version": advice["effective_targets"]["revision"],
        "original_plan": instance.get("planned"), "effective_targets": advice["effective_targets"],
        "groups": groups, "scope": "listed_draft_set_uuids_only_until_next_version_before_set_start",
        "reference_record": None, "reference_exclusions": [],
        "daily_history": history, "daily_decisions": decisions(history, groups),
        "recent_training": recent_training,
        "review_run_id": review["run_id"], "body": review["supplements"].get("current_body_context"),
        "dated_symptom_observations": symptom_reports,
        "source_report_id": source_report_id, "source_report_mapping": source_report_mapping,
        "settings": settings, "knowledge_signature": knowledge,
        "unknown": [] if groups else ["尚无未开始的目标组；仍可自由记录，事实展示不要求模板或计划。"]}
    payload["daily_decisions"].update(body_context=payload["body"], recent_related_training=recent_training,
        current_targets=advice["effective_targets"], body_action_policy="facts_and_rule_applicability_only_no_state_to_load_mapping")
    repo.conn.execute("BEGIN IMMEDIATE")
    try:
        _validate_freeze(repo, svc, advice, revision, context_id, settings, knowledge_root, knowledge)
        repo.conn.execute("INSERT OR IGNORE INTO current_training_advice VALUES(?,?,?,?,?,?)",
            (payload["advice_id"], "local", instance_id, signature, cutoff, json.dumps(payload, ensure_ascii=False)))
        repo.conn.commit()
    except BaseException:
        repo.conn.rollback()
        raise
    _link_report(repo, payload["advice_id"], source_report_id)
    return json.loads(repo.conn.execute("SELECT payload_json FROM current_training_advice WHERE advice_id=?",
                                       (payload["advice_id"],)).fetchone()[0])


def objective_comparison(repo, instance_id, *, cutoff_time=None):
    """Read current actual revisions and freeze a deterministic objective view.

    Explicit scope + the latest pre-start version establish temporal linkage.
    Missing timestamps or tied versions retain ambiguity. No matching by load,
    repetitions, exercise name or success, and no feedback writes.
    """
    svc = TrainingService(repo)
    revision = input_version(repo, None)
    if cutoff_time:
        # Only use today's scoped parent key to locate the immutable replay.
        # Current sets/catalog/conditions are not inputs to a historical view.
        parent = repo.conn.execute(
            "SELECT session_id FROM training_session_exercise WHERE id=? AND user_id=?",
            (instance_id, svc.user_id)).fetchone()
        if parent is None:
            raise TrainingError("找不到此训练动作")
        session = svc.session_as_of(parent[0], cutoff_time=cutoff_time, include_deleted=True)
        instance = next((i for i in session["exercises"] if i["id"] == instance_id), None)
        if instance is None:
            raise ValueError("training_instance_not_visible_at_report_cutoff")
    else:
        instance = svc.get_session_exercise(instance_id)
        session = svc.get_session(instance["session_id"])
    versions = [json.loads(r[0]) for r in repo.conn.execute(
        "SELECT payload_json FROM current_training_advice WHERE user_id='local' AND session_exercise_id=? ORDER BY created_at,advice_id",
        (instance_id,))]
    if cutoff_time:
        versions = [v for v in versions if instant(v["created_at"]) <= instant(cutoff_time)]
    session_state = _session_state(session)
    signature = canonical_hash([VERSION, cutoff_time, instance, session_state, [v["advice_id"] for v in versions]])
    previous = repo.conn.execute("SELECT payload_json FROM training_objective_comparison WHERE user_id='local' "
        "AND session_exercise_id=? AND input_hash=?", (instance_id, signature)).fetchone()
    if previous:
        if revision != input_version(repo, None):
            raise ValueError("concurrent_objective_comparison_retry_required")
        return json.loads(previous[0])
    rows = []
    for actual in instance["sets"]:
        matches = [v for v in versions if any(g["set_uuid"] == actual["set_uuid"] for g in v["groups"])
                   and v["condition"] == instance["condition"] and v["session_id"] == instance["session_id"]]
        begun = actual.get("started_at")
        visible = [v for v in matches if begun and instant(v["created_at"]) <= instant(begun)]
        if visible:
            last = max(instant(v["created_at"]) for v in visible)
            visible = [v for v in visible if instant(v["created_at"]) == last]
        valid = not actual.get("deleted_at") and not instance.get("deleted_at") and not session.get("deleted_at")
        observed = valid and actual.get("completion_state") in {"completed", "aborted", "in_progress"}
        status = "record_removed" if not valid else "no_actual_record" if not observed else (
            "linked_objectively" if len(visible) == 1 else "ambiguous" if visible or (matches and not begun) else "no_prior_applicable_advice")
        selected = visible[0] if status == "linked_objectively" else None
        group = next(g for g in selected["groups"] if g["set_uuid"] == actual["set_uuid"]) if selected else None
        rows.append({"set_uuid": actual["set_uuid"], "actual_revision": actual["revision"], "status": status,
            "exclusion_reason": "parent_session_deleted" if session.get("deleted_at") else "record_deleted" if not valid else None,
            "actual": {k: actual.get(k) for k in ("started_at", "ended_at", "completion_state", "load_value", "load_unit",
                        "reps", "rir", "quality_status", "stop_reason", "deleted_at")},
            "advice_id": selected["advice_id"] if selected else None,
            "possible_advice_ids": [v["advice_id"] for v in visible or matches] if status == "ambiguous" else [],
            "frozen_group": group, "intent": "unknown_not_inferred"})
    result = {"comparison_id": canonical_hash([instance_id, signature]), "version": VERSION,
        "session_exercise_id": instance_id, "session_id": instance["session_id"],
        "session_state": session_state,
        "created_at": datetime.now(timezone.utc).isoformat(), "rows": rows,
        "cutoff_time": cutoff_time,
        "identity": "objective_records_not_adoption_execution_failure_or_causal_effect"}
    cut = cutoff_time or result["created_at"]
    start = session["started_at"]
    source, inherited = snapshot(repo, cut, window_start=start, window_end=cut, include_sources=False,
                                 training_session_ids=(instance["session_id"],))
    actuals = [r for r in source if r.get("session_exercise_id") == instance_id]
    actual_by_uuid = {r["set_uuid"]: r for r in reversed(actuals)}
    version_by_id = {v["advice_id"]: v for v in reversed(versions)}
    for row in result["rows"]:
        chosen = version_by_id.get(row["advice_id"], {})
        reference = chosen.get("reference_record")
        actual = actual_by_uuid.get(row["set_uuid"])
        row["reference_comparison"] = {}
        row["daily_comparisons"] = []
        if chosen.get("daily_history") and actual and row["status"] == "linked_objectively":
            from healthzip.training.daily_decisions import observation
            from healthzip.training.daily_history import daily_comparability
            previous = chosen["daily_history"]["records"]
            for recorded in previous:
                comparison = daily_comparability(recorded, actual)
                limits = list(comparison["reason_codes"])
                metrics = {}
                if len(previous) != 1:
                    limits.append("multiple_historical_sets_no_unique_pairing_all_shown_without_best_match")
                elif comparison["comparable"] and recorded.get("ended_at"):
                    historical = {**recorded, "record_kind": "strength_set",
                        "id": "strength_set:" + recorded["set_uuid"],
                        "event_end": recorded.get("ended_at"), "event_start": recorded.get("started_at")}
                    pair = [historical, actual]
                    metrics = evaluate_subset(("STR-12", "STR-13", "STR-14"), pair, cutoff_time=cut,
                        window_start=min(start, recorded["ended_at"], key=instant), window_end=cut,
                        context={"comparison_pair": pair})
                row["daily_comparisons"].append({"source_set_id": recorded["set_uuid"],
                    "observation": observation(recorded), "actual_set_uuid": row["set_uuid"],
                    "comparability": comparison, "metrics": metrics, "limitations": limits})
        if reference and actual and row["status"] == "linked_objectively":
            pair_start = min(start, reference["ended_at"], key=instant)
            pair = [reference, actual]
            row["reference_comparison"] = evaluate_subset(("STR-12", "STR-13", "STR-14"), pair,
                cutoff_time=cut, window_start=pair_start, window_end=cut, context={"comparison_pair": pair})
    ids = {r.get("set_uuid") for r in actuals}
    context = {**inherited, "plan_snapshot": {"sets": [s for p in inherited.get("session_plans", [])
                for s in p["sets"] if s["id"] in ids]}}
    result["metrics"] = evaluate_subset(("STR-01", "STR-02", "STR-03", "STR-09", "STR-10"), actuals,
        cutoff_time=cut, window_start=start, window_end=cut, context=context)
    repo.conn.execute("BEGIN IMMEDIATE")
    try:
        current_ids = [r[0] for r in repo.conn.execute("SELECT advice_id,created_at FROM current_training_advice "
            "WHERE user_id='local' AND session_exercise_id=? ORDER BY created_at,advice_id", (instance_id,))
            if not cutoff_time or instant(r[1]) <= instant(cutoff_time)]
        if revision != input_version(repo, None) or current_ids != [v["advice_id"] for v in versions]:
            raise ValueError("concurrent_objective_comparison_retry_required")
        repo.conn.execute("INSERT OR IGNORE INTO training_objective_comparison VALUES(?,?,?,?,?,?)",
            (result["comparison_id"], "local", instance_id, signature, result["created_at"], json.dumps(result, ensure_ascii=False)))
        repo.conn.commit()
    except BaseException:
        repo.conn.rollback()
        raise
    return result
