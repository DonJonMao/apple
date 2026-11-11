"""STR-01…30: audit-preserving strength observations and gated research inference."""

from __future__ import annotations

from collections import defaultdict

from .contracts import Window, finite, instant, result
from .formulas import e1rm
from .registry import calibration_matches, verified_look
from .semantics import (
    analysis_task,
    comparable,
    condition_key,
    load_basis,
    load_change,
    load_components,
)
from .statistics import classify_interval, linear_trend, typical_error


def _completed(row: dict) -> bool:
    if row.get("status") != "completed" or row.get("role") != "work":
        return False
    mode = row.get("measurement_mode")
    field = {"repetitions": "reps", "duration": "duration_s", "distance": "distance_m"}.get(mode)
    return bool(field and finite(row.get(field)) is not None and finite(row[field]) > 0)


def _parents(rows: list[dict]) -> list[dict]:
    out = {}
    for row in rows:
        key = (row.get("session_id"), row.get("parent_set_id") or row.get("set_id") or row.get("id"))
        if key[1] is not None:
            out.setdefault(key, row)
    return list(out.values())


def reference_rows(rows: list[dict], context: dict) -> list[dict]:
    selected = []
    for row in rows:
        nominated = row.get("is_reference") is True or row.get("set_id", row.get("id")) in context.get("reference_set_ids", [])
        declared = row.get("reference_declared_at") or context.get("reference_protocol_declared_at")
        observation_start = row.get("event_start") or row.get("started_at") or row.get("_event_end")
        if _completed(row) and nominated and declared and observation_start:
            if instant(declared) <= instant(observation_start):
                selected.append(row)
    groups = defaultdict(list)
    for row in selected:
        groups[(analysis_task(row)["task_id"], row.get("session_id"))].append(row)
    # Multiple contradictory reference assignments do not silently choose best.
    return [items[0] for (_, session), items in groups.items() if session is not None and len(items) == 1]


def opportunity(row: dict) -> str:
    stop = row.get("stop_reason")
    if stop == "target_rir_stop" and finite(row.get("rir")) is not None and row.get("effort_protocol"):
        return "submaximal_reference"
    if stop in {"volitional_failure", "technical_limit", "pain"}:
        return stop
    return "capacity_unobserved"


def strength_metric(metric_id: str, rows: list[dict], window: Window, context: dict) -> dict:
    code = int(metric_id.split("-")[1])
    total = len(rows)
    work = _parents([row for row in rows if _completed(row)])
    refs = reference_rows(rows, context)
    kw = {"records": rows, "total_n": total}

    def emit(value=None, status="valid", **extra):
        return result(metric_id, window, value, data_status=status, **{**kw, **extra})

    if code == 1:
        if not rows:
            return emit(None, "insufficient", reasons=["no_training_log_not_zero_training"], valid_n=0)
        unknown = sum(r.get("status") == "completed" and r.get("role") == "work" and not _completed(r) for r in rows)
        return emit({"completed_work_parent_sets": len(work), "segments": sum(_completed(r) for r in rows),
                     "warmup_sets": len(_parents([r for r in rows if r.get("role") == "warmup"])),
                     "failed_attempts": sum(r.get("status") == "failed" or r.get("reps") == 0 for r in rows),
                     "unknown_work_sets": unknown}, "partial" if unknown else "valid", valid_n=len(work))
    if code == 2:
        values = [{"id": r.get("id"), "measurement_mode": r.get("measurement_mode"),
                   "reps": r.get("reps"), "duration_s": r.get("duration_s"),
                   "distance_m": r.get("distance_m"), "side": r.get("side"), "status": r.get("status")} for r in rows]
        return emit(values, "valid" if values else "insufficient", valid_n=sum(_completed(r) for r in rows))
    if code == 3:
        values = [{"id": r.get("id"), **load_components(r)} for r in rows]
        valid = sum(not v["reason_codes"] for v in values)
        return emit(values or None, "valid" if valid == len(values) and values else "partial" if values else "insufficient", valid_n=valid)
    if code == 4:
        groups, missing = {}, []
        for row in rows:
            if not _completed(row):
                if row.get("role") == "work" and row.get("status") == "completed":
                    missing.append(row.get("id"))
                continue
            load = load_components(row)
            if row.get("measurement_mode") != "repetitions" or load_basis(row) in {"assistance_setting", "bodyweight_no_external", "added_load_kg", "unknown", "machine_setting"}:
                missing.append(row.get("id"))
                continue
            basis = "total" if load["total_load_kg"] is not None else "plates_only"
            weight = load["total_load_kg"] if basis == "total" else load["plate_total_kg"]
            if weight is None:
                missing.append(row.get("id"))
                continue
            key = str((condition_key(row), row.get("exercise_id"), row.get("equipment_instance_id"), load_basis(row), basis))
            item = groups.setdefault(key, {"sum_kg_reps": 0.0, "basis": basis, "set_ids": [],
                                           "exercise_id": row.get("exercise_id")})
            item["sum_kg_reps"] += weight * row["reps"]
            item["set_ids"].append(row.get("id"))
        return emit({"groups": list(groups.values()), "excluded_ids": missing}, "partial" if missing else "valid",
                    valid_n=sum(len(v["set_ids"]) for v in groups.values()), reasons=["bookkeeping_not_mechanical_work_or_stimulus"])
    if code in {5, 6}:
        role = "direct" if code == 5 else "indirect"
        mappings = context.get("muscle_mappings", {})
        grouped, unknown = defaultdict(set), []
        for row in work:
            mapping = mappings.get(row.get("exercise_id"), {})
            if mapping.get("review_status") != "approved" or not mapping.get("version"):
                unknown.append(row.get("id"))
                continue
            for muscle in mapping.get(role, []):
                grouped[(muscle, row.get("side"), mapping["version"])].add(row.get("parent_set_id") or row.get("id"))
        if not grouped:
            return emit(None, "insufficient", reasons=["muscle_mapping_unreviewed"], valid_n=0)
        return emit({"groups": [{"muscle": k[0], "side": k[1], "mapping_version": k[2], "sets": len(v)} for k, v in grouped.items()],
                     "unknown_set_ids": unknown}, "partial" if unknown else "valid", valid_n=len(work) - len(unknown))
    if code in {7, 8}:
        known = [r for r in refs if condition_key(r) is not None]
        times = sorted({(r["session_id"], r["_event_end"]) for r in known}, key=lambda p: p[1])
        dates = [instant(t) for _, t in times]
        elapsed = (min(instant(window.end), instant(window.cutoff_time)) - instant(window.start)).total_seconds() / 86400
        value = {"sessions": len(times), "observed_dates": len({d.date() for d in dates}),
                 "span_days": (dates[-1] - dates[0]).total_seconds() / 86400 if dates else None,
                 "recorded_frequency_per_week": len(times) / elapsed * 7 if elapsed > 0 else None,
                 "interval_days": [(b - a).total_seconds() / 86400 for a, b in zip(dates, dates[1:])]}
        return emit(value, "valid" if known else "insufficient", valid_n=len(known),
                    reasons=["recorded_frequency_not_actual_training_or_recovery"])
    if code == 9:
        plan = context.get("plan_snapshot")
        if not plan:
            return emit(None, "not_applicable", reasons=["unplanned_session"])
        planned = plan.get("sets", [])
        planned_ids = {str(s["id"]) for s in planned}
        actual = {str(r.get("planned_set_id")): r for r in rows if str(r.get("planned_set_id")) in planned_ids}
        done = sum(_completed(r) for r in actual.values())
        skipped = sum(r.get("status") == "skipped" for r in actual.values())
        unknown = len(planned_ids) - done - skipped
        return emit({"completed": done, "skipped": skipped, "unknown": unknown, "planned": len(planned_ids),
                     "completed_fraction_of_plan": done / len(planned_ids) if planned_ids else None,
                     "extra_sets": sum(str(r.get("planned_set_id")) not in planned_ids and _completed(r) for r in rows)},
                    "partial" if unknown else "valid", valid_n=done + skipped, total_n=len(planned_ids), count_domain="planned_sets")
    if code == 10:
        values = []
        for row in rows:
            reserve = finite(row.get("rir"))
            conversion = False
            if reserve is None and row.get("scale_type") == "rir_based_rpe_6_10" and finite(row.get("rpe")) is not None and 6 <= row["rpe"] <= 10:
                reserve, conversion = 10 - row["rpe"], True
            values.append({"id": row.get("id"), "rir": reserve, "rir_interval": row.get("rir_interval"),
                           "original_rpe": row.get("rpe"), "scale_type": row.get("scale_type"),
                           "converted": conversion, "stop_reason": row.get("stop_reason")})
        return emit(values or None, "valid" if values else "insufficient", valid_n=sum(v["rir"] is not None for v in values))
    if code == 11:
        fields = ("id", "session_id", "load_value", "load_unit", "load_basis", "reps", "rir",
                  "rir_interval", "quality", "stop_reason", "set_position", "reference_policy_id",
                  "reference_declared_at", "measurement_mode", "duration_s", "distance_m")
        return emit([{**{key: r.get(key) for key in fields}, "condition_key": condition_key(r)} for r in refs] or None,
                    "valid" if refs and all(condition_key(r) for r in refs) else "insufficient",
                    valid_n=len(refs), reasons=[] if refs else ["predesignated_reference_missing"])
    if code in {12, 13, 14}:
        pair = context.get("comparison_pair") or refs[-2:]
        if len(pair) != 2:
            return emit(None, "insufficient", reasons=["two_reference_observations_required"])
        old, new = pair
        ok, reasons = comparable(old, new)
        if not ok:
            return emit(None, "incompatible", reasons=reasons)
        a, b = load_components(old), load_components(new)
        same_load = a["entered_unit"] == b["entered_unit"] and a["entered_load"] == b["entered_load"]
        same_reps = finite(old.get("reps")) is not None and old.get("reps") == new.get("reps")
        protocol_ok, protocol_reasons = comparable(old, new, protocol=True)
        base = {"reference_id": old.get("id"), "current_id": new.get("id"),
                "rir_before": old.get("rir"), "rir_after": new.get("rir"),
                "stop_before": old.get("stop_reason"), "stop_after": new.get("stop_reason")}
        if code == 12:
            if not same_load or finite(old.get("reps")) is None or finite(new.get("reps")) is None:
                return emit(None, "incompatible", reasons=["same_load_and_observed_reps_required"])
            base["delta_reps"] = new["reps"] - old["reps"]
        elif code == 13:
            if not same_reps:
                return emit(None, "incompatible", reasons=["same_repetitions_required"])
            base.update(load_change(old, new))
        else:
            if not same_reps or not same_load:
                return emit(None, "incompatible", reasons=["same_load_and_repetitions_required"])
            if finite(old.get("rir")) is None or finite(new.get("rir")) is None:
                return emit(None, "insufficient", reasons=["exact_rir_missing"])
            base["delta_rir"] = new["rir"] - old["rir"]
            base["effort_direction"] = "easier_reported" if base["delta_rir"] > 0 else "harder_reported" if base["delta_rir"] < 0 else "unchanged_reported"
        return emit(base, "valid" if protocol_ok else "partial", evidence_status="descriptive",
                    reasons=protocol_reasons + ["raw_change_not_stable_capacity_gain"])
    if code == 15:
        groups = defaultdict(list)
        for row in rows:
            if _completed(row):
                groups[(row.get("session_id"), condition_key(row))].append(row)
        series = []
        for (session, key), group in groups.items():
            group.sort(key=lambda r: r.get("set_position", r.get("set_number", 0)))
            first = group[0]
            if key is None or not first.get("reps"):
                continue
            for row in group:
                if row.get("set_structure") not in {None, "straight"} or row.get("entered_load") != first.get("entered_load"):
                    continue
                if finite(row.get("reps")) is not None:
                    series.append({"session_id": session, "set_id": row.get("id"),
                                   "delta_reps": row["reps"] - first["reps"],
                                   "fraction_decrease": (first["reps"] - row["reps"]) / first["reps"]})
        return emit(series or None, "valid" if series else "insufficient", valid_n=len(series), evidence_status="descriptive")
    if code in {16, 17}:
        estimates = []
        for row in refs or work:
            components = load_components(row)
            estimates.append({"set_id": row.get("id"), **e1rm(components["total_load_kg"], row.get("reps"),
                              rir=row.get("rir"), formula_id=context.get("formula_id", "epley_rir_over_30" if code == 17 else "epley_n3_0.0333"),
                              domain=context.get("formula_domain"), load_basis=load_basis(row),
                              measured_maximum=row.get("measured_1rm", False))})
        valid = sum(e["value"] is not None for e in estimates)
        return emit(estimates or None, "valid" if valid and valid == len(estimates) else "partial" if valid else "not_applicable",
                    valid_n=valid, evidence_status="research_only", reasons=["not_validated_for_personal_decisions"])
    if code == 18:
        data = typical_error(context.get("repeat_pairs", []), context.get("repeat_design", {}))
        return emit(data["value"], "valid" if data["value"] is not None else "insufficient",
                    evidence_status="model_conditional", reasons=data["reason_codes"], assumptions=data["assumptions"])
    if code in {19, 20, 22}:
        if refs and (not comparable(refs[0], refs[0], protocol=True)[0] or any(not comparable(refs[0], r, protocol=True)[0]
                                                     or r.get("entered_load") != refs[0].get("entered_load")
                                                     or r.get("load_unit") != refs[0].get("load_unit") for r in refs[1:])):
            return emit(None, "incompatible", reasons=["trend_reference_conditions_incompatible"])
        allocation, allocation_reasons = verified_look(context, metric_id,
            snapshot_hash=context.get("observed_snapshot_hash"), task_id=context.get("observed_task_id"), cutoff_time=window.cutoff_time)
        trend = linear_trend(refs, alpha=allocation["alpha_look"] if allocation else 0.05,
                             reference_times=context.get("reference_times"), measurement_sd=context.get("measurement_sd"))
        if not allocation:
            trend["interval"] = None
            trend["reason_codes"] = list(dict.fromkeys(trend["reason_codes"] + allocation_reasons))
        else:
            trend["look_allocation"] = allocation
        if code == 19:
            return emit(trend, "valid" if trend["slope_per_day"] is not None else "insufficient",
                        evidence_status="descriptive", valid_n=len(refs), reasons=trend["reason_codes"])
        if code == 20:
            return emit(trend["interval"], "valid" if trend["interval"] else "insufficient",
                        uncertainty=trend["interval"], evidence_status="research_only", valid_n=len(refs),
                        reasons=trend["reason_codes"], parameter_set_id=context.get("parameter_set_id"), look_allocation=allocation)
        calibration = context.get("calibration")
        delta = context.get("practical_equivalence")
        reasons = []
        label = "uncertain"
        if not refs or any(opportunity(r) == "capacity_unobserved" for r in refs):
            label, reasons = "opportunity_unchecked", ["capacity_unobserved"]
        elif not delta or not delta.get("declared_before"):
            reasons = ["practical_equivalence_not_preregistered"]
        elif instant(delta["declared_before"]) > min(instant(r["_event_end"]) for r in refs):
            reasons = ["practical_equivalence_chosen_after_observations"]
        elif not trend["interval"]:
            reasons = trend["reason_codes"]
        elif not calibration_matches(calibration, metric_id=metric_id, scope=context.get("scope", {}), model_version=trend["model_version"]):
            reasons = ["target_calibration_missing_or_scope_mismatch"]
        elif allocation_reasons:
            reasons = allocation_reasons
        else:
            lo, hi = trend["interval"]["lower"], trend["interval"]["upper"]
            left, right = delta["lower_magnitude"], delta["upper_magnitude"]
            label = classify_interval(lo, hi, left, right)
        if not calibration_matches(calibration, metric_id=metric_id, scope=context.get("scope", {}), model_version=trend["model_version"]):
            reasons = list(dict.fromkeys(reasons + ["target_calibration_missing_or_scope_mismatch"]))
        return emit({"classification": label, "trend": trend, "practical_equivalence": delta},
                    "insufficient" if reasons else "valid", evidence_status="research_only" if reasons else "model_conditional",
                    calibration=calibration, reasons=reasons, valid_n=len(refs))
    if code == 21:
        delta = context.get("practical_equivalence")
        if delta and delta.get("unit") is not None and delta.get("unit") != context.get("outcome_unit", "repetitions"):
            raise ValueError("practical_equivalence_unit_mismatch")
        if not delta or any(finite(delta.get(k)) is None or delta[k] < 0 for k in ("lower_magnitude", "upper_magnitude")):
            return emit(None, "insufficient", reasons=["user_or_protocol_equivalence_required"])
        return emit(delta, parameter_set_id=context.get("parameter_set_id"))
    if code == 23:
        return emit([{ "set_id": r.get("id"), "observation": opportunity(r), "stop_reason": r.get("stop_reason")} for r in refs] or None,
                    "valid" if refs else "insufficient", valid_n=len(refs))
    if code == 24:
        allocation, reasons = verified_look(context, metric_id, snapshot_hash=context.get("observed_snapshot_hash"),
            task_id=context.get("observed_task_id"), cutoff_time=window.cutoff_time)
        return emit(allocation, "valid" if allocation else "insufficient",
                    reasons=["union_bound_requires_each_interval_valid", "shared_family_across_actions_metrics"] if allocation else reasons)
    if code == 25:
        history = refs[-1] if refs else None
        plan = context.get("progression_plan")
        if not history or not plan:
            return emit(None, "insufficient", reasons=["comparable_reference_and_user_plan_required"])
        if not comparable(history, history, protocol=True)[0]:
            return emit(None, "insufficient", reasons=["complete_reference_protocol_required"])
        if not history.get("load_unit"):
            return emit(None, "insufficient", reasons=["reference_load_unit_required"])
        required = ("rep_upper", "target_rir_min", "target_rir_max", "available_loads")
        if any(k not in plan for k in required):
            return emit(None, "insufficient", reasons=["plan_targets_or_equipment_steps_missing"])
        current = finite(history.get("entered_load"))
        reserve = finite(history.get("rir"))
        assistance = load_basis(history) == "assistance_setting"
        steps = sorted((float(v) for v in plan["available_loads"] if finite(v) is not None and current is not None
                        and (float(v) < current if assistance else float(v) > current)), reverse=assistance)
        qualified = current is not None and finite(history.get("reps")) is not None and history["reps"] >= plan["rep_upper"] \
            and reserve is not None and plan["target_rir_min"] <= reserve <= plan["target_rir_max"] and history.get("quality") == "acceptable"
        if not qualified or not steps:
            return emit({"candidate": "continue_user_plan_or_collect_reference", "next_load": None}, "partial",
                        reasons=["plan_upper_target_or_effort_or_quality_not_met" if not qualified else "no_available_equipment_step"])
        principles = context.get("reviewed_principles", [])
        reviewed = [p for p in principles if p.get("review_status") == "approved"
                    and p.get("version") and p.get("reviewer") and p.get("reviewed_at")
                    and p.get("capability") == "progression_candidate"
                    and p.get("evidence_spans") and p.get("rights_verified")
                    and p.get("scope_matches")]
        if not reviewed:
            return emit({"candidate": None, "next_load": None,
                         "equipment_step_feasibility": {"next_recorded_setting": steps[0], "basis": load_basis(history)},
                         "user_plan": plan}, "partial", reasons=["reviewed_applicable_progression_principle_required"])
        next_row = {**history, "entered_load": steps[0], "load_value": steps[0]}
        changes = load_change(history, next_row)
        return emit({"candidate": "double_progression_candidate", "current_load": current, "next_load": steps[0],
                     "load_unit": history.get("load_unit"), "reference_set_id": history.get("set_uuid") or history.get("set_id") or history.get("id"),
                     "target_reps": plan.get("next_target_reps"), "load_basis": load_basis(history), "changes": changes,
                     "verification_task": "Record first work set, RIR, quality and stop reason; stop or revise if unsuitable",
                     "expected_success": None, "reviewed_principle_versions": [{"id": p.get("id", p.get("theory_id")), "version": p["version"]} for p in reviewed]}, evidence_status="definition_based",
                    reasons=["user_plan_candidate_not_guaranteed_success_or_optimal_prescription"])
    if code == 26:
        allowed = context.get("allowed_trial_actions", [])
        approved = [p for p in context.get("reviewed_principles", [])
                    if p.get("review_status") == "approved" and p.get("version") and p.get("reviewer")
                    and p.get("reviewed_at") and p.get("evidence_spans") and p.get("rights_verified")
                    and p.get("scope_matches") and p.get("capability") in {"progression_candidate", "trial_candidate"}]
        if not approved:
            return emit({"candidates": ["maintain_and_collect_reference"], "quantified_change": None}, "partial",
                        reasons=["reviewed_principles_missing", "personal_intervention_effect_unvalidated"])
        actions = [v for v in allowed if v in {"repetition_progression", "heavier_lower_reps", "discuss_sets", "discuss_interval", "maintain_and_collect_reference"}]
        numerical = None
        plan = context.get("progression_plan") or {}
        reasons = ["trial_not_causal_effect_estimate"]
        if refs and "heavier_lower_reps" in actions and plan.get("next_target_reps") is not None:
            previous = refs[-1]
            target_reps = finite(plan.get("next_target_reps"))
            if not comparable(previous, previous, protocol=True)[0]:
                return emit(None, "insufficient", reasons=["complete_reference_protocol_required"])
            if not previous.get("load_unit"):
                return emit(None, "insufficient", reasons=["reference_load_unit_required"])
            if target_reps is None or target_reps <= 0 or int(target_reps) != target_reps or finite(previous.get("reps")) is None or target_reps >= previous["reps"]:
                return emit(None, "insufficient", reasons=["positive_integer_target_lower_than_reference_reps_required"])
            current = finite(previous.get("load_value"))
            assistance = load_basis(previous) == "assistance_setting"
            steps = sorted((float(v) for v in plan.get("available_loads", []) if finite(v) is not None and current is not None
                            and (float(v) < current if assistance else float(v) > current)), reverse=assistance)
            if steps and finite(plan.get("next_target_reps")) is not None:
                proposed = {**previous, "load_value": steps[0]}
                numerical = {"load_value": steps[0], "load_basis": load_basis(previous),
                             "load_unit": previous.get("load_unit"), "reference_set_id": previous.get("set_uuid") or previous.get("set_id") or previous.get("id"),
                             "reps_target": plan["next_target_reps"], "changes": load_change(previous, proposed),
                             "expected_success": None, "exit_options": ["stop", "revise_target", "end_exercise"],
                             "reason": "user_allowed_task_trial_not_capacity_guarantee"}
            else:
                reasons.append("harder_available_equipment_step_required")
        elif "heavier_lower_reps" in actions:
            reasons.append("comparable_reference_and_explicit_lower_repetition_target_required")
        return emit({"candidates": actions, "reviewed_principle_ids": [p.get("id", p.get("theory_id")) for p in approved],
                     "task_trial": numerical, "verification_task": context.get("verification_task"), "personal_optimum": None},
                    "valid" if actions and len(reasons) == 1 else "insufficient", reasons=reasons)
    if code in {27, 28}:
        outcomes = context.get("recommendation_outcomes", [])
        if code == 27:
            values = []
            for row in outcomes:
                targets = row.get("frozen_targets", {})
                actual = row.get("actual", {})
                executed = row.get("execution_state") == "executed"
                quality_known = isinstance(row.get("quality_comparable"), bool)
                complete = executed and quality_known and bool(targets) and all(k in actual and actual[k] is not None for k in targets)
                met = complete and row.get("quality_comparable") is True and all(
                    spec["min"] <= actual[k] <= spec["max"] for k, spec in targets.items())
                values.append({"recommendation_id": row.get("recommendation_id"), "adoption": row.get("adoption"),
                               "execution_state": row.get("execution_state"),
                               "short_term_success": bool(met) if complete else None,
                               "reason_codes": ["execution_not_confirmed"] if not executed else ["task_condition_or_quality_unknown"] if not quality_known else [],
                               "nonexecution_reason": row.get("nonexecution_reason"), "complete": complete})
            return emit(values or None, "valid" if values else "insufficient", count_domain="recommendations",
                        valid_n=len(values), total_n=len(outcomes))
        values = strength_metric("STR-27", rows, window, context)["value"] or []
        responding = [r for r in values if r["adoption"] in {"adopted", "partially_adopted", "not_adopted"}]
        complete = [r for r in values if r["short_term_success"] is not None]
        return emit({"adoption_numerator": sum(r["adoption"] == "adopted" for r in responding), "adoption_denominator": len(responding),
                     "unanswered": len(values) - len(responding), "success_numerator": sum(r["short_term_success"] for r in complete),
                     "success_denominator": len(complete), "missing_outcomes": len(values) - len(complete)},
                    "valid" if values else "insufficient", count_domain="recommendations", total_n=len(values), valid_n=len(complete))
    if code == 29:
        return emit({"fields": {k: {"numerator": sum(r.get(k) is not None for r in rows), "denominator": total}
                                for k in ("entered_load", "reps", "rir", "stop_reason")},
                     "comparable_references": sum(condition_key(r) is not None for r in refs), "candidate_references": len(refs)},
                    "valid" if rows else "insufficient", reasons=["no_aggregate_quality_score"])
    if code == 30:
        numerator = finite(context.get("strength_numerator"))
        mass = finite(context.get("body_mass_kg"))
        if numerator is None or mass is None or mass <= 0 or not context.get("complete_load_known"):
            return emit(None, "insufficient", reasons=["complete_numerator_and_comparable_body_mass_required"])
        return emit({"ratio": numerator / mass, "numerator": numerator, "body_mass_kg": mass,
                     "numerator_identity": context.get("strength_numerator_identity")}, evidence_status=context.get("numerator_evidence_status", "descriptive"))
    raise ValueError("unknown_strength_metric")
