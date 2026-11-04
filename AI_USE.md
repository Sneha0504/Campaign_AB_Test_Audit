# AI Use and Honesty Record

This project was built with AI assistance under an explicit honesty standard: only tools
that actually ran are listed as used, every number in the docs comes from script output,
and nothing was fabricated.

## How it was built

- A coder agent (Claude Opus 4.8) implemented each milestone; a separate verifier agent
  (Claude Opus 5.5) independently checked each milestone (re-running code, re-deriving
  numbers) before the next one started. Milestones: M1 scaffold/config/Makefile/loader,
  M2 data sources, M3 profiling, M4 validity checks, M5 effect analysis, M6 economics,
  M7 tests, M8 Excel + VBA, M9 dashboard + screenshot, M10 docs.
- **Commits:** the user directed that no local commits or pushes be made for this project.
  All work is delivered uncommitted in the working tree. (Earlier milestones had been
  committed locally and were later reset to honor this directive.)

## Tools actually used (code ran with them)

- **Python 3.12** - the whole pipeline.
- **pandas**, **numpy** - data loading, aggregation, profiling.
- **scipy** - chi-square (SRM, independence), normal distribution (z-test p-values and
  critical values).
- **matplotlib** - static PNG charts in `outputs/charts/` (`make charts`,
  `src/build_charts.py`). Genuinely run.
- **plotly** - the self-contained dashboard (`outputs/dashboard.html`); plotly.js is
  inlined.
- **openpyxl** - the live-formula Excel report (`outputs/Campaign_Test_Report.xlsx`).
- **playwright** (headless Chromium) - the dashboard screenshot
  (`outputs/dashboard_screenshot.png`) and the offline-load verification (zero external
  requests, zero console errors). Optional; the build skips gracefully if it is absent.
- **pytest** - 13 unit tests.
- **ruff** - lint and format.
- **certifi** - CA bundle for TLS during setup/download.

**VBA** (`vba/RefreshReport.bas`) was written and reviewed but **not executed**: there is
no automatable Excel in the build environment. It is shipped and documented only.

## Bugs caught during the build, and how

- **Doc byte-instability (M3):** auto-generated docs carried a wall-clock `Generated:`
  timestamp, so every regeneration dirtied git. Caught by re-running the generator and
  diffing. Fixed by stamping docs with a data-derived fingerprint (short SHA-256 of the
  input CSV plus row count) instead of a timestamp.
- **p-value collapsed to 0.0 in JSON (M5):** rounding the results JSON to 8 decimals turned
  the overall p-value (1.7e-13) into 0.0, which would have misled the Excel and dashboard.
  Caught when spot-checking the JSON. Fixed by keeping full float precision (NaN mapped to
  null).
- **Logging ValueError (M6):** `%`-style log format strings used comma grouping
  (`%,.2f`), which is invalid in `%`-formatting and raised at log time. Caught on first
  run. Fixed by using plain `%.2f` in logs (f-string grouping kept in docs).
- **Reallocation honesty gap (M6):** the budget reallocation initially treated the source
  band's negative marginal payoff as real, but that band is not statistically significant
  (its 95 percent CI includes 0), and picking the most-negative band is a winner's-curse
  selection. Caught in verification. Fixed by adding a conservative variant (source effect
  set to 0; +56.5 conversions) as the defensible figure, with the optimistic value kept
  only as an explicit upper bound, and the non-significance stated in the doc and JSON.
- **Wrong expected p + weak test (M7):** the hand-calculated two-sided p for the 20/100 vs
  10/100 example was 0.047715 but the true value is 0.047670; corrected. The BH
  monotonicity test was also strengthened with a vector where removing the step-up `min`
  actually changes the result.
- **Excel p-value catastrophic cancellation (M8):** the p-value formula
  `2*(1-NORM.S.DIST(ABS(z)))` loses all precision for small p (it would show about 0 in
  Excel for the 32+ band). Caught when the formula verifier's tolerance was tightened to a
  relative tolerance. Fixed by using `2*NORM.S.DIST(-ABS(z),TRUE)` (the direct lower tail),
  which matches scipy's survival function.
- **xlsx byte-instability (M8):** openpyxl stamped each zip entry and the `modified`
  property with the current time, so two builds differed. Caught by building twice and
  comparing sha256. Fixed by re-zipping with fixed entry timestamps and pinning the core
  properties timestamp.
- **VBA Mac incompatibility (M10):** the overall-counts reload used
  `CreateObject("Scripting.Dictionary")`, which does not exist in Excel for Mac (the user
  is on macOS), so the macro would always fail there. Caught in review. Fixed by using the
  same cross-platform `Select Case` header matching as the band loader.

## Not verified, deviations, and known limitations

- **Excel full recalculation was not available** (no Excel or LibreOffice in the
  environment). Formulas were verified by (a) correct cell-reference construction and (b) a
  Python evaluator that recomputes each key formula cell and compares to the analysis JSON
  (70 cells, 0 mismatches). The workbook was not opened in Excel here; it is set to
  recalculate on open. We do not claim Excel recalculated it.
- **The VBA macro was not executed** (code review only).
- **Economic assumptions are illustrative** (CPM, value per conversion); there is no real
  spend. The ROAS and reallocation figures move with those inputs.
- **Exposure-band effects are observational**, because the number of ads a user saw is
  endogenous. Only the overall randomized ad-vs-PSA lift is causal.
- **No pre-treatment covariate exists**, so group balance cannot be verified; the balance
  section is descriptive only.
- **No calendar dates exist** (only day of week and hour of day of peak exposure), so a
  genuine time-drift / novelty check is not possible; the timing section is cross-sectional.
- **The control group is small** (23,524) and thin by conversions in the low-exposure
  bands (as few as about 3 control conversions), so those band rates are noisy; bands 1 and
  2 to 3 are flagged unreliable.
- **The Kaggle dataset license could not be confirmed** programmatically from the
  JavaScript-rendered dataset page; treat it as unconfirmed and do not redistribute the raw
  CSV.
- **Screenshot determinism:** the dashboard PNG is a binary browser render and may differ
  across machines or Chromium versions; it is produced by an optional target outside
  `make all`.
