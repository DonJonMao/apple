"""Calendar reports use the actual training service and visible period controls."""
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService


def record_history(repo, observations):
    """A synthetic clock supplies coherent declaration/event/availability times."""
    svc = TrainingService(repo)
    equipment = svc.create_equipment("Synthetic period bar", "barbell")
    condition = {"equipment_instance_id": equipment["id"], "load_basis": "external_total_kg", "load_basis_confirmed": True,
        "side": "both", "repetition_semantics": "simultaneous", "rom_protocol": "declared_full",
        "settings": {"grip": "fixed"}, "settings_confirmed": True,
        "reference_protocol": {"protocol_id": "period-reference", "version": "1", "reference_policy_id": "first_work_set",
            "effort_protocol": "target_rir_2", "tempo": "controlled", "rest_protocol": "180-seconds"}}
    saved = []
    for date, load, reps in observations:
        start = datetime.fromisoformat(date)
        clock = [start]
        with patch("healthzip.training.service.timestamp", lambda value=None: timestamp(value or clock[0].isoformat())):
            session = svc.start_session("Synthetic calendar history", started_at=start.isoformat())
            instance = svc.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
            draft = svc.add_set(instance["id"], {"reference_set": True})
            clock[0] = start + timedelta(minutes=2)
            record = svc.edit_set(draft["set_uuid"], {"completion_state": "completed", "reps": reps,
                "load_value": load, "load_unit": "kg", "rir": 2, "quality_status": "acceptable", "pain_flag": False,
                "stop_reason": "target_rir", "started_at": (start+timedelta(minutes=1)).isoformat(),
                "ended_at": clock[0].isoformat()}, base_revision=draft["revision"])
            clock[0] = start + timedelta(hours=1)
            svc.end_session(session["id"], ended_at=clock[0].isoformat())
            saved.append(record)
    return saved


@pytest.mark.parametrize("period,label,n", [("week", "本周", 2), ("month", "本月", 3)])
def test_e2e06_visible_period_report_shows_its_own_load_layers(tmp_path, period, label, n):
    from streamlit.testing.v1 import AppTest

    path = tmp_path / "calendar-report.sqlite3"
    repo = Repository(path)
    records = record_history(repo, [
        ("2026-10-26T09:00:00+00:00", 30, 99),  # Outside the month.
        ("2026-11-12T09:00:00+00:00", 30, 10),
        ("2026-11-12T18:00:00+00:00", 32.5, 8),
        ("2026-11-16T09:00:00+00:00", 30, 12),
        ("2026-11-16T18:00:00+00:00", 32.5, 10),
        ("2026-11-18T09:00:00+00:00", 30, 11),
        ("2026-11-18T18:00:00+00:00", 32.5, 9),
        ("2026-11-20T09:00:00+00:00", 30, 99),  # After the report cutoff.
    ])
    repo.close()
    cutoff = "2026-11-19T12:00:00+00:00"
    script = ("from healthzip.db.repository import Repository\n"
              "from healthzip.analytics.v13 import analyze\n"
              "from healthzip.ui.analysis_page import render_analysis\n"
              f"repo=Repository({str(path)!r})\n"
              f"render_analysis(repo, {{'v13': analyze(repo, cutoff_time={cutoff!r}, timezone_name='UTC')}})\n"
              "repo.close()")
    app = AppTest.from_string(script).run(timeout=30)
    next(s for s in app.selectbox if s.label == "复盘周期").set_value(label)
    next(b for b in app.button if b.label == "生成当前周期复盘").click().run(timeout=30)
    assert not app.exception and not app.error
    section = next(e for e in app.expander if e.label == "本周 / 本月复盘")
    tables = [item.value for item in section.dataframe if "来源记录数" in item.value.columns]
    assert len(tables) == 1, "The period section must show its own comparable load layers."
    shown = tables[0].sort_values("负荷")
    assert shown["负荷"].tolist() == [30, 32.5]
    assert shown["单位"].tolist() == ["kg", "kg"]
    assert shown["有效参考"].tolist() == shown["来源记录数"].tolist() == [n, n]
    assert shown["变化单位"].tolist() == ["repetitions/day", "repetitions/day"]
    assert shown["停滞判断"].tolist() == ["尚不能确认", "尚不能确认"]
    repo = Repository(path)
    saved = [json.loads(r[0]) for r in repo.rows("SELECT result_json FROM analysis_run")]
    report = next(r for r in saved if r["period"] == period)
    assert report["cutoff_time"] == cutoff
    assert report["window_start"] == ("2026-11-16T00:00:00+00:00" if period == "week" else "2026-11-01T00:00:00+00:00")
    series = report["strength_tasks"][0]["metrics"]["STR-19"]["series_results"]
    expected = records[3:7] if period == "week" else records[1:7]
    assert {rid for s in series for rid in s["source_record_ids"]} == {"strength_set:" + r["set_uuid"] for r in expected}
    for index, layer in enumerate(sorted(series, key=lambda s: s["normalized_load"])):
        assert shown.iloc[index]["观察起点"] == layer["first_observed_at"]
        assert shown.iloc[index]["观察终点"] == layer["last_observed_at"]
        assert shown.iloc[index]["每日变化"] == pytest.approx(layer["metric"]["value"]["slope_per_day"])
    repo.close()


def test_recorded_frequency_counts_local_observation_dates(tmp_path):
    repo = Repository(tmp_path / "local-frequency.sqlite3")
    record_history(repo, [("2026-11-18T00:30:00+08:00", 30, 10), ("2026-11-18T23:30:00+08:00", 30, 12)])
    result = analyze(repo, cutoff_time="2026-11-19T12:00:00+08:00", timezone_name="Asia/Shanghai", period="week")
    for metric in ("STR-07", "STR-08"):
        value = result["metrics"][metric]["value"]
        assert value["sessions"] == 2
        assert value["observed_dates"] == 1
        assert value["recorded_frequency_per_week"] is None
    repo.close()


def test_interval_without_look_keeps_observed_point_estimate(tmp_path):
    repo = Repository(tmp_path / "point-estimate.sqlite3")
    record_history(repo, [("2026-11-16T09:00:00+00:00", 30, 10), ("2026-11-17T09:00:00+00:00", 30, 12),
                         ("2026-11-18T09:00:00+00:00", 30, 11)])
    result = analyze(repo, cutoff_time="2026-11-19T12:00:00+00:00", timezone_name="UTC", period="week")
    metric = result["metrics"]["STR-20"]
    assert metric["value"] is None and metric["uncertainty"]["kind"] == "not_estimated"
    assert metric["point_estimate"]["slope_per_day"] == pytest.approx(.5)
    assert metric["point_estimate"]["change"] == pytest.approx(1)
    assert metric["point_estimate"]["unit"] == "repetitions"
    assert metric["point_estimate"]["span_days"] == 2
    assert metric["data_status"] == "insufficient"
    assert metric["series_results"][0]["metric"]["point_estimate"] == metric["point_estimate"]
    repo.close()
