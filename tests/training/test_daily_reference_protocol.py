"""Daily recording does not nominate specialist measurements.

The former automatic first-planned rule is superseded. Historical identities
remain readable, and optional manual references must obey their named protocol.
"""
import json

import pytest

from healthzip.db.repository import Repository
from healthzip.training.reference import policy_candidate, specialist_policy_allows
from healthzip.training.service import TrainingService

EXERCISE = "psa.ex.smith_incline_press"
TARGET = {"reps_min": 8, "reps_max": 12, "rir": 2}


@pytest.fixture
def service(tmp_path):
    repo = Repository(tmp_path / "synthetic.sqlite3")
    yield TrainingService(repo)
    repo.close()


def condition(svc, policy=None):
    machine = svc.create_equipment("Synthetic station", "smith")
    result = {"equipment_instance_id": machine["id"], "load_basis": "plates_per_side_kg",
        "load_basis_confirmed": True, "settings": {"position": "fixed"}, "settings_confirmed": True,
        "side": "both", "repetition_semantics": "simultaneous", "rom_protocol": "user-full",
        "symmetric_loading": True}
    if policy:
        result["reference_protocol"] = {"protocol_id": "synthetic", "version": "1",
            "reference_policy_id": policy, "effort_protocol": "rir-2", "tempo": "controlled",
            "rest_protocol": "180-sec"}
    return result


def instance(svc, policy=None):
    session = svc.start_session("Synthetic session")
    return svc.add_exercise(session["id"], EXERCISE, condition(svc, policy))


def test_plan_creation_edit_reorder_and_replace_do_not_nominate(service):
    c = condition(service, "first-work-set")
    plan = service.create_template("Synthetic plan", [{"exercise_id": EXERCISE,
        "condition": c, "targets": {"sets": [TARGET, {**TARGET, "reference_set": True}]}}])
    session = service.start_session(template_id=plan["id"])
    current = session["exercises"][0]
    first = current["sets"][0]
    assert all(not r["reference_set"] and not r["reference_declared_at"] for r in current["sets"])
    service.update_set_target(first["id"], {**TARGET, "reps_min": 9}, base_revision=first["revision"])
    service.add_set(current["id"], planned=TARGET)
    added = service.add_exercise(session["id"], EXERCISE, c, targets={"sets": [TARGET]})
    parent = service.get_session(session["id"])
    service.reorder_exercises(parent["id"], [added["id"], current["id"]], base_revision=parent["revision"])
    current = service.get_session_exercise(current["id"])
    changed = service.replace_exercise(current["id"], "psa.ex.smith_squat", c, reason="Synthetic replacement",
        targets={"sets": [TARGET]}, base_revision=current["revision"])
    assert not changed["sets"][0]["reference_set"]
    assert all(not r["reference_set"] for r in service.get_session(parent["id"])["sets"])
    assert service.conn.execute("SELECT count(*) FROM training_event WHERE action='reference_selection'").fetchone()[0] == 0


@pytest.mark.parametrize("policy", ["first-work-set", "predeclared-first-work-set"])
def test_first_work_protocol_cannot_skip_unplanned_first_work(service, policy):
    current = instance(service, policy)
    first = service.add_set(current["id"])
    second = service.add_set(current["id"], planned=TARGET)
    assert policy_candidate(service.get_session_exercise(current["id"])["sets"], policy)["set_uuid"] == first["set_uuid"]
    with pytest.raises(ValueError, match="协议冲突"):
        service.edit_set(second["id"], {"reference_set": True}, base_revision=second["revision"])
    selected = service.edit_set(first["id"], {"reference_set": True}, base_revision=first["revision"])
    assert selected["reference_selection"]["selection_protocol"] == policy
    assert not service.get_set(second["id"])["reference_set"]


def test_first_planned_work_protocol_has_distinct_position(service):
    current = instance(service, "first-planned-work-set")
    first = service.add_set(current["id"])
    second = service.add_set(current["id"], planned=TARGET)
    with pytest.raises(ValueError, match="协议冲突"):
        service.edit_set(first["id"], {"reference_set": True}, base_revision=first["revision"])
    selected = service.edit_set(second["id"], {"reference_set": True}, base_revision=second["revision"])
    assert selected["reference_selection"]["selection_protocol"] == "first-planned-work-set"
    assert selected["reference_selection"]["origin"] == "user_explicit"
    assert not service.get_set(first["id"])["reference_set"]


def test_manual_choice_without_declared_policy_does_not_claim_first_protocol(service):
    current = instance(service)
    service.add_set(current["id"])
    second = service.add_set(current["id"], {"reference_set": True}, planned=TARGET)
    assert second["reference_selection"]["selection_protocol"] == "explicit-set"
    assert second["reference_selection"]["declared_plan_protocol"] is None


def test_unknown_policy_is_not_interpreted_by_explicit_plan_hint(service):
    current = instance(service, "unknown-protocol")
    row = service.add_set(current["id"], planned={**TARGET, "reference_set": True})
    assert not row["reference_set"]
    selected = service.edit_set(row["id"], {"reference_set": True}, base_revision=row["revision"])
    assert selected["reference_selection"]["selection_protocol"] == "explicit-set"
    assert selected["reference_selection"]["policy_interpretation"] == "unrecognized_not_interpreted"
    assert selected["reference_selection"]["declared_plan_protocol"]["reference_policy_id"] == "unknown-protocol"


def test_legacy_system_reference_is_not_rewritten_on_plan_edits(service):
    current = instance(service)
    row = service.add_set(current["id"], {"reference_set": True}, planned=TARGET)
    legacy = {**row["reference_selection"], "origin": "system_plan_protocol",
        "selection_protocol": "first-planned-work-set", "selection_protocol_version": "1.0.0"}
    # This fixture represents already persisted d48 provenance; no daily test
    # uses it as a source or upgrades ordinary records into references.
    service.conn.execute("UPDATE strength_set SET reference_selection_json=? WHERE id=?", (json.dumps(legacy), row["id"]))
    service.conn.commit()
    before = service.get_set(row["id"])
    revised = service.update_set_target(row["id"], {**TARGET, "reps_min": 9}, base_revision=before["revision"])
    service.add_set(current["id"], planned=TARGET)
    assert revised["reference_selection"] == legacy
    assert revised["reference_declared_at"] == before["reference_declared_at"]
    assert revised["reference_set"] == before["reference_set"]


@pytest.mark.parametrize("state", ["draft", "aborted", "skipped", "completed"])
def test_specialist_filter_locates_first_before_eligibility(state):
    first = {"session_id": 1, "session_exercise_id": "x", "set_id": "a", "set_position": 1,
        "role": "work", "status": state, "reference_policy_id": "first-work-set", "planned": {}}
    second = {**first, "set_id": "b", "set_position": 2, "status": "completed", "planned": TARGET}
    assert specialist_policy_allows(first, [first, second])
    assert not specialist_policy_allows(second, [first, second])
    planned = [{**r, "reference_policy_id": "first-planned-work-set"} for r in (first, second)]
    assert not specialist_policy_allows(planned[0], planned)
    assert specialist_policy_allows(planned[1], planned)


@pytest.mark.parametrize("policy,expected", [("first-work-set", 0), ("predeclared-first-work-set", 0),
    ("first-planned-work-set", 1)])
def test_real_metric_preserves_unobserved_first_position_before_time_filter(policy, expected):
    from healthzip.science import evaluate, evaluate_all

    common = {"session_id": "session", "session_exercise_id": "instance", "user_id": "synthetic",
        "exercise_id": "bench", "definition_version": 1, "equipment_instance_id": "station",
        "load_basis": "external_total_kg", "load_basis_confirmed": True, "load_value": 60,
        "load_unit": "kg", "measurement_mode": "repetitions", "side": "both",
        "repetition_semantics": "simultaneous", "rom_protocol": "full", "settings": {},
        "settings_confirmed": True, "role": "work", "status": "completed", "reps": 10,
        "rir": 2, "quality_status": "acceptable", "available_at": "2026-11-01T09:00:00+00:00",
        "reference_protocol": {"protocol_id": "synthetic", "version": "1", "reference_policy_id": policy,
            "effort_protocol": "rir-2", "tempo": "controlled", "rest_protocol": "180-sec"}}
    first = {**common, "id": "first", "set_id": "first", "set_position": 1, "planned": {},
        "status": "draft", "reps": None, "event_end": None, "event_start": None, "is_reference": False}
    second = {**common, "id": "second", "set_id": "second", "set_position": 2, "planned": TARGET,
        "event_start": "2026-11-01T10:00:00+00:00", "event_end": "2026-11-01T10:00:30+00:00",
        "is_reference": True, "reference_declared_at": "2026-11-01T09:00:00+00:00"}
    parameters = {"cutoff_time": "2026-11-02T00:00:00+00:00", "window_start": "2026-11-01T00:00:00+00:00",
        "window_end": "2026-11-03T00:00:00+00:00"}
    separate = evaluate("STR-11", [first, second], **parameters)
    combined = evaluate_all([first, second], **parameters)
    assert separate["valid_n"] == expected
    assert combined["STR-11"]["valid_n"] == expected
    assert combined["STR-01"]["value"]["completed_work_parent_sets"] == 1
    if expected:
        assert separate["value"][0]["id"] == "second"
    else:
        assert "predesignated_reference_missing" in separate["reason_codes"]


@pytest.mark.parametrize("latest_role,allowed", [("warmup", True), ("work", False)])
def test_specialist_inventory_uses_latest_visible_role_revision(latest_role, allowed):
    from healthzip.science import evaluate

    common = {"session_id": 1, "session_exercise_id": "x", "reference_policy_id": "first-work-set"}
    old = {**common, "set_id": "first", "set_position": 1,
        "role": "work" if latest_role == "warmup" else "warmup", "revision": 1,
        "available_at": "2026-11-01T09:00:00+00:00"}
    corrected = {**old, "role": latest_role, "revision": 2, "available_at": "2026-11-01T10:00:00+00:00"}
    second = {**common, "set_id": "second", "set_position": 2, "role": "work", "revision": 1,
        "available_at": "2026-11-01T09:00:00+00:00"}
    assert specialist_policy_allows(second, [corrected, old, second]) is allowed
    assert specialist_policy_allows(second, [second, old, corrected]) is allowed
    # Real evaluate builds the position inventory before omitting the undated
    # first slot. Its older role cannot mask the visible correction.
    first_revisions = [{**item, "id": item["set_id"], "status": "draft"} for item in (corrected, old)]
    completed = {**second, "id": "second", "status": "completed", "measurement_mode": "repetitions",
        "reps": 8, "is_reference": True, "reference_declared_at": "2026-11-01T09:00:00+00:00",
        "event_start": "2026-11-01T11:00:00+00:00", "event_end": "2026-11-01T11:00:30+00:00"}
    actual = evaluate("STR-11", [*first_revisions, completed], cutoff_time="2026-11-02T00:00:00+00:00",
        window_start="2026-11-01T00:00:00+00:00", window_end="2026-11-03T00:00:00+00:00")
    assert actual["valid_n"] == int(allowed)
