"""Synthetic SQL and Streamlit coverage for the current Workout workspace."""

from datetime import date, datetime, timezone

import pytest

from healthzip.analytics.workouts import summarize_workouts, workout_inventory
from healthzip.db.repository import Repository


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = Repository(tmp_path / "synthetic-workouts.sqlite3")
    result.create_batch(file_sha256="synthetic-workouts", file_name="synthetic", file_size=0,
                        xml_member_path="")
    yield result
    result.close()


def _workout(repo, identity, start, *, energy=100, unit="kcal", duration=1800,
             status="active", end=None, activity="HKWorkoutActivityTypeRunning"):
    row_id, _ = repo.insert_workout(1, {
        "fingerprint": identity, "activity_type": activity, "start_utc": start,
        "end_utc": end or start, "local_date": "1999-01-01",
        "duration_seconds": duration, "energy_value": energy, "energy_unit": unit,
        "source_name": "Synthetic Watch", "record_status": status,
    })
    return row_id


def _stat(repo, row_id, start, end, value, unit="kcal"):
    repo.insert_workout_stat(row_id, {
        "raw_type": "HKQuantityTypeIdentifierActiveEnergyBurned", "start": start,
        "end": end, "sum": value, "unit": unit,
    })


def _summary(repo, period="week", zone="UTC", start=date(2020, 1, 1), end=date(2025, 12, 31)):
    inventory = workout_inventory(repo, zone)
    return summarize_workouts(inventory["rows"], period, start, end)


def test_iso_week_year_and_partial_date_range_use_actual_local_start(repo):
    for identity, start in (("monday", "2020-12-28T12:00:00Z"),
                            ("sunday", "2021-01-03T12:00:00Z"),
                            ("next", "2021-01-04T12:00:00Z")):
        _workout(repo, identity, start)
    result = _summary(repo, start=date(2020, 12, 29), end=date(2021, 1, 4))
    periods = result["periods"]
    assert [item["period_label"] for item in periods] == ["2020年第53周", "2021年第01周"]
    assert [item["workout_count"] for item in periods] == [1, 1]
    assert periods[0]["period_start"] == date(2020, 12, 28)
    assert periods[0]["selected_start"] == date(2020, 12, 29)
    assert periods[0]["selected_end"] == date(2021, 1, 3)
    assert all(item["partial_period"] for item in periods)


def test_timezone_moves_record_between_calendar_month_and_year(repo):
    _workout(repo, "boundary", "2024-12-31T17:30:00Z")
    _workout(repo, "older", "2024-01-01T00:00:00Z")
    local = _summary(repo, "month", "Asia/Shanghai")
    assert [item["period_label"] for item in local["periods"]] == ["2024年01月", "2025年01月"]
    utc = _summary(repo, "year", "UTC")
    assert [(item["period_label"], item["workout_count"]) for item in utc["periods"]] == [("2024年", 2)]
    shanghai = _summary(repo, "year", "Asia/Shanghai")
    assert [(item["period_label"], item["workout_count"]) for item in shanghai["periods"]] == [
        ("2024年", 1), ("2025年", 1)]


def test_missing_values_stay_unknown_zero_stays_zero_and_kj_converts(repo):
    _workout(repo, "missing", "2024-01-01T12:00:00Z", energy=None, duration=None)
    _workout(repo, "zero", "2024-01-02T12:00:00Z", energy=0, duration=0)
    _workout(repo, "kj", "2024-01-03T12:00:00Z", energy=418.4, unit="kJ", duration=60)
    _workout(repo, "unknown", "2024-01-04T12:00:00Z", energy=10, unit="unknown", duration=-1)
    result = _summary(repo)
    assert result["totals"]["workout_count"] == 4
    assert result["totals"]["energy_kcal"] == pytest.approx(100)
    assert result["totals"]["duration_seconds"] == 60
    assert result["totals"]["missing_energy_count"] == 2
    assert result["totals"]["missing_duration_count"] == 2
    only_missing = _summary(repo, start=date(2024, 1, 1), end=date(2024, 1, 1))["totals"]
    assert only_missing["energy_kcal"] is None and only_missing["duration_seconds"] is None
    only_zero = _summary(repo, start=date(2024, 1, 2), end=date(2024, 1, 2))["totals"]
    assert only_zero["energy_kcal"] == 0 and only_zero["duration_seconds"] == 0


def test_current_status_unknown_time_and_suspected_duplicates_are_explicit(repo):
    _workout(repo, "active", "2024-01-01T12:00:00Z")
    _workout(repo, "deleted", "2024-01-01T12:00:00Z", status="deleted")
    _workout(repo, "superseded", "2024-01-01T12:00:00Z", status="superseded")
    _workout(repo, "undated", None)
    duplicate = _workout(repo, "possible-duplicate", "2024-01-02T12:00:00Z")
    repo.conn.execute("UPDATE workout SET suspected_duplicate=1 WHERE id=?", (duplicate,))
    inventory = workout_inventory(repo)
    assert inventory["undated_count"] == 1
    result = summarize_workouts(inventory["rows"], "year", date(2024, 1, 1), date(2024, 12, 31))
    assert result["totals"]["workout_count"] == 2
    assert result["totals"]["energy_kcal"] == 200
    assert result["totals"]["suspected_duplicate_count"] == 1


def test_energy_uses_one_whole_workout_statistic_without_adding_header_or_samples(repo):
    start, end = "2024-01-01T12:00:00Z", "2024-01-01T13:00:00Z"
    header = _workout(repo, "header", start, end=end, energy=200)
    _stat(repo, header, start, end, 900)
    fallback = _workout(repo, "modern", start, end=end, energy=None)
    # Equivalent instants in Apple's offset syntax, including an identical repeated stat.
    for _ in range(2):
        _stat(repo, fallback, "2024-01-01 20:00:00 +0800", "2024-01-01 21:00:00 +0800", 418.4, "kJ")
    repo.conn.execute("INSERT INTO health_sample(fingerprint,import_batch_id,raw_type,canonical_type,"
                      "raw_value,raw_unit,created_at) VALUES('unrelated',1,"
                      "'HKQuantityTypeIdentifierActiveEnergyBurned','active_energy_kcal',"
                      "'9999','kcal',?)", (start,))
    queries = []
    repo.conn.set_trace_callback(queries.append)
    result = _summary(repo)
    repo.conn.set_trace_callback(None)
    assert result["totals"]["energy_kcal"] == pytest.approx(300)
    assert result["totals"]["missing_energy_count"] == 0
    assert {row["energy_source"] for row in result["rows"]} == {
        "Workout 总能量字段", "Workout 整场活动能量统计"}
    assert not any("health_sample" in query.lower() for query in queries)


def test_ambiguous_subinterval_or_unverified_statistics_stay_missing(repo):
    start, end = "2024-01-01T12:00:00Z", "2024-01-01T13:00:00Z"
    conflict = _workout(repo, "conflict", start, end=end, energy=None)
    _stat(repo, conflict, start, end, 100)
    _stat(repo, conflict, start, end, 200)
    partial = _workout(repo, "partial", start, end=end, energy=None)
    _stat(repo, partial, start, "2024-01-01T12:30:00Z", 50)
    _stat(repo, partial, "2024-01-01T12:30:00Z", end, 50)
    unit = _workout(repo, "unit", start, end=end, energy=None)
    _stat(repo, unit, start, end, 100, "unknown")
    result = _summary(repo)
    assert result["totals"]["energy_kcal"] is None
    assert result["totals"]["missing_energy_count"] == 3
    assert all(row["energy_reason"] for row in result["rows"])


def test_unknown_activity_keeps_raw_metadata_and_inventory_reads_during_another_writer(repo):
    _workout(repo, "known", "2024-01-01T12:00:00Z", activity="running")
    _workout(repo, "unknown", "2024-01-02T12:00:00Z", activity="SyntheticUnmappedType")
    repo.conn.commit()
    observer = Repository(repo.path)
    try:
        repo.conn.execute("BEGIN IMMEDIATE")
        _workout(repo, "pending", "2024-01-03T12:00:00Z")
        changes = observer.conn.total_changes
        inventory = workout_inventory(observer)
        assert observer.conn.total_changes == changes and not observer.conn.in_transaction
        assert len(inventory["rows"]) == 2
        assert inventory["rows"][0]["activity_name"] == "未识别运动类型"
        assert inventory["rows"][0]["raw_activity_type"] == "SyntheticUnmappedType"
        assert inventory["rows"][1]["activity_name"] == "跑步"
        repo.conn.commit()
        assert len(workout_inventory(observer)["rows"]) == 3
    finally:
        repo.conn.rollback()
        observer.close()


def _app(repo, timezone_name="Asia/Shanghai"):
    from streamlit.testing.v1 import AppTest

    repo.conn.commit()
    return AppTest.from_string(
        "from healthzip.db.repository import Repository\n"
        "from healthzip.ui.workout_page import render_workouts\n"
        f"repo=Repository({str(repo.path)!r})\n"
        f"render_workouts(repo, timezone_name={timezone_name!r})\n"
        "repo.close()", default_timeout=30,
    ).run()


def test_real_streamlit_wrapper_filters_dates_and_switches_all_calendar_periods(repo):
    _workout(repo, "old", "2020-12-31T12:00:00Z", energy=None, duration=None)
    _workout(repo, "new-jan", "2021-01-03T12:00:00Z", activity="HKWorkoutActivityTypeTraditionalStrengthTraining")
    _workout(repo, "new-feb", "2021-02-01T12:00:00Z")
    app = _app(repo)
    assert not app.exception
    assert app.selectbox(key="workout_year").value == "2021"
    assert app.date_input(key="workout_dates_2021").value == (date(2021, 1, 1), date(2021, 12, 31))
    assert app.metric[0].value == "2"
    details = app.dataframe[-1].value
    assert "传统力量训练" in details["运动类型"].tolist()
    assert "id" not in " ".join(details.columns).lower()
    app.selectbox(key="workout_year").select("全部年份").run()
    assert not app.exception
    assert app.metric[0].value == "3"
    weeks = app.dataframe[0].value
    assert weeks["周期"].tolist() == ["2020年第53周", "2021年第05周"]
    app.radio(key="workout_period").set_value("按月").run()
    assert app.dataframe[0].value["周期"].tolist() == ["2020年12月", "2021年01月", "2021年02月"]
    app.radio(key="workout_period").set_value("按年").run()
    assert app.dataframe[0].value["周期"].tolist() == ["2020年", "2021年"]
    app.date_input(key="workout_dates_全部年份").set_value((date(2021, 1, 1), date(2021, 1, 31))).run()
    assert not app.exception
    assert app.metric[0].value == "1"
    assert "2021-01-03" in app.dataframe[-1].value.iloc[0]["开始时间（本地）"]


def test_real_streamlit_wrapper_shows_unknown_totals_and_missing_counts(repo):
    _workout(repo, "missing", "2020-01-01T12:00:00Z", energy=None, duration=None)
    app = _app(repo)
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["1", "未记录", "未记录", "1"]
    assert app.dataframe[0].value["能量缺失（次）"].tolist() == [1]
    assert any("TEE" in caption.value for caption in app.caption)
    app.selectbox(key="workout_chart").select("记录能量（kcal）").run()
    assert not app.exception
    assert any("没有可绘制" in item.value for item in app.info)


def test_current_year_defaults_to_local_today_and_full_year_remains_user_selectable(repo, monkeypatch):
    from healthzip.ui import workout_page

    frozen = datetime(2026, 11, 18, 17, tzinfo=timezone.utc)

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)

    monkeypatch.setattr(workout_page, "datetime", FixedClock)
    _workout(repo, "january", "2026-01-01T12:00:00Z")
    _workout(repo, "local-today", "2026-11-18T17:00:00Z")
    _workout(repo, "future", "2026-12-01T12:00:00Z")
    app = _app(repo)
    assert not app.exception
    assert app.date_input(key="workout_dates_2026").value == (date(2026, 1, 1), date(2026, 11, 19))
    app.radio(key="workout_period").set_value("按年").run()
    assert not app.exception
    assert app.metric[0].value == "2"
    assert app.dataframe[0].value["周期范围"].tolist() == ["筛选仅含部分日期"]
    selected = _summary(repo, "year", "Asia/Shanghai", date(2026, 1, 1), date(2026, 11, 19))
    assert selected["periods"][0]["partial_period"] is True
    assert any("晚于今天（2026-11-19）" in item.value for item in app.info)
    app.date_input(key="workout_dates_2026").set_value((date(2026, 1, 1), date(2026, 12, 31))).run()
    assert not app.exception
    assert app.metric[0].value == "3"
    assert app.dataframe[0].value["周期范围"].tolist() == ["筛选包含整周期"]
    assert any("不表示记录完整或周期已经结束" in caption.value for caption in app.caption)
    utc_app = _app(repo, "UTC")
    assert not utc_app.exception
    assert utc_app.date_input(key="workout_dates_2026").value == (date(2026, 1, 1), date(2026, 11, 18))
