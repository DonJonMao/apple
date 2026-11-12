"""Calendar review renders its own observed work and original plan denominator."""
from contextlib import closing
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService

CUTOFF = "2026-11-12T12:00:00+00:00"


def record_session(repo, day, *, draft_only=False, extra=False, load=30):
    clock = [datetime.fromisoformat(day + "T08:00:00+00:00")]
    with patch("healthzip.training.service.timestamp", lambda value=None: timestamp(value or clock[0].isoformat())):
        svc = TrainingService(repo)
        target = {"load_value": load, "load_unit": "kg", "load_basis": "external_total_kg", "reps_min": 8, "reps_max": 10, "rir": 2}
        template = svc.create_template("Synthetic period plan", [{"exercise_id": "psa.ex.barbell_bench_press",
            "condition": {"load_basis": "external_total_kg", "load_basis_confirmed": True}, "targets": {"sets": [target] * 4}}])
        session = svc.start_session(template_id=template["id"])
        if not draft_only:
            clock[0] += timedelta(minutes=1)
            actual = {"completion_state": "completed", "reps": 8, "rir": 2, "load_value": load,
                      "load_unit": "kg", "started_at": clock[0].isoformat(), "ended_at": clock[0].isoformat()}
            svc.edit_set(session["sets"][0]["set_uuid"], actual, base_revision=session["sets"][0]["revision"])
            svc.edit_set(session["sets"][1]["set_uuid"], {"completion_state": "skipped"}, base_revision=session["sets"][1]["revision"])
            if extra:
                svc.add_set(session["exercises"][0]["id"], actual)
            svc.end_session(session["id"])


def render(path, label):
    app = AppTest.from_string(
        "from healthzip.db.repository import Repository\n"
        "from healthzip.analytics.v13 import analyze\n"
        "from healthzip.ui.analysis_page import render_analysis\n"
        f"repo=Repository({str(path)!r})\n"
        f"render_analysis(repo, {{'v13': analyze(repo, window_days=30, cutoff_time={CUTOFF!r}, timezone_name='UTC')}})\n"
        "repo.close()"
    ).run(timeout=30)
    next(x for x in app.selectbox if x.label == "复盘周期").set_value(label)
    next(x for x in app.button if x.label == "生成当前周期复盘").click().run(timeout=30)
    assert not app.exception and not app.error
    return next(x for x in app.expander if x.label == "本周 / 本月复盘")


def table(section, column):
    matches = [x.value for x in section.dataframe if column in x.value.columns]
    assert len(matches) == 1
    return matches[0]


@pytest.mark.parametrize("period,label,planned,done,skipped,unknown,work", [
    ("week", "本周", 8, 2, 2, 4, 3), ("month", "本月", 12, 3, 3, 6, 4)])
def test_period_execution_uses_calendar_counts_and_preserves_mixed_loads(tmp_path, monkeypatch, period, label, planned, done, skipped, unknown, work):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "synthetic-period-facts.sqlite3"
    with closing(Repository(path)) as repo:
        for index, day in enumerate(("2026-10-31", "2026-11-01", "2026-11-09", "2026-11-10")):
            record_session(repo, day, load=30 if index % 2 == 0 else 32.5, extra=index == 3)
        computed = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", period=period)
        rolling = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", window_days=30)
        assert rolling["metrics"]["STR-09"]["value"]["planned"] == 16
    section = render(path, label)
    shown = table(section, "已完成计划组").iloc[0]
    assert [shown[k] for k in ("原计划组数", "已完成计划组", "已跳过计划组", "尚未确认完成的计划组", "额外完成组")] == [planned, done, skipped, unknown, 1]
    assert shown["已完成占原计划"] == done / planned
    assert table(section, "已记录完成工作组").iloc[0]["已记录完成工作组"] == work
    endpoints = table(section, "目标项").set_index("目标项")
    assert endpoints.loc["负荷", "有明确目标组数"] == planned
    assert endpoints.loc["负荷", "已满足"] == done
    assert endpoints.loc["负荷", "未满足"] == skipped
    assert endpoints.loc["负荷", "尚不能判断"] == unknown
    assert any(computed["window_start"] in x.value for x in section.caption)
    assert any("不同负荷" in x.value and "能力" in x.value for x in section.caption)


@pytest.mark.parametrize("draft_only", [False, True])
def test_period_empty_or_only_drafts_never_invents_completed_work(tmp_path, monkeypatch, draft_only):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "synthetic-empty-period.sqlite3"
    with closing(Repository(path)) as repo:
        if draft_only:
            record_session(repo, "2026-11-10", draft_only=True)
    section = render(path, "本周")
    if draft_only:
        shown = table(section, "已完成计划组").iloc[0]
        assert shown["原计划组数"] == shown["尚未确认完成的计划组"] == 4
        assert shown["已完成计划组"] == shown["已跳过计划组"] == 0
    else:
        assert not any("原计划组数" in x.value.columns for x in section.dataframe)
        assert any("未记录本周期的冻结计划" in x.value for x in section.info)
    assert any("不代表没有训练" in x.value for x in section.info)
    assert not any("已记录完成工作组" in x.value.columns for x in section.dataframe)
