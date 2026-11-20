"""Calendar conclusions use real temporal selectors and isolated synthetic data."""

import importlib
import json
from datetime import datetime

import pytest

from healthzip.analytics.cache import clear
from healthzip.analytics.workspace_summary import workspace_summary
from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService

summary_module = importlib.import_module("healthzip.analytics.workspace_summary")
CUTOFF = "2026-11-19T10:00:00+00:00"
VISIBLE = "2026-11-18T01:00:00+00:00"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clear()
    repository = Repository(tmp_path / "synthetic-summary.sqlite3")
    TrainingService(repository)
    repository.create_batch(file_sha256="synthetic-summary", file_name="synthetic", file_size=0, xml_member_path="")
    yield repository
    repository.close()
    clear()


def add(repo, identity, canonical, value=None, unit="bpm", *, end="2026-11-17T12:00:00+00:00",
        start=None, source="合成手表", device="synthetic-device", protocol="synthetic-protocol",
        category=None, available=VISIBLE):
    assert repo.insert_sample(1, {"fingerprint": identity, "raw_type": canonical, "canonical_type": canonical,
        "raw_value": str(value) if value is not None else None, "raw_unit": unit,
        "normalized_value": value, "normalized_unit": unit, "category_value": category,
        "start_utc": start or end, "end_utc": end, "local_date": end[:10], "source_name": source,
        "device": device, "metadata_json": json.dumps({"protocol_id": protocol}), "created_at": available})
    identifier = repo.one("SELECT id FROM health_sample WHERE fingerprint=?", (identity,))[0]
    repo.conn.execute("UPDATE source_revision SET available_at=? WHERE table_name='health_sample' AND record_id=?",
                      (available, identifier))
    repo.conn.commit()
    return identifier


def view(repo, workspace, *, period="week", cutoff=CUTOFF, zone="Asia/Shanghai"):
    result = workspace_summary(repo, workspace, cutoff_time=cutoff, timezone_name=zone)
    return next(item for item in result["periods"] if item["period"] == period)


def fact(period, label):
    return next(item for item in period["facts"] if item["label"] == label)


@pytest.mark.parametrize("zone,cutoff,week,month,days", [
    ("Asia/Shanghai", "2026-01-01T00:30:00+00:00", "2025-12-28T16:00:00+00:00", "2025-12-31T16:00:00+00:00", (4, 1)),
    ("America/New_York", "2026-01-01T00:30:00+00:00", "2025-12-29T05:00:00+00:00", "2025-12-01T05:00:00+00:00", (3, 31)),
    ("America/New_York", "2026-03-09T12:00:00+00:00", "2026-03-09T04:00:00+00:00", "2026-03-01T05:00:00+00:00", (1, 9)),
])
def test_local_calendar_year_and_dst_boundaries(repo, zone, cutoff, week, month, days):
    result = workspace_summary(repo, "导入与总览", timezone_name=zone, cutoff_time=cutoff)
    assert [item["window"]["start"] for item in result["periods"]] == [week, month]
    assert [item["coverage"]["window_days"] for item in result["periods"]] == list(days)
    assert all(item["window"]["closure"] == "[start,end)" and item["window"]["partial"] for item in result["periods"])


def test_exact_calendar_start_is_empty_current_period(repo):
    result = workspace_summary(repo, "睡眠", cutoff_time="2026-06-01T00:00:00+08:00")
    for period in result["periods"]:
        assert period["window"]["start"] == period["window"]["end"]
        assert period["coverage"] == {"observed_days": 0, "window_days": 0, "record_count": 0}
        assert period["facts"] == [] and "暂无" in period["conclusions"][0]


def test_daily_values_not_raw_average_and_sources_stay_separate(repo):
    add(repo, "day1a", "resting_heart_rate_bpm", 50)
    add(repo, "day1b", "resting_heart_rate_bpm", 70)
    add(repo, "day2", "resting_heart_rate_bpm", 90, end="2026-11-18T12:00:00+00:00")
    other = add(repo, "other", "resting_heart_rate_bpm", 100, device="<HKDevice UUID private-device>", protocol="internal-method-key")
    add(repo, "hrv", "hrv_sdnn_ms", 30, "ms")
    add(repo, "late", "hrv_sdnn_ms", 200, "ms", available="2026-11-20T01:00:00+00:00")
    at_cutoff = add(repo, "at-cutoff", "resting_heart_rate_bpm", 200, end=CUTOFF)
    result = view(repo, "心率 / HRV")
    resting = [item for item in result["facts"] if item["label"] == "静息心率"]
    assert sorted(item["value"] for item in resting) == [75, 100]
    assert len({item["source"] for item in resting}) == 2
    assert all("来源" in item["source"] and "private-device" not in item["source"] for item in resting)
    assert f"health_sample:{other}" in {identifier for item in resting for identifier in item["source_record_ids"]}
    assert all(f"health_sample:{at_cutoff}" not in item["source_record_ids"] for item in resting)
    assert fact(result, "HRV（SDNN）")["value"] == 30
    assert "平均 75 bpm" in "".join(result["conclusions"])
    assert "private-device" not in "".join(result["conclusions"])
    assert "internal-method-key" not in "".join(result["conclusions"])
    assert result["coverage"]["record_count"] == 5


def test_sleep_union_positive_days_sources_and_partial_window(repo):
    for identity, start, end, source, category in [
        ("sleep1", "2026-11-16T16:00:00+00:00", "2026-11-17T00:00:00+00:00", "合成手表", "Asleep"),
        ("overlap", "2026-11-16T20:00:00+00:00", "2026-11-17T00:00:00+00:00", "合成手表", "AsleepCore"),
        ("sleep2", "2026-11-17T20:00:00+00:00", "2026-11-18T00:00:00+00:00", "合成手表", "Asleep"),
        ("other", "2026-11-17T22:00:00+00:00", "2026-11-18T00:00:00+00:00", "其他来源", "Asleep"),
        ("zero", "2026-11-18T00:00:00+00:00", "2026-11-18T00:00:00+00:00", "合成手表", "Asleep"),
        ("inbed", "2026-11-18T20:00:00+00:00", "2026-11-19T00:00:00+00:00", "合成手表", "InBed"),
    ]:
        add(repo, identity, "sleep_stage", unit="category", start=start, end=end, source=source,
            category="HKCategoryValueSleepAnalysis" + category)
    result = view(repo, "睡眠")
    by_source = {item["source"]: item for item in result["facts"]}
    assert by_source["合成手表"]["value"] == 6
    assert by_source["合成手表"]["observed_days"] == 2
    assert by_source["合成手表"]["sample_count"] == 3
    assert by_source["其他来源"]["value"] == 2
    assert result["coverage"]["observed_days"] == 2
    assert "平均 6 小时" in "".join(result["conclusions"])
    assert "有效结束日期" in "".join(result["conclusions"])


def test_sleep_boundary_uses_canonical_interval_clipping_and_wake_date(repo):
    add(repo, "cross-week", "sleep_stage", unit="category", start="2026-11-15T12:00:00+00:00",
        end="2026-11-15T20:00:00+00:00", category="HKCategoryValueSleepAnalysisAsleep")
    weekly = view(repo, "睡眠")
    monthly = view(repo, "睡眠", period="month")
    assert fact(weekly, "已观察睡眠")["value"] == 4
    assert fact(monthly, "已观察睡眠")["value"] == 8
    assert fact(weekly, "已观察睡眠")["dates"] == ["2026-11-16"]


def test_window_external_weight_is_not_current_and_body_changes_are_observed(repo):
    add(repo, "old", "body_mass_kg", 80, "kg", end="2026-10-01T00:00:00+00:00")
    assert view(repo, "体重 / 有氧")["facts"] == []
    add(repo, "weight1", "body_mass_kg", 71, "kg")
    add(repo, "weight2", "body_mass_kg", 70, "kg", end="2026-11-18T12:00:00+00:00")
    add(repo, "vo2", "vo2_max_ml_kg_min", 42, "mL/kg/min")
    result = view(repo, "体重 / 有氧")
    assert fact(result, "体重")["value"] == 70.5
    assert fact(result, "体重")["statistics"]["first_to_last_change"] == -1
    assert fact(result, "来源报告 VO₂max")["value"] == 42
    assert "相差 -1.0 kg" in "".join(result["conclusions"])


def test_correction_moves_out_of_window_delete_and_restore_invalidate_cache(repo):
    identifier = add(repo, "rhr", "resting_heart_rate_bpm", 55)
    assert fact(view(repo, "心率 / HRV"), "静息心率")["value"] == 55
    repo.conn.execute("UPDATE health_sample SET start_utc='2026-10-01T00:00:00+00:00',end_utc='2026-10-01T00:00:00+00:00' WHERE id=?", (identifier,))
    repo.conn.execute("UPDATE source_revision SET available_at=? WHERE revision_id=(SELECT MAX(revision_id) FROM source_revision)", (VISIBLE,))
    repo.conn.commit()
    assert view(repo, "心率 / HRV")["facts"] == []
    repo.conn.execute("UPDATE health_sample SET start_utc='2026-11-17T12:00:00+00:00',end_utc='2026-11-17T12:00:00+00:00',record_status='deleted' WHERE id=?", (identifier,))
    repo.conn.execute("UPDATE source_revision SET available_at=? WHERE revision_id=(SELECT MAX(revision_id) FROM source_revision)", (VISIBLE,))
    repo.conn.commit()
    assert view(repo, "心率 / HRV")["facts"] == []
    repo.conn.execute("UPDATE health_sample SET record_status='active' WHERE id=?", (identifier,))
    repo.conn.execute("UPDATE source_revision SET available_at=? WHERE revision_id=(SELECT MAX(revision_id) FROM source_revision)", (VISIBLE,))
    repo.conn.commit()
    assert fact(view(repo, "心率 / HRV"), "静息心率")["value"] == 55


def test_workout_known_totals_missing_units_and_source_separation(repo):
    for name, source, duration, energy, unit in [
        ("known", "合成手表", 60, 418.4, "kJ"), ("missing", "合成手表", None, None, None),
        ("zero", "其他设备", 0, 0, "kcal"),
    ]:
        identifier, _ = repo.insert_workout(1, {"fingerprint": name, "source_name": source,
            "activity_type": "HKWorkoutActivityTypeRunning", "start_utc": "2026-11-17T12:00:00+00:00",
            "end_utc": "2026-11-17T13:00:00+00:00", "duration_seconds": duration,
            "energy_value": energy, "energy_unit": unit})
        repo.conn.execute("UPDATE source_revision SET available_at=? WHERE table_name='workout' AND record_id=?", (VISIBLE, identifier))
    repo.conn.commit()
    result = view(repo, "运动")
    energies = {item["source"]: item for item in result["facts"] if item["label"] == "Workout 报告能量"}
    assert energies["合成手表"]["value"] == pytest.approx(100)
    assert energies["合成手表"]["missing_count"] == 1
    assert energies["其他设备"]["value"] == 0
    assert fact(result, "已记录运动时长")["value"] == 1
    assert result["coverage"]["record_count"] == 3


def test_cycle_keeps_raw_categories_without_counting_bleeding_days(repo):
    add(repo, "none", "menstrual_flow", unit="category", category="HKCategoryValueMenstrualFlowNone")
    add(repo, "unknown", "menstrual_flow", unit="category", category="unknown")
    result = view(repo, "周期")
    item = fact(result, "月经类别原始记录")
    assert item["value"] == 2 and item["observed_days"] == 1
    assert {point["recorded_category"] for point in item["observations"]} == {"unknown", "HKCategoryValueMenstrualFlowNone"}
    assert "不代表出血天数或周期数" in result["conclusions"][0]


def test_strength_real_completed_draft_delete_and_undo(repo, monkeypatch):
    service_module = importlib.import_module("healthzip.training.service")
    original = service_module.timestamp
    clock = {"now": "2026-11-17T14:00:00+00:00"}
    monkeypatch.setattr(service_module, "timestamp", lambda value=None: original(value or clock["now"]))
    service = TrainingService(repo)
    session = service.start_session("合成训练", started_at="2026-11-17T12:00:00+00:00")
    exercise = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", {})
    completed = service.add_set(exercise["id"], actual={"load_value": 20, "load_unit": "kg", "reps": 8,
        "completion_state": "completed", "ended_at": "2026-11-17T13:00:00+00:00"})
    service.add_set(exercise["id"])
    initial = view(repo, "力量")
    assert fact(initial, "已完成实际组")["value"] == 1
    assert initial["coverage"]["record_count"] == 1
    assert initial["facts"][0]["source_record_ids"] == [f"strength_set:{completed['set_uuid']}"]
    clock["now"] = "2026-11-18T14:00:00+00:00"
    session = service.get_session(session["id"])
    service.delete_session(session["id"], base_revision=session["revision"], event_id="synthetic-delete")
    assert view(repo, "力量")["facts"] == []
    clock["now"] = "2026-11-19T09:00:00+00:00"
    deleted = service.get_session(session["id"])
    service.undo_event("synthetic-delete", base_revision=deleted["revision"])
    assert fact(view(repo, "力量"), "已完成实际组")["value"] == 1


def test_hot_cache_does_not_read_sources_replay_training_or_evaluate(repo, monkeypatch):
    add(repo, "rhr", "resting_heart_rate_bpm", 55)
    first = workspace_summary(repo, "导入与总览", cutoff_time=CUTOFF)
    changes = repo.conn.total_changes

    def unexpected(*args, **kwargs):
        raise AssertionError("hot summary must not read or compute business records")

    monkeypatch.setattr(summary_module, "samples_as_of", unexpected)
    monkeypatch.setattr(summary_module, "evaluate", unexpected)
    monkeypatch.setattr(summary_module, "evaluate_observation", unexpected)
    monkeypatch.setattr(TrainingService, "history_as_of", unexpected)
    second = workspace_summary(repo, "导入与总览", cutoff_time=CUTOFF)
    assert first == second
    second["periods"][0]["conclusions"].clear()
    assert workspace_summary(repo, "导入与总览", cutoff_time=CUTOFF) == first
    assert repo.conn.total_changes == changes and not repo.conn.in_transaction


def test_summary_never_commits_caller_transaction_or_writes_analysis(repo):
    repo.conn.execute("INSERT INTO schema_meta(key,value) VALUES('summary_pending','pending')")
    changes = repo.conn.total_changes
    workspace_summary(repo, "睡眠", cutoff_time=CUTOFF)
    assert repo.conn.in_transaction and repo.conn.total_changes == changes
    assert repo.one("SELECT COUNT(*) FROM analysis_run")[0] == 0
    assert repo.one("SELECT COUNT(*) FROM workflow_run")[0] == 0
    other = Repository(repo.path)
    try:
        assert other.one("SELECT value FROM schema_meta WHERE key='summary_pending'") is None
    finally:
        other.close()
        repo.conn.rollback()


def test_concurrent_correction_recomputes_from_new_baseline(repo, monkeypatch):
    identifier = add(repo, "rhr", "resting_heart_rate_bpm", 55)
    original = summary_module.samples_as_of
    calls = []

    def interleaved(*args, **kwargs):
        rows = original(*args, **kwargs)
        calls.append(1)
        if len(calls) == 1:
            repo.conn.execute("UPDATE health_sample SET raw_value='75',normalized_value=75 WHERE id=?", (identifier,))
            repo.conn.execute("UPDATE source_revision SET available_at=? WHERE revision_id=(SELECT MAX(revision_id) FROM source_revision)", (VISIBLE,))
            repo.conn.commit()
        return rows

    monkeypatch.setattr(summary_module, "samples_as_of", interleaved)
    result = view(repo, "心率 / HRV")
    assert fact(result, "静息心率")["value"] == 75 and len(calls) == 2


def test_automatic_cache_crosses_minutes_but_expires_at_local_date(repo, monkeypatch):
    clock = {"now": datetime.fromisoformat(CUTOFF)}

    class ControlledDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    monkeypatch.setattr(summary_module, "datetime", ControlledDatetime)
    first = workspace_summary(repo, "睡眠")
    clock["now"] = datetime.fromisoformat("2026-11-19T10:00:59+00:00")
    assert workspace_summary(repo, "睡眠")["cutoff_time"] == first["cutoff_time"]
    clock["now"] = datetime.fromisoformat("2026-11-19T10:01:00+00:00")
    assert workspace_summary(repo, "睡眠")["cutoff_time"] == first["cutoff_time"]
    clock["now"] = datetime.fromisoformat("2026-11-19T16:00:01+00:00")
    assert workspace_summary(repo, "睡眠")["cutoff_time"] != first["cutoff_time"]


def test_input_validation(repo):
    with pytest.raises(ValueError, match="timezone_required"):
        workspace_summary(repo, "睡眠", cutoff_time="2026-11-19T10:00:00")
    with pytest.raises(ValueError, match="unsupported_summary_workspace"):
        workspace_summary(repo, "无效工作区", cutoff_time=CUTOFF)
