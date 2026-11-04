"""Test-validity checks — the foundation the whole audit stands on.

Three checks, each reported with scrupulous honesty about what this dataset can
and cannot validate:

1. Sample Ratio Mismatch (SRM): chi-square goodness-of-fit of observed ad/psa
   counts against the INTENDED design split (an assumption from config), with a
   sensitivity note showing the result's dependence on that assumption.
2. Group balance: this dataset has NO genuine pre-treatment covariate, so a true
   balance check is impossible. We say so, then provide a clearly-labeled
   DESCRIPTIVE cross-group comparison only.
3. Novelty / time-drift: this dataset has NO calendar/absolute-time axis, so a
   genuine time-drift confound check is impossible. We say so, then provide a
   clearly-labeled cross-sectional day/hour conversion pattern only.

Results are logged and written to docs/validity_report.md. Every number is computed
from the real data; generated docs use a DATA-DERIVED fingerprint (no wall-clock
timestamp) so regeneration is byte-identical when the data is unchanged.

CLI:
    python src/validate_test.py            # compute + log + write report
    python src/validate_test.py --no-write
    python src/validate_test.py --config PATH
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import file_sha256_short, load_config, setup_logging  # noqa: E402
from src.load import load_data  # noqa: E402

logger = setup_logging(name="validate")

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def srm_test(
    n_treatment: int,
    n_control: int,
    intended_control_share: float,
    alpha: float,
) -> dict[str, Any]:
    """Chi-square goodness-of-fit SRM test of observed counts vs the intended split.

    Args:
        n_treatment: Observed treatment (ad) count.
        n_control: Observed control (psa) count.
        intended_control_share: Assumed design share of the control group.
        alpha: Significance level.

    Returns:
        A dict with observed/expected counts, chi-square statistic, p-value, a
        PASS/FAIL verdict (PASS = fail to reject = consistent with intended), and
        a severity. The FAIL branch marks the result ``critical`` because a real
        SRM would undermine the entire experiment.
    """
    total = n_treatment + n_control
    exp_control = total * intended_control_share
    exp_treatment = total * (1.0 - intended_control_share)
    obs = np.array([n_treatment, n_control], dtype=float)
    exp = np.array([exp_treatment, exp_control], dtype=float)
    chi2, p_value = stats.chisquare(f_obs=obs, f_exp=exp)
    passed = bool(p_value >= alpha)
    if passed:
        severity = "info"
        verdict = (
            f"PASS — consistent with the assumed {1 - intended_control_share:.0%}/"
            f"{intended_control_share:.0%} design (SRM not rejected). Note the "
            f"{intended_control_share:.2f} intended split is an ASSUMPTION that sits almost "
            f"exactly on the observed share, so this PASS is assumption-dependent."
        )
    else:
        severity = "critical"
        verdict = (
            "FAIL — SAMPLE RATIO MISMATCH DETECTED. This is a SERIOUS problem: a "
            "broken randomization undermines every downstream result. Do not trust "
            "the effect estimate until the cause is found."
        )
    return {
        "intended_control_share": intended_control_share,
        "observed_control_share": n_control / total if total else 0.0,
        "obs_treatment": n_treatment,
        "obs_control": n_control,
        "exp_treatment": exp_treatment,
        "exp_control": exp_control,
        "chi2": float(chi2),
        "p_value": float(p_value),
        "alpha": alpha,
        "passed": passed,
        "severity": severity,
        "verdict": verdict,
    }


def _contingency_test(df: pd.DataFrame, field: str, group_col: str) -> dict[str, Any]:
    """Chi-square test of independence for one field's distribution across groups."""
    table = pd.crosstab(df[field], df[group_col])
    chi2, p_value, dof, _ = stats.chi2_contingency(table)
    return {"field": field, "chi2": float(chi2), "p_value": float(p_value), "dof": int(dof)}


def balance_check(df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    """Best-available DESCRIPTIVE cross-group comparison (NOT a balance guarantee).

    No field here is pre-treatment, so this cannot verify balance; it only
    describes how the (post-exposure) fields differ across groups.
    """
    data_cfg = config.get("data", {})
    t = data_cfg.get("treatment_label", "ad")
    c = data_cfg.get("control_label", "psa")
    day = _contingency_test(df, "most_ads_day", "test_group")
    hour = _contingency_test(df, "most_ads_hour", "test_group")
    mean_ads = df.groupby("test_group")["total_ads"].mean().to_dict()
    return {
        "treatment": t,
        "control": c,
        "day_chi2": day,
        "hour_chi2": hour,
        "mean_total_ads": {k: float(v) for k, v in mean_ads.items()},
    }


def time_pattern_check(df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    """Cross-sectional conversion-by-day/hour pattern (NOT a temporal drift test).

    There is no calendar/absolute-time axis in this data, so a genuine novelty /
    time-drift confound check is impossible; this is a descriptive proxy only.
    """
    data_cfg = config.get("data", {})
    t = data_cfg.get("treatment_label", "ad")
    c = data_cfg.get("control_label", "psa")

    def _rate_table(index_field: str, order: list[Any] | None) -> pd.DataFrame:
        piv = df.pivot_table(
            index=index_field, columns="test_group", values="converted", aggfunc="mean"
        )
        if order is not None:
            piv = piv.reindex([x for x in order if x in piv.index])
        piv["gap"] = piv.get(t, np.nan) - piv.get(c, np.nan)
        return piv

    day_tbl = _rate_table("most_ads_day", WEEKDAYS)
    hour_tbl = _rate_table("most_ads_hour", list(range(24)))
    return {
        "treatment": t,
        "control": c,
        "day_overall_min": float(day_tbl[t].min()),
        "day_overall_max": float(day_tbl[t].max()),
        "day_table": day_tbl,
        "hour_table": hour_tbl,
    }


def run_validity(config: dict[str, Any]) -> dict[str, Any]:
    """Run all three validity checks and return a results dict."""
    data_cfg = config.get("data", {})
    t = data_cfg.get("treatment_label", "ad")
    c = data_cfg.get("control_label", "psa")
    validity_cfg = config.get("validity", {})
    alpha = float(validity_cfg.get("significance_alpha", 0.05))
    intended = float(validity_cfg.get("intended_control_share", 0.04))
    csv_path = Path(config["resolved_paths"]["data_raw"])

    df = load_data(config)
    n_t = int((df["test_group"] == t).sum())
    n_c = int((df["test_group"] == c).sum())

    sensitivity_share = float(validity_cfg.get("sensitivity_control_share", 0.05))
    srm = srm_test(n_t, n_c, intended, alpha)
    # Sensitivity: the SAME data against a different plausible assumed design.
    srm_sensitivity = srm_test(n_t, n_c, sensitivity_share, alpha)

    balance = balance_check(df, config)
    time_pattern = time_pattern_check(df, config)

    return {
        "data_fingerprint": f"sha256:{file_sha256_short(csv_path)} · {len(df):,} rows",
        "alpha": alpha,
        "srm": srm,
        "srm_sensitivity": srm_sensitivity,
        "balance": balance,
        "time_pattern": time_pattern,
    }


def log_results(r: dict[str, Any]) -> None:
    """Log the headline validity numbers."""
    srm = r["srm"]
    logger.info(
        "SRM: obs ad=%d psa=%d | exp ad=%.1f psa=%.1f | chi2=%.4f p=%.4g | %s",
        srm["obs_treatment"],
        srm["obs_control"],
        srm["exp_treatment"],
        srm["exp_control"],
        srm["chi2"],
        srm["p_value"],
        "PASS" if srm["passed"] else "FAIL",
    )
    sens = r["srm_sensitivity"]
    logger.info(
        "SRM sensitivity @ control share 0.05: chi2=%.1f p=%.4g | %s",
        sens["chi2"],
        sens["p_value"],
        "PASS" if sens["passed"] else "FAIL",
    )
    b = r["balance"]
    logger.info(
        "Balance (DESCRIPTIVE, not pre-treatment): day chi2=%.3f p=%.4g; hour chi2=%.3f p=%.4g",
        b["day_chi2"]["chi2"],
        b["day_chi2"]["p_value"],
        b["hour_chi2"]["chi2"],
        b["hour_chi2"]["p_value"],
    )
    logger.info("Mean total_ads by group (EXPECTED to differ): %s", b["mean_total_ads"])
    tp = r["time_pattern"]
    logger.info(
        "Time pattern (cross-sectional, NOT temporal): ad conv by day in [%.4f, %.4f]",
        tp["day_overall_min"],
        tp["day_overall_max"],
    )


def _fmt_pct(x: float) -> str:
    return f"{x:.4%}" if pd.notna(x) else "n/a"


def _day_table_md(tbl: pd.DataFrame, t: str, c: str) -> str:
    rows = []
    for idx, row in tbl.iterrows():
        rows.append(
            f"| {idx} | {_fmt_pct(row.get(t))} | {_fmt_pct(row.get(c))} | "
            f"{_fmt_pct(row.get('gap'))} |"
        )
    return "\n".join(rows)


def render_report(r: dict[str, Any], config: dict[str, Any]) -> str:
    """Render docs/validity_report.md from the computed results."""
    srm = r["srm"]
    sens = r["srm_sensitivity"]
    b = r["balance"]
    tp = r["time_pattern"]
    t, c = b["treatment"], b["control"]
    sens_share = sens["intended_control_share"]
    intended_share = srm["intended_control_share"]
    day_md = _day_table_md(tp["day_table"], t, c)
    hour_md = _day_table_md(tp["hour_table"], t, c)
    day_chi2 = b["day_chi2"]
    hour_chi2 = b["hour_chi2"]
    mean_t = b["mean_total_ads"].get(t, float("nan"))
    mean_c = b["mean_total_ads"].get(c, float("nan"))

    return f"""# Test-Validity Report — Campaign_AB_Test_Audit

_Auto-generated by `src/validate_test.py` from `data/raw/marketing_AB.csv`. Every
number is computed from the real data. Data fingerprint: {r["data_fingerprint"]}._

**This report is the foundation of the audit.** The effect analysis is only
trustworthy if the test was set up correctly. Below, each check states plainly what
this dataset **can** and **cannot** validate. Significance level alpha = {r["alpha"]}.

---

## 1 — Sample Ratio Mismatch (SRM)  ·  severity: {srm["severity"]}

Chi-square goodness-of-fit of the observed group counts against the **intended
design split**. The intended split is an **ASSUMPTION** (`intended_control_share` in
config = {srm["intended_control_share"]:.4f}); the dataset does not state its true
design ratio, so we test against the assumed value and report the observed one.

| group | observed | expected (intended) |
|---|---|---|
| `{t}` (treatment) | {srm["obs_treatment"]:,} | {srm["exp_treatment"]:,.1f} |
| `{c}` (control) | {srm["obs_control"]:,} | {srm["exp_control"]:,.1f} |

- Observed control share = **{srm["observed_control_share"]:.8f}** (intended
  {srm["intended_control_share"]:.4f}).
- **Chi-square = {srm["chi2"]:.4f}**, df = 1, **p-value = {srm["p_value"]:.4g}**.
- **Verdict ({'PASS' if srm['passed'] else 'FAIL'} at alpha={r["alpha"]}):** {srm["verdict"]}

### Sensitivity to the assumed design (transparency)

The verdict depends on the assumed intended split. Tested against a **different**
plausible design (control share {sens_share:.2f} → {1 - sens_share:.2f}/{sens_share:.2f})
on the *same* observed counts:

- Chi-square = {sens["chi2"]:.1f}, p-value = {sens["p_value"]:.4g} →
  **{'PASS' if sens["passed"] else 'FAIL'}**.

So the clean PASS is specific to the assumed {intended_share:.2f} control share; a
{sens_share:.2f} design would register as an SRM. The observed share
(~{srm["observed_control_share"]:.5f}) sits essentially exactly on {intended_share:.2f},
which is why {intended_share:.2f} passes decisively. The FAIL branch in the code is
real (it fires for the {sens_share:.2f} assumption) — it simply does not trigger for
the documented {intended_share:.2f} assumption. **If a real SRM occurred, it would be
flagged `critical` and called out as undermining the whole test.**

## 2 — Group balance  ·  severity: info (DESCRIPTIVE ONLY)

**A true balance check is NOT possible with this dataset.** Balance means the groups
look alike on **pre-treatment** characteristics. Here, *every* available field —
`total_ads`, `most_ads_day`, `most_ads_hour` — is **post-exposure** (determined by or
after treatment), and there is no user attribute recorded before assignment. So we
**cannot** verify covariate balance and do not claim to.

What we *can* do is a purely **descriptive** cross-group comparison, explicitly **not
a pre-treatment balance guarantee**:

- Distribution of `most_ads_day` across groups (chi-square of independence):
  chi2 = {day_chi2["chi2"]:.3f}, df = {day_chi2["dof"]}, p = {day_chi2["p_value"]:.4g}.
- Distribution of `most_ads_hour` across groups: chi2 = {hour_chi2["chi2"]:.3f},
  df = {hour_chi2["dof"]}, p = {hour_chi2["p_value"]:.4g}.
- Mean `total_ads` by group: `{t}` = {mean_t:.3f}, `{c}` = {mean_c:.3f}. `total_ads`
  is **post-exposure** (ads seen for `{t}`, PSA creatives seen for `{c}`), so it cannot
  serve as a balance covariate regardless of magnitude; any gap here reflects exposure,
  not a pre-treatment imbalance.

**Caveat:** with ~588k rows these tests are extremely high-powered, so even trivial
distributional differences can show small p-values; that is a statement about sample
size and post-exposure timing, not about randomization quality. Treat this section as
context, not validation.

## 3 — Novelty / time-drift  ·  severity: info (CROSS-SECTIONAL ONLY)

**A genuine time-drift / novelty confound check is NOT possible with this dataset.**
There is no calendar date, no timestamp, and no chronological ordering — only
`most_ads_day` (day-of-week) and `most_ads_hour` (hour-of-day) of **peak exposure**.
Without a time axis we cannot test whether conversion drifted over the test period.

The closest available **proxy** is the cross-sectional conversion pattern by
day-of-week and hour-of-day. This is a **pattern across categories, NOT a trend over
time**, and cannot stand in for a novelty check.

### Conversion rate by day-of-week (cross-sectional)

| day | `{t}` rate | `{c}` rate | gap ({t} − {c}) |
|---|---|---|---|
{day_md}

### Conversion rate by hour-of-day (cross-sectional)

| hour | `{t}` rate | `{c}` rate | gap ({t} − {c}) |
|---|---|---|---|
{hour_md}

**Caveat:** these are day-of-week / hour-of-day cross-sections, not a temporal
series. The true novelty / time-drift confound check **cannot be performed** with
this dataset and is not attempted.

---

### Bottom line

- **SRM: {'PASS' if srm['passed'] else 'FAIL'}** against the documented
  {intended_share:.2f} assumption — the observed split is consistent with the assumed
  {1 - intended_share:.0%}/{intended_share:.0%} design (SRM not rejected). The intended
  split is an assumption that sits almost exactly on the observed share, so this is
  assumption-dependent (see sensitivity).
- **Balance: cannot be verified** (no pre-treatment covariate) — descriptive only.
- **Time-drift / novelty: cannot be tested** (no time axis) — cross-sectional proxy only.

The audit proceeds on a randomization that passes SRM, while being explicit that
balance and novelty cannot be fully validated with this data.
"""


def write_report(r: dict[str, Any], config: dict[str, Any]) -> Path:
    """Write the validity report to the configured docs directory."""
    docs_dir = Path(config["resolved_paths"]["docs_dir"])
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / "validity_report.md"
    path.write_text(render_report(r, config), encoding="utf-8")
    logger.info("Wrote %s", path)
    return path


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description="Run test-validity checks and write the report.")
    parser.add_argument("--config", default=None, help="Path to config.yaml.")
    parser.add_argument(
        "--no-write", action="store_true", help="Compute and log only; do not write the report."
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    results = run_validity(config)
    log_results(results)
    if not args.no_write:
        write_report(results, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
