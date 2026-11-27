"""Period summaries recomputed from underlying observations and denominators."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median, quantiles
from zoneinfo import ZoneInfo

from .contracts import Window, finite, instant, result, select_as_of
from .energy import device_energy_days, energy_metric
from .state import (
    comparison_from_daily,
    comparison_windows,
    daily_values,
    elapsed_dates,
    local_date_domain,
    observed_sleep_episodes,
    state_metric,
)
from .strength import strength_metric


def derive_report_context(rows: list[dict], window: Window, *, sleep_rows=None) -> dict:
    """Derive report inputs from exactly the available snapshot, never weekly means.

    A recorded energy day need not be a complete day or actual wear coverage.
    Complete totals require known nonoverlapping components from one stream and
    observed intervals spanning the full local day, or explicit platform daily
    statistic metadata. The current partial day cannot become complete.
    """
    return {"daily_metric_facts": _daily_metric_facts(rows, window, sleep_rows=sleep_rows),
            "energy_days": device_energy_days(rows, window)}


def _daily_metric_facts(rows, window, *, sleep_rows=None, comparison_only=False):
    """Share the same daily definitions without deriving unused comparison domains."""
    zone = ZoneInfo(window.timezone)
    lookup = {str(r.get("_source_id", r.get("id"))): r for r in rows}
    daily = []
    measures = [("resting_heart_rate_bpm", "STATE-RHR"), ("hrv_sdnn_ms", "STATE-SDNN")]
    if not comparison_only:
        measures.append(("body_mass_kg", "BODY-MASS-DAILY"))
    for canonical, metric_id in measures:
        for key, items in daily_values(rows, canonical, window.timezone).items():
            for item in items:
                inputs = [lookup[str(i)] for i in item["source_ids"] if str(i) in lookup]
                if not inputs:
                    continue
                daily.append({**item, "metric_id": metric_id, "source_id": key,
                              "protocol_id": str(item["protocol"]), "measurement_scale": "continuous",
                              "event_end": max(r["_event_end"] for r in inputs),
                              "available_at": max(r.get("available_at", r["_event_end"]) or r["_event_end"] for r in inputs),
                              "source_record_ids": item["source_ids"]})
    sleep = defaultdict(list)
    for episode in observed_sleep_episodes(sleep_rows if sleep_rows is not None else rows, window):
        sleep[(episode["source_id"], episode["date"])].append(episode)
    for (key, day), episodes in sleep.items():
        inputs = [identifier for episode in episodes for identifier in episode["source_record_ids"]]
        intervals = [span for episode in episodes for span in episode["intervals"]]
        daily.append({"metric_id": "sleep_observed_minutes_by_wake_date", "series_id": "observed_sleep_by_wake_date",
            "series_label": "按观测事件结束日期汇总的睡眠（主睡眠／午睡未分类）", "date": day,
            "value": sum(episode["value"] for episode in episodes), "unit": "min", "source_id": key,
            "protocol_id": key, "protocol": episodes[0]["protocol"], "measurement_scale": "continuous",
            "event_start": min(episode["event_start"] for episode in episodes),
            "event_end": max(episode["event_end"] for episode in episodes),
            "available_at": max((episode["available_at"] for episode in episodes if episode["available_at"]), default=None),
            "support_local_dates": sorted(set().union(*(local_date_domain(span["start"], span["end"], window.timezone) for span in intervals))),
            "source_record_ids": inputs, "source_ids": inputs, "n": sum(episode["n"] for episode in episodes),
            "statistic_kind": "union_observed_sleep_minutes_by_event_end_date", "episodes": episodes, "episode_complete": False})
    if comparison_only:
        return daily
    for row in rows:
        for field in ("fatigue", "soreness", "pain"):
            if row.get(field) is None:
                continue
            daily.append({"metric_id": "STATE-" + field.upper(), "date": instant(row["_event_end"]).astimezone(zone).date().isoformat(),
                          "value": row[field], "source_id": row.get("source_name"),
                          "protocol_id": str((row.get("scale_version"), row.get("muscle"), row.get("side"))),
                          "measurement_scale": "ordinal", "event_end": row["_event_end"],
                          "available_at": row.get("available_at"), "source_record_ids": [row.get("_source_id")]})
    return daily


def visible_sleep_history(rows, window, *, retrospective=False):
    sleep = [row for row in rows if row.get("canonical_type") == "sleep_stage"]
    starts = [instant(row.get("event_start") or row.get("start_utc") or window.start) for row in sleep]
    start = min([instant(window.start), *starts])
    selected, _ = select_as_of(sleep, Window(start.isoformat(), window.end, window.cutoff_time, window.timezone),
                               retrospective=retrospective, overlap=True)
    return selected


def report_comparison(rows, window, *, previous=None, baseline_days=28, retrospective=False):
    bounds = comparison_windows(window, previous=previous, baseline_days=baseline_days)
    groups, units = defaultdict(dict), {}
    sleep = visible_sleep_history(rows, window, retrospective=retrospective)
    periods = []
    for name, interval in bounds.items():
        start, end = instant(interval["start"]), instant(interval["end"])
        if start >= end:
            continue
        period = Window(interval["start"], interval["end"], window.cutoff_time, window.timezone)
        periods.append((name, period, start, end))
    timed = []
    if periods:
        support = Window(min(item[2] for item in periods).isoformat(), max(item[3] for item in periods).isoformat(),
                         window.cutoff_time, window.timezone)
        # Resolve every original row at this shared cutoff before any window or
        # type narrowing. Corrections to another type or a future event must
        # still invalidate their predecessors, and missing IDs keep their
        # original position. The selected ordering and source IDs remain intact.
        visible, _ = select_as_of(rows, support, retrospective=retrospective, overlap=True)
        timed = [(row, instant(row["_event_end"]), instant(row.get("event_start") or row.get("start_at_utc")
                  or row.get("start_utc") or row["_event_end"])) for row in visible]
    for name, period, start, end in periods:
        selected = [row for row, event_end, event_start in timed if event_end > start and event_start < end]
        # Comparison consumes only physiology and sleep. Body mass, symptoms
        # and energy still use the full report context, but need not be derived
        # again for each comparison window and then discarded here.
        facts = _daily_metric_facts(selected, period, sleep_rows=sleep, comparison_only=True)
        for fact in facts:
            if fact.get("metric_id") not in {"STATE-RHR", "STATE-SDNN", "sleep_observed_minutes_by_wake_date"}:
                continue
            identity = fact["metric_id"] + ":" + str(fact.get("source_id"))
            groups[identity].setdefault(name, []).append(fact)
            units[identity] = fact.get("unit") or {"STATE-RHR": "bpm", "STATE-SDNN": "ms", "BODY-MASS-DAILY": "kg"}.get(fact["metric_id"])
    output = comparison_from_daily({}, bounds, window.cutoff_time, None)
    output["statistic_kind"] = "median_of_daily_representatives"
    for identity, periods in groups.items():
        output["streams"].extend(comparison_from_daily({identity: periods}, bounds, window.cutoff_time, units[identity])["streams"])
    return output


def report_metric(metric_id: str, rows: list[dict], window: Window, context: dict) -> dict:
    partial = instant(window.cutoff_time) < instant(window.end)
    def emit(value, status=None, **extra):
        return result(metric_id, window, value, data_status=status or ("partial" if partial else "valid"),
                      records=rows, reasons=["current_calendar_period_incomplete"] if partial else [], **extra)
    if metric_id == "REPORT-PERIOD-COVERAGE":
        denominator = elapsed_dates(window)
        facts = context.get("daily_metric_facts", [])
        domain = local_date_domain(instant(window.start), min(instant(window.end), instant(window.cutoff_time)), window.timezone)
        groups = defaultdict(set)
        streams = defaultdict(set)
        for fact in facts:
            if fact.get("value") is not None:
                dates = set(fact.get("support_local_dates", [fact["date"]])) & domain
                groups[fact["metric_id"]].update(dates)
                streams[(fact["metric_id"], fact.get("source_id"), fact.get("protocol_id"))].update(dates)
        values = [{"kind": key, "metric_id": key, "numerator": len(dates), "denominator": denominator,
                   "definition": "valid local dates / elapsed target dates"} for key, dates in groups.items()]
        stream_values = [{"metric_id": key[0], "source_id": key[1], "protocol_id": key[2],
                          "numerator": len(dates), "denominator": denominator, "recorded_local_dates": sorted(dates),
                          "definition": "valid local dates for this source and protocol / elapsed target dates"}
                         for key, dates in streams.items()]
        session_coverage = []
        for identity in ("LOAD-SRPE", "LOAD-DURATION", "LOAD-SRPE-AU"):
            metric = state_metric(identity, rows, window, context)
            session_coverage.append({"kind": identity, "numerator": metric["valid_n"], "denominator": metric["total_n"],
                                     "definition": "known measurements / eligible completed sessions in the window"})
        return emit({"daily_coverage": values, "daily_stream_coverage": stream_values, "session_coverage": session_coverage,
                     "missing_date_interpretation": "no_valid_record_not_absence_of_event",
                     "complete_previous_period_comparable": not partial}, coverage=values)
    if metric_id == "REPORT-STATE-SUMMARY":
        chart_fields = {"metric_id", "series_id", "series_label", "date", "value", "unit", "source_id", "protocol_id", "measurement_scale",
                        "event_start", "event_end", "available_at", "source_record_ids", "episode_complete", "n",
                        "statistic_kind", "protocol", "episodes", "observations", "conditions", "statistics_version"}
        daily_facts = [{k: v for k, v in fact.items() if k in chart_fields}
                       for fact in context.get("daily_metric_facts", [])]
        groups = defaultdict(list)
        for fact in context.get("daily_metric_facts", []):
            groups[(fact["metric_id"], fact.get("protocol_id"), fact.get("source_id"))].append(fact)
        values = []
        for key, group in groups.items():
            if any(row.get("measurement_scale") == "ordinal" for row in group):
                summary = {"frequencies": dict(Counter(str(r["value"]) for r in group if r.get("value") is not None))}
            else:
                numbers = [finite(r.get("value")) for r in group if finite(r.get("value")) is not None]
                if key[0] in {"STATE-RHR", "STATE-SDNN", "sleep_observed_minutes_by_wake_date"}:
                    summary = {"median": median(numbers) if numbers else None,
                               "statistic_kind": "median",
                               "quartiles": quantiles(numbers, n=4, method="inclusive") if len(numbers) > 1 else None}
                else:
                    # Other domains retain their established period statistic.
                    # The SDNN typical-day choice is not a global statistic rule.
                    summary = {"mean": sum(numbers) / len(numbers) if numbers else None,
                               "statistic_kind": "mean"}
            values.append({"metric_id": key[0], "series_id": group[0].get("series_id"), "series_label": group[0].get("series_label"),
                           "protocol_id": key[1], "source_id": key[2], "n": len(group), **summary})
        return emit(values or None, "insufficient" if not values else None, evidence_status="descriptive",
                    daily_facts=daily_facts, algorithm_version="health-period-summary-2.0.0", statistics_version="health-period-summary-2.0.0",
                    statistic_kind="metric_specific_daily_summary")
    if metric_id == "REPORT-ENERGY-SUMMARY":
        days = [d for d in context.get("energy_days", []) if d.get("complete")]
        streams = defaultdict(list)
        for day in days:
            if finite(day.get("device_total_kcal")) is not None:
                streams[str(day.get("stream"))].append(day)
        summaries = [{"stream": key, "known_complete_day_energy_sum": sum(d["device_total_kcal"] for d in group),
                      "valid_day_mean": sum(d["device_total_kcal"] for d in group) / len(group),
                      "valid_complete_days": len(group), "dates": [d["date"] for d in group]} for key, group in streams.items()]
        single = summaries[0] if len(summaries) == 1 else {}
        return emit({"body_mass_trend": energy_metric("BODY-MASS-TREND", rows, window, context),
                     "known_complete_day_energy_sum": single.get("known_complete_day_energy_sum"),
                     "valid_day_mean": single.get("valid_day_mean"), "streams": summaries,
                     "valid_complete_days": single.get("valid_complete_days", 0), "elapsed_dates": elapsed_dates(window),
                     "whole_window_delta_intake": energy_metric("ENERGY-DELTA-INTAKE", rows, window, context),
                     "extrapolated_period_total": None}, "incompatible" if len(summaries) > 1 else None,
                    evidence_status="descriptive")
    if metric_id == "REPORT-RECOMMENDATION-FOLLOWUP":
        from .strength import prepare_strength
        prepared = prepare_strength(rows, context)
        execution = strength_metric("STR-27", rows, window, context, _prepared=prepared)
        return emit({"execution": execution,
                     "summary": strength_metric("STR-28", rows, window, context, _prepared=prepared),
                     "followup_windows": [item["followup"] for item in execution["value"] or [] if item.get("followup")],
                     "causal_effect": None}, evidence_status="descriptive")
    raise ValueError("unknown_report_metric")
