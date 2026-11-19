"""Full local app workspaces use their own routes and avoid opener write locks."""

import json
import socket
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

import pytest
from streamlit.testing.v1 import AppTest

from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.workflows import save_context
from healthzip.workflows.storage import withdraw_context

APP = Path(__file__).resolve().parents[2] / "app.py"


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")

    def network_disabled(*args, **kwargs):
        raise AssertionError("Workspace regression must remain offline")

    monkeypatch.setattr(socket.socket, "connect", network_disabled)
    monkeypatch.setattr(socket, "create_connection", network_disabled)
    path = tmp_path / ".local/healthzip.sqlite3"
    repo = Repository(path)
    today = date.today().isoformat()
    repo.conn.execute(
        "INSERT INTO nutrition_day(fingerprint,day,energy_kcal,log_status,source) VALUES(?,?,?,?,?)",
        ("synthetic-nutrition", today, 1800, "partial", "synthetic_workspace"),
    )
    repo.conn.execute(
        "INSERT INTO cycle_event(fingerprint,event_date,canonical_type,category_value,source) VALUES(?,?,?,?,?)",
        ("synthetic-cycle", today, "menstrual_flow", "synthetic_observation", "synthetic_workspace"),
    )
    repo.conn.commit()
    repo.close()
    return path


def assert_page_ok(app):
    assert not app.exception
    assert not app.error


def test_all_actual_workspaces_switch_and_nutrition_cycle_keep_distinct_routes(isolated_workspace):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert_page_ok(app)
    workspaces = list(app.radio(key="main_workspace").options)
    assert len(workspaces) == 12
    for page in workspaces:
        app.radio(key="main_workspace").set_value(page).run()
        assert_page_ok(app)
        headers = {element.value for element in app.subheader}
        if page == "导入与总览":
            assert "数据总览" in headers
        elif page == "力量":
            assert "我的训练" in headers
        elif page == "分析":
            assert "训练分析" in headers
            assert "营养记录与完整度" not in headers
            assert "周期记录回顾" not in headers
        elif page == "营养":
            assert "营养记录与完整度" in headers
            assert "周期记录回顾" not in headers
            rows = [table.value for table in app.dataframe if "energy_kcal" in table.value.columns]
            assert len(rows) == 1
            assert rows[0]["energy_kcal"].tolist() == [1800.0]
        elif page == "周期":
            assert "周期记录回顾" in headers
            assert "营养记录与完整度" not in headers
            rows = [table.value for table in app.dataframe if "category_value" in table.value.columns]
            assert len(rows) == 1
            assert rows[0]["category_value"].tolist() == ["synthetic_observation"]
        elif page == "报告":
            assert any(element.label == "报告输出路径" for element in app.text_input)
        elif page == "知识库":
            assert any(element.label == "知识主题" for element in app.selectbox)
    app.radio(key="main_workspace").set_value("导入与总览").run()
    assert_page_ok(app)
    assert Path(app.sidebar.text_input[0].value).resolve() == isolated_workspace


def test_overview_rerun_reads_current_repository_while_writer_holds_lock(isolated_workspace):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert_page_ok(app)
    writer = sqlite3.connect(isolated_workspace)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO schema_meta VALUES('synthetic_pending_edit','not_committed')")
        app.run(timeout=3)
        assert_page_ok(app)
        assert writer.in_transaction
        assert app.radio(key="main_workspace").value == "导入与总览"
        assert "数据总览" in {element.value for element in app.subheader}
    finally:
        writer.rollback()
        writer.close()


def test_factual_workspaces_do_not_freeze_unused_full_analysis_and_keep_context_warning(isolated_workspace):
    repo = Repository(isolated_workspace)
    context_id = save_context(repo, {"population": "adults"})
    withdraw_context(repo, context_id)
    repo.close()
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.session_state["analysis_contexts"] = {str(isolated_workspace): context_id}
    for page in ("数据质量", "运动", "营养", "周期"):
        app.radio(key="main_workspace").set_value(page).run()
        assert_page_ok(app)
        assert any("当前选择的适用声明已撤回或被替换" in warning.value for warning in app.warning)
        with sqlite3.connect(isolated_workspace) as conn:
            assert conn.execute("SELECT count(*) FROM analysis_run").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM workflow_run").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM workflow_use_check").fetchone()[0] == 0
    with sqlite3.connect(isolated_workspace) as conn:
        cards = dict(conn.execute("SELECT id,title FROM insight"))
        assert cards["workout_summary"] == "训练频率与时长"
        assert cards["nutrition_completeness"] == "营养记录与完整度"
        assert cards["cycle_review"] == "周期记录回顾"


def test_body_workspaces_show_source_separated_observations_without_full_freeze(isolated_workspace):
    root = Element("HealthData")
    observed = datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=1)

    def record(raw_type, source, value, unit=None, *, start=None, end=None):
        attrs = {"type": raw_type, "sourceName": source, "sourceVersion": "synthetic-1",
                 "device": source + "-device", "value": str(value),
                 "startDate": (start or observed).strftime("%Y-%m-%d %H:%M:%S %z"),
                 "endDate": (end or observed).strftime("%Y-%m-%d %H:%M:%S %z"),
                 "creationDate": observed.strftime("%Y-%m-%d %H:%M:%S %z")}
        if unit:
            attrs["unit"] = unit
        SubElement(root, "Record", attrs)

    for source, heart, sdnn, weight, sleep_hours in (
        ("synthetic_watch_a", 55, 30, 70, 3),
        ("synthetic_watch_b", 65, 40, 80, 5),
    ):
        record("HKQuantityTypeIdentifierRestingHeartRate", source, heart, "count/min")
        record("HKQuantityTypeIdentifierHeartRateVariabilitySDNN", source, sdnn, "ms")
        record("HKQuantityTypeIdentifierBodyMass", source, weight, "kg")
        record("HKCategoryTypeIdentifierSleepAnalysis", source,
               "HKCategoryValueSleepAnalysisAsleepCore", start=observed-timedelta(hours=sleep_hours))
    record("HKQuantityTypeIdentifierVO2Max", "synthetic_watch_a", 42, "mL/(kg·min)")
    archive_path = isolated_workspace.parent / "synthetic-workspaces.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("export.xml", tostring(root))
    repo = Repository(isolated_workspace)
    result = import_apple_zip(archive_path, repo)
    assert result.status == "completed" and result.records_inserted == 9
    context_id = save_context(repo, {"population": "adults"})
    withdraw_context(repo, context_id)
    repo.close()

    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.session_state["analysis_contexts"] = {str(isolated_workspace): context_id}
    for page in ("心率 / HRV", "睡眠", "体重 / 有氧"):
        app.radio(key="main_workspace").set_value(page).run()
        assert_page_ok(app)
        assert any("当前选择的适用声明已撤回或被替换" in warning.value for warning in app.warning)
        with sqlite3.connect(isolated_workspace) as conn:
            assert conn.execute("SELECT count(*) FROM analysis_run").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM workflow_run").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM workflow_use_check").fetchone()[0] == 0
            cards = {row[0]: json.loads(row[1]) for row in conn.execute("SELECT id,facts_json FROM insight")}
        if page == "心率 / HRV":
            heart_values = cards["STATE-RHR"][0]["value"]
            assert len(heart_values) == 2
            assert sorted(day["value"] for days in heart_values.values() for day in days) == [55, 65]
            assert all("synthetic_watch_" in source for source in heart_values)
            sdnn_values = cards["STATE-SDNN"][0]["value"]
            assert sorted(day["value"] for days in sdnn_values.values() for day in days) == [30, 40]
        elif page == "睡眠":
            tables = [table.value for table in app.dataframe if "sleep_hours" in table.value.columns]
            assert len(tables) == 1
            assert sorted(tables[0]["sleep_hours"].tolist()) == [3, 5]
            assert tables[0]["source"].nunique() == 2
        else:
            tables = [table.value for table in app.dataframe if "kg" in table.value.columns]
            assert len(tables) == 1
            assert sorted(tables[0]["kg"].tolist()) == [70, 80]
            assert tables[0]["source"].nunique() == 2
            assert any(table.value.get("value", []).tolist() == [42] for table in app.dataframe
                       if "metric" in table.value.columns and table.value["metric"].tolist() == ["vo2_max"])
