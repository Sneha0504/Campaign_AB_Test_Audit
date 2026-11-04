"""Tests for test-validity checks (src/validate_test.py)."""

from __future__ import annotations

from src.validate_test import srm_test


def test_srm_flags_known_bad_split() -> None:
    """A 50/50 observed split against an intended 96/4 design must FAIL (critical)."""
    # Intended control share 0.04; observed is wildly off (5000 / 5000).
    result = srm_test(n_treatment=5000, n_control=5000, intended_control_share=0.04, alpha=0.05)
    assert result["passed"] is False
    assert result["severity"] == "critical"
    assert result["p_value"] < 0.05
    assert "FAIL" in result["verdict"]


def test_srm_passes_matching_split() -> None:
    """An observed split equal to the intended design must PASS (info)."""
    # Intended 0.04 control => expected 9600 / 400 at n=10000; feed exactly that.
    result = srm_test(n_treatment=9600, n_control=400, intended_control_share=0.04, alpha=0.05)
    assert result["passed"] is True
    assert result["severity"] == "info"
    assert result["p_value"] > 0.05
    # Chi-square should be ~0 for a perfect match.
    assert result["chi2"] < 1e-6
    assert "PASS" in result["verdict"]


def test_srm_sensitivity_different_assumption_fails() -> None:
    """The same near-0.04 counts tested against a 0.05 design should FAIL."""
    passing = srm_test(9600, 400, intended_control_share=0.04, alpha=0.05)
    failing = srm_test(9600, 400, intended_control_share=0.05, alpha=0.05)
    assert passing["passed"] is True
    assert failing["passed"] is False  # verdict depends on the assumed design
