"""Validation and persistence helpers for manually logged strength sessions."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Optional

from healthzip.db.repository import Repository
from healthzip.normalize import parse_number


class StrengthLogError(ValueError):
    """Raised when a strength session cannot be safely written."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_number(value: Any, field: str) -> Optional[float]:
    if value is None or _text(value) == "":
        return None
    parsed = parse_number(value)
    if parsed is None:
        raise StrengthLogError(f"{field} 必须是数字")
    return parsed


def validate_strength_session(
    *,
    session_date: str,
    started_at: str,
    name: str,
    notes: str,
    sets: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Normalize a form payload and reject incomplete or impossible rows."""
    day = _text(session_date)
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise StrengthLogError("训练日期必须是 YYYY-MM-DD") from exc

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(sets, 1):
        exercise = _text(raw.get("exercise_name"))
        if not exercise:
            raise StrengthLogError(f"第 {index} 组缺少动作名称")
        weight = _optional_number(raw.get("weight_kg"), "重量")
        reps_number = _optional_number(raw.get("reps"), "次数")
        if weight is None or weight < 0:
            raise StrengthLogError(f"第 {index} 组重量必须是非负数字")
        if reps_number is None or reps_number < 1 or reps_number != int(reps_number):
            raise StrengthLogError(f"第 {index} 组次数必须是正整数")
        rir = _optional_number(raw.get("rir"), "RIR")
        rpe = _optional_number(raw.get("rpe"), "RPE")
        if rir is not None and not 0 <= rir <= 10:
            raise StrengthLogError(f"第 {index} 组 RIR 应在 0 到 10 之间")
        if rpe is not None and not 0 <= rpe <= 10:
            raise StrengthLogError(f"第 {index} 组 RPE 应在 0 到 10 之间")
        normalized.append(
            {
                "set_date": day,
                "started_at": _text(raw.get("started_at")) or _text(started_at) or day,
                "exercise_id": _text(raw.get("exercise_id")) or exercise,
                "exercise_name": exercise,
                "equipment": _text(raw.get("equipment")),
                "variation": _text(raw.get("variation")),
                "side": _text(raw.get("side")),
                "set_number": int(raw.get("set_number") or index),
                "weight_kg": weight,
                "reps": int(reps_number),
                "rir": rir,
                "rpe": rpe,
                "warmup": int(bool(raw.get("warmup"))),
                "range_of_motion": _text(raw.get("range_of_motion")),
                "notes": _text(raw.get("notes")),
            }
        )
    if not normalized:
        raise StrengthLogError("至少填写一组训练记录")
    return (
        {
            "session_date": day,
            "started_at": _text(started_at) or day,
            "name": _text(name),
            "source": "manual",
            "notes": _text(notes),
        },
        normalized,
    )


def save_strength_log(
    repo: Repository,
    *,
    session_date: str,
    started_at: str,
    name: str,
    notes: str,
    sets: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    session, normalized_sets = validate_strength_session(
        session_date=session_date,
        started_at=started_at,
        name=name,
        notes=notes,
        sets=sets,
    )
    return repo.save_strength_session(session, normalized_sets)


def append_quick_strength_set(
    repo: Repository,
    *,
    session_key: str,
    session_date: str,
    started_at: str,
    exercise_name: str,
    equipment: str = "",
    variation: str = "",
    weight_kg: Any = None,
    reps: Any = None,
    rir: Any = None,
    rpe: Any = None,
    warmup: bool = False,
) -> dict[str, Any]:
    """Validate and append one mobile set to a stable quick-log session."""
    _, normalized = validate_strength_session(
        session_date=session_date,
        started_at=started_at,
        name="手机快速记录",
        notes="",
        sets=[
            {
                "exercise_name": exercise_name,
                "equipment": equipment,
                "variation": variation,
                "weight_kg": weight_kg,
                "reps": reps,
                "rir": rir,
                "rpe": rpe,
                "warmup": warmup,
                "set_number": 0,
            }
        ],
    )
    return repo.append_strength_set(
        session_key=session_key,
        session_date=session_date,
        started_at=started_at,
        data=normalized[0],
    )


__all__ = [
    "StrengthLogError",
    "append_quick_strength_set",
    "save_strength_log",
    "validate_strength_session",
]
