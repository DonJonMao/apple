"""Full app summaries keep the shared navigation and real recording available.

All observations are synthetic and live in a temporary repository. AppTest
replaces only the component transport; separate browser acceptance covers DOM.
The summary's public cutoff argument fixes time without replacing calculation.
"""

import runpy
import socket
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from functools import partial
from importlib import import_module
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

import pytest
from streamlit.testing.v1 import AppTest

from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.training.service import TrainingService

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app.py"
UI = runpy.run_path(str(ROOT / "tests/strength_ui_harness.py"))


@pytest.fixture
def summary_workspace(tmp_path, monkeypatch):
    UI["install"](monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")

    def no_network(*args, **kwargs):
        raise AssertionError("Synthetic workspace summaries must remain offline")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    # A future synthetic cutoff keeps all imported visibility times before the
    # decision time, even when this test is rerun in a later calendar month.
    cutoff = (datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(days=45)).replace(
        day=18, hour=12, minute=0, second=0, microsecond=0
    )
    recent = cutoff - timedelta(hours=1)
    earlier = cutoff.replace(day=1, hour=10)
    root = Element("HealthData")

    def record(kind, value, unit, at, *, start=None):
        attributes = {
            "type": kind, "sourceName": "合成摘要手表", "sourceVersion": "synthetic-1",
            "device": "synthetic-summary-device", "value": str(value),
            "startDate": (start or at).strftime("%Y-%m-%d %H:%M:%S %z"),
            "endDate": at.strftime("%Y-%m-%d %H:%M:%S %z"),
            "creationDate": at.strftime("%Y-%m-%d %H:%M:%S %z"),
        }
        if unit:
            attributes["unit"] = unit
        SubElement(root, "Record", attributes)

    for at, rhr, hrv, sleep_hours in ((earlier, 70, 30, 6), (recent, 60, 50, 7.5)):
        record("HKQuantityTypeIdentifierRestingHeartRate", rhr, "count/min", at)
        record("HKQuantityTypeIdentifierHeartRateVariabilitySDNN", hrv, "ms", at)
        record("HKCategoryTypeIdentifierSleepAnalysis", "HKCategoryValueSleepAnalysisAsleepCore",
               None, at, start=at - timedelta(hours=sleep_hours))
    archive = tmp_path / "synthetic-summary.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as zipped:
        zipped.writestr("export.xml", tostring(root))
    database = tmp_path / ".local/healthzip.sqlite3"
    with closing(Repository(database)) as repo:
        imported = import_apple_zip(archive, repo)
        assert imported.status == "completed" and imported.records_inserted == 6
        service = TrainingService(repo)
        for at, count in ((earlier, 1), (recent, 2)):
            session = service.start_session("合成周期训练", started_at=at.isoformat())
            instance = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", {})
            for index in range(count):
                service.add_set(instance["id"], {
                    "completion_state": "completed", "load_value": 40, "load_unit": "kg",
                    "reps": 8, "ended_at": (at + timedelta(minutes=index + 1)).isoformat(),
                })
            service.end_session(session["id"], ended_at=(at + timedelta(minutes=15)).isoformat())
    module = import_module("healthzip.analytics.workspace_summary")
    monkeypatch.setattr(module, "workspace_summary", partial(module.workspace_summary, cutoff_time=cutoff.isoformat()))
    body = import_module("healthzip.analytics.workspaces")
    monkeypatch.setattr(body, "analyze_workspace", partial(body.analyze_workspace, cutoff_time=cutoff.isoformat()))
    return database


def assert_app_ok(app):
    assert not app.exception, [entry.value for entry in app.exception]
    assert not app.error, [entry.value for entry in app.error]


def assert_shared_navigation(app, workspace):
    assert_app_ok(app)
    main = [radio for radio in app.main.radio if radio.key == "main_workspace"]
    assert len(main) == 1 and main[0].value == workspace
    assert len(main[0].options) == 9 and main[0].horizontal
    assert not any(radio.key == "main_workspace" for radio in app.sidebar.radio)
    assert not app.sidebar.radio and not app.sidebar.text_input
    assert "数据质量" not in main[0].options and "周期" not in main[0].options


def main_text(app):
    return "\n".join(str(entry.value) for entry in [*app.main.markdown, *app.main.caption])


def event_count(database):
    with sqlite3.connect(database) as connection:
        return connection.execute("SELECT count(*) FROM training_event").fetchone()[0]


def test_shared_navigation_retains_an_active_saved_draft_when_switching_body_workspaces(summary_workspace):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert_shared_navigation(app, "总览")
    app.main.radio(key="main_workspace").set_value("力量").run()
    assert_shared_navigation(app, "力量")
    assert UI["send"](app, "start_session")["status"] == "saved"
    session = UI["snapshot"](app)["session"]
    assert UI["send"](app, "add_exercises", {
        "session_id": session["session_uuid"], "base_revision": session["revision"],
        "exercises": ["psa.ex.barbell_bench_press"],
    })["status"] == "saved"
    session = UI["snapshot"](app)["session"]
    row = session["sets"][0]
    assert UI["send"](app, "save_set", {
        "set_id": row["set_uuid"], "base_revision": row["revision"],
        "changes": {"load_value": "32.5", "load_unit": "kg", "reps": "8", "rir": None},
    })["status"] == "saved"
    before = event_count(summary_workspace)
    for workspace in ("睡眠", "心率", "力量"):
        app.main.radio(key="main_workspace").set_value(workspace).run()
        assert_shared_navigation(app, workspace)
        assert not any(radio.key == "workspace_summary_period" for radio in app.radio)
        if workspace != "力量":
            assert app.main.radio(key="body_period").value == "近30天"
    restored = UI["snapshot"](app)["session"]
    assert restored["session_uuid"] == session["session_uuid"]
    assert restored["sets"][0]["set_uuid"] == row["set_uuid"]
    assert restored["sets"][0]["reps"] == 8
    assert float(restored["sets"][0]["load_value"]) == 32.5
    assert restored["sets"][0]["completion_state"] == "draft"
    assert restored["session_status"] == "in_progress" and restored["completed_sets"] == 0
    assert app.query_params["workspace"] == "strength"
    assert event_count(summary_workspace) == before


def test_week_month_cards_trends_and_details_use_the_same_snapshot(summary_workspace):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    before = event_count(summary_workspace)
    expected = {"睡眠": {"本周": ["7.5 小时"], "本月": ["6.8 小时"]},
                "心率": {"本周": ["60.0 次/分", "50.0 毫秒"], "本月": ["65.0 次/分", "40.0 毫秒"]}}
    for workspace in ("睡眠", "心率"):
        app.main.radio(key="main_workspace").set_value(workspace).run()
        for label in ("本周", "本月"):
            app.main.radio(key="body_period").set_value(label).run()
            assert_shared_navigation(app, workspace)
            assert all(value in [metric.value for metric in app.metric] for value in expected[workspace][label])
            assert any("所选范围" in caption.value for caption in app.caption)
            assert "合成摘要手表" in main_text(app)
            assert all(not expander.proto.expanded for expander in app.expander)
            tables = [item.value for item in app.dataframe if "日期" in item.value.columns]
            assert len({day for table in tables for day in table["日期"]}) == (1 if label == "本周" else 2)
            assert not any(radio.key == "workspace_summary_period" for radio in app.radio)
    assert event_count(summary_workspace) == before
    with sqlite3.connect(summary_workspace) as connection:
        assert connection.execute("SELECT count(*) FROM analysis_run").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM workflow_run").fetchone()[0] == 0


@pytest.mark.parametrize("failure", [sqlite3.OperationalError, RuntimeError])
def test_optional_summary_failure_preserves_navigation_and_real_training_recording(
    summary_workspace, monkeypatch, failure
):
    def unavailable(*args, **kwargs):
        raise failure("synthetic optional summary unavailable")

    monkeypatch.setattr("healthzip.analytics.workspace_summary.workspace_summary", unavailable)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    for workspace in ("睡眠", "心率", "力量"):
        app.main.radio(key="main_workspace").set_value(workspace).run()
        assert_shared_navigation(app, workspace)
        assert "本次解释未完成" not in main_text(app)
        # Optional overview summaries are no longer a dependency of body pages or training.
    assert UI["send"](app, "start_session")["status"] == "saved"
    session = UI["snapshot"](app)["session"]
    assert UI["send"](app, "add_exercises", {
        "session_id": session["session_uuid"], "base_revision": session["revision"],
        "exercises": ["psa.ex.barbell_bench_press"],
    })["status"] == "saved"
    row = UI["snapshot"](app)["session"]["sets"][0]
    assert UI["send"](app, "save_set", {
        "set_id": row["set_uuid"], "base_revision": row["revision"], "complete": True,
        "changes": {"load_value": "37.5", "load_unit": "kg", "reps": "9", "rir": None},
    })["status"] == "saved"
    session = UI["snapshot"](app)["session"]
    assert UI["send"](app, "end_session", {
        "session_id": session["session_uuid"], "base_revision": session["revision"],
    })["status"] == "saved"
    assert_shared_navigation(app, "力量")
    with closing(Repository(summary_workspace)) as repo:
        actual = TrainingService(repo).get_session(session["session_uuid"])
        assert actual["session_status"] == "completed" and actual["completed_sets"] == 1
        assert len(actual["sets"]) == 1 and actual["sets"][0]["set_uuid"] == row["set_uuid"]
        assert actual["sets"][0]["reps"] == 9 and float(actual["sets"][0]["load_value"]) == 37.5
        assert actual["sets"][0]["rir"] is None
