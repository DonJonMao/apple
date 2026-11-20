"""Behavior coverage for the common factual detail page and optional explanation."""
from __future__ import annotations

import threading
import time
from datetime import date, timedelta

import pytest
from streamlit.testing.v1 import AppTest

from healthzip.ui.body_pages import daily_statistics, display_points, next_step_for, vo2_rows
from healthzip.ui.health_explanation import job_result, submit_job


def _view():
    return {"workspace_scope": {"workspace": "有氧", "timezone": "Asia/Shanghai",
        "window_start": "2026-11-01T00:00:00+08:00", "window_end": "2026-11-20T12:00:00+08:00",
        "cutoff_time": "2026-11-20T12:00:00+08:00", "metrics": {}},
        "vo2": {"points": [
            {"normalized_value": 42, "local_date": "2026-11-03", "source_name": "Synthetic Watch", "device": "a"},
            {"normalized_value": 44, "local_date": "2026-11-19", "source_name": "Synthetic Watch", "device": "a"}]},
        "weight": {"daily": [{"date": "2026-11-19", "kg": 70, "source": "Synthetic Scale"}]}}


def _app(renderer, view):
    app = AppTest.from_string(f"import streamlit as st\nfrom healthzip.ui.body_pages import {renderer}\n{renderer}(st.session_state['view'])")
    app.session_state["view"] = view
    return app.run()


def test_cardio_and_weight_have_independent_cards_and_details():
    view = _view()
    cardio = _app("render_cardio", view)
    weight = _app("render_weight", view)
    assert not cardio.exception and not weight.exception
    assert "44.0" in [item.value for item in cardio.metric]
    assert "70.0 kg" in [item.value for item in weight.metric]
    assert not any("体重" in item.label for item in cardio.metric)
    assert not any("VO₂" in item.label for item in weight.metric)
    for app in (cardio, weight):
        assert {item.label for item in app.expander} >= {"原始明细", "分析依据与范围"}
        assert all(not item.proto.expanded for item in app.expander)


def test_cardio_old_observation_is_only_a_dated_history_reference():
    view = _view()
    view["vo2"] = {"points": [], "latest_observations": [
        {"normalized_value": 38, "local_date": "2025-01-01", "source_name": "Synthetic Watch"}]}
    app = _app("render_cardio", view)
    assert not app.exception
    assert not app.metric and not app.get("plotly_chart")
    assert any("2025-01-01" in item.value and "历史参考不计入" in item.value for item in app.info)


def test_vo2_same_name_different_protocol_is_never_merged():
    view = _view()
    view["vo2"]["points"][1]["device"] = "b"
    rows = vo2_rows(view)
    assert len({item["来源"] for item in rows}) == 2
    statistics = daily_statistics(rows, "VO₂ max（mL/kg/min）")
    assert [item["change"] for item in statistics] == [None, None]
    assert sorted(item["mean"] for item in statistics) == [42, 44]


def test_sparse_chart_has_only_real_points_and_no_line_across_missing_dates():
    import json
    app = _app("render_cardio", _view())
    figure = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert figure["data"][0]["mode"] == "markers"
    assert [date.fromisoformat(value[:10]) for value in figure["data"][0]["x"]] == [date(2026, 11, 3), date(2026, 11, 19)]


def test_same_source_first_last_difference_is_not_a_previous_period_comparison():
    rows = [{"日期": "2026-11-01", "来源": "A", "v": 60},
            {"日期": "2026-11-20", "来源": "A", "v": 62},
            {"日期": "2026-11-20", "来源": "B", "v": 100}]
    result = daily_statistics(rows, "v")
    assert result[0]["mean"] == 61 and result[0]["change"] == 2
    assert result[0]["days"] == 2
    assert result[1]["change"] is None


def test_explanation_queue_returns_immediately_and_coalesces_identical_work():
    release, entered = threading.Event(), threading.Event()
    calls = []

    def slow():
        entered.set()
        release.wait(5)
        calls.append("done")
        return {"summary": "synthetic"}

    key = "synthetic-slow-" + str(time.monotonic_ns())
    began = time.monotonic()
    first = submit_job(key, slow)
    second = submit_job(key, slow)
    assert time.monotonic() - began < 0.2
    assert first is second and entered.wait(2)
    assert job_result(key)["status"] == "pending"
    release.set()
    assert first.result(timeout=2) == {"summary": "synthetic"}
    assert job_result(key)["status"] == "ready" and calls == ["done"]


def test_explanation_failure_is_retryable_and_does_not_expose_transport_details():
    def fail():
        raise RuntimeError("synthetic-secret-endpoint")

    key = "synthetic-fail-" + str(time.monotonic_ns())
    future = submit_job(key, fail)
    with pytest.raises(RuntimeError):
        future.result(timeout=2)
    assert job_result(key) == {"status": "failed"}


def test_same_day_vo2_first_last_respects_observation_order_not_value_sort():
    view = _view()
    view["vo2"]["points"][0].update(local_date="2026-11-19", normalized_value=44)
    view["vo2"]["points"][1].update(local_date="2026-11-19", normalized_value=42)
    statistics = daily_statistics(vo2_rows(view), "VO₂ max（mL/kg/min）")
    assert statistics[0]["first"] == 44 and statistics[0]["latest"] == 42
    assert statistics[0]["change"] == -2


def test_dense_chart_bound_preserves_brief_extreme_without_changing_statistics():
    rows = [{"日期": (date(2020, 1, 1) + timedelta(days=index)).isoformat(),
             "来源": "Synthetic", "v": 500 if index == 511 else 60 + index % 3}
            for index in range(1000)]
    before = daily_statistics(rows, "v")
    points = display_points(rows, "v", limit=100)
    assert len(points) <= 100 and rows[511] in points
    assert rows[0] in points and rows[-1] in points
    assert daily_statistics(rows, "v") == before and before[0]["count"] == 1000


def test_sleep_next_step_targets_actual_short_record_without_guessing_a_cause():
    rows = [{"日期": "2026-11-03", "来源": "Synthetic", "hours": 7},
            {"日期": "2026-11-09", "来源": "Synthetic", "hours": 4.5}]
    advice = next_step_for(daily_statistics(rows, "hours"), "sleep")
    assert "2026-11-09 的 4.5 小时" in advice and "是否覆盖整段睡眠" in advice
    assert "2026-11-03（7.0 小时）" in advice
    assert "导致" not in advice and "恢复不全" not in advice
