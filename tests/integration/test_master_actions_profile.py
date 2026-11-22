"""Frozen user actions, workspace choices and dated profile inputs."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from healthzip.db.repository import Repository
from healthzip.ui.basic_profile import latest_measurements
from healthzip.ui.preferences import load_preferences, save_preferences
from healthzip.workflows.actions import followup, list_actions, save_feedback, select_action


def question():
    return {"id": "W6", "analysis_version": "original", "observation": "本期已观察睡眠",
            "steps": ["保持实际记录条件"], "rows": [],
            "window": {"start": "2026-10-01T00:00:00+08:00", "end": "2026-10-08T00:00:00+08:00", "timezone": "Asia/Shanghai"}}


def test_action_retry_concurrent_choice_preserves_frozen_baseline(tmp_path):
    path = tmp_path / "actions.sqlite3"
    Repository(path).close()
    original = question()

    def choose(_):
        repo = Repository(path)
        try:
            return select_action(repo, original, original["steps"][0], "2026-10-16T12:00:00+08:00",
                                 source_filter=["watch A"], selected_at="2026-10-09T12:00:00+08:00")
        finally:
            repo.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        identities = list(pool.map(choose, range(6)))
    assert len(set(identities)) == 1
    repo = Repository(path)
    try:
        assert len(list_actions(repo)) == 1
        identity = identities[0]
        save_feedback(repo, identity, "partial", "实际只做了一部分", None, event_id="same-submit")
        save_feedback(repo, identity, "partial", "实际只做了一部分", None, event_id="same-submit")
        assert repo.one("SELECT count(*) FROM review_action_event")[0] == 1
        with pytest.raises(ValueError, match="不同反馈"):
            save_feedback(repo, identity, "executed", "changed", None, event_id="same-submit")
        with pytest.raises(ValueError, match="不属于"):
            save_feedback(repo, identity, "executed", "", {"baseline": {}}, event_id="wrong-action")
        save_feedback(repo, identity, "executed", "完成记录", None, event_id="new-feedback")
        assert len(repo.rows("SELECT * FROM review_action_event")) == 2
        assert json.loads(list_actions(repo)[0]["baseline_json"]) == original
        assert list_actions(repo)[0]["status"] == "executed"
    finally:
        repo.close()


def test_followup_uses_saved_duration_sources_and_time_order(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "actions.sqlite3")
    original = question()
    identity = select_action(repo, original, original["steps"][0], "2026-10-16T12:00:00+08:00",
                             source_filter=["watch A"], selected_at="2026-10-09T12:00:00+08:00")
    calls = []

    def analyze(_repo, **kwargs):
        calls.append(kwargs)
        return [{"analysis_version": "updated"}]

    monkeypatch.setattr("healthzip.analytics.body_metrics.analyze_questions", analyze)
    assert followup(repo, identity, cutoff_time="2026-10-08T00:00:00Z")["status"] == "awaiting_observations"
    assert not calls
    partial = followup(repo, identity, cutoff_time="2026-10-11T00:00:00Z")
    assert partial["status"] == "partial" and not partial["method_matches"]
    assert calls[-1]["source_filter"] == ["watch A"]
    assert calls[-1]["timezone_name"] == "Asia/Shanghai"
    final = followup(repo, identity, cutoff_time="2026-10-20T00:00:00Z")
    assert final["comparison_duration_days"] == 7
    assert calls[-1]["window_start"] == "2026-10-09T04:00:00+00:00"
    assert calls[-1]["window_end"] == "2026-10-16T04:00:00+00:00"
    assert final["baseline"] == original
    repo.close()


def test_action_sources_cannot_drift_from_the_selected_fact_snapshot(tmp_path):
    repo = Repository(tmp_path / "sources.sqlite3")
    baseline = {**question(), "source_filter": ["watch A"]}
    arguments = {"selected_at": "2026-10-09T12:00:00+08:00"}
    identity = select_action(repo, baseline, baseline["steps"][0], "2026-10-16T12:00:00+08:00", **arguments)
    assert json.loads(repo.one("SELECT source_filter_json FROM review_action WHERE action_id=?", (identity,))[0]) == ["watch A"]
    with pytest.raises(ValueError, match="来源须"):
        select_action(repo, baseline, baseline["steps"][0], "2026-10-16T12:00:00+08:00", source_filter=["watch B"], **arguments)
    repo.close()


def test_profile_does_not_redate_old_weight_or_assume_age(tmp_path):
    from healthzip.advice import profile, save_profile
    from healthzip.training.service import TrainingService
    repo = Repository(tmp_path / "profile.sqlite3")
    TrainingService(repo)
    repo.conn.execute("INSERT INTO body_measurement(fingerprint,measured_at,local_date,body_part,value,unit,canonical_type,source) VALUES(?,?,?,?,?,?,?,?)",
                      ("old", "2026-01-01T08:00:00+08:00", "2026-01-01", "body_mass", 70, "kg", "body_mass_kg", "合成称重"))
    repo.conn.commit()
    save_profile(repo, {"age": None, "training_goal": "strength"})
    latest = latest_measurements(repo)["body_mass_kg"]
    assert latest["value"] == 70 and latest["measured_at"].startswith("2026-01-01")
    assert latest["source"] == "合成称重"
    assert profile(repo)["fields"]["age"] is None
    assert "height_cm" not in latest_measurements(repo)
    repo.close()


def test_view_preferences_workspace_isolation_and_atomic_merge(tmp_path):
    a, b = tmp_path / "a.sqlite3", tmp_path / "b.sqlite3"
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda i: save_preferences(a, **{str(i): i}), range(12)))
    save_preferences(a, **{"source:sleep": "watch A", "frozen_sleep": "run-original"})
    save_preferences(b, **{"source:sleep": "watch B"})
    assert all(load_preferences(a)[str(i)] == i for i in range(12))
    assert load_preferences(a)["frozen_sleep"] == "run-original"
    assert load_preferences(b) == {"source:sleep": "watch B"}


def test_real_navigation_preserves_range_and_settings_save_unknown_age(tmp_path, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from healthzip.advice import profile
    from tests.app_navigation import go

    monkeypatch.chdir(tmp_path)
    database = tmp_path / ".local/healthzip.sqlite3"
    Repository(database).close()
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "app.py"), default_timeout=30).run()
    app.radio(key="overview_period_choice").set_value("本月").run()
    go(app, "心率")
    app.radio(key="body_period").set_value("本月").run()
    go(app, "复盘")
    app.radio(key="review_period").set_value("本月").run()
    app.radio(key="review_section").set_value("问题分析").run()
    go(app, "身体")
    assert app.selectbox(key="body_section").value == "心率"
    assert app.radio(key="body_period").value == "本月"
    go(app, "复盘")
    assert app.radio(key="review_section").value == "问题分析"
    app.radio(key="review_section").set_value("周月复盘").run()
    assert app.radio(key="review_period").value == "本月"
    go(app, "总览")
    assert app.radio(key="overview_period_choice").value == "本月"
    go(app, "设置")
    app.radio(key="settings_section").set_value("基础资料").run()
    next(item for item in app.selectbox if item.label == "当前目标").set_value("strength")
    next(item for item in app.button if item.label == "保存基础资料与目标").click().run()
    assert not app.exception and not app.error
    repo = Repository(database)
    try:
        assert profile(repo)["fields"] == {"age": None, "training_goal": "strength"}
        assert not repo.rows("SELECT * FROM body_measurement")
    finally:
        repo.close()
