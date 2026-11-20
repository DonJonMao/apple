"""Scoped body workspaces preserve canonical values from real SQL snapshots."""

import pytest

from healthzip.analytics.v13 import analyze, metric_card
from healthzip.analytics.workspaces import analyze_workspace
from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService

CUTOFF = "2026-11-18T12:00:00+00:00"
LATER = "2026-11-20T12:00:00+00:00"


@pytest.fixture
def synthetic_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Repository(tmp_path / "synthetic.sqlite3")
    TrainingService(repo)
    batch = repo.create_batch(file_sha256="synthetic-workspace", file_name="synthetic",
                              file_size=0, xml_member_path="")
    ids = {}

    def add(name, canonical, value, unit, *, source="synthetic_a", start=None,
            end="2026-11-17T23:30:00+00:00", available="2026-11-18T01:00:00+00:00",
            category=None, raw_value=None, raw_unit=None):
        assert repo.insert_sample(batch, {"fingerprint": name, "raw_type": canonical,
            "canonical_type": canonical, "raw_value": str(value if raw_value is None else raw_value),
            "raw_unit": unit if raw_unit is None else raw_unit, "normalized_value": value,
            "normalized_unit": unit, "category_value": category, "start_utc": start or end,
            "end_utc": end, "local_date": end[:10], "source_name": source, "device": source,
            "metadata_json": '{"protocol_id":"synthetic-v1"}', "utc_offset_minutes": 480,
            "created_at": available})
        identifier = repo.one("SELECT id FROM health_sample WHERE fingerprint=?", (name,))[0]
        repo.conn.execute("UPDATE source_revision SET available_at=? "
                          "WHERE table_name='health_sample' AND record_id=?", (available, identifier))
        ids[name] = f"health_sample:{identifier}"
        return identifier

    rhr = add("rhr-a", "resting_heart_rate_bpm", 55, "bpm")
    add("rhr-b", "resting_heart_rate_bpm", 65, "bpm", source="synthetic_b")
    add("sdnn-a", "hrv_sdnn_ms", 30, "ms")
    add("sdnn-b", "hrv_sdnn_ms", 40, "ms", source="synthetic_b")
    add("late-sdnn", "hrv_sdnn_ms", 99, "ms", available="2026-11-19T01:00:00+00:00")
    add("weight-a", "body_mass_kg", 70, "kg")
    add("weight-b", "body_mass_kg", 80, "kg", source="synthetic_b", raw_value=180, raw_unit="lb")
    for name, source, hours in (("sleep-a", "synthetic_a", 3), ("sleep-b", "synthetic_b", 5)):
        add(name, "sleep_stage", None, "category", source=source,
            start=f"2026-11-17T{23-hours:02d}:00:00+00:00", end="2026-11-17T23:00:00+00:00",
            category="HKCategoryValueSleepAnalysisAsleep")
    add("inbed", "sleep_stage", None, "category", start="2026-11-17T15:00:00+00:00",
        category="HKCategoryValueSleepAnalysisInBed")
    add("vo2", "vo2_max_ml_kg_min", 42, "mL/(kg*min)")
    # This unrelated stream must not be calculated or appear in scoped audits.
    add("energy", "active_energy_kcal", 250, "kcal", start="2026-11-17T22:30:00+00:00")
    add("at-cutoff", "resting_heart_rate_bpm", 200, "bpm", end=CUTOFF,
        available="2026-11-18T11:00:00+00:00")
    repo.conn.execute("UPDATE health_sample SET normalized_value=75,raw_value='75' WHERE id=?", (rhr,))
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-19T02:00:00+00:00' "
                      "WHERE revision_id=(SELECT MAX(revision_id) FROM source_revision "
                      "WHERE table_name='health_sample' AND record_id=?)", (rhr,))
    repo.conn.commit()
    try:
        yield repo, ids
    finally:
        repo.close()


def stable_metric(metric):
    return {key: value for key, value in metric.items() if key != "computed_at"}


@pytest.mark.parametrize("workspace", ["心率 / HRV", "睡眠", "体重 / 有氧"])
def test_first_cold_workspace_result_is_reused_without_another_snapshot(tmp_path, monkeypatch, workspace):
    monkeypatch.chdir(tmp_path)
    repo = Repository(tmp_path / "cold-synthetic.sqlite3")
    try:
        assert repo.one("SELECT value FROM schema_meta WHERE key='training_service_initialization'") is None
        first = analyze_workspace(repo, workspace, cutoff_time=CUTOFF)
        # Browsing a body page must not initialize unrelated training seeds.
        assert repo.one("SELECT value FROM schema_meta WHERE key='training_service_initialization'") is None
        changes = repo.conn.total_changes
        calls = []
        original_rows = repo.rows

        def counted(sql, args=()):
            calls.append(sql)
            return original_rows(sql, args)

        monkeypatch.setattr(repo, "rows", counted)
        second = analyze_workspace(repo, workspace, cutoff_time=CUTOFF)
        assert second == first and not calls
        assert repo.conn.total_changes == changes and not repo.conn.in_transaction
    finally:
        repo.close()


@pytest.mark.parametrize("zone,day", [("Asia/Shanghai", "2026-11-18"),
                                       ("America/New_York", "2026-11-17")])
@pytest.mark.parametrize("workspace", ["心率 / HRV", "睡眠", "体重 / 有氧"])
def test_scoped_views_match_full_canonical_values_sources_units_and_dates(synthetic_repo, zone, day, workspace):
    repo, ids = synthetic_repo
    full = analyze(repo, cutoff_time=CUTOFF, timezone_name=zone, use_cache=False)
    changes = repo.conn.total_changes
    view = analyze_workspace(repo, workspace, cutoff_time=CUTOFF, timezone_name=zone)
    scope = view["workspace_scope"]
    assert "v13" not in view and scope["full_analysis"] is False
    assert scope["cutoff_time"] == full["cutoff_time"]
    assert scope["window_start"] == full["window_start"]
    assert scope["window_end"] == full["window_end"]
    assert scope["timezone"] == zone
    assert scope["audit_scope"] == "unrelated_source_and_context_inventory_not_included"
    assert repo.conn.total_changes == changes and not repo.conn.in_transaction
    for identity, metric in scope["metrics"].items():
        if identity not in {"REPORT-STATE-SUMMARY", "OBS-VO2-REPORTED"}:
            assert stable_metric(metric) == stable_metric(full["metrics"][identity])
        assert not identity.startswith(("STR-", "ENERGY-"))
        assert ids["energy"] not in metric["source_record_ids"]
    if workspace == "心率 / HRV":
        assert view["heart"]["cards"] == [metric_card(full["metrics"][identity])
                                            for identity in ("STATE-RHR", "STATE-SDNN")]
        metric = scope["metrics"]["STATE-RHR"]
        assert metric["source_record_ids"] == sorted([ids["rhr-a"], ids["rhr-b"]])
        assert sorted(item["value"] for stream in metric["value"].values() for item in stream) == [55, 65]
    elif workspace == "睡眠":
        assert view["sleep"]["card"] == metric_card(full["metrics"]["STATE-SLEEP-24H"])
        full_facts = [fact for fact in full["metrics"]["REPORT-STATE-SUMMARY"]["daily_facts"]
                      if fact.get("series_id") == "observed_sleep_by_wake_date"]
        assert scope["metrics"]["REPORT-STATE-SUMMARY"]["daily_facts"] == full_facts
        nights = view["sleep"]["nights"]
        assert sorted(night["sleep_hours"] for night in nights) == [3, 5]
        assert {night["date"] for night in nights} == {day}
        assert len({night["source"] for night in nights}) == 2
        assert {source for night in nights for source in night["source_ids"]} == {ids["sleep-a"], ids["sleep-b"]}
    else:
        assert view["weight"]["card"] == metric_card(full["metrics"]["BODY-MASS-TREND"])
        assert {point["date"] for point in view["weight"]["daily"]} == {day}
        assert sorted(point["kg"] for point in view["weight"]["daily"]) == pytest.approx([70, 180 * 0.45359237])
        assert len({point["source"] for point in view["weight"]["daily"]}) == 2
        assert [point["normalized_value"] for point in view["vo2"]["points"]] == [42]
        assert scope["vo2_scope"] == "latest_visible_revision_in_selected_window"
        assert view["vo2"]["metric"]["window"]["start"] == scope["window_start"]
    assert repo.one("SELECT COUNT(*) FROM analysis_run")[0] == 0
    assert repo.one("SELECT COUNT(*) FROM workflow_run")[0] == 0


def test_late_correction_preserves_prior_cutoff_and_new_view_updates(synthetic_repo):
    repo, ids = synthetic_repo
    earlier = analyze_workspace(repo, "心率 / HRV", cutoff_time=CUTOFF)
    later = analyze_workspace(repo, "心率 / HRV", cutoff_time=LATER)
    rhr = later["workspace_scope"]["metrics"]["STATE-RHR"]
    assert any(item["id"] == ids["rhr-a"] and item["value"] == 75 for item in rhr["numeric_provenance"])
    assert ids["late-sdnn"] in later["workspace_scope"]["metrics"]["STATE-SDNN"]["source_record_ids"]
    old = earlier["workspace_scope"]["metrics"]["STATE-RHR"]
    assert any(item["id"] == ids["rhr-a"] and item["value"] == 55 for item in old["numeric_provenance"])
    assert analyze_workspace(repo, "心率 / HRV", cutoff_time=CUTOFF) == earlier
    # A visible correction changes revision identity even for an explicit key.
    identifier = int(ids["rhr-b"].split(":")[1])
    repo.conn.execute("UPDATE health_sample SET normalized_value=67,raw_value='67' WHERE id=?", (identifier,))
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-18T02:00:00+00:00' "
                      "WHERE revision_id=(SELECT MAX(revision_id) FROM source_revision "
                      "WHERE table_name='health_sample' AND record_id=?)", (identifier,))
    repo.conn.commit()
    updated = analyze_workspace(repo, "心率 / HRV", cutoff_time=CUTOFF)
    assert any(item["id"] == ids["rhr-b"] and item["value"] == 67
               for item in updated["workspace_scope"]["metrics"]["STATE-RHR"]["numeric_provenance"])
    earlier["heart"]["cards"].clear()
    assert len(analyze_workspace(repo, "心率 / HRV", cutoff_time=CUTOFF)["heart"]["cards"]) == 2


def test_scoped_computation_does_not_commit_caller_edits_or_run_all_metrics(synthetic_repo, monkeypatch):
    import healthzip.analytics.v13 as canonical
    import healthzip.science as science

    repo, _ = synthetic_repo

    def unexpected(*args, **kwargs):
        raise AssertionError("unrelated full scientific pipeline must not execute")

    monkeypatch.setattr(science, "evaluate_all", unexpected)
    monkeypatch.setattr(canonical, "analyze", unexpected)
    monkeypatch.setattr(canonical, "persist", unexpected)
    repo.conn.execute("INSERT INTO schema_meta(key,value) VALUES('synthetic_pending','pending')")
    changes = repo.conn.total_changes
    analyze_workspace(repo, "心率 / HRV", cutoff_time=CUTOFF)
    assert repo.conn.in_transaction and repo.conn.total_changes == changes
    other = Repository(repo.path)
    try:
        assert other.one("SELECT value FROM schema_meta WHERE key='synthetic_pending'") is None
    finally:
        other.close()
        repo.conn.rollback()


def test_scoped_entry_validates_cutoff_timezone_and_workspace(synthetic_repo):
    repo, _ = synthetic_repo
    with pytest.raises(ValueError, match="timezone_required"):
        analyze_workspace(repo, "心率 / HRV", cutoff_time="2026-11-18T12:00:00")
    with pytest.raises(ValueError, match="unsupported_body_workspace"):
        analyze_workspace(repo, "力量", cutoff_time=CUTOFF)
