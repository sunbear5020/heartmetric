from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from heartmetric_core import pipeline, stats, synthetic


@pytest.fixture(scope="module")
def cohort():
    return synthetic.generate_cohort(subjects=6, days=8)


# --------------------------------------------------------- paired by subject


def test_subject_pairs_collapses_rows_per_subject(cohort):
    a, b, subjects = stats.subject_pairs(cohort, "sbp")
    assert a.size == 6 and b.size == 6 and len(subjects) == 6
    manual = (
        cohort[cohort["subject_id"] == "S-01"]
        .groupby("condition")["sbp"]
        .mean()
    )
    index = subjects.index("S-01")
    assert a[index] == pytest.approx(manual["forest"])
    assert b[index] == pytest.approx(manual["urban"])


def test_paired_subject_compare_reports_dz_and_nonparametric_p(cohort):
    result = stats.paired_subject_compare(cohort, "sbp")
    assert result["available"] is True
    assert result["paired_by"] == "subject"
    assert result["n_subjects"] == 6
    assert result["diff"] < 0  # forest lower than urban in the generator
    assert result["p_value"] < 0.05
    assert result["cohens_dz"] < 0
    assert 0 < result["permutation_p"] <= 1
    assert 0 < result["sign_test_p"] <= 1
    assert result["ci_low"] < result["diff"] < result["ci_high"]


def test_paired_subject_compare_matches_scipy(cohort):
    scipy_stats = pytest.importorskip("scipy.stats")
    a, b, _ = stats.subject_pairs(cohort, "sbp")
    ours = stats.paired_subject_compare(cohort, "sbp")
    reference = scipy_stats.ttest_rel(a, b)
    assert ours["statistic"] == pytest.approx(float(reference.statistic), rel=1e-9)
    assert ours["p_value"] == pytest.approx(float(reference.pvalue), rel=1e-7)


def test_paired_subject_compare_needs_two_subjects():
    frame = synthetic.generate(days=4, include_anomalies=False)  # one subject
    result = stats.paired_subject_compare(frame, "sbp")
    assert result["available"] is False
    assert "subject" in result["reason"]


def test_compare_table_marks_how_it_paired(cohort):
    table = stats.compare_table(cohort, metric_columns=["sbp", "rmssd"], paired=True)
    assert set(table["paired_by"]) == {"subject"}
    assert table.set_index("metric").loc["sbp", "n_subjects"] == 6
    unpaired = stats.compare_table(cohort, metric_columns=["sbp"], paired=False)
    assert unpaired.iloc[0]["paired_by"] == "unpaired"


def test_compare_table_falls_back_to_row_pairing_without_subject(cohort):
    frame = cohort.drop(columns=["subject_id"])
    table = stats.compare_table(frame, metric_columns=["sbp"], paired=True)
    assert table.iloc[0]["paired_by"] == "row"
    assert table.attrs.get("note")


def test_auto_pairing_uses_row_mode_for_a_single_subject():
    frame = synthetic.generate(days=6, include_anomalies=False)  # one subject, both conditions
    table = stats.compare_table(frame, metric_columns=["sbp"], paired=True)
    assert not table.empty
    assert table.iloc[0]["paired_by"] == "row"


def test_explicit_subject_mode_skips_without_subjects(cohort):
    frame = cohort.drop(columns=["subject_id"])
    table = stats.compare_table(frame, metric_columns=["sbp"], paired=True, paired_by="subject")
    assert table.empty
    assert table.attrs.get("note")


def test_cohens_dz_formula():
    a = [12, 14, 16, 18]
    b = [9, 11, 12, 14]
    diff = np.array(a) - np.array(b)
    assert stats.cohens_dz(a, b) == pytest.approx(diff.mean() / diff.std(ddof=1))


def test_sign_test_extremes():
    assert stats.sign_test([1, 2, 3, 4, 5, 6], [0, 0, 0, 0, 0, 0]) == pytest.approx(2 / 64)
    assert stats.sign_test([1, 1, 1, 1], [2, 2, 2, 2]) == pytest.approx(0.125)


def test_permutation_and_sign_test_are_bounded(cohort):
    a, b, _ = stats.subject_pairs(cohort, "rmssd")
    for value in (stats.sign_flip_permutation(a, b), stats.sign_test(a, b)):
        assert 0.0 < value <= 1.0


def test_wilcoxon_signed_rank_matches_scipy():
    scipy_stats = pytest.importorskip("scipy.stats")
    a = [130, 128, 131, 127, 129, 132, 126, 130, 133, 128]
    b = [134, 133, 135, 131, 132, 136, 130, 134, 137, 133]
    w, p = stats.wilcoxon_signed_rank(a, b)
    reference = scipy_stats.wilcoxon(a, b, method="approx")
    assert w == pytest.approx(float(reference.statistic))
    # normal approximation with continuity correction — close, not identical
    assert 0.5 * float(reference.pvalue) <= p <= 2.0 * float(reference.pvalue)


# ------------------------------------------------------- environment correlation


def test_pearson_and_spearman_match_scipy():
    scipy_stats = pytest.importorskip("scipy.stats")
    rng = np.random.default_rng(11)
    x = rng.normal(20, 6, 40)
    y = 0.6 * x + rng.normal(0, 3, 40)
    ours = stats.pearson(x, y)
    reference = scipy_stats.pearsonr(x, y)
    assert ours["r"] == pytest.approx(float(reference.statistic), rel=1e-12)
    assert ours["p"] == pytest.approx(float(reference.pvalue), rel=1e-6)

    ours_s = stats.spearman(x, y)
    reference_s = scipy_stats.spearmanr(x, y)
    assert ours_s["rho"] == pytest.approx(float(reference_s.statistic), rel=1e-12)
    assert ours_s["p"] == pytest.approx(float(reference_s.pvalue), rel=1e-3)


def test_linear_regression_matches_scipy_and_recovers_slope():
    scipy_stats = pytest.importorskip("scipy.stats")
    rng = np.random.default_rng(5)
    x = rng.uniform(0, 40, 60)
    y = 130 + 0.4 * x + rng.normal(0, 2, 60)
    ours = stats.linear_regression(x, y)
    reference = scipy_stats.linregress(x, y)
    assert ours["slope"] == pytest.approx(float(reference.slope), rel=1e-9)
    assert ours["intercept"] == pytest.approx(float(reference.intercept), rel=1e-9)
    assert ours["p"] == pytest.approx(float(reference.pvalue), rel=1e-6)
    assert ours["slope_ci_low"] < ours["slope"] < ours["slope_ci_high"]
    assert 0.0 <= ours["r2"] <= 1.0


def test_correlation_profile_and_table(cohort):
    profile = stats.correlation_profile(cohort, "pm25", "sbp")
    assert profile["available"] is True
    for key in ("pearson_r", "pearson_p", "spearman_rho", "slope", "intercept", "slope_p", "r_squared"):
        assert key in profile
    table = stats.correlation_table(cohort)
    assert not table.empty
    assert {"pearson_r", "spearman_rho", "slope", "slope_p", "n"} <= set(table.columns)
    assert (table["n"] >= 4).all()


def test_correlation_table_never_reports_exact_zero_p(cohort):
    table = stats.correlation_table(cohort)
    for column in ("pearson_p", "spearman_p", "slope_p"):
        assert (table[column].dropna() > 0).all()


def test_missing_columns_are_reported_not_invented(cohort):
    profile = stats.correlation_profile(cohort, "pm25", "unknown_metric")
    assert profile["available"] is False
    assert profile["reason"]


# --------------------------------------------------------------- env load


def test_env_load_uses_only_environmental_inputs():
    frame = synthetic.generate(include_anomalies=False)
    loaded = frame.assign(env_load=None)
    from heartmetric_core import metrics

    values = metrics.environmental_load(frame)
    assert values.notna().all()
    assert (values >= 0).all() and (values <= 1).all()
    assert values.max() > values.min()


def test_pipeline_bundle_has_v02_sections(cohort):
    bundle = pipeline.analyze(cohort, paired=True)
    assert bundle["meta"]["schema_version"] == "0.2.0"
    assert bundle["meta"]["comparison"]["paired_by"] == "subject"
    assert bundle["meta"]["comparison"]["n_subjects"] == 6
    assert bundle["methodology"]["version"] == "0.2.0"
    assert "env_load" in {row["x"] for row in bundle["correlations"]}
    assert bundle["comparison"][0]["cohens_dz"] is not None
    assert bundle["comparison"][0]["permutation_p"] is not None
