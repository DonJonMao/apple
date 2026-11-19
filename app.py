"""Local daily-use Streamlit UI for the offline health and strength workbench."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

from healthzip.analytics import (
    all_analysis,
    cycle_analysis,
    persist_analysis,
    workout_analysis,
)
from healthzip.analytics.workspaces import analyze_workspace
from healthzip.config import DEFAULT_DB_PATH
from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.importers.apple_zip import inspect_zip
from healthzip.importers.incremental import sync_folder
from healthzip.quality import inventory, readiness
from healthzip.reporting import render_report
from healthzip.ui.body_pages import render_heart, render_sleep, render_weight
from healthzip.ui.overview import render_overview
from healthzip.ui.workout_page import render_workouts


def render_evidence_card(card: dict) -> None:
    """Render a card with the metadata needed to reproduce its conclusion."""
    if not card:
        return
    window = card.get("window") or {}
    st.subheader(card.get("title", "Evidence Card"))
    st.write(card.get("summary", ""))
    if window.get("start") or window.get("end"):
        st.caption(f"记录范围：{window.get('start') or '—'} 至 {window.get('end') or '—'}")
    with st.expander("记录说明", expanded=False):
        if card.get("limitations"):
            st.write("限制：" + "；".join(card["limitations"]))
        st.caption(f"计算版本：{card.get('algorithm_version') or '—'}")


def render_strength_tab(repo: Repository, value: dict) -> None:
    from healthzip.ui.training_page import render_training

    render_training(repo)


st.set_page_config(page_title="Health ZIP Workbench", layout="wide")

with st.sidebar.expander("导入与存储设置", expanded=False):
    db_path = st.text_input("SQLite 路径", str(DEFAULT_DB_PATH))
    zip_path = st.text_input("Apple Health ZIP 路径", "")
    sync_path = st.text_input("手机增量同步目录（JSON/JSONL）", "")
    sync_source = st.text_input("同步来源名称", "phone_export")
    include_cycle = st.checkbox("启用周期数据导入（可选）", value=False)
window_days = st.sidebar.number_input("分析窗口（天）", min_value=7, max_value=3650, value=30, key="analysis_window_days")
timezone_name = st.sidebar.text_input("分析时区", "Asia/Shanghai", key="analysis_timezone")
try:
    ZoneInfo(timezone_name)
except (ZoneInfoNotFoundError, ValueError):
    st.sidebar.error("请输入有效IANA时区，例如 Asia/Shanghai 或 UTC。")
    st.stop()

if zip_path:
    try:
        inspect_zip(zip_path)
        st.sidebar.success("导出文件检查通过，可以导入。")
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
    pages = (
        [
            "导入与总览",
            "数据质量",
            "心率 / HRV",
            "睡眠",
            "运动",
            "体重 / 有氧",
            "力量",
            "分析",
            "周期",
            "报告",
        ]
    )
    if destination := st.session_state.pop("strength_workspace_next", None):
        if destination in pages:
            st.session_state["main_workspace"] = destination
    if "main_workspace" not in st.session_state and st.query_params.get("workspace") == "strength":
        st.session_state["main_workspace"] = "力量"
    if st.session_state.get("main_workspace", pages[0]) not in pages:
        st.session_state["main_workspace"] = pages[0]
    if st.session_state.get("main_workspace") == "力量":
        # Keep the phone workbench usable. The standard sidebar still provides
        # every workspace and the original local storage/import settings.
        page = st.sidebar.radio("工作区", pages, key="main_workspace")
        st.markdown(
            "<style>[data-testid='stMainBlockContainer']{padding:3rem 0.5rem 0;"
            "max-width:1000px} [data-testid='stMain']{background:#26262B}"
            "[data-testid='stHeader']{height:2.75rem;background:#26262B}"
            "[data-testid='stToolbar']{display:none}</style>",
            unsafe_allow_html=True,
        )
    else:
        st.title("训练与健康记录")
        st.caption("查看身体趋势，记录每次训练。")
        page = st.radio("工作区", pages, horizontal=True, key="main_workspace")
    if page == "力量":
        if st.query_params.get("workspace") != "strength":
            st.query_params["workspace"] = "strength"
    elif st.query_params.get("workspace") == "strength":
        del st.query_params["workspace"]
    inv = inventory(repo) if page == "报告" else {}
    context_id = st.session_state.get("analysis_contexts", {}).get(str(repo.path.resolve()))
    # These workspaces consume their existing factual views. Computing and
    # freezing the full scientific/workflow result here adds unrelated work.
    if page == "数据质量":
        analysis = {"readiness": readiness(repo, window_days=int(window_days), as_of=date.today().isoformat())}
    elif page in {"心率 / HRV", "睡眠", "体重 / 有氧"}:
        analysis = analyze_workspace(repo, page, window_days=int(window_days), timezone_name=timezone_name)
    elif page == "运动":
        analysis = {"workouts": workout_analysis(repo, int(window_days))}
    elif page == "周期":
        analysis = {"cycle": cycle_analysis(repo)}
    elif page not in {"导入与总览", "力量"}:
        analysis = all_analysis(repo, int(window_days), timezone_name=timezone_name, context_id=context_id)
    else:
        analysis = {}
    if page in {"数据质量", "心率 / HRV", "睡眠", "运动", "体重 / 有氧", "周期"}:
        from healthzip.workflows.storage import current_context_problem
        analysis["workflow_context_problem"] = current_context_problem(repo, context_id)
    if analysis:
        persist_analysis(repo, analysis)
    if analysis.get("workflow_context_problem"):
        st.warning("当前选择的适用声明已撤回或被替换，来源解释须重新确认。记录事实和历史分析仍保留；"
                   "请在分析页的“查看范围与已确认信息”中确认信息并运行分析。")
    if page == "分析":
        from healthzip.ui.analysis_page import render_analysis
        render_analysis(repo, analysis)
    if page == "导入与总览":
        render_overview(repo, timezone_name=timezone_name,
                        last_import=st.session_state.get("last_import"),
                        last_sync=st.session_state.get("last_sync"))
    if page == "数据质量":
        st.caption("状态是产品数据质量门槛，不是医学阈值。")
        quality_labels = {"resting_heart_rate": "静息心率", "hrv_sdnn": "HRV（SDNN）",
                          "sleep": "睡眠", "vo2_max": "有氧适能", "body_mass": "体重",
                          "workouts": "运动", "strength": "力量训练"}
        status_labels = {"usable": "可查看趋势", "provisional": "记录较少",
                         "insufficient": "记录不足", "not_imported": "暂无记录",
                         "stale": "记录较早"}
        st.dataframe(
            [{"项目": quality_labels[k], "状态": status_labels.get(v["status"], "待核对"),
              "有效记录数": v.get("valid_samples", v.get("n")),
              "记录日期数": v.get("observed_days", v.get("observed_nights", v.get("days"))),
              "最近记录": v.get("last_date") or "暂无日期",
              "说明": v.get("missing") or "—"}
             for k, v in analysis["readiness"].items() if k in quality_labels],
            use_container_width=True, hide_index=True,
        )
    if page == "心率 / HRV":
        render_heart(analysis)
    elif page == "睡眠":
        render_sleep(analysis)
    elif page == "运动":
        render_workouts(repo, timezone_name=timezone_name)
    elif page == "体重 / 有氧":
        render_weight(analysis)
    elif page == "力量":
        render_strength_tab(repo, {
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
        })
    elif page == "周期":
        cycle = analysis["cycle"]
        render_evidence_card(cycle["card"])
        flow_labels = {"HKCategoryValueMenstrualFlowUnspecified": "已记录，强度未注明",
                       "HKCategoryValueMenstrualFlowLight": "少量",
                       "HKCategoryValueMenstrualFlowMedium": "中等",
                       "HKCategoryValueMenstrualFlowHeavy": "较多",
                       "HKCategoryValueMenstrualFlowNone": "无出血（已记录）"}
        if cycle["events"]:
            st.dataframe([{"日期": row["event_date"],
                           "记录": flow_labels.get(row.get("category_value"), "已记录，类型未识别"),
                           "来源": row.get("source") or "未注明"}
                          for row in cycle["events"]], hide_index=True, use_container_width=True)
    if page == "报告":
        report_path = st.text_input("报告输出路径", "reports/latest.md")
        period_label = st.selectbox("报告范围", ["当前分析窗口", "本周", "本月"])
        period = {"本周": "week", "本月": "month"}.get(period_label)
        report_key = "report_page_joint_" + str(repo.path.resolve()) + "_" + str(period)
        if st.button("生成 Markdown 报告"):
            try:
                if period:
                    from healthzip.workflows.period_report import create_report
                    frozen_report = create_report(repo, analysis["v13"], period=period)
                    out = Path(report_path)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(frozen_report["markdown"], encoding="utf-8")
                    st.session_state[report_key] = frozen_report["report_id"]
                else:
                    from healthzip.workflows.reports import review_analysis
                    analysis["workflow_reviews"] = review_analysis(repo, analysis["v13"], include_background=True)
                    out = render_report(analysis, inv, report_path, repo=repo)
                st.success(f"已写入 {out}")
            except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
                st.error(f"本次报告未完成，请重新生成：{exc}")
        if period and st.session_state.get(report_key):
            from healthzip.workflows.period_report import load_report
            frozen_report = load_report(repo, st.session_state[report_key])
            st.markdown(frozen_report["markdown"])
            st.download_button("下载身体与力量联合报告", frozen_report["markdown"], file_name=f"healthzip-{period}.md", mime="text/markdown")
        st.write("报告会包含每个 Evidence Card 的窗口、事实、样本量和限制。")
finally:
    repo.close()
