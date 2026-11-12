"""Real persistence/UI discussion paths use explanation authority, never numeric permission."""

from datetime import datetime, timezone

import pytest

from healthzip.advice import current_use_status, freeze_candidate, save_profile
from healthzip.db.repository import Repository
from healthzip.knowledge import KnowledgeWorkbench
from healthzip.training.service import TrainingService


@pytest.fixture
def discussion_setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    original = KnowledgeWorkbench
    monkeypatch.setattr("healthzip.knowledge.KnowledgeWorkbench",
                        lambda root: original(root, environment_kind="synthetic_test"))
    w = original(".local/knowledge", environment_kind="synthetic_test")
    w.seed()
    w.seed_core()
    version = w.lib.record_version("S1", b"Synthetic general explanations only", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": "Synthetic volume and frequency explanation.", "locator": {"paragraph": 1}}], "synthetic")
    sid = version + ":s00000"
    for outcome in ("volume", "frequency"):
        w.review_claim({"claim_id": "SYNTH-" + outcome, "version": "1", "statement": "Synthetic general " + outcome,
            "scope": {"population": "adults", "age_range": [18, 64], "applicable_goals": ["strength", "hypertrophy"]},
            "limitations": ["Synthetic fixture; no personal numerical authority"],
            "evidence_links": [{"source_id": "S1", "source_version_id": version, "span_ids": [sid]}],
            "answer_task": {"subject": "resistance_training", "outcome": outcome, "requested_relation": "options",
                "answer_parts": [{"text": "合成一般解释：" + outcome + "；没有个人最佳数值。", "span_ids": [sid]}]}},
            {"reviewer": "Synthetic fixture", "reviewer_kind": "synthetic_fixture", "content_checked": True,
             "reviewed_at": "2026-11-12T00:00:00Z", "rationale": "Tests explanation/candidate separation only"})
    assert w.core_status()["effective_candidate_rule_count"] == 0
    w.close()
    repo = Repository(tmp_path / "synthetic-discussions.sqlite3")
    svc = TrainingService(repo)
    equipment = svc.create_equipment("Synthetic station", "barbell")
    condition = {"equipment_instance_id": equipment["id"], "load_basis": "external_total_kg", "load_basis_confirmed": True,
        "side": "both", "repetition_semantics": "simultaneous", "rom_protocol": "full", "settings_confirmed": True,
        "settings": {"grip": "fixed"}, "reference_protocol": {"protocol_id": "synthetic", "version": "1",
        "reference_policy_id": "first-work", "effort_protocol": "rir-2", "tempo": "controlled", "rest_protocol": "180-sec"}}
    save_profile(repo, {"age": 30, "training_goal": "strength"})
    recorded = []
    for index in range(2):
        past = svc.start_session("Synthetic prior " + str(index))
        exercise = svc.add_exercise(past["id"], "psa.ex.barbell_bench_press", condition)
        recorded.append(complete(svc, exercise))
        complete(svc, exercise, set_type="warmup")
        svc.end_session(past["id"])
    session = svc.start_session("Synthetic current")
    instance = svc.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
    for _ in range(2):
        svc.add_set(instance["id"], planned={"reps_min": 8, "reps_max": 10, "rir": 2})
    instance = svc.get_session_exercise(instance["id"])
    yield repo, svc, session, instance, recorded
    repo.close()


def complete(svc, instance, *, set_type="work", pain=False):
    row = svc.add_set(instance["id"], {"set_type": set_type, "reference_set": set_type == "work"})
    row = svc.edit_set(row["id"], {"completion_state": "in_progress", "started_at": datetime.now(timezone.utc).isoformat()}, base_revision=row["revision"])
    return svc.edit_set(row["id"], {"completion_state": "completed", "ended_at": datetime.now(timezone.utc).isoformat(),
        "load_value": 50, "load_unit": "kg", "reps": 10, "rir": 2, "pain_flag": pain,
        "quality_status": "technique_limited" if pain else "acceptable", "stop_reason": "pain" if pain else "target_rir"}, base_revision=row["revision"])


def freeze(setup, strategy):
    repo, svc, session, instance, _ = setup
    effective = svc.current_targets(instance["id"])
    return freeze_candidate(repo, svc, session, instance, effective, effective["sets"][0], [], strategy)


@pytest.mark.parametrize("strategy,outcome", [("discuss_sets", "volume"), ("discuss_interval", "frequency")])
def test_discussion_uses_actual_plan_records_and_explanation_without_numeric_rule(discussion_setup, strategy, outcome):
    record = freeze(discussion_setup, strategy)
    assert record["candidate"]["action_kind"] == strategy
    assert record["candidate"]["proposed_change"]["load"] is None
    assert record["candidate"]["target_range"] == {}
    discussion = record["candidate"]["discussion"]
    assert discussion["authority"] == "source_explanation_only"
    assert discussion["source_explanation"]["claims"][0]["theory_id"] == "SYNTH-" + outcome
    assert discussion["source_explanation"]["citations"]
    facts = discussion["observations"]
    assert facts["explicit_planned_work_sets"] == 2
    assert len(facts["recorded_sessions"]) == 2
    assert [s["completed_work_parent_sets"] for s in facts["recorded_sessions"]] == [1, 1]
    assert len(facts["recorded_interval_days"]) == 1
    assert facts["available_minutes"] is None
    assert not record["input_snapshot"]["theory_authority"]["principles"]
    assert record["input_snapshot"]["metric_result"]["value"]["task_trial"] is None
    assert discussion_setup[1].list_recommendations()[0]["candidate"] == record["candidate"]


def test_current_symptom_keeps_bounded_discussion_and_preserves_its_numeric_restriction(discussion_setup):
    _, svc, _, instance, _ = discussion_setup
    complete(svc, instance, pain=True)
    record = freeze(discussion_setup, "discuss_sets")
    assert record["candidate"]["action_kind"] == "discuss_sets"
    assert record["candidate"]["proposed_change"]["load"] is None
    assert record["input_snapshot"]["metric_result"]["candidate_applicability"]["applicable"] is False
    assert "pain_reported" in record["candidate"]["discussion"]["numeric_action_limitations"]
    assert record["candidate"]["discussion"]["observations"]["current_session_records"][0]["pain_flag"] is True


def test_withdrawn_explanation_changes_current_use_without_mutating_frozen_discussion(discussion_setup):
    repo, svc, _, _, _ = discussion_setup
    record = freeze(discussion_setup, "discuss_interval")
    assert record["candidate"]["action_kind"] == "discuss_interval"
    assert current_use_status(repo, record)["status"] == "active"
    with_workbench = KnowledgeWorkbench(".local/knowledge", environment_kind="synthetic_test")
    with_workbench.lib.update_state("S1", "withdrawn", "Synthetic withdrawal")
    with_workbench.close()
    status = current_use_status(repo, record)
    assert status["status"] == "review_required"
    assert "frozen_explanation_dependencies_no_longer_current" in status["reason_codes"]
    assert svc.list_recommendations()[0]["candidate"] == record["candidate"]
    fresh = freeze(discussion_setup, "discuss_interval")
    assert fresh["candidate"]["action_kind"] == "collect_or_confirm_evidence"
    assert fresh["candidate"]["discussion"]["source_explanation"]["claims"] == []


@pytest.mark.parametrize("minutes", [True, -1, 0, float("inf"), "30"])
def test_invalid_user_time_is_not_a_scientific_default(discussion_setup, minutes):
    repo, svc, session, instance, _ = discussion_setup
    effective = svc.current_targets(instance["id"])
    with pytest.raises(ValueError, match="可用训练时间"):
        freeze_candidate(repo, svc, session, instance, effective, effective["sets"][0], [],
                         "discuss_sets", available_minutes=minutes)
    assert not svc.list_recommendations()


def test_partial_current_answer_requires_review_even_when_citations_unchanged(discussion_setup, monkeypatch):
    from healthzip.discussion import explanation

    record = freeze(discussion_setup, "discuss_sets")

    def partial(*args, **kwargs):
        value = explanation(*args, **kwargs)
        value["answer_status"] = "partially_answered"
        return value

    monkeypatch.setattr("healthzip.discussion.explanation", partial)
    status = current_use_status(discussion_setup[0], record)
    assert status["status"] == "review_required"
    assert "frozen_explanation_dependencies_no_longer_current" in status["reason_codes"]


def test_discussion_cannot_be_modified_into_numeric_permission(discussion_setup):
    from healthzip.advice import modify_candidate

    record = freeze(discussion_setup, "discuss_sets")
    with pytest.raises(ValueError, match="一般讨论"):
        modify_candidate(discussion_setup[0], record, 52.5, {"reps_min": 8, "reps_max": 8})


def test_real_ui_saves_discussion_and_feedback_and_reopens(discussion_setup):
    from streamlit.testing.v1 import AppTest

    repo, svc, session, instance, _ = discussion_setup
    app = AppTest.from_string(
        "from healthzip.db.repository import Repository\n"
        "from healthzip.training.service import TrainingService\n"
        "from healthzip.ui.recommendation_page import render_candidates\n"
        f"repo = Repository({str(repo.path)!r})\n"
        "svc = TrainingService(repo)\n"
        f"render_candidates(repo, svc, svc.get_session({session['id']!r}), svc.get_session_exercise({instance['id']!r}))\n"
        "repo.close()\n", default_timeout=30).run()
    app.selectbox(key="strategy_" + instance["id"]).select("discuss_interval").run()
    app.text_input(key="discussion_minutes_" + instance["id"]).input("35")
    app.button(key="candidate_" + instance["id"]).click().run()
    assert not app.exception
    record = svc.list_recommendations()[0]
    cid = record["candidate_id"]
    assert record["candidate"]["action_kind"] == "discuss_interval"
    assert record["candidate"]["discussion"]["observations"]["available_minutes"] == 35
    assert any("合成一般解释" in x.value for x in app.markdown)
    assert len(app.dataframe) == 2
    app.selectbox(key="choice_" + cid).select("accepted")
    app.text_input(key="reason_" + cid).input("先核对时间安排，数值计划未变")
    app.button(key="feedback_" + cid).click().run()
    assert not app.exception
    reopened = Repository(repo.path)
    try:
        saved = TrainingService(reopened).list_recommendations()[0]
        assert saved["candidate"] == record["candidate"]
        assert saved["feedback"][-1]["user_choice"] == "accepted"
        assert saved["feedback"][-1]["execution_state"] == "unknown"
        assert saved["feedback"][-1]["outcome"]["user_note"] == "先核对时间安排，数值计划未变"
    finally:
        reopened.close()
    assert any("没有可判定的数值成功目标" in x.value for x in app.info)
