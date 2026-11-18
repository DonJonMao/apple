"""No manual-feedback current training path, using real records and calculators."""
import json
import runpy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from healthzip.training.current import current_advice, objective_comparison, save_equipment_loads

HELP = runpy.run_path(str(Path(__file__).with_name("test_workflow_four_repairs.py")))


def fixture(tmp_path, monkeypatch, approved=True):
    values = HELP["HELP"]["W1"]["history"](tmp_path, monkeypatch, approved=approved)
    save_equipment_loads(values[0], values[2]["id"], [30, 34, 38], load_unit="kg")
    return values


def finish(svc, row, load=30, reps=11):
    row = svc.get_set(row["set_uuid"])
    row = svc.edit_set(row["id"], {"completion_state": "in_progress", "started_at": datetime.now(timezone.utc).isoformat()},
                       base_revision=row["revision"])
    return svc.edit_set(row["id"], {"completion_state": "completed", "ended_at": datetime.now(timezone.utc).isoformat(),
        "load_value": load, "load_unit": "kg", "reps": reps, "rir": 2, "pain_flag": False,
        "quality_status": "acceptable", "stop_reason": "target_rir"}, base_revision=row["revision"])


@pytest.mark.parametrize("approved", [True, False])
def test_automatic_advice_permission_and_objective_actual_without_feedback(tmp_path, monkeypatch, approved):
    repo, svc, instance, target, _ = fixture(tmp_path, monkeypatch, approved)
    advice = current_advice(repo, instance["id"])
    heavier = next(o for o in advice["groups"][0]["options"] if o["strategy"] == "heavier_lower_reps")
    assert heavier["load"] == (34 if approved else None)
    if approved:
        assert heavier["reps"] == 8
        assert heavier["basis"]["repetitions_origin"] == "沿用用户计划次数下限"
        assert heavier["basis"]["rules"]
    assert advice["user_choice"] is None and advice["generation_origin"] == "automatic_training"
    assert svc.get_set(target["set_uuid"])["completion_state"] == "draft"
    assert objective_comparison(repo, instance["id"])["rows"][0]["status"] == "no_actual_record"
    # A repeat is returned before workflow evidence retrieval and produces no run.
    from healthzip.workflows import evidence
    with monkeypatch.context() as patch:
        patch.setattr(evidence, "retrieve", lambda *a, **kw: pytest.fail("unchanged rerun retrieved evidence"))
        assert current_advice(repo, instance["id"]) == advice
    actual = finish(svc, target)
    comparison = objective_comparison(repo, instance["id"])
    row = comparison["rows"][0]
    assert row["status"] == "linked_objectively" and row["advice_id"] == advice["advice_id"]
    assert float(row["actual"]["load_value"]) == 30 and row["actual"]["reps"] == 11 and row["actual"]["rir"] == 2
    assert row["intent"] == "unknown_not_inferred"
    assert row["daily_comparisons"][0]["metrics"]["STR-12"]["value"]["delta_reps"] == 1
    assert objective_comparison(repo, instance["id"]) == comparison
    svc.edit_set(actual["id"], {"reps": 12}, base_revision=actual["revision"])
    revised = objective_comparison(repo, instance["id"])
    assert len(revised["rows"]) == 1 and revised["rows"][0]["actual"]["reps"] == 12
    latest = svc.get_set(actual["id"])
    svc.delete_set(latest["id"], base_revision=latest["revision"])
    assert objective_comparison(repo, instance["id"])["rows"][0]["status"] == "record_removed"
    assert json.loads(repo.one("SELECT payload_json FROM current_training_advice WHERE advice_id=?", (advice["advice_id"],))[0]) == advice
    assert json.loads(repo.one("SELECT payload_json FROM training_objective_comparison WHERE comparison_id=?", (comparison["comparison_id"],))[0]) == comparison
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    assert repo.one("SELECT count(*) FROM training_recommendation")[0] == 0
    repo.close()


def test_multiset_versions_bind_by_identity_and_time_not_best_match(tmp_path, monkeypatch):
    repo, svc, instance, first, _ = fixture(tmp_path, monkeypatch)
    second = svc.add_set(instance["id"], planned={"reps_min": 7, "reps_max": 12, "rir": 3})
    original = current_advice(repo, instance["id"])
    finish(svc, first, load=30, reps=11)
    later = current_advice(repo, instance["id"])
    assert [g["set_uuid"] for g in later["groups"]] == [second["set_uuid"]]
    # Second group differs more from its suggested reps; no post-hoc best match.
    finish(svc, second, load=38, reps=5)
    rows = objective_comparison(repo, instance["id"])["rows"]
    assert [r["advice_id"] for r in rows] == [original["advice_id"], later["advice_id"]]
    assert [r["actual"]["reps"] for r in rows] == [11, 5]
    assert len({r["set_uuid"] for r in rows}) == 2
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


def test_explicit_choice_condition_is_not_forged_for_automatic_options(tmp_path, monkeypatch):
    from healthzip.knowledge import KnowledgeWorkbench

    repo, _, instance, _, _ = fixture(tmp_path, monkeypatch)
    workbench = KnowledgeWorkbench(tmp_path / ".local/knowledge")
    row = workbench.lib.theories.execute("SELECT review_json FROM theory WHERE theory_id='TC-progression-load-repetition-options'").fetchone()
    review = json.loads(row[0])
    review["applicability"]["required"]["user_choice"] = "requested_strategy_review"
    # Isolated test authority only. Production rules are never rewritten.
    workbench.lib.theories.execute("UPDATE theory SET review_json=? WHERE theory_id='TC-progression-load-repetition-options'", (json.dumps(review),))
    workbench.lib.theories.commit()
    workbench.close()
    advice = current_advice(repo, instance["id"])
    assert all(o["load"] is None for g in advice["groups"] for o in g["options"])
    heavier = next(o for o in advice["groups"][0]["options"] if o["strategy"] == "heavier_lower_reps")
    assert any(e.get("required_context", {}).get("user_choice") for e in heavier["excluded_rules"])
    repo.close()


def test_real_app_training_automatically_shows_options_and_free_actual(tmp_path, monkeypatch):
    repo, svc, instance, target, _ = fixture(tmp_path, monkeypatch)
    # Real root app, not a wrapper rendering just the new fragment.
    app = HELP["open_app"](repo.path)
    app.radio(key="main_workspace").set_value("力量").run()
    assert not app.exception, [e.message for e in app.exception]
    advice = json.loads(repo.one("SELECT payload_json FROM current_training_advice WHERE session_exercise_id=? ORDER BY created_at DESC", (instance["id"],))[0])
    assert advice["groups"] and any(o["load"] == 34 for o in advice["groups"][0]["options"])
    assert any("本次训练建议与实际记录" in m.value for m in app.markdown)
    # Existing real training editor, with no strategy/adoption interaction.
    TRAINING = HELP["HELP"]["W1"]["TRAINING"]
    TRAINING["finish_reference"](app, repo.path, instance, 30, 11, reference=False)
    assert not app.exception and not app.error
    assert svc.get_set(target["set_uuid"])["reps"] == 11
    comparison = objective_comparison(repo, instance["id"])
    assert comparison["rows"][0]["advice_id"] == advice["advice_id"]
    assert comparison["rows"][0]["actual"]["rir"] == 2
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


def test_real_page_saves_actuals_during_evidence_failure_and_recovers(tmp_path, monkeypatch):
    from healthzip.workflows import evidence

    repo, svc, instance, target, _ = fixture(tmp_path, monkeypatch)
    designated = svc.get_set(target["id"])["reference_selection"]
    assert not designated  # Daily recording never nominates a research reference.
    app = HELP["open_app"](repo.path)

    def unavailable(*args, **kwargs):
        raise OSError("Synthetic temporary source service failure")

    with monkeypatch.context() as patch:
        patch.setattr(evidence, "retrieve", unavailable)
        app.radio(key="main_workspace").set_value("力量").run()
        assert not app.exception
        assert any("本次建议待更新" in w.value for w in app.warning)
        assert repo.one("SELECT count(*) FROM current_training_advice")[0] == 0
        HELP["HELP"]["W1"]["TRAINING"]["finish_reference"](app, repo.path, instance, 30, 11, reference=False)
        assert not app.exception and not app.error
        assert svc.get_set(target["set_uuid"])["reps"] == 11
        assert svc.get_set(target["set_uuid"])["reference_selection"] == designated
    app.run()
    assert not app.exception and not app.error
    assert repo.one("SELECT count(*) FROM current_training_advice")[0] == 1
    assert not any("本次建议待更新" in w.value for w in app.warning)
    assert objective_comparison(repo, instance["id"])["rows"][0]["status"] == "no_prior_applicable_advice"
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()
