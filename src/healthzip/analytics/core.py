"""Deterministic, conservative analytics and Evidence Cards."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from statistics import median, quantiles
from typing import Any, Optional

from healthzip.db.repository import Repository
from healthzip.quality.coverage import readiness

ALGORITHM_VERSION = "0.1.0"


def _mad(values: list[float]) -> float:
    m = median(values)
    return median([abs(x - m) for x in values])


def evidence_card(
    card_id: str,
    title: str,
    status: str,
    summary: str,
    *,
    window: tuple[Optional[str], Optional[str]] = (None, None),
    facts: Optional[list[dict[str, Any]]] = None,
    limitations: Optional[list[str]] = None,
    allowed_actions: Optional[list[str]] = None,
    source_feature_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    return {
        "id": card_id,
        "title": title,
        "status": status,
        "window": {"start": window[0], "end": window[1]},
        "summary": summary,
        "facts": facts or [],
        "limitations": limitations or [],
        "allowed_actions": allowed_actions or ["continue_observation"],
        "source_feature_ids": source_feature_ids or [],
        "algorithm_version": ALGORITHM_VERSION,
    }


def _values(repo: Repository, canonical: str, window_days: int = 30) -> list[dict[str, Any]]:
    end = date.today()
    start = end - timedelta(days=max(1, int(window_days)) - 1)
    return [dict(r) for r in repo.rows(
        "SELECT * FROM health_sample WHERE canonical_type=? AND normalized_value IS NOT NULL "
        "AND record_status='active' AND local_date BETWEEN ? AND ? ORDER BY local_date,start_utc",
        (canonical, start.isoformat(), end.isoformat()),
    )]


def heart_analysis(repo: Repository, window_days: int = 30) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    for canonical, title, unit, minimum in [
        ("resting_heart_rate_bpm", "静息心率趋势", "bpm", 7),
        ("hrv_sdnn_ms", "HRV-SDNN 基线", "ms", 5),
    ]:
        rows = _values(repo, canonical, window_days)
        grouped: dict[str, list[float]] = {}
        for r in rows:
            grouped.setdefault(r["local_date"], []).append(float(r["normalized_value"]))
        daily = [median(v) for _, v in sorted(grouped.items())]
        if not daily:
            cards.append(
                evidence_card(
                    canonical,
                    title,
                    "not_imported",
                    "目前没有该类记录。",
                    limitations=["没有记录不等于没有佩戴或没有该生理状态。"],
                    allowed_actions=["review_data_sources"],
                )
            )
            continue
        status = (
            "usable"
            if len(daily) >= (14 if canonical.startswith("resting") else 10)
            else ("provisional" if len(daily) >= minimum else "insufficient")
        )
        m = median(daily)
        mad = _mad(daily)
        last = daily[-1]
        z = None if mad == 0 or len(daily) < minimum else (last - m) / (1.4826 * mad)
        qs = quantiles(daily, n=4, method="inclusive") if len(daily) >= 2 else []
        limitations = []
        if status != "usable":
            limitations.append(f"当前仅有 {len(daily)} 个有效日期，未达到稳定趋势的工程门槛。")
        if mad == 0:
            limitations.append("MAD=0，个人偏离量不可估计。")
        cards.append(
            evidence_card(
                canonical,
                title,
                status,
                f"最近 {len(daily)} 个日期有记录，中位数为 {m:.1f} {unit}。"
                if status != "insufficient"
                else "数据仍不足，暂不评价趋势。",
                window=(min(grouped), max(grouped)),
                facts=[
                    {
                        "metric": canonical,
                        "value": round(last, 3),
                        "unit": unit,
                        "n_days": len(daily),
                    },
                    {
                        "metric": "baseline_median",
                        "value": round(m, 3),
                        "unit": unit,
                        "n_days": len(daily),
                    },
                    {"metric": "MAD", "value": round(mad, 3), "unit": unit},
                    {
                        "metric": "robust_z",
                        "value": round(z, 3) if z is not None else None,
                        "unit": "personal_deviation",
                    },
                    {"metric": "quartiles", "value": qs, "unit": unit},
                ],
                limitations=limitations,
                source_feature_ids=[f"daily_{canonical}_{min(grouped)}_{max(grouped)}"],
            )
        )
    return {"cards": cards}


def sleep_analysis(repo: Repository, window_days: int = 30) -> dict[str, Any]:
    from healthzip.temporal import sleep_nights

    end = date.today()
    start = end - timedelta(days=max(1, int(window_days)) - 1)
    values = sleep_nights(
        [dict(r) for r in repo.rows("SELECT * FROM health_sample WHERE canonical_type='sleep_stage'")],
        start.isoformat(), end.isoformat(),
    )
    status = (
        "usable"
        if len(values) >= 14
        else ("provisional" if len(values) >= 3 else ("insufficient" if values else "not_imported"))
    )
    summary = (
        f"已记录 {len(values)} 个夜晚，平均睡眠 {sum(x['sleep_hours'] for x in values) / len(values):.1f} 小时。"
        if values
        else "目前没有可用睡眠区间。"
    )
    card = evidence_card(
        "sleep_duration",
        "睡眠时长与作息",
        status,
        summary,
        window=(values[0]["date"] if values else None, values[-1]["date"] if values else None),
        facts=[
            {"metric": "sleep_nights", "value": len(values), "unit": "nights"},
            {
                "metric": "sleep_hours_mean",
                "value": round(sum(x["sleep_hours"] for x in values) / len(values), 2)
                if values
                else None,
                "unit": "h",
            },
        ],
        limitations=["缺失夜晚不代表零睡眠。", "该模块不做临床睡眠诊断。"]
        if values
        else ["需要导入睡眠区间记录。"],
        allowed_actions=["review_sleep_window", "continue_observation"],
    )
    return {"card": card, "nights": values}


def workout_analysis(repo: Repository, window_days: int = 30) -> dict[str, Any]:
    rows = [
        dict(r)
        for r in repo.rows("SELECT * FROM workout WHERE record_status='active' ORDER BY local_date")
    ]
    by_week: dict[str, dict[str, Any]] = {}
    for r in rows:
        try:
            d = date.fromisoformat(r["local_date"])
        except (ValueError, TypeError):
            continue
        monday = d - timedelta(days=d.weekday())
        key = monday.isoformat()
        item = by_week.setdefault(
            key,
            {"week": key, "sessions": 0, "duration_minutes": 0.0, "distance_m": 0.0, "types": {}},
        )
        item["sessions"] += 1
        item["duration_minutes"] += float(r["duration_seconds"] or 0) / 60
        item["distance_m"] += float(r["distance_value"] or 0)
        item["types"][r["activity_type"]] = item["types"].get(r["activity_type"], 0) + 1
    weeks = list(by_week.values())
    status = "usable" if len(weeks) >= 2 else ("provisional" if weeks else "not_imported")
    card = evidence_card(
        "workout_summary",
        "训练频率与时长",
        status,
        f"已记录 {len(rows)} 次训练，共 {sum(x['duration_minutes'] for x in weeks):.0f} 分钟。"
        if rows
        else "目前没有训练会话记录。",
        facts=[
            {"metric": "workout_sessions", "value": len(rows), "unit": "sessions"},
            {"metric": "weeks", "value": len(weeks), "unit": "weeks"},
        ],
        limitations=[
            "不同运动类型不合并为无量纲健康分。",
            "WorkoutStatistics 是摘要，不等于逐秒心率序列。",
        ]
        if rows
        else ["需要导入 Workout 记录。"],
    )
    return {"card": card, "weeks": weeks}


def _theil_sen(points: list[tuple[int, float]]) -> Optional[float]:
    slopes: list[float] = []
    for i, (x1, y1) in enumerate(points):
        for x2, y2 in points[i + 1 :]:
            if x2 != x1:
                slopes.append((y2 - y1) / (x2 - x1))
    return median(slopes) if slopes else None


def weight_analysis(repo: Repository, window_days: int = 30) -> dict[str, Any]:
    rows = [
        dict(r)
        for r in repo.rows(
            "SELECT local_date,normalized_value,source_name FROM health_sample WHERE canonical_type='body_mass_kg' AND normalized_value IS NOT NULL AND record_status='active' ORDER BY local_date"
        )
    ]
    rows.extend(
        {"local_date": r["local_date"], "normalized_value": r["value"], "source_name": r["source"]}
        for r in repo.rows(
            "SELECT local_date,value,source FROM body_measurement WHERE canonical_type='body_mass_kg' AND value IS NOT NULL ORDER BY local_date"
        )
    )
    end = date.today()
    start = end - timedelta(days=max(1, int(window_days)) - 1)
    rows = [r for r in rows if r["local_date"] and start.isoformat() <= r["local_date"] <= end.isoformat()]
    by_day: dict[str, list[float]] = {}
    for r in rows:
        by_day.setdefault(r["local_date"], []).append(float(r["normalized_value"]))
    daily = [(d, median(v)) for d, v in sorted(by_day.items())]
    points = [(date.fromisoformat(d).toordinal(), y) for d, y in daily]
    slope = _theil_sen(points)
    status = (
        "usable"
        if len(daily) >= 5
        and (date.fromisoformat(daily[-1][0]) - date.fromisoformat(daily[0][0])).days >= 14
        else (
            "provisional" if len(daily) >= 2 else ("not_imported" if not daily else "insufficient")
        )
    )
    card = evidence_card(
        "weight_trend",
        "体重趋势",
        status,
        f"已记录 {len(daily)} 个称重日期。"
        + (
            f"稳健斜率约 {slope * 7:.2f} kg/周。"
            if slope is not None and status == "usable"
            else "当前只能显示称重记录，不能判断稳定趋势。"
        ),
        window=(daily[0][0] if daily else None, daily[-1][0] if daily else None),
        facts=[
            {"metric": "weight_days", "value": len(daily), "unit": "days"},
            {
                "metric": "weight_slope",
                "value": slope * 7 if slope is not None else None,
                "unit": "kg/week",
            },
        ],
        limitations=[
            "短期变化也可能包含水分、糖原、胃肠内容物和称量条件。",
            "不能据此判断脂肪、肌肉或水分的具体变化。",
        ]
        if daily
        else ["需要导入体重记录。"],
    )
    return {
        "card": card,
        "daily": [{"date": d, "kg": y} for d, y in daily],
        "slope_kg_per_day": slope,
    }


def vo2_analysis(repo: Repository) -> dict[str, Any]:
    rows = [
        dict(r)
        for r in repo.rows(
            "SELECT local_date,normalized_value,source_name FROM health_sample WHERE canonical_type='vo2_max_ml_kg_min' AND normalized_value IS NOT NULL AND record_status='active' ORDER BY local_date"
        )
    ]
    status = (
        "usable"
        if len(rows) >= 2
        and (
            date.fromisoformat(rows[-1]["local_date"]) - date.fromisoformat(rows[0]["local_date"])
        ).days
        >= 14
        else ("provisional" if rows else "not_imported")
    )
    card = evidence_card(
        "vo2_max_trend",
        "有氧适能（Apple 估计值）",
        status,
        f"有 {len(rows)} 个估计点。" if rows else "目前没有 VO₂ max 估计记录。",
        window=(rows[0]["local_date"] if rows else None, rows[-1]["local_date"] if rows else None),
        facts=[
            {
                "metric": "vo2_max",
                "value": rows[-1]["normalized_value"] if rows else None,
                "unit": "mL/(kg·min)",
                "n": len(rows),
            }
        ],
        limitations=[
            "这是 Apple 的估计值，不是气体分析仪实测。",
            "不能把相对值变化简单归因于减重。",
        ]
        if rows
        else ["需要符合条件的 Apple VO₂ max 估计点。"],
    )
    return {"card": card, "points": rows}


def strength_analysis(repo: Repository) -> dict[str, Any]:
    # A single implementation owns load semantics and formula applicability.
    from healthzip.analytics.p1 import strength_quality

    result = strength_quality(repo)
    return {"card": result["card"], "groups": result["series"], "series": result["series"]}


def nutrition_analysis(repo: Repository) -> dict[str, Any]:
    rows = [dict(r) for r in repo.rows("SELECT * FROM nutrition_day ORDER BY day")]
    if not rows:
        mapping = {
            "dietary_energy_kcal": "energy_kcal",
            "dietary_protein_g": "protein_g",
            "dietary_carbohydrates_g": "carbohydrates_g",
            "dietary_fat_g": "fat_g",
        }
        by_day: dict[str, dict[str, Any]] = {}
        for r in repo.rows(
            "SELECT local_date,canonical_type,normalized_value FROM health_sample WHERE canonical_type IN ('dietary_energy_kcal','dietary_protein_g','dietary_carbohydrates_g','dietary_fat_g') AND normalized_value IS NOT NULL AND record_status='active' ORDER BY local_date"
        ):
            item = by_day.setdefault(
                r["local_date"],
                {"day": r["local_date"], "log_status": "unknown", "source": "HealthKit"},
            )
            field = mapping[r["canonical_type"]]
            item[field] = (item.get(field) or 0) + float(r["normalized_value"])
        rows = list(by_day.values())
    complete = [r for r in rows if r["log_status"] == "complete"]
    energy = sum(float(r.get("energy_kcal") or 0) for r in rows if r.get("energy_kcal") is not None)
    protein = sum(float(r.get("protein_g") or 0) for r in rows if r.get("protein_g") is not None)
    status = "usable" if len(complete) >= 7 else ("provisional" if rows else "not_imported")
    card = evidence_card(
        "nutrition_completeness",
        "营养记录与完整度",
        status,
        f"已记录 {len(rows)} 天，其中完整记录 {len(complete)} 天。"
        if rows
        else "尚未导入营养记录。",
        facts=[
            {"metric": "logged_days", "value": len(rows), "unit": "days"},
            {"metric": "complete_days", "value": len(complete), "unit": "days"},
            {"metric": "logged_energy_total", "value": energy, "unit": "kcal"},
            {"metric": "logged_protein_total", "value": protein, "unit": "g"},
        ],
        limitations=["部分或未确认的日期只代表已记录部分，不能断言全天摄入不足。"]
        if rows
        else ["需要导入营养 CSV 或 HealthKit 营养样本。"],
    )
    return {"card": card, "days": rows}


def cycle_analysis(repo: Repository) -> dict[str, Any]:
    rows = [
        dict(r)
        for r in repo.rows(
            "SELECT * FROM cycle_event WHERE canonical_type='menstrual_flow' ORDER BY event_date"
        )
    ]
    card = evidence_card(
        "cycle_review",
        "周期记录回顾",
        "provisional" if rows else "not_imported",
        f"已记录 {len(rows)} 个出血事件日期。" if rows else "周期功能未启用或没有导入记录。",
        window=(rows[0]["event_date"] if rows else None, rows[-1]["event_date"] if rows else None),
        facts=[{"metric": "observed_bleeding_events", "value": len(rows), "unit": "events"}],
        limitations=[
            "一个周期只能做记录回顾；不确认排卵、避孕或医学状态。",
            "缺少记录不等于没有月经。",
        ]
        if rows
        else ["周期数据默认是可选功能。"],
    )
    return {"card": card, "events": rows}


def all_analysis(repo: Repository, window_days: int = 30) -> dict[str, Any]:
    # P1 strength/body-state functions are kept in a separate module to make
    # their more opinionated joins easy to audit.  Import lazily here because
    # that module reuses ``evidence_card`` from this core module.
    from healthzip.analytics.p1 import (
        body_state,
        body_state_strength,
        period_report,
        strength_quality,
    )

    end = date.today()
    start = end - timedelta(days=max(1, int(window_days)) - 1)
    p1_strength = strength_quality(repo, start.isoformat(), end.isoformat())
    p1_state = body_state(repo, start.isoformat(), end.isoformat())
    p1_joined = body_state_strength(repo, start.isoformat(), end.isoformat())
    output = {
        "heart": heart_analysis(repo, window_days),
        "sleep": sleep_analysis(repo, window_days),
        "workouts": workout_analysis(repo, window_days),
        "weight": weight_analysis(repo, window_days),
        "vo2": vo2_analysis(repo),
        "strength": strength_analysis(repo),
        "nutrition": nutrition_analysis(repo),
        "cycle": cycle_analysis(repo),
        "readiness": readiness(repo, window_days=window_days),
        # Deterministic P1 outputs. ``week_report`` and ``month_report`` use
        # the current date as their anchor and are intentionally separate from
        # the user-selected trend window.
        "strength_quality": p1_strength,
        "body_state": p1_state,
        "body_state_strength": p1_joined,
        "week_report": period_report(repo, "week"),
        "month_report": period_report(repo, "month"),
    }

    from healthzip.analytics.v13 import analyze, metric_card
    output["v13"] = analyze(repo, window_days)
    cutoff = output["v13"]["cutoff_time"]
    output["period_snapshots"] = {period: analyze(repo, cutoff_time=cutoff, period=period)
                                  for period in ("week", "month")}
    metrics = output["v13"]["metrics"]
    daily = metrics["REPORT-STATE-SUMMARY"].get("daily_facts", [])
    output["sleep"]["nights"] = [{"date": x["date"], "sleep_hours": x["value"] / 60,
        "series_id": x.get("series_id"), "series_label": x.get("series_label"),
        "source": x.get("source_id"), "source_ids": x.get("source_record_ids", []),
        "episode_complete": x.get("episode_complete"), "algorithm_version": metrics["REPORT-STATE-SUMMARY"]["algorithm_version"]}
        for x in daily if x.get("series_id") == "observed_sleep_by_wake_date" and x.get("value") is not None]
    output["weight"]["daily"] = [{"date": x["date"], "kg": x["value"], "source": source,
        "source_ids": x["source_ids"], "algorithm_version": metrics["BODY-MASS-DAILY"]["algorithm_version"]}
        for source, values in (metrics["BODY-MASS-DAILY"]["value"] or {}).items() for x in values]
    output["heart"]["cards"] = [metric_card(metrics[k]) for k in ("STATE-RHR", "STATE-SDNN")]
    for key, metric_id in (("sleep", "STATE-SLEEP-24H"), ("weight", "BODY-MASS-TREND"),
                           ("strength", "STR-01")):
        output[key]["card"] = metric_card(metrics[metric_id])
    return output


def persist_analysis(repo: Repository, analysis: dict[str, Any]) -> None:
    """Persist Evidence Cards and selected daily/weekly features for rebuildability."""
    now = datetime.now(timezone.utc).isoformat()
    if analysis.get("v13"):
        from healthzip.analytics.v13 import persist
        persist(repo, analysis["v13"])
        for period_result in analysis.get("period_snapshots", {}).values():
            persist(repo, period_result)

    def walk_cards(value: Any):
        if isinstance(value, dict):
            if {"id", "title", "status", "summary"}.issubset(value):
                yield value
            else:
                for child in value.values():
                    yield from walk_cards(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk_cards(child)

    seen: set[str] = set()
    for card in walk_cards(analysis):
        if card["id"] in seen:
            continue
        seen.add(card["id"])
        window = card.get("window", {})
        repo.conn.execute(
            "INSERT OR REPLACE INTO insight(id,title,status,window_start,window_end,summary,facts_json,limitations_json,allowed_actions_json,source_feature_ids_json,algorithm_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                card["id"],
                card.get("title"),
                card.get("status"),
                window.get("start"),
                window.get("end"),
                card.get("summary"),
                json.dumps(card.get("facts", []), ensure_ascii=False),
                json.dumps(card.get("limitations", []), ensure_ascii=False),
                json.dumps(card.get("allowed_actions", []), ensure_ascii=False),
                json.dumps(card.get("source_feature_ids", []), ensure_ascii=False),
                card.get("algorithm_version", ALGORITHM_VERSION),
                now,
            ),
        )

    def save_daily(
        rows: list[dict[str, Any]],
        key: str,
        metric: str,
        value_field: str,
        unit: str,
        *,
        algorithm_version: str = ALGORITHM_VERSION,
        quality_state: str = "provisional",
    ) -> None:
        for row in rows:
            day = row.get("date") or row.get("local_date")
            if not day or row.get(value_field) is None:
                continue
            source_ids = row.get("source_ids")
            if source_ids is None:
                source_ids = [
                    f"strength_set:{source_id}" for source_id in (row.get("source_set_ids") or [])
                ] + [
                    f"strength_session:{source_id}"
                    for source_id in (row.get("source_session_ids") or [])
                ]
            source_ids = [str(source_id) for source_id in source_ids]
            sample_count = row.get("sample_count")
            if sample_count is None:
                sample_count = len(row.get("source_set_ids") or row.get("source_ids") or []) or 1
            repo.conn.execute(
                "INSERT OR REPLACE INTO daily_feature(feature_key,local_date,metric,value,unit,sample_count,quality_state,window_start,window_end,algorithm_version,source_ids_json,limitations_json,computed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"{key}_{day}_{algorithm_version}_{row.get('session_id', 'daily')}_{row.get('source', '')}",
                    day,
                    metric,
                    row[value_field],
                    unit,
                    sample_count,
                    quality_state,
                    day,
                    day,
                    algorithm_version,
                    json.dumps(source_ids, ensure_ascii=False),
                    json.dumps(row.get("limitations") or [], ensure_ascii=False),
                    now,
                ),
            )

    save_daily(
        analysis.get("sleep", {}).get("nights", []), "sleep", "sleep_hours", "sleep_hours", "h"
    )
    save_daily(analysis.get("weight", {}).get("daily", []), "weight", "body_mass", "kg", "kg")
    save_daily(
        analysis.get("vo2", {}).get("points", []),
        "vo2",
        "vo2_max",
        "normalized_value",
        "mL/(kg·min)",
    )
    for week in analysis.get("workouts", {}).get("weeks", []):
        save_daily(
            [{"date": week.get("week"), "duration_minutes": week.get("duration_minutes")}],
            "workout",
            "workout_duration",
            "duration_minutes",
            "min",
        )

    # Persist the P1 daily body-state and strength-session features as
    # rebuildable rows.  Missing values remain missing; they are never written
    # as zeroes.
    for state in analysis.get("body_state", []):
        for metric, unit in (
            ("sleep_hours", "h"),
            ("resting_heart_rate_bpm", "bpm"),
            ("hrv_sdnn_ms", "ms"),
            ("fatigue", "score"),
            ("soreness", "score"),
        ):
            save_daily(
                [state],
                f"body_state_{metric}",
                metric,
                metric,
                unit,
                algorithm_version="p1-1.3.0",
            )
    for session in analysis.get("strength_quality", {}).get("sessions", []):
        save_daily(
            [session],
            "strength",
            "strength_volume",
            "volume_kg",
            "kg·reps",
            algorithm_version="p1-1.3.0",
        )
    repo.conn.commit()
