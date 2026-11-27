"""Group comparison statistics with no compiled dependencies.

The module implements the tests itself (Welch t, paired t, Mann–Whitney U,
Cohen's d / Hedges' g, bootstrap CI) so the package installs with numpy and
pandas alone. The definitions follow the standard formulas and are checked
against SciPy in the test suite when SciPy is available.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Sequence

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


def _p_round(p: float, digits: int = 4) -> float | None:
    """Round a p-value without ever reporting an exact zero.

    A p of 0.00003 is not zero, and printing ``0.0`` would claim certainty the
    test did not establish, so very small values keep three significant digits.
    """
    if p is None or not isinstance(p, (int, float)) or not math.isfinite(p):
        return None
    if p >= 10 ** (-digits):
        return round(float(p), digits)
    return float(f"{p:.3g}")


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


def cohens_dz(group_a: Iterable[float], group_b: Iterable[float]) -> float:
    """Paired standardized effect size d_z = mean(a − b) / SD(a − b).

    Reference: Cohen, J. (1988) *Statistical Power Analysis for the Behavioral
    Sciences*, 2nd ed.; Lakens, D. (2013) Frontiers in Psychology 4:863 for the
    distinction between d_z and d_av.
    """
    a = np.asarray(list(group_a), dtype=float)
    b = np.asarray(list(group_b), dtype=float)
    if a.size != b.size or a.size < 2:
        return float("nan")
    valid = np.isfinite(a) & np.isfinite(b)
    diff = a[valid] - b[valid]
    if diff.size < 2:
        return float("nan")
    spread = float(diff.std(ddof=1))
    if spread == 0:
        return float("nan")
    return float(diff.mean() / spread)


def sign_flip_permutation(
    group_a: Iterable[float],
    group_b: Iterable[float],
    *,
    n_permutations: int = 5000,
    seed: int = 5020,
) -> float:
    """Two-sided sign-flip permutation p-value for a paired mean difference.

    Under the null hypothesis the two conditions are exchangeable, so the sign
    of each subject's difference is equally likely to be positive or negative.
    The observed |mean difference| is compared with the distribution obtained by
    randomly flipping the signs (deterministic seed, so a report can be rerun).
    No distributional assumption is made.
    """
    a = np.asarray(list(group_a), dtype=float)
    b = np.asarray(list(group_b), dtype=float)
    if a.size != b.size or a.size == 0:
        return float("nan")
    valid = np.isfinite(a) & np.isfinite(b)
    diff = a[valid] - b[valid]
    if diff.size < 2:
        return float("nan")
    observed = abs(float(diff.mean()))
    rng = np.random.default_rng(seed)
    flips = rng.choice([-1.0, 1.0], size=(n_permutations, diff.size))
    simulated = np.abs((flips * diff).mean(axis=1))
    # +1 correction: the observed arrangement counts as one of the permutations.
    return float((int((simulated >= observed - 1e-12).sum()) + 1) / (n_permutations + 1))


def sign_test(group_a: Iterable[float], group_b: Iterable[float]) -> float:
    """Two-sided exact sign test p-value for paired observations.

    Counts how often a − b is positive and compares with Binomial(n, 0.5);
    zero differences are dropped (the conventional conservative handling).
    """
    a = np.asarray(list(group_a), dtype=float)
    b = np.asarray(list(group_b), dtype=float)
    if a.size != b.size or a.size == 0:
        return float("nan")
    valid = np.isfinite(a) & np.isfinite(b)
    diff = a[valid] - b[valid]
    diff = diff[diff != 0]
    n = int(diff.size)
    if n == 0:
        return float("nan")
    positive = int((diff > 0).sum())
    tail = sum(math.comb(n, k) for k in range(0, min(positive, n - positive) + 1))
    return float(min(1.0, 2 * tail / 2**n))


def wilcoxon_signed_rank(group_a: Iterable[float], group_b: Iterable[float]) -> tuple[float, float]:
    """Two-sided Wilcoxon signed-rank test (normal approximation, tie corrected).

    Requires enough pairs to use the normal approximation (n >= 10 after
    dropping zero differences); for a small, assumption-light alternative use
    :func:`sign_flip_permutation` or :func:`sign_test`.
    """
    a = np.asarray(list(group_a), dtype=float)
    b = np.asarray(list(group_b), dtype=float)
    if a.size != b.size or a.size == 0:
        return float("nan"), float("nan")
    valid = np.isfinite(a) & np.isfinite(b)
    diff = a[valid] - b[valid]
    diff = diff[diff != 0]
    n = int(diff.size)
    if n < 1:
        return float("nan"), float("nan")
    ranks = pd.Series(np.abs(diff)).rank(method="average").to_numpy()
    w_plus = float(ranks[diff > 0].sum())
    w = min(w_plus, n * (n + 1) / 2.0 - w_plus)
    mean_w = n * (n + 1) / 4.0
    _, counts = np.unique(np.abs(diff), return_counts=True)
    tie_term = float(sum(c**3 - c for c in counts))
    variance = n * (n + 1) * (2 * n + 1) / 24.0 - tie_term / 48.0
    if variance <= 0:
        return float(w), float("nan")
    z = (w - mean_w + 0.5) / math.sqrt(variance)
    p = 2.0 * (1.0 - normal_cdf(abs(z)))
    return float(w), float(min(max(p, 0.0), 1.0))


# ------------------------------------------------- multiple comparison control


MULTIPLE_COMPARISON_METHODS: tuple[str, ...] = ("bh", "holm")


def _p_array(p_values: Iterable[float]) -> np.ndarray:
    """p-values as a float array in input order; None stays missing (NaN)."""
    out = []
    for value in p_values:
        if value is None:
            out.append(float("nan"))
            continue
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            out.append(float("nan"))
    return np.asarray(out, dtype=float)


def benjamini_hochberg(p_values: Iterable[float], alpha: float = 0.05) -> np.ndarray:
    """Benjamini–Hochberg step-up FDR-adjusted p-values (``q`` values).

    For ``m`` tested hypotheses ordered by ascending p, ``q_(i) = m · p_(i) / i``
    made monotone with ``q_(i) = min(q_(i), q_(i+1))`` so that q never decreases as
    p grows, then clipped to [0, 1]. Reject hypothesis *i* when ``q_(i) <= alpha``.
    The result keeps the order of the input p-values; a missing p (``None``/NaN)
    yields NaN and is left out of the family size, because a test that could not
    run is not a test that was run.

    Reference: Benjamini, Y. & Hochberg, Y. (1995). Controlling the false
    discovery rate: a practical and powerful approach to multiple testing.
    Journal of the Royal Statistical Society B 57(1):289–300.
    """
    p = _p_array(p_values)
    q = np.full(p.shape, np.nan, dtype=float)
    valid = np.isfinite(p)
    m = int(valid.sum())
    if m == 0:
        return q
    pv = np.clip(p[valid], 0.0, 1.0)
    order = np.argsort(pv, kind="mergesort")
    ranked = pv[order]
    ranks = np.arange(1, m + 1, dtype=float)
    adjusted = ranked * m / ranks
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    out = np.empty(m, dtype=float)
    out[order] = np.clip(adjusted, 0.0, 1.0)
    q[valid] = out
    return q


def holm_bonferroni(p_values: Iterable[float], alpha: float = 0.05) -> np.ndarray:
    """Holm–Bonferroni step-down adjusted p-values.

    For ``m`` hypotheses ordered by ascending p,
    ``p_holm_(i) = max_{j <= i} min(1, (m − j + 1) · p_(j))``. Reject hypothesis
    *i* when ``p_holm_(i) <= alpha``; the procedure controls the family-wise error
    rate under arbitrary dependence. The result keeps the order of the input
    p-values; missing p-values stay NaN and are left out of ``m``.

    Reference: Holm, S. (1979). A simple sequentially rejective multiple test
    procedure. Scandinavian Journal of Statistics 6(2):65–70.
    """
    p = _p_array(p_values)
    adjusted_p = np.full(p.shape, np.nan, dtype=float)
    valid = np.isfinite(p)
    m = int(valid.sum())
    if m == 0:
        return adjusted_p
    pv = np.clip(p[valid], 0.0, 1.0)
    order = np.argsort(pv, kind="mergesort")
    ranked = pv[order]
    multipliers = m - np.arange(m, dtype=float)
    adjusted = np.maximum.accumulate(ranked * multipliers)
    out = np.empty(m, dtype=float)
    out[order] = np.clip(adjusted, 0.0, 1.0)
    adjusted_p[valid] = out
    return adjusted_p


def adjust_p_values(
    p_values: Iterable[float],
    method: str = "bh",
    alpha: float = 0.05,
) -> np.ndarray:
    """Adjusted p-values for ``method`` (``"bh"`` or ``"holm"``)."""
    key = str(method or "bh").strip().lower()
    if key in {"bh", "fdr", "benjamini_hochberg", "benjamini-hochberg"}:
        return benjamini_hochberg(p_values, alpha)
    if key in {"holm", "holm_bonferroni", "holm-bonferroni"}:
        return holm_bonferroni(p_values, alpha)
    raise ValueError(f"unsupported multiple-comparison method: {method}")


def multiple_comparison_summary(p_values: Iterable[float], alpha: float = 0.05) -> Dict[str, Any]:
    """Family size and how many hypotheses survive each correction.

    One place to state how many tests were run at once, so a report cannot
    present one uncorrected p-value as if it came from a single test.
    """
    p = _p_array(p_values)
    valid = np.isfinite(p)
    q = benjamini_hochberg(p, alpha)
    holm = holm_bonferroni(p, alpha)
    return {
        "method": "benjamini_hochberg",
        "family": "metrics compared between the two conditions of this table",
        "family_size": int(valid.sum()),
        "alpha": float(alpha),
        "tests_unavailable": int((~valid).sum()),
        "rejected_bh_fdr": int(np.sum(q[valid] <= alpha)) if valid.any() else 0,
        "rejected_holm_fw": int(np.sum(holm[valid] <= alpha)) if valid.any() else 0,
    }


# ------------------------------------------------------- paired by subject


def subject_pairs(
    frame: pd.DataFrame,
    metric: str,
    *,
    group_a: str = "forest",
    group_b: str = "urban",
    subject_column: str = "subject_id",
    condition_column: str = "condition",
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Collapse each subject to one value per condition, keeping the pairing.

    A subject with several readings under one condition contributes the mean of
    those readings (a within-subject summary, not a pooled reading), so the
    paired test compares subject-level responses rather than raw rows.
    Subjects that appear under only one condition are excluded and counted.
    """
    empty = (np.array([]), np.array([]), [])
    if frame is None or frame.empty:
        return empty
    for column in (metric, subject_column, condition_column):
        if column not in frame.columns:
            return empty
    working = frame[[metric, subject_column, condition_column]].copy()
    working[metric] = pd.to_numeric(working[metric], errors="coerce")
    working = working.dropna(subset=[metric, subject_column, condition_column])
    if working.empty:
        return empty
    grouped = working.groupby([subject_column, condition_column])[metric].mean().unstack()
    if group_a not in grouped.columns or group_b not in grouped.columns:
        return empty
    paired = grouped[[group_a, group_b]].dropna()
    return (
        paired[group_a].to_numpy(dtype=float),
        paired[group_b].to_numpy(dtype=float),
        [str(s) for s in paired.index.tolist()],
    )


def paired_subject_compare(
    frame: pd.DataFrame,
    metric: str,
    *,
    group_a: str = "forest",
    group_b: str = "urban",
    subject_column: str = "subject_id",
    condition_column: str = "condition",
    alpha: float = 0.05,
    n_permutations: int = 5000,
) -> Dict[str, Any]:
    """Paired comparison on subject-level means with t, permutation, sign test."""
    a, b, subjects = subject_pairs(
        frame,
        metric,
        group_a=group_a,
        group_b=group_b,
        subject_column=subject_column,
        condition_column=condition_column,
    )
    if a.size < 2:
        return {
            "metric": metric,
            "paired_by": "subject",
            "n_subjects": int(a.size),
            "available": False,
            "reason": f"needs at least 2 subjects measured in both {group_a} and {group_b}",
        }
    base = paired_ttest(a, b, alpha).to_dict()
    dz = cohens_dz(a, b)
    _, wilcoxon_p = wilcoxon_signed_rank(a, b)
    base.update(
        {
            "metric": metric,
            "available": True,
            "paired_by": "subject",
            "n_subjects": int(a.size),
            "n_a": int(a.size),
            "n_b": int(b.size),
            "mean_a": float(a.mean()),
            "mean_b": float(b.mean()),
            "cohens_dz": dz,
            "effect_dz": effect_size_label(dz),
            "permutation_p": sign_flip_permutation(a, b, n_permutations=n_permutations),
            "sign_test_p": sign_test(a, b),
            "wilcoxon_p": wilcoxon_p,
            "subjects": subjects,
        }
    )
    return base


def _row_order_pairs(values_a: pd.Series, values_b: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Fallback pairing: observations in time order, truncated to the shorter side."""
    a = values_a.to_numpy(dtype=float)
    b = values_b.to_numpy(dtype=float)
    n = int(min(a.size, b.size))
    return a[:n], b[:n]


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
    if paired:
        payload["cohens_dz"] = cohens_dz(group_a, group_b)
        payload["permutation_p"] = sign_flip_permutation(group_a, group_b)
        payload["sign_test_p"] = sign_test(group_a, group_b)
    return payload


def _count_subjects_in_both(
    frame: pd.DataFrame,
    subject_column: str,
    condition_column: str,
    group_a: str,
    group_b: str,
) -> int:
    """Subjects that carry at least one row in each of the two conditions."""
    if frame is None or frame.empty:
        return 0
    if subject_column not in frame.columns or condition_column not in frame.columns:
        return 0
    working = frame[[subject_column, condition_column]].dropna()
    if working.empty:
        return 0
    both = working.groupby(subject_column)[condition_column].apply(
        lambda values: {group_a, group_b} <= set(values.astype(str))
    )
    return int(both.sum()) if len(both) else 0


def compare_table(
    frame: pd.DataFrame,
    *,
    metric_columns: Sequence[str],
    group_column: str = "condition",
    group_a: str = "forest",
    group_b: str = "urban",
    paired: bool = False,
    paired_by: str = "auto",
    subject_column: str = "subject_id",
) -> pd.DataFrame:
    """Compare ``group_a`` against ``group_b`` for each metric present.

    ``paired_by``
        * ``"auto"`` (default) — pair by subject when a subject column with at
          least two subjects measured in both conditions exists, otherwise pair
          observations in time order and say so in the ``paired_by`` column.
        * ``"subject"`` — require subject pairing; metrics without it are skipped.
        * ``"row"`` — time-order pairing of the two value lists.
    """
    if frame is None or frame.empty or group_column not in frame.columns:
        return pd.DataFrame()
    has_subject = (
        subject_column in frame.columns
        and frame[subject_column].map(lambda v: bool(pd.notna(v) and str(v).strip())).any()
    )
    resolved = paired_by
    if paired and paired_by == "auto":
        resolved = (
            "subject"
            if has_subject
            and _count_subjects_in_both(
                frame, subject_column, group_column, group_a, group_b
            )
            >= 2
            else "row"
        )
    rows = []
    raw_p_values: list[float] = []
    skipped: Dict[str, str] = {}
    labels = frame[group_column].astype("object")
    for metric in metric_columns:
        if metric not in frame.columns:
            continue
        values = pd.to_numeric(frame[metric], errors="coerce")
        a = values[labels == group_a].dropna()
        b = values[labels == group_b].dropna()
        if len(a) < 2 or len(b) < 2:
            continue
        if paired and resolved == "subject":
            result = paired_subject_compare(
                frame, metric, group_a=group_a, group_b=group_b,
                subject_column=subject_column, condition_column=group_column,
            )
            if not result.get("available"):
                skipped[metric] = str(result.get("reason", "no paired subjects"))
                continue
        else:
            if paired:
                a_values, b_values = _row_order_pairs(a, b)
            else:
                a_values, b_values = a.to_numpy(dtype=float), b.to_numpy(dtype=float)
            result = compare(a_values, b_values, paired=paired)
            result["paired_by"] = "row" if paired else "unpaired"
            result["n_subjects"] = None
            result["available"] = True
        raw_p_values.append(float(result["p_value"]))
        rows.append(
            {
                "metric": metric,
                "paired_by": result.get("paired_by"),
                "n_subjects": result.get("n_subjects"),
                "n_a": result["n_a"],
                "mean_a": round(result["mean_a"], 2),
                "n_b": result["n_b"],
                "mean_b": round(result["mean_b"], 2),
                "diff": round(result["diff"], 2),
                "pct_change": round(result["pct_change"] * 100, 1) if math.isfinite(result["pct_change"]) else None,
                "cohens_d": round(result["cohens_d"], 2) if math.isfinite(result["cohens_d"]) else None,
                "cohens_dz": round(result["cohens_dz"], 2) if math.isfinite(result.get("cohens_dz", float("nan"))) else None,
                "effect": result["effect"],
                "test": result.get("test"),
                "p_value": _p_round(result["p_value"]),
                "permutation_p": _p_round(result.get("permutation_p", float("nan"))),
                "sign_test_p": _p_round(result.get("sign_test_p", float("nan"))),
                "ci_low": round(result["ci_low"], 2) if math.isfinite(result["ci_low"]) else None,
                "ci_high": round(result["ci_high"], 2) if math.isfinite(result["ci_high"]) else None,
            }
        )
    table = pd.DataFrame(rows)
    if not table.empty:
        # Every metric in this table was tested against the same two conditions,
        # so the family is the table itself and both corrections are reported
        # beside the raw p. No correction is applied silently.
        p_holm = holm_bonferroni(raw_p_values)
        q_bh = benjamini_hochberg(raw_p_values)
        table["p_holm"] = [_p_round(float(v)) for v in p_holm]
        table["q_value_bh"] = [_p_round(float(v)) for v in q_bh]
        table["significant_holm_05"] = [bool(np.isfinite(v) and v <= 0.05) for v in p_holm]
        table["significant_fdr_05"] = [bool(np.isfinite(v) and v <= 0.05) for v in q_bh]
        table.attrs["multiple_comparison"] = multiple_comparison_summary(raw_p_values)
    if skipped:
        table.attrs["skipped"] = skipped
    if paired and not has_subject:
        table.attrs["note"] = (
            "no subject_id column was found; observations were paired in time order, not by subject"
        )
    return table


# ------------------------------------------------- environment correlation


def _pair_arrays(x: Iterable[float], y: Iterable[float]) -> tuple[np.ndarray, np.ndarray]:
    xs = np.asarray(list(x), dtype=float)
    ys = np.asarray(list(y), dtype=float)
    if xs.size != ys.size:
        size = min(xs.size, ys.size)
        xs, ys = xs[:size], ys[:size]
    valid = np.isfinite(xs) & np.isfinite(ys)
    return xs[valid], ys[valid]


def _r_p_value(r: float, n: int) -> float:
    """Two-sided p-value of a correlation through the t = r√((n−2)/(1−r²)) form."""
    if not math.isfinite(r) or n < 3 or abs(r) >= 1.0:
        return float("nan")
    t = r * math.sqrt((n - 2) / max(1e-15, 1.0 - r * r))
    return float(min(max(2.0 * t_sf(abs(t), n - 2), 0.0), 1.0))


def pearson(x: Iterable[float], y: Iterable[float]) -> Dict[str, float]:
    """Pearson product-moment correlation with its two-sided p-value."""
    xs, ys = _pair_arrays(x, y)
    n = int(xs.size)
    if n < 3 or xs.std() == 0 or ys.std() == 0:
        return {"r": float("nan"), "p": float("nan"), "n": n}
    r = float(np.corrcoef(xs, ys)[0, 1])
    return {"r": r, "p": _r_p_value(r, n), "n": n}


def spearman(x: Iterable[float], y: Iterable[float]) -> Dict[str, float]:
    """Spearman rank correlation (average ranks for ties).

    The p-value uses the same t approximation as Pearson on the ranks, which is
    the usual large-sample approximation; with fewer than 10 pairs read it as
    approximate and prefer the permutation p-value.
    """
    xs, ys = _pair_arrays(x, y)
    n = int(xs.size)
    if n < 3:
        return {"rho": float("nan"), "p": float("nan"), "n": n}
    rx = pd.Series(xs).rank(method="average").to_numpy()
    ry = pd.Series(ys).rank(method="average").to_numpy()
    if rx.std() == 0 or ry.std() == 0:
        return {"rho": float("nan"), "p": float("nan"), "n": n}
    rho = float(np.corrcoef(rx, ry)[0, 1])
    return {"rho": rho, "p": _r_p_value(rho, n), "n": n}


def linear_regression(
    x: Iterable[float],
    y: Iterable[float],
    *,
    alpha: float = 0.05,
) -> Dict[str, float]:
    """Ordinary least squares ``y = intercept + slope·x`` — the slope and its test."""
    xs, ys = _pair_arrays(x, y)
    n = int(xs.size)
    nan = float("nan")
    if n < 3:
        return {"slope": nan, "intercept": nan, "se_slope": nan, "t": nan, "p": nan, "r2": nan, "n": n}
    x_mean, y_mean = float(xs.mean()), float(ys.mean())
    sxx = float(((xs - x_mean) ** 2).sum())
    if sxx <= 0:
        return {"slope": nan, "intercept": nan, "se_slope": nan, "t": nan, "p": nan, "r2": nan, "n": n}
    sxy = float(((xs - x_mean) * (ys - y_mean)).sum())
    slope = sxy / sxx
    intercept = y_mean - slope * x_mean
    fitted = intercept + slope * xs
    sse = float(((ys - fitted) ** 2).sum())
    sst = float(((ys - y_mean) ** 2).sum())
    df = n - 2
    if sse <= 0 or df < 1:
        return {"slope": slope, "intercept": intercept, "se_slope": nan, "t": nan, "p": nan, "r2": nan, "n": n}
    se_slope = math.sqrt(sse / df / sxx)
    t = slope / se_slope if se_slope else nan
    p = 2.0 * t_sf(abs(t), df) if math.isfinite(t) else nan
    crit = t_ppf(1.0 - alpha / 2.0, df)
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "se_slope": float(se_slope),
        "slope_ci_low": float(slope - crit * se_slope),
        "slope_ci_high": float(slope + crit * se_slope),
        "t": float(t),
        "p": float(min(max(p, 0.0), 1.0)) if math.isfinite(p) else nan,
        "r2": float(1.0 - sse / sst) if sst > 0 else nan,
        "n": n,
    }


#: Default environment × cardiovascular pairs (documented in provenance.py).
DEFAULT_CORRELATION_PAIRS: tuple[tuple[str, str], ...] = (
    ("pm25", "sbp"),
    ("pm25", "dbp"),
    ("pm25", "map"),
    ("pm25", "rmssd"),
    ("pm25", "sdnn"),
    ("green_index", "sbp"),
    ("green_index", "rmssd"),
    ("temp_c", "hr"),
    ("temp_c", "sbp"),
    ("humidity_pct", "hr"),
    ("env_load", "sbp"),
    ("env_load", "rmssd"),
)


def correlation_profile(
    frame: pd.DataFrame,
    x_key: str,
    y_key: str,
    *,
    min_n: int = 4,
) -> Dict[str, Any]:
    """Pearson r, Spearman ρ and the OLS slope for one pair of columns."""
    if frame is None or frame.empty or x_key not in frame.columns or y_key not in frame.columns:
        return {"x": x_key, "y": y_key, "available": False, "reason": "column not present"}
    x = pd.to_numeric(frame[x_key], errors="coerce")
    y = pd.to_numeric(frame[y_key], errors="coerce")
    keep = x.notna() & y.notna()
    xs, ys = x[keep], y[keep]
    if int(keep.sum()) < min_n:
        return {
            "x": x_key,
            "y": y_key,
            "available": False,
            "n": int(keep.sum()),
            "reason": f"needs at least {min_n} paired observations",
        }
    p = pearson(xs, ys)
    s = spearman(xs, ys)
    regression = linear_regression(xs, ys)
    return {
        "x": x_key,
        "y": y_key,
        "available": True,
        "n": int(p["n"]),
        "pearson_r": p["r"],
        "pearson_p": p["p"],
        "spearman_rho": s["rho"],
        "spearman_p": s["p"],
        "slope": regression["slope"],
        "intercept": regression["intercept"],
        "slope_ci_low": regression.get("slope_ci_low", float("nan")),
        "slope_ci_high": regression.get("slope_ci_high", float("nan")),
        "slope_p": regression["p"],
        "r_squared": regression["r2"],
        "warning": "correlation is not causation; a single subject's series cannot separate exposure from season, activity or mood",
    }


def correlation_table(
    frame: pd.DataFrame,
    pairs: Sequence[tuple[str, str]] | None = None,
    *,
    min_n: int = 4,
) -> pd.DataFrame:
    """Environment × cardiovascular correlation table (r, ρ, slope, p, n)."""
    pairs = tuple(pairs or DEFAULT_CORRELATION_PAIRS)
    rows = []
    for x_key, y_key in pairs:
        profile = correlation_profile(frame, x_key, y_key, min_n=min_n)
        if not profile.get("available"):
            continue
        rows.append(
            {
                "x": x_key,
                "y": y_key,
                "n": profile["n"],
                "pearson_r": round(profile["pearson_r"], 3),
                "pearson_p": _p_round(profile["pearson_p"]),
                "spearman_rho": round(profile["spearman_rho"], 3),
                "spearman_p": _p_round(profile["spearman_p"]),
                "slope": round(profile["slope"], 4) if math.isfinite(profile["slope"]) else None,
                "intercept": round(profile["intercept"], 3) if math.isfinite(profile["intercept"]) else None,
                "slope_ci_low": round(profile["slope_ci_low"], 4) if math.isfinite(profile["slope_ci_low"]) else None,
                "slope_ci_high": round(profile["slope_ci_high"], 4) if math.isfinite(profile["slope_ci_high"]) else None,
                "slope_p": _p_round(profile["slope_p"]),
                "r_squared": round(profile["r_squared"], 3) if math.isfinite(profile["r_squared"]) else None,
            }
        )
    return pd.DataFrame(rows)
