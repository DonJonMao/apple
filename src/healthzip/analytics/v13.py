"""Repository adapters for the single v1.3 MetricResult computation path."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from healthzip.db.temporal_schema import samples_as_of
from healthzip.training.service import TrainingService


def _outcome(recommendation, latest, records):
    """Evaluate exactly the frozen task; matching repetitions alone is insufficient."""
    from healthzip.science.contracts import finite, instant
    from healthzip.science.semantics import flatten_record
    from healthzip.science.strength import reference_rows

    candidate = recommendation["candidate"]
    target = candidate.get("target_range") or {}
    change = candidate.get("proposed_change") or {}
    condition = recommendation["input_snapshot"].get("condition") or {}
    targets = {}
    for key in ("reps", "rir", "duration_s", "distance_m"):
        low, high = finite(target.get(key + "_min")), finite(target.get(key + "_max"))
        if low is not None and high is not None:
            targets[key] = {"min": low, "max": high}
    load = finite(change.get("load"))
    if load is not None:
        targets["load_value"] = {"min": load, "max": load}
    elif candidate.get("action_kind") == "collect_or_confirm_evidence":
        targets = {}  # an evidence request is not a numerical task success trial
    referenced = []
    for row in records:
        if row.get("set_uuid") not in latest.get("actual_record_ids", []):
            continue
        observed = flatten_record(row)
        try:
            boundary = max(instant(recommendation["cutoff_time"]), instant(recommendation["created_at"]))
            after_candidate = instant(observed.get("started_at") or observed.get("ended_at")) > boundary
            before_feedback = instant(observed.get("ended_at")) <= instant(latest["occurred_at"])
        except (ValueError, KeyError):
            continue
        target_session = candidate.get("target_session")
        target_exercise = recommendation["input_snapshot"].get("session_exercise_id")
        if (after_candidate and before_feedback and target_session and target_exercise
                and observed.get("session_uuid") == target_session
                and observed.get("session_exercise_id") == target_exercise
                and not observed.get("conflicted") and not observed.get("deleted_at")
                and observed.get("set_type", "work") == "work"):
            observed["_event_end"] = observed.get("ended_at")
            referenced.append(observed)
    reference = reference_rows(referenced, {})
    observed = reference[0] if len(reference) == 1 and latest.get("execution_state") == "executed" else {}
    expected_unit = change.get("load_unit")
    semantic_match = bool(observed.get("condition_key") and observed["condition_key"] == condition.get("condition_key"))
    if load is not None:
        semantic_match = semantic_match and expected_unit is not None and observed.get("load_unit") == expected_unit
        semantic_match = semantic_match and observed.get("load_basis") == change.get("load_basis")
    return {"recommendation_id": recommendation["candidate_id"],
            "adoption": {"accepted": "adopted", "modified": "partially_adopted", "declined": "not_adopted"}.get(latest.get("user_choice")),
            "execution_state": latest.get("execution_state"), "nonexecution_reason": latest.get("nonexecution_reason"),
            "frozen_targets": targets, "actual": {k: finite(observed.get(k)) for k in targets},
            "quality_comparable": semantic_match and observed.get("quality_status") == "acceptable" and observed.get("status") == "completed",
            "created_at": recommendation["created_at"], "feedback_missing": not bool(latest),
            "available_at": latest.get("recorded_at") or recommendation["created_at"],
            "event_end": latest.get("occurred_at") or recommendation["created_at"],
            "source_record_ids": latest.get("actual_record_ids", [])}


def snapshot(repo, cutoff_time: str, *, retrospective=False):
    service = TrainingService(repo)
    records = []
    for table in ("health_sample", "body_measurement", "subjective_log"):
        rows = ([dict(r) for r in repo.rows(f"SELECT * FROM {table}")]
                if retrospective else samples_as_of(repo, cutoff_time, table))
        for row in rows:
            if row.get("record_status", "active") != "active":
                continue
            row.update(record_kind=table, raw_id=row["id"], id=f"{table}:{row['id']}")
            row["event_end"] = row.get("end_utc") or row.get("measured_at") or row.get("observed_at")
            row["event_start"] = row.get("start_utc") or row["event_end"]
            if retrospective:
                row["temporal_provenance"] = row.get("temporal_provenance") or "retrospective_snapshot"
            records.append(row)
    sets = ([dict(r) for r in repo.rows("SELECT * FROM strength_set WHERE deleted_at IS NULL")]
            if retrospective else service.history_as_of(cutoff_time=cutoff_time, include_incomplete=True))
    legacy = service.legacy_records()
    if not retrospective:
        sets.extend({**r, "source_available_at": r.get("available_at"), "available_at": None,
                     "temporal_provenance": "legacy_current_inventory_not_asof"} for r in legacy)
    for row in sets:
        row = dict(row)
        row.update(record_kind="strength_set", raw_id=row["id"], id=f"strength_set:{row.get('set_uuid') or row['id']}")
        row["event_end"] = row.get("ended_at")
        row["event_start"] = row.get("started_at")
        row["is_reference"] = bool(row.get("reference_set"))
        records.append(row)
    sessions = ([dict(r) for r in repo.rows("SELECT * FROM strength_session WHERE deleted_at IS NULL")]
                if retrospective else service.sessions_as_of(cutoff_time=cutoff_time))
    for session in sessions:
        session["session_id"] = session["id"]
        session["event_end"] = session.get("ended_at")
        session["srpe_protocol"] = session.get("session_rpe_scale")
        session["srpe_collected_at"] = session.get("available_at")
    session_uuids = {s["id"]: s.get("session_uuid") for s in sessions}
    for row in records:
        if row.get("record_kind") == "strength_set":
            row["session_uuid"] = session_uuids.get(row.get("session_id"))
    # Capture original template-created set identities, including skipped/missing
    # sets. Later plan edits and extra sets cannot change this denominator.
    plans = []
    for event in service.audit_events():
        if event.get("action") != "start_session" or event.get("status") != "applied":
            continue
        if datetime.fromisoformat(event["recorded_at"]) > datetime.fromisoformat(cutoff_time.replace("Z", "+00:00")):
            continue
        original = event.get("after") or {}
        if not original.get("plan_snapshot") or original.get("id") not in {s["id"] for s in sessions}:
            continue
        planned = [{"id": s["set_uuid"], "session_id": original["id"], "targets": s.get("planned", {})}
                   for s in original.get("sets", [])]
        slots = original["plan_snapshot"].get("client_plan_slots", [])
        if slots:
            planned = [{"id": s["set_uuid"], "session_id": original["id"], "targets": s["targets"]}
                       for s in slots]
        plans.append({"session_id": original["id"], "event_end": original["started_at"],
                      "available_at": event["recorded_at"], "sets": planned})
    planned_ids = {s["id"] for p in plans for s in p["sets"]}
    for row in records:
        if row.get("set_uuid") in planned_ids:
            row["planned_set_id"] = row["set_uuid"]
    outcomes = []
    bound = datetime.fromisoformat(cutoff_time.replace("Z", "+00:00"))
    for recommendation in service.list_recommendations():
        if datetime.fromisoformat(recommendation["created_at"]) > bound:
            continue
        feedback = [x for x in recommendation["feedback"]
                    if datetime.fromisoformat(x["recorded_at"]) <= bound and datetime.fromisoformat(x["occurred_at"]) <= bound]
        latest = feedback[-1] if feedback else {}
        outcomes.append(_outcome(recommendation, latest, records))
    return records, {"sessions": sessions, "recommendation_outcomes": outcomes, "data_version": service.data_version(),
                     "session_plans": plans, "retrospective": retrospective,
                     "legacy_unresolved_inventory": {"count": len(legacy), "record_ids": [r["id"] for r in legacy],
                        "scope": "current_inventory_not_asof; execution_and_historical_visibility_unknown"}}


def analyze(repo, window_days=30, *, cutoff_time=None, timezone_name="Asia/Shanghai",
            context=None, retrospective=False, period=None):
    from healthzip.science import evaluate_all

    cutoff = datetime.fromisoformat(cutoff_time.replace("Z", "+00:00")) if cutoff_time else datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        raise ValueError("cutoff_requires_timezone")
    start = cutoff-timedelta(days=max(1, int(window_days)))
    end = cutoff
    if period:
        local = cutoff.astimezone(ZoneInfo(timezone_name))
        if period == "month":
            start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = (start.replace(day=28)+timedelta(days=4)).replace(day=1)
        elif period == "week":
            start = (local-timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            end = start+timedelta(days=7)
        else:
            raise ValueError("unknown_calendar_period")
    records, inherited = snapshot(repo, cutoff.isoformat(), retrospective=retrospective)
    from healthzip.science.contracts import Window, select_as_of
    plans, _ = select_as_of(inherited["session_plans"], Window(start.isoformat(), end.isoformat(), cutoff.isoformat(), timezone_name))
    merged = {**inherited, "plan_snapshot": {"sets": [s for p in plans for s in p["sets"]]} if plans else None, **(context or {})}
    metrics = evaluate_all(records, cutoff_time=cutoff.isoformat(), window_start=start.isoformat(),
                           window_end=end.isoformat(), context={**merged, "timezone": timezone_name})
    data_hash = hashlib.sha256(json.dumps({"records": records, "context": merged}, sort_keys=True, default=str).encode()).hexdigest()
    return {"metrics": metrics, "cutoff_time": cutoff.isoformat(), "window_start": start.isoformat(),
            "window_end": end.isoformat(), "period": period, "timezone": timezone_name, "data_hash": data_hash,
            "data_version": inherited["data_version"], "algorithm_version": "healthzip-v1.3",
            "legacy_unresolved_inventory": inherited["legacy_unresolved_inventory"],
            "retrospective": retrospective}


def persist(repo, result):
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
    run_id = hashlib.sha256(payload.encode()).hexdigest()
    repo.conn.execute("INSERT OR IGNORE INTO analysis_run(run_id,cutoff_time,computed_at,algorithm_version,data_hash,result_json) VALUES(?,?,?,?,?,?)",
                      (run_id, result["cutoff_time"], datetime.now(timezone.utc).isoformat(),
                       result["algorithm_version"], result["data_hash"], payload))
    service = TrainingService(repo)
    pending = service.pending_invalidations()
    if (pending and result["data_version"] == service.data_version()
            and all(datetime.fromisoformat(x["created_at"].replace("Z", "+00:00"))
                    <= datetime.fromisoformat(result["cutoff_time"].replace("Z", "+00:00")) for x in pending)):
        service.mark_recomputed(result["algorithm_version"], max(x["id"] for x in pending))
    repo.conn.commit()
    return run_id


def metric_card(metric):
    """Display/AI adapter consumes the calculated value without recalculation."""
    from healthzip.science import definitions
    title = definitions()[metric["metric_id"]]["title"]
    unit = metric.get("unit")
    status = metric["data_status"]
    summary = (f"{title}：{metric['value']} {unit or ''}。"
               if metric["value"] is not None else f"{title}：当前无法判断。")
    return {"id": metric["metric_id"], "title": title,
            "status": status, "summary": summary, "window": metric["window"],
            "facts": [{"metric": metric["metric_id"], "value": metric["value"], "unit": unit,
                       "window": metric["window"], "n": metric["valid_n"]}],
            "limitations": metric.get("limitations", [])+metric["reason_codes"],
            "allowed_actions": ["review_records", "continue_observation"],
            "source_feature_ids": metric["source_record_ids"],
            "algorithm_version": metric["algorithm_version"], "evidence_refs": metric["evidence_refs"]}
