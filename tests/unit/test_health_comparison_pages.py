"""Independent product scenarios render actual MetricResult computations."""

from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from streamlit.testing.v1 import AppTest

from healthzip.analytics.health_context import joint_health_context
from healthzip.science import evaluate
from healthzip.ui.joint_health import joint_observations

ZONE = ZoneInfo("Asia/Shanghai")
START = datetime(2026, 11, 9, tzinfo=ZONE)
END = START + timedelta(days=7)


def record(mid, day, value, *, index=0):
    at = START + timedelta(days=day, hours=7, minutes=index)
    return {"id": f"synthetic-{mid}-{day}-{index}", "record_kind": "health_sample",
        "canonical_type": mid, "normalized_value": value,
        "normalized_unit": "count/min" if mid == "resting_heart_rate_bpm" else "ms",
        "source_name": "合成手表", "device": "synthetic-watch", "source_version": "test-v1",
        "protocol_id": "synthetic-protocol", "event_end": at.isoformat(),
        "event_start": at.isoformat(), "available_at": at.isoformat()}


def view_with(rows):
    metrics = {mid: evaluate(mid, rows, cutoff_time=END.isoformat(),
        window_start=START.isoformat(), window_end=END.isoformat(), context={"timezone": "Asia/Shanghai"})
        for mid in ("STATE-RHR", "STATE-SDNN", "REPORT-STATE-SUMMARY")}
    return {"workspace_scope": {"workspace": "心率", "window_start": START.isoformat(),
        "window_end": END.isoformat(), "cutoff_time": END.isoformat(), "timezone": "Asia/Shanghai",
        "metrics": metrics}, "heart": {}, "sleep": {"nights": []}}


def render(view, function="render_heart"):
    app = AppTest.from_string("import streamlit as st\nfrom healthzip.ui.body_pages import " + function +
                             "\n" + function + "(st.session_state['fixture'])")
    app.session_state["fixture"] = view
    app.run(timeout=20)
    assert not app.exception
    return app


def page_text(app):
    return "\n".join(item.value for group in (app.markdown, app.caption, app.info) for item in group)


def test_rhr_first_screen_uses_computed_median_history_range_coverage_and_difference():
    rows = [record("resting_heart_rate_bpm", day, 59 if day < 0 else 64) for day in range(-28, 7)]
    view = view_with(rows)
    before_render = deepcopy(view)
    app = render(view)
    text = page_text(app)
    # The change now lives on the first value card rather than a repeated prose paragraph.
    first = app.metric[0]
    assert (first.label, first.value, first.delta) == (
        "日静息心率", "64.0 bpm", "较前期 +5.0 bpm")
    assert {item.label: item.value for item in app.metric} == {
        "日静息心率": "64.0 bpm", "本期日静息心率": "64.0 bpm",
        "前期日静息心率": "59.0 bpm", "个人历史参考日静息心率": "59.0 bpm"}
    assert "日代表值中位数" in text
    assert "2026-11-09 至 2026-11-15" in text
    assert "2026-11-02 至 2026-11-08" in text
    assert "2026-10-12 至 2026-11-08" in text
    assert "记录 7/7 天" in text and "记录 28/28 天" in text
    stream = view["workspace_scope"]["metrics"]["STATE-RHR"]["comparison"]["streams"][0]
    assert stream["protocol"] == ["合成手表", "synthetic-watch", "synthetic-protocol", "test-v1"]
    assert [(point["date"], point["value"], point["source_ids"])
            for point in stream["current"]["daily_points"]] == [
        (f"2026-11-{9 + day:02d}", 64.0, [f"synthetic-resting_heart_rate_bpm-{day}-0"])
        for day in range(7)]
    table = next(item.value for item in app.dataframe if "日代表值" in item.value.columns)
    assert table["日代表值"].tolist() == [64.0] * 7
    assert set(table["来源"]) == {"合成手表"}
    assert "设备：synthetic-watch · 协议：synthetic-protocol · 来源版本：test-v1" in text
    assert view == before_render  # Display does not recompute or mutate the source snapshot.
    assert "异常" not in text and "疲劳导致" not in text


def test_nearby_distributions_remain_a_specific_observation_with_no_invented_problem():
    rows = [record("resting_heart_rate_bpm", day, 62 + day % 3) for day in range(-28, 7)]
    view = view_with(rows)
    app = render(view)
    text = page_text(app)
    first = app.metric[0]
    assert (first.label, first.value, first.delta) == (
        "日静息心率", "63.0 bpm", "较前期 +0.0 bpm")
    assert "日代表值中位数" in text
    # Seven independent daily values have the same median but different middle halves.
    stream = view["workspace_scope"]["metrics"]["STATE-RHR"]["comparison"]["streams"][0]
    assert stream["current"]["quartiles"] == [62.0, 63.0, 63.5]
    assert stream["previous"]["quartiles"] == [62.5, 63.0, 64.0]
    assert "本期中间一半日值 62.0–63.5 bpm" in text
    assert "前期中间一半日值 62.5–64.0 bpm" in text
    table = next(item.value for item in app.dataframe if "日代表值" in item.value.columns)
    assert table["日代表值"].tolist() == [62.0, 63.0, 64.0, 62.0, 63.0, 64.0, 62.0]
    assert "过度训练" not in text and "感染" not in text and "证据不足" not in text


def test_sparse_period_keeps_both_real_coverages_and_sample_counts():
    rows = [record("resting_heart_rate_bpm", day, 59) for day in range(-20, 0)]
    rows.extend(record("resting_heart_rate_bpm", day, 64) for day in (1, 5))
    app = render(view_with(rows))
    text = page_text(app)
    assert "记录 2/7 天" in text and "记录 20/28 天" in text
    assert "代表性不能直接视为相同" in text
    assert "未记录日期" in text


def test_sdnn_typical_day_and_record_counts_are_visible_without_sample_weighting():
    rows = [record("hrv_sdnn_ms", 1, 20, index=index) for index in range(20)]
    rows.append(record("hrv_sdnn_ms", 2, 80))
    app = render(view_with(rows))
    assert "50.0 ms" in {item.value for item in app.metric}
    table = next(item.value for item in app.dataframe if "原始记录数" in item.value.columns)
    assert sorted(table["原始记录数"].tolist()) == [1, 20]
    assert "SDNN 与 RMSSD 分开" in page_text(app)


def test_ordinary_heart_rate_has_no_fabricated_resting_value():
    view = view_with([])
    view["heart"]["observations"] = [{"date": "2026-11-10", "observed_at": "2026-11-10T12:00:00+08:00",
                                      "value": 110, "source": "合成手表"}]
    app = render(view)
    text = page_text(app)
    assert "1 条普通心率观测" in text and "不替代日静息心率" in text
    assert not app.metric


def test_joint_context_excludes_other_months_and_uses_existing_training_and_fatigue():
    view = view_with([record("resting_heart_rate_bpm", 1, 64), record("hrv_sdnn_ms", 1, 58)])
    metrics = view["workspace_scope"]["metrics"]
    metrics["REPORT-STATE-SUMMARY"]["daily_facts"].extend([
        {"metric_id": "sleep_observed_minutes_by_wake_date", "series_id": "observed_sleep_by_wake_date",
         "date": "2026-11-10", "value": 360, "source_record_ids": ["sleep-synthetic"], "unit": "min"},
        {"metric_id": "STATE-FATIGUE", "date": "2026-11-10", "value": 7,
         "source_record_ids": ["fatigue-synthetic"]},
        {"metric_id": "STATE-FATIGUE", "date": "2026-10-10", "value": 9,
         "source_record_ids": ["outside-synthetic"]}])
    window = {"start": START.isoformat(), "end": END.isoformat(), "cutoff_time": END.isoformat(), "timezone": "Asia/Shanghai"}
    context = joint_health_context(metrics, [
        {"id": "training-synthetic", "started_at": "2026-11-10T16:00:00+08:00"},
        {"id": "outside", "started_at": "2026-10-10T16:00:00+08:00"}], window)
    snapshot = {"metrics": metrics, "joint_health_context": context}
    observations = joint_observations(snapshot)
    assert context["three_metric_overlap_dates"] == ["2026-11-10"]
    assert len(context["training_sessions"]) == 1
    assert context["dates_by_metric"]["STATE-FATIGUE"] == ["2026-11-10"]
    text = " ".join(observations["statements"] + observations["next_steps"])
    assert "已记录 1 场训练" in text and "已记录主观疲劳" in text
    assert "不能据此宣布恢复改善" in text and "无需重复填写" in text
    assert "饮酒" not in text and "感染" not in text


def test_sleep_modes_use_separate_metric_windows_and_do_not_mix_frozen_main(tmp_path):
    from healthzip.analytics.sleep_selection import (
        declare_episode,
        selected_sleep_metrics,
        sleep_options,
    )
    from healthzip.analytics.v13 import snapshot
    from healthzip.analytics.workspaces import analyze_workspace
    from healthzip.db.repository import Repository
    from healthzip.science.contracts import Window
    from tests.health_change_fixture import CUTOFF, create_health_change_fixture

    path = tmp_path / "synthetic.sqlite3"
    create_health_change_fixture(path)
    repo = Repository(path)
    try:
        view = analyze_workspace(repo, "睡眠", window_days=7, cutoff_time=CUTOFF)
        app = render(view, "render_sleep")
        assert "6.0 小时" in {item.value for item in app.metric}
        app.radio(key="body_sleep_scope_standalone").set_value("截止前24小时").run()
        assert not app.exception
        assert [item.value for item in app.metric] == ["5.0 小时"]  # Actual 24h clipping, not the whole night's 6h.
        assert "2026-11-21 00:00" in page_text(app)
        assert "2026-11-15 00:00" not in page_text(app)
        window = Window("2026-11-15T00:00:00+08:00", CUTOFF, CUTOFF, "Asia/Shanghai")
        records, _ = snapshot(repo, CUTOFF, window_start=window.start, window_end=window.end)
        options = sleep_options(records, window)
        source = options["streams"][0]["stream_id"]
        episode = declare_episode(options, source, start="2026-11-20T23:00:00+08:00",
            end="2026-11-21T05:00:00+08:00", attribution_date="2026-11-21", declared_at=CUTOFF)
        metrics, audit = selected_sleep_metrics(records, window, {"stream_id": source,
            "episodes": [episode], "main_episode_id": episode["id"]})
        assert audit["accepted"]
        app.session_state["analysis_sleep_results"] = {"standalone": {"metrics": metrics,
            "sleep_selection": audit, "cutoff_time": CUTOFF, "data_version": "synthetic"}}
        app.radio(key="body_sleep_scope_standalone").set_value("已声明主睡眠（冻结）").run()
        assert not app.exception
        assert [item.value for item in app.metric] == ["6.0 小时"]
        assert "原冻结范围与截止" in page_text(app)
        assert "2026-11-20 23:00" in page_text(app)
        assert "2026-11-15 00:00" not in page_text(app)
        view["workspace_scope"]["source_filter"] = ["其他合成来源"]
        app.session_state["fixture"] = view
        app.run()
        assert not app.metric and "不在当前来源筛选中" in page_text(app)
        app.session_state["analysis_sleep_results"] = {"other-workspace": {"metrics": metrics}}
        app.run()
        assert not app.metric and "尚无此工作区" in page_text(app)
    finally:
        repo.close()
