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
    metric_ids,
    result,
    select_as_of,
    validate_result,
)
from .energy import energy_metric
from .evaluation import quality_metric
from .prediction import prediction_metric
from .reports import derive_report_context, report_comparison, report_metric, visible_sleep_history
from .semantics import _analysis_task, flatten_record, outcome_series
from .state import physiology_comparison, record_conditions, state_metric
from .strength import prepare_strength, reference_rows, strength_metric

TASK_METRICS = {f"STR-{number:02d}" for number in (7, 8, 11, 12, 13, 14, *range(16, 27))} | {"PRED-B0", "PRED-B1"}
SERIES_METRICS = {"STR-19", "STR-20", "STR-22", "STR-24"}
NUMERIC_TYPES = {name for name, unit in TYPE_MAP.values() if unit != "category"}


def _bounded_followup_outcome(record, cutoff_time):
    """Do not reuse later derived observations at an earlier analysis cutoff."""
    row = dict(record)
    cutoff = instant(cutoff_time)
    def future(observation):
        for key in ("observed_at", "available_at"):
            try:
                if observation.get(key) and instant(observation[key]) > cutoff:
                    return True
            except ValueError:
                return True
        return False
    if any(future(item) for item in row.get("actual_observations", [])):
        row.update(actual={}, actual_observations=[], target_comparisons=[], quality_comparable=None,
                   execution_change=None, execution_change_reason_codes=["execution_observation_after_analysis_cutoff"])
    change = row.get("execution_change")
    if change and any(future(change[part]) for part in ("before", "after")):
        row.update(execution_change=None, execution_change_reason_codes=["comparison_revision_after_analysis_cutoff"])
    followup = row.get("followup")
    if followup:
        try:
            later_snapshot = instant(followup.get("cutoff_time")) > cutoff
        except ValueError:
            later_snapshot = True
        later_observation = any(future(pair[part]) for pair in followup.get("observations", []) for part in ("before", "after"))
        if later_snapshot or later_observation:
            row["followup"] = {**followup, "observations": [], "exclusions": [], "status": "unavailable",
                "reason_codes": ["followup_snapshot_after_analysis_cutoff_or_unverified"], "cutoff_time": cutoff_time}
    return row


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


def _bounded_context(context, window):
    context = dict(context)
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
                row = {**_bounded_followup_outcome(record, window.cutoff_time), "source_record_id": record["recommendation_id"]}
            elif key == "sleep_episodes":
                # A declared sleep episode is one event, attributed by its end;
                # its original endpoints remain intact for midpoint arithmetic.
                row = {**record, "event_start": record.get("start"), "event_end": record.get("end")}
            source.append(flatten_record(row))
        query_window = window
        if key == "baseline_daily" and context.get("baseline_window"):
            bounds = context["baseline_window"]
            query_window = Window(bounds["start"], bounds["end"], window.cutoff_time, window.timezone)
        if key == "recommendation_outcomes":
            dates = [instant(window.start)]
            for row in source:
                try:
                    dates.append(instant(row.get("event_end")))
                except ValueError:
                    pass
            # A candidate created earlier can have a declared follow-up window
            # in this report. Preserve its actual timestamps and state exactly;
            # membership by planned overlap is explicit, never a synthetic event.
            query_window = Window(min(dates).isoformat(),
                max(instant(window.end), instant(window.cutoff_time) + timedelta(microseconds=1)).isoformat(), window.cutoff_time, window.timezone)
        context[key], rejected = select_as_of(source, query_window, retrospective=context.get("retrospective", False),
                                              overlap=key in {"energy_days", "daily_metric_facts"})
        if key == "recommendation_outcomes":
            included = []
            for row in context[key]:
                event_in_window = instant(window.start) <= instant(row["_event_end"]) < instant(window.end)
                plan = (row.get("followup") or {}).get("window") or {}
                try:
                    planned_overlap = instant(plan["start"]) < instant(window.end) and instant(plan["end"]) > instant(window.start)
                except (ValueError, KeyError):
                    planned_overlap = False
                if event_in_window or planned_overlap:
                    row["report_membership"] = "feedback_or_creation_in_window" if event_in_window else "predeclared_followup_overlap"
                    included.append(row)
            context[key] = included
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
        if not event or not available or instant(event) > instant(window.cutoff_time) or instant(available) > instant(window.cutoff_time):
            context[key] = None
            context_exclusions.append({"context": key, "reason": "observation_availability_unverified_or_future"})
    return context, context_exclusions


def evaluate(metric_id: str, records: Optional[list[dict]] = None, *, cutoff_time: str,
             window_start: str, window_end: str, context: Optional[dict] = None,
             _normalized: Optional[list[dict]] = None, _selection_cache=None, _context_bound=None) -> dict:
    if metric_id not in metric_ids():
        raise ValueError("unregistered_metric_id")
    context = dict(context or {})
    window = Window(window_start, window_end, cutoff_time, context.get("timezone", "UTC"))
    if _context_bound is None:
        context, context_exclusions = _bounded_context(context, window)
    else:
        context, context_exclusions = dict(_context_bound[0]), _context_bound[1]
    normalized = _normalized if _normalized is not None else [flatten_record(r) for r in records or []]
    if metric_id.startswith("REPORT-") or metric_id == "ENERGY-RECORD-COVERAGE":
        if "daily_metric_facts" not in context or "energy_days" not in context:
            report_rows, _ = select_as_of(normalized, window, retrospective=context.get("retrospective", False), overlap=True)
            derived = derive_report_context(report_rows, window, sleep_rows=visible_sleep_history(
                normalized, window, retrospective=context.get("retrospective", False)))
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
        if context.get("baseline_completed_days"):
            window = selection_window
    # Named first-work protocols locate their position before successful/time
    # filtering. Drafts without observation time still occupy their real slot.
    if metric_id.startswith("STR-") and "reference_inventory" not in context:
        context["reference_inventory"] = [row for row in relevant if row.get("available_at")
            and instant(row["available_at"]) <= instant(cutoff_time)]
    overlap = metric_id.startswith(("STATE-SLEEP-", "ENERGY-", "REPORT-"))
    # Only evaluate_all supplies this request-local cache for its one immutable
    # normalized snapshot. Equal record selections keep the same exclusions,
    # event boundaries, retrospective identity and source IDs.
    selection_key = (tuple(id(row) for row in relevant), selection_window.start, selection_window.end,
                     selection_window.cutoff_time, bool(context.get("retrospective", False)), overlap)
    if _selection_cache is not None and selection_key in _selection_cache:
        selected, excluded = _selection_cache[selection_key]
    else:
        selected, excluded = select_as_of(relevant, selection_window, retrospective=context.get("retrospective", False), overlap=overlap)
        if _selection_cache is not None:
            _selection_cache[selection_key] = selected, excluded
    plan_status_provenance = []
    if metric_id == "STR-09":
        states, plan_status_provenance = _undated_plan_states(relevant, window, context)
        selected = list(selected)
        selected.extend(states)
        retained_ids = {row["_source_id"] for row in states}
        excluded = [entry for entry in excluded if not (entry["id"] in retained_ids and entry["reason"] == "timestamp_required")]
    numeric_audit = [{"id": r.get("_source_id"), **quantity_value(r)} for r in selected
                     if r.get("canonical_type", r.get("metric_type")) in NUMERIC_TYPES]
    if metric_id in {"STR-19", "STR-20", "STR-22", "STR-24"}:
        derived_key = ("strength_snapshot", id(selected), window.start, window.end, str(context.get("data_version")))
        derived = _selection_cache.get(derived_key) if _selection_cache is not None else None
        if derived is None:
            digest = canonical_hash({"records": selected, "window": window.as_dict(), "cutoff_time": cutoff_time,
                                     "data_version": str(context.get("data_version"))})
            task_ids = {_analysis_task(row)["task_id"] for row in selected}
            derived = digest, next(iter(task_ids)) if len(task_ids) == 1 else None
            if _selection_cache is not None:
                _selection_cache[derived_key] = derived
        context["observed_snapshot_hash"], context["observed_task_id"] = derived
    if metric_id in SERIES_METRICS and not context.get("_series_evaluation"):
        value = _series_metric(metric_id, selected, window, context)
    elif metric_id.startswith("STR-"):
        prepared = None
        loads = None
        if _selection_cache is not None:
            prepared_key = ("strength_inputs", id(selected))
            if prepared_key not in _selection_cache:
                _selection_cache[prepared_key] = prepare_strength(selected, context)
            prepared = _selection_cache[prepared_key]
            if metric_id in {"STR-03", "STR-04", "STR-16", "STR-17"}:
                loads = _selection_cache.setdefault(("strength_loads", id(selected)), {})
        value = strength_metric(metric_id, selected, window, context, _prepared=prepared,
                                _normalized=True, _load_cache=loads)
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
    if metric_id == "STATE-SDNN":
        value["exclusions"].extend({"id": row.get("_source_id"),
            "reason": "SDNN_identifier_conflicts_with_recorded_metric_identity",
            "recorded_metric_identity": record_conditions(row)["metric_identity"]["value"]}
            for row in selected if str(record_conditions(row)["metric_identity"]["value"] or "SDNN").upper() != "SDNN")
    if numeric_audit:
        value["numeric_provenance"] = numeric_audit
        if any(item["value"] is None for item in numeric_audit):
            value["reason_codes"] = list(dict.fromkeys(value["reason_codes"] + ["numeric_value_or_unit_unverified"]))
    if metric_id in {"STATE-RHR", "STATE-SDNN", "REPORT-STATE-SUMMARY"}:
        options = {"previous": context.get("comparison_window"),
                   "baseline_days": context.get("baseline_days", 28),
                   "retrospective": context.get("retrospective", False)}
        value["comparison"] = (report_comparison(normalized, window, **options)
            if metric_id == "REPORT-STATE-SUMMARY" else physiology_comparison(
                relevant, "resting_heart_rate_bpm" if metric_id == "STATE-RHR" else "hrv_sdnn_ms", window, **options))
    value["input_snapshot_n"] = len(relevant)
    value["input_available_n"] = len(selected)
    if metric_id == "STR-09":
        value["plan_status_provenance"] = plan_status_provenance
    if any(r["reason"] == "unresolved_record_conflict" for r in excluded):
        value["reason_codes"].append("unresolved_input_conflict_excluded")
        value["data_status"] = "conflicted"
    validate_result(value, calibration=context.get("calibration"))
    return value


def evaluate_subset(metric_ids_to_compute, records, *, cutoff_time, window_start, window_end, context=None):
    """The same public metric executors with shared immutable input preparation."""
    context = dict(context or {})
    window = Window(window_start, window_end, cutoff_time, context.get("timezone", "UTC"))
    normalized = [flatten_record(row) for row in records]
    bounded = _bounded_context(context, window)
    selections = {}
    return {mid: evaluate(mid, cutoff_time=cutoff_time, window_start=window_start, window_end=window_end,
        context=context, _normalized=normalized, _context_bound=bounded, _selection_cache=selections)
        for mid in metric_ids_to_compute}


_REFERENCE_ATOMIC_TYPES = frozenset({type(None), bool, int, float, str})


def _clone_ordinary_reference_result(value, memo=None):
    """Clone this validated prototype without dispatching every JSON scalar.

    A per-copy memo preserves aliases while isolating nested mutable values.
    Only exact built-in dict/list/scalars take the fast path; tuples and any
    subclasses keep standard deepcopy semantics, including their own metadata.
    This is private to ordinary STR-11 absence results, not a MetricResult copier.
    """
    value_type = type(value)
    if value_type in _REFERENCE_ATOMIC_TYPES:
        return value
    if memo is None:
        memo = {}
    identity = id(value)
    if identity in memo:
        return memo[identity]
    if value_type is dict:
        cloned = {}
        memo[identity] = cloned
        for key, item in value.items():
            copied_key = key if type(key) in _REFERENCE_ATOMIC_TYPES else _clone_ordinary_reference_result(key, memo)
            cloned[copied_key] = item if type(item) in _REFERENCE_ATOMIC_TYPES else _clone_ordinary_reference_result(item, memo)
        return cloned
    if value_type is list:
        cloned = []
        memo[identity] = cloned
        cloned.extend(item if type(item) in _REFERENCE_ATOMIC_TYPES else _clone_ordinary_reference_result(item, memo)
                      for item in value)
        return cloned
    from copy import deepcopy

    return deepcopy(value, memo)


def _ordinary_reference_result(rows, window, context, bounded, templates):
    """Reuse the STR-11 absence result for already selected ordinary inventories.

    Only the repository analysis caller supplies these same-window, revision-
    resolved records and a fresh per-request template map. Reference eligibility
    still runs for every task; nominated or exceptional inputs keep the normal
    executor. Each public result owns its nested values and all source IDs.
    """
    def normal():
        return evaluate("STR-11", cutoff_time=window.cutoff_time, window_start=window.start,
                        window_end=window.end, context=context, _normalized=rows,
                        _context_bound=bounded)

    if (not rows or any(not row.get("_source_id") or not row.get("_event_end")
                        or row.get("record_kind", "strength_set") != "strength_set"
                        or row.get("canonical_type", row.get("metric_type")) in NUMERIC_TYPES for row in rows)):
        return normal()
    reference_context = dict(bounded[0])
    if "reference_inventory" not in reference_context:
        cutoff = instant(window.cutoff_time)
        reference_context["reference_inventory"] = [row for row in rows if row.get("available_at")
                                                    and instant(row["available_at"]) <= cutoff]
    if reference_rows(rows, reference_context):
        return normal()
    prototype = templates.get("no_designated_reference")
    if prototype is None:
        prototype = normal()
        if prototype["value"] is not None or prototype["reason_codes"] not in (
                ["predesignated_reference_missing"],
                ["predesignated_reference_missing", "retrospective_snapshot_not_prospective"]):
            return prototype
        templates["no_designated_reference"] = _clone_ordinary_reference_result(prototype)
        return prototype
    value = _clone_ordinary_reference_result(prototype)
    value.update(source_record_ids=sorted({str(row["_source_id"]) for row in rows}),
                 total_n=len(rows), input_snapshot_n=len(rows), input_available_n=len(rows),
                 n_sessions=len({row["session_id"] for row in rows if row.get("session_id") is not None}))
    value["reason_codes"] = ["predesignated_reference_missing"]
    if any(row.get("_retrospective_snapshot") for row in rows):
        value["reason_codes"].append("retrospective_snapshot_not_prospective")
    validate_result(value, calibration=context.get("calibration"))
    return value


def evaluate_all(records: Optional[list[dict]] = None, *, cutoff_time: str, window_start: str,
                 window_end: str, context: Optional[dict] = None, _normalized=None) -> dict[str, dict]:
    # Repository analysis may reuse the normalization prepared for its own
    # reference inventory. Public callers still prepare their raw inputs here.
    normalized = _normalized if _normalized is not None else [flatten_record(r) for r in records or []]
    context = dict(context or {})
    window = Window(window_start, window_end, cutoff_time, context.get("timezone", "UTC"))
    report_rows, _ = select_as_of(normalized, window, retrospective=context.get("retrospective", False), overlap=True)
    context = {**derive_report_context(report_rows, window, sleep_rows=visible_sleep_history(
        normalized, window, retrospective=context.get("retrospective", False))), **context}
    def safe_evaluate(metric_id, **kwargs):
        try:
            return evaluate(metric_id, **kwargs)
        except (ValueError, TypeError, ArithmeticError) as exc:
            return result(metric_id, window, None, data_status="not_applicable", valid_n=0, total_n=0,
                          reasons=["metric_execution_failed"], error={"kind": type(exc).__name__, "message": str(exc)})
    selection_cache = {}
    try:
        bounded = _bounded_context(context, window)
    except (ValueError, TypeError, ArithmeticError):
        # Retain per-metric failure results for malformed optional context.
        bounded = None
    output = {metric_id: safe_evaluate(metric_id, cutoff_time=cutoff_time, window_start=window_start,
                                  window_end=window_end, context=context, _normalized=normalized, _selection_cache=selection_cache, _context_bound=bounded)
              for metric_id in definitions()}
    available, _ = select_as_of([r for r in normalized if r.get("record_kind", "strength_set") == "strength_set"],
                                window, retrospective=context.get("retrospective", False))
    groups, identities = {}, {}
    for row in available:
        if not row.get("is_reference"):
            continue
        task = _analysis_task(row)
        identities[task["task_id"]] = task
        groups.setdefault(task["task_id"], []).append(row)
    prepared_tasks = {}
    if groups:
        cutoff = instant(cutoff_time)
        inventory = [row for row in normalized if row.get("available_at") and instant(row["available_at"]) <= cutoff]
        for task_id, rows in groups.items():
            task_context = {**context, **context.get("task_contexts", {}).get(task_id, {}),
                "task_id": task_id, "reference_inventory": inventory}
            task_context["data_snapshot_hash"] = canonical_hash({"records": rows, "window": window.as_dict(),
                "cutoff_time": cutoff_time, "data_version": str(context.get("data_version"))})
            try:
                task_bound = _bounded_context(task_context, window)
            except (ValueError, TypeError, ArithmeticError):
                task_bound = None  # safe_evaluate retains each metric's prior failure contract.
            prepared_tasks[task_id] = (task_context, task_bound, {}, canonical_hash(rows))
    for metric_id in TASK_METRICS:
        task_results = []
        for task_id, rows in groups.items():
            task_context, task_bound, selections, input_hash = prepared_tasks[task_id]
            calculated = safe_evaluate(metric_id, cutoff_time=cutoff_time, window_start=window_start,
                                  window_end=window_end, context=task_context, _normalized=rows,
                                  _context_bound=task_bound, _selection_cache=selections)
            task_results.append({**identities[task_id], "data_snapshot_hash": task_context["data_snapshot_hash"],
                                 "input_data_hash": input_hash, "metric": calculated})
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
