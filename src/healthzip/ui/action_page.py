"""Plain-language action definitions and actual execution feedback."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import streamlit as st

from healthzip.ui.body_workspace import local_window_label
from healthzip.workflows.actions import (
    EXECUTION,
    followup,
    format_outcome_value,
    list_actions,
    outcome_options,
    proposed_definition,
    save_feedback,
    select_action,
)


def _window(window):
    return local_window_label(window["start"], window["end"], window["timezone"])


def render_definition(definition):
    if not definition:
        st.caption("旧行动未预先记录主要结果定义；原观察和反馈保留，不追溯编造成功标准。")
        return
    st.write("主要观察：" + definition["primary"]["label"])
    st.caption("基线：" + _window(definition["baseline_window"]))
    st.caption("后续固定观察范围：" + _window(definition["followup_window"]))
    st.caption(definition["expectation"])
    if definition["early_review"]:
        st.info("计划复评早于完整观察窗口结束，到期会显示阶段观察，不提前判定成功。")
    st.caption("计划开始与实际开始分别保存；未反馈时实际执行保持未知。")


def select_action_ui(repo, question, sources):
    steps = question.get("steps") or []
    if not steps:
        return
    with st.expander("选择行动并安排复评"):
        action = st.selectbox("本次选择", steps, key="review_action_choice:" + question["id"])
        options = outcome_options(question, action)
        primary_index = st.selectbox("主要看什么", range(len(options)),
            format_func=lambda i: options[i]["label"], key="review_action_primary:" + question["id"] + ":" + action)
        zone = ZoneInfo(question["window"]["timezone"])
        today = datetime.now(zone).date()
        start_day = st.date_input("计划开始日期", value=today + timedelta(days=1),
            min_value=today, key="review_action_start:" + question["id"])
        due = st.date_input("计划复评日期", value=today + timedelta(days=7),
            min_value=today + timedelta(days=1), key="review_action_due:" + question["id"])
        now = datetime.now(zone)
        planned = max(datetime.combine(start_day, datetime.min.time(), zone), now)
        due_at = datetime.combine(due, datetime.min.time().replace(hour=12), zone)
        definition = proposed_definition(question, action, due_at.isoformat(), selected_at=now.isoformat(),
            planned_start=planned.isoformat(), primary=options[primary_index], source_filter=sources)
        render_definition(definition)
        if st.button("保存这项行动", key="review_action_save:" + question["id"]):
            select_action(repo, question, action, due_at.isoformat(), selected_at=now.isoformat(),
                planned_start=planned.isoformat(), primary=options[primary_index], source_filter=sources)
            st.success("已保存行动和主要观察定义，可在“行动复评”记录实际执行并查看后续观察。")


def _observations(rows):
    if not rows:
        st.caption("当前没有该主要观察的可用记录。")
        return
    for row in rows:
        st.write(row["title"] + (" · " + str(row["source"]) if row.get("source") else ""))
        if row["type"] == "measurement_conditions":
            for key, label in (("baseline", "选择时"), ("current", "后续")):
                value = row.get(key)
                if value:
                    st.caption(f"{label} {value['record_count']} 条测量，覆盖 {value['recorded_days']} 天，"
                               f"{value['posture_known_count']} 条有姿势；实际时刻 " + "、".join(value["local_times"]))
                    if value["postures"]:
                        st.caption("已记录姿势：" + "、".join(value["postures"]))
        else:
            before, after = row.get("first_value"), row.get("value")
            st.write(f"期间中位数：{format_outcome_value(row, before)} → {format_outcome_value(row, after)}")
            if row.get("difference") is not None:
                st.caption("同口径差值 " + format_outcome_value(row, row["difference"], signed=True))
            for key, label in (("baseline", "基线"), ("current", "后续")):
                value = row.get(key)
                if value and "recorded_days" in value:
                    st.caption(f"{label}完整日记录 {value['recorded_days']}/{value['window_days']} 天；不完整日期单独保留。")
                elif value and "record_count" in value:
                    st.caption(f"{label} {value['record_count']} 个实际组、{value['session_count']} 场；RIR 未填与 0 分开保存。")
        if row.get("reason"):
            st.caption(row["reason"])
        with st.expander("这一观察的实际记录"):
            for key, title in (("baseline", "基线"), ("current", "后续")):
                value = row.get(key)
                if value:
                    records = value.get("records") or value.get("daily_points") or []
                    if records:
                        st.write(title)
                        st.dataframe(records, hide_index=True)
                    if value.get("partial_daily_points"):
                        st.write(title + "未完整日期的实际记录（不混入期间统计）")
                        st.dataframe(value["partial_daily_points"], hide_index=True)


def _actual_time(value, zone):
    if not value.strip():
        return None
    if ":" not in value:
        raise ValueError("实际时间请包含日期和时分；不确定时留空。")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("实际时间请填写 年-月-日 时:分；不确定时留空。") from exc
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)).isoformat()


def render_actions(repo):
    actions = list_actions(repo)
    if not actions:
        st.info("还没有已选择的行动。可在问题分析中选择一项，并填写计划复评日期。")
        return
    labels = {row["action_id"]: row["selected_at"][:10] + " · " + row["action_text"] for row in actions}
    if st.session_state.get("review_action_id") not in labels:
        st.session_state["review_action_id"] = next(iter(labels))
    identity = st.selectbox("已选择的行动", list(labels), format_func=labels.get, key="review_action_id")
    action = next(row for row in actions if row["action_id"] == identity)
    baseline = json.loads(action["baseline_json"])
    zone = ZoneInfo(baseline["window"]["timezone"])
    st.write(action["action_text"])
    st.caption("计划复评 " + datetime.fromisoformat(action["review_due"]).astimezone(zone).strftime("%Y-%m-%d %H:%M"))
    definition = json.loads(action["definition_json"]) if action.get("definition_json") else None
    if definition:
        st.write("主要观察：" + definition["primary"]["label"])
    else:
        st.caption("旧行动未预先记录主要结果定义，保留原观察与反馈。")
    st.write("实际执行：" + EXECUTION.get(action.get("status"), EXECUTION["unreported"]))
    execution = json.loads(action["execution_json"]) if action.get("execution_json") else {}
    if execution.get("started_at"):
        st.caption("实际开始：" + execution["started_at"] + "；实际结束：" + str(execution.get("ended_at") or "未记录"))
    if action.get("notes"):
        st.write(action["notes"])
    with st.expander("计划、比较口径与选择时的观察"):
        render_definition(definition)
        st.write(baseline["observation"])
    state_key = "action_followup:" + str(repo.path.resolve()) + ":" + identity
    if st.button("查看后续同口径观察"):
        st.session_state[state_key] = followup(repo, identity)
    result = st.session_state.get(state_key)
    if result:
        review = result["review"]
        st.write("现在观察到的主要结果")
        if review["status"] == "partial_window":
            st.caption("观察窗口尚未完整，当前为阶段观察。")
        elif review["status"] == "awaiting_observations":
            st.caption("原定观察窗口尚未开始；执行情况以真实反馈为准。")
        if not review.get("method_matches"):
            st.caption("问题分析方法已有更新，原定义与各项统计版本仍明确保留。")
        if definition and definition["primary"]["kind"] == "check":
            st.write(review["execution_label"] + "；以核对任务的真实反馈为准。")
        else:
            _observations(review.get("primary_observations", []))
        if review.get("secondary_observations"):
            with st.expander("次要观察与背景（不替代主要结果）"):
                _observations(review["secondary_observations"])
        if review.get("recorded_context"):
            with st.expander("已记录的疲劳、疼痛与其他背景"):
                from healthzip.analytics.question_context import describe_subjective
                for item in review["recorded_context"]:
                    st.write(item["date"] + " · " + describe_subjective(item))
        st.caption(review["limitation"])
    with st.form("action_feedback:" + identity):
        options = {k: v for k, v in EXECUTION.items() if k != "unreported"}
        status = st.selectbox("实际执行情况", list(options), format_func=options.get, index=None)
        actual_start = st.text_input("实际开始时间（可选）", value=execution.get("started_at") or "", placeholder="年-月-日 时:分（按分析时区）")
        actual_end = st.text_input("实际结束时间（可选）", value=execution.get("ended_at") or "", placeholder="未结束或不确定时留空")
        st.caption("只有实际知道时填写；留空不会把选择时间当作执行开始。")
        notes = st.text_area("实际感受或未执行原因（可选）", value=action.get("notes") or "")
        if st.form_submit_button("保存执行与复评"):
            if status is None:
                st.info("请选择真实执行情况。")
            else:
                try:
                    save_feedback(repo, identity, status, notes, result, event_id=uuid4().hex,
                        actual_start=_actual_time(actual_start, zone), actual_end=_actual_time(actual_end, zone))
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.session_state.pop(state_key, None)
                    st.success("执行情况和本次观察已追加保存；旧复评保持原版本。")
