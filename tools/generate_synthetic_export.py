#!/usr/bin/env python3
"""Generate a synthetic Apple Health export ZIP for parser tests. No real data."""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import random
import xml.etree.ElementTree as ET

TZ = timezone(timedelta(hours=8))

def fmt(dt: datetime) -> str:
    return dt.isoformat(sep=" ", timespec="seconds")

def add_record(root, typ, value, unit, start, end=None, source="Apple Watch", device="<Device: Apple Watch>0"):
    ET.SubElement(root, "Record", {
        "type": typ, "sourceName": source, "sourceVersion": "11.0",
        "device": device, "unit": unit, "creationDate": fmt(end or start),
        "startDate": fmt(start), "endDate": fmt(end or start), "value": str(value)
    })

def generate(output: Path, days: int = 45):
    random.seed(42)
    root = ET.Element("HealthData", {"locale": "zh_CN"})
    ET.SubElement(root, "ExportDate", {"value": fmt(datetime.now(TZ))})
    now = datetime.now(TZ).replace(hour=7, minute=0, second=0, microsecond=0)
    for d in range(days):
        day = now - timedelta(days=days-d)
        add_record(root, "HKQuantityTypeIdentifierRestingHeartRate", 56 + (d % 5) + random.random(), "count/min", day)
        for j in range(3):
            t = day.replace(hour=9 + j*4, minute=10)
            add_record(root, "HKQuantityTypeIdentifierHeartRate", 68 + j*22 + random.randint(-4,4), "count/min", t, t+timedelta(seconds=60))
        if d % 2 == 0:
            add_record(root, "HKQuantityTypeIdentifierHeartRateVariabilitySDNN", 42 + random.random()*10, "ms", day.replace(hour=6, minute=45))
        if d % 7 == 0:
            add_record(root, "HKQuantityTypeIdentifierVO2Max", 39 + d*0.025, "mL/min·kg", day.replace(hour=8))
        add_record(root, "HKQuantityTypeIdentifierBodyMass", 98.5 - d*0.025 + random.random()*0.12, "kg", day.replace(hour=7, minute=10), source="Smart Scale")
        add_record(root, "HKQuantityTypeIdentifierStepCount", 6500 + d*31, "count", day.replace(hour=0), day.replace(hour=23, minute=59), source="iPhone")
        add_record(root, "HKQuantityTypeIdentifierActiveEnergyBurned", 550 + (d%4)*45, "kcal", day.replace(hour=0), day.replace(hour=23, minute=59))
        add_record(root, "HKQuantityTypeIdentifierRespiratoryRate", 14.5 + (d%3)*0.3, "count/min", day.replace(hour=5, minute=30))
        add_record(root, "HKQuantityTypeIdentifierAppleSleepingWristTemperature", 34.2 + (d%4)*0.08, "degC", day.replace(hour=6, minute=20))
        add_record(root, "HKQuantityTypeIdentifierDietaryEnergyConsumed", 2200 + (d%4)*40, "kcal", day.replace(hour=20))
        add_record(root, "HKQuantityTypeIdentifierDietaryProtein", 145 + (d%5)*3, "g", day.replace(hour=20))
        add_record(root, "HKQuantityTypeIdentifierDietaryCarbohydrates", 240 + (d%4)*5, "g", day.replace(hour=20))
        add_record(root, "HKQuantityTypeIdentifierDietaryFatTotal", 65 + (d%3)*2, "g", day.replace(hour=20))
        # Sleep intervals cross midnight. Sleep stages are category Records.
        sleep_start = (day - timedelta(days=1)).replace(hour=23, minute=20)
        sleep_segments = [
            ("HKCategoryValueSleepAnalysisAsleepCore", sleep_start, sleep_start+timedelta(hours=2)),
            ("HKCategoryValueSleepAnalysisAsleepDeep", sleep_start+timedelta(hours=2), sleep_start+timedelta(hours=3)),
            ("HKCategoryValueSleepAnalysisAsleepREM", sleep_start+timedelta(hours=3), sleep_start+timedelta(hours=4, minutes=20)),
        ]
        for val, st, en in sleep_segments:
            el=ET.SubElement(root,"Record",{"type":"HKCategoryTypeIdentifierSleepAnalysis","sourceName":"Apple Watch","sourceVersion":"11.0","device":"<Device: Apple Watch>","value":val,"creationDate":fmt(en),"startDate":fmt(st),"endDate":fmt(en)})
        # Synthetic menstrual events for parser coverage only; synthetic profile does not imply user identity.
        if d in (3, 31):
            add_record(root, "HKCategoryTypeIdentifierMenstrualFlow", "HKCategoryValueMenstrualFlowMedium", "", day, day, source="Health")
            add_record(root, "HKCategoryTypeIdentifierMenstrualCramps", "HKCategoryValueSeverityMild", "", day, day, source="Health")
        # A few strength and running workouts.
        if d % 3 == 0:
            st = day.replace(hour=18, minute=0)
            en = st + timedelta(minutes=50)
            w = ET.SubElement(root, "Workout", {
                "workoutActivityType": "HKWorkoutActivityTypeTraditionalStrengthTraining",
                "duration": "50", "durationUnit": "min", "totalEnergyBurned": "280",
                "totalEnergyBurnedUnit": "kcal", "sourceName": "Apple Watch",
                "sourceVersion": "11.0", "device": "<Device: Apple Watch>",
                "creationDate": fmt(en), "startDate": fmt(st), "endDate": fmt(en)
            })
            ET.SubElement(w, "WorkoutStatistics", {"type":"HKQuantityTypeIdentifierHeartRate","startDate":fmt(st),"endDate":fmt(en),"average":"118","maximum":"156","minimum":"72","unit":"count/min"})
            ET.SubElement(w, "WorkoutEvent", {"type":"HKWorkoutEventTypePause","date":fmt(st+timedelta(minutes=20)),"duration":"60"})
        if d % 5 == 1:
            st = day.replace(hour=7, minute=30)
            en = st + timedelta(minutes=32)
            w = ET.SubElement(root, "Workout", {
                "workoutActivityType": "HKWorkoutActivityTypeRunning", "duration": "32",
                "durationUnit": "min", "totalDistance": "5.1", "totalDistanceUnit": "km",
                "totalEnergyBurned": "390", "totalEnergyBurnedUnit": "kcal",
                "sourceName": "Apple Watch", "sourceVersion": "11.0", "device": "<Device: Apple Watch>",
                "creationDate": fmt(en), "startDate": fmt(st), "endDate": fmt(en)
            })
            ET.SubElement(w, "WorkoutStatistics", {"type":"HKQuantityTypeIdentifierHeartRate","startDate":fmt(st),"endDate":fmt(en),"average":"148","maximum":"172","minimum":"105","unit":"count/min"})
    # Daily activity summary and unknown future type to verify forward compatibility.
    for d in range(min(days, 5)):
        day = now - timedelta(days=days-d)
        ET.SubElement(root, "ActivitySummary", {
            "dateComponents": day.strftime("%Y-%m-%d"),
            "activeEnergyBurned": "550", "activeEnergyBurnedGoal": "600",
            "appleExerciseTime": "35", "appleExerciseTimeGoal": "30",
            "appleStandHours": "10", "appleStandHoursGoal": "12"
        })
    add_record(root, "HKQuantityTypeIdentifierFutureUnknownMetric", 1.23, "units", now)
    # Intentional exact duplicate from the same source; importer must deduplicate.
    add_record(root, "HKQuantityTypeIdentifierRestingHeartRate", 56, "count/min", now - timedelta(days=days-1))
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("apple_health_export/export.xml", xml_bytes)
        zf.writestr("apple_health_export/README.txt", "Synthetic test fixture only. No personal data.\n")
    print(f"Created synthetic export: {output} ({output.stat().st_size:,} bytes, {days} days)")

if __name__ == "__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",default="fixtures/synthetic_apple_health_export.zip")
    ap.add_argument("--days",type=int,default=45)
    args=ap.parse_args()
    generate(Path(args.output), args.days)
