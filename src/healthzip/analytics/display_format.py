"""Display-only precision and units; never feed formatted values into analysis."""
from __future__ import annotations


def local_timestamp(value, timezone_name, *, date_only=False):
    """Display one instant in the analysis zone; the original value stays frozen."""
    from zoneinfo import ZoneInfo

    from healthzip.science.contracts import instant
    if not value:
        return "未记录"
    at = instant(value).astimezone(ZoneInfo(timezone_name))
    return at.strftime("%Y-%m-%d" if date_only else "%Y-%m-%d %H:%M")


def display_unit(unit, kind=None):
    if unit == "min" and (kind == "sleep_stage" or str(kind).startswith("STATE-SLEEP")):
        return "小时"
    return {"count/min": "次/分" if kind == "respiratory_rate_bpm" else "bpm",
            "fraction": "%", "degC": "℃", "count": "次", "min": "分钟",
            "count/hr": "次/小时"}.get(unit, unit or "")


def display_value(value, unit, kind=None):
    if value is None:
        return None
    if unit == "fraction":
        return value * 100
    if unit == "min" and (kind == "sleep_stage" or str(kind).startswith("STATE-SLEEP")):
        return value / 60
    return value


def display_precision(unit, kind=None):
    if unit in {"count", "次", "场", "组"}:
        return 0
    if unit in {"m/s", "m"} and kind not in {"six_minute_walk_m"}:
        return 2
    if unit == "degC":
        return 2
    return 1


def format_measurement(value, unit, *, kind=None, signed=False):
    if value is None:
        return "未知"
    value = display_value(value, unit, kind)
    # Avoid showing a minus sign on display-rounded zero. Raw values retain it.
    precision = display_precision(unit, kind)
    if round(value, precision) == 0:
        value = 0.0
    number = format(value, ("+" if signed else "") + f",.{precision}f")
    return f"{number} {display_unit(unit, kind)}".strip()
