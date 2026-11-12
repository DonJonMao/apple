"""STR-01…30: audit-preserving strength observations and gated research inference."""

from __future__ import annotations

from collections import defaultdict
from zoneinfo import ZoneInfo

from healthzip.normalize import quantity_value

from .applicability import candidate_applicability
from .contracts import Window, canonical_hash, finite, instant, result
from .formulas import e1rm
from .registry import calibration_scope_check, task_calibration_scope, verified_look
from .semantics import (
    analysis_task,
    comparable,
    condition_key,
    load_basis,
    load_change,
    load_components,
    outcome_series,
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


def equivalence_reasons(delta, outcome_unit, refs=()):
    if delta and delta.get("unit") is not None and delta["unit"] != outcome_unit:
        raise ValueError("practical_equivalence_unit_mismatch")
    if not delta or any(finite(delta.get(k)) is None or delta[k] < 0 for k in ("lower_magnitude", "upper_magnitude")):
        return ["user_or_protocol_equivalence_required"]
    reasons = []
    if not delta.get("unit"):
        reasons.append("practical_equivalence_unit_required")
    if not delta.get("declared_before"):
        reasons.append("practical_equivalence_not_preregistered")
    elif refs and instant(delta["declared_before"]) > min(instant(r["_event_end"]) for r in refs):
        reasons.append("practical_equivalence_chosen_after_observations")
    if not delta.get("provenance"):
        reasons.append("practical_equivalence_provenance_required")
    return reasons


def _plan_rir_range(plan, *, required):
    raw = (plan.get("target_rir_min"), plan.get("target_rir_max"))
    if raw == (None, None) and not required:
        return None, []
    lower, upper = map(finite, raw)
    if lower is None or upper is None:
        return None, ["complete_finite_target_rir_range_required"]
    if not 0 <= lower <= upper <= 10:
        return None, ["ordered_target_rir_range_within_zero_to_ten_required"]
    return {"min": lower, "max": upper}, []


def _plan_equipment_steps(plan):
    raw = plan.get("available_loads")
    if not isinstance(raw, (list, tuple)):
        return None
    values = [finite(value) for value in raw]
    if any(value is None or value < 0 for value in values):
        return None
    return values


def _frozen_muscle_mapping(row):
    mapping = row.get("reviewed_anatomy_snapshot")
    if not isinstance(mapping, dict):
        return None, "frozen_muscle_mapping_required"
    if (mapping.get("review_status") != "approved"
            or any(not isinstance(mapping.get(k), str) or not mapping[k].strip() for k in ("mapping_id", "reviewer"))
            or not mapping.get("version") or isinstance(mapping["version"], bool)
            or not isinstance(mapping.get("evidence_refs"), list) or not mapping["evidence_refs"]
            or any(not isinstance(ref, (str, dict)) or not ref for ref in mapping["evidence_refs"])):
        return None, "frozen_mapping_review_or_evidence_incomplete"
    if (not mapping.get("exercise_id") or mapping.get("definition_version") is None
            or mapping.get("exercise_id") != row.get("exercise_id")
            or str(mapping.get("definition_version")) != str(row.get("definition_version"))):
        return None, "frozen_mapping_exercise_version_mismatch"
    if any(not isinstance(mapping.get(role), list) or any(not isinstance(name, str) or not name.strip() for name in mapping[role])
           for role in ("direct", "indirect")):
        return None, "frozen_mapping_roles_invalid"
    try:
        reviewed, frozen, available = (instant(mapping.get("reviewed_at")), instant(mapping.get("frozen_at")),
                                       instant(row.get("available_at") or row.get("ingested_at")))
    except ValueError:
        return None, "frozen_mapping_time_or_availability_unknown"
    if not reviewed <= frozen <= available:
        return None, "frozen_mapping_review_or_binding_after_record_availability"
    return mapping, None


def _plan_target_observation(endpoint, target, row, planned_id):
    """Compare one original target with one recorded endpoint, never a score."""
    from healthzip.training.semantics import TrainingError, load_semantics
    from healthzip.training.semantics import load_change as recorded_load_change

    row = row or {}
    state = row.get("status")
    out = {"planned_set_id": planned_id, "actual_record_id": row.get("_source_id", row.get("id")),
           "execution_state": state, "status": "unknown", "observed_match": None, "reason_codes": []}
    if endpoint == "load":
        spec = {key: target.get(key) for key in ("load_value", "load_unit", "load_basis")}
        observed = {key: row.get(key) for key in spec}
        present = spec["load_value"] is not None
    else:
        exact = target.get("rir") if endpoint == "rir" else None
        spec = {"min": exact if exact is not None else target.get(endpoint + "_min"),
                "max": exact if exact is not None else target.get(endpoint + "_max")}
        present = any(value is not None for value in spec.values())
        observed = row.get("rir_interval") if endpoint == "rir" else None
        if observed is None:
            observed = {"lower": row.get(endpoint), "upper": row.get(endpoint)}
    out.update(target=spec, actual=observed)
    if not present:
        out.update(status="no_target", reason_codes=["original_plan_has_no_endpoint_target"])
        return out
    if state == "skipped":
        out.update(status="not_met", reason_codes=["explicitly_skipped_not_executed"])
        return out
    if not row:
        out["reason_codes"] = ["actual_record_missing_or_unavailable"]
        return out
    if endpoint == "load":
        basis = spec["load_basis"]
        if basis in (None, "", "unknown", "band_configuration") or not spec["load_unit"]:
            out["reason_codes"] = ["original_target_load_unit_and_basis_required"]
            return out
        if observed["load_basis"] != basis:
            out["reason_codes"] = ["actual_and_target_load_basis_incompatible_or_unknown"]
            return out
        try:
            goal = load_semantics(spec["load_value"], spec["load_unit"], basis)
            actual = load_semantics(observed["load_value"], observed["load_unit"], basis)
            comparable_units = (goal["normalized_recorded_kg"] is not None and actual["normalized_recorded_kg"] is not None
                                or spec["load_unit"] == observed["load_unit"])
            comparison = recorded_load_change(spec, observed, {"load_basis": basis})
        except TrainingError:
            out["reason_codes"] = ["finite_load_and_explicit_compatible_units_required"]
            return out
        if not comparable_units or comparison["recorded_change"] is None:
            out["reason_codes"] = ["observed_load_or_compatible_unit_missing"]
            return out
        out["comparison"] = comparison
        matched = comparison["recorded_change"] == 0
        out["comparison_definition"] = "recorded_plan_load_match_not_harder_is_better"
    else:
        low, high = finite(spec["min"]), finite(spec["max"])
        if (low is None or high is None or low < 0 or low > high
                or endpoint == "reps" and (int(low) != low or int(high) != high)
                or endpoint == "rir" and high > 10):
            out["reason_codes"] = ["complete_valid_original_target_range_required"]
            return out
        if not isinstance(observed, dict):
            out["reason_codes"] = ["observed_endpoint_unknown"]
            return out
        lower, upper = finite(observed.get("lower")), finite(observed.get("upper"))
        if (lower is None and upper is None or lower is not None and lower < 0
                or upper is not None and upper < 0 or lower is not None and upper is not None and lower > upper
                or observed.get("lower") is not None and lower is None
                or observed.get("upper") is not None and upper is None):
            out["reason_codes"] = ["observed_endpoint_unknown_or_invalid"]
            return out
        if lower is not None and upper is not None and low <= lower <= upper <= high:
            matched = True
        elif lower is not None and lower > high or upper is not None and upper < low:
            matched = False
        else:
            matched = None
            out["reason_codes"] = ["reported_interval_does_not_determine_target_match"]
    out["observed_match"] = matched
    if state not in {"completed", "aborted"}:
        out["reason_codes"].append("execution_not_final_observation_is_provisional")
    elif matched is not None:
        out["status"] = "met" if matched else "not_met"
    return out


def _plan_target_attainment(planned, actual):
    # Preserve each original plan identity even when its endpoint is absent.
    unique = {str(entry["id"]): entry for entry in planned}
    output = {}
    for endpoint in ("load", "reps", "rir"):
        observations = [_plan_target_observation(endpoint, entry.get("targets") or {}, actual.get(identity), identity)
                        for identity, entry in unique.items()]
        counts = {state: sum(row["status"] == state for row in observations)
                  for state in ("met", "not_met", "unknown", "no_target")}
        known = counts["met"] + counts["not_met"]
        targeted = len(unique) - counts["no_target"]
        output[endpoint] = {"planned_n": len(unique), "target_n": targeted, "known_n": known,
                            **{key + "_n": value for key, value in counts.items()},
                            "fraction_of_known_targets": counts["met"] / known if known else None,
                            "observed_met_fraction_of_targets": counts["met"] / targeted if targeted else None,
                            "observations": observations}
    return output


def strength_metric(metric_id: str, rows: list[dict], window: Window, context: dict) -> dict:
    code = int(metric_id.split("-")[1])
    total = len(rows)
    work = _parents([row for row in rows if _completed(row)])
    refs = reference_rows(rows, context)
    kw = {"records": rows, "total_n": total}
    if code in {25, 26}:
        applicability = candidate_applicability(refs[-1] if refs else None, context.get("current_session_observations"))
        unknown_observations = context.get("current_session_observation_unknown_ids", [])
        if unknown_observations:
            applicability["current_session_record_ids"] = sorted(set(applicability["current_session_record_ids"]) | set(unknown_observations))
            applicability["reason_codes"].append("current_observation_time_or_availability_unknown")
            if applicability["applicable"] is not False:
                applicability.update(applicable=None, status="unknown")
        kw["candidate_applicability"] = applicability

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
        grouped, unknown, reasons, valid, versions = {}, [], [], [], defaultdict(set)
        for row in work:
            mapping, reason = _frozen_muscle_mapping(row)
            if reason:
                unknown.append(row.get("id"))
                reasons.append(reason)
                continue
            identity = (mapping["mapping_id"], str(mapping["version"]))
            versions[identity].add(canonical_hash({k: v for k, v in mapping.items() if k != "frozen_at"}))
            valid.append((row, mapping, identity))
        bindings = []
        for row, mapping, identity in valid:
            if len(versions[identity]) > 1:
                unknown.append(row.get("id"))
                reasons.append("frozen_mapping_version_content_conflict")
                continue
            source_id = row.get("_source_id", row.get("id"))
            bindings.append({"source_record_id": source_id, "mapping_id": identity[0], "mapping_version": identity[1],
                             "frozen_at": mapping["frozen_at"], "snapshot_sha256": canonical_hash(mapping)})
            for muscle in mapping[role]:
                group = grouped.setdefault((muscle, row.get("side"), *identity), {
                    "muscle": muscle, "side": row.get("side"), "mapping_id": identity[0], "mapping_version": identity[1],
                    "reviewer": mapping["reviewer"], "reviewed_at": mapping["reviewed_at"], "evidence_refs": mapping["evidence_refs"],
                    "source_record_ids": set()})
                group["source_record_ids"].add(source_id)
        if not bindings:
            return emit(None, "insufficient", reasons=sorted(set(reasons or ["frozen_muscle_mapping_required"])), valid_n=0)
        values = [{**g, "source_record_ids": sorted(g["source_record_ids"]), "sets": len(g["source_record_ids"])} for g in grouped.values()]
        return emit({"groups": values, "unknown_set_ids": unknown, "mapping_bindings": bindings},
                    "partial" if unknown else "valid", valid_n=len(bindings), reasons=sorted(set(reasons)))
    if code in {7, 8}:
        known = [r for r in refs if condition_key(r) is not None]
        times = sorted({(r["session_id"], r["_event_end"]) for r in known}, key=lambda p: p[1])
        dates = [instant(t) for _, t in times]
        elapsed = (min(instant(window.end), instant(window.cutoff_time)) - instant(window.start)).total_seconds() / 86400
        recorded = {r["session_id"]: r for r in work if r.get("session_id")}
        eligible = {r["session_id"] for r in known if outcome_series(r)["eligible"]}
        series_groups = defaultdict(list)
        for record in known:
            identity = outcome_series(record)
            if identity["eligible"]:
                series_groups[identity["outcome_series_id"]].append(record)
        exposures = []
        for group in series_groups.values():
            endpoints = sorted(instant(r["_event_end"]) for r in group)
            exposures.append({**outcome_series(group[0]), "sessions": len({r["session_id"] for r in group}),
                              "span_days": (endpoints[-1] - endpoints[0]).total_seconds() / 86400,
                              "first_observed_at": endpoints[0].isoformat(), "last_observed_at": endpoints[-1].isoformat(),
                              "source_record_ids": [r.get("_source_id") for r in group]})
        frequency_n = len(recorded) if code == 8 else len(times)
        zone = ZoneInfo(window.timezone)
        frequency_dates = ({instant(r["_event_end"]).astimezone(zone).date() for r in recorded.values()}
                           if code == 8 else {d.astimezone(zone).date() for d in dates})
        value = {"sessions": frequency_n, "observed_dates": len(frequency_dates),
                 "span_days": (dates[-1] - dates[0]).total_seconds() / 86400 if dates else None,
                 "recorded_frequency_per_week": frequency_n / elapsed * 7 if elapsed > 0 and len(frequency_dates) > 1 else None,
                 "frequency_window_elapsed_days": elapsed,
                 "interval_days": [(b - a).total_seconds() / 86400 for a, b in zip(dates, dates[1:])],
                 "recorded_training_sessions": len(recorded), "comparable_reference_sessions": len(eligible),
                 "recorded_without_eligible_reference_session_ids": sorted(set(recorded) - eligible),
                 "outcome_series_exposures": exposures}
        return emit(value, "valid" if known or code == 8 and recorded else "insufficient", valid_n=len(known) if code == 7 else len(recorded),
                    reasons=["recorded_frequency_not_actual_training_or_recovery"])
    if code == 9:
        def plan_group_completed(row):
            # The plan denominator includes prescribed warmups as well as work.
            # Other strength metrics retain the work-only _completed contract.
            field = {"repetitions": "reps", "duration": "duration_s", "distance": "distance_m"}.get(row.get("measurement_mode"))
            value = finite(row.get(field)) if field else None
            return row.get("status") == "completed" and value is not None and value > 0

        plan = context.get("plan_snapshot")
        if not plan:
            return emit(None, "not_applicable", reasons=["unplanned_session"])
        planned = plan.get("sets", [])
        planned_ids = {str(s["id"]) for s in planned}
        actual = {str(r.get("planned_set_id")): r for r in rows if str(r.get("planned_set_id")) in planned_ids}
        done = sum(plan_group_completed(r) for r in actual.values())
        skipped = sum(r.get("status") == "skipped" for r in actual.values())
        unknown = len(planned_ids) - done - skipped
        attainment = _plan_target_attainment(planned, actual)
        return emit({"completed": done, "skipped": skipped, "unknown": unknown, "planned": len(planned_ids),
                     "completed_fraction_of_plan": done / len(planned_ids) if planned_ids else None,
                     "extra_sets": sum(str(r.get("planned_set_id")) not in planned_ids and plan_group_completed(r) for r in rows),
                     "target_attainment": attainment, "target_attainment_version": "original-plan-endpoints-1.4.0",
                     "target_attainment_definition": "separate_recorded_endpoint_matches_not_group_completion_or_training_benefit"},
                    "partial" if unknown or any(item["unknown_n"] for item in attainment.values()) else "valid",
                    valid_n=done + skipped, total_n=len(planned_ids), count_domain="planned_sets")
    if code == 10:
        values = []
        for row in rows:
            reserve = finite(row.get("rir"))
            conversion = False
            # An interval (for example 3+) is a reported RIR observation, not a
            # missing value to replace with a potentially conflicting RPE map.
            if (row.get("rir") is None and row.get("rir_interval") is None
                    and row.get("scale_type") == "rir_based_rpe_6_10"
                    and finite(row.get("rpe")) is not None and 6 <= row["rpe"] <= 10):
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
        comparison_series = []
        if code in {12, 14} and not context.get("comparison_pair"):
            layers = defaultdict(list)
            for record in refs:
                identity = outcome_series(record)
                key = (identity["outcome_series_id"], record.get("reps") if code == 14 else None)
                layers[key].append(record)
            for (identity, _), group in layers.items():
                if len(group) >= 2:
                    calculated = strength_metric(metric_id, group, window, {**context, "comparison_pair": group[-2:]})
                    comparison_series.append({"outcome_series_id": identity, "value": calculated["value"],
                                              "data_status": calculated["data_status"], "reason_codes": calculated["reason_codes"]})
            if comparison_series:
                valid = [item for item in comparison_series if item["value"] is not None]
                if valid:
                    latest = max(valid, key=lambda item: instant(item["value"]["current_observed_at"]))
                    return emit({**latest["value"], "comparison_series": comparison_series}, latest["data_status"],
                                evidence_status="descriptive", reasons=latest["reason_codes"])
        if len(pair) != 2:
            return emit(None, "insufficient", reasons=["two_reference_observations_required"])
        old, new = pair
        ok, reasons = comparable(old, new)
        if not ok:
            return emit(None, "incompatible", reasons=reasons)
        same_load = outcome_series(old)["outcome_series_id"] == outcome_series(new)["outcome_series_id"]
        same_reps = finite(old.get("reps")) is not None and old.get("reps") == new.get("reps")
        protocol_ok, protocol_reasons = comparable(old, new, protocol=True)
        base = {"reference_id": old.get("id"), "current_id": new.get("id"),
                "reference_observed_at": old.get("_event_end"), "current_observed_at": new.get("_event_end"),
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
        series, comparison_exclusions = [], []
        for (session, key), group in groups.items():
            group.sort(key=lambda r: r.get("set_position", r.get("set_number", 0)))
            first = group[0]
            if key is None or not first.get("reps"):
                continue
            for row in group:
                if row.get("set_structure") not in {None, "straight"}:
                    comparison_exclusions.append({"set_id": row.get("id"), "reason": "within_session_set_structure_changed"})
                    continue
                if load_change(first, row)["entered_change"] != 0:
                    comparison_exclusions.append({"set_id": row.get("id"), "reason": "within_session_load_changed_or_unknown"})
                    continue
                if finite(row.get("reps")) is not None:
                    series.append({"session_id": session, "set_id": row.get("id"),
                                   "delta_reps": row["reps"] - first["reps"],
                                   "fraction_decrease": (first["reps"] - row["reps"]) / first["reps"]})
        return emit(series or None, "partial" if series and comparison_exclusions else "valid" if series else "insufficient",
                    valid_n=len(series), evidence_status="descriptive", comparison_exclusions=comparison_exclusions)
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
        delta = context.get("practical_equivalence")
        delta_reasons = equivalence_reasons(delta, "repetitions", refs) if code == 22 else []
        if refs and (not comparable(refs[0], refs[0], protocol=True)[0] or any(not comparable(refs[0], r, protocol=True)[0]
                                                     or outcome_series(r)["outcome_series_id"] != outcome_series(refs[0])["outcome_series_id"] for r in refs[1:])):
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
                        reasons=trend["reason_codes"], parameter_set_id=context.get("parameter_set_id"), look_allocation=allocation,
                        point_estimate={**{key: trend.get(key) for key in ("slope_per_day", "change", "span_days", "horizon_days", "n")},
                                        "unit": "repetitions", "slope_unit": "repetitions/day", "evidence_status": "descriptive"})
        calibration = context.get("calibration")
        scope_check = calibration_scope_check(calibration, metric_id=metric_id,
            scope=task_calibration_scope(refs[-1] if refs else None, context), model_version=trend["model_version"])
        reasons = []
        label = "uncertain"
        if not refs or any(opportunity(r) == "capacity_unobserved" for r in refs):
            label, reasons = "opportunity_unchecked", ["capacity_unobserved"]
        elif delta_reasons:
            reasons = delta_reasons
        elif not trend["interval"]:
            reasons = trend["reason_codes"]
        elif not scope_check["matches"]:
            reasons = ["target_calibration_missing_or_scope_mismatch"]
        elif allocation_reasons:
            reasons = allocation_reasons
        else:
            lo, hi = trend["interval"]["lower"], trend["interval"]["upper"]
            left, right = delta["lower_magnitude"], delta["upper_magnitude"]
            label = classify_interval(lo, hi, left, right)
        if not scope_check["matches"]:
            reasons = list(dict.fromkeys(reasons + ["target_calibration_missing_or_scope_mismatch"] + scope_check["reason_codes"]))
        return emit({"classification": label, "trend": trend, "practical_equivalence": delta},
                    "insufficient" if reasons else "valid", evidence_status="research_only" if reasons else "model_conditional",
                    calibration=calibration, calibration_scope_check=scope_check, reasons=reasons, valid_n=len(refs))
    if code == 21:
        delta = context.get("practical_equivalence")
        reasons = equivalence_reasons(delta, context.get("outcome_unit", "repetitions"), refs)
        if reasons:
            return emit(None, "insufficient", reasons=reasons)
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
        if not history or not isinstance(plan, dict) or not plan:
            return emit(None, "insufficient", reasons=["comparable_reference_and_user_plan_required"])
        if applicability["applicable"] is not True:
            return emit({"candidate": "review_observations_or_collect_reference", "next_load": None}, "partial",
                        reasons=["candidate_applicability_" + applicability["status"], *applicability["reason_codes"]])
        if not comparable(history, history, protocol=True)[0]:
            return emit(None, "insufficient", reasons=["complete_reference_protocol_required"])
        if not history.get("load_unit"):
            return emit(None, "insufficient", reasons=["reference_load_unit_required"])
        upper, next_reps = finite(plan.get("rep_upper")), finite(plan.get("next_target_reps"))
        reasons = []
        if upper is None or upper <= 0 or int(upper) != upper:
            reasons.append("positive_integer_plan_repetition_upper_required")
        if next_reps is None or next_reps <= 0 or int(next_reps) != next_reps:
            reasons.append("positive_integer_next_repetition_target_required")
        elif upper is not None and next_reps > upper:
            reasons.append("next_repetition_target_exceeds_plan_upper")
        effort, effort_reasons = _plan_rir_range(plan, required=True)
        reasons.extend(effort_reasons)
        available = _plan_equipment_steps(plan)
        if available is None:
            reasons.append("finite_nonnegative_equipment_steps_required")
        if reasons:
            return emit(None, "insufficient", reasons=reasons)
        current = finite(history.get("entered_load"))
        reserve = finite(history.get("rir"))
        observed_reps = finite(history.get("reps"))
        assistance = load_basis(history) == "assistance_setting"
        steps = sorted((v for v in available if current is not None
                        and (v < current if assistance else v > current)), reverse=assistance)
        qualified = current is not None and observed_reps is not None and observed_reps >= upper \
            and reserve is not None and effort["min"] <= reserve <= effort["max"] and history.get("quality") == "acceptable"
        if not qualified or not steps:
            return emit({"candidate": "continue_user_plan_or_collect_reference", "next_load": None}, "partial",
                        reasons=["plan_upper_target_or_effort_or_quality_not_met" if not qualified else "no_available_equipment_step"])
        principles = context.get("reviewed_principles", [])
        reviewed = [p for p in principles if p.get("review_status") == "approved"
                    and p.get("version") and p.get("reviewer") and p.get("reviewed_at")
                    and p.get("capability") == "progression_candidate"
                    and "double_progression" in p.get("permitted_actions", [])
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
                     "target_reps": int(next_reps), "target_rir_range": effort,
                     "load_basis": load_basis(history), "changes": changes,
                     "verification_task": "Record first work set, RIR, quality and stop reason; stop or revise if unsuitable",
                     "expected_success": None, "reviewed_principle_versions": [{"id": p.get("id", p.get("theory_id")), "version": p["version"]} for p in reviewed]}, evidence_status="definition_based",
                    reasons=["user_plan_candidate_not_guaranteed_success_or_optimal_prescription"])
    if code == 26:
        discussion = context.get("reviewed_discussion")
        if (discussion and discussion.get("strategy") in {"discuss_sets", "discuss_interval", "discuss_rest"}
                and discussion.get("strategy") in context.get("allowed_trial_actions", [])):
            source = discussion.get("source_explanation", {})
            supported = (discussion.get("authority") == "source_explanation_only"
                         and source.get("answer_status") == "answered_with_support"
                         and bool(source.get("claims")) and bool(source.get("citations")))
            return emit({"candidates": [discussion["strategy"]] if supported else [],
                         "discussion": discussion, "task_trial": None, "quantified_change": None,
                         "personal_optimum": None, "reviewed_principle_ids": []},
                        "valid" if supported else "insufficient",
                        reasons=["source_explanation_only_no_numerical_permission" if supported
                                 else "eligible_source_explanation_required",
                                 "personal_intervention_effect_unvalidated"])
        if applicability["applicable"] is not True:
            return emit({"candidates": ["maintain_and_collect_reference"], "task_trial": None,
                         "quantified_change": None, "review_options": ["review_symptoms_and_technique", "clarify_unknown_observations"]}, "partial",
                        reasons=["candidate_applicability_" + applicability["status"], *applicability["reason_codes"]])
        allowed = context.get("allowed_trial_actions", [])
        approved = [p for p in context.get("reviewed_principles", [])
                    if p.get("review_status") == "approved" and p.get("version") and p.get("reviewer")
                    and p.get("reviewed_at") and p.get("evidence_spans") and p.get("rights_verified")
                    and p.get("scope_matches") and p.get("capability") in {"progression_candidate", "trial_candidate"}]
        if not approved:
            return emit({"candidates": ["maintain_and_collect_reference"], "quantified_change": None}, "partial",
                        reasons=["reviewed_principles_missing", "personal_intervention_effect_unvalidated"])
        permitted = {action for principle in approved for action in principle.get("permitted_actions", [])}
        actions = [v for v in allowed if v in permitted
                   and v in {"repetition_progression", "heavier_lower_reps", "discuss_sets", "discuss_interval", "maintain_and_collect_reference"}]
        if not actions:
            return emit({"candidates": ["maintain_and_collect_reference"], "task_trial": None, "quantified_change": None},
                        "partial", reasons=["specific_reviewed_rule_action_permission_required"])
        numerical = None
        plan = context.get("progression_plan") or {}
        reasons = ["trial_not_causal_effect_estimate"]
        if not isinstance(plan, dict):
            return emit(None, "insufficient", reasons=["user_trial_plan_must_be_structured"])
        effort, effort_reasons = _plan_rir_range(plan, required=False)
        if effort_reasons and {"heavier_lower_reps", "repetition_progression"}.intersection(actions):
            return emit({"candidates": actions, "task_trial": None}, "insufficient", reasons=effort_reasons)
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
            available = _plan_equipment_steps(plan)
            if available is None:
                return emit(None, "insufficient", reasons=["finite_nonnegative_equipment_steps_required"])
            steps = sorted((v for v in available if current is not None
                            and (v < current if assistance else v > current)), reverse=assistance)
            if steps and finite(plan.get("next_target_reps")) is not None:
                proposed = {**previous, "load_value": steps[0]}
                numerical = {"load_value": steps[0], "load_basis": load_basis(previous),
                             "load_unit": previous.get("load_unit"), "reference_set_id": previous.get("set_uuid") or previous.get("set_id") or previous.get("id"),
                             "reps_target": int(target_reps), "changes": load_change(previous, proposed),
                             "expected_success": None, "exit_options": ["stop", "revise_target", "end_exercise"],
                             "reason": "user_allowed_task_trial_not_capacity_guarantee"}
            else:
                reasons.append("harder_available_equipment_step_required")
        elif "heavier_lower_reps" in actions:
            reasons.append("comparable_reference_and_explicit_lower_repetition_target_required")
        if "repetition_progression" in actions and "heavier_lower_reps" not in actions:
            previous = refs[-1] if refs else None
            upper = finite(plan.get("rep_upper"))
            if not previous:
                reasons.append("comparable_reference_required")
            elif not comparable(previous, previous, protocol=True)[0]:
                reasons.append("complete_reference_protocol_required")
            elif not previous.get("load_unit") or finite(previous.get("load_value")) is None:
                reasons.append("reference_load_and_unit_required")
            elif upper is None or upper <= 0 or int(upper) != upper:
                reasons.append("explicit_positive_integer_user_repetition_upper_target_required")
            elif finite(previous.get("reps")) is None or upper <= previous["reps"]:
                reasons.append("user_upper_repetition_target_not_above_observation")
            else:
                reference_id = previous.get("set_uuid") or previous.get("set_id") or previous.get("id")
                numerical = {"load_value": finite(previous["load_value"]), "load_basis": load_basis(previous),
                             "load_unit": previous["load_unit"], "reference_set_id": reference_id,
                             "reps_target": int(upper), "changes": load_change(previous, previous),
                             "expected_success": None, "exit_options": ["stop", "revise_target", "end_exercise"],
                             "reason": "same_observed_load_and_explicit_user_repetition_upper_target",
                             "numeric_provenance": {
                                 "load_value": {"kind": "observed", "unit": previous["load_unit"], "source_record_id": reference_id},
                                 "reps_target": {"kind": "user_target", "unit": "repetitions", "source": "progression_plan.rep_upper",
                                                 "target_version": context.get("target_version")}}}
        if numerical is not None:
            numerical["target_rir_range"] = effort
            numerical["effort_target_status"] = "user_specified" if effort is not None else "unspecified"
            if effort is None:
                reasons.append("target_rir_unspecified_not_effort_matched")
        return emit({"candidates": actions, "reviewed_principle_ids": [p.get("id", p.get("theory_id")) for p in approved],
                     "action_authority": [{"action": action, "rule_versions": [
                         {"id": p.get("id", p.get("theory_id")), "version": p["version"]} for p in approved if action in p.get("permitted_actions", [])]}
                         for action in actions],
                     "task_trial": numerical, "verification_task": context.get("verification_task"), "personal_optimum": None},
                    "partial" if numerical is not None and effort is None else
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
                               "strategy": row.get("strategy"), "task_id": row.get("task_id"), "rule_versions": row.get("rule_versions"),
                               "execution_state": row.get("execution_state"),
                               "short_term_success": bool(met) if complete else None,
                               "reason_codes": (["execution_not_confirmed"] if not executed else ["task_condition_or_quality_unknown"] if not quality_known else [])
                                   + row.get("comparison_reason_codes", []),
                               "nonexecution_reason": row.get("nonexecution_reason"), "complete": complete,
                               "frozen_targets": targets, "actual": actual,
                               "target_comparisons": row.get("target_comparisons", []),
                               "actual_observations": row.get("actual_observations", []),
                               "execution_change": row.get("execution_change"),
                               "execution_change_reason_codes": row.get("execution_change_reason_codes", []),
                               "followup": row.get("followup"), "feedback_missing": row.get("feedback_missing"),
                               "report_membership": row.get("report_membership")})
            return emit(values or None, "valid" if values else "insufficient", count_domain="recommendations",
                        valid_n=len(values), total_n=len(outcomes))
        values = strength_metric("STR-27", rows, window, context)["value"] or []
        responding = [r for r in values if r["adoption"] in {"adopted", "partially_adopted", "not_adopted"}]
        complete = [r for r in values if r["short_term_success"] is not None]
        def observation_counts(group):
            return {"execution_numerator": sum(r.get("execution_state") == "executed" for r in group),
                    "execution_denominator": sum(r.get("execution_state") in {"executed", "partially_executed", "not_executed"} for r in group),
                    "execution_states": {state: sum((r.get("execution_state") or "unknown") == state for r in group)
                    for state in ("executed", "partially_executed", "not_executed", "unknown")},
                    "followup_states": {state: sum((r.get("followup") or {}).get("status", "not_planned") == state for r in group)
                    for state in ("not_planned", "pending", "observed", "no_comparable_observation", "not_executed", "execution_unconfirmed", "unavailable")},
                    "comparable_followup_observations": sum(len((r.get("followup") or {}).get("observations", [])) for r in group)}
        groups, strata = defaultdict(list), []
        for item in values:
            identity = {key: item.get(key) for key in ("strategy", "task_id", "rule_versions")}
            groups[canonical_hash(identity)].append(item)
        for group in groups.values():
            replied = [item for item in group if item["adoption"] in {"adopted", "partially_adopted", "not_adopted"}]
            known = [item for item in group if item["short_term_success"] is not None]
            strata.append({**{key: group[0].get(key) for key in ("strategy", "task_id", "rule_versions")},
                           "recommendation_ids": [item["recommendation_id"] for item in group],
                           "counts": {"adoption_numerator": sum(item["adoption"] == "adopted" for item in replied),
                                      "adoption_denominator": len(replied), "unanswered": len(group) - len(replied),
                                      "success_numerator": sum(item["short_term_success"] for item in known),
                                      "success_denominator": len(known), "missing_outcomes": len(group) - len(known),
                                      **observation_counts(group)}})
        return emit({"adoption_numerator": sum(r["adoption"] == "adopted" for r in responding), "adoption_denominator": len(responding),
                     "unanswered": len(values) - len(responding), "success_numerator": sum(r["short_term_success"] for r in complete),
                     "success_denominator": len(complete), "missing_outcomes": len(values) - len(complete), "strata": strata,
                     **observation_counts(values)},
                    "valid" if values else "insufficient", count_domain="recommendations", total_n=len(values), valid_n=len(complete))
    if code == 29:
        return emit({"fields": {k: {"numerator": sum(r.get(k) is not None for r in rows), "denominator": total}
                                for k in ("entered_load", "reps", "rir", "stop_reason")},
                     "comparable_references": sum(condition_key(r) is not None for r in refs), "candidate_references": len(refs),
                     "protocol_complete_references": sum(analysis_task(r)["protocol_complete"] for r in refs),
                     "outcome_series_eligible_references": sum(outcome_series(r)["eligible"] for r in refs),
                     "outcome_series_ids": sorted({outcome_series(r)["outcome_series_id"] for r in refs if outcome_series(r)["eligible"]})},
                    "valid" if rows else "insufficient", reasons=["no_aggregate_quality_score"])
    if code == 30:
        numerator = finite(context.get("strength_numerator"))
        mass_record = context.get("body_mass_observation")
        mass_numeric = quantity_value(mass_record) if mass_record else {}
        mass = mass_numeric.get("value") if mass_numeric.get("unit") == "kg" else None
        if numerator is None or context.get("strength_numerator_unit") != "kg" or mass is None or mass <= 0 or not context.get("complete_load_known"):
            return emit(None, "insufficient", reasons=["complete_numerator_and_comparable_body_mass_required"])
        return emit({"ratio": numerator / mass, "numerator": numerator, "body_mass_kg": mass,
                     "body_mass_record_id": mass_record.get("id", mass_record.get("_source_id")),
                     "body_mass_observed_at": mass_record.get("event_end", mass_record.get("end_utc")),
                     "body_mass_source": mass_record.get("source_name"), "body_mass_normalization": mass_numeric,
                     "numerator_identity": context.get("strength_numerator_identity")}, evidence_status=context.get("numerator_evidence_status", "descriptive"))
    raise ValueError("unknown_strength_metric")
