"""Scoped, versioned facts from visible Repository revisions for the body pages."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import timedelta
from statistics import median
from zoneinfo import ZoneInfo

from healthzip.db.temporal_schema import samples_as_of
from healthzip.normalize import quantity_value
from healthzip.science.body_catalog import METRIC_CATALOG
from healthzip.science.calendar_trend import fit_daily
from healthzip.science.contracts import Window, canonical_hash, instant, result
from healthzip.science.sleep_regularity import sleep_regularity
from healthzip.science.state import (
    comparison_windows,
    daily_values,
    observed_sleep_episodes,
    period_statistics,
    physiology_stream_key,
    record_conditions,
)

from .alternate_observations import alternate_dependencies, alternate_rows
from .cache import cached

VERSION = "typed-body-facts-1.2"


def _rows(repo, table, types, start, end, cutoff, sources):
    rows = samples_as_of(
        repo,
        cutoff,
        table,
        canonical_types=types,
        window_start=start.isoformat(),
        window_end=end.isoformat(),
    )
    answer = []
    for row in rows:
        source = row.get("source_name") or row.get("source_bundle_id") or row.get("source")
        stop = row.get("end_utc") or row.get("measured_at") or row.get("observed_at")
        if stop and instant(stop) <= instant(cutoff) and (not sources or source in sources):
            answer.append(
                {
                    **row,
                    "source_name": source,
                    "record_kind": table,
                    "id": f"{table}:{row['id']}",
                    "event_end": stop,
                    "event_start": row.get("start_utc") or stop,
                }
            )
    return answer


def _metadata(row):
    try:
        data = json.loads(row.get("metadata_json") or "{}")
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    for entry in data.get("MetadataEntry", []):
        if isinstance(entry, dict) and entry.get("key"):
            data.setdefault(entry["key"], entry.get("value"))
    return data


def _point(day, value, observations):
    ids = [x["id"] for x in observations]
    return {
        "date": day,
        "value": value,
        "observed_at": observations[-1]["event_end"],
        "n": len(ids),
        "sample_count": len(ids),
        "source_record_ids": ids,
        "observations": observations,
    }


def _observation(row, value, metadata, unit):
    return {
        "id": row["id"],
        "value": value,
        "unit": unit,
        "source": row.get("source_name"),
        "source_version": row.get("source_version"),
        "device": row.get("device"),
        "event_start": row["event_start"],
        "event_end": row["event_end"],
        "available_at": row.get("available_at"),
        "raw_value": row.get("raw_value"),
        "raw_unit": row.get("raw_unit"),
        "raw_type": row.get("raw_type"),
        "original_timestamps": metadata.get("original_timestamps"),
        "utc_offset_minutes": row.get("utc_offset_minutes"),
        "category": row.get("category_value"),
        "aggregation": metadata.get("aggregation"),
        "support_start": metadata.get("support_start"),
        "support_end": metadata.get("support_end"),
        "calibration": metadata.get("calibration"),
        "algorithm_version": metadata.get("algorithm_version"),
        "method": metadata.get("method"),
        "measurement_context": metadata.get("measurement_context"),
        "workout_ids": row.get("workout_ids"),
        "sleep_episode_ids": row.get("sleep_episode_ids"),
        "representation": metadata.get("representation", row.get("record_kind")),
        "event_time_precision": metadata.get("event_time_precision", "instant"),
        "log_status": metadata.get("log_status"),
    }


def _summarize_group(kind, observations, excluded):
    items = sorted(
        observations, key=lambda x: (instant(x["event_start"]), instant(x["event_end"]), x["id"])
    )
    if items and all(x["aggregation"] == "daily_summary" for x in items):
        if len({x["value"] for x in items}) == 1:
            return items[0]["value"]
        excluded.extend({"id": x["id"], "reason": "conflicting_daily_summary"} for x in items)
        return None
    if kind == "event":
        return len(items)
    if kind == "stand":
        stood = {"HKCategoryValueAppleStandHourStood", "stood", "0"}
        idle = {"HKCategoryValueAppleStandHourIdle", "idle", "1"}
        if any(x["category"] not in stood | idle for x in items):
            excluded.extend(
                {"id": x["id"], "reason": "unknown_stand_hour_category"}
                for x in items
                if x["category"] not in stood | idle
            )
            return None
        return len(
            {
                instant(x["event_start"]).replace(minute=0, second=0, microsecond=0)
                for x in items
                if x["category"] in stood
            }
        )
    if kind not in {"sum", "sound", "intake"}:
        return median(i["value"] for i in items)
    cumulative = [
        x for x in items if x["aggregation"] in ("cumulative", "daily_cumulative", "running_total")
    ]
    if cumulative:
        if len(cumulative) == len(items) and all(
            x["event_start"] == items[0]["event_start"] for x in items
        ):
            return items[-1]["value"]
        excluded.extend(
            {"id": x["id"], "reason": "ambiguous_cumulative_and_incremental_support"} for x in items
        )
        return None
    if kind == "intake":
        return sum(x["value"] for x in items)
    if any(instant(a["event_end"]) > instant(b["event_start"]) for a, b in zip(items, items[1:])):
        excluded.extend({"id": x["id"], "reason": "overlapping_support_unresolved"} for x in items)
        return None
    if kind == "sum":
        return sum(x["value"] for x in items)
    durations = [
        (instant(x["event_end"]) - instant(x["event_start"])).total_seconds() for x in items
    ]
    if any(s <= 0 for s in durations):
        excluded.extend(
            {"id": x["id"], "reason": "sound_duration_required"}
            for x, d in zip(items, durations)
            if d <= 0
        )
        return None
    # Subtracting the maximum before exponentiation avoids overflow without censoring observations.
    peak = max(x["value"] for x in items)
    return peak + 10 * math.log10(
        sum(s * 10 ** ((x["value"] - peak) / 10) for x, s in zip(items, durations)) / sum(durations)
    )


def _points(key, rows, window, excluded, episodes):
    spec = METRIC_CATALOG[key]
    kind = spec["kind"]
    zone = ZoneInfo(window.timezone)
    grouped = defaultdict(lambda: defaultdict(list))
    if key in {"resting_heart_rate_bpm", "hrv_sdnn_ms", "body_mass_kg"}:
        points = {}
        eligible = []
        for row in rows:
            value = quantity_value(row)["value"]
            if value is not None and value < 0:
                excluded.append({"id": row["id"], "reason": "nonnegative_quantity_required"})
            else:
                eligible.append(row)
        rows = eligible
        if key == "body_mass_kg":
            adapted = []
            for row in rows:
                meta = _metadata(row)
                conditions = {
                    k: meta[k]
                    for k in (
                        "instrument",
                        "scale_id",
                        "method",
                        "measurement_context",
                        "posture",
                        "day_type",
                    )
                    if k in meta
                }
                if conditions:
                    row = {
                        **row,
                        "protocol_id": json.dumps(
                            [physiology_stream_key(row)[2], conditions],
                            sort_keys=True,
                            ensure_ascii=False,
                        ),
                    }
                adapted.append(row)
            rows = adapted
        for series in daily_values(rows, key, window.timezone).values():
            for p in series:
                p.update(
                    observed_at=p["observations"][-1]["end"],
                    sample_count=p["n"],
                    source_record_ids=p["source_ids"],
                )
            points[tuple(series[0]["protocol"])] = series
        used = {rid for series in points.values() for p in series for rid in p["source_ids"]}
        excluded.extend(
            {"id": r["id"], "reason": "metric_identity_or_numeric_unit_unverified"}
            for r in rows
            if r["id"] not in used
        )
        return points
    if kind == "sleep":
        for ep in episodes:
            if not instant(window.start) <= instant(ep["event_end"]) < instant(window.end):
                continue
            known = sum(ep["stage_minutes"].values())
            observation = {
                **ep,
                "known_stage_minutes": known,
                "stage_fraction_of_known": {k: v / known for k, v in ep["stage_minutes"].items()}
                if known
                else None,
            }
            grouped[tuple(ep["protocol"])][ep["date"]].append(observation)
        return {
            s: [
                {
                    "date": day,
                    "value": sum(e["value"] for e in eps),
                    "observed_at": eps[-1]["event_end"],
                    "sample_count": sum(e["n"] for e in eps),
                    "n": sum(e["n"] for e in eps),
                    "source_record_ids": [i for e in eps for i in e["source_record_ids"]],
                    "observations": eps,
                }
                for day, eps in sorted(days.items())
            ]
            for s, days in grouped.items()
        }
    for r in rows:
        end, start = instant(r["event_end"]), instant(r["event_start"])
        allocation = (
            end - timedelta(microseconds=1)
            if end > start and kind in {"sum", "stand", "sound"}
            else end
        )
        if not instant(window.start) <= allocation < instant(window.end):
            continue
        meta = _metadata(r)
        stream = list(physiology_stream_key(r))
        extras = {
            k: meta[k]
            for k in (
                "method",
                "algorithm_version",
                "temperature_identity",
                "carrying_position",
                "speed_stratum",
                "instrument",
                "scale_id",
                "body_position",
                "day_type",
                "route",
                "calibration_id",
            )
            if meta.get(k) is not None
        }
        if key in {
            "oxygen_saturation_fraction",
            "respiratory_rate_bpm",
            "sleeping_wrist_temperature_c",
        }:
            extras["sleep_overlap"] = bool(r.get("sleep_episode_ids"))
        if extras:
            stream[2] = json.dumps([stream[2], extras], sort_keys=True, ensure_ascii=False)
        numeric = quantity_value(r)
        value = numeric["value"]
        summary_stand = key == "stand_hour" and meta.get("representation") == "activity_summary"
        if summary_stand:
            value = r["normalized_value"]
        if key == "sleeping_wrist_temperature_c" and meta.get("temperature_identity") in {
            "baseline_delta",
            "relative",
            "deviation",
        }:
            # Celsius differences transform linearly; Fahrenheit differences
            # have no 32-degree origin offset.
            from healthzip.normalize import parse_number

            raw = parse_number(r.get("raw_value"))
            u = str(r.get("raw_unit", "")).lower()
            if raw is not None and u in {"f", "degf", "°f"}:
                value = raw * 5 / 9
        if key == "heart_rate_recovery_1m" and value is not None and value <= 0:
            excluded.append(
                {"id": r["id"], "reason": "source_definition_requires_positive_recovery_count"}
            )
            continue
        if kind in {"event", "stand"} and not summary_stand:
            if r.get("category_value") is None:
                excluded.append({"id": r["id"], "reason": "category_unavailable"})
                continue
        elif value is None or (spec["unit"] == "fraction" and not 0 <= value <= 1):
            excluded.append({"id": r["id"], "reason": "value_or_unit_unverified"})
            continue
        elif value < 0 and key not in {
            "sleeping_wrist_temperature_c",
            "environmental_audio_dba",
            "headphone_audio_dba",
        }:
            excluded.append({"id": r["id"], "reason": "nonnegative_quantity_required"})
            continue
        # Include interval endings exactly at midnight in the day just completed.
        day = allocation.astimezone(zone).date().isoformat()
        obs = _observation(r, value, meta, spec["unit"])
        if (
            kind in {"sum", "sound"}
            and start.astimezone(zone).date() != allocation.astimezone(zone).date()
        ):
            if kind == "sum":
                excluded.append(
                    {
                        "id": r["id"],
                        "reason": "increment_spans_calendar_days_daily_allocation_unknown",
                        "observation": obs,
                    }
                )
                continue
            # A single interval Leq does not establish constituent daily Leqs.
            excluded.append(
                {
                    "id": r["id"],
                    "reason": "sound_interval_spans_midnight_energy_split_unknown",
                    "observation": obs,
                }
            )
            continue
        grouped[tuple(stream)][day].append(obs)
    output = {}
    for stream, days in grouped.items():
        points = []
        for day, obs in sorted(days.items()):
            obs.sort(key=lambda x: (instant(x["event_end"]), x["id"]))
            if kind in {"estimate", "event", "samples"}:
                # Low-frequency estimates retain distinct publication times; no synthetic days.
                for o in obs:
                    points.append(_point(day, 1 if kind == "event" else o["value"], [o]))
            else:
                value = _summarize_group(kind, obs, excluded)
                if value is not None:
                    points.append(_point(day, value, obs))
        if kind == "estimate":
            seen, previous_support = set(), []
            for point in points:
                obs = point["observations"][0]
                a, b = obs["support_start"], obs["support_end"]
                known_apple_method = (
                    key == "six_minute_walk_m"
                    and obs["algorithm_version"] == "Apple-6MWD-2021"
                    and obs["method"] == "passive_estimate"
                )
                if known_apple_method and not a and not b:
                    a = (instant(obs["event_end"]) - timedelta(days=28)).isoformat()
                    b = obs["event_end"]
                try:
                    support = (
                        (instant(a), instant(b)) if a and b and instant(a) < instant(b) else None
                    )
                except ValueError:
                    support = None
                identity = (a, b, obs["value"])
                overlap = bool(
                    support
                    and any(max(support[0], x) < min(support[1], y) for x, y in previous_support)
                )
                point["estimate_support"] = {
                    "start": a,
                    "end": b,
                    "repeated_publication": bool(support and identity in seen),
                    "overlaps_prior_window": overlap if support else None,
                    "method": obs["method"],
                    "algorithm_version": obs["algorithm_version"],
                    "upper_limit_m": 500 if known_apple_method else None,
                    "at_reportable_limit": obs["value"] == 500 if known_apple_method else None,
                    "calibration": obs["calibration"],
                }
                if support:
                    seen.add(identity)
                    previous_support.append(support)
        output[stream] = points
        if kind in {"sum", "stand", "sound"}:
            for point in points:
                last = point["observations"][-1]
                stop = instant(last["event_end"])
                point["allocation_at"] = (
                    stop - timedelta(microseconds=1)
                    if stop > instant(last["event_start"])
                    else stop
                ).isoformat()
    return output


def _daily_summary(points, bounds, cutoff, unit, kind):
    # Date-equal period comparisons; within-date raw observations remain viewable.
    grouped = defaultdict(list)
    for p in points:
        if (
            instant(bounds["start"])
            <= instant(p.get("allocation_at", p["observed_at"]))
            < min(instant(bounds["end"]), instant(cutoff))
        ):
            grouped[p["date"]].append(p)
    daily = []
    for day, items in grouped.items():
        values = [p["value"] for p in items]
        daily.append(
            {
                "date": day,
                "value": sum(values) if kind == "event" else median(values),
                "n": sum(i["n"] for i in items),
                "source_ids": [r for i in items for r in i["source_record_ids"]],
            }
        )
    summary = period_statistics(daily, bounds, cutoff, unit)
    summary["calendar_coverage_proves_measurement_coverage"] = False
    summary["sample_count"] = summary["raw_record_count"]
    if kind in {"sum", "intake", "stand", "event"}:
        summary["recorded_total"] = (
            sum(i["value"] for i in summary["daily_points"]) if summary["daily_points"] else None
        )
    return summary


def change_layers(
    change, reference, *, current=None, measurement=None, goal=None, identity=None, unit=None
):
    """Matched repeatability evidence and an independent goal scale are optional."""

    def qualified(evidence):
        return bool(
            identity
            and unit
            and evidence
            and evidence.get("identity") == identity
            and evidence.get("unit") == unit
            and evidence.get("source")
            and isinstance(evidence.get("threshold"), (float, int))
            and not isinstance(evidence.get("threshold"), bool)
            and math.isfinite(evidence["threshold"])
            and evidence["threshold"] > 0
        )

    quartiles = reference.get("quartiles")
    matched_error = (
        qualified(measurement) and measurement.get("basis") == "matched_repeat_measurements"
    )
    matched_goal = qualified(goal) and goal.get("basis") == "prespecified_goal_scale"
    return {
        "historical_quartiles": quartiles,
        "observed_difference": change,
        "within_reference_iqr": quartiles[0] <= current <= quartiles[2]
        if current is not None and quartiles
        else None,
        "exceeds_repeatability_limit": abs(change) > measurement["threshold"]
        if change is not None and matched_error
        else None,
        "meets_independent_goal_magnitude": abs(change) >= goal["threshold"]
        if change is not None and matched_goal
        else None,
        "measurement_evidence": measurement if matched_error else None,
        "goal_evidence": goal if matched_goal else None,
    }


def analyze_body_metric(
    repo,
    canonical_type,
    *,
    window_start,
    window_end,
    cutoff_time,
    timezone_name="Asia/Shanghai",
    source_filter=(),
    with_model=False,
    previous=None,
    baseline_days=28,
    availability_context=None,
    period=None,
    change_evidence=(),
):
    spec = METRIC_CATALOG[canonical_type]
    start, end, cutoff = instant(window_start), instant(window_end), instant(cutoff_time)
    window = Window(start.isoformat(), end.isoformat(), cutoff.isoformat(), timezone_name)
    if previous is None and period in {"week", "month"}:
        z = ZoneInfo(timezone_name)
        local_start, local_end = start.astimezone(z), min(end, cutoff).astimezone(z)
        if period == "week":
            prior_start, prior_end = local_start - timedelta(days=7), local_end - timedelta(days=7)
        else:
            prior_start = (local_start - timedelta(days=1)).replace(day=1)
            prior_end = min(local_start, prior_start + (local_end - local_start))
        previous = {"start": prior_start.isoformat(), "end": prior_end.isoformat()}
    bounds = comparison_windows(window, previous=previous, baseline_days=baseline_days)
    lower = min(instant(v["start"]) for v in bounds.values())
    upper = min(end, cutoff)
    sources = tuple(sorted(source_filter or ()))
    field = "heart_rate_bpm" if canonical_type == "workout_heart_rate_bpm" else canonical_type
    dependencies = [("health_sample", field)]
    dependencies.extend(alternate_dependencies(field))
    if field in {"body_mass_kg", "height_cm", "body_fat_fraction", "lean_body_mass_kg"}:
        dependencies.append(("body_measurement", field))
    night = field in {
        "sleep_stage",
        "oxygen_saturation_fraction",
        "respiratory_rate_bpm",
        "sleeping_wrist_temperature_c",
    }
    if night and field != "sleep_stage":
        dependencies.append(("health_sample", "sleep_stage"))
    if canonical_type == "workout_heart_rate_bpm":
        dependencies.append(("workout", None))
    context_status = (availability_context or {}).get("status")
    if context_status not in {
        None,
        "not_applicable",
        "feature_disabled",
        "export_unsupported",
        "parser_unsupported",
    }:
        raise ValueError("unknown_availability_declaration")
    batch_clock = tuple(
        repo.one(
            "SELECT count(*),max(id),max(imported_at) FROM import_batch WHERE julianday(imported_at)<=julianday(?) AND status IN ('completed','partial_failed')",
            (cutoff.isoformat(),),
        )
    )
    key = {
        "period": period,
        "availability_context": availability_context,
        "batch_clock": batch_clock,
        "version": VERSION,
        "field": canonical_type,
        "bounds": bounds,
        "cutoff": cutoff.isoformat(),
        "source_filter": sources,
        "model": with_model,
        "change_evidence": change_evidence,
    }

    def compute():
        rows = []
        for table, typ in dependencies:
            if typ == field:
                rows.extend(_rows(repo, table, [typ], lower, upper, cutoff.isoformat(), sources))
        rows += alternate_rows(
            repo, field, lower, upper, cutoff.isoformat(), timezone_name, sources, rows
        )
        if canonical_type == "workout_heart_rate_bpm":
            workouts = _rows(repo, "workout", None, lower, upper, cutoff.isoformat(), ())
            for r in rows:
                r["workout_ids"] = [
                    w["id"]
                    for w in workouts
                    if instant(w["event_start"])
                    <= instant(r["event_end"])
                    < instant(w["event_end"])
                ]
            rows = [
                r
                for r in rows
                if r["workout_ids"]
                or record_conditions(r)["activity_context"]["value"] == "workout"
            ]
        episodes = []
        regularity = {}
        full = Window(lower.isoformat(), upper.isoformat(), cutoff.isoformat(), timezone_name)
        if night:
            sleeps = (
                rows
                if field == "sleep_stage"
                else _rows(
                    repo, "health_sample", ["sleep_stage"], lower, upper, cutoff.isoformat(), ()
                )
            )
            episodes = observed_sleep_episodes(sleeps, full)
            if field == "sleep_stage":
                current_episodes = [e for e in episodes if start <= instant(e["event_end"]) < upper]
                regularity = sleep_regularity(sleeps, current_episodes, window)
            else:
                intervals = [
                    (instant(i["start"]), instant(i["end"]), e["episode_id"])
                    for e in episodes
                    for i in e["intervals"]
                ]
                for r in rows:
                    r["sleep_episode_ids"] = [
                        eid for a, b, eid in intervals if a <= instant(r["event_end"]) < b
                    ]
        excluded = []
        streams = _points(canonical_type, rows, full, excluded, episodes)
        output = []
        unit = "次" if spec["kind"] == "event" else spec["unit"]
        for s, points in streams.items():
            current_points = [
                p
                for p in points
                if start <= instant(p.get("allocation_at", p["observed_at"])) < upper
            ]
            summaries = {
                k: _daily_summary(points, b, cutoff.isoformat(), unit, spec["kind"])
                for k, b in bounds.items()
            }
            current, prior = summaries["current"], summaries["previous"]
            change = (
                current["value"] - prior["value"]
                if current["value"] is not None and prior["value"] is not None
                else None
            )
            trend = {
                "status": "descriptive_only",
                "reason": "此观察单位保留事件或分组比较。",
                "interval": None,
            }
            if with_model and spec["kind"] in {"daily", "sleep"}:
                trend = fit_daily(current["daily_points"], unit)
            overlap = set(current["weekday_counts"]) & set(prior["weekday_counts"])

            def matched(item):
                vals = [
                    p["value"]
                    for p in item["daily_points"]
                    if str(instant(p["date"] + "T12:00:00Z").weekday()) in overlap
                ]
                return median(vals) if vals else None

            c, p = matched(current), matched(prior)
            comparison_identity = "body-comparison:" + canonical_hash(
                [canonical_type, list(s), unit]
            )
            eligible_evidence = [
                e for e in change_evidence if e.get("identity") == comparison_identity
            ]
            measurement = next(
                (e for e in eligible_evidence if e.get("basis") == "matched_repeat_measurements"),
                None,
            )
            goal = next(
                (e for e in eligible_evidence if e.get("basis") == "prespecified_goal_scale"), None
            )
            output.append(
                {
                    "source": s[0],
                    "device": s[1],
                    "protocol": s[2],
                    "source_version": s[3],
                    "comparison_identity": comparison_identity,
                    "points": current_points,
                    **summaries,
                    "absolute_change": change,
                    "trend": trend,
                    "regularity": regularity.get(s),
                    "sensitivity": {
                        "common_weekdays": sorted(overlap),
                        "difference": c - p if c is not None and p is not None else None,
                        "scope": "两期均有记录的星期；不假设其余日期随机缺失。",
                    },
                    "change_layers": change_layers(
                        change,
                        summaries["reference"],
                        current=current["value"],
                        measurement=measurement,
                        goal=goal,
                        identity=comparison_identity,
                        unit=unit,
                    ),
                    "comparison_scope": "同来源已记录日期；协议未知时只描述这些记录。",
                    "fact_id": "body:"
                    + canonical_hash(
                        [key, s, [(x["date"], x["value"], x["source_record_ids"]) for x in points]]
                    ),
                }
            )
        current_rows = [
            r
            for r in rows
            if start
            <= (
                instant(r["event_end"]) - timedelta(microseconds=1)
                if spec["kind"] in {"sum", "sound", "stand"}
                and instant(r["event_end"]) > instant(r["event_start"])
                else instant(r["event_end"])
            )
            < upper
        ]
        current_ids = {r["id"] for r in current_rows}
        valid = {
            i for s in output for p in s["points"] for i in p["source_record_ids"]
        } & current_ids
        availability = (
            "observed"
            if valid
            else "invalid_or_unusable"
            if current_rows
            else "no_visible_records_in_period"
        )
        if not current_rows:
            if context_status and (availability_context or {}).get("source"):
                availability = context_status
            elif not batch_clock[0] and not rows:
                availability = "no_visible_import_or_record"
        return result(
            spec["metric_id"],
            window,
            {"streams": output},
            unit=unit,
            algorithm_version=VERSION,
            records=current_rows,
            valid_n=len(valid),
            total_n=len(current_rows),
            evidence_status="descriptive",
            data_status="partial" if valid else "insufficient",
            reasons=[availability],
            exclusions=excluded,
            availability=availability,
            canonical_type=canonical_type,
            scope=key,
            capabilities={
                "generated_by_device": "originating_source_report_available_device_eligibility_unverified"
                if current_rows
                else "unknown",
                "exported": "observed_in_import"
                if any(r.get("source_kind") == "apple_zip" for r in current_rows)
                else "unknown",
                "parse": "implemented",
                "calculate": "observed" if valid else "no_eligible_inputs",
                "interpret": "descriptive_only",
                "display": "supported",
            },
        )

    return cached(repo, VERSION, key, compute, dependencies=dependencies)


def analyze_questions(
    repo,
    *,
    window_start,
    window_end,
    cutoff_time,
    timezone_name="Asia/Shanghai",
    source_filter=(),
    question_ids=None,
    period=None,
    previous=None,
):
    from .body_questions import question_views

    return question_views(
        repo,
        window_start=window_start,
        window_end=window_end,
        cutoff_time=cutoff_time,
        timezone_name=timezone_name,
        source_filter=source_filter,
        question_ids=question_ids,
        period=period,
        previous=previous,
    )
