"""Shared event-time/knowledge-time and sleep interval rules.

Retrospective exports remain useful for descriptions. They cannot establish what
was known before import; decision queries must check both clocks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def instant(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return result if result.tzinfo else None


def visible(row: dict, cutoff: Any, *, event_key: str = "end_utc") -> bool:
    end = instant(row.get(event_key) or row.get("event_end"))
    available = instant(row.get("available_at"))
    bound = instant(cutoff)
    invalidated = instant(row.get("invalidated_at"))
    return bool(
        bound and end and available and end <= bound and available <= bound
        and (invalidated is None or bound < invalidated)
        and not (row.get("record_status") in {"deleted", "superseded"} and invalidated is None)
    )


ASLEEP = {"asleep", "asleepunspecified", "asleepcore", "asleepdeep", "asleeprem",
          "core", "deep", "rem", "1", "3", "4", "5"}


def sleep_nights(rows: list[dict], start: Optional[str] = None,
                 end: Optional[str] = None, cutoff: Optional[str] = None) -> list[dict]:
    """Union observed asleep intervals, assign the local wake date, never fill gaps."""
    nights: dict[str, list] = {}
    for row in rows:
        if cutoff and not visible(row, cutoff):
            continue
        if not cutoff and row.get("record_status", "active") != "active":
            continue
        stage = str(row.get("category_value") or "").replace(
            "HKCategoryValueSleepAnalysis", "").lower()
        if stage not in ASLEEP:
            continue
        a, b = instant(row.get("start_utc")), instant(row.get("end_utc"))
        if not a or not b or b <= a:
            continue
        offset = row.get("utc_offset_minutes")
        # Unknown timezone cannot establish a local wake-date.
        if offset is None:
            continue
        day = b.astimezone(timezone(timedelta(minutes=int(offset)))).date().isoformat()
        if (start and day < start) or (end and day > end):
            continue
        nights.setdefault(day, []).append((a, b, row.get("id")))
    result = []
    for day, segments in sorted(nights.items()):
        merged: list[tuple[datetime, datetime]] = []
        for a, b, _ in sorted(segments, key=lambda x: x[0]):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        result.append({"date": day,
                       "sleep_hours": sum((b-a).total_seconds() for a, b in merged) / 3600,
                       "segments": len(segments),
                       "source_ids": [f"health_sample:{x[2]}" for x in segments],
                       "coverage_kind": "observed_asleep_lower_bound"})
    return result
