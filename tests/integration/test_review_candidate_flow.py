"""Review R03/R08: candidate tasks start from visible training controls.

Knowledge authority is synthetic and confined to pytest's temporary directory.
Training inputs, protocols, targets, execution and feedback use real UI controls.
"""

import pytest

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService


def open_app(path):
    from streamlit.testing.v1 import AppTest

    return AppTest.from_string(
        "from healthzip.db.repository import Repository\n"
        "from healthzip.ui.training_page import render_training\n"
        f"repo=Repository({str(path)!r})\nrender_training(repo)\nrepo.close()"
    ).run(timeout=30)


def current(path):
    repo = Repository(path)
    try:
        svc = TrainingService(repo)
        return svc.get_session(svc.list_sessions()[0]["id"])
    finally:
        repo.close()


def start_with_exercise(app, path):
    app.text_input(key="start_name").set_value("Synthetic review trial")
    app.button(key="training_start").click().run()
    app.text_input(key="session_selector_query").set_value("杠铃卧推").run()
    app.checkbox(key="session_condition_confirmed").check()
    next(b for b in app.button if b.label == "添加到本次训练").click().run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    return current(path)["exercises"][0]


def test_r03_visible_strategy_choice(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "trial.sqlite3"
    app = open_app(path)
    instance = start_with_exercise(app, path)
    assert "strategy_" + instance["id"] in {w.key for w in app.selectbox}


def test_r08_feedback_remains_after_finishing_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "feedback.sqlite3"
    app = open_app(path)
    instance = start_with_exercise(app, path)
    app.button(key="candidate_" + instance["id"]).click().run()
    assert not app.exception and not app.error
    repo = Repository(path)
    record = TrainingService(repo).list_recommendations()[0]
    repo.close()

    next(b for b in app.button if b.label == "结束训练并保存反馈").click().run()
    assert not app.exception and not app.error
    cid = record["candidate_id"]
    assert "history_feedback_" + cid in {b.key for b in app.button}
    app.selectbox(key="history_choice_" + cid).set_value("declined")
    app.selectbox(key="history_execution_" + cid).set_value("not_executed")
    app.text_input(key="history_reason_" + cid).set_value("Synthetic: chose to stop")
    app.button(key="history_feedback_" + cid).click().run()
    assert not app.exception and not app.error
    repo = Repository(path)
    saved = TrainingService(repo).list_recommendations()[0]
    assert saved["feedback"][-1]["user_choice"] == "declined"
    assert saved["feedback"][-1]["execution_state"] == "not_executed"
    assert saved["input_snapshot"] == record["input_snapshot"]
    repo.close()


def synthetic_authority(root, basis):
    from healthzip.knowledge import KnowledgeWorkbench

    knowledge = KnowledgeWorkbench(root)
    try:
        knowledge.seed()
        version = knowledge.lib.record_version(
            "S5", b"Synthetic candidate task rule; no human efficacy evidence.", "fulltext",
            {"url": "https://example.org/synthetic-ui-test"}, {"title": "Synthetic UI fixture"},
            {"index_allowed": True, "license_id": "CC0"}, "matched",
            [{"text": "Synthetic: a user-selected harder available setting and lower repetition task may be recorded as an optional trial.",
              "locator": {"xpath": "/article/body/p"}}],
        )
        span = version + ":s00000"
        knowledge.review_theory(
            "TC-progression-load-repetition-options", "0.1.0",
            reviewer="SYNTHETIC qualified reviewer role for software acceptance only",
            reviewer_kind="qualified_human_review", authority="progression_candidate",
            rationale="Synthetic permission fixture; not a real professional review or efficacy claim.",
            implementation_tests=[__name__ + "::test_visible_candidate_task_end_to_end"],
            applicability={"required": {"load_basis": basis}, "scope": "synthetic software acceptance only"},
            evidence_links=[{"source_id": "S5", "source_version_id": version, "span_ids": [span]}],
            claims=[{"text": "Synthetic optional task trial", "span_ids": [span], "support_rationale": "Synthetic software-only assertion."}],
        )
    finally:
        knowledge.close()


def configure_condition(app, prefix, *, complete_protocol=True):
    app.selectbox(key=prefix + "_basis").set_value("external_total_kg")
    app.checkbox(key=prefix + "_confirmed").check()
    app.selectbox(key=prefix + "_side").set_value("both")
    app.selectbox(key=prefix + "_repmeaning").set_value("simultaneous")
    app.text_input(key=prefix + "_rom").set_value("User-declared full comfortable range")
    app.text_input(key=prefix + "_settings").set_value("Fixed user setup")
    app.checkbox(key=prefix + "_settings_ok").check()
    if complete_protocol:
        for field, value in (("id", "user-reference"), ("version", "1"),
                             ("policy", "predeclared-first-work-set"), ("effort", "stop-at-rir-2"),
                             ("tempo", "controlled-no-pause"), ("rest", "user-fixed-180-seconds")):
            app.text_input(key=prefix + "_protocol_" + field).set_value(value)


def finish_reference(app, path, instance, load, reps, *, reference=True, unit="kg"):
    selected = next(x for x in current(path)["exercises"] if x["id"] == instance["id"])
    row = selected["sets"][-1]
    key = "set_" + row["set_uuid"]
    if reference:
        app.button(key=key + "_reference").click().run()
    app.button(key=key + "_in_progress").click().run()
    app.selectbox(key=key + "_unit").set_value(unit).run()
    for field, value in (("load_value", load), ("reps", reps), ("rir", 2)):
        app.text_input(key=key + "_" + field).set_value(str(value)).run()
        assert not app.exception and not app.error, [e.value for e in app.error]
    app.selectbox(key=key + "_quality").set_value("acceptable")
    app.selectbox(key=key + "_stop").set_value("target_rir")
    app.button(key=key + "_completed").click().run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    return row["set_uuid"]


@pytest.mark.parametrize("mode,strategy,prior_reps,approved,complete_protocol", [
    ("template", "heavier_lower_reps", 10, True, True),
    ("temporary", "double_progression", 12, True, True),
    ("temporary", "heavier_lower_reps", 10, False, True),
    ("template", "heavier_lower_reps", 10, True, False),
])
def test_visible_candidate_task_end_to_end(tmp_path, monkeypatch, mode, strategy, prior_reps, approved, complete_protocol):
    from healthzip.analytics.v13 import analyze

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "visible-candidate.sqlite3"
    if approved:
        synthetic_authority(tmp_path / ".local/knowledge", "external_total_kg")
    app = open_app(path)
    prefix = "template_condition" if mode == "template" else "session_condition"
    selector = "template_selector" if mode == "template" else "session_selector"
    if mode == "temporary":
        app.text_input(key="start_name").set_value("Synthetic temporary history")
        app.button(key="training_start").click().run()
    app.text_input(key=selector + "_query").set_value("杠铃平板卧推").run()
    app.text_input(key=prefix + "_new_machine").set_value("Synthetic bench station")
    app.button(key=prefix + "_add_machine").click().run()
    repo = Repository(path)
    machine = TrainingService(repo).list_equipment()[0]["id"]
    repo.close()

    app.selectbox(key=prefix + "_instance").set_value(machine)
    configure_condition(app, prefix, complete_protocol=complete_protocol)
    if mode == "template":
        app.text_input(key="template_name_None").set_value("Synthetic task plan")
        for field, value in (("low", "8"), ("high", "12"), ("rir", "2")):
            app.text_input(key="template_targets_" + field).set_value(value)
        app.button(key="template_save").click().run()
        repo = Repository(path)
        template_id = TrainingService(repo).list_templates()[0]["id"]
        repo.close()
        app.run()
        app.selectbox(key="start_template").set_value(template_id)
        app.text_input(key="start_name").set_value("Synthetic template history")
        app.button(key="training_start").click().run()
    else:
        next(b for b in app.button if b.label == "添加到本次训练").click().run()
        instance = current(path)["exercises"][0]
        app.button(key="add_set_" + instance["id"]).click().run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    instance = current(path)["exercises"][0]
    reference_id = finish_reference(app, path, instance, 50, prior_reps)
    if approved and complete_protocol and mode == "template":
        # A later ordinary group must never supply the reference task's unit.
        app.button(key="add_set_" + instance["id"]).click().run()
        finish_reference(app, path, instance, 110, 10, reference=False, unit="lb")
    next(b for b in app.button if b.label == "结束训练并保存反馈").click().run()

    app.text_input(key="start_name").set_value("Synthetic next task")
    app.button(key="training_start").click().run()
    if mode == "temporary":
        app.text_input(key="session_selector_query").set_value("杠铃平板卧推").run()
        app.selectbox(key="session_condition_instance").set_value(machine)
        configure_condition(app, "session_condition", complete_protocol=complete_protocol)
        next(b for b in app.button if b.label == "添加到本次训练").click().run()
        instance = current(path)["exercises"][0]
        app.button(key="add_set_" + instance["id"]).click().run()
    session = current(path)
    instance = session["exercises"][0]
    sid = instance["sets"][0]["set_uuid"]
    # Modify a group's effective target through the UI: R07 must feed this exact revision.
    for field, value in (("low", "6"), ("high", "8"), ("rir", "2")):
        app.text_input(key="set_" + sid + "_target_" + field).set_value(value)
    app.button(key="set_" + sid + "_target_save").click().run()
    app.selectbox(key="strategy_" + instance["id"]).set_value(strategy)
    app.text_input(key="loads_" + instance["id"]).set_value("50,52.5,55")
    app.button(key="candidate_" + instance["id"]).click().run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    repo = Repository(path)
    svc = TrainingService(repo)
    record = svc.list_recommendations()[0]
    target = record["input_snapshot"]["selected_target"]
    assert target["set_uuid"] == sid and target["target"]["reps_min"] == 6
    assert record["input_snapshot"]["strategy"] == strategy
    candidate = record["candidate"]
    repo.close()
    if not approved or not complete_protocol:
        assert candidate["proposed_change"]["load"] is None
        assert candidate["eligibility"]
        assert candidate["target_range"] == {}
        return
    assert candidate["proposed_change"]["load"] == 52.5
    assert candidate["proposed_change"]["load_unit"] == "kg"
    assert record["input_snapshot"]["reference_set_id"] == reference_id
    assert candidate["target_range"]["reps_min"] == candidate["target_range"]["reps_max"] == 6
    cid = candidate["candidate_id"]
    app.selectbox(key="choice_" + cid).set_value("accepted")
    app.button(key="feedback_" + cid).click().run()
    actual_id = finish_reference(app, path, instance, 52.5, 6)
    next(b for b in app.button if b.label == "结束训练并保存反馈").click().run()
    # Choose this completed session in the actual history selector.
    history = next(w for w in app.selectbox if w.label == "训练历史")
    history.set_value(session["id"]).run()
    app.selectbox(key="history_choice_" + cid).set_value("accepted")
    app.selectbox(key="history_execution_" + cid).set_value("executed")
    app.multiselect(key="history_actual_records_" + cid).set_value([actual_id])
    app.text_input(key="history_reason_" + cid).set_value("Synthetic trial completed; no causal efficacy claim")
    app.button(key="history_feedback_" + cid).click().run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    assert any("已满足记录的目标" in str(w.value) for w in app.markdown)
    repo = Repository(path)
    saved = TrainingService(repo).list_recommendations()[0]
    assert saved["input_snapshot"] == record["input_snapshot"]
    results = analyze(repo)["metrics"]["STR-27"]["value"]
    assert next(x for x in results if x["recommendation_id"] == cid)["short_term_success"] is True
    repo.close()


def test_multiaction_ui_history_reaches_default_analysis(tmp_path, monkeypatch):
    from healthzip.analytics.v13 import analyze

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "multi-action.sqlite3"
    app = open_app(path)
    template_id = None
    for query in ("杠铃平板卧推", "高脚杯深蹲"):
        if template_id:
            app.selectbox(key="edit_template").set_value(template_id).run()
        else:
            app.text_input(key="template_name_None").set_value("Synthetic two-action plan")
        app.text_input(key="template_selector_query").set_value(query).run()
        app.text_input(key="template_condition_new_machine").set_value("Synthetic " + query)
        app.button(key="template_condition_add_machine").click().run()
        repo = Repository(path)
        machine = next(x for x in TrainingService(repo).list_equipment() if x["label"] == "Synthetic " + query)
        repo.close()
        app.selectbox(key="template_condition_instance").set_value(machine["id"])
        configure_condition(app, "template_condition")
        for field, value in (("low", "6"), ("high", "12"), ("rir", "2")):
            app.text_input(key="template_targets_" + field).set_value(value)
        app.button(key="template_save").click().run()
        assert not app.exception and not app.error, [e.value for e in app.error]
        repo = Repository(path)
        template_id = TrainingService(repo).list_templates()[0]["id"]
        repo.close()
        app.run()
    app.selectbox(key="start_template").set_value(template_id)
    for repetition in range(3):
        app.text_input(key="start_name").set_value(f"Synthetic multi-action {repetition}")
        app.button(key="training_start").click().run()
        exercises = current(path)["exercises"]
        assert len(exercises) == 2
        for index, instance in enumerate(exercises):
            finish_reference(app, path, instance, 50 if index == 0 else 20, 6 + index + repetition)
        next(b for b in app.button if b.label == "结束训练并保存反馈").click().run()
        assert not app.exception and not app.error, [e.value for e in app.error]
    repo = Repository(path)
    analysis = analyze(repo)
    repo.close()
    tasks = analysis["strength_tasks"]
    assert len(tasks) == 2
    assert {t["exercise_id"] for t in tasks} == {"psa.ex.barbell_bench_press", "psa.ex.goblet_squat"}
    for task in tasks:
        assert task["protocol_complete"] is True
        assert task["metrics"]["STR-11"]["valid_n"] == 3
        trend = task["metrics"]["STR-19"]
        assert trend["valid_n"] == 3 and trend["data_status"] == "valid"
        assert trend["value"]["slope_per_day"] > 0
        assert task["metrics"]["STR-22"]["data_status"] != "valid"
