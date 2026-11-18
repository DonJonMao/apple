"""Versioned daily single-set options over all latest-session observations.

Selection is separate from strict research reference sampling. Arithmetic and
reviewed-rule gates are shared with STR-25/26; these business results have their
own identity and do not claim to be those unchanged scientific metrics.
"""
from healthzip.science.applicability import candidate_applicability
from healthzip.science.contracts import instant
from healthzip.science.semantics import flatten_record
from healthzip.science.strength import _completed, progression_candidate

VERSION = "daily-set-options-1.0.0"
STRATEGIES = ("double_progression", "heavier_lower_reps", "repetition_progression")


def observation(record):
    row = flatten_record(record)
    return {k: row.get(k) for k in ("set_uuid", "session_id", "session_exercise_id", "set_number",
        "set_type", "completion_state", "started_at", "ended_at", "available_at", "revision", "deleted_at",
        "exercise_name", "load_value", "load_unit", "load_basis", "reps", "rir", "rir_interval", "rir_qualifier",
        "quality_status", "pain_flag", "stop_reason", "conflicted", "condition", "daily_comparability")}


def latest_symptom_reports(records):
    """Keep all reports at the latest actual time per exact recorded scope."""
    latest = {}
    for row in records:
        if row.get("record_kind") != "subjective_log" or row.get("pain") is None or not row.get("observed_at"):
            continue
        key = (row.get("source_name"), row.get("muscle"), row.get("side"), row.get("location"))
        previous = latest.get(key, [])
        if not previous or instant(row["observed_at"]) > instant(previous[0]["observed_at"]):
            latest[key] = [row]
        elif instant(row["observed_at"]) == instant(previous[0]["observed_at"]) and row not in previous:
            previous.append(row)
    return sorted([row for group in latest.values() for row in group], key=lambda row: str(row.get("id")))


def _body_checks(records, action_scopes):
    """Latest explicit pain self-report per recorded scope, without expiry.

    Reported symptoms require current review, not a diagnosis or a load mapping.
    No report creates no prerequisite. Dates and scope stay in the frozen check.
    """
    checks = []
    for row in latest_symptom_reports(records):
        scope_known = not row.get("muscle") or row["muscle"] in action_scopes
        checks.append({"group": "body_self_report", "record_id": row["id"],
            "applicable": True if row["pain"] == "denied" else False if row["pain"] == "reported" and scope_known else None,
            "reason_codes": [] if row["pain"] == "denied" else
                ["latest_body_pain_report_requires_current_review"] if row["pain"] == "reported" and scope_known else
                ["body_pain_scope_or_status_requires_clarification"],
            "scope_status": "general_or_matching_recorded_region" if scope_known else "free_text_scope_not_inferred",
            "observations": {k: row.get(k) for k in ("observed_at", "available_at", "pain", "muscle", "side", "location", "movement_impact")}})
    return checks


def option(record, history, target, loads, strategy, authority, context, *, target_set_uuid=None):
    """Evaluate one recorded work set; every observation also informs restrictions."""
    row = flatten_record(record) if record else None
    all_observations = [r for r in history["records"] + history.get("unranked_records", []) if not r.get("deleted_at")
        and (r.get("completion_state") in {"completed", "aborted", "failed", "in_progress"}
             or r.get("started_at") or r.get("ended_at"))]
    check = candidate_applicability(row, all_observations + context.get("current_session_observations", []))
    body_checks = _body_checks(context.get("body_observations", []), context.get("body_action_scopes", []))
    check["checks"].extend(body_checks)
    check["reason_codes"] = sorted(set(check["reason_codes"]) | {r for c in body_checks for r in c["reason_codes"]})
    if any(c["applicable"] is False for c in body_checks):
        check.update(applicable=False, status="restricted")
    elif check["applicable"] is True and any(c["applicable"] is None for c in body_checks):
        check.update(applicable=None, status="unknown")
    reasons = []
    if history.get("unranked_records"):
        reasons.append("history_occurrence_order_unknown")
    if row is None:
        reasons.append("no_personal_exercise_observation")
    else:
        if any(r.get("conflicted") for r in all_observations + context.get("current_session_observations", [])):
            reasons.append("relevant_observation_conflicted")
        if not _completed(row):
            reasons.append("completed_work_set_with_positive_observed_repetitions_required")
        if row.get("deleted_at"):
            reasons.append("source_record_deleted")
        if not record.get("daily_comparability", {}).get("comparable"):
            reasons.extend(record.get("daily_comparability", {}).get("reason_codes") or ["daily_condition_not_comparable"])
        if not (row.get("ended_at") or row.get("started_at")):
            reasons.append("source_observation_time_unknown")
        if row.get("measurement_mode") != "repetitions":
            reasons.append("repetition_rule_not_applicable_to_measurement_mode")
        if target.get("load_unit") and target["load_unit"] != row.get("load_unit"):
            reasons.append("target_and_observation_load_units_differ")
        if strategy == "repetition_progression":
            pass  # Retains this actual load; no equipment-step arithmetic.
        elif context.get("equipment_load_unit") is None:
            reasons.append("explicit_equipment_step_unit_required")
        elif context["equipment_load_unit"] != row.get("load_unit"):
            reasons.append("equipment_and_observation_load_units_differ")
    plan = {"rep_upper": target.get("reps_max"), "next_target_reps": target.get("reps_min"),
            "target_rir_min": target.get("rir"), "target_rir_max": target.get("rir"), "available_loads": loads}
    code = 25 if strategy == "double_progression" else 26
    evaluated_context = {**context, "strategy": strategy, "progression_plan": plan if target else None,
        "reviewed_principles": authority["principles"], "allowed_trial_actions": [strategy] if code == 26 else []}

    def emit(value=None, status="valid", **extra):
        # Deliberately not MetricResult STR-25/26: different input-selection purpose.
        return {"business_rule_id": "DAILY-SET-OPTION", "algorithm_version": VERSION,
                "data_status": status, "value": value, "reason_codes": extra.pop("reasons", []),
                "candidate_applicability": check, **extra}

    metric = emit(None, "insufficient", reasons=reasons) if reasons else progression_candidate(
        code, [row], evaluated_context, check, emit, require_protocol=False)
    value = metric.get("value") or {}
    trial = value.get("task_trial") or {}
    load = value.get("next_load") if code == 25 else trial.get("load_value")
    reps = value.get("target_reps") if code == 25 else trial.get("reps_target")
    # Ordinary evidence must never acquire reference-set terminology or identity.
    for item in (value, trial):
        if "reference_set_id" in item:
            item["source_set_id"] = item.pop("reference_set_id")
    if "verification_task" in value:
        value["verification_task"] = "Record this optional target set, actual load, reps, RIR, quality and stop reason; stop or revise if unsuitable"
    source_id = row.get("set_uuid") if row else None
    used = [source_id] if row and not reasons else []
    excluded = [{"set_uuid": r.get("set_uuid"), "reason": "separate_observation_not_aggregated_for_this_single_set_option",
                 "applicability_checked": r in all_observations} for r in history["records"] if r.get("set_uuid") not in used]
    rule_list = [p for p in authority["principles"] if strategy in p.get("permitted_actions", [])]
    return {"strategy": strategy, "metric": metric, "load": load,
        "load_unit": (value.get("load_unit") if code == 25 else trial.get("load_unit")) if load is not None else None,
        "reps": reps, "rir": target.get("rir") if load is not None else None,
        "basis": {"rules": rule_list, "source_set_id": source_id, "source_observation": observation(record) if row else None,
            "source_set_ids": [r["set_uuid"] for r in history["records"]], "calculation_record_ids": used,
            "other_record_uses": excluded, "latest_session": history.get("latest_session"),
            "scope": "one_optional_set_trial_not_all_sets", "target_set_uuid": target_set_uuid,
            "weight_origin": "该普通实际组的记录负荷" if strategy == "repetition_progression" else "匹配行动规则许可的实际器械档位",
            "repetitions_origin": "沿用用户计划次数上限" if strategy == "repetition_progression" else "沿用用户计划次数下限",
            "rir_origin": "用户计划 RIR；未指定时保持未知", "plan": target, "available_loads": loads},
        "limitations": ["仅为此目标组的可选试验；各历史组分别核对，不能推出全场统一加重。",
            "历史表现是观察，不等于今天能力；未使用间隔衰减或安全重量公式。",
            "可自由保持或调整并记录；不推断采纳、拒绝或效果。"],
        "excluded_rules": authority.get("excluded", [])}


def decisions(history, groups):
    rows = []
    for record in history["records"]:
        options = [o for g in groups for o in g["options"] if o["basis"]["source_set_id"] == record["set_uuid"]]
        rows.append({"set_uuid": record["set_uuid"], "observation": observation(record),
            "uses": ["latest_session_fact", "restriction_check"] if not record.get("deleted_at") and
                (record.get("completion_state") in {"completed", "aborted", "failed", "in_progress"}
                 or record.get("started_at") or record.get("ended_at")) else ["latest_session_fact"],
            "evaluations": [{"target_set_uuid": o["basis"]["target_set_uuid"], "strategy": o["strategy"],
                "load": o["load"], "reps": o["reps"], "metric": o["metric"]} for o in options]})
    return {"version": VERSION, "input_record_ids": [r["set_uuid"] for r in history["records"]],
        "records": rows, "limitations": ["没有单一代表组，没有组间平均或最好成绩替代。",
        "现有规则提供单组可选试验，未授权整场处方、严格停滞或个人因果推断。"]}
