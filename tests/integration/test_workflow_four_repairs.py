"""Four workflow boundary regressions using isolated records and real pages."""
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService
from healthzip.workflows import (
    WorkflowRequest,
    check_current_use,
    load_analysis,
    load_run,
    run_workflow,
)
from healthzip.workflows.calendar import completed_periods
from healthzip.workflows.reports import markdown
from tests.app_navigation import go, legacy_analysis

HELP = runpy.run_path(str(Path(__file__).with_name("test_workflow_six_repairs.py")))
APP = Path(__file__).resolve().parents[2] / "app.py"


def open_app(path):
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    go(app, "设置")
    app.radio(key="settings_section").set_value("导入与同步").run()
    next(item for item in app.text_input if item.label == "SQLite 路径").set_value(str(path))
    next(item for item in app.button if item.label == "保存工作区设置").click().run()
    go(app, "复盘")
    legacy_analysis(app, "问题分析")
    app.button(key="review_compute").click().run()
    assert not app.exception
    return app


def add_current(svc, instance, exercise=None):
    session = svc.start_session("Synthetic current action")
    current = svc.add_exercise(session["id"], exercise or instance["catalog_id"], instance["condition"])
    svc.add_set(current["id"], planned={"reps_min": 8, "reps_max": 12, "rir": 2})
    return current


@pytest.mark.parametrize("period", ["week", "month"])
@pytest.mark.parametrize("feedback", ["b", "a", "both", "none"])
def test_partial_feedback_always_scoped_without_current_reference(tmp_path, monkeypatch, period, feedback):
    repo, svc, a, _, ids = HELP["W1"]["history"](tmp_path, monkeypatch, approved=False)
    for sid in ids:
        row = svc.get_set(sid)
        svc.delete_set(row["id"], base_revision=row["revision"])
    now = datetime.now(timezone.utc)
    periods = completed_periods(now.isoformat(), "UTC", period)
    historical = datetime.fromisoformat(periods[-1][0]) + timedelta(days=1)
    HELP["record"](svc, monkeypatch, a, days=(now-historical).total_seconds()/86400)
    HELP["record"](svc, monkeypatch, a, days=.1, exercise="psa.ex.smith_squat")
    b = add_current(svc, a, "psa.ex.smith_squat")
    candidates = {}
    for label, instance in (("a", a), ("b", b)):
        if feedback in {label, "both"}:
            candidate = HELP["freeze"](repo, svc, instance)
            candidates[label] = candidate["candidate_id"]
            svc.recommendation_feedback(candidate["candidate_id"], user_choice="declined",
                execution_state="not_executed", nonexecution_reason="user_choice")
    task = next(t for t in analyze(repo, 100)["strength_tasks"] if t["exercise_id"] == a["catalog_id"])
    run = run_workflow(repo, WorkflowRequest("W4", period=period, timezone="UTC", task_id=task["task_id"]),
                       knowledge_root=tmp_path / "missing")
    part = run["supplements"]["partial_current_period"]
    assert part["metric"] is None  # No current reference must not remove A's own feedback.
    metrics = part["followup"]
    rows = metrics["STR-27"]["value"] or []
    assert [r["recommendation_id"] for r in rows] == ([candidates["a"]] if "a" in candidates else [])
    expected = int("a" in candidates)
    assert metrics["STR-27"]["total_n"] == expected
    assert metrics["STR-28"]["total_n"] == expected
    assert metrics["STR-28"]["value"]["adoption_denominator"] == expected
    assert metrics["STR-28"]["value"]["execution_denominator"] == expected
    report_value = metrics["REPORT-RECOMMENDATION-FOLLOWUP"]["value"]
    for field in ("value", "total_n", "valid_n", "data_status"):
        assert report_value["execution"][field] == metrics["STR-27"][field]
        assert report_value["summary"][field] == metrics["STR-28"][field]
    other_task = next(t for t in analyze(repo, 100)["strength_tasks"] if t["exercise_id"] == b["catalog_id"])
    other_run = run_workflow(repo, WorkflowRequest("W4", period=period, timezone="UTC", task_id=other_task["task_id"]),
                             knowledge_root=tmp_path / "missing")
    other_metrics = other_run["supplements"]["partial_current_period"]["followup"]
    assert [r["recommendation_id"] for r in other_metrics["STR-27"]["value"] or []] == ([candidates["b"]] if "b" in candidates else [])
    assert other_metrics["STR-28"]["value"]["adoption_denominator"] == int("b" in candidates)
    report = "\n".join(markdown([run], repo=repo))
    if "b" in candidates:
        assert candidates["b"] not in report
    if "a" in candidates:
        assert candidates["a"] in report and "not_executed" in report
        svc.recommendation_feedback(candidates["a"], user_choice="accepted", execution_state="unknown")
    assert "\n".join(markdown([load_run(repo, run["run_id"])], repo=repo)) == report
    repo.close()


def test_real_app_invalid_cutoff_does_not_retire_selected_context(tmp_path, monkeypatch):
    repo, _, _, _, _ = HELP["W1"]["history"](tmp_path, monkeypatch, approved=False)
    app = open_app(repo.path)
    app.selectbox(key="workflow_population").select("adults")
    app.button(key="workflow_run").click().run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    scope = str(repo.path.resolve())
    original = app.session_state["analysis_contexts"][scope]
    frozen = repo.rows("SELECT run_id,result_json FROM workflow_run WHERE json_extract(request_json,'$.context_id')=?", (original,))
    app.selectbox(key="workflow_population").select("trained_adults")
    app.text_input(key="workflow_cutoff").set_value("invalid")
    app.button(key="workflow_run").click().run()
    assert app.error and not app.exception
    assert app.session_state["analysis_contexts"][scope] == original
    assert repo.one("SELECT count(*) FROM workflow_context_event WHERE context_id=?", (original,))[0] == 0
    app.run()
    assert not app.exception and app.button(key="workflow_run")
    app.text_input(key="workflow_cutoff").set_value("")
    app.button(key="workflow_run").click().run()
    assert not app.exception and not app.error
    current = app.session_state["analysis_contexts"][scope]
    assert current != original
    assert json.loads(repo.one("SELECT payload_json FROM workflow_context_revision WHERE context_id=?", (current,))[0]) == {"population": "trained_adults"}
    for row in frozen:
        assert repo.one("SELECT result_json FROM workflow_run WHERE run_id=?", (row["run_id"],))[0] == row["result_json"]
    repo.close()


def test_real_report_page_can_review_training_created_after_cutoff(tmp_path, monkeypatch):
    repo, svc, instance, _, _ = HELP["W1"]["history"](tmp_path, monkeypatch)
    app = open_app(repo.path)
    app.selectbox(key="workflow_kind").select("W4").run()
    app.selectbox(key="workflow_outcome").select("STR-11").run()
    app.button(key="workflow_run").click().run()
    assert not app.exception and not app.error
    key = "workflow_run_" + str(repo.path.resolve()) + "_W4"
    old = load_run(repo, app.session_state[key])
    current = add_current(svc, instance)
    app.run()
    app.selectbox(key="workflow_action_target").select(current["id"]).run()
    form = "workflow_long_" + current["id"]
    app.selectbox(key="strategy_" + form).select("heavier_lower_reps")
    app.text_input(key="loads_" + form).set_value("30,34,38")
    app.button(key="candidate_" + form).click().run()
    assert not app.exception and not app.error
    candidates = [r for r in svc.list_recommendations() if r["input_snapshot"]["session_exercise_id"] == current["id"]]
    assert len(candidates) == 1 and candidates[0]["candidate"]["proposed_change"]["load"] == 34
    assert load_run(repo, old["run_id"]) == old
    repo.close()


def mass_sample(repo, timestamp, value=80, identity="scale:mass", status="active"):
    bid = repo.create_batch(file_sha256=f"synthetic-{identity}-{value}-{status}", file_name="synthetic",
                            file_size=1, xml_member_path="synthetic.json")
    result = repo.insert_incremental_sample(bid, {"fingerprint": f"{identity}-{value}-{status}",
        "source_record_id": identity, "source_kind": "incremental", "record_status": status,
        "raw_type": "HKQuantityTypeIdentifierBodyMass", "canonical_type": "body_mass_kg",
        "raw_value": str(value), "raw_unit": "kg", "normalized_value": value,
        "normalized_unit": "kg", "unit_status": "valid", "start_utc": timestamp, "end_utc": timestamp,
        "source_name": "Synthetic scale", "device": "Synthetic device", "source_version": "1",
        "metadata_json": json.dumps({"protocol_id": "synthetic-fixed"}), "created_at": timestamp})
    repo.conn.commit()
    return result


def test_w2_interleaved_public_mass_revision_cannot_remain_current(tmp_path, monkeypatch):
    from healthzip.workflows import evidence
    repo, svc, _, _, ids = HELP["W1"]["history"](tmp_path, monkeypatch, approved=False)
    stamp = (datetime.fromisoformat(svc.get_set(ids[0])["ended_at"])-timedelta(days=1)).isoformat()
    assert mass_sample(repo, stamp) == "new"
    original = evidence.retrieve
    changed = False

    def revise(*args, **kwargs):
        nonlocal changed
        answer = original(*args, **kwargs)
        if not changed:
            changed = True
            other = Repository(repo.path)
            assert mass_sample(other, stamp, 90) == "updated"
            other.close()
        return answer

    monkeypatch.setattr(evidence, "retrieve", revise)
    try:
        run = run_workflow(repo, WorkflowRequest("W2", mode="retrospective"), knowledge_root=tmp_path / "missing")
    except ValueError as exc:
        assert "concurrent" in str(exc)
        assert repo.one("SELECT count(*) FROM workflow_run")[0] == 0
        assert repo.one("SELECT count(*) FROM analysis_run")[0] == 0
    else:
        masses = [p["value"] for ctx in run["supplements"]["pretraining_contexts"]
            for rows in (ctx["metrics"]["BODY-MASS-DAILY"]["value"] or {}).values() for p in rows]
        assert masses
        if check_current_use(repo, run["run_id"], knowledge_root=tmp_path / "missing")["status"] == "current":
            assert set(masses) == {90}
    assert changed
    repo.close()


def test_real_app_execution_failure_keeps_committed_declaration_selected(tmp_path, monkeypatch):
    from healthzip.workflows import evidence
    from healthzip.workflows.storage import context_as_of
    repo, _, _, _, ids = HELP["W1"]["history"](tmp_path, monkeypatch, approved=False)
    app = open_app(repo.path)
    app.selectbox(key="workflow_population").select("adults")
    app.button(key="workflow_run").click().run()
    scope = str(repo.path.resolve())
    old = app.session_state["analysis_contexts"][scope]
    retrieve = evidence.retrieve
    changed = False

    def interleave(*args, **kwargs):
        nonlocal changed
        answer = retrieve(*args, **kwargs)
        if not changed and args[3]["values"].get("population") == "trained_adults":
            changed = True
            other = Repository(repo.path)
            service = TrainingService(other)
            row = service.get_set(ids[-1])
            service.edit_set(row["id"], {"reps": 12}, base_revision=row["revision"])
            other.close()
        return answer

    with monkeypatch.context() as patch:
        patch.setattr(evidence, "retrieve", interleave)
        app.selectbox(key="workflow_population").select("trained_adults")
        app.button(key="workflow_run").click().run()
    assert changed and not app.exception
    assert any("concurrent" in e.value for e in app.error)
    new = app.session_state["analysis_contexts"][scope]
    assert new != old
    assert context_as_of(repo, new, datetime.now(timezone.utc).isoformat(), "prospective")["values"]["population"] == "trained_adults"
    app.run()
    assert not app.exception and app.button(key="workflow_run")
    app.button(key="workflow_run").click().run()
    assert not app.exception and not app.error
    repo.close()


@pytest.mark.parametrize("replacement", [False, True])
def test_real_app_retired_selection_has_explicit_reconfirmation(tmp_path, monkeypatch, replacement):
    from healthzip.workflows import save_context
    from healthzip.workflows.storage import withdraw_context
    repo, _, _, _, _ = HELP["W1"]["history"](tmp_path, monkeypatch, approved=False)
    app = open_app(repo.path)
    app.selectbox(key="workflow_population").select("adults")
    app.button(key="workflow_run").click().run()
    scope = str(repo.path.resolve())
    old = app.session_state["analysis_contexts"][scope]
    if replacement:
        other = save_context(repo, {"population": "healthy_adults"}, replaces_context_id=old)
    else:
        withdraw_context(repo, old)
        other = None
    history = repo.rows("SELECT run_id,result_json FROM workflow_run ORDER BY run_id")
    app.run()
    assert not app.exception and app.button(key="workflow_run")
    assert any("声明已撤回或被替换" in w.value for w in app.warning)
    assert app.session_state["analysis_contexts"][scope] == old  # Never auto-pick another declaration.
    assert any("训练分析" in h.value for h in app.subheader)
    app.button(key="workflow_run").click().run()
    assert not app.exception and not app.error
    new = app.session_state["analysis_contexts"][scope]
    assert new not in {old, other}
    app.run()
    assert not any("声明已撤回或被替换" in w.value for w in app.warning)
    for row in history:
        assert repo.one("SELECT result_json FROM workflow_run WHERE run_id=?", (row["run_id"],))[0] == row["result_json"]
    repo.close()


@pytest.mark.parametrize("period,age", [("week", 8), ("month", 35)])
def test_historical_report_current_action_separates_bounds_and_current_targets(tmp_path, monkeypatch, period, age):
    from healthzip.advice import freeze_candidate
    repo, svc, instance, _, _ = HELP["W1"]["history"](tmp_path, monkeypatch)
    if period == "month":
        HELP["record"](svc, monkeypatch, instance, days=70)
        HELP["record"](svc, monkeypatch, instance, days=80)
    task = next(t for t in analyze(repo, 100)["strength_tasks"] if t["exercise_id"] == instance["catalog_id"])
    old = run_workflow(repo, WorkflowRequest("W4", period=period, task_id=task["task_id"], timezone="UTC",
        cutoff_time=(datetime.now(timezone.utc)-timedelta(days=age)).isoformat()), knowledge_root=tmp_path / "missing")
    original = load_analysis(repo, old["run_id"])
    text = "\n".join(markdown([old], repo=repo))
    recorded = original["metrics"]["STR-11"]["value"][0]
    revised = svc.get_set(str(recorded["id"]).removeprefix("strength_set:"))
    svc.edit_set(revised["id"], {"reps": 11}, base_revision=revised["revision"])
    current = add_current(svc, instance)
    row = svc.add_set(current["id"], planned={"reps_min": 7, "reps_max": 12, "rir": 3})
    row = svc.update_set_target(row["id"], {"reps_min": 6, "reps_max": 11, "rir": 2}, base_revision=row["revision"])
    effective = svc.current_targets(current["id"])
    target = next(t for t in effective["sets"] if t["set_uuid"] == row["set_uuid"])
    request = WorkflowRequest(**{**old["request"], "source_run_id": old["run_id"]})

    def freeze():
        return freeze_candidate(repo, svc, svc.get_session(current["session_id"]), current, effective, target,
            [30, 34, 38], "heavier_lower_reps", review_request=request)

    candidate = freeze()
    assert candidate["candidate"]["proposed_change"]["load"] == 34
    assert candidate["candidate"]["target_range"]["reps_min"] == 6
    ref = candidate["input_snapshot"]["analysis_review"]
    review = load_run(repo, ref["run_id"])
    snapshot = load_analysis(repo, ref["run_id"])
    if datetime.fromisoformat(revised["ended_at"]) >= datetime.fromisoformat(snapshot["window_start"]):
        assert next(r for r in snapshot["metrics"]["STR-11"]["value"] if r["id"] == recorded["id"])["reps"] == 11
    else:
        assert recorded["id"] not in {r["id"] for r in snapshot["metrics"]["STR-11"]["value"]}
    assert recorded["reps"] == 10
    assert review["request"]["cutoff_time"] > svc.get_session(current["session_id"])["started_at"]
    for key in ("window_start", "window_end"):
        assert snapshot[key] != original[key]
        assert review["supplements"]["source_report"][key] == original[key]
    assert datetime.fromisoformat(snapshot["window_start"]) == datetime.fromisoformat(snapshot["cutoff_time"])-timedelta(days=30)
    assert snapshot["window_end"] == snapshot["cutoff_time"]
    assert ref["source_run_id"] == old["run_id"]
    assert review["parent_run_id"] is None  # Cross-workflow references are not parent links.
    assert review["supplements"]["source_report"]["cutoff_time"] == old["request"]["cutoff_time"]
    with pytest.raises(ValueError, match="successor_must_keep_workflow_identity"):
        run_workflow(repo, WorkflowRequest("W1"), parent_run_id=old["run_id"])
    repeated = freeze()
    assert repeated["candidate_id"] == candidate["candidate_id"]
    assert repeated["input_snapshot"] == candidate["input_snapshot"]
    later = load_run(repo, repeated["current_analysis_review"]["run_id"])
    assert later["request"]["source_run_id"] == old["run_id"]
    assert later["parent_run_id"] == review["run_id"]
    assert len(svc.list_recommendations()) == 1
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    assert "\n".join(markdown([old], repo=repo)) == text
    assert load_analysis(repo, old["run_id"]) == original
    assert "历史比较范围" in "\n".join(markdown([review], repo=repo))
    repo.close()


@pytest.mark.parametrize("mutation", ["delete", "late", "unrelated", "outside_window", "none"])
@pytest.mark.parametrize("during", [False, True])
def test_w2_mass_scope_detects_removal_and_late_arrival(tmp_path, monkeypatch, mutation, during):
    from healthzip.importers.incremental import import_json_payload
    from healthzip.workflows import evidence
    repo, svc, _, _, ids = HELP["W1"]["history"](tmp_path, monkeypatch, approved=False)
    stamp = (datetime.fromisoformat(svc.get_set(ids[0])["ended_at"])-timedelta(days=1)).isoformat()
    if mutation != "late":
        assert mass_sample(repo, stamp) == "new"
    request = WorkflowRequest("W2", mode="retrospective")
    retrieve = evidence.retrieve
    changed = False

    def mutate():
        nonlocal changed
        if changed:
            return
        changed = True
        other = Repository(repo.path)
        if mutation == "delete":
            result = import_json_payload({"deleted": [{"id": "mass"}]}, other, source_name="scale", source_kind="incremental")
            assert result.deleted == 1
        elif mutation == "late":
            assert mass_sample(other, stamp, 90) == "new"
        elif mutation == "unrelated":
            TrainingService(other).start_session("Unrelated empty draft")
        elif mutation == "outside_window":
            assert mass_sample(other, (datetime.now(timezone.utc)-timedelta(days=200)).isoformat(), 90, identity="scale:unrelated") == "new"
        other.close()

    def interleaved(*args, **kwargs):
        answer = retrieve(*args, **kwargs)
        mutate()
        return answer

    if during:
        monkeypatch.setattr(evidence, "retrieve", interleaved)
    try:
        run = run_workflow(repo, request, knowledge_root=tmp_path / "missing")
    except ValueError as exc:
        assert during and mutation in {"delete", "late"} and "concurrent" in str(exc)
        assert repo.one("SELECT count(*) FROM workflow_run")[0] == 0
        assert repo.one("SELECT count(*) FROM analysis_run")[0] == 0
    else:
        if not during:
            mutate()
        current = check_current_use(repo, run["run_id"], knowledge_root=tmp_path / "missing")
        assert current["status"] == ("needs_review" if mutation in {"delete", "late"} else "current")
        if mutation in {"delete", "late"}:
            assert "relevant_records_or_targets_changed" in current["reason_codes"]
        assert load_run(repo, run["run_id"]) == run
    repo.close()


@pytest.mark.parametrize("mutation", ["deleted_target", "condition", "withdrawn_context"])
def test_report_action_still_rejects_invalid_current_target_or_declaration(tmp_path, monkeypatch, mutation):
    from healthzip.advice import freeze_candidate
    from healthzip.workflows import save_context
    from healthzip.workflows.storage import withdraw_context
    repo, svc, instance, _, _ = HELP["W1"]["history"](tmp_path, monkeypatch)
    context_id = save_context(repo, {"population": "adults"})
    task = analyze(repo)["strength_tasks"][0]
    report = run_workflow(repo, WorkflowRequest("W4", task_id=task["task_id"], context_id=context_id))
    current = add_current(svc, instance)
    effective = svc.current_targets(current["id"])
    target = effective["sets"][0]
    if mutation == "deleted_target":
        row = svc.get_set(target["set_uuid"])
        svc.delete_set(row["id"], base_revision=row["revision"])
    elif mutation == "condition":
        current = svc.update_condition(current["id"], {**current["condition"], "rom_protocol": "different-recorded-rom"},
                                       base_revision=current["revision"])
        effective = svc.current_targets(current["id"])
        target = effective["sets"][0]
    else:
        withdraw_context(repo, context_id)
    before = repo.one("SELECT count(*) FROM workflow_run")[0]
    with pytest.raises(ValueError):
        freeze_candidate(repo, svc, svc.get_session(current["session_id"]), current, effective, target,
            [30, 34, 38], "heavier_lower_reps",
            review_request=WorkflowRequest(**{**report["request"], "source_run_id": report["run_id"]}))
    assert not svc.list_recommendations()
    assert repo.one("SELECT count(*) FROM workflow_run")[0] == before
    assert load_run(repo, report["run_id"]) == report
    repo.close()


@pytest.mark.parametrize("period", ["week", "month"])
def test_two_exercises_report_new_action_feedback_and_frozen_page_download(tmp_path, monkeypatch, period):
    import streamlit as st

    from healthzip.advice import freeze_candidate
    from healthzip.workflows.reports import review_analysis
    repo, svc, instance, _, _ = HELP["W1"]["history"](tmp_path, monkeypatch)
    HELP["record"](svc, monkeypatch, instance, days=12, exercise="psa.ex.smith_squat")
    HELP["record"](svc, monkeypatch, instance, days=.1, exercise="psa.ex.smith_squat")
    HELP["record"](svc, monkeypatch, instance, days=40)
    tasks = analyze(repo, 100)["strength_tasks"]
    a_task = next(t for t in tasks if t["exercise_id"] == instance["catalog_id"])
    old = run_workflow(repo, WorkflowRequest("W4", period=period, task_id=a_task["task_id"]))
    old_text = "\n".join(markdown([old], repo=repo))
    current = add_current(svc, instance)
    effective = svc.current_targets(current["id"])
    request = WorkflowRequest(**{**old["request"], "source_run_id": old["run_id"]})
    candidates = []
    for _ in range(2):
        candidates.append(freeze_candidate(repo, svc, svc.get_session(current["session_id"]), current,
            effective, effective["sets"][0], [30, 34, 38], "heavier_lower_reps", review_request=request))
    cid = candidates[0]["candidate_id"]
    assert candidates[1]["candidate_id"] == cid
    svc.recommendation_feedback(cid, user_choice="declined", execution_state="not_executed", nonexecution_reason="user_choice")
    b = add_current(svc, instance, "psa.ex.smith_squat")
    other = HELP["freeze"](repo, svc, b)
    other_id = other["candidate_id"]
    svc.recommendation_feedback(other_id, user_choice="accepted", execution_state="not_executed", nonexecution_reason="user_choice")
    runs = review_analysis(repo, analyze(repo), period=period, knowledge_root=tmp_path / "missing")
    selected = next(r for r in runs if r["request"]["task_id"] == a_task["task_id"])
    assert len(svc.list_recommendations()) == 2
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 2
    assert [r["recommendation_id"] for r in selected["supplements"]["partial_current_period"]["followup"]["STR-27"]["value"]] == [cid]
    captured = {}
    download = st.download_button

    def capture(label, data, **kwargs):
        captured[label] = data
        return download(label, data, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(st, "download_button", capture)
        app = AppTest.from_string(f'''from healthzip.db.repository import Repository
from healthzip.ui.workflow_page import render_run
from healthzip.workflows import load_run
repo = Repository({str(repo.path)!r})
try:
    render_run(repo, load_run(repo, {selected["run_id"]!r}))
finally:
    repo.close()
''', default_timeout=30).run()
    assert not app.exception and not app.error
    payload = json.loads(captured["下载本次本地结果"])
    assert payload["workflow"] == selected
    assert payload["snapshot"] == load_analysis(repo, selected["run_id"])
    screen = "\n".join(e.value for e in app.json) + "\n".join(e.value for e in app.markdown)
    assert cid in screen and other_id not in screen
    assert other_id not in captured["下载本次本地结果"]
    before = captured["下载本次本地结果"]
    svc.recommendation_feedback(cid, user_choice="accepted", execution_state="unknown")
    assert json.loads(before)["workflow"] == load_run(repo, selected["run_id"])
    assert "\n".join(markdown([old], repo=repo)) == old_text
    repo.close()


@pytest.mark.parametrize("wid", ["W1", "W2", "W4", "W5"])
def test_consumed_body_measurement_rows_are_dependencies(tmp_path, monkeypatch, wid):
    repo, svc, _, _, ids = HELP["W1"]["history"](tmp_path, monkeypatch, approved=False)
    stamp = (datetime.fromisoformat(svc.get_set(ids[0])["ended_at"])-timedelta(days=1)).isoformat()
    data = {"fingerprint": "synthetic-mass-csv", "measured_at": stamp, "canonical_type": "body_mass_kg",
            "value": 80, "unit": "kg", "source": "Synthetic scale"}
    assert repo.insert_external("body_measurement", data, data.keys())
    task_id = analyze(repo)["strength_tasks"][0]["task_id"] if wid == "W4" else None
    run = run_workflow(repo, WorkflowRequest(wid, task_id=task_id, mode="retrospective"), knowledge_root=tmp_path / "missing")
    assert any(key.startswith("body_measurement:") for key in run["dependencies"]["record_hashes"])
    assert check_current_use(repo, run["run_id"], knowledge_root=tmp_path / "missing")["status"] == "current"
    repo.close()
