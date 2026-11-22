"""Observed sleep, protocol-separated daily physiology and session questionnaires."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import median, quantiles, stdev
from zoneinfo import ZoneInfo

from healthzip.normalize import parse_apple_datetime, quantity_value

from .contracts import Window, canonical_hash, finite, instant, result, select_as_of

ASLEEP = {"asleep", "asleepunspecified", "asleepcore", "asleepdeep", "asleeprem", "core", "deep", "rem"}


PHYSIOLOGY_VERSION = "daily-physiology-2.0.0"
SLEEP_VERSION = "sleep-connected-observations-2.0.0"


def record_conditions(row):
    """Only explicit recorded conditions; missing metadata remains unknown."""
    try:
        metadata = json.loads(row.get("metadata_json") or "{}")
    except (ValueError, TypeError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    entries = defaultdict(list)
    for entry in metadata.get("MetadataEntry", []):
        if isinstance(entry, dict) and entry.get("key"):
            entries[entry["key"]].append(entry.get("value"))
    for name, values in entries.items():
        if name not in metadata and all(value == values[0] for value in values):
            metadata[name] = values[0]
    if "HKMetadataKeyHeartRateMotionContext" in metadata and "activity_context" not in metadata:
        metadata["activity_context"] = metadata["HKMetadataKeyHeartRateMotionContext"]
    fields = ("sampling_mode", "measurement_context", "breathing_context", "posture",
              "respiration", "activity_context", "recording_duration_seconds", "os_version",
              "algorithm_version", "metric_identity")
    return {name: {"value": row.get(name, metadata.get(name)),
                   "source": "record" if name in row else "metadata" if name in metadata else "unknown"}
            for name in fields}


def physiology_stream_key(row):
    key = list(stream_key(row))
    conditions = record_conditions(row)
    known = {name: conditions[name]["value"] for name in
             ("sampling_mode", "measurement_context", "breathing_context", "posture", "respiration", "activity_context")
             if conditions[name]["value"] is not None}
    if known:
        key[2] = (str(key[2]) + ";" if key[2] else "context:") + json.dumps(known, sort_keys=True, ensure_ascii=False)
    return tuple(key)


def stream_key(row: dict) -> tuple:
    source = row.get("source_name") or row.get("source_bundle_id") or row.get("source")
    if source is None:
        source = "unknown_source:" + str(row.get("_source_id", row.get("id", "unidentified")))
    protocol = row.get("protocol_id")
    if protocol is None:
        # Canonical JSON imports preserve explicit source metadata. No device
        # name, HealthKit field or nonempty free text is inferred as validation.
        try:
            metadata = json.loads(row.get("metadata_json") or "{}")
            declared = metadata.get("protocol_id") if isinstance(metadata, dict) else None
            if declared is None and isinstance(metadata, dict):
                entries = [e.get("value") for e in metadata.get("MetadataEntry", [])
                           if isinstance(e, dict) and e.get("key") == "protocol_id"]
                if entries and all(v == entries[0] for v in entries):
                    declared = entries[0]
            protocol = declared if isinstance(declared, str) and declared.strip() and declared != "unknown" else None
        except (ValueError, TypeError):
            protocol = None
    return (source, row.get("device_id") or row.get("device"), protocol, row.get("source_version"))


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


def sleep_intervals(rows: list[dict], start, end, context: dict, *, include_awake=False) -> tuple[list[dict], list[str]]:
    candidates = [r for r in rows if r.get("canonical_type") == "sleep_stage" or r.get("metric_type") == "sleep" or "stage" in r]
    # Source eligibility is established by actual asleep observations. InBed or
    # an awake-only stream does not compete with an asleep-recording device.
    streams = {stream_key(r) for r in candidates if stage(r) in ASLEEP}
    selected_stream = context.get("primary_sleep_stream")
    reasons = []
    if selected_stream is None and len(streams) == 1:
        selected_stream = next(iter(streams))
    if selected_stream is not None:
        selected_stream = tuple(selected_stream)
        candidates = [r for r in candidates if stream_key(r) == selected_stream]
    elif len(streams) > 1:
        return [], ["multiple_sleep_streams_primary_source_required"]
    relevant_stages = ASLEEP | ({"awake"} if include_awake else set())
    candidates = [r for r in candidates if stage(r) in relevant_stages]
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


def subtract_intervals(intervals, excluded):
    result = []
    for first, last in union(intervals):
        fragments = [(first, last)]
        for a, b in union(excluded):
            fragments = [(x, y) for c, d in fragments for x, y in
                         ((c, min(d, a)), (max(c, b), d)) if x < y]
        result.extend(fragments)
    return result


def observed_sleep_episodes(rows, window):
    """Connected observed intervals stay intact across midnight and DST.

    Contiguous asleep/awake annotations identify only an observed event, never a
    proven complete night, actual wake-up, main sleep or nap. Separate sources
    are returned separately; no cross-source interval mosaic is constructed.
    """
    streams = defaultdict(list)
    for row in rows:
        if row.get("canonical_type") != "sleep_stage" or stage(row) not in ASLEEP | {"awake"}:
            continue
        try:
            a = instant(row.get("event_start") or row.get("start_utc"))
            b = instant(row.get("_event_end") or row.get("event_end") or row.get("end_utc"))
        except ValueError:
            continue
        if a < b <= instant(window.cutoff_time):
            streams[stream_key(row)].append((a, b, row))
    episodes = []
    for key, items in streams.items():
        clusters = []
        for a, b, row in sorted(items, key=lambda item: (item[0], item[1])):
            if clusters and a <= clusters[-1][1]:
                clusters[-1][1] = max(clusters[-1][1], b)
                clusters[-1][2].append((a, b, row))
            else:
                clusters.append([a, b, [(a, b, row)]])
        for first, last, entries in clusters:
            asleep = [(a, b) for a, b, row in entries if stage(row) in ASLEEP]
            awake = [(a, b) for a, b, row in entries if stage(row) == "awake"]
            if not asleep:
                continue
            day = last.astimezone(ZoneInfo(window.timezone)).date().isoformat()
            if not instant(window.start) <= last < min(instant(window.end), instant(window.cutoff_time)) or day not in local_date_domain(window.start, min(instant(window.end), instant(window.cutoff_time)), window.timezone):
                continue
            selected = subtract_intervals(asleep, awake)
            conflicts = [{"kind": "awake_asleep_overlap", "start": max(a, c).isoformat(), "end": min(b, d).isoformat()}
                         for a, b in union(asleep) for c, d in union(awake) if max(a, c) < min(b, d)]
            by_stage = defaultdict(list)
            for a, b, row in entries:
                name = stage(row).replace("asleep", "")
                if name in {"core", "deep", "rem"}:
                    by_stage[name].append((a, b))
            stage_conflicts = []
            names = sorted(by_stage)
            for i, name in enumerate(names):
                for other in names[i+1:]:
                    stage_conflicts.extend((max(a, c), min(b, d)) for a, b in union(by_stage[name])
                                          for c, d in union(by_stage[other]) if max(a, c) < min(b, d))
            if stage_conflicts:
                conflicts.extend({"kind": "stage_overlap", "start": a.isoformat(), "end": b.isoformat()}
                                 for a, b in union(stage_conflicts))
            stages = {name: subtract_intervals(values, awake + stage_conflicts) for name, values in by_stage.items()}
            staged = seconds([interval for values in stages.values() for interval in values])
            total = seconds(selected)
            ids = [row.get("_source_id", row.get("id")) for _, _, row in entries]
            episodes.append({"episode_id": "observed-sleep:" + canonical_hash([key, first, last, ids]),
                "statistics_version": SLEEP_VERSION, "date": day, "protocol": list(key), "source_id": str(key),
                "event_start": first.isoformat(), "event_end": last.isoformat(), "observed_start": first.isoformat(),
                "observed_end": last.isoformat(), "actual_wake_time": None, "end_uncertainty": "recording_may_have_stopped",
                "classification": "unclassified", "episode_complete": False, "value": total / 60, "unit": "min",
                "stage_minutes": {name: seconds(values) / 60 for name, values in stages.items()},
                "stage_coverage": staged / total if total else None, "stage_denominator_minutes": total / 60,
                "unknown_stage_minutes": (total-staged) / 60, "conflicts": conflicts,
                "arbitration": "single_stream_union_asleep_minus_explicit_awake;ambiguous_stages_unassigned",
                "intervals": [{"start": a.isoformat(), "end": b.isoformat()} for a, b in selected],
                "source_record_ids": ids, "n": len(entries),
                "available_at": max((row.get("available_at") or row.get("ingested_at") for _, _, row in entries
                                     if row.get("available_at") or row.get("ingested_at")), default=None)})
    for episode in episodes:
        episode["source_conflicts"] = [{"source_id": other["source_id"], "episode_id": other["episode_id"]}
            for other in episodes if episode["source_id"] != other["source_id"]
            and instant(episode["event_start"]) < instant(other["event_end"])
            and instant(other["event_start"]) < instant(episode["event_end"])]
    return episodes


def elapsed_dates(window: Window) -> int:
    return len(local_date_domain(instant(window.start), min(instant(window.end), instant(window.cutoff_time)), window.timezone))


def local_date_domain(start, end, zone_name: str) -> set[str]:
    """Local dates with positive support in the half-open instant interval."""
    zone = ZoneInfo(zone_name)
    start, end = instant(start), instant(end)
    if end <= start:
        return set()
    first = start.astimezone(zone).date()
    last = (end - timedelta(microseconds=1)).astimezone(zone).date()
    return {(first + timedelta(days=offset)).isoformat() for offset in range((last-first).days+1)}


def daily_values(rows: list[dict], canonical: str, zone_name: str) -> dict:
    streams = defaultdict(lambda: defaultdict(list))
    zone = ZoneInfo(zone_name)
    for row in rows:
        if row.get("canonical_type", row.get("metric_type")) != canonical:
            continue
        numeric = quantity_value(row)
        value = numeric["value"]
        if value is None:
            continue
        conditions = record_conditions(row)
        if canonical == "hrv_sdnn_ms" and str(conditions["metric_identity"]["value"] or "SDNN").upper() != "SDNN":
            continue
        end = row.get("_event_end") or row.get("event_end") or row.get("end_utc")
        day = instant(end).astimezone(zone).date().isoformat()
        key = physiology_stream_key(row) if canonical in {"hrv_sdnn_ms", "resting_heart_rate_bpm"} else stream_key(row)
        streams[key][day].append((value, {**row, "_numeric_provenance": numeric, "_conditions": conditions}))
    output = {}
    for key, days in streams.items():
        points = []
        for day, items in sorted(days.items()):
            primary = [(v, r) for v, r in items if r.get("is_primary") is True]
            # SDNN always describes a typical recorded sample that day. A primary
            # flag cannot give one opportunistic sample extra statistical weight.
            value = median(v for v, _ in items) if canonical == "hrv_sdnn_ms" or len(primary) != 1 else primary[0][0]
            observations = []
            for numeric, row in items:
                end = row.get("_event_end") or row.get("event_end") or row.get("end_utc")
                start = row.get("event_start") or row.get("start_utc") or end
                try:
                    metadata = json.loads(row.get("metadata_json") or "{}")
                    raw_times = metadata.get("original_timestamps", {}) if isinstance(metadata, dict) else {}
                except (ValueError, TypeError):
                    raw_times = {}
                original_start = raw_times.get("start") or row.get("start_original") or row.get("local_datetime")
                original_end = raw_times.get("end") or row.get("end_original")
                observations.append({"source_record_id": row.get("_source_id", row.get("id")),
                    "value": numeric, "unit": row["_numeric_provenance"]["unit"],
                    "start": start, "end": end, "local_time": instant(end).astimezone(zone).isoformat(),
                    "original_start": original_start, "original_end": original_end,
                    "start_offset_minutes": parse_apple_datetime(original_start)[2] if original_start else row.get("utc_offset_minutes"),
                    "end_offset_minutes": parse_apple_datetime(original_end)[2] if original_end else None,
                    "analysis_timezone": zone_name,
                    "available_at": row.get("available_at"), "conditions": row["_conditions"]})
            points.append({"date": day, "value": value, "n": len(items),
                "source_ids": [r.get("_source_id", r.get("id")) for _, r in items], "protocol": list(key),
                "statistic_kind": "median" if canonical == "hrv_sdnn_ms" or len(primary) != 1 else "explicit_primary_record",
                "aggregation_unit": "local_day", "statistics_version": PHYSIOLOGY_VERSION,
                "observations": observations, "conditions": observations[0]["conditions"],
                "numeric_provenance": [r["_numeric_provenance"] for _, r in items]})
        output[str(key)] = points
    return output


def comparison_windows(window, *, previous=None, baseline_days=28):
    """Viewing intervals, never medical minimum observation requirements."""
    zone = ZoneInfo(window.timezone)
    start, end = instant(window.start).astimezone(zone), min(instant(window.end), instant(window.cutoff_time)).astimezone(zone)
    reference_end = start.replace(hour=0, minute=0, second=0, microsecond=0)
    reference_start = reference_end - timedelta(days=max(1, int(baseline_days)))
    prior = previous or {"start": (start - (end-start)).isoformat(), "end": start.isoformat()}
    if instant(prior["end"]) > instant(window.start):
        raise ValueError("comparison_windows_must_not_overlap")
    return {"current": window.as_dict(),
            "previous": {**prior, "timezone": window.timezone, "closure": "[start,end)"},
            "reference": {"start": reference_start.isoformat(), "end": reference_end.isoformat(),
                          "timezone": window.timezone, "closure": "[start,end)"}}


def period_statistics(points, bounds, cutoff_time, unit):
    first, last = instant(bounds["start"]), min(instant(bounds["end"]), instant(cutoff_time))
    zone = ZoneInfo(bounds["timezone"])
    observed_domain = local_date_domain(first, last, bounds["timezone"])
    # Complete local calendar days, including 23/25-hour DST days. Existing
    # metric.value still exposes today's observations; they are not the default
    # completed-day comparison or reference population.
    domain = set()
    for day in observed_domain:
        midnight = datetime.fromisoformat(day).replace(tzinfo=zone)
        if first <= instant(midnight) and instant(midnight + timedelta(days=1)) <= last:
            domain.add(day)
    selected = [point for point in points if point["date"] in domain and finite(point.get("value")) is not None]
    partial_points = [point for point in points if point["date"] in observed_domain-domain and finite(point.get("value")) is not None]
    dates = sorted({point["date"] for point in selected})
    numbers = [point["value"] for point in selected]
    weekdays = Counter(instant(point["date"] + "T12:00:00+00:00").weekday() for point in selected)
    complete_window = ({"start": datetime.fromisoformat(min(domain)).replace(tzinfo=zone).isoformat(),
                        "end": (datetime.fromisoformat(max(domain)).replace(tzinfo=zone)+timedelta(days=1)).isoformat(),
                        "timezone": bounds["timezone"], "closure": "[start,end)"} if domain else None)
    return {"window": bounds, "complete_window": complete_window,
        "observed_window": {**bounds, "end": last.isoformat()},
        "value": median(numbers) if numbers else None, "unit": unit,
        "statistic_kind": "median", "quartiles": quantiles(numbers, n=4, method="inclusive") if len(numbers) > 1 else None,
        "recorded_days": len(dates), "window_days": len(domain), "dates": dates,
        "missing_dates": sorted(domain - set(dates)), "weekday_counts": {str(k): v for k, v in sorted(weekdays.items())},
        "daily_points": selected, "partial_daily_points": partial_points, "partial_dates": sorted(observed_domain-domain),
        "observed_window_days": len(observed_domain), "raw_record_count": sum(point.get("n", len(point.get("source_ids", []))) for point in selected),
        "source_record_ids": sorted({str(i) for point in selected for i in point.get("source_ids", point.get("source_record_ids", [])) if i is not None}),
        "current_date_complete": not partial_points}


def comparison_from_daily(groups, bounds, cutoff_time, unit):
    streams = []
    for key, periods in groups.items():
        summaries = {name: period_statistics(periods.get(name, []), interval, cutoff_time, unit) for name, interval in bounds.items()}
        current = summaries["current"]
        changes = {}
        limitations = ["个人历史观察范围不是健康正常范围；记录覆盖不代表完整采集。"]
        for name in ("previous", "reference"):
            other = summaries[name]
            difference = current["value"] - other["value"] if current["value"] is not None and other["value"] is not None else None
            changes[name + "_change"] = {"absolute": difference,
                "relative_percent": difference / other["value"] * 100 if difference is not None and other["value"] not in {None, 0} else None}
            if current["recorded_days"] != other["recorded_days"] or current["window_days"] != other["window_days"]:
                limitations.append(f"{name}与本期的记录天数或区间长度不同，代表性可能不同。")
            left = {k for k, v in current["weekday_counts"].items() if v}
            right = {k for k, v in other["weekday_counts"].items() if v}
            if left and right and left != right:
                limitations.append(f"{name}与本期的星期组成不同，不能直接推广到整周。")
        if current["partial_dates"]:
            limitations.append("当前或起始日期尚非完整观测日，已保留在趋势，未混入完整日比较。")
        first_point = next((p for points in periods.values() for p in points), {})
        protocol = first_point.get("protocol")
        if not protocol or protocol[2] is None or str(protocol[2]).startswith("context:"):
            limitations.append("测量协议未完整记录；同设备不证明相同体位、呼吸或采样情境。")
        entry = {"stream_id": key, "protocol": protocol, "metric_id": first_point.get("metric_id"),
                 **summaries, **changes, "limitations": limitations}
        entry["fact_id"] = "comparison:" + canonical_hash(entry)
        streams.append(entry)
    return {"version": PHYSIOLOGY_VERSION, "statistic_kind": "median_of_daily_medians", "streams": streams,
            "reference_policy": "complete_local_days_strictly_before_evaluation_window", "windows": bounds}


def physiology_comparison(rows, canonical, window, *, previous=None, baseline_days=28, retrospective=False):
    bounds = comparison_windows(window, previous=previous, baseline_days=baseline_days)
    groups = defaultdict(dict)
    exclusions = {}
    for name, interval in bounds.items():
        if instant(interval["start"]) >= instant(interval["end"]):
            continue
        selected, exclusions[name] = select_as_of(rows, Window(interval["start"], interval["end"], window.cutoff_time, window.timezone), retrospective=retrospective)
        for key, points in daily_values(selected, canonical, window.timezone).items():
            groups[key][name] = points
    output = comparison_from_daily(groups, bounds, window.cutoff_time, "ms" if canonical == "hrv_sdnn_ms" else "bpm")
    output["exclusions"] = exclusions
    return output


def state_metric(metric_id: str, rows: list[dict], window: Window, context: dict) -> dict:
    def emit(value=None, status="valid", **extra):
        return result(metric_id, window, value, data_status=status, **{"records": rows, **extra})

    if metric_id.startswith("STATE-SLEEP-"):
        start, end = instant(window.start), min(instant(window.end), instant(window.cutoff_time))
        if metric_id == "STATE-SLEEP-24H":
            end = instant(window.cutoff_time)
            start = end - timedelta(hours=24)
        main = context.get("main_sleep_episode")
        if metric_id == "STATE-SLEEP-MAIN" and not main:
            return emit(None, "insufficient", reasons=["main_sleep_episode_not_declared"], valid_n=0)
        if metric_id in {"STATE-SLEEP-MAIN", "STATE-SLEEP-STAGE"} and main:
            if not main.get("start") or not main.get("end") or not instant(main["start"]) < instant(main["end"]) <= instant(window.cutoff_time):
                return emit(None, "insufficient", reasons=["main_sleep_episode_boundary_invalid_or_future"], valid_n=0)
            start, end = max(start, instant(main["start"])), min(end, instant(main["end"]))
        intervals, reasons = sleep_intervals(rows, start, end, context, include_awake=True)
        if reasons and not intervals:
            return emit(None, "incompatible", reasons=reasons, valid_n=0, total_n=len(rows))
        raw_asleep = [(v["start"], v["end"]) for v in intervals if v["stage"] in ASLEEP]
        awake = [(v["start"], v["end"]) for v in intervals if v["stage"] == "awake"]
        asleep = subtract_intervals(raw_asleep, awake)
        sleep_conflicts = [{"start": max(a, c).isoformat(), "end": min(b, d).isoformat()}
                           for a, b in union(raw_asleep) for c, d in union(awake) if max(a, c) < min(b, d)]
        if metric_id in {"STATE-SLEEP-MAIN", "STATE-SLEEP-24H"}:
            if not asleep:
                return emit(None, "insufficient", reasons=["no_observed_asleep_intervals"])
            complete = metric_id == "STATE-SLEEP-MAIN" and bool(main and main.get("complete"))
            return emit({"observed_minutes": seconds(asleep) / 60, "complete_episode": complete,
                         "conflicts": sleep_conflicts, "arbitration": "single_stream_union_asleep_minus_explicit_awake",
                         "attribution_date": (main.get("attribution_date") or instant(main["end"]).astimezone(ZoneInfo(window.timezone)).date().isoformat()) if main else None,
                         "intervals": [{"start": a.isoformat(), "end": b.isoformat()} for a, b in asleep]},
                        "valid" if complete else "partial", evidence_status="observed",
                        reasons=([] if complete else ["observed_sleep_not_proven_complete_episode"]) + (["awake_asleep_conflict_excluded"] if sleep_conflicts else []),
                        algorithm_version=SLEEP_VERSION)
        if metric_id == "STATE-SLEEP-COVERAGE":
            domain = local_date_domain(start, end, window.timezone)
            dates = set().union(*(local_date_domain(a, b, window.timezone) for a, b in asleep)) & domain
            denominator = len(domain)
            return emit({"recorded_dates": len(dates), "elapsed_dates": denominator,
                         "fraction": len(dates) / denominator if denominator and dates else None,
                         "recorded_date_ids": sorted(dates), "eligible_date_ids": sorted(domain)},
                        "valid" if denominator and dates else "insufficient", valid_n=len(dates), total_n=denominator,
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
            try:
                a, b = instant(episode.get("start")), instant(episode.get("end"))
            except ValueError:
                continue
            if a < b <= instant(window.cutoff_time):
                episode_zone = episode.get("timezone", window.timezone)
                mid = (a + (b - a) / 2).astimezone(ZoneInfo(episode_zone))
                points.append({"start": a.isoformat(), "end": b.isoformat(), "midpoint": mid.isoformat(),
                               "recorded_start": episode["start"], "recorded_end": episode["end"],
                               "available_at": episode.get("available_at"), "source_record_id": episode.get("_source_id"),
                               "timezone": episode_zone,
                               "local_hour": mid.hour + mid.minute / 60 + mid.second / 3600})
        if not points:
            return emit(None, "insufficient", reasons=["explicit_sleep_episode_boundaries_required"],
                        records=episodes, valid_n=0, count_domain="sleep_episodes")
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
                     "resultant_length": concentration if len(groups) == 1 else None, "timezone_segments": groups,
                     "window_membership": "episode_end_in_half_open_window"},
                    "valid", evidence_status="descriptive", reasons=["timezone_changes_not_pooled"] if len(groups) > 1 else [],
                    records=episodes, valid_n=len(points), count_domain="sleep_episodes")
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
                    valid_n=sum(item["n"] for stream in values.values() for item in stream),
                    statistics_version=PHYSIOLOGY_VERSION, algorithm_version=PHYSIOLOGY_VERSION, statistic_kind="daily_median", aggregation_unit="local_day",
                    measurement_identity=canonical, measurement_origin="source_reported",
                    reasons=["protocol_streams_not_pooled", "SDNN_is_not_RMSSD"] if metric_id == "STATE-SDNN" else ["protocol_streams_not_pooled"])
    if metric_id in {"STATE-REFERENCE-MEDIAN", "STATE-REFERENCE-MAD", "STATE-DEVIATION"}:
        if "baseline_daily" not in context:
            streams = []
            reasons = ["equal_weight_per_day", "current_day_excluded_from_own_reference"]
            completed_days = context.get("baseline_completed_days")
            day_start = instant(window.cutoff_time).astimezone(ZoneInfo(window.timezone)).replace(hour=0, minute=0, second=0, microsecond=0)
            valid = 0
            for canonical in ("resting_heart_rate_bpm", "hrv_sdnn_ms"):
                for key, daily in daily_values(rows, canonical, window.timezone).items():
                    if not daily:
                        continue
                    current, past = daily[-1], daily[:-1]
                    if completed_days:
                        current = next((p for p in daily if p["date"] == day_start.date().isoformat()), None)
                        past = [p for p in daily if (day_start-timedelta(days=completed_days)).date().isoformat() <= p["date"] < day_start.date().isoformat()]
                    protocol = daily[-1]["protocol"]
                    center = median(v["value"] for v in past) if past else None
                    mad = median(abs(v["value"] - center) for v in past) if len(past) > 1 else None
                    protocol_known = (all(protocol) if completed_days else protocol[2] is not None) and not str(protocol[2]).startswith("context:")
                    deviation = current["value"] - center if current is not None and center is not None else None
                    z = deviation / (1.4826 * mad) if deviation is not None and protocol_known and mad is not None and mad > 0 else None
                    streams.append({"canonical_type": canonical, "stream": key, "protocol": protocol,
                                    "baseline_daily_n": len(past), "baseline_median": center, "MAD": mad,
                                    "scaled_MAD": 1.4826 * mad if mad is not None else None,
                                    "current_daily_value": current["value"] if current else None, "current_date": current["date"] if current else None,
                                    "absolute_deviation": deviation, "robust_z": z,
                                    "baseline_source_ids": [i for d in past for i in d["source_ids"]],
                                    "current_source_ids": current["source_ids"] if current else [],
                                    "reference_window": {"start": (day_start-timedelta(days=completed_days)).isoformat(), "end": day_start.isoformat(), "timezone": window.timezone} if completed_days else context.get("baseline_window", window.as_dict()),
                                    "baseline_dates": [p["date"] for p in past],
                                    "protocol_known": protocol_known})
                    valid += len(past)
                    if not protocol_known:
                        reasons.append("unknown_protocol_stream_descriptive_only")
                    if mad == 0:
                        reasons.append("MAD_zero_standardized_deviation_not_estimable")
                    if current is None:
                        reasons.append("current_local_day_not_observed")
            if not context.get("baseline_window"):
                reasons.append("baseline_window_equals_requested_window_product_default")
            if completed_days:
                reasons.append("explicit_completed_local_days_product_baseline")
            return emit({"streams": streams} if streams else None,
                        "valid" if streams and all(v["baseline_daily_n"] >= 2 and v["protocol_known"] and (metric_id != "STATE-DEVIATION" or v["absolute_deviation"] is not None) for v in streams)
                        else "partial" if valid else "insufficient", evidence_status="descriptive",
                        parameter_set_id=f"completed-local-days-1.6.1:{completed_days}" if completed_days else None,
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
                   "movement_impact": r.get("movement_impact"),
                   "observed_at": r.get("_event_end"), "available_at": r.get("available_at")} for r in rows if r.get(field) is not None]
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
            elapsed_seconds = (b - a).total_seconds()
            pause_seconds = seconds(pauses)
            duration_reasons = []
            if protocol == "user_elapsed_including_rest" and explicit is not None:
                duration = explicit / 60
                duration_source = "user_reported"
            elif protocol in {"elapsed_including_set_rest", "elapsed_minus_pauses", "event_elapsed_including_rest"}:
                expected = elapsed_seconds - pause_seconds if protocol == "elapsed_minus_pauses" else elapsed_seconds
                duration = expected / 60
                duration_source = "event_timestamps_and_union_pauses" if protocol == "elapsed_minus_pauses" else "event_elapsed"
                if explicit is not None and explicit != expected:
                    duration = None
                    duration_reasons.append("manual_and_event_duration_conflict")
            else:
                duration = None
                duration_source = "unknown_protocol"
            srpe = finite(session.get("session_rpe")) if session.get("srpe_protocol") else None
            # Repository sessions preserve their actual scale. The explicit
            # offline research protocol contract remains a 0–10 input; it does
            # not grant Foster applicability to a user's Borg or RIR-based RPE.
            scale = session.get("session_rpe_scale")
            bounds = {"cr10": (0, 10), "Foster_modified_CR10": (0, 10),
                      "borg6_20": (6, 20), "rir_rpe10": (1, 10)}.get(scale, (0, 10) if scale is None else None)
            if srpe is not None and (bounds is None or not bounds[0] <= srpe <= bounds[1]):
                srpe = None
            au_compatible = scale in {None, "cr10", "Foster_modified_CR10"}
            if srpe is not None and not au_compatible:
                duration_reasons.append("recorded_RPE_scale_not_session_CR10_load")
            delay = (instant(session["srpe_collected_at"]) - b).total_seconds() / 60 if session.get("srpe_collected_at") else None
            values.append({"session_id": session["session_id"], "session_rpe": srpe,
                           "duration_minutes": duration, "duration_source": duration_source,
                           "observed_elapsed_minutes": elapsed_seconds / 60, "union_pause_minutes": pause_seconds / 60,
                           "user_duration_seconds": explicit, "reason_codes": duration_reasons,
                           "actual_collection_delay_minutes": delay,
                           "recorded_scale": scale, "recorded_scale_range": list(bounds) if bounds else None,
                           "srpe_protocol": session.get("srpe_protocol"), "duration_protocol": session.get("duration_protocol"),
                           "AU": srpe * duration if au_compatible and srpe is not None and duration is not None else None})
        field = {"LOAD-SRPE": "session_rpe", "LOAD-DURATION": "duration_minutes", "LOAD-SRPE-AU": "AU"}[metric_id]
        valid = sum(v[field] is not None for v in values)
        return emit(values or None, "valid" if values and valid == len(values) else "partial" if valid else "insufficient",
                    valid_n=valid, total_n=len(values), n_sessions=len(values), count_domain="sessions",
                    source_record_ids=["session:" + str(v["session_id"]) for v in values], reasons=["set_RPE_not_session_RPE"])
    raise ValueError("unknown_state_metric")
