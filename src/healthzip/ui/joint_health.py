"""Readable joint observations from the shared canonical snapshot."""

import streamlit as st

from healthzip.analytics.health_context import joint_observations as joint_observations
from healthzip.analytics.health_context import sleep_comparison_metric
from healthzip.ui.health_comparison import render_comparison


def render_joint_health(snapshot, *, key="joint", charts=False):
    observations = joint_observations(snapshot)
    if not observations["context"].get("daily_points"):
        return
    st.markdown("**同一时间窗内的身体与训练记录**")
    for text in observations["statements"]:
        st.write(text)
    if charts:
        for mid, label, unit, scale in (("STATE-RHR", "日静息心率", "bpm", 1),
                                      ("STATE-SDNN", "SDNN", "ms", 1),
                                      ("REPORT-STATE-SUMMARY", "已记录睡眠", "小时", 60)):
            metric = snapshot.get("metrics", {}).get(mid, {})
            if mid == "REPORT-STATE-SUMMARY":
                metric = sleep_comparison_metric(metric)
            render_comparison(metric, label, unit, scale=scale, key=key + mid)
    st.caption("睡眠按观测事件结束的本地日期与当日心率记录对齐；日值不能证明心率采样一定在醒来后。不同月份的记录不会被拼成同步变化。")
    st.markdown("**下一步**")
    for step in observations["next_steps"]:
        st.write(step)
    with st.expander("核对共同日期与已记录背景"):
        rows = []
        labels = {"STATE-RHR": "RHR（bpm）", "STATE-SDNN": "SDNN（ms）", "sleep": "已记录睡眠（分钟）",
                  "STATE-FATIGUE": "主观疲劳原值", "STATE-SORENESS": "酸痛原值", "STATE-PAIN": "疼痛原值"}
        for point in observations["context"]["daily_points"]:
            row = {"日期": point["date"]}
            for mid, label in labels.items():
                row[label] = "；".join(str(item.get("value")) for item in point["facts"].get(mid, [])) or "未记录"
            count = len(point["facts"].get("training", []))
            row["已记录训练场数"] = str(count) if count else "未记录"
            rows.append(row)
        st.dataframe(rows, hide_index=True, use_container_width=True)
        st.caption("多来源数值并列保留，不合成为恢复分；未记录不等于没有症状、没有训练或没有睡眠。")
