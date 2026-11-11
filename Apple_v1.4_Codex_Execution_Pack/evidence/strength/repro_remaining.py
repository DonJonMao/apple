"""Synthetic, read-only engine audit for HEAD 912aefc; not efficacy evidence."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from healthzip.science import evaluate, evaluate_all
from healthzip.science.registry import calibration_matches
from healthzip.science.semantics import analysis_task

START = "2026-09-01T00:00:00+00:00"
END = "2026-11-12T00:00:00+00:00"
CUTOFF = "2026-11-11T12:00:00+00:00"
PROTOCOL = {
    "protocol_id": "review_reference", "version": "1",
    "reference_policy_id": "first_work_set", "effort_protocol": "target_rir_2",
    "tempo": "controlled", "rest_protocol": "user_180s",
}


def row(index, load, reps, exercise="bench"):
    moment = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(days=index*3)
    return {
        "id": f"{exercise}-set-{index}", "set_id": f"{exercise}-set-{index}",
        "session_id": f"session-{index}", "user_id": "synthetic_review",
        "record_kind": "strength_set", "exercise_id": exercise, "definition_version": 1,
        "equipment_instance_id": exercise+"-equipment", "load_basis": "external_total_kg",
        "load_basis_confirmed": True, "load_value": load, "load_unit": "kg",
        "measurement_mode": "repetitions", "side": "both",
        "repetition_semantics": "simultaneous", "rom_protocol": "user_full",
        "settings": {}, "settings_confirmed": True, "reference_protocol": PROTOCOL,
        "set_position": 1, "role": "work", "status": "completed", "reps": reps,
        "rir": 2, "stop_reason": "target_rir_stop", "is_reference": True,
        "reference_declared_at": START, "quality_status": "acceptable",
        "event_end": moment.isoformat(), "available_at": moment.isoformat(),
    }


def metric(mid, rows):
    return evaluate(mid, rows, cutoff_time=CUTOFF, window_start=START, window_end=END)


def concise(m):
    return {k: m[k] for k in ("value", "data_status", "valid_n", "reason_codes")}


old_load = [row(i, 30, v) for i,v in enumerate((10, 12, 11))]
new_load = [row(i+3, 32.5, v) for i,v in enumerate((8, 10, 9))]
both = old_load+new_load
combined = evaluate_all(both, cutoff_time=CUTOFF, window_start=START, window_end=END)
load_result = {
    "old_load_only": concise(metric("STR-19", old_load)),
    "new_load_only": concise(metric("STR-19", new_load)),
    "all_history_STR19": concise(combined["STR-19"]),
    "task_count": len(combined["STR-19"]["task_results"]),
    "distinct_task_ids": len({analysis_task(r)["task_id"] for r in both}),
}
assert load_result["old_load_only"]["data_status"] == "valid"
assert load_result["new_load_only"]["data_status"] == "valid"
assert load_result["all_history_STR19"]["data_status"] == "incompatible"
assert load_result["task_count"] == 1

# This tests only an applicability predicate. It is intentionally NOT inserted
# into any registry or represented as actual real-world validation.
artifact_shape_for_predicate_test = {
    "scope_status": "validated_for_scope", "data_kind": "real", "independent_holdout": True,
    "metric_ids": ["STR-22"], "model_version": "ols_true_time_student_t_v1",
    "scope": {"exercise_id": "bench", "population": "trained_adults",
              "outcome_unit": "repetitions", "protocol_id": "reference_v1"},
}
scope_results = {}
for label, supplied_scope in {
    "full_correct_scope": dict(artifact_shape_for_predicate_test["scope"]),
    "full_wrong_exercise": {**artifact_shape_for_predicate_test["scope"], "exercise_id": "squat"},
    "missing_exercise_unit_protocol": {"population": "trained_adults"},
    "empty_scope": {},
}.items():
    scope_results[label] = calibration_matches(artifact_shape_for_predicate_test, metric_id="STR-22",
                                                scope=supplied_scope, model_version="ols_true_time_student_t_v1")
assert scope_results == {"full_correct_scope": True, "full_wrong_exercise": False,
                        "missing_exercise_unit_protocol": True, "empty_scope": False}

# The classification gate calls STR-22 directly; its dimensional validation
# cannot depend on another metric (STR-21) being invoked first. Demonstrate the
# asymmetry without making a calibrated inference or inventing real data.
bad_delta = {"lower_magnitude": 1, "upper_magnitude": 1, "unit": "kg", "declared_before": START}
unit_results = {}
for mid in ("STR-21", "STR-22"):
    try:
        out = evaluate(mid, new_load, cutoff_time=CUTOFF, window_start=START, window_end=END,
                       context={"practical_equivalence": bad_delta, "outcome_unit": "repetitions"})
        unit_results[mid] = {"raised": False, "reason_codes": out["reason_codes"], "retained_delta": (out.get("value") or {}).get("practical_equivalence")}
    except ValueError as exc:
        unit_results[mid] = {"raised": True, "error": str(exc)}
assert unit_results["STR-21"]["raised"] is True
assert unit_results["STR-22"]["raised"] is False

output = {
    "scope": "Synthetic read-only code review, not human calibration or efficacy evidence",
    "load_change_invalidates_all_descriptive_trends": load_result,
    "calibration_applicability_missing_fields_accepted": scope_results,
    "equivalence_unit_check_not_shared_with_classifier": unit_results,
}
path = Path(__file__).with_suffix(".json")
path.write_text(json.dumps(output, ensure_ascii=False, indent=2)+"\n")
print(json.dumps({"output": str(path), "load_strata": {
    "old_only": load_result["old_load_only"]["data_status"],
    "new_only": load_result["new_load_only"]["data_status"],
    "all": load_result["all_history_STR19"]["data_status"],
    "task_count": load_result["task_count"]}, "scope_checks": scope_results,
    "unit_checks": unit_results}, ensure_ascii=False, indent=2))
