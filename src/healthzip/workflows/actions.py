"""Prespecified action outcomes and append-only, visibility-safe reassessments."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

from healthzip.science.body_catalog import METRIC_CATALOG
from healthzip.science.contracts import canonical_hash, instant

VERSION = "action-outcomes-2.0"
EXECUTION = {"executed": "已执行", "partial": "部分执行", "not_executed": "未执行",
             "stopped": "已停止", "unknown": "执行情况未知", "unreported": "尚未填写执行情况"}
STREAM_FIELDS = ("source", "device", "protocol", "source_version")


def format_outcome_value(row, value, *, signed=False):
    from healthzip.analytics.display_format import format_measurement
    if row.get("type") == "strength":
        return "未知" if value is None else format(value, "+g" if signed else "g") + " 次"
    return format_measurement(value, row.get("unit"), kind=row.get("metric"), signed=signed)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def outcome_options(question, action_text):
    """Product defaults are explicit choices, never evidence of expected benefit."""
    options = []
    fields = sorted({r["metric"] for r in question.get("rows", []) if r.get("metric") in METRIC_CATALOG})
    if any(word in action_text for word in ("姿势", "测量时段", "测量时间", "相同条件称重")):
        metric = "hrv_sdnn_ms" if "SDNN" in action_text else "body_mass_kg"
        options.append({"kind": "measurement_conditions", "metric": metric,
                        "label": "实际测量时间、已记录姿势与可比记录覆盖"})
    if any(r.get("type") == "strength" for r in question.get("rows", [])):
        options.append({"kind": "training", "label": "已记录执行与同动作、同条件、同组位的完成次数"})
    if "睡眠" in action_text and "姿势" not in action_text:
        options.insert(0, {"kind": "metric", "metric": "sleep_stage", "label": "已记录睡眠时长：完整日代表值中位数"})
    if question.get("id") in {"E", "W8"} or any(word in action_text for word in ("打开", "核对原通知")):
        options.insert(0, {"kind": "check", "label": "核对任务的实际完成情况"})
    for metric in fields:
        options.append({"kind": "metric", "metric": metric,
                        "label": METRIC_CATALOG[metric]["title"] + "：完整日代表值中位数"})
    options.append({"kind": "check", "label": "核对任务的实际完成情况"})
    return list({(item["kind"], item.get("metric")): item for item in options}.values())


def proposed_definition(question, action_text, review_due, *, selected_at=None, planned_start=None,
                        primary=None, source_filter=()):
    """Readable proposal shown before the deliberate save; no repository mutation."""
    now = instant(selected_at) if selected_at else datetime.now(timezone.utc)
    start = instant(planned_start) if planned_start else now
    duration = instant(question["window"]["end"]) - instant(question["window"]["start"])
    if duration <= timedelta(0) or start < now:
        raise ValueError("观察范围须为正，计划开始不能早于选择时间。")
    options = outcome_options(question, action_text)
    chosen = primary or options[0]
    if not any(chosen.get("kind") == o["kind"] and chosen.get("metric") == o.get("metric") for o in options):
        raise ValueError("请选择本次行动提供的主要观察。")
    chosen = next(o for o in options if chosen.get("kind") == o["kind"] and chosen.get("metric") == o.get("metric"))
    due, end = instant(review_due), start + duration
    return {"version": VERSION, "primary": chosen, "question_id": question["id"],
            "question_result_id": question.get("fact_id"), "question_algorithm": question.get("analysis_version"),
            "evidence": question.get("evidence", question.get("knowledge", [])),
            "baseline_window": question["window"],
            "followup_window": {"start": start.isoformat(), "end": end.isoformat(),
                                "timezone": question["window"]["timezone"]},
            "review_due": due.isoformat(), "early_review": due < end,
            "source_filter": sorted(question.get("source_filter", source_filter) or []),
            "statistic": "complete_local_day_median" if chosen["kind"] == "metric" else
                         "median_of_all_comparable_recorded_sets" if chosen["kind"] == "training" else
                         "recorded_conditions_and_coverage" if chosen["kind"] == "measurement_conditions" else "reported_task_completion",
            "expectation": "仅观察，不预设改善方向或成功阈值；前后变化不自动归因于行动。",
            "window_policy": "观察窗口在选择时固定；实际执行起止另行记录，延迟或停止不移动窗口。"}


def _metric_observations(repo, metric, window, cutoff, sources):
    from healthzip.analytics.body_metrics import VERSION as metric_version
    from healthzip.analytics.body_metrics import analyze_body_metric
    result = analyze_body_metric(repo, metric, window_start=window["start"], window_end=window["end"],
        cutoff_time=cutoff, timezone_name=window["timezone"], source_filter=sources, with_model=False)
    entries = []
    for stream in result["value"]["streams"]:
        current = stream["current"]
        entries.append({"type": "metric", "metric": metric, "title": METRIC_CATALOG[metric]["title"],
            **{k: stream[k] for k in STREAM_FIELDS}, "unit": result["unit"],
            "value": current["value"], "statistic": "complete_local_day_median",
            "recorded_days": current["recorded_days"], "window_days": current["window_days"],
            "partial_dates": current["partial_dates"], "partial_daily_points": current["partial_daily_points"],
            "source_record_ids": current["source_record_ids"], "daily_points": current["daily_points"],
            "fact_id": stream["fact_id"], "algorithm": metric_version,
            "condition_known": bool(stream["device"] and stream["protocol"] and not str(stream["protocol"]).startswith("context:")),
            "reason": None if stream["device"] and stream["protocol"] else
                      "设备或协议未明确，保留期间统计，不能据此认定测量条件一致。"})
    return entries


def _training_observations(repo, window, cutoff):
    from healthzip.analytics.body_questions import _training
    from healthzip.training.daily_history import MATCH_VERSION, daily_identity
    _, rows = _training(repo, instant(window["start"]), instant(window["end"]), cutoff)
    groups = defaultdict(list)
    for row in rows:
        if row.get("set_type") != "work" or row.get("reps") is None:
            continue
        identity = daily_identity(row)
        key = (row.get("exercise_id"), identity["condition_key"], row.get("set_position"),
               row.get("load_value"), row.get("load_unit"), row.get("load_basis"), row.get("set_type"))
        if identity["reason_codes"] or row.get("set_position") is None:
            key += (row.get("set_uuid"),)
        groups[key].append(row)
    output = []
    for key, records in groups.items():
        row = records[0]
        identity = daily_identity(row)
        # Repeated instances of the same exercise in one session are not one
        # uniquely matched set position. Retain every record and limit pairing.
        sessions = Counter(r["session_id"] for r in records)
        known = not identity["reason_codes"] and key[2] is not None and max(sessions.values()) == 1
        output.append({"type": "strength", "exercise_id": key[0], "condition_key": key[1],
            "position": key[2], "load": float(key[3]) if key[3] is not None else None,
            "load_unit": key[4], "load_basis": key[5], "set_type": key[6],
            "title": row.get("exercise_name") or row.get("raw_exercise_name") or key[0], "unit": "次",
            "value": median(float(r["reps"]) for r in records),
            "statistic": "median_of_all_comparable_recorded_sets", "record_count": len(records),
            "session_count": len(sessions), "source_record_ids": [r["set_uuid"] for r in records],
            "records": [{"set_id": r["set_uuid"], "session_id": r["session_id"], "date": r["ended_at"],
                         "reps": r["reps"], "rir": r.get("rir"), "load": r.get("load_value"),
                         "session_exercise_id": r.get("session_exercise_id")} for r in records],
            "rir_values": [r.get("rir") for r in records], "algorithm": MATCH_VERSION,
            "condition_known": known, "reason": None if known else
            "动作条件、组位未知或同场存在重复动作组位；原始完成情况保留，不自动选择最佳组配对。"})
    return output


def _condition_observations(repo, metric, window, cutoff, sources):
    from healthzip.analytics.body_metrics import _rows
    from healthzip.science.state import physiology_stream_key, record_conditions
    start, end = instant(window["start"]), min(instant(window["end"]), instant(cutoff))
    rows = _rows(repo, "health_sample", [metric], start, end, cutoff, sources)
    if metric == "body_mass_kg":
        rows += _rows(repo, "body_measurement", [metric], start, end, cutoff, sources)
    groups = defaultdict(list)
    zone = ZoneInfo(window["timezone"])
    for r in rows:
        at = instant(r["event_end"]).astimezone(zone)
        conditions = record_conditions(r)
        groups[physiology_stream_key(r)].append({"id": r["id"], "date": at.isoformat(),
            "local_time": at.strftime("%H:%M:%S"), "posture": conditions["posture"]["value"],
            "sampling_mode": conditions["sampling_mode"]["value"],
            "measurement_context": conditions["measurement_context"]["value"]})
    return [{"type": "measurement_conditions", "metric": metric, "title": "测量条件与可比观测覆盖",
             **dict(zip(STREAM_FIELDS, key)), "record_count": len(records),
             "recorded_days": len({r["date"][:10] for r in records}), "records": records,
             "source_record_ids": [r["id"] for r in records],
             "posture_known_count": sum(r["posture"] is not None for r in records),
             "local_times": sorted({r["local_time"] for r in records}),
             "postures": sorted({str(r["posture"]) for r in records if r["posture"] is not None}),
             "condition_known": bool(key[1] and key[2]) and all(r["posture"] is not None for r in records),
             "value": None, "unit": "", "algorithm": VERSION,
             "reason": "展示实际时刻和已记录姿势；未设置任意时间相近阈值，缺少姿势时一致性仍未知。"}
            for key, records in groups.items()]


def _collect(repo, primary, window, cutoff, sources):
    if primary["kind"] == "training":
        return _training_observations(repo, window, cutoff)
    if primary["kind"] == "measurement_conditions":
        return _condition_observations(repo, primary["metric"], window, cutoff, sources)
    if primary["kind"] == "metric":
        return _metric_observations(repo, primary["metric"], window, cutoff, sources)
    return []


def select_action(repo, question, action_text, review_due, *, source_filter=(), selected_at=None,
                  planned_start=None, primary=None):
    if action_text not in question.get("steps", []):
        raise ValueError("请选择本次问题分析中给出的行动。")
    if "source_filter" in question:
        frozen_sources = sorted(question.get("source_filter") or [])
        if source_filter and sorted(source_filter) != frozen_sources:
            raise ValueError("行动来源须与这次保存的观察一致。")
        source_filter = frozen_sources
    now = instant(selected_at) if selected_at else datetime.now(timezone.utc)
    if instant(review_due) <= now:
        raise ValueError("复评时间须晚于行动选择时间。")
    if instant(question["window"]["end"]) > now:
        raise ValueError("行动依据不能含尚未发生的记录。")
    definition = proposed_definition(question, action_text, review_due, selected_at=now.isoformat(),
        planned_start=planned_start, primary=primary, source_filter=source_filter)
    definition["workspace"] = canonical_hash(str(repo.path.resolve()))
    baseline_cutoff = question["window"].get("cutoff_time", question["window"]["end"])
    definition["baseline_primary"] = _collect(repo, definition["primary"], question["window"], baseline_cutoff, source_filter)
    fields = sorted({r["metric"] for r in question.get("rows", []) if r.get("metric") in METRIC_CATALOG})
    if definition["primary"]["kind"] == "metric":
        fields = [f for f in fields if f != definition["primary"]["metric"]]
    definition["evidence_status"] = "attached" if definition["evidence"] else "no_reviewed_evidence_attached_product_observation_only"
    definition["baseline_secondary"] = [r for metric in fields for r in
        _metric_observations(repo, metric, question["window"], baseline_cutoff, source_filter)]
    definition["definition_id"] = "action-definition:" + canonical_hash(definition)
    # A retry of the same choice reuses its action. An explicit planned start is
    # part of the choice; the automatic wall-clock start is not a retry nonce.
    identity = canonical_hash({"workspace": definition["workspace"], "question": question,
        "text": action_text, "due": instant(review_due).isoformat(), "source_filter": sorted(source_filter),
        "primary": definition["primary"], "planned_start": planned_start, "version": VERSION})
    with repo.transaction():
        repo.conn.execute("INSERT OR IGNORE INTO review_action(action_id,user_id,question_id,selected_at,review_due,action_text,baseline_json,source_filter_json,definition_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (identity, "local", question["id"], now.isoformat(), instant(review_due).isoformat(),
             action_text, _json(question), _json(sorted(source_filter)), _json(definition)))
    return identity


def list_actions(repo):
    rows = repo.rows("SELECT a.*,e.status,e.notes,e.result_json,e.execution_json,e.recorded_at AS feedback_at FROM review_action a "
        "LEFT JOIN review_action_event e ON e.rowid=(SELECT rowid FROM review_action_event WHERE action_id=a.action_id ORDER BY julianday(recorded_at) DESC,rowid DESC LIMIT 1) "
        "WHERE a.user_id='local' ORDER BY a.selected_at DESC LIMIT 100")
    return [dict(row) for row in rows]


def _identity(row):
    if row["type"] == "strength":
        physical = tuple(row.get(k) for k in ("type", "exercise_id", "condition_key", "position", "load", "load_unit", "load_basis", "set_type"))
        return physical if row.get("condition_known") else physical + (tuple(row["source_record_ids"]),)
    return tuple(row.get(k) for k in ("type", "metric", *STREAM_FIELDS, "unit"))


def _compare(baseline, current, *, role):
    index = {_identity(r): r for r in current}
    observations = []
    for old in baseline:
        new = index.pop(_identity(old), None)
        known = old.get("condition_known") and new and new.get("condition_known")
        method = bool(new and old.get("algorithm") == new.get("algorithm"))
        first, value = old.get("value"), new.get("value") if new else None
        difference = value - first if known and method and isinstance(first, (int, float)) and isinstance(value, (int, float)) else None
        observations.append({**old, "role": role, "first_value": first, "value": value, "difference": difference,
            "baseline": old, "current": new, "baseline_source_record_ids": old.get("source_record_ids", []),
            "source_record_ids": new.get("source_record_ids", []) if new else [],
            "method_matches": method, "reason": "后续固定窗口内未见相同记录身份。" if new is None else
                "统计方法版本不同，保留两期结果，不给同方法差值。" if not method else
                old.get("reason") or new.get("reason") if not known else new.get("reason")})
    for new in index.values():
        observations.append({**new, "role": role, "first_value": None, "difference": None,
            "baseline": None, "current": new, "reason": "后续出现新的来源、条件或动作组；未与旧基线混算。"})
    return observations


def evaluate_action(repo, action, *, end, cutoff, timezone_name=None, version=None):
    """One evaluation shared by the action page, W4 and frozen reports."""
    action = dict(action)
    baseline = action.get("baseline") or json.loads(action["baseline_json"])
    definition = json.loads(action["definition_json"]) if action.get("definition_json") else None
    feedback = action.get("feedback") or {}
    execution = json.loads(feedback["execution_json"]) if feedback.get("execution_json") else {}
    execution_status = feedback.get("status", "unreported")
    base = {"action_id": action["action_id"], "question_id": action["question_id"],
            "action_text": action["action_text"], "selected_at": action["selected_at"], "review_due": action["review_due"],
            "execution_status": execution_status, "execution_label": EXECUTION.get(execution_status, EXECUTION["unreported"]),
            "execution": execution, "feedback_at": feedback.get("recorded_at"), "notes": feedback.get("notes"),
            "baseline_window": baseline["window"], "cutoff_time": instant(cutoff).isoformat(),
            "prespecified_question": baseline.get("title", action["question_id"]), "definition": definition,
            "observations": [], "primary_observations": [], "secondary_observations": [],
            "view_timezone_matches": baseline["window"]["timezone"] == timezone_name if timezone_name else True,
            "method_matches": baseline.get("analysis_version") == version if version else True,
            "limitation": "执行反馈与真实记录分别保留；前后差值不是行动的因果效果。"}
    if definition is None:
        base.update(definition_status="not_prespecified", status="legacy_definition_missing",
            followup_window=None, summary=f"已选行动“{action['action_text']}”：{base['execution_label']}；旧行动未预先记录主要结果定义，不追溯判断成功。")
        if feedback.get("result_json"):
            base["saved_feedback_result"] = json.loads(feedback["result_json"])
        return base
    if definition.get("workspace") != canonical_hash(str(repo.path.resolve())):
        raise ValueError("行动结果定义不属于当前工作区。")
    planned = definition["followup_window"]
    stop = min(instant(planned["end"]), instant(end), instant(cutoff))
    start = instant(planned["start"])
    window = {**planned, "end": max(start, stop).isoformat(), "planned_end": planned["end"],
              "cutoff_time": instant(cutoff).isoformat()}
    status = "awaiting_observations" if stop <= start else "partial_window" if stop < instant(planned["end"]) else "complete_window"
    base.update(definition_status="prespecified", followup_window=window, status=status,
                review_due_reached=instant(cutoff) >= instant(action["review_due"]))
    sources = definition["source_filter"]
    current = _collect(repo, definition["primary"], window, instant(cutoff).isoformat(), sources) if stop > start else []
    primary = _compare(definition["baseline_primary"], current, role="primary")
    secondary_fields = sorted({r["metric"] for r in definition["baseline_secondary"]})
    secondary = [r for m in secondary_fields for r in _metric_observations(repo, m, window, instant(cutoff).isoformat(), sources)] if stop > start else []
    secondary = _compare(definition["baseline_secondary"], secondary, role="secondary")
    base.update(primary_observations=primary, secondary_observations=secondary, observations=primary + secondary)
    if stop > start:
        from healthzip.analytics.body_metrics import _rows
        from healthzip.analytics.question_context import subjective_rows
        base["recorded_context"] = subjective_rows(_rows(repo, "subjective_log", None,
            start, stop, instant(cutoff).isoformat(), ()))
    else:
        base["recorded_context"] = []
    label = definition["primary"]["label"]
    text = f"已选行动“{action['action_text']}”：{base['execution_label']}；主要观察：{label}"
    if definition["primary"]["kind"] == "check":
        text += "；完成情况以实际反馈为准" if feedback else "；尚未收到核对完成反馈"
    elif definition["primary"]["kind"] == "measurement_conditions":
        n = sum(r.get("current", {}).get("record_count", 0) for r in primary if r.get("current"))
        known = sum(r["current"].get("posture_known_count", 0) for r in primary if r.get("current"))
        text += f"；后续 {n} 条测量，{known} 条明确记录姿势；未记录的条件仍未知"
    else:
        compared = [r for r in primary if r["difference"] is not None]
        if compared:
            # Every prescribed group is reported; no first-row or largest-change selection.
            if len(compared) <= 3:
                text += "；" + "；".join(f"{r['title']}（{r.get('source') or '同条件组位 ' + str(r.get('position'))}）期间中位数 {format_outcome_value(r, r['first_value'])} → {format_outcome_value(r, r['value'])}" for r in compared)
            else:
                text += f"；{len(compared)} 个预设分组已有同口径前后记录，各组数值与限制见主要观察明细"
        else:
            text += "；后续尚无可对齐的主要观察，不从背景指标替代"
    if status == "partial_window":
        text += "；观察窗口尚未完整，目前为阶段观察"
    if execution.get("started_at") and instant(execution["started_at"]) > start:
        text += "；实际延迟开始，原定观察窗口保持不变"
    if execution.get("ended_at") and instant(execution["ended_at"]) < instant(planned["end"]):
        text += "；实际执行已提前结束"
    base["summary"] = text + "。"
    base["evaluation_id"] = "action-review:" + canonical_hash(base)
    return base


def followup(repo, action_id, *, cutoff_time=None):
    row = repo.one("SELECT * FROM review_action WHERE action_id=? AND user_id='local'", (action_id,))
    if row is None:
        raise ValueError("所选行动在当前工作区不存在。")
    action = dict(row)
    now = instant(cutoff_time) if cutoff_time else datetime.now(timezone.utc)
    events = [dict(r) for r in repo.rows("SELECT rowid AS sequence,* FROM review_action_event WHERE action_id=?", (action_id,)) if instant(r["recorded_at"]) <= now]
    action["feedback"] = max(events, key=lambda r: (instant(r["recorded_at"]), r["sequence"])) if events else None
    baseline = json.loads(action["baseline_json"])
    from healthzip.analytics.body_questions import VERSION as question_version
    review = evaluate_action(repo, action, end=now, cutoff=now, version=question_version)
    current = {"id": action["question_id"], "title": "行动的主要结果复评", "observation": review["summary"],
               "rows": review["observations"], "window": review.get("followup_window"), "steps": [],
               "analysis_version": question_version} if review["status"] != "awaiting_observations" else None
    duration = instant(baseline["window"]["end"]) - instant(baseline["window"]["start"])
    return {"status": "partial" if review["status"] == "partial_window" else review["status"],
            "action_id": action_id, "baseline": baseline, "current": current, "review": review,
            "evaluation_id": review.get("evaluation_id"), "selected_at": action["selected_at"],
            "cutoff_time": now.isoformat(), "comparison_duration_days": duration / timedelta(days=1),
            "method_matches": review["method_matches"], "interpretation": review["limitation"]}


def save_feedback(repo, action_id, status, notes, result, *, event_id, actual_start=None,
                  actual_end=None, recorded_at=None):
    if status not in EXECUTION or status == "unreported":
        raise ValueError("请选择真实执行情况。")
    action = repo.one("SELECT baseline_json,selected_at FROM review_action WHERE action_id=? AND user_id='local'", (action_id,))
    if not action:
        raise ValueError("所选行动在当前工作区不存在。")
    if result and (result.get("baseline") != json.loads(action["baseline_json"]) or result.get("action_id", action_id) != action_id):
        raise ValueError("复评结果不属于本次行动保存的观察。")
    now = instant(recorded_at) if recorded_at else datetime.now(timezone.utc)
    if actual_end and not actual_start:
        raise ValueError("填写实际结束前，须先填写实际开始时间。")
    start = instant(actual_start) if actual_start else None
    stop = instant(actual_end) if actual_end else None
    if (start and (start < instant(action["selected_at"]) or start > now)) or (stop and (stop < start or stop > now)):
        raise ValueError("实际起止须按真实先后记录，不能早于行动选择或晚于反馈时点。")
    if status == "not_executed" and (start or stop):
        raise ValueError("未执行时不填写实际执行起止。")
    if result and result.get("cutoff_time") and instant(result["cutoff_time"]) > now:
        raise ValueError("复评观察截止不能晚于反馈时点。")
    execution = _json({"started_at": start.isoformat() if start else None, "ended_at": stop.isoformat() if stop else None,
                       "time_status": "reported" if start else "unknown", "source": "user_feedback"})
    serialized = _json(result) if result else None
    with repo.transaction():
        existing = repo.one("SELECT action_id,status,notes,result_json,execution_json FROM review_action_event WHERE event_id=?", (event_id,))
        if existing:
            if tuple(existing) != (action_id, status, notes, serialized, execution):
                raise ValueError("这次保存标识已用于不同反馈，请保留当前输入后重试。")
            return
        repo.conn.execute("INSERT INTO review_action_event(event_id,action_id,recorded_at,status,notes,result_json,execution_json) VALUES(?,?,?,?,?,?,?)",
            (event_id, action_id, now.isoformat(), status, notes, serialized, execution))
