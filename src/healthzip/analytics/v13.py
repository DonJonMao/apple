"""Repository adapters for the single v1.3 MetricResult computation path."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from healthzip.db.temporal_schema import current_source_rows, samples_as_of
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
    def known_equal(first, second):
        return None if first in (None, "", "unknown") or second in (None, "", "unknown") else first == second
    checks = [known_equal(observed.get("condition_key"), condition.get("condition_key"))]
    if load is not None:
        checks.extend((known_equal(observed.get("load_unit"), expected_unit),
                       known_equal(observed.get("load_basis"), change.get("load_basis"))))
    checks.extend((known_equal(observed.get("quality_status"), "acceptable"),
                   known_equal(observed.get("status"), "completed")))
    quality_comparable = False if False in checks else None if None in checks else True
    return {"recommendation_id": recommendation["candidate_id"],
            "strategy": recommendation["input_snapshot"].get("strategy"),
            "task_id": recommendation["input_snapshot"].get("advice_context", {}).get("task_id"),
            "rule_versions": [{"rule_id": p.get("rule_id", p.get("theory_id")), "version": p.get("version")}
                              for p in recommendation["input_snapshot"].get("theory_authority", {}).get("principles", [])] or None,
            "adoption": {"accepted": "adopted", "modified": "partially_adopted", "declined": "not_adopted"}.get(latest.get("user_choice")),
            "execution_state": latest.get("execution_state"), "nonexecution_reason": latest.get("nonexecution_reason"),
            "frozen_targets": targets, "actual": {k: finite(observed.get(k)) for k in targets},
            "quality_comparable": quality_comparable,
            "created_at": recommendation["created_at"], "feedback_missing": not bool(latest),
            "available_at": latest.get("recorded_at") or recommendation["created_at"],
            "event_end": latest.get("occurred_at") or recommendation["created_at"],
            "source_record_ids": latest.get("actual_record_ids", [])}


def snapshot(repo, cutoff_time: str, *, retrospective=False, window_start=None, window_end=None,
             canonical_types=None, include_sources=True):
    service = TrainingService(repo)
    records = []
    source_counts = {}
    for table in (("health_sample", "body_measurement", "subjective_log") if include_sources else ()):
        rows = (current_source_rows(repo, table, window_start=window_start, window_end=window_end,
                                    canonical_types=canonical_types if table == "health_sample" else None)
                if retrospective else samples_as_of(repo, cutoff_time, table, window_start=window_start,
                    window_end=window_end, canonical_types=canonical_types if table == "health_sample" else None))
        source_counts[table] = len(rows)
        for row in rows:
            if row.get("record_status", "active") != "active":
                continue
            row.update(record_kind=table, raw_id=row["id"], id=f"{table}:{row['id']}")
            # CSV body measurements preserve an explicit source column. It is
            # provenance, not an inferred scale or measurement protocol.
            row["source_name"] = row.get("source_name") or row.get("source_bundle_id") or row.get("source")
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
                     "query_plan": {"window_start": window_start, "window_end": window_end,
                                    "canonical_types": canonical_types, "source_rows_returned": source_counts,
                                    "revision_order": "latest_visible_before_support_filter"},
                     "session_plans": plans, "retrospective": retrospective,
                     "legacy_unresolved_inventory": {"count": len(legacy), "record_ids": [r["id"] for r in legacy],
                        "scope": "current_inventory_not_asof; execution_and_historical_visibility_unknown"}}


def analyze(repo, window_days=30, *, cutoff_time=None, timezone_name="Asia/Shanghai",
            context=None, retrospective=False, period=None, use_cache=True):
    from healthzip.analytics.cache import cached

    # Automatic views refresh at most once a minute unless input versions change.
    # This is a documented UI cache cadence; the exact computed cutoff is shown.
    now = datetime.now(timezone.utc)
    arguments = {"window_days": window_days, "cutoff": cutoff_time or now.replace(second=0, microsecond=0).isoformat(),
                 "mode": "explicit" if cutoff_time else "auto", "timezone": timezone_name,
                 "context": context, "retrospective": retrospective, "period": period}
    def compute():
        value = _analyze_uncached(repo, window_days, cutoff_time=cutoff_time or now.isoformat(),
                                  timezone_name=timezone_name, context=context, retrospective=retrospective, period=period)
        value["cutoff_mode"] = "explicit" if cutoff_time else "auto"
        value["cache_policy"] = {"automatic_refresh_seconds": 60, "parameter_kind": "product_parameter",
                                 "revision_invalidated": True}
        return value
    return cached(repo, "canonical", arguments, compute) if use_cache else compute()


def _analyze_uncached(repo, window_days=30, *, cutoff_time=None, timezone_name="Asia/Shanghai",
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
    # Sleep24h declares a 24-hour lookback; all other observed metrics use the
    # requested window. Calendar-day membership remains in the science layer.
    query_start = min(start, cutoff - timedelta(hours=24))
    if context and context.get("baseline_window"):
        query_start = min(query_start, datetime.fromisoformat(context["baseline_window"]["start"].replace("Z", "+00:00")))
    required_types = {"resting_heart_rate_bpm", "hrv_sdnn_ms", "sleep_stage", "body_mass_kg", "basal_energy_kcal", "active_energy_kcal"}
    if context and context.get("baseline_canonical_type"):
        required_types.add(context["baseline_canonical_type"])
    records, inherited = snapshot(repo, cutoff.isoformat(), retrospective=retrospective,
                                  window_start=query_start.isoformat(), window_end=end.isoformat(), canonical_types=sorted(required_types))
    from healthzip.science.contracts import Window, select_as_of
    plans, _ = select_as_of(inherited["session_plans"], Window(start.isoformat(), end.isoformat(), cutoff.isoformat(), timezone_name))
    merged = {**inherited, "plan_snapshot": {"sets": [s for p in plans for s in p["sets"]]} if plans else None, **(context or {})}
    metrics = evaluate_all(records, cutoff_time=cutoff.isoformat(), window_start=start.isoformat(),
                           window_end=end.isoformat(), context={**merged, "timezone": timezone_name})
    strength_tasks = {}
    for metric_id, metric in metrics.items():
        for task in metric.get("task_results", []):
            entry = strength_tasks.setdefault(task["task_id"], {k: v for k, v in task.items() if k != "metric"} | {"metrics": {}})
            entry["metrics"][metric_id] = task["metric"]
    data_hash = hashlib.sha256(json.dumps({"records": records, "context": merged}, sort_keys=True, default=str).encode()).hexdigest()
    return {"metrics": metrics, "strength_tasks": list(strength_tasks.values()), "cutoff_time": cutoff.isoformat(), "window_start": start.isoformat(),
            "cutoff_mode": "explicit" if cutoff_time is not None else "auto",
            "window_end": end.isoformat(), "period": period, "timezone": timezone_name, "data_hash": data_hash,
            "data_version": inherited["data_version"], "algorithm_version": "healthzip-v1.4.0",
            "query_plan": inherited["query_plan"],
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


def view_task_interval(repo, analysis, task_id: str, *, family_id: str, alpha_total: float,
                       metric_id: str = "STR-20", context=None, outcome_series_id=None):
    """An explicit local view spends one registered look for this exact snapshot."""
    from healthzip.science import ParameterRegistry, evaluate
    from healthzip.science.contracts import Window, canonical_hash, select_as_of
    from healthzip.science.semantics import analysis_task, flatten_record, outcome_series

    if metric_id not in {"STR-20", "STR-22"} or not family_id.strip():
        raise ValueError("明确选择趋势区间或停滞复核，并填写共享分析家族标识")
    service = TrainingService(repo)
    if service.data_version() != analysis["data_version"]:
        raise ValueError("记录已变化，请重新生成分析后再查看区间")
    records, inherited = snapshot(repo, analysis["cutoff_time"], retrospective=analysis["retrospective"],
                                  window_start=analysis["window_start"], window_end=analysis["window_end"])
    window = Window(analysis["window_start"], analysis["window_end"], analysis["cutoff_time"], analysis["timezone"])
    available, _ = select_as_of([flatten_record(r) for r in records if r.get("record_kind") == "strength_set"],
                                window, retrospective=analysis["retrospective"])
    rows = [r for r in available if r.get("is_reference") and analysis_task(r)["task_id"] == task_id]
    if not rows:
        raise ValueError("所选任务没有已知参考记录")
    digest = canonical_hash({"records": rows, "window": window.as_dict(), "cutoff_time": analysis["cutoff_time"],
                             "data_version": str(analysis["data_version"])})
    task = next((task for task in analysis.get("strength_tasks", []) if task["task_id"] == task_id), None)
    if task is None or task["data_snapshot_hash"] != digest:
        raise ValueError("任务快照已变化，请重新生成分析")
    series = task["metrics"]["STR-19"].get("series_results", [])
    if len(series) > 1 and outcome_series_id is None:
        raise ValueError("该动作有多个负荷层，请明确选择要查看的同负荷描述序列")
    if outcome_series_id is not None:
        selected = next((s for s in series if s["outcome_series_id"] == outcome_series_id), None)
        if selected is None:
            raise ValueError("所选描述序列不属于本次任务快照")
        rows = [r for r in rows if outcome_series(r)["outcome_series_id"] == outcome_series_id]
        digest = canonical_hash({"records": rows, "window": window.as_dict(), "cutoff_time": analysis["cutoff_time"],
                                 "data_version": str(analysis["data_version"])})
        if digest != selected["data_snapshot_hash"]:
            raise ValueError("描述序列快照已变化，请重新生成分析")
    if repo.conn.in_transaction:
        raise ValueError("存在尚未完成的记录事务，请先保存记录")
    registry = ParameterRegistry(str(repo.path))
    try:
        old = registry.conn.execute("SELECT alpha_total FROM analysis_family WHERE family_id=?", (family_id,)).fetchone()
        if old is None:
            registry.register_family(family_id, alpha_total, {"declared_before": datetime.now(timezone.utc).isoformat(),
                "metrics": ["STR-20", "STR-22"], "scope": "shared_across_actions_and_trend_decisions",
                "origin": "explicit_local_analysis_view"})
        elif old["alpha_total"] != alpha_total:
            raise ValueError("该分析家族的总错误预算已冻结，不能修改")
        allocation = registry.allocate_look(family_id, digest, metric_id, data_version=analysis["data_version"],
                                           task_id=task_id, cutoff_time=analysis["cutoff_time"], outcome_series_id=outcome_series_id)
    finally:
        registry.close()
    bound = {**inherited, **(context or {}), "timezone": analysis["timezone"], "look_allocation": allocation,
             "look_registry_path": str(repo.path), "look_metric_id": metric_id, "task_id": task_id}
    if outcome_series_id is not None:
        bound["outcome_series_id"] = outcome_series_id
    arguments = {"cutoff_time": analysis["cutoff_time"], "window_start": window.start, "window_end": window.end, "context": bound}
    metric = evaluate(metric_id, rows, **arguments)
    metric["look_audit"] = evaluate("STR-24", rows, **arguments)
    return metric


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
