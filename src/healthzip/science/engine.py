"""One execution and return contract for all 77 v1.3 metrics."""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from .contracts import Window, definitions, instant, select_as_of, validate_result
from .energy import energy_metric
from .evaluation import quality_metric
from .prediction import prediction_metric
from .reports import derive_report_context, report_metric
from .semantics import flatten_record
from .state import state_metric
from .strength import strength_metric


def evaluate(metric_id: str, records: Optional[list[dict]] = None, *, cutoff_time: str,
             window_start: str, window_end: str, context: Optional[dict] = None,
             _normalized: Optional[list[dict]] = None) -> dict:
    if metric_id not in definitions():
        raise ValueError("unregistered_metric_id")
    context = dict(context or {})
    window = Window(window_start, window_end, cutoff_time, context.get("timezone", "UTC"))
    context_exclusions = []
    # Optional derived context must obey the same decision-time contract as SQL
    # samples. It cannot become a back door for future revisions or outcomes.
    for key in ("comparison_pair", "mass_series", "baseline_daily", "b1_training_pairs",
                "daily_metric_facts", "energy_days", "recommendation_outcomes"):
        if key not in context:
            continue
        source = [flatten_record(r) for r in context[key]]
        query_window = window
        if key == "baseline_daily" and context.get("baseline_window"):
            bounds = context["baseline_window"]
            query_window = Window(bounds["start"], bounds["end"], cutoff_time, window.timezone)
        context[key], rejected = select_as_of(source, query_window, retrospective=context.get("retrospective", False),
                                              overlap=key == "energy_days")
        context_exclusions.extend({"context": key, **r} for r in rejected)
    for key in ("current_observation", "state_at_cutoff", "previous_state"):
        observation = context.get(key)
        if not observation:
            continue
        event = observation.get("event_end")
        available = observation.get("available_at")
        if not event or not available or instant(event) > instant(cutoff_time) or instant(available) > instant(cutoff_time):
            context[key] = None
            context_exclusions.append({"context": key, "reason": "observation_availability_unverified_or_future"})
    normalized = _normalized if _normalized is not None else [flatten_record(r) for r in records or []]
    if metric_id.startswith("REPORT-") or metric_id == "ENERGY-RECORD-COVERAGE":
        if "daily_metric_facts" not in context or "energy_days" not in context:
            report_rows, _ = select_as_of(normalized, window, retrospective=context.get("retrospective", False), overlap=True)
            derived = derive_report_context(report_rows, window)
            context = {**derived, **context}
    if metric_id.startswith("STR-") or metric_id.startswith("PRED-"):
        relevant = [r for r in normalized if r.get("record_kind", "strength_set") == "strength_set"]
    elif metric_id.startswith("STATE-SLEEP-"):
        relevant = [r for r in normalized if r.get("canonical_type") == "sleep_stage" or r.get("metric_type") == "sleep" or "stage" in r]
    elif metric_id in {"STATE-RHR", "STATE-SDNN"}:
        canonical = "resting_heart_rate_bpm" if metric_id == "STATE-RHR" else "hrv_sdnn_ms"
        relevant = [r for r in normalized if r.get("canonical_type", r.get("metric_type")) == canonical]
    elif metric_id in {"STATE-REFERENCE-MEDIAN", "STATE-REFERENCE-MAD", "STATE-DEVIATION"}:
        canonical = context.get("baseline_canonical_type")
        types = {canonical} if canonical else {"resting_heart_rate_bpm", "hrv_sdnn_ms"}
        relevant = [r for r in normalized if r.get("canonical_type", r.get("metric_type")) in types]
    elif metric_id in {"STATE-FATIGUE", "STATE-SORENESS", "STATE-PAIN"}:
        field = metric_id.split("-")[1].lower()
        relevant = [r for r in normalized if field in r or r.get("record_kind") == "subjective_log"]
    elif metric_id.startswith("BODY-MASS-"):
        relevant = [r for r in normalized if r.get("canonical_type") == "body_mass_kg"]
    elif metric_id in {"ENERGY-BASAL", "ENERGY-ACTIVE", "ENERGY-DEVICE-TOTAL"}:
        types = {"ENERGY-BASAL": {"basal_energy_kcal"}, "ENERGY-ACTIVE": {"active_energy_kcal"},
                 "ENERGY-DEVICE-TOTAL": {"basal_energy_kcal", "active_energy_kcal"}}[metric_id]
        relevant = [r for r in normalized if r.get("canonical_type", r.get("metric_type")) in types]
    elif metric_id.startswith("QAL-") or metric_id.startswith("LOAD-"):
        relevant = []  # Explicit evaluation/session context has its own count domain.
    else:
        relevant = normalized
    selection_window = window
    if metric_id == "STATE-SLEEP-24H":
        window = Window((instant(cutoff_time) - timedelta(hours=24)).isoformat(),
                        instant(cutoff_time).isoformat(), cutoff_time, window.timezone)
        selection_window = window
    if metric_id in {"STATE-REFERENCE-MEDIAN", "STATE-REFERENCE-MAD", "STATE-DEVIATION"} and context.get("baseline_window"):
        bounds = context["baseline_window"]
        selection_window = Window(bounds["start"], bounds["end"], cutoff_time, window.timezone)
    selected, excluded = select_as_of(relevant, selection_window, retrospective=context.get("retrospective", False),
                                     overlap=metric_id.startswith(("STATE-SLEEP-", "ENERGY-", "REPORT-")))
    if metric_id.startswith("STR-"):
        value = strength_metric(metric_id, selected, window, context)
    elif metric_id.startswith("STATE-") or metric_id.startswith("LOAD-"):
        value = state_metric(metric_id, selected, window, context)
    elif metric_id.startswith("BODY-") or metric_id.startswith("ENERGY-"):
        value = energy_metric(metric_id, selected, window, context)
    elif metric_id.startswith("PRED-"):
        value = prediction_metric(metric_id, selected, window, context)
    elif metric_id.startswith("REPORT-"):
        value = report_metric(metric_id, selected, window, context)
    elif metric_id.startswith("QAL-"):
        value = quality_metric(metric_id, selected, window, context)
    else:
        raise ValueError("registered_metric_has_no_executor")
    value["exclusions"] = excluded + context_exclusions
    value["input_snapshot_n"] = len(relevant)
    value["input_available_n"] = len(selected)
    if any(r["reason"] == "unresolved_record_conflict" for r in excluded):
        value["reason_codes"].append("unresolved_input_conflict_excluded")
        value["data_status"] = "conflicted"
    validate_result(value, calibration=context.get("calibration"))
    return value


def evaluate_all(records: Optional[list[dict]] = None, *, cutoff_time: str, window_start: str,
                 window_end: str, context: Optional[dict] = None) -> dict[str, dict]:
    normalized = [flatten_record(r) for r in records or []]
    context = dict(context or {})
    window = Window(window_start, window_end, cutoff_time, context.get("timezone", "UTC"))
    report_rows, _ = select_as_of(normalized, window, retrospective=context.get("retrospective", False), overlap=True)
    context = {**derive_report_context(report_rows, window), **context}
    return {metric_id: evaluate(metric_id, cutoff_time=cutoff_time, window_start=window_start,
                                window_end=window_end, context=context, _normalized=normalized)
            for metric_id in definitions()}
