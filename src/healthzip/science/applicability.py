"""Tri-state applicability of a harder trial, independent of rule authority.

This does not diagnose injury or estimate capacity. Restricted observations are
still retained facts; they simply cannot license a harder numerical task.
"""
from __future__ import annotations

from .semantics import flatten_record

RESTRICTED_STOPS = {"pain", "discomfort", "technique_limited", "technical_limit", "technical_failure", "technique", "symptoms"}
KNOWN_STOPS = {"planned_stop", "target_rir_stop", "failure", "volitional_failure", "muscular_failure",
               "repetition_failure", "task_failure", "maximum_effort", "time_limit"}


def candidate_applicability(reference: dict | None, current_observations: list[dict] | None = None) -> dict:
    checks = []
    groups = [("reference", [reference] if reference else []), ("current_session", current_observations or [])]
    for group, records in groups:
        for record in records:
            row = flatten_record(record)
            identity = row.get("set_uuid") or row.get("set_id") or row.get("id") or row.get("_source_id")
            reasons, unknown = [], []
            pain = row.get("pain_flag")
            if pain is True:
                reasons.append("pain_reported")
            elif pain is not False:
                unknown.append("pain_status_unknown")
            quality = row.get("quality")
            if quality not in (None, "", "unknown", "acceptable"):
                reasons.append("quality_restricted")
            elif quality != "acceptable":
                unknown.append("quality_unknown")
            stop = row.get("stop_reason")
            if stop in RESTRICTED_STOPS:
                reasons.append("stop_reason_restricted")
            elif stop not in KNOWN_STOPS:
                unknown.append("stop_reason_unknown")
            for symptom, flag in (row.get("symptom_flags") or {}).items():
                if flag is True:
                    reasons.append("symptom_reported:" + symptom)
                elif flag is not False:
                    unknown.append("symptom_unknown:" + symptom)
            checks.append({"group": group, "record_id": str(identity) if identity is not None else None,
                           "applicable": False if reasons else None if unknown else True,
                           "reason_codes": reasons + unknown,
                           "observations": {"quality": quality, "stop_reason": stop, "pain_flag": pain,
                                            "symptom_flags": row.get("symptom_flags")}})
    known_false = any(check["applicable"] is False for check in checks)
    missing = reference is None or any(check["applicable"] is None for check in checks)
    applicable = False if known_false else None if missing else True
    return {"applicable": applicable, "status": "eligible" if applicable is True else "restricted" if applicable is False else "unknown",
            "reason_codes": sorted({reason for check in checks for reason in check["reason_codes"]}
                                   | ({"reference_missing"} if reference is None else set())),
            "reference_record_ids": [c["record_id"] for c in checks if c["group"] == "reference" and c["record_id"] is not None],
            "current_session_record_ids": [c["record_id"] for c in checks if c["group"] == "current_session" and c["record_id"] is not None],
            "checks": checks}
