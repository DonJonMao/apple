"""User-selected candidate tasks and review, with immutable input snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import streamlit as st

from healthzip.analytics.v13 import snapshot
from healthzip.science import evaluate
from healthzip.training.semantics import numeric

STRATEGIES = {
    "double_progression": "按计划上沿核对双重进阶",
    "heavier_lower_reps": "选择更难档位、降低次数的可选试验",
    "repetition_progression": "讨论次数进阶试验",
    "discuss_sets": "讨论组数试验",
    "discuss_interval": "讨论训练间隔试验",
    "maintain_and_collect_reference": "维持计划并继续收集参考",
}
CHOICES = {"deferred": "暂缓", "accepted": "采纳", "declined": "不采纳", "modified": "修改后采用"}
EXECUTIONS = {"unknown": "尚未记录", "executed": "已执行", "partially_executed": "部分执行", "not_executed": "未执行"}
VERIFICATION = "在执行前指定参考组，记录实际重量、次数、RIR、动作质量与停止原因；不适合时可停止、改目标或结束动作。"


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


def _freeze_candidate(repo, svc, session, instance, effective, selected, available, strategy):
    from healthzip.knowledge import KnowledgeWorkbench

    now = datetime.now(timezone.utc)
    records, context = snapshot(repo, now.isoformat())
    condition_key = instance.get("condition_key")
    records = [r for r in records if condition_key and r.get("record_kind") == "strength_set"
               and r.get("condition_key") == condition_key and r.get("session_id") != session["id"]
               and r.get("completion_state") == "completed" and r.get("ended_at")]
    records.sort(key=lambda r: datetime.fromisoformat(r["ended_at"].replace("Z", "+00:00")))
    target = selected["target"] if selected else {}
    plan = {"rep_upper": target.get("reps_max"), "target_rir_min": target.get("rir"),
            "target_rir_max": target.get("rir"), "available_loads": available,
            "next_target_reps": target.get("reps_min")}
    if any(plan[k] is None for k in ("rep_upper", "target_rir_min", "target_rir_max", "next_target_reps")):
        plan = None
    parameters = _register_parameters(repo, instance, plan, available, strategy)
    knowledge = KnowledgeWorkbench(".local/knowledge")
    try:
        authority = knowledge.reviewed_principles("progression", instance["condition"])
    finally:
        knowledge.close()
    metric_id = "STR-25" if strategy == "double_progression" else "STR-26"
    metric = evaluate(metric_id, records, cutoff_time=now.isoformat(),
                      window_start=(now - timedelta(days=365)).isoformat(), window_end=now.isoformat(),
                      context={**context, "progression_plan": plan, "reviewed_principles": authority["principles"],
                               "allowed_trial_actions": [strategy] if metric_id == "STR-26" else [],
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
        "followup_window": "本次所选动作的候选创建后执行记录；结束后可在历史中复核",
        "rule_version": metric["algorithm_version"], "user_choice": None,
    }
    frozen = {
        "source_record_ids": [r.get("set_uuid") or r["raw_id"] for r in records], "metric_result": metric,
        "plan_snapshot": {"sets": [target] if target else []}, "original_plan_snapshot": instance.get("planned"),
        "effective_targets_snapshot": effective, "selected_target": selected,
        "reference_set_id": reference.get("reference_set_id"),
        "condition": instance["condition"], "theory_authority": authority, "strategy": strategy,
        "session_exercise_id": instance["id"], "parameter_manifest": parameters,
    }
    return svc.record_recommendation(
        candidate, frozen, cutoff_time=now.isoformat(),
        theory_version=str(authority.get("source_release") or authority.get("review_snapshot_sha256") or "none_reviewed_for_numerical_action"),
    )


def _create_form(repo, svc, session, instance, key):
    effective = svc.current_targets(instance["id"])
    targets = effective["sets"]
    by_id = {x["set_uuid"]: x for x in targets}
    selected = None
    if by_id:
        chosen = st.selectbox("本次依据的组目标", list(by_id), key="candidate_target_" + key,
                              format_func=lambda sid: f"第 {list(by_id).index(sid) + 1} 组 · {by_id[sid]['target']}")
        selected = by_id[chosen]
    else:
        st.info("尚无逐组目标。可新增一组并填写目标；仍可保存当前缺项。")
    strategy = st.selectbox("本次候选策略", list(STRATEGIES), format_func=STRATEGIES.get, key="strategy_" + key)
    if strategy != "double_progression":
        st.caption("这是你选择的可选试验，未达到次数上沿也可核对依据。它不代表已诊断停滞，也不保证有效。")
    loads = st.text_input("本台器械实际可用重量 / 刻度（逗号分隔，与记录单位一致）", key="loads_" + key)
    if st.button("核对候选依据并保存", key="candidate_" + key):
        try:
            available = [numeric(x.strip(), "器械档位") for x in loads.split(",") if x.strip()]
            if any(x is None or x < 0 for x in available):
                raise ValueError("器械档位须为非负有限数字")
            _freeze_candidate(repo, svc, session, instance, effective, selected, available, strategy)
            st.success("已保存当前目标、策略、审核依据与缺项；采纳和执行单独记录。")
        except ValueError as exc:
            st.error(str(exc))


def _render_feedback(repo, svc, instance, record, prefix):
    candidate = record["candidate"]
    cid = candidate["candidate_id"]
    st.write("候选 / 缺项", candidate["action_kind"], candidate["eligibility"])
    if candidate.get("proposed_change", {}).get("load") is not None:
        st.write("待选择的任务", candidate["proposed_change"], candidate["target_range"])
    st.caption(candidate["verification_protocol"])
    authority = record["input_snapshot"].get("theory_authority", {})
    st.caption(f"当时适用的候选审核依据：{len(authority.get('principles', []))} 项。数值候选不代表个人有效性已验证。")
    with st.expander("查看冻结依据", expanded=False):
        st.json(record["input_snapshot"])
    latest = record["feedback"][-1] if record["feedback"] else {}
    last_id = latest.get("event_id")
    revision_key = prefix + "feedback_loaded_" + cid
    choice_key, execution_key, reason_key = (prefix + stem + cid for stem in ("choice_", "execution_", "reason_"))
    record_key = prefix + "actual_records_" + cid
    actual = {r["set_uuid"]: r for r in instance["sets"]
              if r.get("completion_state") in {"completed", "aborted"} and not r.get("deleted_at")}
    if revision_key not in st.session_state or st.session_state[revision_key] != last_id:
        st.session_state[revision_key] = last_id
        st.session_state[choice_key] = latest.get("user_choice") or "deferred"
        st.session_state[execution_key] = latest.get("execution_state") or "unknown"
        st.session_state[reason_key] = latest.get("outcome", {}).get("user_note", "")
        selected = record["input_snapshot"].get("selected_target") or {}
        defaults = latest.get("actual_record_ids", [selected.get("set_uuid")])
        st.session_state[record_key] = [sid for sid in defaults if sid in actual]
    # A later correction/deletion may remove a previously selected actual group.
    st.session_state[record_key] = [sid for sid in st.session_state.get(record_key, []) if sid in actual]
    choice = st.selectbox("我的选择", list(CHOICES), format_func=CHOICES.get, key=choice_key)
    execution = st.selectbox("实际执行", list(EXECUTIONS), format_func=EXECUTIONS.get, key=execution_key)
    selected_ids = st.multiselect("用于复核的实际组", list(actual), key=record_key,
                                 format_func=lambda sid: f"第 {actual[sid].get('set_number')} 组 · {actual[sid].get('load_value')} × {actual[sid].get('reps')}")
    reason = st.text_input("未执行原因 / 后续结果", key=reason_key)
    if st.button("保存选择与执行反馈", key=prefix + "feedback_" + cid):
        try:
            if execution in {"executed", "partially_executed"} and not selected_ids:
                raise ValueError("请选取实际组用于复核；尚未记录时将执行状态保留为尚未记录。")
            svc.recommendation_feedback(
                cid, user_choice=choice, execution_state=execution, nonexecution_reason=reason or "unknown",
                outcome={"user_note": reason},
                actual_record_ids=selected_ids if execution in {"executed", "partially_executed"} else [],
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if latest:
        st.caption("最近反馈：" + str(latest.get("recorded_at")))
        now = datetime.now(timezone.utc)
        _, context = snapshot(repo, now.isoformat())
        outcome = next((r for r in context["recommendation_outcomes"] if r["recommendation_id"] == cid), None)
        if outcome:
            metric = evaluate("STR-27", [], cutoff_time=now.isoformat(),
                              window_start=(now - timedelta(days=365)).isoformat(), window_end=now.isoformat(),
                              context={"recommendation_outcomes": [outcome]})
            values = metric.get("value") or []
            success = values[0].get("short_term_success") if values else None
            st.write("冻结任务复核：" + ("已满足记录的目标" if success is True else "未满足记录的目标" if success is False else "尚不能判断：需要候选之后的有效参考组、完整目标与执行反馈"))
            st.caption("任务完成与否不证明试验导致进步；历史记录更正后按当前事实重新核对，冻结依据保留。")


def render_candidates(repo, svc, session, instance, *, allow_create=True, key_prefix=""):
    key = key_prefix + instance["id"]
    with st.expander("本次候选与后续复核"):
        st.caption("可选改变来自明确计划和可比记录；未满足依据时保留缺项。采纳不会自动修改模板。")
        if allow_create and not instance.get("replaced_by_instance_id"):
            _create_form(repo, svc, session, instance, key)
        candidates = [record for record in svc.list_recommendations()
                      if record.get("target_session") == session["session_uuid"]
                      and record["input_snapshot"].get("session_exercise_id") == instance["id"]]
        if not allow_create and not candidates:
            st.caption("此动作没有已冻结候选。")
        for record in candidates:
            _render_feedback(repo, svc, instance, record, key_prefix)
