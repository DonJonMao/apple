"""Versioned parameter, calibration and repeated-look registries in local SQLite."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .contracts import canonical_hash, instant

PARAMETER_KINDS = {
    "observation_definition", "unit_conversion", "user_plan", "equipment_constraint",
    "product_setting", "statistical_design", "literature_model", "personal_estimate",
}
VALIDATION_STATES = {"definition", "user_declared", "literature_replication_only",
                     "simulation_only", "pending_target_validation", "validated_for_scope"}


class ParameterRegistry:
    """Immutable versions. Supplying a new value requires a new explicit version."""

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS parameter_version (
                parameter_id TEXT NOT NULL, version TEXT NOT NULL, payload TEXT NOT NULL,
                sha256 TEXT NOT NULL, PRIMARY KEY(parameter_id,version));
            CREATE TABLE IF NOT EXISTS calibration_artifact (
                artifact_id TEXT PRIMARY KEY, payload TEXT NOT NULL, sha256 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS analysis_family (
                family_id TEXT PRIMARY KEY, alpha_total REAL NOT NULL, protocol TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS analysis_look (
                family_id TEXT NOT NULL, data_hash TEXT NOT NULL, look_number INTEGER NOT NULL,
                alpha_look REAL NOT NULL, metric_id TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(family_id,data_hash,metric_id), UNIQUE(family_id,look_number));
        """)

    def close(self) -> None:
        self.conn.close()

    def register(self, item: dict) -> dict:
        required = {"parameter_id", "version", "kind", "definition", "value_or_distribution",
                    "unit", "provenance", "scope", "validation_status"}
        if not required <= item.keys():
            raise ValueError("parameter_fields_missing")
        if item["kind"] not in PARAMETER_KINDS or item["validation_status"] not in VALIDATION_STATES:
            raise ValueError("parameter_identity_invalid")
        if not {"basis", "source_ids", "source_location"} <= item["provenance"].keys():
            raise ValueError("parameter_provenance_missing")
        if item["validation_status"] == "validated_for_scope" and not item.get("calibration_artifact_id"):
            raise ValueError("parameter_calibration_required")
        digest = canonical_hash(item)
        existing = self.conn.execute("SELECT sha256 FROM parameter_version WHERE parameter_id=? AND version=?",
                                     (item["parameter_id"], item["version"])).fetchone()
        if existing and existing[0] != digest:
            raise ValueError("parameter_version_is_immutable")
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO parameter_version VALUES(?,?,?,?)",
                              (item["parameter_id"], item["version"], json.dumps(item), digest))
        return item

    def get(self, parameter_id: str, version: str) -> Optional[dict]:
        row = self.conn.execute("SELECT payload FROM parameter_version WHERE parameter_id=? AND version=?",
                                (parameter_id, version)).fetchone()
        return json.loads(row[0]) if row else None

    def save_calibration(self, artifact: dict) -> dict:
        required = {"artifact_id", "model_version", "metric_ids", "scope", "data_kind",
                    "data_hash", "training_window", "validation_window", "holdout_window",
                    "error_model", "coverage", "width", "failure_scenarios", "threshold_selection",
                    "scope_status", "independent_holdout", "validation_protocol"}
        if not required <= artifact.keys():
            raise ValueError("calibration_fields_missing")
        if artifact["data_kind"] not in {"simulation", "real"}:
            raise ValueError("calibration_data_kind_invalid")
        if artifact["data_kind"] == "simulation" and artifact["scope_status"] != "simulation_only":
            raise ValueError("simulation_cannot_validate_people")
        if artifact["scope_status"] == "validated_for_scope":
            if not artifact["independent_holdout"] or not artifact.get("reviewer"):
                raise ValueError("real_validation_review_required")
            if not artifact.get("preregistered_targets") or not artifact.get("target_results"):
                raise ValueError("registered_targets_and_results_required")
            periods = [artifact.get(key) for key in ("training_window", "validation_window", "holdout_window")]
            if any(not isinstance(period, dict) or not {"start", "end"} <= period.keys() for period in periods):
                raise ValueError("real_calibration_split_boundaries_required")
            if any(instant(p["start"]) >= instant(p["end"]) for p in periods) or any(
                    instant(a["end"]) > instant(b["start"]) for a, b in zip(periods, periods[1:])):
                raise ValueError("real_calibration_splits_overlap")
            if not artifact.get("preregistered_at") or instant(artifact["preregistered_at"]) > instant(periods[1]["start"]):
                raise ValueError("targets_must_precede_validation")
            if not artifact.get("data_provenance") or not artifact.get("consent_scope"):
                raise ValueError("real_data_provenance_and_consent_required")
            for target, threshold in artifact["preregistered_targets"].items():
                attained = artifact["target_results"].get(target)
                if attained is None or not threshold["min"] <= attained <= threshold["max"]:
                    raise ValueError("validation_target_not_met")
        digest = canonical_hash(artifact)
        old = self.conn.execute("SELECT sha256 FROM calibration_artifact WHERE artifact_id=?",
                                (artifact["artifact_id"],)).fetchone()
        if old and old[0] != digest:
            raise ValueError("calibration_artifact_is_immutable")
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO calibration_artifact VALUES(?,?,?)",
                              (artifact["artifact_id"], json.dumps(artifact), digest))
        return artifact

    def calibration(self, artifact_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT payload FROM calibration_artifact WHERE artifact_id=?",
                                (artifact_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def register_family(self, family_id: str, alpha_total: float, protocol: dict) -> None:
        if not 0 < alpha_total < 1 or not protocol.get("declared_before"):
            raise ValueError("predeclared_error_budget_required")
        instant(protocol["declared_before"])
        old = self.conn.execute("SELECT alpha_total,protocol FROM analysis_family WHERE family_id=?",
                               (family_id,)).fetchone()
        if old and (old[0] != alpha_total or json.loads(old[1]) != protocol):
            raise ValueError("family_budget_and_protocol_are_immutable")
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO analysis_family VALUES(?,?,?)",
                              (family_id, alpha_total, json.dumps(protocol)))

    def allocate_look(self, family_id: str, data_hash: str, metric_id: str) -> dict:
        # BEGIN IMMEDIATE prevents two concurrent page requests spending one look twice.
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            old = self.conn.execute("SELECT * FROM analysis_look WHERE family_id=? AND data_hash=? AND metric_id=?",
                                    (family_id, data_hash, metric_id)).fetchone()
            if old:
                self.conn.commit()
                return dict(old)
            family = self.conn.execute("SELECT alpha_total FROM analysis_family WHERE family_id=?",
                                       (family_id,)).fetchone()
            if not family:
                raise ValueError("unregistered_analysis_family")
            k = self.conn.execute("SELECT COUNT(*) FROM analysis_look WHERE family_id=?", (family_id,)).fetchone()[0] + 1
            alpha = family[0] / (k * (k + 1))
            out = {"family_id": family_id, "data_hash": data_hash, "look_number": k,
                   "alpha_look": alpha, "metric_id": metric_id,
                   "created_at": datetime.now(timezone.utc).isoformat()}
            self.conn.execute("INSERT INTO analysis_look VALUES(:family_id,:data_hash,:look_number,:alpha_look,:metric_id,:created_at)", out)
            self.conn.commit()
            return out
        except Exception:
            self.conn.rollback()
            raise


def calibration_matches(artifact: Optional[dict], *, metric_id: str, scope: dict,
                        model_version: Optional[str] = None) -> bool:
    if not artifact or artifact.get("scope_status") != "validated_for_scope":
        return False
    if artifact.get("data_kind") != "real" or not artifact.get("independent_holdout"):
        return False
    if metric_id not in artifact.get("metric_ids", []):
        return False
    if model_version and artifact.get("model_version") != model_version:
        return False
    registered = artifact.get("scope", {})
    return bool(scope) and all(k in registered and registered[k] == v for k, v in scope.items())


def hall_chow_replication_parameters() -> list[dict[str, Any]]:
    return [{"parameter_id": "hall_chow_2011_replication." + name, "version": "1",
             "kind": "literature_model", "definition": definition,
             "value_or_distribution": value, "unit": unit,
             "provenance": {"basis": "literature_replication_only", "source_ids": ["E2"],
                            "source_location": "main-text average parameter example; Appendix A3/A4"},
             "scope": {"model": "hall_chow_2011_replication", "use": "research_only",
                       "population": "publication weight-management replication, not personal calibration"},
             "validation_status": "literature_replication_only"}
            for name, value, unit, definition in [
                ("rho", 9100, "kcal/kg", "Effective dynamical coefficient; NOT tissue energy density"),
                ("epsilon", 22, "kcal/(kg*day)", "Whole-model mass-dependent expenditure coefficient")]]


def builtin_parameters() -> list[dict[str, Any]]:
    """Registered meanings of calculation constants, not a physiological recipe."""
    rows = [
        ("international_lb_to_kg", "unit_conversion", 0.45359237, "kg/lb", "exact international avoirdupois pound definition", [], "definition"),
        ("gaussian_MAD_consistency", "statistical_design", 1.4826, "dimensionless", "normal-distribution consistency approximation; not a physiological cutoff", [], "definition"),
        ("epley_n3_coefficient", "literature_model", 0.0333, "1/repetition", "N3 Table 1 formula reproduction; limited original study scope", ["N3"], "literature_replication_only"),
        ("epley_r_over_30_divisor", "observation_definition", 30, "repetitions", "explicit algebraic variant, distinct formula identity", [], "definition"),
        ("research_default_alpha", "statistical_design", 0.05, "probability", "declared reference simulation error tolerance, not a training threshold", [], "simulation_only"),
    ]
    return [{"parameter_id": identity, "version": "1", "kind": kind,
             "definition": meaning, "value_or_distribution": value, "unit": unit,
             "provenance": {"basis": meaning, "source_ids": sources,
                            "source_location": "Table 1" if identity == "epley_n3_coefficient" else None},
             "scope": {"purpose": "computation_identity_or_research_design", "personal_prescription": False},
             "validation_status": status} for identity, kind, value, unit, meaning, sources, status in rows] + hall_chow_replication_parameters()
