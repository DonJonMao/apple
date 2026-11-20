"""Local health and training workbench with one top-level navigation."""
from __future__ import annotations

import sqlite3
from time import perf_counter
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

from healthzip.analytics.workspaces import analyze_workspace
from healthzip.config import DEFAULT_DB_PATH
from healthzip.db.repository import Repository
from healthzip.ui.body_pages import render_cardio, render_heart, render_sleep, render_weight
from healthzip.ui.overview import render_overview
from healthzip.ui.theme import apply_theme, render_footer, render_header

PAGES = ["总览", "力量", "心率", "睡眠", "体重", "有氧", "运动", "复盘", "设置"]
ALIASES = {"导入与总览": "总览", "心率 / HRV": "心率", "体重 / 有氧": "体重",
           "分析": "复盘", "报告": "复盘"}
ROUTES = dict(zip(PAGES, ["overview", "strength", "heart", "sleep", "weight", "cardio", "workouts", "review", "settings"]))

st.set_page_config(page_title="HealthZIP · 健康与训练", layout="wide", initial_sidebar_state="collapsed")
apply_theme()
st.session_state.setdefault("database_path", str(DEFAULT_DB_PATH))
st.session_state.setdefault("analysis_timezone", "Asia/Shanghai")
st.session_state.setdefault("analysis_window_days", 30)
st.session_state["body_period"] = st.session_state.get("body_period", "近30天")
st.session_state["analysis_window_days"] = st.session_state["analysis_window_days"]
if destination := st.session_state.pop("strength_workspace_next", None):
    st.session_state["main_workspace"] = ALIASES.get(destination, destination)
if "main_workspace" not in st.session_state:
    route = st.query_params.get("workspace")
    st.session_state["main_workspace"] = next((page for page, slug in ROUTES.items() if slug == route), "总览")
selected = st.session_state.get("main_workspace")
st.session_state["main_workspace"] = ALIASES.get(selected, selected) if selected in PAGES or selected in ALIASES else "总览"
page = render_header(PAGES)
if st.query_params.get("workspace") != ROUTES[page]:
    st.query_params["workspace"] = ROUTES[page]
timezone_name = st.session_state["analysis_timezone"]
try:
    ZoneInfo(timezone_name)
except (ZoneInfoNotFoundError, ValueError):
    st.error("分析时区无效，请在设置中选择有效 IANA 时区。")
    if page != "设置":
        st.stop()

if page == "设置":
    from healthzip.ui.settings_page import render_settings
    render_settings()
else:
    started = perf_counter()
    repo = None
    try:
        repo = Repository(st.session_state["database_path"])
        if page == "总览":
            render_overview(repo, timezone_name=timezone_name)
        elif page == "力量":
            from healthzip.ui.training_page import render_training
            render_training(repo)
        elif page == "复盘":
            from healthzip.ui.review_page import render_review
            render_review(repo, timezone_name=timezone_name)
        else:
            st.subheader(page)
            with st.container(key="page_period"):
                period_label = st.radio("查看范围", ["本周", "本月", "近30天", "自定义"],
                                        index=2, horizontal=True, key="body_period", label_visibility="collapsed")
                if period_label == "自定义":
                    st.number_input("最近天数", min_value=1, max_value=3650, key="analysis_window_days")
            period = {"本周": "week", "本月": "month", "近30天": "30d", "自定义": None}[period_label]
            if page == "运动":
                from healthzip.ui.workout_page import render_workouts
                render_workouts(repo, timezone_name=timezone_name, period=period,
                                window_days=int(st.session_state["analysis_window_days"]), show_title=False)
            else:
                analysis = analyze_workspace(repo, page, window_days=int(st.session_state["analysis_window_days"]),
                                             timezone_name=timezone_name, period=period)
                from healthzip.workflows.storage import current_context_problem
                context = st.session_state.get("analysis_contexts", {}).get(str(repo.path.resolve()))
                if current_context_problem(repo, context):
                    st.warning("当前选择的适用声明已撤回或被替换，来源解释须重新确认；记录事实仍可查看。请在复盘的问题分析中确认适用信息。")
                {"心率": render_heart, "睡眠": render_sleep,
                 "体重": render_weight, "有氧": render_cardio}[page](analysis, repo=repo, show_title=False)
    except (sqlite3.Error, OSError, RuntimeError) as exc:
        st.error(f"这次读取未完成：{exc}。已保存记录仍然保留，可以重试。")
        if st.button("重新读取当前页面", key="page_retry"):
            st.rerun()
    finally:
        if repo is not None:
            repo.close()
        # Local session diagnostic only; never records health values or paths.
        st.session_state["page_timing"] = {"workspace": page, "server_seconds": perf_counter() - started}
        st.markdown(f'<span hidden data-hz-render="{uuid4()}" data-workspace="{ROUTES[page]}" '
                    f'data-server-ms="{st.session_state["page_timing"]["server_seconds"] * 1000:.3f}"></span>',
                    unsafe_allow_html=True)
render_footer()
