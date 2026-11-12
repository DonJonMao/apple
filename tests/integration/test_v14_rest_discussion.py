"""Rest discussions preserve plans, manual observations and endpoint derivations."""

from datetime import datetime, timezone

import pytest
from streamlit.testing.v1 import AppTest
from test_v14_bounded_discussions import complete
from test_v14_bounded_discussions import discussion_setup as discussion_setup

from healthzip.advice import current_use_status, freeze_candidate, modify_candidate
from healthzip.db.repository import Repository
from healthzip.knowledge import KnowledgeWorkbench
from healthzip.training.service import TrainingService


@pytest.fixture
def rest_setup(discussion_setup):
    repo, svc, session, instance, _ = discussion_setup
    w = KnowledgeWorkbench(".local/knowledge", environment_kind="synthetic_test")
    span = dict(w.lib.sources.execute("SELECT span_id, version_id FROM span LIMIT 1").fetchone())
    w.review_claim({"claim_id": "SYNTH-rest", "version": "1", "statement": "Synthetic rest explanation",
        "scope": {"population": "adults", "age_range": [18, 64], "applicable_goals": ["strength", "hypertrophy"]},
        "limitations": ["Synthetic fixture; no personal numerical rest prescription"],
        "evidence_links": [{"source_id": "S1", "source_version_id": span["version_id"], "span_ids": [span["span_id"]]}],
        "answer_task": {"subject": "resistance_training", "outcome": "rest", "requested_relation": "options",
            "answer_parts": [{"text": "合成组间休息解释；没有个人最佳秒数。", "span_ids": [span["span_id"]]}]}},
        {"reviewer": "Synthetic fixture", "reviewer_kind": "synthetic_fixture", "content_checked": True,
         "reviewed_at": "2026-11-12T00:00:00Z", "rationale": "Tests explanation-only discussion wiring"})
    assert w.core_status()["effective_candidate_rule_count"] == 0
    w.close()
    target = instance["sets"][0]
    svc.update_set_target(target["id"], {**target["planned"], "rest_seconds": 180}, base_revision=target["revision"])
    past = svc.start_session("Synthetic rest observations")
    exercise = svc.add_exercise(past["id"], "psa.ex.barbell_bench_press", instance["condition"])
    first = svc.add_set(exercise["id"], {"completion_state": "completed", "reps": 10,
        "started_at": "2026-11-10T10:00:00Z", "ended_at": "2026-11-10T10:01:00Z"})
    second = svc.add_set(exercise["id"], {"completion_state": "completed", "reps": 9,
        "started_at": "2026-11-10T10:03:00Z", "ended_at": "2026-11-10T10:04:00Z",
        "rest_recorded_s": 115, "rest_recorded_method": "stopwatch"})
    assert second["rest_actual_s"] == 120
    svc.end_session(past["id"])
    return repo, svc, session, instance, first, second


def freeze_rest(setup):
    repo, svc, session, instance, *_ = setup
    effective = svc.current_targets(instance["id"])
    return freeze_candidate(repo, svc, session, instance, effective, effective["sets"][0], [], "discuss_rest")


def rest_observation(record, row):
    return next(item for item in record["candidate"]["discussion"]["observations"]["rest_observations"]
                if item["record_id"] == row["set_uuid"])


def test_rest_discussion_freezes_distinct_plan_manual_and_derived_values(rest_setup):
    record = freeze_rest(rest_setup)
    assert record["candidate"]["action_kind"] == "discuss_rest"
    assert record["candidate"]["proposed_change"]["load"] is None
    assert record["candidate"]["target_range"] == {}
    assert not record["input_snapshot"]["theory_authority"]["principles"]
    assert record["input_snapshot"]["numeric_provenance"] == []
    facts = record["candidate"]["discussion"]["observations"]
    assert [row["seconds"] for row in facts["planned_rest"]] == [180, None]
    assert all(row["origin"] == "user_plan" for row in facts["planned_rest"])
    observed = rest_observation(record, rest_setup[-1])
    assert observed["manual"]["seconds"] == 115
    assert observed["manual"]["method"] == "stopwatch"
    assert observed["derived"]["seconds"] == 120
    assert observed["performance"]["reps"] == 9
    assert observed["derived"]["provenance"]["previous_set_uuid"] == rest_setup[-2]["set_uuid"]
    assert observed["revision"] == rest_setup[1].get_set(rest_setup[-1]["id"])["revision"]
    assert observed["available_at"]
    assert record["candidate"]["discussion"]["source_explanation"]["claims"][0]["theory_id"] == "SYNTH-rest"


def test_missing_endpoint_does_not_fill_rest_from_plan_or_manual_value(rest_setup):
    _, svc, _, _, _, row = rest_setup
    current = svc.get_set(row["id"])
    svc.edit_set(row["id"], {"started_at": None}, base_revision=current["revision"])
    record = freeze_rest(rest_setup)
    observed = rest_observation(record, row)
    assert observed["manual"]["seconds"] == 115
    assert observed["derived"]["seconds"] is None
    assert observed["derived"]["provenance"]["reason"] == "missing_current_start"
    assert record["candidate"]["discussion"]["observations"]["planned_rest"][0]["seconds"] == 180


def test_current_manual_zero_is_preserved_without_inventing_missing_endpoints(rest_setup):
    _, svc, _, instance, *_ = rest_setup
    row = svc.get_set(instance["sets"][0]["id"])
    svc.edit_set(row["id"], {"completion_state": "in_progress", "rest_recorded_s": 0,
        "rest_recorded_method": "self_report", "started_at": None}, base_revision=row["revision"])
    record = freeze_rest(rest_setup)
    observed = rest_observation(record, row)
    assert observed["manual"]["seconds"] == 0
    assert observed["derived"]["seconds"] is None
    assert observed["started_at"] is None and observed["ended_at"] is None
    assert observed["origin"] == "current_session"
    assert row["set_uuid"] in record["input_snapshot"]["unknown_current_observation_ids"]
    assert record["candidate"]["action_kind"] == "discuss_rest"
    assert record["candidate"]["proposed_change"]["load"] is None


def test_endpoint_revision_does_not_rewrite_frozen_rest_discussion(rest_setup):
    _, svc, _, _, first, second = rest_setup
    original = freeze_rest(rest_setup)
    current = svc.get_set(first["id"])
    svc.edit_set(first["id"], {"ended_at": "2026-11-10T10:02:00Z"}, base_revision=current["revision"])
    revised = freeze_rest(rest_setup)
    assert rest_observation(original, second)["derived"]["seconds"] == 120
    assert rest_observation(revised, second)["derived"]["seconds"] == 60
    assert rest_observation(revised, second)["manual"]["seconds"] == 115
    saved = next(item for item in svc.list_recommendations() if item["candidate_id"] == original["candidate_id"])
    assert saved["candidate"] == original["candidate"]


def test_withdrawn_rest_source_preserves_facts_without_authorizing_discussion(rest_setup):
    original = freeze_rest(rest_setup)
    w = KnowledgeWorkbench(".local/knowledge", environment_kind="synthetic_test")
    w.lib.update_state("S1", "withdrawn", "Synthetic test withdrawal")
    w.close()
    assert current_use_status(rest_setup[0], original)["status"] == "review_required"
    fresh = freeze_rest(rest_setup)
    assert fresh["candidate"]["action_kind"] == "collect_or_confirm_evidence"
    assert fresh["candidate"]["discussion"]["source_explanation"]["claims"] == []
    assert rest_observation(fresh, rest_setup[-1])["derived"]["seconds"] == 120
    assert fresh["candidate"]["proposed_change"]["load"] is None


def test_rest_discussion_cannot_grant_numeric_task_permission(rest_setup):
    record = freeze_rest(rest_setup)
    with pytest.raises(ValueError, match="一般讨论"):
        modify_candidate(rest_setup[0], record, 52.5, {"reps_min": 8, "reps_max": 8})


def rest_app(setup, *, history=False):
    repo, _, session, instance, *_ = setup
    return AppTest.from_string(
        "from healthzip.db.repository import Repository\n"
        "from healthzip.training.service import TrainingService\n"
        "from healthzip.ui.recommendation_page import render_candidates\n"
        f"repo=Repository({str(repo.path)!r})\nsvc=TrainingService(repo)\n"
        f"render_candidates(repo,svc,svc.get_session({session['id']!r}),svc.get_session_exercise({instance['id']!r}),allow_create={not history!r})\n"
        "repo.close()\n", default_timeout=30).run()


def test_normal_ui_rest_choice_survives_execution_end_feedback_and_reopen(rest_setup):
    repo, svc, session, instance, *_ = rest_setup
    app = rest_app(rest_setup)
    assert "讨论组间休息" in app.selectbox(key="strategy_" + instance["id"]).options
    app.selectbox(key="strategy_" + instance["id"]).select("discuss_rest").run()
    app.text_input(key="discussion_minutes_" + instance["id"]).input("35")
    app.button(key="candidate_" + instance["id"]).click().run()
    assert not app.exception and not app.error
    record = svc.list_recommendations()[0]
    cid = record["candidate_id"]
    assert record["candidate"]["action_kind"] == "discuss_rest"
    assert any("合成组间休息解释" in item.value for item in app.markdown)
    app.selectbox(key="choice_" + cid).select("accepted")
    app.button(key="feedback_" + cid).click().run()
    actual = complete(svc, instance)
    svc.end_session(session["id"])
    app = rest_app(rest_setup, history=True)
    app.selectbox(key="execution_" + cid).select("executed")
    app.multiselect(key="actual_records_" + cid).select(actual["set_uuid"])
    app.text_input(key="reason_" + cid).input("核对了组间休息与计划，未宣称最佳秒数")
    app.button(key="feedback_" + cid).click().run()
    assert not app.exception and not app.error
    assert any("没有可判定的数值成功目标" in item.value for item in app.info)
    reopened = Repository(repo.path)
    try:
        saved = TrainingService(reopened).list_recommendations()[0]
        assert saved["candidate"] == record["candidate"]
        assert saved["feedback"][-1]["user_choice"] == "accepted"
        assert saved["feedback"][-1]["execution_state"] == "executed"
        assert saved["feedback"][-1]["actual_record_ids"] == [actual["set_uuid"]]
        assert datetime.fromisoformat(saved["feedback"][-1]["recorded_at"]) <= datetime.now(timezone.utc)
    finally:
        reopened.close()
