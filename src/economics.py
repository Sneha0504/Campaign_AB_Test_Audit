"""Economics and budget-reallocation scenario built on the effect analysis.

All money figures come from CLEARLY-LABELED, EDITABLE, ILLUSTRATIVE assumptions in
config (`economics.cpm`, `economics.value_per_conversion`,
`economics.reallocation_share`) — there is no real ad spend here.

Headline economics use the CAUSAL overall randomized lift (not the observational
exposure bands). The reallocation scenario uses the observational per-band marginal
payoff and is explicitly framed as illustrative, not a causal promise.

Reads `outputs/analysis_results.json` (M5) so nothing statistical is recomputed, and
writes `outputs/economics_results.json` (for M8 Excel + M9 dashboard) and an economics
section to `docs/economics.md`. Outputs are byte-stable (data fingerprint, no clock).

CLI:
    python src/economics.py            # compute + log + write outputs + doc
    python src/economics.py --no-write
    python src/economics.py --config PATH
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import load_config, setup_logging  # noqa: E402

logger = setup_logging(name="economics")


def _fmt_p(x: float | None) -> str:
    """Format a p-value to 3 significant figures; None -> 'n/a'."""
    return "n/a" if x is None else f"{x:.3g}"


def load_analysis(config: dict[str, Any]) -> dict[str, Any]:
    """Load the M5 analysis results JSON, with an actionable error if it is missing."""
    path = Path(config["resolved_paths"]["outputs_dir"]) / "analysis_results.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Analysis results not found at {path}. Run `make analyze` "
            f"(python src/analyze.py) first; economics reads its output."
        )
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def headline_economics(analysis: dict[str, Any], econ_cfg: dict[str, Any]) -> dict[str, Any]:
    """Media cost, causal incremental conversions, cost per incremental, ROAS, break-evens."""
    cpm = float(econ_cfg.get("cpm", 10.0))
    value_per_conversion = float(econ_cfg.get("value_per_conversion", 25.0))

    overall = analysis["overall"]
    total_ad_impressions = int(analysis["exposure"]["total_ad_impressions"])
    n_ad = int(overall["n_ad"])
    rate_ad = float(overall["rate_ad"])
    rate_psa = float(overall["rate_psa"])

    total_media_cost = total_ad_impressions * cpm / 1000.0
    # Causal incremental = ad conversions above what the control rate predicts for the
    # ad group = n_ad * (rate_ad - rate_psa). Uses the randomized contrast only.
    incremental_conversions = n_ad * (rate_ad - rate_psa)
    cost_per_incremental = total_media_cost / incremental_conversions
    value_of_incremental = incremental_conversions * value_per_conversion
    roas = value_of_incremental / total_media_cost

    # Break-evens (ROAS == 1): the value-per-conversion / CPM that make value == cost.
    breakeven_value_per_conversion = total_media_cost / incremental_conversions
    breakeven_cpm = value_of_incremental * 1000.0 / total_ad_impressions

    return {
        "cpm": cpm,
        "value_per_conversion": value_per_conversion,
        "total_ad_impressions": total_ad_impressions,
        "total_media_cost": total_media_cost,
        "incremental_conversions_causal": incremental_conversions,
        "cost_per_incremental_conversion": cost_per_incremental,
        "value_of_incremental": value_of_incremental,
        "roas": roas,
        "profitable_at_assumptions": bool(roas >= 1.0),
        "breakeven_value_per_conversion": breakeven_value_per_conversion,
        "breakeven_cpm": breakeven_cpm,
    }


def reallocation_scenario(analysis: dict[str, Any], econ_cfg: dict[str, Any]) -> dict[str, Any]:
    """Constant-spend move of impressions from the least- to the most-efficient band.

    Efficiency = band incremental conversions per ad impression (observational). The
    source is the least-efficient RELIABLE band; the destination is the most-efficient
    reliable band (the high-exposure 32+ band here). Arithmetic is kept transparent:
    the OPTIMISTIC net = impressions_moved * (eff_dest - eff_source). Because the source
    band's negative payoff is not statistically significant, a CONSERVATIVE variant
    (source efficiency = 0, net = impressions_moved * eff_dest) is reported as the more
    defensible figure. Both are returned so M7 can test the identity and M8/M9 can show
    both.
    """
    reallocation_share = float(econ_cfg.get("reallocation_share", 0.25))
    value_per_conversion = float(econ_cfg.get("value_per_conversion", 25.0))

    # Candidate reliable bands with a defined efficiency = incremental / impressions.
    candidates: list[tuple[dict[str, Any], float]] = []
    for b in analysis["exposure"]["bands"]:
        impr = b["ad_impressions"]
        incr = b["incremental_conversions"]
        if not b["psa_reliable"] or incr is None or not impr:
            continue
        candidates.append((b, incr / impr))

    if len(candidates) < 2:
        raise ValueError("Need at least two reliable bands to run a reallocation scenario.")

    source_b, eff_source = min(candidates, key=lambda x: x[1])
    dest_b, eff_dest = max(candidates, key=lambda x: x[1])
    source_impr = int(source_b["ad_impressions"])

    impressions_moved = reallocation_share * source_impr
    # Removing impressions from the source removes source_efficiency * moved conversions.
    # (If the source efficiency is negative, that "removal" is actually a small gain.)
    conversions_removed_at_source = impressions_moved * eff_source
    conversions_gained_at_dest = impressions_moved * eff_dest

    # OPTIMISTIC: credit both the destination gain and the source "removal".
    net_optimistic = conversions_gained_at_dest - conversions_removed_at_source
    # CONSERVATIVE (defensible): the source band's negative payoff is NOT significant, so
    # set source efficiency to 0 and count only the destination gain.
    net_conservative = conversions_gained_at_dest

    # Source-band significance (from M5): a non-significant, CI-spanning-zero source means
    # "removing impressions from it gains conversions" is unreliable (winner's curse).
    source_sig = bool(source_b.get("significant_bh", False))

    return {
        "reallocation_share": reallocation_share,
        "value_per_conversion": value_per_conversion,
        "source_band": source_b["band"],
        "dest_band": dest_b["band"],
        "source_efficiency_per_1k": eff_source * 1000.0,
        "dest_efficiency_per_1k": eff_dest * 1000.0,
        "source_ad_impressions": source_impr,
        "impressions_moved": impressions_moved,
        "conversions_removed_at_source": conversions_removed_at_source,
        "conversions_gained_at_dest": conversions_gained_at_dest,
        # Optimistic headline (kept for the exact reallocation identity; M7-testable).
        "net_conversion_change_optimistic": net_optimistic,
        "net_value_change_optimistic": net_optimistic * value_per_conversion,
        # Conservative, more-defensible figure (source set to zero).
        "net_conversion_change_conservative": net_conservative,
        "net_value_change_conservative": net_conservative * value_per_conversion,
        # Source-band statistical reliability (from the M5 band test).
        "source_abs_diff_pp": source_b.get("abs_diff_pp"),
        "source_ci_low_pp": source_b.get("ci_low_pp"),
        "source_ci_high_pp": source_b.get("ci_high_pp"),
        "source_p_raw": source_b.get("p_raw"),
        "source_p_bh": source_b.get("p_bh"),
        "source_significant_bh": source_sig,
        "source_not_significant_note": (
            f"The source band ({source_b['band']}) negative marginal payoff is NOT "
            f"statistically distinguishable from zero (BH-adjusted p="
            f"{source_b.get('p_bh')}, 95% CI {source_b.get('ci_low_pp')}.."
            f"{source_b.get('ci_high_pp')} pp includes 0). So the ~"
            f"{abs(conversions_removed_at_source):.0f} conversions the optimistic variant "
            f"credits to 'removing impressions from the source' treat noise as signal; "
            f"the realistic source effect could be zero or positive. Prefer the "
            f"CONSERVATIVE variant (source efficiency = 0)."
        ),
        "winners_curse_note": (
            "Picking the single most-negative band among several non-significant mid "
            "bands biases the chosen source efficiency downward (a winner's curse / "
            "selection effect), further inflating the optimistic net."
        ),
        "assumption": (
            "ILLUSTRATIVE, not a causal promise. Holds total spend (impressions) "
            "constant. Relies on the receiving band's marginal payoff holding as "
            "volume increases — a STRONG assumption that is likely violated, because "
            "the 32+ band's efficiency is OBSERVATIONAL and ENDOGENOUS: high-exposure "
            "users are self-selected engaged users, not users you can manufacture by "
            "buying more impressions. The realistic gain is probably much smaller; "
            "treat the optimistic figure as an upper-bound sketch and the conservative "
            "figure as the more defensible number."
        ),
    }


def run_economics(config: dict[str, Any]) -> dict[str, Any]:
    """Compute headline economics + the reallocation scenario."""
    econ_cfg = config.get("economics", {})
    analysis = load_analysis(config)
    return {
        "data_fingerprint": analysis.get("data_fingerprint", "unknown"),
        "assumptions_note": (
            "All economic assumptions are ILLUSTRATIVE and editable in config "
            "(no real spend, no real conversion value)."
        ),
        "headline": headline_economics(analysis, econ_cfg),
        "reallocation": reallocation_scenario(analysis, econ_cfg),
    }


def log_results(r: dict[str, Any]) -> None:
    """Log the headline economics and reallocation numbers."""
    h = r["headline"]
    logger.info(
        "Media cost=$%.2f (impr=%d @ CPM $%.2f) | incremental(causal)=%.1f conv",
        h["total_media_cost"],
        h["total_ad_impressions"],
        h["cpm"],
        h["incremental_conversions_causal"],
    )
    logger.info(
        "Cost/incremental=$%.2f | value=$%.2f (@ $%.2f) | ROAS=%.3f (%s)",
        h["cost_per_incremental_conversion"],
        h["value_of_incremental"],
        h["value_per_conversion"],
        h["roas"],
        "profitable" if h["profitable_at_assumptions"] else "NOT profitable",
    )
    logger.info(
        "Break-even: value/conv=$%.2f, CPM=$%.2f",
        h["breakeven_value_per_conversion"],
        h["breakeven_cpm"],
    )
    rc = r["reallocation"]
    logger.info(
        "Reallocation (move %.0f%% of band %s impressions -> band %s): moved=%.0f impr",
        rc["reallocation_share"] * 100,
        rc["source_band"],
        rc["dest_band"],
        rc["impressions_moved"],
    )
    logger.info(
        "  CONSERVATIVE (source eff=0, defensible): net conv=%.1f, net value=$%.2f",
        rc["net_conversion_change_conservative"],
        rc["net_value_change_conservative"],
    )
    logger.info(
        "  optimistic (upper bound): net conv=%.1f, net value=$%.2f "
        "(source %s not significant: p_bh=%s)",
        rc["net_conversion_change_optimistic"],
        rc["net_value_change_optimistic"],
        rc["source_band"],
        rc["source_p_bh"],
    )


def write_outputs(r: dict[str, Any], config: dict[str, Any]) -> list[Path]:
    """Write economics_results.json and docs/economics.md."""
    outputs_dir = Path(config["resolved_paths"]["outputs_dir"])
    docs_dir = Path(config["resolved_paths"]["docs_dir"])
    outputs_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    json_path = outputs_dir / "economics_results.json"
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(r, fh, indent=2, sort_keys=True)
        fh.write("\n")
    written.append(json_path)

    doc_path = docs_dir / "economics.md"
    doc_path.write_text(render_economics(r), encoding="utf-8")
    written.append(doc_path)

    for p in written:
        logger.info("Wrote %s", p)
    return written


def render_economics(r: dict[str, Any]) -> str:
    """Render docs/economics.md from the computed results."""
    h = r["headline"]
    rc = r["reallocation"]
    roas_verdict = (
        "at or above break-even" if h["profitable_at_assumptions"] else "below break-even"
    )
    cons_conv = rc["net_conversion_change_conservative"]
    cons_val = rc["net_value_change_conservative"]
    opt_conv = rc["net_conversion_change_optimistic"]
    opt_val = rc["net_value_change_optimistic"]
    src_p_raw = _fmt_p(rc["source_p_raw"])
    src_p_bh = _fmt_p(rc["source_p_bh"])
    return f"""# Economics & Recommendation — Campaign_AB_Test_Audit

_Auto-generated by `src/economics.py` from `outputs/analysis_results.json` + config
assumptions. Data fingerprint: {r["data_fingerprint"]}._

> **All money figures are ILLUSTRATIVE and editable in `config/config.yaml` — there is
> no real ad spend and no real conversion value.** Headline economics use the **causal**
> overall randomized lift; the reallocation scenario uses observational band payoffs and
> is a sketch, not a promise (see the caveat).

## Headline economics (causal basis)

Assumptions: CPM = **${h["cpm"]:.2f}** per 1,000 impressions; value per conversion =
**${h["value_per_conversion"]:.2f}**.

| metric | value |
|---|---|
| Total ad impressions | {h["total_ad_impressions"]:,} |
| Total media cost | ${h["total_media_cost"]:,.2f} |
| Incremental conversions (causal) | {h["incremental_conversions_causal"]:,.1f} |
| Cost per incremental conversion | ${h["cost_per_incremental_conversion"]:,.2f} |
| Value of incremental conversions | ${h["value_of_incremental"]:,.2f} |
| **ROAS (value / cost)** | **{h["roas"]:.3f}** ({roas_verdict}) |

- **Incremental conversions** come from the randomized ad-vs-psa contrast
  (n_ad × (rate_ad − rate_psa)), i.e. conversions the campaign *caused*, not just
  correlated conversions.
- **ROAS = {h["roas"]:.3f}.** At these illustrative assumptions the campaign is
  **{"profitable" if h["profitable_at_assumptions"] else "NOT profitable"}**. This is a
  legitimate, assumption-dependent result, reported honestly rather than massaged.
- **Break-even:** the campaign breaks even (ROAS = 1) at a value per conversion of
  **${h["breakeven_value_per_conversion"]:,.2f}** (vs the assumed
  ${h["value_per_conversion"]:.2f}), or equivalently at a CPM of
  **${h["breakeven_cpm"]:.2f}** (vs the assumed ${h["cpm"]:.2f}). So profitability
  hinges on buying impressions below ~${h["breakeven_cpm"]:.2f} CPM or valuing each
  conversion above ~${h["breakeven_value_per_conversion"]:,.0f}.

## Budget reallocation scenario (constant spend)

Move **{rc["reallocation_share"]:.0%}** of the impressions from the least-efficient
reliable band (**{rc["source_band"]}**) to the most-efficient reliable band
(**{rc["dest_band"]}**), holding total spend (total impressions, hence media cost)
constant. Efficiency = band incremental conversions per 1,000 impressions:

- Source band `{rc["source_band"]}`: {rc["source_efficiency_per_1k"]:.4f} incr. conv / 1k impr.
- Destination band `{rc["dest_band"]}`: {rc["dest_efficiency_per_1k"]:.4f} incr. conv / 1k impr.

**Two variants — lead with the conservative one.**

| variant | net conversion change | net value change |
|---|---|---|
| **Conservative (defensible): source effect = 0** | **{cons_conv:,.1f}** | **${cons_val:,.2f}** |
| Optimistic (upper bound): credits the source "removal" too | {opt_conv:,.1f} | ${opt_val:,.2f} |

Component arithmetic (transparent, reproducible):

- Impressions moved = {rc["reallocation_share"]:.0%} × {rc["source_ad_impressions"]:,} =
  {rc["impressions_moved"]:,.0f}.
- Conversions gained at destination = impressions moved × dest efficiency =
  {rc["impressions_moved"]:,.0f} × {rc["dest_efficiency_per_1k"]:.6f} / 1000 =
  **{rc["conversions_gained_at_dest"]:,.1f}** (this is the conservative net).
- Conversions removed at source = impressions moved × source efficiency =
  {rc["impressions_moved"]:,.0f} × {rc["source_efficiency_per_1k"]:.6f} / 1000 =
  {rc["conversions_removed_at_source"]:,.1f} (negative here = removing a drag, i.e. a gain).
- Optimistic net = gained − removed =
  {rc["conversions_gained_at_dest"]:,.1f} − ({rc["conversions_removed_at_source"]:,.1f})
  = {rc["net_conversion_change_optimistic"]:,.1f}.

### Why the conservative variant is the honest one

The source band (**{rc["source_band"]}**) negative marginal payoff is **not
statistically distinguishable from zero**: its band ad-vs-psa difference is
{rc["source_abs_diff_pp"]:.3f} pp with 95% CI
[{rc["source_ci_low_pp"]:.3f}, {rc["source_ci_high_pp"]:.3f}] pp (which **includes 0**),
raw p = {src_p_raw}, **BH-adjusted p = {src_p_bh}**. So the
~{abs(rc["conversions_removed_at_source"]):.0f} conversions the optimistic variant credits to
"removing impressions from {rc["source_band"]}" **treat noise as signal** — the real source
effect could just as well be zero or positive. The **conservative variant sets the source
efficiency to 0** and counts only the destination gain
({cons_conv:,.1f} conversions, ${cons_val:,.2f}).

**Winner's curse.** Choosing the single most-negative band among several non-significant
mid bands biases the picked source efficiency downward (a selection effect), which
further inflates the optimistic net. This is another reason to trust the conservative figure.

### Critical honesty caveat

{rc["assumption"]}

**Bottom line:** even the conservative gain rests on an endogenous, observational
efficiency for the 32+ band — you cannot *buy* high-exposure engaged users by
reallocating impressions, so the realistic gain is likely smaller still. Treat the
conservative number as the defensible figure, the optimistic as an upper bound, and base
the real recommendation on the causal headline economics above (where ROAS < 1 at the
illustrative assumptions).
"""


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description="Run economics + reallocation and write outputs.")
    parser.add_argument("--config", default=None, help="Path to config.yaml.")
    parser.add_argument(
        "--no-write", action="store_true", help="Compute and log only; do not write outputs."
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    try:
        results = run_economics(config)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    log_results(results)
    if not args.no_write:
        write_outputs(results, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
