"""Preserve reported interval RIR through persistence, science and the real UI."""

import ast
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from healthzip.analytics.v13 import snapshot
from healthzip.db.repository import Repository
from healthzip.science import evaluate
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService

START = "2026-11-01T00:00:00+00:00"
CUTOFF = "2026-11-19T12:00:00+00:00"


def record_effort(repo, *, rir=3, qualifier="at_least", rpe=9, scale="rir_rpe10"):
    """A synthetic clock keeps all real Service event/availability times coherent."""
    start = datetime.fromisoformat("2026-11-18T09:00:00+00:00")
    clock = [start]
    svc = TrainingService(repo)
    with patch("healthzip.training.service.timestamp", lambda value=None: timestamp(value or clock[0].isoformat())):
        session = svc.start_session("Synthetic interval effort", started_at=start.isoformat())
        instance = svc.add_exercise(session["id"], "psa.ex.barbell_bench_press", {})
        clock[0] = start + timedelta(minutes=2)
        saved = svc.add_set(instance["id"], {
            "completion_state": "completed", "reps": 8, "rir": rir,
            "rir_qualifier": qualifier, "rpe": rpe, "rpe_scale": scale,
            "started_at": (start + timedelta(minutes=1)).isoformat(),
            "ended_at": clock[0].isoformat(),
        })
        clock[0] = start + timedelta(hours=1)
        svc.end_session(session["id"], ended_at=clock[0].isoformat())
    return saved


def test_service_snapshot_preserves_interval_rir_over_conflicting_rpe(tmp_path):
    repo = Repository(tmp_path / "interval.sqlite3")
    try:
        saved = record_effort(repo)
        records, context = snapshot(repo, CUTOFF)
        original = next(r for r in records if r.get("set_uuid") == saved["set_uuid"])
        assert original["rir"] == 3 and original["rir_qualifier"] == "at_least"
        metric = evaluate("STR-10", records, cutoff_time=CUTOFF, window_start=START,
                          window_end=CUTOFF, context=context)
        observed = metric["value"][0]
        assert observed["rir_interval"] == {"lower": 3, "upper": None}
        assert observed["original_rpe"] == 9
        assert observed["scale_type"] == "rir_based_rpe_6_10"
        assert observed["rir"] is None, "A reported lower bound cannot become an exact RPE-derived RIR."
        assert observed["converted"] is False
        assert metric["valid_n"] == 0
        assert metric["source_record_ids"] == ["strength_set:" + saved["set_uuid"]]
        persisted = TrainingService(repo).get_set(saved["set_uuid"])
        assert persisted["rir"] == 3 and persisted["rpe"] == 9
    finally:
        repo.close()


@pytest.mark.parametrize("rir,qualifier,rpe,scale,expected,converted", [
    (3, "exact", 9, "rir_rpe10", 3, False),
    (None, None, 9, "rir_rpe10", 1, True),
    (None, None, 9, "cr10", None, False),
    (None, None, 9, "borg6_20", None, False),
    (None, None, 5, "rir_rpe10", None, False),
])
def test_service_keeps_direct_rir_and_only_maps_declared_scale_when_absent(
        tmp_path, rir, qualifier, rpe, scale, expected, converted):
    repo = Repository(tmp_path / "effort.sqlite3")
    try:
        record_effort(repo, rir=rir, qualifier=qualifier, rpe=rpe, scale=scale)
        records, context = snapshot(repo, CUTOFF)
        metric = evaluate("STR-10", records, cutoff_time=CUTOFF, window_start=START,
                          window_end=CUTOFF, context=context)
        observed = metric["value"][0]
        assert observed["rir"] == expected and observed["converted"] is converted
        assert observed["original_rpe"] == rpe
    finally:
        repo.close()


@pytest.mark.parametrize("direct,interval", [
    (None, {"lower": 3, "upper": None}),
    (None, {"lower": 2, "upper": 4}),
    (None, {}),
    ("invalid-direct-observation", None),
])
def test_existing_interval_or_invalid_direct_rir_is_not_missing(direct, interval):
    row = {"id": "synthetic-interval", "event_end": "2026-11-18T09:00:00+00:00",
           "available_at": "2026-11-18T09:01:00+00:00", "rir": direct,
           "rir_interval": interval, "rpe": 9, "scale_type": "rir_based_rpe_6_10"}
    observed = evaluate("STR-10", [row], cutoff_time=CUTOFF, window_start=START,
                        window_end=CUTOFF)["value"][0]
    assert observed["rir"] is None and observed["converted"] is False
    assert observed["rir_interval"] == interval and observed["original_rpe"] == 9


def test_actual_analysis_page_keeps_reported_interval_and_original_rpe(tmp_path):
    from streamlit.testing.v1 import AppTest

    path = tmp_path / "interval-ui.sqlite3"
    repo = Repository(path)
    record_effort(repo)
    repo.close()
    script = ("from healthzip.db.repository import Repository\n"
              "from healthzip.analytics.v13 import analyze\n"
              "from healthzip.ui.analysis_page import render_analysis\n"
              f"repo=Repository({str(path)!r})\n"
              f"render_analysis(repo, {{'v13': analyze(repo, cutoff_time={CUTOFF!r}, timezone_name='UTC', use_cache=False)}})\n"
              "repo.close()")
    app = AppTest.from_string(script).run(timeout=30)
    assert not app.exception and not app.error
    table = next(t.value for t in app.dataframe
                 if "指标" in t.value.columns and "逐组RIR与RPE" in t.value["指标"].values)
    displayed = ast.literal_eval(table.loc[table["指标"] == "逐组RIR与RPE", "结果"].iloc[0])[0]
    assert displayed["rir_interval"] == {"lower": 3, "upper": None}
    assert displayed["original_rpe"] == 9
    assert displayed["rir"] is None and displayed["converted"] is False
    full = next(json.loads(item.value) for item in app.json
                if json.loads(item.value).get("metric_id") == "STR-10")
    assert full["value"] == [displayed]
