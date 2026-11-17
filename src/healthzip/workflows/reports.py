"""Analysis refresh, calendar reports and pages share the workflow service."""
from healthzip.analytics.v13 import analyze

from .contracts import WorkflowRequest
from .service import run_workflow


def review_analysis(repo, analysis, *, period=None, include_background=False, knowledge_root=".local/knowledge"):
    cutoff, zone = analysis["cutoff_time"], analysis["timezone"]
    selection_id = None
    if analysis.get("selection_context"):
        from healthzip.analytics.v13 import persist
        selection_id = persist(repo, analysis)
    bounds_args = {} if period else {"window_start": analysis["window_start"], "window_end": analysis["window_end"]}
    selection = analysis
    if period:
        from .calendar import completed_periods
        bounds = completed_periods(cutoff, zone, period)
        selection = analyze(repo, cutoff_time=cutoff, timezone_name=zone,
            window_start=bounds[0][0], window_end=bounds[-1][1], context=analysis.get("selection_context"),
            retrospective=analysis.get("retrospective", False))
    runs = []
    for task in selection["strength_tasks"]:
        runs.append(run_workflow(repo, WorkflowRequest("W4", cutoff_time=cutoff, timezone=zone,
            window_days=analysis.get("window_days", 30), period=period, task_id=task["task_id"], result_metric_id="STR-11",
            mode="retrospective" if analysis.get("retrospective") else "prospective", selection_analysis_id=selection_id, **bounds_args),
            knowledge_root=knowledge_root))
    if include_background:
        for wid in ("W2", "W3", "W5"):
            runs.append(run_workflow(repo, WorkflowRequest(wid, cutoff_time=cutoff, timezone=zone,
                window_days=analysis.get("window_days", 30), period=period,
                mode="retrospective" if analysis.get("retrospective") else "prospective", selection_analysis_id=selection_id, **bounds_args), knowledge_root=knowledge_root))
    return runs


def markdown(runs):
    """Render frozen facts and authority origins, without new calculations."""
    lines = ["", "## 同一分析核心的复核", ""]
    for run in runs:
        lines += [f"### {run['title']}", "", f"运行 `{run['run_id']}`；截止 {run['request']['cutoff_time']}。", ""]
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
