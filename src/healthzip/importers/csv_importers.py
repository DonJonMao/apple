"""Validated CSV imports for user-maintained strength, nutrition and logs."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Optional, Union

from healthzip.db.repository import Repository
from healthzip.normalize import parse_number, stable_fingerprint


class CSVImportError(ValueError):
    pass


def _read(path: Union[str, Path]) -> tuple[list[dict[str, str]], list[str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise CSVImportError("CSV is missing a header")
        return list(reader), [x.strip() for x in reader.fieldnames]


def _required(fields: list[str], required: set[str]) -> None:
    missing = sorted(required - set(fields))
    if missing:
        raise CSVImportError("missing columns: " + ", ".join(missing))


def _bool(value: Optional[str]) -> int:
    if value is None or value.strip() == "":
        return 0
    if value.strip().lower() in {"1", "true", "yes", "y", "是"}:
        return 1
    if value.strip().lower() in {"0", "false", "no", "n", "否"}:
        return 0
    raise CSVImportError("invalid boolean: " + value)


def import_strength_csv(path: Union[str, Path], repo: Repository) -> dict[str, Any]:
    rows, fields = _read(path)
    _required(fields, {"reps"})
    if not ({"date", "datetime"} & set(fields)):
        raise CSVImportError("missing date or datetime column")
    if not ({"exercise_name", "exercise"} & set(fields)):
        raise CSVImportError("missing exercise_name or exercise column")
    if not ({"weight", "weight_kg"} & set(fields)):
        raise CSVImportError("missing weight or weight_kg column")
    errors: list[dict[str, Any]] = []
    inserted = 0
    for idx, row in enumerate(rows, 2):
        try:
            started_at = (
                row.get("started_at") or row.get("datetime") or row.get("date") or ""
            ).strip()
            date = (row.get("date") or started_at[:10]).strip()
            if not date:
                raise CSVImportError("date is required")
            weight = parse_number(row.get("weight") or row.get("weight_kg"))
            reps = parse_number(row.get("reps"))
            if weight is None or reps is None:
                raise CSVImportError("weight and reps must be numeric")
            unit = (row.get("weight_unit") or ("kg" if row.get("weight_kg") else "kg")).lower()
            if unit in {"lb", "lbs"}:
                weight *= 0.45359237
            if unit not in {"kg", "lb", "lbs"}:
                raise CSVImportError("weight_unit must be kg or lb")
            data = {
                "set_date": date,
                "started_at": started_at or date,
                "exercise_id": row.get("exercise_id")
                or row.get("session_id")
                or row.get("exercise_name")
                or row.get("exercise"),
                "exercise_name": row.get("exercise_name") or row.get("exercise"),
                "equipment": row.get("equipment") or "",
                "variation": row.get("variation") or row.get("exercise_variant") or "",
                "side": row.get("side") or "",
                "set_number": int(parse_number(row.get("set_number")) or 0) or None,
                "weight_kg": weight,
                "reps": int(reps),
                "rir": parse_number(row.get("rir")),
                "rpe": parse_number(row.get("rpe")),
                "warmup": _bool(row.get("warmup") or row.get("is_warmup")),
                "range_of_motion": row.get("range_of_motion") or "",
                "notes": row.get("notes") or "",
                "import_batch_id": None,
            }
            data["fingerprint"] = stable_fingerprint(
                [
                    data[k]
                    for k in (
                        "set_date",
                        "started_at",
                        "exercise_name",
                        "equipment",
                        "variation",
                        "side",
                        "set_number",
                        "weight_kg",
                        "reps",
                        "rir",
                        "rpe",
                        "warmup",
                    )
                ]
            )
            if repo.insert_external("strength_set", data, data.keys()):
                inserted += 1
        except (ValueError, TypeError, CSVImportError) as exc:
            errors.append({"line": idx, "error": str(exc)})
    return {"kind": "strength", "rows": len(rows), "inserted": inserted, "errors": errors}


def import_nutrition_csv(path: Union[str, Path], repo: Repository) -> dict[str, Any]:
    rows, fields = _read(path)
    _required(fields, {"date", "log_status"})
    inserted = 0
    errors: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, 2):
        try:
            day = row.get("date", "").strip()
            status = row.get("log_status", "unknown").strip().lower()
            if not day:
                raise CSVImportError("date is required")
            if status not in {"complete", "partial", "unknown"}:
                raise CSVImportError("log_status must be complete, partial or unknown")
            data = {
                "day": day,
                "energy_kcal": parse_number(row.get("energy_kcal")),
                "protein_g": parse_number(row.get("protein_g")),
                "carbohydrates_g": parse_number(
                    row.get("carbohydrates_g") or row.get("carbohydrate_g")
                ),
                "fat_g": parse_number(row.get("fat_g")),
                "log_status": status,
                "source": row.get("source") or "csv",
                "notes": row.get("notes") or "",
                "import_batch_id": None,
            }
            data["fingerprint"] = stable_fingerprint(
                [
                    data["day"],
                    data["energy_kcal"],
                    data["protein_g"],
                    data["carbohydrates_g"],
                    data["fat_g"],
                    data["log_status"],
                    data["source"],
                ]
            )
            if repo.insert_external("nutrition_day", data, data.keys()):
                inserted += 1
        except (ValueError, TypeError, CSVImportError) as exc:
            errors.append({"line": idx, "error": str(exc)})
    return {"kind": "nutrition", "rows": len(rows), "inserted": inserted, "errors": errors}


def import_measurements_csv(path: Union[str, Path], repo: Repository) -> dict[str, Any]:
    rows, fields = _read(path)
    _required(fields, {"value", "unit"})
    if not ({"date", "datetime"} & set(fields)):
        raise CSVImportError("missing date or datetime column")
    if not ({"measurement_type", "measurement"} & set(fields)):
        raise CSVImportError("missing measurement_type or measurement column")
    inserted = 0
    errors: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, 2):
        try:
            measured = (row.get("datetime") or row.get("date") or "").strip()
            value = parse_number(row.get("value"))
            unit = row.get("unit", "").strip()
            if not measured or value is None or not unit:
                raise CSVImportError("date, value and unit are required")
            typ = (row.get("measurement_type") or row.get("measurement") or "").strip().lower()
            canonical = {
                "weight": "body_mass_kg",
                "body_mass": "body_mass_kg",
                "waist": "waist_cm",
                "height": "height_cm",
                "body_fat": "body_fat_fraction",
            }.get(typ, typ)
            if canonical == "body_mass_kg" and unit.lower() in {"lb", "lbs"}:
                value *= 0.45359237
                unit = "kg"
            elif canonical == "height_cm" and unit.lower() == "m":
                value *= 100
                unit = "cm"
            elif canonical == "body_fat_fraction" and (unit == "%" or value > 1):
                value /= 100
                unit = "fraction"
            data = {
                "measured_at": measured,
                "local_date": measured[:10],
                "body_part": row.get("body_part") or "",
                "value": value,
                "unit": unit,
                "canonical_type": canonical,
                "source": row.get("source") or "csv",
                "notes": row.get("notes") or "",
                "import_batch_id": None,
            }
            data["fingerprint"] = stable_fingerprint(
                [
                    data[k]
                    for k in (
                        "measured_at",
                        "body_part",
                        "value",
                        "unit",
                        "canonical_type",
                        "source",
                    )
                ]
            )
            if repo.insert_external("body_measurement", data, data.keys()):
                inserted += 1
        except (ValueError, TypeError, CSVImportError) as exc:
            errors.append({"line": idx, "error": str(exc)})
    return {"kind": "measurements", "rows": len(rows), "inserted": inserted, "errors": errors}


def import_subjective_csv(path: Union[str, Path], repo: Repository) -> dict[str, Any]:
    rows, fields = _read(path)
    _required(fields, {"date"})
    inserted = 0
    errors: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, 2):
        try:
            day = row.get("date", "").strip()
            if not day:
                raise CSVImportError("date is required")
            data = {
                "day": day,
                "energy_level": parse_number(row.get("energy_level")),
                "fatigue": parse_number(row.get("fatigue")),
                "soreness": parse_number(row.get("soreness")),
                "stress": parse_number(row.get("stress")),
                "sleep_quality": parse_number(row.get("sleep_quality")),
                "pain_location": row.get("pain_location") or "",
                "pain_level": parse_number(row.get("pain_level")),
                "illness_or_travel": row.get("illness_or_travel") or "",
                "notes": row.get("notes") or "",
                "import_batch_id": None,
            }
            data["fingerprint"] = stable_fingerprint(
                [
                    data["day"],
                    data["energy_level"],
                    data["fatigue"],
                    data["soreness"],
                    data["stress"],
                    data["sleep_quality"],
                    data["pain_location"],
                    data["pain_level"],
                ]
            )
            if repo.insert_external("subjective_log", data, data.keys()):
                inserted += 1
        except (ValueError, TypeError, CSVImportError) as exc:
            errors.append({"line": idx, "error": str(exc)})
    return {"kind": "subjective", "rows": len(rows), "inserted": inserted, "errors": errors}
