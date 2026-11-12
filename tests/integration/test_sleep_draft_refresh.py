"""Ordinary automatic analysis refresh must not discard an in-progress draft."""

import pytest
from streamlit.testing.v1 import AppTest
from test_sleep_episode_selection import sleep_repo

from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository


def draft_app(tmp_path, *, days=30, period=None):
    repo = sleep_repo(tmp_path)
    output = analyze(repo, cutoff_time="2026-11-18T12:00:00+00:00", timezone_name="UTC", window_days=days, period=period)
    source = next(item["stream_id"] for item in output["sleep_options"]["streams"] if item["source_name"] == "Synthetic Watch A")
    path = repo.path
    repo.close()
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from datetime import datetime, timezone\n"
        "from unittest.mock import patch\n"
        "from healthzip.db.repository import Repository\n"
        "from healthzip.analytics.v13 import analyze\n"
        "from healthzip.ui.analysis_page import render_analysis\n"
        "class Clock(datetime):\n"
        "    @classmethod\n"
        "    def now(cls, tz=None):\n"
        "        return datetime.fromisoformat(st.session_state.get('test_clock','2026-11-18T12:00:00+00:00')).astimezone(tz or timezone.utc)\n"
        f"repo=Repository({str(path)!r})\n"
        "with patch('healthzip.analytics.v13.datetime',Clock), patch('healthzip.ui.sleep_selection._now',lambda:Clock.now(timezone.utc)):\n"
        f"    render_analysis(repo, {{'v13':analyze(repo,timezone_name='UTC',window_days=st.session_state.get('test_days',{days}),period={period!r})}})\n"
        "repo.close()"
    ).run(timeout=30)
    app.selectbox(key="analysis_sleep_stream").select(source).run(timeout=30)
    app.text_input(key="analysis_sleep_start").set_value("2026-11-17T23:00:00Z")
    app.text_input(key="analysis_sleep_end").set_value("2026-11-18T06:00:00Z")
    app.text_input(key="analysis_sleep_date").set_value("2026-11-18")
    app.button(key="analysis_sleep_add").click().run(timeout=30)
    assert not app.exception and not app.error
    return app


def test_automatic_minute_refresh_preserves_declared_night_and_main_choice(tmp_path):
    app = draft_app(tmp_path)
    original = app.session_state["analysis_sleep_declarations"]
    app.selectbox(key="analysis_sleep_main").select(original[0]["id"]).run(timeout=30)
    app.session_state["test_clock"] = "2026-11-18T12:01:01+00:00"
    app.run(timeout=30)
    assert app.session_state["analysis_sleep_declarations"] == original
    assert app.selectbox(key="analysis_sleep_main").value == original[0]["id"]
    # A correction to another night changes the source inventory, not the
    # selected episode's support or its declaration time.
    repo = Repository(tmp_path / "synthetic-sleep-selection.sqlite3")
    last_revision = repo.one("SELECT MAX(revision_id) AS n FROM source_revision")["n"]
    repo.conn.execute("UPDATE health_sample SET end_utc='2026-11-17T07:00:00Z' WHERE source_name='Synthetic Watch A' AND end_utc LIKE '2026-11-17%'")
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-18T12:02:00Z' WHERE revision_id>?", (last_revision,))
    repo.conn.commit()
    repo.close()
    app.session_state["test_clock"] = "2026-11-18T12:09:05+00:00"
    app.run(timeout=30)
    assert app.session_state["analysis_sleep_declarations"] == original
    app.button(key="analysis_sleep_submit").click().run(timeout=30)
    result = app.session_state["analysis_sleep_result"]
    assert result["metrics"]["STATE-SLEEP-MAIN"]["value"]["observed_minutes"] == 420
    assert result["sleep_selection"]["episodes"][0]["declared_at"] == original[0]["declared_at"]
    assert not app.exception and not app.error


def test_rolling_episode_really_leaving_window_is_explicitly_invalidated(tmp_path):
    app = draft_app(tmp_path, days=1)
    app.session_state["test_clock"] = "2026-11-18T23:00:00.000001+00:00"
    app.run(timeout=30)
    assert app.session_state["analysis_sleep_declarations"] == []
    assert any("窗口" in warning.value for warning in app.warning)
    assert app.button(key="analysis_sleep_submit").disabled
    assert not app.exception


def test_user_window_change_clears_draft_with_explanation(tmp_path):
    app = draft_app(tmp_path)
    app.session_state["test_days"] = 7
    app.run(timeout=30)
    assert app.session_state["analysis_sleep_declarations"] == []
    assert any("窗口" in warning.value for warning in app.warning)
    assert not app.exception


@pytest.mark.parametrize("period,clock", [("week", "2026-11-23T12:00:00+00:00"), ("month", "2026-12-01T12:00:00+00:00")])
def test_calendar_period_rollover_clears_old_draft_with_explanation(tmp_path, period, clock):
    app = draft_app(tmp_path, period=period)
    app.session_state["test_clock"] = clock
    app.run(timeout=30)
    assert app.session_state["analysis_sleep_declarations"] == []
    assert any("窗口" in warning.value for warning in app.warning)
    assert not app.exception
