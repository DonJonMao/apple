"""Current-session business versions over the existing advice/workflow core.

Automatic association is objective identity/time linkage, never a user feedback
event. Immutable suggestions, plans and actual revisions remain separate.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from healthzip.advice import build_advice_context
from healthzip.analytics.v13 import snapshot
from healthzip.science import evaluate
from healthzip.science.contracts import canonical_hash, instant
from healthzip.training.semantics import numeric
from healthzip.training.service import TrainingService
from healthzip.workflows import WorkflowRequest, run_workflow
from healthzip.workflows.dependencies import input_version

VERSION = "current-training-1.1.0"
STRATEGIES = ("double_progression", "heavier_lower_reps", "repetition_progression")


def _link_report(repo, advice_id, source_report_id):
    if source_report_id:
        repo.conn.execute("INSERT OR IGNORE INTO current_advice_report_link VALUES(?,?,?)",
            (advice_id, source_report_id, datetime.now(timezone.utc).isoformat()))
        repo.conn.commit()


def knowledge_signature(root):
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


def save_equipment_loads(repo, instance_id, loads):
    """Persist a user's actual settings for this physical condition, not a rule."""
    svc = TrainingService(repo)
    instance = svc.get_session_exercise(instance_id)
    if not isinstance(loads, list) or any(isinstance(v, bool) for v in loads):
        raise ValueError("器械档位须为非负有限数字列表")
    values = [numeric(v, "器械档位") for v in loads]
    if any(v is None or v < 0 for v in values):
        raise ValueError("器械档位须为非负有限数字列表")
    condition = canonical_hash(instance["condition"])
    payload = {"available_loads": sorted(set(values)), "load_basis": instance["condition"].get("load_basis"),
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
            "provenance": config.get("step_source") if known else None, "equipment_id": identity,
            "load_basis": instance["condition"].get("load_basis")}


def _option(advice, target, loads, strategy, authority, cutoff, zone):
    plan = {"rep_upper": target.get("reps_max"), "next_target_reps": target.get("reps_min"),
            "target_rir_min": target.get("rir"), "target_rir_max": target.get("rir"), "available_loads": loads}
    metric_id = "STR-25" if strategy == "double_progression" else "STR-26"
    metric = evaluate(metric_id, advice["records"], cutoff_time=cutoff,
        window_start=(instant(cutoff)-timedelta(days=365)).isoformat(), window_end=cutoff,
        context={**advice["context"], "timezone": zone, "strategy": strategy,
                 "progression_plan": plan if target else None, "reviewed_principles": authority["principles"],
                 "allowed_trial_actions": [strategy] if metric_id == "STR-26" else []})
    value = metric.get("value") or {}
    trial = value.get("task_trial") or {}
    load = value.get("next_load") if metric_id == "STR-25" else trial.get("load_value")
    reps = value.get("target_reps") if metric_id == "STR-25" else trial.get("reps_target")
    reference = value.get("reference_set_id") if metric_id == "STR-25" else trial.get("reference_set_id")
    observed = next((r for r in advice["records"] if r.get("set_uuid") == reference), None)
    rules = [p for p in authority["principles"] if strategy in p.get("permitted_actions", [])]
    return {"strategy": strategy, "metric": metric, "load": load,
            "load_unit": value.get("load_unit") if metric_id == "STR-25" else trial.get("load_unit"),
            "reps": reps, "rir": target.get("rir") if load is not None else None,
            "basis": {"rules": rules, "reference_set_id": reference,
                      "reference_observation": _reference_observation(observed) if observed else None,
                      "personal_record_ids": advice["context"]["baseline_record_ids"],
                      "weight_origin": "可比参考组的实际负荷" if strategy == "repetition_progression" else "匹配行动规则许可的实际器械档位",
                      "repetitions_origin": "沿用用户计划次数上限" if strategy == "repetition_progression" else "沿用用户计划次数下限",
                      "rir_origin": "用户计划 RIR；未指定时保持未知",
                      "plan": target, "available_loads": loads},
            "limitations": ["可选方案，不表示用户采纳或承诺执行。", "实际下一档不单独证明适宜；计划次数不是资料库推导的个人最优次数。"],
            "excluded_rules": authority.get("excluded", [])}


def _reference_observation(record):
    from healthzip.science.semantics import flatten_record
    row = flatten_record(record)
    return {k: row.get(k) for k in ("set_uuid", "session_id", "session_exercise_id", "ended_at", "started_at",
        "exercise_name", "load_value", "load_unit", "load_basis", "reps", "rir", "rir_interval", "rir_qualifier",
        "reference_declared_at", "reference_selection", "condition", "quality_status", "stop_reason")}


def _reference_exclusions(records, references):
    chosen = references[-1] if references else None
    recent = [r for r in records if not chosen or instant(r["ended_at"]) > instant(chosen["ended_at"])]
    result = []
    for row in recent:
        if not row.get("reference_set"):
            reason = "最近实际未在开始前指定为参考；普通实际仍参与描述分析"
        elif not row.get("reference_declared_at") or not row.get("started_at") or instant(row["reference_declared_at"]) > instant(row["started_at"]):
            reason = "参考指定时间或实际开始时间缺失，或指定晚于开始"
        else:
            reason = "同任务参考身份冲突或非完成工作组，不能自动择优替代"
        result.append({"observation": _reference_observation(row), "reason": reason,
            "retained_reference": _reference_observation(chosen) if chosen else None})
    return result


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


def _validate_freeze(repo, svc, advice, revision, context_id, settings, knowledge_root, knowledge):
    instance = svc.get_session_exercise(advice["instance"]["id"])
    session = svc.get_session(instance["session_id"])
    if (input_version(repo, context_id) != revision
            or _instance_state(instance) != _instance_state(advice["instance"])
            or _session_state(session) != _session_state(advice["session"])
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
    advice = build_advice_context(repo, identity["session_id"], instance_id, None, [], None,
        cutoff_time=cutoff, timezone_name=timezone_name, generation_origin="automatic_training")
    instance = advice["instance"]
    if instance.get("deleted_at") or instance.get("replaced_by_instance_id"):
        raise ValueError("selected_training_instance_unavailable")
    if source_report_id:
        from healthzip.workflows import load_run
        source = load_run(repo, source_report_id)
        if (source.get("task_selection") or {}).get("task_id") != advice["context"]["task_id"]:
            raise ValueError("source_report_task_mismatch")
    settings = equipment_loads(repo, instance)
    records, _ = snapshot(repo, cutoff, window_start=(instant(cutoff)-timedelta(days=baseline_days)).isoformat(),
        window_end=cutoff, canonical_types=["sleep_stage", "resting_heart_rate_bpm", "hrv_sdnn_ms", "body_mass_kg"])
    background = [r for r in records if r.get("record_kind") != "strength_set"]
    knowledge = knowledge_signature(knowledge_root)
    current_context = {k: v for k, v in advice["context"].items()
                       if k in {"profile_revision", "profile_provenance", "task_id", "protocol", "current_session_observations"}}
    signature = canonical_hash({"version": VERSION, "instance": instance, "records": advice["records"],
        "body": background, "context": current_context, "settings": settings, "context_id": context_id,
        "context_revision": {k: v for k, v in revision.items() if k.startswith("context")},
        "window_days": window_days, "baseline_days": baseline_days, "timezone": timezone_name,
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
    targets = advice["effective_targets"]["sets"]
    remaining = {s["set_uuid"] for s in instance["sets"] if s.get("completion_state") == "draft"
        and not s.get("deleted_at") and not s.get("started_at") and not s.get("ended_at")
        and advice["session"].get("session_status") in {"draft", "in_progress", "paused"}}
    groups = []
    for selected in targets:
        if selected["set_uuid"] in remaining:
            groups.append({"set_uuid": selected["set_uuid"], "original_target": selected,
                "options": [_option(advice, selected["target"], settings["available_loads"], strategy,
                    authorities.get(strategy, {"principles": [], "excluded": [{"reason": "local_knowledge_store_missing"}]}),
                    cutoff, timezone_name) for strategy in STRATEGIES]})
    from healthzip.science.semantics import flatten_record
    from healthzip.science.strength import reference_rows
    references = reference_rows([{**flatten_record(r), "_event_end": r["ended_at"]} for r in advice["records"]], {})
    payload = {"advice_id": canonical_hash([instance_id, signature]), "version": VERSION, "created_at": cutoff,
        "generation_origin": "automatic_training", "user_choice": None, "input_hash": signature,
        "session_id": instance["session_id"], "session_uuid": advice["session"]["session_uuid"],
        "session_exercise_id": instance_id, "task_id": advice["context"]["task_id"], "condition": instance["condition"],
        "exercise_name": instance["exercise"]["name"], "target_version": advice["effective_targets"]["revision"],
        "original_plan": instance.get("planned"), "effective_targets": advice["effective_targets"],
        "groups": groups, "scope": "listed_draft_set_uuids_only_until_next_version_before_set_start",
        "reference_record": references[-1] if references else None,
        "reference_exclusions": _reference_exclusions(advice["records"], references),
        "review_run_id": review["run_id"], "body": review["supplements"].get("current_body_context"),
        "source_report_id": source_report_id, "settings": settings, "knowledge_signature": knowledge,
        "unknown": [] if groups else ["尚无未开始的逐组目标；请确定动作和目标后核对具体数值，实际训练仍可直接记录。"]}
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
    instance = svc.get_session_exercise(instance_id)
    session = svc.get_session(instance["session_id"])
    if cutoff_time:
        session = svc.session_as_of(instance["session_id"], cutoff_time=cutoff_time, include_deleted=True)
        instance = next((i for i in session["exercises"] if i["id"] == instance_id), None)
        if instance is None:
            raise ValueError("training_instance_not_visible_at_report_cutoff")
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
    source, inherited = snapshot(repo, cut, window_start=start, window_end=cut, include_sources=False)
    actuals = [r for r in source if r.get("session_exercise_id") == instance_id]
    for row in result["rows"]:
        chosen = next((v for v in versions if v["advice_id"] == row["advice_id"]), {})
        reference = chosen.get("reference_record")
        actual = next((r for r in actuals if r["set_uuid"] == row["set_uuid"]), None)
        row["reference_comparison"] = {}
        if reference and actual and row["status"] == "linked_objectively":
            pair_start = min(start, reference["ended_at"], key=instant)
            pair = [reference, actual]
            row["reference_comparison"] = {mid: evaluate(mid, pair, cutoff_time=cut,
                window_start=pair_start, window_end=cut, context={"comparison_pair": pair})
                for mid in ("STR-12", "STR-13", "STR-14")}
    ids = {r.get("set_uuid") for r in actuals}
    context = {**inherited, "plan_snapshot": {"sets": [s for p in inherited.get("session_plans", [])
                for s in p["sets"] if s["id"] in ids]}}
    result["metrics"] = {mid: evaluate(mid, actuals, cutoff_time=cut, window_start=start, window_end=cut, context=context)
                         for mid in ("STR-01", "STR-02", "STR-03", "STR-09", "STR-10")}
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
