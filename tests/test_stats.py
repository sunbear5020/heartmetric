from __future__ import annotations

import math

import numpy as np
import pytest

from heartmetric_core import stats


def test_t_distribution_matches_reference_values():
    # Two-sided 5 % critical values of Student's t.
    assert stats.t_ppf(0.975, 10) == pytest.approx(2.228, abs=1e-3)
    assert stats.t_ppf(0.975, 1) == pytest.approx(12.706, abs=1e-2)
    assert stats.t_sf(2.228, 10) == pytest.approx(0.025, abs=1e-4)


def test_t_distribution_matches_scipy_when_available():
    scipy_stats = pytest.importorskip("scipy.stats")
    for df in (1, 3, 8, 30, 250):
        for t in (-3.0, -0.5, 0.0, 0.7, 2.4):
            assert stats.t_sf(t, df) == pytest.approx(float(scipy_stats.t.sf(t, df)), rel=1e-7, abs=1e-9)


def test_welch_ttest_known_result():
    a = [130, 128, 131, 127, 129, 132]
    b = [140, 143, 138, 141, 139, 145]
    result = stats.welch_ttest(a, b)
    assert result.diff == pytest.approx(np.mean(a) - np.mean(b))
    assert result.p_value < 0.001
    assert result.ci_high < 0  # a is lower than b
    assert result.d == pytest.approx(-1.5, abs=0.6) or result.d < -1.0


def test_welch_ttest_matches_scipy_when_available():
    scipy_stats = pytest.importorskip("scipy.stats")
    rng = np.random.default_rng(7)
    a = rng.normal(128, 6, 40)
    b = rng.normal(134, 7, 37)
    ours = stats.welch_ttest(a, b)
    reference = scipy_stats.ttest_ind(a, b, equal_var=False)
    assert ours.statistic == pytest.approx(float(reference.statistic), rel=1e-9)
    assert ours.df == pytest.approx(float(reference.df), rel=1e-9)
    assert ours.p_value == pytest.approx(float(reference.pvalue), rel=1e-7, abs=1e-12)


def test_cohens_d_and_hedges_g():
    a = [10, 11, 12, 13, 14]
    b = [8, 9, 10, 11, 12]
    d = stats.cohens_d(a, b)
    assert d == pytest.approx(1.2649, abs=1e-3)
    g = stats.hedges_g(a, b)
    assert g < d
    assert stats.effect_size_label(d) == "large"
    assert stats.effect_size_label(0.1) == "negligible"


def test_mann_whitney_u_matches_scipy_when_available():
    scipy_stats = pytest.importorskip("scipy.stats")
    a = [130, 127, 131, 129, 133, 128]
    b = [141, 139, 144, 138, 142, 140]
    u, p = stats.mann_whitney_u(a, b)
    reference = scipy_stats.mannwhitneyu(a, b, alternative="two-sided", method="asymptotic")
    assert u == pytest.approx(float(reference.statistic))
    assert p == pytest.approx(float(reference.pvalue), rel=0.05)


def test_mann_whitney_handles_ties():
    u, p = stats.mann_whitney_u([1, 2, 2, 3], [2, 3, 3, 4])
    assert math.isfinite(u) and 0 <= p <= 1


def test_paired_ttest():
    a = [140, 138, 142, 139]
    b = [130, 128, 131, 129]
    result = stats.paired_ttest(a, b)
    assert result.test == "paired_t"
    assert result.df == 3
    assert result.diff == pytest.approx(10.5, abs=0.3)


def test_compare_table(demo_frame):
    table = stats.compare_table(
        demo_frame,
        metric_columns=["sbp", "dbp"],
        group_a="forest",
        group_b="urban",
    )
    assert set(table["metric"]) == {"sbp", "dbp"}
    row = table.set_index("metric").loc["sbp"]
    assert row["mean_a"] < row["mean_b"]
    assert row["diff"] < 0
    assert row["n_a"] > 5 and row["n_b"] > 5


def test_bootstrap_ci_contains_mean():
    rng = np.random.default_rng(3)
    values = rng.normal(130, 5, 60)
    low, high = stats.bootstrap_mean_ci(values)
    assert low < values.mean() < high


def test_empty_groups_are_nan_not_crash():
    result = stats.welch_ttest([], [1, 2, 3])
    assert not math.isfinite(result.p_value)
    assert result.n_a == 0
