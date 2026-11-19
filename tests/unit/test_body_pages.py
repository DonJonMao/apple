"""Daily body tables remain readable without changing scientific snapshots."""

import copy
import json

import pytest
from streamlit.testing.v1 import AppTest

from healthzip.ui.body_pages import (
    heart_rows,
    latest_weight_rows,
    sleep_rows,
    sleep_summary,
    source_name,
    weight_rows,
)


@pytest.fixture
def view():
    first = str(("我的 Apple Watch", "private-device-a", "protocol-a", "1"))
    second = str(("体脂秤", "private-device-b", "protocol-b", "1"))
    return {"workspace_scope": {"window_start": "2026-10-19T12:00:00+00:00",
        "window_end": "2026-11-18T12:00:00+00:00", "cutoff_time": "2026-11-18T12:00:00+00:00",
        "timezone": "Asia/Shanghai", "metrics": {
            "STATE-RHR": {"algorithm_version": "synthetic-v1", "value": {
                first: [{"date": "2026-11-17", "value": 55}],
                second: [{"date": "2026-11-17", "value": 65}]}},
            "STATE-SDNN": {"algorithm_version": "synthetic-v1", "value": {
                first: [{"date": "2026-11-17", "value": 30}]}}}},
        "sleep": {"nights": [{"date": "2026-11-17", "sleep_hours": 7.5,
            "source": first, "source_ids": ["private-record"], "series_id": "internal-series"}]},
        "weight": {"daily": [{"date": "2026-11-17", "kg": 70, "source": second,
            "source_ids": ["private-record"]}]},
        "vo2": {"points": [{"local_date": "2026-11-17", "normalized_value": 42,
            "source_name": "我的 Apple Watch"}]}}


def test_heart_tables_use_chinese_metrics_units_and_readable_source_names(view):
    rows = heart_rows(view)
    assert sorted(row["数值"] for row in rows) == [30, 55, 65]
    assert {row["指标"] for row in rows} == {"静息心率", "HRV（SDNN）"}
    assert {row["单位"] for row in rows} == {"次/分", "毫秒"}
    assert {row["来源"] for row in rows} == {"我的 Apple Watch", "体脂秤"}
    assert all(set(row) == {"日期", "指标", "数值", "单位", "来源"} for row in rows)
    assert source_name("('unknown_source:health_sample:123', None, None, None)") == "来源未注明"


def test_sleep_omits_zero_negative_missing_and_nonfinite_only_from_display_statistics(view):
    source = view["sleep"]["nights"][0]["source"]
    view["sleep"]["nights"] = [{"date": "2026-11-17", "sleep_hours": value, "source": source}
                                for value in (3, 5, 0, -1, None, float("nan"), float("inf"))]
    before = json.dumps(view, sort_keys=True)
    assert [row["睡眠时长（小时）"] for row in sleep_rows(view)] == [3, 5]
    assert sleep_summary(view) == [{"来源": "我的 Apple Watch", "有效记录日期": 1,
                                   "有效记录条数": 2, "平均时长（小时）": 4}]
    assert json.dumps(view, sort_keys=True) == before


def test_same_named_sources_with_different_conditions_are_still_separate(view):
    metric = view["workspace_scope"]["metrics"]["STATE-RHR"]
    metric["value"] = {str(("Apple Watch", device, protocol, "1")):
                       [{"date": "2026-11-17", "value": value}]
                       for device, protocol, value in (("device-a", "a", 55), ("device-b", "b", 65))}
    rows = [row for row in heart_rows(view) if row["指标"] == "静息心率"]
    assert {row["来源"] for row in rows} == {"Apple Watch（来源 1）", "Apple Watch（来源 2）"}
    assert "device-" not in str(rows) and "protocol" not in str(rows)


def test_weight_historical_reference_does_not_become_selected_window_data(view):
    view["weight"]["daily"] = []
    view["weight"]["latest_observations"] = [{"date": "2026-05-01", "value": 72, "unit": "kg",
        "source": "体脂秤", "source_record_ids": ["private-record"], "scope": "outside_selected_window"}]
    before = copy.deepcopy(view)
    assert weight_rows(view) == []
    assert latest_weight_rows(view) == [{"日期": "2026-05-01", "体重（kg）": 72, "来源": "体脂秤"}]
    assert view == before


@pytest.mark.parametrize("renderer,column,values", [
    ("render_heart", "数值", [30, 55, 65]),
    ("render_sleep", "睡眠时长（小时）", [7.5]),
    ("render_weight", "体重（kg）", [70]),
])
def test_streamlit_body_pages_show_readable_tables(view, renderer, column, values):
    app = AppTest.from_string(
        f"import streamlit as st\nfrom healthzip.ui.body_pages import {renderer}\n"
        f"{renderer}(st.session_state['body_view'])\n")
    app.session_state["body_view"] = view
    app.run()
    assert not app.exception and not app.error
    tables = [table.value for table in app.dataframe if column in table.value.columns]
    assert sorted(value for table in tables for value in table[column].tolist()) == values
    assert all("private-" not in table.to_string() and "source_ids" not in str(table.columns)
               and "series_id" not in str(table.columns) for table in tables)
    assert any("所选范围" in caption.value for caption in app.caption)


def test_sleep_display_statistics_and_tables_work_without_plotly(view, monkeypatch):
    import healthzip.ui.body_pages as body_pages

    monkeypatch.setattr(body_pages, "px", None)
    view["sleep"]["nights"].append({"date": "2026-11-18", "sleep_hours": 0, "source": "手工记录"})
    app = AppTest.from_string("import streamlit as st\nfrom healthzip.ui.body_pages import render_sleep\nrender_sleep(st.session_state['body_view'])")
    app.session_state["body_view"] = view
    app.run()
    assert not app.exception and not app.error
    summary = next(table.value for table in app.dataframe if "平均时长（小时）" in table.value.columns)
    assert summary["有效记录条数"].tolist() == [1]
    assert summary["平均时长（小时）"].tolist() == [7.5]
    assert any("1 条零时长或无效记录" in caption.value for caption in app.caption)


def test_empty_weight_window_shows_actual_historical_date_and_can_expand(view):
    view["weight"]["daily"] = []
    view["weight"]["latest_observations"] = [{"date": "2026-05-01", "value": 72,
                                               "source": "体脂秤", "unit": "kg"}]
    app = AppTest.from_string("import streamlit as st\nfrom healthzip.ui.body_pages import render_weight\nst.number_input('分析窗口（天）', min_value=7, max_value=3650, value=30, key='analysis_window_days')\nrender_weight(st.session_state['body_view'])")
    app.session_state["body_view"] = view
    app.run()
    assert not app.exception and not app.error
    assert any("所选范围内无称重记录，最近一次为 2026-05-01" in info.value for info in app.info)
    app.button(key="body_weight_expand_window").click().run()
    assert not app.exception and not app.error
    assert app.number_input(key="analysis_window_days").value == 202
