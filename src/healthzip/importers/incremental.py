"""Incremental JSON/JSONL ingestion for phone-side HealthKit exporters.

The initial ZIP import remains the historical backfill path.  This module
accepts a small, stable envelope so a phone exporter can send a rolling window
or append-only JSONL without making the desktop rescan ``export.xml``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Union

from healthzip.db.repository import Repository
from healthzip.normalize import (
    TYPE_MAP,
    normalize_value,
    parse_apple_datetime,
    parse_number,
    stable_fingerprint,
)

HAE_TYPE_MAP = {
    "active_energy": "HKQuantityTypeIdentifierActiveEnergyBurned",
    "basal_energy_burned": "HKQuantityTypeIdentifierBasalEnergyBurned",
    "apple_exercise_time": "HKQuantityTypeIdentifierAppleExerciseTime",
    "step_count": "HKQuantityTypeIdentifierStepCount",
    "vo2max": "HKQuantityTypeIdentifierVO2Max",
    "weight_body_mass": "HKQuantityTypeIdentifierBodyMass",
    "heart_rate": "HKQuantityTypeIdentifierHeartRate",
    "resting_heart_rate": "HKQuantityTypeIdentifierRestingHeartRate",
    "heart_rate_variability": "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
    "cardio_recovery": "HKQuantityTypeIdentifierHeartRateRecoveryOneMinute",
    "respiratory_rate": "HKQuantityTypeIdentifierRespiratoryRate",
    "blood_oxygen_saturation": "HKQuantityTypeIdentifierOxygenSaturation",
    "apple_sleeping_wrist_temperature": "HKQuantityTypeIdentifierAppleSleepingWristTemperature",
    "dietary_energy": "HKQuantityTypeIdentifierDietaryEnergyConsumed",
    "protein": "HKQuantityTypeIdentifierDietaryProtein",
    "carbohydrates": "HKQuantityTypeIdentifierDietaryCarbohydrates",
    "total_fat": "HKQuantityTypeIdentifierDietaryFatTotal",
    "dietary_water": "HKQuantityTypeIdentifierDietaryWater",
    "dietary_caffeine": "HKQuantityTypeIdentifierDietaryCaffeine",
}


@dataclass
class IncrementalResult:
    batch_id: Optional[int]
    source: str
    status: str = "completed"
    records_seen: int = 0
    new: int = 0
    duplicate: int = 0
    updated: int = 0
    deleted: int = 0
    invalid: int = 0
    errors: list[str] = field(default_factory=list)
    date_min: Optional[str] = None
    date_max: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "source": self.source,
            "status": self.status,
            "records_seen": self.records_seen,
            "new": self.new,
            "duplicate": self.duplicate,
            "updated": self.updated,
            "deleted": self.deleted,
            "invalid": self.invalid,
            "errors": self.errors,
            "date_min": self.date_min,
            "date_max": self.date_max,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _payload_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _raw_type(name: Any) -> Optional[str]:
    value = str(name or "").strip()
    if value in TYPE_MAP:
        return value
    if value in HAE_TYPE_MAP:
        return HAE_TYPE_MAP[value]
    if value.startswith("HKQuantity") or value.startswith("HKCategory"):
        return value if value in TYPE_MAP else None
    return None


def _item_date(item: dict[str, Any]) -> Optional[str]:
    return item.get("date") or item.get("startDate") or item.get("start")


def _metric_value(metric_name: str, item: dict[str, Any]) -> tuple[Any, str]:
    """Return value and aggregation marker.

    Health Auto Export can emit summary heart-rate rows with Min/Avg/Max.  A
    summary is not a raw sample and must not silently become one.  The caller
    rejects those rows for heart rate and HRV while retaining the reason in
    the batch error list.
    """
    if "qty" in item:
        return item.get("qty"), "record"
    if "value" in item:
        return item.get("value"), "record"
    if "raw_value" in item:
        return item.get("raw_value"), "record"
    if "Avg" in item:
        return item.get("Avg"), "summary"
    if "avg" in item:
        return item.get("avg"), "summary"
    return None, "unknown"


def _sample_from_metric(
    metric_name: str,
    units: Optional[str],
    item: dict[str, Any],
    source_kind: str,
    source_namespace: str,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    raw_type = _raw_type(metric_name)
    if raw_type is None:
        return None, f"unsupported_metric:{metric_name}"
    value, aggregation = _metric_value(metric_name, item)
    canonical = TYPE_MAP[raw_type][0]
    if aggregation == "summary" and canonical in {"heart_rate_bpm", "hrv_sdnn_ms"}:
        return None, "aggregate_not_raw"
    start_text = _item_date(item)
    end_text = item.get("endDate") or item.get("end") or start_text
    start_utc, local_dt, offset, local_date = parse_apple_datetime(start_text)
    end_utc, _, _, _ = parse_apple_datetime(end_text)
    if start_text and start_utc is None:
        return None, "invalid_timestamp"
    normalized, normalized_unit, unit_status = normalize_value(raw_type, value, units)
    if normalized is None and item.get("categoryValue") is None:
        return None, "invalid_value"
    source_name = item.get("source") or item.get("sourceName") or source_kind
    source_version = item.get("sourceVersion")
    device = item.get("device")
    source_record_id = item.get("id") or item.get("uuid")
    if source_record_id is not None:
        source_record_id = f"{source_namespace}:{source_record_id}"
    metadata = {
        str(k): v
        for k, v in item.items()
        if k
        not in {
            "qty",
            "value",
            "units",
            "unit",
            "date",
            "start",
            "end",
            "startDate",
            "endDate",
            "source",
            "sourceName",
            "sourceVersion",
            "device",
            "id",
            "uuid",
        }
    }
    metadata["source_format"] = "health_auto_export" if metric_name in HAE_TYPE_MAP else "canonical"
    metadata["aggregation"] = aggregation
    logical_key = stable_fingerprint(
        [raw_type, start_utc, end_utc, source_name, source_version, device]
    )
    fingerprint = stable_fingerprint(
        [raw_type, value, units, start_utc, end_utc, source_name, source_version, device, metadata]
    )
    return {
        "fingerprint": fingerprint,
        "source_kind": source_kind,
        "source_record_id": str(source_record_id) if source_record_id is not None else None,
        "logical_key": logical_key,
        "record_status": "active",
        "raw_type": raw_type,
        "canonical_type": canonical,
        "raw_value": None if value is None else str(value),
        "raw_unit": units,
        "normalized_value": normalized,
        "normalized_unit": normalized_unit,
        "unit_status": unit_status,
        "category_value": item.get("categoryValue"),
        "start_utc": start_utc,
        "end_utc": end_utc,
        "creation_utc": None,
        "local_datetime": local_dt,
        "local_date": local_date,
        "utc_offset_minutes": offset,
        "source_name": source_name,
        "source_version": source_version,
        "device": device,
        "metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str),
        "quality_flags_json": json.dumps(
            {"aggregation": aggregation, "source_kind": source_kind}, ensure_ascii=False
        ),
        "created_at": _now(),
    }, None


def _workout_from_item(
    item: dict[str, Any], source_kind: str, source_namespace: str
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    start_text = item.get("start") or item.get("startDate")
    end_text = item.get("end") or item.get("endDate")
    start_utc, _, _, local_date = parse_apple_datetime(start_text)
    end_utc, _, _, _ = parse_apple_datetime(end_text)
    if start_text and start_utc is None:
        return None, "invalid_timestamp"
    activity = item.get("name") or item.get("activityType") or item.get("workoutActivityType")
    if not activity:
        return None, "missing_workout_type"
    source_name = item.get("source") or item.get("sourceName") or source_kind
    source_record_id = item.get("id") or item.get("uuid")
    logical_key = stable_fingerprint([activity, start_utc, end_utc, source_name])
    if source_record_id is not None:
        source_record_id = f"{source_namespace}:{source_record_id}"
    else:
        source_record_id = logical_key
    fingerprint = stable_fingerprint(
        [activity, start_utc, end_utc, item.get("duration"), item.get("distance"), source_name]
    )
    duration = parse_number(item.get("duration"))
    distance = item.get("distance")
    if isinstance(distance, dict):
        distance_value = parse_number(distance.get("qty") or distance.get("value"))
        distance_unit = distance.get("units") or distance.get("unit")
    else:
        distance_value = parse_number(distance)
        distance_unit = item.get("distanceUnit")
    energy = item.get("activeEnergyBurned") or item.get("energy")
    if isinstance(energy, dict):
        energy_value = parse_number(energy.get("qty") or energy.get("value"))
        energy_unit = energy.get("units") or energy.get("unit")
    else:
        energy_value = parse_number(energy)
        energy_unit = item.get("energyUnit")
    return {
        "fingerprint": fingerprint,
        "source_kind": source_kind,
        "source_record_id": str(source_record_id),
        "logical_key": logical_key,
        "record_status": "active",
        "activity_type": str(activity),
        "start_utc": start_utc,
        "end_utc": end_utc,
        "local_date": local_date,
        "duration_seconds": duration,
        "distance_value": distance_value,
        "distance_unit": distance_unit,
        "energy_value": energy_value,
        "energy_unit": energy_unit,
        "source_name": source_name,
        "source_version": item.get("sourceVersion"),
        "device": item.get("device"),
        "metadata_json": json.dumps(
            {"source_format": "health_auto_export", "raw": item},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ),
        "suspected_duplicate": 0,
        "statistics": [],
        "events": [],
    }, None


def _iter_payload(payload: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    data = payload.get("data", payload)
    for metric in data.get("metrics", []) or []:
        if not isinstance(metric, dict):
            continue
        name = metric.get("name")
        units = metric.get("units")
        for item in metric.get("data", []) or []:
            if isinstance(item, dict):
                yield "metric", (str(name or ""), units, item)
    for item in data.get("workouts", []) or []:
        if isinstance(item, dict):
            yield "workout", item
    for item in data.get("samples", data.get("health_samples", [])) or []:
        if isinstance(item, dict):
            yield "sample", item
    for item in data.get("deleted", data.get("deleted_samples", [])) or []:
        if isinstance(item, dict):
            yield "deleted", item


def _deleted_id(item: dict[str, Any]) -> Optional[str]:
    value = item.get("id") or item.get("uuid") or item.get("source_record_id")
    return str(value) if value is not None else None


def _mark_deleted(repo: Repository, source_kind: str, source_namespace: str, item: dict[str, Any]) -> bool:
    upstream_id = _deleted_id(item)
    if not upstream_id:
        return False
    record_namespace = item.get("source") or item.get("sourceName") or source_namespace
    upstream_id = f"{record_namespace}:{upstream_id}"
    table = "workout" if item.get("kind") == "workout" else "health_sample"
    rows = repo.rows(
        f"SELECT id FROM {table} WHERE source_kind=? AND source_record_id=? AND record_status='active'",
        (source_kind, upstream_id),
    )
    if not rows:
        return False
    repo.conn.execute(
        f"UPDATE {table} SET record_status='deleted' WHERE source_kind=? AND source_record_id=? AND record_status='active'",
        (source_kind, upstream_id),
    )
    return True


def import_json_payload(
    payload: dict[str, Any],
    repo: Repository,
    *,
    source_name: str,
    source_kind: str = "health_auto_export",
    source_ref: Optional[str] = None,
    raw_bytes: Optional[bytes] = None,
) -> IncrementalResult:
    """Import one exporter payload with new/duplicate/update/delete counts."""
    if not isinstance(payload, dict):
        raise ValueError("incremental payload must be a JSON object")
    raw = raw_bytes or json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = _payload_hash(raw)
    source = repo.get_or_create_sync_source(source_name, source_kind)
    batch_id = repo.create_batch(
        file_sha256=digest,
        file_name=source_ref or f"{source_name}.json",
        file_size=len(raw),
        xml_member_path="",
        source_kind=source_kind,
        source_ref=source_ref or source_name,
    )
    result = IncrementalResult(batch_id, source_name)
    try:
        with repo.transaction():
            for kind, item in _iter_payload(payload):
                result.records_seen += 1
                if kind == "deleted":
                    result.deleted += int(_mark_deleted(repo, source_kind, source_name, item))
                    repo.record_ingest_event(
                        source_id=int(source["id"]),
                        batch_id=batch_id,
                        upstream_id=_deleted_id(item),
                        event_kind="deleted",
                        payload_hash=digest,
                        status="processed",
                    )
                    continue
                if kind == "metric":
                    data, error = _sample_from_metric(*item, source_kind, source_name)
                elif kind == "sample":
                    name = item.get("raw_type") or item.get("type")
                    data, error = _sample_from_metric(
                        str(name or ""),
                        item.get("raw_unit") or item.get("unit"),
                        item,
                        source_kind,
                        source_name,
                    )
                else:
                    data, error = _workout_from_item(item, source_kind, source_name)
                if data is None:
                    result.invalid += 1
                    if len(result.errors) < 20:
                        result.errors.append(error or "invalid_record")
                    repo.record_ingest_event(
                        source_id=int(source["id"]),
                        batch_id=batch_id,
                        upstream_id=_deleted_id(item) if isinstance(item, dict) else None,
                        event_kind=kind,
                        payload_hash=digest,
                        status="invalid",
                        error=error,
                    )
                    continue
                outcome = (
                    repo.insert_incremental_workout(batch_id, data)
                    if kind == "workout"
                    else repo.insert_incremental_sample(batch_id, data)
                )
                setattr(result, outcome, getattr(result, outcome) + 1)
                if data.get("local_date"):
                    result.date_min = min(result.date_min or data["local_date"], data["local_date"])
                    result.date_max = max(result.date_max or data["local_date"], data["local_date"])
                repo.record_ingest_event(
                    source_id=int(source["id"]),
                    batch_id=batch_id,
                    upstream_id=data.get("source_record_id"),
                    event_kind=outcome,
                    payload_hash=digest,
                    status="processed",
                )
            result.status = "partial_failed" if result.invalid else "completed"
            repo.finish_batch(
                batch_id,
                status=result.status,
                records_seen=result.records_seen,
                records_inserted=result.new + result.updated,
                records_deduplicated=result.duplicate,
                records_skipped=result.invalid,
                errors_count=result.invalid,
                date_min=result.date_min,
                date_max=result.date_max,
                source_kind=source_kind,
                source_ref=source_ref or source_name,
                records_new=result.new,
                records_duplicate=result.duplicate,
                records_updated=result.updated,
                records_deleted=result.deleted,
                records_invalid=result.invalid,
                error_samples_json=json.dumps(result.errors, ensure_ascii=False),
            )
            repo.update_sync_source_status(int(source["id"]), success=True)
    except Exception:
        repo.update_sync_source_status(int(source["id"]), success=False, error="incremental import failed")
        repo.finish_batch(batch_id, status="partial_failed")
        raise
    return result


def _load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value, raw


def import_json_file(
    path: Union[str, Path],
    repo: Repository,
    *,
    source_name: str,
    source_kind: str = "health_auto_export",
) -> IncrementalResult:
    file_path = Path(path)
    raw = file_path.read_bytes()
    digest = _payload_hash(raw)
    source = repo.get_or_create_sync_source(source_name, source_kind)
    state = repo.get_sync_file(int(source["id"]), str(file_path))
    stat = file_path.stat()
    if state and state["status"] == "completed" and state["content_hash"] == digest:
        return IncrementalResult(None, source_name, status="unchanged")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{file_path} must contain a JSON object")
    result = import_json_payload(
        payload,
        repo,
        source_name=source_name,
        source_kind=source_kind,
        source_ref=str(file_path),
        raw_bytes=raw,
    )
    repo.upsert_sync_file(
        int(source["id"]),
        str(file_path),
        {
            "inode": getattr(stat, "st_ino", 0),
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "content_hash": digest,
            "format": "json",
            "last_offset": stat.st_size,
            "status": "completed",
            "last_error": None,
        },
    )
    return result


def import_jsonl_file(
    path: Union[str, Path],
    repo: Repository,
    *,
    source_name: str,
    source_kind: str = "health_auto_export_jsonl",
) -> list[IncrementalResult]:
    """Read complete JSONL lines after the persisted offset.

    A final unterminated line is left for the next scan, which prevents a
    partially copied phone file from being marked as consumed.
    """
    file_path = Path(path)
    source = repo.get_or_create_sync_source(source_name, source_kind)
    stat = file_path.stat()
    state = repo.get_sync_file(int(source["id"]), str(file_path))
    offset = int(state["last_offset"] if state else 0)
    if state and (int(state["size_bytes"] or 0) > stat.st_size or int(state["inode"] or 0) != getattr(stat, "st_ino", 0)):
        offset = 0
    results: list[IncrementalResult] = []
    with file_path.open("rb") as handle:
        handle.seek(offset)
        while True:
            line_start = handle.tell()
            raw = handle.readline()
            if not raw:
                break
            if not raw.endswith(b"\n"):
                handle.seek(line_start)
                break
            try:
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("JSONL line must be an object")
                result = import_json_payload(
                    payload,
                    repo,
                    source_name=source_name,
                    source_kind=source_kind,
                    source_ref=str(file_path),
                    raw_bytes=raw,
                )
                results.append(result)
            except Exception as exc:
                error = str(exc)[:300]
                repo.upsert_sync_file(
                    int(source["id"]),
                    str(file_path),
                    {
                        "inode": getattr(stat, "st_ino", 0),
                        "size_bytes": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                        "format": "jsonl",
                        "last_offset": line_start,
                        "status": "error",
                        "last_error": error,
                    },
                )
                raise
            offset = handle.tell()
    repo.upsert_sync_file(
        int(source["id"]),
        str(file_path),
        {
            "inode": getattr(stat, "st_ino", 0),
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "content_hash": None,
            "format": "jsonl",
            "last_offset": offset,
            "status": "completed",
            "last_error": None,
        },
    )
    return results


def sync_folder(
    directory: Union[str, Path],
    repo: Repository,
    *,
    source_name: str = "phone_export",
    source_kind: str = "health_auto_export",
) -> dict[str, Any]:
    """Scan a local sync directory without deleting source files."""
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"sync directory does not exist: {root}")
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    paths = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".json", ".jsonl"})
    for path in paths:
        try:
            if path.suffix.lower() == ".jsonl":
                results.extend(r.as_dict() for r in import_jsonl_file(path, repo, source_name=source_name, source_kind=source_kind))
            else:
                results.append(import_json_file(path, repo, source_name=source_name, source_kind=source_kind).as_dict())
        except Exception as exc:
            errors.append(f"{path}: {str(exc)[:300]}")
    return {"directory": str(root), "files_seen": len(paths), "batches": results, "errors": errors}


__all__ = [
    "IncrementalResult",
    "import_json_payload",
    "import_json_file",
    "import_jsonl_file",
    "sync_folder",
]
