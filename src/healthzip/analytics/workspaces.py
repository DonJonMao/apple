"""Scoped body views using the existing canonical scientific evaluators.

These views are not complete analyses or frozen analysis runs. Their audit
inventory covers the selected source types, rather than unrelated inputs from
all 77 metrics. Each metric keeps its original scientific algorithm and window.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from time import perf_counter
from zoneinfo import ZoneInfo

from healthzip.analysis_settings import DEFAULT_BASELINE_DAYS
from healthzip.db.temporal_schema import latest_visible_source, samples_as_of
from healthzip.normalize import quantity_value
from healthzip.science import evaluate
from healthzip.science.contracts import Window, instant
from healthzip.science.observations import evaluate as evaluate_observation
from healthzip.science.state import comparison_windows, physiology_stream_key, record_conditions

from .cache import WORKSPACE_CACHE_SECONDS, cached, revision_identity
from .v13 import metric_card

SCOPE_VERSION = "body-workspace-scope-v3.0.0"
_SPECS = {
    "心率": (("resting_heart_rate_bpm", "hrv_sdnn_ms", "heart_rate_bpm"), ("STATE-RHR", "STATE-SDNN")),
    "心率 / HRV": (("resting_heart_rate_bpm", "hrv_sdnn_ms", "heart_rate_bpm"), ("STATE-RHR", "STATE-SDNN")),
    "睡眠": (("sleep_stage",), ("STATE-SLEEP-24H", "REPORT-STATE-SUMMARY")),
    "体重": (("body_mass_kg",), ("BODY-MASS-DAILY", "BODY-MASS-TREND")),
    "有氧": (("vo2_max_ml_kg_min",), ()),
    "体重 / 有氧": (("body_mass_kg",), ("BODY-MASS-DAILY", "BODY-MASS-TREND")),
}


def _latest_weight_observations(repo, cutoff, before, timezone_name, source_filter=()):
    """Find an outside-window reference using indexed, expanding time pages.

    Each page uses the same latest-visible-revision selector as canonical
    analysis, so a deleted or moved recent record cannot resurrect its past
    version. Paging changes query cost only, never historical eligibility.
    """
    cursor, width = before, 365
    floor = datetime.min.replace(tzinfo=timezone.utc)
    pages = 0
    while cursor > floor:
        start = cursor - timedelta(days=width) if (cursor - floor).days >= width else floor
        candidates = []
        for table, event_key in (("health_sample", "end_utc"), ("body_measurement", "measured_at")):
            rows = samples_as_of(repo, cutoff.isoformat(), table, window_start=start.isoformat(),
                                 window_end=cursor.isoformat(), canonical_types=["body_mass_kg"])
            for row in rows:
                source = row.get("source_name") or row.get("source_bundle_id") or row.get("source")
                if source_filter and source not in source_filter:
                    continue
                event = instant(row[event_key])
                numeric = quantity_value(row)
                if event >= cursor or numeric["value"] is None or numeric["unit"] != "kg" or numeric["value"] <= 0:
                    continue
                candidates.append({"date": event.astimezone(ZoneInfo(timezone_name)).date().isoformat(),
                    "event_end": event.isoformat(), "available_at": row.get("available_at"),
                    "value": numeric["value"], "unit": "kg",
                    "source": row.get("source_name") or row.get("source_bundle_id") or row.get("source"),
                    "source_record_ids": [f"{table}:{row['id']}"], "numeric_provenance": numeric,
                    "temporal_provenance": row.get("temporal_provenance"),
                    "scope": "historical_reference_outside_selected_window"})
        pages += 1
        if candidates:
            latest = max(instant(point["event_end"]) for point in candidates)
            return [point for point in candidates if instant(point["event_end"]) == latest], pages
        cursor, width = start, width * 2
    return [], pages


class WorkspaceInputsChanged(RuntimeError):
    """A concurrent import prevented a stable read; the UI can retry locally."""


def workspace_window(cutoff, timezone_name, *, period=None, window_days=30, window_start=None):
    """One half-open window for every fact, plot, explanation and detail."""
    local = cutoff.astimezone(ZoneInfo(timezone_name))
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if window_start:
        start = instant(window_start)
    elif period == "week":
        start = midnight - timedelta(days=local.weekday())
    elif period == "month":
        start = midnight.replace(day=1)
    elif period in {"30d", "last30"}:
        start = midnight - timedelta(days=29)
    elif period is None:
        start = cutoff - timedelta(days=max(1, int(window_days)))
    else:
        raise ValueError("unsupported_workspace_period")
    return start.astimezone(timezone.utc), cutoff


def latest_observation_dates(repo, timezone_name="Asia/Shanghai", *, cutoff_time=None):
    """Last active visible observation by source table, using indexed candidates.

    Resolve the latest revision before checking deletion or event time. This is
    footer metadata, independent from the selected page's measurement window.
    """
    zone = ZoneInfo(timezone_name)
    cutoff = instant(cutoff_time) if cutoff_time else datetime.now(timezone.utc)
    dependencies = [(table, None) for table in ("health_sample", "workout", "body_measurement")]

    def compute():
        output = {}
        for table, _ in dependencies:
            row = latest_visible_source(repo, table, cutoff.isoformat())
            if row:
                observed = row.get("end_utc") or row.get("measured_at") or row.get("observed_at")
                output[table] = instant(observed).astimezone(zone).date().isoformat()
            else:
                output[table] = None
        return output

    return cached(repo, "latest-observation-dates-1", {"timezone": timezone_name,
        "cutoff": cutoff.isoformat() if cutoff_time else cutoff.astimezone(zone).date().isoformat()},
        compute, dependencies=dependencies, max_age_seconds=None if cutoff_time else WORKSPACE_CACHE_SECONDS)


def _body_snapshot(repo, cutoff, start, canonical_types, *, source_filter=None, timings=None):
    records, counts = [], {}
    tables = ["health_sample"] + (["body_measurement"] if "body_mass_kg" in canonical_types else [])
    for table in tables:
        selected = _cached_source_rows(repo, table, canonical_types, start, cutoff, timings)
        counts[table] = len(selected)
        for original in selected:
            row = dict(original)
            row.update(record_kind=table, raw_id=row["id"], id=f"{table}:{row['id']}")
            row["source_name"] = row.get("source_name") or row.get("source_bundle_id") or row.get("source")
            if source_filter and row["source_name"] not in source_filter:
                continue
            row["event_end"] = row.get("end_utc") or row.get("measured_at")
            row["event_start"] = row.get("start_utc") or row["event_end"]
            records.append(row)
    return records, {"source_rows_returned": counts, "training_events_returned": 0,
                     "window_start": start.isoformat(), "window_end": cutoff.isoformat(),
                     "canonical_types": list(canonical_types),
                     "revision_policy": "latest_visible_before_type_and_support_filter"}


def _cached_source_rows(repo, table, canonical_types, start, cutoff, timings=None):
    """Reuse sparse source-month reads when switching comparison ranges/filters.

    Exact as-of visibility remains part of each key. Month boundaries are query
    partitions, never observation dates or sleep episode boundaries. Intervals
    overlapping two partitions are deduplicated by their resolved source ID.
    High-frequency ordinary heart rate keeps its existing bounded window query.
    """
    if start >= cutoff:
        return []
    if "heart_rate_bpm" in canonical_types or "vo2_max_ml_kg_min" in canonical_types:
        return samples_as_of(repo, cutoff.isoformat(), table, window_start=start.isoformat(),
            window_end=cutoff.isoformat(), canonical_types=list(canonical_types), timings=timings)
    cursor = start.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    dependencies = [(table, kind) for kind in canonical_types]
    rows = {}
    began = perf_counter()
    while cursor < cutoff:
        following = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = min(following, cutoff)
        bounds = {"start": cursor.isoformat(), "end": end.isoformat(),
                  "cutoff": cutoff.isoformat(), "table": table, "types": sorted(canonical_types)}
        def query(bounds=bounds):
            return samples_as_of(repo, bounds["cutoff"], table,
                window_start=bounds["start"], window_end=bounds["end"],
                canonical_types=list(canonical_types))
        for row in cached(repo, "source-month-1", bounds, query, dependencies=dependencies,
                          max_age_seconds=WORKSPACE_CACHE_SECONDS):
            event_end = instant(row.get("end_utc") or row.get("measured_at"))
            event_start = instant(row.get("start_utc") or row.get("measured_at") or event_end)
            if start <= event_end < cutoff or event_end > start and event_start < cutoff:
                rows[row["id"]] = row
        cursor = following
    if timings is not None:
        timings["source_partition_lookup_ms"] = timings.get("source_partition_lookup_ms", 0) + (perf_counter()-began)*1000
    return list(rows.values())


def _vo2_view(records, cutoff, start, timezone_name):
    metric = evaluate_observation("OBS-VO2-REPORTED", records, cutoff_time=cutoff.isoformat(),
        window_start=start.isoformat(), window_end=cutoff.isoformat(), context={"timezone": timezone_name})
    points = []
    for stream in (metric.get("value") or {}).get("streams", []):
        for observed in stream["observations"]:
            points.append({**observed, "normalized_value": observed["value"],
                "local_date": instant(observed["observed_at"]).astimezone(ZoneInfo(timezone_name)).date().isoformat(),
                **{key: stream.get(key) for key in ("source_name", "device", "protocol_id", "source_version")}})
    points.sort(key=lambda point: point["observed_at"])
    return {"points": points, "observations": points, "metric": metric, "card": metric_card(metric)}


def _historical_vo2(repo, cutoff, start, timezone_name, source_filter):
    cursor, width = start, 365
    floor = datetime.min.replace(tzinfo=timezone.utc)
    while cursor > floor:
        beginning = cursor - timedelta(days=width) if (cursor - floor).days >= width else floor
        records, _ = _body_snapshot(repo, cutoff, beginning, ("vo2_max_ml_kg_min",), source_filter=source_filter)
        records = [row for row in records if instant(row["event_end"]) < cursor]
        # Evaluate only historical candidates; selected page boundaries stay untouched.
        view = _vo2_view(records, cutoff, beginning, timezone_name)
        if view["points"]:
            latest = max(point["observed_at"] for point in view["points"])
            return [{**point, "scope": "historical_reference_outside_selected_window"}
                    for point in view["points"] if point["observed_at"] == latest]
        cursor, width = beginning, width * 2
    return []


def _ordinary_heart_observations(records, start, cutoff, zone, *, display_limit=400):
    """All records determine distributions; only actual points are downsampled."""
    groups = defaultdict(list)
    # Many opportunity samples carry identical source/protocol metadata. Resolve
    # that identity once per request, while retaining every actual observation.
    # Unknown sources stay record-specific, exactly as physiology_stream_key.
    resolved = {}
    identity_fields = ("source_name", "source_bundle_id", "source", "device_id", "device", "protocol_id",
                       "source_version", "metadata_json", "sampling_mode", "measurement_context",
                       "breathing_context", "posture", "respiration", "activity_context")
    for row in records:
        event = instant(row["event_end"])
        if not start <= event < cutoff:
            continue
        numeric = quantity_value(row)
        if numeric["value"] is not None:
            signature = tuple((name in row, row.get(name)) for name in identity_fields)
            if not (row.get("source_name") or row.get("source_bundle_id") or row.get("source")):
                signature += (("unknown_record", row.get("_source_id", row.get("id", "unidentified"))),)
            try:
                protocol = resolved.get(signature)
            except TypeError:
                # Irregular imported metadata values are still interpreted by
                # the original canonical adapter, not coerced for the cache.
                protocol = physiology_stream_key(row)
            else:
                if protocol is None:
                    protocol = physiology_stream_key(row)
                    if len(resolved) >= 512:
                        resolved.clear()
                    resolved[signature] = protocol
            groups[(event.astimezone(zone).date().isoformat(), protocol)].append((numeric["value"], row))
    daily, candidates = [], []
    for (day, protocol), items in sorted(groups.items(), key=lambda item: (item[0][0], str(item[0][1]))):
        source = protocol[0]
        values = [value for value, _ in items]
        daily.append({"date": day, "source": source, "protocol": protocol,
            "conditions": record_conditions(items[0][1]), "sample_count": len(items),
            "sample_median": median(values), "minimum": min(values), "maximum": max(values),
            "unit": "bpm", "statistic_kind": "opportunistic_sample_distribution"})
        # Keep actual endpoints/extrema per temporal bucket, never synthetic averages.
        ordered = sorted(items, key=lambda item: item[1]["event_end"])
        bucket_count = max(1, display_limit // max(1, len(groups)) // 4)
        width = max(1, (len(ordered)+bucket_count-1)//bucket_count)
        for position in range(0, len(ordered), width):
            bucket = ordered[position:position+width]
            chosen = [bucket[0], min(bucket, key=lambda item: item[0]), max(bucket, key=lambda item: item[0]), bucket[-1]]
            for numeric, row in chosen:
                candidates.append({"date": day, "observed_at": row["event_end"], "value": numeric, "unit": "bpm",
                    "source": source, "source_record_id": row["id"], "conditions": record_conditions(row)})
    unique = {point["source_record_id"]: point for point in candidates}
    points = sorted(unique.values(), key=lambda point: point["observed_at"])
    if len(points) > display_limit:
        indices = {round(index*(len(points)-1)/(display_limit-1)) for index in range(display_limit)}
        points = [point for index, point in enumerate(points) if index in indices]
    return {"observations": points, "ordinary_daily": daily, "ordinary_sample_count": sum(item["sample_count"] for item in daily),
            "ordinary_display_count": len(points), "ordinary_display_method": "actual_endpoints_and_extrema_bounded_display_only",
            "ordinary_heart_rate_statistic": "opportunistic_observations_not_time_weighted_daily_average"}


def analyze_workspace(repo, workspace, window_days=30, timezone_name="Asia/Shanghai", cutoff_time=None,
                      *, period=None, window_start=None, source_filter=None, baseline_days=DEFAULT_BASELINE_DAYS,
                      comparison_start=None, comparison_end=None):
    """Read only the page's scientific dependencies, using one committed snapshot.

    Ordinary browsing never initializes training, persists analysis, runs RAG or
    touches recommendations. Automatic calls reuse the original observed cutoff
    until a relevant committed revision, local date boundary or safety expiry.
    """
    if workspace not in _SPECS:
        raise ValueError("unsupported_body_workspace")
    zone = ZoneInfo(timezone_name)
    cutoff = instant(cutoff_time) if cutoff_time else datetime.now(timezone.utc)
    canonical_types, metric_ids = _SPECS[workspace]
    if workspace == "体重 / 有氧":
        canonical_types = (*canonical_types, "vo2_max_ml_kg_min")
    dependencies = [("health_sample", kind) for kind in canonical_types]
    if workspace in {"心率", "心率 / HRV"}:
        dependencies.append(("subjective_log", None))
    if "body_mass_kg" in canonical_types:
        dependencies.append(("body_measurement", "body_mass_kg"))
    if cutoff_time is None:
        # A retained request clock lets adjacent windows reuse the same as-of
        # source partitions without mixing two visibility cutoffs.
        cutoff = instant(cached(repo, "body-request-clock-1",
            {"workspace": workspace, "timezone": timezone_name, "date": cutoff.astimezone(zone).date().isoformat()},
            lambda: cutoff.isoformat(), dependencies=dependencies, max_age_seconds=WORKSPACE_CACHE_SECONDS))
    start, cutoff = workspace_window(cutoff, timezone_name, period=period,
                                     window_days=window_days, window_start=window_start)
    if start > cutoff:
        raise ValueError("workspace_window_reversed")
    previous = None
    if comparison_start or comparison_end:
        if not comparison_start or not comparison_end:
            raise ValueError("comparison_start_and_end_required")
        previous = {"start": comparison_start, "end": comparison_end}
    elif period == "week":
        previous = {"start": (start.astimezone(zone) - timedelta(days=7)).isoformat(),
                    "end": (cutoff.astimezone(zone) - timedelta(days=7)).isoformat()}
    elif period == "month":
        local_start = start.astimezone(zone)
        previous_end = local_start
        previous_start = (local_start - timedelta(days=1)).replace(day=1)
        previous = {"start": previous_start.isoformat(),
                    "end": min(previous_start + (cutoff.astimezone(zone)-local_start), previous_end).isoformat()}
    comparisons = (comparison_windows(Window(start.isoformat(), cutoff.isoformat(), cutoff.isoformat(), timezone_name),
                   previous=previous, baseline_days=baseline_days) if start < cutoff else None)
    source_filter = tuple(sorted(source_filter or ()))
    arguments = {"scope_version": SCOPE_VERSION, "workspace": workspace, "window_days": int(window_days),
                 "period": period, "window_start": window_start, "source_filter": source_filter,
                 "baseline_days": baseline_days, "comparison_start": comparison_start, "comparison_end": comparison_end,
                 "timezone": timezone_name, "cutoff": cutoff.isoformat(),
                 "cutoff_mode": "explicit" if cutoff_time else "auto"}

    for _ in range(2):
        baseline = revision_identity(repo, dependencies=dependencies)

        def compute():
            began = perf_counter()
            timings = {}
            # STATE-SLEEP-24H has a fixed scientific window. Month/week views
            # near midnight must also read yesterday's eligible sleep; the
            # page's daily facts still evaluate only the selected page window.
            query_start = min(instant(bound["start"]) for bound in comparisons.values()) if comparisons and workspace in {"心率", "心率 / HRV", "睡眠"} else start
            if workspace == "睡眠" and start < cutoff:
                query_start = min(query_start - timedelta(days=1), cutoff-timedelta(hours=24))
            scientific_types = tuple(kind for kind in canonical_types if kind != "heart_rate_bpm")
            records, plan = _body_snapshot(repo, cutoff, query_start, scientific_types,
                                          source_filter=source_filter, timings=timings)
            ordinary = {}
            ordinary_latest = None
            if "heart_rate_bpm" in canonical_types and start < cutoff:
                ordinary_records, ordinary_plan = _body_snapshot(repo, cutoff, start, ("heart_rate_bpm",),
                    source_filter=source_filter, timings=timings)
                ordinary_latest = max((row["event_end"] for row in ordinary_records
                    if start <= instant(row["event_end"]) < cutoff), key=instant, default=None)
                ordinary = _ordinary_heart_observations(ordinary_records, start, cutoff, zone)
                plan["ordinary_heart_query"] = ordinary_plan
                del ordinary_records
            page_records = [row for row in records if
                start <= instant(row["event_end"]) < cutoff or
                instant(row["event_end"]) > start and instant(row["event_start"]) < cutoff]
            evaluated = perf_counter()
            data_version = str(baseline["metadata"])
            context = {"timezone": timezone_name, "data_version": data_version,
                       "baseline_days": baseline_days, "comparison_window": previous}
            if workspace in {"心率", "心率 / HRV"} and start < cutoff:
                subjective = samples_as_of(repo, cutoff.isoformat(), "subjective_log",
                    window_start=start.isoformat(), window_end=cutoff.isoformat())
                for row in subjective:
                    records.append({**row, "record_kind": "subjective_log", "id": f"subjective_log:{row['id']}",
                        "event_start": row.get("observed_at"), "event_end": row.get("observed_at")})
            metrics = {identity: evaluate(identity, records, cutoff_time=cutoff.isoformat(),
                       window_start=start.isoformat(), window_end=cutoff.isoformat(), context=context)
                       for identity in metric_ids} if start < cutoff else {}
            if workspace in {"心率", "心率 / HRV"} and start < cutoff:
                metrics["STATE-FATIGUE"] = evaluate("STATE-FATIGUE", records, cutoff_time=cutoff.isoformat(),
                    window_start=start.isoformat(), window_end=cutoff.isoformat(), context=context)
            scope = {"scope_version": SCOPE_VERSION, "workspace": workspace, "full_analysis": False,
                     "canonical_types": list(canonical_types), "metric_ids": list(metric_ids), "period": period,
                     "metrics": metrics, "comparisons": {key: value["comparison"] for key, value in metrics.items() if "comparison" in value}, "cutoff_time": cutoff.isoformat(), "cutoff_mode": arguments["cutoff_mode"],
                     "window_start": start.isoformat(), "window_end": cutoff.isoformat(), "timezone": timezone_name,
                     "data_version": data_version, "query_plan": plan, "source_filter": list(source_filter),
                     "latest_observed_at": max([row["event_end"] for row in page_records
                         if instant(row["event_end"]) <= cutoff] + ([ordinary_latest] if ordinary_latest else []), key=instant, default=None),
                     "input_scope": "workspace_canonical_types_only",
                     "audit_scope": "unrelated_source_and_context_inventory_not_included",
                     "cache_policy": {"automatic_refresh_seconds": WORKSPACE_CACHE_SECONDS,
                                      "revision_invalidated": True, "dependency_domains": dependencies,
                                      "persistent_writes": False}}
            if workspace == "睡眠" and metrics:
                scope["extra_metric_windows"] = {"STATE-SLEEP-24H": {
                    "label": "过去24小时（独立于所选范围）",
                    "window": metrics["STATE-SLEEP-24H"]["window"],
                    "included_in_page_daily_statistics": False}}
            output = {"workspace_scope": scope}
            if start == cutoff:
                # Scientific MetricResult requires a positive window. An empty
                # calendar boundary has no metric; do not borrow yesterday's data.
                return {**output, "heart": {"cards": []}, "sleep": {"nights": []},
                        "weight": {"daily": []}, "vo2": {"points": [], "observations": []}}
            if not page_records:
                historical = [latest_visible_source(repo, table, cutoff.isoformat(),
                    canonical_types=canonical_types, before=start.isoformat(), sources=source_filter)
                    for table in (["health_sample", "body_measurement"] if "body_mass_kg" in canonical_types else ["health_sample"])]
                scope["latest_historical_observation_at"] = max((row.get("end_utc") or row.get("measured_at")
                    for row in historical if row), default=None)
            if workspace in {"心率", "心率 / HRV"}:
                output["heart"] = {"cards": [metric_card(metrics[identity]) for identity in metric_ids], **ordinary}
            elif workspace == "睡眠":
                summary = metrics["REPORT-STATE-SUMMARY"]
                output["sleep"] = {"card": metric_card(metrics["STATE-SLEEP-24H"]), "nights": [
                    {"date": fact["date"], "sleep_hours": fact["value"] / 60,
                     "series_id": fact.get("series_id"), "series_label": fact.get("series_label"),
                     "source": fact.get("source_id"), "source_ids": fact.get("source_record_ids", []),
                     "episode_complete": fact.get("episode_complete"), "episodes": fact.get("episodes", []),
                     "observed_start": fact.get("event_start"), "observed_end": fact.get("event_end"),
                     "n": fact.get("n"), "statistic_kind": fact.get("statistic_kind"),
                     "algorithm_version": summary["algorithm_version"]}
                    for fact in summary.get("daily_facts", [])
                    if fact.get("series_id") == "observed_sleep_by_wake_date" and fact.get("value") is not None]}
            elif "body_mass_kg" in canonical_types:
                daily = metrics["BODY-MASS-DAILY"]
                output["weight"] = {"card": metric_card(metrics["BODY-MASS-TREND"]), "daily": [
                    {"date": fact["date"], "kg": fact["value"], "source": source,
                     "source_ids": fact["source_ids"], "algorithm_version": daily["algorithm_version"]}
                    for source, facts in (daily["value"] or {}).items() for fact in facts]}
                if not output["weight"]["daily"]:
                    latest, pages = _latest_weight_observations(repo, cutoff, start, timezone_name, source_filter)
                    output["weight"]["latest_observations"] = latest
                    scope["history_reference"] = {"selection": "latest_visible_usable_weight_by_event_time",
                        "scope": "outside_selected_window", "cutoff_time": cutoff.isoformat(),
                        "searched_time_pages": pages, "included_in_window_metrics": False}
            if "vo2_max_ml_kg_min" in canonical_types:
                output["vo2"] = _vo2_view(records, cutoff, start, timezone_name)
                if not output["vo2"]["points"]:
                    output["vo2"]["latest_observations"] = _historical_vo2(repo, cutoff, start, timezone_name, source_filter)
                scope["vo2_scope"] = "latest_visible_revision_in_selected_window"
                scope["metrics"]["OBS-VO2-REPORTED"] = output["vo2"]["metric"]
            timings["scientific_evaluation_ms"] = (perf_counter() - evaluated) * 1000
            timings["server_compute_ms"] = (perf_counter() - began) * 1000
            scope["timings_ms"] = timings
            if revision_identity(repo, dependencies=dependencies) != baseline:
                raise WorkspaceInputsChanged("body_workspace_inputs_changed")
            return output

        try:
            value = cached(repo, SCOPE_VERSION, arguments, compute, dependencies=dependencies,
                           max_age_seconds=None if cutoff_time else WORKSPACE_CACHE_SECONDS)
        except WorkspaceInputsChanged:
            continue
        if revision_identity(repo, dependencies=dependencies) == baseline:
            return value
    raise WorkspaceInputsChanged("body_workspace_inputs_changed_retry_later")
