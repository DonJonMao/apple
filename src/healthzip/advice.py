"""Private, versioned advice inputs shared by UI and programmatic callers."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from healthzip.analytics.v13 import snapshot
from healthzip.science import evaluate
from healthzip.science.contracts import canonical_hash, finite, instant
from healthzip.science.semantics import analysis_task, flatten_record
from healthzip.training.service import TrainingService

VERIFICATION = "在执行前指定参考组，记录实际重量、次数、RIR、动作质量与停止原因；不适合时可停止、改目标或结束动作。"
PROFILE_FIELDS = {"age", "training_goal", "training_experience", "health_scope"}


def migrate_advice(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS advice_profile_revision (
        revision INTEGER PRIMARY KEY, user_id TEXT NOT NULL, fields_json TEXT NOT NULL,
        provenance_json TEXT NOT NULL, recorded_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS recommendation_use_event (
        event_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, status TEXT NOT NULL,
        reasons_json TEXT NOT NULL, input_signature TEXT NOT NULL, recorded_at TEXT NOT NULL,
        UNIQUE(candidate_id,input_signature))""")
    conn.execute("INSERT OR IGNORE INTO schema_meta(key,value) VALUES('advice_profile_version','0')")


def profile(repo, user_id="local", *, cutoff_time=None):
    # Compare parsed instants, including microseconds and offsets, rather than
    # allowing a later profile revision to change a historical decision.
    rows = repo.conn.execute("SELECT * FROM advice_profile_revision WHERE user_id=? ORDER BY revision DESC", (user_id,))
    cutoff = instant(cutoff_time) if cutoff_time else None
    row = next((r for r in rows if cutoff is None or instant(r["recorded_at"]) <= cutoff), None)
    if not row:
        return {"revision": None, "fields": {}, "provenance": {}}
    return {"revision": row["revision"], "fields": json.loads(row["fields_json"]),
            "provenance": json.loads(row["provenance_json"]), "recorded_at": row["recorded_at"]}


def save_profile(repo, fields, *, user_id="local"):
    if set(fields) - PROFILE_FIELDS:
        raise ValueError("用户适用信息包含未支持字段")
    fields = {key: None if value in (None, "", "unknown") else value for key, value in fields.items()}
    age = fields.get("age")
    if age is not None and (isinstance(age, bool) or not isinstance(age, (int, float)) or not math.isfinite(age) or age < 0):
        raise ValueError("年龄须为非负数或未知")
    now = datetime.now(timezone.utc).isoformat()
    provenance = {key: {"kind": "user_self_report", "recorded_at": now, "professionally_verified": False}
                  for key, value in fields.items() if value is not None}
    repo.conn.execute("INSERT INTO advice_profile_revision(user_id,fields_json,provenance_json,recorded_at) VALUES(?,?,?,?)",
                      (user_id, json.dumps(fields, ensure_ascii=False), json.dumps(provenance, ensure_ascii=False), now))
    repo.conn.execute("UPDATE schema_meta SET value=CAST(value AS INTEGER)+1 WHERE key='advice_profile_version'")
    repo.conn.commit()
    return profile(repo, user_id)


def build_advice_context(repo, session_id, session_exercise_id, selected_set_uuid, available_loads,
                         strategy, *, cutoff_time=None, timezone_name="Asia/Shanghai"):
    """Derive actual task fields; callers cannot remove them to widen scope."""
    svc = TrainingService(repo)
    session = svc.get_session(session_id)
    instance = svc.get_session_exercise(session_exercise_id)
    if instance["session_id"] != session["id"]:
        raise ValueError("所选动作不属于当前展示的训练")
    effective = svc.current_targets(session_exercise_id)
    selected = next((s for s in effective["sets"] if s["set_uuid"] == selected_set_uuid), None)
    if selected_set_uuid and selected is None:
        raise ValueError("所选目标已删除或不属于当前动作")
    cutoff = instant(cutoff_time) if cutoff_time else datetime.now(timezone.utc)
    records, inherited = snapshot(repo, cutoff.isoformat(), include_sources=False)
    key = instance.get("condition_key")
    baseline, current = [], []
    for raw in records:
        if raw.get("record_kind") != "strength_set":
            continue
        row = flatten_record(raw)
        end = row.get("ended_at") or row.get("started_at")
        if end and instant(end) > cutoff:
            continue
        if row.get("session_id") == session["id"]:
            if (row.get("session_exercise_id") == instance["id"]
                    and row.get("completion_state") in {"completed", "aborted", "in_progress"}):
                # Preserve observed symptoms even when their set endpoints are
                # unknown. The science gate must see that missing time; neither
                # dropping this row nor borrowing the session time is valid.
                current.append(raw)
        elif row.get("ended_at") and key and row.get("condition_key") == key and row.get("completion_state") == "completed":
            baseline.append(raw)
    baseline.sort(key=lambda r: instant(r["ended_at"]))
    current.sort(key=lambda r: instant(r.get("ended_at") or r["started_at"]).isoformat()
                 if r.get("ended_at") or r.get("started_at") else "")
    task_row = {**instance["condition"], "exercise_id": instance["catalog_id"],
                "definition_version": instance["definition_version"], "user_id": svc.user_id,
                "set_number": next((s["set_number"] for s in instance["sets"] if selected and s["set_uuid"] == selected["set_uuid"]), None)}
    task = analysis_task(task_row)
    from healthzip.science.semantics import outcome_series
    from healthzip.science.strength import reference_rows
    references = reference_rows([{**flatten_record(r), "_event_end": r["ended_at"]} for r in baseline], {})
    series = outcome_series(references[-1]) if references else None
    if references:
        task = analysis_task(references[-1])
    personal = profile(repo, svc.user_id, cutoff_time=cutoff.isoformat())
    context = {**inherited, **personal["fields"], **instance["condition"],
               "advice_context_version": "1.4.0", "as_of": cutoff.isoformat(), "timezone": timezone_name,
               "task_id": task["task_id"], "selected_set_uuid": selected_set_uuid,
               "outcome_series_id": series["outcome_series_id"] if series else None,
               "target_version": effective["revision"], "definition_version": instance["definition_version"],
               "exercise_id": instance["catalog_id"], "strategy": strategy, "available_loads": list(available_loads),
               "profile_revision": personal["revision"], "profile_provenance": personal["provenance"],
               "baseline_record_ids": [r["set_uuid"] for r in baseline],
               "current_session_record_ids": [r["set_uuid"] for r in current],
               "unknown_current_observation_ids": [r["set_uuid"] for r in current
                   if not (r.get("ended_at") or r.get("started_at"))],
               "current_session_observations": current,
               "user_choice": "requested_strategy_review", "protocol": task["protocol"]}
    return {"records": baseline, "context": context, "session": session, "instance": instance,
            "effective_targets": effective, "selected_target": selected}


def current_use_status(repo, record):
    """Append a current-use decision while leaving the candidate snapshot intact."""
    from healthzip.knowledge import KnowledgeWorkbench
    from healthzip.science.applicability import candidate_applicability

    svc = TrainingService(repo)
    record = next((r for r in svc.list_recommendations() if r["candidate_id"] == record["candidate_id"]), None)
    if record is None:
        raise ValueError("候选不存在或不属于当前用户")
    frozen = record["input_snapshot"]
    instance = svc.get_session_exercise(frozen["session_exercise_id"])
    advice = build_advice_context(repo, instance["session_id"], instance["id"], None, [], frozen.get("strategy"))
    reference_id = frozen.get("reference_set_id")
    reference = next((r for r in advice["records"] if r.get("set_uuid") == reference_id), None)
    check = candidate_applicability(reference, advice["context"]["current_session_observations"])
    discussion = record["candidate"].get("discussion")
    reasons = list(check["reason_codes"]) if check["applicable"] is not True and not discussion else []
    if advice["context"]["unknown_current_observation_ids"]:
        if not discussion:
            reasons.append("current_observation_time_or_availability_unknown")
        check["reason_codes"].append("current_observation_time_or_availability_unknown")
        if check["applicable"] is not False:
            check.update(applicable=None, status="unknown")
    workbench = KnowledgeWorkbench(".local/knowledge")
    try:
        authority = workbench.reviewed_principles("progression", advice["context"])
        if discussion:
            from healthzip.discussion import dependencies, explanation
            current_explanation = explanation(workbench, discussion["strategy"], advice["context"])
            old_dependencies = dependencies(discussion["source_explanation"])
            if (current_explanation["answer_status"] != "answered_with_support"
                    or not old_dependencies or old_dependencies - dependencies(current_explanation)):
                reasons.append("frozen_explanation_dependencies_no_longer_current")
    finally:
        workbench.close()
    active = {(p.get("rule_id", p.get("theory_id")), str(p.get("version"))) for p in authority["principles"]}
    old = {(p.get("rule_id", p.get("theory_id")), str(p.get("version"))) for p in frozen.get("theory_authority", {}).get("principles", [])}
    missing_authority = bool(old - active)
    if missing_authority:
        reasons.append("frozen_rule_dependencies_no_longer_current")
    if record.get("stale"):
        reasons.append("input_records_changed_since_freeze")
    status = "review_required" if reasons else "active"
    decision = {"status": status, "reason_codes": sorted(set(reasons)), "applicability": check,
                "authority_snapshot": authority.get("review_snapshot_sha256"),
                "data_version": svc.data_version(), "profile_revision": advice["context"]["profile_revision"]}
    signature = canonical_hash(decision)
    repo.conn.execute("INSERT OR IGNORE INTO recommendation_use_event VALUES(?,?,?,?,?,?)",
        (str(uuid4()), record["candidate_id"], status, json.dumps(decision, ensure_ascii=False), signature,
         datetime.now(timezone.utc).isoformat()))
    repo.conn.commit()
    return decision


def modify_candidate(repo, record, proposed_load, target_range):
    """Freeze a separately validated user choice; never rewrite the old task."""
    from copy import deepcopy

    svc = TrainingService(repo)
    record = next((r for r in svc.list_recommendations() if r["candidate_id"] == record["candidate_id"]), None)
    if record is None:
        raise ValueError("候选不存在或不属于当前用户")
    if record["candidate"].get("discussion"):
        raise ValueError("一般讨论没有可修改的数值任务；请先编辑计划并另行核对候选依据")
    state = current_use_status(repo, record)
    if state["status"] != "active":
        raise ValueError("当前依据或记录需要重新核对，请先生成适用的候选")
    frozen = deepcopy(record["input_snapshot"])
    available = frozen.get("advice_context", {}).get("available_loads", [])
    if (isinstance(proposed_load, bool) or not isinstance(proposed_load, (int, float))
            or not math.isfinite(proposed_load) or proposed_load < 0 or proposed_load not in available):
        raise ValueError("修改重量必须是已确认的本台器械可用档位")
    for measure in ("reps", "duration_s", "distance_m", "rir"):
        low, high = target_range.get(measure + "_min"), target_range.get(measure + "_max")
        if low is None and high is None:
            continue
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 for x in (low, high)) or low > high:
            raise ValueError("修改目标须为完整、非负且有序的范围")
        if measure == "reps" and (int(low) != low or int(high) != high or low <= 0):
            raise ValueError("次数须为正整数")
        if measure == "rir" and high > 10:
            raise ValueError("RIR须在本记录量表的0–10范围内")
    original = record["candidate"]
    original_targets = original.get("target_range", {})
    if set(target_range) != set(original_targets) or any(
            value is not None and target_range.get(key) is None for key, value in original_targets.items()):
        raise ValueError("修改必须保留原任务的测量终点，不能切换动作模式或删除目标")
    if not target_range or not any(key.endswith("_min") and value is not None for key, value in target_range.items()):
        raise ValueError("修改任务须保留可核对的目标")
    # A choice modification stays within the already confirmed plan. To widen
    # that plan, the user edits its targets and requests a fresh candidate.
    selected = frozen.get("selected_target") or {}
    plan_target = selected.get("target", {})
    low, high = target_range.get("reps_min"), target_range.get("reps_max")
    if (low is None or high is None or plan_target.get("reps_min") is None
            or plan_target.get("reps_max") is None
            or low < plan_target["reps_min"] or high > plan_target["reps_max"]):
        raise ValueError("修改次数须在已确认的组目标范围内；扩大目标请先修改计划并重新核对")
    if target_range.get("rir_min") != original_targets.get("rir_min") or target_range.get("rir_max") != original_targets.get("rir_max"):
        raise ValueError("修改余力目标请先修改计划并重新核对依据")
    instance = svc.get_session_exercise(frozen["session_exercise_id"])
    advice = build_advice_context(repo, instance["session_id"], instance["id"], None, available, frozen.get("strategy"))
    reference = next((flatten_record(r) for r in advice["records"] if r.get("set_uuid") == frozen.get("reference_set_id")), None)
    if reference is None:
        raise ValueError("原参考组已不可用，请重新核对候选")
    strategy = frozen.get("strategy")
    from healthzip.science.semantics import load_basis, load_change
    current_load, reference_reps = finite(reference.get("load_value")), finite(reference.get("reps"))
    if current_load is None or reference_reps is None:
        raise ValueError("参考负荷或次数不完整，请重新核对候选")
    if strategy == "repetition_progression":
        if proposed_load != current_load or low <= reference_reps:
            raise ValueError("次数进阶必须保持参考负荷，且次数目标高于参考观察")
    elif strategy in {"heavier_lower_reps", "double_progression"}:
        harder = proposed_load < current_load if load_basis(reference) == "assistance_setting" else proposed_load > current_load
        if not harder or strategy == "heavier_lower_reps" and high >= reference_reps:
            raise ValueError("该策略须使用更难的可用档位；增重降次数试验还须低于参考次数")
    else:
        raise ValueError("当前策略没有可修改的数值任务")
    candidate = deepcopy(original)
    candidate["candidate_id"] = str(uuid4())
    candidate["parent_candidate_id"] = record["candidate_id"]
    candidate["proposed_change"]["load"] = proposed_load
    candidate["proposed_change"]["changes"] = load_change(reference, {**reference, "load_value": proposed_load, "entered_load": proposed_load})
    candidate["target_range"] = deepcopy(target_range)
    candidate["user_choice"] = "modified"
    candidate["eligibility"] = list(candidate["eligibility"]) + ["user_modified_task_within_confirmed_equipment"]
    frozen["choice_modification"] = {"parent_candidate_id": record["candidate_id"], "proposed_load": proposed_load,
                                     "target_range": target_range, "source_kind": "user_target"}
    frozen["choice_validation"] = {"version": "user-choice-validation-1.4.0", "strategy": strategy,
                                    "within_confirmed_plan": True, "current_use": state,
                                    "algorithm_output_is_parent_task": True,
                                    "reference_set_id": frozen.get("reference_set_id")}
    frozen["numeric_provenance"] = [
        {"field": "proposed_change.load", "kind": "equipment_step", "value": proposed_load,
         "unit": candidate["proposed_change"].get("load_unit"), "source": available},
        {"field": "target_range", "kind": "user_target", "value": target_range, "source": "explicit_choice_modification"}]
    now = datetime.now(timezone.utc).isoformat()
    return svc.record_recommendation(candidate, frozen, cutoff_time=now, theory_version=record["theory_version"])


def _register_parameters(repo, instance, plan, available, strategy):
    from healthzip.science.registry import ParameterRegistry

    if repo.conn.in_transaction:
        raise ValueError("请先保存当前编辑，再核对候选依据。")
    registry = ParameterRegistry(str(repo.path))
    try:
        parameters = []
        for kind, value, unit in (
            ("user_plan", {"plan": plan, "strategy": strategy}, "declared_task"),
            ("equipment_constraint", available, "recorded_load_unit"),
        ):
            digest = hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()
            parameters.append(registry.register({
                "parameter_id": f"{kind}:{instance['id']}", "version": digest,
                "kind": kind, "definition": "用户计划与策略" if kind == "user_plan" else "用户确认本台器械可用档位",
                "value_or_distribution": value, "unit": unit,
                "provenance": {"basis": "user_declared", "source_ids": [], "source_location": "training_candidate_form"},
                "scope": {"session_exercise_id": instance["id"], "condition_key": instance.get("condition_key")},
                "validation_status": "user_declared",
            }))
        return parameters
    finally:
        registry.close()


def freeze_candidate(repo, svc, session, instance, effective, selected, available, strategy, *, timezone_name="Asia/Shanghai", followup_window=None, available_minutes=None):
    from healthzip.knowledge import KnowledgeWorkbench
    from healthzip.training.followup import freeze_window

    advice = build_advice_context(repo, session["id"], instance["id"],
                                  selected["set_uuid"] if selected else None, available, strategy, timezone_name=timezone_name)
    if advice["effective_targets"]["revision"] != effective["revision"]:
        raise ValueError("逐组目标已变化，请重新加载后核对候选")
    records, context = advice["records"], advice["context"]
    selected = advice["selected_target"]
    now = instant(context["as_of"])
    target = selected["target"] if selected else {}
    plan = {"rep_upper": target.get("reps_max"), "target_rir_min": target.get("rir"),
            "target_rir_max": target.get("rir"), "available_loads": available,
            "next_target_reps": target.get("reps_min")}
    if not target:
        plan = None
    parameters = _register_parameters(repo, instance, plan, available, strategy)
    knowledge = KnowledgeWorkbench(".local/knowledge")
    discussion = None
    try:
        authority = knowledge.reviewed_principles("progression", context)
        from healthzip.discussion import TOPICS, build_discussion
        if strategy in TOPICS:
            discussion = build_discussion(knowledge, advice, strategy, available_minutes)
            # Numerical candidate permissions never derive from explanation claims.
            authority = {**authority, "principles": []}
    finally:
        knowledge.close()
    metric_id = "STR-25" if strategy == "double_progression" else "STR-26"
    metric = evaluate(metric_id, records, cutoff_time=now.isoformat(),
                      window_start=(now - timedelta(days=365)).isoformat(), window_end=now.isoformat(),
                      context={**context, "progression_plan": plan, "reviewed_principles": authority["principles"],
                               "allowed_trial_actions": [strategy] if metric_id == "STR-26" else [],
                               "reviewed_discussion": discussion,
                               "verification_task": VERIFICATION})
    metric["parameter_set_id"] = parameters[0]["parameter_id"] + "@" + parameters[0]["version"]
    metric["parameters_used"] = [{"parameter_id": p["parameter_id"], "version": p["version"], "kind": p["kind"]} for p in parameters]
    value = metric.get("value") or {}
    trial = value.get("task_trial") or {}
    load = value.get("next_load") if metric_id == "STR-25" else trial.get("load_value")
    reference = value if metric_id == "STR-25" else trial
    action = (value.get("candidate") if metric_id == "STR-25" else strategy) if load is not None else "collect_or_confirm_evidence"
    if metric_id == "STR-26" and load is None and strategy in value.get("candidates", []):
        action = strategy  # Discussion/observation tasks have no numerical success target.
    reps = value.get("target_reps") if metric_id == "STR-25" else trial.get("reps_target")
    target_range = {"reps_min": reps, "reps_max": reps, "rir_min": target.get("rir"), "rir_max": target.get("rir")} if load is not None else {}
    candidate = {
        "candidate_id": str(uuid4()), "target_session": session["session_uuid"], "action_kind": action,
        "proposed_change": {"load": load, "load_unit": reference.get("load_unit"),
                            "load_basis": instance["condition"].get("load_basis"), "changes": trial.get("changes", value.get("changes"))},
        "target_range": target_range, "reason_evidence_ids": [metric_id], "eligibility": metric["reason_codes"],
        "uncertainty": metric["uncertainty"], "verification_protocol": VERIFICATION,
        "followup_window": freeze_window(followup_window, declared_at=now.isoformat()),
        "rule_version": metric["algorithm_version"], "user_choice": None,
    }
    if discussion:
        discussion["numeric_action_limitations"] = metric["candidate_applicability"]["reason_codes"]
        candidate["discussion"] = discussion
        candidate["verification_protocol"] = "保存你的讨论选择、计划调整与理由；后续实际训练另行记录。一般讨论没有数值成功目标。"
    frozen = {
        # Known-time numerical sources retain the persistence time checks.
        # Undated current facts are separately identified audit evidence, with
        # original fields preserved in advice_context, never dated by inference.
        "source_record_ids": context["baseline_record_ids"] + [identity for identity in context["current_session_record_ids"]
            if identity not in context["unknown_current_observation_ids"]],
        "unknown_current_observation_ids": context["unknown_current_observation_ids"], "metric_result": metric,
        "advice_context": context, "numeric_provenance": [
            {"field": "proposed_change.load", "kind": "observed" if strategy == "repetition_progression" else "equipment_step",
             "value": load, "unit": reference.get("load_unit"),
             "source": reference.get("reference_set_id") if strategy == "repetition_progression" else parameters[1]},
            {"field": "target_range.reps", "kind": "user_target", "unit": "repetitions", "source": selected}],
        "plan_snapshot": {"sets": [target] if target else []}, "original_plan_snapshot": instance.get("planned"),
        "effective_targets_snapshot": effective, "selected_target": selected,
        "reference_set_id": reference.get("reference_set_id"),
        "condition": instance["condition"], "theory_authority": authority, "strategy": strategy,
        "session_exercise_id": instance["id"], "parameter_manifest": parameters,
    }
    if discussion:
        frozen["discussion_explanation"] = discussion["source_explanation"]
        frozen["numeric_provenance"] = []
    return svc.record_recommendation(
        candidate, frozen, cutoff_time=now.isoformat(),
        theory_version=str(authority.get("source_release") or authority.get("review_snapshot_sha256") or "none_reviewed_for_numerical_action"),
    )


def main():
    """Local CLI uses exactly the same context and freeze service as the UI."""
    import argparse
    from pathlib import Path

    from healthzip.db.repository import Repository

    parser = argparse.ArgumentParser(description="本机训练任务核对；默认只输出上下文，--freeze才冻结候选")
    parser.add_argument("--db", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--exercise-instance", required=True)
    parser.add_argument("--set-uuid")
    parser.add_argument("--strategy", default="double_progression")
    parser.add_argument("--available-loads", default="")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--available-minutes", type=float, help="用户声明的讨论时间约束；不产生数值训练处方")
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    from healthzip.training.semantics import numeric
    loads = [numeric(x.strip(), "器械档位") for x in args.available_loads.split(",") if x.strip()]
    if any(x is None or x < 0 for x in loads):
        parser.error("器械档位须为非负有限值")
    repo = Repository(args.db)
    try:
        session_id = int(args.session_id) if args.session_id.isdigit() else args.session_id
        advice = build_advice_context(repo, session_id, args.exercise_instance, args.set_uuid,
                                      loads, args.strategy, timezone_name=args.timezone)
        output = freeze_candidate(repo, TrainingService(repo), advice["session"], advice["instance"],
                                  advice["effective_targets"], advice["selected_target"], loads, args.strategy,
                                  timezone_name=args.timezone, available_minutes=args.available_minutes) if args.freeze else advice
        rendered = json.dumps(output, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(rendered + "\n")
        else:
            print(rendered)
    finally:
        repo.close()


if __name__ == "__main__":
    main()
