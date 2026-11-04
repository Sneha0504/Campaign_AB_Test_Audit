"""Tests for the effect-analysis helpers (src/analyze.py)."""

from __future__ import annotations

import math

import pandas as pd

from src.analyze import (
    _band_labels,
    assign_bands,
    benjamini_hochberg,
    two_proportion_ztest,
)

EDGES = [1, 2, 4, 8, 16, 32]


def test_two_proportion_ztest_matches_hand_calc() -> None:
    """Hand-worked tiny example.

    treatment: 20/100 => p_a = 0.20 ; control: 10/100 => p_b = 0.10 ; diff = 0.10
    pooled p = (20+10)/(100+100) = 0.15
    se_pool = sqrt(0.15 * 0.85 * (1/100 + 1/100)) = sqrt(0.00255) = 0.05049752...
    z = 0.10 / 0.05049752 = 1.980295...
    p = 2 * P(Z > 1.980295) ~= 0.047670
    se_unpooled = sqrt(0.2*0.8/100 + 0.1*0.9/100) = sqrt(0.0025) = 0.05
    95% CI = 0.10 +/- 1.959964*0.05 = [0.002002, 0.197998]
    relative lift = diff / p_b = 0.10 / 0.10 = 1.0
    """
    r = two_proportion_ztest(conv_a=20, n_a=100, conv_b=10, n_b=100, alpha=0.05)
    assert r["rate_a"] == 0.20
    assert r["rate_b"] == 0.10
    assert math.isclose(r["diff"], 0.10, abs_tol=1e-12)
    assert math.isclose(r["z"], 1.980295, abs_tol=1e-4)
    assert r["z"] > 0  # treatment > control
    assert math.isclose(r["p_value"], 0.047670, abs_tol=1e-4)
    assert math.isclose(r["ci_low"], 0.002002, abs_tol=1e-4)
    assert math.isclose(r["ci_high"], 0.197998, abs_tol=1e-4)
    assert math.isclose(r["relative_lift"], 1.0, abs_tol=1e-9)


def test_two_proportion_ztest_degenerate_returns_nan() -> None:
    """Empty groups should return NaN, not raise."""
    r = two_proportion_ztest(conv_a=0, n_a=0, conv_b=1, n_b=10, alpha=0.05)
    assert math.isnan(r["z"])
    assert math.isnan(r["p_value"])


def test_band_labels() -> None:
    """Labels derived from right-open edges."""
    assert _band_labels(EDGES) == ["1", "2-3", "4-7", "8-15", "16-31", "32+"]


def test_exposure_bucketing_edge_values() -> None:
    """Right-open banding maps the off-by-one-prone edge values correctly."""
    values = [1, 2, 3, 4, 7, 8, 15, 16, 31, 32, 2065]
    expected = ["1", "2-3", "2-3", "4-7", "4-7", "8-15", "8-15", "16-31", "16-31", "32+", "32+"]
    bands = assign_bands(pd.Series(values), EDGES)
    assert [str(b) for b in bands] == expected
    # No value in [1, inf) should be unbinned.
    assert bands.isna().sum() == 0


def test_benjamini_hochberg_hand_calc() -> None:
    """BH step-up on a hand-constructable vector (unsorted).

    p = [0.01, 0.04, 0.03, 0.005], m = 4
    sorted ascending: 0.005(i3), 0.01(i0), 0.03(i2), 0.04(i1)
    raw*m/rank: rank1 0.02, rank2 0.02, rank3 0.04, rank4 0.04
    step-up (monotone from the top): adj sorted = [0.02, 0.02, 0.04, 0.04]
    mapped back by index: i0=0.02, i1=0.04, i2=0.04, i3=0.02
    """
    adj = benjamini_hochberg([0.01, 0.04, 0.03, 0.005])
    assert math.isclose(adj[0], 0.02, abs_tol=1e-12)
    assert math.isclose(adj[1], 0.04, abs_tol=1e-12)
    assert math.isclose(adj[2], 0.04, abs_tol=1e-12)
    assert math.isclose(adj[3], 0.02, abs_tol=1e-12)
    # Monotone non-decreasing when ordered by the raw p-value.
    order = sorted(range(4), key=lambda i: [0.01, 0.04, 0.03, 0.005][i])
    adj_sorted = [adj[i] for i in order]
    assert adj_sorted == sorted(adj_sorted)


def test_benjamini_hochberg_stepup_min_matters() -> None:
    """A vector where the step-up `min` actually changes the result.

    p = [0.01, 0.011, 0.04], m = 3 (already ascending)
    raw*m/rank: rank1 0.01*3/1 = 0.03, rank2 0.011*3/2 = 0.0165, rank3 0.04*3/3 = 0.04
    step-up (monotone from the top) pulls rank1 down from 0.03 to 0.0165:
    BH = [0.0165, 0.0165, 0.04]. Without the step-up `min`, adj[0] would be 0.03 and FAIL.
    """
    adj = benjamini_hochberg([0.01, 0.011, 0.04])
    assert math.isclose(adj[0], 0.0165, abs_tol=1e-12)
    assert math.isclose(adj[1], 0.0165, abs_tol=1e-12)
    assert math.isclose(adj[2], 0.04, abs_tol=1e-12)
    assert adj == sorted(adj)  # already in raw-p order, so must be non-decreasing


def test_benjamini_hochberg_passes_through_none() -> None:
    """None / NaN entries are preserved, adjustment uses only valid p-values."""
    adj = benjamini_hochberg([0.01, None, 0.02])
    assert adj[1] is None
    assert adj[0] is not None and adj[2] is not None
    # Two valid values: 0.01*2/1=0.02, 0.02*2/2=0.02 -> both 0.02.
    assert math.isclose(adj[0], 0.02, abs_tol=1e-12)
    assert math.isclose(adj[2], 0.02, abs_tol=1e-12)
