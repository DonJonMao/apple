"""Local health and training workbench with five top-level destinations."""
from __future__ import annotations

import sqlite3
from time import perf_counter
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

from healthzip.config import DEFAULT_DB_PATH
from healthzip.db.repository import Repository
from healthzip.ui.navigation import PAGES, current_route, initialize_navigation
from healthzip.ui.overview import render_overview
from healthzip.ui.theme import apply_theme, render_footer, render_header

st.set_page_config(page_title="HealthZIP · 健康与训练", layout="wide", initial_sidebar_state="collapsed")
apply_theme()
st.session_state.setdefault("database_path", str(DEFAULT_DB_PATH))
st.session_state.setdefault("analysis_timezone", "Asia/Shanghai")
st.session_state.setdefault("analysis_window_days", 30)
initialize_navigation()
page = render_header(PAGES)
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
        elif page == "训练":
            st.session_state.setdefault("training_section", "本次训练")
            section = st.radio("训练内容", ["本次训练", "动作进展", "运动记录"], horizontal=True, key="training_section")
            if section == "本次训练":
                from healthzip.ui.training_page import render_training
                render_training(repo)
            elif section == "动作进展":
                from healthzip.ui.sequence_review import render_exercise_progress
                render_exercise_progress(repo)
            else:
                from healthzip.ui.body_workspace import range_controls
                from healthzip.ui.workout_page import render_workouts
                scope = range_controls(timezone_name)
                render_workouts(repo, timezone_name=timezone_name, period=scope["period"], window_days=scope["window_days"],
                                window_start=scope["window_start"], cutoff_time=scope["cutoff_time"])
        elif page == "复盘":
            from healthzip.ui.review_page import render_review
            render_review(repo, timezone_name=timezone_name)
        elif page == "身体":
            from healthzip.ui.body_workspace import render_body
            render_body(repo, timezone_name=timezone_name)
    except (sqlite3.Error, OSError, RuntimeError) as exc:
        st.error(f"这次读取未完成，{exc}。已保存记录仍可恢复，请重试。")
        if st.button("重新读取当前页面", key="page_retry"):
            st.rerun()
    finally:
        if repo is not None:
            repo.close()
        st.session_state["page_timing"] = {"workspace": page, "server_seconds": perf_counter() - started}
        st.markdown(f'<span hidden data-hz-render="{uuid4()}" data-workspace="{current_route(page)}" '
                    f'data-server-ms="{st.session_state["page_timing"]["server_seconds"] * 1000:.3f}"></span>',
                    unsafe_allow_html=True)
route = current_route(page)
if st.query_params.get("workspace") != route:
    st.query_params["workspace"] = route
render_footer()
