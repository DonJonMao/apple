"""Actual-time body mass and identifiable, explicitly conditional energy models."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from healthzip.normalize import quantity_value

from .contracts import Window, finite, instant, result
from .state import daily_values, elapsed_dates, local_date_domain, stream_key, union
from .statistics import theil_sen


def hall_chow(times: list[float], weights: list[float], *, baseline: dict, parameters: dict,
              covariance=None, baseline_variance=None, baseline_covariance=None,
              parameter_covariance=None, end_estimator: str = "observed_last") -> dict:
    """Linear observation operator with explicit joint baseline covariance.

    rho is a dynamical coefficient, never a tissue storage density. No default
    rho, epsilon, equilibrium mass, intake baseline, or error band is inferred.
    """
    out = {"delta_intake_kcal_day": None, "variance": None, "reason_codes": [],
           "identity": "change_relative_to_initial_equilibrium_intake_not_current_energy_gap",
           "model_version": "hall_chow_linear_operator_v1"}
    if not baseline.get("equilibrium_confirmed") or not baseline.get("baseline_id") or finite(baseline.get("W0")) is None:
        out["reason_codes"] = ["independently_identified_equilibrium_baseline_required"]
        return out
    if not parameters.get("parameter_set_id") or not parameters.get("provenance"):
        out["reason_codes"] = ["registered_model_parameters_required"]
        return out
    rho, epsilon = finite(parameters.get("rho")), finite(parameters.get("epsilon"))
    if rho is None or epsilon is None or rho <= 0 or epsilon < 0:
        out["reason_codes"] = ["invalid_model_parameters"]
        return out
    if (rho == 9100 or epsilon == 22) and parameters.get("model") != "hall_chow_2011_replication":
        out["reason_codes"] = ["publication_constants_only_in_named_replication_configuration"]
        return out
    if len(times) != len(weights) or len(times) < 2 or len(set(times)) < 2:
        out["reason_codes"] = ["distinct_observation_times_required"]
        return out
    try:
        import numpy as np
    except ImportError:
        out["reason_codes"] = ["research_dependencies_missing"]
        return out
    x, w = np.asarray(times, dtype=float), np.asarray(weights, dtype=float)
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(w)):
        out["reason_codes"] = ["nonfinite_observations"]
        return out
    q = (x - x.mean()) / np.sum((x - x.mean()) ** 2)
    if end_estimator == "observed_last":
        ell = np.zeros(len(x))
        ell[int(np.argmax(x))] = 1
    elif end_estimator == "fitted_last":
        ell = np.ones(len(x)) / len(x) + (max(x) - x.mean()) * q
    else:
        raise ValueError("end_estimator_unknown")
    a, endpoint = float(q @ w), float(ell @ w)
    h = rho * q + epsilon * ell
    value = float(h @ w - epsilon * baseline["W0"])
    out.update(delta_intake_kcal_day=value, slope_kg_day=a, endpoint_weight_kg=endpoint,
               W0=baseline["W0"], baseline_id=baseline["baseline_id"],
               parameter_set_id=parameters["parameter_set_id"], observation_weights=h.tolist(),
               end_estimator=end_estimator, evidence_status="research_only" if parameters.get("model") == "hall_chow_2011_replication" else "model_conditional")
    if covariance is None or baseline_variance is None:
        out["reason_codes"] = ["measurement_and_baseline_error_not_identified_interval_unavailable"]
        return out
    sigma = np.asarray(covariance, dtype=float)
    baseline_cov = np.asarray(baseline_covariance if baseline_covariance is not None else np.zeros(len(x)), dtype=float)
    if sigma.shape != (len(x), len(x)) or baseline_cov.shape != (len(x),):
        raise ValueError("covariance_shape_mismatch")
    if baseline.get("same_sample_baseline") and baseline_covariance is None:
        out["reason_codes"] = ["shared_baseline_covariance_required"]
        return out
    joint = np.block([[sigma, baseline_cov[:, None]], [baseline_cov[None, :], np.array([[baseline_variance]])]])
    if not np.allclose(joint, joint.T) or np.linalg.eigvalsh(joint).min() < -1e-9:
        raise ValueError("joint_covariance_must_be_positive_semidefinite")
    gradient = np.concatenate((h, [-epsilon]))
    variance = float(gradient @ joint @ gradient)
    if parameter_covariance is not None:
        covariance_p = np.asarray(parameter_covariance, dtype=float)
        if covariance_p.shape != (2, 2) or not np.allclose(covariance_p, covariance_p.T) or np.linalg.eigvalsh(covariance_p).min() < -1e-9:
            raise ValueError("parameter_covariance_invalid")
        parameter_gradient = np.array([a, endpoint - baseline["W0"]])
        variance += float(parameter_gradient @ covariance_p @ parameter_gradient)
        out["parameter_error_method"] = "first_order_delta_method_independent_parameter_block"
    out["variance"] = max(0.0, variance)
    out["reason_codes"] = ["conditional_error_model_not_total_physiological_uncertainty"]
    return out


def atomic_energy(rows: list[dict], canonical: str, window: Window) -> dict:
    chosen = [r for r in rows if r.get("canonical_type", r.get("metric_type")) == canonical]
    streams = defaultdict(list)
    for row in chosen:
        streams[stream_key(row)].append(row)
    values, conflicts, unknown = [], [], []
    for key, samples in streams.items():
        intervals = []
        for row in samples:
            numeric = quantity_value(row)
            value = numeric["value"]
            try:
                start = instant(row.get("event_start") or row.get("start_utc"))
                end = instant(row["_event_end"])
            except ValueError:
                unknown.append(row.get("_source_id"))
                continue
            if value is None or value < 0 or numeric["unit"] != "kcal":
                unknown.append(row.get("_source_id"))
                continue
            if start < instant(window.start) or end > min(instant(window.end), instant(window.cutoff_time)):
                unknown.append(row.get("_source_id"))
                continue  # no unjustified rate assumption / prorating.
            intervals.append((start, end, value, {**row, "_numeric_provenance": numeric}))
        intervals.sort(key=lambda p: p[0])
        stream_conflicted = False
        for i, first in enumerate(intervals):
            for second in intervals[i + 1:]:
                if second[0] >= first[1]:
                    break
                if min(first[1], second[1]) > max(first[0], second[0]):
                    conflicts.append([first[3].get("_source_id"), second[3].get("_source_id")])
                    stream_conflicted = True
        values.append({"stream": list(key), "known_kcal": None if stream_conflicted or not intervals else sum(v for _, _, v, _ in intervals),
                       "sample_count": len(intervals), "conflicted": stream_conflicted,
                       "source_ids": [r.get("_source_id") for _, _, _, r in intervals],
                       "numeric_provenance": [r["_numeric_provenance"] for _, _, _, r in intervals]})
    return {"streams": values, "conflicts": conflicts, "unknown_or_boundary_ids": unknown}


def device_energy_days(rows: list[dict], window: Window) -> list[dict]:
    """Pair components only on the same local date, source and observed support."""
    zone = ZoneInfo(window.timezone)
    eligible = [r for r in rows if r.get("canonical_type") in {"basal_energy_kcal", "active_energy_kcal"}]
    dates = set()
    for row in eligible:
        raw = row.get("event_start") or row.get("start_utc")
        if raw:
            first = max(instant(raw), instant(window.start))
            last = min(instant(row["_event_end"]), instant(window.end), instant(window.cutoff_time))
            day = first.astimezone(zone).date()
            while datetime.combine(day, time.min, zone) < last:
                dates.add(day)
                day += timedelta(days=1)
    output = []
    for day in sorted(dates):
        start = datetime.combine(day, time.min, zone)
        end = datetime.combine(day + timedelta(days=1), time.min, zone)
        a, b = max(instant(start), instant(window.start)), min(instant(end), instant(window.end), instant(window.cutoff_time))
        if a >= b:
            continue
        daily_window = Window(a.isoformat(), b.isoformat(), window.cutoff_time, window.timezone)
        daily = [r for r in eligible if instant(r["_event_end"]) > a
                 and instant(r.get("event_start") or r["start_utc"]) < b]
        for stream in sorted({stream_key(r) for r in daily}, key=str):
            inputs = [r for r in daily if stream_key(r) == stream]
            amounts, supports, component_complete, conflicts, rejected = {}, {}, {}, [], []
            for label, canonical in (("basal", "basal_energy_kcal"), ("active", "active_energy_kcal")):
                selected = [r for r in inputs if r["canonical_type"] == canonical]
                item = atomic_energy(selected, canonical, daily_window)
                streams = item["streams"]
                amounts[label] = streams[0]["known_kcal"] if len(streams) == 1 else None
                ids = {identity for value in streams for identity in value["source_ids"]}
                observed = [r for r in selected if r.get("_source_id") in ids]
                supports[label] = union([(instant(r.get("event_start") or r["start_utc"]), instant(r["_event_end"])) for r in observed])
                component_complete[label] = bool(observed) and (all(r.get("platform_complete_day") is True for r in observed)
                    or supports[label] == [(instant(start), instant(end))])
                conflicts.extend(item["conflicts"])
                rejected.extend(item["unknown_or_boundary_ids"])
            matched = (all(amounts[k] is not None for k in ("basal", "active")) and not conflicts and not rejected
                       and (supports["basal"] == supports["active"] or all(component_complete.values())))
            complete = matched and all(component_complete.values()) and a == instant(start) and b == instant(end)
            output.append({"date": day.isoformat(), "stream": list(stream), "event_start": a.isoformat(), "event_end": b.isoformat(),
                           "available_at": max((instant(r.get("available_at") or r["_event_end"]).isoformat() for r in inputs)),
                           "basal_kcal": amounts["basal"], "active_kcal": amounts["active"],
                           "basal_valid": amounts["basal"] is not None, "active_valid": amounts["active"] is not None,
                           "total_valid": matched, "complete": complete,
                           "device_total_kcal": sum(amounts.values()) if matched else None,
                           "source_record_ids": [r.get("_source_id") for r in inputs],
                           "source_conflicted": bool(conflicts), "unknown_or_boundary_ids": rejected,
                           "component_support": {k: [{"start": x.isoformat(), "end": y.isoformat()} for x, y in v] for k, v in supports.items()}})
    return output


def energy_metric(metric_id: str, rows: list[dict], window: Window, context: dict) -> dict:
    def emit(value=None, status="valid", **extra):
        return result(metric_id, window, value, data_status=status, records=rows, **extra)

    if metric_id.startswith("BODY-MASS-"):
        streams = daily_values(rows, "body_mass_kg", window.timezone)
        if not streams:
            return emit(None, "insufficient", reasons=["comparable_body_mass_observations_missing"])
        if metric_id == "BODY-MASS-DAILY":
            return emit(streams, evidence_status="observed", reasons=["scales_and_protocols_not_pooled"])
        values = []
        for key, samples in streams.items():
            points = [(instant(s["date"] + "T00:00:00+00:00").timestamp() / 86400, s["value"]) for s in samples]
            slope = theil_sen(points)
            declared_reference = context.get("body_mass_reference") or {}
            reference = (float(declared_reference["value"]) if declared_reference.get("definition")
                         and finite(declared_reference.get("value")) is not None else median(p[1] for p in points))
            values.append({"stream": key, "kg_per_week": slope * 7 if slope is not None else None,
                           "percent_per_week": slope * 7 / reference * 100 if slope is not None and reference > 0 else None,
                           "reference_mass_kg": reference, "reference_definition": declared_reference.get("definition", "within_window_equal_day_median"),
                           "n_days": len(points), "span_days": max(p[0] for p in points) - min(p[0] for p in points),
                           "source_ids": [i for s in samples for i in s["source_ids"]]})
        return emit(values, "valid" if all(v["kg_per_week"] is not None for v in values) else "partial",
                    evidence_status="descriptive", reasons=["actual_calendar_time", "mass_not_tissue_composition"])
    if metric_id in {"ENERGY-BASAL", "ENERGY-ACTIVE"}:
        canonical = "basal_energy_kcal" if metric_id == "ENERGY-BASAL" else "active_energy_kcal"
        value = atomic_energy(rows, canonical, window)
        status = "conflicted" if value["conflicts"] else "partial" if value["unknown_or_boundary_ids"] else "valid" if value["streams"] else "insufficient"
        return emit(value if value["streams"] else None, status, evidence_status="observed",
                    unit="kcal", aggregation="observed_window_cumulative", daily_buckets=device_energy_days(rows, window),
                    reasons=["device_report_not_true_TEE", "cross_boundary_samples_not_prorated"])
    if metric_id == "ENERGY-DEVICE-TOTAL":
        days = device_energy_days(rows, window)
        grouped = defaultdict(list)
        for day in days:
            if day["total_valid"]:
                grouped[tuple(day["stream"])].append(day)
        values = []
        for stream, matched in grouped.items():
            complete = [d for d in matched if d["complete"]]
            values.append({"stream": list(stream), "basal_kcal": sum(d["basal_kcal"] for d in matched),
                           "active_kcal": sum(d["active_kcal"] for d in matched),
                           "device_total_kcal": sum(d["device_total_kcal"] for d in matched),
                           "paired_dates": [d["date"] for d in matched], "complete_days": len(complete),
                           "valid_day_mean_kcal_day": sum(d["device_total_kcal"] for d in complete) / len(complete) if complete else None})
        status = "conflicted" if any(d["source_conflicted"] for d in days) else "insufficient" if not values else "partial" if any(not d["complete"] for d in days) else "valid"
        return emit(values or None, status, evidence_status="observed", unit="kcal", aggregation="paired_observed_window_cumulative",
                    daily_buckets=days, reasons=["same_date_stream_and_interval_components_only", "workout_not_added_again", "no_TEF_multiplier", "device_report_not_true_TEE"])
    if metric_id == "ENERGY-RECORD-COVERAGE":
        days = context.get("energy_days", [])
        domain = local_date_domain(instant(window.start), min(instant(window.end), instant(window.cutoff_time)), window.timezone)
        days = [d for d in days if d.get("date") in domain]
        denominator = elapsed_dates(window)
        b = {d["date"] for d in days if d.get("basal_valid")}
        a = {d["date"] for d in days if d.get("active_valid")}
        totals = {d["date"] for d in days if d.get("basal_valid") and d.get("active_valid") and d.get("total_valid", True)}
        coverage = [{"kind": label, "numerator": len(values), "denominator": denominator,
                     "definition": "recorded valid dates / elapsed target dates, not wear time"}
                    for label, values in (("basal", b), ("active", a), ("total", totals))]
        return emit(coverage, "valid" if denominator else "insufficient", coverage=coverage,
                    valid_n=len(totals), total_n=denominator, count_domain="dates")
    if metric_id == "ENERGY-IDENTIFIABILITY":
        independent = context.get("independent_constraints", {})
        documented = {k: v for k, v in independent.items() if isinstance(v, dict)
                      and all(v.get(field) for field in ("provenance", "version", "scope"))}
        delta = energy_metric("ENERGY-DELTA-INTAKE", rows, window, context)
        absolute = energy_metric("ENERGY-ABSOLUTE-INTAKE", rows, window, context)
        absolute_computable = bool(absolute["value"] and "absolute_intake_kcal_day" in absolute["value"])
        identified = bool(documented.get("intake_baseline") and absolute_computable)
        return emit({"identified": identified, "invariant_family": "(I+c, E+c, b-c) leaves D=E+b and Q=I-E unchanged",
                     "documented_constraint_ids": sorted(documented), "delta_computable": delta["value"] is not None,
                     "absolute_computable": absolute_computable, "model_reason_codes": sorted(set(delta["reason_codes"] + absolute["reason_codes"])),
                     "required_independent_data": [] if identified else ["traceable independent equilibrium intake baseline", "applicable intake-change model and its prerequisites"]},
                    "valid" if identified else "not_identifiable", evidence_status="definition_based")
    if metric_id == "ENERGY-NET-STORAGE":
        model = context.get("composition_model")
        if not model or not model.get("model_version") or not model.get("provenance") or finite(model.get("elapsed_days")) is None or model["elapsed_days"] <= 0:
            return emit(None, "not_identifiable", reasons=["body_mass_does_not_identify_storage", "composition_model_required"])
        terms = model.get("components", [])
        if not terms or any(finite(t.get("density_kcal_kg")) is None or finite(t.get("delta_kg")) is None for t in terms):
            return emit(None, "not_identifiable", reasons=["composition_or_storage_parameters_missing"])
        if any(t.get("identity") in {"total_weight", "effective_rho", "lean_mass_as_protein"} for t in terms):
            return emit(None, "incompatible", reasons=["invalid_storage_identity"])
        q = sum(t["density_kcal_kg"] * t["delta_kg"] for t in terms) / model["elapsed_days"]
        variance = None
        if all(t.get("delta_variance") is not None and t.get("density_variance") is not None for t in terms) and model.get("independent_components"):
            variance = sum(t["density_kcal_kg"] ** 2 * t["delta_variance"] + t["delta_kg"] ** 2 * t["density_variance"]
                           + t["delta_variance"] * t["density_variance"] for t in terms) / model["elapsed_days"] ** 2
        return emit({"net_storage_kcal_day": q, "variance": variance, "model_version": model["model_version"],
                     "components": terms}, "valid", evidence_status="research_only",
                    reasons=[] if variance is not None else ["joint_composition_parameter_error_not_available"])
    if metric_id == "ENERGY-DELTA-INTAKE":
        series = context.get("mass_series", [])
        if not series:
            return emit(None, "insufficient", reasons=["mass_series_required"])
        times = [(instant(p["event_end"]) - instant(series[0]["event_end"])).total_seconds() / 86400 for p in series]
        value = hall_chow(times, [p["value"] for p in series], baseline=context.get("equilibrium_baseline", {}),
                          parameters=context.get("energy_parameters", {}), covariance=context.get("mass_covariance"),
                          baseline_variance=context.get("baseline_variance"), baseline_covariance=context.get("baseline_covariance"),
                          parameter_covariance=context.get("parameter_covariance"), end_estimator=context.get("end_estimator", "observed_last"))
        return emit(value if value["delta_intake_kcal_day"] is not None else None,
                    "valid" if value["delta_intake_kcal_day"] is not None else "not_identifiable",
                    evidence_status=value.get("evidence_status", "research_only"), reasons=value["reason_codes"],
                    parameter_set_id=context.get("energy_parameters", {}).get("parameter_set_id"))
    if metric_id == "ENERGY-ABSOLUTE-INTAKE":
        baseline = context.get("intake_baseline", {})
        delta = context.get("delta_intake")
        if baseline.get("independent") and baseline.get("baseline_id") and finite(baseline.get("I0")) is not None and delta and finite(delta.get("value")) is not None:
            variance = None
            if baseline.get("variance") is not None and delta.get("variance") is not None and context.get("intake_delta_covariance") is not None:
                variance = baseline["variance"] + delta["variance"] + 2 * context["intake_delta_covariance"]
            return emit({"absolute_intake_kcal_day": baseline["I0"] + delta["value"], "variance": variance,
                         "baseline_id": baseline["baseline_id"]}, evidence_status="model_conditional",
                        reasons=["conditional_estimate_not_measured_intake"])
        scenario = context.get("energy_scenario", {})
        required = ("device_total", "bias_lower", "bias_upper", "storage_lower", "storage_upper")
        if scenario.get("provenance") and all(finite(scenario.get(k)) is not None for k in required):
            if scenario["bias_lower"] > scenario["bias_upper"] or scenario["storage_lower"] > scenario["storage_upper"]:
                raise ValueError("energy_scenario_bounds_reversed")
            lo = scenario["device_total"] - scenario["bias_upper"] + scenario["storage_lower"]
            hi = scenario["device_total"] - scenario["bias_lower"] + scenario["storage_upper"]
            if lo > hi:
                raise ValueError("energy_scenario_bounds_reversed")
            uncertainty = {"kind": "scenario_range", "lower": lo, "upper": hi, "level": None,
                           "assumptions": ["device value treated fixed", "declared bias and storage ranges", "not calibrated coverage"]}
            return emit({"scenario_lower": lo, "scenario_upper": hi, "provenance": scenario["provenance"]},
                        uncertainty=uncertainty, evidence_status="model_conditional")
        return emit(None, "not_identifiable", reasons=["independent_intake_baseline_or_credible_bias_storage_scenario_required"])
    raise ValueError("unknown_energy_metric")
