"""A shared, concise current-data conclusion above each workspace."""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st


def _time(value, timezone_name):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            ZoneInfo(timezone_name)
        ).strftime("%Y-%m-%d %H:%M")
    except (AttributeError, TypeError, ValueError):
        return "时间未注明"


def _value(value):
    if isinstance(value, bool) or value is None:
        return "未记录"
    if isinstance(value, (int, float)):
        return f"{value:,.2f}".rstrip("0").rstrip(".") if math.isfinite(value) else "未记录"
    return value if isinstance(value, str) else "见记录说明"


def render_workspace_summary(repo, workspace, *, timezone_name="Asia/Shanghai", period="week"):
    with st.container(key="workspace_findings"):
        st.markdown("**本期发现**")
        try:
            from healthzip.analytics.workspace_summary import workspace_summary

            summary = workspace_summary(repo, workspace, timezone_name=timezone_name)
        except (ImportError, ValueError, OSError, RuntimeError, sqlite3.Error):
            st.caption("当前分析暂未更新，可继续查看记录或记录训练。")
            return
        selected = next((item for item in summary.get("periods", [])
                         if item.get("period") == period), None)
        if not selected:
            st.caption("当前范围暂无可显示的分析。")
            return
        for conclusion in selected.get("conclusions", [])[:3]:
            st.write(conclusion)
        coverage = selected.get("coverage", {})
        window = selected.get("window", {})
        st.caption(
            f"{selected.get('label', '本期')}：{_time(window.get('start'), timezone_name)}"
            f" 至 {_time(window.get('end'), timezone_name)} · "
            f"有记录日期 {coverage.get('observed_days', 0)} 天"
            f"／本期已历 {coverage.get('window_days', 0)} 天。本期尚未结束。"
        )
        st.caption(f"更新于 {_time(summary.get('cutoff_time'), timezone_name)}；新增或更正记录后自动更新。")
        with st.expander("分析依据与范围", expanded=False):
            for fact in selected.get("facts", []):
                text = f"{fact.get('label', '记录')}：{_value(fact.get('value'))}"
                if fact.get("unit"):
                    text += f" {fact['unit']}"
                if fact.get("source"):
                    text += f" · 来源：{fact['source']}"
                if fact.get("sample_count") is not None:
                    text += f" · {fact['sample_count']} 条有效记录"
                st.write(text)
            for limitation in dict.fromkeys(selected.get("limitations", [])):
                st.caption(limitation)
            st.caption(f"时区：{timezone_name}。按已记录数据作描述性分析，记录缺失保持未知。")
