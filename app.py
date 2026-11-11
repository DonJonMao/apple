"""Local daily-use Streamlit UI for the offline health and strength workbench."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

try:
    import plotly.express as px
except ImportError:  # pragma: no cover - optional UI dependency
    px = None

from healthzip.analytics import (
    all_analysis,
    persist_analysis,
)
from healthzip.config import DEFAULT_DB_PATH
from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.importers.apple_zip import inspect_zip
from healthzip.importers.incremental import sync_folder
from healthzip.quality import inventory
from healthzip.reporting import render_report


def render_evidence_card(card: dict) -> None:
    """Render a card with the metadata needed to reproduce its conclusion."""
    if not card:
        return
    window = card.get("window") or {}
    st.subheader(card.get("title", "Evidence Card"))
    st.write(f"状态：{card.get('status')} · {card.get('summary', '')}")
    st.caption(
        f"时间范围：{window.get('start') or '—'} 至 {window.get('end') or '—'} · "
        f"算法版本：{card.get('algorithm_version') or '—'}"
    )
    if card.get("facts"):
        st.dataframe(card["facts"], use_container_width=True, hide_index=True)
    with st.expander("限制与来源", expanded=False):
        if card.get("limitations"):
            st.write("限制：" + "；".join(card["limitations"]))
        st.write("允许行动：" + "、".join(card.get("allowed_actions") or []))
        source_ids = [str(source_id) for source_id in (card.get("source_feature_ids") or [])]
        source_preview = "、".join(source_ids[:20]) or "—"
        if len(source_ids) > 20:
            source_preview += f" ……（共 {len(source_ids)} 条）"
        st.write("来源特征：" + source_preview)


def render_strength_tab(repo: Repository, value: dict) -> None:
    from healthzip.ui.analysis_page import render_analysis
    from healthzip.ui.training_page import render_training

    render_training(repo)
    if st.checkbox("查看表现分析与复盘", value=False, key="show_training_analysis"):
        render_analysis(repo, value)


st.set_page_config(page_title="Health ZIP Workbench", layout="wide")
st.title("训练与健康记录")
st.caption("本地 Apple Health ZIP 整理与分析；不上传原始健康数据，不是医疗诊断。")

db_path = st.sidebar.text_input("SQLite 路径", str(DEFAULT_DB_PATH))
zip_path = st.sidebar.text_input("Apple Health ZIP 路径", "")
sync_path = st.sidebar.text_input("手机增量同步目录（JSON/JSONL）", "")
sync_source = st.sidebar.text_input("同步来源名称", "phone_export")
include_cycle = st.sidebar.checkbox("启用周期数据导入（可选）", value=False)
window_days = st.sidebar.number_input("分析窗口（天）", min_value=7, max_value=3650, value=30)
timezone_name = st.sidebar.text_input("分析时区", "Asia/Shanghai", key="analysis_timezone")
try:
    ZoneInfo(timezone_name)
except (ZoneInfoNotFoundError, ValueError):
    st.sidebar.error("请输入有效IANA时区，例如 Asia/Shanghai 或 UTC。")
    st.stop()

if zip_path:
    try:
        info = inspect_zip(zip_path)
        st.sidebar.success(f"已检查：{info.member_count} 个成员，XML：{info.xml_member_path}")
        with st.expander("ZIP 预扫描", expanded=False):
            st.json(info.as_dict())
        if st.sidebar.button("流式导入", type="primary"):
            repo = Repository(db_path)
            try:
                result = import_apple_zip(zip_path, repo, include_cycle=include_cycle)
                st.session_state["last_import"] = result.as_dict()
            finally:
                repo.close()
    except Exception as exc:
        st.sidebar.error(f"ZIP 检查失败：{exc}")

if sync_path:
    if st.sidebar.button("扫描增量数据"):
        repo = Repository(db_path)
        try:
            st.session_state["last_sync"] = sync_folder(
                sync_path, repo, source_name=sync_source or "phone_export"
            )
        except Exception as exc:
            st.session_state["last_sync"] = {"errors": [str(exc)]}
        finally:
            repo.close()

repo = Repository(db_path)
try:
    if st.session_state.get("last_import"):
        st.subheader("最近导入")
        st.json(st.session_state["last_import"])
    if st.session_state.get("last_sync"):
        st.subheader("最近增量同步")
        st.json(st.session_state["last_sync"])
    pages = (
        [
            "导入与总览",
            "数据质量",
            "心率 / HRV",
            "睡眠",
            "运动",
            "体重 / 有氧",
            "力量",
            "营养",
            "周期",
            "报告",
            "知识库",
        ]
    )
    page = st.radio("工作区", pages, horizontal=True, key="main_workspace")
    inv = inventory(repo) if page in {"导入与总览", "报告"} else {}
    analysis = all_analysis(repo, int(window_days), timezone_name=timezone_name) if page not in {"导入与总览", "力量", "知识库"} else {}
    if analysis:
        persist_analysis(repo, analysis)
    if page == "导入与总览":
        st.subheader("数据总览")
        st.dataframe(inv.get("sample_types", []), use_container_width=True)
        st.write("Workout 类型")
        st.json(inv.get("workouts", {}))
        with st.expander("同步来源与游标", expanded=False):
            st.json(repo.sync_status())
    if page == "数据质量":
        st.caption("状态是产品数据质量门槛，不是医学阈值。")
        st.dataframe(
            [{"feature": k, **v} for k, v in analysis["readiness"].items()],
            use_container_width=True,
        )
    for tab, key in (
        (pages[2], "heart"),
        (pages[3], "sleep"),
        (pages[4], "workouts"),
        (pages[5], "weight"),
        (pages[6], "strength"),
        (pages[7], "nutrition"),
        (pages[8], "cycle"),
    ):
        if page == tab:
            value = analysis.get(key, {})
            cards = value.get("cards", []) if key == "heart" else [value.get("card")]
            for card in cards:
                render_evidence_card(card)
            if key == "sleep":
                if value.get("nights") and px:
                    st.plotly_chart(
                        px.line(
                            value["nights"], x="date", y="sleep_hours", color="source", title="按来源已观察睡眠（小时；完整性另列）"
                        ),
                        use_container_width=True,
                    )
                st.dataframe(value.get("nights", []), use_container_width=True)
            elif key == "workouts":
                if value.get("weeks") and px:
                    st.plotly_chart(
                        px.bar(
                            value["weeks"],
                            x="week",
                            y="duration_minutes",
                            title="每周训练时长（分钟）",
                        ),
                        use_container_width=True,
                    )
                st.dataframe(value.get("weeks", []), use_container_width=True)
            elif key == "weight":
                if value.get("daily") and px:
                    st.plotly_chart(
                        px.line(value["daily"], x="date", y="kg", color="source", title="按来源体重记录（kg）"),
                        use_container_width=True,
                    )
                st.dataframe(value.get("daily", []), use_container_width=True)
                vo2 = analysis["vo2"]
                if vo2.get("points"):
                    render_evidence_card(vo2["card"])
                    if px:
                        st.plotly_chart(
                            px.line(
                                vo2["points"],
                                x="local_date",
                                y="normalized_value",
                                title="VO₂ max 估计值",
                            ),
                            use_container_width=True,
                        )
            elif key == "strength":
                render_strength_tab(
                    repo,
                    {
                        **analysis,
                        "analysis_timezone": timezone_name,
                        "analysis_window_days": int(window_days),
                        "strength_quality": analysis.get("strength_quality", {}),
                        "body_state_strength": analysis.get("body_state_strength", {}),
                        "week_report": analysis.get("week_report", {}),
                        "month_report": analysis.get("month_report", {}),
                        "heart": analysis.get("heart", {}),
                        "sleep": analysis.get("sleep", {}),
                        "weight": analysis.get("weight", {}),
                    },
                )
            elif key == "nutrition":
                st.dataframe(value.get("days", []), use_container_width=True)
            elif key == "cycle":
                st.dataframe(value.get("events", []), use_container_width=True)
    if page == "知识库":
        from healthzip.ui.knowledge_page import render_knowledge
        render_knowledge()
    if page == "报告":
        report_path = st.text_input("报告输出路径", "reports/latest.md")
        period_label = st.selectbox("报告范围", ["当前分析窗口", "本周", "本月"])
        if st.button("生成 Markdown 报告"):
            if period_label != "当前分析窗口":
                from healthzip.analytics.v13 import analyze
                period = {"本周": "week", "本月": "month"}[period_label]
                analysis["period_snapshots"] = {period: analyze(repo, cutoff_time=analysis["v13"]["cutoff_time"], period=period,
                                                              timezone_name=timezone_name)}
            out = render_report(analysis, inv, report_path)
            st.success(f"已写入 {out}")
        st.write("报告会包含每个 Evidence Card 的窗口、事实、样本量和限制。")
finally:
    repo.close()
