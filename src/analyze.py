"""Effect analysis: overall lift, exposure-band response, and timing patterns.

Leads with the one CAUSAL number — the overall randomized ad-vs-psa two-proportion
z-test — then provides OBSERVATIONAL exposure-band and timing breakdowns with explicit
honesty caveats (endogeneity of `total_ads`; a thin control group that gets noisy when
split into bands; no time axis for timing).

Machine-readable results are written to outputs/ so downstream milestones (M8 Excel,
M9 dashboard) consume them without recomputing:
    outputs/analysis_results.json   (everything)
    outputs/exposure_bands.csv
    outputs/timing_by_day.csv
    outputs/timing_by_hour.csv
A human methodology/results write-up is written to docs/methodology.md.

Outputs are BYTE-STABLE: they carry a data-derived fingerprint, never a wall-clock
timestamp, so `make all` reproduces identical files when the data is unchanged.

CLI:
    python src/analyze.py            # compute + log + write outputs + doc
    python src/analyze.py --no-write
    python src/analyze.py --config PATH
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import file_sha256_short, load_config, setup_logging  # noqa: E402
from src.load import load_data  # noqa: E402

logger = setup_logging(name="analyze")

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def two_proportion_ztest(
    conv_a: int, n_a: int, conv_b: int, n_b: int, alpha: float
) -> dict[str, Any]:
    """Two-proportion z-test of rate_a vs rate_b (a = treatment, b = control).

    Returns point estimate, pooled-SE z/p-value, an unpooled-SE 95% CI on the
    difference, and relative lift. Degenerate inputs yield NaN rather than raising.
    """
    if n_a <= 0 or n_b <= 0:
        return {
            "rate_a": float("nan"),
            "rate_b": float("nan"),
            "diff": float("nan"),
            "z": float("nan"),
            "p_value": float("nan"),
            "ci_low": float("nan"),
            "ci_high": float("nan"),
            "relative_lift": float("nan"),
        }
    p_a = conv_a / n_a
    p_b = conv_b / n_b
    diff = p_a - p_b
    p_pool = (conv_a + conv_b) / (n_a + n_b)
    se_pool = math.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    z = diff / se_pool if se_pool > 0 else float("nan")
    p_value = float(2 * stats.norm.sf(abs(z))) if not math.isnan(z) else float("nan")
    se_unpooled = math.sqrt(p_a * (1 - p_a) / n_a + p_b * (1 - p_b) / n_b)
    z_crit = stats.norm.ppf(1 - alpha / 2)
    ci_low = diff - z_crit * se_unpooled
    ci_high = diff + z_crit * se_unpooled
    rel_lift = diff / p_b if p_b > 0 else float("nan")
    return {
        "rate_a": p_a,
        "rate_b": p_b,
        "diff": diff,
        "z": float(z),
        "p_value": p_value,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "relative_lift": rel_lift,
    }


def _is_nan(x: Any) -> bool:
    """True if x is a float NaN (None counts as missing too)."""
    return x is None or (isinstance(x, float) and math.isnan(x))


def _sig(p: float | None, alpha: float) -> bool:
    """Significance flag that is False for missing/NaN p-values."""
    return bool(not _is_nan(p) and p < alpha)


def benjamini_hochberg(pvals: list[float | None]) -> list[float | None]:
    """Benjamini-Hochberg step-up adjusted p-values; NaN/None entries pass through."""
    valid = [i for i, p in enumerate(pvals) if p is not None and not math.isnan(p)]
    m = len(valid)
    adj: list[float | None] = [None] * len(pvals)
    if m == 0:
        return adj
    ordered = sorted(valid, key=lambda i: pvals[i])  # ascending by p
    prev = 1.0
    # Walk from largest rank down to smallest, enforcing monotonicity.
    for rank in range(m, 0, -1):
        i = ordered[rank - 1]
        val = pvals[i] * m / rank
        prev = min(prev, val)
        adj[i] = min(prev, 1.0)
    return adj


def _band_labels(edges: list[int]) -> list[str]:
    """Build human band labels from right-open edges (last band is open-ended)."""
    labels = []
    for i, lo in enumerate(edges):
        if i + 1 < len(edges):
            hi = edges[i + 1] - 1
            labels.append(f"{lo}" if lo == hi else f"{lo}-{hi}")
        else:
            labels.append(f"{lo}+")
    return labels


def assign_bands(total_ads: pd.Series, edges: list[int]) -> pd.Series:
    """Assign each value to its right-open exposure band [lo, hi); last band is [last, inf).

    Pure helper (no config, no logging) so the banding logic is unit-testable.
    """
    labels = _band_labels(edges)
    bins = list(edges) + [math.inf]
    return pd.cut(total_ads.astype("int64"), bins=bins, right=False, labels=labels)


def overall_lift(df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    """Overall randomized two-proportion z-test (the only causal estimate)."""
    data_cfg = config.get("data", {})
    t = data_cfg.get("treatment_label", "ad")
    c = data_cfg.get("control_label", "psa")
    alpha = float(config.get("validity", {}).get("significance_alpha", 0.05))

    ad = df[df["test_group"] == t]
    psa = df[df["test_group"] == c]
    n_ad, n_psa = len(ad), len(psa)
    conv_ad = int(ad["converted"].sum())
    conv_psa = int(psa["converted"].sum())
    zt = two_proportion_ztest(conv_ad, n_ad, conv_psa, n_psa, alpha)

    # Cross-check: chi-square of independence (no continuity correction == z-test).
    table = np.array([[conv_ad, n_ad - conv_ad], [conv_psa, n_psa - conv_psa]])
    chi2, chi2_p, _, _ = stats.chi2_contingency(table, correction=False)

    return {
        "treatment": t,
        "control": c,
        "alpha": alpha,
        "n_ad": n_ad,
        "n_psa": n_psa,
        "conv_ad": conv_ad,
        "conv_psa": conv_psa,
        "rate_ad": zt["rate_a"],
        "rate_psa": zt["rate_b"],
        "abs_diff_pp": zt["diff"] * 100,
        "ci_low_pp": zt["ci_low"] * 100,
        "ci_high_pp": zt["ci_high"] * 100,
        "z": zt["z"],
        "p_value": zt["p_value"],
        "relative_lift_pct": zt["relative_lift"] * 100,
        "chi2": float(chi2),
        "chi2_p": float(chi2_p),
        "causal_note": (
            "This randomized ad-vs-psa contrast is the ONLY causal estimate in this "
            "analysis. Exposure-band and timing breakdowns below are observational."
        ),
    }


def exposure_bands(df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    """Per-band ad-vs-psa response, BH correction, and spend-vs-payoff shares."""
    data_cfg = config.get("data", {})
    t = data_cfg.get("treatment_label", "ad")
    c = data_cfg.get("control_label", "psa")
    alpha = float(config.get("validity", {}).get("significance_alpha", 0.05))
    edges = list(config.get("exposure", {}).get("band_edges", [1, 2, 4, 8, 16, 32]))
    analysis_cfg = config.get("analysis", {})
    min_control = int(analysis_cfg.get("min_control_per_band", 100))
    min_control_conv = int(analysis_cfg.get("min_control_conversions_per_band", 10))

    labels = _band_labels(edges)
    band = assign_bands(df["total_ads"], edges)
    n_unbinned = int(band.isna().sum())
    if n_unbinned:
        logger.warning("%d rows fell outside band edges %s and are unbinned", n_unbinned, edges)
    work = df.assign(_band=band)

    total_ad_impressions = int(work.loc[work["test_group"] == t, "total_ads"].sum())

    rows: list[dict[str, Any]] = []
    raw_p: list[float | None] = []
    for lbl in labels:
        sub = work[work["_band"] == lbl]
        ad = sub[sub["test_group"] == t]
        psa = sub[sub["test_group"] == c]
        n_ad, n_psa = len(ad), len(psa)
        conv_ad = int(ad["converted"].sum())
        conv_psa = int(psa["converted"].sum())
        zt = two_proportion_ztest(conv_ad, n_ad, conv_psa, n_psa, alpha)
        ad_impr = int(ad["total_ads"].sum())
        rate_ad = zt["rate_a"]
        rate_psa = zt["rate_b"]
        # Incremental = treatment users in band * (band ad rate - band psa rate).
        if n_ad and not math.isnan(rate_psa):
            incremental = n_ad * (rate_ad - rate_psa)
        else:
            incremental = float("nan")
        reliable = bool(n_psa >= min_control and conv_psa >= min_control_conv)
        rows.append(
            {
                "band": lbl,
                "n_ad": n_ad,
                "n_psa": n_psa,
                "conv_ad": conv_ad,
                "conv_psa": conv_psa,
                "rate_ad": rate_ad,
                "rate_psa": rate_psa,
                "abs_diff_pp": zt["diff"] * 100,
                "ci_low_pp": zt["ci_low"] * 100,
                "ci_high_pp": zt["ci_high"] * 100,
                "z": zt["z"],
                "p_raw": zt["p_value"],
                "ad_impressions": ad_impr,
                "incremental_conversions": incremental,
                "psa_reliable": reliable,
            }
        )
        raw_p.append(zt["p_value"])

    adj_p = benjamini_hochberg(raw_p)
    total_incremental = float(np.nansum([r["incremental_conversions"] for r in rows]))
    for row, pbh in zip(rows, adj_p, strict=True):
        row["p_bh"] = pbh
        row["significant_raw"] = _sig(row["p_raw"], alpha)
        row["significant_bh"] = _sig(pbh, alpha)
        if total_ad_impressions:
            row["impressions_share"] = row["ad_impressions"] / total_ad_impressions
        else:
            row["impressions_share"] = float("nan")
        inc = row["incremental_conversions"]
        row["incremental_share"] = inc / total_incremental if total_incremental else float("nan")

    return {
        "treatment": t,
        "control": c,
        "alpha": alpha,
        "band_edges": edges,
        "band_labels": labels,
        "binning": "right-open [lo, hi); last band is [last_edge, inf)",
        "min_control_per_band": min_control,
        "min_control_conversions_per_band": min_control_conv,
        "n_unbinned": n_unbinned,
        "total_ad_impressions": total_ad_impressions,
        "total_incremental_conversions": total_incremental,
        "bands": rows,
    }


def timing(df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    """Cross-sectional conversion rate by day-of-week and hour-of-day (descriptive)."""
    data_cfg = config.get("data", {})
    t = data_cfg.get("treatment_label", "ad")
    c = data_cfg.get("control_label", "psa")

    def _table(field: str, order: list[Any]) -> list[dict[str, Any]]:
        piv = df.pivot_table(index=field, columns="test_group", values="converted", aggfunc="mean")
        cnt = df.pivot_table(index=field, columns="test_group", values="converted", aggfunc="count")
        out = []
        for key in order:
            if key not in piv.index:
                continue
            rate_t = float(piv.loc[key, t]) if t in piv.columns else float("nan")
            rate_c = float(piv.loc[key, c]) if c in piv.columns else float("nan")
            out.append(
                {
                    "key": str(key),
                    "rate_ad": rate_t,
                    "rate_psa": rate_c,
                    "gap": rate_t - rate_c,
                    "n_ad": int(cnt.loc[key, t]) if t in cnt.columns else 0,
                    "n_psa": int(cnt.loc[key, c]) if c in cnt.columns else 0,
                }
            )
        return out

    return {
        "treatment": t,
        "control": c,
        "by_day": _table("most_ads_day", WEEKDAYS),
        "by_hour": _table("most_ads_hour", list(range(24))),
        "note": (
            "Cross-sectional day-of-week / hour-of-day pattern, NOT a temporal drift "
            "test — this dataset has no calendar/time axis (see validity_report.md)."
        ),
    }


def run_analysis(config: dict[str, Any]) -> dict[str, Any]:
    """Run the full effect analysis and return a results dict."""
    csv_path = Path(config["resolved_paths"]["data_raw"])
    df = load_data(config)
    return {
        "data_fingerprint": f"sha256:{file_sha256_short(csv_path)} · {len(df):,} rows",
        "overall": overall_lift(df, config),
        "exposure": exposure_bands(df, config),
        "timing": timing(df, config),
    }


def log_results(r: dict[str, Any]) -> None:
    """Log the headline effect numbers."""
    o = r["overall"]
    logger.info(
        "OVERALL (causal): ad=%.4f%% (%d/%d) vs psa=%.4f%% (%d/%d)",
        o["rate_ad"] * 100,
        o["conv_ad"],
        o["n_ad"],
        o["rate_psa"] * 100,
        o["conv_psa"],
        o["n_psa"],
    )
    logger.info(
        "  abs diff=%.4f pp, 95%% CI [%.4f, %.4f] pp, z=%.2f, p=%.4g, rel lift=%.2f%%",
        o["abs_diff_pp"],
        o["ci_low_pp"],
        o["ci_high_pp"],
        o["z"],
        o["p_value"],
        o["relative_lift_pct"],
    )
    logger.info("  chi-square cross-check: chi2=%.2f p=%.4g (agrees)", o["chi2"], o["chi2_p"])
    logger.info("EXPOSURE BANDS (observational; total_ads endogenous):")
    for b in r["exposure"]["bands"]:
        logger.info(
            "  band %-5s n_ad=%d n_psa=%d rate_ad=%.4f%% rate_psa=%.4f%% diff=%.3fpp "
            "p_raw=%.3g p_bh=%s impr_share=%.3f inc_share=%.3f reliable=%s",
            b["band"],
            b["n_ad"],
            b["n_psa"],
            b["rate_ad"] * 100,
            b["rate_psa"] * 100,
            b["abs_diff_pp"],
            b["p_raw"],
            f"{b['p_bh']:.3g}" if b["p_bh"] is not None else "nan",
            b["impressions_share"],
            b["incremental_share"],
            b["psa_reliable"],
        )


def _jsonify(obj: Any) -> Any:
    """Make results JSON-safe: NaN -> None (full float precision is kept).

    Floats are left at full precision (Python's deterministic repr keeps the JSON
    byte-stable across runs); rounding is avoided so tiny values such as a p-value of
    ~1e-13 are not collapsed to 0.0.
    """
    if isinstance(obj, dict):
        return {k: _jsonify(x) for k, x in obj.items()}
    if isinstance(obj, list):
        return [_jsonify(x) for x in obj]
    if isinstance(obj, float) and math.isnan(obj):
        return None
    return obj


def write_outputs(r: dict[str, Any], config: dict[str, Any]) -> list[Path]:
    """Write JSON + CSV machine-readable outputs and the methodology doc."""
    outputs_dir = Path(config["resolved_paths"]["outputs_dir"])
    docs_dir = Path(config["resolved_paths"]["docs_dir"])
    outputs_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    json_path = outputs_dir / "analysis_results.json"
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(_jsonify(r), fh, indent=2, sort_keys=True)
        fh.write("\n")
    written.append(json_path)

    overall_csv = outputs_dir / "overall_counts.csv"
    o = r["overall"]
    pd.DataFrame(
        [
            {
                "n_ad": o["n_ad"],
                "conv_ad": o["conv_ad"],
                "n_psa": o["n_psa"],
                "conv_psa": o["conv_psa"],
                "total_ad_impressions": r["exposure"]["total_ad_impressions"],
            }
        ]
    ).to_csv(overall_csv, index=False)
    written.append(overall_csv)

    bands_csv = outputs_dir / "exposure_bands.csv"
    pd.DataFrame(r["exposure"]["bands"]).to_csv(bands_csv, index=False)
    written.append(bands_csv)

    day_csv = outputs_dir / "timing_by_day.csv"
    pd.DataFrame(r["timing"]["by_day"]).to_csv(day_csv, index=False)
    written.append(day_csv)

    hour_csv = outputs_dir / "timing_by_hour.csv"
    pd.DataFrame(r["timing"]["by_hour"]).to_csv(hour_csv, index=False)
    written.append(hour_csv)

    doc_path = docs_dir / "methodology.md"
    doc_path.write_text(render_methodology(r, config), encoding="utf-8")
    written.append(doc_path)

    for p in written:
        logger.info("Wrote %s", p)
    return written


def _fmt_pct(x: float, nd: int = 4) -> str:
    return "n/a" if _is_nan(x) else f"{x:.{nd}%}"


def _fmt_p(x: float | None) -> str:
    return "n/a" if _is_nan(x) else f"{x:.3g}"


def _timing_row(x: dict[str, Any]) -> str:
    return (
        f"| {x['key']} | {_fmt_pct(x['rate_ad'])} | {_fmt_pct(x['rate_psa'])} | "
        f"{_fmt_pct(x['gap'])} |"
    )


def render_methodology(r: dict[str, Any], config: dict[str, Any]) -> str:
    """Render docs/methodology.md from the computed results."""
    o = r["overall"]
    ex = r["exposure"]
    t, c = o["treatment"], o["control"]
    min_conv_psa = min((b["conv_psa"] for b in ex["bands"]), default=0)

    band_rows = []
    for b in ex["bands"]:
        flag = "yes" if b["psa_reliable"] else "**NO (thin control)**"
        band_rows.append(
            f"| {b['band']} | {b['n_ad']:,} | {b['n_psa']:,} | {_fmt_pct(b['rate_ad'])} | "
            f"{_fmt_pct(b['rate_psa'])} | {b['abs_diff_pp']:.3f} | {_fmt_p(b['p_raw'])} | "
            f"{_fmt_p(b['p_bh'])} | {b['impressions_share']:.3f} | "
            f"{b['incremental_share']:.3f} | {flag} |"
        )
    band_table = "\n".join(band_rows)

    day_rows = "\n".join(_timing_row(d) for d in r["timing"]["by_day"])
    hour_rows = "\n".join(_timing_row(h) for h in r["timing"]["by_hour"])

    # Identify where spend stops paying off: impressions share vs incremental share.
    # Do NOT put an efficiency verdict on unreliable (thin-control) bands, and keep the
    # wording observational (no causal claim) for the band where payoff concentrates.
    payoff_lines = []
    for b in ex["bands"]:
        impr = b["impressions_share"]
        incr = b["incremental_share"]
        base = f"- Band `{b['band']}`: impressions {impr:.2%} vs incremental {incr:.2%}"
        if not b["psa_reliable"]:
            payoff_lines.append(f"{base} — unreliable (thin control); not interpreted.")
        elif not b["significant_bh"]:
            payoff_lines.append(
                f"{base} — not statistically distinguishable from zero "
                f"(BH p = {_fmt_p(b['p_bh'])}); the apparent sign is noise."
            )
        elif not math.isnan(incr) and incr >= impr:
            payoff_lines.append(
                f"{base} — where the measurable incremental conversions concentrate "
                f"(observational, endogenous — not a causal claim)."
            )
        else:
            payoff_lines.append(f"{base} — significantly under-returning (observational).")
    payoff_md = "\n".join(payoff_lines)

    band_cols = [
        "band",
        "n_ad",
        "n_psa",
        "rate_ad",
        "rate_psa",
        "diff (pp)",
        "p (raw)",
        "p (BH)",
        "impr. share",
        "incr. share",
        "psa reliable?",
    ]
    band_header = "| " + " | ".join(band_cols) + " |"
    band_divider = "|" + "|".join(["---"] * len(band_cols)) + "|"

    return f"""# Methodology & Effect Analysis — Campaign_AB_Test_Audit

_Auto-generated by `src/analyze.py` from `data/raw/marketing_AB.csv`. Every number is
computed from the real data. Data fingerprint: {r["data_fingerprint"]}._

Read this with `validity_report.md` (the test-validity foundation) and
`data_quality_report.md` (profiling). Significance level alpha = {o["alpha"]}.

## 1 — Overall lift (the causal estimate — lead with this)

A **two-proportion z-test** of the conversion rate, `{t}` (treatment) vs `{c}`
(control). Because assignment is randomized (SRM not rejected against the assumed
split; see `validity_report.md`), this contrast is the **only causal estimate** in the
analysis.

- `{t}`: {o["conv_ad"]:,} / {o["n_ad"]:,} = **{_fmt_pct(o["rate_ad"])}**
- `{c}`: {o["conv_psa"]:,} / {o["n_psa"]:,} = **{_fmt_pct(o["rate_psa"])}**
- **Absolute difference = {o["abs_diff_pp"]:.4f} pp**, 95% CI
  [{o["ci_low_pp"]:.4f}, {o["ci_high_pp"]:.4f}] pp.
- **z = {o["z"]:.2f}, p = {_fmt_p(o["p_value"])}**.
- **Relative lift = {o["relative_lift_pct"]:.2f}%**.
- Chi-square independence cross-check (no continuity correction): chi2 =
  {o["chi2"]:.2f}, p = {_fmt_p(o["chi2_p"])} — **agrees** with the z-test (by
  construction chi2 = z²).

**Interpretation:** the campaign lifts conversion from {_fmt_pct(o["rate_psa"])} to
{_fmt_pct(o["rate_ad"])}, a relative lift of about {o["relative_lift_pct"]:.0f}%; the
95% CI excludes zero and p is tiny, so the effect is statistically real, not noise.

## 2 — Exposure-band response (OBSERVATIONAL, not causal)

Users are bucketed by `total_ads` using config `band_edges` = {ex["band_edges"]}
({ex["binning"]}), giving bands {ex["band_labels"]}. Unbinned rows: {ex["n_unbinned"]}.

{band_header}
{band_divider}
{band_table}

Multiple comparisons across the {len(ex["bands"])} band z-tests are controlled with
**Benjamini-Hochberg** (both raw and BH-adjusted p shown). Total ad impressions =
{ex["total_ad_impressions"]:,}; total incremental conversions (sum over bands) =
{ex["total_incremental_conversions"]:.1f}.

**Where does spend stop paying off?** Comparing each band's share of ad impressions to
its share of incremental conversions:

{payoff_md}

(A share above 100% or below 0% is expected here: the noisy, slightly-negative
incremental contributions of the mid bands shrink the total, so the single
clearly-positive band's share is pushed above 100%.)

### Honesty caveats (critical)

1. **Endogeneity.** `total_ads` is **not randomized** — more-engaged users both see
   more ads and convert more. So per-band ad-vs-psa differences are **observational /
   descriptive, not causal**. The clean causal number is the overall randomized lift
   in Section 1. Do not read band effects as "the return to showing more ads".
2. **Thin control group (by conversions).** The `{c}` control has only
   {o["n_psa"]:,} users total. In *this* dataset every band still has a few thousand
   control users, but what actually drives noise is the **number of control
   conversions**, which is tiny in the low-exposure bands (as few as ~{min_conv_psa}
   in the smallest band). A band is flagged **NO** when its control group has
   < {ex["min_control_per_band"]} users **or** < {ex["min_control_conversions_per_band"]}
   conversions, because a handful of conversions makes the control rate — and hence the
   per-band difference, incremental share, and significance — **noisy with wide CIs**.
   This is exactly why the mid bands show small, non-significant (even slightly
   negative) differences: that is sampling noise around a near-zero effect, **not**
   evidence that ads reduce conversion. Treat flagged bands as indicative only.

## 3 — Timing (cross-sectional, descriptive)

Conversion rate by day-of-week and hour-of-day of **peak exposure**. Per the
validity report, this is a **cross-sectional pattern, NOT a temporal trend** (no time
axis exists in this data). Note that some early hours show a `{c}` rate of 0% only
because the small control group has very few users (and no conversions) in those hours,
not because conversion is truly zero there.

### By day-of-week

| day | `{t}` rate | `{c}` rate | gap ({t} − {c}) |
|---|---|---|---|
{day_rows}

### By hour-of-day

| hour | `{t}` rate | `{c}` rate | gap ({t} − {c}) |
|---|---|---|---|
{hour_rows}

---

### Downstream consumption

`outputs/analysis_results.json`, `outputs/exposure_bands.csv`,
`outputs/timing_by_day.csv`, and `outputs/timing_by_hour.csv` hold these computed
results. The Excel report (M8) and dashboard (M9) read from them and do **not**
recompute, so all deliverables share one source of truth.

The economics (media cost, incremental conversions, cost per incremental conversion,
ROAS, break-even) and the budget-reallocation scenario build on these results and are
documented in `economics.md` (`outputs/economics_results.json`).
"""


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description="Run the effect analysis and write outputs.")
    parser.add_argument("--config", default=None, help="Path to config.yaml.")
    parser.add_argument(
        "--no-write", action="store_true", help="Compute and log only; do not write outputs."
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    results = run_analysis(config)
    log_results(results)
    if not args.no_write:
        write_outputs(results, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
