"""Workout records and calendar totals, without inferring energy expenditure."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st

from healthzip.analytics.workouts import summarize_workouts, workout_inventory


def _number(value, divisor=1):
    return "未记录" if value is None else f"{value / divisor:,.1f}"


def render_workouts(repo, timezone_name="Asia/Shanghai"):
    inventory = workout_inventory(repo, timezone_name)
    rows = inventory["rows"]
    st.subheader("运动记录")
    st.caption("查看运动记录；按运动开始时间统计。"
               f"时区：{timezone_name}。记录缺失不代表没有运动。")
    if inventory["undated_count"]:
        st.info(f"另有 {inventory['undated_count']} 条运动缺少可靠的开始时间，未纳入日期汇总。")
    if not rows:
        st.info("尚无可按日期查看的运动记录。")
        return

    years = sorted({row["local_date"].year for row in rows}, reverse=True)
    selected_year = st.selectbox("年份", [str(year) for year in years] + ["全部年份"], key="workout_year")
    today = datetime.now(ZoneInfo(timezone_name)).date()
    if selected_year == "全部年份":
        first, last = min(row["local_date"] for row in rows), max(row["local_date"] for row in rows)
    else:
        first, last = date(int(selected_year), 1, 1), date(int(selected_year), 12, 31)
    default_end = today if selected_year == str(today.year) else last
    bounds = st.date_input("日期范围", value=(first, default_end), min_value=first, max_value=last,
                           key=f"workout_dates_{selected_year}")
    future_count = sum(row["local_date"] > today and (selected_year == "全部年份" or
                       row["local_date"].year == int(selected_year)) for row in rows)
    if future_count:
        st.info(f"有 {future_count} 条运动日期晚于今天（{today.isoformat()}），请核对记录时间。")
    if len(bounds) != 2:
        st.info("请选择开始和结束日期。")
        return
    labels = {"按周": "week", "按月": "month", "按年": "year"}
    period = labels[st.radio("汇总方式", list(labels), horizontal=True, key="workout_period")]
    summary = summarize_workouts(rows, period, *bounds)
    totals = summary["totals"]
    st.caption(f"查看范围：{bounds[0].isoformat()} 至 {bounds[1].isoformat()}（含首尾日期）。")
    columns = st.columns(4)
    columns[0].metric("运动次数", totals["workout_count"])
    columns[1].metric("已记录时长（小时）", _number(totals["duration_seconds"], 3600))
    columns[2].metric("记录能量（kcal）", _number(totals["energy_kcal"]))
    columns[3].metric("能量缺失（次）", totals["missing_energy_count"])
    st.caption(f"时长缺失 {totals['missing_duration_count']} 次；能量缺失 {totals['missing_energy_count']} 次。"
               "设备记录的消耗能量，仅累计已有有效记录。")
    if totals["suspected_duplicate_count"]:
        st.info(f"本范围有 {totals['suspected_duplicate_count']} 次运动标记为可能重复，仍保留原记录，汇总可能受影响。")
    if not summary["rows"]:
        st.info("所选日期范围没有运动记录。")
        return

    periods = summary["periods"]
    st.write("周期汇总")
    st.dataframe([{
        "周期": item["period_label"],
        "实际筛选日期": f"{item['selected_start']} 至 {item['selected_end']}",
        "周期范围": "筛选仅含部分日期" if item["partial_period"] else "筛选包含整周期",
        "运动次数": item["workout_count"],
        "记录时长（分钟）": item["duration_seconds"] / 60 if item["duration_seconds"] is not None else None,
        "时长缺失（次）": item["missing_duration_count"],
        "记录能量（kcal）": item["energy_kcal"], "能量缺失（次）": item["missing_energy_count"],
    } for item in periods], hide_index=True, use_container_width=True)
    st.caption("周期标签只说明筛选覆盖的日期，不表示记录完整或周期已经结束。"
               "仅列出有记录的周期；未列出的周期不表示没有运动。部分周期不能直接与完整周期比较总量。")
    chart_labels = {"运动次数": ("workout_count", 1), "记录时长（分钟）": ("duration_seconds", 60),
                    "记录能量（kcal）": ("energy_kcal", 1)}
    chart = st.selectbox("图表内容", list(chart_labels), key="workout_chart")
    field, divisor = chart_labels[chart]
    values = [item[field] / divisor if item[field] is not None else None for item in periods]
    if any(value is not None for value in values):
        st.bar_chart({"周期": [item["period_label"] for item in periods], chart: values},
                     x="周期", y=chart)
    else:
        st.info("所选周期没有可绘制的该项记录。")

    st.write("运动明细")
    st.dataframe([{
        "开始时间（本地）": item["local_start"].strftime("%Y-%m-%d %H:%M:%S %z"),
        "运动类型": item["activity_name"],
        "记录时长（分钟）": item["duration_seconds"] / 60 if item["duration_seconds"] is not None else None,
        "记录能量（kcal）": item["energy_kcal"], "设备或应用来源": item["source_name"] or "未记录",
    } for item in summary["rows"]], hide_index=True, use_container_width=True)
    with st.expander("统计口径"):
        st.caption("默认显示最近有记录的年份；当前年份默认截至所选时区今天，历史年份默认全年。"
                   "日期仍可自行调整，包含首尾，按本地开始时间归类。"
                   "周从周一开始，跨年周使用 ISO 周年。仅统计当前有效记录，不纳入已删除或已替代的版本。")
        st.caption("合计只含有有效记录的部分，全部缺失时显示“未记录”；记录值 0 保留为 0。"
                   "时长使用原有记录，不根据开始与结束时间补算。")
        st.caption("能量来自 Workout 总能量字段；该字段无有效值时，仅采用唯一、无冲突的整场活动能量统计。"
                   "重复相同统计只取一次，不累加分段或冲突统计。kJ 换算为 kcal，未知单位保持缺失。")
        st.caption("不与日常健康样本中的活动能量相加。设备记录能量不等于真实代谢或全天总消耗（TEE）。")
