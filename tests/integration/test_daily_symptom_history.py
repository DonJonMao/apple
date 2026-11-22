"""Latest categorical symptom state is independent from body display windows.

All records are synthetic and enter through real services. No current advice,
selector, permission check or final result is replaced by a mock.
"""
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from healthzip.science import evaluate
from healthzip.state_log import save_state
from healthzip.training.current import current_advice, save_equipment_loads
from tests.app_navigation import go

PAGE = runpy.run_path(str(Path(__file__).with_name("test_daily_training_page.py")))
FLOW = runpy.run_path(str(Path(__file__).with_name("test_current_training_flow.py")))
TARGET = {"reps_min": 8, "reps_max": 12, "rir": 2}


def numeric(advice):
    return [option for group in advice["groups"] for option in group["options"] if option["load"] is not None]


def body_checks(advice):
    option = advice["groups"][0]["options"][0]
    return [check for check in option["metric"]["candidate_applicability"]["checks"]
            if check["group"] == "body_self_report"]


@pytest.mark.parametrize("age", [27, 29])
def test_latest_reported_pain_does_not_expire_at_body_display_window_and_new_denial_restores(tmp_path, monkeypatch, age):
    repo, _, instance, rows, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    observed = (datetime.now(timezone.utc) - timedelta(days=age)).isoformat()
    identity = save_state(repo, observed_at=observed, pain="reported", muscle="chest")
    advice = current_advice(repo, instance["id"], baseline_days=28)
    assert advice["daily_decisions"]["input_record_ids"] == [row["set_uuid"] for row in rows]
    assert not numeric(advice)
    assert any(check["record_id"] == "subjective_log:" + str(identity)
               and check["observations"]["observed_at"] == observed
               and check["observations"]["pain"] == "reported" for check in body_checks(advice))
    if age == 29:
        assert advice["body"]["metrics"]["STATE-PAIN"]["value"] is None
    frozen = repo.one("SELECT payload_json FROM current_training_advice WHERE advice_id=?", (advice["advice_id"],))[0]
    denied = save_state(repo, pain="denied", muscle="chest")
    refreshed = current_advice(repo, instance["id"], baseline_days=28)
    assert refreshed["advice_id"] != advice["advice_id"]
    assert len(numeric(refreshed)) == 3
    assert {check["record_id"] for check in body_checks(refreshed)} == {"subjective_log:" + str(denied)}
    assert json.loads(repo.one("SELECT payload_json FROM current_training_advice WHERE advice_id=?", (advice["advice_id"],))[0]) == json.loads(frozen)
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


@pytest.mark.parametrize("responses", [("denied", "reported"), ("reported", "denied")])
def test_same_actual_time_contradictory_pain_reports_keep_both_and_require_review(tmp_path, monkeypatch, responses):
    repo, _, instance, _, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    observed = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    identities = [save_state(repo, observed_at=observed, pain=response, muscle="chest") for response in responses]
    advice = current_advice(repo, instance["id"])
    assert not numeric(advice)
    checks = body_checks(advice)
    assert {check["record_id"] for check in checks} == {"subjective_log:" + str(identity) for identity in identities}
    assert {check["observations"]["pain"] for check in checks} == {"denied", "reported"}
    assert {check["observations"]["observed_at"] for check in checks} == {observed}
    assert all(option["metric"]["candidate_applicability"]["status"] == "restricted"
               for group in advice["groups"] for option in group["options"])
    repo.close()


def test_missing_body_state_adds_no_symptom_prerequisite(tmp_path, monkeypatch):
    repo, _, instance, _, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    advice = current_advice(repo, instance["id"])
    assert len(numeric(advice)) == 3
    assert body_checks(advice) == []
    assert repo.one("SELECT count(*) FROM subjective_log")[0] == 0
    repo.close()


def test_first_work_specialist_cannot_skip_unplanned_first_but_daily_uses_both_actuals(tmp_path, monkeypatch):
    repo, svc, instance, _, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch, history=False, planned=False)
    physical = {**instance["condition"], "reference_protocol": {
        "protocol_id": "synthetic-first-work", "version": "1", "reference_policy_id": "first-work-set",
        "effort_protocol": "rir-2", "tempo": "controlled", "rest_protocol": "180-sec"}}
    svc.update_condition(instance["id"], physical, base_revision=instance["revision"])
    instance = svc.get_session_exercise(instance["id"])
    first = instance["sets"][0]
    second = svc.add_set(instance["id"], planned=TARGET)
    assert first["planned"] == {} and second["planned"] == TARGET
    with pytest.raises(ValueError, match="协议"):
        svc.edit_set(second["id"], {"reference_set": True}, base_revision=second["revision"])
    first = FLOW["finish"](svc, first, load=55, reps=10)
    second = FLOW["finish"](svc, second, load=50, reps=11)
    svc.end_session(instance["session_id"])
    parent = svc.start_session("Synthetic following first-work boundary")
    following = svc.add_exercise(parent["id"], instance["catalog_id"], physical)
    svc.add_set(following["id"], planned=TARGET)
    save_equipment_loads(repo, following["id"], [50, 55, 60, 65], load_unit="kg")
    advice = current_advice(repo, following["id"])
    records = advice["daily_history"]["records"]
    assert [record["set_uuid"] for record in records] == [first["set_uuid"], second["set_uuid"]]
    assert advice["daily_decisions"]["input_record_ids"] == [first["set_uuid"], second["set_uuid"]]
    assert all(not record["reference_set"] and not record["reference_declared_at"] for record in records)
    assert len(numeric(advice)) == 2
    # A legacy wrong-position nomination is supplied ONLY to the strict method;
    # ordinary stored records above remain entirely undesignated.
    specialist = [{**record, "record_kind": "strength_set", "event_start": record["started_at"],
        "event_end": record["ended_at"], "is_reference": index == 1,
        "reference_declared_at": first["started_at"] if index == 1 else None}
        for index, record in enumerate(records)]
    strict = evaluate("STR-11", specialist, cutoff_time=advice["created_at"],
        window_start=first["started_at"], window_end=advice["created_at"])
    assert strict["valid_n"] == 0
    assert "predesignated_reference_missing" in strict["reason_codes"]
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


def test_explicit_step_unit_limits_only_its_incompatible_source_in_mixed_unit_session(tmp_path, monkeypatch):
    repo, svc, instance, rows, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    last = svc.get_set(rows[-1]["id"])
    svc.edit_set(last["id"], {"load_unit": "lb"}, base_revision=last["revision"])
    advice = current_advice(repo, instance["id"])
    assert advice["daily_decisions"]["input_record_ids"] == [row["set_uuid"] for row in rows]
    assert [record["load_unit"] for record in advice["daily_history"]["records"]] == ["kg", "kg", "lb"]
    trials = [option for group in advice["groups"] for option in group["options"]
              if option["strategy"] == "heavier_lower_reps"]
    assert [(option["basis"]["source_set_id"], option["load"], option["load_unit"]) for option in trials] == [
        (rows[0]["set_uuid"], 60, "kg"), (rows[1]["set_uuid"], 60, "kg"), (rows[2]["set_uuid"], None, None)]
    assert "equipment_and_observation_load_units_differ" in trials[-1]["metric"]["reason_codes"]
    for option in trials:
        assert {check["record_id"] for check in option["metric"]["candidate_applicability"]["checks"]} >= {row["set_uuid"] for row in rows}
    repo.close()


def test_real_app_shows_dated_pain_beyond_body_window_without_expiry_or_numeric_trial(tmp_path, monkeypatch):
    from tests.strength_ui_harness import install, legacy, send

    install(monkeypatch)
    repo, _, instance, rows, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    observed = (datetime.now(timezone.utc) - timedelta(days=29)).isoformat()
    save_state(repo, observed_at=observed, pain="reported", muscle="chest")
    app = PAGE["HELP"]["open_app"](repo.path)
    go(app, "力量")
    assert not app.exception and not app.error
    assert send(app, "advice", {"instance_id": instance["id"]})["status"] == "saved"
    legacy(app, "recommendations", instance_id=instance["id"])
    advice = PAGE["latest"](repo, instance)
    assert advice["daily_decisions"]["input_record_ids"] == [row["set_uuid"] for row in rows]
    assert not numeric(advice)
    assert advice["body"]["metrics"]["STATE-PAIN"]["value"] is None
    assert [row["observed_at"] for row in advice["dated_symptom_observations"]] == [observed]
    text = PAGE["page_text"](app)
    assert "最近可见的疼痛自评" in text and observed in text
    assert "有疼痛或不适，需按当前情况复核" in text
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


@pytest.mark.parametrize("scope", ["historical_later", "current_duplicate"])
def test_actual_started_draft_pain_restricts_other_options_without_becoming_completed_work(tmp_path, monkeypatch, scope):
    repo, svc, instance, rows, _, _ = PAGE["ordinary_setup"](tmp_path, monkeypatch)
    if scope == "historical_later":
        row = svc.get_set(rows[-1]["id"])
        restricted = svc.edit_set(row["id"], {"completion_state": "draft", "ended_at": None,
            "pain_flag": True, "quality_status": "technique_limited", "stop_reason": "pain"},
            base_revision=row["revision"])
    else:
        duplicate = svc.add_exercise(instance["session_id"], instance["catalog_id"], instance["condition"])
        restricted = svc.add_set(duplicate["id"], {"completion_state": "draft",
            "started_at": datetime.now(timezone.utc).isoformat(), "pain_flag": True,
            "quality_status": "technique_limited", "stop_reason": "pain"})
    advice = current_advice(repo, instance["id"])
    assert restricted["completion_state"] == "draft" and restricted["started_at"] and not restricted["ended_at"]
    assert not numeric(advice)
    for group in advice["groups"]:
        for option in group["options"]:
            check = option["metric"]["candidate_applicability"]
            assert check["status"] == "restricted"
            assert any(item["record_id"] == restricted["set_uuid"] and "pain_reported" in item["reason_codes"]
                       for item in check["checks"])
    if scope == "historical_later":
        factual = next(row for row in advice["daily_history"]["records"] if row["set_uuid"] == restricted["set_uuid"])
        assert factual["completion_state"] == "draft"
        own = [option for group in advice["groups"] for option in group["options"]
               if option["basis"]["source_set_id"] == restricted["set_uuid"]]
        assert all("completed_work_set_with_positive_observed_repetitions_required" in option["metric"]["reason_codes"]
                   for option in own)
    else:
        assert restricted["set_uuid"] not in advice["daily_decisions"]["input_record_ids"]
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()
