"""Group comparison statistics with no compiled dependencies.

The module implements the tests itself (Welch t, paired t, Mann–Whitney U,
Cohen's d / Hedges' g, bootstrap CI) so the package installs with numpy and
pandas alone. The definitions follow the standard formulas and are checked
against SciPy in the test suite when SciPy is available.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, Sequence

import numpy as np
import pandas as pd

# --------------------------------------------------------------- distributions


def _betacf(a: float, b: float, x: float, max_iter: int = 300, eps: float = 3e-14) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-300:
        d = 1e-300
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(log_beta + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_sf(t: float, df: float) -> float:
    """Upper tail probability P(T > t) for Student's t with ``df``."""
    if df <= 0 or not math.isfinite(df):
        return float("nan")
    x = df / (df + t * t)
    half = 0.5 * betainc(df / 2.0, 0.5, x)
    return half if t >= 0 else 1.0 - half


def t_cdf(t: float, df: float) -> float:
    return 1.0 - t_sf(t, df)


def t_ppf(q: float, df: float) -> float:
    """Inverse Student's t CDF by bisection (stable and dependency-free)."""
    if not 0.0 < q < 1.0:
        raise ValueError("q must be in (0, 1)")
    low, high = -1e3, 1e3
    for _ in range(200):
        mid = (low + high) / 2.0
        if t_cdf(mid, df) < q:
            low = mid
        else:
            high = mid
        if high - low < 1e-10:
            break
    return (low + high) / 2.0


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


# ------------------------------------------------------------------- helpers


def _as_array(values: Iterable[float]) -> np.ndarray:
    arr = np.asarray([v for v in values if v is not None], dtype=float)
    return arr[np.isfinite(arr)]


def describe(values: Iterable[float]) -> Dict[str, float]:
    arr = _as_array(values)
    if arr.size == 0:
        return {"n": 0}
    return {
        "n": int(arr.size),
        "mean": float(arr.mean()),
        "sd": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
        "median": float(np.median(arr)),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "p25": float(np.percentile(arr, 25)),
        "p75": float(np.percentile(arr, 75)),
    }


def cohens_d(group_a: Iterable[float], group_b: Iterable[float]) -> float:
    """Standardized mean difference (a − b), pooled SD with n−1 weights."""
    a, b = _as_array(group_a), _as_array(group_b)
    n1, n2 = a.size, b.size
    if n1 < 2 or n2 < 2:
        return float("nan")
    pooled = math.sqrt(((n1 - 1) * a.var(ddof=1) + (n2 - 1) * b.var(ddof=1)) / (n1 + n2 - 2))
    if pooled == 0:
        return float("nan")
    return float((a.mean() - b.mean()) / pooled)


def hedges_g(group_a: Iterable[float], group_b: Iterable[float]) -> float:
    """Small-sample corrected Cohen's d."""
    d = cohens_d(group_a, group_b)
    a, b = _as_array(group_a), _as_array(group_b)
    n = a.size + b.size
    if not math.isfinite(d) or n < 4:
        return float("nan")
    correction = 1.0 - 3.0 / (4.0 * n - 9.0)
    return float(d * correction)


def effect_size_label(d: float | None) -> str:
    if d is None or not isinstance(d, (int, float)) or not math.isfinite(d):
        return "—"
    magnitude = abs(d)
    if magnitude < 0.2:
        return "negligible"
    if magnitude < 0.5:
        return "small"
    if magnitude < 0.8:
        return "medium"
    return "large"


@dataclass
class TestResult:
    test: str
    statistic: float
    df: float
    p_value: float
    n_a: int
    n_b: int
    mean_a: float
    mean_b: float
    diff: float
    pct_change: float
    d: float
    g: float
    effect: str
    ci_low: float
    ci_high: float

    def to_dict(self) -> Dict[str, float | str]:
        return {
            "test": self.test,
            "statistic": self.statistic,
            "df": self.df,
            "p_value": self.p_value,
            "n_a": self.n_a,
            "n_b": self.n_b,
            "mean_a": self.mean_a,
            "mean_b": self.mean_b,
            "diff": self.diff,
            "pct_change": self.pct_change,
            "cohens_d": self.d,
            "hedges_g": self.g,
            "effect": self.effect,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "significant": bool(self.p_value < 0.05) if math.isfinite(self.p_value) else False,
        }


def _empty_result(test: str) -> TestResult:
    nan = float("nan")
    return TestResult(test, nan, nan, nan, 0, 0, nan, nan, nan, nan, nan, nan, "—", nan, nan)


def welch_ttest(group_a: Iterable[float], group_b: Iterable[float], alpha: float = 0.05) -> TestResult:
    """Welch's unequal-variance t-test with a confidence interval for a − b."""
    a, b = _as_array(group_a), _as_array(group_b)
    if a.size < 2 or b.size < 2:
        return _empty_result("welch_t")
    v1, v2 = a.var(ddof=1), b.var(ddof=1)
    se = math.sqrt(v1 / a.size + v2 / b.size)
    diff = float(a.mean() - b.mean())
    if se == 0:
        return _empty_result("welch_t")
    t = diff / se
    numerator = (v1 / a.size + v2 / b.size) ** 2
    denominator = (v1 / a.size) ** 2 / (a.size - 1) + (v2 / b.size) ** 2 / (b.size - 1)
    df = numerator / denominator if denominator > 0 else float(a.size + b.size - 2)
    p = 2.0 * t_sf(abs(t), df)
    crit = t_ppf(1.0 - alpha / 2.0, df)
    d = cohens_d(a, b)
    return TestResult(
        test="welch_t",
        statistic=float(t),
        df=float(df),
        p_value=float(min(max(p, 0.0), 1.0)),
        n_a=int(a.size),
        n_b=int(b.size),
        mean_a=float(a.mean()),
        mean_b=float(b.mean()),
        diff=diff,
        pct_change=float(diff / b.mean()) if b.mean() else float("nan"),
        d=d,
        g=hedges_g(a, b),
        effect=effect_size_label(d),
        ci_low=float(diff - crit * se),
        ci_high=float(diff + crit * se),
    )


def paired_ttest(group_a: Iterable[float], group_b: Iterable[float], alpha: float = 0.05) -> TestResult:
    """Paired t-test for matched observations (same participants, two conditions)."""
    a, b = np.asarray(list(group_a), dtype=float), np.asarray(list(group_b), dtype=float)
    if a.size != b.size or a.size < 2:
        return _empty_result("paired_t")
    valid = np.isfinite(a) & np.isfinite(b)
    a, b = a[valid], b[valid]
    if a.size < 2:
        return _empty_result("paired_t")
    diff = a - b
    mean_diff = float(diff.mean())
    sd_diff = float(diff.std(ddof=1))
    if sd_diff == 0:
        return _empty_result("paired_t")
    se = sd_diff / math.sqrt(a.size)
    t = mean_diff / se
    df = a.size - 1
    p = 2.0 * t_sf(abs(t), df)
    crit = t_ppf(1.0 - alpha / 2.0, df)
    d = cohens_d(a, b)
    return TestResult(
        test="paired_t",
        statistic=float(t),
        df=float(df),
        p_value=float(min(max(p, 0.0), 1.0)),
        n_a=int(a.size),
        n_b=int(b.size),
        mean_a=float(a.mean()),
        mean_b=float(b.mean()),
        diff=mean_diff,
        pct_change=float(mean_diff / b.mean()) if b.mean() else float("nan"),
        d=d,
        g=hedges_g(a, b),
        effect=effect_size_label(d),
        ci_low=float(mean_diff - crit * se),
        ci_high=float(mean_diff + crit * se),
    )


def mann_whitney_u(group_a: Iterable[float], group_b: Iterable[float]) -> tuple[float, float]:
    """Two-sided Mann–Whitney U with tie-corrected normal approximation."""
    a, b = _as_array(group_a), _as_array(group_b)
    n1, n2 = a.size, b.size
    if n1 == 0 or n2 == 0:
        return float("nan"), float("nan")
    combined = np.concatenate([a, b])
    order = combined.argsort(kind="mergesort")
    ranks = np.empty(combined.size, dtype=float)
    ranks[order] = np.arange(1, combined.size + 1, dtype=float)
    # average ranks for ties
    sorted_values = combined[order]
    i = 0
    tie_term = 0.0
    while i < sorted_values.size:
        j = i
        while j + 1 < sorted_values.size and sorted_values[j + 1] == sorted_values[i]:
            j += 1
        if j > i:
            average = (i + j + 2) / 2.0
            ranks[order[i : j + 1]] = average
            size = j - i + 1
            tie_term += size**3 - size
        i = j + 1
    rank_sum_a = float(ranks[:n1].sum())
    u1 = rank_sum_a - n1 * (n1 + 1) / 2.0
    u = min(u1, n1 * n2 - u1)
    n = n1 + n2
    sigma = math.sqrt((n1 * n2 / 12.0) * ((n + 1) - tie_term / (n * (n - 1)))) if n > 1 else 0.0
    if sigma == 0:
        return float(u), float("nan")
    z = (u - n1 * n2 / 2.0 + 0.5) / sigma
    p = 2.0 * (1.0 - normal_cdf(abs(z)))
    return float(u), float(min(max(p, 0.0), 1.0))


def bootstrap_mean_ci(
    values: Iterable[float],
    *,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 5020,
) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean (deterministic seed)."""
    arr = _as_array(values)
    if arr.size < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    draws = rng.choice(arr, size=(n_boot, arr.size), replace=True).mean(axis=1)
    return float(np.percentile(draws, 100 * alpha / 2)), float(np.percentile(draws, 100 * (1 - alpha / 2)))


def compare(
    group_a: Iterable[float],
    group_b: Iterable[float],
    *,
    paired: bool = False,
    alpha: float = 0.05,
) -> Dict[str, float | str]:
    """Full comparison bundle for one metric (Welch/paired t + U + effect size)."""
    primary = paired_ttest(group_a, group_b, alpha) if paired else welch_ttest(group_a, group_b, alpha)
    u, u_p = mann_whitney_u(group_a, group_b)
    payload = primary.to_dict()
    payload.update({"mann_whitney_u": u, "mann_whitney_p": u_p})
    return payload


def compare_table(
    frame: pd.DataFrame,
    *,
    metric_columns: Sequence[str],
    group_column: str = "condition",
    group_a: str = "forest",
    group_b: str = "urban",
    paired: bool = False,
) -> pd.DataFrame:
    """Compare ``group_a`` against ``group_b`` for each metric present."""
    if frame is None or frame.empty or group_column not in frame.columns:
        return pd.DataFrame()
    rows = []
    labels = frame[group_column].astype("object")
    for metric in metric_columns:
        if metric not in frame.columns:
            continue
        values = pd.to_numeric(frame[metric], errors="coerce")
        a = values[labels == group_a].dropna()
        b = values[labels == group_b].dropna()
        if len(a) < 2 or len(b) < 2:
            continue
        result = compare(a, b, paired=paired)
        rows.append(
            {
                "metric": metric,
                "n_a": result["n_a"],
                "mean_a": round(result["mean_a"], 2),
                "n_b": result["n_b"],
                "mean_b": round(result["mean_b"], 2),
                "diff": round(result["diff"], 2),
                "pct_change": round(result["pct_change"] * 100, 1) if math.isfinite(result["pct_change"]) else None,
                "cohens_d": round(result["cohens_d"], 2) if math.isfinite(result["cohens_d"]) else None,
                "effect": result["effect"],
                "p_value": round(result["p_value"], 4) if math.isfinite(result["p_value"]) else None,
                "ci_low": round(result["ci_low"], 2) if math.isfinite(result["ci_low"]) else None,
                "ci_high": round(result["ci_high"], 2) if math.isfinite(result["ci_high"]) else None,
            }
        )
    return pd.DataFrame(rows)
