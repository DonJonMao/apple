"""Question-specific local comparisons and user-selected follow-up actions."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import streamlit as st

from healthzip.analytics.body_metrics import analyze_questions
from healthzip.analytics.body_questions import QUESTIONS
from healthzip.analytics.cache import WORKSPACE_CACHE_SECONDS, cached
from healthzip.ui.body_workspace import _source_selection, local_window_label, range_controls
from healthzip.ui.preferences import load_preferences


def render_questions(repo, *, timezone_name):
    scope = range_controls(timezone_name)
    include_cycle = load_preferences(repo.path).get("cycle_enabled") or repo.one("SELECT 1 FROM cycle_event LIMIT 1")
    ids = [qid for qid in QUESTIONS if qid != "W8" or include_cycle]
    if st.session_state.get("review_question") not in ids:
        st.session_state["review_question"] = ids[0]
    question_id = st.selectbox("想了解的问题", ids, format_func=lambda key: QUESTIONS[key][0], key="review_question")
    from healthzip.analytics.alternate_observations import alternate_dependencies
    fields = set(QUESTIONS[question_id][1])
    action_revision = None
    if question_id == "W4":
        from healthzip.analytics.question_context import visible_goal_actions
        from healthzip.science.body_catalog import METRIC_CATALOG
        from healthzip.science.contracts import instant
        # A newly saved goal or feedback must advance a relative view's cutoff
        # immediately; an explicit historical range keeps its original cutoff.
        _, actions, action_revision = visible_goal_actions(repo, instant(scope["actual_start"]),
                                                           instant(scope["actual_end"]), instant(scope["actual_end"]))
        fields.update(row["metric"] for action in actions for row in action["baseline"].get("rows", [])
                      if row.get("type") == "metric" and row.get("metric") in METRIC_CATALOG)
        if actions:
            fields.add("sleep_stage")
    alternate = [dep for kind in fields for dep in alternate_dependencies(kind)]
    clock = cached(repo, "question-view-clock-1", {"question": question_id, "zone": timezone_name,
        "action_revision": action_revision,
        "period": st.session_state["body_period"], "days": scope["window_days"], "start": scope["window_start"],
        "end": scope["cutoff_time"], "day": datetime.fromisoformat(scope["actual_end"]).astimezone(ZoneInfo(timezone_name)).date().isoformat()},
        lambda: (scope["actual_start"], scope["actual_end"]), max_age_seconds=WORKSPACE_CACHE_SECONDS,
        dependencies=alternate + [("health_sample", kind) for kind in fields] + [("subjective_log", None), ("training", None), ("workout", None), ("body_measurement", None)])
    args = {"window_start": clock[0], "window_end": clock[1], "cutoff_time": clock[1],
            "timezone_name": timezone_name, "question_ids": [question_id]}
    question = analyze_questions(repo, **args)[0]
    sources = {row["source"] for row in question["rows"] if row.get("source")}
    source = _source_selection(repo, "question:" + question_id, sources)
    if source:
        question = analyze_questions(repo, source_filter=[source], **args)[0]
    render_question(question, repo=repo)
    _select_action(repo, question, [source] if source else [])
    from healthzip.ui.topic_sources import render_topic_sources
    render_topic_sources(question_id)


def render_question(question, *, repo):
    st.markdown("### " + question["title"])
    window = question["window"]
    st.caption(local_window_label(window["start"], window["end"], window["timezone"]))
    st.write(question["observation"])
    _render_goal_actions(question)
    association = question.get("association")
    if association:
        _association(association)
    for key, title in (("support", "支持这项解释的记录"), ("counterevidence", "削弱这项解释的记录")):
        if question.get(key):
            st.write(title)
            for item in question[key]:
                st.write(item)
    rows = question.get("rows") or []
    if rows:
        with st.expander("相关记录与日期", expanded=False):
            labels = {"date": "观察日期", "first_date": "比较日期", "title": "项目", "value": "本次值", "first_value": "前次值",
                      "source": "来源", "unit": "单位", "difference": "差值", "fatigue": "疲劳", "soreness": "酸痛", "pain": "疼痛",
                      "category": "实际类别", "reps": "次数", "load": "负荷", "position": "组位", "exercise": "动作",
                      "load_kg": "实际外部重量（kg）", "mass_kg": "对应体重（kg）", "mass_measured_at": "体重测量时间",
                      "scale_source": "体重来源", "load_per_kg": "重量/体重比", "activity": "运动类型",
                      "duration_minutes": "运动分钟", "distance_m": "距离（米）", "speed_m_s": "速度（米/秒）", "pain_level": "疼痛程度", "movement_impact": "对动作的影响",
                      "illness_or_travel": "已记录感染或旅行背景", "symptoms": "实际症状",
                      "reason": "未匹配原因", "pain_location": "疼痛部位", "location": "部位", "notes": "本人备注"}
            from healthzip.analytics.question_context import subjective_display_value
            display = [{labels[k]: subjective_display_value(k, v) for k, v in row.items() if k in labels} for row in rows]
            st.dataframe([row for row in display if row], hide_index=True, use_container_width=True)
            _render_estimate_support(rows)
            _render_event_performance(rows)
            sessions = sorted({str(row["session_id"]) for row in rows if row.get("session_id")}
                              | {str(row["first_session_id"]) for row in rows if row.get("first_session_id")}
                              | {str(identity) for row in rows for identity in row.get("same_date_sessions", [])})
            if sessions:
                session_labels = {}
                for index, identity in enumerate(sessions, 1):
                    session = repo.one("SELECT session_date,name FROM strength_session WHERE id=? OR session_uuid=?",
                                       (identity, identity))
                    session_labels[identity] = (f"{session['session_date']} · {session['name'] or '实际训练'}"
                                                if session else f"关联训练 {index}")
                selected = st.selectbox("打开对应训练", sessions, format_func=session_labels.get,
                                        key="question_session:" + question["id"])
                if st.button("查看这场实际训练", key="question_open_session:" + question["id"]):
                    _open_training(repo, selected)
                    st.rerun()
    if question.get("training_pairs"):
        with st.expander("睡眠与训练的实际先后"):
            for direction, title in (("before_training", "训练前的睡眠"), ("after_training", "训练后的睡眠")):
                st.write(title)
                pairs = question["training_pairs"][direction]
                shown = []
                for row in pairs:
                    if row["matches"]:
                        shown.extend({"训练开始": row["started_at"], "训练结束": row.get("ended_at"), "睡眠开始": match["event_start"],
                                      "睡眠结束": match["event_end"], "已观察分钟": match["value"]} for match in row["matches"])
                    else:
                        shown.append({"训练开始": row["started_at"], "未匹配原因": row["unmatched_reason"]})
                if shown:
                    st.dataframe(shown, hide_index=True)
    for note in question.get("limitations", []):
        st.caption(note)
    st.write("下一步")
    for step in question.get("steps", [])[:3]:
        st.write(step)


def _association(association):
    import plotly.graph_objects as go
    groups = association.get("groups", [])
    if not groups:
        st.caption(association.get("reason", "当前记录仅支持描述性比较。"))
    for index, group in enumerate(groups):
        if group.get("status") == "estimated":
            lo, hi = group["interval"]
            st.write(f"同条件记录的估计关联 {group['coefficient']:+.3g} {group['effect_unit']}，区间 [{lo:.3g}, {hi:.3g}]。")
            st.caption(f"实际日期 {group['range'][0]} — {group['range'][1]}，{group['n']} 个配对日期；同时调整实际经过时间及一阶相关误差。")
            pairs = group["pairs"]
            fig = go.Figure(go.Scatter(x=[row["sleep_hours"] for row in pairs], y=[row["value"] for row in pairs],
                text=[row["date"] for row in pairs], mode="markers", name="真实配对",
                hovertemplate="%{text}<br>睡眠 %{x:.2f} 小时<br>SDNN %{y:.2f} ms<extra></extra>"))
            fig.update_layout(height=270, xaxis_title="测量前已观察睡眠（小时）", yaxis_title="同条件 SDNN 日代表值（ms）")
            st.plotly_chart(fig, use_container_width=True, key="question_association:" + str(index), config={"displayModeBar": False})
        else:
            st.caption(group.get("reason", "本组保留已配对记录。"))
        with st.expander("本组配对日期与适用性 " + str(index + 1)):
            st.dataframe([{ "日期": row["date"], "睡眠结束": row["sleep_end"], "SDNN测量开始": row["sdnn_first"],
                           "睡眠小时": row["sleep_hours"], "SDNN毫秒": row["value"]} for row in group.get("pairs", [])], hide_index=True)
            from healthzip.ui.body_workspace import render_diagnostics
            render_diagnostics(group.get("diagnostics", {}))
    if association.get("unmatched"):
        with st.expander("未能配对的记录"):
            st.dataframe([{ "日期": row.get("date"), "原因": row.get("reason")} for row in association["unmatched"]], hide_index=True)


def _open_training(repo, session_id):
    from healthzip.training.service import TrainingService
    from healthzip.ui.training_workbench import open_recorded_session
    session = TrainingService(repo, initialize=False).get_session(int(session_id) if str(session_id).isdigit() else session_id)
    open_recorded_session(repo, session["session_uuid"])


def _select_action(repo, question, sources):
    steps = question.get("steps") or []
    if not steps:
        return
    with st.expander("选择行动并安排复评"):
        action = st.selectbox("本次选择", steps, key="review_action_choice:" + question["id"])
        zone = ZoneInfo(question["window"]["timezone"])
        today = datetime.now(zone).date()
        due = st.date_input("计划复评日期", value=today+timedelta(days=7),
                            min_value=today+timedelta(days=1), key="review_action_due:" + question["id"])
        st.caption("复评日期由你选择。保存本次观察和来源，之后按相同观察范围查看后续记录。")
        if st.button("保存这项行动", key="review_action_save:" + question["id"]):
            from healthzip.workflows.actions import select_action
            select_action(repo, question, action, datetime.combine(due, datetime.min.time().replace(hour=12), zone).isoformat(), source_filter=sources)
            st.success("已保存行动，可在“行动复评”记录执行情况和查看后续观察。")


def render_actions(repo):
    from healthzip.workflows.actions import followup, list_actions, save_feedback
    actions = list_actions(repo)
    if not actions:
        st.info("还没有已选择的行动。可在问题分析中选择一项，并填写计划复评日期。")
        return
    labels = {row["action_id"]: _action_day(row, "selected_at") + " · " + row["action_text"] for row in actions}
    if st.session_state.get("review_action_id") not in labels:
        st.session_state["review_action_id"] = next(iter(labels))
    identity = st.selectbox("已选择的行动", list(labels), format_func=labels.get, key="review_action_id")
    action = next(row for row in actions if row["action_id"] == identity)
    st.write(action["action_text"])
    st.caption(f"选择于 {_action_day(action, 'selected_at')} · 计划复评 {_action_day(action, 'review_due')}")
    baseline = json.loads(action["baseline_json"])
    st.write("选择行动时的观察")
    st.write(baseline["observation"])
    state_key = "action_followup:" + str(repo.path.resolve()) + ":" + identity
    if st.button("查看后续同口径观察"):
        st.session_state[state_key] = followup(repo, identity)
    result = st.session_state.get(state_key)
    if result and result.get("current"):
        if result["status"] == "partial":
            st.caption("后续范围尚未达到原观察范围的长度，当前展示已到来的记录。")
        if not result.get("method_matches"):
            st.warning("计算方法已有更新，请展开原观察与当前方法后再判断可比性。")
        render_question(result["current"], repo=repo)
    elif result:
        st.info("选择行动后的观察窗口尚未开始。")
    options = {"executed": "已执行", "partial": "部分执行", "not_executed": "未执行", "stopped": "已停止"}
    with st.form("action_feedback:" + identity):
        status = st.selectbox("实际执行情况", list(options), format_func=options.get, index=None)
        notes = st.text_area("实际感受或未执行原因（可选）", value=action.get("notes") or "")
        if st.form_submit_button("保存执行与复评"):
            if status is None:
                st.info("请选择真实执行情况。")
            else:
                save_feedback(repo, identity, status, notes, result, event_id=uuid4().hex)
                st.success("执行情况和本次观察已保存。")


def _action_day(action, key):
    zone = ZoneInfo(json.loads(action["baseline_json"])["window"]["timezone"])
    return datetime.fromisoformat(action[key]).astimezone(zone).date().isoformat()


def _render_estimate_support(rows):
    display = []
    for row in rows:
        if row.get("support_limitation"):
            st.caption(row["support_limitation"])
        for point in row.get("estimate_observations", []):
            support = point.get("estimate_support") or {}
            display.append({"项目": row.get("title"), "观察日期": point.get("date"),
                            "发布日期": point.get("observed_at"), "实际发布值": point.get("value"),
                            "支持起点": support.get("start"), "支持终点": support.get("end"),
                            "与前次支持重叠": support.get("overlaps_prior_window"),
                            "同支持窗口重复发布": support.get("repeated_publication"),
                            "来源报告上限": support.get("upper_limit_m"), "位于报告上限": support.get("at_reportable_limit"),
                            "方法": support.get("method"), "版本": support.get("algorithm_version")})
    if display:
        st.write("低频估计的实际发布与支持窗口")
        st.dataframe(display, hide_index=True)


def _render_event_performance(rows):
    labels = {"exercise_name": "动作", "exercise": "动作", "set_number": "组位", "position": "组位",
              "load_value": "实际重量", "load": "实际重量", "load_unit": "单位", "unit": "单位",
              "reps": "次数", "duration_s": "时长（秒）", "distance_m": "距离（米）", "rir": "实际RIR",
              "ended_at": "实际组时间", "completion_state": "完成状态", "condition_known": "记录条件完整"}
    for row in rows:
        if row.get("type") == "event_training":
            precision = "（仅日期，日内顺序未知）" if row.get("event_time_precision") == "calendar_day" else ""
            st.write(f"{row.get('event_title', '实际事件')} · {row.get('event_at', '')}{precision}")
            st.caption(f"训练 {row.get('started_at', '')} — {row.get('ended_at', '')}；{row.get('temporal_relation', '')}")
            actual = [{label: item.get(key) for key, label in labels.items() if key in item} for item in row.get("actual_sets", [])]
            if actual:
                st.dataframe(actual, hide_index=True)
                if any(not item.get("condition_known") for item in row.get("actual_sets", [])):
                    st.caption("部分实际组的动作、器械、侧别或重量口径条件未知；保留原值，不作为已确认的同条件比较。")
        elif row.get("type") == "event_set_pair":
            st.write(f"{row.get('exercise', '实际动作')} · {row.get('first_date', '')} → {row.get('date', '')}")
            comparison = row.get("comparison") or {}
            pairs = comparison.get("comparisons", []) or ([row] if "set_number" in row else [])
            if pairs:
                st.dataframe([{"组位": pair["set_number"], "前次重量": pair.get("previous_load_value"),
                               "本次重量": pair.get("load_value"), "单位": pair.get("load_unit"),
                               "前次次数": pair.get("previous_reps"), "本次次数": pair.get("current_reps"),
                               "同条件同负荷": pair.get("comparable"), "同负荷次数变化": pair.get("reps_change"),
                               "前次RIR": pair.get("previous_rir"), "本次RIR": pair.get("current_rir"),
                               "前次休息（秒）": pair.get("previous_rest_s"), "本次休息（秒）": pair.get("current_rest_s")}
                              for pair in pairs], hide_index=True)
                if any(not pair.get("comparable") for pair in pairs):
                    st.caption("部分组的动作、器械、侧别、重量口径或测量条件不同/未知；实际值保留，不能视为同条件变化。")
            for observation in comparison.get("observations", []):
                st.write(observation)


def _render_goal_actions(question):
    goal = question.get("goal_context")
    if goal:
        st.write("当前目标 · " + goal.get("title", "尚未选择"))
        if goal.get("recorded_at"):
            st.caption("目标记录于 " + goal["recorded_at"])
        if goal.get("quantitative_target_status"):
            st.caption(goal["quantitative_target_status"])
        if goal.get("limitation"):
            st.caption(goal["limitation"])
    reviews = question.get("action_reviews") or []
    if not reviews:
        return
    statuses = {"executed": "已执行", "partial": "部分执行", "not_executed": "未执行", "stopped": "已停止"}
    with st.expander("已选行动、实际执行与预设观察", expanded=True):
        for review in reviews:
            st.write(review["action_text"])
            if review.get("prespecified_question"):
                st.caption("选择时的观察问题：" + review["prespecified_question"])
            if review.get("method_matches") is False:
                st.caption("当前问题方法已有更新；原观察仍冻结保存，前后对照需同时核对计算方法。")
            if review.get("view_timezone_matches") is False:
                st.caption("行动前后观察沿用选择时的分析时区，与当前页面时区不同。")
            st.caption("执行反馈：" + statuses.get(review.get("execution_status"), "尚未反馈")
                       + " · 计划复评 " + str(review.get("review_due", "")))
            if review.get("notes"):
                st.write("已记录反馈：" + review["notes"])
            for key, label in (("baseline_window", "选择时观察范围"), ("followup_window", "后续观察范围")):
                window = review.get(key)
                if window and window.get("start") and window.get("end"):
                    st.caption(label + "：" + local_window_label(window["start"], window["end"],
                               window.get("timezone", question["window"]["timezone"])))
            observations = review.get("observations") or []
            if observations:
                labels = {"title": "观察项目", "source": "来源", "unit": "单位", "baseline_value": "选择时数值",
                          "current_value": "后续数值", "difference": "差值", "baseline_date": "选择时观测日期",
                          "current_date": "后续观测日期", "first_value": "选择时数值", "value": "后续数值",
                          "first_date": "选择时观测日期", "date": "后续观测日期", "load": "实际比较重量",
                          "load_unit": "重量单位", "position": "组位", "reason": "可比性说明"}
                display = [{label: item.get(key) for key, label in labels.items() if key in item} for item in observations]
                st.dataframe([item for item in display if item], hide_index=True)
            if review.get("limitation"):
                st.caption(review["limitation"])
