"""Current training flow: real repositories, public services and real app pages."""
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from healthzip.analytics.v13 import analyze
from healthzip.workflows import load_run, save_context
from healthzip.workflows.reports import markdown, review_analysis
from healthzip.workflows.storage import withdraw_context
from tests.app_navigation import go, legacy_analysis

HELP = runpy.run_path(str(Path(__file__).with_name("test_workflow_four_repairs.py")))


@pytest.mark.parametrize("period", ["week", "month"])
@pytest.mark.parametrize("training", [True, False])
def test_frozen_joint_report_has_current_body_and_training_not_only_old_periods(tmp_path, monkeypatch, period, training):
    from healthzip.workflows.period_report import create_report, load_report

    repo, svc, instance, _, ids = HELP["HELP"]["W1"]["history"](tmp_path, monkeypatch, approved=False)
    measured = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    HELP["mass_sample"](repo, measured, 81)
    if not training:
        for identity in ids:
            row = svc.get_set(identity)
            svc.delete_set(row["id"], base_revision=row["revision"])
    else:
        # Body input is imported before this real session starts.
        session = svc.start_session("Synthetic report current")
        new = svc.add_exercise(session["id"], instance["catalog_id"], instance["condition"])
        target = svc.add_set(new["id"], planned={"reps_min": 7, "reps_max": 13, "rir": 2})
        FLOW = runpy.run_path(str(Path(__file__).with_name("test_current_training_flow.py")))
        FLOW["finish"](svc, target, load=34, reps=9)
        svc.end_session(session["id"])
    report = create_report(repo, analyze(repo), period=period, include_details=True)
    masses = report["current"]["metrics"]["BODY-MASS-DAILY"]
    assert {p["value"] for values in masses["value"].values() for p in values} == {81}
    assert "81" in report["markdown"] and "kg" in report["markdown"] and "Synthetic scale" in report["markdown"]
    current_runs = [load_run(repo, identity) for identity in report["workflow_run_ids"]]
    joins = [ctx for run in current_runs for ctx in run["supplements"].get("training_session_contexts", [])]
    if training:
        relevant = next(ctx for ctx in joins if ctx["session_id"] == session["id"])
        assert relevant["actual_records"][0]["reps"] == 9
        assert relevant["actual_records"][0]["rir"] == 2
        before = relevant["metrics"]["BODY-MASS-DAILY"]
        assert {p["value"] for values in before["value"].values() for p in values} == {81}
        # Readable reports summarize dates; the complete time and original body
        # context remain frozen in their referenced workflow and audit export.
        assert relevant["training_started_at"][:10] in report["markdown"]
        from healthzip.workflows.report_objects import audit_bundle
        bundle = audit_bundle(repo, report["report_id"])
        assert relevant["training_started_at"] in json.dumps(bundle)
    else:
        assert not joins
        assert "本期尚无可建立时间对应的训练记录" in report["markdown"]
    HELP["mass_sample"](repo, measured, 82)
    assert load_report(repo, report["report_id"], include_details=True) == report
    later = create_report(repo, analyze(repo), period=period, include_details=True)
    assert later["report_id"] != report["report_id"]
    assert {p["value"] for values in later["current"]["metrics"]["BODY-MASS-DAILY"]["value"].values() for p in values} == {82}
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


@pytest.mark.parametrize("history_kind", ["improving", "none"])
def test_normal_draft_reads_body_without_long_review_or_fake_records(tmp_path, monkeypatch, history_kind):
    from healthzip.advice import build_advice_context
    from healthzip.workflows import WorkflowRequest, load_analysis, run_workflow

    repo, svc, instance, target, ids = HELP["HELP"]["W1"]["history"](tmp_path, monkeypatch, approved=False)
    if history_kind == "none":
        for identity in ids:
            row = svc.get_set(identity)
            svc.delete_set(row["id"], base_revision=row["revision"])
    else:
        row = svc.get_set(ids[-1])
        svc.edit_set(row["id"], {"reps": 12}, base_revision=row["revision"])
    measured = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    HELP["mass_sample"](repo, measured, 81)
    count = repo.one("SELECT count(*) FROM strength_set")[0]
    run = run_workflow(repo, WorkflowRequest("W1", session_id=instance["session_id"],
        session_exercise_id=instance["id"], selected_set_uuid=target["set_uuid"]))
    assert run["nodes"][2]["long_term_review_trigger"] is False
    background = run["supplements"]["current_body_context"]
    mass = background["metrics"]["BODY-MASS-DAILY"]
    points = [p for values in mass["value"].values() for p in values]
    assert [p["value"] for p in points] == [81]
    assert mass["source_record_ids"] and mass["unit"] == "kg"
    assert "STATE-SLEEP-COVERAGE" in background["metrics"]
    assert svc.get_set(target["set_uuid"])["completion_state"] == "draft"
    assert repo.one("SELECT count(*) FROM strength_set")[0] == count
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    assert load_analysis(repo, run["run_id"])["target"]["selected_target"]["set_uuid"] == target["set_uuid"]
    automatic = build_advice_context(repo, instance["session_id"], instance["id"], target["set_uuid"],
        [30, 34, 38], "heavier_lower_reps", generation_origin="automatic_training")
    explicit = build_advice_context(repo, instance["session_id"], instance["id"], target["set_uuid"],
        [30, 34, 38], "heavier_lower_reps")
    assert automatic["context"]["user_choice"] is None
    assert explicit["context"]["user_choice"] == "requested_strategy_review"
    assert automatic["context"]["generation_origin"] == "automatic_training"
    frozen = json.dumps(background, sort_keys=True)
    HELP["mass_sample"](repo, measured, 83)
    assert json.dumps(load_run(repo, run["run_id"])["supplements"]["current_body_context"], sort_keys=True) == frozen
    later = run_workflow(repo, WorkflowRequest("W1", session_id=instance["session_id"],
        session_exercise_id=instance["id"], selected_set_uuid=target["set_uuid"]))
    assert {p["value"] for values in later["supplements"]["current_body_context"]["metrics"]["BODY-MASS-DAILY"]["value"].values()
            for p in values} == {83}
    repo.close()


@pytest.mark.parametrize("retirement", ["withdrawn", "superseded"])
def test_report_retired_context_preserves_facts_and_identity(tmp_path, monkeypatch, retirement):
    repo, _, _, _, _ = HELP["HELP"]["W1"]["history"](tmp_path, monkeypatch, approved=False)
    selected = save_context(repo, {"population": "adults"})
    snapshot = analyze(repo, context={"workflow_context_id": selected})
    original = review_analysis(repo, snapshot, include_background=True)
    old_text = "\n".join(markdown(original, repo=repo))
    if retirement == "withdrawn":
        withdraw_context(repo, selected)
    else:
        save_context(repo, {"population": "trained_adults"}, replaces_context_id=selected)
    # Deliberately keep the earlier analysis cutoff: retirement is checked at
    # generation too; it must not silently authorize a fresh report.
    current = review_analysis(repo, snapshot, include_background=True)
    for run in current:
        restriction = run["supplements"]["context_restriction"]
        assert run["context_id"] == selected
        assert restriction["historical_values"] == {"population": "adults"}
        assert restriction["values"] == {}
        assert restriction["lifecycle_events"][-1]["kind"] == retirement
    strength = next(r for r in current if r["task_selection"])
    assert strength["facts"] and strength["supplements"]["long_term_review"]["series"][0]["rir_used_n"] == 5
    text = "\n".join(markdown(current, repo=repo))
    assert selected in text and "workflow_context_withdrawn_or_superseded" in text
    assert "依赖该声明的解释需重新确认" in text and "30" in text
    assert "\n".join(markdown(original, repo=repo)) == old_text
    assert all(load_run(repo, r["run_id"]) == r for r in original)
    repo.close()


@pytest.mark.parametrize("entry", ["分析", "报告"])
@pytest.mark.parametrize("retirement", ["withdrawn", "superseded"])
def test_real_report_buttons_after_retirement(tmp_path, monkeypatch, entry, retirement):
    import streamlit as st

    repo, _, _, _, _ = HELP["HELP"]["W1"]["history"](tmp_path, monkeypatch, approved=False)
    captured = {}
    download = st.download_button

    def capture(label, data, **kwargs):
        captured[label] = data
        return download(label, data, **kwargs)

    monkeypatch.setattr(st, "download_button", capture)
    app = HELP["open_app"](repo.path)
    app.selectbox(key="workflow_population").select("adults")
    app.button(key="workflow_run").click().run()
    assert not app.exception
    selected = app.session_state["analysis_contexts"][str(repo.path.resolve())]
    before = repo.rows("SELECT run_id,result_json FROM workflow_run")
    if retirement == "withdrawn":
        withdraw_context(repo, selected)
    else:
        save_context(repo, {"population": "trained_adults"}, replaces_context_id=selected)
    go(app, "复盘")
    legacy_analysis(app, "问题分析" if entry == "分析" else "报告")
    label = "生成当前周期复盘" if entry == "分析" else "生成 Markdown 报告"
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception, [e.message for e in app.exception]
    if entry == "分析":
        text = captured["下载周期复核报告"]
        payload = json.loads(captured["下载本周期完整结果"])
        assert payload["workflow_reviews"]
    else:
        text = (tmp_path / "reports/latest.md").read_text()
    assert selected in text and "workflow_context_withdrawn_or_superseded" in text
    assert "依赖该声明的解释需重新确认" in text
    # Compact prose need not repeat frozen details to reach an arbitrary length.
    assert repo.one("SELECT COUNT(*) FROM workflow_run")[0] >= len(before)
    for row in before:
        assert repo.one("SELECT result_json FROM workflow_run WHERE run_id=?", (row["run_id"],))[0] == row["result_json"]
    repo.close()
