"""Prospective product sampling only; scientific eligibility stays in STR-25/26.

No actual load, reps, RIR or success is used to select a row. The event ledger
locks selection once observation/skip has occurred, including later deletions
and undo. Old completed ordinary rows are never nominated by migration.
"""
import json
from collections import defaultdict

from healthzip.science.contracts import canonical_hash
from healthzip.science.semantics import analysis_task
from healthzip.training.semantics import TrainingError, json_text

PROTOCOL = "first-planned-work-set"
VERSION = "1.0.0"
FIRST_POLICIES = {"first-work-set", "predeclared-first-work-set", PROTOCOL}


def scope(row):
    # Sampling spans repeated instances of the same physical/protocol task.
    # Position is chosen prospectively and remains part of the scientific task.
    return row.get("condition_key") or canonical_hash(row.get("condition") or {})


def observed(row):
    return bool(row.get("started_at") or row.get("ended_at")
        or row.get("completion_state") in {"in_progress", "completed", "aborted"}
        or row.get("completion_state") == "skipped" and not (row.get("reference_selection") or {}).get("replacement_before_start_event_id"))


def locked_scopes(svc, session):
    locked = {scope(row) for row in session["sets"] if observed(row)}
    # Ledger, rather than current state alone: deleting/reverting a poor result
    # must never reopen the ability to sample a better already-observed group.
    for raw in svc.conn.execute("SELECT after_json FROM training_event WHERE user_id=? AND status='applied' "
            "AND entity_type IN ('set','session_exercise','session') AND "
            "(json_extract(after_json,'$.session_id')=? OR (entity_type='session' AND json_extract(after_json,'$.id')=?))",
            (svc.user_id, session["id"], session["id"])):
        value = json.loads(raw[0])
        for row in [value] if value.get("set_uuid") else value.get("sets", []):
            if observed(row):
                locked.add(scope(row))
    return locked


def selection(svc, session, instance, row, now, origin):
    protocol = (instance["condition"].get("reference_protocol") or {})
    policy = protocol.get("reference_policy_id")
    explicit = (row.get("planned") or {}).get("reference_set") is True
    return {"origin": origin, "selection_protocol": "explicit-planned-reference-set" if explicit else PROTOCOL, "selection_protocol_version": VERSION,
        "protocol_kind": "product_sampling_not_scientific_optimization",
        "declared_plan_protocol": protocol or None,
        "selection_basis": "user_explicit" if origin == "user_explicit" else "explicit_plan_set" if explicit else
            "explicit_plan_policy" if policy in FIRST_POLICIES else "product_default_plan_order",
        "session_id": session["id"], "session_uuid": session["session_uuid"],
        "session_exercise_id": instance["id"], "condition": instance["condition"],
        "task_id": analysis_task(row)["task_id"], "set_uuid": row["set_uuid"],
        "target_version": svc.targets_from_instance(instance)["revision"],
        "selected_target": row.get("planned") or {},
        "template_id": session.get("template_id"), "template_version": session.get("template_version"),
        "declared_at": now, "state": "designated"}


def manual_selection(svc, row, now):
    instance = svc.get_session_exercise(row["session_exercise_id"])
    session = svc.get_session(row["session_id"])
    if row.get("completion_state") != "draft" or observed(row) or scope(row) in locked_scopes(svc, session):
        raise TrainingError("参考组必须在本任务开始观察之前预先指定，不能事后追认")
    competing = [s for s in session["sets"] if s["set_uuid"] != row["set_uuid"] and s.get("reference_set")
        and not s.get("deleted_at") and analysis_task(s)["task_id"] == analysis_task(row)["task_id"]]
    if competing:
        raise TrainingError("同一任务已指定参考组；请在开始前先撤销原指定")
    return selection(svc, session, instance, row, now, "user_explicit")


def missing_requirements(row):
    target = row.get("planned") or {}
    reasons = []
    if not row.get("condition_key"):
        reasons.append("动作／器械条件尚未确认完整")
    if not target:
        reasons.append("尚无明确的计划工作组目标")
    elif (row.get("condition") or {}).get("measurement_mode") == "repetitions":
        if any(target.get(k) is None for k in ("reps_min", "reps_max")):
            reasons.append("计划次数范围不完整")
        if target.get("rir") is None:
            reasons.append("计划 RIR 未指定")
    else:
        reasons.append("本产品采样协议只覆盖已计划的次数工作组")
    policy = ((row.get("condition") or {}).get("reference_protocol") or {}).get("reference_policy_id")
    if policy and policy not in FIRST_POLICIES and target.get("reference_set") is not True:
        reasons.append("计划的参考选择规则需要明确指定，不能自动解释其含义")
    return reasons


def reconcile(svc, session_id, source_event_id):
    """Called inside the triggering training mutation, never by retrieval/read."""
    session = svc.get_session(session_id)
    if session.get("deleted_at") or session.get("session_status") not in {"draft", "in_progress", "paused"}:
        return
    locked = locked_scopes(svc, session)
    trigger = svc.conn.execute("SELECT action,after_json FROM training_event WHERE event_id=?", (source_event_id,)).fetchone()
    created = set()
    if trigger and trigger[0] in {"start_session", "add_exercise", "add_set", "replace_exercise"}:
        value = json.loads(trigger[1])
        created = {r["set_uuid"] for r in ([value] if value.get("set_uuid") else value.get("sets", []))}
    groups = defaultdict(list)
    instances = {i["id"]: i for i in session["exercises"]}
    for instance in session["exercises"]:
        for row in instance["sets"]:
            groups[scope(row)].append((instance, row))
    for key, entries in groups.items():
        # Fixed ordering only. Never inspect actual weights, repetitions or RIR.
        entries.sort(key=lambda pair: (pair[0]["position"], pair[0]["id"], pair[1]["set_number"], pair[1]["id"]))
        if key in locked:
            continue
        active = [(i, r) for i, r in entries if not i.get("deleted_at") and not i.get("replaced_by_instance_id")
            and not r.get("deleted_at") and r.get("completion_state") == "draft"]
        def stale_manual(instance, row):
            meta = row.get("reference_selection") or {}
            return meta.get("origin") == "user_explicit" and (
                meta.get("condition") != instance["condition"]
                or meta.get("selected_target") != (row.get("planned") or {}))

        manual = any(r.get("reference_set") and (r.get("reference_selection") or {}).get("origin") != "system_plan_protocol"
            and not stale_manual(i, r) for i, r in active)
        work = [(i, r) for i, r in active if r.get("set_type") == "work" and r.get("planned")]
        explicit = [(i, r) for i, r in work if r["planned"].get("reference_set") is True]
        candidate = (explicit[0] if len(explicit) == 1 else work[0] if work and not explicit else None)
        withdrawn = candidate and (candidate[1].get("reference_selection") or {}).get("state") == "withdrawn_by_user"
        if manual or withdrawn or candidate and missing_requirements(candidate[1]):
            candidate = None
        for instance, row in entries:
            old = row.get("reference_selection") or {}
            chosen = candidate is not None and row["set_uuid"] == candidate[1]["set_uuid"]
            automatic = old.get("origin") == "system_plan_protocol"
            if not chosen and not (row.get("reference_set") and (automatic or stale_manual(instance, row))):
                continue
            from .service import _uuid, timestamp
            now = timestamp()
            if chosen:
                meta = selection(svc, session, instances[instance["id"]], row, now, "system_plan_protocol")
                if row.get("reference_set") and {k: v for k, v in meta.items() if k != "declared_at"} == {
                        k: v for k, v in old.items() if k != "declared_at"}:
                    continue
            else:
                meta = {**old, "state": "invalidated_before_observation", "invalidated_at": now,
                    "reason": "plan_order_target_condition_or_availability_changed"}

            initial = row["set_uuid"] in created and row["revision"] == 1 and not old

            def apply(current, eid, recorded, *, meta=meta, chosen=chosen, row=row, initial=initial):
                svc.conn.execute("UPDATE strength_set SET reference_set=?,reference_declared_at=?,reference_selection_json=?,"
                    "revision=revision+?,available_at=? WHERE id=?",
                    (int(chosen), meta["declared_at"] if chosen else row.get("reference_declared_at"), json_text(meta),
                     int(not initial), recorded, row["id"]))
                return svc.get_set(row["id"])

            svc._mutate("reference_selection", "set", row["set_uuid"],
                {"source_event_id": source_event_id, "selection": meta,
                 "reason": "initial_prospective_sampling" if initial else "plan_order_target_condition_or_availability_changed"}, apply,
                event_id=_uuid(source_event_id, "reference:" + row["set_uuid"]),
                before=lambda row=row: svc.get_set(row["id"]))
