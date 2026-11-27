def _ordinary_reference_result(rows, window, context, bounded, templates):
    """Reuse the STR-11 absence result for already selected ordinary inventories.

    Only the repository analysis caller supplies these same-window, revision-
    resolved records and a fresh per-request template map. Reference eligibility
    still runs for every task; nominated or exceptional inputs keep the normal
    executor. Each public result owns its nested values and all source IDs.
    """
    from copy import deepcopy

    def normal():
        return evaluate("STR-11", cutoff_time=window.cutoff_time, window_start=window.start,
                        window_end=window.end, context=context, _normalized=rows,
                        _context_bound=bounded)

    if (not rows or any(not row.get("_source_id") or not row.get("_event_end")
                        or row.get("record_kind", "strength_set") != "strength_set"
                        or row.get("canonical_type", row.get("metric_type")) in NUMERIC_TYPES for row in rows)):
        return normal()
    reference_context = dict(bounded[0])
    if "reference_inventory" not in reference_context:
        cutoff = instant(window.cutoff_time)
        reference_context["reference_inventory"] = [row for row in rows if row.get("available_at")
                                                    and instant(row["available_at"]) <= cutoff]
    if reference_rows(rows, reference_context):
        return normal()
    prototype = templates.get("no_designated_reference")
    if prototype is None:
        prototype = normal()
        if prototype["value"] is not None or prototype["reason_codes"] not in (
                ["predesignated_reference_missing"],
                ["predesignated_reference_missing", "retrospective_snapshot_not_prospective"]):
            return prototype
        templates["no_designated_reference"] = deepcopy(prototype)
        return prototype
    value = deepcopy(prototype)
    value.update(source_record_ids=sorted({str(row["_source_id"]) for row in rows}),
                 total_n=len(rows), input_snapshot_n=len(rows), input_available_n=len(rows),
                 n_sessions=len({row["session_id"] for row in rows if row.get("session_id") is not None}))
    value["reason_codes"] = ["predesignated_reference_missing"]
    if any(row.get("_retrospective_snapshot") for row in rows):
        value["reason_codes"].append("retrospective_snapshot_not_prospective")
    validate_result(value, calibration=context.get("calibration"))
    return value

