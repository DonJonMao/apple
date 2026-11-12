"""Bind user-selected historical tasks to the existing ratio and B0 calculators."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from healthzip.normalize import quantity_value
from healthzip.science import evaluate
from healthzip.science.contracts import Window, instant, select_as_of, validate_result
from healthzip.science.semantics import (
    PROTOCOL_FIELDS,
    analysis_task,
    flatten_record,
    load_components,
    outcome_series,
)
from healthzip.science.strength import reference_rows

VERSION = "repository-reference-selection-1.4.0"

# A repeat intent contains only condition/protocol/load declarations. Copying an
# observed row wholesale risks reintroducing outcomes through nested snapshots.
TARGET_FIELDS = {
    "user_id", "exercise_id", "variant_id", "definition_version", "equipment_instance_id",
    "load_basis", "load_basis_confirmed", "side", "repetition_semantics", "rom_protocol",
    "settings", "settings_confirmed", "measurement_mode", "symmetric_loading", "implement_count",
    "effective_bar_mass_kg", "assistance_method", "reference_protocol", "load_value", "load_unit",
    "observation_segment", *PROTOCOL_FIELDS,
}


def _local_date(row, window):
    return instant(row["_event_end"]).astimezone(ZoneInfo(window.timezone)).date().isoformat()


def _inputs(records, window):
    # Even a retrospective report cannot backdate previously unavailable inputs
    # into a predictive reference. Unknown visibility therefore stays excluded.
    strength, _ = select_as_of([flatten_record(row) for row in records
                               if row.get("record_kind") == "strength_set"], window)
    references = [row for row in reference_rows(strength, {})
                  if outcome_series(row)["eligible"]
                  and instant(row["_event_end"]) < instant(window.cutoff_time)]
    masses, _ = select_as_of([row for row in records if row.get("canonical_type") == "body_mass_kg"], window)
    masses = [row for row in masses if quantity_value(row)["unit"] == "kg"
              and quantity_value(row)["value"] is not None and quantity_value(row)["value"] > 0]
    return references, masses


def _reference_metadata(row, window):
    task, series, load = analysis_task(row), outcome_series(row), load_components(row)
    return {"record_id": row["_source_id"], "task_id": task["task_id"], "exercise_name": task["exercise_name"],
            "condition_key": task["condition_key"], "protocol": task["protocol"],
            "definition_version": row.get("definition_version"), "outcome_series_id": series["outcome_series_id"],
            "observed_at": row["_event_end"], "available_at": row.get("available_at"),
            "local_date": _local_date(row, window), "load": load, "reps": row["reps"],
            "rir": row.get("rir"), "rir_interval": row.get("rir_interval"),
            "source_name": row.get("source_name") or row.get("source") or "local_training_record"}


def reference_options(records: list[dict], window: Window) -> dict:
    references, masses = _inputs(records, window)
    return {"adapter_version": VERSION, "references": [_reference_metadata(row, window) for row in references],
            "body_mass": [{"record_id": row["_source_id"], "observed_at": row["_event_end"],
                "available_at": row.get("available_at"), "local_date": _local_date(row, window),
                "source_name": row.get("source_name"), "normalization": quantity_value(row)} for row in masses],
            "mass_matching_policy": "same_local_calendar_day_and_explicit_user_confirmation",
            "matching_policy_kind": "product_alignment_not_physiological_equivalence"}


def selected_reference_metrics(records: list[dict], window: Window, selection: dict, *, data_version) -> tuple[dict, dict]:
    """Resolve IDs afresh; no user-supplied numerator/target can replace source facts."""
    references, masses = _inputs(records, window)
    audit = {"adapter_version": VERSION, "selection": dict(selection), "reason_codes": [],
             "cutoff_time": window.cutoff_time, "target_intent": "repeat_selected_condition_protocol_and_load",
             "matching_policy_kind": "product_alignment_not_physiological_equivalence"}
    reference = next((row for row in references if row["_source_id"] == selection.get("reference_record_id")
                      and analysis_task(row)["task_id"] == selection.get("task_id")), None)
    context = {"timezone": window.timezone, "data_version": data_version}
    selected_rows, history = [], []
    if reference is None:
        audit["reason_codes"].append("reference_record_unavailable_or_ineligible")
    else:
        selected_rows = [reference]
        metadata = _reference_metadata(reference, window)
        audit["reference"] = metadata
        series_id = metadata["outcome_series_id"]
        history = [row for row in references if outcome_series(row)["outcome_series_id"] == series_id]
        # Only task/condition/load attributes define the intended repeat. Actual
        # repetitions, effort and completion are never copied into a future fact.
        target = {key: reference[key] for key in TARGET_FIELDS if key in reference}
        target.update(is_reference=False, reference_set=False, prediction_cutoff_time=window.cutoff_time)
        context["prediction_target"] = target
        total = metadata["load"]["total_load_kg"]
        context.update(strength_numerator=total, strength_numerator_unit="kg", complete_load_known=total is not None,
                       strength_numerator_identity="observed_complete_external_load", numerator_evidence_status="descriptive")
        if total is None:
            audit["reason_codes"].append("complete_external_load_unknown")
        mass = next((row for row in masses if row["_source_id"] == selection.get("body_mass_record_id")), None)
        if mass is None:
            audit["reason_codes"].append("body_mass_record_unavailable_or_unverified")
        elif _local_date(mass, window) != _local_date(reference, window):
            audit["reason_codes"].append("body_mass_local_date_mismatch")
        elif selection.get("body_mass_matches_reference") is not True:
            audit["reason_codes"].append("body_mass_match_not_confirmed")
        else:
            context["body_mass_observation"] = mass
            audit["body_mass"] = {"record_id": mass["_source_id"], "observed_at": mass["_event_end"],
                "available_at": mass.get("available_at"), "local_date": _local_date(mass, window),
                "source_name": mass.get("source_name"), "normalization": quantity_value(mass)}
    arguments = {"cutoff_time": window.cutoff_time, "window_start": window.start,
                 "window_end": window.end, "context": context}
    ratio = evaluate("STR-30", selected_rows, **arguments)
    b0 = evaluate("PRED-B0", history, **arguments)
    ratio.update(count_domain="selected_reference_mass_pairs", valid_n=int(ratio["value"] is not None),
                 total_n=int(reference is not None), selection_binding=audit)
    ratio["excluded_n"] = ratio["total_n"] - ratio["valid_n"]
    ratio["coverage"] = [{"kind": "selected_reference_mass_pairs", "numerator": ratio["valid_n"],
        "denominator": ratio["total_n"],
        "definition": "Eligible selected references with complete external load and explicitly confirmed same-local-date mass"}]
    ratio["reason_codes"] = list(dict.fromkeys(ratio["reason_codes"] + audit["reason_codes"]))
    if ratio["value"] is not None:
        ratio["source_record_ids"] = sorted([reference["_source_id"], context["body_mass_observation"]["_source_id"]])
    b0["selection_binding"] = {key: value for key, value in audit.items() if key not in {"body_mass", "reason_codes"}}
    b0["count_domain"] = "strictly_comparable_historical_references"
    if b0["value"] is not None:
        previous = next(row for row in history if row["id"] == b0["value"]["reference_id"])
        b0["value"]["previous_rir_interval"] = previous.get("rir_interval")
        b0["value"]["reference_observed_at"] = previous["_event_end"]
        b0["value"]["reference_available_at"] = previous.get("available_at")
    else:
        b0["valid_n"] = 0
    b0["excluded_n"] = b0["total_n"] - b0["valid_n"]
    b0["coverage"] = [{"kind": "strictly_comparable_historical_references", "numerator": b0["valid_n"],
        "denominator": b0["total_n"], "definition": "Visible eligible references matching the selected task, protocol and normalized load"}]
    for metric in (ratio, b0):
        validate_result(metric)
    return {"STR-30": ratio, "PRED-B0": b0}, audit
