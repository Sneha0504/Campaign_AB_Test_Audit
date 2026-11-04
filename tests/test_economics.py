"""Tests for the economics + reallocation logic (src/economics.py)."""

from __future__ import annotations

import math

from src.economics import headline_economics, reallocation_scenario


def _synthetic_analysis() -> dict:
    """A tiny analysis dict with round numbers for hand-checkable economics."""
    return {
        "overall": {
            "n_ad": 1000,
            "rate_ad": 0.02,
            "rate_psa": 0.01,
        },
        "exposure": {
            "total_ad_impressions": 100_000,
            "bands": [
                {
                    "band": "low",
                    "ad_impressions": 1000,
                    "incremental_conversions": -5.0,  # eff = -0.005
                    "psa_reliable": True,
                    "significant_bh": False,
                    "abs_diff_pp": -0.5,
                    "ci_low_pp": -1.2,
                    "ci_high_pp": 0.3,
                    "p_raw": 0.3,
                    "p_bh": 0.6,
                },
                {
                    "band": "high",
                    "ad_impressions": 2000,
                    "incremental_conversions": 40.0,  # eff = 0.02
                    "psa_reliable": True,
                    "significant_bh": True,
                    "abs_diff_pp": 2.0,
                    "ci_low_pp": 1.5,
                    "ci_high_pp": 2.5,
                    "p_raw": 1e-6,
                    "p_bh": 1e-6,
                },
            ],
        },
    }


def test_headline_economics_identities() -> None:
    """Media cost, incremental, cost/incremental, value, ROAS, break-evens.

    impressions = 100000, CPM = 10 -> media cost = 100000*10/1000 = 1000
    incremental (causal) = n_ad*(rate_ad-rate_psa) = 1000*(0.02-0.01) = 10
    cost per incremental = 1000/10 = 100
    value = 10 * 25 = 250 ; ROAS = 250/1000 = 0.25
    break-even value/conv = 1000/10 = 100 ; break-even CPM = 250*1000/100000 = 2.5
    """
    h = headline_economics(_synthetic_analysis(), {"cpm": 10.0, "value_per_conversion": 25.0})
    assert math.isclose(h["total_media_cost"], 1000.0, abs_tol=1e-9)
    assert math.isclose(h["incremental_conversions_causal"], 10.0, abs_tol=1e-9)
    assert math.isclose(h["cost_per_incremental_conversion"], 100.0, abs_tol=1e-9)
    assert math.isclose(h["value_of_incremental"], 250.0, abs_tol=1e-9)
    assert math.isclose(h["roas"], 0.25, abs_tol=1e-12)
    assert h["profitable_at_assumptions"] is False
    assert math.isclose(h["breakeven_value_per_conversion"], 100.0, abs_tol=1e-9)
    assert math.isclose(h["breakeven_cpm"], 2.5, abs_tol=1e-9)
    # Identity: value == incremental * value_per_conversion; ROAS == value / cost.
    assert math.isclose(
        h["value_of_incremental"], h["incremental_conversions_causal"] * 25.0, abs_tol=1e-9
    )
    assert math.isclose(h["roas"], h["value_of_incremental"] / h["total_media_cost"], abs_tol=1e-12)


def test_reallocation_arithmetic_consistency() -> None:
    """impressions_moved * efficiency == reported conversion change, both variants.

    source = low (eff -0.005), dest = high (eff 0.02), share 0.5, value/conv 10
    impressions_moved = 0.5 * 1000 = 500
    conservative = 500 * 0.02 = 10.0
    optimistic   = 500 * (0.02 - (-0.005)) = 500 * 0.025 = 12.5 = gained - removed
    """
    rc = reallocation_scenario(
        _synthetic_analysis(), {"reallocation_share": 0.5, "value_per_conversion": 10.0}
    )
    assert rc["source_band"] == "low"
    assert rc["dest_band"] == "high"
    assert math.isclose(rc["impressions_moved"], 500.0, abs_tol=1e-9)

    eff_source = rc["source_efficiency_per_1k"] / 1000.0
    eff_dest = rc["dest_efficiency_per_1k"] / 1000.0
    moved = rc["impressions_moved"]

    # Conservative: impressions_moved * eff_dest == net_conservative == gained_at_dest.
    assert math.isclose(moved * eff_dest, rc["net_conversion_change_conservative"], abs_tol=1e-9)
    assert math.isclose(
        rc["conversions_gained_at_dest"], rc["net_conversion_change_conservative"], abs_tol=1e-9
    )
    assert math.isclose(rc["net_conversion_change_conservative"], 10.0, abs_tol=1e-9)

    # Optimistic: impressions_moved * (eff_dest - eff_source) == net == gained - removed.
    assert math.isclose(
        moved * (eff_dest - eff_source), rc["net_conversion_change_optimistic"], abs_tol=1e-9
    )
    assert math.isclose(
        rc["conversions_gained_at_dest"] - rc["conversions_removed_at_source"],
        rc["net_conversion_change_optimistic"],
        abs_tol=1e-9,
    )
    assert math.isclose(rc["net_conversion_change_optimistic"], 12.5, abs_tol=1e-9)

    # Value identities.
    assert math.isclose(rc["net_value_change_conservative"], 10.0 * 10.0, abs_tol=1e-9)
    assert math.isclose(rc["net_value_change_optimistic"], 12.5 * 10.0, abs_tol=1e-9)


def test_reallocation_flags_nonsignificant_source() -> None:
    """The non-significant source band is surfaced so the caveat holds."""
    rc = reallocation_scenario(
        _synthetic_analysis(), {"reallocation_share": 0.25, "value_per_conversion": 25.0}
    )
    assert rc["source_significant_bh"] is False
    assert "source_not_significant_note" in rc
    assert "winners_curse_note" in rc
    # Conservative should be the smaller (more defensible) magnitude here.
    assert rc["net_conversion_change_conservative"] < rc["net_conversion_change_optimistic"]
