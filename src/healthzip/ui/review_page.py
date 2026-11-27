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
                report = create_report(repo, current, period=period, include_details=True)
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
    state_key = "opened_report:" + str(repo.path.resolve())
    with st.expander("已保存的复盘"):
        exists = repo.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='joint_period_report'")
        rows = repo.rows("SELECT report_id,created_at,json_extract(payload_json,'$.period') AS period "
                         "FROM joint_period_report WHERE user_id='local' ORDER BY created_at DESC LIMIT 30") if exists else []
        if not rows:
            st.caption("尚无已保存的联合复盘。生成后可在这里重新打开。")
            return
        from healthzip.analytics.display_format import local_timestamp
        zone = st.session_state.get("analysis_timezone", "Asia/Shanghai")
        labels = {row["report_id"]: f"{local_timestamp(row['created_at'], zone)} · {'周' if row['period'] == 'week' else '月'}复盘" for row in rows}
        selected = st.selectbox("历史复盘", list(labels), format_func=labels.get)
        if st.button("打开这份复盘"):
            st.session_state[state_key] = selected
            st.rerun()
    if st.session_state.get(state_key):
        from healthzip.workflows.period_report import load_report
        report = load_report(repo, st.session_state[state_key])
        current_sources = _render_report_source_status(report, repo=repo)
        _render_readable_report(report, "history:" + report["report_id"])
        _render_frozen_details(repo, report, "history:" + report["report_id"], current_sources=current_sources)
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
    opened_key = "opened_report:" + str(repo.path.resolve())
    if st.session_state.get(opened_key):
        if st.button("返回当前周期复盘", key="close_saved_report"):
            st.session_state.pop(opened_key, None)
            st.rerun()
        _history(repo)
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
    slot = "period_report_job:" + str(repo.path.resolve()) + ":" + timezone_name + ":" + period
    job = st.session_state.get(slot)
    status = poll_report(job["key"]) if job else None
    completed = status and status["status"] == "ready"
    summary = workspace_summary(repo, "总览", timezone_name=timezone_name, period=period)
    item = next(row for row in summary["periods"] if row["period"] == period)
    first = datetime.fromisoformat(item["window"]["start"]).astimezone(ZoneInfo(timezone_name))
    end = datetime.fromisoformat(item["window"]["end"]).astimezone(ZoneInfo(timezone_name))
    if not completed:
        st.caption(f"{first:%Y-%m-%d} — {end:%Y-%m-%d %H:%M} · {timezone_name}")
    cards = _select_cards(item["facts"])
    if cards and not completed:
        for observation in item.get("conclusions", [])[:3]:
            st.write(observation)
        for column, (title, fact) in zip(st.columns(len(cards)), cards):
            number = f"{fact['value']:,.0f}" if fact.get("unit") in {"次", "场", "组"} else f"{fact['value']:,.1f}"
            column.metric(title, f"{number} {fact.get('unit', '')}")
        _trend(item)
    elif not cards and not completed:
        st.info("本期还没有可用于复盘的记录。可以直接记录训练或导入健康数据。")
    if not completed:
        st.caption("生成复盘后，这份阅读内容会补充训练背景、解释、行动与冻结依据。")
    pending = status and status["status"] == "pending"
    context_id = st.session_state.get("analysis_contexts", {}).get(str(repo.path.resolve()))
    if st.button("生成当前周期复盘", type="primary", disabled=bool(pending), key="generate_period_report"):
        revision = input_version(repo, context_id)
        attempt = job.get("attempt", 0)+1 if job else 0
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
    current_sources = _render_report_source_status(report)
    _render_readable_report(report, "completed:" + report["report_id"])
    st.caption(f"完整本地复盘已保存，用时 {report['job_elapsed_seconds']:.2f} 秒。")
    from contextlib import closing
    with closing(Repository(database)) as details_repo:
        _render_frozen_details(details_repo, report, "completed:" + report["report_id"], current_sources=current_sources)
    st.download_button("下载身体与力量联合报告", report["markdown"], file_name=f"healthzip-{report['period']}.md", mime="text/markdown")


def report_sections(markdown):
    """Split at Markdown chapter boundaries, never inside tables or code fences."""
    sections, lines, title, fenced = [], [], "报告开头", False
    for line in markdown.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            if lines:
                sections.append((title, "\n".join(lines)))
            title, lines = line[3:], []
        lines.append(line)
    if lines:
        sections.append((title, "\n".join(lines)))
    return sections


def _render_full_text(markdown, key):
    if len(markdown) <= 50_000:
        st.markdown(markdown)
        return
    sections = report_sections(markdown)
    st.caption("按章节查看；下载保留完整正文，表格与句子不拆分。")
    selected = st.selectbox("报告章节", range(len(sections)), format_func=lambda i: sections[i][0],
                            key="report_chapter:" + key)
    st.markdown(sections[selected][1])


def _render_readable_report(report, key):
    """One reading path: main findings, frozen chart, then explanation/actions."""
    reading = report.get("reading_view")
    st.markdown('<span data-hz-report-id="' + report["report_id"] + '" data-reading-view="'
                + (reading or {}).get("version", "legacy") + '" style="display:none"></span>', unsafe_allow_html=True)
    if not reading:
        _render_full_text(report["markdown"], key)
        return
    sections = report_sections(report["markdown"])
    opening = next((body for title, body in sections if title == "报告开头"), "")
    # The complete frozen opening remains available below. Keep its title and
    # interval compact so mobile readers reach an actual finding in one screen.
    header = [line for line in opening.splitlines() if line.strip()]
    st.caption(" · ".join(line.lstrip("# ") for line in header[:2]))
    for title, body in sections:
        if title in {"本期主要变化", "已填写的状态与备注"}:
            st.markdown(body.replace("## " + title, "### " + title, 1))
    charts = reading.get("charts", [])
    if charts:
        from healthzip.ui.health_comparison import _chart, _stream_name
        choices = [(chart, stream) for chart in charts for stream in chart["comparison"]["streams"]]
        index = st.selectbox("查看本期趋势", range(len(choices)),
            format_func=lambda i: choices[i][0]["title"] + " · " + _stream_name(choices[i][1]), key="report_chart:" + key)
        chart, stream = choices[index]
        _chart(stream, chart["title"], chart["unit"], chart["scale"], "report_plot:" + key)
    for title, body in sections:
        if title not in {"报告开头", "本期主要变化", "已填写的状态与备注"}:
            st.markdown(body)
    with st.expander("报告范围与阅读口径"):
        st.markdown(opening)


def _render_report_source_status(report, *, repo=None):
    from healthzip.workflows.reports import current_report_source_status
    current = current_report_source_status(report, repo=repo)
    restricted = [i for i in current["items"] if i["status"] != "verified"]
    if current["status"] == "unavailable":
        st.caption(current["label"])
    elif restricted:
        st.warning(f"这份历史报告有 {len(restricted)} 个主张或依赖来源当前不可直接用于新建议；冻结正文未改写。")
        for item in restricted:
            st.caption(item["label"])
    return {(i["claim_id"], i["version"]): i for i in current["items"]}


def _render_frozen_details(repo, report, key, *, current_sources=None):
    if current_sources is None:
        current_sources = _render_report_source_status(report, repo=repo)
    questions = report.get("questions", [])
    if questions:
        with st.expander("按问题查看冻结记录与依据"):
            selected = st.selectbox("冻结问题", range(len(questions)),
                format_func=lambda i: questions[i]["title"], key="frozen_question:" + key)
            preview = questions[selected]
            # Streamlit executes collapsed expanders too. A deliberate request
            # gates object loading instead of merely putting work in an expander.
            requested_key = "requested_question:" + key
            if st.button("读取这个问题的冻结明细", key="read_question:" + key):
                st.session_state[requested_key] = preview["id"]
            if st.session_state.get(requested_key) != preview["id"]:
                st.caption(preview.get("observation", "选择问题后读取其冻结记录。"))
            else:
                from healthzip.workflows.report_objects import read_object, read_question
                question = read_question(repo, preview)
                st.caption("以下保留生成时的记录与来源版本。当前建议需重新核对，不以历史解释替代。")
                rows = question.get("rows", [])
                if rows:
                    page = st.number_input("记录页", min_value=1, max_value=max(1, (len(rows)+49)//50),
                                           key="frozen_records:" + key)
                    labels = {"date": "日期", "first_date": "比较日期", "title": "项目", "source": "来源",
                              "value": "本期值", "first_value": "前期值", "unit": "单位", "difference": "差值",
                              "exercise": "动作", "reps": "次数", "load": "负荷", "position": "组位"}
                    st.dataframe([{labels[k]: v for k, v in row.items() if k in labels}
                                  for row in rows[(page-1)*50:page*50]], hide_index=True, use_container_width=True)
                training = question.get("ordinary_training", {})
                ordinary = training.get("series", [])
                if training.get("index_ref"):
                    if st.button("读取动作轨迹目录", key="read_training_index:" + key):
                        st.session_state["training_index:" + key] = training["index_ref"]
                    if st.session_state.get("training_index:" + key) == training["index_ref"]:
                        ordinary = read_object(repo, training["index_ref"])
                if ordinary:
                    index = st.selectbox("动作与条件轨迹", range(len(ordinary)),
                        format_func=lambda i: ordinary[i]["summary"], key="frozen_training:" + key)
                    group = read_object(repo, ordinary[index]["reference"]) if "reference" in ordinary[index] else ordinary[index]
                    st.dataframe(group["points"], hide_index=True, use_container_width=True)
                for item in question.get("evidence", {}).get("items", []):
                    status = current_sources.get((item["claim_id"], item["version"]))
                    if status and status["status"] != "verified":
                        st.warning(status["label"])
                    st.write(item["statement"])
                    st.caption("；".join(item.get("limitations", [])))
                    for source in item.get("citations", []):
                        st.markdown(f"[{source['title']}]({source['url']})")
                st.caption("事实身份：" + question.get("fact_id", "旧版本未单列"))
    _audit_download(repo, report, key)


def _audit_download(repo, report, key):
    if st.button("准备完整审计包", key="prepare_audit:" + key):
        from healthzip.workflows.report_objects import audit_bundle
        st.session_state["audit:" + key] = json.dumps(audit_bundle(repo, report["report_id"]), ensure_ascii=False)
    if "audit:" + key in st.session_state:
        st.download_button("下载完整审计包", st.session_state["audit:" + key],
                           file_name="healthzip-frozen-audit.json", mime="application/json", key="download_audit:" + key)
