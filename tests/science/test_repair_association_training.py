"""Independent repair scenarios; no private workspace and no screenshot fixture reuse."""
import json
from datetime import datetime, timedelta
from random import Random
from unittest.mock import patch

import pytest

from healthzip.analytics.body_metrics import analyze_body_metric, analyze_questions
from healthzip.analytics.body_questions import _render_question, sleep_sdnn_associations
from healthzip.db.repository import Repository
from healthzip.science.contracts import Window
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService
from healthzip.workflows import WorkflowRequest, run_workflow
from healthzip.workflows.longitudinal import ordinary_review


def association_inputs(coefficient, *, source="独立设备甲", n=132, seed=91241, time_trend=False):
    rng = Random(seed)
    start = datetime.fromisoformat("2024-02-03T00:00:00+08:00")
    stream = (source, "设备 " + source, "晨起坐姿", "test-3")
    episodes, points = [], []
    for i in range(n):
        hours = 5.5 + i * .02 if time_trend else 6.8 + rng.uniform(-.9, .9)
        wake = start + timedelta(days=i, hours=7)
        sample = wake + timedelta(minutes=40 + i % 4)
        value = 46 + coefficient * (hours - 6.8) + .007 * i + rng.gauss(0, .7)
        identity = f"{source}-{i}"
        episodes.append({"date": wake.date().isoformat(), "event_start": (wake - timedelta(hours=hours)).isoformat(),
                         "event_end": wake.isoformat(), "value": hours * 60, "protocol": stream,
                         "episode_id": "sleep-" + identity})
        points.append({"date": wake.date().isoformat(), "value": value, "observed_at": sample.isoformat(),
                       "source_record_ids": [identity], "observations": [{"value": value, "start": sample.isoformat(),
                        "end": (sample + timedelta(minutes=1)).isoformat(), "source_record_id": identity,
                        "conditions": {"sampling_mode": {"value": "active", "source": "record"},
                                       "posture": {"value": "seated", "source": "record"}}}]})
    return episodes, {stream: points}


@pytest.mark.parametrize("coefficient,direction", [(4.3, "positive"), (-3.7, "negative"), (0, "uncertain")])
def test_t01_t03_independent_directions_have_no_support_votes(coefficient, direction):
    episodes, points = association_inputs(coefficient)
    question = _render_question("W6", {"hrv_sdnn_ms": points}, [], [], [], episodes, [],
        Window("2024-02-03T00:00:00+08:00", "2024-06-15T00:00:00+08:00", "2024-06-15T00:00:00+08:00"))
    model = question["association"]["groups"][0]
    assert model["status"] == "estimated"
    assert model["coefficient"] == pytest.approx(coefficient, abs=.3)
    assert model["direction"] == direction
    assert not question["support"] and not question["counterevidence"]
    assert question["support_count"] == question["counterevidence_count"] == 0
    assert len(model["neutral_observations"]) == 131
    assert all(p["identity"] == "adjacent_description_not_independent_hypothesis_evidence"
               for p in model["neutral_observations"])
    assert model["hypothesis"]["status"] == "exploratory_no_prespecified_direction"
    if coefficient < 0:
        assert any(p["sleep_hours_change"] > 0 and p["sdnn_ms_change"] < 0 for p in model["neutral_observations"])
    assert "恢复改善" not in question["observation"]


def test_t03_time_confounding_keeps_actual_pairs():
    episodes, points = association_inputs(4, time_trend=True)
    result = sleep_sdnn_associations(episodes, points, timezone_name="Asia/Shanghai")
    assert result["status"] == "descriptive_only"
    group = result["groups"][0]
    assert group["direction"] == "not_estimable" and len(group["pairs"]) == 132
    assert "时间" in group["reason"] and group["identity"]["paired_dates"] == 132


def test_t04_opposite_groups_and_sparse_group_keep_independent_identity():
    e1, p1 = association_inputs(3.8, source="独立正向设备")
    e2, p2 = association_inputs(-4.2, source="独立负向设备", seed=91243)
    e3, p3 = association_inputs(2, source="独立稀疏设备", n=4)
    result = sleep_sdnn_associations(e1 + e2 + e3, {**p1, **p2, **p3}, timezone_name="Asia/Shanghai")
    assert result["status"] == "descriptive_only" and "coefficient" not in result
    groups = {g["identity"]["source"]: g for g in result["groups"]}
    assert groups["独立正向设备"]["direction"] == "positive"
    assert groups["独立负向设备"]["direction"] == "negative"
    assert groups["独立稀疏设备"]["status"] == "descriptive_only"
    for source, group in groups.items():
        identity = group["identity"]
        assert identity["device"] == "设备 " + source
        assert identity["sleep_source"]["source"] == source
        assert identity["known_conditions"]["sampling_mode"] == ["active"]
        assert identity["actual_local_time_range"] == ["07:40:00", "07:44:00"]
        assert identity["time_band"]["basis"].startswith("product_")
        assert identity["paired_dates"] == (4 if "稀疏" in source else 132)


def test_t04_algorithm_and_recording_duration_do_not_merge_in_one_time_bucket():
    episodes, points = association_inputs(3.5, n=24)
    for i, point in enumerate(next(iter(points.values()))):
        point["observations"][0]["conditions"].update(
            algorithm_version={"value": "a" if i % 2 else "b", "source": "record"},
            recording_duration_seconds={"value": 60 if i % 2 else 180, "source": "record"})
    result = sleep_sdnn_associations(episodes, points, timezone_name="Asia/Shanghai")
    assert len(result["groups"]) == 2
    assert {tuple(g["identity"]["known_conditions"]["algorithm_version"]) for g in result["groups"]} == {("a",), ("b",)}
    assert sum(g["identity"]["sdnn_sample_count"] for g in result["groups"]) == 24


TRAINING_WINDOW = {"start": "2024-07-01T00:00:00+08:00", "end": "2024-07-29T00:00:00+08:00", "timezone": "Asia/Shanghai"}


def ordinary_set(i, *, reps=None, load=30, rir=2, **changes):
    return {"id": f"strength_set:{i}", "set_uuid": str(i), "user_id": "local", "exercise_id": "bench",
        "definition_version": "1", "measurement_mode": "repetitions", "exercise_name": "合成卧推",
        "equipment_instance_id": "rack-a", "load_basis": "external_total_kg", "load_basis_confirmed": True,
        "side": "bilateral", "repetition_semantics": "full_repetitions", "rom_protocol": "full",
        "settings": {}, "settings_confirmed": True, "completion_state": "completed", "set_type": "work",
        "set_number": 1, "session_id": i, "session_exercise_id": f"instance-{i}",
        "ended_at": f"2024-07-{i * 6:02d}T17:00:00+08:00", "load_value": load, "load_unit": "kg",
        "reps": reps if reps is not None else 9 + i, "rir": rir, "reference_set": False, **changes}


def test_t06_three_ordinary_records_without_reference_keep_every_point_and_stage():
    result = ordinary_review([ordinary_set(i) for i in range(1, 4)], TRAINING_WINDOW)
    assert result["record_count"] == 3 and len(result["series"]) == 1
    group = result["series"][0]
    assert [p["reps"] for p in group["points"]] == [10, 11, 12]
    assert not any(p["reference_set"] for p in group["points"])
    assert [p["same_load_repetitions_change"] for p in group["comparisons"]] == [1, 1]
    assert group["periods"][0]["same_load_summaries"][0]["reps"] == {"n": 2, "median": 10.5, "min": 10, "max": 11}
    assert group["periods"][1]["same_load_summaries"][0]["reps"]["median"] == 12


@pytest.mark.parametrize("change", [{"equipment_instance_id": "rack-b"}, {"load_basis": "plates_per_side_kg"},
                                    {"set_number": 2}, {"set_type": "warmup"}, {"side": "left"}])
def test_t07_changed_physical_identity_and_ordinal_split_only_affected_series(change):
    result = ordinary_review([ordinary_set(1), ordinary_set(2, **change), ordinary_set(3)], TRAINING_WINDOW)
    assert result["record_count"] == 3 and len(result["series"]) == 2
    groups = sorted(result["series"], key=lambda g: g["record_count"])
    assert not groups[0]["comparisons"]
    assert groups[1]["comparisons"][0]["same_load_repetitions_change"] == 2


def test_t07_unknown_rir_zero_tradeoff_assistance_and_duplicate_instances():
    result = ordinary_review([ordinary_set(1, rir=None), ordinary_set(2, rir=0), ordinary_set(3, load=35, reps=8)], TRAINING_WINDOW)
    group = result["series"][0]
    assert group["rir_missing_n"] == 1
    assert group["points"][1]["rir"] == 0
    assert group["comparisons"][0]["same_load_repetitions_change"] == 1
    assert group["comparisons"][0]["rir_change"] is None
    assert group["comparisons"][1]["load_change"] == 5
    assert group["comparisons"][1]["repetitions_change"] == -3
    assert group["comparisons"][1]["same_load_repetitions_change"] is None
    assistance = ordinary_review([ordinary_set(1, load_basis="assistance_setting"),
                                  ordinary_set(2, load=25, load_basis="assistance_setting")], TRAINING_WINDOW)
    assert assistance["series"][0]["comparisons"][0]["load_meaning"] == "assistance_reduced"
    unknown = ordinary_review([ordinary_set(1, equipment_instance_id=None), ordinary_set(2, equipment_instance_id=None)], TRAINING_WINDOW)
    assert len(unknown["series"]) == 2 and not any(g["comparisons"] for g in unknown["series"])
    assert all(not g["condition_known"] and g["points"] for g in unknown["series"])
    repeated = ordinary_review([ordinary_set(1), ordinary_set(2), ordinary_set(3, session_id=2)], TRAINING_WINDOW)
    assert len(repeated["series"]) == 1 and not repeated["series"][0]["comparisons"]
    assert set(repeated["series"][0]["unpaired_record_ids"]) == {"2", "3"}


def test_t06_real_service_question_and_legacy_workflow_keep_ordinary_progress(tmp_path):
    repo = Repository(tmp_path / "ordinary.sqlite")
    service = TrainingService(repo)
    equipment = service.create_equipment("Synthetic independent rack", "barbell")
    condition = {"equipment_instance_id": equipment["id"], "load_basis": "external_total_kg", "load_basis_confirmed": True,
                 "side": "bilateral", "repetition_semantics": "full_repetitions", "rom_protocol": "full", "settings": {}, "settings_confirmed": True}
    for day, reps in ((6, 10), (12, 11), (18, 12)):
        at = f"2024-07-{day:02d}T17:00:00+08:00"
        with patch("healthzip.training.service.timestamp", side_effect=lambda value=None: timestamp(value) if value else at):
            session = service.start_session("Synthetic ordinary training", started_at=at)
            instance = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
            service.add_set(instance["id"], actual={"completion_state": "completed", "set_type": "work", "load_value": 30,
                "load_unit": "kg", "reps": reps, "rir": None, "ended_at": at})
            service.end_session(session["id"], ended_at=at)
    args = {"window_start": TRAINING_WINDOW["start"], "window_end": TRAINING_WINDOW["end"], "cutoff_time": TRAINING_WINDOW["end"]}
    questions = analyze_questions(repo, question_ids=["W1", "W4"], **args)
    assert all([p["reps"] for p in q["ordinary_training"]["series"][0]["points"]] == [10, 11, 12] for q in questions)
    result = run_workflow(repo, WorkflowRequest("W1", cutoff_time=TRAINING_WINDOW["end"], window_days=28), knowledge_root=tmp_path / "absent")
    assert result["supplements"]["ordinary_training"]["record_count"] == 3
    assert not result["supplements"].get("strength_points")  # No invented STR-11 permission.
    from healthzip.training.service import report_event_reads
    with report_event_reads(repo):
        original = service.session_as_of(session["id"], cutoff_time=TRAINING_WINDOW["end"])
        original["sets"][0]["reps"] = 999
        original["exercises"][0]["condition"]["settings"]["mutated_by_consumer"] = True
        reread = service.session_as_of(session["id"], cutoff_time=TRAINING_WINDOW["end"])
        assert reread["sets"][0]["reps"] == 12
        assert "mutated_by_consumer" not in reread["exercises"][0]["condition"]["settings"]
    repo.close()


def test_t05_question_period_medians_equal_detail_and_batch_identity(tmp_path):
    repo = Repository(tmp_path / "medians.sqlite")
    for i, value in enumerate((59, 60, 98, 61, 62, 100), 1):
        at = f"2024-08-{i:02d}T09:00:00+08:00"
        row = {"id": i, "record_status": "active", "canonical_type": "resting_heart_rate_bpm", "value": value,
               "normalized_value": value, "normalized_unit": "count/min", "unit": "count/min", "raw_value": str(value), "raw_unit": "count/min",
               "start_utc": at, "end_utc": at, "source_name": "Independent median source", "source_version": "1", "device": "test-watch",
               "raw_type": "HKQuantityTypeIdentifierRestingHeartRate", "metadata_json": json.dumps({"protocol_id": "seated"})}
        repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) VALUES('health_sample',?,?,?,'synthetic_acceptance')",
                          (i, at, json.dumps(row)))
    repo.conn.commit()
    args = {"window_start": "2024-08-04T00:00:00+08:00", "window_end": "2024-08-07T00:00:00+08:00", "cutoff_time": "2024-08-07T00:00:00+08:00"}
    metric = analyze_body_metric(repo, "resting_heart_rate_bpm", **args)["value"]["streams"][0]
    question = analyze_questions(repo, question_ids=["W4"], **args)[0]
    observation = next(r for r in question["rows"] if r.get("metric") == "resting_heart_rate_bpm")
    assert observation["value"] == metric["current"]["value"] == 62
    assert observation["first_value"] == metric["previous"]["value"] == 60
    assert observation["difference"] == metric["absolute_change"] == 2
    assert observation["trajectory_difference"] == 39
    assert observation["source_record_ids"] == metric["current"]["source_record_ids"]
    assert observation["comparison"]["current"]["recorded_days"] == metric["current"]["recorded_days"] == 3
    assert question["fact_id"] == next(q for q in analyze_questions(repo, **args) if q["id"] == "W4")["fact_id"]
    repo.close()
