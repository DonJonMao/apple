"""Scoped body views using the existing canonical scientific evaluators.

These views are not complete analyses or frozen analysis runs. Their audit
inventory covers the selected source types, rather than unrelated inputs from
all 77 metrics. Each metric keeps its original scientific algorithm and window.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from healthzip.db.temporal_schema import samples_as_of
from healthzip.normalize import quantity_value
from healthzip.science import evaluate
from healthzip.science.contracts import instant
from healthzip.training.service import TrainingService

from .cache import cached
from .core import vo2_analysis
from .v13 import metric_card, snapshot

SCOPE_VERSION = "body-workspace-scope-v1.1.0"
_SPECS = {
    "心率 / HRV": (("resting_heart_rate_bpm", "hrv_sdnn_ms"), ("STATE-RHR", "STATE-SDNN")),
    "睡眠": (("sleep_stage",), ("STATE-SLEEP-24H", "REPORT-STATE-SUMMARY")),
    "体重 / 有氧": (("body_mass_kg",), ("BODY-MASS-DAILY", "BODY-MASS-TREND")),
}


def _latest_weight_observations(repo, cutoff, before, timezone_name):
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


def analyze_workspace(repo, workspace, window_days=30, timezone_name="Asia/Shanghai", cutoff_time=None):
    """Calculate only the canonical metrics consumed by one body workspace.

    The VO2 view retains its existing current-record inventory semantics; it is
    explicitly separate from the canonical metrics' decision-time snapshot.
    Automatic cache reuse displays the original computed cutoff, as analyze().
    """
    if workspace not in _SPECS:
        raise ValueError("unsupported_body_workspace")
    ZoneInfo(timezone_name)
    now = datetime.now(timezone.utc)
    cutoff = instant(cutoff_time) if cutoff_time else now
    days = max(1, int(window_days))
    arguments = {"scope_version": SCOPE_VERSION, "workspace": workspace, "window_days": days,
                 "timezone": timezone_name, "cutoff": cutoff.isoformat() if cutoff_time else
                 now.replace(second=0, microsecond=0).isoformat(),
                 "cutoff_mode": "explicit" if cutoff_time else "auto"}

    def compute():
        start = cutoff - timedelta(days=days)
        canonical_types, metric_ids = _SPECS[workspace]
        records, inherited = snapshot(repo, cutoff.isoformat(), window_start=start.isoformat(),
                                      window_end=cutoff.isoformat(), canonical_types=list(canonical_types))
        # snapshot() also adapts training and other source tables. They are not
        # inputs to these scoped body metrics; keep the narrower audit explicit.
        records = [row for row in records if row.get("canonical_type") in canonical_types]
        context = {"timezone": timezone_name, "data_version": inherited["data_version"]}
        metrics = {identity: evaluate(identity, records, cutoff_time=cutoff.isoformat(),
                   window_start=start.isoformat(), window_end=cutoff.isoformat(), context=context)
                   for identity in metric_ids}
        scope = {"scope_version": SCOPE_VERSION, "workspace": workspace, "full_analysis": False,
                 "canonical_types": list(canonical_types), "metric_ids": list(metric_ids),
                 "metrics": metrics, "cutoff_time": cutoff.isoformat(),
                 "cutoff_mode": arguments["cutoff_mode"], "window_start": start.isoformat(),
                 "window_end": cutoff.isoformat(), "timezone": timezone_name,
                 "data_version": inherited["data_version"], "query_plan": inherited["query_plan"],
                 "input_scope": "workspace_canonical_types_only",
                 "audit_scope": "unrelated_source_and_context_inventory_not_included",
                 "cache_policy": {"automatic_refresh_seconds": 60, "revision_invalidated": True}}
        output = {"workspace_scope": scope}
        if workspace == "心率 / HRV":
            output["heart"] = {"cards": [metric_card(metrics[identity]) for identity in metric_ids]}
        elif workspace == "睡眠":
            summary = metrics["REPORT-STATE-SUMMARY"]
            output["sleep"] = {"card": metric_card(metrics["STATE-SLEEP-24H"]), "nights": [
                {"date": fact["date"], "sleep_hours": fact["value"] / 60,
                 "series_id": fact.get("series_id"), "series_label": fact.get("series_label"),
                 "source": fact.get("source_id"), "source_ids": fact.get("source_record_ids", []),
                 "episode_complete": fact.get("episode_complete"),
                 "algorithm_version": summary["algorithm_version"]}
                for fact in summary.get("daily_facts", [])
                if fact.get("series_id") == "observed_sleep_by_wake_date" and fact.get("value") is not None]}
        else:
            daily = metrics["BODY-MASS-DAILY"]
            output["weight"] = {"card": metric_card(metrics["BODY-MASS-TREND"]), "daily": [
                {"date": fact["date"], "kg": fact["value"], "source": source,
                 "source_ids": fact["source_ids"], "algorithm_version": daily["algorithm_version"]}
                for source, facts in (daily["value"] or {}).items() for fact in facts]}
            if not output["weight"]["daily"]:
                latest, pages = _latest_weight_observations(repo, cutoff, start, timezone_name)
                output["weight"]["latest_observations"] = latest
                scope["history_reference"] = {"selection": "latest_visible_usable_weight_by_event_time",
                    "scope": "outside_selected_window", "cutoff_time": cutoff.isoformat(),
                    "searched_time_pages": pages, "included_in_window_metrics": False}
            output["vo2"] = vo2_analysis(repo)
            scope["vo2_scope"] = "current_active_record_inventory_without_asof_or_window_filter"
        return output

    # Cold initialization changes revision metadata. Finish it before choosing
    # the cache key; subsequent calls remain read-only and reuse the first run.
    TrainingService(repo)
    return cached(repo, SCOPE_VERSION, arguments, compute)
