"""Descriptive component comparisons, independent of statistical plateau inference."""
from collections import Counter, defaultdict
from datetime import timedelta
from statistics import median

from healthzip.science.contracts import Window, canonical_hash, finite, instant, select_as_of
from healthzip.science.semantics import flatten_record, load_components
from healthzip.science.state import sleep_intervals, stream_key
from healthzip.training.daily_history import daily_identity

from .report_inputs import report_value, source_snapshot


def ordinary_review(records, window):
    """All ordinary completed sets, never selected by reference or best result.

    Physical identity, set type and original ordinal define a descriptive series.
    Multiple matching instances in one session remain observations but have no
    unique longitudinal pair. Equal-duration earlier/recent halves are an explicit
    display choice; every observed point and its original identity is retained.
    """
    start, end = instant(window["start"]), instant(window["end"])
    midpoint = start + (end - start) / 2
    groups = defaultdict(list)
    for raw in records:
        row = flatten_record(raw)
        if row.get("status") != "completed" or row.get("deleted_at") or not row.get("ended_at"):
            continue
        if not start <= instant(row["ended_at"]) < end:
            continue
        identity = daily_identity(row)
        reasons = list(identity["reason_codes"])
        if row.get("set_position") is None:
            reasons.append("set_position_unknown")
        if not row.get("set_type"):
            reasons.append("set_type_unknown")
        if not row.get("session_id") or not row.get("session_exercise_id"):
            reasons.append("training_instance_unknown")
        parts = load_components(row)
        normalized = parts.get("normalized_kg")
        unit = "kg" if normalized is not None else row.get("load_unit")
        load = normalized if normalized is not None else finite(row.get("load_value"))
        record_id = row.get("set_uuid") or row.get("id")
        key = (row.get("exercise_id"), identity["condition_key"], row.get("set_position"),
               row.get("set_type"), row.get("load_basis"), unit, record_id if reasons else None)
        groups[key].append({
            "record_id": record_id, "source_record_id": raw.get("id", record_id),
            "session_id": row.get("session_id"), "session_exercise_id": row.get("session_exercise_id"),
            "date": row["ended_at"], "revision": row.get("revision"),
            "exercise": row.get("exercise_name") or row.get("raw_exercise_name") or row.get("exercise_id"),
            "condition_key": identity["condition_key"], "condition_limitations": reasons,
            "recorded_load": row.get("load_value"), "recorded_unit": row.get("load_unit"),
            "load": load, "unit": unit, "reps": finite(row.get("reps")), "rir": finite(row.get("rir")),
            "rir_interval": row.get("rir_interval"), "duration_s": row.get("duration_s"),
            "distance_m": row.get("distance_m"), "stop_reason": row.get("stop_reason"),
            "pain_flag": row.get("pain_flag"), "quality": row.get("quality"),
            "rest_seconds": row.get("rest_recorded_s", row.get("rest_seconds")),
            "reference_set": row.get("is_reference", False),
            "physical_condition": {k: row.get(k) for k in (
                "equipment_instance_id", "settings", "side", "rom_protocol", "load_basis",
                "repetition_semantics", "definition_version", "measurement_mode")},
        })
    output = []
    for key, points in sorted(groups.items(), key=lambda item: str(item[0])):
        points.sort(key=lambda p: (instant(p["date"]), str(p["record_id"])))
        counts = Counter(p["session_id"] for p in points)
        duplicates = {sid for sid, count in counts.items() if count > 1}
        reasons = list(dict.fromkeys(r for p in points for r in p["condition_limitations"]))
        if duplicates:
            reasons.append("duplicate_same_condition_position_in_session_no_unique_pair")
        eligible = [p for p in points if not p["condition_limitations"] and p["session_id"] not in duplicates]
        eligible_ids = {p["record_id"] for p in eligible}
        comparisons = []
        for left, right in zip(eligible, eligible[1:]):
            if instant(left["date"]) == instant(right["date"]):
                continue
            change = (right["load"] - left["load"]
                      if left["load"] is not None and right["load"] is not None else None)
            same_load = change == 0 or (key[4] == "bodyweight_no_external"
                                        and left["load"] is None and right["load"] is None)
            reps_change = (right["reps"] - left["reps"]
                           if left["reps"] is not None and right["reps"] is not None else None)
            comparisons.append({"previous_record_id": left["record_id"], "record_id": right["record_id"],
                "first_date": left["date"], "date": right["date"], "load_change": change,
                "load_unit": key[5], "same_load": same_load,
                "repetitions_change": reps_change, "same_load_repetitions_change": reps_change if same_load else None,
                "rir_change": right["rir"] - left["rir"] if same_load and left["rir"] is not None and right["rir"] is not None else None,
                "load_meaning": "assistance_reduced" if key[4] == "assistance_setting" and change is not None and change < 0
                                else "assistance_increased" if key[4] == "assistance_setting" and change is not None and change > 0
                                else "recorded_load_change",
                "effort_comparability": "recorded_rir_available_not_calibrated_capacity" if left["rir"] is not None and right["rir"] is not None
                                        else "rir_missing_effort_unknown"})
        stages = []
        for label, a, b in (("earlier", start, midpoint), ("recent", midpoint, end)):
            selected = [p for p in points if a <= instant(p["date"]) < b]
            by_load = defaultdict(list)
            for point in selected:
                by_load[point["load"]].append(point)
            summaries = []
            for load, items in sorted(by_load.items(), key=lambda item: str(item[0])):
                def stats(field):
                    values = [p[field] for p in items if p.get(field) is not None]
                    return {"n": len(values), "median": median(values) if values else None,
                            "min": min(values) if values else None, "max": max(values) if values else None}
                summaries.append({"load": load, "unit": key[5], "record_count": len(items),
                                  "reps": stats("reps"), "rir": stats("rir"),
                                  "record_ids": [p["record_id"] for p in items]})
            stages.append({"period": label, "start": a.isoformat(), "end": b.isoformat(),
                           "record_count": len(selected), "session_count": len({p["session_id"] for p in selected}),
                           "same_load_summaries": summaries})
        missing_rir = sum(p["rir"] is None for p in points)
        if missing_rir:
            reasons.append("rir_missing_effort_unknown")
        first, last = points[0], points[-1]
        def actual(point):
            load = f"{float(point['recorded_load']):g} {point['recorded_unit']}" if finite(point["recorded_load"]) is not None else "自重或未填写负荷"
            return f"{load} × {point['reps']:g} 次" if point["reps"] is not None else load
        summary = f"{last['exercise']}第 {key[2] or '未知'} 组，{len(points)} 条实际记录；{first['date'][:10]} {actual(first)}"
        if len(points) > 1:
            summary += f" 至 {last['date'][:10]} {actual(last)}，中间各次记录均保留"
        if not eligible:
            summary += "；条件尚不能唯一对齐，先查看实际轨迹"
        output.append({"series_id": canonical_hash(key), "exercise_id": key[0], "exercise": last["exercise"],
            "condition_key": key[1], "position": key[2], "set_type": key[3], "load_basis": key[4], "unit": key[5],
            "condition_known": not any(p["condition_limitations"] for p in points),
            "points": points, "record_count": len(points), "session_count": len(counts),
            "comparisons": comparisons, "periods": stages, "limitations": reasons,
            "unpaired_record_ids": [p["record_id"] for p in points if p["record_id"] not in eligible_ids],
            "summary": summary, "rir_missing_n": missing_rir})
    return {"version": "ordinary-training-description-1.0", "window": dict(window),
            "identity": "all_completed_sets_no_reference_or_best_set_selection", "series": output,
            "record_count": sum(g["record_count"] for g in output),
            "summary": [group["summary"] for group in output],
            "period_definition": "equal_elapsed_duration_halves_of_requested_window_product_display_choice",
            "matching_rule": "physical_condition_set_type_original_position_unique_per_session_chronological_adjacent",
            "limitations": ["实际重量、次数与已填写 RIR 分别展示，不合成为能力百分比或停滞判断。",
                            "较早与近期是所选观察范围的等时长两段，阶段内按同负荷列示全部记录的中位数与范围。",
                            "未知条件仍保留原始轨迹；同场同条件同组位出现多个实例时不挑最优记录配对。",
                            "组位、器械、负荷口径或组类型改变会分开；缺 RIR 不妨碍查看完成量，但努力程度保持未知。"]}


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
    return report_value(repo, "body_context", [cutoff_time, request["mode"], request["timezone"],
        request.get("baseline_days", 28), selection], lambda: _body_context(repo, cutoff_time, request, selection))


def _body_context(repo, cutoff_time, request, selection=None):
    cutoff = instant(cutoff_time)
    start = cutoff - timedelta(days=request.get("baseline_days", 28))
    records, inherited = source_snapshot(repo, cutoff.isoformat(), window_start=start.isoformat(), window_end=cutoff.isoformat(),
        retrospective=request["mode"] == "retrospective",
        canonical_types=["sleep_stage", "resting_heart_rate_bpm", "hrv_sdnn_ms", "body_mass_kg"], include_training=False,
        source_filter=(selection or {}).get("source_filter", ()))
    context = {**inherited, "timezone": request["timezone"], "retrospective": request["mode"] == "retrospective"}
    if (selection or {}).get("primary_sleep_stream"):
        context["primary_sleep_stream"] = selection["primary_sleep_stream"]
    from healthzip.science.engine import evaluate_subset
    metrics = evaluate_subset((
        "STATE-SLEEP-MAIN", "STATE-SLEEP-24H", "STATE-SLEEP-COVERAGE", "STATE-SLEEP-STAGE", "STATE-SLEEP-TIMING",
        "STATE-RHR", "STATE-SDNN", "STATE-REFERENCE-MEDIAN", "STATE-REFERENCE-MAD", "STATE-DEVIATION",
        "STATE-FATIGUE", "STATE-SORENESS", "STATE-PAIN", "BODY-MASS-DAILY", "BODY-MASS-TREND"), records,
        cutoff_time=cutoff.isoformat(), window_start=start.isoformat(), window_end=cutoff.isoformat(), context=context)
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
