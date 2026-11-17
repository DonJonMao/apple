"""Task-scoped calls to existing calculators, using repository-owned records."""
from healthzip.analytics.v13 import snapshot
from healthzip.science import evaluate
from healthzip.science.contracts import Window, select_as_of
from healthzip.science.semantics import flatten_record, outcome_series


def strength_inputs(repo, request, analysis, task):
    records, context = snapshot(repo, request["cutoff_time"], retrospective=request["mode"] == "retrospective",
        window_start=analysis["window_start"], window_end=analysis["window_end"], include_sources=False)
    rows = [r for r in records if r.get("record_kind") == "strength_set"]
    if task:
        rows = [r for r in rows if r.get("catalog_id", r.get("exercise_id")) == task["exercise_id"]
                and r.get("condition_key") == task["condition_key"]]
    ids = {r.get("set_uuid") for r in rows}
    window = Window(analysis["window_start"], analysis["window_end"], request["cutoff_time"], request["timezone"])
    plans, _ = select_as_of(context["session_plans"], window)
    context["plan_snapshot"] = {"sets": [s for p in plans for s in p["sets"] if s["id"] in ids]} if plans else None
    if task:
        context["recommendation_outcomes"] = [r for r in context["recommendation_outcomes"] if r.get("task_id") == task["task_id"]]
    context.update(timezone=request["timezone"], retrospective=request["mode"] == "retrospective")
    return rows, context


def scoped_metrics(repo, request, analysis, task, metrics):
    rows, context = strength_inputs(repo, request, analysis, task)
    if task:
        for mid in ("STR-01", "STR-02", "STR-03", "STR-04", "STR-05", "STR-06", "STR-09", "STR-10",
                    "STR-15", "STR-27", "STR-28", "STR-29", "REPORT-RECOMMENDATION-FOLLOWUP"):
            if mid in metrics:
                metrics[mid] = evaluate(mid, rows, cutoff_time=request["cutoff_time"],
                    window_start=analysis["window_start"], window_end=analysis["window_end"], context=context)
    references = (metrics.get("STR-11") or {}).get("value")
    ids = {str(r["id"]) for r in references} if isinstance(references, list) else set()
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
