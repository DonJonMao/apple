"""The report page retains arbitrary-window Markdown from current local facts."""
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from streamlit.testing.v1 import AppTest

from healthzip.db.repository import Repository
from healthzip.workflows.storage import save_context, withdraw_context


def _sample(repo, age, value):
    when = (datetime.now(timezone.utc) - timedelta(days=age)).isoformat()
    batch = repo.create_batch(file_sha256=f"synthetic-report-{value}", file_name="synthetic",
                              file_size=0, xml_member_path="")
    repo.insert_sample(batch, {
        "fingerprint": f"synthetic-report-{value}", "raw_type": "HKQuantityTypeIdentifierBodyMass",
        "canonical_type": "body_mass_kg", "raw_value": str(value), "raw_unit": "kg",
        "normalized_value": value, "normalized_unit": "kg", "unit_status": "valid",
        "start_utc": when, "end_utc": when, "source_name": "Synthetic scale",
        "created_at": when,
    })
    repo.conn.commit()


@pytest.mark.parametrize("withdrawn", [False, True])
def test_current_window_markdown_uses_new_facts_range_and_declaration(tmp_path, monkeypatch, withdrawn):
    monkeypatch.chdir(tmp_path)
    repo = Repository(tmp_path / "synthetic.sqlite3")
    _sample(repo, 2, 70)
    original_context = save_context(repo, {"population": "adults"})
    workspace = str(repo.path.resolve())
    script = f'''import streamlit as st
from healthzip.db.repository import Repository
from healthzip.ui.review_page import render_review
st.session_state.setdefault("analysis_contexts", {{{workspace!r}: {original_context!r}}})
repo = Repository({str(repo.path)!r})
try:
    render_review(repo, timezone_name="UTC")
finally:
    repo.close()
'''
    app = AppTest.from_string(script, default_timeout=60).run()
    app.number_input(key="review_window_days").set_value(7)
    app.button(key="review_compute").click().run()
    assert not app.exception and not app.error
    saved_key = "review_snapshot:" + workspace + ":UTC"
    old_cutoff = app.session_state[saved_key]["value"]["v13"]["cutoff_time"]
    frozen = [tuple(row) for row in repo.rows("SELECT run_id,result_json FROM workflow_run ORDER BY run_id")]

    # Records and the selected declaration change after the displayed analysis.
    _sample(repo, 1, 71)
    _sample(repo, 15, 93)
    selected = save_context(repo, {"population": "healthy_adults"}, replaces_context_id=original_context)
    app.session_state["analysis_contexts"] = {workspace: selected}
    if withdrawn:
        withdraw_context(repo, selected)
    app.radio(key="review_section").set_value("报告").run()
    app.selectbox(key="review_report_period").select("当前分析窗口").run()
    output = tmp_path / "current-window.md"
    next(widget for widget in app.text_input if widget.label == "报告输出路径").set_value(str(output))
    next(widget for widget in app.button if widget.label == "生成 Markdown 报告").click().run()
    assert not app.exception and not app.error, [item.value for item in app.error]
    text = output.read_text()
    snapshot = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1))
    assert snapshot["window_days"] == 7
    assert datetime.fromisoformat(snapshot["window_end"]) - datetime.fromisoformat(snapshot["window_start"]) == timedelta(days=7)
    assert snapshot["cutoff_time"] > old_cutoff
    assert snapshot["selection_context"]["workflow_context_id"] == selected
    values = {point["value"] for points in snapshot["metrics"]["BODY-MASS-DAILY"]["value"].values() for point in points}
    assert values == {70, 71}
    assert "## 同一分析核心的复核" in text
    if withdrawn:
        assert "workflow_context_withdrawn_or_superseded" in text
    assert any(button.label == "下载当前分析窗口报告" for button in app.get("download_button"))
    for run_id, payload in frozen:
        assert repo.one("SELECT result_json FROM workflow_run WHERE run_id=?", (run_id,))[0] == payload
    # Ordinary rerenders and changing report tabs do not generate new reports.
    count = repo.one("SELECT count(*) FROM workflow_run")[0]
    app.run()
    assert repo.one("SELECT count(*) FROM workflow_run")[0] == count
    app.radio(key="review_section").set_value("周月复盘").run()
    assert app.selectbox(key="review_report_period").value == "本周"
    assert not app.exception and not app.error
    repo.close()


def test_current_window_report_preserves_explicit_historical_cutoff(tmp_path, monkeypatch):
    from healthzip.analytics.core import all_analysis
    from healthzip.analytics.v13 import analyze

    monkeypatch.chdir(tmp_path)
    repo = Repository(tmp_path / "synthetic-history.sqlite3")
    _sample(repo, 3, 70)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    value = all_analysis(repo, 7, timezone_name="UTC")
    value["v13"] = analyze(repo, 7, cutoff_time=cutoff, timezone_name="UTC", retrospective=True)
    _sample(repo, 1, 72)
    workspace = str(repo.path.resolve())
    script = f'''from healthzip.db.repository import Repository
from healthzip.ui.review_page import render_review
repo = Repository({str(repo.path)!r})
try:
    render_review(repo, timezone_name="UTC")
finally:
    repo.close()
'''
    app = AppTest.from_string(script, default_timeout=60).run()
    app.session_state["review_snapshot:" + workspace + ":UTC"] = {
        "value": value, "revision": [], "days": 7,
    }
    app.number_input(key="review_window_days").set_value(7)
    app.radio(key="review_section").set_value("报告").run()
    app.selectbox(key="review_report_period").select("当前分析窗口").run()
    output = tmp_path / "historical-window.md"
    next(widget for widget in app.text_input if widget.label == "报告输出路径").set_value(str(output))
    next(widget for widget in app.button if widget.label == "生成 Markdown 报告").click().run()
    assert not app.exception and not app.error
    snapshot = json.loads(re.search(r"```json\n(.*?)\n```", output.read_text(), re.S).group(1))
    assert snapshot["cutoff_time"] == cutoff
    assert snapshot["cutoff_mode"] == "explicit" and snapshot["retrospective"] is True
    assert snapshot["window_start"] == value["v13"]["window_start"]
    assert snapshot["window_end"] == value["v13"]["window_end"]
    values = {point["value"] for points in snapshot["metrics"]["BODY-MASS-DAILY"]["value"].values() for point in points}
    assert values == {70}
    repo.close()
