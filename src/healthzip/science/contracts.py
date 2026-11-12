"""Canonical v1.3 result contract and decision-time filtering.

Data sufficiency is deliberately independent of scientific validation.  In
particular, a simulation artifact never licenses a user-facing validated claim.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from typing import Any, Optional

DATA_STATES = {
    "valid", "partial", "insufficient", "incompatible", "conflicted", "stale",
    "not_identifiable", "not_applicable",
}
EVIDENCE_STATES = {
    "observed", "definition_based", "descriptive", "model_conditional", "research_only",
    "predictive_validated_for_scope", "intervention_validated_for_scope",
}
ALGORITHM_VERSION = "healthzip-science-1.4.2"


def definitions() -> dict[str, dict[str, Any]]:
    data = json.loads(files("healthzip.science").joinpath("metrics.json").read_text("utf-8"))
    return {item["metric_id"]: item for item in data["metrics"]}


def instant(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp_required")
    if parsed.tzinfo is None:
        raise ValueError("timezone_required")
    return parsed.astimezone(timezone.utc)


def finite(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Window:
    start: str
    end: str
    cutoff_time: str
    timezone: str = "UTC"

    def __post_init__(self) -> None:
        if instant(self.start) >= instant(self.end):
            raise ValueError("window_must_have_positive_duration")

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "timezone": self.timezone,
                "closure": "[start,end)"}


def select_as_of(records: list[dict], window: Window, *, retrospective: bool = False,
                 overlap: bool = False) -> tuple[list[dict], list[dict]]:
    """Resolve known revisions, then apply event and availability boundaries.

    Unknown available_at is never silently equated with event time.  Explicit
    retrospective mode permits descriptive snapshots and labels that limitation.
    Tombstones invalidate only revisions known at the requested cutoff.
    """
    cutoff = instant(window.cutoff_time)
    eligible, exclusions = [], []
    for position, original in enumerate(records):
        row = dict(original)
        key = str(row.get("record_id", row.get("id", position)))
        row["_source_id"] = key
        available = row.get("available_at") or row.get("ingested_at")
        try:
            if available is None:
                if not retrospective:
                    exclusions.append({"id": key, "reason": "available_at_unknown"})
                    continue
                row["_retrospective_snapshot"] = True
            elif instant(available) > cutoff:
                exclusions.append({"id": key, "reason": "available_after_cutoff"})
                continue
        except ValueError as exc:
            exclusions.append({"id": key, "reason": str(exc)})
            continue
        eligible.append(row)
    # A source's stable UUID identifies revisions. Distinct real sets keep IDs.
    latest: dict[tuple, dict] = {}
    for row in eligible:
        logical = (row.get("source_kind"), row.get("source_name"),
                   row.get("source_record_id") or row.get("original_uuid") or row["_source_id"])
        available = row.get("available_at") or row.get("ingested_at")
        rank = (instant(available).isoformat() if available else "",
                str(row.get("revision_id", "")), row["_source_id"])
        previous = latest.get(logical)
        if previous is None or rank > previous["_revision_rank"]:
            if previous is not None:
                exclusions.append({"id": previous["_source_id"], "reason": "superseded_as_of"})
            row["_revision_rank"] = rank
            latest[logical] = row
        else:
            exclusions.append({"id": row["_source_id"], "reason": "duplicate_or_old_revision"})
    selected = []
    for row in latest.values():
        if row.get("conflicted") is True or row.get("record_status") == "conflicted":
            exclusions.append({"id": row["_source_id"], "reason": "unresolved_record_conflict"})
            continue
        deleted_at = row.get("deleted_at")
        if row.get("record_status") == "deleted" or (deleted_at and instant(deleted_at) <= cutoff):
            exclusions.append({"id": row["_source_id"], "reason": "deleted_as_of"})
            continue
        # An already-visible correction invalidates its predecessor even if its
        # corrected event is future/unknown. Event filtering before revision
        # resolution would resurrect that predecessor (including tombstones).
        event = row.get("event_end") or row.get("end_at_utc") or row.get("end_utc")
        event = event or row.get("performed_at") or row.get("timestamp")
        try:
            end = instant(event)
        except ValueError as exc:
            exclusions.append({"id": row["_source_id"], "reason": str(exc)})
            continue
        if end > cutoff:
            exclusions.append({"id": row["_source_id"], "reason": "event_after_cutoff"})
            continue
        row["_event_end"] = end.isoformat()
        if overlap:
            start = instant(row.get("event_start") or row.get("start_at_utc")
                            or row.get("start_utc") or row["_event_end"])
            inside = end > instant(window.start) and start < instant(window.end)
        else:
            inside = instant(window.start) <= end < instant(window.end)
        if inside:
            selected.append(row)
        else:
            exclusions.append({"id": row["_source_id"], "reason": "outside_window"})
    return sorted(selected, key=lambda row: row["_event_end"]), exclusions


def result(metric_id: str, window: Window, value: Any = None, *, unit: Optional[str] = None,
           data_status: str = "valid", evidence_status: str = "definition_based",
           records: Optional[list[dict]] = None, valid_n: Optional[int] = None,
           total_n: Optional[int] = None, count_domain: str = "records",
           reasons: Optional[list[str]] = None, assumptions: Optional[list[str]] = None,
           uncertainty: Optional[dict] = None, coverage: Optional[list[dict]] = None,
           parameter_set_id: Optional[str] = None, calibration: Optional[dict] = None,
           **extra: Any) -> dict:
    definition = definitions()[metric_id]
    rows = records or []
    output = {
        "metric_id": metric_id, "algorithm_version": ALGORITHM_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "cutoff_time": window.cutoff_time, "window": window.as_dict(),
        "value": value, "unit": definition["unit"] if unit is None else unit,
        "data_status": data_status, "evidence_status": evidence_status,
        "valid_n": valid_n if valid_n is not None else len(rows),
        "total_n": total_n if total_n is not None else len(rows),
        "n_sessions": len({r["session_id"] for r in rows if r.get("session_id") is not None}),
        "count_domain": count_domain, "coverage": coverage or [],
        "uncertainty": uncertainty or {"kind": "not_estimated", "lower": None,
                                       "upper": None, "level": None, "assumptions": []},
        "assumptions": assumptions or [], "reason_codes": reasons or [],
        "source_record_ids": sorted({str(r.get("_source_id", r.get("id"))) for r in rows
                                     if r.get("_source_id", r.get("id")) is not None}),
        "evidence_refs": definition["evidence_refs"],
        "parameter_set_id": parameter_set_id,
        "calibration_artifact_id": calibration.get("artifact_id") if calibration else None,
        "limitations": [definition.get("uncertainty", ""), *definition.get("forbidden_inferences", [])],
        **extra,
    }
    if any(r.get("_retrospective_snapshot") for r in rows):
        output["reason_codes"].append("retrospective_snapshot_not_prospective")
    validate_result(output, calibration=calibration)
    return output


def validate_result(value: dict, *, calibration: Optional[dict] = None) -> None:
    required = {"metric_id", "algorithm_version", "computed_at", "cutoff_time", "window",
                "value", "unit", "data_status", "evidence_status", "valid_n", "total_n",
                "coverage", "uncertainty", "assumptions", "reason_codes", "source_record_ids",
                "evidence_refs", "parameter_set_id", "calibration_artifact_id"}
    if not required <= value.keys():
        raise ValueError("missing_result_fields")
    if value["data_status"] not in DATA_STATES or value["evidence_status"] not in EVIDENCE_STATES:
        raise ValueError("invalid_result_state")
    instant(value["cutoff_time"])
    instant(value["computed_at"])
    w = value["window"]
    if w.get("closure") != "[start,end)" or instant(w["start"]) >= instant(w["end"]):
        raise ValueError("invalid_window")
    n, total = value["valid_n"], value["total_n"]
    if n is not None and (not isinstance(n, int) or n < 0):
        raise ValueError("invalid_count")
    if total is not None and (not isinstance(total, int) or total < 0 or (n is not None and n > total)):
        raise ValueError("invalid_denominator")
    u = value["uncertainty"]
    if u["kind"] in {"scenario_range", "sensitivity_range"} and u["level"] is not None:
        raise ValueError("scenario_has_no_coverage_probability")
    if u["lower"] is not None and u["upper"] is not None and u["lower"] > u["upper"]:
        raise ValueError("reversed_interval")
    if value["evidence_status"].endswith("validated_for_scope"):
        if not calibration or calibration.get("scope_status") != "validated_for_scope":
            raise ValueError("real_validation_artifact_required")
        if calibration.get("data_kind") != "real" or not calibration.get("independent_holdout"):
            raise ValueError("independent_real_holdout_required")
        if value["metric_id"] not in calibration.get("metric_ids", []):
            raise ValueError("calibration_metric_scope_mismatch")
    for item in value["coverage"]:
        if not {"kind", "numerator", "denominator", "definition"} <= item.keys():
            raise ValueError("coverage_contract_incomplete")
        numerator, denominator = item["numerator"], item["denominator"]
        if numerator is not None and numerator < 0 or denominator is not None and denominator < 0:
            raise ValueError("coverage_counts_invalid")
        if numerator is not None and denominator is not None and numerator > denominator:
            raise ValueError("coverage_exceeds_defined_denominator")
    # Prevent NaN and Infinity from entering SQLite JSON, reports or model payloads.
    json.dumps(value, allow_nan=False)
