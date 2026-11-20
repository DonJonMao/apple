"""Shared graphite shell, top navigation and chart tokens."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).with_name("assets")


@lru_cache(maxsize=1)
def _styles():
    return (ASSETS / "theme.css").read_text(encoding="utf-8")


def apply_theme():
    st.markdown("<style>" + _styles() + "</style>", unsafe_allow_html=True)
    import plotly.graph_objects as go
    import plotly.io as pio
    pio.templates["healthzip"] = go.layout.Template(layout={
        "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": "system-ui, sans-serif", "color": "#A3AFBF", "size": 13},
        "colorway": ["#38BFA3", "#89A9E8", "#D7B77B", "#BEA4CF"],
        "xaxis": {"gridcolor": "#2B3543", "zeroline": False, "automargin": True},
        "yaxis": {"gridcolor": "#2B3543", "zeroline": False, "automargin": True},
        "margin": {"l": 12, "r": 12, "t": 20, "b": 12},
        "hoverlabel": {"bgcolor": "#141A22", "font_color": "#F1F5F9"},
    })
    pio.templates.default = "healthzip"


def open_workspace(page):
    st.session_state["main_workspace"] = page
    st.session_state["mobile_menu_open"] = False


def render_header(pages):
    with st.container(key="app_header"):
        left, right = st.columns([1, 5], vertical_alignment="center")
        with left:
            st.markdown('<div class="app-brand"><span aria-hidden="true">▥</span> HealthZIP</div>',
                        unsafe_allow_html=True)
        with right:
            with st.container(key="desktop_navigation"):
                st.radio("顶部导航", pages, horizontal=True, key="main_workspace",
                         label_visibility="collapsed")
            with st.container(key="mobile_navigation"):
                with st.popover("菜单 · " + st.session_state.get("main_workspace", pages[0]),
                                use_container_width=True, key="mobile_menu_open", on_change="rerun"):
                    st.caption("前往")
                    for page in pages:
                        st.button(page, key="mobile_nav_" + page, on_click=open_workspace,
                                  args=(page,), use_container_width=True,
                                  type="primary" if page == st.session_state.get("main_workspace") else "secondary")
    return st.session_state["main_workspace"]


def render_footer():
    # Intentionally small; observation and import timestamps belong to the page.
    st.markdown('<footer class="app-footer">HealthZIP · 数据保存在当前工作区</footer>',
                unsafe_allow_html=True)
