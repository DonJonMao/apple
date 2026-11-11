"""Reproducible simulation/calibration commands; never imply human validity."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .contracts import canonical_hash
from .energy import hall_chow
from .prediction import forward_evaluate
from .registry import ParameterRegistry, builtin_parameters
from .statistics import linear_trend


def simulate_trends(*, seed: int = 1301, repetitions: int = 300) -> dict:
    import numpy as np

    rng = np.random.default_rng(seed)
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = np.array([0, 3, 7, 12, 18, 25, 31, 39, 46, 55, 67, 82], dtype=float)
    scenarios = {}
    for name in ("iid_gaussian", "serial_correlation", "heteroskedastic", "rounded_count", "zero_residual_unknown_error"):
        covered, widths, undefined = 0, [], 0
        for iteration in range(repetitions):
            noise = rng.normal(size=len(times))
            if name == "serial_correlation":
                for i in range(1, len(noise)):
                    noise[i] = 0.8 * noise[i - 1] + math.sqrt(1 - 0.8 ** 2) * noise[i]
            elif name == "heteroskedastic":
                noise *= np.linspace(0.4, 3, len(times))
            elif name == "zero_residual_unknown_error":
                noise[:] = 0
            y = 8 + 0.025 * times + noise
            if name == "rounded_count":
                y = np.round(y)
            records = [{"session_id": f"sim-{iteration}-{i}", "event_end": (origin + timedelta(days=float(t))).isoformat(),
                        "value": float(v)} for i, (t, v) in enumerate(zip(times, y))]
            output = linear_trend(records, alpha=0.05)
            interval = output["interval"]
            if interval is None:
                undefined += 1
                continue
            covered += interval["lower"] <= 0.025 * (times[-1] - times[0]) <= interval["upper"]
            widths.append(interval["upper"] - interval["lower"])
        defined = len(widths)
        scenarios[name] = {"repetitions": repetitions, "intervals_defined": defined, "undefined": undefined,
                           "covered": int(covered), "empirical_coverage": covered / defined if defined else None,
                           "mean_width": sum(widths) / defined if defined else None,
                           "nominal_coverage": 0.95, "scope_status": "simulation_only",
                           "assumptions_satisfied_by_generator": name == "iid_gaussian"}
    return {"seed": seed, "repetitions": repetitions, "model_version": "ols_true_time_student_t_v1",
            "scenarios": scenarios, "release_decision": "no_real_scope_validation",
            "failure_return_verified": scenarios["zero_residual_unknown_error"]["undefined"] == repetitions}


def simulate_energy(*, seed: int = 1302, repetitions: int = 2000) -> dict:
    import numpy as np

    rng = np.random.default_rng(seed)
    times = np.array([0, 1, 4, 9, 14, 20, 27, 40], dtype=float)
    weights = 90 - 0.05 * times
    # Same-sample baseline, explicitly retain correlation with first weight.
    covariance = 0.09 * np.power(0.6, np.abs(np.arange(len(times))[:, None] - np.arange(len(times))[None, :]))
    baseline = {"baseline_id": "synthetic-equilibrium", "equilibrium_confirmed": True,
                "W0": 90.0, "same_sample_baseline": True}
    parameters = {"parameter_set_id": "hall_chow_2011_replication-v1", "model": "hall_chow_2011_replication",
                  "rho": 9100, "epsilon": 22, "provenance": "E2 replication, not a personal calibration"}
    model = hall_chow(times.tolist(), weights.tolist(), baseline=baseline, parameters=parameters,
                      covariance=covariance, baseline_variance=covariance[0, 0], baseline_covariance=covariance[:, 0])
    draws = rng.multivariate_normal(weights, covariance, size=repetitions)
    h = np.array(model["observation_weights"])
    simulated = draws @ h - parameters["epsilon"] * draws[:, 0]
    sd = math.sqrt(model["variance"])
    half_width = 1.959963984540054 * sd
    truth = model["delta_intake_kcal_day"]
    return {"seed": seed, "repetitions": repetitions, "scope_status": "simulation_only",
            "times_days": times.tolist(), "true_delta_intake": truth,
            "analytic_variance": model["variance"], "empirical_variance": float(np.var(simulated, ddof=1)),
            "empirical_coverage": float(np.mean(np.abs(simulated - truth) <= half_width)),
            "nominal_coverage": 0.95, "interval_width": 2 * half_width,
            "baseline_covariance_preserved": True, "model": model,
            "limitation": "Known Gaussian generator covariance is not a user's physiological error model"}


def prediction_fixture(*, seed: int, users: int = 4, exposures: int = 45, state_effect: float = 0.0) -> list[dict]:
    import numpy as np

    rng = np.random.default_rng(seed)
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for user in range(users):
        previous_state = 7.5
        previous_reps = 10.0
        for index in range(exposures):
            start = origin + timedelta(days=index * 3, hours=user)
            state = float(rng.normal(7.5, 0.6))
            reps = max(1.0, previous_reps + state_effect * (state - previous_state) + float(rng.normal(0, 0.6)))
            rows.append({"id": f"u{user}-s{index}", "user_id": f"u{user}", "session_id": f"u{user}-session-{index}",
                         "exercise_id": "synthetic_press", "definition_version": 1, "equipment_instance_id": "synthetic_bar",
                         "load_basis": "external_total_kg", "load_basis_confirmed": True, "load_value": 60.0, "load_unit": "kg",
                         "measurement_mode": "repetitions", "side": "bilateral", "repetition_semantics": "both_together",
                         "rom_protocol": "full_declared", "settings": {}, "settings_confirmed": True,
                         "reference_protocol": "first_work_set", "effort_protocol": "target_rir_2",
                         "reps": reps, "session_started_at": start.isoformat(),
                         "event_end": (start + timedelta(hours=1)).isoformat(),
                         "available_at": (start + timedelta(hours=1, minutes=1)).isoformat(),
                         "features": {"sleep_hours": {"value": state, "event_end": (start - timedelta(hours=2)).isoformat(),
                                                     "available_at": (start - timedelta(hours=1)).isoformat()}}})
            previous_reps, previous_state = reps, state
    return rows


def simulate_predictions(*, seed: int = 1303) -> dict:
    split = {"registered_at": "2025-12-01T00:00:00+00:00", "train_end": "2026-03-01T00:00:00+00:00",
             "validation_end": "2026-04-01T00:00:00+00:00", "test_end": "2026-06-01T00:00:00+00:00",
             "heldout_users": ["u3"]}
    return {"seed": seed, "scope_status": "simulation_only", "scenarios": {
        "no_incremental_state_signal": forward_evaluate(prediction_fixture(seed=seed, state_effect=0), split=split, feature="sleep_hours"),
        "synthetic_state_signal": forward_evaluate(prediction_fixture(seed=seed + 1, state_effect=1.8), split=split, feature="sleep_hours"),
    }, "limitation": "Simulation predictive association does not support changing sleep, calories or personal load"}


def calibrate(output_dir: str, *, seed: int = 1300, repetitions: int = 300) -> dict:
    if repetitions < 1:
        raise ValueError("positive_simulation_repetitions_required")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    trend = simulate_trends(seed=seed + 1, repetitions=repetitions)
    energy = simulate_energy(seed=seed + 2, repetitions=max(repetitions, 1000))
    prediction = simulate_predictions(seed=seed + 3)
    outputs = {"trend": trend, "energy": energy, "prediction": prediction}
    registry = ParameterRegistry(str(directory / "science_registry.sqlite3"))
    for parameter in builtin_parameters():
        registry.register(parameter)
    artifacts = []
    for name, payload in outputs.items():
        path = directory / f"{name}_simulation.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        scope = {"population": "synthetic_generator", "model": name, "seed": seed}
        digest = canonical_hash(payload)
        artifact = {
            "artifact_id": f"simulation-{name}-{digest[:16]}", "model_version": payload.get("model_version", name + "-research-v1"),
            "metric_ids": {"trend": ["STR-19", "STR-20", "STR-22"], "energy": ["ENERGY-DELTA-INTAKE"],
                           "prediction": ["PRED-B0", "PRED-B1", "PRED-ERROR-GAIN", "PRED-INTERVAL"]}[name],
            "scope": scope, "data_kind": "simulation", "data_hash": digest,
            "training_window": None, "validation_window": None, "holdout_window": None,
            "error_model": "declared simulation generator; see linked payload",
            "coverage": energy["empirical_coverage"] if name == "energy" else trend["scenarios"] if name == "trend" else None,
            "width": energy["interval_width"] if name == "energy" else None,
            "failure_scenarios": ["unknown individual noise", "nonidentifiable baseline", "future unavailable feature", "source protocol drift"],
            "threshold_selection": "simulation design fixed before execution; no human threshold fitted",
            "scope_status": "simulation_only", "independent_holdout": False,
            "validation_protocol": "reproducible generator tests; not real-world validation",
            "payload_path": str(path), "missing_real_data": ["consented longitudinal individual reference sessions",
                "timestamped pre-session features and revisions", "preregistered independent temporal and user holdouts",
                "independent measurement-error and energy calibration"]}
        registry.save_calibration(artifact)
        artifacts.append(artifact)
    registry.close()
    manifest = {"scope_status": "simulation_only", "scientific_validation": "pending_real_data",
                "seed": seed, "artifacts": artifacts, "commands": [f"python -m healthzip.science calibrate --output {output_dir} --seed {seed} --repetitions {repetitions}"]}
    (directory / "calibration_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
