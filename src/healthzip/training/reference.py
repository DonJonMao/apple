"""Optional prospective specialist references, independent of daily advice.

Ordinary mutations never invoke this module to nominate/reselect a reference.
The ledger prevents retrospective nominations; existing designations retain
their original provenance. Policy names describe distinct selection positions.
"""
import json

from healthzip.science.contracts import canonical_hash, instant
from healthzip.science.semantics import analysis_task
from healthzip.training.semantics import TrainingError

PROTOCOL = "first-planned-work-set"
VERSION = "1.1.0"
FIRST_WORK_POLICIES = {"first-work-set", "predeclared-first-work-set"}
FIRST_POLICIES = FIRST_WORK_POLICIES | {PROTOCOL}


def policy_candidate(rows, policy):
    """Locate the protocol position before checking data/target eligibility.

    ``rows`` must be the full ordered set inventory, not only successful or
    otherwise eligible sets. Deletion, missing targets and failed performance
    cannot promote the next work set into the first-work-set position.
    """
    if policy not in FIRST_POLICIES:
        return None
    work = [row for row in rows if row.get("set_type", row.get("role")) == "work"]
    if policy == PROTOCOL:
        work = [row for row in work if row.get("planned")]
    return work[0] if work else None


def specialist_policy_allows(row, rows):
    """Validate named position for a new specialist calculation, not history.

    Accepts normalized science rows. It does not rewrite stored nominations or
    their frozen results. Callers must supply all known sets, including failed,
    skipped and incomplete work, before other scientific eligibility filtering.
    """
    policy = row.get("reference_policy_id")
    if not policy:
        return True
    if policy not in FIRST_POLICIES:
        return False
    # Full inventories precede observation-time filtering, but may contain
    # multiple visible revisions of one logical set. A superseded work/warmup
    # role must not establish today's first-work position. Availability ranks
    # revisions; it never supplies a missing performance occurrence time.
    latest = {}
    for item in rows:
        identity = item.get("set_uuid") or item.get("source_record_id") or item.get("set_id") or item.get("id")
        if identity is None:
            continue
        available = item.get("available_at")
        rank = (instant(available) if available else instant("0001-01-01T00:00:00+00:00"),
                item.get("revision") or 0)
        if identity not in latest or rank > latest[identity][0]:
            latest[identity] = (rank, item)
    instance = row.get("session_exercise_id")
    candidates = [r for _, r in latest.values() if r.get("session_id") == row.get("session_id")
        and (r.get("session_exercise_id") == instance if instance else scope(r) == scope(row))]
    # Unknown positions cannot be repaired with grades, timestamps or IDs.
    work = [r for r in candidates if r.get("set_type", r.get("role")) == "work"]
    if not work or any(r.get("set_position", r.get("set_number")) is None for r in work):
        return False
    work.sort(key=lambda r: r.get("set_position", r.get("set_number")))
    candidate = policy_candidate(work, policy)

    def identity(r):
        return r.get("set_uuid") or r.get("set_id") or r.get("id")

    return candidate is not None and identity(candidate) == identity(row)


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
    return {"origin": origin, "selection_protocol": policy if policy in FIRST_POLICIES else "explicit-set", "selection_protocol_version": VERSION,
        "protocol_kind": "optional_specialist_selection_not_daily_advice",
        "declared_plan_protocol": protocol or None,
        "policy_interpretation": "recognized_position_only" if policy in FIRST_POLICIES else "unrecognized_not_interpreted" if policy else "no_named_policy",
        "selection_basis": "user_explicit",
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
    policy = (instance["condition"].get("reference_protocol") or {}).get("reference_policy_id")
    if policy in FIRST_POLICIES:
        ordered = [r for i in sorted(session["exercises"], key=lambda i: (i["position"], i["id"]))
            for r in sorted(i["sets"], key=lambda r: (r["set_number"], r["id"]))
            if scope(r) == scope(row)]
        candidate = policy_candidate(ordered, policy)
        if candidate is None or candidate["set_uuid"] != row["set_uuid"]:
            raise TrainingError("逐组指定与已声明的首工作组协议冲突；不能跳过协议位置或替换其语义")
    competing = [s for s in session["sets"] if s["set_uuid"] != row["set_uuid"] and s.get("reference_set")
        and not s.get("deleted_at") and analysis_task(s)["task_id"] == analysis_task(row)["task_id"]]
    if competing:
        raise TrainingError("同一任务已指定参考组；请在开始前先撤销原指定")
    return selection(svc, session, instance, row, now, "user_explicit")
