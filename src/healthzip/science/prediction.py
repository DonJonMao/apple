"""Paired B0/B1 temporal evaluation, with unavailable features kept unavailable."""

from __future__ import annotations

import math
from collections import defaultdict

from .contracts import Window, finite, instant, result
from .registry import calibration_scope_check, task_calibration_scope
from .semantics import comparable, condition_key, outcome_series
from .strength import reference_rows


def _mae(values: list[float]):
    return sum(abs(v) for v in values) / len(values) if values else None


def _rmse(values: list[float]):
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else None


def paired_errors(predictions: list[dict]) -> dict:
    pairs = [p for p in predictions if all(finite(p.get(k)) is not None for k in ("actual", "B0", "B1"))]
    e0 = [p["actual"] - p["B0"] for p in pairs]
    e1 = [p["actual"] - p["B1"] for p in pairs]
    strata = defaultdict(list)
    for p in pairs:
        strata[str((p.get("user_id"), p.get("condition_key")))].append(p)
    return {"n_pairs": len(pairs), "eligible_n": len(predictions), "excluded_n": len(predictions) - len(pairs),
            "MAE_B0": _mae(e0), "MAE_B1": _mae(e1), "RMSE_B0": _rmse(e0), "RMSE_B1": _rmse(e1),
            "delta_MAE": _mae(e0) - _mae(e1) if pairs else None,
            "delta_RMSE": _rmse(e0) - _rmse(e1) if pairs else None,
            "fallback_n": sum(p.get("fallback") is True for p in pairs),
            "strata": {key: {"n": len(group), "MAE_B0": _mae([p["actual"] - p["B0"] for p in group]),
                             "MAE_B1": _mae([p["actual"] - p["B1"] for p in group])} for key, group in strata.items()},
            "independent_person_effect_validation": False}


def interval_evaluation(predictions: list[dict]) -> dict:
    eligible = [p for p in predictions if all(finite(p.get(k)) is not None for k in ("actual", "lower", "upper"))]
    groups = defaultdict(list)
    for row in eligible:
        if row["lower"] > row["upper"]:
            raise ValueError("prediction_interval_reversed")
        groups[str((row.get("user_id"), row.get("condition_key"), row.get("missingness"), row.get("nominal_level")))].append(row)
    return {"n": len(eligible), "total_n": len(predictions),
            "covered": sum(p["lower"] <= p["actual"] <= p["upper"] for p in eligible),
            "coverage": sum(p["lower"] <= p["actual"] <= p["upper"] for p in eligible) / len(eligible) if eligible else None,
            "mean_width": sum(p["upper"] - p["lower"] for p in eligible) / len(eligible) if eligible else None,
            "strata": {key: {"n": len(group), "coverage": sum(p["lower"] <= p["actual"] <= p["upper"] for p in group) / len(group),
                             "mean_width": sum(p["upper"] - p["lower"] for p in group) / len(group)} for key, group in groups.items()}}


def fit_b1(pairs: list[dict]) -> dict:
    """OLS through zero for predeclared state-change vs B0 residual model."""
    clean = [p for p in pairs if finite(p.get("state_delta")) is not None and finite(p.get("reps_delta")) is not None]
    if len(clean) < 2:
        return {"beta": None, "n": len(clean), "reason": "insufficient_training_pairs"}
    xx = sum(p["state_delta"] ** 2 for p in clean)
    if xx <= 0:
        return {"beta": None, "n": len(clean), "reason": "rank_deficient_state"}
    beta = sum(p["state_delta"] * p["reps_delta"] for p in clean) / xx
    return {"beta": beta, "n": len(clean), "reason": None, "model_version": "B1_single_state_delta_ols_v1",
            "interpretation": "predictive_association_not_intervention_effect"}


def forward_evaluate(observations: list[dict], *, split: dict, feature: str,
                     minimum_training_pairs: int = 2) -> dict:
    """Locked windows; paired test outputs and separate rolling-origin validation.

    State values must have their own availability and event-end timestamps and
    be visible at the *start* of the target session, including training rows.
    A target's session RPE measured afterward is therefore excluded.
    """
    train_end = instant(split["train_end"])
    validation_end = instant(split["validation_end"])
    test_end = instant(split["test_end"])
    if not train_end < validation_end < test_end:
        raise ValueError("ordered_disjoint_split_required")
    frozen = split.get("registered_at")
    if not frozen or instant(frozen) > train_end:
        raise ValueError("split_and_feature_must_be_preregistered")
    streams = defaultdict(list)
    exclusions = []
    for row in observations:
        key = condition_key(row)
        if key is None or not row.get("session_id") or finite(row.get("reps")) is None:
            exclusions.append({"id": row.get("id"), "reason": "comparable_reference_missing"})
            continue
        streams[(row.get("user_id"), key, row.get("load_value"), row.get("effort_protocol"))].append(row)
    predictions, validation, training_pairs = [], [], []
    held_users = set(split.get("heldout_users", []))
    for stream, values in streams.items():
        values.sort(key=lambda r: instant(r["event_end"]))
        pairs = []
        previous = None
        for row in values:
            if previous is None:
                previous = row
                continue
            cutoff = instant(row["session_started_at"])
            event = instant(row["event_end"])
            if instant(previous["event_end"]) > cutoff or instant(previous["available_at"]) > cutoff:
                exclusions.append({"id": row.get("id"), "reason": "previous_outcome_unavailable_at_cutoff"})
                previous = row
                continue
            def state_value(record):
                observation = record.get("features", {}).get(feature)
                if not observation:
                    return None
                if instant(observation["event_end"]) > instant(record["session_started_at"]) or instant(observation["available_at"]) > instant(record["session_started_at"]):
                    return None
                return finite(observation.get("value"))
            current_state, previous_state = state_value(row), state_value(previous)
            state_delta = current_state - previous_state if current_state is not None and previous_state is not None else None
            pair = {"state_delta": state_delta, "reps_delta": row["reps"] - previous["reps"],
                    "available_at": row["available_at"], "event_end": row["event_end"], "session_id": row["session_id"]}
            historical = [p for p in pairs if instant(p["available_at"]) <= cutoff and instant(p["event_end"]) < cutoff]
            # Freeze fitted model after validation. Test outcomes never train it.
            frozen_train = [p for p in historical if instant(p["event_end"]) < validation_end]
            model = fit_b1(frozen_train) if len(frozen_train) >= minimum_training_pairs else {"beta": None}
            b0 = previous["reps"]
            fallback = model["beta"] is None or state_delta is None
            b1 = b0 if fallback else b0 + model["beta"] * state_delta
            prediction = {"id": row.get("id"), "user_id": row.get("user_id"), "session_id": row["session_id"],
                          "condition_key": stream[1], "cutoff_time": cutoff.isoformat(), "actual": row["reps"],
                          "B0": b0, "B1": b1, "fallback": fallback,
                          "reason": "missing_or_unavailable_state" if state_delta is None else "insufficient_model" if fallback else None,
                          "training_session_ids": [p["session_id"] for p in frozen_train], "model_beta": model["beta"],
                          "target_state_delta": state_delta}
            if train_end <= event < validation_end and row.get("user_id") not in held_users:
                validation.append(prediction)
            elif validation_end <= event < test_end:
                predictions.append(prediction)
            if event < validation_end and row.get("user_id") not in held_users:
                training_pairs.append({**pair, "user_id": row.get("user_id")})
            if row.get("user_id") not in held_users:
                pairs.append(pair)
            previous = row
    # Held-out users contribute no outcomes to model fitting. Their own previous
    # observed task remains the B0 reference; incremental coefficient is learned
    # solely from other users before the frozen final training boundary.
    for prediction in predictions:
        if prediction["user_id"] not in held_users:
            continue
        candidates = [p for p in training_pairs if p["user_id"] not in held_users
                      and instant(p["available_at"]) <= instant(prediction["cutoff_time"])
                      and instant(p["event_end"]) < validation_end]
        model = fit_b1(candidates) if len(candidates) >= minimum_training_pairs else {"beta": None}
        delta = prediction["target_state_delta"]
        prediction["fallback"] = model["beta"] is None or delta is None
        prediction["B1"] = prediction["B0"] if prediction["fallback"] else prediction["B0"] + model["beta"] * delta
        prediction["reason"] = "heldout_user_state_or_cross_user_model_unavailable" if prediction["fallback"] else None
        prediction["training_session_ids"] = [p["session_id"] for p in candidates]
        prediction["training_user_ids"] = sorted({p["user_id"] for p in candidates})
        prediction["model_beta"] = model["beta"]
    val = paired_errors(validation)
    improvement = val["delta_MAE"] is not None and val["delta_MAE"] > 0
    return {"feature": feature, "split": split, "model_version": "B1_single_state_delta_ols_v1",
            "validation": val, "test": paired_errors(predictions), "test_predictions": predictions,
            "validation_predictions": validation, "excluded": exclusions,
            "release_choice": "B0", "research_choice": "B1_candidate" if improvement else "B0",
            "reason": "real_scope_calibration_required_even_if_simulation_improves",
            "heldout_user_results": paired_errors([p for p in predictions if p["user_id"] in held_users])}


def prediction_metric(metric_id: str, rows: list[dict], window: Window, context: dict) -> dict:
    def emit(value=None, status="valid", **extra):
        return result(metric_id, window, value, data_status=status, records=rows, **extra)
    if metric_id == "PRED-ERROR-GAIN":
        values = context.get("paired_predictions", [])
        return emit(paired_errors(values), "valid" if values else "insufficient", evidence_status="research_only",
                    valid_n=sum(all(finite(p.get(k)) is not None for k in ("actual", "B0", "B1")) for p in values),
                    total_n=len(values), count_domain="paired_test_exposures")
    if metric_id == "PRED-INTERVAL":
        values = context.get("interval_predictions", [])
        evaluation = interval_evaluation(values)
        return emit(evaluation, "valid" if evaluation["n"] else "insufficient", evidence_status="research_only",
                    valid_n=evaluation["n"], total_n=len(values), count_domain="predicted_intervals")
    refs = reference_rows(rows, context)
    target = context.get("prediction_target")
    if not target:
        return emit(None, "insufficient", reasons=["fixed_task_prediction_target_required"])
    same = [r for r in refs if comparable(r, target, protocol=True)[0] and outcome_series(r)["eligible"]
            and outcome_series(r)["outcome_series_id"] == outcome_series(target)["outcome_series_id"]]
    if not same:
        return emit(None, "insufficient", reasons=["strictly_comparable_available_history_missing"])
    previous = max(same, key=lambda r: instant(r["_event_end"]))
    b0 = {"predicted_reps": previous["reps"], "previous_rir": previous.get("rir"),
          "reference_id": previous.get("id"), "model_version": "B0_last_comparable_v1"}
    if metric_id == "PRED-B0":
        return emit(b0, evidence_status="descriptive", reasons=["historical_reference_not_guaranteed_completion"])
    model = fit_b1(context.get("b1_training_pairs", []))
    current_state = context.get("state_at_cutoff")
    previous_state = context.get("previous_state")
    if model["beta"] is None or current_state is None or previous_state is None:
        return emit({"B0": b0, "B1": None, "selected_model": "B0"}, "partial", evidence_status="research_only",
                    reasons=[model.get("reason") or "state_missing_fallback_B0"])
    for observation in (current_state, previous_state):
        if instant(observation["event_end"]) > instant(window.cutoff_time) or instant(observation["available_at"]) > instant(window.cutoff_time):
            return emit({"B0": b0, "B1": None, "selected_model": "B0"}, "partial", reasons=["feature_unavailable_at_prediction_cutoff"])
    estimate = b0["predicted_reps"] + model["beta"] * (current_state["value"] - previous_state["value"])
    calibration = context.get("calibration")
    scope_check = calibration_scope_check(calibration, metric_id=metric_id, scope=task_calibration_scope(target, context), model_version=model["model_version"])
    valid = scope_check["matches"]
    return emit({"B0": b0, "B1": {"predicted_reps": estimate, "model": model}, "selected_model": "B1" if valid else "B0"},
                evidence_status="predictive_validated_for_scope" if valid else "research_only", calibration=calibration,
                calibration_scope_check=scope_check,
                reasons=["prediction_association_not_causal_sleep_or_load_adjustment"] + ([] if valid else ["target_validation_missing_fallback_B0"]))
