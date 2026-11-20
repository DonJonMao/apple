"""Read-only review of recorded exercise order and comparable set observations.

This is a descriptive workflow, not a new physiological metric. It preserves
individual loads/RIR and never uses total tonnage as a common stimulus scale.
Optional source explanations use the existing STR-15 scientific and permission
contracts, retrieved afresh; frozen retrieval receipts confer no current rights.
"""
from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

from healthzip.science.contracts import instant

from .daily_history import daily_comparability
from .semantics import TrainingError, timestamp

VERSION = "exercise-sequence-review-1.0.0"


def _instance(session, catalog_id):
    matches = [item for item in session["exercises"]
               if item["catalog_id"] == catalog_id and not item.get("deleted_at")]
    if len(matches) != 1:
        raise TrainingError("所选动作在每场训练中须恰好有一个实例；重复实例请先在历史中核对")
    return matches[0]


def _work_sets(instance):
    return [row for row in instance["sets"] if row.get("completion_state") == "completed"
            and not row.get("deleted_at") and row.get("set_type") == "work"]


def _observations(rows):
    keys = ("set_uuid", "set_number", "load_value", "load_unit", "reps", "rir",
            "duration_s", "distance_m", "started_at", "ended_at", "rest_recorded_s",
            "quality_status", "pain_flag", "completion_state", "revision")
    return [{**{key: row.get(key) for key in keys},
             "load_basis": (row.get("condition") or {}).get("load_basis", "unknown")}
            for row in rows]


def _pairs(previous, current):
    pairs = []
    for old, new in zip(previous, current):
        comparable = daily_comparability(old, new)
        same_load = (old.get("load_value") is not None and new.get("load_value") is not None
                     and old["load_value"] == new["load_value"]
                     and old.get("load_unit") is not None
                     and old["load_unit"] == new["load_unit"])
        bodyweight = ((old.get("condition") or {}).get("load_basis") == "bodyweight_no_external"
                      and old.get("load_value") is None and new.get("load_value") is None)
        comparable_load = comparable["comparable"] and (same_load or bodyweight)
        pairs.append({"previous_set_id": old["set_uuid"], "current_set_id": new["set_uuid"],
            "comparable": comparable_load, "condition_check": comparable,
            "load_value": new.get("load_value"), "load_unit": new.get("load_unit"),
            "previous_reps": old.get("reps"), "current_reps": new.get("reps"),
            "previous_rir": old.get("rir"), "current_rir": new.get("rir"),
            "reps_change": new["reps"] - old["reps"] if comparable_load
                and old.get("reps") is not None and new.get("reps") is not None else None,
            "rir_change": new["rir"] - old["rir"] if comparable_load
                and old.get("rir") is not None and new.get("rir") is not None else None})
    return pairs


def _background(svc, session, cutoff, timezone_name):
    from healthzip.db.temporal_schema import samples_as_of
    from healthzip.science import evaluate

    end = instant(session["started_at"])
    start = end - timedelta(hours=24)
    records = []
    for sample in samples_as_of(svc.repo, cutoff, "health_sample", window_start=start.isoformat(),
                                window_end=end.isoformat(), canonical_types=["sleep_stage"]):
        # Do not include observations that ended after the training began.
        if instant(sample["end_utc"]) > end:
            continue
        records.append({**sample, "record_kind": "health_sample", "id": f"health_sample:{sample['id']}",
                        "event_start": sample["start_utc"], "event_end": sample["end_utc"]})
    metric = evaluate("REPORT-STATE-SUMMARY", records, cutoff_time=cutoff,
        window_start=start.isoformat(), window_end=end.isoformat(),
        context={"timezone": timezone_name, "retrospective": True})
    sleep = [point for point in metric.get("daily_facts", [])
             if point.get("series_id") == "observed_sleep_by_wake_date" and point.get("value", 0) > 0]
    previous = svc.conn.execute("SELECT s.id,s.started_at FROM strength_session s "
        "WHERE s.user_id=? AND s.deleted_at IS NULL AND julianday(s.started_at)<julianday(?) "
        "AND EXISTS (SELECT 1 FROM strength_set g WHERE g.session_id=s.id AND g.deleted_at IS NULL "
        "AND g.completion_state='completed') ORDER BY julianday(s.started_at) DESC LIMIT 1",
        (svc.user_id, session["started_at"])).fetchone()
    return {"training_started_at": session["started_at"], "sleep_window": metric["window"],
            "sleep": sleep, "sleep_metric": metric,
            "previous_recorded_training_at": previous["started_at"] if previous else None,
            "hours_since_previous_recorded_training": (end - instant(previous["started_at"])).total_seconds() / 3600 if previous else None,
            "visibility": "retrospective_currently_available_records_not_pretraining_prediction"}


def _current_evidence(svc, sessions, rows, *, cutoff, knowledge_root, context_id):
    """Optional explicit action. Reuse MetricResult and the current rights gate."""
    from healthzip.knowledge import KnowledgeWorkbench
    from healthzip.science import evaluate
    from healthzip.workflows.evidence import local_context
    from healthzip.workflows.storage import context_as_of

    first = min(instant(session["started_at"]) for session in sessions)
    last = max(instant(session.get("ended_at") or session["started_at"]) for session in sessions)
    end = min(last + timedelta(microseconds=1), instant(cutoff))
    canonical = [{**row, "record_kind": "strength_set", "raw_id": row["id"],
                  "id": f"strength_set:{row['set_uuid']}", "event_end": row.get("ended_at"),
                  "event_start": row.get("started_at") or row.get("ended_at")}
                 for row in rows]
    metric = evaluate("STR-15", canonical, cutoff_time=cutoff, window_start=first.isoformat(),
                      window_end=end.isoformat(), context={"retrospective": True})
    result = {"metric_result": metric, "current_checked": False, "claims": [], "spans": []}
    root = Path(knowledge_root)
    if not all((root / name).is_file() for name in ("sources.sqlite3", "theories.sqlite3")):
        return {**result, "status": "source_unavailable"}
    if metric.get("value") is None:
        return {**result, "status": "metric_requirements_missing"}
    declaration = context_as_of(svc.repo, context_id, cutoff, "retrospective") if context_id else {"values": {}}
    workbench = KnowledgeWorkbench(root)
    try:
        import json
        releases = workbench.lib.sources.execute(
            "SELECT release_id,manifest_json FROM index_release ORDER BY created_at DESC")
        release = next((row[0] for row in releases
                        if json.loads(row[1]).get("candidate_scope_version")), None)
        if not release:
            return {**result, "status": "compatible_release_missing"}
        context = local_context("STR-15", metric, sessions, declaration)
        protocols = {(row.get("condition") or {}).get("reference_protocol", {}).get("protocol_id")
                     for row in rows if isinstance((row.get("condition") or {}).get("reference_protocol"), dict)}
        if len(protocols) == 1 and None not in protocols and len(rows) == sum(
                isinstance((row.get("condition") or {}).get("reference_protocol"), dict) for row in rows):
            context["measurement_protocol"] = next(iter(protocols))
        response = workbench.retrieve_for_metric("STR-15", "strength", metric,
            context, release,
            mode="lexical", candidate_scope="reviewed_metric", query_form="en", k=6)
        allowed = response.get("capability_permissions", {}).get("source_explanation", False)
        return {**result, "current_checked": True, "status": response["status"],
                "source_explanation": bool(allowed),
                "claims": response.get("matched_claims", []) if allowed else [],
                "spans": [{key: span.get(key) for key in ("source_id", "source_version", "span_id",
                    "source_metadata", "section_path", "locator")} for span in
                    response.get("evidence_spans", [])] if allowed else [],
                "limitations": response.get("limitations", []),
                "conflicts": response.get("conflicts", [])}
    finally:
        workbench.close()


def review_sequence(svc, session_id, prior_session_id, preceding_catalog_id, target_catalog_id,
                    *, knowledge=None, include_evidence=False, knowledge_root=".local/knowledge",
                    context_id=None, timezone_name="Asia/Shanghai"):
    """Compare two explicit sessions; no auto-selection of a favourable baseline.

    ``knowledge`` is accepted only for compatibility; a historical permission
    receipt is deliberately not trusted. Set include_evidence for fresh local
    retrieval, ideally in an independent UI background worker.
    """
    if str(session_id) == str(prior_session_id) or preceding_catalog_id == target_catalog_id:
        raise TrainingError("请选择两场不同训练，以及不同的前置和后续动作")
    owns = not svc.conn.in_transaction
    if owns:
        svc.conn.execute("BEGIN")
    try:
        previous, current = svc.get_session(prior_session_id), svc.get_session(session_id)
        if any(session.get("deleted_at") for session in (previous, current)):
            raise TrainingError("所选训练已删除，请重新选择")
        if not all(session.get("started_at") for session in (previous, current)):
            raise TrainingError("所选训练缺少实际开始日期，暂不能确定先后")
        if instant(previous["started_at"]) >= instant(current["started_at"]):
            raise TrainingError("比较训练必须发生在本次训练之前")
        before = [_instance(session, preceding_catalog_id) for session in (previous, current)]
        after = [_instance(session, target_catalog_id) for session in (previous, current)]
        cutoff = timestamp()
        events = svc.events_as_of(cutoff_time=cutoff, _session_ids=[previous["id"], current["id"]])
        history = svc.history_as_of(cutoff_time=cutoff, include_incomplete=True, _events=events)
        visible = {row["set_uuid"]: row for row in history if row.get("set_uuid")}
        before_rows = [[{**row, **visible.get(row["set_uuid"], {})} for row in _work_sets(item)]
                       for item in before]
        after_rows = [[{**row, **visible.get(row["set_uuid"], {})} for row in _work_sets(item)]
                      for item in after]
        backgrounds = [_background(svc, session, cutoff, timezone_name) for session in (previous, current)]
        revisions = {"data_version": svc.data_version(),
                     "sessions": [session["revision"] for session in (previous, current)]}
        if owns:
            svc.conn.commit()
    except BaseException:
        if owns:
            svc.conn.rollback()
        raise
    order = [left["position"] < right["position"] for left, right in zip(before, after)]
    order_changed = [(before[0]["position"], after[0]["position"])] != [(before[1]["position"], after[1]["position"])]
    missing, observations = [], []
    preceding_name = before[1]["exercise"]["name"]
    target_name = after[1]["exercise"]["name"]
    observations.append(f"{previous['started_at'][:10]} 与 {current['started_at'][:10]}：按两场保存的动作顺序核对。")
    observations.append(f"{preceding_name}已完成工作组 {len(before_rows[0])} → {len(before_rows[1])}；各组负荷、次数与 RIR 分别列出。")
    if not all(order):
        missing.append("至少一场中前置动作并未排在所选后续动作之前")
    if order_changed:
        missing.append("两场动作位置改变，不能把差异只归于前置训练量")
    all_rows = sum(before_rows + after_rows, [])
    if not all_rows or any(row.get("rest_recorded_s") is None for row in all_rows):
        missing.append("部分组未记录实际休息时长")
    if any(row.get("rir") is None for row in all_rows):
        missing.append("部分组缺少本次实际 RIR，努力程度不可完全对照")
    if any(row.get("started_at") is None for row in all_rows):
        missing.append("部分组缺少实际开始时刻，执行顺序主要依据保存的动作次序")
    for leading, trailing in zip(before_rows, after_rows):
        ends = [instant(row["ended_at"]) for row in leading if row.get("ended_at")]
        starts = [instant(row["started_at"]) for row in trailing if row.get("started_at")]
        if ends and starts and max(ends) > min(starts):
            missing.append("组时间显示动作可能交错执行，不能视为完整前置后再做后续")
    comparisons = _pairs(after_rows[0], after_rows[1])
    preceding_comparisons = _pairs(before_rows[0], before_rows[1])
    if len(after_rows[0]) != len(after_rows[1]):
        missing.append("两场后续动作的完成工作组数不同，仅按已记录顺序并列对应组")
    if not comparisons or any(not pair["comparable"] for pair in comparisons):
        missing.append("后续动作部分器械、负荷口径、ROM、侧别或重量不完整／不同，相关组不计算次数变化")
    for index, pair in enumerate(comparisons, 1):
        if pair["reps_change"] is not None:
            observations.append(f"{target_name}第 {index} 个已完成工作组：{pair['load_value']} {pair['load_unit'] or ''}，"
                f"{pair['previous_reps']} → {pair['current_reps']} 次；RIR "
                f"{pair['previous_rir'] if pair['previous_rir'] is not None else '未记录'} → "
                f"{pair['current_rir'] if pair['current_rir'] is not None else '未记录'}。")
    evidence = {"status": "not_requested", "current_checked": False, "claims": [], "spans": []}
    if include_evidence:
        try:
            evidence = _current_evidence(svc, [previous, current], all_rows, cutoff=cutoff,
                knowledge_root=knowledge_root, context_id=context_id)
        except (ValueError, KeyError, OSError, RuntimeError):
            evidence = {**evidence, "status": "unavailable"}
    explanations = []
    comparable_decline = any(pair["reps_change"] is not None and pair["reps_change"] < 0 for pair in comparisons)
    preceding_increase = len(before_rows[1]) > len(before_rows[0]) or any(
        pair["reps_change"] is not None and pair["reps_change"] > 0 for pair in preceding_comparisons)
    if evidence.get("source_explanation") and all(order) and comparable_decline and preceding_increase:
        for claim in evidence["claims"]:
            statements = claim.get("statements", [])
            text = str(statements)
            scope_matches = any(term in text.lower() for term in ("exercise order", "preceding", "prior exercise", "动作顺序", "前置", "前序"))
            if scope_matches and ("fatigue" in text.lower() or "疲劳" in text):
                explanations.append({"text": "前置训练疲劳可作为待核对的可能解释，已有来源说明了动作顺序的适用边界。"
                    "该依据不证明前置动作造成了后续下降，也不推断肌肉损伤或恢复不全。",
                    "claim_id": claim.get("claim_id"), "claim_version": claim.get("claim_version"),
                    "statements": statements, "scope": claim.get("scope"),
                    "evidence_span_ids": claim.get("evidence_span_ids", [])})
    if not explanations:
        missing.append("尚无本次可用且当前审核通过的机制解释；不能由先后关系推断原因")
    for label, background in zip(("比较场次", "本次场次"), backgrounds):
        gap = background["hours_since_previous_recorded_training"]
        if gap is None:
            missing.append(label + "之前没有可定位的已完成训练，训练间隔未知")
        else:
            observations.append(f"{label}距上一场有完成组的记录 {gap:.1f} 小时；未记录活动仍未知。")
        if not background["sleep"]:
            missing.append(label + "前24小时没有可用睡眠片段，不能假定睡眠相同")
        else:
            streams = list(dict.fromkeys(point["source_id"] for point in background["sleep"]))
            for point in background["sleep"]:
                try:
                    fields = ast.literal_eval(point["source_id"])
                    name = fields[0] if isinstance(fields, (list, tuple)) and fields else "未注明"
                except (ValueError, SyntaxError):
                    name = "未注明"
                source = f"来源{streams.index(point['source_id']) + 1}（{name or '未注明'}）"
                observations.append(f"{label}前24小时内，{source}在{point['date']}已观察睡眠 {point['value'] / 60:.2f} 小时（完整性未知）。")
    return {"version": VERSION, "cutoff_time": cutoff, "revisions": revisions,
        "session_ids": [previous["session_uuid"], current["session_uuid"]],
        "observations": observations, "possible_explanations": explanations,
        "next_steps": ["下次在相同器械与负荷口径下，按相同动作和组顺序记录表现，补记实际 RIR 与组间休息。",
                       "同时查看前置动作的工作组、各组次数及 RIR；一次只核对一个条件变化，不把总吨位当作同等刺激。"],
        "missing": list(dict.fromkeys(missing)), "evidence": evidence,
        "comparisons": comparisons, "preceding_comparisons": preceding_comparisons,
        "backgrounds": backgrounds, "session_gap_hours": (instant(current["started_at"]) - instant(previous["started_at"])).total_seconds() / 3600,
        "order": {"preceding_before_target": order, "changed": order_changed,
                  "basis": "recorded_instance_position_with_available_actual_time_checks"},
        "preceding": {"name": preceding_name, "previous": _observations(before_rows[0]), "current": _observations(before_rows[1])},
        "target": {"name": target_name, "previous": _observations(after_rows[0]), "current": _observations(after_rows[1])},
        "identity": "descriptive_record_review_not_causal_confirmation"}
