"""Science adapters for the single training load and condition vocabulary."""
from __future__ import annotations

import json
from typing import Optional

from healthzip.training.semantics import (
    LOAD_BASES,
    TrainingError,
    condition_snapshot,
    load_semantics,
)
from healthzip.training.semantics import load_change as training_load_change

LEGACY_LOAD_ALIASES = {
    "barbell_total": "external_total_kg", "external_total": "external_total_kg",
    "bilateral_plates_per_side": "plates_per_side_kg", "per_side": "plates_per_side_kg",
    "dumbbell_per_hand": "per_dumbbell_kg", "per_hand": "per_dumbbell_kg",
    "stack_marked": "machine_setting", "bodyweight": "bodyweight_no_external",
    "bodyweight_added": "added_load_kg", "assistance_positive": "assistance_setting",
}


def flatten_record(record: dict) -> dict:
    row = dict(record)
    for key in ("condition_json", "actual_json"):
        value = row.get(key)
        if isinstance(value, str):
            value = json.loads(value)
        if isinstance(value, dict):
            row.update(value)
    for key in ("condition", "actual"):
        if isinstance(row.get(key), dict):
            row.update(row[key])
    row["ingestion_status"] = row.get("status")
    row["status"] = row.get("completion_state") if row.get("completion_state") is not None else row.get("status")
    row["role"] = row.get("role", row.get("set_type"))
    row["parent_set_id"] = row.get("parent_set_id", row.get("parent_set_uuid"))
    row["set_id"] = row.get("set_id", row.get("set_uuid", row.get("id")))
    row["is_reference"] = row.get("is_reference", row.get("reference_set") == 1)
    row["set_position"] = row.get("set_position", row.get("set_number"))
    row["set_structure"] = row.get("set_structure", row.get("relation_kind", "straight"))
    row["raw_stop_reason"] = row.get("stop_reason")
    row["stop_reason"] = {"plan_target": "planned_stop", "target_rir": "target_rir_stop"}.get(row.get("stop_reason"), row.get("stop_reason"))
    if row.get("rir_qualifier") == "at_least" and row.get("rir") is not None:
        row["rir_interval"] = {"lower": row["rir"], "upper": None}
        row["rir"] = None
    row["scale_type"] = row.get("scale_type", {"rir_rpe10": "rir_based_rpe_6_10"}.get(row.get("rpe_scale"), row.get("rpe_scale")))
    if isinstance(row.get("reference_protocol"), dict):
        protocol = row["reference_protocol"]
        for key in ("reference_policy_id", "effort_protocol", "tempo", "rest_protocol"):
            row[key] = row.get(key, protocol.get(key))
    raw = row.get("load_basis", row.get("load_mode", row.get("load_convention")))
    row["load_basis"] = raw if raw in LOAD_BASES else LEGACY_LOAD_ALIASES.get(raw, "unknown")
    row["legacy_raw_load_basis"] = raw
    row["load_value"] = row.get("load_value", row.get("entered_load", row.get("weight_kg")))
    row["load_unit"] = row.get("load_unit", row.get("unit", "kg" if "weight_kg" in row else None))
    row["entered_load"] = row["load_value"]
    row["quality"] = row.get("quality", row.get("quality_status"))
    row["unit"] = row["load_unit"]
    mode = row.get("measurement_mode")
    row["measurement_mode"] = {"dynamic_reps": "repetitions", "isometric_hold": "duration", "distance_carry": "distance"}.get(mode, mode)
    return row


def load_basis(record: dict) -> str:
    return flatten_record(record)["load_basis"]


def condition_key(record: dict) -> Optional[str]:
    row = flatten_record(record)
    if not row.get("exercise_id") or not row.get("definition_version") or not row.get("user_id"):
        return None
    try:
        snapshot = condition_snapshot({"exercise_id": row["exercise_id"], "definition_version": row["definition_version"],
                                       "recording_mode": row.get("measurement_mode")}, row, row["user_id"])
    except TrainingError:
        return None
    return snapshot["condition_key"]


def comparable(first: dict, second: dict, *, protocol: bool = False) -> tuple[bool, list[str]]:
    a, b = condition_key(first), condition_key(second)
    if a is None or b is None:
        return False, ["comparability_unknown"]
    if a != b:
        return False, ["physical_condition_changed"]
    if protocol:
        keys = ("reference_policy_id", "set_position", "effort_protocol", "tempo", "rest_protocol")
        if any(first.get(k) is None or second.get(k) is None for k in keys):
            return False, ["protocol_unknown"]
        if any(first[k] != second[k] for k in keys):
            return False, ["protocol_changed"]
    return True, []


def load_components(record: dict) -> dict:
    row = flatten_record(record)
    basis = row["load_basis"]
    out = {"entered_load": row["load_value"], "entered_unit": row["load_unit"], "load_basis": basis,
           "normalized_kg": None, "plate_total_kg": None, "total_load_kg": None,
           "per_hand_kg": None, "implements_mass_sum_kg": None, "assistance_kg": None, "marked_load": None, "reason_codes": []}
    try:
        parsed = load_semantics(row["load_value"], row["load_unit"], basis,
                                **{k: v for k, v in row.items() if k not in {"load_basis", "value", "unit", "basis"}})
    except TrainingError as exc:
        out["reason_codes"] = [str(exc)]
        return out
    out.update(normalized_kg=parsed["normalized_recorded_kg"], plate_total_kg=parsed["plates_total_kg"],
               total_load_kg=parsed["external_total_kg"], implements_mass_sum_kg=parsed.get("implements_mass_sum_kg"))
    if basis == "per_dumbbell_kg":
        out["per_hand_kg"] = out["normalized_kg"]
    elif basis == "assistance_setting":
        out["assistance_kg"] = out["normalized_kg"]
        out["reason_codes"].append("larger_value_means_more_assistance")
    elif basis == "machine_setting":
        out["marked_load"] = float(row["load_value"]) if row["load_value"] is not None else None
        out["reason_codes"].append("machine_mark_not_mechanical_resistance")
    elif basis == "plates_per_side_kg" and out["total_load_kg"] is None:
        out["reason_codes"].append("bar_mass_or_symmetric_loading_unknown")
    elif basis in {"unknown", "bodyweight_no_external", "added_load_kg", "band_configuration"}:
        out["reason_codes"].append("total_effective_resistance_unknown")
    if row["load_value"] is None:
        out["reason_codes"].append("load_missing")
    return out


def load_change(first: dict, second: dict) -> dict:
    old, new = flatten_record(first), flatten_record(second)
    ok, reasons = comparable(old, new)
    if not ok:
        return {"reason_codes": reasons, "entered_change": None, "plate_total_change_kg": None,
                "total_load_change_kg": None, "total_load_change_percent": None, "direction": None}
    change = training_load_change(old, new, {k: v for k, v in old.items() if k not in {"unit", "value", "basis"}})
    return {"entered_change": change["recorded_change"], "plate_total_change_kg": change["plates_total_change_kg"],
            "total_load_change_kg": change["external_total_change_kg"],
            "total_load_change_percent": change["external_total_percent_change"],
            "direction": change["task_direction"], "reason_codes": []}
