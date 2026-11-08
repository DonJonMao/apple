"""P1 training analytics.

The functions in this module deliberately return plain dictionaries so they can be
rendered by Streamlit or exported without coupling the calculations to a UI.  They
describe observations and associations; they do not diagnose or prescribe medical
treatment.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any, Optional

from healthzip.analytics.core import evidence_card
from healthzip.db.repository import Repository

ALGORITHM_VERSION = "p1-0.1.0"


def _day(value: Any) -> Optional[date]:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> Optional[float]:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def _e1rm(weight: Any, reps: Any) -> Optional[float]:
    w, r = _num(weight), _num(reps)
    if w is None or r is None or w <= 0 or r <= 0:
        return None
    # Epley becomes very noisy at high repetitions, so cap its use to a set that
    # is normally used for strength comparison.
    return round(w * (1 + min(r, 15) / 30), 2)


def _quality(set_row: dict[str, Any]) -> dict[str, Any]:
    w, reps = _num(set_row.get("weight_kg")), _num(set_row.get("reps"))
    rir, rpe = _num(set_row.get("rir")), _num(set_row.get("rpe"))
    return {
        "volume_kg": round(w * reps, 2) if w is not None and reps is not None else None,
        "e1rm_kg": _e1rm(w, reps),
        "rir": rir,
        "rpe": rpe,
    }


def _strength_rows(
    repo: Repository, start: Optional[date], end: Optional[date]
) -> list[dict[str, Any]]:
    rows = [
        dict(r) for r in repo.rows("SELECT * FROM strength_set ORDER BY set_date, started_at, id")
    ]
    result = []
    for row in rows:
        day = _day(row.get("set_date"))
        if day is None or (start and day < start) or (end and day > end):
            continue
        row["date"] = day.isoformat()
        row["warmup"] = bool(row.get("warmup"))
        row.update(_quality(row))
        result.append(row)
    return result


def _condition(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("exercise_name") or "").strip().lower(),
        str(row.get("equipment") or "").strip().lower(),
        str(row.get("variation") or "").strip().lower(),
    )


def _slope(points: list[tuple[int, float]]) -> Optional[float]:
    if len(points) < 2:
        return None
    x0, y0 = points[0]
    x1, y1 = points[-1]
    span = max(1, x1 - x0)
    return round((y1 - y0) / span, 3)


def strength_quality(
    repo: Repository, start_date: Optional[str] = None, end_date: Optional[str] = None
) -> dict[str, Any]:
    """Summarize comparable strength conditions and per-session quality."""
    start, end = _day(start_date), _day(end_date)
    rows = _strength_rows(repo, start, end)
    work = [r for r in rows if not r["warmup"]]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in work:
        groups[_condition(row)].append(row)

    series: list[dict[str, Any]] = []
    for key, vals in sorted(groups.items()):
        by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for value in vals:
            by_date[value["date"]].append(value)
        points = []
        for day, sets in sorted(by_date.items()):
            e1rms = [x["e1rm_kg"] for x in sets if x["e1rm_kg"] is not None]
            reps = [x.get("reps") for x in sets if x.get("reps") is not None]
            volume = [x["volume_kg"] for x in sets if x["volume_kg"] is not None]
            points.append(
                {
                    "date": day,
                    "sets": len(sets),
                    "source_set_ids": [int(x["id"]) for x in sets if x.get("id") is not None],
                    "source_session_ids": sorted(
                        {int(x["session_id"]) for x in sets if x.get("session_id") is not None}
                    ),
                    "top_e1rm_kg": max(e1rms) if e1rms else None,
                    "median_reps": round(median(reps), 2) if reps else None,
                    "volume_kg": round(sum(volume), 2) if volume else None,
                    "median_rir": round(median([x["rir"] for x in sets if x["rir"] is not None]), 2)
                    if any(x["rir"] is not None for x in sets)
                    else None,
                    "median_rpe": round(median([x["rpe"] for x in sets if x["rpe"] is not None]), 2)
                    if any(x["rpe"] is not None for x in sets)
                    else None,
                }
            )
        e1 = [(i, p["top_e1rm_kg"]) for i, p in enumerate(points) if p["top_e1rm_kg"] is not None]
        same_load: list[dict[str, Any]] = []
        for value in vals:
            if value.get("weight_kg") is None or value.get("reps") is None:
                continue
            weight = float(value["weight_kg"])
            peers = [
                x
                for x in vals
                if x.get("weight_kg") is not None
                and abs(float(x["weight_kg"]) - weight) <= max(1.25, weight * 0.025)
            ]
            same_load.append(
                {
                    "date": value["date"],
                    "source_set_id": value.get("id"),
                    "source_session_id": value.get("session_id"),
                    "weight_kg": weight,
                    "reps": int(value["reps"]),
                    "peer_sets": len(peers),
                }
            )
        series.append(
            {
                "exercise_name": key[0],
                "equipment": key[1],
                "variation": key[2],
                "exposures": len(points),
                "records": len(vals),
                "points": points,
                "e1rm_change_kg": round(e1[-1][1] - e1[0][1], 2) if len(e1) >= 2 else None,
                "e1rm_slope_kg_per_exposure": _slope(e1),
                "same_load_reps": same_load,
            }
        )

    sessions = _session_quality(rows)
    usable = sum(1 for item in series if item["exposures"] >= 3)
    card = evidence_card(
        "strength_quality_p1",
        "力量训练质量与可比表现",
        "usable" if usable else ("provisional" if series else "not_imported"),
        f"记录 {len(sessions)} 次训练、{len(series)} 个动作条件，其中 {usable} 个有至少三次可比暴露。"
        if series
        else "尚未导入力量组记录。",
        window=(rows[0]["date"] if rows else None, rows[-1]["date"] if rows else None),
        facts=[
            {"metric": "strength_sessions", "value": len(sessions), "unit": "sessions"},
            {"metric": "exercise_conditions", "value": len(series), "unit": "conditions"},
            {"metric": "usable_conditions", "value": usable, "unit": "conditions"},
        ],
        limitations=[
            "e1RM 是基于重量和次数的近似指标，不是测得的 1RM。",
            "动作、器械、活动范围或 RIR 变化会降低可比性。",
        ]
        if series
        else ["需要导入力量训练组记录。"],
        allowed_actions=[
            "review_comparable_exercises",
            "progress_gradually",
            "continue_observation",
        ],
        source_feature_ids=sorted(
            {
                f"strength_set:{source_id}"
                for item in series
                for point in item.get("points", [])
                for source_id in point.get("source_set_ids", [])
            }
        )[:500],
    )
    card["algorithm_version"] = ALGORITHM_VERSION
    return {"card": card, "series": series, "sessions": sessions, "sets": rows}


def _session_quality(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[row["date"]].append(row)
    result = []
    for day, vals in sorted(by_day.items()):
        work = [x for x in vals if not x["warmup"]]
        volumes = [x["volume_kg"] for x in work if x["volume_kg"] is not None]
        volume = round(sum(volumes), 2) if volumes else None
        e1rms = [x["e1rm_kg"] for x in work if x["e1rm_kg"] is not None]
        rpe = [x["rpe"] for x in work if x["rpe"] is not None]
        rir = [x["rir"] for x in work if x["rir"] is not None]
        session_rpe = round(median(rpe), 2) if rpe else None
        # When duration and explicit session RPE are unavailable, volume is retained
        # as the fallback load and labelled accordingly.
        result.append(
            {
                "date": day,
                "sets": len(work),
                "all_sets": len(vals),
                "source_set_ids": [int(x["id"]) for x in work if x.get("id") is not None],
                "source_session_ids": sorted(
                    {int(x["session_id"]) for x in vals if x.get("session_id") is not None}
                ),
                "volume_kg": volume,
                "top_e1rm_kg": max(e1rms) if e1rms else None,
                "median_rpe": session_rpe,
                "median_rir": round(median(rir), 2) if rir else None,
                "duration_minutes": None,
                "session_rpe": session_rpe,
                "session_rpe_load": None,
                "load_method": "volume_kg_fallback",
            }
        )
    return result


def body_state(
    repo: Repository, start_date: Optional[str] = None, end_date: Optional[str] = None
) -> list[dict[str, Any]]:
    """Build daily body-state features with personal baselines where available."""
    start, end = _day(start_date), _day(end_date)
    by_day: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in repo.rows(
        "SELECT id,local_date,canonical_type,normalized_value FROM health_sample "
        "WHERE normalized_value IS NOT NULL ORDER BY local_date"
    ):
        day = _day(row["local_date"])
        if day is None or (start and day < start) or (end and day > end):
            continue
        typ = row["canonical_type"]
        if typ in {"resting_heart_rate_bpm", "hrv_sdnn_ms", "body_mass_kg"}:
            item = by_day[day.isoformat()]
            item.setdefault(typ, []).append(float(row["normalized_value"]))
            item.setdefault("_source_ids", []).append(f"health_sample:{row['id']}")
    for row in repo.rows(
        "SELECT id,day,energy_level,fatigue,soreness,stress,sleep_quality,pain_level "
        "FROM subjective_log ORDER BY day"
    ):
        d = _day(row["day"])
        if d is None or (start and d < start) or (end and d > end):
            continue
        item = by_day[d.isoformat()]
        item.setdefault("_source_ids", []).append(f"subjective_log:{row['id']}")
        for key in (
            "energy_level",
            "fatigue",
            "soreness",
            "stress",
            "sleep_quality",
            "pain_level",
        ):
            if row[key] is not None:
                item[key] = float(row[key])
    # Sleep duration is calculated from asleep/in-bed intervals conservatively.
    for row in repo.rows(
        "SELECT id,local_date,start_utc,end_utc,category_value FROM health_sample "
        "WHERE canonical_type='sleep_stage'"
    ):
        d = _day(row["local_date"])
        if d is None or not row["start_utc"] or not row["end_utc"]:
            continue
        try:
            st = datetime.fromisoformat(str(row["start_utc"]).replace("Z", "+00:00"))
            en = datetime.fromisoformat(str(row["end_utc"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        stage = str(row["category_value"] or "").lower()
        if en > st and ("awake" not in stage):
            item = by_day[d.isoformat()]
            item.setdefault("_sleep_segments", []).append((st, en))
            item.setdefault("_source_ids", []).append(f"health_sample:{row['id']}")
    output = []
    for day, raw in sorted(by_day.items()):
        item = {
            k: (round(median(v), 2) if isinstance(v, list) else v)
            for k, v in raw.items()
            if not k.startswith("_")
        }
        segs = sorted(raw.get("_sleep_segments", []))
        merged: list[tuple[datetime, datetime]] = []
        for st, en in segs:
            if merged and st <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], en))
            else:
                merged.append((st, en))
        if merged:
            item["sleep_hours"] = round(sum((b - a).total_seconds() for a, b in merged) / 3600, 2)
        if raw.get("_source_ids"):
            item["source_ids"] = sorted(set(raw["_source_ids"]))
        d = _day(day)
        prior = []
        for old in output:
            if (d - _day(old["date"])).days <= 28 and (d - _day(old["date"])).days > 0:
                prior.append(old)
        for metric in (
            "resting_heart_rate_bpm",
            "hrv_sdnn_ms",
            "sleep_hours",
            "fatigue",
            "soreness",
        ):
            value = item.get(metric)
            baseline = [x[metric] for x in prior if x.get(metric) is not None]
            if value is not None and baseline:
                item[f"{metric}_baseline"] = round(median(baseline), 2)
                item[f"{metric}_deviation"] = round(value - median(baseline), 2)
        item["date"] = day
        output.append(item)
    return output


def body_state_strength(
    repo: Repository, start_date: Optional[str] = None, end_date: Optional[str] = None
) -> dict[str, Any]:
    """Join body state to strength sessions within a ±1 day window."""
    quality = strength_quality(repo, start_date, end_date)
    states = body_state(repo, start_date, end_date)
    indexed = {_day(x["date"]): x for x in states}
    joins = []
    for session in quality["sessions"]:
        d = _day(session["date"])
        candidates = [
            (abs((d - k).days), v) for k, v in indexed.items() if k and abs((d - k).days) <= 1
        ]
        state = min(candidates, key=lambda x: x[0])[1] if candidates else None
        joins.append(
            {
                "date": session["date"],
                "session": session,
                "body_state": state,
                "alignment": "same_day"
                if state and state["date"] == session["date"]
                else ("adjacent_day" if state else "missing"),
            }
        )
    usable = [x for x in joins if x["body_state"] is not None]
    paired_metrics: list[dict[str, Any]] = []
    for metric in (
        "sleep_hours",
        "resting_heart_rate_bpm_deviation",
        "hrv_sdnn_ms_deviation",
        "fatigue",
        "soreness",
    ):
        pairs = [item for item in usable if (item.get("body_state") or {}).get(metric) is not None]
        if not pairs:
            continue

        def median_value(key: str) -> Optional[float]:
            values = [
                item["session"].get(key) for item in pairs if item["session"].get(key) is not None
            ]
            return round(median(values), 2) if values else None

        body_values = [float(item["body_state"][metric]) for item in pairs]
        paired_metrics.append(
            {
                "body_metric": metric,
                "n": len(pairs),
                "body_median": round(median(body_values), 2),
                "volume_median_kg": median_value("volume_kg"),
                "top_e1rm_median_kg": median_value("top_e1rm_kg"),
                "median_rpe": median_value("median_rpe"),
                "median_rir": median_value("median_rir"),
                "interpretation": "同一人的配对描述统计；不表示因果关系。",
            }
        )
    association_facts = [
        {"metric": "joined_sessions", "value": len(usable), "unit": "sessions"},
        {"metric": "total_sessions", "value": len(joins), "unit": "sessions"},
        {"metric": "paired_body_metrics", "value": len(paired_metrics), "unit": "metrics"},
    ]
    for item in paired_metrics:
        prefix = item["body_metric"]
        association_facts.extend(
            [
                {"metric": f"{prefix}.n", "value": item["n"], "unit": "sessions"},
                {
                    "metric": f"{prefix}.body_median",
                    "value": item["body_median"],
                    "unit": "personal_scale",
                },
                {
                    "metric": f"{prefix}.volume_median_kg",
                    "value": item["volume_median_kg"],
                    "unit": "kg",
                },
                {
                    "metric": f"{prefix}.top_e1rm_median_kg",
                    "value": item["top_e1rm_median_kg"],
                    "unit": "kg",
                },
            ]
        )
    card = evidence_card(
        "body_state_strength_quality",
        "身体状态与力量训练质量的同期观察",
        "provisional" if usable else "insufficient",
        f"{len(usable)} 次力量训练有同日或相邻日身体状态记录。"
        if joins
        else "尚无可关联的力量训练记录。",
        window=(joins[0]["date"] if joins else None, joins[-1]["date"] if joins else None),
        facts=association_facts,
        limitations=[
            "这是时间邻近的描述性关联，不能证明因果关系。",
            "身体状态与训练质量均可能受未记录因素影响。",
            "样本量不足时不生成可靠个体阈值。",
        ],
        allowed_actions=[
            "compare_context",
            "adjust_with_warmup_and_reassessment",
            "continue_observation",
        ],
        source_feature_ids=sorted(
            {
                f"strength_set:{row['id']}"
                for row in quality.get("sets", [])
                if row.get("id") is not None
            }
            | {
                source_id
                for item in joins
                for source_id in (item.get("body_state") or {}).get("source_ids", [])
            },
            key=str,
        )[:500],
    )
    card["algorithm_version"] = ALGORITHM_VERSION
    return {
        "card": card,
        "joins": joins,
        "paired_metrics": paired_metrics,
        "body_state": states,
        "sessions": quality["sessions"],
    }


def period_report(
    repo: Repository, period: str = "week", anchor: Optional[str] = None
) -> dict[str, Any]:
    """Return a bounded weekly or monthly report with evidence cards."""
    today = _day(anchor) or date.today()
    if period == "month":
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    else:
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        period = "week"
    q = strength_quality(repo, start.isoformat(), end.isoformat())
    assoc = body_state_strength(repo, start.isoformat(), end.isoformat())
    prior_start = start - (end - start + timedelta(days=1))
    prior_end = start - timedelta(days=1)
    prior = strength_quality(repo, prior_start.isoformat(), prior_end.isoformat())
    current_volumes = [x["volume_kg"] for x in q["sessions"] if x["volume_kg"] is not None]
    previous_volumes = [x["volume_kg"] for x in prior["sessions"] if x["volume_kg"] is not None]
    volume = round(sum(current_volumes), 2) if current_volumes else None
    previous = round(sum(previous_volumes), 2) if previous_volumes else None
    delta = round(volume - previous, 2) if volume is not None and previous is not None else None
    trend = (
        "增加"
        if delta is not None and delta > 0
        else ("减少" if delta is not None and delta < 0 else "无法比较")
    )
    recommendations: list[str] = []
    if not q["sessions"]:
        recommendations.append("先连续记录力量训练的动作、重量和次数，再比较周期变化。")
    else:
        if delta is not None and previous and delta > previous * 0.20:
            recommendations.append(
                "本周期训练量增幅较大；下一周期先保持动作条件和目标次数，观察恢复与动作质量。"
            )
        elif delta is not None and delta < 0:
            recommendations.append(
                "本周期训练量低于上一周期；先核对缺失记录、动作条件和训练安排，再决定是否调整。"
            )
        else:
            recommendations.append(
                "保持动作、器械、变式和活动范围一致，继续记录 RIR/RPE 以便比较。"
            )
        hard_sessions = [
            item
            for item in q["sessions"]
            if (item.get("median_rpe") is not None and item["median_rpe"] >= 9)
            or (item.get("median_rir") is not None and item["median_rir"] <= 1)
        ]
        if hard_sessions:
            recommendations.append(
                "有训练日主观用力偏高；下一次先热身和首组复评，必要时减少重量或组数。"
            )
    if assoc["joins"] and len([x for x in assoc["joins"] if x["body_state"]]) < len(assoc["joins"]):
        recommendations.append(
            "为训练日补充睡眠、疲劳、酸痛或主观状态记录，减少联合分析中的未知项。"
        )
    card = evidence_card(
        f"strength_report_{period}_{start.isoformat()}",
        f"{start.isoformat()} 至 {end.isoformat()} 力量训练报告",
        "usable"
        if q["sessions"] and current_volumes
        else ("provisional" if q["sessions"] else "insufficient"),
        f"本{('月' if period == 'month' else '周')}记录 {len(q['sessions'])} 次训练，总训练量 {volume:.0f} kg；与上一周期相比{trend}。"
        if volume is not None
        else f"本{('月' if period == 'month' else '周')}记录 {len(q['sessions'])} 次训练，但重量或次数记录不完整，暂无法汇总训练量。",
        window=(start.isoformat(), end.isoformat()),
        facts=[
            {"metric": "sessions", "value": len(q["sessions"]), "unit": "sessions"},
            {
                "metric": "volume_kg",
                "value": round(volume, 2) if volume is not None else None,
                "unit": "kg",
            },
            {
                "metric": "previous_volume_kg",
                "value": round(previous, 2) if previous is not None else None,
                "unit": "kg",
            },
            {"metric": "volume_delta_kg", "value": delta, "unit": "kg"},
            {
                "metric": "joined_body_state_sessions",
                "value": len([x for x in assoc["joins"] if x["body_state"]]),
                "unit": "sessions",
            },
        ],
        limitations=[
            "训练量以非热身组的重量×次数汇总；没有时长时不等同于 session-RPE load。",
            "周期比较需要动作、器械和记录完整度相近。",
        ],
        allowed_actions=["review_progression", "plan_next_microcycle", "continue_observation"],
    )
    card["algorithm_version"] = ALGORITHM_VERSION
    return {
        "period": period,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "card": card,
        "strength": q,
        "association": assoc,
        "comparison": {
            "previous_start": prior_start.isoformat(),
            "previous_end": prior_end.isoformat(),
            "volume_delta_kg": delta,
        },
        "recommendations": recommendations,
    }


def today_training_setup(
    repo: Repository,
    exercise_name: str,
    planned_weight_kg: Optional[float] = None,
    planned_reps: Optional[int] = None,
    today: Optional[str] = None,
    *,
    equipment: Optional[str] = None,
    variation: Optional[str] = None,
) -> dict[str, Any]:
    """Suggest a bounded starting range and a reassessment rule for today's lift."""
    day = _day(today) or date.today()
    rows = _strength_rows(repo, None, day - timedelta(days=1))
    key = str(exercise_name).strip().lower()
    equipment_key = str(equipment or "").strip().lower()
    variation_key = str(variation or "").strip().lower()
    candidates = [
        x
        for x in rows
        if _condition(x)[0] == key
        and (not equipment_key or _condition(x)[1] == equipment_key)
        and (not variation_key or _condition(x)[2] == variation_key)
        and not x["warmup"]
    ]
    recent = candidates[-12:]
    weights = [float(x["weight_kg"]) for x in recent if x.get("weight_kg") is not None]
    last = weights[-1] if weights else None
    base = float(planned_weight_kg or last or 0)
    recent_rpe = [float(x["rpe"]) for x in recent if x.get("rpe") is not None]
    recent_rir = [float(x["rir"]) for x in recent if x.get("rir") is not None]
    states = body_state(repo, (day - timedelta(days=7)).isoformat(), day.isoformat())
    state = states[-1] if states else None
    modifier = 0.0
    if state:
        if state.get("sleep_hours") is not None and state["sleep_hours"] < 6:
            modifier -= 0.05
        if state.get("fatigue") is not None and state["fatigue"] >= 7:
            modifier -= 0.05
        if state.get("soreness") is not None and state["soreness"] >= 7:
            modifier -= 0.05
        if state.get("pain_level") is not None and state["pain_level"] >= 5:
            modifier -= 0.05
        if (
            state.get("resting_heart_rate_bpm_deviation") is not None
            and state["resting_heart_rate_bpm_deviation"] >= 8
        ):
            modifier -= 0.05
    if recent_rpe and median(recent_rpe) >= 9:
        modifier -= 0.05
    if recent_rir and median(recent_rir) <= 1:
        modifier -= 0.05
    modifier = max(-0.10, modifier)
    center = round(base * (1 + modifier), 2) if base else None
    lower, upper = (round(center * 0.95, 2), round(center * 1.0, 2)) if center else (None, None)
    card = evidence_card(
        "today_training_setup",
        "今日训练起始设定",
        "provisional" if center else "insufficient",
        f"建议以 {lower:g}–{upper:g} kg 的起始范围进行热身和首组复核。"
        if center
        else "缺少该动作的近期可比重量，无法给出起始范围。",
        window=(day.isoformat(), day.isoformat()),
        facts=[
            {"metric": "reference_last_weight_kg", "value": last, "unit": "kg"},
            {"metric": "suggested_low_kg", "value": lower, "unit": "kg"},
            {"metric": "suggested_high_kg", "value": upper, "unit": "kg"},
            {"metric": "planned_reps", "value": planned_reps, "unit": "reps"},
            {
                "metric": "recent_median_rpe",
                "value": round(median(recent_rpe), 2) if recent_rpe else None,
                "unit": "RPE",
            },
            {
                "metric": "recent_median_rir",
                "value": round(median(recent_rir), 2) if recent_rir else None,
                "unit": "RIR",
            },
            {"metric": "adjustment_fraction", "value": modifier, "unit": "fraction"},
        ],
        limitations=[
            "这是基于近期记录和有限状态信号的训练起始范围，不是精确处方。",
            "先完成热身和首组，若动作速度、技术或主观用力不符合目标，应下调或停止。",
            "单个 HRV 或心率读数不能决定重量。",
            "出现疼痛时应停止或寻求专业评估；系统不判断疼痛原因。",
        ],
        allowed_actions=[
            "warm_up_and_reassess",
            "reduce_load_if_technique_changes",
            "stop_if_pain",
        ],
        source_feature_ids=(
            [f"strength_set:{x['id']}" for x in recent if x.get("id") is not None]
            + (state or {}).get("source_ids", [])
        )[:500],
    )
    card["algorithm_version"] = ALGORITHM_VERSION
    return {
        "card": card,
        "exercise_name": exercise_name,
        "equipment": equipment or "",
        "variation": variation or "",
        "date": day.isoformat(),
        "range_kg": {"low": lower, "high": upper},
        "state": state,
        "recent_sets": recent,
    }


def weekly_report(repo: Repository, anchor: Optional[str] = None) -> dict[str, Any]:
    """Convenience alias for the current Monday–Sunday report."""
    return period_report(repo, "week", anchor)


def monthly_report(repo: Repository, anchor: Optional[str] = None) -> dict[str, Any]:
    """Convenience alias for the calendar-month report."""
    return period_report(repo, "month", anchor)


training_quality_analysis = strength_quality


__all__ = [
    "strength_quality",
    "training_quality_analysis",
    "body_state",
    "body_state_strength",
    "period_report",
    "weekly_report",
    "monthly_report",
    "today_training_setup",
]
