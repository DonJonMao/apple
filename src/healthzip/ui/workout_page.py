"""Actual activity records, with one temporal window for every visible number."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from healthzip.analytics.workouts import _totals, scoped_workout_inventory, summarize_workouts
from healthzip.ui.body_pages import _cards, _empty, _window


def _number(value, divisor=1):
    return "未记录" if value is None else f"{value / divisor:,.1f}"


def render_workouts(repo, timezone_name="Asia/Shanghai", *, period="30d", cutoff_time=None,
                    window_start=None, window_days=30, show_title=True):
    inventory = scoped_workout_inventory(repo, timezone_name, period=period,
        cutoff_time=cutoff_time, window_start=window_start, window_days=window_days)
    rows = inventory["rows"]
    scope = inventory["workspace_scope"]
    if show_title:
        st.subheader("运动")
    _window(inventory)
    if not rows:
        _empty("所选范围内没有运动记录。可切换上方范围，或在设置导入 Apple Health 运动数据。", "workout")
        return
    totals = _totals(rows)
    _cards([{"label": "运动记录", "value": f"{totals['workout_count']} 次"},
            {"label": "已记录时长", "value": _number(totals["duration_seconds"], 60) + " 分钟"
             if totals["duration_seconds"] is not None else "未记录"},
            {"label": "运动日期", "value": f"{len({row['local_date'] for row in rows})} 天"}])
    chart_labels = {"记录时长（分钟）": ("duration_seconds", 60), "运动次数": ("workout_count", 1),
                    "记录能量（kcal）": ("energy_kcal", 1)}
    chart = st.selectbox("趋势内容", list(chart_labels), key="workout_chart")
    field, divisor = chart_labels[chart]
    daily = defaultdict(list)
    for row in rows:
        daily[row["local_date"]].append(row)
    points = [{"日期": day.isoformat(), chart: _totals(items)[field] / divisor
               if _totals(items)[field] is not None else None}
              for day, items in sorted(daily.items())]
    if any(row[chart] is not None for row in points):
        import plotly.express as px
        figure = px.bar(points, x="日期", y=chart, color_discrete_sequence=["#38BFA3"])
        figure.update_layout(height=290, margin={"t": 12, "b": 32, "l": 12, "r": 12},
                             paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                             font={"color": "#F1F5F9", "family": "system-ui,sans-serif"},
                             xaxis={"title": None, "type": "date", "tickformat": "%m/%d"},
                             yaxis={"gridcolor": "#2B3543"})
        figure.update_traces(hovertemplate="%{x|%Y-%m-%d}<br>%{y:.1f}<extra></extra>")
        st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})
    else:
        st.info("所选范围没有可绘制的该项记录。")
    st.markdown("**本期关键记录**")
    kinds = defaultdict(int)
    for row in rows:
        kinds[row["activity_name"]] += 1
    st.write("、".join(f"{name} {count} 次" for name, count in sorted(kinds.items(), key=lambda item: -item[1])))
    st.caption("仅显示有记录的日期；空白日期不能据此判断没有运动。本期部分日期不与完整上期比较总量。")
    if totals["suspected_duplicate_count"]:
        st.info(f"有 {totals['suspected_duplicate_count']} 条运动被标记为可能重复；原记录仍保留，请在明细核对来源。")
    st.markdown("**下一步**")
    st.write("查看同类运动的时长与记录频率；有氧适能估计可在“有氧”单独查看。")
    with st.expander("原始明细", expanded=False):
        pages = max(1, (len(rows) + 49) // 50)
        page = st.number_input("明细页", 1, pages, 1, key="workout_details_page") if pages > 1 else 1
        st.dataframe([{
            "开始时间（本地）": item["local_start"].strftime("%Y-%m-%d %H:%M:%S %z"),
            "运动类型": item["activity_name"],
            "记录时长（分钟）": item["duration_seconds"] / 60 if item["duration_seconds"] is not None else None,
            "记录能量（kcal）": item["energy_kcal"], "设备或应用来源": item["source_name"] or "未记录",
        } for item in rows[(page - 1) * 50:page * 50]], hide_index=True, use_container_width=True)
        st.caption(f"共 {len(rows)} 条记录，每页最多 50 条。")
    with st.expander("分析依据与范围", expanded=False):
        _window(inventory)
        st.caption(f"时长缺失 {totals['missing_duration_count']} 次；能量缺失 {totals['missing_energy_count']} 次。"
                   "缺失不补零；真实记录的 0 保留为 0。")
        st.caption("时长使用原始记录，不根据起止时间补算。设备报告能量不等于真实代谢或全天总消耗（TEE）。")
        for limitation in scope.get("limitations", []):
            st.caption(limitation)
        zone = ZoneInfo(timezone_name)
        start = datetime.fromisoformat(scope["window_start"]).astimezone(zone).date()
        end = datetime.fromisoformat(scope["window_end"]).astimezone(zone).date()
        summary = summarize_workouts(rows, "week" if period == "week" else "month", start, end)
        st.dataframe([{"周期": item["period_label"],
                       "实际筛选日期": f"{item['selected_start']} 至 {item['selected_end']}",
                       "运动次数": item["workout_count"],
                       "记录时长（分钟）": item["duration_seconds"] / 60 if item["duration_seconds"] is not None else None,
                       "时长缺失（次）": item["missing_duration_count"],
                       "记录能量（kcal）": item["energy_kcal"], "能量缺失（次）": item["missing_energy_count"]}
                      for item in summary["periods"]], hide_index=True, use_container_width=True)
