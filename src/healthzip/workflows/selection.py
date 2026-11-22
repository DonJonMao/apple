"""Task-scoped calls to existing calculators, using repository-owned records."""
from healthzip.science.contracts import Window, select_as_of, task_metric_results
from healthzip.science.semantics import analysis_task, flatten_record, outcome_series

from .report_inputs import source_snapshot


def strength_inputs(repo, request, analysis, task):
    records, context = source_snapshot(repo, request["cutoff_time"], retrospective=request["mode"] == "retrospective",
        window_start=analysis["window_start"], window_end=analysis["window_end"], include_sources=False)
    rows = [r for r in records if r.get("record_kind") == "strength_set"]
    if task:
        task_ids = set(task["inventory_task_ids"]) if "inventory_task_ids" in task else {task["task_id"]}
        rows = [r for r in rows if analysis_task(r)["task_id"] in task_ids]
    ids = {r.get("set_uuid") for r in rows}
    window = Window(analysis["window_start"], analysis["window_end"], request["cutoff_time"], request["timezone"])
    plans, _ = select_as_of(context["session_plans"], window)
    context["plan_snapshot"] = {"sets": [s for p in plans for s in p["sets"] if s["id"] in ids]} if plans else None
    if task:
        context["recommendation_outcomes"] = [r for r in context["recommendation_outcomes"] if r.get("task_id") in task_ids]
    context.update(timezone=request["timezone"], retrospective=request["mode"] == "retrospective")
    return rows, context


def scoped_metrics(repo, request, analysis, task, metrics):
    rows, context = strength_inputs(repo, request, analysis, task)
    if task:
        scoped = (tuple(mid for mid in metrics if mid.startswith("STR-")) + ("REPORT-RECOMMENDATION-FOLLOWUP",)
                  if "inventory_task_ids" in task else ("STR-01", "STR-02", "STR-03", "STR-04", "STR-05", "STR-06", "STR-09", "STR-10",
                    "STR-15", "STR-27", "STR-28", "STR-29", "REPORT-RECOMMENDATION-FOLLOWUP"))
        from healthzip.science.engine import evaluate_subset
        metrics.update(evaluate_subset([mid for mid in scoped if mid in metrics], rows, cutoff_time=request["cutoff_time"],
            window_start=analysis["window_start"], window_end=analysis["window_end"], context=context))
    references = task_metric_results(metrics["STR-11"]) if "STR-11" in metrics else []
    ids = {str(r["id"]) for child in references for r in child["metric"]["value"] or []}
    points = []
    sessions = {s["session_id"]: s for s in context.get("sessions", [])}
    for raw in rows:
        if str(raw["id"]) not in ids:
            continue
        row = flatten_record(raw)
        series = outcome_series(row)
        points.append({"metric_id": "STR-11", "record_id": raw["id"], "date": raw["ended_at"],
            "task_id": series["task_id"], "normalized_load": series["normalized_load"],
            "normalized_unit": series["normalized_unit"],
            "value": row["reps"], "unit": "次", "recorded_load": row["load_value"], "load_unit": row["load_unit"],
            "load_basis": row["load_basis"], "rir": row.get("rir"),
            "rir_interval": row.get("rir_interval"), "stop_reason": row.get("stop_reason"),
            "quality": row.get("quality"), "session_id": row.get("session_id"),
            "training_started_at": sessions.get(row.get("session_id"), {}).get("started_at"),
            "stream": series["outcome_series_id"] if series["eligible"] else "unknown:" + raw["id"],
            "source": raw.get("source_method", "manual"), "condition_key": row.get("condition_key"),
            "comparable": series["eligible"]})
    return points


def session_backgrounds(repo, request, analysis, task, selection):
    """Actual sessions including those without a designated reference set."""
    from .longitudinal import body_context
    rows, context = strength_inputs(repo, request, analysis, task)
    sessions = {s["session_id"]: s for s in context.get("sessions", [])}
    groups = {}
    for row in rows:
        if row.get("completion_state") in {"completed", "aborted", "in_progress"} and not row.get("deleted_at"):
            groups.setdefault(row.get("session_id"), []).append(row)
    result = []
    for sid, actuals in groups.items():
        session = sessions.get(sid, {})
        start = session.get("started_at")
        if not start:
            continue
        result.append({"session_id": sid, "training_started_at": start,
            "reference_record_id": actuals[0]["id"], "actual_record_ids": [r["id"] for r in actuals],
            "identity": "actual_session_background_no_reference_set_inferred",
            "actual_records": [{k: r.get(k) for k in ("id", "set_uuid", "ended_at", "load_value", "load_unit", "reps", "rir", "condition_key")} for r in actuals],
            **body_context(repo, start, request, selection)})
    return sorted(result, key=lambda r: r["training_started_at"])
