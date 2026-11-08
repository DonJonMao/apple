"""Small compatibility wrapper for canonical-unit conversions."""

from __future__ import annotations

from typing import Optional

from . import TYPE_MAP, parse_number
from . import normalize_value as _normalize


def normalize_value(value: Optional[str], unit: Optional[str], canonical: Optional[str]):
    if canonical is None:
        return parse_number(value), unit, "unknown"
    raw_type = next((key for key, (name, _) in TYPE_MAP.items() if name == canonical), "")
    return _normalize(raw_type, value, unit)


__all__ = ["parse_number", "normalize_value"]
