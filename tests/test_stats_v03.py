"""v0.3 — multiple-comparison control (BH-FDR, Holm-Bonferroni)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heartmetric_core import pipeline, stats, synthetic

# The classic Benjamini–Hochberg example set (12 p-values, m = 12).
P_VALUES = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216, 0.222, 0.251]


def test_benjamini_hochberg_matches_scipy():
    reference = pytest.importorskip("scipy.stats").false_discovery_control
    ours = stats.benjamini_hochberg(P_VALUES)
    expected = reference(P_VALUES, method="bh")
    assert np.allclose(ours, expected, atol=1e-12)


def test_benjamini_hochberg_is_monotone_and_in_range():
    q = stats.benjamini_hochberg(P_VALUES)
    assert np.all(q >= 0) and np.all(q <= 1)
    order = np.argsort(P_VALUES)
    assert np.all(np.diff(q[order]) >= -1e-12), "q must not decrease as p grows"


def test_benjamini_hochberg_keeps_input_order():
    shuffled = [P_VALUES[i] for i in (3, 0, 7, 1, 11, 5, 2, 9, 4, 10, 6, 8)]
    q_shuffled = stats.benjamini_hochberg(shuffled)
    q_sorted = stats.benjamini_hochberg(P_VALUES)
    lookup = {p: q for p, q in zip(P_VALUES, q_sorted)}
    for p, q in zip(shuffled, q_shuffled):
        assert q == pytest.approx(lookup[p])


def test_benjamini_hochberg_hand_computed_small_family():
    # m = 4: 0.01·4/1=0.04, 0.02·4/2=0.04, 0.03·4/3=0.04, 0.20·4/4=0.20
    q = stats.benjamini_hochberg([0.01, 0.02, 0.03, 0.20])
    assert np.allclose(q, [0.04, 0.04, 0.04, 0.20])


def test_holm_bonferroni_hand_computed():
    # m = 3, ascending: 0.01·3=0.03, 0.03·2=0.06, 0.04·1=0.04 -> monotone max
    # -> sorted [0.03, 0.06, 0.06]; back in input order: 0.01, 0.04, 0.03 -> [0.03, 0.06, 0.06]
    p_holm = stats.holm_bonferroni([0.01, 0.04, 0.03])
    assert np.allclose(p_holm, [0.03, 0.06, 0.06])


def test_holm_matches_statsmodels_when_available():
    multipletests = pytest.importorskip("statsmodels.stats.multitest").multipletests
    ours = stats.holm_bonferroni(P_VALUES)
    expected = multipletests(P_VALUES, method="holm")[1]
    assert np.allclose(ours, expected, atol=1e-12)


def test_missing_p_values_are_left_out_of_the_family():
    q = stats.benjamini_hochberg([0.01, None, 0.04])
    assert np.isnan(q[1])
    # m = 2, so q = [0.02, 0.04]
    assert q[0] == pytest.approx(0.02)
    assert q[2] == pytest.approx(0.04)
    summary = stats.multiple_comparison_summary([0.01, None, 0.04])
    assert summary["family_size"] == 2
    assert summary["tests_unavailable"] == 1


def test_holm_is_never_less_conservative_than_bh():
    q = stats.benjamini_hochberg(P_VALUES)
    p_holm = stats.holm_bonferroni(P_VALUES)
    assert np.all(p_holm >= q - 1e-12)


def test_adjust_p_values_dispatches_and_rejects_unknown_method():
    assert np.allclose(stats.adjust_p_values(P_VALUES, "fdr"), stats.benjamini_hochberg(P_VALUES))
    assert np.allclose(stats.adjust_p_values(P_VALUES, "holm"), stats.holm_bonferroni(P_VALUES))
    with pytest.raises(ValueError):
        stats.adjust_p_values(P_VALUES, "bonferroni-ish")


def test_compare_table_reports_bh_and_holm_beside_raw_p():
    cohort = synthetic.generate_cohort(subjects=6, days=8)
    table = stats.compare_table(
        cohort,
        metric_columns=["sbp", "dbp", "map", "pp", "hr", "rmssd", "sdnn"],
        paired=True,
    )
    assert {"p_value", "p_holm", "q_value_bh", "significant_fdr_05", "significant_holm_05"} <= set(table.columns)
    raw = table["p_value"].to_numpy(dtype=float)
    assert np.allclose(table["q_value_bh"].to_numpy(dtype=float), stats.benjamini_hochberg(raw), atol=1e-4)
    assert np.allclose(table["p_holm"].to_numpy(dtype=float), stats.holm_bonferroni(raw), atol=1e-4)
    assert table.attrs["multiple_comparison"]["family_size"] == len(table)
    assert bool(table["significant_fdr_05"].any())


def test_pipeline_bundle_carries_multiple_comparison_block():
    cohort = synthetic.generate_cohort(subjects=6, days=8)
    bundle = pipeline.analyze(cohort, paired=True)
    block = bundle["meta"]["multiple_comparison"]
    assert block["method"] == "benjamini_hochberg"
    assert block["alpha"] == 0.05
    assert block["family_size"] == len(bundle["comparison"])
    assert bundle["multiple_comparison"]["family_size"] == len(bundle["comparison"])
    for row in bundle["comparison"]:
        assert "p_value" in row and "p_holm" in row and "q_value_bh" in row
        assert isinstance(row["significant_fdr_05"], bool)


def test_fdr_rejection_count_matches_q_threshold():
    cohort = synthetic.generate_cohort(subjects=6, days=8)
    bundle = pipeline.analyze(cohort, paired=True)
    rows = bundle["comparison"]
    expected = sum(1 for row in rows if row["q_value_bh"] is not None and row["q_value_bh"] <= 0.05)
    assert bundle["meta"]["multiple_comparison"]["rejected_bh_fdr"] == expected


def test_compare_table_without_conditions_has_no_rows_and_no_crash():
    frame = pd.DataFrame({"timestamp": ["2026-05-06 07:10"], "sbp": [120]})
    table = stats.compare_table(frame, metric_columns=["sbp"])
    assert table.empty
