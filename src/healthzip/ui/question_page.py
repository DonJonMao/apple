"""Question-specific local comparisons and user-selected follow-up actions."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from healthzip.analytics.body_metrics import analyze_questions
from healthzip.analytics.body_questions import QUESTIONS
from healthzip.analytics.cache import WORKSPACE_CACHE_SECONDS, cached
from healthzip.ui.body_workspace import _source_selection, local_window_label, range_controls
from healthzip.ui.preferences import load_preferences


def render_questions(repo, *, timezone_name):
    scope = range_controls(timezone_name)
    enabled = bool(load_preferences(repo.path).get("cycle_enabled"))
    include_cycle = enabled or _visible_cycle_records(repo, scope, timezone_name)
    ids = [qid for qid in QUESTIONS if qid != "W8" or include_cycle]
    if st.session_state.get("review_question") not in ids:
        st.session_state["review_question"] = ids[0]
    question_id = st.selectbox("想了解的问题", ids, format_func=lambda key: QUESTIONS[key][0], key="review_question",
                               label_visibility="collapsed")
    from healthzip.analytics.alternate_observations import alternate_dependencies
    fields = set(QUESTIONS[question_id][1])
    action_revision = None
    if question_id == "W4":
        from healthzip.analytics.question_context import (
            action_metric_dependencies,
            visible_goal_actions,
        )
        from healthzip.science.contracts import instant
        # A newly saved goal or feedback must advance a relative view's cutoff
        # immediately; an explicit historical range keeps its original cutoff.
        _, actions, action_revision = visible_goal_actions(repo, instant(scope["actual_start"]),
                                                           instant(scope["actual_end"]), instant(scope["actual_end"]))
        fields.update(action_metric_dependencies(actions))
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
            "timezone_name": timezone_name, "question_ids": [question_id], "period": scope.get("period"),
            "cycle_enabled": enabled}
    question = analyze_questions(repo, **args)[0]
    sources = {row["source"] for row in question["rows"] if row.get("source")}
    with st.popover("记录来源", use_container_width=True):
        source = _source_selection(repo, "question:" + question_id, sources)
    if source:
        question = analyze_questions(repo, source_filter=[source], **args)[0]
    render_question(question, repo=repo)
    _select_action(repo, question, [source] if source else [])
    from healthzip.ui.topic_sources import render_topic_sources
    render_topic_sources(question_id)


def _visible_cycle_records(repo, scope, timezone_name):
    """Use visible primary cycle records, including imported sample representation."""
    from healthzip.analytics.alternate_observations import alternate_rows
    from healthzip.analytics.body_metrics import _rows
    from healthzip.science.contracts import instant
    start, end = instant(scope["actual_start"]), instant(scope["actual_end"])
    fields = QUESTIONS["W8"][1]
    if _rows(repo, "health_sample", fields, start, end, end.isoformat(), ()):
        return True
    return any(alternate_rows(repo, field, start, end, end.isoformat(), timezone_name) for field in fields)


def render_question(question, *, repo):
    if question.get("fact_id"):
        st.markdown('<span data-hz-question="' + question["fact_id"] + '" style="display:none"></span>', unsafe_allow_html=True)
    titles = {"W1": "同动作完成表现", "W2": "训练与随后状态", "W3": "心肺与实际运动", "W4": "长期目标与行动",
              "W5": "体重与绝对表现", "W6": "睡眠与 SDNN", "W7": "活动量与行动能力", "W8": "周期与症状记录", "E": "设备事件"}
    st.markdown("### " + titles.get(question["id"], question["title"]))
    window = question["window"]
    zone = ZoneInfo(window["timezone"])
    st.caption(datetime.fromisoformat(window["start"]).astimezone(zone).date().isoformat() + " — "
               + datetime.fromisoformat(window["end"]).astimezone(zone).date().isoformat())
    if question["id"] != "W6":
        st.write(question["observation"])
    if question.get("ordinary_training"):
        render_ordinary_training(question["ordinary_training"], show_summary=False, namespace="question:" + question["id"])
    _render_goal_actions(question)
    association = question.get("association")
    if association:
        _association(association)
        with st.expander("本次观察与生活记录"):
            st.write(question["observation"])
    for key, title in (("support", "支持这项解释的记录"), ("counterevidence", "削弱这项解释的记录")):
        if question.get(key):
            st.write(title)
            for item in question[key]:
                st.write(item)
    rows = question.get("rows") or []
    if rows:
        with st.expander("相关记录与日期", expanded=False):
            st.caption(local_window_label(window["start"], window["end"], window["timezone"]))
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
            for source_row, shown in zip(rows, display):
                if source_row.get("comparison"):
                    shown["统计口径"] = ("窗口内末次来源估计；非独立每日测量" if source_row.get("statistic_kind") == "source_estimate_points"
                                       else "完整记录日代表值的期间中位数")
                    for key, label in (("current", "本期范围"), ("previous", "前期范围")):
                        period = source_row["comparison"][key]["window"]
                        shown[label] = local_window_label(period["start"], period["end"], period["timezone"])
            st.dataframe([row for row in display if row], hide_index=True, use_container_width=True)
            _render_estimate_support(rows, window["timezone"])
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
    elif len(groups) > 1:
        st.caption(f"共 {len(groups)} 组，来源、设备、已知测量条件和采样时段分别保留；各组状态独立。")
    for index, group in enumerate(groups):
        identity = group.get("identity", {})
        if identity:
            st.write(f"{identity['source']} · {identity.get('device') or '设备未知'}")
            labels = {"sampling_mode": "采样", "measurement_context": "情境", "breathing_context": "呼吸情境",
                      "posture": "姿势", "respiration": "呼吸", "activity_context": "活动情境",
                      "recording_duration_seconds": "采样秒数", "algorithm_version": "算法版本"}
            conditions = [f"{label}：{'、'.join(map(str, identity['known_conditions'][key]))}"
                          for key, label in labels.items() if key in identity["known_conditions"]]
            readable = {"主动": "主动", "background": "后台", "active": "主动", "seated": "坐姿",
                        "standing": "站姿", "supine": "仰卧", "rest": "静息"}
            condition_text = " · ".join(conditions) or "已记录协议；具体姿势与活动情境未记录"
            for raw, value in readable.items():
                condition_text = condition_text.replace(raw, value)
            st.caption(condition_text)
            clock = identity["actual_local_time_range"]
            dates = identity["date_range"]
            st.caption(f"实际采样 {clock[0]}–{clock[1]} · {dates[0]}—{dates[1]} · "
                       f"{identity['paired_dates']} 个配对日期、{identity['sdnn_sample_count']} 条 SDNN")
        if group.get("status") == "estimated":
            lo, hi = group["interval"]
            st.write(f"观察性条件关联 {group['coefficient']:+.3g} {group['effect_unit']}，区间 [{lo:.3g}, {hi:.3g}]。")
            if group.get("direction") == "uncertain":
                st.caption("区间包含零，当前记录没有明确的关联方向。")
            st.caption(f"实际日期 {group['range'][0]} — {group['range'][1]}，{group['n']} 个配对日期；同时调整实际经过时间及一阶相关误差。")
        else:
            st.write("本组暂不能估计条件关联")
            st.caption(group.get("reason", "本组保留已配对记录。"))
        pairs = group.get("pairs", [])
        if pairs:
            fig = go.Figure(go.Scatter(x=[row["sleep_hours"] for row in pairs], y=[row["value"] for row in pairs],
                text=[row["date"] for row in pairs], mode="markers", name="真实配对",
                hovertemplate="%{text}<br>睡眠 %{x:.2f} 小时<br>SDNN %{y:.2f} ms<extra></extra>"))
            fig.update_layout(height=270, xaxis_title="测量前已观察睡眠（小时）", yaxis_title="同条件 SDNN 日代表值（ms）")
            st.plotly_chart(fig, use_container_width=True, key="question_association:" + str(index), config={"displayModeBar": False})
            st.caption("图为原始配对散点，未扣除时间等因素；不是调整后的拟合效果图。")
        with st.expander("本组配对日期与适用性 " + str(index + 1)):
            if identity:
                band = identity["time_band"]
                st.caption(f"按测量开始时间 {band['start_hour']:02d}:00–{band['end_hour']:02d}:00 分组是产品展示方法；"
                           "同一 6 小时时段不代表生理测量条件完全相同。")
                st.write("睡眠来源：", identity["sleep_source"]["source"])
                st.write("协议身份：", identity["protocol"])
                st.write("来源版本：", identity.get("source_version") or "未记录")
                st.caption("分组身份：" + group["group_id"])
            st.dataframe([{ "日期": row["date"], "睡眠结束": row["sleep_end"], "SDNN测量开始": row["sdnn_first"],
                           "睡眠小时": row["sleep_hours"], "SDNN毫秒": row["value"]} for row in group.get("pairs", [])], hide_index=True)
            if group.get("neutral_observations"):
                st.write("相邻记录的实际变化")
                st.caption("相邻变化共享日期，不能当作独立样本投票，也不用于给本组拟合结果制造支持证据。")
                st.dataframe([{"前次日期": row["from_date"], "本次日期": row["to_date"],
                               "睡眠变化（小时）": row["sleep_hours_change"], "SDNN变化（ms）": row["sdnn_ms_change"]}
                              for row in group["neutral_observations"]], hide_index=True)
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


def render_ordinary_training(review, *, show_summary=True, namespace="ordinary"):
    """Read every ordinary point; selection is presentation, never best-set sampling."""
    groups = review.get("series", [])
    if not groups:
        return
    if show_summary:
        for text in review.get("summary", [])[:3]:
            st.write(text)
    with st.expander(f"普通训练的完整轨迹与阶段对照 · {review['record_count']} 条记录"):
        choices = {g["series_id"]: g for g in groups}
        selected = st.selectbox("动作、条件与组位", list(choices),
            format_func=lambda key: f"{choices[key]['exercise']} · 第 {choices[key]['position'] or '未知'} 组 · "
                f"{choices[key]['set_type'] or '组类型未知'} · {choices[key]['record_count']} 条 · "
                f"{choices[key]['points'][0]['date'][:10]} 至 {choices[key]['points'][-1]['date'][:10]}",
            key="ordinary_training:" + namespace + ":" + str(review["window"]))
        group = choices[selected]
        st.write(group["summary"])
        points = group["points"]
        import plotly.graph_objects as go
        loads = list(dict.fromkeys(p["load"] for p in points))
        fig = go.Figure()
        for load in loads:
            items = [p for p in points if p["load"] == load and p["reps"] is not None]
            if items:
                fig.add_trace(go.Scatter(x=[p["date"] for p in items], y=[p["reps"] for p in items],
                    mode="markers+lines" if group["condition_known"] else "markers",
                    name=f"{load:g} {group['unit']}" if load is not None else "负荷未填写／自重"))
        if fig.data:
            fig.update_layout(height=260, xaxis_title="实际记录日期", yaxis_title="已完成次数")
            st.plotly_chart(fig, use_container_width=True, key="ordinary_chart:" + namespace + ":" + selected, config={"displayModeBar": False})
        st.dataframe([{"日期": p["date"], "原始重量": p["recorded_load"], "原始单位": p["recorded_unit"],
                       "次数": p["reps"], "RIR": p["rir"], "停止原因": p["stop_reason"],
                       "训练": p["session_id"], "动作实例": p["session_exercise_id"]} for p in points], hide_index=True)
        stage_rows = []
        for period in group["periods"]:
            for summary in period["same_load_summaries"]:
                stage_rows.append({"阶段": "较早" if period["period"] == "earlier" else "近期",
                    "范围": period["start"][:10] + " 至 " + period["end"][:10],
                    "重量": summary["load"], "单位": summary["unit"], "记录数": summary["record_count"],
                    "次数中位数": summary["reps"]["median"], "次数最少": summary["reps"]["min"], "次数最多": summary["reps"]["max"],
                    "RIR中位数": summary["rir"]["median"], "RIR填写数": summary["rir"]["n"]})
        if stage_rows:
            st.dataframe(stage_rows, hide_index=True)
        if not group["condition_known"]:
            st.caption("动作、器械／设置、侧别、负荷口径或组位尚未完整记录，以上只展示实际值，不认定条件相同。")
        if group["unpaired_record_ids"]:
            st.caption(f"{len(group['unpaired_record_ids'])} 条记录因条件未知或同场组位不唯一未自动配对；原记录完整保留。")
        if group["rir_missing_n"]:
            st.caption(f"{group['rir_missing_n']} 条记录没有精确 RIR，不能宣称努力程度相同；RIR=0 保留为实际零值。")
        if group["load_basis"] == "assistance_setting":
            st.caption("此处重量是辅助重量；辅助减少不等于表现退步。")
        for note in review["limitations"]:
            st.caption(note)


def _select_action(repo, question, sources):
    from healthzip.ui.action_page import select_action_ui
    select_action_ui(repo, question, sources)


def render_actions(repo):
    from healthzip.ui.action_page import render_actions as render
    render(repo)


def _render_estimate_support(rows, timezone_name="Asia/Shanghai"):
    from healthzip.analytics.display_format import local_timestamp
    display = []
    for row in rows:
        if row.get("support_limitation"):
            st.caption(row["support_limitation"])
        for point in row.get("estimate_observations", []):
            support = point.get("estimate_support") or {}
            display.append({"项目": row.get("title"), "来源": row.get("source"),
                            "来源观测时间": local_timestamp(point.get("observed_at"), timezone_name),
                            "明确发布时间": local_timestamp(point.get("published_at"), timezone_name), "来源估计值": point.get("value"),
                            "支持起点": local_timestamp(support.get("start"), timezone_name), "支持终点": local_timestamp(support.get("end"), timezone_name),
                            "与前次支持重叠": support.get("overlaps_prior_window"),
                            "同支持窗口重复发布": support.get("repeated_publication"),
                            "来源报告上限": support.get("upper_limit_m"), "位于报告上限": support.get("at_reportable_limit"),
                            "方法": support.get("method"), "版本": support.get("algorithm_version")})
    if display:
        st.write("低频估计的来源观测、发布时间与支持窗口")
        st.caption("导入时间不作为发布时间；发布时间未提供时保持未知，记录天数不代表独立测量次数。")
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
            st.write(review.get("summary") or review["action_text"])
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
