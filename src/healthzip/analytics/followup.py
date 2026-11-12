"""Descriptive candidate follow-up from the Repository's visible revisions."""

from decimal import Decimal

from healthzip.science.contracts import finite, instant
from healthzip.science.semantics import comparable, flatten_record, load_change, outcome_series
from healthzip.science.strength import reference_rows
from healthzip.training.followup import validate_frozen_window
from healthzip.training.semantics import LB_TO_KG

UNITS = {"reps": "repetitions", "rir": "RIR", "duration_s": "s", "distance_m": "m"}


def load_at_target_unit(row, change):
    """Convert only a declared mass unit; the recorded load convention stays fixed."""
    raw = finite(row.get("load_value"))
    source_unit, target_unit = row.get("load_unit"), change.get("load_unit")
    out = {"raw_value": raw, "raw_unit": source_unit, "value": None, "unit": target_unit,
           "conversion_id": None, "reason_codes": []}
    if raw is None:
        out["reason_codes"] = ["actual_load_missing"]
    elif source_unit == target_unit and source_unit in {"kg", "lb", "level", "stack_level"}:
        out.update(value=raw, conversion_id="identity")
    elif source_unit in {"kg", "lb"} and target_unit in {"kg", "lb"}:
        amount = Decimal(str(row["load_value"]))
        out.update(value=float(amount * LB_TO_KG if source_unit == "lb" else amount / LB_TO_KG),
                   conversion_id="international_avoirdupois:" + source_unit + "->" + target_unit)
    else:
        out["reason_codes"] = ["endpoint_units_incompatible_or_unknown"]
    return out


def observation(row):
    return {"record_id": row.get("set_uuid", row.get("set_id", row.get("id"))),
            "revision": row.get("revision"), "session_id": row.get("session_id"),
            "observed_at": row.get("ended_at") or row.get("_event_end"),
            "available_at": row.get("available_at"), "condition_key": row.get("condition_key"),
            "values": {key: finite(row.get(key)) for key in ("load_value", *UNITS)},
            "units": {"load_value": row.get("load_unit"), **UNITS}, "load_basis": row.get("load_basis"),
            "rir_interval": row.get("rir_interval"), "quality_status": row.get("quality_status"),
            "stop_reason": row.get("raw_stop_reason", row.get("stop_reason")), "pain_flag": row.get("pain_flag")}


def observed_change(before, after, *, fixed_load=False):
    allowed, reasons = comparable(before, after, protocol=True)
    a, b = outcome_series(before), outcome_series(after)
    if not a["eligible"] or not b["eligible"]:
        reasons += a["reason_codes"] + b["reason_codes"]
        allowed = False
    if fixed_load and a["outcome_series_id"] != b["outcome_series_id"]:
        reasons.append("different_fixed_load_outcome_series")
        allowed = False
    out = {"before": observation(before), "after": observation(after), "comparable": allowed,
           "reason_codes": sorted(set(reasons)), "differences": {}, "causal_effect": None}
    if allowed:
        out["load_change"] = load_change(before, after)
        for key, unit in UNITS.items():
            first, second = finite(before.get(key)), finite(after.get(key))
            out["differences"][key] = {"value": second - first if first is not None and second is not None else None,
                                        "unit": unit, "reason": None if first is not None and second is not None
                                        else "endpoint_missing_or_interval_censored"}
        out["interpretation"] = "observed_same_load_change" if fixed_load else "observed_task_change_not_capacity_gain"
    return out


def execution_details(targets, change, referenced, observed, *, quality_comparable, records, recommendation):
    rows = [observation(row) for row in referenced]
    comparisons = []
    for endpoint, target in targets.items():
        normalization = load_at_target_unit(observed, change) if endpoint == "load_value" else None
        actual = normalization["value"] if normalization else finite(observed.get(endpoint))
        unit = change.get("load_unit") if endpoint == "load_value" else UNITS.get(endpoint)
        actual_unit = normalization["unit"] if normalization and actual is not None else observed.get("load_unit") if endpoint == "load_value" else unit
        units_match = unit is not None and unit == actual_unit
        basis_matches = endpoint != "load_value" or change.get("load_basis") not in (None, "unknown") and change.get("load_basis") == observed.get("load_basis")
        arithmetic_allowed = units_match and basis_matches
        comparisons.append({"endpoint": endpoint, "target": target, "actual": actual,
            "target_unit": unit, "actual_unit": actual_unit,
            "load_normalization": normalization,
            "actual_interval": observed.get("rir_interval") if endpoint == "rir" else None,
            "target_load_basis": change.get("load_basis") if endpoint == "load_value" else None,
            "actual_load_basis": observed.get("load_basis") if endpoint == "load_value" else None,
            "actual_minus_min": actual - target["min"] if actual is not None and arithmetic_allowed else None,
            "actual_minus_max": actual - target["max"] if actual is not None and arithmetic_allowed else None,
            "within_target": target["min"] <= actual <= target["max"] if actual is not None and arithmetic_allowed else None,
            "quality_comparable": quality_comparable,
            "reason_codes": (["actual_endpoint_missing_or_interval_censored"] if actual is None else [])
                + ([] if units_match else ["endpoint_units_incompatible_or_unknown"])
                + ([] if basis_matches else ["load_basis_incompatible_or_unknown"])})
    baseline_id = recommendation["input_snapshot"].get("reference_set_id")
    baseline = next((flatten_record(row) for row in records if row.get("set_uuid") == baseline_id), None)
    if baseline:
        baseline["_event_end"] = baseline.get("ended_at")
        try:
            if (not reference_rows([baseline], {})
                    or instant(baseline["ended_at"]) > instant(recommendation["cutoff_time"])):
                baseline = None
        except (ValueError, KeyError):
            baseline = None
    observed_delta = observed_change(baseline, observed) if baseline and observed else None
    return {"target_comparisons": comparisons, "actual_observations": rows,
            "execution_change": observed_delta,
            "execution_change_reason_codes": [] if observed_delta else ["baseline_or_single_execution_reference_unavailable"]}


def followup_observations(recommendation, latest, records, anchor, *, cutoff_time):
    plan = recommendation["candidate"].get("followup_window")
    output = {"recommendation_id": recommendation["candidate_id"], "window": plan if isinstance(plan, dict) else None,
              "status": "not_planned", "reason_codes": [], "observations": [], "exclusions": [],
              "cutoff_time": cutoff_time, "causal_effect": None}
    if not isinstance(plan, dict):
        output["reason_codes"] = ["followup_window_not_predeclared"]
        return output
    try:
        validate_frozen_window(plan, created_at=recommendation["created_at"])
        start, end, cutoff = instant(plan["start"]), instant(plan["end"]), instant(cutoff_time)
    except (ValueError, KeyError):
        output.update(status="unavailable", reason_codes=["invalid_or_retrospective_followup_window"])
        return output
    output["window_complete"] = cutoff >= end
    state = latest.get("execution_state")
    if state != "executed":
        output.update(status="not_executed" if state == "not_executed" else "execution_unconfirmed",
                      reason_codes=["partial_execution" if state == "partially_executed" else "execution_not_confirmed"])
        return output
    if not anchor or not outcome_series(anchor)["eligible"]:
        output.update(status="unavailable", reason_codes=["comparable_execution_reference_required"])
        return output
    if cutoff < start:
        output.update(status="pending", reason_codes=["followup_window_not_started"])
        return output
    eligible = []
    for raw in records:
        if raw.get("record_kind") != "strength_set":
            continue
        row = flatten_record(raw)
        if row.get("exercise_id") != anchor.get("exercise_id"):
            continue
        try:
            occurred = instant(row.get("ended_at"))
            visible = instant(row.get("available_at"))
        except ValueError:
            continue  # Unknown-time rows cannot establish window membership.
        if not start <= occurred < end or occurred > cutoff or visible > cutoff:
            continue
        identity = row.get("set_uuid")
        reason = None
        if row.get("session_id") == anchor.get("session_id") or occurred <= instant(anchor["ended_at"]):
            reason = "execution_session_or_not_after_execution"
        elif row.get("conflicted") or row.get("deleted_at"):
            reason = "record_deleted_or_conflicted"
        if reason:
            output["exclusions"].append({"record_id": identity, "reason_codes": [reason]})
            continue
        row["_event_end"] = row["ended_at"]
        eligible.append(row)
    references = reference_rows(eligible, {})
    selected_ids = {row["set_uuid"] for row in references}
    for row in eligible:
        if row["set_uuid"] not in selected_ids:
            output["exclusions"].append({"record_id": row["set_uuid"], "reason_codes": ["unique_predeclared_completed_reference_required"]})
            continue
        comparison = observed_change(anchor, row, fixed_load=True)
        if comparison["comparable"]:
            output["observations"].append(comparison)
        else:
            output["exclusions"].append({"record_id": row["set_uuid"], "reason_codes": comparison["reason_codes"],
                                          "observed": comparison["after"]})
    output["status"] = "observed" if output["observations"] else "no_comparable_observation" if cutoff >= end else "pending"
    if not output["observations"]:
        output["reason_codes"] = ["visible_followup_records_ineligible" if output["exclusions"] else "no_followup_records_visible"]
        if cutoff < end:
            output["reason_codes"].append("followup_window_in_progress")
    return output
