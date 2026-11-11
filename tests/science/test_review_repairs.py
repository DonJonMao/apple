"""Focused scientific contract regressions from the post-publication review."""

from test_contracts_and_strength import CUTOFF, END, START, row, run

from healthzip.science import ParameterRegistry


def test_r01_each_exercise_in_a_session_keeps_its_reference():
    rows = [row(i, session_id=f"session-{i}", id=f"{exercise}-{i}", set_id=f"{exercise}-{i}", exercise_id=exercise)
            for i in range(1, 4) for exercise in ("bench", "squat")]
    result = run("STR-11", rows)
    assert result["valid_n"] == 6
    assert len(result["value"]) == 6


def test_r02_protocol_identity_and_version_are_part_of_measurement_contract():
    from healthzip.science.semantics import comparable, flatten_record
    original = row(reference_protocol={"protocol_id": "press-protocol", "version": "1",
        "reference_policy_id": "first-work", "effort_protocol": "target-rir-2", "tempo": "controlled", "rest_protocol": "180s"})
    changed = {**original, "reference_protocol": {**original["reference_protocol"], "version": "2"}}
    assert flatten_record(original).get("reference_protocol_id") == "press-protocol"
    assert not comparable(flatten_record(original), flatten_record(changed), protocol=True)[0]


def test_r10_registered_look_alpha_controls_actual_interval(tmp_path):
    from healthzip.science.contracts import Window, canonical_hash, select_as_of
    from healthzip.science.semantics import analysis_task, flatten_record
    registry = ParameterRegistry(str(tmp_path / "registry.sqlite3"))
    registry.register_family("family", .05, {"declared_before": START, "metrics": ["STR-20"]})
    rows = [row(1, reps=8), row(2, reps=11), row(3, reps=9)]
    window = Window(START, END, CUTOFF)
    selected, _ = select_as_of([flatten_record(r) for r in rows], window)
    digest = canonical_hash({"records": selected, "window": window.as_dict(), "cutoff_time": CUTOFF, "data_version": "v1"})
    task_id = analysis_task(selected[0])["task_id"]
    allocation = registry.allocate_look("family", digest, "STR-20", data_version="v1", task_id=task_id, cutoff_time=CUTOFF)
    context = {"look_allocation": allocation, "look_registry_path": str(tmp_path / "registry.sqlite3"), "data_version": "v1"}
    result = run("STR-20", rows, context)
    assert result["uncertainty"]["level"] == 1 - allocation["alpha_look"]
    assert registry.allocate_look("family", digest, "STR-20", data_version="v1", task_id=task_id, cutoff_time=CUTOFF) == allocation
    assert run("STR-20", rows, {**context, "alpha_look": .5})["uncertainty"] == result["uncertainty"]
    assert run("STR-20", rows, {**context, "data_version": "v2"})["value"] is None
    assert run("STR-20", rows, {**context, "look_allocation": {**allocation, "alpha_look": .4}})["value"] is None
    assert run("STR-24", rows, {**context, "look_metric_id": "STR-20"})["data_status"] == "valid"
    registry.close()


def test_followup_unknown_quality_is_not_a_failed_task():
    base = {"recommendation_id": "review", "event_end": "2026-10-10T12:00:00+00:00",
            "available_at": "2026-10-10T12:01:00+00:00", "execution_state": "executed",
            "frozen_targets": {"reps": {"min": 8, "max": 8}}, "actual": {"reps": 8}}
    outcomes = [{**base, "recommendation_id": str(index), "quality_comparable": quality}
                for index, quality in enumerate((True, False, None))]
    details = run("STR-27", context={"recommendation_outcomes": outcomes})["value"]
    assert [item["short_term_success"] for item in details] == [True, False, None]
    summary = run("STR-28", context={"recommendation_outcomes": outcomes})["value"]
    assert summary["success_denominator"] == 2 and summary["missing_outcomes"] == 1


def test_r01_equal_recorded_numbers_with_different_units_are_not_one_trend():
    rows = [row(1, load_value=50, load_unit="kg"), row(2, load_value=50, load_unit="lb"), row(3, load_value=50, load_unit="kg")]
    assert run("STR-19", rows)["data_status"] == "incompatible"
