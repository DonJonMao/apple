"""Product ranges, read-only browsing and cross-process cache validity."""
import importlib
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from healthzip.analytics.cache import cached, clear
from healthzip.analytics.workouts import scoped_workout_inventory
from healthzip.analytics.workspace_summary import workspace_summary
from healthzip.analytics.workspaces import analyze_workspace, latest_observation_dates
from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService

CUTOFF = "2026-11-20T12:00:00+00:00"


@pytest.fixture
def repo(tmp_path):
    clear()
    value = Repository(tmp_path / "synthetic-product.sqlite3")
    yield value
    value.close()
    clear()


def revision(repo, identity, canonical="resting_heart_rate_bpm", value=60, *,
             event="2026-11-18T12:00:00+00:00", available="2026-11-19T12:00:00+00:00",
             status="active", source="Synthetic", table="health_sample"):
    unit = {"resting_heart_rate_bpm": "bpm", "hrv_sdnn_ms": "ms",
            "body_mass_kg": "kg", "vo2_max_ml_kg_min": "mL/kg/min"}.get(canonical, "count")
    payload = {"id": identity, "canonical_type": canonical, "normalized_value": value,
        "normalized_unit": unit, "raw_value": str(value), "raw_unit": unit,
        "source_name": source, "device": "Synthetic", "metadata_json": "{}",
        "start_utc": event, "end_utc": event, "record_status": status}
    repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) "
                      "VALUES(?,?,?,?,'synthetic')", (table, identity, available, json.dumps(payload)))
    repo.conn.commit()


def heart(repo, **kwargs):
    return analyze_workspace(repo, "心率", cutoff_time=CUTOFF, period="month", **kwargs)


def values(view):
    return sorted(point["value"] for series in (view["workspace_scope"]["metrics"]["STATE-RHR"]["value"] or {}).values()
                  for point in series)


def test_fresh_health_and_overview_are_read_only_under_external_writer(repo):
    revision(repo, 1)
    other = Repository(repo.path)
    other.conn.execute("BEGIN IMMEDIATE")
    try:
        changes = repo.conn.total_changes
        assert values(heart(repo)) == [60]
        assert workspace_summary(repo, "总览", cutoff_time=CUTOFF)["periods"][0]["facts"]
        assert repo.conn.total_changes == changes
        assert not repo.conn.in_transaction
        assert repo.one("SELECT value FROM schema_meta WHERE key='training_service_initialization'") is None
    finally:
        other.conn.rollback()
        other.close()


@pytest.mark.parametrize("change", ["type", "date", "delete", "availability"])
def test_domain_revision_invalidates_old_type_and_restoration(repo, change):
    revision(repo, 1)
    first = heart(repo)
    assert values(first) == [60]
    if change == "availability":
        repo.conn.execute("UPDATE source_revision SET available_at='2026-12-01T00:00:00Z'")
        repo.conn.commit()
    else:
        revision(repo, 1, canonical="step_count" if change == "type" else "resting_heart_rate_bpm",
                 event="2026-09-01T00:00:00Z" if change == "date" else "2026-11-18T12:00:00Z",
                 status="deleted" if change == "delete" else "active")
    assert values(heart(repo)) == []
    revision(repo, 1, value=62)
    assert values(heart(repo)) == [62]


def test_other_import_process_invalidates_committed_domain(repo):
    revision(repo, 1)
    assert values(heart(repo)) == [60]
    # Separate interpreter and SQLite connection, using existing ledger triggers.
    code = """import sqlite3,sys,json
conn=sqlite3.connect(sys.argv[1])
row=conn.execute('SELECT payload_json FROM source_revision LIMIT 1').fetchone()
value=json.loads(row[0]); value['normalized_value']=71; value['raw_value']='71'
conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) VALUES('health_sample',1,'2026-11-19T13:00:00Z',?,'synthetic')",(json.dumps(value),))
conn.commit();conn.close()
"""
    subprocess.run([sys.executable, "-c", code, str(repo.path)], check=True)
    assert values(heart(repo)) == [71]


def test_unrelated_catalog_and_source_edit_keep_heart_cache(repo, monkeypatch):
    revision(repo, 1)
    first = heart(repo)
    revision(repo, 2, "step_count", 100)
    repo.conn.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('training_data_version','999')")
    repo.conn.commit()
    module = importlib.import_module("healthzip.analytics.workspaces")
    monkeypatch.setattr(module, "_body_snapshot", lambda *a, **k: pytest.fail("unrelated edit recomputed heart"))
    assert heart(repo) == first


def test_workspace_path_source_and_timezone_are_cache_dependencies(repo, tmp_path):
    revision(repo, 1, source="Synthetic A", event="2026-11-01T00:30:00Z")
    revision(repo, 2, value=72, source="Synthetic B", event="2026-11-01T00:30:00Z")
    assert values(heart(repo, source_filter=["Synthetic A"])) == [60]
    assert values(heart(repo, source_filter=["Synthetic B"])) == [72]
    assert values(heart(repo, timezone_name="America/New_York")) == []
    other = Repository(tmp_path / "another-workspace.sqlite3")
    try:
        assert values(heart(other)) == []
    finally:
        other.close()


def test_month_thirty_days_and_calendar_midnight_have_exact_scopes(repo):
    revision(repo, 1, event="2026-10-25T12:00:00Z")
    assert values(heart(repo)) == []
    trailing = analyze_workspace(repo, "心率", cutoff_time=CUTOFF, period="30d")
    assert values(trailing) == [60]
    assert trailing["workspace_scope"]["window_start"] == "2026-10-21T16:00:00+00:00"
    empty = analyze_workspace(repo, "心率", cutoff_time="2026-11-01T00:00:00+08:00", period="month")
    scope = empty["workspace_scope"]
    assert scope["window_start"] == scope["window_end"] and scope["metrics"] == {}


@pytest.mark.parametrize("period,cutoff,night_end", [
    ("month", "2026-11-01T01:00:00+08:00", "2026-10-31T08:00:00+08:00"),
    ("week", "2026-11-16T01:00:00+08:00", "2026-11-15T08:00:00+08:00"),
])
def test_sleep_fixed_24h_dependency_does_not_change_page_calendar_facts(repo, tmp_path, monkeypatch,
                                                                      period, cutoff, night_end):
    from datetime import timedelta

    from healthzip.analytics.v13 import analyze

    monkeypatch.chdir(tmp_path)
    end = datetime.fromisoformat(night_end)
    payload = {"id": 1, "canonical_type": "sleep_stage", "source_name": "Synthetic sleep",
        "device": "Synthetic", "category_value": "HKCategoryValueSleepAnalysisAsleepCore",
        "start_utc": (end - timedelta(hours=8)).isoformat(), "end_utc": night_end, "record_status": "active"}
    repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) "
                      "VALUES('health_sample',1,?,?,'synthetic')", (night_end, json.dumps(payload)))
    repo.conn.commit()
    view = analyze_workspace(repo, "睡眠", cutoff_time=cutoff, period=period)
    canonical = analyze(repo, cutoff_time=cutoff, period=period, use_cache=False)
    metric = view["workspace_scope"]["metrics"]["STATE-SLEEP-24H"]
    assert metric["value"] == canonical["metrics"]["STATE-SLEEP-24H"]["value"]
    assert metric["value"]["observed_minutes"] == 420
    assert view["sleep"]["nights"] == []
    assert view["workspace_scope"]["metrics"]["REPORT-STATE-SUMMARY"]["daily_facts"] == []
    assert view["workspace_scope"]["latest_observed_at"] is None
    extra = view["workspace_scope"]["extra_metric_windows"]["STATE-SLEEP-24H"]
    assert extra["window"] == metric["window"] and not extra["included_in_page_daily_statistics"]
    assert "独立于所选范围" in extra["label"]


def test_vo2_old_points_are_only_historical_and_weight_has_no_vo2(repo):
    revision(repo, 1, "vo2_max_ml_kg_min", 42, event="2026-10-01T00:00:00Z")
    view = analyze_workspace(repo, "有氧", cutoff_time=CUTOFF, period="month")
    assert view["vo2"]["points"] == []
    assert view["vo2"]["latest_observations"][0]["normalized_value"] == 42
    assert view["vo2"]["latest_observations"][0]["scope"] == "historical_reference_outside_selected_window"
    assert "vo2" not in analyze_workspace(repo, "体重", cutoff_time=CUTOFF, period="month")


def test_footer_latest_dates_resolve_tombstones_type_date_changes_and_asof(repo):
    revision(repo, 1, "body_mass_kg", 70, table="body_measurement")
    revision(repo, 2, event="2026-10-01T00:00:00Z")
    first = latest_observation_dates(repo, cutoff_time=CUTOFF)
    assert first == {"body_measurement": "2026-11-18", "health_sample": "2026-10-01", "workout": None}
    revision(repo, 1, "body_mass_kg", 70, status="deleted", table="body_measurement")
    assert latest_observation_dates(repo, cutoff_time=CUTOFF)["body_measurement"] is None
    view = heart(repo)
    assert view["workspace_scope"]["latest_observed_at"] is None
    assert view["workspace_scope"]["latest_historical_observation_at"] == "2026-10-01T00:00:00Z"


def test_historical_weight_source_filter_selects_that_sources_latest(repo):
    revision(repo, 1, "body_mass_kg", 71, source="Synthetic A", event="2026-10-01T00:00:00Z")
    revision(repo, 2, "body_mass_kg", 81, source="Synthetic B", event="2026-10-15T00:00:00Z")
    view = analyze_workspace(repo, "体重", cutoff_time=CUTOFF, period="month", source_filter=["Synthetic A"])
    assert view["weight"]["daily"] == []
    assert view["weight"]["latest_observations"][0]["value"] == 71


def test_auto_cache_cross_minute_ttl_and_local_date(repo, monkeypatch):
    module = importlib.import_module("healthzip.analytics.workspaces")
    cache = importlib.import_module("healthzip.analytics.cache")
    clock = {"now": datetime.fromisoformat(CUTOFF), "elapsed": 1}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setattr(cache, "monotonic", lambda: clock["elapsed"])
    first = analyze_workspace(repo, "心率", period="month")
    clock["now"] = datetime.fromisoformat("2026-11-20T12:02:00+00:00")
    assert analyze_workspace(repo, "心率", period="month") == first
    clock["elapsed"] += 301
    second = analyze_workspace(repo, "心率", period="month")
    assert second["workspace_scope"]["cutoff_time"] != first["workspace_scope"]["cutoff_time"]
    clock["now"] = datetime.fromisoformat("2026-11-20T16:00:01+00:00")
    assert analyze_workspace(repo, "心率", period="month")["workspace_scope"]["cutoff_time"] != second["workspace_scope"]["cutoff_time"]


@pytest.mark.parametrize("entry", ["canonical", "complete"])
def test_full_analysis_auto_cache_retains_cutoff_until_ttl_revision_or_local_date(repo, monkeypatch, entry):
    canonical = importlib.import_module("healthzip.analytics.v13")
    complete = importlib.import_module("healthzip.analytics.core")
    cache = importlib.import_module("healthzip.analytics.cache")
    clock = {"now": datetime.fromisoformat(CUTOFF), "elapsed": 1}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    monkeypatch.setattr(canonical, "datetime", Clock)
    monkeypatch.setattr(complete, "datetime", Clock)
    monkeypatch.setattr(cache, "monotonic", lambda: clock["elapsed"])

    def read():
        return canonical.analyze(repo) if entry == "canonical" else complete.all_analysis(repo)["v13"]

    first = read()
    assert first["cutoff_time"] == CUTOFF
    clock["now"] = datetime.fromisoformat("2026-11-20T12:02:00+00:00")
    assert read() == first
    clock["elapsed"] += 301
    second = read()
    assert second["cutoff_time"] != first["cutoff_time"]
    revision(repo, 1)
    assert read()["data_hash"] != second["data_hash"]
    clock["now"] = datetime.fromisoformat("2026-11-20T16:00:01+00:00")
    assert read()["cutoff_time"] != second["cutoff_time"]


def test_full_analysis_explicit_cutoff_does_not_expire_with_automatic_clock(repo, monkeypatch):
    canonical = importlib.import_module("healthzip.analytics.v13")
    cache = importlib.import_module("healthzip.analytics.cache")
    clock = {"elapsed": 1}
    monkeypatch.setattr(cache, "monotonic", lambda: clock["elapsed"])
    first = canonical.analyze(repo, cutoff_time=CUTOFF)
    clock["elapsed"] += 301
    monkeypatch.setattr(canonical, "_analyze_uncached", lambda *a, **k: pytest.fail("explicit as-of view expired"))
    assert canonical.analyze(repo, cutoff_time=CUTOFF) == first
    assert first["cutoff_time"] == CUTOFF
    assert first["cache_policy"]["automatic_refresh_seconds"] is None


def test_same_key_concurrent_calls_merge_without_sharing_connections(repo):
    started = threading.Barrier(4)
    computed = []

    def request():
        local = Repository(repo.path)
        try:
            started.wait()

            def compute():
                computed.append(threading.get_ident())
                time.sleep(.03)
                return {"facts": [1, 2]}

            return cached(local, "synthetic", {}, compute, dependencies=[])
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: request(), range(4)))
    assert len(computed) == 1 and len(results) == 4
    results[0]["facts"].clear()
    assert results[1]["facts"] == [1, 2]


def test_current_partial_period_compares_same_elapsed_time_and_empty_training_not_counted(repo):
    summary = workspace_summary(repo, "总览", cutoff_time=CUTOFF)
    weekly, monthly = summary["periods"]
    assert weekly["comparison"]["window"]["end"] == "2026-11-13T12:00:00+00:00"
    assert monthly["comparison"]["window"]["end"] == "2026-10-20T12:00:00+00:00"
    service = TrainingService(repo)
    session = service.start_session("Synthetic empty")
    service.end_session(session["id"])
    current = workspace_summary(repo, "总览")
    assert not any(fact["label"] == "已完成训练" and fact["value"] > 0
                   for period in current["periods"] for fact in period["facts"])


def test_workout_scope_preserves_visible_revision_and_shared_range(repo):
    batch = repo.create_batch(file_sha256="synthetic", file_name="synthetic", file_size=0, xml_member_path="")
    identity, _ = repo.insert_workout(batch, {"fingerprint": "synthetic-workout", "activity_type": "HKWorkoutActivityTypeRunning",
        "start_utc": "2026-11-18T12:00:00Z", "end_utc": "2026-11-18T13:00:00Z", "duration_seconds": 3600,
        "energy_value": 200, "energy_unit": "kcal", "source_name": "Synthetic"})
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-19T00:00:00Z'")
    repo.conn.commit()
    view = scoped_workout_inventory(repo, period="month", cutoff_time=CUTOFF)
    assert len(view["rows"]) == 1 and view["rows"][0]["energy_kcal"] == 200
    repo.conn.execute("UPDATE workout SET record_status='deleted' WHERE id=?", (identity,))
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-19T01:00:00Z' WHERE revision_id=(SELECT MAX(revision_id) FROM source_revision)")
    repo.conn.commit()
    assert scoped_workout_inventory(repo, period="month", cutoff_time=CUTOFF)["rows"] == []
