"""Transparent research baselines; model-conditional intervals are not validation."""

from __future__ import annotations

import math
from statistics import median, stdev
from typing import Optional

from .contracts import finite, instant


def linear_trend(observations: list[dict], *, alpha: float = 0.05,
                 reference_times: Optional[list[str]] = None,
                 measurement_sd: Optional[float] = None) -> dict:
    out = {"slope_per_day": None, "change": None, "interval": None,
           "residual_sd": None, "measurement_sd": measurement_sd,
           "reason_codes": [], "n": len(observations), "span_days": None,
           "model_version": "ols_true_time_student_t_v1",
           "assumptions": ["independent homoscedastic Gaussian errors",
                           "one predesignated observation per session",
                           "linear mean over actual observed time support"]}
    if len(observations) < 2:
        out["reason_codes"] = ["insufficient_observations"]
        return out
    try:
        import numpy as np
        from scipy.stats import t
    except ImportError:
        out["reason_codes"] = ["research_dependencies_missing"]
        return out
    sessions = [row.get("session_id") for row in observations]
    if None in sessions or len(set(sessions)) != len(sessions):
        out["reason_codes"] = ["one_observation_per_identified_session_required"]
        return out
    times = [instant(row.get("_event_end", row.get("event_end"))) for row in observations]
    values = [finite(row.get("value", row.get("reps"))) for row in observations]
    if None in values:
        out["reason_codes"] = ["outcome_missing"]
        return out
    origin = min(times)
    x = np.array([(value - origin).total_seconds() / 86400 for value in times])
    y = np.array(values)
    design = np.column_stack((np.ones(len(x)), x))
    beta, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    if rank < 2:
        out["reason_codes"] = ["rank_deficient_time"]
        return out
    if reference_times:
        first, last = [instant(v) for v in reference_times]
        if not origin <= first < last <= max(times):
            out["reason_codes"] = ["reference_times_outside_observed_support"]
            return out
        horizon = (last - first).total_seconds() / 86400
    else:
        horizon = float(max(x) - min(x))
    out.update(slope_per_day=float(beta[1]), change=float(beta[1] * horizon),
               span_days=float(max(x) - min(x)), horizon_days=horizon,
               intercept=float(beta[0]), reference_times=reference_times)
    if len(x) < 3:
        out["reason_codes"] = ["interval_degrees_of_freedom_insufficient"]
        return out
    residual_sd = math.sqrt(float(np.sum((y - design @ beta) ** 2)) / (len(x) - 2))
    out["residual_sd"] = residual_sd
    # A zero residual is numerical fit, never measured zero individual error.
    if residual_sd < 1e-10 and (measurement_sd is None or measurement_sd <= 0):
        out["reason_codes"] = ["measurement_error_unknown_zero_residual"]
        return out
    if measurement_sd is not None and measurement_sd < 0:
        raise ValueError("measurement_sd_must_be_nonnegative")
    if not 0 < alpha < 1:
        raise ValueError("alpha_must_be_between_zero_and_one")
    sigma = max(residual_sd, measurement_sd or 0)
    se = sigma / math.sqrt(float(np.sum((x - x.mean()) ** 2)))
    half = float(t.ppf(1 - alpha / 2, len(x) - 2)) * se * horizon
    out["interval"] = {"kind": "confidence_interval", "lower": out["change"] - half,
                       "upper": out["change"] + half, "level": 1 - alpha,
                       "assumptions": out["assumptions"]}
    out["reason_codes"] = ["model_conditional_interval_not_target_validated"]
    return out


def typical_error(pairs: list[dict], design: dict) -> dict:
    from .semantics import outcome_series
    assumptions = ["independent repeat pairs", "equal within-person variance",
                   "no systematic learning or fatigue between repeats"]
    if not design.get("independent_repeats") or not design.get("equal_variance") \
            or not design.get("no_systematic_change"):
        return {"value": None, "reason_codes": ["repeat_measurement_design_unconfirmed"],
                "assumptions": assumptions}
    if not design.get("same_task_protocol_confirmed") or any(not design.get(k) for k in ("task_id", "protocol_id", "unit")):
        return {"value": None, "reason_codes": ["repeat_task_protocol_and_unit_required"], "assumptions": assumptions}
    for pair in pairs:
        first, second = pair.get("first_record"), pair.get("second_record")
        if first is not None or second is not None:
            if not first or not second:
                return {"value": None, "reason_codes": ["repeat_pair_provenance_incomplete"], "assumptions": assumptions}
            a, b = outcome_series(first), outcome_series(second)
            if not a["eligible"] or not b["eligible"] or a["outcome_series_id"] != b["outcome_series_id"]:
                return {"value": None, "reason_codes": ["repeat_pair_task_or_protocol_changed"], "assumptions": assumptions}
    differences = [finite(p.get("second")) - finite(p.get("first")) for p in pairs
                   if finite(p.get("first")) is not None and finite(p.get("second")) is not None]
    if len(differences) < 2:
        return {"value": None, "reason_codes": ["insufficient_repeat_pairs"], "assumptions": assumptions}
    te = stdev(differences) / math.sqrt(2)
    return {"value": {"TE": te, "MDC95_two_scores": 1.96 * math.sqrt(2) * te,
                      "mean_difference": sum(differences) / len(differences),
                      "pairs": len(differences), "unit": design["unit"], "task_id": design["task_id"],
                      "protocol_id": design["protocol_id"]},
            "reason_codes": ["zero_observed_repeat_variability_not_proof_of_zero_measurement_error"] if te == 0 else [], "assumptions": assumptions}


def theil_sen(points: list[tuple[float, float]]) -> Optional[float]:
    slopes = [(b[1] - a[1]) / (b[0] - a[0]) for i, a in enumerate(points)
              for b in points[i + 1:] if b[0] != a[0]]
    return median(slopes) if slopes else None


def classify_interval(lower: float, upper: float, delta_lower: float, delta_upper: float) -> str:
    """Mathematical classification only; caller must pass calibration gates first."""
    if lower > upper or min(delta_lower, delta_upper) < 0:
        raise ValueError("invalid_equivalence_bounds")
    if lower > delta_upper:
        return "material_progress"
    if upper < -delta_lower:
        return "decline"
    if lower >= -delta_lower and upper <= delta_upper:
        return "no_material_change_candidate"
    return "uncertain"
