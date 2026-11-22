"""Synthetic multi-month observations through the normal stream ZIP importer."""

from datetime import datetime, timedelta
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZIP_DEFLATED, ZipFile

from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.normalize import TYPE_MAP

CUTOFF = "2026-11-22T00:00:00+08:00"
RANGE_START = "2026-07-20T00:00:00+08:00"


def create_master_science_fixture(path, *, include_training=True):
    path = Path(path)
    if path.exists():
        raise ValueError("Synthetic fixture requires an unused database path.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if include_training:
        from tests.health_change_fixture import create_health_change_fixture

        create_health_change_fixture(path)
    repo = Repository(path)
    root = Element("HealthData", locale="en_US")
    kinds = {v[0]: (k, v[1]) for k, v in TYPE_MAP.items()}
    rng = Random(629)
    first = datetime.fromisoformat(RANGE_START)
    end = datetime.fromisoformat(CUTOFF)

    def add(k, value, at, stop=None, *, source="合成长时段手表", meta=None, unit=None):
        raw, nominal = kinds[k]
        fields = {
            "type": raw,
            "sourceName": source,
            "sourceVersion": "fixture-2",
            "device": "合成设备 S",
            "value": str(value),
            "startDate": at.isoformat(),
            "endDate": (stop or at).isoformat(),
        }
        if nominal != "category":
            fields["unit"] = unit or nominal
        e = SubElement(root, "Record", fields)
        for name, data in (meta or {"protocol_id": "固定晨间"}).items():
            SubElement(e, "MetadataEntry", key=name, value=str(data))

    ar = er = 0.0
    for i in range((end - first).days):
        date = first + timedelta(days=i)
        sleep_hours = round((7 + 0.55 * rng.uniform(-1, 1)) * 60) / 60
        ar = 0.48 * ar + rng.gauss(0, 0.52)
        er = 0.48 * er + rng.gauss(0, 0.40)
        if i % 19 == 4:
            continue
        wake = date + timedelta(hours=6)
        add(
            "sleep_stage",
            "HKCategoryValueSleepAnalysisAsleepUnspecified",
            wake - timedelta(hours=sleep_hours),
            wake,
        )
        add("resting_heart_rate_bpm", round(65 - 0.023 * i + ar, 3), wake + timedelta(hours=1))
        add(
            "hrv_sdnn_ms",
            round(40 + 3.1 * (sleep_hours - 7) + 0.016 * i + er, 3),
            wake + timedelta(hours=1),
        )
        add(
            "steps",
            3000 if i < len(range((end - first).days)) // 2 else 2000,
            date + timedelta(hours=10),
            date + timedelta(hours=11),
        )
        add(
            "walking_speed_m_s",
            1.2,
            date + timedelta(hours=10),
            source="合成 iPhone",
            meta={"carrying_position": "front_pocket", "route": "route A"},
        )
        add(
            "body_mass_kg",
            round(70 - 0.01 * i + rng.gauss(0, 0.12), 3),
            wake + timedelta(minutes=5),
            source="合成体重秤",
        )
    example = {
        "heart_rate_bpm": 83,
        "walking_heart_rate_bpm": 89,
        "heart_rate_recovery_1m": 18,
        "vo2_max_ml_kg_min": 42,
        "respiratory_rate_bpm": 15,
        "oxygen_saturation_fraction": 0.97,
        "sleeping_wrist_temperature_c": 35.6,
        "sleep_breathing_disturbances": 3,
        "distance_walking_running_m": 1200,
        "distance_cycling_m": 2500,
        "exercise_minutes": 24,
        "stand_minutes": 7,
        "flights_climbed": 3,
        "number_of_times_fallen": 1,
        "physical_effort_met": 3.2,
        "six_minute_walk_m": 500,
        "stair_ascent_m_s": 0.4,
        "stair_descent_m_s": 0.5,
        "walking_step_length_m": 0.64,
        "walking_double_support_fraction": 0.26,
        "walking_asymmetry_fraction": 0.03,
        "walking_steadiness_fraction": 0.8,
        "height_cm": 172,
        "body_fat_fraction": 0.2,
        "lean_body_mass_kg": 55,
        "active_energy_kcal": 230,
        "basal_energy_kcal": 600,
        "dietary_energy_kcal": 350,
        "dietary_protein_g": 22,
        "dietary_carbohydrates_g": 36,
        "dietary_fat_g": 12,
        "dietary_water_ml": 260,
        "dietary_caffeine_mg": 80,
        "daylight_minutes": 18,
        "environmental_audio_dba": 70,
        "headphone_audio_dba": 73,
    }
    when = end - timedelta(days=2) + timedelta(hours=2)
    for k, v in example.items():
        meta = {"protocol_id": "fixed synthetic protocol"}
        if k == "six_minute_walk_m":
            meta.update(
                method="passive_estimate",
                support_start=(when - timedelta(days=28)).isoformat(),
                support_end=when.isoformat(),
                algorithm_version="Apple-6MWD-2021",
            )
            add(
                k,
                v,
                when - timedelta(days=7),
                meta={
                    **meta,
                    "support_start": (when - timedelta(days=35)).isoformat(),
                    "support_end": (when - timedelta(days=7)).isoformat(),
                },
            )
        add(k, v, when, when + timedelta(minutes=10), meta=meta)
    add(
        "environmental_audio_dba",
        80,
        when + timedelta(minutes=10),
        when + timedelta(minutes=20),
        meta={"protocol_id": "fixed synthetic protocol"},
    )
    add("stand_hour", "HKCategoryValueAppleStandHourStood", when, when + timedelta(hours=1))
    for k in kinds:
        if kinds[k][1] == "category" and k not in {"sleep_stage", "stand_hour"}:
            add(k, "HKCategoryValueNotApplicable" if k.endswith("event") else "1", when)
    SubElement(
        root,
        "Workout",
        workoutActivityType="HKWorkoutActivityTypeWalking",
        sourceName="合成长时段手表",
        startDate=when.isoformat(),
        endDate=(when + timedelta(minutes=20)).isoformat(),
        duration="20",
        durationUnit="min",
    )
    with TemporaryDirectory() as folder:
        archive = Path(folder) / "synthetic.zip"
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as z:
            z.writestr(
                "apple_health_export/export.xml",
                tostring(root, encoding="utf-8", xml_declaration=True),
            )
        # The preexisting synthetic fixture uses ledger-only IDs; shift its IDs
        # out of the range of this independent import BEFORE appending rows.
        if include_training:
            repo.conn.execute(
                "UPDATE source_revision SET record_id=record_id+1000000, payload_json=json_set(payload_json,'$.id',record_id+1000000) WHERE table_name='health_sample'"
            )
            repo.conn.commit()
        receipt = import_apple_zip(archive, repo, include_cycle=True)
    # Give this synthetic-only fixture reproducible original availability times.
    # Real importer rows are intentionally never backdated.
    repo.conn.execute(
        "UPDATE source_revision SET available_at=json_extract(payload_json,'$.end_utc') WHERE temporal_provenance='locally_observed' AND table_name IN ('health_sample','workout')"
    )
    repo.conn.commit()
    repo.close()
    return {
        "data": "synthetic_only",
        "records_inserted": receipt.records_inserted,
        "records_seen": receipt.records_seen,
        "import_errors": receipt.errors_count,
        "range_start": RANGE_START,
        "cutoff": CUTOFF,
        "rng_seed": 629,
        "rhr_slope_per_day": -0.023,
        "conditional_sdnn_per_sleep_hour": 3.1,
    }
