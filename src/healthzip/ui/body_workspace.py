"""Body topics and one analysis range shared by facts, plots and explanations."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import streamlit as st

from healthzip.analytics.cache import WORKSPACE_CACHE_SECONDS, cached
from healthzip.analytics.display_format import display_unit, display_value, format_measurement
from healthzip.analytics.workspaces import workspace_window
from healthzip.ui.body_pages import (
    render_cardio,
    render_heart,
    render_sleep,
    render_weight,
    source_name,
)
from healthzip.ui.navigation import BODY_SECTIONS
from healthzip.ui.preferences import load_preferences, persist_widget
from healthzip.ui.theme import open_workspace

_SPECIAL = {"心率": render_heart, "睡眠": render_sleep, "体重": render_weight, "有氧": render_cardio}
_SUMMARIES = {"心率": "心率与 HRV 概览", "睡眠": "睡眠事件与时长", "体重": "体重变化", "有氧": "有氧能力估计"}


def range_controls(timezone_name):
    zone = ZoneInfo(timezone_name)
    # The scoped backend owns the request clock, including the acceptance clock.
    from healthzip.analytics import workspaces
    now = workspaces.datetime.now(timezone.utc)
    st.session_state.setdefault("body_period", "近30天")
    st.session_state.setdefault("analysis_window_days", 30)
    with st.container(key="page_period"):
        label = st.radio("查看范围", ["本周", "本月", "近30天", "长期", "自定义"],
                         horizontal=True, key="body_period", label_visibility="collapsed")
        days = int(st.session_state["analysis_window_days"])
        period = {"本周": "week", "本月": "month", "近30天": "30d"}.get(label)
        cutoff, first = None, None
        if label == "长期":
            with st.expander("长期范围设置"):
                days = int(st.number_input("长期范围（天）", min_value=1, max_value=3650, value=365, key="body_long_days"))
        elif label == "自定义":
            with st.expander(f"自定义范围 · 最近 {days} 天"):
                days = int(st.number_input("最近天数", min_value=1, max_value=3650, key="analysis_window_days"))
                dates = st.date_input("自定义日期范围", value=(now.astimezone(zone).date()-timedelta(days=days-1), now.astimezone(zone).date()),
                                      max_value=now.astimezone(zone).date(), key="body_custom_dates")
                if st.checkbox("使用上述日期范围", key="body_use_custom_dates"):
                    if not isinstance(dates, tuple) or len(dates) != 2:
                        st.info("请选择起止两个日期。")
                        st.stop()
                    first = datetime.combine(dates[0], time.min, zone).isoformat()
                    cutoff = min(now, datetime.combine(dates[1]+timedelta(days=1), time.min, zone)).isoformat()
        start, end = workspace_window(datetime.fromisoformat(cutoff) if cutoff else now, timezone_name,
                                       period=period, window_days=days, window_start=first)
    return {"period": period, "window_days": days, "window_start": first, "cutoff_time": cutoff,
            "actual_start": start.isoformat(), "actual_end": end.isoformat(), "with_model": label == "长期"}


def _source_selection(repo, section, sources):
    key = "body_source_" + str(repo.path.resolve()) + "_" + section
    preference = "source:" + section
    if key not in st.session_state:
        st.session_state[key] = load_preferences(repo.path).get(preference)
    selected = st.session_state.get(key)
    options = [None, *sorted(set(sources) | ({selected} if selected else set()))]
    if len(options) > 2 or selected is not None:
        return st.selectbox("记录来源", options, key=key, placeholder="全部来源（分别展示）",
            format_func=lambda value: "全部来源（分别展示）" if value is None else source_name(value) + (" · 当前范围未见记录" if value not in sources else ""),
            on_change=persist_widget, args=(str(repo.path), key, preference))
    return selected


def _special_detail(repo, section, scope, timezone_name):
    from healthzip.analytics.workspaces import analyze_workspace
    arguments = {key: scope[key] for key in ("period", "window_days", "window_start", "cutoff_time") if scope[key] is not None}
    analysis = analyze_workspace(repo, section, timezone_name=timezone_name, **arguments)
    sources = set()
    for metric in analysis.get("workspace_scope", {}).get("metrics", {}).values():
        for stream in metric.get("comparison", {}).get("streams", []):
            protocol = stream.get("protocol") or []
            if protocol and protocol[0]:
                sources.add(protocol[0])
    for point in analysis.get("heart", {}).get("observations", []):
        name = point.get("source_name") or point.get("source")
        if name:
            sources.add(name)
    for night in analysis.get("sleep", {}).get("nights", []):
        name = source_name(night.get("source"))
        if name != "来源未注明":
            sources.add(name)
    selected = _source_selection(repo, section, sources)
    if selected:
        analysis = analyze_workspace(repo, section, timezone_name=timezone_name, source_filter=[selected], **arguments)
    _SPECIAL[section](analysis, repo=repo, show_title=False)
    if scope["with_model"] and (section != "睡眠" or st.session_state.get("body_sleep_scope_" + str(repo.path.resolve()), "所选时期逐日总量") == "所选时期逐日总量"):
        kind = {"心率": "resting_heart_rate_bpm", "睡眠": "sleep_stage", "体重": "body_mass_kg", "有氧": "vo2_max_ml_kg_min"}[section]
        from healthzip.analytics.body_metrics import METRIC_CATALOG
        if kind in METRIC_CATALOG:
            st.write("长期模型与适用性")
            render_metric(repo, kind, scope, timezone_name, selected_source=selected, model_only=True)


def _topic_metrics(section):
    from healthzip.analytics.body_metrics import METRIC_CATALOG
    return {kind: spec for kind, spec in METRIC_CATALOG.items() if spec["theme"] == section}



def render_body(repo, *, timezone_name):
    preferences = load_preferences(repo.path)
    has_cycle = repo.one("SELECT 1 FROM cycle_event LIMIT 1") is not None
    sections = [*BODY_SECTIONS, *(["周期与症状"] if has_cycle or preferences.get("cycle_enabled") else [])]
    if st.session_state.get("body_section") not in sections:
        st.session_state["body_section"] = sections[0]
    section = st.session_state["body_section"]
    heading, menu = st.columns([1.2, 1], vertical_alignment="center")
    with heading:
        st.subheader("身体" if section == "身体总览" else section)
    with menu.popover("切换主题或指标", use_container_width=True):
        section = st.selectbox("身体主题", sections, key="body_section")
        metrics = _topic_metrics(section) if section != "身体总览" else {}
        default = _SUMMARIES.get(section)
        options = ([default] if default else []) + list(metrics)
        choice = None
        if options:
            key = "body_metric:" + section
            if st.session_state.get(key) not in options:
                st.session_state[key] = options[0]
            choice = st.selectbox("查看指标", options, key=key, format_func=lambda value: metrics.get(value, {}).get("title", value))
    if section == "身体总览":
        render_body_overview(repo, timezone_name)
        return
    if choice != default and choice:
        st.write(metrics[choice]["title"])
    scope = range_controls(timezone_name)
    from healthzip.workflows.storage import current_context_problem
    context = st.session_state.get("analysis_contexts", {}).get(str(repo.path.resolve()))
    if current_context_problem(repo, context):
        st.warning("当前选择的适用声明已撤回或被替换，来源解释须重新确认；记录事实仍可查看。请在复盘的问题分析中确认适用信息。")
    if choice == default:
        _special_detail(repo, section, scope, timezone_name)
    elif choice:
        render_metric(repo, choice, scope, timezone_name)


def render_body_overview(repo, timezone_name):
    from healthzip.analytics.workspace_summary import workspace_summary
    result = workspace_summary(repo, "总览", timezone_name=timezone_name, period="week")
    item = next(row for row in result["periods"] if row["period"] == "week")
    st.caption("本周已记录的身体变化。进入主题可选择指标、来源和时间范围。")
    facts = item["facts"]
    for sections in (("心率", "睡眠"), ("有氧", "体重"), ("活动与行动能力", "夜间生理"), ("环境", "健康与安全事件")):
        for column, section in zip(st.columns(2), sections):
            labels = {"心率": {"静息心率"}, "睡眠": {"已观察睡眠"}, "体重": {"体重"}, "有氧": {"来源报告 VO₂max", "VO₂max"}}.get(section, set())
            rows = [row for row in facts if row.get("label") in labels and row.get("value") is not None]
            with column.container(border=True):
                st.write(section)
                if rows:
                    row = rows[0]
                    st.markdown(f"**{row['value']:.1f} {row.get('unit', '')}**")
                    st.caption(f"{row.get('observed_days', 0)} 个记录日期 · {row.get('source', '来源未注明')}")
                else:
                    st.caption({"活动与行动能力": "步数、距离、站立与步态", "夜间生理": "呼吸、血氧、腕温与呼吸紊乱", "环境": "日照与声音暴露", "健康与安全事件": "设备实际记录的通知和事件"}.get(section, "本周未见可用于摘要的记录"))
                st.button("查看" + section, key="open_body_" + section, on_click=open_workspace, args=(section,), use_container_width=True)
    if load_preferences(repo.path).get("cycle_enabled") or repo.one("SELECT 1 FROM cycle_event LIMIT 1"):
        st.button("周期与症状", on_click=open_workspace, args=("周期与症状",))


def render_metric(repo, kind, scope, timezone_name, *, selected_source=None, model_only=False):
    from healthzip.analytics.body_metrics import METRIC_CATALOG, analyze_body_metric
    spec = METRIC_CATALOG[kind]
    arguments = {"window_start": scope["actual_start"], "window_end": scope["actual_end"], "cutoff_time": scope["actual_end"],
                 "timezone_name": timezone_name, "with_model": scope["with_model"], "period": scope.get("period")}
    # Freeze automatic cutoffs for the product refresh interval and revision.
    from healthzip.analytics.alternate_observations import alternate_dependencies
    dependencies = [("health_sample", kind), ("body_measurement", kind), *alternate_dependencies(kind)]
    clock_key = {"kind": kind, "period": scope["period"], "days": scope["window_days"], "timezone": timezone_name,
                 "date": datetime.fromisoformat(scope["actual_end"]).astimezone(ZoneInfo(timezone_name)).date().isoformat(),
                 "start": scope["window_start"], "explicit_cutoff": scope["cutoff_time"]}
    bounds = cached(repo, "body-metric-view-clock-1", clock_key,
                    lambda: {key: arguments[key] for key in ("window_start", "window_end", "cutoff_time")},
                    dependencies=dependencies, max_age_seconds=WORKSPACE_CACHE_SECONDS)
    arguments.update(bounds)
    metric = analyze_body_metric(repo, kind, **arguments)
    streams = (metric.get("value") or {}).get("streams", [])
    if not model_only:
        selected_source = _source_selection(repo, kind, {row["source"] for row in streams if row.get("source")})
    if selected_source:
        metric = analyze_body_metric(repo, kind, source_filter=[selected_source], **arguments)
        streams = (metric.get("value") or {}).get("streams", [])
    st.caption(local_window_label(arguments["window_start"], arguments["window_end"], timezone_name))
    if not streams:
        st.info("所选范围与来源未见有效记录。可以调整范围或在设置中查看导入情况。")
    for index, stream in enumerate(streams):
        current = stream.get("current") or {}
        previous = stream.get("previous") or {}
        unit = current.get("unit") or spec["unit"]
        change = stream.get("absolute_change")
        if not model_only:
            st.write(source_name(stream.get("source")))
            value = current.get("value")
            if isinstance(value, (int, float)):
                delta = ("较前期 " + format_measurement(change, unit, kind=kind, signed=True)
                         if change is not None else None)
                st.metric(spec["title"], format_measurement(value, unit, kind=kind), delta=delta,
                          delta_color="off", delta_arrow="off")
            elif stream.get("points"):
                latest = stream["points"][-1]
                st.metric("最近实际观察", format_measurement(latest["value"], unit, kind=kind))
                st.caption(f"观察于 {latest.get('observed_at') or latest['date']}，当前日期尚未完整。")
            st.caption(f"完整日记录 {current.get('recorded_days', 0)}/{current.get('window_days', 0)} 天 · 日代表值中位数 · 原始样本数 {current.get('raw_record_count', 0)}")
            if current.get("recorded_total") is not None:
                st.write("本期完整日期的已记录合计 " + format_measurement(current["recorded_total"], unit, kind=kind) + "。")
            if current.get("partial_daily_points"):
                st.caption(f"另有 {len(current['partial_daily_points'])} 个部分日期的观察点，图表保留这些点。")
            _metric_chart(stream, unit, kind + str(index), timezone_name=timezone_name, kind=kind)
        elif scope["with_model"]:
            _metric_chart(stream, unit, "long_" + kind + str(index), timezone_name=timezone_name, kind=kind)
        if scope["with_model"]:
            _model_summary(stream.get("trend") or {}, unit, kind=kind)
        if not model_only:
            with st.expander("相关记录与比较条件", expanded=False):
                st.caption(local_window_label(arguments["window_start"], arguments["window_end"], timezone_name))
                st.write("前期中位数：" + format_measurement(previous.get("value"), unit, kind=kind))
                points = stream.get("points", [])
                page = st.number_input("明细页", min_value=1, max_value=max(1, (len(points)+49)//50), value=1, key=f"detail_page:{kind}:{index}")
                shown = points[(page-1)*50:page*50]
                st.dataframe([{ "日期": p.get("date"), "观测时间": _point_time(p), "数值": display_value(p.get("value"), unit, kind), "单位": display_unit(unit, kind),
                               "样本数": p.get("sample_count"), "情境": p.get("context", stream.get("protocol"))} for p in shown], hide_index=True)
                st.caption(f"本页最多 50 条，共 {len(points)} 个观察点。计算使用全部适用记录。")
                st.write(spec.get("note", ""))
                _observation_details(stream, unit)
                if stream.get("sensitivity"):
                    sensitivity = stream["sensitivity"]
                    st.write(sensitivity.get("scope", ""))
                    if sensitivity.get("difference") is not None:
                        st.write(f"相同星期组成核对后差值 {sensitivity['difference']:+g} {unit}。")
    if not model_only:
        st.write("下一步")
        st.write(spec.get("next_step") or "沿用相同来源和测量条件继续记录，并结合实际活动与症状查看相关日期。")
        _render_exclusions(metric.get("exclusions") or [])
        for note in metric.get("limitations", [])[:3]:
            st.caption(str(note))
        st.button("查看相关问题分析", key="body_question:" + kind, on_click=_open_question, args=(spec["workflow"],))
        from healthzip.ui.topic_sources import render_topic_sources
        render_topic_sources("BODY-OBS-" + kind)


def _open_question(question_id):
    st.session_state["review_section"] = "问题分析"
    st.session_state["review_question"] = question_id
    open_workspace("复盘")


def _observation_details(stream, unit):
    estimates, events = [], []
    for point in stream.get("points", []):
        support = point.get("estimate_support")
        if support:
            estimates.append({"发布日期": point.get("observed_at"), "支持起点": support.get("start"), "支持终点": support.get("end"),
                              "与前次窗口重叠": support.get("overlaps_prior_window"), "算法报告上限（米）": support.get("upper_limit_m"),
                              "位于报告上限": support.get("at_reportable_limit"), "方法": support.get("method"), "算法版本": support.get("algorithm_version")})
        for observation in point.get("observations", []):
            if observation.get("category") is not None:
                events.append({"实际时间": _point_time(point) if observation.get("event_time_precision") == "calendar_day" else observation.get("event_start"), "来源报告类别": observation["category"]})
    if estimates:
        st.write("估计支持窗口与发布身份")
        st.dataframe(estimates, hide_index=True)
    if events:
        st.dataframe(events, hide_index=True)
    regularity = stream.get("regularity")
    if regularity:
        st.write("睡眠时点与有效睡醒状态")
        mean = regularity.get("observed_start_circular_mean_minutes")
        if mean is not None:
            minute = round(mean) % 1440
            st.write(f"已观察睡眠开始的周期平均时点 {minute // 60:02d}:{minute % 60:02d}，来自 {regularity.get('episode_count', 0)} 次睡眠事件。")
        st.write(f"相隔 24 小时的有效状态对 {regularity.get('paired_minutes', 0):g} 分钟；未知或冲突部分 {regularity.get('unpaired_minutes', 0):g} 分钟。")
        if regularity.get("sri") is not None:
            st.write(f"完整范围 SRI：{regularity['sri']:.1f}。")
        else:
            st.caption("当前未提供完整范围 SRI。" + regularity.get("reason", ""))
        if regularity.get("observed_pair_sri") is not None:
            st.write(f"仅有效状态对的条件统计：{regularity['observed_pair_sri']:.1f}。" + regularity.get("observed_pair_scope", ""))
        hours = regularity.get("paired_clock_hour_minutes", {})
        if hours:
            st.dataframe([{"本地时钟小时": int(hour), "有效配对分钟": minutes} for hour, minutes in hours.items()], hide_index=True)
        if regularity.get("unpaired_anchor_ranges"):
            st.dataframe([{"排除起点": row[0], "排除终点": row[1]} for row in regularity["unpaired_anchor_ranges"]], hide_index=True)
    layers = stream.get("change_layers") or {}
    if layers:
        quartiles = layers.get("historical_quartiles")
        if quartiles:
            st.write(f"前置个人记录的四分位数为 {', '.join(f'{x:g}' for x in quartiles)} {unit}。")
        st.caption("重复测量误差依据" + ("已提供。" if layers.get("exceeds_repeatability_limit") is not None else "尚未提供相匹配的设计与界限。"))
        st.caption("独立目标幅度" + ("已提供。" if layers.get("meets_independent_goal_magnitude") is not None else "尚未设定。"))
        for evidence_key, label, conclusion_key in (("measurement_evidence", "重复测量误差", "exceeds_repeatability_limit"),
                                                   ("goal_evidence", "预先设定的目标幅度", "meets_independent_goal_magnitude")):
            evidence = layers.get(evidence_key)
            if evidence:
                st.write(f"{label}依据：{evidence['source']}；相匹配的界限 {evidence['threshold']:g} {evidence['unit']}。")
                st.caption("当前观察差值" + ("达到该幅度。" if layers.get(conclusion_key) else "未达到该幅度。"))


def _metric_chart(stream, unit, key, *, timezone_name="Asia/Shanghai", kind=None):
    import plotly.graph_objects as go
    points = [p for p in stream.get("points", []) if isinstance(p.get("value"), (float, int))]
    if not points:
        return
    if len(points) > 400:
        from healthzip.ui.body_pages import display_points
        display = [{"日期": _plot_time(point, timezone_name), "来源": "本期", "value": point["value"], "point": point} for point in points]
        shown = [row["point"] for row in display_points(display, "value", limit=400)]
        st.caption(f"图表显示 {len(shown)}/{len(points)} 个观察点，统计使用全部有效记录。")
    else:
        shown = points
    figure = go.Figure(go.Scatter(x=[_plot_time(p, timezone_name) for p in shown], y=[display_value(p["value"], unit, kind) for p in shown], mode="markers", name="实际观测",
        customdata=[[p.get("sample_count", 1)] for p in shown],
        hovertemplate="%{x}<br>%{y:.2f} " + display_unit(unit, kind) + "<br>样本数 %{customdata[0]}<extra></extra>"))
    trend = stream.get("trend") or {}
    fitted = trend.get("fitted_points", [])
    if trend.get("status") == "estimated" and fitted:
        figure.add_trace(go.Scatter(x=[p["date"] for p in fitted], y=[display_value(p["value"], unit, kind) for p in fitted], mode="lines", name="计算条件均值"))
    moments = list(dict.fromkeys(_plot_time(point, timezone_name) for point in shown))
    figure.update_xaxes(type="date", tickformat="%m-%d")
    if len(moments) <= 5:
        figure.update_xaxes(tickmode="array", tickvals=moments, ticktext=[value[:16].replace("T", " ") for value in moments])
    figure.update_layout(height=270, yaxis_title=display_unit(unit, kind), margin={"l": 12, "r": 12, "t": 16, "b": 32})
    st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False}, key="body_metric:" + key)


def _model_summary(trend, unit, *, kind=None):
    if trend.get("status") == "estimated":
        interval = trend.get("interval") or []
        st.write(f"计算趋势 {display_value(trend['slope_per_day'], unit, kind):+.3g} {display_unit(unit, kind)}/天，期间估计变化 " + format_measurement(trend.get('estimated_change', 0), unit, kind=kind, signed=True) + "。")
        if len(interval) == 2:
            st.caption(f"斜率区间 [{display_value(interval[0], unit, kind):.3g}, {display_value(interval[1], unit, kind):.3g}] {display_unit(unit, kind)}/天。模型估计条件均值，页面期间代表值另按所示统计口径计算。")
        with st.expander("模型方法与诊断"):
            st.write(trend.get("method", "实际经过时间趋势与一阶相关误差"))
            render_diagnostics(trend.get("diagnostics", {}))
            for note in trend.get("limitations", []):
                st.caption(note)
    else:
        st.caption("本范围保留观察点和描述性变化。" + str(trend.get("reason") or "当前记录不适合该连续日型趋势模型。"))


def render_diagnostics(diagnostics):
    """Expose model checks using readable labels rather than internal mappings."""
    labels = {
        "records": "可比日期数", "elapsed_days": "实际跨度（天）", "max_gap_days": "最大观测间隔（天）",
        "adjacent_pairs": "相邻日期对数", "rho": "一日误差相关估计", "residual_sd": "残差标准差",
        "max_leave_one_innovation_change": "单个观测影响的最大变化", "max_leverage": "最大杠杆值",
        "quadratic_residual_fraction": "弯曲结构的残差比例", "midperiod_step_residual_fraction": "前后阶段的残差比例",
        "residual_lag_order_corr": "白化残差顺序相关", "spread_trend_p": "波动随时间变化的检验概率",
    }
    if diagnostics.get("scope"):
        st.caption("模型适用日期：" + " — ".join(diagnostics["scope"]))
    rows = [{"检查项目": label, "结果": f"{diagnostics[key]:.5g}"} for key, label in labels.items()
            if isinstance(diagnostics.get(key), (int, float))]
    if rows:
        st.dataframe(rows, hide_index=True)
    gaps = diagnostics.get("example_gap_transitions")
    if gaps:
        st.caption("缺日保留真实日历间隔，跨间隔误差相关按估计的一日相关推导。")
        st.dataframe([{"间隔天数": int(gap), "跨间隔误差相关": value} for gap, value in gaps.items()], hide_index=True)
    st.caption("这些是模型适用性检查，不是健康异常界限；估计仍依赖线性、平稳和残差假设。")


def _point_time(point):
    observations = point.get("observations") or []
    if observations and all(row.get("event_time_precision") == "calendar_day" for row in observations):
        return point.get("date", "") + "（仅日期，未记录具体时刻）"
    return point.get("observed_at") or point.get("date")


def _render_exclusions(exclusions):
    if not exclusions:
        return
    reasons = {
        "increment_spans_calendar_days_daily_allocation_unknown": "跨本地日期，无法可靠分配到每天",
        "sound_interval_spans_midnight_energy_split_unknown": "声音区间跨午夜，无法可靠拆分声能",
        "conflicting_daily_summary": "同日来源摘要冲突", "ambiguous_cumulative_and_incremental_support": "累计与增量记录的支持范围不明确",
        "overlapping_support_unresolved": "观察支持区间重叠，无法可靠去重", "sound_duration_required": "缺少声音暴露持续时间",
        "nonnegative_quantity_required": "来源数量应为非负值", "metric_identity_or_numeric_unit_unverified": "指标身份或数值单位未能核实",
        "source_definition_requires_positive_recovery_count": "与来源恢复量的正数定义不符", "value_or_unit_unverified": "数值或单位未能核实",
        "unknown_stand_hour_category": "来源站立类别未识别", "category_unavailable": "未提供有效类别",
        "overlapping_incremental_intervals": "增量观察区间重叠，避免重复累计",
        "overlapping_noise_intervals": "声音暴露区间重叠，无法按独立时段汇总",
    }
    with st.expander(f"未纳入汇总的记录 · {len(exclusions)} 条"):
        st.caption("这些记录保留原始事实；排除日汇总不表示事件没有发生。")
        rows = []
        for item in exclusions:
            observation = item.get("observation") or {}
            reason = item.get("reason", "")
            rows.append({"原因": reasons.get(reason, reason), "观察开始": observation.get("event_start") or observation.get("start"),
                         "观察结束": observation.get("event_end") or observation.get("end"), "原值": observation.get("value"),
                         "单位": observation.get("unit"), "来源": observation.get("source")})
        st.dataframe(rows, hide_index=True)


def _plot_time(point, timezone_name="Asia/Shanghai"):
    observed = _point_time(point)
    if "（仅日期" in observed or len(observed) == 10:
        return point.get("date")
    # Plotly axes use the analysis clock. Original instants remain in facts and
    # detail rows; a single point gets an explicit tick rather than microseconds.
    return datetime.fromisoformat(observed).astimezone(ZoneInfo(timezone_name)).replace(tzinfo=None).isoformat()


def local_window_label(start, end, timezone_name):
    zone = ZoneInfo(timezone_name)
    first = datetime.fromisoformat(start).astimezone(zone)
    last = datetime.fromisoformat(end).astimezone(zone)
    return f"{first:%Y-%m-%d %H:%M} — {last:%Y-%m-%d %H:%M} · {timezone_name}（不含结束时刻）"
