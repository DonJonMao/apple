"""Render the versioned MetricResult comparison without recomputing statistics."""

from __future__ import annotations

import streamlit as st

from healthzip.analytics.health_context import (
    comparison_statements as comparison_statements,
)
from healthzip.analytics.health_context import (
    coverage_label,
    period_label,
)


def comparison_next_steps(metric, domain):
    streams = metric.get("comparison", {}).get("streams", [])
    steps = []
    if len(streams) > 1:
        steps.append("当前有多个来源或测量条件；先用来源筛选分别查看，并核对设备版本、采样时段与主动测量记录。")
    for stream in streams:
        current = stream.get("current", {})
        missing = current.get("missing_dates", [])
        if missing:
            dates = "、".join(missing[:2])
            steps.append(f"先核对 {dates} 的{'电量、睡眠跟踪设置与区间覆盖' if domain == 'sleep' else '记录来源与采样情况'}；缺测日期保持空白。")
            break
    if not steps:
        if domain == "sleep":
            steps.append("打开每晚区间核对观测起止与来源；记录终点可能是跟踪停止，若知道实际醒来时间可在复盘补充睡眠声明。")
        else:
            steps.append("核对本期与对照期的采样时段、主动呼吸练习和设备是否一致，再用相近条件继续观察。")
    return steps[:3]


def _stream_name(stream):
    from healthzip.ui.body_pages import source_name
    return source_name(stream.get("protocol") or stream.get("stream_id"))


def compact_period_label(summary):
    label = period_label(summary)
    parts = label.split(" 至 ")
    if len(parts) == 2 and parts[0][:4] == parts[1][:4]:
        return parts[0][5:].replace("-", "/") + "–" + parts[1][5:].replace("-", "/")
    return label


def sampling_description(point):
    times = sorted(item.get("local_time", "")[11:16] for item in point.get("observations", [])
                   if item.get("local_time"))
    conditions = point.get("conditions") or {}
    labels = {"sampling_mode": "采样", "measurement_context": "情境", "breathing_context": "呼吸练习",
              "posture": "体位", "activity_context": "活动", "recording_duration_seconds": "记录秒数",
              "os_version": "系统版本", "algorithm_version": "算法版本"}
    translations = {"background": "后台", "active": "主动", "unknown": "未知"}
    known = []
    for field, title in labels.items():
        value = conditions.get(field)
        if isinstance(value, dict):
            value = value.get("value")
        if value is not None:
            known.append(title + "：" + translations.get(str(value), str(value)))
    if times:
        known.insert(0, "采样时段 " + times[0] + ("–" + times[-1] if times[-1] != times[0] else ""))
    return "；".join(known) or "测量情境未记录"


def _chart(stream, title, unit, scale, key):
    import plotly.graph_objects as go

    figure = go.Figure()
    raw_count, displayed_count = 0, 0
    for period, field, name, color in (("previous", "daily_points", "前期", "#94A7D6"),
            ("current", "daily_points", "本期", "#38BFA3"),
            ("current", "partial_daily_points", "本期未完整日期", "#D6B376")):
        points = stream.get(period, {}).get(field, [])
        points = [point for point in points if point.get("value") is not None]
        if not points:
            continue
        raw_count += len(points)
        if len(points) > 400:
            from healthzip.ui.body_pages import display_points
            display = [{"日期": point["date"], "来源": name, "value": point["value"], "point": point}
                       for point in points]
            points = [row["point"] for row in display_points(display, "value", limit=400)]
        displayed_count += len(points)
        # Markers preserve real observations and never bridge a missing date.
        figure.add_trace(go.Scatter(x=[p["date"] for p in points],
            y=[p["value"] / scale for p in points], mode="markers", name=name,
            marker={"color": color, "size": 8},
            customdata=[[p.get("n", p.get("raw_record_count", len(p.get("source_ids", [])))),
                         sampling_description(p)]
                        for p in points],
            hovertemplate="%{x}<br>" + title + "：%{y:.1f} " + unit +
                "<br>原始记录数：%{customdata[0]}<br>采样条件：%{customdata[1]}<extra>%{fullData.name}</extra>"))
    if not figure.data:
        return
    current = stream.get("current", {}).get("window", {})
    if current.get("start") and current.get("end"):
        figure.add_vrect(x0=current["start"], x1=current["end"], fillcolor="#38BFA3",
                         opacity=0.06, line_width=0, layer="below")
    figure.update_layout(height=260, margin={"t": 12, "b": 32, "l": 12, "r": 12},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "system-ui, sans-serif", "color": "#F1F5F9"},
        legend={"orientation": "h", "y": -0.22},
        xaxis={"type": "date", "tickformat": "%m/%d", "showgrid": False},
        yaxis={"title": unit, "gridcolor": "#2B3543", "zeroline": False})
    st.plotly_chart(figure, use_container_width=True, key=key,
                    config={"displayModeBar": False, "scrollZoom": False})
    if displayed_count < raw_count:
        st.caption(f"图表显示 {displayed_count}/{raw_count} 个真实日值，保留首末与局部高低点；统计仍使用全部日值。")


def render_comparison(metric, title, unit, *, scale=1, key="health", chart=True):
    """Return false for historical contracts; callers retain their frozen presentation."""
    comparison = metric.get("comparison", {})
    streams = comparison.get("streams", [])
    if not streams:
        return False
    for index, stream in enumerate(streams):
        current = stream.get("current", {})
        if len(streams) > 1:
            st.markdown(f"**{title} · {_stream_name(stream)} · 条件组 {index + 1}**")
        else:
            st.caption("来源：" + _stream_name(stream))
        if current.get("value") is None:
            partial = current.get("partial_daily_points", [])
            if partial:
                st.write(f"{period_label(current)} 已有{title}观测，尚无完整日汇总；下方单列截至当前的记录。")
            else:
                st.write(f"{period_label(current)} 尚无可用的完整日{title}记录；已知前期与参考记录单独保留。")
        previous = stream.get("previous", {})
        value, prior = current.get("value"), previous.get("value")
        delta = f"较前期 {(value-prior)/scale:+.1f} {unit}" if value is not None and prior is not None else None
        st.metric(title, "暂无完整日" if value is None and current.get("partial_daily_points") else
                  "暂无记录" if value is None else f"{value / scale:.1f} {unit}", delta=delta,
                  delta_color="off", delta_arrow="off")
        st.caption(f"{compact_period_label(current)} · {coverage_label(current)} · 日代表值中位数")
        for point in current.get("partial_daily_points", []):
            st.caption(f"未完整日期 {point['date']}：已观察日代表值 {point['value'] / scale:.1f} {unit}，"
                       f"{sampling_description(point)}；单列展示，不进入完整日比较。")
        if chart:
            _chart(stream, title, unit, scale, key + "_" + str(index))
        current_q = current.get("quartiles")
        previous_q = stream.get("previous", {}).get("quartiles")
        ranges = []
        for quantiles, label in ((current_q, "本期"), (previous_q, "前期")):
            if quantiles and len(quantiles) >= 3:
                ranges.append(f"{label}中间一半日值 {quantiles[0] / scale:.1f}–{quantiles[2] / scale:.1f} {unit}")
        if ranges:
            st.caption("；".join(ranges) + "。这是个人历史观察分布。")
        previous = stream.get("previous", {})
        if current.get("window_days") and previous.get("window_days"):
            current_fraction = current.get("recorded_days", 0) / current["window_days"]
            previous_fraction = previous.get("recorded_days", 0) / previous["window_days"]
            if current_fraction != previous_fraction:
                st.caption("两期记录覆盖不同，数值各自描述实际有记录的日期，代表性不能直接视为相同。")
        with st.expander(f"比较依据 · {title} · {_stream_name(stream)} · {index + 1}"):
            for column, period, label in zip(st.columns(3), ("current", "previous", "reference"),
                                              ("本期", "前期", "个人历史参考")):
                summary = stream.get(period, {})
                value = summary.get("value")
                column.metric(label + title, "暂无完整日" if value is None else f"{value / scale:.1f} {unit}")
                column.caption(f"{period_label(summary)} · {coverage_label(summary)}")
            st.caption("各日先取同条件日代表值，再以日为单位取期间中位数。当前未结束日期单列，不进入完整日比较；个人参考仅使用本期之前的日期。")
            for period, label in (("current", "本期"), ("previous", "前期"), ("reference", "个人参考")):
                summary = stream.get(period, {})
                st.write(f"{label}：{period_label(summary)} · {coverage_label(summary)}")
                if summary.get("missing_dates"):
                    st.caption("未记录日期：" + "、".join(summary["missing_dates"]))
                if summary.get("weekday_counts"):
                    st.caption("有记录日期组成（星期一至日）：" + str(summary["weekday_counts"]))
            for limitation in stream.get("limitations", []):
                st.caption(str(limitation))
            protocol = stream.get("protocol") or []
            if len(protocol) >= 4:
                st.caption(f"设备：{protocol[1] or '未记录'} · 协议：{protocol[2] or '未知'} · 来源版本：{protocol[3] or '未记录'}。同设备不证明测量协议一致。")
            st.caption("计算口径：" + comparison.get("statistic_kind", "median") + " · " + comparison.get("version", "未注明"))
    return True
