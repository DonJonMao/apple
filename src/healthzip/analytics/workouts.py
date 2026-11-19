"""Current Workout inventory, with local calendar grouping and recorded units.

This view is descriptive: it does not combine Workout energy with health_sample
energy or estimate true expenditure. Only current active records participate.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from healthzip.normalize import normalize_value, parse_number

ENERGY_TYPE = "HKQuantityTypeIdentifierActiveEnergyBurned"
ACTIVITY_NAMES = {
    "AmericanFootball": "美式橄榄球", "Archery": "射箭", "AustralianFootball": "澳式足球",
    "Badminton": "羽毛球", "Barre": "芭蕾塑形", "Baseball": "棒球", "Basketball": "篮球",
    "Bowling": "保龄球", "Boxing": "拳击", "Climbing": "攀岩", "CoreTraining": "核心训练",
    "Cricket": "板球", "CrossCountrySkiing": "越野滑雪", "CrossTraining": "交叉训练",
    "Curling": "冰壶", "Cycling": "骑行", "Dance": "舞蹈", "DanceInspiredTraining": "舞蹈训练",
    "DiscSports": "飞盘", "DownhillSkiing": "高山滑雪", "Elliptical": "椭圆机",
    "EquestrianSports": "马术", "Fencing": "击剑", "Fishing": "钓鱼", "FitnessGaming": "健身游戏",
    "Flexibility": "柔韧训练", "FunctionalStrengthTraining": "功能性力量训练", "Golf": "高尔夫",
    "Gymnastics": "体操", "HandCycling": "手摇自行车", "Handball": "手球",
    "HighIntensityIntervalTraining": "高强度间歇训练", "Hiking": "徒步", "Hockey": "曲棍球",
    "Hunting": "狩猎", "JumpRope": "跳绳", "Kickboxing": "自由搏击", "Lacrosse": "长曲棍球",
    "MartialArts": "武术", "MindAndBody": "身心训练", "MixedCardio": "混合有氧训练",
    "MixedMetabolicCardioTraining": "混合有氧训练", "Other": "其他运动", "PaddleSports": "桨类运动",
    "Pickleball": "匹克球", "Pilates": "普拉提", "Play": "休闲活动", "PreparationAndRecovery": "准备与恢复",
    "Racquetball": "美式壁球", "Rowing": "划船", "Rugby": "英式橄榄球", "Running": "跑步",
    "Sailing": "帆船", "SkatingSports": "滑冰", "Snowboarding": "单板滑雪", "SnowSports": "雪上运动",
    "Soccer": "足球", "SocialDance": "交谊舞", "Softball": "垒球", "Squash": "壁球",
    "StairClimbing": "爬楼梯", "Stairs": "楼梯训练", "StepTraining": "踏板训练", "SurfingSports": "冲浪",
    "Swimming": "游泳", "TableTennis": "乒乓球", "TaiChi": "太极", "Tennis": "网球",
    "TrackAndField": "田径", "TraditionalStrengthTraining": "传统力量训练", "Transition": "转换阶段",
    "UnderwaterDiving": "潜水", "Volleyball": "排球", "Walking": "步行", "WaterFitness": "水中健身",
    "WaterPolo": "水球", "WaterSports": "水上运动", "WheelchairRunPace": "轮椅跑步配速",
    "WheelchairWalkPace": "轮椅步行配速", "Wrestling": "摔跤", "Yoga": "瑜伽",
}
_ACTIVITY_NAMES_CASEFOLD = {key.casefold(): value for key, value in ACTIVITY_NAMES.items()}


def activity_name(raw_type):
    if not raw_type:
        return "未记录运动类型"
    name = str(raw_type).removeprefix("HKWorkoutActivityType")
    if name.casefold() in _ACTIVITY_NAMES_CASEFOLD:
        return _ACTIVITY_NAMES_CASEFOLD[name.casefold()]
    # Some incremental sources already supply a Chinese name. Preserve that
    # source description; do not guess an equivalence for unfamiliar types.
    return str(raw_type) if any("\u4e00" <= ch <= "\u9fff" for ch in name) else "未识别运动类型"


def _instant(value):
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _nonnegative(value):
    number = parse_number(value)
    return number if number is not None and number >= 0 else None


def _energy(value, unit):
    number, _, _ = normalize_value(ENERGY_TYPE, value, unit)
    return _nonnegative(number)


def _recorded_energy(workout, statistics):
    header = _energy(workout["energy_value"], workout["energy_unit"])
    if header is not None:
        return header, "Workout 总能量字段", ""
    start, end = _instant(workout["start_utc"]), _instant(workout["end_utc"])
    whole = [stat for stat in statistics if start is not None and end is not None
             and _instant(stat["statistic_start"]) == start and _instant(stat["statistic_end"]) == end]
    if whole:
        values = [_energy(stat["sum_value"], stat["unit"]) for stat in whole]
        # Repeated identical imports may repeat the same statistic. Accept one
        # unique value, but never add duplicates, subintervals or conflicting sums.
        if all(value is not None for value in values) and len(set(values)) == 1:
            return values[0], "Workout 整场活动能量统计", ""
        return None, "未记录可汇总能量", "整场活动能量统计冲突或数值、单位不明"
    return None, "未记录可汇总能量", "缺少有效总能量或唯一整场活动能量统计"


def workout_inventory(repo, timezone_name="Asia/Shanghai"):
    """Read current active Workouts and their own energy statistics in one query."""
    zone = ZoneInfo(timezone_name)
    joined = repo.rows("""SELECT w.*, s.statistic_start, s.statistic_end,
        s.sum_value, s.unit AS statistic_unit
        FROM workout w LEFT JOIN workout_statistic s
          ON s.workout_id=w.id AND s.raw_type=?
        WHERE w.record_status='active' ORDER BY w.id,s.id""", (ENERGY_TYPE,))
    grouped = {}
    for row in joined:
        item = dict(row)
        workout, stats = grouped.setdefault(item["id"], (item, []))
        if item["statistic_start"] is not None or item["sum_value"] is not None:
            stats.append({"statistic_start": item["statistic_start"],
                          "statistic_end": item["statistic_end"],
                          "sum_value": item["sum_value"], "unit": item["statistic_unit"]})
    output, undated = [], 0
    for workout, stats in grouped.values():
        start = _instant(workout["start_utc"])
        if start is None:
            undated += 1
            continue
        local_start = start.astimezone(zone)
        energy, energy_source, reason = _recorded_energy(workout, stats)
        output.append({
            "local_start": local_start, "local_date": local_start.date(),
            "activity_name": activity_name(workout["activity_type"]),
            "raw_activity_type": workout["activity_type"],
            "duration_seconds": _nonnegative(workout["duration_seconds"]),
            "energy_kcal": energy, "energy_source": energy_source, "energy_reason": reason,
            "raw_energy_value": workout["energy_value"], "raw_energy_unit": workout["energy_unit"],
            "source_name": workout["source_name"],
            "suspected_duplicate": bool(workout["suspected_duplicate"]),
        })
    return {"rows": sorted(output, key=lambda row: row["local_start"], reverse=True),
            "undated_count": undated, "timezone": timezone_name}


def _totals(rows):
    durations = [row["duration_seconds"] for row in rows if row["duration_seconds"] is not None]
    energies = [row["energy_kcal"] for row in rows if row["energy_kcal"] is not None]
    return {"workout_count": len(rows), "duration_seconds": sum(durations) if durations else None,
            "missing_duration_count": len(rows) - len(durations),
            "energy_kcal": sum(energies) if energies else None,
            "missing_energy_count": len(rows) - len(energies),
            "suspected_duplicate_count": sum(row["suspected_duplicate"] for row in rows)}


def _period(day, period):
    if period == "week":
        start = day - timedelta(days=day.weekday())
        iso = day.isocalendar()
        return start, start + timedelta(days=6), f"{iso[0]}年第{iso[1]:02d}周"
    if period == "month":
        start = day.replace(day=1)
        following = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
        return start, following - timedelta(days=1), f"{day.year}年{day.month:02d}月"
    if period == "year":
        return date(day.year, 1, 1), date(day.year, 12, 31), f"{day.year}年"
    raise ValueError("unsupported_workout_period")


def summarize_workouts(rows, period, start_date, end_date):
    """Group by inclusive local start date; empty or missing values stay unknown."""
    if period not in {"week", "month", "year"}:
        raise ValueError("unsupported_workout_period")
    if start_date > end_date:
        raise ValueError("workout_date_range_reversed")
    selected = [row for row in rows if start_date <= row["local_date"] <= end_date]
    groups = defaultdict(list)
    for row in selected:
        groups[_period(row["local_date"], period)].append(row)
    periods = []
    for (first, last, label), group in sorted(groups.items()):
        periods.append({"period_start": first, "period_end": last, "period_label": label,
                        "selected_start": max(first, start_date), "selected_end": min(last, end_date),
                        "partial_period": first < start_date or last > end_date, **_totals(group)})
    return {"rows": selected, "periods": periods, "totals": _totals(selected),
            "start_date": start_date, "end_date": end_date, "period": period}
