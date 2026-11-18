"""Availability-safe daily facts, distinct from research reference sampling.

The latest actual session is selected before checking numerical eligibility.
Every recorded set in that session is retained, including incompatible, failed,
unfinished and deleted observations. No representative performance is invented.
"""
from __future__ import annotations

from copy import deepcopy

from healthzip.science.contracts import canonical_hash, instant
from healthzip.science.semantics import analysis_task, flatten_record

from .semantics import condition_snapshot, timestamp

MATCH_VERSION = "daily-exercise-history-1.0.0"


def daily_identity(record):
    """Physical daily identity; research protocol/order keeps its own task ID.

    Reuse the canonical condition vocabulary and its missing-data requirements.
    Only reference sampling protocol is outside this daily factual purpose.
    Equipment, definition, side, ROM, settings and load conventions are retained.
    """
    row = flatten_record(record)
    physical = {**row, "reference_protocol": None}
    if not all(physical.get(k) for k in ("user_id", "exercise_id", "definition_version")):
        return {"version": MATCH_VERSION, "condition_key": None,
                "reason_codes": ["daily_physical_identity_unknown"]}
    try:
        normalized = condition_snapshot({"exercise_id": physical["exercise_id"],
            "definition_version": physical["definition_version"],
            "recording_mode": physical.get("measurement_mode")}, physical, physical["user_id"])
    except ValueError:
        return {"version": MATCH_VERSION, "condition_key": None,
                "reason_codes": ["daily_physical_identity_unknown"]}
    return {"version": MATCH_VERSION, "condition_key": normalized["condition_key"],
            "reason_codes": ["daily_missing_" + k for k in normalized["missing_comparability_fields"]]}


def daily_comparability(first, second):
    """No name matching, task-ID clearing or unknown-condition equivalence."""
    left, right = daily_identity(first), daily_identity(second)
    reasons = list(dict.fromkeys(left["reason_codes"] + right["reason_codes"]))
    if not reasons and left["condition_key"] != right["condition_key"]:
        reasons.append("daily_physical_condition_changed")
    return {"comparable": not reasons, "reason_codes": reasons,
            "daily_identity": left, "current_daily_identity": right,
            "strict_task_id": analysis_task(first)["task_id"],
            "current_strict_task_id": analysis_task(second)["task_id"]}


def _time(value):
    if not value:
        return None
    try:
        return instant(value)
    except (TypeError, ValueError):
        return None


def _observed(row):
    return (row.get("completion_state") in {"completed", "aborted", "in_progress"}
            or bool(row.get("started_at") or row.get("ended_at")))


def _replay(events):
    """Keep raw states omitted by scientific timestamp eligibility filters."""
    sessions, instances, rows = {}, {}, {}
    for event in events:
        value = event.get("after")
        if event.get("status") != "applied" or not isinstance(value, dict):
            continue
        kind = event.get("entity_type")
        if kind == "session":
            sessions[value["id"]] = value
            for item in value.get("exercises", []):
                instances[item["id"]] = item
            for child in value.get("sets", []):
                rows.setdefault(child["set_uuid"], child)
        elif kind == "session_exercise":
            instances[value["id"]] = value
            for child in value.get("sets", []):
                rows[child["set_uuid"]] = child
        elif kind == "set" and value.get("set_uuid"):
            rows[value["set_uuid"]] = value
    return sessions, instances, rows


def select_daily_history(service, instance, *, cutoff_time, history=None):
    """Find lifetime latest same-exercise facts, then expose each set's limits.

    ``history`` may supply the caller's already-replayed rows for the same cutoff;
    it never replaces lifetime event discovery with a bounded display window.
    The caller owns before/after dependency validation. This read holds no write
    lock, uses one cutoff, and never changes reference identities or feedback.
    """
    cutoff_time = timestamp(cutoff_time)
    cutoff = instant(cutoff_time)
    events = service.events_as_of(cutoff_time=cutoff_time)
    sessions, instances, raw = _replay(events)
    # Canonical replay supplies conflict state and session tombstones. Raw replay
    # additionally retains missing-time observations as facts with an explicit limit.
    replayed = service.history_as_of(cutoff_time=cutoff_time, include_incomplete=True,
                                    include_deleted=True, _events=events)
    for row in replayed:
        raw[row["set_uuid"]] = row
    for row in history or []:
        identity = row.get("set_uuid")
        if identity in raw:
            # Only enrich provenance; caller windows cannot change authoritative state.
            raw[identity] = {**row, **raw[identity]}
    exercise_id = instance.get("catalog_id") or instance.get("exercise_id")
    current = {**instance.get("condition", {}),
               "exercise_id": exercise_id,
               "definition_version": instance.get("definition_version"),
               "user_id": service.user_id}
    grouped, unranked, deleted = {}, [], []
    unresolved = []
    for legacy in service.legacy_records():
        if (legacy.get("catalog_id") or legacy.get("exercise_id")) != exercise_id:
            continue
        available = _time(legacy.get("available_at"))
        if available and available > cutoff:
            continue
        unresolved.append({**legacy, "temporal_provenance": "legacy_current_inventory_not_asof",
                           "daily_fact_limitations": ["legacy_visibility_or_condition_unknown"],
                           "daily_comparability": daily_comparability(legacy, current)})
    for original in raw.values():
        row = deepcopy(original)
        row_exercise = row.get("catalog_id") or row.get("exercise_id") or (row.get("condition") or {}).get("exercise_id")
        if row_exercise != exercise_id or row.get("session_id") == instance["session_id"]:
            continue
        session = sessions.get(row.get("session_id"), {})
        when = _time(row.get("ended_at") or row.get("started_at"))
        if when and when > cutoff:
            continue
        session_when = _time(session.get("started_at"))
        if session_when and session_when > cutoff:
            continue
        row.update(session_status=session.get("session_status"),
                   session_started_at=session.get("started_at"),
                   session_deleted_at=session.get("deleted_at"),
                   session_uuid=session.get("session_uuid"),
                   daily_comparability=daily_comparability(row, current),
                   instance_position=instances.get(row.get("session_exercise_id"), {}).get("position"))
        row["daily_fact_limitations"] = []
        if not when:
            row["daily_fact_limitations"].append("set_occurrence_time_unknown")
        # A real parent's actual start is a known session date, not import time.
        rank_time = when or session_when
        row["daily_occurrence_time"] = rank_time.isoformat() if rank_time else None
        row["daily_occurrence_time_source"] = ("set_actual_time" if when else "session_started_at" if session_when else None)
        grouped.setdefault(row.get("session_id"), []).append(row)
        if (_observed(row) and not rank_time and not row.get("deleted_at")
                and not row.get("session_deleted_at")):
            unranked.append(row)
    candidates = []
    for identity, rows in grouped.items():
        observed = [r for r in rows if _observed(r) and not r.get("deleted_at") and not r.get("session_deleted_at")]
        removed = [r for r in rows if _observed(r) and (r.get("deleted_at") or r.get("session_deleted_at"))]
        if removed:
            times = [_time(r["daily_occurrence_time"]) for r in removed if r["daily_occurrence_time"]]
            deleted.append({"session_id": identity, "session_deleted_at": sessions.get(identity, {}).get("deleted_at"),
                            "occurred_at": max(times).isoformat() if times else None,
                            "set_uuids": [r.get("set_uuid") for r in removed],
                            "reason": "deleted_actuals_excluded_from_latest_selection"})
        times = [_time(r["daily_occurrence_time"]) for r in observed if r["daily_occurrence_time"]]
        if times:
            candidates.append((max(times), identity))
    candidates.sort(key=lambda pair: (pair[0], str(pair[1])))
    tied = []
    if candidates:
        latest_time = candidates[-1][0]
        tied = [identity for when, identity in candidates if when == latest_time]
    identity = tied[0] if len(tied) == 1 else None
    rows = grouped.get(identity, [])
    rows.sort(key=lambda r: (r.get("instance_position") if r.get("instance_position") is not None else float("inf"),
                              r.get("set_number") if r.get("set_number") is not None else float("inf"),
                              str(r.get("id")), str(r.get("set_uuid"))))
    limitations = ["recorded_sets_do_not_establish_complete_session_coverage",
                   "historical_performance_is_observation_not_current_capacity"]
    if unranked:
        limitations.append("unknown_occurrence_time_cannot_order_all_history")
    if unresolved:
        limitations.append("legacy_inventory_does_not_establish_asof_history")
    if len(tied) > 1:
        limitations.append("latest_session_time_tied_no_unique_latest")
    if deleted:
        limitations.append("deleted_actuals_excluded_history_retained")
    session = sessions.get(identity, {})
    active = [r for r in rows if _observed(r) and not r.get("deleted_at")]
    comparable = [r for r in active if r["daily_comparability"]["comparable"]]
    if unranked:
        status = "history_time_ambiguous"
    elif identity is None:
        status = ("history_time_ambiguous" if tied or unranked else
                  "history_visibility_unknown" if unresolved else "no_history")
    else:
        status = "history_available" if comparable else "history_not_comparable"
        if session.get("session_status") != "completed":
            limitations.append("latest_session_not_completed")
        if any(r.get("completion_state") in {"draft", "in_progress"} for r in rows):
            limitations.append("latest_session_contains_unfinished_records")
        if len(comparable) != len(active):
            limitations.append("some_latest_records_not_physically_comparable")
    latest = ({**{key: session.get(key) for key in ("id", "session_uuid", "session_status", "revision", "started_at", "ended_at", "available_at", "deleted_at")},
               "status": session.get("session_status"),
               "latest_known_time_only": bool(unranked),
               "occurred_at": candidates[-1][0].isoformat(),
               "days_since": (cutoff - candidates[-1][0]).total_seconds() / 86400,
               "recorded_set_uuids": [r["set_uuid"] for r in rows]} if identity is not None else None)
    selection = {"match_version": MATCH_VERSION, "cutoff_time": cutoff_time,
                 "search_scope": "all_visible_training_events_no_history_horizon",
                 "current_session_excluded": instance["session_id"],
                 "candidate_sessions": [identity for _, identity in candidates],
                 "tied_latest_session_ids": tied if len(tied) > 1 else [],
                 "deleted_history": deleted,
                 "task_mapping": [{"set_uuid": r["set_uuid"], "session_exercise_id": r.get("session_exercise_id"),
                    "strict_task_id": r["daily_comparability"]["strict_task_id"],
                    "daily_identity": r["daily_comparability"]["daily_identity"]} for r in rows]}
    older = [{"session_id": previous_id, "occurred_at": when.isoformat(),
              "status": sessions.get(previous_id, {}).get("session_status"),
              "records": grouped[previous_id]} for when, previous_id in candidates
             if previous_id != identity]
    stable_selection = {key: value for key, value in selection.items() if key != "cutoff_time"}
    return {"status": status, "match_version": MATCH_VERSION, "latest_session": latest,
            "latest_known_time_only": bool(unranked and latest),
            "records": rows, "unranked_records": unranked, "limitations": limitations,
            "unresolved_inventory": unresolved,
            "older_sessions": older,
            "selection": selection, "selection_hash": canonical_hash([stable_selection, rows, unranked, unresolved, older]),
            "comparable_set_uuids": [r["set_uuid"] for r in comparable]}
