"""Shared, local-only earthy visual shell for every health workspace."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ASSETS = Path(__file__).with_name("assets")
_assets = components.declare_component("healthzip_theme_assets", path=str(ASSETS))


@lru_cache(maxsize=1)
def _styles():
    return (ASSETS / "theme.css").read_text(encoding="utf-8")


def apply_theme():
    prefix = str(st.get_option("server.baseUrlPath") or "").strip("/")
    asset_root = ("/" + prefix if prefix else "") + "/component/" + _assets.name
    css = _styles().replace("__ASSET_ROOT__", asset_root)
    st.markdown("<style>" + css + "</style>", unsafe_allow_html=True)


def _open_training():
    st.session_state["main_workspace"] = "力量"


def render_header(pages):
    with st.container(key="earthy_app_header"):
        with st.container(key="earthy_header_row"):
            left, right = st.columns([0.74, 0.26], vertical_alignment="center")
            with left:
                st.markdown(
                    '<div class="earthy-brand"><span class="earthy-brand-mark" aria-hidden="true">'
                    '<svg viewBox="0 0 28 28" fill="none"><path d="M22 6C11 4 5 10 7 17'
                    'c2 7 15 5 15-11Z" stroke="currentColor" stroke-width="1.6"/>'
                    '<path d="m7 23 11-12M13 17h6" stroke="currentColor" stroke-width="1.6" '
                    'stroke-linecap="round"/></svg></span>'
                    '<span class="earthy-wordmark">HealthZIP<span>.</span></span>'
                    '<span class="earthy-local">本地 · 私人 · 慢慢积累</span></div>',
                    unsafe_allow_html=True,
                )
                st.title("训练与健康记录")
            with right:
                st.button("记录训练 ↗", key="shell_open_training", type="primary",
                          on_click=_open_training, use_container_width=True)
        with st.container(key="workspace_navigation"):
            return st.radio("工作区", pages, horizontal=True, key="main_workspace",
                            label_visibility="collapsed")


def render_footer():
    st.markdown(
        '<footer class="earthy-footer"><div><span class="earthy-footer-wordmark">HealthZIP'
        '<span>.</span></span><p>关照身体，从每一次真实记录开始。</p></div>'
        '<div><span class="earthy-footer-label">YOUR RECORDS, YOUR SPACE</span>'
        '<p>私人健康数据保存在本地 · 缺失记录保持未知</p></div>'
        '<div class="earthy-footer-bottom">为日常记录留一点耐心。'
        '<span>Grown with care.</span></div></footer>', unsafe_allow_html=True,
    )
