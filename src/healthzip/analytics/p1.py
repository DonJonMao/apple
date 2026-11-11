"""Legacy view adapters for v1.3 observed facts; no readiness-to-load mapping."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median

from healthzip.analytics.core import evidence_card
from healthzip.temporal import instant, sleep_nights, visible

ALGORITHM_VERSION = "p1-1.3.0"


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _e1rm(weight, reps, **kwargs):
    from healthzip.science.formulas import e1rm
    return e1rm(weight, reps, **kwargs)["value"]


def _condition(row):
    # The domain service validates all physical conditions. Unknowns are never
    # wildcards; historic rows remain visible as separate unconfirmed records.
    key = row.get("condition_key") if row.get("comparability_status") == "user_confirmed" else None
    return (str(row.get("exercise_name") or ""), str(row.get("equipment") or ""),
            str(row.get("variation") or ""), key or f"unknown:{row.get('id')}")


def _strength_rows(repo, start=None, end=None):
    sessions = {r["id"]: dict(r) for r in repo.rows("SELECT * FROM strength_session")}
    output = []
    for record in repo.rows("SELECT * FROM strength_set ORDER BY set_date,started_at,id"):
        row = dict(record)
        d = _day(row.get("set_date"))
        session = sessions.get(row.get("session_id"), {})
        if not d or (start and d < start) or (end and d > end) or row.get("deleted_at") or session.get("deleted_at"):
            continue
        state = row.get("completion_state")
        if state not in {None, "completed"}:
            continue
        row["date"] = d.isoformat()
        row["warmup"] = bool(row.get("warmup")) or row.get("set_type") == "warmup"
        row["session"] = session
        row["e1rm_kg"] = None
        row["volume_kg"] = None
        basis = row.get("load_basis")
        if basis in {"external_total_kg", "dumbbells_total_kg", "single_implement_kg", "barbell_total", "external_total"} and row.get("reps") is not None and row.get("weight_kg") is not None:
            row["volume_kg"] = row["reps"] * row["weight_kg"]
        condition = json.loads(row.get("condition_json") or "{}")
        if condition.get("formula_domain") and not row["warmup"]:
            row["e1rm_kg"] = _e1rm(row.get("weight_kg"), row.get("reps"),
                load_basis=basis, domain=condition["formula_domain"])
        output.append(row)
    return output


def _session_quality(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row.get("session_id") or f"unknown:{row['id']}"].append(row)
    result = []
    for sid, vals in groups.items():
        work = [x for x in vals if not x["warmup"]]
        session = vals[0].get("session", {})
        rpe = [x["rpe"] for x in work if x.get("rpe") is not None]
        rir = [x["rir"] for x in work if x.get("rir") is not None]
        conditions = {_condition(x) for x in work}
        volumes = [x["volume_kg"] for x in work if x.get("volume_kg") is not None]
        volume = sum(volumes) if len(conditions) == 1 and len(volumes) == len(work) and work else None
        duration = session.get("duration_seconds")
        srpe = session.get("session_rpe")
        srpe_ok = session.get("session_rpe_scale") and session.get("duration_protocol")
        e1 = [x["e1rm_kg"] for x in work if x.get("e1rm_kg") is not None]
        result.append({"date": vals[0]["date"], "session_id": sid,
            "started_at": session.get("started_at"), "sets": len(work), "all_sets": len(vals),
            "source_set_ids": [x["id"] for x in work], "source_session_ids": [sid],
            "volume_kg": volume, "volume_unit": "kg·reps within one confirmed condition",
            "top_e1rm_kg": max(e1) if e1 and len(conditions) == 1 else None,
            "median_rpe": median(rpe) if rpe else None, "median_rir": median(rir) if rir else None,
            "duration_minutes": duration / 60 if duration is not None else None,
            "session_rpe": srpe, "session_rpe_load": srpe * duration / 60 if srpe_ok and srpe is not None and duration is not None else None,
            "load_method": "explicit_session_rpe" if srpe_ok else "not_recorded"})
    return result


def strength_quality(repo, start_date=None, end_date=None):
    rows = _strength_rows(repo, _day(start_date), _day(end_date))
    groups = defaultdict(list)
    for row in rows:
        if not row["warmup"]:
            groups[_condition(row)].append(row)
    series = []
    for key, vals in groups.items():
        sessions = _session_quality(vals)
        points = [{**s, "source_session_ids": s["source_session_ids"]} for s in sessions]
        comparable = not key[3].startswith("unknown:")
        series.append({"exercise_name": key[0], "equipment": key[1], "variation": key[2],
            "condition_key": key[3], "comparability_status": "comparable" if comparable else "unknown",
            "exposures": len(sessions), "records": len(vals), "points": points,
            "e1rm_change_kg": None, "e1rm_slope_kg_per_exposure": None,
            "same_load_reps": [{"date": x["date"], "source_set_id": x["id"],
                "source_session_id": x.get("session_id"), "weight_kg": x.get("weight_kg"),
                "reps": x.get("reps"), "peer_sets": sum(y.get("weight_kg") == x.get("weight_kg") for y in vals) if comparable else None}
                for x in vals]})
    sessions = _session_quality(rows)
    card = evidence_card("strength_quality_p1", "力量训练记录与可比条件",
        "provisional" if rows else "not_imported",
        f"记录 {len(sessions)} 次训练、{len(groups)} 个已确认或待确认的动作条件。",
        window=(start_date or (rows[0]["date"] if rows else None), end_date or (rows[-1]["date"] if rows else None)),
        facts=[{"metric": "strength_sessions", "value": len(sessions), "unit": "sessions"},
               {"metric": "work_sets", "value": sum(not x["warmup"] for x in rows), "unit": "sets"}],
        limitations=["未知口径的历史记录保留原值，不认定可比。", "组数和负荷×次数不代表机械功或肌肉刺激。", "三次记录不能证明个人统计推断有效。"],
        source_feature_ids=[f"strength_set:{x['id']}" for x in rows])
    card["algorithm_version"] = ALGORITHM_VERSION
    return {"card": card, "series": series, "sessions": sessions, "sets": rows}


def body_state(repo, start_date=None, end_date=None, *, cutoff_time=None):
    start, end = _day(start_date), _day(end_date)
    lookback = start - timedelta(days=28) if start else None
    if cutoff_time:
        from healthzip.db.temporal_schema import samples_as_of
        bounds = {"window_start": datetime.combine(lookback, datetime.min.time(), tzinfo=timezone.utc).isoformat(),
                  "window_end": datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).isoformat()} if lookback and end else {}
        records = samples_as_of(repo, cutoff_time, canonical_types=("resting_heart_rate_bpm", "hrv_sdnn_ms", "sleep_stage"), **bounds)
        subjective = samples_as_of(repo, cutoff_time, "subjective_log", **bounds)
    else:
        filters, args = "", []
        if lookback:
            filters += " AND local_date>=?"
            args.append((lookback-timedelta(days=1)).isoformat())
        if end:
            filters += " AND local_date<=?"
            args.append((end+timedelta(days=1)).isoformat())
        records = [dict(r) for r in repo.rows("SELECT * FROM health_sample WHERE record_status='active' "
                   "AND canonical_type IN ('resting_heart_rate_bpm','hrv_sdnn_ms','sleep_stage')"+filters, tuple(args))]
        subjective = [dict(r) for r in repo.rows("SELECT * FROM subjective_log WHERE 1=1"+filters.replace("local_date", "day"), tuple(args))]
    days = defaultdict(dict)
    for row in records:
        d = _day(row.get("local_date"))
        typ = row.get("canonical_type")
        if typ not in {"resting_heart_rate_bpm", "hrv_sdnn_ms"} or row.get("normalized_value") is None:
            continue
        if not d or (lookback and d < lookback) or (end and d > end) or (cutoff_time and not visible(row, cutoff_time)):
            continue
        item = days[d.isoformat()]
        item.setdefault(typ, []).append(row["normalized_value"])
        item.setdefault("_protocols", set()).add((row.get("source_name"), row.get("device"), row.get("source_version")))
        item.setdefault("source_ids", []).append(f"health_sample:{row['id']}")
    for night in sleep_nights(records, lookback.isoformat() if lookback else None, end_date, cutoff_time):
        days[night["date"]]["sleep_hours"] = night["sleep_hours"]
        days[night["date"]].setdefault("source_ids", []).extend(night["source_ids"])
    for row in subjective:
        d = _day(row.get("day"))
        if not d or (lookback and d < lookback) or (end and d > end):
            continue
        # Without a recorded actual observation time a day-only questionnaire
        # cannot be established as pre-session; keep it in retrospective views.
        if cutoff_time and not visible(row, cutoff_time, event_key="observed_at"):
            continue
        item = days[d.isoformat()]
        item.setdefault("source_ids", []).append(f"subjective_log:{row['id']}")
        for k in ("energy_level", "fatigue", "soreness", "stress", "sleep_quality", "pain_level"):
            if row.get(k) is not None:
                item[k] = row[k]
    output = []
    for day, raw in sorted(days.items()):
        item = {k: median(v) if isinstance(v, list) and k != "source_ids" else v for k, v in raw.items() if not k.startswith("_")}
        item["date"] = day
        item["protocol_status"] = "mixed_or_unknown" if len(raw.get("_protocols", set())) != 1 else "source_stream_only"
        prior = [x for x in output if 0 < (_day(day) - _day(x["date"])).days <= 28]
        for metric in ("sleep_hours", "fatigue", "soreness"):
            baseline = [x[metric] for x in prior if x.get(metric) is not None]
            if baseline and item.get(metric) is not None:
                item[metric + "_baseline"] = median(baseline)
                item[metric + "_deviation"] = item[metric] - median(baseline)
        output.append(item)
    return [x for x in output if not start or _day(x["date"]) >= start]


def body_state_strength(repo, start_date=None, end_date=None):
    quality = strength_quality(repo, start_date, end_date)
    joins = []
    for session in quality["sessions"]:
        cutoff = instant(session.get("started_at"))
        states = body_state(repo, (cutoff.date()-timedelta(days=1)).isoformat(), cutoff.date().isoformat(), cutoff_time=cutoff.isoformat()) if cutoff else []
        state = states[-1] if states else None
        joins.append({"date": session["date"], "session": session, "body_state": state,
                      "alignment": "available_before_session" if state else "missing_pre_session_data"})
    n = sum(x["body_state"] is not None for x in joins)
    card = evidence_card("body_state_strength_quality", "训练前可用身体记录",
        "provisional" if n else "insufficient", f"{n} 次训练有训练开始前已发生且本机已知的状态。",
        window=(start_date, end_date), facts=[{"metric": "joined_sessions", "value": n, "unit": "sessions"}],
        limitations=["缺少开始时间或历史可见时间的资料不能进入训练前分析。", "配对是观察，不是因果。"])
    card["algorithm_version"] = ALGORITHM_VERSION
    return {"card": card, "joins": joins, "paired_metrics": [],
            "body_state": body_state(repo, start_date, end_date), "sessions": quality["sessions"]}


def period_report(repo, period="week", anchor=None):
    today = _day(anchor) or date.today()
    start = today.replace(day=1) if period == "month" else today-timedelta(days=today.weekday())
    prior_end = start-timedelta(days=1)
    prior_start = prior_end.replace(day=1) if period == "month" else start-timedelta(days=7)
    q = strength_quality(repo, start.isoformat(), today.isoformat())
    assoc = body_state_strength(repo, start.isoformat(), today.isoformat())
    card = evidence_card(f"strength_report_{period}_{start}", "训练周期复盘", "provisional" if q["sessions"] else "insufficient",
        f"已过去时段记录 {len(q['sessions'])} 次训练；不同动作和负荷口径分别查看。",
        window=(start.isoformat(), today.isoformat()), facts=[{"metric": "sessions", "value": len(q["sessions"]), "unit": "sessions"}],
        limitations=["当前周期可能未结束，不将部分周期与完整上期直接比较。", "跨动作不合成机械功、肌肉刺激或恢复分。"])
    card["algorithm_version"] = ALGORITHM_VERSION
    return {"period": period, "start": str(start), "end": str(today), "card": card,
            "strength": q, "association": assoc, "comparison": {"previous_start": str(prior_start),
            "previous_end": str(prior_end), "volume_delta_kg": None},
            "recommendations": ["查看同条件原始记录与计划执行，缺失信息保持未知。"]}


def today_training_setup(repo, exercise_name, planned_weight_kg=None, planned_reps=None,
                         today=None, *, equipment=None, variation=None):
    day = _day(today) or date.today()
    rows = [x for x in _strength_rows(repo, None, day-timedelta(days=1))
            if x.get("exercise_name") == exercise_name and not x["warmup"]]
    card = evidence_card("today_training_setup", "今日计划与历史参考", "insufficient",
        "可查看上次原始记录；请确认器械、负荷口径和计划目标后查看可检验候选。",
        window=(str(day), str(day)),
        facts=[{"metric": "user_planned_weight", "value": planned_weight_kg, "unit": "kg"},
               {"metric": "user_planned_reps", "value": planned_reps, "unit": "reps"}],
        limitations=["身体状态不能换算成固定减重百分比。", "历史完成不保证今天完成，未知条件不视为匹配。"],
        source_feature_ids=[f"strength_set:{r['id']}" for r in rows])
    card["algorithm_version"] = ALGORITHM_VERSION
    return {"card": card, "exercise_name": exercise_name, "date": str(day),
            "candidate": None, "reason_codes": ["confirmed_plan_and_condition_required"],
            "recent_sets": rows, "state": None}


def weekly_report(repo, anchor=None):
    return period_report(repo, "week", anchor)


def monthly_report(repo, anchor=None):
    return period_report(repo, "month", anchor)


training_quality_analysis = strength_quality
