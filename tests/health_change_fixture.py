"""Independent, fixed-calendar acceptance records; all identities are synthetic."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import patch

from healthzip.db.repository import Repository
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService

CUTOFF = "2026-11-22T00:00:00+08:00"


def create_health_change_fixture(path):
    repo = Repository(path)
    cutoff = datetime.fromisoformat(CUTOFF)
    count = 0

    def add(kind, value, start, end, *, source="合成手表", metadata=None, category=None):
        nonlocal count
        count += 1
        unit = "ms" if kind == "hrv_sdnn_ms" else "bpm"
        row = {"id": count, "canonical_type": kind, "raw_type": kind,
               "normalized_value": value, "raw_value": str(value) if value is not None else None,
               "raw_unit": unit, "normalized_unit": unit,
               "source_name": source, "device": "synthetic-watch", "source_version": "synthetic-v1",
               "start_utc": start.isoformat(), "end_utc": end.isoformat(),
               "start_original": start.isoformat(), "end_original": end.isoformat(),
               "metadata_json": json.dumps(metadata or {}), "category_value": category,
               "record_status": "active"}
        repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) "
                          "VALUES('health_sample',?,?,?,'synthetic_acceptance')",
                          (count, end.isoformat(), json.dumps(row)))

    for day in range(1, 36):
        at = (cutoff - timedelta(days=day)).replace(hour=8)
        current = day <= 7
        add("resting_heart_rate_bpm", 64 if current else 59, at, at)
        # Two unequal-frequency days distinguish daily-equal from record-weighted aggregation.
        repetitions = 20 if day == 1 else 1
        for index in range(repetitions):
            observed = at + timedelta(minutes=index)
            add("hrv_sdnn_ms", 30 if current else 45, observed, observed,
                metadata={"sampling_mode": "background"})
        add("heart_rate_bpm", 78 + day % 5, at, at)
        hours = 6 if current else 8
        sleep_end = at.replace(hour=5)
        asleep_start = sleep_end - timedelta(hours=hours)
        # Parent asleep and overlapping child phases must not double count.
        add("sleep_stage", None, asleep_start, sleep_end,
            category="HKCategoryValueSleepAnalysisAsleepUnspecified")
        if day != 3:  # A duration-only night must survive without stage data.
            split = asleep_start + timedelta(hours=hours / 2)
            add("sleep_stage", None, asleep_start, split,
                category="HKCategoryValueSleepAnalysisAsleepCore")
            add("sleep_stage", None, split, sleep_end,
                category="HKCategoryValueSleepAnalysisAsleepREM")
    subjective = {"id": 1, "day": "2026-11-20", "fatigue": 7, "notes": "合成自报：近期训练后疲劳",
                  "record_status": "active", "observed_at": "2026-11-20T20:00:00+08:00"}
    repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) "
                      "VALUES('subjective_log',1,?,?,'synthetic_acceptance')",
                      (subjective["observed_at"], json.dumps(subjective)))
    repo.conn.commit()
    service = TrainingService(repo)
    sessions = []
    for day, sets in ((17, 2), (10, 2), (5, 4), (2, 4)):
        at = cutoff - timedelta(days=day) + timedelta(hours=17)
        recorded = (at + timedelta(hours=1)).isoformat()
        with patch("healthzip.training.service.timestamp", side_effect=lambda value=None: timestamp(value) if value else recorded):
            session = service.start_session("合成验收训练", started_at=at.isoformat())
            exercise = service.add_exercise(session["id"], "psa.ex.barbell_bench_press",
                {"load_basis": "external_total_kg", "load_basis_confirmed": True})
            for index in range(sets):
                service.add_set(exercise["id"], actual={"completion_state": "completed", "set_type": "work",
                    "load_value": 40, "load_unit": "kg", "reps": 8, "rir": 2,
                    "ended_at": (at + timedelta(minutes=5 + index * 3)).isoformat()})
            service.end_session(session["id"], ended_at=(at + timedelta(minutes=45)).isoformat())
            sessions.append(session["id"])
    repo.close()
    return {"data": "synthetic_only", "cutoff": CUTOFF, "health_records": count,
            "current": ["2026-11-15", "2026-11-21"], "reference": ["2026-10-18", "2026-11-14"],
            "expected_rhr": {"current": 64, "reference": 59, "difference": 5, "coverage": [7, 28]},
            "sessions": sessions, "sleep_duration_only_date": "2026-11-19"}
