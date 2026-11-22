"""A pre-specified conditional mean model for one comparable daily stream.

Integer calendar gaps determine the AR(1) transitions and innovation variance.
The model does not impute missing observations. Estimated intervals are
conditional, approximate and require the reported diagnostics.
"""

from datetime import date

VERSION = "calendar-gap-ar1-reml-profile-1.1"


def fit_daily(points, unit, *, factor=None):
    base = {
        "status": "descriptive_only",
        "version": VERSION,
        "slope_per_day": None,
        "interval": None,
        "estimated_change": None,
        "unit": unit,
        "factor": factor,
    }
    try:
        import numpy as np
        from scipy.optimize import minimize_scalar
        from scipy.stats import chi2, spearmanr, t
    except ImportError:
        return {**base, "reason": "当前安装缺少可选研究计算组件。"}
    ordered = sorted(points, key=lambda p: p["date"])
    n, k = len(ordered), 3 if factor else 2
    if n < 2 * k + 4:
        return {**base, "reason": "可比日期过少，无法同时核查残差、影响度与区间。"}
    days = np.array([date.fromisoformat(p["date"]).toordinal() for p in ordered], dtype=int)
    gaps = np.diff(days)
    if np.any(gaps <= 0):
        return {**base, "reason": "每个可比日期应有唯一日代表值。"}
    if not np.any(gaps == 1):
        return {**base, "reason": "没有相邻日期，无法识别一日误差相关。"}
    d = days - days[0]
    X = np.column_stack([np.ones(n), d - d.mean()])
    y = np.asarray([p["value"] for p in ordered], dtype=float)
    if not np.all(np.isfinite(y)) or np.ptp(y) == 0:
        return {**base, "reason": "观测没有可估计的残差变化。"}
    if factor:
        try:
            f = np.asarray([p.get(factor) for p in ordered], dtype=float)
        except (TypeError, ValueError):
            return {**base, "reason": "因素值缺失或非有限数值。"}
        if not np.all(np.isfinite(f)):
            return {**base, "reason": "因素值缺失或非有限数值。"}
        # A near-constant exposure or exposure segregated by calendar phase
        # cannot identify a within-person contrast at overlapping conditions.
        a, b = np.array_split(f, 2)
        if min(max(a), max(b)) <= max(min(a), min(b)):
            return {**base, "reason": "前后时段因素水平没有重叠，无法区分因素与时间。"}
        # Factor in hours here; imported sleep durations have minute resolution.
        if factor == "sleep_hours" and np.ptp(f) < 1 / 60:
            return {**base, "reason": "因素变幅小于输入的分钟分辨率。"}
        X = np.column_stack([X, f - f.mean()])
    if np.linalg.matrix_rank(X) != k or np.linalg.cond(X / np.linalg.norm(X, axis=0)) > 100:
        return {**base, "reason": "时间与因素高度重合，无法稳定分解。"}

    def transformed(rho):
        a = rho**gaps
        sd = np.sqrt(1 - a * a)
        xx = np.vstack([X[0], (X[1:] - a[:, None] * X[:-1]) / sd[:, None]])
        yy = np.r_[y[0], (y[1:] - a * y[:-1]) / sd]
        beta = np.linalg.lstsq(xx, yy, rcond=None)[0]
        eps = yy - xx @ beta
        rss = eps @ eps
        gram = xx.T @ xx
        score = (
            (n - k) * np.log(max(rss / (n - k), 1e-30))
            + 2 * np.log(sd).sum()
            + np.linalg.slogdet(gram)[1]
        )
        return score, xx, eps, beta, gram

    # Search both signs: even gaps create a non-monotone likelihood and can
    # conceal negative serial dependence. Optimize locally from a coarse grid.
    grid = np.linspace(-0.99, 0.99, 13)
    best = min(range(len(grid)), key=lambda i: transformed(grid[i])[0])
    opt = minimize_scalar(
        lambda r: transformed(r)[0],
        bounds=(grid[max(0, best - 1)], grid[min(best + 1, len(grid) - 1)]),
        method="bounded",
    )
    rho = float(opt.x)
    if not opt.success or not np.isfinite(opt.fun):
        return {**base, "reason": "相关参数优化未收敛。"}
    best_score, xx, eps, beta, gram = transformed(rho)
    rss = float(eps @ eps)
    if rss <= np.finfo(float).eps * max(1, float(np.var(y))) * n or abs(rho) > 0.975:
        return {**base, "reason": "残差方差或相关参数位于估计边界。", "rho": rho}
    inv = np.linalg.inv(gram)
    se = np.sqrt(np.diag(inv) * rss / (n - k))
    target = k - 1
    half_width = float(t.ppf(0.975, df=n - k - 1) * se[target])
    # Profile uncertainty in the estimated daily correlation; a plug-in t
    # interval treats rho as known and can under-cover correlated trajectories.
    # A fixed-rho offset b gives RSS(b) = RSS_hat + (b-beta_hat)^2/Ginv[j,j].
    # The admissible beta range is the union over rho at the profile cutoff.
    threshold = (n - k) * np.log1p(t.ppf(0.975, df=n - k - 1) ** 2 / (n - k))

    def endpoints(r):
        score, _, err, coeffs, g = transformed(r)
        remaining = threshold - (score - best_score)
        if remaining < 0:
            return None
        width = np.sqrt(
            np.expm1(remaining / (n - k)) * (err @ err) * np.linalg.inv(g)[target, target]
        )
        return coeffs[target] - width, coeffs[target] + width

    tested = sorted({rho, *np.linspace(-0.99, 0.99, 33)})
    profiles = [(r, endpoints(r)) for r in tested]
    limits = []
    for j, side in enumerate((1, -1)):
        index = min(
            (i for i in range(len(tested)) if profiles[i][1] is not None),
            key=lambda i: side * profiles[i][1][j],
        )

        def objective(r):
            ends = endpoints(r)
            return side * ends[j] if ends is not None else 1.0e100

        opt_endpoint = minimize_scalar(
            objective,
            bounds=(tested[max(0, index - 1)], tested[min(index + 1, len(tested) - 1)]),
            method="bounded",
        )
        limits.append(float(side * min(opt_endpoint.fun, objective(tested[index]))))

    leverage = np.einsum("ij,jk,ik->i", xx, inv, xx)
    deletion = (xx @ inv[:, target]) * eps / np.maximum(1 - leverage, 1e-9)
    diagnostics = {
        "records": n,
        "elapsed_days": int(d[-1]),
        "max_gap_days": int(max(gaps)),
        "adjacent_pairs": int(sum(gaps == 1)),
        "rho": rho,
        "example_gap_transitions": {str(int(g)): float(rho**g) for g in sorted(set(gaps))[:10]},
        "max_leave_one_innovation_change": float(max(abs(deletion))),
        "max_leverage": float(max(leverage)),
        "residual_sd": float(np.sqrt(rss / (n - k))),
        "scope": [ordered[0]["date"], ordered[-1]["date"]],
    }

    # Curvature / phase shift, expanding residual spread and remaining serial
    # structure are engineering diagnostics, not clinical change thresholds.
    def whiten(z):
        a = rho**gaps
        return np.r_[z[0], (z[1:] - a * z[:-1]) / np.sqrt(1 - a * a)]

    def lack_of_fit(z):
        zz = whiten(z)
        zz -= xx @ np.linalg.lstsq(xx, zz, rcond=None)[0]
        denom = zz @ zz
        if denom < 1e-12:
            return 0.0
        return float((eps @ zz) ** 2 / (denom * rss))

    curve = lack_of_fit((d - d.mean()) ** 2)
    shift = lack_of_fit((d >= np.median(d)).astype(float))
    residual_corr = float(np.corrcoef(eps[:-1], eps[1:])[0, 1])
    hetero = float(spearmanr(abs(eps), d).pvalue)
    diagnostics.update(
        quadratic_residual_fraction=curve,
        midperiod_step_residual_fraction=shift,
        residual_lag_order_corr=residual_corr,
        spread_trend_p=hetero,
    )
    reasons = []
    if max(curve, shift) > 0.30 and n * max(curve, shift) > 9:
        reasons.append("轨迹存在明显弯曲或前后阶段差")
    if hetero < 0.005:
        reasons.append("残差波动随时间变化")
    if n * residual_corr**2 > chi2.ppf(0.995, 1):
        reasons.append("白化后的残差仍有时间相关")
    if max(abs(deletion)) > half_width or max(leverage) > 0.80:
        reasons.append("个别观测对估计影响过大")
    if reasons:
        return {**base, "reason": "；".join(reasons), "diagnostics": diagnostics}
    effect = float(beta[target])
    return {
        **base,
        "status": "estimated",
        "reason": None,
        "rho": rho,
        "n": n,
        "slope_per_day": float(beta[1]),
        "coefficient": effect,
        "effect_unit": f"{unit}/小时睡眠" if factor else f"{unit}/天",
        "estimated_change": float(beta[1] * d[-1]),
        "interval": limits,
        "interval_kind": "approximate_95pct_profiled_correlation_conditional_mean_coefficient",
        "range": diagnostics["scope"],
        "diagnostics": diagnostics,
        "fitted_points": [
            {"date": ordered[i]["date"], "value": float(beta[0] + beta[1] * (d[i] - d.mean()))}
            for i in (0, n - 1)
        ],
        "residual_assumptions": "分段内线性条件均值、平稳一阶日误差与近似同方差。",
    }
