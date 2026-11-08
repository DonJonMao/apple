"""Timestamp helper returning a structured mapping for callers that need it."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from . import parse_apple_datetime as _parse


class TimestampError(ValueError):
    pass


def parse_apple_datetime(value: Optional[str]) -> Optional[dict[str, Any]]:
    if not value:
        return None
    utc, local, offset, local_date = _parse(value)
    if utc is None:
        raise TimestampError(f"unsupported Apple timestamp: {value!r}")
    return {
        "raw": value,
        "utc": utc,
        "local_datetime": local,
        "local_date": local_date,
        "utc_offset_minutes": offset,
        "dt": datetime.fromisoformat(local) if local else None,
    }


__all__ = ["TimestampError", "parse_apple_datetime"]
