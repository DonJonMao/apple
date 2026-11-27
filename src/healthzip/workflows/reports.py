"""Analysis refresh, calendar reports and pages share the workflow service."""

from .contracts import WorkflowRequest
from .report_inputs import period_facts
from .service import run_workflow


def review_analysis(repo, analysis, *, period=None, include_background=False, knowledge_root=".local/knowledge", include_session_background=False):
    cutoff, zone = analysis["cutoff_time"], analysis["timezone"]
    context_id = analysis.get("selection_context", {}).get("workflow_context_id")
    selection_id = None
    if analysis.get("selection_context"):
        from healthzip.analytics.v13 import persist
        selection_id = persist(repo, analysis)
    bounds_args = {} if period else {"window_start": analysis["window_start"], "window_end": analysis["window_end"],
                                    "fact_period": analysis.get("period")}
    selection = analysis
    tasks = {task["task_id"]: task for task in analysis["strength_tasks"]}
    if period:
        from .calendar import completed_periods
        bounds = completed_periods(cutoff, zone, period)
        selection = period_facts(repo, cutoff_time=cutoff, timezone_name=zone,
            window_start=bounds[0][0], window_end=bounds[-1][1], context=analysis.get("selection_context"),
            retrospective=analysis.get("retrospective", False))
        current = period_facts(repo, cutoff_time=cutoff, timezone_name=zone, period=period,
            context=analysis.get("selection_context"), retrospective=analysis.get("retrospective", False))
        tasks = {task["task_id"]: task for task in selection["strength_tasks"] + current["strength_tasks"]}
    runs = []
    ordinary = [task for task in tasks.values() if task.get("task_metrics_scope") == "requested_only"]
    if ordinary:
        runs.append(run_workflow(repo, WorkflowRequest("W4", cutoff_time=cutoff, timezone=zone,
            window_days=analysis.get("window_days", 30), period=period, result_metric_id="STR-11",
            mode="retrospective" if analysis.get("retrospective") else "prospective", context_id=context_id,
            selection_analysis_id=selection_id, context_policy="preserve_facts", ordinary_inventory=True,
            include_session_background=include_session_background, **bounds_args), knowledge_root=knowledge_root))
    for task in tasks.values():
        if task.get("task_metrics_scope") == "requested_only":
            continue
        runs.append(run_workflow(repo, WorkflowRequest("W4", cutoff_time=cutoff, timezone=zone,
            window_days=analysis.get("window_days", 30), period=period, task_id=task["task_id"], result_metric_id="STR-11",
            mode="retrospective" if analysis.get("retrospective") else "prospective", context_id=context_id,
            selection_analysis_id=selection_id, context_policy="preserve_facts",
            include_session_background=include_session_background, **bounds_args),
            knowledge_root=knowledge_root))
    if include_background:
        for wid in ("W2", "W3", "W5"):
            runs.append(run_workflow(repo, WorkflowRequest(wid, cutoff_time=cutoff, timezone=zone,
                window_days=analysis.get("window_days", 30), period=period,
                mode="retrospective" if analysis.get("retrospective") else "prospective", context_id=context_id,
                selection_analysis_id=selection_id, context_policy="preserve_facts", **bounds_args), knowledge_root=knowledge_root))
    return runs


def markdown(runs, *, repo):
    """Render frozen facts and authority origins, without new calculations."""
    lines = ["", "## 同一分析核心的复核", ""]
    for run in runs:
        from .presentation import frozen_fact_lines
        from .storage import load_analysis, load_run
        run = load_run(repo, run["run_id"])
        lines += [f"### {run['title']}", "", f"运行 `{run['run_id']}`；截止 {run['request']['cutoff_time']}。", ""]
        restriction = run["supplements"].get("context_restriction")
        if restriction:
            lines += [restriction["limitation"],
                      f"原声明 `{restriction['context_id']}`；受限原因 `{restriction['reason']}`。", ""]
        source = run["supplements"].get("source_report")
        if source:
            lines += [f"历史报告 `{source['run_id']}`：原截止 {source['cutoff_time']}；"
                      f"历史比较范围 {source['window_start']} 至 {source['window_end']}（不含终点）。",
                      f"本次行动核对时刻 {source['current_action_cutoff_time']}；历史报告仅作来源链接，当前目标与当前查看范围另行核对，原报告不变。", ""]
        lines += frozen_fact_lines(load_analysis(repo, run["run_id"]), run)
        review = run["supplements"].get("long_term_review")
        if review:
            lines += [f"比较范围：{review['window']['start']} 至 {review['window']['end']}（不含终点）；每个可比任务以周期内首条预指定参考为起点。", ""]
            lines += ["本比较周期已启动长期复核。" if review["start_long_term_review"] else "本比较周期未触发描述性未改善分支；各项记录仍分别保留。", ""]
            for series in review["series"]:
                first = series["anchor"]
                lines.append(f"- 同条件负荷 {first['recorded_load']} {first['load_unit']}；{series['n']} 次参考，跨度 {series['span_days']:g} 天；实际使用 {series['rir_used_n']} 次 RIR 差值比较。")
            for task in review.get("tasks", []):
                for comparison in task["comparisons"]:
                    lines.append(f"- {comparison['observed_at']}：负荷差 {comparison['load_change']} {comparison['load_unit']}，次数差 {comparison['repetitions_change']}，RIR 差 {comparison['rir_change']}；{comparison['identity']}。记录 `{comparison['record_id']}` 对照 `{comparison['anchor_record_id']}`。")
            lines += ["", "；".join(review["limitations"]), ""]
        for hypothesis in run["hypotheses"]:
            lines.append(f"- {hypothesis['title']}：{hypothesis['status']}；支持 {hypothesis['support']}；削弱 {hypothesis['counterevidence']}；未知 {hypothesis.get('unknown', [])}；{hypothesis['next_step']}")
            for claim in hypothesis.get("source_claim_refs", []):
                lines.append(f"  来源解释 `{claim['claim_id']}@{claim['version']}`（{claim['relation']}）：{'；'.join(claim['statements'])}。用途限于记录/方法解释，不确认个人原因。")
        for query in run["knowledge"]["queries"]:
            lines += ["", f"来源用途：{query['metric_id']} / {query['status']}。"]
            for span in query.get("spans", []):
                lines.append(f"- `{span['source_id']}` / `{span['source_version']}` / `{span['span_id']}`，定位 {span.get('locator')}。")
            for claim in query.get("claims", []):
                lines.append(f"- 已核对命题：{'；'.join(claim['statements'])}；适用范围 {claim['scope']}；限制 {claim['limitations']}。")
        for basis in run.get("linked_candidate_bases", []):
            lines += ["", f"候选 `{basis['candidate_id']}` 的冻结依据（执行前仍须当前复查）：", ""]
            for rule in basis["strategy_basis"]:
                lines.append(f"- 策略依据 `{rule['rule_id']}@{rule['version']}`；逻辑 {rule['application_logic']}；来源 {rule['source_spans']}；限制 {rule['limits']}。")
            if basis.get("discussion_basis"):
                lines.append(f"- 讨论依据：{basis['discussion_basis']}")
            lines.append(f"- 个人记录依据：{basis['personal_record_basis']['source_record_ids']}。")
            lines.append(f"- 实际参考：{basis['personal_record_basis']['reference_observation']}。")
            for origin in basis["numeric_origins"]:
                lines.append(f"- {origin['field']} {origin['value']} {origin['unit']}：{origin['origin']}。{origin['limitation']}")
        followup = run["supplements"].get("followup", {})
        for row in followup.get("STR-27", {}).get("value") or []:
            lines.append(f"- 候选 `{row['recommendation_id']}`：采纳 {row['adoption']}；执行 {row['execution_state']}；任务达成 {row['short_term_success']}。")
        report = followup.get("REPORT-RECOMMENDATION-FOLLOWUP", {})
        if report.get("value") is not None:
            lines.append(f"- 后续观察（冻结窗口与缺项）：{report['value']}")
        partial = run["supplements"].get("partial_current_period", {})
        if partial:
            lines += ["", f"本期未结束部分：{partial['start']} 至 {partial['cutoff_time']}；以下新反馈不计入前两个完整周期的完成率。", ""]
            for row in partial.get("followup", {}).get("STR-27", {}).get("value") or []:
                lines.append(f"- 候选 `{row['recommendation_id']}`：采纳 {row['adoption']}；执行 {row['execution_state']}；任务达成 {row['short_term_success']}；后续观察 {row.get('followup')}。")
        lines += ["", "采纳、执行、达标与因果效果分开；没有匹配行动规则时，不产生系统数值候选。", ""]
    return lines


def period_questions(repo, current, *, period, knowledge_root, source_filter=(), cycle_enabled=None):
    """The normal question producer, once for a union of applicable dependencies.

    Source explanations are separate from the factual identity, so a withdrawn
    claim cannot erase an observation or rewrite a historical result.
    """
    import sqlite3
    from pathlib import Path

    from healthzip.analytics.body_metrics import analyze_questions
    from healthzip.analytics.body_questions import QUESTIONS
    from healthzip.knowledge import KnowledgeWorkbench
    from healthzip.knowledge.topics import question_sources
    from healthzip.ui.preferences import load_preferences

    enabled = bool(load_preferences(repo.path).get("cycle_enabled")) if cycle_enabled is None else cycle_enabled
    # Include real cycle records as-of, not a guessed phase. Empty optional
    # results retain a distinct status but do not occupy the readable body.
    questions = analyze_questions(repo, window_start=current["window_start"], window_end=current["window_end"],
        cutoff_time=current["cutoff_time"], timezone_name=current["timezone"], source_filter=source_filter,
        question_ids=list(QUESTIONS), period=period)
    w, opening_failure = None, None
    try:
        if all((Path(knowledge_root) / name).is_file() for name in ("sources.sqlite3", "theories.sqlite3")):
            try:
                w = KnowledgeWorkbench(knowledge_root)
            except (OSError, sqlite3.Error, ValueError) as exc:
                opening_failure = type(exc).__name__
        for question in questions:
            question["report_comparison_context"] = {
                "canonical_retrospective": bool(current.get("retrospective")),
                "declared_sleep_present": bool(current.get("selection_context", {}).get("sleep_selection")),
                "question_mode": "as_of",
                "question_sleep_definition": "记录睡眠事件按结束日期归属，完整日代表值的期间中位数",
                "difference_is_explicit": bool(current.get("retrospective") or current.get("selection_context", {}).get("sleep_selection"))}
            question.setdefault("analysis_identity", {}).update(visibility_mode="as_of",
                sleep_definition="recorded_episode_end_date_complete_daily_period_median")
            has_records = bool(question.get("rows") or question.get("action_reviews") or question.get("goal_context"))
            question["report_status"] = ("not_requested" if question["id"] == "W8" and not enabled and not has_records
                                          else "available" if has_records else "no_records")
            if question["report_status"] in {"not_requested", "no_records"}:
                question["evidence"] = {"status": "not_requested", "items": []}
                continue
            if w is None:
                question["evidence"] = {"status": "service_failure" if opening_failure else "not_configured",
                    "items": [], "reason": opening_failure or "local_knowledge_store_missing"}
                continue
            try:
                question["evidence"] = question_sources(w, question["id"], include_evidence=True)
            except (OSError, sqlite3.Error, ValueError) as exc:
                question["evidence"] = {"status": "service_failure", "items": [], "reason": type(exc).__name__}
    finally:
        if w is not None:
            w.close()
    return questions


def current_report_source_status(report, *, repo=None, knowledge_root=".local/knowledge"):
    """Current annotations only; frozen report bytes and historical uses stay intact."""
    import sqlite3
    from pathlib import Path

    from healthzip.knowledge import KnowledgeWorkbench
    from healthzip.knowledge.core import _claim

    identities = set()
    if repo is not None and not report.get("questions"):
        import json
        run_ids = report.get("workflow_run_ids", []) + report.get("historical_run_ids", [])
        rows = repo.rows("SELECT json_extract(result_json,'$.knowledge.queries') FROM workflow_run "
            "WHERE user_id='local' AND run_id IN (SELECT value FROM json_each(?))", (json.dumps(run_ids),))
        for row in rows:
            for query in json.loads(row[0] or "[]"):
                for claim in query.get("claims", []):
                    identities.add((claim["claim_id"], claim.get("claim_version") or claim.get("version")))
    for question in report.get("questions", []):
        evidence = question.get("evidence") or {}
        for item in [*evidence.get("items", []), *evidence.get("restricted_items", []),
                     *evidence.get("claim_reviews", [])]:
            version = item.get("version") or item.get("claim_version")
            if item.get("claim_id") and version:
                identities.add((item["claim_id"], version))
            for required in item.get("required_claim_refs", []):
                identities.add((required["claim_id"], required.get("claim_version") or required.get("version")))
    if not identities:
        return {"status": "no_frozen_claims", "items": []}
    if not all((Path(knowledge_root) / name).is_file() for name in ("sources.sqlite3", "theories.sqlite3")):
        return {"status": "unavailable", "items": [], "label": "当前资料库不可用；无法核对历史主张的当前状态，冻结原文仍保留。"}
    w = None
    try:
        w = KnowledgeWorkbench(knowledge_root)
        items = []
        for identity, version in sorted(identities):
            row = w.lib.theories.execute("SELECT status FROM source_claim WHERE claim_id=? AND version=?", (identity, version)).fetchone()
            state, reason = (row["status"] if row else "missing"), None
            if state == "verified":
                try:
                    _claim(w, {"claim_id": identity, "version": version})
                except ValueError as exc:
                    reason = str(exc)
                    state = "source_withdrawn" if reason == "withdrawn" else "needs_review"
            labels = {"verified": "该版本当前仍可用于其原有审核范围；不自动成为个人建议。",
                "revoked": "该主张已撤销，不能支持当前新建议；原文仅保留为历史。",
                "disabled": "该主张当前已停用，不能支持新建议。",
                "source_withdrawn": "该主张的来源已撤回，不能支持当前新建议；原文仅保留为历史。",
                "needs_review": "该主张或来源当前需要重新审核，不能直接作为新建议。",
                "missing": "当前库未找到该历史版本，无法核对当前适用状态。"}
            items.append({"claim_id": identity, "version": version, "status": state,
                          "label": labels.get(state, labels["needs_review"]), "reason": reason})
        return {"status": "current" if all(i["status"] == "verified" for i in items) else "restricted", "items": items}
    except (OSError, sqlite3.Error, ValueError) as exc:
        return {"status": "unavailable", "items": [], "reason": type(exc).__name__,
                "label": "当前资料状态核对暂不可用；冻结事实和原文仍可查看，不将读取失败标成科学撤回。"}
    finally:
        if w is not None:
            w.close()
