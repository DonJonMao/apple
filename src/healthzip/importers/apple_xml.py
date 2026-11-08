"""Incremental, local-only Apple Health XML importer."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional, Union
from zipfile import ZipFile

from lxml import etree

from healthzip.config import ImportLimits
from healthzip.db.repository import Repository
from healthzip.importers.apple_zip import inspect_zip
from healthzip.normalize import (
    SLEEP_VALUES,
    TYPE_MAP,
    normalize_value,
    parse_apple_datetime,
    parse_number,
    stable_fingerprint,
)


def _clear_element(elem) -> None:
    """Keep incremental parsing memory bounded by deleting processed siblings."""
    elem.clear()
    parent = elem.getparent()
    if parent is not None:
        while elem.getprevious() is not None:
            del parent[0]


@dataclass
class ImportResult:
    batch_id: Optional[int]
    status: str
    records_seen: int = 0
    records_inserted: int = 0
    records_deduplicated: int = 0
    records_skipped: int = 0
    errors_count: int = 0
    unknown_type_counts: dict[str, int] = field(default_factory=dict)
    error_samples: list[str] = field(default_factory=list)
    date_min: Optional[str] = None
    date_max: Optional[str] = None
    exported_at: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "status": self.status,
            "records_seen": self.records_seen,
            "records_inserted": self.records_inserted,
            "records_deduplicated": self.records_deduplicated,
            "records_skipped": self.records_skipped,
            "errors_count": self.errors_count,
            "unknown_type_counts": self.unknown_type_counts,
            "error_samples": self.error_samples,
            "date_min": self.date_min,
            "date_max": self.date_max,
            "exported_at": self.exported_at,
        }


def _metadata(attrs: dict[str, str]) -> dict[str, str]:
    known = {
        "type",
        "value",
        "unit",
        "startDate",
        "endDate",
        "creationDate",
        "sourceName",
        "sourceVersion",
        "device",
    }
    return {k: v for k, v in attrs.items() if k not in known}


def _record_data(
    attrs: dict[str, str], include_cycle: bool
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    raw_type = attrs.get("type", "")
    canonical_tuple = TYPE_MAP.get(raw_type)
    is_cycle = bool(
        canonical_tuple
        and canonical_tuple[0]
        in {
            "menstrual_flow",
            "intermenstrual_bleeding",
            "cervical_mucus_quality",
            "ovulation_test_result",
            "menstrual_cramps",
        }
    )
    if is_cycle and not include_cycle:
        return None, "cycle_disabled"
    if not canonical_tuple:
        return None, "unknown_type"
    start_utc, local_dt, offset, local_date = parse_apple_datetime(attrs.get("startDate"))
    end_utc, _, _, _ = parse_apple_datetime(attrs.get("endDate"))
    creation_utc, _, _, _ = parse_apple_datetime(attrs.get("creationDate"))
    if (
        (attrs.get("startDate") and start_utc is None)
        or (attrs.get("endDate") and end_utc is None)
        or (attrs.get("creationDate") and creation_utc is None)
    ):
        return None, "invalid_timestamp"
    normalized, normalized_unit, unit_status = normalize_value(
        raw_type, attrs.get("value"), attrs.get("unit")
    )
    category = (
        attrs.get("value") if normalized is None or raw_type.startswith("HKCategory") else None
    )
    fp = stable_fingerprint(
        [
            raw_type,
            attrs.get("value"),
            attrs.get("unit"),
            start_utc,
            end_utc,
            creation_utc,
            attrs.get("sourceName"),
            attrs.get("sourceVersion"),
            attrs.get("device"),
            _metadata(attrs),
        ]
    )
    return {
        "fingerprint": fp,
        "source_kind": "apple_zip",
        "source_record_id": attrs.get("uuid") or attrs.get("id"),
        "logical_key": stable_fingerprint(
            [raw_type, start_utc, end_utc, creation_utc, attrs.get("sourceName"), attrs.get("device")]
        ),
        "record_status": "active",
        "raw_type": raw_type,
        "canonical_type": canonical_tuple[0],
        "raw_value": attrs.get("value"),
        "raw_unit": attrs.get("unit"),
        "normalized_value": normalized,
        "normalized_unit": normalized_unit,
        "unit_status": unit_status,
        "category_value": category,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "creation_utc": creation_utc,
        "local_datetime": local_dt,
        "local_date": local_date,
        "utc_offset_minutes": offset,
        "source_name": attrs.get("sourceName"),
        "source_version": attrs.get("sourceVersion"),
        "device": attrs.get("device"),
        "metadata_json": json.dumps(_metadata(attrs), ensure_ascii=False, sort_keys=True),
        "quality_flags_json": json.dumps(
            {"sleep_value": SLEEP_VALUES.get(category, category) if category else None},
            ensure_ascii=False,
        ),
        "created_at": __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .isoformat(),
    }, None


def _workout_data(attrs: dict[str, str]) -> dict[str, Any]:
    start_utc, _, _, local_date = parse_apple_datetime(attrs.get("startDate"))
    end_utc, _, _, _ = parse_apple_datetime(attrs.get("endDate"))
    duration = parse_number(attrs.get("duration"))
    if duration is not None and attrs.get("durationUnit", "min").lower().startswith("min"):
        duration *= 60
    distance = parse_number(attrs.get("totalDistance"))
    distance_unit = attrs.get("totalDistanceUnit")
    if (
        distance is not None
        and distance_unit
        and distance_unit.lower() in {"km", "kilometer", "kilometre"}
    ):
        distance *= 1000
        distance_unit = "m"
    fp = stable_fingerprint(
        [
            attrs.get("workoutActivityType"),
            start_utc,
            end_utc,
            duration,
            distance,
            attrs.get("totalEnergyBurned"),
            attrs.get("sourceName"),
            attrs.get("device"),
        ]
    )
    return {
        "fingerprint": fp,
        "source_kind": "apple_zip",
        "source_record_id": attrs.get("uuid") or attrs.get("id"),
        "logical_key": stable_fingerprint(
            [
                attrs.get("workoutActivityType"),
                start_utc,
                end_utc,
                attrs.get("sourceName"),
                attrs.get("device"),
            ]
        ),
        "record_status": "active",
        "activity_type": attrs.get("workoutActivityType"),
        "start_utc": start_utc,
        "end_utc": end_utc,
        "local_date": local_date,
        "duration_seconds": duration,
        "distance_value": distance,
        "distance_unit": distance_unit,
        "energy_value": parse_number(attrs.get("totalEnergyBurned")),
        "energy_unit": attrs.get("totalEnergyBurnedUnit"),
        "source_name": attrs.get("sourceName"),
        "source_version": attrs.get("sourceVersion"),
        "device": attrs.get("device"),
        "metadata_json": json.dumps(_metadata(attrs), ensure_ascii=False, sort_keys=True),
        "suspected_duplicate": 0,
    }


def _iter_export(
    stream, result: ImportResult, include_cycle: bool
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield one normalized item at a time; no all-records list is kept."""
    try:
        context = etree.iterparse(
            stream,
            events=("end",),
            tag=(
                "ExportDate",
                "Record",
                "Workout",
                "ActivitySummary",
                "Correlation",
                "ClinicalRecord",
                "Electrocardiogram",
            ),
            resolve_entities=False,
            load_dtd=False,
            no_network=True,
            huge_tree=False,
        )
        for _, elem in context:
            tag = elem.tag.rsplit("}", 1)[-1] if isinstance(elem.tag, str) else ""
            attrs = {str(k): str(v) for k, v in elem.attrib.items()}
            if tag == "ExportDate":
                result.exported_at = attrs.get("value")
            elif tag == "Record":
                result.records_seen += 1
                raw_type = attrs.get("type", "")
                if raw_type not in TYPE_MAP:
                    result.unknown_type_counts[raw_type] = (
                        result.unknown_type_counts.get(raw_type, 0) + 1
                    )
                data, reason = _record_data(attrs, include_cycle)
                if data is None:
                    if reason == "invalid_timestamp":
                        result.errors_count += 1
                        if len(result.error_samples) < 20:
                            result.error_samples.append(
                                f"invalid Record timestamp: {attrs.get('startDate', '')[:80]}"
                            )
                    result.records_skipped += 1
                else:
                    date = data.get("local_date")
                    if date and (result.date_min is None or date < result.date_min):
                        result.date_min = date
                    if date and (result.date_max is None or date > result.date_max):
                        result.date_max = date
                    yield "sample", data
            elif tag == "Workout":
                result.records_seen += 1
                data = _workout_data(attrs)
                if data.get("local_date") and (
                    result.date_min is None or data["local_date"] < result.date_min
                ):
                    result.date_min = data["local_date"]
                if data.get("local_date") and (
                    result.date_max is None or data["local_date"] > result.date_max
                ):
                    result.date_max = data["local_date"]
                stats = []
                events = []
                for child in elem:
                    child_tag = child.tag.rsplit("}", 1)[-1] if isinstance(child.tag, str) else ""
                    c = {str(k): str(v) for k, v in child.attrib.items()}
                    if child_tag == "WorkoutStatistics":
                        stats.append(
                            {
                                "raw_type": c.get("type"),
                                "start": c.get("startDate"),
                                "end": c.get("endDate"),
                                "average": parse_number(c.get("average")),
                                "minimum": parse_number(c.get("minimum")),
                                "maximum": parse_number(c.get("maximum")),
                                "sum": parse_number(c.get("sum")),
                                "unit": c.get("unit"),
                            }
                        )
                    elif child_tag == "WorkoutEvent":
                        events.append(
                            {
                                "type": c.get("type"),
                                "date": c.get("date"),
                                "duration": parse_number(c.get("duration")),
                                "metadata": c,
                            }
                        )
                data["statistics"] = stats
                data["events"] = events
                yield "workout", data
            elif tag == "ActivitySummary":
                result.records_seen += 1
                yield (
                    "activity_summary",
                    {
                        "date": attrs.get("dateComponents"),
                        "active_energy": parse_number(attrs.get("activeEnergyBurned")),
                        "active_energy_goal": parse_number(attrs.get("activeEnergyBurnedGoal")),
                        "exercise_minutes": parse_number(attrs.get("appleExerciseTime")),
                        "exercise_minutes_goal": parse_number(attrs.get("appleExerciseTimeGoal")),
                        "stand_hours": parse_number(attrs.get("appleStandHours")),
                        "stand_hours_goal": parse_number(attrs.get("appleStandHoursGoal")),
                    },
                )
            _clear_element(elem)
        del context
    except etree.XMLSyntaxError as exc:
        result.errors_count += 1
        result.error_samples.append(f"XML parse error: {str(exc)[:300]}")


def import_apple_zip(
    path: Union[str, Path],
    repo: Repository,
    *,
    include_cycle: bool = False,
    limits: Optional[ImportLimits] = None,
    skip_duplicate_file: bool = True,
) -> ImportResult:
    limits = limits or ImportLimits()
    inspection = inspect_zip(path, limits)
    existing = repo.existing_completed_batch(inspection.sha256) if skip_duplicate_file else None
    if existing:
        return ImportResult(
            int(existing["id"]),
            "already_imported",
            int(existing["records_seen"] or 0),
            0,
            int(existing["records_deduplicated"] or 0),
            0,
            int(existing["errors_count"] or 0),
            json.loads(existing["unknown_type_counts_json"] or "{}"),
            [],
            existing["date_min"],
            existing["date_max"],
            existing["exported_at"],
        )
    batch_id = repo.create_batch(
        file_sha256=inspection.sha256,
        file_name=Path(path).name,
        file_size=inspection.file_size_bytes,
        xml_member_path=inspection.xml_member_path or "",
    )
    result = ImportResult(batch_id, "completed")
    try:
        with ZipFile(path) as zf, zf.open(inspection.xml_member_path) as stream:
            for kind, data in _iter_export(stream, result, include_cycle):
                try:
                    if kind == "sample":
                        if repo.insert_sample(batch_id, data):
                            result.records_inserted += 1
                        else:
                            result.records_deduplicated += 1
                        if data.get("canonical_type") in {
                            "menstrual_flow",
                            "intermenstrual_bleeding",
                            "cervical_mucus_quality",
                            "ovulation_test_result",
                            "menstrual_cramps",
                        }:
                            repo.insert_cycle_event(batch_id, data)
                    elif kind == "workout":
                        workout_id, inserted = repo.insert_workout(batch_id, data)
                        if inserted:
                            result.records_inserted += 1
                        else:
                            result.records_deduplicated += 1
                        if workout_id:
                            for stat in data.get("statistics", []):
                                repo.insert_workout_stat(workout_id, stat)
                            for event in data.get("events", []):
                                repo.insert_workout_event(workout_id, event)
                    else:
                        repo.insert_activity_summary(batch_id, data)
                        result.records_inserted += 1
                    if result.records_inserted % limits.batch_size == 0:
                        repo.insert_many_commit()
                except Exception as exc:
                    result.errors_count += 1
                    if len(result.error_samples) < 20:
                        result.error_samples.append(f"{kind}: {str(exc)[:300]}")
        result.status = "partial_failed" if result.errors_count else "completed"
    except Exception as exc:
        result.errors_count += 1
        result.status = "partial_failed"
        result.error_samples.append(str(exc)[:300])
    repo.finish_batch(
        batch_id,
        exported_at=result.exported_at,
        status=result.status,
        records_seen=result.records_seen,
        records_inserted=result.records_inserted,
        records_deduplicated=result.records_deduplicated,
        records_skipped=result.records_skipped,
        errors_count=result.errors_count,
        date_min=result.date_min,
        date_max=result.date_max,
        unknown_type_counts_json=json.dumps(result.unknown_type_counts, ensure_ascii=False),
        error_samples_json=json.dumps(result.error_samples, ensure_ascii=False),
    )
    return result
