"""Reviews are explicit computations, with existing reports and tasks retained."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from healthzip.analytics.cache import revision_identity


def render_review(repo, *, timezone_name="Asia/Shanghai"):
    st.subheader("复盘")
    section = st.radio("复盘内容", ["周月复盘", "问题分析", "报告"], horizontal=True, key="review_section")
    if section == "问题分析":
        from healthzip.ui.sequence_review import render_sequence_review
        render_sequence_review(repo)
    key = "review_snapshot:" + str(repo.path.resolve()) + ":" + timezone_name
    days = st.number_input("分析窗口（天）", min_value=1, max_value=3650,
                           value=int(st.session_state.get("analysis_window_days", 30)), key="review_window_days")
    st.caption("先选范围，再生成分析；保存的结果保留当时的事实与依据。")
    if st.button("更新分析", type="primary", key="review_compute"):
        from healthzip.analytics import all_analysis, persist_analysis
        with st.spinner("正在生成本次复盘…"):
            context = st.session_state.get("analysis_contexts", {}).get(str(repo.path.resolve()))
            value = all_analysis(repo, int(days), timezone_name=timezone_name, context_id=context)
            persist_analysis(repo, value)
        st.session_state[key] = {"value": value, "revision": revision_identity(repo), "days": days}
    saved = st.session_state.get(key)
    if not saved:
        st.info("生成一次分析后，可查看问题分析、周月复盘和下载报告。健康事实与训练记录可随时从顶部查看。")
        _history(repo)
        return
    if saved["revision"] != revision_identity(repo) or saved["days"] != days:
        st.warning("以下为已保存的分析，数据或查看范围已有变化。点击“更新分析”生成当前结果。")
    value = saved["value"]
    from healthzip.workflows.storage import current_context_problem
    context = st.session_state.get("analysis_contexts", {}).get(str(repo.path.resolve()))
    value = {**value, "workflow_context_problem": current_context_problem(repo, context)}
    if value["workflow_context_problem"]:
        st.warning("当前选择的适用声明已撤回或被替换，依赖该声明的解释需重新确认；原记录与历史结果保留。")
    if section == "问题分析":
        from healthzip.ui.analysis_page import render_analysis
        render_analysis(repo, value)
        return
    choices = ["本周", "本月"] + (["当前分析窗口"] if section == "报告" else [])
    label = st.selectbox("报告范围", choices, key="review_report_period")
    period = {"本周": "week", "本月": "month"}.get(label)
    report_key = key + ":report:" + (period or f"window:{int(days)}")
    report_path = st.text_input("报告输出路径", "reports/latest.md") if section == "报告" else None
    if st.button("生成当前周期复盘" if section == "周月复盘" else "生成 Markdown 报告"):
        from healthzip.analytics.v13 import analyze
        from healthzip.workflows.period_report import create_report
        try:
            selected_context = {**value["v13"].get("selection_context", {})}
            if context:
                selected_context["workflow_context_id"] = context
            explicit = value["v13"].get("cutoff_mode") == "explicit"
            current = analyze(repo, int(days), timezone_name=timezone_name,
                              cutoff_time=value["v13"]["cutoff_time"] if explicit else None,
                              context=selected_context or None,
                              retrospective=value["v13"].get("retrospective", False), use_cache=False)
            if period:
                report = create_report(repo, current, period=period)
            else:
                from healthzip.analytics import all_analysis
                from healthzip.quality.coverage import inventory
                from healthzip.reporting.markdown_report import render_report
                from healthzip.workflows.reports import review_analysis
                current_analysis = dict(value) if explicit else all_analysis(
                    repo, int(days), timezone_name=timezone_name, context_id=context)
                current_analysis["v13"] = current
                current_analysis["workflow_reviews"] = review_analysis(repo, current, include_background=True)
                out = render_report(current_analysis, inventory(repo), report_path, repo=repo)
                report = {"markdown": out.read_text(encoding="utf-8"), "current": current}
            if report_path and period:
                out = Path(report_path)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(report["markdown"], encoding="utf-8")
            st.session_state[report_key] = report
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(f"复盘未完成：{exc}。可以重试，训练记录仍保留。")
    report = st.session_state.get(report_key)
    if report:
        st.markdown(report["markdown"])
        st.download_button("下载身体与力量联合报告" if period else "下载当前分析窗口报告", report["markdown"],
                           file_name=f"healthzip-{period or 'analysis'}.md", mime="text/markdown")
    if section == "报告":
        st.download_button("下载当前分析结果", json.dumps(value, ensure_ascii=False, indent=2, default=str),
                           file_name="healthzip-analysis.json", mime="application/json")
    _history(repo)


def _history(repo):
    with st.expander("已保存的复盘"):
        exists = repo.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='joint_period_report'")
        rows = repo.rows("SELECT report_id,created_at,json_extract(payload_json,'$.period') AS period "
                         "FROM joint_period_report WHERE user_id='local' ORDER BY created_at DESC LIMIT 30") if exists else []
        if not rows:
            st.caption("尚无已保存的联合复盘。生成后可在这里重新打开。")
            return
        labels = {row["report_id"]: f"{row['created_at']} · {'周' if row['period'] == 'week' else '月'}复盘" for row in rows}
        selected = st.selectbox("历史复盘", list(labels), format_func=labels.get)
        state_key = "opened_report:" + str(repo.path.resolve())
        if st.button("打开这份复盘"):
            st.session_state[state_key] = selected
        if st.session_state.get(state_key):
            from healthzip.workflows.period_report import load_report
            report = load_report(repo, st.session_state[state_key])
            st.markdown(report["markdown"])
            st.download_button("下载这份复盘", report["markdown"], file_name="healthzip-review.md")
