"""Real services: ordinary all-set evidence, limits, freezing and concurrency."""
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from healthzip.db.repository import Repository
from healthzip.state_log import save_state
from healthzip.training.current import current_advice, save_equipment_loads
from healthzip.training.service import TrainingService

PAGE = runpy.run_path(str(Path(__file__).with_name("test_daily_training_page.py")))
FLOW = runpy.run_path(str(Path(__file__).with_name("test_current_training_flow.py")))


def numeric(advice):
    return [o for g in advice["groups"] for o in g["options"] if o["load"] is not None]


def stored(repo, identity):
    return json.loads(repo.one("SELECT payload_json FROM current_training_advice WHERE advice_id=?", (identity,))[0])


def add_past_actuals(svc, condition, monkeypatch, *, age=2, reference=None, failed=False):
    import healthzip.training.service as module

    historical = datetime.now(timezone.utc) - timedelta(days=age)
    original = module.timestamp
    with monkeypatch.context() as patch:
        patch.setattr(module, "timestamp", lambda value=None: original(value) if value else historical.isoformat())
        parent = svc.start_session("Synthetic newer ordinary")
        item = svc.add_exercise(parent["id"], "psa.ex.barbell_bench_press", condition)
        rows = []
        for index, (load, reps, rir) in enumerate(((55, 10, 2), (55, 9, 1), (50, 11, 2))):
            row = svc.add_set(item["id"], {"reference_set": reference if index == 0 else None})
            started = historical + timedelta(minutes=index + 1)
            row = svc.edit_set(row["id"], {"completion_state": "aborted" if failed else "completed",
                "load_value": 45 if failed else load, "load_unit": "kg", "reps": 0 if failed else reps,
                "rir": None if failed else rir, "quality_status": "technique_limited" if failed else "acceptable",
                "pain_flag": failed, "stop_reason": "pain" if failed else "target_rir",
                "started_at": started.isoformat(), "ended_at": (started + timedelta(seconds=30)).isoformat()},
                base_revision=row["revision"])
            rows.append(row)
        svc.end_session(parent["id"])
    return parent, item, rows


@pytest.mark.parametrize("reference", [True, False, None])
def test_reference_flag_never_changes_daily_latest_facts_or_single_set_options(tmp_path, monkeypatch, reference):
    repo, svc, instance, _, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch, history=False)
    parent, _, rows = add_past_actuals(svc, instance["condition"], monkeypatch, reference=reference)
    advice = current_advice(repo, instance["id"])
    assert advice["daily_history"]["latest_session"]["id"] == parent["id"]
    assert [(float(r["load_value"]), r["reps"], r["rir"]) for r in advice["daily_history"]["records"]] == [(55, 10, 2), (55, 9, 1), (50, 11, 2)]
    options = [o for o in numeric(advice) if o["strategy"] == "heavier_lower_reps"]
    assert [(o["basis"]["source_set_id"], o["load"], o["reps"], o["rir"]) for o in options] == [(rows[0]["set_uuid"], 60, 8, 2), (rows[1]["set_uuid"], 60, 8, 2), (rows[2]["set_uuid"], 55, 8, 2)]
    assert advice["reference_record"] is None
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


def test_ordinary_all_groups_actually_enter_rule_evaluation_and_later_pain_limits_every_option(tmp_path, monkeypatch):
    repo, svc, instance, rows, previous, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    advice = current_advice(repo, instance["id"])
    ids = [r["set_uuid"] for r in rows]
    assert all(not r["reference_set"] and not r["reference_declared_at"] for r in rows)
    assert advice["daily_decisions"]["input_record_ids"] == ids
    for item in advice["daily_decisions"]["records"]:
        assert item["uses"] == ["latest_session_fact", "restriction_check"]
        assert len(item["evaluations"]) == 3
    assert len(numeric(advice)) == 3
    for option in numeric(advice):
        basis = option["basis"]
        assert basis["source_set_ids"] == ids
        assert basis["calculation_record_ids"] == [basis["source_set_id"]]
        assert {item["set_uuid"] for item in basis["other_record_uses"]} == set(ids) - {basis["source_set_id"]}
        assert all(item["applicability_checked"] for item in basis["other_record_uses"])
        assert basis["scope"] == "one_optional_set_trial_not_all_sets"
        assert basis["target_set_uuid"] == instance["sets"][0]["set_uuid"]
        assert basis["repetitions_origin"] == "沿用用户计划次数下限"
        assert basis["rir_origin"] == "用户计划 RIR；未指定时保持未知"
        assert basis["rules"] and option["metric"]["business_rule_id"] == "DAILY-SET-OPTION"
    assert all(o["load"] is None for o in advice["groups"][0]["options"] if o["strategy"] == "double_progression")
    last = svc.get_set(rows[-1]["id"])
    svc.edit_set(last["id"], {"pain_flag": True, "quality_status": "technique_limited"}, base_revision=last["revision"])
    changed = current_advice(repo, instance["id"])
    assert changed["advice_id"] != advice["advice_id"]
    assert changed["daily_history"]["latest_session"]["id"] == previous["id"]
    assert changed["daily_history"]["records"][0] == advice["daily_history"]["records"][0]
    assert not numeric(changed)
    for group in changed["groups"]:
        for option in group["options"]:
            checks = option["metric"]["candidate_applicability"]
            assert checks["status"] == "restricted"
            assert rows[-1]["set_uuid"] in checks["current_session_record_ids"]
    assert stored(repo, advice["advice_id"]) == advice
    repo.close()


@pytest.mark.parametrize("scope", ["latest_later_group", "current_observation"])
def test_unresolved_pain_quality_conflict_is_retained_and_restricts_all_harder_options(tmp_path, monkeypatch, scope):
    repo, svc, instance, rows, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    if scope == "latest_later_group":
        disputed = svc.get_set(rows[-1]["id"])
    else:
        now = datetime.now(timezone.utc)
        disputed = svc.add_set(instance["id"], {"completion_state": "completed", "load_value": 55,
            "load_unit": "kg", "reps": 10, "rir": 2, "quality_status": "acceptable", "pain_flag": False,
            "stop_reason": "target_rir", "started_at": (now - timedelta(seconds=2)).isoformat(),
            "ended_at": (now - timedelta(seconds=1)).isoformat()})
    conflict = svc.edit_set(disputed["id"], {"pain_flag": True, "quality_status": "technique_limited"}, base_revision=0)
    assert conflict["status"] == "conflicted"
    advice = current_advice(repo, instance["id"])
    assert not numeric(advice)
    if scope == "latest_later_group":
        assert advice["daily_history"]["records"][-1]["conflicted"]
        assert advice["daily_history"]["records"][0]["set_uuid"] == rows[0]["set_uuid"]
    assert all("conflict" in " ".join(o["metric"]["reason_codes"]) for g in advice["groups"] for o in g["options"])
    svc.resolve_conflict(conflict["conflict_id"], choice="keep_current")
    restored = current_advice(repo, instance["id"])
    assert numeric(restored)
    assert stored(repo, advice["advice_id"]) == advice
    repo.close()


@pytest.mark.parametrize("step_unit,expected", [("kg", None), (None, None), ("lb", 60)])
def test_equipment_step_unit_is_explicit_and_never_borrowed_from_history(tmp_path, monkeypatch, step_unit, expected):
    repo, svc, instance, rows, previous, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    authority_root = tmp_path / ".local/unit-test-authority"
    PAGE["REVIEW"]["synthetic_authority"](authority_root, "external_total_kg",
        actions=["double_progression", "heavier_lower_reps", "repetition_progression"])
    for source in rows:
        current = svc.get_set(source["id"])
        svc.edit_set(current["id"], {"load_unit": "lb"}, base_revision=current["revision"])
    save_equipment_loads(repo, instance["id"], [50, 55, 60, 65], load_unit=step_unit)
    advice = current_advice(repo, instance["id"], knowledge_root=authority_root)
    assert advice["daily_history"]["latest_session"]["id"] == previous["id"]
    assert [r["load_unit"] for r in advice["daily_history"]["records"]] == ["lb", "lb", "lb"]
    repetition_options = [o for o in numeric(advice) if o["strategy"] == "repetition_progression"]
    assert [(o["load"], o["load_unit"], o["reps"]) for o in repetition_options] == [(55, "lb", 12), (55, "lb", 12), (50, "lb", 12)]
    step_options = [o for o in numeric(advice) if o["strategy"] in {"double_progression", "heavier_lower_reps"}]
    if expected is None:
        assert not step_options
        assert any("unit" in reason for group in advice["groups"] for option in group["options"]
                   for reason in option["metric"]["reason_codes"])
    else:
        first = next(o for o in step_options if o["basis"]["source_set_id"] == rows[0]["set_uuid"])
        assert first["load"] == expected and first["load_unit"] == "lb"
        assert first["reps"] == 8 and first["rir"] == 2
        assert advice["settings"]["load_unit"] == "lb"
    repo.close()


def test_body_reported_pain_in_action_scope_requires_review_and_denied_update_restores_options(tmp_path, monkeypatch):
    repo, _, instance, rows, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    ordinary = current_advice(repo, instance["id"])
    assert numeric(ordinary)  # Body absence is no blanket prerequisite.
    report = save_state(repo, pain="reported", muscle="chest", location="synthetic-pectoral",
                        movement_impact="reported during this movement")
    restricted = current_advice(repo, instance["id"])
    assert not numeric(restricted)
    checks = [check for group in restricted["groups"] for option in group["options"]
              for check in option["metric"]["candidate_applicability"]["checks"]
              if check["group"] == "body_self_report"]
    assert checks and all(check["applicable"] is False for check in checks)
    assert {str(c["record_id"]) for c in checks} == {f"subjective_log:{report}"}
    assert all(c["observations"]["pain"] == "reported" and c["observations"]["observed_at"]
               and c["observations"]["muscle"] == "chest" for c in checks)
    assert restricted["daily_decisions"]["input_record_ids"] == [r["set_uuid"] for r in rows]
    denied = save_state(repo, pain="denied", muscle="chest", location="synthetic-pectoral")
    restored = current_advice(repo, instance["id"])
    assert numeric(restored)
    restored_checks = [c for g in restored["groups"] for o in g["options"]
                       for c in o["metric"]["candidate_applicability"]["checks"] if c["group"] == "body_self_report"]
    assert {str(c["record_id"]) for c in restored_checks} == {f"subjective_log:{denied}"}
    assert stored(repo, restricted["advice_id"]) == restricted
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


def test_current_duplicate_action_pain_is_retained_as_restriction_without_pairing_instances(tmp_path, monkeypatch):
    repo, svc, instance, rows, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    duplicate = svc.add_exercise(instance["session_id"], instance["catalog_id"], instance["condition"])
    now = datetime.now(timezone.utc)
    painful = svc.add_set(duplicate["id"], {"completion_state": "aborted", "load_value": 40,
        "load_unit": "kg", "reps": 0, "rir": None, "quality_status": "technique_limited",
        "pain_flag": True, "stop_reason": "pain", "started_at": (now - timedelta(seconds=2)).isoformat(),
        "ended_at": (now - timedelta(seconds=1)).isoformat()})
    advice = current_advice(repo, instance["id"])
    assert not numeric(advice)
    assert advice["daily_decisions"]["input_record_ids"] == [r["set_uuid"] for r in rows]
    assert all(g["set_uuid"] != painful["set_uuid"] for g in advice["groups"])
    assert svc.get_set(painful["id"])["session_exercise_id"] == duplicate["id"]
    for group in advice["groups"]:
        for option in group["options"]:
            restriction = option["metric"]["candidate_applicability"]
            assert restriction["status"] == "restricted"
            assert painful["set_uuid"] in restriction["current_session_record_ids"]
            assert "pain_reported" in restriction["reason_codes"]
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


def test_unranked_actual_with_pain_cannot_be_bypassed_by_dated_better_history(tmp_path, monkeypatch):
    repo, svc, instance, rows, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    parent, _, unknown_rows = add_past_actuals(svc, instance["condition"], monkeypatch, failed=True)
    for old in unknown_rows:
        row = svc.get_set(old["id"])
        svc.edit_set(row["id"], {"started_at": None, "ended_at": None}, base_revision=row["revision"])
    svc.update_session(parent["id"], {"started_at": None}, base_revision=svc.get_session(parent["id"])["revision"])
    advice = current_advice(repo, instance["id"])
    assert advice["daily_history"]["status"] == "history_time_ambiguous"
    assert advice["daily_history"]["latest_known_time_only"]
    assert advice["daily_history"]["latest_session"]["latest_known_time_only"]
    assert advice["daily_decisions"]["input_record_ids"] == [r["set_uuid"] for r in rows]
    assert not numeric(advice)
    for group in advice["groups"]:
        for option in group["options"]:
            assert "history_occurrence_order_unknown" in option["metric"]["reason_codes"]
            restriction = option["metric"]["candidate_applicability"]
            assert restriction["status"] == "restricted"
            assert set(r["set_uuid"] for r in unknown_rows).issubset(restriction["current_session_record_ids"])
    repo.close()


def test_latest_failed_decline_is_not_replaced_by_older_success(tmp_path, monkeypatch):
    repo, svc, instance, rows, previous, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    parent, _, failed = add_past_actuals(svc, instance["condition"], monkeypatch, failed=True)
    advice = current_advice(repo, instance["id"])
    assert advice["daily_history"]["latest_session"]["id"] == parent["id"] != previous["id"]
    assert advice["daily_decisions"]["input_record_ids"] == [r["set_uuid"] for r in failed]
    assert not set(r["set_uuid"] for r in rows).intersection(advice["daily_decisions"]["input_record_ids"])
    assert all(r["completion_state"] == "aborted" and r["pain_flag"] for r in advice["daily_history"]["records"])
    assert not numeric(advice)
    repo.close()


def test_other_same_region_action_is_context_without_personal_load_conversion(tmp_path, monkeypatch):
    repo, svc, instance, rows, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    machine = svc.create_equipment("Synthetic dumbbells", "dumbbell")
    condition = {**instance["condition"], "equipment_instance_id": machine["id"], "load_basis": "per_dumbbell_kg"}
    added = svc.add_exercise(instance["session_id"], "psa.ex.dumbbell_incline_press", condition,
                             targets={"sets": [{"reps_min": 8, "reps_max": 12, "rir": 2}]})
    save_equipment_loads(repo, added["id"], [10, 15, 20], load_unit="kg")
    advice = current_advice(repo, added["id"])
    assert advice["daily_history"]["status"] == "no_history"
    assert not advice["daily_decisions"]["input_record_ids"] and not numeric(advice)
    assert {r["record"]["set_uuid"] for r in advice["recent_training"]} == {r["set_uuid"] for r in rows}
    assert all(r["purpose"] == "recent_same_region_context_no_load_conversion" for r in advice["recent_training"])
    repo.close()


def test_latest_delete_restore_new_selection_and_original_frozen_advice_survive(tmp_path, monkeypatch):
    repo, svc, instance, rows, previous, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    original = current_advice(repo, instance["id"])
    parent, _, newer_rows = add_past_actuals(svc, instance["condition"], monkeypatch)
    newer = current_advice(repo, instance["id"])
    assert newer["daily_history"]["latest_session"]["id"] == parent["id"]
    deletion = svc.delete_session(parent["id"], base_revision=svc.get_session(parent["id"])["revision"], event_id="synthetic-daily-history-delete")
    fallback = current_advice(repo, instance["id"])
    assert fallback["daily_history"]["latest_session"]["id"] == previous["id"]
    assert fallback["daily_decisions"]["input_record_ids"] == [r["set_uuid"] for r in rows]
    assert fallback["daily_history"]["selection"]["deleted_history"][0]["session_id"] == parent["id"]
    svc.undo_event("synthetic-daily-history-delete", base_revision=deletion["revision"])
    restored = current_advice(repo, instance["id"])
    assert restored["daily_history"]["latest_session"]["id"] == parent["id"]
    assert restored["daily_decisions"]["input_record_ids"] == [r["set_uuid"] for r in newer_rows]
    assert len(set(restored["daily_decisions"]["input_record_ids"])) == 3
    assert stored(repo, original["advice_id"]) == original
    assert stored(repo, newer["advice_id"]) == newer
    repo.close()


@pytest.mark.parametrize("state", ["completed", "aborted", "deleted"])
@pytest.mark.parametrize("cached", [False, True])
def test_ended_parent_never_returns_pending_advice_with_or_without_cache_and_restores(tmp_path, monkeypatch, state, cached):
    repo, svc, instance, _, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    original = current_advice(repo, instance["id"]) if cached else None
    parent = svc.get_session(instance["session_id"])
    if state == "deleted":
        ended = svc.delete_session(parent["id"], base_revision=parent["revision"], event_id="synthetic-daily-end")
    else:
        ended = svc.update_session(parent["id"], {"session_status": state, "ended_at": datetime.now(timezone.utc).isoformat()},
            base_revision=parent["revision"], event_id="synthetic-daily-end")
    with pytest.raises(ValueError, match="current_training_session_ended"):
        current_advice(repo, instance["id"])
    if original:
        assert stored(repo, original["advice_id"]) == original
    svc.undo_event("synthetic-daily-end", base_revision=ended["revision"])
    restored = current_advice(repo, instance["id"])
    assert restored["groups"] and numeric(restored)
    if original:
        assert restored["advice_id"] != original["advice_id"]
    repo.close()


@pytest.mark.parametrize("mutation", ["closer", "target", "end", "delete_history", "settings", "revoke_rule"])
def test_interleaving_after_history_selection_refuses_mixed_version_and_keeps_actual_save(tmp_path, monkeypatch, mutation):
    import healthzip.training.current as current
    import healthzip.training.daily_decisions as daily
    import healthzip.training.daily_history as historical

    repo, svc, instance, rows, previous, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    writer_repo = Repository(repo.path)
    writer = TrainingService(writer_repo)
    use_option_hook = mutation in {"settings", "revoke_rule"}
    original = daily.option if use_option_hook else historical.select_daily_history
    fired = False

    def interleave(*args, **kwargs):
        nonlocal fired
        result = original(*args, **kwargs)
        if fired:
            return result
        fired = True
        if mutation == "closer":
            add_past_actuals(writer, instance["condition"], monkeypatch)
        elif mutation == "target":
            row = writer.get_set(instance["sets"][0]["id"])
            writer.update_set_target(row["id"], {"reps_min": 7, "reps_max": 12, "rir": 2}, base_revision=row["revision"])
        elif mutation == "end":
            writer.end_session(instance["session_id"])
        elif mutation == "delete_history":
            writer.delete_session(previous["id"], base_revision=writer.get_session(previous["id"])["revision"])
        elif mutation == "settings":
            save_equipment_loads(writer_repo, instance["id"], [50, 55, 62], load_unit="kg")
        else:
            from healthzip.knowledge import KnowledgeWorkbench
            workbench = KnowledgeWorkbench(tmp_path / ".local/knowledge")
            workbench.lib.theories.execute("UPDATE theory SET review_json='{}' WHERE theory_id='TC-progression-load-repetition-options'")
            workbench.lib.theories.commit()
            workbench.close()
        return result

    if use_option_hook:
        monkeypatch.setattr(daily, "option", interleave)
    else:
        monkeypatch.setattr(historical, "select_daily_history", interleave)
    with pytest.raises(ValueError, match="concurrent_current_advice"):
        current.current_advice(repo, instance["id"])
    assert fired
    assert repo.one("SELECT count(*) FROM current_training_advice")[0] == 0
    # A failed advice request cannot roll back ordinary actuals. An ended parent
    # is legally restored before recording; no advice retry is needed to save.
    parent = svc.get_session(instance["session_id"])
    if parent["session_status"] == "completed":
        svc.update_session(parent["id"], {"session_status": "in_progress", "ended_at": None}, base_revision=parent["revision"])
    actual = FLOW["finish"](svc, svc.get_set(instance["sets"][0]["id"]), 55, 9)
    assert svc.get_set(actual["id"])["completion_state"] == "completed"
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    writer_repo.close()
    repo.close()
