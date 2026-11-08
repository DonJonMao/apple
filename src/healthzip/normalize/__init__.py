"""Canonical types, timestamps and unit normalization."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

TYPE_MAP = {
    "HKQuantityTypeIdentifierHeartRate": ("heart_rate_bpm", "count/min"),
    "HKQuantityTypeIdentifierRestingHeartRate": ("resting_heart_rate_bpm", "count/min"),
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": ("hrv_sdnn_ms", "ms"),
    "HKQuantityTypeIdentifierHeartRateRecoveryOneMinute": ("heart_rate_recovery_1m", None),
    "HKQuantityTypeIdentifierVO2Max": ("vo2_max_ml_kg_min", "mL/(kg·min)"),
    "HKQuantityTypeIdentifierRespiratoryRate": ("respiratory_rate_bpm", "count/min"),
    "HKQuantityTypeIdentifierOxygenSaturation": ("oxygen_saturation_fraction", "fraction"),
    "HKQuantityTypeIdentifierAppleSleepingWristTemperature": (
        "sleeping_wrist_temperature_c",
        "degC",
    ),
    "HKCategoryTypeIdentifierSleepAnalysis": ("sleep_stage", "category"),
    "HKQuantityTypeIdentifierStepCount": ("steps", "count"),
    "HKQuantityTypeIdentifierActiveEnergyBurned": ("active_energy_kcal", "kcal"),
    "HKQuantityTypeIdentifierBasalEnergyBurned": ("basal_energy_kcal", "kcal"),
    "HKQuantityTypeIdentifierAppleExerciseTime": ("exercise_minutes", "min"),
    "HKQuantityTypeIdentifierDistanceWalkingRunning": ("distance_walking_running_m", "m"),
    "HKQuantityTypeIdentifierDistanceCycling": ("distance_cycling_m", "m"),
    "HKQuantityTypeIdentifierBodyMass": ("body_mass_kg", "kg"),
    "HKQuantityTypeIdentifierHeight": ("height_cm", "cm"),
    "HKQuantityTypeIdentifierBodyFatPercentage": ("body_fat_fraction", "fraction"),
    "HKQuantityTypeIdentifierLeanBodyMass": ("lean_body_mass_kg", "kg"),
    "HKQuantityTypeIdentifierDietaryEnergyConsumed": ("dietary_energy_kcal", "kcal"),
    "HKQuantityTypeIdentifierDietaryProtein": ("dietary_protein_g", "g"),
    "HKQuantityTypeIdentifierDietaryCarbohydrates": ("dietary_carbohydrates_g", "g"),
    "HKQuantityTypeIdentifierDietaryFatTotal": ("dietary_fat_g", "g"),
    "HKQuantityTypeIdentifierDietaryWater": ("dietary_water_ml", "mL"),
    "HKQuantityTypeIdentifierDietaryCaffeine": ("dietary_caffeine_mg", "mg"),
    "HKCategoryTypeIdentifierMenstrualFlow": ("menstrual_flow", "category"),
    "HKCategoryTypeIdentifierIntermenstrualBleeding": ("intermenstrual_bleeding", "category"),
    "HKCategoryTypeIdentifierCervicalMucusQuality": ("cervical_mucus_quality", "category"),
    "HKCategoryTypeIdentifierOvulationTestResult": ("ovulation_test_result", "category"),
    "HKCategoryTypeIdentifierMenstrualCramps": ("menstrual_cramps", "category"),
}
SLEEP_VALUES = {
    "HKCategoryValueSleepAnalysisAsleep": "asleep",
    "HKCategoryValueSleepAnalysisAsleepCore": "core",
    "HKCategoryValueSleepAnalysisAsleepDeep": "deep",
    "HKCategoryValueSleepAnalysisAsleepREM": "rem",
    "HKCategoryValueSleepAnalysisAwake": "awake",
    "HKCategoryValueSleepAnalysisInBed": "in_bed",
}


def canonical_type(raw_type: str) -> Optional[str]:
    if raw_type in TYPE_MAP:
        return TYPE_MAP[raw_type][0]
    for key, (name, _) in TYPE_MAP.items():
        if raw_type.endswith(key):
            return name
    return None


def parse_apple_datetime(
    value: Optional[str],
) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[str]]:
    if not value:
        return None, None, None, None
    text = value.strip().replace("Z", "+00:00")
    if re.search(r"[+-]\d{4}$", text):
        text = text[:-5] + text[-5:-2] + ":" + text[-2:]
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None, None, None, None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    offset_obj = dt.utcoffset()
    offset = int(offset_obj.total_seconds() // 60) if offset_obj else 0
    utc = dt.astimezone(timezone.utc)
    return utc.isoformat().replace("+00:00", "Z"), dt.isoformat(), offset, dt.date().isoformat()


def parse_number(value: Any) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def normalize_value(
    raw_type: str, value: Any, unit: Optional[str]
) -> Tuple[Optional[float], Optional[str], str]:
    canonical_tuple = TYPE_MAP.get(raw_type)
    canonical = canonical_tuple[0] if canonical_tuple else None
    target = canonical_tuple[1] if canonical_tuple else None
    number = parse_number(value)
    if number is None or canonical is None:
        return number, target or unit, "unknown" if canonical is None or number is None else "known"
    u = (unit or "").strip().lower()
    if canonical in {"body_mass_kg", "lean_body_mass_kg"} and u in {"lb", "lbs", "pound", "pounds"}:
        return number * 0.45359237, "kg", "converted"
    if canonical == "height_cm" and u in {"m", "meter", "metre"}:
        return number * 100, "cm", "converted"
    if canonical.startswith("distance_") and u in {"km", "kilometer", "kilometre"}:
        return number * 1000, "m", "converted"
    if canonical == "dietary_energy_kcal" and u in {"kj", "kilojoule", "kilojoules"}:
        return number / 4.184, "kcal", "converted"
    if canonical in {"oxygen_saturation_fraction", "body_fat_fraction"} and (
        u in {"%", "percent", "percentage"} or number > 1
    ):
        return number / 100, "fraction", "converted"
    if canonical == "sleeping_wrist_temperature_c" and u in {"f", "degf", "°f"}:
        return (number - 32) * 5 / 9, "degC", "converted"
    if canonical == "exercise_minutes" and u in {"s", "sec", "seconds"}:
        return number / 60, "min", "converted"
    if canonical == "vo2_max_ml_kg_min" and u in {"ml/min·kg", "ml/(kg·min)", "ml/kg/min"}:
        return number, "mL/(kg·min)", "known"
    if target and u and u != target.lower():
        return number, target, "unit_unverified"
    return number, target or unit, "known"


def stable_fingerprint(parts: Any) -> str:
    if not isinstance(parts, (list, tuple)):
        parts = [parts]
    encoded = json.dumps(
        list(parts), ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
