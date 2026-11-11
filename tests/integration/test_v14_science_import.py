"""F01/F09 through the real ZIP importer and Repository analysis adapter."""
from datetime import datetime, timedelta, timezone
from zipfile import ZipFile

import pytest

from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip


@pytest.mark.parametrize("unit,basal,active,sdnn_unit,sdnn", [("kJ", 6694.4, 2510.4, "s", .05),
    ("kcal", 1600, 600, "ms", 50), ("unknown", 6694.4, 2510.4, "unknown", .05)])
def test_f01_real_import_checks_units_before_energy_and_physiology(tmp_path, unit, basal, active, sdnn_unit, sdnn):
    path = tmp_path / "synthetic-v14.zip"
    records = [f'<Record type="HKQuantityTypeIdentifier{kind}EnergyBurned" unit="{unit}" value="{amount}" '
        'sourceName="synthetic_watch" startDate="2026-11-01 00:00:00 +0000" endDate="2026-11-02 00:00:00 +0000"/>'
        for kind, amount in (("Basal", basal), ("Active", active))]
    records.append(f'<Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" unit="{sdnn_unit}" value="{sdnn}" '
        'sourceName="synthetic_watch" startDate="2026-11-01 08:00:00 +0000" endDate="2026-11-01 08:01:00 +0000"/>')
    with ZipFile(path, "w") as archive:
        archive.writestr("export.xml", "<HealthData>" + "".join(records) + "</HealthData>")
    repo = Repository(tmp_path / "v14.sqlite3")
    try:
        assert import_apple_zip(path, repo).status == "completed"
        saved = [dict(r) for r in repo.rows("SELECT * FROM health_sample")]
        assert len(saved) == 3
        assert {r["raw_unit"] for r in saved} == {unit, sdnn_unit}
        if unit == "unknown":
            assert all(r["normalized_value"] is None and r["normalized_unit"] is None for r in saved)
        output = analyze(repo, window_days=365, timezone_name="UTC",
                         cutoff_time=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat())
        if unit == "unknown":
            assert output["metrics"]["ENERGY-DEVICE-TOTAL"]["value"] is None
            assert output["metrics"]["STATE-SDNN"]["value"] is None
        else:
            assert output["metrics"]["ENERGY-DEVICE-TOTAL"]["value"][0]["device_total_kcal"] == pytest.approx(2200)
            streams = output["metrics"]["STATE-SDNN"]["value"]
            assert next(iter(streams.values()))[0]["value"] == pytest.approx(50)
    finally:
        repo.close()


def test_f09_actual_zip_with_inbed_phone_and_asleep_watch(tmp_path):
    path = tmp_path / "synthetic-sleep-v14.zip"
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=1)
    end = cutoff - timedelta(hours=5)
    records = [f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysis{stage}" '
               f'sourceName="{source}" startDate="{(end-timedelta(hours=hours)).isoformat()}" endDate="{end.isoformat()}"/>'
               for stage, source, hours in (("InBed", "synthetic_phone", 8), ("Asleep", "synthetic_watch", 7))]
    with ZipFile(path, "w") as archive:
        archive.writestr("export.xml", "<HealthData>" + "".join(records) + "</HealthData>")
    repo = Repository(tmp_path / "sleep.sqlite3")
    try:
        assert import_apple_zip(path, repo).status == "completed"
        output = analyze(repo, timezone_name="UTC", cutoff_time=cutoff.isoformat())
        assert output["metrics"]["STATE-SLEEP-24H"]["value"]["observed_minutes"] == 420
        assert output["metrics"]["STATE-SLEEP-MAIN"]["value"] is None
        facts = output["metrics"]["REPORT-STATE-SUMMARY"]["daily_facts"]
        assert sum(f["value"] for f in facts if f.get("series_id") == "observed_sleep_by_wake_date") == 420
    finally:
        repo.close()


def test_f07_real_training_service_preserves_load_layers_in_analysis(tmp_path):
    from healthzip.training.service import TrainingService
    repo = Repository(tmp_path / "series.sqlite3")
    try:
        svc = TrainingService(repo)
        equipment = svc.create_equipment("synthetic_v14_bar", "barbell")
        exercise = svc.search_exercises("杠铃卧推")[0]
        condition = {"equipment_instance_id": equipment["id"], "load_basis": "external_total_kg", "load_basis_confirmed": True,
                     "side": "both", "repetition_semantics": "simultaneous", "rom_protocol": "declared_full",
                     "settings": {"grip": "declared"}, "settings_confirmed": True,
                     "reference_protocol": {"protocol_id": "v14_reference", "version": "1", "reference_policy_id": "first_work_set",
                        "effort_protocol": "target_rir_2", "tempo": "2-0-1", "rest_protocol": "120_seconds_before_reference"}}
        start = datetime.now(timezone.utc) + timedelta(minutes=1)
        for index, (load, reps) in enumerate([(30, 10), (30, 12), (30, 11), (32.5, 8), (32.5, 10), (32.5, 9)]):
            time = start + timedelta(days=index)
            session = svc.start_session("synthetic-v14", started_at=time.isoformat())
            instance = svc.add_exercise(session["id"], exercise["exercise_id"], condition)
            draft = svc.add_set(instance["id"], {"reference_set": True, "set_number": 1})
            svc.edit_set(draft["set_uuid"], {"completion_state": "completed", "reps": reps,
                "load_value": str(load), "load_unit": "kg", "rir": 2, "quality_status": "acceptable", "pain_flag": False,
                "stop_reason": "target_rir", "started_at": (time+timedelta(minutes=1)).isoformat(),
                "ended_at": (time+timedelta(minutes=2)).isoformat()}, base_revision=draft["revision"])
            svc.end_session(session["id"], ended_at=(time+timedelta(hours=1)).isoformat())
        output = analyze(repo, cutoff_time=(start+timedelta(days=7)).isoformat())
        assert len(output["strength_tasks"]) == 1
        series = output["strength_tasks"][0]["metrics"]["STR-19"]["series_results"]
        assert {s["normalized_load"] for s in series} == {30, 32.5}
        assert all(s["metric"]["value"]["n"] == 3 for s in series)
    finally:
        repo.close()
