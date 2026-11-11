"""Immutable, explicitly distinct formula identities; no input clipping."""

from __future__ import annotations

from typing import Optional

from .contracts import finite

FORMULAS = {
    "epley_n3_0.0333": {"version": "1", "expression": "w * (1 + 0.0333 * r)",
                         "source_id": "N3", "source_location": "Table 1", "rir": False},
    "epley_r_over_30": {"version": "1", "expression": "w * (1 + r / 30)",
                         "source_id": None, "source_location": "explicit algebraic variant", "rir": False},
    "epley_rir_over_30": {"version": "1", "expression": "w * (1 + (r + RIR) / 30)",
                           "source_id": None, "source_location": "v1.3 experimental proposal", "rir": True},
}


def e1rm(weight, reps, *, formula_id: str = "epley_r_over_30", rir=None,
         domain: Optional[dict] = None, load_basis: Optional[str] = None,
         measured_maximum: bool = False) -> dict:
    if formula_id not in FORMULAS:
        raise ValueError("unknown_formula")
    out = {"value": None, "unit": "kg", "formula_id": formula_id,
           "formula_version": FORMULAS[formula_id]["version"],
           "inputs": {"weight": weight, "reps": reps, "rir": rir, "load_basis": load_basis},
           "data_status": "not_applicable", "evidence_status": "research_only",
           "reason_codes": [], "domain": domain}
    w, r, reserve = finite(weight), finite(reps), finite(rir)
    if w is None or r is None or w <= 0 or r < 1 or int(r) != r:
        out["reason_codes"] = ["invalid_or_missing_input"]
        return out
    if measured_maximum:
        out["reason_codes"] = ["store_measured_1rm_separately"]
        return out
    if load_basis not in {"external_total_kg", "single_implement_kg", "dumbbells_total_kg"}:
        out["reason_codes"] = ["total_load_or_formula_scope_unknown"]
        return out
    if not domain or not {"min_reps", "max_reps", "scope_id"} <= domain.keys():
        out["reason_codes"] = ["formula_domain_not_declared"]
        return out
    if not domain["min_reps"] <= r <= domain["max_reps"]:
        out["reason_codes"] = ["repetitions_outside_declared_domain"]
        return out
    if FORMULAS[formula_id]["rir"] and (reserve is None or reserve < 0):
        out["reason_codes"] = ["rir_missing_or_interval_not_scalar"]
        return out
    if FORMULAS[formula_id]["rir"] and ("max_rir" not in domain or reserve > domain["max_rir"]):
        out["reason_codes"] = ["rir_outside_declared_domain"]
        return out
    if formula_id == "epley_n3_0.0333":
        value = w * (1 + 0.0333 * r)
    else:
        value = w * (1 + (r + (reserve if FORMULAS[formula_id]["rir"] else 0)) / 30)
    out.update(value=value, data_status="valid", reason_codes=["proxy_not_measured_strength"])
    return out
