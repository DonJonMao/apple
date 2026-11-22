"""Reviews are explicit computations, with existing reports and tasks retained."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from healthzip.analytics.cache import revision_identity


def render_legacy_review(repo, *, timezone_name="Asia/Shanghai", section="问题分析", show_history=True):
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
    if not report:
        from healthzip.ui.joint_health import render_joint_health
        render_joint_health(value["v13"], key="review_current_joint")
    if report:
        from healthzip.ui.joint_health import render_joint_health
        render_joint_health(report["current"], key="review_joint", charts=True)
        st.markdown(report["markdown"])
        st.download_button("下载身体与力量联合报告" if period else "下载当前分析窗口报告", report["markdown"],
                           file_name=f"healthzip-{period or 'analysis'}.md", mime="text/markdown")
    if section == "报告":
        st.download_button("下载当前分析结果", json.dumps(value, ensure_ascii=False, indent=2, default=str),
                           file_name="healthzip-analysis.json", mime="application/json")
    if show_history:
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
            _render_full_text(report["markdown"], "history:" + report["report_id"])
            st.download_button("下载这份复盘", report["markdown"], file_name="healthzip-review.md")


def render_review(repo, *, timezone_name="Asia/Shanghai"):
    st.subheader("复盘")
    section = st.radio("复盘内容", ["周月复盘", "问题分析", "行动复评", "报告"], horizontal=True, key="review_section")
    if section == "问题分析":
        from healthzip.ui.question_page import render_questions
        render_questions(repo, timezone_name=timezone_name)
        if st.toggle("打开专项分析与已有训练建议", key="review_advanced"):
            render_legacy_review(repo, timezone_name=timezone_name)
        return
    if section == "行动复评":
        from healthzip.ui.question_page import render_actions
        render_actions(repo)
        return
    _render_period_preview(repo, timezone_name, section)
    if section == "报告" and st.toggle("导出自定义分析窗口", key="review_custom_export"):
        render_legacy_review(repo, timezone_name=timezone_name, section="报告", show_history=False)
    _history(repo)


def _render_period_preview(repo, timezone_name, section):
    from healthzip.analytics.workspace_summary import workspace_summary
    from healthzip.ui.overview import _select_cards, _trend
    from healthzip.ui.report_jobs import poll_report, submit_report
    from healthzip.workflows.dependencies import input_version
    label = st.radio("复盘范围", ["本周", "本月"], horizontal=True, key="review_period")
    period = "week" if label == "本周" else "month"
    summary = workspace_summary(repo, "总览", timezone_name=timezone_name)
    item = next(row for row in summary["periods"] if row["period"] == period)
    first = datetime.fromisoformat(item["window"]["start"]).astimezone(ZoneInfo(timezone_name))
    end = datetime.fromisoformat(item["window"]["end"]).astimezone(ZoneInfo(timezone_name))
    st.caption(f"{first:%Y-%m-%d} — {end:%Y-%m-%d %H:%M} · {timezone_name}")
    cards = _select_cards(item["facts"])
    if cards:
        for column, (title, fact) in zip(st.columns(len(cards)), cards):
            number = f"{fact['value']:,.0f}" if fact.get("unit") in {"次", "场", "组"} else f"{fact['value']:,.1f}"
            column.metric(title, f"{number} {fact.get('unit', '')}")
        _trend(item)
        for observation in item.get("conclusions", [])[:3]:
            st.write(observation)
    else:
        st.info("本期还没有可用于复盘的记录。可以直接记录训练或导入健康数据。")
    st.caption("上方为本地事实预览。生成完整复盘会进一步核对训练背景、前期比较与本地资料依据。")
    slot = "period_report_job:" + str(repo.path.resolve()) + ":" + timezone_name + ":" + period
    job = st.session_state.get(slot)
    status = poll_report(job["key"]) if job else None
    pending = status and status["status"] == "pending"
    context_id = st.session_state.get("analysis_contexts", {}).get(str(repo.path.resolve()))
    if st.button("生成当前周期复盘", type="primary", disabled=bool(pending), key="generate_period_report"):
        revision = input_version(repo, context_id)
        attempt = job.get("attempt", 0)+1 if status and status["status"] in {"failed", "expired"} else 0
        key = submit_report(str(repo.path.resolve()), cutoff_time=item["window"]["end"], timezone_name=timezone_name,
                            period=period, context_id=context_id, revision=revision, attempt=attempt)
        from healthzip.ui.health_explanation import knowledge_clock
        st.session_state[slot] = {"key": key, "revision": revision, "attempt": attempt,
                                  "knowledge": knowledge_clock(".local/knowledge")}
        job = st.session_state[slot]
        pending = True
    if job:
        poll = st.fragment(run_every=1 if pending else None)(_render_report_progress)
        poll(slot, str(repo.path.resolve()), context_id)


def _render_report_progress(slot, database, context_id):
    from healthzip.db.repository import Repository
    from healthzip.ui.report_jobs import poll_report, report_progress
    from healthzip.workflows.dependencies import input_version
    job = st.session_state[slot]
    status = poll_report(job["key"])
    if status["status"] == "pending":
        st.info(f"{report_progress(job['key'])} · 已用 {status['elapsed_seconds']:.0f} 秒。可以切页，返回后继续查看。")
        return
    if not job.get("settled"):
        st.session_state[slot] = {**job, "settled": True}
        st.rerun()
    if status["status"] in {"failed", "expired"}:
        st.warning("本次复盘任务未完成或已过期。可以重新生成；已经保存的复盘在下方历史中。")
        return
    report = status["result"]
    repo = Repository(database)
    try:
        changed = input_version(repo, context_id) != job["revision"]
    finally:
        repo.close()
    if changed:
        st.caption("以下复盘保留生成时的范围和记录版本，当前数据已有更新。")
    from healthzip.ui.health_explanation import knowledge_clock
    if job.get("knowledge") != knowledge_clock(".local/knowledge"):
        st.caption("资料或用途审核已有更新。以下内容保留为历史复盘，新解释请重新生成并核对当前依据。")
    st.success(f"完整本地复盘已保存，用时 {report['job_elapsed_seconds']:.2f} 秒。")
    from healthzip.ui.joint_health import render_joint_health
    render_joint_health(report["current"], key="review_completed_joint", charts=True)
    with st.expander("查看完整复盘与原始依据", expanded=False):
        _render_full_text(report["markdown"], "completed:" + report["report_id"])
    st.download_button("下载身体与力量联合报告", report["markdown"], file_name=f"healthzip-{report['period']}.md", mime="text/markdown")


def _render_full_text(markdown, key):
    """Keep the full frozen download while bounding browser text transfers."""
    limit = 100_000
    if len(markdown) <= limit:
        st.markdown(markdown)
        return
    st.caption(f"完整复盘含较多逐组记录与原始依据，共 {len(markdown):,} 字符。可下载全文，或按页查看。")
    if st.toggle("按页查看完整复盘文本", key="report_text_open:" + key):
        total = (len(markdown) + limit - 1) // limit
        page = st.number_input("正文页", min_value=1, max_value=total, value=1, key="report_text_page:" + key)
        st.caption(f"第 {page}/{total} 页；分页只限制传给浏览器的文本，计算、保存和下载均保留全文。")
        st.code(markdown[(page-1)*limit:page*limit], language="markdown", wrap_lines=True)
