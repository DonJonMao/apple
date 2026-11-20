"""Reproducible synthetic product data; never opens an existing user workspace."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.training.service import TrainingService


def create_product_fixture(database: Path, *, mode="normal"):
    database.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    anchor = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if anchor >= now:
        anchor -= timedelta(days=1)
    xml = Element("HealthData")
    days = range(42) if mode == "normal" else ([90] if mode == "old" else ([1] if mode == "single" else []))
    for day in days:
        at = anchor - timedelta(days=day)
        # Deliberately leave gaps; the UI must not fill missing days with zero.
        if day in {3, 8, 15, 22}:
            continue
        values = [
            ("HKQuantityTypeIdentifierRestingHeartRate", 59 + day % 6, "count/min", 0),
            ("HKQuantityTypeIdentifierHeartRateVariabilitySDNN", 43 + day % 9, "ms", 0),
            ("HKCategoryTypeIdentifierSleepAnalysis", "HKCategoryValueSleepAnalysisAsleepCore", None, 6.5 + day % 4 / 3),
            ("HKQuantityTypeIdentifierBodyMass", 77.8 + day / 60, "kg", 0),
        ]
        if day % 6 == 0 or mode in {"old", "single"}:
            values.append(("HKQuantityTypeIdentifierVO2Max", 41.5 - day / 80, "mL/(kg·min)", 0))
        for kind, value, unit, duration in values:
            attrs = {"type": kind, "sourceName": "合成手表" if "Mass" not in kind else "合成体重秤",
                     "sourceVersion": "synthetic-1", "device": "synthetic-device", "value": str(value),
                     "startDate": (at - timedelta(hours=duration)).strftime("%Y-%m-%d %H:%M:%S %z"),
                     "endDate": at.strftime("%Y-%m-%d %H:%M:%S %z"),
                     "creationDate": at.strftime("%Y-%m-%d %H:%M:%S %z")}
            if unit:
                attrs["unit"] = unit
            SubElement(xml, "Record", attrs)
        if day % 4 == 0:
            SubElement(xml, "Workout", {"workoutActivityType": "HKWorkoutActivityTypeRunning",
                "duration": "30", "durationUnit": "min", "totalEnergyBurned": "220",
                "totalEnergyBurnedUnit": "kcal", "sourceName": "合成手表",
                "startDate": (at - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S %z"),
                "endDate": (at - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S %z")})
    archive = database.parent / "synthetic-product.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as stream:
        stream.writestr("export.xml", tostring(xml))
    sessions = []
    with closing(Repository(database)) as repo:
        imported = import_apple_zip(archive, repo)
        svc = TrainingService(repo)
        for day in ([1, 4, 7, 10, 15] if mode == "normal" else []):
            at = anchor - timedelta(days=day)
            session = svc.start_session("合成训练 · " + at.strftime("%m月%d日"), started_at=at.isoformat())
            for exercise, load in (("psa.ex.barbell_bench_press", 32.5), ("psa.ex.single_arm_dumbbell_row", 20)):
                item = svc.add_exercise(session["id"], exercise, {"load_basis": "external_total_kg" if "barbell" in exercise else "per_dumbbell_kg", "load_basis_confirmed": True})
                for order in range(3):
                    svc.add_set(item["id"], {"completion_state": "completed", "set_type": "work",
                        "load_value": load, "load_unit": "kg", "reps": 8 + order % 2, "rir": order,
                        "ended_at": (at + timedelta(minutes=5 + order * 3)).isoformat()})
            svc.end_session(session["id"], ended_at=(at + timedelta(minutes=35)).isoformat())
            sessions.append(session["id"])
        if mode == "normal":
            blank = svc.start_session("合成空会话", started_at=(anchor - timedelta(days=2)).isoformat())
            svc.end_session(blank["id"], ended_at=(anchor - timedelta(days=2) + timedelta(minutes=1)).isoformat())
    return {"data": "synthetic_only", "anchor": anchor.isoformat(), "mode": mode,
            "health_samples": imported.records_inserted, "completed_training_ids": sessions}
