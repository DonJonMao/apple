"""Align existing canonical daily facts with recorded context, without a score."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from healthzip.science.contracts import canonical_hash, instant

VERSION = "joint-health-context-1.0.0"


def sleep_comparison_metric(metric):
    """REPORT-STATE-SUMMARY also carries heart/weight streams; never label those sleep."""
    comparison = metric.get("comparison", {})
    return {**metric, "comparison": {**comparison, "streams": [stream for stream in comparison.get("streams", [])
        if stream.get("metric_id") == "sleep_observed_minutes_by_wake_date"]}}


def joint_health_context(metrics, sessions, window, *, records=None):
    """Keep streams distinct and use only events inside the frozen analysis range.

    Sleep has already been attributed by the canonical event selector. A shared
    local date is an alignment convention, not proof that the heart sample was
    recorded after awakening or that training caused a change.
    """
    zone = ZoneInfo(window.get("timezone", "Asia/Shanghai"))
    start, end = instant(window["start"]), min(instant(window["end"]), instant(window["cutoff_time"]))
    daily = metrics.get("REPORT-STATE-SUMMARY", {}).get("daily_facts", [])
    grouped = defaultdict(lambda: defaultdict(list))
    for mid in ("STATE-RHR", "STATE-SDNN"):
        for source, points in (metrics.get(mid, {}).get("value") or {}).items():
            for point in points:
                day = point.get("date")
                if not day or point.get("value") is None:
                    continue
                grouped[day][mid].append({"value": point["value"], "source": source,
                    "source_record_ids": point.get("source_ids", []), "date": day,
                    "unit": "bpm" if mid == "STATE-RHR" else "ms"})
    for fact in daily:
        mid = fact.get("metric_id")
        if fact.get("series_id") == "observed_sleep_by_wake_date":
            mid = "sleep"
        if mid not in {"sleep", "STATE-FATIGUE", "STATE-SORENESS", "STATE-PAIN"} or fact.get("value") is None:
            continue
        grouped[fact["date"]][mid].append({"value": fact["value"], "unit": fact.get("unit"),
            "source": fact.get("source_id"), "source_record_ids": fact.get("source_record_ids", []),
            "date": fact["date"], "event_end": fact.get("event_end"), "protocol_id": fact.get("protocol_id")})
    for mid in ("STATE-FATIGUE", "STATE-SORENESS", "STATE-PAIN"):
        for observation in (metrics.get(mid, {}).get("value") or {}).get("observations", []):
            observed = observation.get("observed_at") or observation.get("event_end")
            if not observed:
                continue
            moment = instant(observed)
            if not start <= moment < end:
                continue
            day = moment.astimezone(zone).date().isoformat()
            if not grouped[day].get(mid):
                grouped[day][mid].append({**observation, "date": day,
                    "source_record_ids": [observation.get("id")]})
    training = []
    for session in sessions or []:
        observed = session.get("started_at")
        if not observed or session.get("deleted_at"):
            continue
        try:
            moment = instant(observed)
            visible = session.get("available_at")
            if not start <= moment < end or visible and instant(visible) > instant(window["cutoff_time"]):
                continue
        except (ValueError, TypeError):
            continue
        day = moment.astimezone(zone).date().isoformat()
        item = {"date": day, "started_at": observed, "ended_at": session.get("ended_at"),
                "session_id": session.get("session_id", session.get("id")),
                "session_rpe": session.get("session_rpe"), "srpe_protocol": session.get("srpe_protocol")}
        training.append(item)
        grouped[day]["training"].append(item)
    def overlaps(day):
        day_start = datetime.combine(datetime.fromisoformat(day).date(), time.min, zone)
        day_end = day_start + timedelta(days=1)
        return day_start < end and day_end > start
    points = [{"date": day, "facts": dict(facts)} for day, facts in sorted(grouped.items())
              if overlaps(day)]
    dates = {mid: sorted(point["date"] for point in points if point["facts"].get(mid))
             for mid in ("STATE-RHR", "STATE-SDNN", "sleep", "STATE-FATIGUE", "training")}
    overlap = sorted(set(dates["STATE-RHR"]) & set(dates["STATE-SDNN"]) & set(dates["sleep"]))
    result = {"version": VERSION, "window": window, "daily_points": points, "dates_by_metric": dates,
              "three_metric_overlap_dates": overlap, "three_metric_overlap_days": len(overlap),
              "training_sessions": training, "causal_attribution": None,
              "alignment": "sleep_event_end_local_date_to_same_local_date_heart",
              "temporal_order": "not_established_by_daily_values"}
    previous = metrics.get("STATE-RHR", {}).get("comparison", {}).get("windows", {}).get("previous")
    if records is not None and previous and instant(previous["start"]) < instant(previous["end"]):
        from healthzip.science import evaluate
        previous_metric = evaluate("STR-01", records, cutoff_time=window["cutoff_time"],
            window_start=previous["start"], window_end=previous["end"],
            context={"timezone": window.get("timezone", "Asia/Shanghai")})
        current_metric = metrics.get("STR-01", {})
        current_sets = (current_metric.get("value") or {}).get("completed_work_parent_sets")
        previous_sets = (previous_metric.get("value") or {}).get("completed_work_parent_sets")
        result["training_comparison"] = {"current_metric": current_metric, "previous_metric": previous_metric,
            "current_sets": current_sets, "previous_sets": previous_sets,
            "difference": current_sets - previous_sets if current_sets is not None and previous_sets is not None else None,
            "meaning": "recorded_execution_count_not_load_or_physiological_dose"}
    result["fact_id"] = "joint:" + canonical_hash(result)
    return result


def period_label(summary):
    window = summary.get("complete_window") or summary.get("observed_window") or summary.get("window", {})
    try:
        zone = ZoneInfo(window.get("timezone", "Asia/Shanghai"))
        start = datetime.fromisoformat(window["start"].replace("Z", "+00:00")).astimezone(zone)
        end = datetime.fromisoformat(window["end"].replace("Z", "+00:00")).astimezone(zone)
        if end.time().isoformat() == "00:00:00":
            end -= timedelta(microseconds=1)
        return f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}"
    except (KeyError, ValueError, TypeError):
        return "范围未注明"


def coverage_label(summary):
    return f"记录 {summary.get('recorded_days', 0)}/{summary.get('window_days', 0)} 天"


def comparison_statements(metric, title, unit, *, scale=1):
    """Personal numbers and dates are bound to the computed snapshot, never LLM text."""
    statements = []
    for stream in metric.get("comparison", {}).get("streams", []):
        current = stream.get("current", {})
        value = current.get("value")
        if value is None:
            continue
        text = f"{period_label(current)}，{title}日代表值的中位数为 {value / scale:.1f} {unit}"
        protocol = stream.get("protocol")
        if isinstance(protocol, (list, tuple)):
            identity = " / ".join(str(v) for v in protocol[:2] if v)
            if identity:
                text += f"（{identity}）"
        for key, label in (("previous", "前期"), ("reference", "个人参考")):
            other = stream.get(key, {})
            delta = stream.get(key + "_change", {}).get("absolute")
            if delta is None or other.get("value") is None:
                continue
            change = "相同" if delta == 0 else f"{'高' if delta > 0 else '低'} {abs(delta) / scale:.1f} {unit}"
            text += f"；较{label}（{period_label(other)}，{other['value'] / scale:.1f} {unit}）{change}"
        statements.append(text + "。")
    return statements


def joint_observations(snapshot):
    metrics = snapshot.get("metrics", {})
    context = snapshot.get("joint_health_context")
    if not context:
        context = joint_health_context(metrics, [], {"start": snapshot["window_start"],
            "end": snapshot["window_end"], "cutoff_time": snapshot["cutoff_time"],
            "timezone": snapshot.get("timezone", "Asia/Shanghai")})
    statements = []
    for mid, label, unit, scale in (("STATE-RHR", "日静息心率", "bpm", 1),
                                  ("STATE-SDNN", "SDNN", "ms", 1),
                                  ("REPORT-STATE-SUMMARY", "已记录睡眠", "小时", 60)):
        metric = metrics.get(mid, {})
        if mid == "REPORT-STATE-SUMMARY":
            metric = sleep_comparison_metric(metric)
        statements.extend(comparison_statements(metric, label, unit, scale=scale))
    overlap = context["three_metric_overlap_dates"]
    statements.append(f"睡眠结束日期与同日 RHR、SDNN 均有记录的日期共有 {len(overlap)} 天。"
                      + (f"范围 {overlap[0]} 至 {overlap[-1]}。" if overlap else "各指标仍按自己的真实记录展示。"))
    steps = []
    training = context.get("training_sessions", [])
    fatigue = context.get("dates_by_metric", {}).get("STATE-FATIGUE", [])
    if training:
        dates = sorted({item["date"] for item in training})
        statements.append(f"同一窗口已记录 {len(training)} 场训练，分布在 {len(dates)} 个日期（{'、'.join(dates[:5])}）。")
        steps.append("在力量页查看这些日期的实际组数、重量、次数与主观感受，核对它们与身体记录的时间对应；共同出现不能确定原因。")
    activity = context.get("training_comparison", {})
    if activity.get("current_sets") is not None and activity.get("previous_sets") is not None:
        statements.append(f"对应本期已记录完成工作组 {activity['current_sets']} 组，前期 {activity['previous_sets']} 组，"
                          f"相差 {activity['difference']:+g} 组。这里比较实际执行数量，不推断训练刺激或身体变化的原因。")
    if fatigue:
        statements.append("已记录主观疲劳的日期：" + "、".join(fatigue[:5]) + "。这些主观记录应与同期身体数值一并考虑，不能据此宣布恢复改善。")
        steps.append("结合已填写的疲劳记录核对当次训练表现；无需重复填写相同日期。")
    elif training:
        steps.append("若训练表现与身体数值方向不同，可补充最相关一次训练的主观疲劳，帮助区分数值变化与实际感受。")
    if not steps:
        steps.append("优先核对图中来源、测量时段或缺测日期；需要解释训练关系时，再记录对应日期的实际训练或感受。")
    return {"statements": statements, "next_steps": steps[:3], "context": context}


