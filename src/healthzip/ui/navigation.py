"""Five top-level destinations with stable legacy health and training links."""
from __future__ import annotations

import streamlit as st

PAGES = ["总览", "训练", "身体", "复盘", "设置"]
BODY_SECTIONS = ["身体总览", "心率", "有氧", "睡眠", "夜间生理", "活动与行动能力", "体重", "环境", "健康与安全事件"]
ROUTES = {"总览": "overview", "训练": "strength", "身体": "body", "复盘": "review", "设置": "settings",
          "心率": "heart", "睡眠": "sleep", "体重": "weight", "有氧": "cardio", "运动": "workouts",
          "夜间生理": "night", "活动与行动能力": "activity", "环境": "environment",
          "健康与安全事件": "events", "周期与症状": "cycle", "动作进展": "progress"}
ALIASES = {"力量": "训练", "导入与总览": "总览", "心率 / HRV": "心率", "体重 / 有氧": "体重",
           "分析": "复盘", "报告": "复盘"}


def select_destination(destination):
    destination = ALIASES.get(destination, destination)
    if destination == "导入与同步":
        st.session_state["main_workspace"] = "设置"
        st.session_state["settings_section"] = "导入与同步"
    elif destination == "动作进展":
        st.session_state["main_workspace"] = "训练"
        st.session_state["training_section"] = "动作进展"
    elif destination in BODY_SECTIONS or destination == "周期与症状":
        st.session_state["main_workspace"] = "身体"
        st.session_state["body_section"] = destination
    elif destination == "运动":
        st.session_state["main_workspace"] = "训练"
        st.session_state["training_section"] = "运动记录"
    else:
        st.session_state["main_workspace"] = destination if destination in PAGES else "总览"
        if destination == "训练":
            st.session_state["training_section"] = "本次训练"
    st.session_state["mobile_menu_open"] = False


def initialize_navigation():
    pending = st.session_state.pop("strength_workspace_next", None)
    if pending:
        select_destination(pending)
    elif "main_workspace" not in st.session_state:
        route = st.query_params.get("workspace", "overview")
        select_destination(next((page for page, slug in ROUTES.items() if slug == route), "总览"))
    elif st.session_state["main_workspace"] not in PAGES:
        select_destination(st.session_state["main_workspace"])
    # Streamlit otherwise removes the hidden subpage widgets on navigation.
    for key in list(st.session_state):
        if key in {"body_section", "training_section", "body_period", "analysis_window_days", "body_long_days", "body_custom_dates", "body_use_custom_dates", "review_question", "review_section", "review_period", "review_report_period", "review_action_id", "overview_period_choice", "settings_section"} or key.startswith("body_metric:"):
            st.session_state[key] = st.session_state[key]


def current_route(page):
    if page == "身体":
        return ROUTES.get(st.session_state.get("body_section"), "body")
    if page == "训练" and st.session_state.get("training_section") == "运动记录":
        return "workouts"
    if page == "训练" and st.session_state.get("training_section") == "动作进展":
        return "progress"
    return ROUTES[page]
