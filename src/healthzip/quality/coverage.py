"""Coverage, inventory and per-feature readiness calculations."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from healthzip.config import Thresholds
from healthzip.db.repository import Repository


def _date_span(values: list[str]) -> tuple[Optional[str], Optional[str], int]:
    clean = sorted({v[:10] for v in values if v})
    if not clean:
        return None, None, 0
    try:
        span = (date.fromisoformat(clean[-1]) - date.fromisoformat(clean[0])).days
    except ValueError:
        span = 0
    return clean[0], clean[-1], span


def inventory(repo: Repository) -> dict[str, Any]:
    result: dict[str, Any] = {"sample_types": [], "workouts": {}, "external": {}, "batches": []}
    for row in repo.rows(
        "SELECT canonical_type,raw_type,COUNT(*) n,MIN(local_date) first_date,MAX(local_date) last_date,COUNT(DISTINCT local_date) observed_days,COUNT(DISTINCT source_name) source_count FROM health_sample GROUP BY canonical_type,raw_type ORDER BY canonical_type"
    ):
        result["sample_types"].append(dict(row))
    for row in repo.rows(
        "SELECT activity_type,COUNT(*) n,MIN(local_date) first_date,MAX(local_date) last_date FROM workout GROUP BY activity_type ORDER BY activity_type"
    ):
        result["workouts"][row["activity_type"]] = dict(row)
    for table in (
        "strength_set",
        "nutrition_day",
        "body_measurement",
        "subjective_log",
        "cycle_event",
    ):
        result["external"][table] = repo.count(table)
    for row in repo.rows("SELECT * FROM import_batch ORDER BY id"):
        d = dict(row)
        result["batches"].append(d)
    return result


def sample_coverage(
    repo: Repository,
    canonical_type: str,
    window_days: Optional[int] = None,
    as_of: Optional[str] = None,
) -> dict[str, Any]:
    args: list[Any] = [canonical_type]
    where = "canonical_type=?"
    if window_days and as_of:
        where += " AND local_date >= date(?, ?)"
        args.extend([as_of[:10], f"-{window_days - 1} day"])
    rows = repo.rows(f"SELECT * FROM health_sample WHERE {where} ORDER BY local_date", tuple(args))
    dates = [r["local_date"] for r in rows if r["local_date"]]
    first, last, span = _date_span(dates)
    return {
        "canonical_type": canonical_type,
        "valid_samples": sum(
            1 for r in rows if r["normalized_value"] is not None or r["category_value"] is not None
        ),
        "sample_count": len(rows),
        "first_date": first,
        "last_date": last,
        "time_span_days": span,
        "observed_days": len(set(dates)),
        "source_count": len({r["source_name"] for r in rows if r["source_name"]}),
        "rows": rows,
    }


def readiness(
    repo: Repository,
    thresholds: Optional[Thresholds] = None,
    window_days: int = 30,
    as_of: Optional[str] = None,
) -> dict[str, dict[str, Any]]:
    t = thresholds or Thresholds()
    out: dict[str, dict[str, Any]] = {}
    if as_of is None:
        latest = repo.one(
            "SELECT MAX(local_date) AS latest FROM health_sample WHERE local_date IS NOT NULL"
        )
        as_of = latest["latest"] if latest and latest["latest"] else None

    def state(count: int, provisional: int, usable: int, present: bool = True) -> str:
        if not present:
            return "not_imported"
        if count >= usable:
            return "usable"
        if count >= provisional:
            return "provisional"
        return "insufficient"

    rhr = sample_coverage(repo, "resting_heart_rate_bpm", window_days, as_of)
    out["resting_heart_rate"] = {
        **{
            k: rhr[k]
            for k in ("valid_samples", "observed_days", "first_date", "last_date", "source_count")
        },
        "status": state(
            rhr["observed_days"], t.rhr_provisional_days, t.rhr_usable_days, rhr["sample_count"] > 0
        ),
        "missing": "需要至少 7 个有效日期"
        if rhr["observed_days"] < t.rhr_provisional_days
        else None,
    }
    hrv = sample_coverage(repo, "hrv_sdnn_ms", window_days, as_of)
    out["hrv_sdnn"] = {
        **{
            k: hrv[k]
            for k in ("valid_samples", "observed_days", "first_date", "last_date", "source_count")
        },
        "status": state(
            hrv["observed_days"], t.hrv_provisional_days, t.hrv_usable_days, hrv["sample_count"] > 0
        ),
        "missing": "HRV 样本稀疏，暂不评价恢复趋势"
        if hrv["observed_days"] < t.hrv_provisional_days
        else None,
    }
    sleep = sample_coverage(repo, "sleep_stage", window_days, as_of)
    # Count distinct local dates containing a sleep interval as a conservative night count.
    out["sleep"] = {
        "valid_samples": sleep["valid_samples"],
        "observed_nights": sleep["observed_days"],
        "first_date": sleep["first_date"],
        "last_date": sleep["last_date"],
        "status": state(
            sleep["observed_days"],
            t.sleep_provisional_nights,
            t.sleep_usable_nights,
            sleep["sample_count"] > 0,
        ),
        "missing": "只显示已有夜晚；缺失夜晚不代表零睡眠"
        if sleep["observed_days"] < t.sleep_provisional_nights
        else None,
    }
    vo2 = sample_coverage(repo, "vo2_max_ml_kg_min", window_days, as_of)
    out["vo2_max"] = {
        "valid_samples": vo2["valid_samples"],
        "observed_days": vo2["observed_days"],
        "first_date": vo2["first_date"],
        "last_date": vo2["last_date"],
        "status": state(vo2["valid_samples"], 1, t.vo2_usable_points, vo2["sample_count"] > 0),
        "missing": "暂无足够估计点" if vo2["valid_samples"] < t.vo2_usable_points else None,
    }
    weight = sample_coverage(repo, "body_mass_kg", window_days, as_of)
    external_weight = repo.rows(
        "SELECT local_date,value FROM body_measurement WHERE canonical_type='body_mass_kg' AND value IS NOT NULL ORDER BY local_date"
    )
    weight_days = {row["local_date"] for row in weight["rows"] if row["local_date"]} | {
        row["local_date"] for row in external_weight if row["local_date"]
    }
    weight_first = min(weight_days) if weight_days else None
    weight_last = max(weight_days) if weight_days else None
    weight_span = (
        (date.fromisoformat(weight_last) - date.fromisoformat(weight_first)).days
        if weight_first and weight_last
        else 0
    )
    weight_valid = weight["valid_samples"] + len(external_weight)
    out["body_mass"] = {
        "valid_samples": weight_valid,
        "observed_days": len(weight_days),
        "time_span_days": weight_span,
        "first_date": weight_first,
        "last_date": weight_last,
        "status": "usable"
        if weight_valid >= t.weight_usable_points and weight_span >= t.weight_usable_span_days
        else (
            "provisional"
            if weight_valid >= t.weight_provisional_points
            else ("insufficient" if weight["sample_count"] or external_weight else "not_imported")
        ),
        "missing": "目前只能显示称重记录，不能判断趋势"
        if weight_valid < t.weight_provisional_points
        else None,
    }
    workouts = repo.rows(
        "SELECT COUNT(*) n,COUNT(DISTINCT local_date) days,MIN(local_date) first_date,MAX(local_date) last_date FROM workout"
    )
    w = dict(workouts[0])
    out["workouts"] = {
        **w,
        "status": "usable"
        if w["days"] and w["days"] >= 14
        else ("provisional" if w["n"] else "not_imported"),
        "missing": None if w["n"] else "尚未导入训练会话",
    }
    ss = repo.one(
        "SELECT COUNT(DISTINCT exercise_name || '|' || equipment || '|' || variation) n,COUNT(*) sets FROM strength_set"
    )
    out["strength"] = {
        "valid_samples": int(ss["sets"]),
        "exposures": int(ss["n"]),
        "status": "usable"
        if ss["n"] >= t.strength_usable_exposures
        else ("provisional" if ss["sets"] else "not_imported"),
        "missing": "需要导入更多同动作 / 器械记录"
        if ss["n"] < t.strength_usable_exposures
        else None,
    }
    nd = repo.rows(
        "SELECT COUNT(*) n,SUM(CASE WHEN log_status='complete' THEN 1 ELSE 0 END) complete_days FROM nutrition_day"
    )[0]
    out["nutrition"] = {
        "days": int(nd["n"] or 0),
        "complete_days": int(nd["complete_days"] or 0),
        "status": "usable"
        if (nd["complete_days"] or 0) >= t.nutrition_usable_complete_days
        else ("provisional" if nd["n"] else "not_imported"),
        "missing": "请标记完整记录日；部分记录不能断言全天摄入不足"
        if (nd["complete_days"] or 0) < t.nutrition_usable_complete_days
        else None,
    }
    if as_of:
        for value in out.values():
            last = value.get("last_date") or value.get("last_observed_at")
            if last:
                value["status"] = freshness_state(value["status"], last, as_of, window_days)
    return out


def freshness_state(
    status: str, last_observed: Optional[str], as_of: Optional[str], stale_after_days: int = 30
) -> str:
    """Mark an otherwise usable historical signal stale only when a reference date is explicit."""
    if not last_observed or not as_of:
        return status
    try:
        age = (date.fromisoformat(as_of[:10]) - date.fromisoformat(last_observed[:10])).days
    except ValueError:
        return status
    return "stale" if age > stale_after_days and status in {"usable", "provisional"} else status
