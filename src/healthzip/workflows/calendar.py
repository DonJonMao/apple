"""Complete local calendar comparisons, with the current partial period separate."""
from datetime import timedelta
from zoneinfo import ZoneInfo

from healthzip.analytics.v13 import analyze
from healthzip.science.contracts import instant


def completed_periods(cutoff_time, timezone, period):
    local = instant(cutoff_time).astimezone(ZoneInfo(timezone))
    current = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        current -= timedelta(days=current.weekday())
        prior, earlier = current - timedelta(days=7), current - timedelta(days=14)
    elif period == "month":
        current = current.replace(day=1)
        prior = (current - timedelta(days=1)).replace(day=1)
        earlier = (prior - timedelta(days=1)).replace(day=1)
    else:
        raise ValueError("calendar_comparison_requires_week_or_month")
    return [(earlier.isoformat(), prior.isoformat()), (prior.isoformat(), current.isoformat())]


def comparison(repo, request, context):
    metric_id = request.get("result_metric_id") or ("STR-11" if request.get("task_id") else "BODY-MASS-DAILY")
    windows = []
    for start, end in completed_periods(request["cutoff_time"], request["timezone"], request["period"]):
        analysis = analyze(repo, cutoff_time=request["cutoff_time"], timezone_name=request["timezone"],
            window_start=start, window_end=end, context=context, retrospective=request["mode"] == "retrospective", use_cache=False)
        task = next((item for item in analysis["strength_tasks"] if item["task_id"] == request.get("task_id")), None)
        metric = (task["metrics"].get(metric_id) if task else None) if metric_id == "STR-11" else analysis["metrics"][metric_id]
        windows.append({"start": start, "end": end, "complete_calendar_period": True,
                        "metric": metric, "missing_reason": "selected_task_not_recorded_in_period" if metric is None else None})
    return {"metric_id": metric_id, "period": request["period"], "periods": windows,
        "identity": "two_preceding_complete_local_calendar_periods",
        "limitations": ["本期未结束部分另列；完整日历范围不代表每天都有记录。",
                        "按实际日期、来源和协议展示；不插值，不搜索最有利窗口或因果滞后。"]}
