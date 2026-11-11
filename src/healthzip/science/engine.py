"""One execution and return contract for all 77 v1.3 metrics."""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from healthzip.normalize import TYPE_MAP, quantity_value

from .contracts import (
    Window,
    canonical_hash,
    definitions,
    instant,
    result,
    select_as_of,
    validate_result,
)
from .energy import energy_metric
from .evaluation import quality_metric
from .prediction import prediction_metric
from .reports import derive_report_context, report_metric
from .semantics import analysis_task, flatten_record, outcome_series
from .state import state_metric
from .strength import reference_rows, strength_metric

TASK_METRICS = {f"STR-{number:02d}" for number in (7, 8, 11, 12, 13, 14, *range(16, 27))} | {"PRED-B0", "PRED-B1"}
SERIES_METRICS = {"STR-19", "STR-20", "STR-22", "STR-24"}
NUMERIC_TYPES = {name for name, unit in TYPE_MAP.values() if unit != "category"}


def _undated_plan_states(rows, window, context):
    """Retain visible plan decisions without inventing an execution endpoint."""
    declarations = [{**plan, "id": "plan-session:" + str(plan["session_id"])}
                    for plan in context.get("session_plans", []) if plan.get("session_id") is not None]
    plans, _ = select_as_of(declarations, window)
    membership = {(str(slot["id"]), plan["session_id"]): plan
                  for plan in plans for slot in plan.get("sets", [])
                  if slot.get("id") is not None and slot.get("session_id") == plan["session_id"]}
    requested = {str(slot["id"]) for slot in (context.get("plan_snapshot") or {}).get("sets", [])}
    latest = {}
    for position, original in enumerate(rows):
        row = dict(original)
        identity = str(row.get("record_id", row.get("id", position)))
        available = row.get("available_at") or row.get("ingested_at")
        try:
            known_at = instant(available)
        except ValueError:
            continue
        if known_at > instant(window.cutoff_time):
            continue
        logical = (row.get("source_kind"), row.get("source_name"),
                   row.get("source_record_id") or row.get("original_uuid") or identity)
        rank = (known_at.isoformat(), str(row.get("revision_id", "")), identity)
        if logical not in latest or rank > latest[logical][0]:
            latest[logical] = (rank, {**row, "_source_id": identity})
    retained, provenance = [], []
    for _, row in latest.values():
        planned_id = str(row.get("planned_set_id"))
        plan = membership.get((planned_id, row.get("session_id")))
        if not plan or planned_id not in requested:
            continue
        if (row.get("status") not in {"draft", "in_progress", "aborted", "skipped"}
                or row.get("conflicted") is True or row.get("record_status") in {"deleted", "conflicted"}
                or row.get("deleted_at") and instant(row["deleted_at"]) <= instant(window.cutoff_time)):
            continue
        event = (row.get("event_end") or row.get("end_at_utc") or row.get("end_utc")
                 or row.get("performed_at") or row.get("timestamp"))
        if event:
            continue  # Dated execution facts retain the ordinary event-window path.
        start = row.get("event_start") or row.get("started_at")
        if start and instant(start) > instant(window.cutoff_time):
            continue
        retained.append(row)
        provenance.append({"source_record_id": row["_source_id"], "planned_set_id": planned_id,
                           "session_id": row["session_id"], "state_available_at": row.get("available_at") or row.get("ingested_at"),
                           "original_plan_event_end": plan["_event_end"],
                           "membership": "original_plan_session_in_half_open_window_actual_endpoint_unknown"})
    return retained, provenance


def _series_metric(metric_id, rows, window, context):
    groups, identities, excluded = {}, {}, []
    for row in reference_rows(rows, context):
        identity = outcome_series(row)
        if not identity["eligible"]:
            excluded.append({"id": row.get("_source_id"), "reason": "outcome_series_ineligible",
                             "reason_codes": identity["reason_codes"]})
            continue
        key = identity["outcome_series_id"]
        if context.get("outcome_series_id") and key != context["outcome_series_id"]:
            excluded.append({"id": row.get("_source_id"), "reason": "different_outcome_series"})
            continue
        identities[key] = identity
        groups.setdefault(key, []).append(row)
    results = []
    for key, group in groups.items():
        derived = {**context, **context.get("series_contexts", {}).get(key, {}), "_series_evaluation": True,
                   "observed_outcome_series_id": key}
        # Legacy single-series callers retain their old receipt binding. New
        # explicit series callers bind both series identity and record snapshot.
        if context.get("outcome_series_id") or context.get("series_contexts"):
            derived["outcome_series_id"] = key
        digest = canonical_hash({"records": group, "window": window.as_dict(), "cutoff_time": window.cutoff_time,
                                 "data_version": str(context.get("data_version"))})
        derived["data_snapshot_hash"] = digest
        calculated = evaluate(metric_id, cutoff_time=window.cutoff_time, window_start=window.start,
                              window_end=window.end, context=derived, _normalized=group)
        results.append({**identities[key], "source_record_ids": [r["_source_id"] for r in group],
                        "first_observed_at": group[0]["_event_end"], "last_observed_at": group[-1]["_event_end"],
                        "data_snapshot_hash": digest, "input_data_hash": canonical_hash(group), "metric": calculated})
    if not results:
        return result(metric_id, window, None, records=rows, valid_n=0, data_status="insufficient",
                      reasons=["eligible_outcome_series_missing"], series_results=[], series_exclusions=excluded)
    if len(results) == 1:
        return {**results[0]["metric"], "series_results": results, "series_exclusions": excluded}
    return result(metric_id, window,
                  {"series": [{"outcome_series_id": item["outcome_series_id"], "normalized_load": item["normalized_load"],
                               "normalized_unit": item["normalized_unit"], "value": item["metric"]["value"],
                               "valid_n": item["metric"]["valid_n"], "data_status": item["metric"]["data_status"]} for item in results]},
                  records=rows, valid_n=sum(item["metric"]["valid_n"] for item in results),
                  data_status="valid" if all(item["metric"]["data_status"] == "valid" for item in results) else "partial",
                  evidence_status="descriptive" if metric_id == "STR-19" else "research_only",
                  reasons=["independent_fixed_load_outcome_series"], series_results=results, series_exclusions=excluded)


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
                "daily_metric_facts", "energy_days", "recommendation_outcomes", "current_session_observations",
                "sleep_episodes"):
        if key not in context:
            continue
        source = []
        for record in context[key]:
            row = record
            if key == "recommendation_outcomes" and record.get("recommendation_id"):
                row = {**record, "source_record_id": record["recommendation_id"]}
            elif key == "sleep_episodes":
                # A declared sleep episode is one event, attributed by its end;
                # its original endpoints remain intact for midpoint arithmetic.
                row = {**record, "event_start": record.get("start"), "event_end": record.get("end")}
            source.append(flatten_record(row))
        query_window = window
        if key == "baseline_daily" and context.get("baseline_window"):
            bounds = context["baseline_window"]
            query_window = Window(bounds["start"], bounds["end"], cutoff_time, window.timezone)
        context[key], rejected = select_as_of(source, query_window, retrospective=context.get("retrospective", False),
                                              overlap=key in {"energy_days", "daily_metric_facts"})
        if key == "current_session_observations":
            context["current_session_observation_unknown_ids"] = [r["id"] for r in rejected
                if r["reason"] in {"timestamp_required", "timezone_required", "available_at_unknown"}]
        context_exclusions.extend({"context": key, **r} for r in rejected)
    for key in ("current_observation", "state_at_cutoff", "previous_state", "body_mass_observation"):
        observation = context.get(key)
        if not observation:
            continue
        event = observation.get("event_end", observation.get("end_utc"))
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
    plan_status_provenance = []
    if metric_id == "STR-09":
        states, plan_status_provenance = _undated_plan_states(relevant, window, context)
        selected.extend(states)
        retained_ids = {row["_source_id"] for row in states}
        excluded = [entry for entry in excluded if not (entry["id"] in retained_ids and entry["reason"] == "timestamp_required")]
    numeric_audit = [{"id": r.get("_source_id"), **quantity_value(r)} for r in selected
                     if r.get("canonical_type", r.get("metric_type")) in NUMERIC_TYPES]
    if metric_id in {"STR-19", "STR-20", "STR-22", "STR-24"}:
        context["observed_snapshot_hash"] = canonical_hash({"records": selected, "window": window.as_dict(), "cutoff_time": cutoff_time,
                                                          "data_version": str(context.get("data_version"))})
        task_ids = {analysis_task(row)["task_id"] for row in selected}
        context["observed_task_id"] = next(iter(task_ids)) if len(task_ids) == 1 else None
    if metric_id in SERIES_METRICS and not context.get("_series_evaluation"):
        value = _series_metric(metric_id, selected, window, context)
    elif metric_id.startswith("STR-"):
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
    value["exclusions"] = excluded + context_exclusions + value.get("series_exclusions", []) + [
        {"id": item["id"], "reason": "numeric_value_or_unit_unverified"} for item in numeric_audit if item["value"] is None]
    if numeric_audit:
        value["numeric_provenance"] = numeric_audit
        if any(item["value"] is None for item in numeric_audit):
            value["reason_codes"] = list(dict.fromkeys(value["reason_codes"] + ["numeric_value_or_unit_unverified"]))
    value["input_snapshot_n"] = len(relevant)
    value["input_available_n"] = len(selected)
    if metric_id == "STR-09":
        value["plan_status_provenance"] = plan_status_provenance
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
    def safe_evaluate(metric_id, **kwargs):
        try:
            return evaluate(metric_id, **kwargs)
        except (ValueError, TypeError, ArithmeticError) as exc:
            return result(metric_id, window, None, data_status="not_applicable", valid_n=0, total_n=0,
                          reasons=["metric_execution_failed"], error={"kind": type(exc).__name__, "message": str(exc)})
    output = {metric_id: safe_evaluate(metric_id, cutoff_time=cutoff_time, window_start=window_start,
                                  window_end=window_end, context=context, _normalized=normalized)
              for metric_id in definitions()}
    available, _ = select_as_of([r for r in normalized if r.get("record_kind", "strength_set") == "strength_set"],
                                window, retrospective=context.get("retrospective", False))
    groups, identities = {}, {}
    for row in available:
        if not row.get("is_reference"):
            continue
        task = analysis_task(row)
        identities[task["task_id"]] = task
        groups.setdefault(task["task_id"], []).append(row)
    for metric_id in TASK_METRICS:
        task_results = []
        for task_id, rows in groups.items():
            task_context = {**context, **context.get("task_contexts", {}).get(task_id, {}), "task_id": task_id}
            task_context["data_snapshot_hash"] = canonical_hash({"records": rows, "window": window.as_dict(), "cutoff_time": cutoff_time,
                                                                 "data_version": str(context.get("data_version"))})
            calculated = safe_evaluate(metric_id, cutoff_time=cutoff_time, window_start=window_start,
                                  window_end=window_end, context=task_context, _normalized=rows)
            task_results.append({**identities[task_id], "data_snapshot_hash": task_context["data_snapshot_hash"],
                                 "input_data_hash": canonical_hash(rows), "metric": calculated})
        if task_results:
            if metric_id == "STR-08":
                # The window-wide recorded-session frequency must retain
                # sessions that have no eligible reference measurement.
                output[metric_id]["task_results"] = task_results
                continue
            if len(task_results) == 1:
                output[metric_id] = {**task_results[0]["metric"], "task_results": task_results}
            else:
                item = output[metric_id]
                item.update(value={"tasks": [{k: v for k, v in task.items() if k != "metric"} | {
                    "value": task["metric"]["value"], "data_status": task["metric"]["data_status"],
                    "valid_n": task["metric"]["valid_n"], "reason_codes": task["metric"]["reason_codes"]} for task in task_results]},
                    task_results=task_results, data_status="valid" if all(task["metric"]["data_status"] == "valid" for task in task_results) else "partial",
                    valid_n=sum(task["metric"]["valid_n"] or 0 for task in task_results),
                    total_n=sum(task["metric"]["total_n"] or 0 for task in task_results),
                    reason_codes=["independent_action_condition_protocol_tasks"],
                    uncertainty={"kind": "not_estimated", "lower": None, "upper": None, "level": None, "assumptions": []})
    return output
