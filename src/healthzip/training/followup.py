"""User-declared observation windows, without a default physiological duration."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .semantics import TrainingError, timestamp


def freeze_window(value, *, declared_at):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TrainingError("后续观察窗口须明确填写起止时间和时区")
    try:
        start, end = timestamp(value.get("start") or ""), timestamp(value.get("end") or "")
        zone = value.get("timezone")
        ZoneInfo(zone)
        if not datetime.fromisoformat(declared_at) <= datetime.fromisoformat(start) < datetime.fromisoformat(end):
            raise ValueError("window_order")
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        raise TrainingError("后续观察窗口须使用有效时区，起点不早于现在，终点晚于起点") from exc
    return {"start": start, "end": end, "timezone": zone, "closure": "[start,end)",
            "origin": "user_declared", "declared_at": declared_at}


def validate_frozen_window(value, *, created_at):
    """Legacy prose remains readable but cannot establish an observation window."""
    if not isinstance(value, dict):
        return
    declared = timestamp(value.get("declared_at") or "")
    if value.get("origin") != "user_declared" or datetime.fromisoformat(declared) > datetime.fromisoformat(created_at):
        raise TrainingError("后续观察窗口必须在候选创建前由用户声明")
    freeze_window(value, declared_at=created_at)
