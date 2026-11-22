"""Cross-representation and temporal contracts through real import/query APIs."""

import json
from datetime import timedelta
from unittest.mock import patch
from zipfile import ZipFile

from healthzip.analytics.body_metrics import analyze_body_metric, analyze_questions
from healthzip.db.repository import Repository
from healthzip.db.temporal_schema import samples_as_of
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.science.contracts import instant
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService

KW = {
    "window_start": "2026-11-01T00:00:00+08:00",
    "window_end": "2026-11-04T00:00:00+08:00",
    "cutoff_time": "2026-11-04T00:00:00+08:00",
}


def imported(tmp_path, body):
    archive = tmp_path / "alternate.zip"
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr("apple_health_export/export.xml", "<HealthData>" + body + "</HealthData>")
    repo = Repository(tmp_path / "db")
    outcome = import_apple_zip(archive, repo, include_cycle=True)
    assert outcome.errors_count == 0
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-03T00:00:00+08:00'")
    repo.conn.execute("UPDATE import_batch SET imported_at='2026-11-03T00:00:00+08:00'")
    repo.conn.commit()
    return repo


def test_alternate_workout_and_ring_totals_are_used_without_cross_representation_addition(tmp_path):
    repo = imported(
        tmp_path,
        """
      <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" value="50" unit="kcal" sourceName="Watch" startDate="2026-11-01T10:00:00+08:00" endDate="2026-11-01T11:00:00+08:00"/>
      <Workout workoutActivityType="HKWorkoutActivityTypeWalking" sourceName="Watch" startDate="2026-11-01T10:00:00+08:00" endDate="2026-11-01T11:00:00+08:00" duration="60" durationUnit="min" totalEnergyBurned="50" totalEnergyBurnedUnit="kcal" totalDistance="1" totalDistanceUnit="km">
        <WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" sum="50" unit="kcal" startDate="2026-11-01T10:00:00+08:00" endDate="2026-11-01T11:00:00+08:00"/>
        <WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" sum="50" unit="kcal" startDate="2026-11-01T10:00:00+08:00" endDate="2026-11-01T11:00:00+08:00"/>
        <WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" sum="25" unit="kcal" startDate="2026-11-01T10:00:00+08:00" endDate="2026-11-01T10:30:00+08:00"/>
      </Workout>
      <ActivitySummary dateComponents="2026-11-01" activeEnergyBurned="500" activeEnergyBurnedUnit="kcal" appleExerciseTime="60" appleStandHours="10"/>
    """,
    )
    m = analyze_body_metric(repo, "active_energy_kcal", **KW)
    assert sorted(s["current"]["recorded_total"] for s in m["value"]["streams"]) == [50, 50, 500]
    assert {
        p["observations"][0]["representation"] for s in m["value"]["streams"] for p in s["points"]
    } == {"health_sample", "workout_statistic", "activity_summary"}
    distance = analyze_body_metric(repo, "distance_walking_running_m", **KW)
    assert distance["value"]["streams"][0]["current"]["recorded_total"] == 1000
    stand = analyze_body_metric(repo, "stand_hour", **KW)
    assert stand["value"]["streams"][0]["current"]["recorded_total"] == 10
    assert (
        stand["value"]["streams"][0]["points"][0]["observations"][0]["event_time_precision"]
        == "calendar_day"
    )
    repo.conn.execute("UPDATE workout SET record_status='deleted'")
    repo.conn.execute(
        "UPDATE source_revision SET available_at='2026-11-04T00:00:00+08:00' WHERE table_name='workout' AND json_extract(payload_json,'$.record_status')='deleted'"
    )
    repo.conn.commit()
    assert analyze_body_metric(repo, "distance_walking_running_m", **KW)["valid_n"] == 0
    old = {**KW, "cutoff_time": "2026-11-03T12:00:00+08:00"}
    assert analyze_body_metric(repo, "distance_walking_running_m", **old)["valid_n"] == 1
    repo.close()


def test_daily_snapshots_and_delete_are_asof_not_additive_or_resurrected(tmp_path):
    repo = imported(
        tmp_path,
        '<ActivitySummary dateComponents="2026-11-01" activeEnergyBurned="500" activeEnergyBurnedUnit="kcal"/>',
    )
    repo.conn.execute("UPDATE activity_summary SET active_energy=600")
    repo.conn.execute(
        "UPDATE source_revision SET available_at='2026-11-03T10:00:00+08:00' WHERE table_name='activity_summary' AND json_extract(payload_json,'$.active_energy')=600"
    )
    repo.conn.commit()

    def energy(cutoff):
        return analyze_body_metric(repo, "active_energy_kcal", **{**KW, "cutoff_time": cutoff})

    assert (
        energy("2026-11-03T05:00:00+08:00")["value"]["streams"][0]["current"]["recorded_total"]
        == 500
    )
    assert (
        energy("2026-11-03T15:00:00+08:00")["value"]["streams"][0]["current"]["recorded_total"]
        == 600
    )
    repo.conn.execute("DELETE FROM activity_summary")
    repo.conn.execute(
        "UPDATE source_revision SET available_at='2026-11-03T20:00:00+08:00' WHERE table_name='activity_summary' AND json_extract(payload_json,'$.record_status')='deleted'"
    )
    repo.conn.commit()
    assert energy(KW["cutoff_time"])["valid_n"] == 0
    assert energy("2026-11-03T15:00:00+08:00")["valid_n"] == 1
    repo.close()


def test_legacy_nutrition_and_cycle_use_real_logs_and_date_precision(tmp_path):
    repo = imported(tmp_path, "")
    repo.conn.execute(
        "INSERT INTO nutrition_day(day,energy_kcal,protein_g,log_status,source) VALUES('2026-11-01',350,20,'partial','CSV')"
    )
    repo.conn.execute(
        "INSERT INTO cycle_event(event_date,canonical_type,category_value,source) VALUES('2026-11-01','menstrual_flow','1','manual')"
    )
    repo.conn.execute(
        "UPDATE source_revision SET available_at='2026-11-03T00:00:00+08:00' WHERE table_name IN ('nutrition_day','cycle_event')"
    )
    repo.conn.commit()
    food = analyze_body_metric(repo, "dietary_energy_kcal", **KW)
    assert food["value"]["streams"][0]["current"]["recorded_total"] == 350
    assert food["value"]["streams"][0]["points"][0]["observations"][0]["log_status"] == "partial"
    question = analyze_questions(repo, question_ids=["W8"], **KW)[0]
    assert len([r for r in question["rows"] if r["type"] == "event"]) == 1
    repo.close()


def test_interval_ending_at_window_midnight_belongs_to_completed_day(tmp_path):
    repo = imported(
        tmp_path,
        '<Record type="HKQuantityTypeIdentifierStepCount" value="50" unit="count" sourceName="S" startDate="2026-11-03T23:00:00+08:00" endDate="2026-11-04T00:00:00+08:00"/>',
    )
    result = analyze_body_metric(repo, "steps", **KW)
    point = result["value"]["streams"][0]["points"][0]
    assert point["date"] == "2026-11-03" and point["value"] == 50
    assert result["valid_n"] == 1
    assert result["value"]["streams"][0]["current"]["recorded_total"] == 50
    repo.close()


def test_change_evidence_runs_through_normal_metric_identity_and_cache(tmp_path):
    records = []
    for day, value in [(1, 60), (2, 64)]:
        records.append(
            f'<Record type="HKQuantityTypeIdentifierRestingHeartRate" value="{value}" unit="count/min" sourceName="S" startDate="2026-11-0{day}T08:00:00+08:00" endDate="2026-11-0{day}T08:00:00+08:00"/>'
        )
    repo = imported(tmp_path, "".join(records))
    scope = {
        "window_start": "2026-11-02T00:00:00+08:00",
        "window_end": "2026-11-03T00:00:00+08:00",
        "cutoff_time": KW["cutoff_time"],
    }
    base = analyze_body_metric(repo, "resting_heart_rate_bpm", **scope)
    stream = base["value"]["streams"][0]
    assert stream["absolute_change"] == 4
    assert stream["change_layers"]["exceeds_repeatability_limit"] is None
    evidence = [
        {
            "identity": stream["comparison_identity"],
            "unit": "count/min",
            "source": "synthetic repeat measurements",
            "threshold": 3,
            "basis": "matched_repeat_measurements",
        },
        {
            "identity": stream["comparison_identity"],
            "unit": "count/min",
            "source": "independent synthetic goal",
            "threshold": 5,
            "basis": "prespecified_goal_scale",
        },
    ]
    tested = analyze_body_metric(repo, "resting_heart_rate_bpm", change_evidence=evidence, **scope)[
        "value"
    ]["streams"][0]
    assert tested["change_layers"]["exceeds_repeatability_limit"] is True
    assert tested["change_layers"]["meets_independent_goal_magnitude"] is False
    assert tested["fact_id"] != stream["fact_id"]
    repo.close()


def test_old_auxiliary_rows_migrate_at_observation_time_without_backdating(tmp_path):
    repo = Repository(tmp_path / "db")
    repo.conn.execute("DROP TRIGGER ledger_nutrition_day_insert")
    repo.conn.execute(
        "INSERT INTO nutrition_day(day,energy_kcal,log_status) VALUES('2020-01-01',350,'partial')"
    )
    repo.conn.execute("DELETE FROM schema_meta WHERE key='alternate_observation_ledger'")
    for table in (
        "nutrition_day",
        "cycle_event",
        "workout_statistic",
        "workout_event",
        "activity_summary",
    ):
        for operation in ("insert", "update", "delete"):
            repo.conn.execute(f"DROP TRIGGER IF EXISTS ledger_{table}_{operation}")
    repo.conn.execute("UPDATE schema_meta SET value='4' WHERE key='repository_migration_revision'")
    repo.conn.commit()
    repo.close()
    repo = Repository(tmp_path / "db")
    assert samples_as_of(repo, "2020-02-01T00:00Z", "nutrition_day") == []
    stored = dict(repo.one("SELECT * FROM source_revision WHERE table_name='nutrition_day'"))
    assert stored["temporal_provenance"] == "observed_at_migration_historical_visibility_unknown"
    assert json.loads(stored["payload_json"])["day"] == "2020-01-01"
    assert (
        len(
            samples_as_of(
                repo,
                (instant(stored["available_at"]) + timedelta(seconds=1)).isoformat(),
                "nutrition_day",
            )
        )
        == 1
    )
    repo.close()


def test_w3_uses_actual_equal_distance_workouts_and_their_hr_samples(tmp_path):
    parts = []
    for day, duration, hr in [(1, 30, 100), (2, 25, 95)]:
        parts.append(f'''<Workout workoutActivityType="HKWorkoutActivityTypeWalking" sourceName="Watch" device="W" startDate="2026-11-0{day}T00:00:00+08:00" endDate="2026-11-0{day}T00:{duration}:00+08:00" duration="{duration}" durationUnit="min" totalDistance="2" totalDistanceUnit="km"><MetadataEntry key="route" value="recorded route A"/></Workout>
        <Record type="HKQuantityTypeIdentifierHeartRate" value="{hr}" unit="count/min" sourceName="Watch" device="W" startDate="2026-11-0{day}T00:05:00+08:00" endDate="2026-11-0{day}T00:05:00+08:00"/>''')
    repo = imported(tmp_path, "".join(parts))
    question = analyze_questions(repo, question_ids=["W3"], **KW)[0]
    comparison = next(row for row in question["rows"] if row["type"] == "workout_comparison")
    assert comparison["distance_m"] == 2000 and comparison["difference"] == -5
    assert comparison["known_route"] == "recorded route A"
    assert comparison["heart_rate_comparisons"][0]["value"] == 95
    assert question["support_count"] == 1 and "2000" in question["observation"]
    assert "2026-11-01 到 2026-11-02" in question["observation"]
    assert comparison["first_date"].startswith("2026-10-31")  # Original UTC fact stays unchanged.
    repo.close()


def test_supplied_original_zip_backfills_alternate_metadata_once(tmp_path):
    repo = imported(
        tmp_path,
        """
      <Record type="HKQuantityTypeIdentifierStepCount" value="20" unit="count" sourceName="S" startDate="2026-11-01T08:00:00+08:00" endDate="2026-11-01T08:05:00+08:00"/>
      <Workout workoutActivityType="HKWorkoutActivityTypeWalking" sourceName="S" startDate="2026-11-01T10:00:00+08:00" endDate="2026-11-01T11:00:00+08:00" duration="60" durationUnit="min"><MetadataEntry key="route" value="source route"/></Workout>
      <ActivitySummary dateComponents="2026-11-01" activeEnergyBurned="500" activeEnergyBurnedUnit="kcal"/>
    """,
    )
    repo.conn.execute("UPDATE activity_summary SET metadata_json='{}'")
    repo.conn.execute("UPDATE workout SET metadata_json='{}'")
    repo.conn.commit()
    receipt = import_apple_zip(tmp_path / "alternate.zip", repo)
    assert receipt.records_seen == 2 and receipt.errors_count == 0
    assert repo.count("health_sample") == 1 and repo.count("workout") == 1
    metadata = json.loads(repo.one("SELECT metadata_json FROM workout")[0])
    assert metadata["original_timestamps"]["start"] == "2026-11-01T10:00:00+08:00"
    assert metadata["MetadataEntry"][0]["value"] == "source route"
    assert import_apple_zip(tmp_path / "alternate.zip", repo).status == "already_imported"
    repo.close()


def test_directional_sleep_pairs_query_support_outside_training_window(tmp_path):
    repo = imported(
        tmp_path,
        """
      <Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysisAsleepUnspecified" sourceName="S" startDate="2026-11-01T00:00:00+08:00" endDate="2026-11-01T07:00:00+08:00"/>
      <Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysisAsleepUnspecified" sourceName="S" startDate="2026-11-02T00:00:00+08:00" endDate="2026-11-02T08:00:00+08:00"/>
    """,
    )
    service = TrainingService(repo)
    with patch(
        "healthzip.training.service.timestamp",
        side_effect=lambda value=None: timestamp(value) if value else "2026-11-02T12:00:00+08:00",
    ):
        session = service.start_session(
            "synthetic boundary", started_at="2026-11-01T20:00:00+08:00"
        )
        service.end_session(session["id"], ended_at="2026-11-01T21:00:00+08:00")
    view = analyze_questions(
        repo,
        question_ids=["W2"],
        **{
            **KW,
            "window_start": "2026-11-01T18:00:00+08:00",
            "window_end": "2026-11-02T00:00:00+08:00",
        },
    )[0]
    assert view["training_pairs"]["before_training"][0]["matches"][0]["value"] == 420
    assert view["training_pairs"]["after_training"][0]["matches"][0]["value"] == 480
    repo.close()


def test_event_prose_uses_analysis_timezone_without_changing_timestamp(tmp_path):
    repo = imported(tmp_path, '<Record type="HKCategoryTypeIdentifierHighHeartRateEvent" value="HKCategoryValueNotApplicable" sourceName="S" startDate="2026-11-02T00:30:00+08:00" endDate="2026-11-02T00:30:00+08:00"/>')
    question = analyze_questions(repo, question_ids=["E"], **KW)[0]
    assert "最近一次是 2026-11-02" in question["observation"]
    assert question["rows"][0]["date"].startswith("2026-11-01")
    repo.close()
