"""Explicit development-fixture bridge to real deterministic executors.

This does not parse user language or synthesize private data. It accepts only
the three structured arithmetic development contexts published in the pack.
Timestamps and source labels below identify synthetic fixtures, not acquired
health records. Energy fixture assumptions are displayed in the result.
"""

from .engine import evaluate


def metric_provider(case: dict) -> list[dict]:
    data = case.get("input_context", {})
    identity = case.get("case_id")
    bounds = {"cutoff_time": "2026-11-11T12:00:00+00:00",
              "window_start": "2026-11-10T00:00:00+00:00", "window_end": "2026-11-11T12:00:00+00:00"}
    if identity == "Q04" and isinstance(data.get("sets"), list):
        rows = [{"id": f"synthetic-Q04-set-{i}", "session_id": "synthetic-Q04-session", "record_kind": "strength_set",
                 "role": "work", "status": "completed", "measurement_mode": "repetitions", "load_value": row["load_total_kg"],
                 "load_unit": "kg", "load_basis": "external_total_kg", "reps": row["reps"],
                 "event_end": "2026-11-10T12:00:00+00:00", "available_at": "2026-11-10T12:01:00+00:00"}
                for i, row in enumerate(data["sets"])]
        value = evaluate("STR-04", rows, **bounds)
    elif identity == "Q17" and {"session_rpe", "duration_min"} <= data.keys():
        session = {"session_id": "synthetic-Q17-session", "started_at": "2026-11-10T10:00:00+00:00",
                   "ended_at": "2026-11-10T11:00:00+00:00", "available_at": "2026-11-10T11:30:00+00:00",
                   "session_rpe": data["session_rpe"], "duration_seconds": data["duration_min"] * 60,
                   "duration_protocol": "user_elapsed_including_rest", "srpe_protocol": "declared_whole_session_0_10",
                   "srpe_collected_at": "2026-11-10T11:30:00+00:00"}
        value = evaluate("LOAD-SRPE-AU", [], context={"sessions": [session]}, **bounds)
    elif identity == "Q21" and {"basal_kcal", "active_kcal", "workout_kcal"} <= data.keys():
        rows = [{"id": "synthetic-Q21-" + name, "canonical_type": canonical, "normalized_value": data[name], "normalized_unit": "kcal",
                 "source_name": "single-source-fixture-assumption", "protocol_id": "same-interval-fixture-assumption",
                 "event_start": "2026-11-10T00:00:00+00:00", "event_end": "2026-11-11T00:00:00+00:00",
                 "available_at": "2026-11-11T01:00:00+00:00"} for name, canonical in
                (("basal_kcal", "basal_energy_kcal"), ("active_kcal", "active_energy_kcal"), ("workout_kcal", "workout_energy_kcal"))]
        value = evaluate("ENERGY-DEVICE-TOTAL", rows, **bounds)
        value["assumptions"].append("Synthetic conditional example: same source, same interval, nonoverlapping component semantics; verify those conditions for real data")
    else:
        return []
    value["fixture_identity"] = identity
    value["assumptions"].append("Published structured development fixture, not independent real-user validation")
    return [value]
