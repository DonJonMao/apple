"""Ordinary-history contract, concurrent freeze and parent deletion regressions.

The daily all-record contract replaces automatic prospective nomination. The
concurrency, historical freezing and optional specialist boundaries remain.
"""
import json
import runpy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from healthzip.db.repository import Repository
from healthzip.training.current import current_advice, objective_comparison
from healthzip.training.service import TrainingService
from tests.app_navigation import go

UI = runpy.run_path(str(Path(__file__).resolve().parents[1] / "strength_ui_harness.py"))
FLOW = runpy.run_path(str(Path(__file__).with_name("test_current_training_flow.py")))


def test_ordinary_record_updates_next_numeric_basis(tmp_path, monkeypatch):
    repo, svc, instance, target, _ = FLOW["fixture"](tmp_path, monkeypatch)
    nominated = svc.get_set(target["id"])
    assert not nominated["reference_set"]
    assert nominated["reference_selection"] is None
    first = current_advice(repo, instance["id"])
    assert any(o["load"] == 34 for o in first["groups"][0]["options"])
    actual = FLOW["finish"](svc, nominated, 34, 12)
    svc.end_session(instance["session_id"])
    following = FLOW["HELP"]["add_current"](svc, instance)
    advice = current_advice(repo, following["id"])
    option = next(o for o in advice["groups"][0]["options"] if o["strategy"] == "heavier_lower_reps")
    assert option["basis"]["source_set_id"] == actual["set_uuid"]
    assert (option["load"], option["reps"], option["rir"]) == (38, 8, 2)
    reference = option["basis"]["source_observation"]
    assert (float(reference["load_value"]), reference["reps"], reference["rir"]) == (34, 12, 2)
    stored = svc.get_set(option["basis"]["source_set_id"])
    assert not stored["reference_set"] and stored["reference_selection"] is None
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


@pytest.mark.parametrize("invalid_reference", [False, True])
def test_all_ordinary_sets_remain_facts_without_retrospective_nomination(tmp_path, monkeypatch, invalid_reference):
    repo, svc, instance, target, _ = FLOW["fixture"](tmp_path, monkeypatch)
    second = svc.add_set(instance["id"], planned={"reps_min": 8, "reps_max": 12, "rir": 2})
    actual = FLOW["finish"](svc, target, 34, 8)
    if invalid_reference:
        svc.edit_set(actual["id"], {"quality_status": "technique_limited"}, base_revision=actual["revision"])
    FLOW["finish"](svc, second, 34, 12)
    assert not svc.get_set(second["id"])["reference_set"]
    with pytest.raises(ValueError, match="开始"):
        svc.edit_set(second["id"], {"reference_set": True}, base_revision=svc.get_set(second["id"])["revision"])
    svc.end_session(instance["session_id"])
    following = FLOW["HELP"]["add_current"](svc, instance)
    advice = current_advice(repo, following["id"])
    records = advice["daily_history"]["records"]
    assert [r["set_uuid"] for r in records] == [actual["set_uuid"], second["set_uuid"]]
    assert [r["reps"] for r in records] == [8, 12]
    assert advice["reference_record"] is None
    assert not any(r["reference_set"] for r in records)
    assert advice["daily_decisions"]
    if invalid_reference:
        assert records[0]["quality_status"] == "technique_limited"
        assert all(o["load"] is None for g in advice["groups"] for o in g["options"])
    repo.close()


@pytest.mark.parametrize("mutation", ["start", "complete", "delete_set", "target", "condition", "replace", "delete_session", "equipment"])
def test_second_connection_changes_before_freeze_are_rejected(tmp_path, monkeypatch, mutation):

    repo, svc, instance, target, _ = FLOW["fixture"](tmp_path, monkeypatch)
    original_advice = current_advice(repo, instance["id"])
    # Force a fresh, independently authorized calculation, preserving the old one.
    from healthzip.advice import save_profile
    from healthzip.training.current import save_equipment_loads
    save_profile(repo, {"age": 35, "training_goal": "strength", "training_experience": "trained", "health_scope": "healthy"})
    other = Repository(repo.path)
    writer = TrainingService(other)
    import healthzip.training.daily_decisions as daily
    original = daily.option
    fired = False

    def interleave(*args, **kwargs):
        nonlocal fired
        result = original(*args, **kwargs)
        if not fired:
            fired = True
            row = writer.get_set(target["id"])
            if mutation == "start":
                writer.edit_set(row["id"], {"completion_state": "in_progress", "started_at": datetime.now(timezone.utc).isoformat()}, base_revision=row["revision"])
            elif mutation == "complete":
                FLOW["finish"](writer, row, 34, 12)
            elif mutation == "delete_set":
                writer.delete_set(row["id"], base_revision=row["revision"])
            elif mutation == "target":
                writer.update_set_target(row["id"], {"reps_min": 9, "reps_max": 12, "rir": 2}, base_revision=row["revision"])
            elif mutation in {"condition", "replace"}:
                selected = writer.get_session_exercise(instance["id"])
                changed = {**selected["condition"], "rom_protocol": "synthetic-new-rom"}
                if mutation == "condition":
                    writer.update_condition(selected["id"], changed, base_revision=selected["revision"])
                else:
                    writer.replace_exercise(selected["id"], selected["catalog_id"], changed, reason="synthetic replacement",
                        targets={"sets": [row["planned"]]}, base_revision=selected["revision"])
            elif mutation == "delete_session":
                session = writer.get_session(instance["session_id"])
                writer.delete_session(session["id"], base_revision=session["revision"])
            else:
                save_equipment_loads(other, instance["id"], [30, 35, 40], load_unit="kg")
        return result

    monkeypatch.setattr(daily, "option", interleave)
    with pytest.raises(ValueError, match="concurrent_current_advice"):
        current_advice(repo, instance["id"])
    assert fired
    assert repo.one("SELECT count(*) FROM current_training_advice")[0] == 1
    assert json.loads(repo.one("SELECT payload_json FROM current_training_advice")[0]) == original_advice
    other.close()
    repo.close()


def test_cache_hit_checks_interleaved_session_deletion(tmp_path, monkeypatch):
    import healthzip.training.current as current

    repo, svc, instance, _, _ = FLOW["fixture"](tmp_path, monkeypatch)
    original_advice = current_advice(repo, instance["id"])
    other = Repository(repo.path)
    writer = TrainingService(other)
    signature = current.knowledge_signature
    fired = False

    def interleave(root):
        nonlocal fired
        value = signature(root)
        if not fired:
            fired = True
            session = writer.get_session(instance["session_id"])
            writer.delete_session(session["id"], base_revision=session["revision"])
        return value

    monkeypatch.setattr(current, "knowledge_signature", interleave)
    with pytest.raises(ValueError, match="concurrent_current_advice"):
        current_advice(repo, instance["id"])
    assert json.loads(repo.one("SELECT payload_json FROM current_training_advice")[0]) == original_advice
    other.close()
    repo.close()


def test_rule_retraction_during_calculation_rejects_old_authority(tmp_path, monkeypatch):
    from healthzip.knowledge import KnowledgeWorkbench

    repo, _, instance, _, _ = FLOW["fixture"](tmp_path, monkeypatch)
    import healthzip.training.daily_decisions as daily
    original = daily.option
    fired = False

    def interleave(*args, **kwargs):
        nonlocal fired
        value = original(*args, **kwargs)
        if not fired:
            fired = True
            workbench = KnowledgeWorkbench(tmp_path / ".local/knowledge")
            workbench.lib.theories.execute("UPDATE theory SET review_json='{}' WHERE theory_id='TC-progression-load-repetition-options'")
            workbench.lib.theories.commit()
            workbench.close()
        return value

    monkeypatch.setattr(daily, "option", interleave)
    with pytest.raises(ValueError, match="concurrent_current_advice"):
        current_advice(repo, instance["id"])
    assert fired and repo.one("SELECT count(*) FROM current_training_advice")[0] == 0
    repo.close()


def test_initial_read_interleaving_cannot_freeze_completed_group(tmp_path, monkeypatch):
    repo, svc, instance, target, _ = FLOW["fixture"](tmp_path, monkeypatch)
    other = Repository(repo.path)
    writer = TrainingService(other)
    original = TrainingService.get_session_exercise
    fired = False

    def interleave(self, identity):
        nonlocal fired
        result = original(self, identity)
        if self.repo is repo and identity == instance["id"] and not fired:
            fired = True
            FLOW["finish"](writer, target, 34, 12)
        return result

    monkeypatch.setattr(TrainingService, "get_session_exercise", interleave)
    with pytest.raises(ValueError, match="concurrent_current_advice"):
        current_advice(repo, instance["id"])
    assert fired
    assert svc.get_set(target["id"])["completion_state"] == "completed"
    assert repo.one("SELECT count(*) FROM current_training_advice")[0] == 0
    other.close()
    repo.close()


@pytest.mark.parametrize("cached", [True, False])
def test_parent_deletion_cutoff_and_undo(tmp_path, monkeypatch, cached):
    repo, svc, instance, target, _ = FLOW["fixture"](tmp_path, monkeypatch)
    advice = current_advice(repo, instance["id"])
    FLOW["finish"](svc, target)
    svc.end_session(instance["session_id"])
    before_cut = datetime.now(timezone.utc).isoformat()
    before = objective_comparison(repo, instance["id"]) if cached else None
    session = svc.get_session(instance["session_id"])
    deleted = svc.delete_session(session["id"], base_revision=session["revision"])
    after_cut = datetime.now(timezone.utc).isoformat()
    removed = objective_comparison(repo, instance["id"])
    assert removed["rows"][0]["status"] == "record_removed"
    assert removed["session_state"]["deleted_at"]
    assert removed["metrics"]["STR-01"]["value"] is None
    assert removed["metrics"]["STR-01"]["valid_n"] == 0
    assert objective_comparison(repo, instance["id"], cutoff_time=before_cut)["rows"][0]["status"] == "linked_objectively"
    assert objective_comparison(repo, instance["id"], cutoff_time=after_cut)["rows"][0]["status"] == "record_removed"
    svc.undo_event(deleted["event_id"], base_revision=deleted["revision"])
    restored = objective_comparison(repo, instance["id"])
    assert restored["comparison_id"] != removed["comparison_id"]
    assert restored["rows"][0]["status"] == "linked_objectively"
    assert restored["metrics"]["STR-01"]["value"]["completed_work_parent_sets"] == 1
    if before:
        assert before["comparison_id"] != restored["comparison_id"]
        assert json.loads(repo.one("SELECT payload_json FROM training_objective_comparison WHERE comparison_id=?", (before["comparison_id"],))[0]) == before
    assert json.loads(repo.one("SELECT payload_json FROM current_training_advice WHERE advice_id=?", (advice["advice_id"],))[0]) == advice
    repo.close()


def test_real_app_ordinary_plan_update_and_deleted_history(tmp_path, monkeypatch, record_property):
    from healthzip.analytics.v13 import analyze
    from healthzip.workflows.period_report import create_report, load_report

    repo, svc, instance, _, _ = FLOW["fixture"](tmp_path, monkeypatch)
    template = svc.create_template("Synthetic reference plan", [{"exercise_id": instance["catalog_id"],
        "condition": instance["condition"], "targets": {"sets": [{"reps_min": 8, "reps_max": 12, "rir": 2}]}}])
    svc.end_session(instance["session_id"])
    UI["install"](monkeypatch)
    app = FLOW["HELP"]["open_app"](repo.path)
    go(app, "力量")
    started = UI["send"](app, "start_session", {"template_id": template["id"]})
    assert started["status"] == "saved"
    assert not app.exception and not app.error
    session = svc.get_session(started["data"]["id"])
    selected = session["exercises"][0]
    row = selected["sets"][0]
    assert not row["reference_set"] and not row["reference_declared_at"]
    assert row["completion_state"] == "draft"
    assert UI["send"](app, "advice", {"instance_id": selected["id"]})["status"] == "saved"
    before = json.loads(repo.one("SELECT payload_json FROM current_training_advice WHERE session_exercise_id=? ORDER BY created_at DESC LIMIT 1", (selected["id"],))[0])
    first_option = next(o for o in before["groups"][0]["options"] if o["strategy"] == "heavier_lower_reps")
    assert (first_option["load"], first_option["reps"]) == (34, 8)
    UI["legacy"](app, "set_details", set_id=row["set_uuid"])
    FLOW["HELP"]["HELP"]["W1"]["TRAINING"]["finish_reference"](app, repo.path, selected, 34, 12, reference=False)
    assert not app.exception and not app.error
    actual = svc.get_set(row["id"])
    assert actual["reference_selection"] is None
    assert not actual["reference_declared_at"]
    current_session = svc.get_session(session["id"])
    assert UI["send"](app, "end_session", {"session_id": current_session["id"], "base_revision": current_session["revision"]})["status"] == "saved"
    following_start = UI["send"](app, "start_session", {"template_id": template["id"]})
    assert following_start["status"] == "saved"
    following = svc.get_session(following_start["data"]["id"])["exercises"][0]
    assert UI["send"](app, "advice", {"instance_id": following["id"]})["status"] == "saved"
    advice = json.loads(repo.one("SELECT payload_json FROM current_training_advice WHERE session_exercise_id=? ORDER BY created_at DESC LIMIT 1", (following["id"],))[0])
    option = next(o for o in advice["groups"][0]["options"] if o["strategy"] == "heavier_lower_reps")
    assert option["basis"]["source_set_id"] == actual["set_uuid"]
    assert (option["load"], option["reps"], option["rir"]) == (38, 8, 2)
    assert advice["daily_history"]["records"][0]["set_uuid"] == actual["set_uuid"]
    record_property("ordinary_record_evidence", json.dumps({"source_set_id": actual["set_uuid"],
        "observation": option["basis"]["source_observation"], "next_option": {k: option[k] for k in ("load", "reps", "rir")}}, ensure_ascii=False))
    previous_reports = [create_report(repo, analyze(repo), period=p, include_details=True) for p in ("week", "month")]
    old_comparison = objective_comparison(repo, selected["id"])
    session = svc.get_session(session["id"])
    svc.delete_session(session["id"], base_revision=session["revision"])
    UI["management"](app, "历史记录与撤销")
    app.selectbox(key="training_history_session").set_value(session["id"]).run()
    assert not app.exception and not app.error
    assert any("这场训练已删除" in w.value for w in app.warning)
    assert any("所属训练已删除" in w.value for w in app.warning)
    assert objective_comparison(repo, selected["id"])["comparison_id"] != old_comparison["comparison_id"]
    for frozen in previous_reports:
        assert load_report(repo, frozen["report_id"], include_details=True) == frozen
        new = create_report(repo, analyze(repo), period=frozen["period"], include_details=True)
        assert all(r["set_uuid"] != actual["set_uuid"] for c in new["objective_comparisons"] for r in c["rows"])
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


def test_ordinary_draft_lifecycle_and_repeated_instances(tmp_path, monkeypatch):
    repo, svc, instance, first, _ = FLOW["fixture"](tmp_path, monkeypatch, approved=False)
    first = svc.get_set(first["id"])
    assert first["reference_selection"] is None and not first["reference_set"]
    revised = svc.update_set_target(first["id"], {"reps_min": 9, "reps_max": 12, "rir": 2}, base_revision=first["revision"])
    assert revised["reference_selection"] is None and not revised["reference_set"]
    second = svc.add_set(instance["id"], planned={"reps_min": 8, "reps_max": 12, "rir": 2}, event_id="synthetic-add-second")
    assert svc.add_set(instance["id"], planned={"reps_min": 8, "reps_max": 12, "rir": 2}, event_id="synthetic-add-second")["replayed"]
    first = svc.get_set(first["id"])
    removed = svc.delete_set(first["id"], base_revision=first["revision"])
    assert not svc.get_set(first["id"])["reference_set"]
    assert not svc.get_set(second["id"])["reference_set"]
    svc.undo_event(removed["event_id"], base_revision=svc.get_set(first["id"])["revision"])
    assert not svc.get_set(first["id"])["reference_set"]
    assert not svc.get_set(second["id"])["reference_set"]
    repeated = svc.add_exercise(instance["session_id"], instance["catalog_id"], instance["condition"],
        targets={"sets": [{"reps_min": 8, "reps_max": 12, "rir": 2}]})
    assert not repeated["sets"][0]["reference_set"]
    old = svc.get_session_exercise(instance["id"])
    changed = svc.replace_exercise(old["id"], "psa.ex.smith_squat", old["condition"], reason="before starting",
        targets={"sets": [{"reps_min": 8, "reps_max": 12, "rir": 2}]}, base_revision=old["revision"])
    assert not changed["sets"][0]["reference_set"]
    assert changed["catalog_id"] != instance["catalog_id"]
    # Repeated ordinary instances keep their separate UUIDs without nominations.
    repeated = svc.get_session_exercise(repeated["id"])
    assert not repeated["sets"][0]["reference_set"]
    target = changed["sets"][0]
    start = {"completion_state": "in_progress", "started_at": datetime.now(timezone.utc).isoformat()}
    started = svc.edit_set(target["id"], start, base_revision=target["revision"], event_id="synthetic-start-once")
    assert svc.edit_set(target["id"], start, base_revision=target["revision"], event_id="synthetic-start-once")["replayed"]
    assert svc.get_set(target["id"])["revision"] == started["revision"]
    repo.close()


@pytest.mark.parametrize("action", ["skip", "skip_with_replacement_note", "delete_completed", "undo_start"])
def test_observed_or_skipped_task_cannot_reopen_sampling(tmp_path, monkeypatch, action):
    repo, svc, instance, first, _ = FLOW["fixture"](tmp_path, monkeypatch, approved=False)
    second = svc.add_set(instance["id"], planned={"reps_min": 8, "reps_max": 12, "rir": 2})
    first = svc.get_set(first["id"])
    if action in {"skip", "skip_with_replacement_note"}:
        svc.edit_set(first["id"], {"completion_state": "skipped", "notes": "替换动作: user-entered note"
            if action == "skip_with_replacement_note" else ""}, base_revision=first["revision"])
    elif action == "delete_completed":
        actual = FLOW["finish"](svc, first, 34, 8)
        svc.delete_set(actual["id"], base_revision=actual["revision"])
    else:
        started = svc.edit_set(first["id"], {"completion_state": "in_progress", "started_at": datetime.now(timezone.utc).isoformat()}, base_revision=first["revision"])
        svc.undo_event(started["event_id"], base_revision=started["revision"])
        first = svc.get_set(first["id"])
        svc.delete_set(first["id"], base_revision=first["revision"])
    assert not svc.get_set(second["id"])["reference_set"]
    with pytest.raises(ValueError, match="开始"):
        svc.edit_set(second["id"], {"reference_set": True}, base_revision=svc.get_set(second["id"])["revision"])
    repo.close()


@pytest.mark.parametrize("missing", ["plan", "rir", "equipment", "quality", "recorded_rir", "rule"])
def test_sampling_does_not_relax_science_conditions(tmp_path, monkeypatch, missing):
    from healthzip.training.current import save_equipment_loads

    repo, svc, instance, first, _ = FLOW["fixture"](tmp_path, monkeypatch, approved=missing != "rule")
    if missing in {"quality", "recorded_rir"}:
        actual = FLOW["finish"](svc, first, 34, 12)
        svc.edit_set(actual["id"], {"quality_status": None} if missing == "quality" else {"rir": None}, base_revision=actual["revision"])
        svc.end_session(instance["session_id"])
        instance = FLOW["HELP"]["add_current"](svc, instance)
    elif missing in {"plan", "rir"}:
        target = {} if missing == "plan" else {"reps_min": 8, "reps_max": 12}
        svc.update_set_target(first["id"], target, base_revision=svc.get_set(first["id"])["revision"])
        assert not svc.get_set(first["id"])["reference_set"]
    elif missing == "protocol":
        svc.update_condition(instance["id"], {**instance["condition"], "reference_protocol": None}, base_revision=instance["revision"])
    elif missing == "equipment":
        save_equipment_loads(repo, instance["id"], [], load_unit="kg")
    advice = current_advice(repo, instance["id"])
    options = [o for g in advice["groups"] for o in g["options"]]
    if missing in {"rir", "recorded_rir"}:
        # Existing STR-25 requires effort matching; existing STR-26 separately
        # permits a non-guaranteed trial. Sampling must not alter either gate.
        assert next(o for o in options if o["strategy"] == "double_progression")["load"] is None
        trial = next(o for o in options if o["strategy"] == "heavier_lower_reps")
        if missing == "rir":
            assert trial["rir"] is None
            assert "target_rir_unspecified_not_effort_matched" in trial["metric"]["reason_codes"]
        else:
            assert trial["basis"]["source_observation"]["rir"] is None
        assert trial["metric"]["value"]["task_trial"]["expected_success"] is None
    else:
        assert all(o["load"] is None for o in options)
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


def test_completed_ordinary_history_is_never_backfilled(tmp_path, monkeypatch):
    from healthzip.advice import build_advice_context

    repo, svc, instance, _, _ = FLOW["fixture"](tmp_path, monkeypatch)
    old_session = svc.start_session("Synthetic imported ordinary history")
    old_instance = svc.add_exercise(old_session["id"], instance["catalog_id"], instance["condition"])
    now = datetime.now(timezone.utc).isoformat()
    ordinary = svc.add_set(old_instance["id"], {"completion_state": "completed", "started_at": now, "ended_at": now,
        "load_value": 34, "load_unit": "kg", "reps": 14, "rir": 2, "quality_status": "acceptable", "pain_flag": False,
        "stop_reason": "target_rir"}, planned={"reps_min": 8, "reps_max": 12, "rir": 2})
    svc.end_session(old_session["id"])
    # Reopening the service runs the actual compatibility migration.
    assert not TrainingService(repo).get_set(ordinary["id"])["reference_set"]
    assert not svc.get_set(ordinary["id"])["reference_declared_at"]
    current = FLOW["HELP"]["add_current"](svc, instance)
    context = build_advice_context(repo, current["session_id"], current["id"], None, [], None)
    assert ordinary["set_uuid"] in context["context"]["baseline_record_ids"]
    advice = current_advice(repo, current["id"])
    assert advice["reference_record"] is None
    assert [r["set_uuid"] for r in advice["daily_history"]["records"]] == [ordinary["set_uuid"]]
    future = svc.get_session_exercise(current["id"])["sets"][0]
    assert not future["reference_set"]
    FLOW["finish"](svc, future, 34, 12)
    svc.end_session(current["session_id"])
    next_instance = FLOW["HELP"]["add_current"](svc, instance)
    assert current_advice(repo, next_instance["id"])["daily_history"]["records"][0]["set_uuid"] == future["set_uuid"]
    assert not svc.get_set(ordinary["id"])["reference_set"]
    repo.close()


def test_explicit_plan_reference_and_unknown_policy(tmp_path, monkeypatch):
    repo, svc, instance, _, _ = FLOW["fixture"](tmp_path, monkeypatch, approved=False)
    condition = {**instance["condition"], "reference_protocol": {
        **instance["condition"]["reference_protocol"], "reference_policy_id": "user-specific-choice"}}
    session = svc.start_session("Synthetic explicit plan")
    current = svc.add_exercise(session["id"], instance["catalog_id"], condition, targets={"sets": [
        {"reps_min": 8, "reps_max": 12, "rir": 2},
        {"reps_min": 8, "reps_max": 12, "rir": 2, "reference_set": True}]})
    assert not current["sets"][0]["reference_set"]
    assert current["sets"][1]["reference_selection"] is None
    assert not current["sets"][1]["reference_set"]
    selected = svc.edit_set(current["sets"][1]["id"], {"reference_set": True}, base_revision=current["sets"][1]["revision"])
    assert selected["reference_selection"]["selection_protocol"] == "explicit-set"
    assert selected["reference_selection"]["policy_interpretation"] == "unrecognized_not_interpreted"
    session2 = svc.start_session("Synthetic unknown selection policy")
    unknown = svc.add_exercise(session2["id"], instance["catalog_id"], condition, targets={"sets": [
        {"reps_min": 8, "reps_max": 12, "rir": 2}]})
    assert not unknown["sets"][0]["reference_set"]
    repo.close()


def test_draft_with_actual_start_time_is_not_pending_advice(tmp_path, monkeypatch):
    repo, svc, instance, target, _ = FLOW["fixture"](tmp_path, monkeypatch)
    svc.edit_set(target["id"], {"started_at": datetime.now(timezone.utc).isoformat()}, base_revision=target["revision"])
    assert current_advice(repo, instance["id"])["groups"] == []
    repo.close()


def test_explicit_withdrawal_does_not_erase_another_reference(tmp_path, monkeypatch):
    repo, svc, instance, first, _ = FLOW["fixture"](tmp_path, monkeypatch, approved=False)
    second = svc.add_set(instance["id"], {"reference_set": False}, planned={"reps_min": 8, "reps_max": 12, "rir": 2})
    assert not second["reference_set"] and not svc.get_set(first["id"])["reference_set"]
    selected = svc.edit_set(first["id"], {"reference_set": True}, base_revision=svc.get_set(first["id"])["revision"])
    assert selected["reference_set"]
    first = svc.get_set(first["id"])
    svc.edit_set(first["id"], {"reference_set": False}, base_revision=first["revision"])
    svc.add_set(instance["id"], planned={"reps_min": 8, "reps_max": 12, "rir": 2})
    assert not any(r["reference_set"] for r in svc.get_session_exercise(instance["id"])["sets"])
    repo.close()
