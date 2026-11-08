"""Configuration and canonical Health export type definitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

QUALITY_STATES = ("usable", "provisional", "insufficient", "not_imported", "stale")


@dataclass(frozen=True)
class ImportLimits:
    max_members: int = 10000
    max_member_uncompressed_bytes: int = 2_000_000_000
    max_total_uncompressed_bytes: int = 4_000_000_000
    max_compression_ratio: float = 1000.0
    batch_size: int = 500


@dataclass(frozen=True)
class Thresholds:
    rhr_provisional_days: int = 7
    rhr_usable_days: int = 14
    hrv_provisional_days: int = 5
    hrv_usable_days: int = 10
    sleep_provisional_nights: int = 3
    sleep_usable_nights: int = 14
    vo2_usable_points: int = 2
    weight_provisional_points: int = 2
    weight_usable_points: int = 5
    weight_usable_span_days: int = 14
    strength_usable_exposures: int = 3
    nutrition_usable_complete_days: int = 7
    cycle_usable_cycles: int = 3


DEFAULT_DB_PATH = Path(".local/healthzip.sqlite3")
