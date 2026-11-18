"""Descriptive component comparisons, independent of statistical plateau inference."""
from datetime import timedelta

from healthzip.analytics.v13 import snapshot
from healthzip.science import evaluate
from healthzip.science.contracts import Window, instant, select_as_of
from healthzip.science.state import sleep_intervals, stream_key


def _rir_difference(first, later):
    def bounds(point):
        value = point.get("rir")
        return (value, value) if value is not None else (
            (point.get("rir_interval") or {}).get("lower"),
            (point.get("rir_interval") or {}).get("upper"))
    a, b = bounds(first), bounds(later)
    low = b[0] - a[1] if b[0] is not None and a[1] is not None else None
    high = b[1] - a[0] if b[1] is not None and a[0] is not None else None
    return low, high


def _compare(first, later):
    reps = later["value"] - first["value"]
    load = later["normalized_load"] - first["normalized_load"]
    difficulty = -load if first["load_basis"] == "assistance_setting" else load
    low, high = _rir_difference(first, later)
    if difficulty >= 0 and reps >= 0 and low is not None and low >= 0 and (difficulty > 0 or reps > 0 or low > 0):
        status = "recorded_joint_improvement"
    elif difficulty <= 0 and reps <= 0 and high is not None and high <= 0:
        status = "unchanged_or_lower_recorded_vector"
    elif low is None or high is None:
        status = "effort_not_exactly_comparable"
    else:
        status = "repetition_effort_tradeoff"
    return {"anchor_record_id": first["record_id"], "record_id": later["record_id"],
        "observed_at": later["date"], "load_change": load, "load_unit": first["normalized_unit"],
        "load_difficulty_change": difficulty, "repetitions_change": reps,
        "rir_change": low if low is not None and low == high else None,
        "rir_change_bounds": {"lower": low, "upper": high},
        "rir_recorded": any(p.get("rir") is not None or p.get("rir_interval") is not None for p in (first, later)),
        "identity": status}


def _summarize(rows):
    rows = sorted(rows, key=lambda p: instant(p["date"]))
    first = rows[0]
    comparisons = [_compare(first, later) for later in rows[1:]]
    improved = any(p["identity"] == "recorded_joint_improvement" for p in comparisons)
    observed_no_improvement = bool(comparisons) and all(
        p["identity"] == "unchanged_or_lower_recorded_vector" for p in comparisons)
    work_not_increased = bool(comparisons) and all(
        p["load_difficulty_change"] <= 0 and p["repetitions_change"] <= 0 for p in comparisons)
    incomplete = any(p["identity"] == "effort_not_exactly_comparable" for p in comparisons)
    trigger = observed_no_improvement or (work_not_increased and incomplete and not improved)
    return {"anchor": first, "last": rows[-1], "n": len(rows),
        "span_days": (instant(rows[-1]["date"]) - instant(first["date"])).total_seconds() / 86400,
        "comparisons": comparisons, "observed_joint_improvement": improved if comparisons else None,
        "recorded_work_not_increased": work_not_increased if comparisons else None,
        "rir_used_n": sum(p["rir_change"] is not None for p in comparisons),
        "rir_bounded_comparison_n": sum(p["rir_change"] is None and any(v is not None for v in p["rir_change_bounds"].values()) for p in comparisons),
        "status": "recorded_no_improvement_in_selected_period" if observed_no_improvement else
            "work_not_increased_effort_comparison_incomplete" if trigger else
            "recorded_improvement_present" if improved else "mixed_or_insufficient_comparison",
        "start_long_term_review": bool(trigger), "record_ids": [p["record_id"] for p in rows]}


def review(points, window):
    eligible = [p for p in points if p["comparable"]]
    series = [{"outcome_series_id": identity, **_summarize([p for p in eligible if p["stream"] == identity])}
              for identity in dict.fromkeys(p["stream"] for p in eligible)]
    tasks = [{"task_id": identity, **_summarize([p for p in eligible if p["task_id"] == identity])}
             for identity in dict.fromkeys(p["task_id"] for p in eligible)]
    return {"version": "joint-record-review-1.6.1", "window": window,
        "comparison_anchor": "first_visible_predesignated_reference_within_requested_window",
        "series": series, "tasks": tasks, "start_long_term_review": any(t["start_long_term_review"] for t in tasks),
        "excluded_record_ids": [p["record_id"] for p in points if not p["comparable"]],
        "identity": "descriptive_record_fact_not_statistical_or_physiological_plateau",
        "limitations": ["仅说明所选周期相对起点的记录分量；每次变化单列，不能据此判定生理或统计停滞。",
                        "负荷、次数、RIR 分别比较，不相加成能力分数；增重降次数等取舍保持不可判定。",
                        "固定负荷分层保留；其他负荷已有明确改善时，不把旧负荷序列概括成整个任务未改善。",
                        "比较需要起点和后续记录，这是差值定义，不是生理停滞的次数或天数阈值。",
                        "已记录 RIR 或区间参与比较，缺失不补零；自报差值不是已校准的容量变化。"]}


def body_context(repo, cutoff_time, request, selection=None):
    """One shared background calculation for real training starts and advice.

    This creates no training/reference record. The caller labels the actual
    time being described; product lookback is not a recovery threshold.
    """
    cutoff = instant(cutoff_time)
    start = cutoff - timedelta(days=request.get("baseline_days", 28))
    records, inherited = snapshot(repo, cutoff.isoformat(), window_start=start.isoformat(), window_end=cutoff.isoformat(),
        retrospective=request["mode"] == "retrospective",
        canonical_types=["sleep_stage", "resting_heart_rate_bpm", "hrv_sdnn_ms", "body_mass_kg"])
    context = {**inherited, "timezone": request["timezone"], "retrospective": request["mode"] == "retrospective"}
    if (selection or {}).get("primary_sleep_stream"):
        context["primary_sleep_stream"] = selection["primary_sleep_stream"]
    metrics = {mid: evaluate(mid, records, cutoff_time=cutoff.isoformat(), window_start=start.isoformat(),
                window_end=cutoff.isoformat(), context=context) for mid in (
        "STATE-SLEEP-MAIN", "STATE-SLEEP-24H", "STATE-SLEEP-COVERAGE", "STATE-SLEEP-STAGE", "STATE-SLEEP-TIMING",
        "STATE-RHR", "STATE-SDNN", "STATE-REFERENCE-MEDIAN", "STATE-REFERENCE-MAD", "STATE-DEVIATION",
        "STATE-FATIGUE", "STATE-SORENESS", "STATE-PAIN", "BODY-MASS-DAILY", "BODY-MASS-TREND")}
    window = Window(start.isoformat(), cutoff.isoformat(), cutoff.isoformat(), request["timezone"])
    if (selection or {}).get("sleep_selection"):
        from healthzip.analytics.sleep_selection import selected_sleep_metrics
        sleep, _ = selected_sleep_metrics(records, window, selection["sleep_selection"])
        metrics.update({mid: value for mid, value in sleep.items() if mid in metrics})
        binding = sleep["STATE-SLEEP-24H"].get("sleep_selection_binding", {})
        if binding.get("accepted"):
            context["primary_sleep_stream"] = binding["source"]["stream_key"]
    visible, _ = select_as_of(records, window, retrospective=request["mode"] == "retrospective", overlap=True)
    asleep, _ = sleep_intervals(visible, cutoff - timedelta(hours=24), cutoff, context)
    sleep_streams = list(dict.fromkeys(stream_key(p["row"]) for p in asleep))
    return {"metrics": metrics, "sleep_streams": [list(s) for s in sleep_streams],
            "cutoff_time": cutoff.isoformat(), "visibility": request["mode"],
            "baseline_days": request.get("baseline_days", 28),
            "baseline_kind": "product_display_window_not_recovery_threshold"}


def pretraining_contexts(repo, points, request, selection=None):
    """Each reference's context ends at its actual training start, including middle observations."""
    available = sorted((p for p in points if p.get("training_started_at")
                        and instant(p["training_started_at"]) <= instant(p["date"])), key=lambda p: instant(p["date"]))
    results, cache = [], {}
    for point in available:
        cutoff = instant(point["training_started_at"])
        if point["session_id"] not in cache:
            cache[point["session_id"]] = body_context(repo, cutoff.isoformat(), request, selection)
        results.append({"reference_record_id": point["record_id"], "session_id": point["session_id"],
            "training_started_at": cutoff.isoformat(), **cache[point["session_id"]],
            "visibility": request["mode"], "baseline_days": request.get("baseline_days", 28), "baseline_kind": "product_display_window_not_recovery_threshold"})
    return results
