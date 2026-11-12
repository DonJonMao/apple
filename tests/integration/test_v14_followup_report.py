"""Synthetic Repository observations verify execution and later follow-up wiring."""

from datetime import datetime, timedelta, timezone

import pytest

from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.training.followup import freeze_window
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService


@pytest.fixture
def trial(tmp_path, monkeypatch):
    import healthzip.training.service as service_module

    clock = [datetime(2026, 1, 1, 8, tzinfo=timezone.utc)]
    monkeypatch.setattr(service_module, "timestamp", lambda value=None: timestamp(value) if value is not None else clock[0].isoformat())
    repo = Repository(tmp_path / "synthetic-followup.sqlite3")
    svc = TrainingService(repo)
    machine = svc.create_equipment("Synthetic station", "barbell")
    condition = {"equipment_instance_id": machine["id"], "load_basis": "external_total_kg", "load_basis_confirmed": True,
        "side": "both", "repetition_semantics": "simultaneous", "rom_protocol": "full_declared",
        "settings": {"grip": "fixed"}, "settings_confirmed": True,
        "reference_protocol": {"protocol_id": "synthetic", "version": "1", "reference_policy_id": "first-work",
            "effort_protocol": "target-rir-2", "tempo": "controlled", "rest_protocol": "user-declared"}}

    def add_reference(day, *, load=52.5, reps=9, changed=None):
        clock[0] = datetime(2026, 1, day, 8, tzinfo=timezone.utc)
        session = svc.start_session("Synthetic followup")
        instance = svc.add_exercise(session["id"], "psa.ex.barbell_bench_press", {**condition, **(changed or {})})
        draft = svc.add_set(instance["id"], {"reference_set": True})
        clock[0] += timedelta(minutes=2)
        actual = svc.edit_set(draft["set_uuid"], {"completion_state": "completed", "load_value": load, "load_unit": "kg",
            "reps": reps, "rir": 2, "quality_status": "acceptable", "pain_flag": False, "stop_reason": "target_rir",
            "started_at": (clock[0] - timedelta(minutes=1)).isoformat(), "ended_at": clock[0].isoformat()}, base_revision=draft["revision"])
        svc.end_session(session["id"])
        return actual

    baseline = add_reference(1, load=50, reps=10)
    clock[0] = datetime(2026, 1, 2, 8, tzinfo=timezone.utc)
    session = svc.start_session("Synthetic execution")
    instance = svc.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
    draft = svc.add_set(instance["id"], {"reference_set": True})
    clock[0] += timedelta(minutes=1)
    candidate = {"candidate_id": "synthetic-trial", "target_session": session["session_uuid"], "action_kind": "heavier_lower_reps",
        "proposed_change": {"load": 52.5, "load_unit": "kg", "load_basis": "external_total_kg"},
        "target_range": {"reps_min": 8, "reps_max": 8, "rir_min": 2, "rir_max": 2},
        "reason_evidence_ids": [], "eligibility": [], "uncertainty": {}, "verification_protocol": "synthetic test",
        "followup_window": freeze_window({"start": "2026-01-03T00:00:00Z", "end": "2026-02-10T00:00:00Z", "timezone": "UTC"}, declared_at=clock[0].isoformat()),
        "rule_version": "synthetic-software-test-only", "user_choice": None}
    record = svc.record_recommendation(candidate, {"condition": instance["condition"], "session_exercise_id": instance["id"],
        "reference_set_id": baseline["set_uuid"], "source_record_ids": [baseline["set_uuid"]], "strategy": "heavier_lower_reps",
        "advice_context": {"task_id": "synthetic-task"}}, cutoff_time=clock[0].isoformat(), theory_version="synthetic-not-scientific-evidence")
    clock[0] += timedelta(minutes=2)
    actual = svc.edit_set(draft["set_uuid"], {"completion_state": "completed", "load_value": 52.5, "load_unit": "kg", "reps": 8,
        "rir": 2, "quality_status": "acceptable", "pain_flag": False, "stop_reason": "target_rir",
        "started_at": (clock[0] - timedelta(minutes=1)).isoformat(), "ended_at": clock[0].isoformat()}, base_revision=draft["revision"])
    clock[0] += timedelta(minutes=1)
    svc.recommendation_feedback(record["candidate_id"], user_choice="accepted", execution_state="executed", actual_record_ids=[actual["set_uuid"]])
    svc.end_session(session["id"])
    yield repo, svc, clock, record, baseline, actual, add_reference
    repo.close()


def report(repo, cutoff, **kwargs):
    return analyze(repo, cutoff_time=cutoff, timezone_name="UTC", use_cache=False, **kwargs)["metrics"]["REPORT-RECOMMENDATION-FOLLOWUP"]["value"]


def test_repository_execution_differences_and_same_load_followup(trial):
    repo, svc, clock, record, baseline, actual, add = trial
    followup = add(4, reps=10)
    add(5, load=55, reps=8)
    other = svc.create_equipment("Synthetic other station", "barbell")
    add(6, changed={"equipment_instance_id": other["id"]})
    result = report(repo, "2026-01-08T00:00:00Z")
    item = result["execution"]["value"][0]
    assert item["short_term_success"] is True
    comparisons = {x["endpoint"]: x for x in item["target_comparisons"]}
    assert comparisons["load_value"]["target_unit"] == "kg" and comparisons["reps"]["actual_minus_min"] == 0
    assert item["execution_change"]["differences"]["reps"]["value"] == -2
    assert item["execution_change"]["load_change"]["total_load_change_kg"] == 2.5
    window = result["followup_windows"][0]
    assert window["status"] == "observed" and len(window["observations"]) == 1
    assert window["observations"][0]["after"]["record_id"] == followup["set_uuid"]
    assert window["observations"][0]["differences"]["reps"]["value"] == 2
    assert {reason for row in window["exclusions"] for reason in row["reason_codes"]} >= {"different_fixed_load_outcome_series", "physical_condition_changed"}
    assert result["causal_effect"] is None
    summary = result["summary"]["value"]
    assert summary["execution_states"]["executed"] == 1 and summary["comparable_followup_observations"] == 1
    assert report(repo, "2026-01-08T00:00:00Z")["summary"]["value"] == summary
    assert svc.list_recommendations()[0]["candidate"] == record["candidate"]


def test_repository_execution_load_unit_conversion_matches_success_and_display(trial):
    repo, svc, clock, record, _, actual, _ = trial
    clock[0] = datetime(2026, 1, 2, 8, 1, tzinfo=timezone.utc)
    candidate = {**record["candidate"], "candidate_id": "synthetic-unit-trial",
        "proposed_change": {**record["candidate"]["proposed_change"], "load": 45.359237}}
    svc.record_recommendation(candidate, record["input_snapshot"], cutoff_time=clock[0].isoformat(), theory_version="synthetic")
    clock[0] = datetime(2026, 1, 2, 8, 5, tzinfo=timezone.utc)
    svc.edit_set(actual["set_uuid"], {"load_value": 100, "load_unit": "lb"}, base_revision=actual["revision"])
    svc.recommendation_feedback(candidate["candidate_id"], user_choice="accepted", execution_state="executed", actual_record_ids=[actual["set_uuid"]])
    result = report(repo, "2026-01-08T00:00:00Z")
    item = next(x for x in result["execution"]["value"] if x["recommendation_id"] == candidate["candidate_id"])
    assert item["short_term_success"] is True
    load = next(x for x in item["target_comparisons"] if x["endpoint"] == "load_value")
    assert load["actual"] == item["actual"]["load_value"] == 45.359237
    assert load["actual_minus_min"] == 0 and load["actual_unit"] == "kg"
    assert load["load_normalization"]["raw_value"] == 100 and load["load_normalization"]["raw_unit"] == "lb"


def test_incompatible_load_units_keep_execution_unknown(trial):
    from healthzip.analytics.v13 import _outcome, snapshot
    from healthzip.science import evaluate
    from healthzip.science.semantics import flatten_record

    repo, svc, _, _, _, actual, _ = trial
    record = svc.list_recommendations()[0]
    rows, _ = snapshot(repo, "2026-01-08T00:00:00Z")
    row = flatten_record(next(r for r in rows if r.get("set_uuid") == actual["set_uuid"]))
    for key in ("actual", "actual_json", "condition", "condition_json"):
        row.pop(key, None)
    row["load_unit"] = "level"
    outcome = _outcome(record, record["feedback"][-1], [row], cutoff_time="2026-01-08T00:00:00Z")
    output = evaluate("STR-27", [], cutoff_time="2026-01-08T00:00:00Z", window_start="2026-01-01T00:00:00Z",
        window_end="2026-02-01T00:00:00Z", context={"recommendation_outcomes": [outcome]})
    assert output["value"][0]["short_term_success"] is None
    load = next(x for x in output["value"][0]["target_comparisons"] if x["endpoint"] == "load_value")
    assert load["actual_minus_min"] is None and load["load_normalization"]["raw_unit"] == "level"


def test_followup_respects_asof_revisions_and_deletion(trial):
    repo, svc, clock, _, baseline, _, add = trial
    followup = add(4, reps=10)
    historical = report(repo, "2026-01-08T00:00:00Z")
    clock[0] = datetime(2026, 1, 9, tzinfo=timezone.utc)
    svc.edit_set(followup["set_uuid"], {"reps": 12}, base_revision=followup["revision"])
    svc.edit_set(baseline["set_uuid"], {"reps": 11}, base_revision=baseline["revision"])
    replay = report(repo, "2026-01-08T00:00:00Z")
    assert replay["followup_windows"] == historical["followup_windows"]
    current = report(repo, "2026-01-09T01:00:00Z")
    assert current["followup_windows"][0]["observations"][0]["differences"]["reps"]["value"] == 4
    assert current["execution"]["value"][0]["execution_change"]["differences"]["reps"]["value"] == -3
    clock[0] = datetime(2026, 1, 10, tzinfo=timezone.utc)
    current_row = svc.get_set(followup["set_uuid"])
    svc.delete_set(followup["set_uuid"], base_revision=current_row["revision"])
    assert report(repo, "2026-01-08T00:00:00Z")["followup_windows"] == historical["followup_windows"]
    assert report(repo, "2026-02-11T00:00:00Z", window_days=60)["followup_windows"][0]["status"] == "no_comparable_observation"


def test_later_derived_snapshot_cannot_be_reused_at_earlier_cutoff(trial):
    from healthzip.analytics.v13 import snapshot
    from healthzip.science import evaluate

    repo, _, _, _, _, _, add = trial
    add(9, reps=99)
    _, context = snapshot(repo, "2026-01-10T00:00:00Z")
    output = evaluate("REPORT-RECOMMENDATION-FOLLOWUP", [], cutoff_time="2026-01-08T00:00:00Z",
        window_start="2026-01-01T00:00:00Z", window_end="2026-02-01T00:00:00Z", context=context)
    followup = output["value"]["followup_windows"][0]
    assert followup["status"] == "unavailable" and not followup["observations"]
    assert followup["reason_codes"] == ["followup_snapshot_after_analysis_cutoff_or_unverified"]


def test_followup_window_keeps_old_candidate_in_later_calendar_report(trial):
    repo, _, _, _, _, _, _ = trial
    value = report(repo, "2026-02-11T00:00:00Z", period="month")
    assert len(value["execution"]["value"]) == 1
    assert value["execution"]["value"][0]["report_membership"] == "predeclared_followup_overlap"
    assert value["followup_windows"][0]["status"] == "no_comparable_observation"


@pytest.mark.parametrize("state,status", [("not_executed", "not_executed"), ("partially_executed", "execution_unconfirmed"), ("unknown", "execution_unconfirmed")])
def test_nonexecution_and_missing_followup_are_separate(trial, state, status):
    repo, svc, clock, record, _, actual, add = trial
    add(4)
    clock[0] = datetime(2026, 1, 5, tzinfo=timezone.utc)
    svc.recommendation_feedback(record["candidate_id"], user_choice="accepted", execution_state=state,
        nonexecution_reason="synthetic choice", actual_record_ids=[actual["set_uuid"]] if state == "partially_executed" else [])
    value = report(repo, "2026-02-11T00:00:00Z", window_days=60)
    assert value["followup_windows"][0]["status"] == status
    assert not value["followup_windows"][0]["observations"]
    assert value["summary"]["value"]["success_denominator"] == 0


def test_window_is_explicit_prospective_and_timezone_aware():
    assert freeze_window(None, declared_at="2026-01-02T00:00:00+00:00") is None
    for start, end in [("2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z"),
                       ("2026-01-03T00:00:00Z", "2026-01-02T00:00:00Z"),
                       ("2026-01-03T00:00:00", "2026-01-04T00:00:00Z")]:
        with pytest.raises(ValueError):
            freeze_window({"start": start, "end": end, "timezone": "UTC"}, declared_at="2026-01-02T00:00:00+00:00")


def test_repository_rejects_window_declared_after_candidate_creation(trial):
    repo, svc, clock, record, _, _, _ = trial
    candidate = {**record["candidate"], "candidate_id": "synthetic-retrospective-window",
        "followup_window": {**record["candidate"]["followup_window"], "declared_at": "2026-01-03T00:00:00+00:00"}}
    with pytest.raises(ValueError, match="创建前"):
        svc.record_recommendation(candidate, record["input_snapshot"], cutoff_time=clock[0].isoformat(), theory_version="synthetic")
    clock[0] = datetime(2026, 1, 4, tzinfo=timezone.utc)
    candidate["followup_window"]["declared_at"] = clock[0].isoformat()
    with pytest.raises(ValueError, match="起点"):
        svc.record_recommendation(candidate, record["input_snapshot"], cutoff_time=clock[0].isoformat(), theory_version="synthetic")


def test_followup_interval_rir_is_not_a_point_difference_and_future_is_hidden(trial):
    repo, svc, clock, _, _, _, add = trial
    first = add(4, reps=10)
    clock[0] += timedelta(minutes=1)
    svc.edit_set(first["set_uuid"], {"rir": 4, "rir_qualifier": "at_least"}, base_revision=first["revision"])
    add(9, reps=99)
    result = report(repo, "2026-01-08T00:00:00Z")
    observed = result["followup_windows"][0]["observations"]
    assert len(observed) == 1
    assert observed[0]["after"]["rir_interval"] == {"lower": 4, "upper": None}
    assert observed[0]["differences"]["rir"]["value"] is None
    assert observed[0]["differences"]["reps"]["value"] == 2


def test_visible_followup_report_shows_target_actual_and_later_difference(trial):
    from streamlit.testing.v1 import AppTest

    repo, _, _, _, _, _, add = trial
    add(4, reps=10)
    value = report(repo, "2026-01-08T00:00:00Z")
    app = AppTest.from_string("from healthzip.ui.followup_report import render_followup_report\n"
                              f"render_followup_report({value!r})").run()
    assert not app.exception and not app.error
    assert len(app.dataframe) == 2
    target, later = (table.value for table in app.dataframe)
    assert set(target["记录项"]) == {"负荷", "次数", "RIR"}
    assert target.loc[target["记录项"] == "负荷", "实做"].iloc[0] == 52.5
    assert later.loc[later["比较项"] == "次数", "观察差值"].iloc[0] == 2


def test_visible_candidate_form_freezes_optional_user_window(tmp_path, monkeypatch):
    from test_v14_advice_flow import HELPERS, _clean_candidate

    repo, svc, instance, _ = _clean_candidate(tmp_path, monkeypatch)
    path = repo.path
    repo.close()
    app = HELPERS["open_app"](path)
    key = instance["id"]
    app.checkbox(key="followup_enabled_" + key).check().run()
    start = datetime.now(timezone.utc) + timedelta(days=2)
    end = start + timedelta(days=3)
    app.text_input(key="followup_start_" + key).set_value(start.isoformat())
    app.text_input(key="followup_end_" + key).set_value(end.isoformat())
    app.text_input(key="loads_" + key).set_value("50,52.5,55")
    app.button(key="candidate_" + key).click().run(timeout=30)
    assert not app.exception and not app.error
    repo = Repository(path)
    candidate = TrainingService(repo).list_recommendations()[0]["candidate"]
    assert candidate["followup_window"]["start"] == start.isoformat()
    assert candidate["followup_window"]["end"] == end.isoformat()
    assert candidate["followup_window"]["origin"] == "user_declared"
    repo.close()
