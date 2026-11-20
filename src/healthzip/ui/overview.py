"""A small, readable landing page; private inventories stay behind the UI."""

from __future__ import annotations

import base64
from datetime import datetime
from functools import lru_cache
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

BODY_TYPES = (
    ("心率", ("heart_rate_bpm", "resting_heart_rate_bpm")),
    ("HRV", ("hrv_sdnn_ms",)),
    ("睡眠", ("sleep_stage",)),
    ("体重", ("body_mass_kg",)),
    ("有氧适能", ("vo2_max_ml_kg_min",)),
)


def overview_data(repo):
    """Read latest dates with the existing type/date index, without raw rows."""
    updates = []
    for label, types in BODY_TYPES:
        found, dates = False, []
        for canonical in types:
            row = repo.one(
                "SELECT local_date FROM health_sample WHERE canonical_type=? "
                "AND record_status='active' ORDER BY local_date DESC LIMIT 1",
                (canonical,),
            )
            found = found or row is not None
            if row and row[0]:
                dates.append(row[0])
        if label == "体重":
            row = repo.one(
                "SELECT local_date FROM body_measurement WHERE canonical_type='body_mass_kg' "
                "ORDER BY local_date DESC LIMIT 1"
            )
            found = found or row is not None
            if row and row[0]:
                dates.append(row[0])
        updates.append({"项目": label, "最近记录": max(dates) if dates else
                        ("日期未知" if found else "暂无记录"),
                        "数据状态": "已有记录" if found else "暂无记录"})
    workouts = repo.one("SELECT COUNT(*),MAX(local_date) FROM workout WHERE record_status='active'")
    updates.append({"项目": "运动", "最近记录": workouts[1] or
                    ("日期未知" if workouts[0] else "暂无记录"),
                    "数据状态": "已有记录" if workouts[0] else "暂无记录"})
    latest_dates = [row["最近记录"] for row in updates if row["最近记录"][:4].isdigit()]
    sessions = repo.one("SELECT COUNT(*) FROM strength_session WHERE deleted_at IS NULL")[0]
    batch = repo.one("SELECT imported_at,status FROM import_batch ORDER BY id DESC LIMIT 1")
    return {"updates": updates, "latest_date": max(latest_dates) if latest_dates else None,
            "workout_count": workouts[0], "training_count": sessions,
            "recorded_categories": sum(row["数据状态"] == "已有记录" for row in updates) + int(sessions > 0),
            "latest_import": dict(batch) if batch else None}


def _open_workspace(workspace):
    st.session_state["main_workspace"] = workspace


@lru_cache(maxsize=1)
def _overview_style():
    return (Path(__file__).with_name("assets") / "overview.css").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _meadow_image():
    data = (Path(__file__).with_name("assets") / "overview-meadow.jpg").read_bytes()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


_CARD_ICONS = {
    "sleep": '<path d="M20.5 14A8.5 8.5 0 0 1 10 3.5 8.5 8.5 0 1 0 20.5 14Z"/>',
    "heart": '<path d="M20.8 4.7a5.5 5.5 0 0 0-7.8 0L12 5.8l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.5a5.5 5.5 0 0 0 0-7.8Z"/><path d="m5 12 3 0 2-4 3 8 2-4h4"/>',
    "workouts": '<path d="m6 18 6-13 6 13M8 14h8M3 21h18"/><path d="M18 4h3v3"/>',
    "weight": '<rect x="4" y="4" width="16" height="17" rx="4"/><path d="M8 8a6 6 0 0 1 8 0M12 8v4"/>',
}


def _card_icon(name):
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.45" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            + _CARD_ICONS[name] + '</svg>')


def _latest_category(data, labels):
    rows = [row for row in data["updates"] if row["项目"] in labels]
    dates = [row["最近记录"] for row in rows if row["最近记录"][:4].isdigit()]
    if dates:
        return "最近记录 " + max(dates)
    return "日期未注明" if any(row["数据状态"] == "已有记录" for row in rows) else "等待第一条记录"


def _overview_hero(data):
    with st.container(key="earthy_overview_hero"):
        copy, visual = st.columns([1.13, 1], gap="large", vertical_alignment="center")
        with copy:
            st.markdown(
                '<div class="overview-hero overview-hero-copy"><span class="overview-eyebrow">'
                '<span class="overview-spark" aria-hidden="true">✧</span> A LITTLE CARE, EVERY DAY</span>'
                '<h2>让日常的记录，<br><em>长成清晰的变化。'
                '<svg viewBox="0 0 460 22" preserveAspectRatio="none" aria-hidden="true">'
                '<path d="M4 14C100 0 259 2 453 10M18 20C155 7 298 10 440 16"/>'
                '</svg></em></h2><p>从睡眠、心率到每一次训练，<br>'
                '留一点耐心，看见属于自己的节奏。</p></div>',
                unsafe_allow_html=True,
            )
            primary, secondary = st.columns(2, gap="small")
            primary.button("记录力量训练", on_click=_open_workspace, args=("力量",),
                           key="overview_open_training", type="primary", use_container_width=True)
            secondary.button("查看心率与 HRV", on_click=_open_workspace, args=("心率 / HRV",),
                             key="overview_open_heart", use_container_width=True)
            st.markdown('<div class="overview-trust"><span>本地保存</span><i></i>'
                        '<span>真实记录</span><i></i><span>按需分析</span></div>',
                        unsafe_allow_html=True)
        with visual:
            latest = escape(data["latest_date"] or "等待第一条记录")
            st.markdown(
                '<div class="overview-hero-visual"><div class="overview-photo-wash"></div>'
                f'<img src="{_meadow_image()}" alt="夕阳下起伏的金色田野，作为页面装饰" '
                'class="overview-meadow"><div class="overview-photo-badge">'
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" '
                'aria-hidden="true"><path d="M12 21V10M12 15C3 15 3 7 3 7s9-1 9 8Z'
                'M12 12C12 4 21 3 21 3s1 9-9 9Z"/></svg>慢慢来，也在向前</div>'
                '<div class="overview-photo-note"><span>YOUR LATEST OBSERVATION</span>'
                f'<strong>{latest}</strong><p>最近身体／运动记录 · 按实际发生日期</p></div></div>',
                unsafe_allow_html=True,
            )


def _workspace_cards(data):
    st.markdown('<div class="overview-section-label">YOUR EVERYDAY CANVAS</div>', unsafe_allow_html=True)
    st.subheader("从一个小小的观察开始")
    st.caption("各项记录各有来处。选一个工作区，看看已有数据讲述了什么。")
    cards = (
        ("sleep", "01", "睡眠", "留意每一夜的节奏", "查看已观察睡眠时长，按周、按月回看。", "查看睡眠记录", "睡眠", ("睡眠",)),
        ("heart", "02", "心率与 HRV", "听见身体的起伏", "分别查看静息心率与 SDNN 的真实记录。", "查看心率记录", "心率 / HRV", ("心率", "HRV")),
        ("workouts", "03", "运动", "记住动起来的日子", "回看运动次数、已有时长和设备记录能量。", "查看运动记录", "运动", ("运动",)),
        ("weight", "04", "体重与有氧", "给变化一点时间", "按来源查看称重记录与有氧适能估计。", "查看体重与有氧", "体重 / 有氧", ("体重", "有氧适能")),
    )
    columns = st.columns(4, gap="medium")
    for column, (name, number, title, headline, description, action, page, labels) in zip(columns, cards):
        with column, st.container(key="earthy_card_" + name):
            st.markdown(
                f'<div class="overview-workspace-card overview-{name}">'
                f'<div class="overview-card-art"><span class="overview-card-category">{title}</span>'
                f'<span class="overview-card-number">{number}</span>{_card_icon(name)}</div>'
                f'<h3>{headline}</h3><p>{description}</p>'
                f'<span class="overview-card-date">{escape(_latest_category(data, labels))}</span></div>',
                unsafe_allow_html=True,
            )
            st.button(action, key="earthy_open_" + name, on_click=_open_workspace,
                      args=(page,), use_container_width=True)


def _import_summary(result, *, sync=False):
    batches = result.get("batches", []) if sync else [result]
    added = sum(int(row.get("new", row.get("records_inserted", 0)) or 0) for row in batches)
    duplicates = sum(int(row.get("duplicate", row.get("records_deduplicated", 0)) or 0) for row in batches)
    updated = sum(int(row.get("updated", 0) or 0) for row in batches)
    invalid = sum(int(row.get("invalid", row.get("errors_count", 0)) or 0) for row in batches)
    errors = len(result.get("errors") or []) if sync else 0
    message = f"新增 {added:,} 条，重复 {duplicates:,} 条"
    if sync:
        message += f"，更新 {updated:,} 条"
    if errors or invalid or result.get("status") in {"partial_failed", "failed"}:
        st.warning(f"本次导入部分未完成：{message}；{errors + invalid} 项需要检查。")
    else:
        st.success("本次同步完成：" + message if sync else "本次导入完成：" + message)


def render_overview(repo, *, timezone_name="Asia/Shanghai", last_import=None, last_sync=None,
                    summary_renderer=None):
    data = overview_data(repo)
    st.markdown("<style>" + _overview_style() + "</style>", unsafe_allow_html=True)
    st.subheader("数据总览")
    _overview_hero(data)
    with st.container(key="earthy_overview_stats"):
        columns = st.columns(4)
        columns[0].metric("最近身体／运动记录", data["latest_date"] or "暂无记录")
        columns[1].metric("运动记录", f"{data['workout_count']:,} 次")
        columns[2].metric("力量训练记录", f"{data['training_count']:,} 次")
        columns[3].metric("已有数据项目", f"{data['recorded_categories']} 项")
        st.markdown('<p class="overview-stats">只陈述当前已有记录；项目数量不代表记录完整程度或身体评分。</p>',
                    unsafe_allow_html=True)
    if summary_renderer is not None:
        summary_renderer()
    _workspace_cards(data)
    st.markdown('<div class="overview-section-label">A NOTE FROM YOUR RECORDS</div>', unsafe_allow_html=True)
    st.subheader("数据更新概况")
    st.dataframe(data["updates"], hide_index=True, use_container_width=True)
    st.caption("这里显示实际记录的日期；没有记录不能确定是否佩戴手表。")
    latest = data["latest_import"]
    if latest:
        try:
            imported = datetime.fromisoformat(latest["imported_at"].replace("Z", "+00:00"))
            imported_text = imported.astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError, AttributeError):
            imported_text = "时间未记录"
        statuses = {"completed": "已完成", "partial_failed": "部分未完成",
                    "failed": "未完成", "running": "导入中"}
        st.caption(f"最近一次导入：{imported_text} · {statuses.get(latest['status'], '状态待核对')}")
    if last_import:
        _import_summary(last_import)
    if last_sync:
        _import_summary(last_sync, sync=True)
    with st.expander("如何导入后续数据"):
        st.write("展开左侧“导入与存储设置”，填写新的 Apple Health ZIP 路径后点击“流式导入”。")
        st.write("手机增量文件放入配置的同步目录后，点击“扫描增量数据”；已经导入的重复记录会自动识别。")
        st.caption("导入与训练记录分别保存；还没有身体数据时也可以正常记录力量训练。")
