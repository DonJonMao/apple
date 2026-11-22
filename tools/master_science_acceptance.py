"""Reproduce the field inventory and calendar-gap model calibration on synthetic data."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from random import Random
from statistics import mean, median
from tempfile import TemporaryDirectory

from healthzip.analytics.body_metrics import METRIC_CATALOG, analyze_body_metric, analyze_questions
from healthzip.db.repository import Repository
from healthzip.science.calendar_trend import VERSION, fit_daily
from tests.master_science_fixture import CUTOFF, RANGE_START, create_master_science_fixture


def simulate(seed, n_runs, slope, rho, missing, *, relation=False):
    rng = Random(seed)
    estimates = []
    covered = positive = 0
    reasons = Counter()
    widths = []
    rhos = []
    true = 2.5 if relation else slope
    for _ in range(n_runs):
        points = []
        error = rng.gauss(0, 1)
        for i in range(120):
            error = rho * error + (1 - rho**2) ** 0.5 * rng.gauss(0, 1)
            exposure = 7 + rng.uniform(-0.7, 0.7)
            if rng.random() < missing:
                continue
            value = 40 + slope * i + error + (2.5 * (exposure - 7) if relation else 0.0)
            points.append(
                {
                    "date": (date(2026, 4, 1) + timedelta(days=i)).isoformat(),
                    "value": value,
                    "sleep_hours": exposure,
                }
            )
        result = fit_daily(points, "unit", factor="sleep_hours" if relation else None)
        if result["status"] != "estimated":
            reasons[result["reason"]] += 1
            continue
        v = result["coefficient"]
        lo, hi = result["interval"]
        estimates.append(v)
        covered += lo <= true <= hi
        positive += lo > 0 or hi < 0
        widths.append(hi - lo)
        rhos.append(result["rho"])
    n = len(estimates)
    return {
        "slope_truth": slope,
        "factor_truth": 2.5 if relation else None,
        "rho_truth": rho,
        "missing_probability": missing,
        "attempted": n_runs,
        "estimated": n,
        "descriptive_fallback": dict(reasons),
        "accepted_model_bias": mean(estimates) - true if n else None,
        "accepted_model_rmse": mean((v - true) ** 2 for v in estimates) ** 0.5 if n else None,
        "mean_estimated_daily_rho": mean(rhos) if n else None,
        "coverage_95pct_on_estimated": covered / n if n else None,
        "intervals_covering_truth": covered,
        "intervals_excluding_zero": positive,
        "false_positives_all_trials": positive if true == 0 else None,
        "false_positive_rate_all_trials": positive / n_runs if true == 0 else None,
        "median_interval_width": median(widths) if n else None,
    }


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("artifacts/master_redesign/science"))
    parser.add_argument("--replicates", type=int, default=200)
    parser.add_argument(
        "--seed",
        type=int,
        default=74031,
        help="Base random seed; use a new seed for an independent simulation.",
    )
    parser.add_argument("--simulation-only", action="store_true")
    parser.add_argument("--census-only", action="store_true", help="Regenerate field/question receipts without rerunning unchanged simulations.")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if not args.simulation_only:
        with TemporaryDirectory() as temp:
            db = Path(temp) / "synthetic.sqlite3"
            receipt = create_master_science_fixture(db)
            repo = Repository(db)
            kw = dict(window_start=RANGE_START, window_end=CUTOFF, cutoff_time=CUTOFF)
            rows = {}
            for k, d in METRIC_CATALOG.items():
                m = analyze_body_metric(repo, k, with_model=True, **kw)
                rows[k] = {
                    "title": d["title"],
                    "theme": d["theme"],
                    "question": d["workflow"],
                    "unit": m["unit"],
                    "statistic": d["kind"],
                    "visible_rows": m["total_n"],
                    "used_rows": m["valid_n"],
                    "status": m["availability"],
                    "capabilities": m["capabilities"],
                    "scope": kw,
                    "streams": [
                        {
                            "source": s["source"],
                            "count": len(s["points"]),
                            "window_days": s["current"]["window_days"],
                            "recorded_days": s["current"]["recorded_days"],
                            "period_value": s["current"]["value"],
                            "recorded_total": s["current"].get("recorded_total"),
                            "absolute_change": s["absolute_change"],
                            "first_observed": s["points"][0]["observed_at"],
                            "last_observed": s["points"][-1]["observed_at"],
                            "model_status": s["trend"]["status"],
                            "fact_id": s["fact_id"],
                        }
                        for s in m["value"]["streams"]
                        if s["points"]
                    ],
                }
            write(args.out / "field-census.json", {"fixture": receipt, "fields": rows})
            qs = analyze_questions(repo, **kw)
            views = []
            for q in qs:
                a = q.get("association") or {}
                views.append(
                    {
                        **{
                            k: q[k]
                            for k in (
                                "id",
                                "title",
                                "observation",
                                "steps",
                                "support",
                                "counterevidence",
                                "limitations",
                                "analysis_version",
                            )
                        },
                        "row_types": dict(Counter(row["type"] for row in q["rows"])),
                        "association_groups": [
                            {k: v for k, v in g.items() if k != "pairs"}
                            for g in a.get("groups", [])
                        ],
                        "matched_examples": next(
                            (
                                g["pairs"][:2]
                                for g in a.get("groups", [])
                                if g["status"] == "estimated"
                            ),
                            [],
                        ),
                        "unmatched_dates": len(a.get("unmatched", [])),
                    }
                )
            write(args.out / "question-census.json", {"fixture": receipt, "questions": views})
            repo.close()
    if args.census_only:
        return
    configs = [
        (0.0, 0.0, 0.0),
        (0.03, 0.0, 0.0),
        (0.0, 0.65, 0.0),
        (0.03, 0.65, 0.0),
        (0.0, 0.65, 0.30),
        (0.03, 0.65, 0.30),
        (0.0, -0.4, 0.30),
    ]
    calibration = [
        simulate(args.seed + i, args.replicates, *config) for i, config in enumerate(configs)
    ]
    calibration.append(simulate(args.seed + 1000, args.replicates, 0.02, 0.60, 0.3, relation=True))
    name = "simulation-independent.json" if args.simulation_only else "simulation.json"
    write(
        args.out / name,
        {
            "seed": args.seed,
            "scope": "simulation_only",
            "algorithm": VERSION,
            "days_per_trial": 120,
            "design": "固定种子；平稳高斯 AR(1)，独立随机缺日；先生成完整日历过程再移除观测。协变量在共同时间段内变动。区间用受限剖面似然在可能的 rho 内对斜率或预设因素系数取并集，以固定 rho 时 t 区间为基准。",
            "trials": calibration,
            "boundaries": [
                "留存记录非随机时另报告敏感性。",
                "结果不能授予设备准确性、个人临床重要变化或因果权限。",
            ],
        },
    )


if __name__ == "__main__":
    main()
