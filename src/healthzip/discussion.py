"""Source explanations and recorded facts for non-numerical user discussions."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from healthzip.science.contracts import finite, instant
from healthzip.science.semantics import flatten_record

TOPICS = {"discuss_sets": "volume", "discuss_interval": "frequency", "discuss_rest": "rest"}
QUESTIONS = {"volume": "力量训练组数有哪些一般考虑？",
             "frequency": "力量训练每周频率与场次分布有哪些一般考虑？",
             "rest": "力量训练组间休息有哪些一般考虑？"}


def explanation(workbench, strategy, context):
    """A selected discussion topic establishes no numerical action permission."""
    outcome = TOPICS[strategy]
    question = QUESTIONS[outcome]
    answer = workbench.query(question, route="progression", context={
        **{key: context[key] for key in ("age", "training_goal", "training_experience", "health_scope") if key in context},
        "corpus_roles": ["core"], "question_contract": {"subject": "resistance_training",
            "outcome": outcome, "requested_relation": "options", "user_confirmed": True}})
    return {key: answer[key] for key in ("answer_status", "answer", "claims", "citations", "limits", "evidence_bundle_hash")}


def build_discussion(workbench, advice, strategy, available_minutes=None):
    if available_minutes is not None and (not isinstance(available_minutes, (int, float))
                                         or finite(available_minutes) is None or available_minutes <= 0):
        raise ValueError("可用训练时间须为正的有限分钟数，或留空")
    context = advice["context"]
    cutoff = instant(context["as_of"])
    start = cutoff - timedelta(days=365)
    sessions = defaultdict(list)
    for raw in advice["records"]:
        row = flatten_record(raw)
        if row.get("ended_at") and start <= instant(row["ended_at"]) < cutoff:
            sessions[row["session_id"]].append(row)
    observations = []
    for session_id, rows in sessions.items():
        parents = {r.get("parent_set_id") or r["set_uuid"] for r in rows if r.get("role") == "work"}
        observations.append({"session_id": session_id, "first_recorded_set_start": min(
            (r["started_at"] for r in rows if r.get("started_at")), key=instant, default=None),
            "last_recorded_set_end": max((r["ended_at"] for r in rows), key=instant),
            "completed_work_parent_sets": len(parents), "work_parent_set_ids": sorted(parents),
            "record_ids": [r["set_uuid"] for r in rows],
            "unknown_role_record_ids": [r["set_uuid"] for r in rows if r.get("role") not in {"work", "warmup"}]})
    observations.sort(key=lambda r: instant(r["last_recorded_set_end"]))
    intervals = []
    for previous, current in zip(observations, observations[1:]):
        a, b = previous["first_recorded_set_start"], current["first_recorded_set_start"]
        intervals.append({"from_session_id": previous["session_id"], "to_session_id": current["session_id"],
            "value": (instant(b) - instant(a)).total_seconds() / 86400 if a and b else None,
            "unit": "days", "basis": "first_recorded_same_condition_set_start_to_start"})
    raw_sets = {r["set_uuid"]: r for r in advice["instance"]["sets"]}
    planned = [r for r in advice["effective_targets"]["sets"] if r["target"]
               and raw_sets[r["set_uuid"]].get("set_type") == "work"]
    value = {"strategy": strategy, "topic": TOPICS[strategy], "authority": "source_explanation_only",
        "source_explanation": explanation(workbench, strategy, context),
        "observations": {"explicit_planned_work_sets": len(planned), "planned_work_set_ids": [r["set_uuid"] for r in planned],
            "target_version": advice["effective_targets"]["revision"], "recorded_sessions": observations,
            "current_session_records": [{key: row.get(key) for key in (
                "set_uuid", "revision", "set_type", "completion_state", "started_at", "ended_at",
                "load_value", "load_unit", "reps", "rir", "pain_flag", "quality_status", "stop_reason")}
                for row in map(flatten_record, context["current_session_observations"])],
            "recorded_interval_days": intervals, "condition_key": advice["instance"].get("condition_key"),
            "window": {"start": start.isoformat(), "end": cutoff.isoformat(), "kind": "product_observation_window"},
            "cutoff_time": cutoff.isoformat(), "available_minutes": available_minutes,
            "available_minutes_provenance": {"kind": "user_constraint", "unit": "minutes", "recorded_at": cutoff.isoformat()} if available_minutes is not None else None},
        "questions": {
            "discuss_sets": ["当前计划中哪些工作组是你希望保留或调整的？", "可用时间和已记录的动作质量是否允许执行你选择的安排？"],
            "discuss_interval": ["你希望把现有训练安排在哪些场次？", "场次间隔和每组间歇是不同的记录；你希望讨论哪次训练的安排？"],
            "discuss_rest": ["你希望核对哪些明确计划中的组间休息安排？", "实际组前间隔、记录方法、动作质量和停止原因是否已记录，以便后续复核？"],
        }[strategy],
        "numeric_action_limitations": [],
        "limitations": ["仅讨论来源的一般原则及已记录事实，不确定个人最佳组数、频率、组间间歇或恢复天数。",
            "未记录的场次与组数保持未知；所示间隔仅连接本机已记录的同条件场次，不能证明期间没有其他训练。",
            "可用时间是用户约束，不是推算最佳训练量的科学参数。"]}
    if strategy == "discuss_rest":
        value["observations"].update(_rest_facts(advice, sessions))
        value["limitations"] += [
            "计划休息、用户主动记录和相邻组端点派生间隔分别保留；它们不能互相填补缺值。",
            "派生间隔来自当时可见的相邻执行端点，可能跨动作；它不证明期间完全静息，也不等于恢复所需时间。",
        ]
    return value


def _rest_facts(advice, sessions):
    """Read already-derived facts without replacing missing endpoints or plans."""
    targets = advice["effective_targets"]
    planned = [{"record_id": row["set_uuid"], "revision": row["revision"],
        "seconds": row["target"].get("rest_seconds"), "unit": "s", "origin": "user_plan",
        "target_version": targets["revision"], "completion_state": row["completion_state"]}
        for row in targets["sets"]]
    observations = []
    for origin, rows in (("historical_same_condition", [row for group in sessions.values() for row in group]),
                         ("current_session", advice["context"]["current_session_observations"])):
        for raw in rows:
            row = flatten_record(raw)
            observations.append({"record_id": row["set_uuid"], "revision": row.get("revision"),
                "session_id": row["session_id"], "condition_key": row.get("condition_key"),
                "origin": origin, "available_at": row.get("available_at"),
                "started_at": row.get("started_at"), "ended_at": row.get("ended_at"),
                "completion_state": row.get("completion_state"), "set_type": row.get("set_type"),
                "performance": {key: row.get(key) for key in (
                    "load_value", "load_unit", "reps", "rir", "rir_interval", "quality_status", "raw_stop_reason", "pain_flag")},
                "manual": {"seconds": row.get("rest_recorded_s"), "unit": "s",
                           "method": row.get("rest_recorded_method"), "origin": "user_recorded"},
                "derived": {"seconds": row.get("rest_actual_s"), "unit": "s",
                            "provenance": row.get("rest_derivation"), "origin": "adjacent_record_endpoints"}})
    return {"planned_rest": planned, "rest_observations": observations}


def dependencies(value):
    return {(c["theory_id"], str(c["theory_version"]), c["source_version_id"], tuple(c["span_ids"]))
            for c in value.get("citations", [])}
