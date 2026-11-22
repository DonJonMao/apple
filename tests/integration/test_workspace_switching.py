"""Full local app workspaces use their own routes and avoid opener write locks."""

import runpy
import socket
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

import pytest
from streamlit.testing.v1 import AppTest

from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.training.service import TrainingService
from healthzip.workflows import save_context
from healthzip.workflows.storage import withdraw_context
from tests.app_navigation import go

APP = Path(__file__).resolve().parents[2] / "app.py"
UI = runpy.run_path(str(Path(__file__).parents[1] / "strength_ui_harness.py"))


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    UI["install"](monkeypatch)
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


def test_all_visible_workspaces_switch_and_optional_sections_stay_hidden(isolated_workspace):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    expected = ["总览", "训练", "身体", "复盘", "设置"]
    assert list(app.radio(key="main_workspace").options) == expected
    for page in expected:
        go(app, page)
        assert_page_ok(app)
        assert not app.sidebar.text_input and not app.sidebar.radio
        if page == "训练":
            assert UI["snapshot"](app)["today"]
        else:
            assert page in {element.value for element in app.subheader}
    with closing(Repository(isolated_workspace)) as repo:
        assert repo.one("SELECT count(*) FROM cycle_event")[0] == 1
        assert repo.one("SELECT count(*) FROM nutrition_day")[0] == 1
        assert repo.one("SELECT count(*) FROM analysis_run")[0] == 0


def test_overview_and_health_reruns_are_readonly_while_writer_holds_lock(isolated_workspace):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert_page_ok(app)
    writer = sqlite3.connect(isolated_workspace)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO schema_meta VALUES('synthetic_pending_edit','not_committed')")
        for page in ("总览", "心率", "睡眠", "体重", "有氧", "运动", "复盘"):
            go(app, page, timeout=3)
            assert_page_ok(app)
            assert writer.in_transaction
        assert writer.execute("SELECT count(*) FROM insight").fetchone()[0] == 0
    finally:
        writer.rollback()
        writer.close()


def test_factual_workspaces_do_not_freeze_analysis_and_keep_context_warning(isolated_workspace):
    with closing(Repository(isolated_workspace)) as repo:
        context_id = save_context(repo, {"population": "adults"})
        withdraw_context(repo, context_id)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.session_state["analysis_contexts"] = {str(isolated_workspace): context_id}
    for page in ("心率", "睡眠", "体重", "有氧"):
        go(app, page)
        assert_page_ok(app)
        assert any("当前选择的适用声明已撤回或被替换" in warning.value for warning in app.warning)
    with sqlite3.connect(isolated_workspace) as conn:
        for table in ("analysis_run", "workflow_run", "workflow_use_check", "insight"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_body_workspaces_show_separate_sources_and_weight_cardio_without_writes(isolated_workspace):
    root = Element("HealthData")
    observed = datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=1)
    def record(kind, source, value, unit=None, hours=0):
        attrs = {"type": kind, "sourceName": source, "sourceVersion": "synthetic-1",
                 "device": source + "-device", "value": str(value),
                 "startDate": (observed - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S %z"),
                 "endDate": observed.strftime("%Y-%m-%d %H:%M:%S %z"),
                 "creationDate": observed.strftime("%Y-%m-%d %H:%M:%S %z")}
        if unit:
            attrs["unit"] = unit
        SubElement(root, "Record", attrs)
    for source, heart, sdnn, weight, hours in (("合成手表甲", 55, 30, 70, 3), ("合成手表乙", 65, 40, 80, 5)):
        record("HKQuantityTypeIdentifierRestingHeartRate", source, heart, "count/min")
        record("HKQuantityTypeIdentifierHeartRateVariabilitySDNN", source, sdnn, "ms")
        record("HKQuantityTypeIdentifierBodyMass", source, weight, "kg")
        record("HKCategoryTypeIdentifierSleepAnalysis", source, "HKCategoryValueSleepAnalysisAsleepCore", hours=hours)
    record("HKQuantityTypeIdentifierVO2Max", "合成手表甲", 42, "mL/(kg·min)")
    archive = isolated_workspace.parent / "synthetic-workspaces.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as zipped:
        zipped.writestr("export.xml", tostring(root))
    with closing(Repository(isolated_workspace)) as repo:
        assert import_apple_zip(archive, repo).records_inserted == 9
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    for page, field, expected in (("心率", "数值", [30, 40, 55, 65]),
                                   ("睡眠", "睡眠时长（小时）", [3, 5]),
                                   ("体重", "体重（kg）", [70, 80]),
                                   ("有氧", "VO₂ max（mL/kg/min）", [42])):
        go(app, page)
        assert_page_ok(app)
        tables = [table.value for table in app.dataframe if field in table.value.columns]
        assert sorted(value for table in tables for value in table[field].tolist()) == expected
        if page == "体重":
            assert not any("VO₂ max（mL/kg/min）" in table.value.columns for table in app.dataframe)
        if page == "有氧":
            assert not any("体重（kg）" in table.value.columns for table in app.dataframe)
        assert {expander.label for expander in app.expander} >= {"原始明细", "分析依据与范围"}
    with sqlite3.connect(isolated_workspace) as conn:
        assert conn.execute("SELECT count(*) FROM insight").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM analysis_run").fetchone()[0] == 0


def test_overview_direct_training_counts_only_completed_facts(isolated_workspace):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert_page_ok(app)
    assert not app.metric  # Missing health data is not a wall of zero-filled cards.
    assert not app.dataframe and not app.json
    app.button(key="overview_open_training").click().run()
    assert app.radio(key="main_workspace").value == "训练"
    UI["send"](app, "start_session")
    session = UI["snapshot"](app)["session"]
    assert UI["send"](app, "add_exercises", {"session_id": session["session_uuid"],
        "base_revision": session["revision"], "exercises": ["psa.ex.barbell_bench_press"]})["status"] == "saved"
    row = UI["snapshot"](app)["session"]["sets"][0]
    assert UI["send"](app, "save_set", {"set_id": row["set_uuid"], "base_revision": row["revision"],
        "complete": True, "changes": {"load_value": "32.5", "load_unit": "kg", "reps": "8", "rir": 0}})["status"] == "saved"
    go(app, "总览")
    assert next(item.value for item in app.metric if item.label == "完成训练") == "0 次"
    go(app, "力量")
    assert UI["send"](app, "end_session", {"session_id": session["session_uuid"],
        "base_revision": UI["snapshot"](app)["session"]["revision"]})["status"] == "saved"
    go(app, "总览")
    assert_page_ok(app)
    assert next(item.value for item in app.metric if item.label == "完成训练") == "1 次"
    with closing(Repository(isolated_workspace)) as repo:
        actual = TrainingService(repo).get_set(row["set_uuid"])
        assert float(actual["load_value"]) == 32.5 and actual["reps"] == 8 and actual["rir"] == 0
        assert not actual.get("reference_set") and not actual.get("reference_declared_at")


def test_settings_network_consent_survives_page_changes(isolated_workspace):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    go(app, "设置")
    app.radio(key="settings_section").set_value("模型与资料库").run()
    app.checkbox(key="_setting_network_consent").check().run()
    go(app, "心率")
    assert app.session_state["health_explanation_network_consent"] is True
    go(app, "设置")
    app.radio(key="settings_section").set_value("模型与资料库").run()
    assert app.checkbox(key="_setting_network_consent").value is True
    app.checkbox(key="_setting_network_consent").uncheck().run()
    assert app.session_state["health_explanation_network_consent"] is False


def test_short_custom_window_remains_valid_in_review(isolated_workspace):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    go(app, "心率")
    app.radio(key="body_period").set_value("自定义").run()
    app.number_input(key="analysis_window_days").set_value(1).run()
    go(app, "复盘")
    assert_page_ok(app)
    app.radio(key="review_section").set_value("问题分析").run()
    assert app.number_input(key="analysis_window_days").value == 1
    go(app, "心率")
    assert app.radio(key="body_period").value == "自定义"
    assert app.number_input(key="analysis_window_days").value == 1


def test_import_receipts_are_workspace_scoped_and_failure_replaces_old_success(isolated_workspace):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.session_state["workspace_import_results"] = {str(isolated_workspace): {
        "import": {"status": "completed", "records_inserted": 5}}}
    go(app, "设置")
    app.radio(key="settings_section").set_value("导入与同步").run()
    assert any("新增 5 条" in row.value for row in app.success)
    next(item for item in app.text_input if item.label == "Apple Health ZIP 路径").set_value("missing-synthetic.zip")
    next(item for item in app.button if item.label == "流式导入").click().run()
    assert not any("新增 5 条" in row.value for row in app.success)
    assert any("未完成" in row.value for row in app.warning)
    second = isolated_workspace.parent / "synthetic-second.sqlite3"
    next(item for item in app.text_input if item.label == "SQLite 路径").set_value(str(second))
    next(item for item in app.button if item.label == "保存工作区设置").click().run()
    assert_page_ok(app)
    assert not app.warning
    assert not any("本次导入" in row.value for row in app.success)
