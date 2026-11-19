"""Readable daily body records, separate from canonical scientific results."""

from __future__ import annotations

import ast
import math
from collections import Counter, defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st

try:
    import plotly.express as px
except ImportError:  # pragma: no cover - optional UI dependency
    px = None


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) else None


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def source_name(value):
    """Read the declared name from a canonical stream key without showing IDs."""
    source = value
    if isinstance(value, str):
        try:
            source = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            source = value
    if isinstance(source, (tuple, list)):
        source = source[0] if source else None
    if not isinstance(source, str) or not source.strip():
        return "来源未注明"
    if source.startswith(("unknown_source:", "health_sample:", "body_measurement:")):
        return "来源未注明"
    return source.strip()


def _source_labels(keys):
    keys = list(dict.fromkeys(keys))
    names = {key: source_name(key) for key in keys}
    counts = Counter(names.values())
    positions = Counter()
    labels = {}
    for key in keys:
        name = names[key]
        positions[name] += 1
        labels[key] = name if counts[name] == 1 else f"{name}（来源 {positions[name]}）"
    return labels


def heart_rows(view):
    """Daily canonical values with only human-facing columns."""
    metrics = view.get("workspace_scope", {}).get("metrics", {})
    records = []
    for identity, title, unit in (("STATE-RHR", "静息心率", "次/分"),
                                  ("STATE-SDNN", "HRV（SDNN）", "毫秒")):
        for source, points in (metrics.get(identity, {}).get("value") or {}).items():
            for point in points:
                value, day = _number(point.get("value")), _day(point.get("date"))
                if value is not None and day:
                    records.append((day, title, value, unit, source))
    labels = _source_labels(row[4] for row in records)
    return [{"日期": day, "指标": title, "数值": value, "单位": unit, "来源": labels[source]}
            for day, title, value, unit, source in sorted(records)]


def sleep_rows(view):
    """Positive finite sleep observations for this page, without changing metrics."""
    records = []
    for point in view.get("sleep", {}).get("nights", []):
        value, day = _number(point.get("sleep_hours")), _day(point.get("date"))
        if value is not None and value > 0 and day:
            records.append((day, value, point.get("source")))
    labels = _source_labels(row[2] for row in records)
    return [{"日期": day, "睡眠时长（小时）": value, "来源": labels[source]}
            for day, value, source in sorted(records, key=lambda row: (row[0], str(row[2])))]


def sleep_summary(view):
    groups = defaultdict(list)
    for row in sleep_rows(view):
        groups[row["来源"]].append(row)
    return [{"来源": source, "有效记录日期": len({row["日期"] for row in rows}),
             "有效记录条数": len(rows),
             "平均时长（小时）": sum(row["睡眠时长（小时）"] for row in rows) / len(rows)}
            for source, rows in groups.items()]


def weight_rows(view):
    records = []
    for point in view.get("weight", {}).get("daily", []):
        value, day = _number(point.get("kg")), _day(point.get("date"))
        if value is not None and day:
            records.append((day, value, point.get("source")))
    labels = _source_labels(row[2] for row in records)
    return [{"日期": day, "体重（kg）": value, "来源": labels[source]}
            for day, value, source in sorted(records, key=lambda row: (row[0], str(row[2])))]


def latest_weight_rows(view):
    """Historical reference rows remain separate from the selected-window rows."""
    output = []
    for point in view.get("weight", {}).get("latest_observations", []):
        value, day = _number(point.get("value")), _day(point.get("date"))
        if value is not None and day:
            output.append({"日期": day, "体重（kg）": value, "来源": source_name(point.get("source"))})
    return output


def vo2_rows(view):
    output = []
    for point in view.get("vo2", {}).get("points", []):
        value, day = _number(point.get("normalized_value")), _day(point.get("local_date"))
        if value is not None and day:
            output.append({"日期": day, "VO₂ max（mL/kg/min）": value,
                           "来源": source_name(point.get("source_name"))})
    return output


def _window(view):
    scope = view.get("workspace_scope", {})
    zone = scope.get("timezone", "Asia/Shanghai")

    def local(value):
        if not value:
            return "未注明"
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo(zone)).strftime("%Y年%m月%d日 %H:%M")
        except (ValueError, TypeError):
            return "未注明"

    st.caption(f"所选范围：{local(scope.get('window_start'))} 至 {local(scope.get('window_end'))} · 时区：{zone}")
    st.caption(f"数据截止：{local(scope.get('cutoff_time'))}。不同来源和记录条件分开显示。")


def _chart(rows, value, title):
    if rows and px is not None:
        st.plotly_chart(px.line(rows, x="日期", y=value, color="来源", markers=True, title=title),
                        use_container_width=True)


def _details(view):
    with st.expander("记录与计算说明", expanded=False):
        st.write("表格展示已记录的观察值，不代表诊断或完整佩戴记录。缺少记录不能据此推断身体状态。")
        versions = sorted({metric.get("algorithm_version", "未注明") for metric in
                           view.get("workspace_scope", {}).get("metrics", {}).values()})
        if versions:
            st.caption("计算版本：" + "、".join(versions))


def render_heart(view):
    st.subheader("心率与 HRV 记录")
    _window(view)
    rows = heart_rows(view)
    for title, unit in (("静息心率", "次/分"), ("HRV（SDNN）", "毫秒")):
        st.subheader(title)
        selected = [row for row in rows if row["指标"] == title]
        if selected:
            st.caption(f"{len({row['日期'] for row in selected})} 个日期有记录 · 单位：{unit}")
            st.dataframe(selected, hide_index=True, use_container_width=True)
            _chart(selected, "数值", title + f"（{unit}）")
        else:
            st.info("所选范围内没有该指标的可显示记录，可在左侧扩大分析范围。")
    st.caption("HRV 此处展示 SDNN，不能与 RMSSD 混用；不同来源的数值不合并为一个健康分。")
    _details(view)


def render_sleep(view):
    st.subheader("睡眠记录")
    _window(view)
    rows = sleep_rows(view)
    if rows:
        st.caption(f"本范围内有 {len(rows)} 条有效时长记录，覆盖 {len({row['日期'] for row in rows})} 个日期。")
        st.dataframe(rows, hide_index=True, use_container_width=True)
        _chart(rows, "睡眠时长（小时）", "按来源观察到的睡眠时长")
        st.write("各来源的有效记录统计")
        st.dataframe(sleep_summary(view), hide_index=True, use_container_width=True)
    else:
        st.info("所选范围内没有可显示的有效睡眠时长。缺少记录不代表没有睡眠或未佩戴设备。")
    omitted = len(view.get("sleep", {}).get("nights", [])) - len(rows)
    if omitted:
        st.caption(f"另有 {omitted} 条零时长或无效记录，未计入本页有效统计；原始记录保留。")
    st.caption("按睡眠结束日期显示已观察时长，不把它认定为完整整夜睡眠；不同来源分别统计。")
    _details(view)


def _expand_weight_window(days):
    st.session_state["analysis_window_days"] = max(int(st.session_state.get("analysis_window_days", 30)), days)


def render_weight(view):
    st.subheader("体重记录")
    _window(view)
    rows = weight_rows(view)
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
        _chart(rows, "体重（kg）", "按来源记录的体重")
    else:
        latest = latest_weight_rows(view)
        if latest:
            latest_day = max(row["日期"] for row in latest)
            st.info(f"所选范围内无称重记录，最近一次为 {latest_day}。以下为历史参考，不计入当前范围。")
            st.dataframe(latest, hide_index=True, use_container_width=True)
            scope = view.get("workspace_scope", {})
            cutoff = scope.get("cutoff_time")
            if cutoff:
                cutoff_day = datetime.fromisoformat(cutoff.replace("Z", "+00:00")).astimezone(
                    ZoneInfo(scope.get("timezone", "Asia/Shanghai"))).date()
                days = (cutoff_day - date.fromisoformat(latest_day)).days + 1
                if 7 <= days <= 3650:
                    st.button(f"将分析范围扩大到 {days} 天", key="body_weight_expand_window",
                              on_click=_expand_weight_window, args=(days,))
        else:
            st.info("所选范围内无称重记录，尚未找到可显示的历史称重。可在左侧扩大分析范围或导入记录。")
    st.caption("体重受水分、糖原及称量条件影响；记录变化不能区分脂肪与肌肉变化。")
    aerobic = vo2_rows(view)
    st.subheader("有氧适能估计（VO₂ max）")
    if aerobic:
        st.dataframe(aerobic, hide_index=True, use_container_width=True)
        _chart(aerobic, "VO₂ max（mL/kg/min）", "设备记录的有氧适能估计")
    else:
        st.info("目前没有可显示的 VO₂ max 估计记录。")
    st.caption("VO₂ max 是设备估计值；此处保留全部已有估计记录，不按称重分析窗口筛选。")
    _details(view)
