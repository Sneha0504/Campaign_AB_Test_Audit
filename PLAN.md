# PLAN.md — Campaign_AB_Test_Audit

Portfolio data-analysis project for a Digital Experimentation / A/B Testing
Analyst role. Audit a real marketing A/B test end to end: verify it was set up
correctly, measure the true campaign effect, find where exposure stops paying
off, and turn it into a business recommendation with a self-service Excel report
and a self-contained dashboard. **This plan is for approval — no analysis code is
written until you approve it (PROJECT.md Step 2).**

## Goal and key questions (restated)

1. **Randomization** — was the test randomized correctly? Sample-ratio-mismatch
   (SRM) check + group balance on observable (non-outcome) variables.
2. **Effect** — did the campaign change conversion, and is it statistically real?
3. **Exposure response** — does the effect vary with how much a user was exposed,
   and where does more exposure stop paying off?
4. **Business call** — what would scaling / capping / reallocating gain or lose,
   and how confident can we be?

## Data and why it fits

- **Kaggle "Marketing A/B Testing"** (faviovaz): ~588,101 users, each in an **ad**
  (treatment) or **psa** (public-service-announcement control) group, with
  `converted` (bool), `total ads` (count seen), `most ads day` (day of week), and
  `most ads hour` (hour). It's a genuine ad-experiment structure with an
  intentional small control holdout — exactly the SRM + lift + exposure-response +
  economics audit an experimentation analyst does.
- **Download:** no Kaggle API token is configured in this environment, so this is
  a **manual download** (exact steps below). Save untouched to
  `data/raw/marketing_AB.csv`. Document URL, license, date accessed, row count,
  columns, date range in `docs/data_sources.md`.
- Manual steps (given now so you can grab it during the build):
  1. Sign in at https://www.kaggle.com/datasets/faviovaz/marketing-ab-testing
  2. Click **Download** (zip), unzip, and place `marketing_AB.csv` at
     `Campaign_AB_Test_Audit/data/raw/marketing_AB.csv`.
  (If you later add a `~/.kaggle/kaggle.json` token, `make download` can fetch it
  via the Kaggle API instead; the loader will support both.)

## Statistical methods, per question (exact test + why)

1. **SRM (randomization):** chi-square goodness-of-fit of observed ad/psa counts
   against the **intended design split** (configurable; ad-tech holdouts are
   typically ~95/5 or 96/4 — the exact intended ratio is **not documented in the
   dataset**, so we test against a stated assumed design ratio from config and
   report the observed ratio honestly; if SRM fails we flag it plainly as
   undermining the whole test). **Balance:** the dataset has **no genuine
   pre-treatment covariate** (`total ads`/day/hour are all post-exposure), so a
   true balance check isn't possible; we will (a) say that plainly, and (b) at most
   compare the distribution of `most ads day`/`hour` across groups as a weak,
   explicitly-non-pre-treatment descriptive check, not a validity guarantee.
2. **Effect:** **two-proportion z-test** (ad vs psa conversion rate) — the right
   test for comparing two independent binomial proportions on a large sample —
   reporting the absolute difference, **95% CI** (normal approx), **p-value**, and
   **relative lift**. Cross-check with a chi-square of independence.
3. **Exposure response:** bucket users by `total ads` into **documented,
   defensible bands** (config-driven edges, e.g. 1, 2-3, 4-7, 8-15, 16-31, 32+;
   finalized from the real distribution during profiling). Per band: conversion
   rate ad vs psa, a two-proportion z-test, and **share of impressions vs share of
   incremental conversions** (where spend does / doesn't pay off). **Multiple
   comparisons:** Benjamini-Hochberg across bands; report raw **and** adjusted
   significance. **Honesty caveat (important):** `total ads` is *endogenous*
   (engaged users both see more ads and convert more), so per-band differences are
   **observational/descriptive, not causal** — the clean causal estimate is the
   overall randomized ad-vs-psa contrast. This will be stated clearly in the memo
   and methodology.
4. **Timing:** conversion rate by `most ads day` and `most ads hour` (descriptive).
5. **Economics:** editable illustrative assumptions (CPM = cost per 1,000
   impressions, value per conversion) in config → total media cost, incremental
   conversions (from the randomized lift), cost per incremental conversion, ROAS;
   plus a **reallocation scenario** (move impressions from least- to most-efficient
   band at constant spend), with the marginal-payoff-holds assumption stated.

## Deliverables

- Code: `src/{load,validate_test,analyze,economics,build_excel_report,build_dashboard}.py`,
  pinned `requirements.txt`, `config/config.yaml` (bucket edges, cost assumptions,
  significance thresholds, intended split, paths — no hard-coded paths), `Makefile`
  (setup, download, validate, analyze, excel, dashboard, test, all), type hints,
  docstrings, logging, ruff-clean.
- **Excel report** `outputs/Campaign_Test_Report.xlsx` (openpyxl, LIVE FORMULAS):
  Inputs tab (editable CPM / value-per-conv / planned control share / realloc
  share), Summary tab (users, conversions, rates, lift, CI, p-value, SRM,
  economics as formulas referencing Inputs + data tabs), Exposure tab (per-band
  lift + significance + charts, formulas), Recommendation tab (reallocation driven
  by Inputs). Data tabs hold the Python-computed aggregates; the headline metrics
  are Excel formulas over them, not pasted values.
- **VBA** `vba/RefreshReport.bas`: reload data tabs from fresh CSV exports, run
  integrity checks (rates in [0,1], no missing counts), recalc, export Summary as
  PDF, refuse to publish on a failed check; with import/run docs.
- **Self-contained Plotly `outputs/dashboard.html`** (data embedded, plotly.js
  inlined, opens by double-click): KPI summary (lift, p-value, economics),
  exposure-band chart (conversion + budget-vs-payoff), timing charts (day, hour).
  Plus `outputs/dashboard_screenshot.png`.
- Docs: `data_sources.md`, `data_quality_report.md`, `methodology.md`, `memo.md`,
  `README.md`, `AI_USE.md`.

## Tests (pytest)

- SRM test flags a known-bad synthetic split;
- two-proportion z-test matches a hand-calculated value on a tiny synthetic sample;
- exposure bucketing assigns edge values to the correct band;
- economics reallocation arithmetic is internally consistent (impressions moved ×
  rate == reported conversion change).

## How it will be built (routing policy)

Milestone by milestone: **coder (Opus 4.8)** implements, **verifier (Opus 5.5)**
independently checks each (re-running code, re-deriving numbers), fix loop until it
passes, **local commit** per milestone. **Pushes handed to you** as a copy-paste
block (never run by me).

Milestones: M1 scaffold+git+config+Makefile · M2 load + data_sources · M3 profiling
+ data_quality_report · M4 validity checks (SRM/balance/time) · M5 effect analysis
(lift + exposure bands + timing + BH) · M6 economics + recommendation · M7 pytest ·
M8 Excel report (live formulas) + VBA macro · M9 dashboard + screenshot · M10 docs
(methodology, memo, README, AI_USE) · M11 `make all` green from clean.

## Risks and fallbacks

- **Excel formula recalculation can't be automated here** (no LibreOffice/soffice,
  and openpyxl writes formulas but does not evaluate them). Fallback per the spec:
  compute every headline value in Python, write the Excel formulas, and
  **spot-verify each formula's result against the Python number by hand**, stating
  honestly that automated recalc wasn't available. (If a `soffice` becomes
  available we'll use `--headless --convert-to` to force a recalc and check for
  error cells.)
- **VBA macro can't be executed in this environment** (no automatable Excel). We
  ship `RefreshReport.bas` + import/run instructions and verify it by code review
  only; we will NOT claim it was executed. Stated honestly in AI_USE.md.
- **Manual Kaggle download** (no token) — exact steps provided; the loader supports
  both API (if a token appears) and the manual file.
- **Exposure endogeneity** — per-band effects are observational; the memo leads
  with the randomized overall estimate and labels band results descriptive.
- **No true pre-treatment covariate** — balance check is limited and labeled as
  such, not overstated.
- **Intended split ratio undocumented** — SRM tested against a stated assumed
  design ratio (config), with the observed ratio reported plainly.
- **Space-in-path** (`Coding Projects`) — Makefile uses relative, quoted paths.

## Out of scope

- No real ad spend / no real CPM or conversion value (assumptions are illustrative
  and editable).
- No causal modeling of exposure beyond the randomized contrast (no IV/propensity
  reweighting) — called out, not attempted.
- No live data connection; the VBA refresh targets local CSV exports.
- Not a production BI deployment; the dashboard + Excel are self-service artifacts.
