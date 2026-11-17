"""Saved tasks survive navigation; selected outcomes drive the visible review."""
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from healthzip.db.repository import Repository
from healthzip.workflows import (
    WorkflowRequest,
    check_current_use,
    load_analysis,
    load_run,
    run_workflow,
    save_context,
)

PAGE = runpy.run_path(str(Path(__file__).with_name("test_analysis_workflow_page.py")))
OBS = runpy.run_path(str(Path(__file__).with_name("test_analysis_observation_flows.py")))


@pytest.mark.parametrize("wid,canonical,metric_id", [
    ("W2", "resting_heart_rate_bpm", "STATE-RHR"),
    ("W3", "vo2_max_ml_kg_min", "OBS-VO2-REPORTED"),
    ("W4", "resting_heart_rate_bpm", "STATE-RHR"),
    ("W5", "body_mass_kg", "BODY-MASS-DAILY"),
])
def test_reopen_supplement_and_resume_preserves_saved_task(tmp_path, monkeypatch, wid, canonical, metric_id):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "saved-task.sqlite3"
    repo = Repository(path)
    bid = OBS["batch"](repo)
    now = datetime.now(timezone.utc)
    for days, value in ((4, 60), (2, 62)):
        OBS["sample"](repo, bid, str(days), canonical, value, (now-timedelta(days=days)).isoformat())
    repo.conn.commit()
    context = save_context(repo, {"population": "healthy_adults"})
    first = run_workflow(repo, WorkflowRequest(wid, timezone="UTC", window_days=7, context_id=context,
        result_metric_id="STATE-RHR" if wid == "W4" else None), knowledge_root=tmp_path / "missing")
    assert load_analysis(repo, first["run_id"])["metrics" if wid != "W3" else "observations"][metric_id]["valid_n"] == 2
    repo.close()
    # Reopen from saved history with a fresh page, whose new-task controls use
    # default 30 days/Asia-Shanghai/unknown population and W4 body mass.
    app = PAGE["open_workflow"](path)
    app.selectbox(key="workflow_kind").select(wid).run()
    app.selectbox(key="workflow_history_" + wid).select(first["run_id"]).run()
    app.button(key="workflow_open_run").click().run(timeout=30)
    if wid == "W4":
        charts = [json.loads(chart.proto.spec) for chart in app.get("plotly_chart")]
        assert any(chart["layout"]["title"]["text"] == "静息心率每日代表值" for chart in charts)
    repo = Repository(path)
    OBS["sample"](repo, bid, "new", canonical, 64, (now-timedelta(days=1)).isoformat())
    repo.conn.commit()
    repo.close()
    app.button(key="workflow_resume").click().run(timeout=30)
    assert not app.error and not app.exception
    repo = Repository(path)
    successor = load_run(repo, app.session_state["workflow_run_" + str(path.resolve()) + "_" + wid])
    assert successor["parent_run_id"] == first["run_id"]
    for field in ("timezone", "window_days", "baseline_days", "period", "context_id", "result_metric_id", "mode"):
        assert successor["request"][field] == first["request"][field]
    metrics = load_analysis(repo, successor["run_id"])["metrics" if wid != "W3" else "observations"]
    assert metrics[metric_id]["valid_n"] == 3
    assert load_run(repo, first["run_id"]) == first
    repo.close()


@pytest.mark.parametrize("metric_id,canonical", [("STATE-RHR", "resting_heart_rate_bpm"), ("STATE-SDNN", "hrv_sdnn_ms"), ("BODY-MASS-DAILY", "body_mass_kg")])
def test_non_strength_outcome_does_not_borrow_strength_no_improvement(tmp_path, monkeypatch, metric_id, canonical):
    history = runpy.run_path(str(Path(__file__).with_name("test_analysis_w1_flow.py")))["history"]
    repo, _, _, _, _ = history(tmp_path, monkeypatch, approved=False)
    result = run_workflow(repo, WorkflowRequest("W4", result_metric_id=metric_id), knowledge_root=tmp_path / "missing")
    assert result["nodes"][2]["truth"] is None
    assert result["nodes"][2]["long_term_review_trigger"] is False
    assert result["nodes"][3]["branch"] == "ordinary_review"
    assert result["nodes"][2]["metric_refs"] == [metric_id]
    assert not result["dependencies"]["session_hashes"] and not result["dependencies"]["outcome_hashes"]
    bid = OBS["batch"](repo)
    now = datetime.now(timezone.utc)
    for days, value in ((4, 60), (2, 62)):
        OBS["sample"](repo, bid, str(days), canonical, value, (now-timedelta(days=days)).isoformat())
    repo.conn.commit()
    positive = run_workflow(repo, WorkflowRequest("W4", result_metric_id=metric_id), knowledge_root=tmp_path / "missing")
    assert positive["nodes"][2]["truth"] is True
    assert positive["nodes"][2]["long_term_review_trigger"] is False
    assert [f["metric_id"] for f in positive["facts"]] == [metric_id]
    assert check_current_use(repo, positive["run_id"], knowledge_root=tmp_path / "missing")["status"] == "current"
    repo.close()


@pytest.mark.parametrize("current", [True, False])
def test_w2_explicit_completed_day_baseline_independent_of_display(tmp_path, monkeypatch, current):
    monkeypatch.chdir(tmp_path)
    repo = Repository(tmp_path / "baseline.sqlite3")
    bid = OBS["batch"](repo)
    for day, value in ((13, 300), (14, 60), (15, 60), (16, 60), *(((17, 80),) if current else ())):
        OBS["sample"](repo, bid, str(day), "resting_heart_rate_bpm", value, f"2026-11-{day}T08:00:00+00:00")
    OBS["visible"](repo)
    saved = []
    for days in (1, 30):
        result = run_workflow(repo, WorkflowRequest("W2", cutoff_time="2026-11-17T12:00:00+00:00", timezone="UTC", window_days=days, baseline_days=3), knowledge_root=tmp_path / "missing")
        metric = load_analysis(repo, result["run_id"])["metrics"]["STATE-DEVIATION"]
        value = metric["value"]["streams"][0]
        assert value["baseline_daily_n"] == 3 and value["baseline_median"] == 60
        assert value["baseline_dates"] == ["2026-11-14", "2026-11-15", "2026-11-16"]
        assert value["absolute_deviation"] == (20 if current else None)
        assert value["robust_z"] is None
        assert value["reference_window"]["end"] == "2026-11-17T00:00:00+00:00"
        assert metric["window"]["start"] == "2026-11-14T00:00:00+00:00"
        assert metric["parameter_set_id"] == "completed-local-days-1.6.1:3"
        assert result["dependencies"]["record_hashes"]
        saved.append(value)
    assert saved[0] == saved[1]
    repo.close()
