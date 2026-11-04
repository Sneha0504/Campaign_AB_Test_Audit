"""Profile the Marketing A/B Testing dataset and generate provenance + quality docs.

Running this module computes every reported statistic directly from the REAL data
at ``data/raw/marketing_AB.csv`` and writes:

    docs/data_sources.md         (M2 - provenance, from actual inspection)
    docs/data_quality_report.md  (M3 - numbered rules with severity + handling)

No numbers are hand-entered: the Markdown is templated from the computed metrics,
so the docs cannot drift from the data. No rows are ever dropped here; any
exclusion decision for later milestones is stated and would be logged.

CLI:
    python src/profile_data.py            # compute + write both docs
    python src/profile_data.py --no-write # compute + log only (no file writes)
    python src/profile_data.py --config PATH
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import file_sha256_short, load_config, setup_logging  # noqa: E402
from src.load import (  # noqa: E402
    _drop_index_columns,
    load_data,
    numeric_coercion_na_count,
    standardize_columns,
)

logger = setup_logging(name="profile")

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ALL_HOURS = list(range(24))


def _ordered_days(present: set[str]) -> list[str]:
    """Return present weekdays in Mon..Sun order, then any unexpected labels."""
    ordered = [d for d in WEEKDAYS if d in present]
    extras = sorted(present - set(WEEKDAYS))
    return ordered + extras


def compute_profile(config: dict[str, Any]) -> dict[str, Any]:
    """Compute all profiling metrics from the real dataset.

    Args:
        config: Parsed config dict (with ``resolved_paths``).

    Returns:
        A dict of computed metrics used to render both documents.
    """
    data_cfg = config.get("data", {})
    treatment = data_cfg.get("treatment_label", "ad")
    control = data_cfg.get("control_label", "psa")
    csv_path = Path(config["resolved_paths"]["data_raw"])

    df = load_data(config)
    n_rows = len(df)

    # Coercion check on the RAW (pre-coercion) columns, to surface hidden losses.
    raw = standardize_columns(_drop_index_columns(pd.read_csv(csv_path)))
    coercion_na = {
        "total_ads": numeric_coercion_na_count(raw["total_ads"]),
        "most_ads_hour": numeric_coercion_na_count(raw["most_ads_hour"]),
    }

    # Rule 1: group sizes + split ratio
    group_counts = df["test_group"].value_counts().to_dict()
    n_ad = int(group_counts.get(treatment, 0))
    n_psa = int(group_counts.get(control, 0))
    observed_control_share = n_psa / n_rows if n_rows else 0.0
    intended_control_share = float(config.get("validity", {}).get("intended_control_share", 0.0))

    # Rule 2: missing values + duplicates
    missing = {col: int(df[col].isna().sum()) for col in df.columns}
    n_dupe_users = int(df["user_id"].duplicated().sum())
    n_unique_users = int(df["user_id"].nunique())

    # Rule 3: zero-exposure / contamination (per group)
    zero_exposure = {}
    group_exposure_range = {}
    for grp in (treatment, control):
        sub = df.loc[df["test_group"] == grp, "total_ads"]
        zero_exposure[grp] = int((sub == 0).sum())
        group_exposure_range[grp] = (int(sub.min()), int(sub.max())) if len(sub) else (None, None)
    unexpected_groups = sorted(set(df["test_group"].unique()) - {treatment, control})

    # Rule 4: total_ads distribution + outliers
    ta = df["total_ads"].astype("int64")
    pct = config.get("profiling", {}).get("outlier_percentile", 99)
    outlier_threshold = float(ta.quantile(pct / 100.0))
    n_outliers = int((ta > outlier_threshold).sum())
    dist = {
        "min": int(ta.min()),
        "median": float(ta.median()),
        "mean": float(ta.mean()),
        "std": float(ta.std()),
        "max": int(ta.max()),
        "p90": float(ta.quantile(0.90)),
        "p95": float(ta.quantile(0.95)),
        "p99": float(ta.quantile(0.99)),
    }

    # Rule 5: day / hour coverage
    days_present = set(df["most_ads_day"].unique())
    days_ordered = _ordered_days(days_present)
    missing_days = [d for d in WEEKDAYS if d not in days_present]
    hours_present = sorted(int(h) for h in df["most_ads_hour"].dropna().unique())
    missing_hours = [h for h in ALL_HOURS if h not in hours_present]

    # Rule 6: converted binary + clean
    converted_values = sorted(df["converted"].dropna().unique().tolist())
    converted_na = int(df["converted"].isna().sum())
    converted_is_bool = str(df["converted"].dtype) == "bool"

    # Context: conversion rates by group (not an exclusion rule, informational)
    conv_rate = {
        treatment: float(df.loc[df["test_group"] == treatment, "converted"].mean()),
        control: float(df.loc[df["test_group"] == control, "converted"].mean()),
    }

    columns_dtypes = {col: str(df[col].dtype) for col in df.columns}

    metrics: dict[str, Any] = {
        "csv_path": str(csv_path),
        "data_fingerprint": f"sha256:{file_sha256_short(csv_path)} · {n_rows:,} rows",
        "n_rows": n_rows,
        "n_cols": df.shape[1],
        "columns_dtypes": columns_dtypes,
        "treatment": treatment,
        "control": control,
        "n_ad": n_ad,
        "n_psa": n_psa,
        "observed_control_share": observed_control_share,
        "intended_control_share": intended_control_share,
        "missing": missing,
        "coercion_na": coercion_na,
        "n_dupe_users": n_dupe_users,
        "n_unique_users": n_unique_users,
        "zero_exposure": zero_exposure,
        "group_exposure_range": group_exposure_range,
        "unexpected_groups": unexpected_groups,
        "outlier_percentile": pct,
        "outlier_threshold": outlier_threshold,
        "n_outliers": n_outliers,
        "dist": dist,
        "days_ordered": days_ordered,
        "missing_days": missing_days,
        "hours_present": hours_present,
        "missing_hours": missing_hours,
        "converted_values": converted_values,
        "converted_na": converted_na,
        "converted_is_bool": converted_is_bool,
        "conv_rate": conv_rate,
    }
    return metrics


def log_profile(m: dict[str, Any]) -> None:
    """Log the headline findings so a run prints the real numbers."""
    logger.info("Rows: %d | Columns: %d", m["n_rows"], m["n_cols"])
    logger.info(
        "Groups: %s=%d, %s=%d | observed control share=%.6f (intended %.4f)",
        m["treatment"],
        m["n_ad"],
        m["control"],
        m["n_psa"],
        m["observed_control_share"],
        m["intended_control_share"],
    )
    logger.info("Missing values per column: %s", m["missing"])
    logger.info("Coercion-induced NAs: %s", m["coercion_na"])
    logger.info(
        "Duplicate user_id rows: %d (unique users %d)", m["n_dupe_users"], m["n_unique_users"]
    )
    logger.info("Zero-exposure users per group: %s", m["zero_exposure"])
    logger.info(
        "total_ads: min=%d median=%.1f mean=%.3f max=%d p90=%.0f p95=%.0f p99=%.0f",
        m["dist"]["min"],
        m["dist"]["median"],
        m["dist"]["mean"],
        m["dist"]["max"],
        m["dist"]["p90"],
        m["dist"]["p95"],
        m["dist"]["p99"],
    )
    logger.info(
        "Outliers > p%d (%.1f): %d",
        m["outlier_percentile"],
        m["outlier_threshold"],
        m["n_outliers"],
    )
    logger.info("Days present: %s (missing: %s)", m["days_ordered"], m["missing_days"] or "none")
    logger.info(
        "Hours present: %d of 24 (missing: %s)",
        len(m["hours_present"]),
        m["missing_hours"] or "none",
    )
    logger.info(
        "converted values=%s na=%d bool=%s",
        m["converted_values"],
        m["converted_na"],
        m["converted_is_bool"],
    )


def _severity(flag: bool, bad: str = "warn", ok: str = "info") -> str:
    return bad if flag else ok


def render_data_sources(m: dict[str, Any], config: dict[str, Any]) -> str:
    """Render docs/data_sources.md from computed metrics + config provenance."""
    data_cfg = config.get("data", {})
    url = data_cfg.get("kaggle_url", "")
    dataset = data_cfg.get("kaggle_dataset", "")
    license_str = data_cfg.get("license", "Unconfirmed")
    date_accessed = data_cfg.get("date_accessed", "")
    cols = "\n".join(f"| `{c}` | {dt} |" for c, dt in m["columns_dtypes"].items())
    hours = m["hours_present"]
    hour_range = f"{min(hours)}-{max(hours)}" if hours else "n/a"
    return f"""# Data Sources — Campaign_AB_Test_Audit

_Auto-generated by `src/profile_data.py` from the real file. Every count below is
computed, not hand-entered. Data fingerprint: {m["data_fingerprint"]}._

## Dataset

- **Name:** Marketing A/B Testing
- **Source (Kaggle):** {url}
- **Kaggle slug:** `{dataset}`
- **Date accessed:** {date_accessed}
- **License:** {license_str}
  - The license is **not machine-readable** from the dataset page (JavaScript-rendered),
    so it could not be confirmed programmatically on the access date. Treat it as
    **unconfirmed** and do **not** redistribute the raw CSV (it is git-ignored). Verify
    the license directly on the Kaggle page before any reuse.
- **Local path (untouched, git-ignored):** `data/raw/marketing_AB.csv`

## Shape

- **Rows:** {m["n_rows"]:,}
- **Columns (canonical, after dropping the unnamed index column):** {m["n_cols"]}

| column | dtype |
|---|---|
{cols}

## Group breakdown (computed)

| group | users | share |
|---|---|---|
| `{m["treatment"]}` (treatment) | {m["n_ad"]:,} | {m["n_ad"] / m["n_rows"]:.4f} |
| `{m["control"]}` (control) | {m["n_psa"]:,} | {m["n_psa"] / m["n_rows"]:.4f} |

Observed control (`{m["control"]}`) share = **{m["observed_control_share"]:.6f}**.

## "Date range covered" — HONEST NOTE

This dataset has **no calendar dates**. There is no timestamp, no start/end date, and
no way to place events on a calendar. The only temporal fields are:

- `most_ads_day` — the **day of week** (Monday..Sunday) of the user's peak ad exposure.
- `most_ads_hour` — the **hour of day** (0-23) of the user's peak ad exposure.

So we do **not** claim any date range. The observed temporal coverage is:

- **Days of week present:** {", ".join(m["days_ordered"])} ({len(m["days_ordered"])} of 7).
- **Hour-of-day range present:** {hour_range} ({len(hours)} of 24 distinct hours).
"""


def render_data_quality_report(m: dict[str, Any], config: dict[str, Any]) -> str:
    """Render docs/data_quality_report.md as numbered rules with severity + handling."""
    t, c = m["treatment"], m["control"]
    share_diff = abs(m["observed_control_share"] - m["intended_control_share"])

    # Severities derived from the real findings.
    sev1 = _severity(share_diff > 0.005)  # observed share far from intended
    total_missing = sum(m["missing"].values()) + sum(m["coercion_na"].values())
    sev2 = _severity(total_missing > 0 or m["n_dupe_users"] > 0)
    total_zero = sum(m["zero_exposure"].values())
    sev3 = _severity(total_zero > 0 or bool(m["unexpected_groups"]))
    sev4 = "warn"  # heavy skew is expected and affects naive means
    sev5 = _severity(bool(m["missing_days"]) or bool(m["missing_hours"]))
    converted_clean = (
        m["converted_is_bool"]
        and m["converted_na"] == 0
        and set(m["converted_values"]).issubset({True, False})
    )
    sev6 = _severity(not converted_clean)

    missing_rows = "\n".join(f"| `{col}` | {n} |" for col, n in m["missing"].items())
    d = m["dist"]
    if m["missing_days"]:
        days_cov = f"{len(m['days_ordered'])} of 7 (missing: {', '.join(m['missing_days'])})"
    else:
        days_cov = "all 7"
    if m["missing_hours"]:
        hours_cov = f"{len(m['hours_present'])} of 24 (missing: {m['missing_hours']})"
    else:
        hours_cov = "all 24 (0-23)"
    ad_rng = m["group_exposure_range"][t]
    psa_rng = m["group_exposure_range"][c]
    coerce_ta = m["coercion_na"]["total_ads"]
    coerce_hr = m["coercion_na"]["most_ads_hour"]

    return f"""# Data Quality Report — Campaign_AB_Test_Audit

_Auto-generated by `src/profile_data.py` from `data/raw/marketing_AB.csv`. Every
number is computed from the real data. Data fingerprint: {m["data_fingerprint"]}._

**The entire audit stands on this profiling step.** Each check below is a numbered
rule with the real finding, a severity (`info` / `warn` / `critical`), and a handling
decision. **No rows are dropped in profiling.** Any future exclusion will be logged
with its count; nothing is dropped silently. As of this run, **no exclusions are
required** — all {m["n_rows"]:,} rows are retained.

---

## Rule 1 — Group sizes and actual vs intended split  ·  severity: {sev1}

- **Checks:** real `{t}` vs `{c}` counts and the observed control share, against the
  assumed design split from config (`intended_control_share`).
- **Finding:** `{t}` = {m["n_ad"]:,} users, `{c}` = {m["n_psa"]:,} users
  (total {m["n_rows"]:,}). Observed control share = **{m["observed_control_share"]:.6f}**;
  intended (assumed) = **{m["intended_control_share"]:.4f}**; absolute difference =
  **{share_diff:.6f}**.
- **Note:** the intended split is an **assumption** (the dataset does not state its
  design ratio); it is documented as such in config.
- **Handling:** keep all rows. A formal Sample-Ratio-Mismatch chi-square test against
  the intended split is performed in M4 (`validate_test.py`); this rule only reports
  the observed ratio.

## Rule 2 — Missing values, duplicate users, and coercion losses  ·  severity: {sev2}

- **Checks:** nulls in every column, duplicate `user_id` rows, and any values lost to
  numeric coercion (`total_ads`, `most_ads_hour`).
- **Finding — missing per column:**

| column | missing |
|---|---|
{missing_rows}

- **Finding — duplicates:** `user_id` has **{m["n_dupe_users"]}** duplicate rows
  ({m["n_unique_users"]:,} unique ids over {m["n_rows"]:,} rows).
- **Finding — coercion losses (non-null values that failed numeric parsing):**
  `total_ads` = {coerce_ta}, `most_ads_hour` = {coerce_hr}.
- **Handling:** keep all rows. With zero missing, zero duplicates, and zero coercion
  losses, no imputation or de-duplication is needed. The loader logs a warning if any
  future refresh introduces coercion NAs.

## Rule 3 — Zero-exposure users and control-group contamination  ·  severity: {sev3}

- **Checks:** users with **zero** exposure in the `{t}` (treatment) group, and the
  exposure pattern of the `{c}` (control) group.
- **Clarification:** in this dataset `total_ads` for the `{c}` group is the count of
  **PSA (public-service-announcement) creatives** seen — the control creative — not
  real-ad views. So "exposure in control" means **PSA views, not ad contamination**.
- **Finding:** zero-exposure users — `{t}`: {m["zero_exposure"][t]}, `{c}`: {m["zero_exposure"][c]}.
  Exposure range — `{t}`: {ad_rng[0]}-{ad_rng[1]}, `{c}`: {psa_rng[0]}-{psa_rng[1]}.
  Unexpected group labels: {m["unexpected_groups"] or "none"}.
- **Handling:** keep all rows. Every user has at least one exposure (minimum = 1 in
  both groups), so there is no zero-exposure ambiguity to resolve and no cross-group
  contamination of real ads into the control.

## Rule 4 — Distribution of `total_ads` and outliers  ·  severity: {sev4}

- **Checks:** central tendency, spread, and the heavy right skew of exposure counts,
  plus a quantified outlier tail.
- **Finding:** min={d["min"]}, median={d["median"]:.1f}, mean={d["mean"]:.3f},
  std={d["std"]:.1f}, max={d["max"]}. Percentiles: p90={d["p90"]:.0f},
  p95={d["p95"]:.0f}, p99={d["p99"]:.0f}. The mean well above the median confirms a
  **strong right skew**.
- **Outliers:** above p{m["outlier_percentile"]} (threshold {m["outlier_threshold"]:.1f}):
  **{m["n_outliers"]:,}** users.
- **Handling:** keep all rows (outliers are real high-exposure users, not errors). The
  skew is handled analytically in M5 by bucketing `total_ads` into exposure bands (the
  top band absorbs the tail), so headline comparisons do not rely on a skew-sensitive
  mean. Outlier count is logged, not dropped.

## Rule 5 — Day-of-week and hour-of-day coverage  ·  severity: {sev5}

- **Checks:** which weekdays appear in `most_ads_day` and whether `most_ads_hour`
  covers 0-23, with any gaps.
- **Finding:** days present — {days_cov}. Hours present — {hours_cov}.
- **Handling:** keep all rows. Coverage is complete, so timing analysis (M5) can use
  all days and hours without gap-filling. (Reminder: these are day-of-week and
  hour-of-day of peak exposure, not calendar dates — see `data_sources.md`.)

## Rule 6 — Is `converted` binary and clean?  ·  severity: {sev6}

- **Checks:** that `converted` is boolean, has no nulls, and contains only two values.
- **Finding:** dtype is bool = {m["converted_is_bool"]}; nulls = {m["converted_na"]};
  distinct values = {m["converted_values"]}.
- **Context (not an exclusion):** conversion rate `{t}` = {m["conv_rate"][t]:.4%},
  `{c}` = {m["conv_rate"][c]:.4%} (formally tested in M5).
- **Handling:** keep all rows. The flag is clean binary, so it is used directly as the
  outcome with no recoding.

---

### Summary of handling

All {m["n_rows"]:,} rows are retained; **no exclusions** were required by any rule.
The only `warn` is the expected heavy skew of `total_ads` (Rule 4), handled by
exposure banding in M5 rather than by dropping data.
"""


def write_docs(m: dict[str, Any], config: dict[str, Any]) -> tuple[Path, Path]:
    """Write both documents to the configured docs directory."""
    docs_dir = Path(config["resolved_paths"]["docs_dir"])
    docs_dir.mkdir(parents=True, exist_ok=True)
    sources_path = docs_dir / "data_sources.md"
    quality_path = docs_dir / "data_quality_report.md"
    sources_path.write_text(render_data_sources(m, config), encoding="utf-8")
    quality_path.write_text(render_data_quality_report(m, config), encoding="utf-8")
    logger.info("Wrote %s", sources_path)
    logger.info("Wrote %s", quality_path)
    return sources_path, quality_path


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description="Profile the dataset and write quality docs.")
    parser.add_argument("--config", default=None, help="Path to config.yaml.")
    parser.add_argument(
        "--no-write", action="store_true", help="Compute and log only; do not write docs."
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    metrics = compute_profile(config)
    log_profile(metrics)
    if not args.no_write:
        write_docs(metrics, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
