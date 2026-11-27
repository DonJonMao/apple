"""Event-linked training and visible goal/action facts for local question views."""

from __future__ import annotations

import json
from collections import defaultdict
from zoneinfo import ZoneInfo

from healthzip.science.body_catalog import METRIC_CATALOG
from healthzip.science.contracts import canonical_hash, instant
from healthzip.training.daily_history import daily_identity
from healthzip.training.sequence_review import compare_work_sets

GOALS = {"strength": "力量表现", "hypertrophy": "肌肉增长", "general_fitness": "一般体能"}
EXECUTION = {"executed": "已执行", "partial": "部分执行", "not_executed": "未执行", "stopped": "已停止", "unreported": "尚未填写执行情况"}
SUBJECTIVE_FIELDS = ("fatigue", "soreness", "pain", "pain_level", "pain_location", "location",
                     "movement_impact", "illness_or_travel", "symptoms", "notes")
SUBJECTIVE_LABELS = {"fatigue": "疲劳", "soreness": "酸痛", "pain": "疼痛记录", "pain_level": "疼痛",
                     "pain_location": "疼痛部位", "location": "部位", "movement_impact": "动作影响",
                     "illness_or_travel": "疾病或旅行背景", "symptoms": "症状", "notes": "本人备注"}


def subjective_rows(records):
    return [{"type": "subjective", "title": "已记录的主观状态", "date": r["event_end"],
             "event_start": r["event_start"], "event_end": r["event_end"],
             "event_time_precision": "instant",
             "symptom_identity": tuple((k, str(r[k]) if isinstance(r[k], str) else "severity")
                 for k in SUBJECTIVE_FIELDS if r.get(k) is not None),
             "source": r.get("source_name"), "source_record_ids": [r["id"]],
             **{k: r[k] for k in SUBJECTIVE_FIELDS if r.get(k) is not None}}
            for r in records if any(r.get(k) is not None for k in SUBJECTIVE_FIELDS)]


def describe_subjective(row):
    return "、".join(f"{SUBJECTIVE_LABELS[k]} {subjective_display_value(k, row[k])}"
                    for k in SUBJECTIVE_FIELDS if row.get(k) is not None)


def subjective_display_value(key, value):
    if key == "pain" and isinstance(value, str):
        return {"reported": "有疼痛或不适", "denied": "明确没有", "unknown": "不确定"}.get(value, value)
    return str(value) if isinstance(value, (list, dict)) else value


def event_training_context(events, sessions, sets, timezone_name, *, comparisons=False):
    """A dated log is not assigned an onset time; real intervals keep their order."""
    zone = ZoneInfo(timezone_name)
    by_session = defaultdict(list)
    for record in sets:
        by_session[record["session_id"]].append(record)
    links, grouped, unmatched = [], defaultdict(dict), []
    for event in events:
        at = instant(event["date"])
        first = instant(event.get("event_start") or event["date"])
        last = instant(event.get("event_end") or event["date"])
        date_only = event.get("event_time_precision") == "calendar_day"
        matched = False
        for session in sessions:
            start = instant(session["started_at"])
            stop = instant(session["ended_at"]) if session.get("ended_at") else None
            same_date = at.astimezone(zone).date() == start.astimezone(zone).date()
            if date_only:
                if not same_date:
                    continue
                relation = "同一记录日期，具体先后未知"
            elif not (abs((start-at).total_seconds()) <= 24*3600 or (stop and first <= stop and last >= start)):
                continue
            elif last <= start:
                relation = "记录结束在训练开始之前"
            elif stop and first >= stop:
                relation = "记录开始在训练结束之后"
            elif stop:
                relation = "记录区间与训练区间相交"
            else:
                relation = "记录位于训练开始后，训练结束时间未知"
            matched = True
            actuals = []
            for record in by_session[session["id"]]:
                identity = daily_identity(record)
                actuals.append({"exercise": record.get("exercise_name") or record.get("raw_exercise_name") or record.get("exercise_id"),
                    "exercise_id": record.get("exercise_id"), "set_id": record.get("set_uuid"),
                    "position": record.get("set_number"), "load": record.get("load_value"),
                    "unit": record.get("load_unit"), "reps": record.get("reps"), "rir": record.get("rir"),
                    "duration_s": record.get("duration_s"), "distance_m": record.get("distance_m"),
                    "ended_at": record.get("ended_at"), "set_type": record.get("set_type"),
                    "condition_known": not identity["reason_codes"], "condition_limitations": identity["reason_codes"]})
            link = {"type": "event_training", "title": "实际记录与相邻训练", "event_title": event["title"],
                    "event_at": event["date"], "event_time_precision": event.get("event_time_precision", "instant"),
                    "event_start": first.isoformat(), "event_end": last.isoformat(),
                    "date": session["started_at"], "session_id": session["id"],
                    "started_at": session["started_at"], "ended_at": session.get("ended_at"),
                    "temporal_relation": relation, "actual_sets": actuals,
                    "event_source_record_ids": event.get("source_record_ids", []),
                    "matching_scope": "有时刻记录与训练开始相隔24小时内，或区间相交；仅日期记录只连同日本地日期。"}
            links.append(link)
            if comparisons:
                group = (event["title"], event.get("source"), event.get("category"), event.get("symptom_identity"))
                entry = grouped[group].setdefault(session["id"], {"session": session, "events": [], "sets": by_session[session["id"]]})
                entry["events"].append(event)
        if not matched:
            unmatched.append({"type": "event_training_unmatched", "title": event["title"],
                "date": event["date"], "reason": "所选配对范围内未见可关联的实际训练；不代表没有训练。",
                "source_record_ids": event.get("source_record_ids", [])})
    pairs = []
    for group, sessions_by_id in grouped.items():
        by_exercise = defaultdict(list)
        for entry in sessions_by_id.values():
            for exercise in {r.get("exercise_id") for r in entry["sets"]}:
                by_exercise[exercise].append({**entry, "sets": [r for r in entry["sets"] if r.get("exercise_id") == exercise]})
        for exercise, entries in by_exercise.items():
            entries.sort(key=lambda e: instant(e["session"]["started_at"]))
            for before, after in zip(entries, entries[1:]):
                # Two sessions linked to the same single event are not repeated
                # symptom-event correspondence. Keep those timelines without a pair.
                a_ids = {i for e in before["events"] for i in e.get("source_record_ids", [])}
                b_ids = {i for e in after["events"] for i in e.get("source_record_ids", [])}
                if not a_ids.isdisjoint(b_ids):
                    continue
                old, new = {exercise: before["sets"]}, {exercise: after["sets"]}
                comparison = compare_work_sets(sorted(old[exercise], key=lambda r:r.get("set_number") or 0),
                                               sorted(new[exercise], key=lambda r:r.get("set_number") or 0))
                for item in comparison["comparisons"]:
                    pairs.append({"type": "event_set_pair", "title": "实际事件对应的同动作组记录",
                        "event_title": group[0], "exercise": new[exercise][-1].get("exercise_name") or exercise,
                        "session_id": after["session"]["id"], "first_session_id": before["session"]["id"],
                        "first_date": before["session"]["started_at"], "date": after["session"]["started_at"],
                        "first_event_dates": [e["date"] for e in before["events"]], "event_dates": [e["date"] for e in after["events"]],
                        "first_value": item["previous_reps"], "value": item["current_reps"],
                        "difference": item["reps_change"], "unit": "次", **item})
                if not comparison["comparisons"]:
                    unmatched.append({"type": "event_comparison_unmatched", "title": group[0],
                        "date": after["session"]["started_at"], "session_id": after["session"]["id"],
                        "first_session_id": before["session"]["id"], "exercise": exercise,
                        "reason": "有实际训练，但组位缺失或重复，不能形成唯一组对照。"})
    return links, pairs, unmatched


def visible_goal_actions(repo, start, end, cutoff):
    from healthzip.advice import profile
    has_profile = repo.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='advice_profile_revision'")
    goal = profile(repo, cutoff_time=cutoff.isoformat()) if has_profile else {"revision": None, "fields": {}, "provenance": {}}
    actions = []
    for raw in repo.rows("SELECT * FROM review_action WHERE user_id='local' ORDER BY selected_at,action_id"):
        action = dict(raw)
        selected = instant(action["selected_at"])
        if selected > cutoff or selected >= end:
            continue
        visible = [dict(r) for r in repo.rows("SELECT rowid AS sequence,* FROM review_action_event WHERE action_id=?", (action["action_id"],))
                   if instant(r["recorded_at"]) <= cutoff]
        feedback = max(visible, key=lambda r:(instant(r["recorded_at"]),r["sequence"])) if visible else None
        if not (selected >= start or instant(action["review_due"]) >= start or
                feedback and instant(feedback["recorded_at"]) >= start or
                not feedback or feedback["status"] in {"partial", "not_executed"}):
            continue
        actions.append({**action, "feedback": feedback, "baseline": json.loads(action["baseline_json"]),
                        "sources": json.loads(action["source_filter_json"])})
    return goal, actions, canonical_hash({"goal": goal, "actions": actions})


def action_metric_dependencies(actions):
    """A primary result can be selected before its first observation exists."""
    fields = {r["metric"] for a in actions for r in a["baseline"].get("rows", [])
              if r.get("metric") in METRIC_CATALOG}
    for action in actions:
        definition = json.loads(action["definition_json"]) if action.get("definition_json") else {}
        metric = definition.get("primary", {}).get("metric")
        if metric in METRIC_CATALOG:
            fields.add(metric)
        fields.update(r["metric"] for r in definition.get("baseline_secondary", [])
                      if r.get("metric") in METRIC_CATALOG)
    return fields


def action_observations(repo, goal, actions, *, end, cutoff, timezone_name, version):
    from healthzip.workflows.actions import evaluate_action

    kind = goal["fields"].get("training_goal")
    goal_context = {"goal": kind, "title": GOALS.get(kind, kind) if kind else "尚未选择目标",
                    "revision": goal.get("revision"), "recorded_at": goal.get("recorded_at"),
                    "provenance": goal.get("provenance", {}).get("training_goal"),
                    "quantitative_target_status": "未记录独立数值目标，不能判断达标",
                    "limitation": "目标方向不等于已设定个人重要变化阈值；肌肉增长目标不能由体重直接推算肌肉增量。"}
    return goal_context, [evaluate_action(repo, action, end=end, cutoff=cutoff,
        timezone_name=timezone_name, version=version) for action in actions]
