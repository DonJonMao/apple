"""Full local app workspaces use their own routes and avoid opener write locks."""

import socket
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from healthzip.db.repository import Repository
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
