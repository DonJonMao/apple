"""Observed sleep, protocol-separated daily physiology and session questionnaires."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import timedelta
from statistics import median, stdev
from zoneinfo import ZoneInfo

from .contracts import Window, finite, instant, result

ASLEEP = {"asleep", "asleepunspecified", "asleepcore", "asleepdeep", "asleeprem", "core", "deep", "rem"}


def stream_key(row: dict) -> tuple:
    return (row.get("source_name", row.get("source_bundle_id")), row.get("device_id", row.get("device")),
            row.get("protocol_id"), row.get("source_version"))


def union(intervals: list[tuple]) -> list[tuple]:
    merged = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def seconds(intervals: list[tuple]) -> float:
    return sum((end - start).total_seconds() for start, end in union(intervals))


def stage(row: dict) -> str:
    return str(row.get("stage", row.get("category_value", ""))).replace("HKCategoryValueSleepAnalysis", "").lower()


def sleep_intervals(rows: list[dict], start, end, context: dict) -> tuple[list[dict], list[str]]:
    candidates = [r for r in rows if r.get("canonical_type") == "sleep_stage" or r.get("metric_type") == "sleep" or "stage" in r]
    streams = {stream_key(r) for r in candidates}
    selected_stream = context.get("primary_sleep_stream")
    reasons = []
    if selected_stream is not None:
        selected_stream = tuple(selected_stream)
        candidates = [r for r in candidates if stream_key(r) == selected_stream]
    elif len(streams) > 1:
        return [], ["multiple_sleep_streams_primary_source_required"]
    out = []
    for row in candidates:
        try:
            first = max(instant(row.get("event_start") or row.get("start_at_utc") or row.get("start_utc")), start)
            last = min(instant(row.get("_event_end") or row.get("event_end") or row.get("end_utc")), end)
        except ValueError:
            reasons.append("sleep_timestamp_invalid")
            continue
        if last > first:
            out.append({"start": first, "end": last, "stage": stage(row), "row": row})
    return out, reasons


def elapsed_dates(window: Window) -> int:
    zone = ZoneInfo(window.timezone)
    start = instant(window.start).astimezone(zone)
    end = min(instant(window.end), instant(window.cutoff_time)).astimezone(zone)
    if end <= start:
        return 0
    # Include the partly elapsed local day, never future days in a monthly view.
    return ((end - timedelta(microseconds=1)).date() - start.date()).days + 1


def daily_values(rows: list[dict], canonical: str, zone_name: str) -> dict:
    streams = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row.get("canonical_type", row.get("metric_type")) != canonical:
            continue
        value = finite(row.get("normalized_value", row.get("value")))
        if value is None:
            continue
        unit = row.get("normalized_unit", row.get("unit", row.get("raw_unit")))
        if canonical == "hrv_sdnn_ms" and unit in {"s", "sec", "second"}:
            value *= 1000
        elif canonical == "body_mass_kg" and unit in {"lb", "lbs"}:
            value *= 0.45359237
        if canonical == "hrv_sdnn_ms" and row.get("metric_identity") == "RMSSD":
            continue
        day = instant(row["_event_end"]).astimezone(ZoneInfo(zone_name)).date().isoformat()
        streams[stream_key(row)][day].append((value, row))
    return {str(key): [{"date": day, "value": next((v for v, r in items if r.get("is_primary") is True), median(v for v, _ in items)), "n": len(items),
                        "source_ids": [r.get("_source_id") for _, r in items], "protocol": list(key)}
                       for day, items in sorted(days.items())] for key, days in streams.items()}


def state_metric(metric_id: str, rows: list[dict], window: Window, context: dict) -> dict:
    def emit(value=None, status="valid", **extra):
        return result(metric_id, window, value, data_status=status, **{"records": rows, **extra})

    if metric_id.startswith("STATE-SLEEP-"):
        start, end = instant(window.start), min(instant(window.end), instant(window.cutoff_time))
        if metric_id == "STATE-SLEEP-24H":
            end = instant(window.cutoff_time)
            start = end - timedelta(hours=24)
        main = context.get("main_sleep_episode")
        if metric_id == "STATE-SLEEP-MAIN" and main:
            start, end = max(start, instant(main["start"])), min(end, instant(main["end"]))
        intervals, reasons = sleep_intervals(rows, start, end, context)
        if reasons and not intervals:
            return emit(None, "incompatible", reasons=reasons, valid_n=0, total_n=len(rows))
        asleep = union([(v["start"], v["end"]) for v in intervals if v["stage"] in ASLEEP])
        if metric_id in {"STATE-SLEEP-MAIN", "STATE-SLEEP-24H"}:
            if not asleep:
                return emit(None, "insufficient", reasons=["no_observed_asleep_intervals"])
            complete = metric_id == "STATE-SLEEP-MAIN" and bool(main and main.get("complete"))
            return emit({"observed_minutes": seconds(asleep) / 60, "complete_episode": complete,
                         "intervals": [{"start": a.isoformat(), "end": b.isoformat()} for a, b in asleep]},
                        "valid" if complete else "partial", evidence_status="observed",
                        reasons=[] if complete else ["observed_sleep_not_proven_complete_episode"])
        if metric_id == "STATE-SLEEP-COVERAGE":
            dates = {end.astimezone(ZoneInfo(window.timezone)).date().isoformat() for _, end in asleep}
            denominator = elapsed_dates(window)
            return emit({"recorded_dates": len(dates), "elapsed_dates": denominator,
                         "fraction": len(dates) / denominator if denominator else None},
                        "valid" if denominator else "insufficient", valid_n=len(dates), total_n=denominator,
                        count_domain="local_dates", reasons=["record_coverage_not_wear_time_or_complete_nights"])
        if metric_id == "STATE-SLEEP-STAGE":
            by_stage = defaultdict(list)
            for entry in intervals:
                name = entry["stage"].replace("asleep", "")
                if name in {"core", "deep", "rem", "awake"}:
                    by_stage[name].append((entry["start"], entry["end"]))
            conflicts = []
            names = sorted(by_stage)
            for i, first in enumerate(names):
                for second in names[i + 1:]:
                    for a, b in union(by_stage[first]):
                        for c, d in union(by_stage[second]):
                            if min(b, d) > max(a, c):
                                conflicts.append({"stages": [first, second], "start": max(a, c).isoformat(), "end": min(b, d).isoformat()})
            annotated = seconds([p for group in by_stage.values() for p in group])
            span = (instant(main["end"]) - instant(main["start"])).total_seconds() if main else None
            return emit({"stage_minutes": {k: seconds(v) / 60 for k, v in by_stage.items()},
                         "annotation_coverage": annotated / span if span and span > 0 else None,
                         "conflicts": conflicts}, "conflicted" if conflicts else "partial" if span is None else "valid",
                        reasons=["mutually_exclusive_stage_overlap"] if conflicts else ["episode_boundary_unknown"] if span is None else [])
        episodes = context.get("sleep_episodes", [])
        points = []
        for episode in episodes:
            a, b = instant(episode["start"]), instant(episode["end"])
            if a < b <= instant(window.cutoff_time):
                episode_zone = episode.get("timezone", window.timezone)
                mid = (a + (b - a) / 2).astimezone(ZoneInfo(episode_zone))
                points.append({"start": a.isoformat(), "end": b.isoformat(), "midpoint": mid.isoformat(),
                               "timezone": episode_zone,
                               "local_hour": mid.hour + mid.minute / 60 + mid.second / 3600})
        if not points:
            return emit(None, "insufficient", reasons=["explicit_sleep_episode_boundaries_required"])
        sine = sum(math.sin(2 * math.pi * p["local_hour"] / 24) for p in points) / len(points)
        cosine = sum(math.cos(2 * math.pi * p["local_hour"] / 24) for p in points) / len(points)
        concentration = math.hypot(sine, cosine)
        mean = (math.atan2(sine, cosine) * 24 / (2 * math.pi)) % 24 if concentration > 1e-12 else None
        groups = {}
        for name in {p["timezone"] for p in points}:
            items = [p for p in points if p["timezone"] == name]
            ss = sum(math.sin(2 * math.pi * p["local_hour"] / 24) for p in items) / len(items)
            cc = sum(math.cos(2 * math.pi * p["local_hour"] / 24) for p in items) / len(items)
            groups[name] = {"n": len(items), "circular_midpoint_hour": (math.atan2(ss, cc) * 24 / (2 * math.pi)) % 24,
                            "resultant_length": math.hypot(ss, cc)}
        return emit({"episodes": points, "circular_midpoint_hour": mean if len(groups) == 1 else None,
                     "resultant_length": concentration if len(groups) == 1 else None, "timezone_segments": groups},
                    "valid", evidence_status="descriptive", reasons=["timezone_changes_not_pooled"] if len(groups) > 1 else [])
    if metric_id in {"STATE-RHR", "STATE-SDNN"}:
        canonical = "resting_heart_rate_bpm" if metric_id == "STATE-RHR" else "hrv_sdnn_ms"
        values = daily_values(rows, canonical, window.timezone)
        if metric_id == "STATE-SDNN" and context.get("clean_nn_intervals_ms") is not None:
            nn = context["clean_nn_intervals_ms"]
            if not context.get("artifact_cleaning_protocol") or len(nn) < 2:
                return emit(None, "insufficient", reasons=["cleaning_protocol_and_two_nn_required"])
            return emit({"SDNN_ms": stdev(nn), "n_NN": len(nn), "cleaning_protocol": context["artifact_cleaning_protocol"]},
                        evidence_status="observed", reasons=["SDNN_is_not_RMSSD"])
        return emit(values or None, "valid" if values else "insufficient", evidence_status="observed",
                    reasons=["protocol_streams_not_pooled", "SDNN_is_not_RMSSD"] if metric_id == "STATE-SDNN" else ["protocol_streams_not_pooled"])
    if metric_id in {"STATE-REFERENCE-MEDIAN", "STATE-REFERENCE-MAD", "STATE-DEVIATION"}:
        if "baseline_daily" not in context:
            streams = []
            reasons = ["equal_weight_per_day", "current_day_excluded_from_own_reference"]
            valid = 0
            for canonical in ("resting_heart_rate_bpm", "hrv_sdnn_ms"):
                for key, daily in daily_values(rows, canonical, window.timezone).items():
                    if not daily:
                        continue
                    current, past = daily[-1], daily[:-1]
                    center = median(v["value"] for v in past) if past else None
                    mad = median(abs(v["value"] - center) for v in past) if len(past) > 1 else None
                    protocol_known = current["protocol"][2] is not None
                    deviation = current["value"] - center if center is not None else None
                    z = deviation / (1.4826 * mad) if protocol_known and mad is not None and mad > 0 else None
                    streams.append({"canonical_type": canonical, "stream": key, "protocol": current["protocol"],
                                    "baseline_daily_n": len(past), "baseline_median": center, "MAD": mad,
                                    "scaled_MAD": 1.4826 * mad if mad is not None else None,
                                    "current_daily_value": current["value"], "current_date": current["date"],
                                    "absolute_deviation": deviation, "robust_z": z,
                                    "baseline_source_ids": [i for d in past for i in d["source_ids"]],
                                    "current_source_ids": current["source_ids"],
                                    "reference_window": context.get("baseline_window", window.as_dict()),
                                    "protocol_known": protocol_known})
                    valid += len(past)
                    if not protocol_known:
                        reasons.append("unknown_protocol_stream_descriptive_only")
                    if mad == 0:
                        reasons.append("MAD_zero_standardized_deviation_not_estimable")
            if not context.get("baseline_window"):
                reasons.append("baseline_window_equals_requested_window_product_default")
            return emit({"streams": streams} if streams else None,
                        "valid" if streams and all(v["baseline_daily_n"] >= 2 and v["protocol_known"] for v in streams)
                        else "partial" if valid else "insufficient", evidence_status="descriptive",
                        reasons=sorted(set(reasons)))
        baseline = context.get("baseline_daily", [])
        current = context.get("current_observation")
        current_time = instant(current["event_end"]) if current else instant(window.cutoff_time)
        selected = [r for r in baseline if instant(r["event_end"]) < current_time and instant(r["available_at"]) <= instant(window.cutoff_time)]
        if not selected:
            return emit(None, "insufficient", reasons=["prior_daily_baseline_missing"])
        protocols = {r.get("protocol_id") for r in selected}
        if len(protocols) != 1 or (current and current.get("protocol_id") not in protocols):
            return emit(None, "incompatible", reasons=["baseline_protocol_changed"])
        by_day = defaultdict(list)
        for row in selected:
            if finite(row.get("value")) is not None:
                by_day[instant(row["event_end"]).astimezone(ZoneInfo(window.timezone)).date()].append(row["value"])
        values = [median(v) for v in by_day.values()]
        if not values:
            return emit(None, "insufficient", reasons=["baseline_values_missing"])
        center = median(values)
        mad = median(abs(v - center) for v in values)
        output = {"median": center, "MAD": mad if len(values) > 1 else None,
                  "scaled_MAD": 1.4826 * mad if len(values) > 1 else None,
                  "baseline_id": context.get("baseline_id"), "daily_n": len(values)}
        reasons = ["baseline_day_equal_weight", "current_value_excluded_from_own_baseline"]
        if metric_id == "STATE-DEVIATION":
            value = finite(current.get("value")) if current else None
            output["absolute_deviation"] = value - center if value is not None else None
            output["robust_z"] = (value - center) / (1.4826 * mad) if value is not None and mad > 0 and len(values) > 1 else None
            if mad == 0:
                reasons.append("MAD_zero_standardized_deviation_not_estimable")
        return emit(output, "partial" if len(values) < 2 else "valid", evidence_status="descriptive", reasons=reasons,
                    valid_n=len(values), total_n=len(by_day), count_domain="baseline_days", source_record_ids=[str(r["id"]) for r in selected if r.get("id") is not None])
    if metric_id in {"STATE-FATIGUE", "STATE-SORENESS", "STATE-PAIN"}:
        field = {"STATE-FATIGUE": "fatigue", "STATE-SORENESS": "soreness", "STATE-PAIN": "pain"}[metric_id]
        values = [{"id": r.get("id"), "value": r[field], "scale_version": r.get("scale_version"),
                   "anchors": r.get("anchors"), "muscle": r.get("muscle"), "side": r.get("side"),
                   "location": r.get("location"), "quality": r.get("quality"),
                   "movement_impact": r.get("movement_impact")} for r in rows if r.get(field) is not None]
        out = {"observations": values, "frequency_by_scale": {}}
        for value in values:
            key = str((value["scale_version"], value["muscle"], value["side"]))
            bucket = out["frequency_by_scale"].setdefault(key, Counter())
            bucket[str(value["value"])] += 1
        if field == "pain":
            out["safety_protocol_id"] = context.get("reviewed_symptom_protocol_id")
            out["clinical_interpretation"] = None
        return emit(out if values else None, "valid" if values else "insufficient", evidence_status="observed",
                    reasons=["ordinal_observations_not_combined_recovery_score"])
    if metric_id.startswith("LOAD-"):
        sessions = context.get("sessions", [])
        values = []
        for session in sessions:
            if not session.get("session_id"):
                continue
            try:
                a, b = instant(session["started_at"]), instant(session["ended_at"])
                available = instant(session["available_at"])
                if b > instant(window.cutoff_time) or available > instant(window.cutoff_time) \
                        or b <= instant(window.start) or a >= instant(window.end):
                    continue
            except (ValueError, KeyError):
                continue
            pauses = [(max(a, instant(p["start"])), min(b, instant(p["end"]))) for p in session.get("pauses", [])]
            protocol = session.get("duration_protocol")
            explicit = finite(session.get("duration_seconds"))
            if protocol == "user_elapsed_including_rest" and explicit is not None:
                duration = explicit / 60
                duration_source = "user_reported"
            elif protocol in {"elapsed_including_set_rest", "elapsed_minus_pauses", "event_elapsed_including_rest"}:
                duration = ((b - a).total_seconds() - seconds(pauses)) / 60
                duration_source = "event_timestamps_and_union_pauses"
            else:
                duration = None
                duration_source = "unknown_protocol"
            srpe = finite(session.get("session_rpe")) if session.get("srpe_protocol") else None
            if srpe is not None and not 0 <= srpe <= 10:
                srpe = None
            delay = (instant(session["srpe_collected_at"]) - b).total_seconds() / 60 if session.get("srpe_collected_at") else None
            values.append({"session_id": session["session_id"], "session_rpe": srpe,
                           "duration_minutes": duration, "duration_source": duration_source,
                           "actual_collection_delay_minutes": delay,
                           "srpe_protocol": session.get("srpe_protocol"), "duration_protocol": session.get("duration_protocol"),
                           "AU": srpe * duration if srpe is not None and duration is not None else None})
        field = {"LOAD-SRPE": "session_rpe", "LOAD-DURATION": "duration_minutes", "LOAD-SRPE-AU": "AU"}[metric_id]
        valid = sum(v[field] is not None for v in values)
        return emit(values or None, "valid" if values and valid == len(values) else "partial" if valid else "insufficient",
                    valid_n=valid, total_n=len(values), n_sessions=len(values), count_domain="sessions",
                    source_record_ids=["session:" + str(v["session_id"]) for v in values], reasons=["set_RPE_not_session_RPE"])
    raise ValueError("unknown_state_metric")
