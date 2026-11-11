"""Period summaries recomputed from underlying observations and denominators."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from statistics import median, quantiles
from zoneinfo import ZoneInfo

from .contracts import Window, finite, instant, result
from .energy import atomic_energy, energy_metric
from .state import ASLEEP, daily_values, elapsed_dates, seconds, stage, state_metric, stream_key
from .strength import strength_metric


def derive_report_context(rows: list[dict], window: Window) -> dict:
    """Derive report inputs from exactly the available snapshot, never weekly means.

    A recorded energy day need not be a complete day or actual wear coverage.
    Complete totals require known nonoverlapping components from one stream and
    observed intervals spanning the full local day, or explicit platform daily
    statistic metadata. The current partial day cannot become complete.
    """
    zone = ZoneInfo(window.timezone)
    lookup = {str(r.get("_source_id", r.get("id"))): r for r in rows}
    daily = []
    for canonical, metric_id in (("resting_heart_rate_bpm", "STATE-RHR"), ("hrv_sdnn_ms", "STATE-SDNN"), ("body_mass_kg", "BODY-MASS-DAILY")):
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
    for row in rows:
        if row.get("canonical_type") == "sleep_stage" and stage(row) in ASLEEP:
            end = instant(row["_event_end"])
            sleep[(stream_key(row), end.astimezone(zone).date().isoformat())].append(row)
    for (key, day), inputs in sleep.items():
        intervals = []
        for row in inputs:
            raw = row.get("event_start") or row.get("start_utc")
            if raw:
                intervals.append((max(instant(raw), instant(window.start)),
                                  min(instant(row["_event_end"]), instant(window.end), instant(window.cutoff_time))))
        daily.append({"metric_id": "STATE-SLEEP-MAIN", "date": day, "value": seconds(intervals) / 60,
                      "unit": "min", "source_id": str(key), "protocol_id": str(key), "measurement_scale": "continuous",
                      "event_end": max(r["_event_end"] for r in inputs),
                      "available_at": max(r.get("available_at", r["_event_end"]) or r["_event_end"] for r in inputs),
                      "source_record_ids": [r.get("_source_id") for r in inputs], "episode_complete": False})
    for row in rows:
        for field in ("fatigue", "soreness", "pain"):
            if row.get(field) is None:
                continue
            daily.append({"metric_id": "STATE-" + field.upper(), "date": instant(row["_event_end"]).astimezone(zone).date().isoformat(),
                          "value": row[field], "source_id": row.get("source_name"),
                          "protocol_id": str((row.get("scale_version"), row.get("muscle"), row.get("side"))),
                          "measurement_scale": "ordinal", "event_end": row["_event_end"],
                          "available_at": row.get("available_at"), "source_record_ids": [row.get("_source_id")]})
    energy_rows = [r for r in rows if r.get("canonical_type") in {"basal_energy_kcal", "active_energy_kcal"}]
    dates = set()
    for row in energy_rows:
        raw = row.get("event_start") or row.get("start_utc")
        if raw:
            dates.add(instant(raw).astimezone(zone).date())
    energy_days = []
    for day in sorted(dates):
        a = datetime.combine(day, time.min, zone)
        b = datetime.combine(day + timedelta(days=1), time.min, zone)
        if b <= instant(window.start) or a >= min(instant(window.end), instant(window.cutoff_time)):
            continue
        day_window = Window(max(a, instant(window.start)).isoformat(), min(b, instant(window.end)).isoformat(), window.cutoff_time, window.timezone)
        day_rows = [r for r in energy_rows if instant(r["_event_end"]) > instant(a)
                    and instant(r.get("event_start") or r["start_utc"]) < instant(b)]
        parts = {name: atomic_energy(day_rows, canonical, day_window)
                 for name, canonical in (("basal", "basal_energy_kcal"), ("active", "active_energy_kcal"))}
        known = {name: [v for v in payload["streams"] if v["known_kcal"] is not None] for name, payload in parts.items()}
        same_stream = len(known["basal"]) == len(known["active"]) == 1 and known["basal"][0]["stream"] == known["active"][0]["stream"]
        sources = [source_id for payload in parts.values() for item in payload["streams"] for source_id in item["source_ids"]]
        inputs = [lookup[str(i)] for i in sources if str(i) in lookup]
        complete = same_stream and b <= instant(window.cutoff_time)
        for canonical in ("basal_energy_kcal", "active_energy_kcal"):
            samples = [r for r in inputs if r.get("canonical_type") == canonical]
            intervals = [(instant(r.get("event_start") or r["start_utc"]), instant(r["_event_end"])) for r in samples]
            complete = complete and bool(samples) and (all(r.get("platform_complete_day") is True for r in samples) or
                abs(seconds(intervals) - (instant(b) - instant(a)).total_seconds()) < 1e-6)
        energy_days.append({"date": day.isoformat(), "event_start": a.isoformat(), "event_end": min(b, instant(window.cutoff_time)).isoformat(),
                            "available_at": max((r.get("available_at") or r["_event_end"] for r in inputs), default=window.cutoff_time),
                            "basal_valid": bool(known["basal"]), "active_valid": bool(known["active"]),
                            "total_valid": same_stream, "complete": bool(complete),
                            "device_total_kcal": known["basal"][0]["known_kcal"] + known["active"][0]["known_kcal"] if same_stream else None,
                            "source_record_ids": sources, "source_conflicted": any(p["conflicts"] for p in parts.values())})
    return {"daily_metric_facts": daily, "energy_days": energy_days}


def report_metric(metric_id: str, rows: list[dict], window: Window, context: dict) -> dict:
    partial = instant(window.cutoff_time) < instant(window.end)
    def emit(value, status=None, **extra):
        return result(metric_id, window, value, data_status=status or ("partial" if partial else "valid"),
                      records=rows, reasons=["current_calendar_period_incomplete"] if partial else [], **extra)
    if metric_id == "REPORT-PERIOD-COVERAGE":
        denominator = elapsed_dates(window)
        facts = context.get("daily_metric_facts", [])
        groups = defaultdict(set)
        for fact in facts:
            if fact.get("value") is not None:
                groups[fact["metric_id"]].add(fact["date"])
        values = [{"kind": key, "metric_id": key, "numerator": len(dates), "denominator": denominator,
                   "definition": "valid local dates / elapsed target dates"} for key, dates in groups.items()]
        session_coverage = []
        for identity in ("LOAD-SRPE", "LOAD-DURATION", "LOAD-SRPE-AU"):
            metric = state_metric(identity, rows, window, context)
            session_coverage.append({"kind": identity, "numerator": metric["valid_n"], "denominator": metric["total_n"],
                                     "definition": "known measurements / eligible completed sessions in the window"})
        return emit({"daily_coverage": values, "session_coverage": session_coverage,
                     "complete_previous_period_comparable": not partial}, coverage=values)
    if metric_id == "REPORT-STATE-SUMMARY":
        chart_fields = {"metric_id", "date", "value", "unit", "source_id", "protocol_id", "measurement_scale",
                        "event_end", "available_at", "source_record_ids", "episode_complete", "n"}
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
                summary = {"median": median(numbers) if numbers else None,
                           "quartiles": quantiles(numbers, n=4, method="inclusive") if len(numbers) > 1 else None}
            values.append({"metric_id": key[0], "protocol_id": key[1], "source_id": key[2], "n": len(group), **summary})
        return emit(values or None, "insufficient" if not values else None, evidence_status="descriptive",
                    daily_facts=daily_facts)
    if metric_id == "REPORT-ENERGY-SUMMARY":
        days = [d for d in context.get("energy_days", []) if d.get("complete")]
        totals = [d["device_total_kcal"] for d in days if finite(d.get("device_total_kcal")) is not None]
        return emit({"body_mass_trend": energy_metric("BODY-MASS-TREND", rows, window, context),
                     "known_complete_day_energy_sum": sum(totals) if totals else None,
                     "valid_day_mean": sum(totals) / len(totals) if totals else None,
                     "valid_complete_days": len(totals), "elapsed_dates": elapsed_dates(window),
                     "whole_window_delta_intake": energy_metric("ENERGY-DELTA-INTAKE", rows, window, context),
                     "extrapolated_period_total": None}, evidence_status="descriptive")
    if metric_id == "REPORT-RECOMMENDATION-FOLLOWUP":
        return emit({"execution": strength_metric("STR-27", rows, window, context),
                     "summary": strength_metric("STR-28", rows, window, context),
                     "followup_windows": context.get("followup_windows", []),
                     "causal_effect": None}, evidence_status="descriptive")
    raise ValueError("unknown_report_metric")
