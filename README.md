# Campaign_AB_Test_Audit

Audit a real marketing A/B test end to end: verify the test was set up correctly,
measure the true effect of the campaign, find where the effect is strongest and
weakest, and turn the result into a business recommendation backed by a self-service
Excel report and an interactive dashboard. The project answers four questions:

1. Was the test actually randomized correctly (sample-ratio check, group balance)?
2. Did the campaign change the outcome, and is the effect statistically real?
3. Does the effect vary by how much a user was exposed, and where does more exposure
   stop paying off?
4. What would the business gain or lose from scaling, capping, or reallocating the
   campaign, and how confident can we be in that recommendation?

## Data

The **Marketing A/B Testing** dataset on Kaggle
(<https://www.kaggle.com/datasets/faviovaz/marketing-ab-testing>): **588,101 users**
split between an ad-exposed group (**564,577**) and a public-service-announcement
(PSA) control group (**23,524**), with ad exposure count, peak-exposure day/hour, and
a binary conversion flag. Saved untouched to `data/raw/marketing_AB.csv` (git-ignored).
Provenance (URL, license, date accessed, row count, columns) is in
[`docs/data_sources.md`](docs/data_sources.md).

## Deliverables

- **Interactive dashboard:** [`outputs/dashboard.html`](outputs/dashboard.html) — a
  single self-contained Plotly file (data embedded, no server; double-click to open).
  Sections: KPI summary (lift, p-value, economics), exposure-band chart (conversion
  and budget-vs-payoff), and timing charts (day and hour). Screenshot:
  [`outputs/dashboard_screenshot.png`](outputs/dashboard_screenshot.png).
- **Excel report:** [`outputs/Campaign_Test_Report.xlsx`](outputs/Campaign_Test_Report.xlsx)
  — built with openpyxl, with an **Inputs** tab (editable CPM, value-per-conversion,
  control share, reallocation share), and **Summary / Exposure / Recommendation** tabs
  driven by **live formulas** that reference the Inputs and data tabs (not pasted
  values). See [`docs/excel_report.md`](docs/excel_report.md).
- **VBA refresh macro:** [`vba/RefreshReport.bas`](vba/RefreshReport.bas) — reloads the
  data tabs from fresh CSV exports, runs integrity checks (rates in [0,1], no missing
  counts), recalculates, and exports a PDF of the Summary tab, refusing to publish if a
  check fails.
- **Charts:** [`outputs/charts/`](outputs/charts/) — `conversion_by_band.png`,
  `conversion_by_day.png`, `conversion_by_hour.png`.
- **Data extracts:** [`outputs/overall_counts.csv`](outputs/overall_counts.csv),
  [`outputs/exposure_bands.csv`](outputs/exposure_bands.csv),
  [`outputs/timing_by_day.csv`](outputs/timing_by_day.csv),
  [`outputs/timing_by_hour.csv`](outputs/timing_by_hour.csv), and the JSON results
  [`outputs/analysis_results.json`](outputs/analysis_results.json),
  [`outputs/economics_results.json`](outputs/economics_results.json).
- **Reports:** [`docs/methodology.md`](docs/methodology.md),
  [`docs/validity_report.md`](docs/validity_report.md),
  [`docs/data_quality_report.md`](docs/data_quality_report.md),
  [`docs/economics.md`](docs/economics.md),
  [`docs/memo.md`](docs/memo.md).

> All of these deliverables are produced by `make all` from the raw dataset.

## Key findings

All dollar figures are **illustrative and editable** (assumed CPM of $10 per 1,000
impressions and $25 per conversion). The conversion numbers are real, computed from
the dataset.

- **Did the campaign change conversion? Yes, and it is not noise.** Two-proportion
  z-test on the randomized groups: ad group **2.5547%** (14,423 / 564,577) vs control
  **1.7854%** (420 / 23,524) — an absolute lift of **+0.77 pp** (95% CI 0.60–0.94 pp),
  **+43.1% relative**, p = 1.7e-13 (z = 7.37). Because users were randomized into ad
  vs PSA, this overall lift is a genuine causal estimate.
- **Where does more exposure stop paying off?** Grouping by ads seen (1, 2–3, 4–7,
  8–15, 16–31, 32+) with Benjamini-Hochberg correction, the lift is concentrated in
  the **highest-exposure band (32+ ads)**: ad 9.30% vs control 5.78%, a +3.53 pp
  difference, highly significant after correction (adjusted p 1.7e-16). Every band
  below that is not statistically distinguishable from zero. The top band holds ~66%
  of all ad impressions and accounts for essentially all incremental conversions.
  **Caveat:** ads-seen is not randomized (engaged users both see more ads and convert
  more), so the per-band results are observational, not causal.
- **Economics (illustrative assumptions):** 14,014,701 total impressions → $140,147
  media cost; 4,343 incremental conversions (from the causal lift); **cost per
  incremental conversion $32.27**; value $108,575; **ROAS 0.775**. At $10 CPM / $25
  per conversion the campaign returns less than it costs; it turns positive below a
  break-even CPM of $7.75 or above a break-even conversion value of $32.27.
- **Recommendation:** shifting 25% of impressions from the least-efficient reliable
  band (4–7 ads) into the 32+ band, holding spend constant, gives a defensible
  estimated **+56.5 incremental conversions (~+$1,413)** (optimistic upper bound
  +82.7 / ~+$2,067, not relied on). This rests on a strong assumption — that the
  high-exposure band's efficiency would hold at higher volume — which likely would not,
  because high-exposure users are self-selected. Treat it as an illustrative
  upper-bound sketch, not a promise.

## What could and could not be validated

- **Randomization:** the observed ~4% control share is consistent with an assumed
  96/4 design (sample-ratio-mismatch test not rejected). The intended split is an
  assumption that sits almost exactly on the observed share, so this check is
  assumption-dependent.
- **Group balance:** cannot be verified — the dataset has no pre-treatment
  characteristic to compare.
- **Time / novelty effects:** cannot be tested — only day-of-week and hour-of-day of
  peak exposure are available, no calendar dates.
- The control group is small (23,524), so low-exposure band rates are noisy.

Only the overall lift in question 2 is a clean causal number; the band, timing, and
economic extrapolations are useful context but carry the caveats above. Full detail in
[`docs/validity_report.md`](docs/validity_report.md) and
[`docs/methodology.md`](docs/methodology.md).

## Folder layout

```
Campaign_AB_Test_Audit/
  config/config.yaml      bucket edges, cost assumptions, significance thresholds
  data/raw/               untouched marketing_AB.csv (git-ignored)
  src/                    load, profile_data, validate_test, analyze, economics,
                          build_charts, build_excel_report, build_dashboard
  vba/RefreshReport.bas   Excel refresh + integrity-check + PDF-export macro
  tests/                  pytest (sample-ratio, z-test, bucketing, economics)
  docs/                   data_sources, data_quality_report, methodology,
                          validity_report, economics, excel_report, memo
  outputs/                dashboard.html, Campaign_Test_Report.xlsx, charts/, CSV/JSON
  Makefile  requirements.txt  ruff.toml
```

## How to run

Prerequisites: **Python 3.11+** (pinned `requirements.txt`: pandas, NumPy, SciPy,
matplotlib, openpyxl, Plotly). No credentials. Place the Kaggle CSV at
`data/raw/marketing_AB.csv` (the `download` target prints exact steps if it is
missing and no Kaggle token is configured).

```bash
make all            # setup -> download -> profile -> validate -> analyze -> economics
                    #   -> charts -> excel -> dashboard -> test
```

| Target | What it does |
|---|---|
| `setup` | Create the venv and install pinned `requirements.txt`. |
| `download` | Fetch the Kaggle dataset (API if a token exists), else print manual steps. |
| `profile` | Data profiling + `docs/data_quality_report.md`. |
| `validate` | Test-validity checks (sample-ratio mismatch, balance, novelty) → `docs/validity_report.md`. |
| `analyze` | Overall lift, exposure-band analysis (BH-corrected), timing analysis. |
| `economics` | Media cost, incremental conversions, cost/conversion, ROAS, reallocation scenario. |
| `charts` | matplotlib PNGs → `outputs/charts/`. |
| `excel` | Build `outputs/Campaign_Test_Report.xlsx` with live formulas. |
| `dashboard` | Build the self-contained `outputs/dashboard.html`. |
| `screenshot` | Render `outputs/dashboard_screenshot.png` (best-effort Playwright). |
| `test` | `pytest tests/`. |
| `lint` / `format` | `ruff check` / `ruff format`. |
| `clean` | Remove regenerable outputs. |

## Tests

`pytest tests/`: the sample-ratio test flags a known-bad synthetic split, the
two-proportion z-test matches a hand-calculated value on a tiny synthetic example,
exposure bucketing assigns edge values correctly, and the economics scenario's
arithmetic is internally consistent (impressions moved × rate equals the reported
conversion change).
