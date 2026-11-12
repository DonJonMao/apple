"""User-selected candidate tasks and review, with immutable input snapshots."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def _freeze_candidate(repo, svc, session, instance, effective, selected, available, strategy, *, followup_window=None, available_minutes=None):
    from healthzip.advice import freeze_candidate
    return freeze_candidate(repo, svc, session, instance, effective, selected, available, strategy,
                            timezone_name=st.session_state.get("analysis_timezone", "Asia/Shanghai"),
                            followup_window=followup_window, available_minutes=available_minutes)


def _create_form(repo, svc, session, instance, key):
    from healthzip.advice import profile, save_profile

    personal = profile(repo, svc.user_id)
    fields = personal["fields"]
    with st.expander("建议适用信息（保存在本机，可留未知）"):
        st.caption("这些是你的自报信息，用于核对来源适用范围；填写不等于医疗评估或专业审核。")
        age_text = st.text_input("年龄（可留空）", value=str(fields.get("age") or ""), key="advice_age_" + key)
        choices = {
            "training_goal": ("训练目标", {"unknown": "尚未明确", "strength": "力量表现", "hypertrophy": "肌肉增长", "general_fitness": "一般体能"}),
            "training_experience": ("力量训练经验", {"unknown": "尚未记录", "novice": "新手", "experienced": "有训练经验"}),
            "health_scope": ("健康适用范围自报", {"unknown": "尚未确认", "healthy_adult_self_reported": "自报一般健康成人", "clinical_or_rehabilitation": "有疾病或康复相关限制"}),
        }
        entered = {}
        for name, (label, options) in choices.items():
            current = fields.get(name) or "unknown"
            entered[name] = st.selectbox(label, list(options), index=list(options).index(current) if current in options else 0,
                                         format_func=options.get, key="advice_profile_" + name + "_" + key)
        if st.button("保存适用信息", key="advice_profile_save_" + key):
            try:
                entered["age"] = numeric(age_text, "年龄") if age_text.strip() else None
                save_profile(repo, entered, user_id=svc.user_id)
                st.success("已保存自报范围及版本；未确认信息保持未知。")
            except ValueError as exc:
                st.error(str(exc))
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
    discussion_minutes = ""
    if strategy in {"discuss_sets", "discuss_interval"}:
        st.caption("讨论将展示已核对的一般原则、明确计划和同条件记录。它不能确定个人最佳组数或恢复间隔。")
        discussion_minutes = st.text_input("本次可用训练时间（分钟，可留空）", key="discussion_minutes_" + key)
    followup_window = None
    with st.expander("可选：预先约定后续观察窗口"):
        st.caption("按你的计划选择起止时间。报告将寻找窗口内后续场次的同条件、同负荷参考组；不会把变化归因为本次策略。未约定时只复核本次执行。")
        enabled = st.checkbox("为这个候选约定后续观察窗口", key="followup_enabled_" + key)
        if enabled:
            start = st.text_input("观察起点（含时区，如 2026-12-01T08:00:00+08:00）", key="followup_start_" + key)
            end = st.text_input("观察终点（不含该时刻；须晚于起点）", key="followup_end_" + key)
            followup_window = {"start": start, "end": end, "timezone": st.session_state.get("analysis_timezone", "Asia/Shanghai")}
    if st.button("核对候选依据并保存", key="candidate_" + key):
        try:
            available = [numeric(x.strip(), "器械档位") for x in loads.split(",") if x.strip()]
            if any(x is None or x < 0 for x in available):
                raise ValueError("器械档位须为非负有限数字")
            _freeze_candidate(repo, svc, session, instance, effective, selected, available, strategy,
                              followup_window=followup_window,
                              available_minutes=numeric(discussion_minutes, "可用训练时间") if discussion_minutes.strip() else None)
            st.success("已保存当前目标、策略、审核依据与缺项；采纳和执行单独记录。")
        except ValueError as exc:
            st.error(str(exc))


def _render_feedback(repo, svc, instance, record, prefix):
    from healthzip.advice import current_use_status

    candidate = record["candidate"]
    cid = candidate["candidate_id"]
    current_status = current_use_status(repo, record)
    if current_status["status"] == "review_required":
        st.warning("当前使用需重新核对：" + "；".join(current_status["reason_codes"]))
        st.caption("原候选及当时依据保持不变；新的观察、目标或知识状态单独留有复核记录。")
    st.write("候选 / 缺项", candidate["action_kind"], candidate["eligibility"])
    if candidate.get("proposed_change", {}).get("load") is not None:
        st.write("待选择的任务", candidate["proposed_change"], candidate["target_range"])
    if candidate.get("discussion"):
        _render_discussion(candidate["discussion"])
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
    modified = None
    if choice == "modified":
        proposed = candidate.get("proposed_change", {}).get("load")
        if proposed is not None:
            st.caption("修改将冻结为独立任务；须仍符合当前依据、测量模式与已确认器械档位，原候选保留。")
            changed_load = st.number_input("修改后的重量 / 刻度", value=float(proposed), min_value=0.0, key=prefix + "modified_load_" + cid)
            changed_targets = dict(candidate.get("target_range", {}))
            for name, value in list(changed_targets.items()):
                if value is not None:
                    changed_targets[name] = st.number_input("修改目标 " + name, value=float(value), min_value=0.0,
                                                          key=prefix + "modified_" + name + "_" + cid)
            modified = (changed_load, changed_targets)
        else:
            st.info("当前只有缺项或讨论任务，请先补充条件并核对新的任务。")
    execution = st.selectbox("实际执行", list(EXECUTIONS), format_func=EXECUTIONS.get, key=execution_key)
    selected_ids = st.multiselect("用于复核的实际组", list(actual), key=record_key,
                                 format_func=lambda sid: f"第 {actual[sid].get('set_number')} 组 · {actual[sid].get('load_value')} × {actual[sid].get('reps')}")
    reason = st.text_input("未执行原因 / 后续结果", key=reason_key)
    if st.button("保存选择与执行反馈", key=prefix + "feedback_" + cid):
        try:
            feedback_id = cid
            if choice == "modified":
                if modified is None:
                    raise ValueError("没有可核对的数值任务可修改")
                if execution != "unknown":
                    raise ValueError("新修改任务先保存为尚未记录，再记录其后的实际执行")
                from healthzip.advice import modify_candidate
                revised = modify_candidate(repo, record, *modified)
                feedback_id = revised["candidate_id"]
            if execution in {"executed", "partially_executed"} and not selected_ids:
                raise ValueError("请选取实际组用于复核；尚未记录时将执行状态保留为尚未记录。")
            svc.recommendation_feedback(
                feedback_id, user_choice=choice, execution_state=execution, nonexecution_reason=reason or "unknown",
                outcome={"user_note": reason},
                actual_record_ids=selected_ids if execution in {"executed", "partially_executed"} else [],
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if latest:
        st.caption("最近反馈：" + str(latest.get("recorded_at")))
        if candidate.get("discussion"):
            st.info("已记录讨论选择与反馈；一般讨论没有可判定的数值成功目标。")
            return
        now = datetime.now(timezone.utc)
        _, context = snapshot(repo, now.isoformat(), include_sources=False)
        outcome = next((r for r in context["recommendation_outcomes"] if r["recommendation_id"] == cid), None)
        if outcome:
            metric = evaluate("STR-27", [], cutoff_time=now.isoformat(),
                              window_start=(now - timedelta(days=365)).isoformat(), window_end=now.isoformat(),
                              context={"recommendation_outcomes": [outcome]})
            values = metric.get("value") or []
            success = values[0].get("short_term_success") if values else None
            st.write("冻结任务复核：" + ("已满足记录的目标" if success is True else "未满足记录的目标" if success is False else "尚不能判断：需要候选之后的有效参考组、完整目标与执行反馈"))
            st.caption("任务完成与否不证明试验导致进步；历史记录更正后按当前事实重新核对，冻结依据保留。")


def _render_discussion(discussion):
    source, facts = discussion["source_explanation"], discussion["observations"]
    st.write("一般原则与当前讨论")
    st.write(source["answer"])
    st.write(f"当前明确计划的工作组：{facts['explicit_planned_work_sets']}；已记录同条件场次：{len(facts['recorded_sessions'])}。")
    st.caption(f"记录窗口：{facts['window']['start']} 至 {facts['window']['end']}；这是产品观察窗口。")
    if facts["available_minutes"] is not None:
        st.write(f"你声明的可用时间：{facts['available_minutes']:g} 分钟。")
    if facts["recorded_sessions"]:
        st.dataframe(facts["recorded_sessions"], hide_index=True)
    if facts.get("current_session_records"):
        st.write("本次已经记录的组（保留未完成和缺项）")
        st.dataframe(facts["current_session_records"], hide_index=True)
    if facts["recorded_interval_days"]:
        st.write("已记录场次起点之间的间隔（天）")
        st.dataframe(facts["recorded_interval_days"], hide_index=True)
    for question in discussion["questions"]:
        st.write(question)
    for citation in source["citations"]:
        st.caption(f"来源：{citation['source_id']} · {citation['source_version_id']} · " + ", ".join(citation["span_ids"]))
    for limit in [*discussion["limitations"], *source["limits"]]:
        st.caption(limit)
    if discussion["numeric_action_limitations"]:
        st.caption("数值任务仍受限制：" + "；".join(discussion["numeric_action_limitations"]))


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
