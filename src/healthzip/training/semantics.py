"""Explicit physical recording conventions; no inferred force or physiology."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

LOAD_BASES = {
    "unknown",
    "external_total_kg",
    "plates_per_side_kg",
    "per_dumbbell_kg",
    "dumbbells_total_kg",
    "single_implement_kg",
    "machine_setting",
    "bodyweight_no_external",
    "added_load_kg",
    "assistance_setting",
    "band_configuration",
}
MEASUREMENT_MODES = {"repetitions", "duration", "distance"}
LB_TO_KG = Decimal("0.45359237")  # International avoirdupois definition, not a model parameter.


class TrainingError(ValueError):
    """Recoverable input or identity error suitable for a field-level UI message."""


def json_text(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def timestamp(value: Optional[str] = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise TrainingError("时间必须是带时区的 ISO 8601 时间") from exc
    if parsed.tzinfo is None:
        raise TrainingError("时间缺少时区")
    return parsed.isoformat()


def numeric(value: Any, field: str, *, integer: bool = False) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise TrainingError(f"{field} 不能是布尔值")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise TrainingError(f"{field} 必须是数值") from exc
    if not number.is_finite() or number < 0:
        raise TrainingError(f"{field} 必须是有限非负数")
    if integer and number != number.to_integral_value():
        raise TrainingError(f"{field} 必须是整数")
    return int(number) if integer else float(number)


def load_semantics(value: Any, unit: Optional[str], basis: Optional[str], **conditions) -> dict:
    """Return only quantities justified by the explicitly recorded convention.

    Per-side plate mass does not become total system mass without symmetric
    loading and a known effective bar mass. Machine labels stay machine labels.
    """
    basis = basis or "unknown"
    if basis not in LOAD_BASES:
        raise TrainingError(f"未知负荷口径: {basis}")
    amount = numeric(value, "load_value")
    if amount is not None and unit not in {"kg", "lb", "stack_level", "level"}:
        raise TrainingError("负荷必须明确 kg/lb/stack_level/level 单位")
    if amount is not None and basis.endswith("_kg") and unit not in {"kg", "lb"}:
        raise TrainingError("质量口径必须使用 kg 或 lb")
    kg = None if amount is None or unit not in {"kg", "lb"} else Decimal(str(value))
    if kg is not None and unit == "lb":
        kg *= LB_TO_KG
    out = {
        "raw_value": None if amount is None else str(value),
        "raw_unit": unit,
        "load_basis": basis,
        "normalized_recorded_kg": float(kg) if kg is not None else None,
        "external_total_kg": None,
        "plates_total_kg": None,
        "implements_mass_sum_kg": None,
        "task_difficulty_direction": "decreasing_assistance"
        if basis == "assistance_setting"
        else (
            "unknown" if basis in {"unknown", "band_configuration"} else "increasing_recorded_load"
        ),
        "status": "unknown" if basis == "unknown" else "recorded",
    }
    if kg is None:
        return out
    if basis in {"external_total_kg", "dumbbells_total_kg", "single_implement_kg"}:
        out["external_total_kg"] = float(kg)
    elif basis == "plates_per_side_kg" and conditions.get("symmetric_loading") is True:
        out["plates_total_kg"] = float(kg * 2)
        bar = conditions.get("effective_bar_mass_kg")
        if bar is not None:
            out["external_total_kg"] = float(
                kg * 2 + Decimal(str(numeric(bar, "effective_bar_mass_kg")))
            )
    elif basis == "per_dumbbell_kg" and conditions.get("implement_count") is not None:
        count = numeric(conditions["implement_count"], "implement_count", integer=True)
        if count < 1:
            raise TrainingError("器具数量必须是正整数")
        # This is inventory mass bookkeeping, not force or barbell equivalence.
        out["implements_mass_sum_kg"] = float(kg * count)
    # Per-dumbbell effective resistance, added load, body mass and assistance stay independent.
    return out


def load_change(before: dict, after: dict, condition: dict) -> dict:
    basis = condition.get("load_basis", "unknown")
    a = load_semantics(
        before.get("load_value"),
        before.get("load_unit"),
        basis,
        **{k: v for k, v in condition.items() if k != "load_basis"},
    )
    b = load_semantics(
        after.get("load_value"),
        after.get("load_unit"),
        basis,
        **{k: v for k, v in condition.items() if k != "load_basis"},
    )
    delta = None
    unit = before.get("load_unit")
    if a["normalized_recorded_kg"] is not None and b["normalized_recorded_kg"] is not None:
        delta = b["normalized_recorded_kg"] - a["normalized_recorded_kg"]
        unit = "kg"
    elif before.get("load_unit") == after.get("load_unit"):
        x, y = (
            numeric(before.get("load_value"), "load_value"),
            numeric(after.get("load_value"), "load_value"),
        )
        delta = y - x if x is not None and y is not None else None
    plates_delta = None
    if a["plates_total_kg"] is not None and b["plates_total_kg"] is not None:
        plates_delta = b["plates_total_kg"] - a["plates_total_kg"]
    total_delta = None
    if a["external_total_kg"] is not None and b["external_total_kg"] is not None:
        total_delta = b["external_total_kg"] - a["external_total_kg"]
    return {
        "recorded_change": delta,
        "recorded_unit": unit,
        "plates_total_change_kg": plates_delta,
        "external_total_change_kg": total_delta,
        "external_total_percent_change": (
            100 * total_delta / a["external_total_kg"]
            if total_delta is not None and a["external_total_kg"]
            else None
        ),
        "task_direction": ("harder" if delta < 0 else "easier" if delta > 0 else "unchanged")
        if basis == "assistance_setting" and delta is not None
        else "not_inferred",
    }


def condition_snapshot(exercise: dict, condition: dict, user_id: str) -> dict:
    result = dict(condition)
    protocol = result.get("reference_protocol")
    if isinstance(protocol, str):
        # A legacy note does not establish a complete measurement protocol.
        result.setdefault("reference_protocol_note", protocol)
        result["reference_protocol"] = None
    elif protocol is not None:
        if not isinstance(protocol, dict):
            raise TrainingError("参考协议必须是结构化定义，说明文本请填备注")
        keys = {
            "protocol_id",
            "version",
            "reference_policy_id",
            "effort_protocol",
            "tempo",
            "rest_protocol",
        }
        if set(protocol) - keys or any(
            value is not None and not isinstance(value, str) for value in protocol.values()
        ):
            raise TrainingError("参考协议字段须为明确文字或未知")
        result["reference_protocol"] = {
            key: (protocol.get(key) or "").strip() or None for key in sorted(keys)
        }
    result.update(
        user_id=user_id,
        exercise_id=exercise["exercise_id"],
        definition_version=exercise["definition_version"],
        measurement_mode=exercise["recording_mode"],
    )
    result["load_basis"] = result.get("load_basis") or "unknown"
    if result["load_basis"] not in LOAD_BASES:
        raise TrainingError("负荷口径不合法")
    if result.get("load_basis_confirmed") is not True and result["load_basis"] != "unknown":
        raise TrainingError("请明确确认负荷输入口径")
    required = ["equipment_instance_id", "side", "repetition_semantics", "rom_protocol"]
    missing = [key for key in required if result.get(key) in (None, "", "unknown")]
    if result["load_basis"] == "unknown":
        missing.append("load_basis")
    if result.get("settings_confirmed") is not True:
        missing.append("mechanically_relevant_settings")
    result["missing_comparability_fields"] = missing
    result["comparability_status"] = "user_confirmed" if not missing else "comparability_unknown"
    # Exclude goals/context/labels. A rename cannot alter a physical condition.
    key_fields = {
        key: result.get(key)
        for key in (
            "user_id",
            "exercise_id",
            "variant_id",
            "definition_version",
            "equipment_instance_id",
            "load_basis",
            "side",
            "repetition_semantics",
            "rom_protocol",
            "settings",
            "measurement_mode",
            "symmetric_loading",
            "implement_count",
            "effective_bar_mass_kg",
            "assistance_method",
            "reference_protocol",
        )
    }
    result["condition_key"] = (
        hashlib.sha256(json_text(key_fields).encode()).hexdigest() if not missing else None
    )
    return result
