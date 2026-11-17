"""W2–W5 positive repository/page cases with hand-checkable observations."""
import json
import runpy
from pathlib import Path

import pytest

from healthzip.db.repository import Repository
from healthzip.workflows import WorkflowRequest, load_analysis, run_workflow
from healthzip.workflows.calendar import completed_periods

PAGE = runpy.run_path(str(Path(__file__).with_name("test_analysis_workflow_page.py")))
CUTOFF = "2026-11-17T00:00:00+00:00"
TYPES = {
    "vo2_max_ml_kg_min": ("HKQuantityTypeIdentifierVO2Max", "mL/kg/min"),
    "body_mass_kg": ("HKQuantityTypeIdentifierBodyMass", "kg"),
    "resting_heart_rate_bpm": ("HKQuantityTypeIdentifierRestingHeartRate", "count/min"),
    "hrv_sdnn_ms": ("HKQuantityTypeIdentifierHeartRateVariabilitySDNN", "ms"),
    "basal_energy_kcal": ("HKQuantityTypeIdentifierBasalEnergyBurned", "kcal"),
    "active_energy_kcal": ("HKQuantityTypeIdentifierActiveEnergyBurned", "kcal"),
}


def sample(repo, batch, key, canonical, value, start, end=None, *, version="1", protocol="synthetic-v1"):
    raw, unit = TYPES[canonical]
    assert repo.insert_sample(batch, {"fingerprint": key, "source_record_id": key,
        "raw_type": raw, "canonical_type": canonical, "raw_value": str(value), "raw_unit": unit,
        "start_utc": start, "end_utc": end or start, "source_name": "Synthetic source",
        "device": "Synthetic device", "source_version": version,
        "metadata_json": json.dumps({"protocol_id": protocol}), "created_at": "2026-11-16T23:00:00+00:00"})


def batch(repo):
    return repo.create_batch(file_sha256="synthetic-only", file_name="synthetic", file_size=1, xml_member_path="synthetic.xml")


def visible(repo):
    # Explicit synthetic ingestion time; never applied to a real private DB.
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-16T23:00:00+00:00'")
    repo.conn.commit()


def test_w3_single_unknown_and_known_segmented_estimates_reach_page(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Repository(tmp_path / "vo2.sqlite3")
    bid = batch(repo)
    for key, value, day, version, protocol in (
        ("a", 40, 10, "1", "synthetic-v1"), ("b", 42, 11, "1", "synthetic-v1"),
        ("c", 47, 12, "2", "synthetic-v1"), ("d", 48, 13, "2", None),
        ("e", 49, 14, "2", None),
    ):
        sample(repo, bid, key, "vo2_max_ml_kg_min", value, f"2026-11-{day}T08:00:00+00:00", version=version, protocol=protocol)
    visible(repo)
    run = run_workflow(repo, WorkflowRequest("W3", cutoff_time=CUTOFF, timezone="UTC"), knowledge_root=tmp_path / "missing")
    segments = run["supplements"]["vo2_segments"]
    assert sorted(s["n"] for s in segments) == [1, 2, 2]
    assert [s["recorded_difference"] for s in segments if s["source_version"] == "1"] == [2]
    assert all(s["recorded_difference"] is None for s in segments if s["source_version"] == "2")
    assert run["nodes"][2]["truth"] is True
    path = repo.path
    repo.close()
    app = PAGE["open_workflow"](path)
    app.selectbox(key="workflow_kind").select("W3").run()
    app.text_input(key="workflow_cutoff").set_value(CUTOFF)
    app.button(key="workflow_run").click().run(timeout=30)
    assert not app.exception and not app.error
    assert app.get("plotly_chart")
    app.button(key="workflow_resume").click().run(timeout=30)
    assert not app.exception and not app.error


def test_w5_four_of_seven_complete_days_do_not_infer_intake_or_fill_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Repository(tmp_path / "energy.sqlite3")
    bid = batch(repo)
    for day in (10, 12, 14, 15):
        for kind, amount in (("basal", 1500), ("active", 500)):
            sample(repo, bid, f"{kind}{day}", kind+"_energy_kcal", amount,
                f"2026-11-{day}T00:00:00+00:00", f"2026-11-{day+1}T00:00:00+00:00")
    for day, value in ((10, 80), (15, 79)):
        sample(repo, bid, f"mass{day}", "body_mass_kg", value, f"2026-11-{day}T08:00:00+00:00")
    # A separate workout summary is already part of device active energy and
    # must not be added to the device total by the workflow.
    repo.conn.execute("INSERT INTO workout(fingerprint,import_batch_id,activity_type,start_utc,end_utc,energy_value,energy_unit,source_name) VALUES(?,?,?,?,?,?,?,?)",
        ("synthetic-workout", bid, "synthetic", "2026-11-12T12:00:00+00:00", "2026-11-12T13:00:00+00:00", 300, "kcal", "Synthetic source"))
    visible(repo)
    run = run_workflow(repo, WorkflowRequest("W5", cutoff_time=CUTOFF, timezone="UTC", window_days=7), knowledge_root=tmp_path / "missing")
    row = run["supplements"]["energy_coverage"][0]
    assert (row["complete_days"], row["window_days"], row["mean_kcal_per_complete_day"]) == (4, 7, 2000)
    metrics = load_analysis(repo, run["run_id"])["metrics"]
    assert metrics["ENERGY-DEVICE-TOTAL"]["value"][0]["device_total_kcal"] == 8000
    assert metrics["ENERGY-IDENTIFIABILITY"]["data_status"] == "not_identifiable"
    assert run["candidate_ids"] == []
    path = repo.path
    repo.close()
    app = PAGE["open_workflow"](path)
    app.selectbox(key="workflow_kind").select("W5").run()
    app.text_input(key="workflow_cutoff").set_value(CUTOFF)
    app.number_input(key="workflow_days").set_value(7)
    app.session_state["analysis_timezone"] = "UTC"
    app.button(key="workflow_run").click().run(timeout=30)
    assert not app.exception and not app.error
    assert any("完整能量日 4/7" in str(item.value) for item in app.markdown)


@pytest.mark.parametrize("period,expected", [
    ("week", [("2026-11-02", "2026-11-09"), ("2026-11-09", "2026-11-16")]),
    ("month", [("2026-09-01", "2026-10-01"), ("2026-10-01", "2026-11-01")]),
])
def test_w4_complete_period_bounds_are_calendar_based(period, expected):
    assert [(start[:10], end[:10]) for start, end in completed_periods(CUTOFF, "Asia/Shanghai", period)] == expected


def test_w4_selected_mass_outcome_previous_complete_weeks_and_partial_current(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Repository(tmp_path / "calendar.sqlite3")
    bid = batch(repo)
    for day, value in ((3, 80), (6, 79.5), (10, 79), (13, 78.5), (16, 78)):
        sample(repo, bid, str(day), "body_mass_kg", value, f"2026-11-{day:02}T08:00:00+00:00")
    visible(repo)
    run = run_workflow(repo, WorkflowRequest("W4", cutoff_time=CUTOFF, timezone="UTC", period="week",
        result_metric_id="BODY-MASS-DAILY"), knowledge_root=tmp_path / "missing")
    comparison = run["supplements"]["calendar_comparison"]
    assert comparison["metric_id"] == "BODY-MASS-DAILY"
    assert [p["metric"]["valid_n"] for p in comparison["periods"]] == [2, 2]
    assert load_analysis(repo, run["run_id"])["metrics"]["BODY-MASS-DAILY"]["valid_n"] == 4
    assert run["supplements"]["partial_current_period"]["metric"]["valid_n"] == 1
    path = repo.path
    repo.close()
    app = PAGE["open_workflow"](path)
    app.selectbox(key="workflow_kind").select("W4").run()
    app.selectbox(key="workflow_period").select("week")
    app.text_input(key="workflow_cutoff").set_value(CUTOFF)
    app.button(key="workflow_run").click().run(timeout=30)
    assert not app.exception and not app.error
    assert any("前两个完整日历周期" in str(item.value) for item in app.markdown)
