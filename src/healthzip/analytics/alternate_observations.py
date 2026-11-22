"""Visible alternate representations, kept separate from raw sample totals."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from healthzip.db.temporal_schema import samples_as_of
from healthzip.normalize import TYPE_MAP, normalize_value, parse_apple_datetime, parse_number
from healthzip.science.contracts import instant

ACTIVITY_FIELDS = {
    "active_energy_kcal": "active_energy",
    "exercise_minutes": "exercise_minutes",
    "stand_hour": "stand_hours",
}
NUTRITION_FIELDS = {
    "dietary_energy_kcal": "energy_kcal",
    "dietary_protein_g": "protein_g",
    "dietary_carbohydrates_g": "carbohydrates_g",
    "dietary_fat_g": "fat_g",
}
WORKOUT_FIELDS = {"active_energy_kcal", "distance_walking_running_m", "distance_cycling_m"}
CYCLE_FIELDS = {
    "menstrual_flow",
    "intermenstrual_bleeding",
    "cervical_mucus_quality",
    "ovulation_test_result",
    "menstrual_cramps",
    "abdominal_cramps",
}


def alternate_dependencies(field):
    deps = []
    if field in ACTIVITY_FIELDS:
        deps.append(("activity_summary", None))
    if field in NUTRITION_FIELDS:
        deps.append(("nutrition_day", None))
    if field in CYCLE_FIELDS:
        deps.append(("cycle_event", None))
    if field in WORKOUT_FIELDS:
        deps += [("workout", None), ("workout_statistic", None)]
    return deps


def _metadata(row):
    try:
        value = json.loads(row.get("metadata_json") or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _adapt(row, table, field, at, source, value, unit, metadata, *, first=None):
    return {
        **row,
        "id": f"{table}:{row['id']}",
        "record_kind": table,
        "canonical_type": field,
        "source_name": source,
        "source_kind": row.get("source_kind")
        or (
            "apple_zip"
            if table in {"activity_summary", "workout_statistic", "workout"}
            else "legacy_log"
        ),
        "protocol_id": table + ":" + str(metadata.get("representation", "")),
        "event_start": first or at,
        "event_end": at,
        "start_utc": first or at,
        "end_utc": at,
        "raw_type": next(raw for raw, (key, _) in TYPE_MAP.items() if key == field),
        "raw_value": str(value) if value is not None else None,
        "raw_unit": unit,
        "normalized_value": value,
        "normalized_unit": unit,
        "metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
    }


def alternate_rows(repo, field, start, end, cutoff, timezone_name, sources=(), primary=()):
    zone = ZoneInfo(timezone_name)
    rows = []
    for table, _ in alternate_dependencies(field):
        if table in {"workout", "workout_statistic"}:
            continue
        visible = samples_as_of(
            repo,
            cutoff,
            table,
            window_start=(start - timedelta(days=1)).isoformat(),
            window_end=(end + timedelta(days=1)).isoformat(),
            include_deleted=table != "cycle_event",
        )
        selected = {}
        for row in visible:
            day = row.get("summary_date") or row.get("day") or row.get("event_date")
            try:
                at = datetime.fromisoformat(day).replace(tzinfo=zone)
            except (TypeError, ValueError):
                continue
            if not start <= at < end or at > instant(cutoff):
                continue
            source = row.get("source") or "Apple ActivitySummary（原结构未提供设备来源）"
            if sources and source not in sources:
                continue
            meta = {
                **_metadata(row),
                "event_time_precision": "calendar_day",
                "representation": table,
                "calendar_date": day,
                "coverage": "unknown",
                "aggregation": "daily_summary",
            }
            if table == "cycle_event":
                if row.get("canonical_type") != field or any(
                    r.get("fingerprint") == row.get("fingerprint") for r in primary
                ):
                    continue
                item = _adapt(row, table, field, at.isoformat(), source, None, "category", meta)
                rows.append(item)
                continue
            if table == "nutrition_day":
                column = NUTRITION_FIELDS[field]
                value, unit = parse_number(row.get(column)), dict(TYPE_MAP.values())[field]
                meta["log_status"] = row.get("log_status", "unknown")
            else:
                column = ACTIVITY_FIELDS[field]
                value = parse_number(row.get(column))
                unit = {"stand_hour": "h", "exercise_minutes": "min"}.get(field, "kcal")
                if field == "active_energy_kcal":
                    raw_unit = meta.get("activeEnergyBurnedUnit")
                    value, unit, _ = normalize_value(
                        "HKQuantityTypeIdentifierActiveEnergyBurned", value, raw_unit
                    )
                    meta["original_value"] = row.get(column)
                    meta["original_unit"] = raw_unit
            if row.get(column) is None:
                continue
            item = _adapt(row, table, field, at.isoformat(), source, value, unit, meta)
            # These are alternate date snapshots; choose the latest visible
            # publication, never sum repeated daily summaries/imports.
            key = (source, day)
            old = selected.get(key)
            if old is None or (instant(row["available_at"]), row["id"]) > (
                instant(old["available_at"]),
                int(old["id"].split(":")[-1]),
            ):
                selected[key] = item
        rows.extend(
            row for row in selected.values() if row.get("record_status", "active") == "active"
        )
    if field not in WORKOUT_FIELDS:
        return rows
    workouts = samples_as_of(
        repo, cutoff, "workout", window_start=start.isoformat(), window_end=end.isoformat()
    )
    parents = {
        w["id"]: w
        for w in workouts
        if w.get("end_utc") and instant(w["end_utc"]) <= instant(cutoff)
    }
    statistics = samples_as_of(
        repo,
        cutoff,
        "workout_statistic",
        window_start=start.isoformat(),
        window_end=end.isoformat(),
    )
    grouped = defaultdict(list)
    for stat in statistics:
        if (
            TYPE_MAP.get(stat.get("raw_type"), (None,))[0] == field
            and stat["workout_id"] in parents
        ):
            grouped[stat["workout_id"]].append(stat)
    for wid, workout in parents.items():
        source = workout.get("source_name") or "Workout（来源未知）"
        if sources and source not in sources:
            continue
        a, b = workout["start_utc"], workout["end_utc"]
        candidates = []
        for stat in grouped[wid]:
            sa = parse_apple_datetime(stat.get("statistic_start"))[0]
            sb = parse_apple_datetime(stat.get("statistic_end"))[0]
            value, unit, _ = normalize_value(
                stat["raw_type"], stat.get("sum_value"), stat.get("unit")
            )
            if (
                value is not None
                and value >= 0
                and sa
                and sb
                and instant(a) <= instant(sa) <= instant(sb) <= instant(b)
            ):
                candidates.append((stat, sa, sb, value, unit))
        whole = [
            s for s in candidates if instant(s[1]) == instant(a) and instant(s[2]) == instant(b)
        ]
        # Whole-workout summaries take precedence over their own subintervals.
        if whole:
            candidates = whole
        unique = {}
        for entry in candidates:
            unique.setdefault((entry[1], entry[2], entry[3], entry[4]), entry)
        for stat, sa, sb, value, unit in unique.values():
            meta = {
                "representation": "workout_statistic",
                "workout_ids": [f"workout:{wid}"],
                "aggregation": "incremental",
                "coverage": "workout_interval_only",
            }
            item = _adapt(stat, "workout_statistic", field, sb, source, value, unit, meta, first=sa)
            item.update(
                device=workout.get("device"),
                source_version=workout.get("source_version"),
                workout_ids=[f"workout:{wid}"],
            )
            rows.append(item)
        activity = str(workout.get("activity_type", "")).removeprefix("HKWorkoutActivityType")
        eligible = (
            field == "distance_walking_running_m" and activity in {"Walking", "Running", "Hiking"}
        ) or (field == "distance_cycling_m" and activity == "Cycling")
        if not candidates and eligible:
            raw = next(raw for raw, (key, _) in TYPE_MAP.items() if key == field)
            value, unit, _ = normalize_value(
                raw, workout.get("distance_value"), workout.get("distance_unit")
            )
            if value is not None and value >= 0:
                meta = {
                    "representation": "workout_distance_header",
                    "aggregation": "incremental",
                    "coverage": "workout_interval_only",
                }
                rows.append(
                    _adapt(workout, "workout", field, b, source, value, unit, meta, first=a)
                )
    return rows
