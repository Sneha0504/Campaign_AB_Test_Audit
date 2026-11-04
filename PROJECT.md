You are building a portfolio data analysis project from scratch. Work carefully, verify everything
you claim, and never fabricate data, results, or tool usage.

=====================================================================
PROJECT DETAILS
=====================================================================
Project name:   Campaign_AB_Test_Audit
Target role:    Digital Experimentation Analyst / A/B Testing Analyst
Goal:           Audit a real marketing A/B test end to end: verify the test was set up correctly,
                measure the true effect of the campaign, find where the effect is strongest and
                weakest, and turn the result into a business recommendation with a self-service
                Excel report for stakeholders.
Key questions:
  1. Was the test actually randomized correctly? (sample ratio check, group balance on observable
     characteristics)
  2. Did the campaign change the outcome, and is the effect statistically real, not noise?
  3. Does the effect vary by how much a user was exposed to the campaign? Where does more exposure
     stop paying off?
  4. What would the business gain or lose from scaling, capping, or reallocating the campaign, and how
     confident can we be in that recommendation?
Required tools: Python (pandas, NumPy, SciPy, matplotlib), Excel (openpyxl, live formulas), VBA,
                Plotly (for a self-contained HTML version of the dashboard).
Deliverables:   analysis pipeline, statistical test suite, an Excel report with live formulas and a
                VBA refresh macro, a self-contained HTML dashboard, memo, README.

=====================================================================
STEP 0: READ MY SKILLS FIRST (MANDATORY)
=====================================================================
Before doing anything else, read every file in the `.claude` folder (check `coding projects/.claude/`
first, then `~/.claude/` if it exists). These are skills I wrote for you. Follow them throughout. If a
skill conflicts with this prompt, tell me which one and ask before proceeding. List the skills you
found and how you will apply them.

=====================================================================
STEP 1: FOLDER SETUP
=====================================================================
My main folder is `coding projects`. Create the subfolder `coding projects/Campaign_AB_Test_Audit/`
and work only inside it:

  Campaign_AB_Test_Audit/
    README.md  PLAN.md  AI_USE.md  requirements.txt  Makefile  .gitignore
    config/config.yaml
    data/raw/                       untouched downloaded CSV (git-ignored)
    src/                            load.py, validate_test.py, analyze.py, economics.py,
                                    build_excel_report.py, build_dashboard.py
    vba/RefreshReport.bas
    tests/
    outputs/                        Campaign_Test_Report.xlsx, dashboard.html, charts/
    docs/                           data_sources.md, data_quality_report.md, methodology.md, memo.md

Initialize git. .gitignore excludes data/raw, venvs, outputs/*.xlsx if large. Commit at each milestone.

=====================================================================
STEP 2: SCOPE AND PLAN (PAUSE FOR MY APPROVAL)
=====================================================================
Write PLAN.md: goal and key questions restated, the data and why it fits, the statistical methods for
each question (with the exact test used and why), the Excel and dashboard deliverables, risks with
fallbacks, out of scope. Then STOP and wait for my approval.

=====================================================================
STEP 3: GETTING THE DATA
=====================================================================
Use the "Marketing A/B Testing" dataset on Kaggle (real-style ad campaign experiment: about 588,000
users split between an ad-exposed group and a public-service-announcement control group, with ad
exposure count, timing, and whether each user converted):
  https://www.kaggle.com/datasets/faviovaz/marketing-ab-testing
Download it (Kaggle account required; use the Kaggle API if a token is configured, otherwise give exact
manual download steps). Save as data/raw/marketing_AB.csv, untouched. Document in docs/data_sources.md:
URL, license, date accessed, row count, columns, and date range covered.

=====================================================================
STEP 4: PROFILING AND DATA QUALITY
=====================================================================
Profile the data and write docs/data_quality_report.md. Check at minimum:
  - Group sizes and the actual vs intended split ratio (most ad-tech tests intentionally hold out a
    small control group; confirm what ratio this data actually has)
  - Missing values in any column, duplicate user records
  - Users with zero ad exposure in the test group, or exposure in the control group (contamination)
  - Distribution of total ads seen (likely extremely skewed; identify and quantify outliers)
  - Day-of-week and hour-of-day coverage for the exposure timing fields
  - Whether the conversion flag is binary and clean
Turn each into a numbered rule with severity and handling. Never drop rows silently; log every exclusion.

=====================================================================
STEP 5: TEST VALIDITY CHECKS
=====================================================================
src/validate_test.py must run and report, as the foundation the whole audit stands on:
  - Sample ratio mismatch test (chi-square against the intended split) — if this fails, flag it as a
    serious problem that undermines the whole test, and say so plainly in the memo
  - Group balance on any available non-outcome variable (e.g. day of most ads, if usable pre-treatment)
  - A novelty/time check: does the conversion rate drift over the test period in a way that suggests
    a confound, independent of the treatment effect?

=====================================================================
STEP 6: EFFECT ANALYSIS
=====================================================================
src/analyze.py:
  - Overall lift: two-proportion z-test comparing conversion rate (ad group vs control), with the
    point estimate, 95% confidence interval, p-value, and relative lift.
  - Exposure-band analysis: bucket users by total ads seen (choose defensible, documented bucket
    edges), compute conversion rate and significance per band for ad vs control, and the share of
    total ad impressions vs share of incremental conversions per band (this identifies where ad spend
    is and isn't paying off).
  - Timing analysis: conversion rate by day of week and hour of day of peak exposure.
  - Multiple comparisons: if testing many exposure bands, address multiple-comparison inflation
    (e.g. Benjamini-Hochberg) and report both raw and adjusted significance.

=====================================================================
STEP 7: ECONOMICS AND RECOMMENDATION
=====================================================================
src/economics.py, using clearly labeled, editable assumptions (cost per 1,000 impressions, value per
conversion) documented as illustrative:
  - Total media cost, incremental conversions, cost per incremental conversion, return on spend.
  - A budget reallocation scenario: what happens if impressions move from the least-efficient exposure
    band to the most-efficient one, holding total spend constant. Show the net change in conversions
    and value, and state the assumption this relies on (the receiving band's marginal payoff holds as
    volume increases).

=====================================================================
STEP 8: TESTS
=====================================================================
pytest tests: the sample ratio test correctly flags a known-bad synthetic split, the two-proportion
z-test matches a hand-calculated value on a tiny synthetic example, exposure bucketing assigns edge
values correctly, the economics scenario's arithmetic is internally consistent (impressions moved times
rate equals the reported conversion change).

=====================================================================
STEP 9: CODE STANDARDS
=====================================================================
Python 3.11+, pinned requirements.txt, virtual environment, type hints, docstrings, logging not print,
config in config.yaml (bucket edges, cost assumptions, significance thresholds), no hard-coded paths.
Lint with ruff. Makefile targets: setup, download, validate, analyze, excel, dashboard, test, all.

=====================================================================
STEP 10: EXCEL REPORT (LIVE FORMULAS)
=====================================================================
src/build_excel_report.py builds outputs/Campaign_Test_Report.xlsx with openpyxl:
  - Inputs tab: cost per 1,000 impressions, value per conversion, planned control share, a budget
    reallocation share, all in clearly marked editable cells.
  - Summary tab: users, conversions, conversion rates, lift, confidence interval, p-value, sample
    ratio check, economics, as LIVE FORMULAS referencing the Inputs and data tabs, not pasted values.
  - Exposure tab: lift and significance by band, with charts, as live formulas.
  - Recommendation tab: the budget reallocation scenario as live formulas driven by the Inputs tab.
  - Confirm zero formula errors after a full recalculation (use a recalculation tool or LibreOffice
    headless if available; otherwise document that formulas were checked by manual spot-verification
    against the Python output and say so honestly).
vba/RefreshReport.bas: a macro that reloads the data tabs from fresh CSV exports, runs basic integrity
checks (rates between 0 and 1, no missing counts), recalculates, and exports a PDF of the Summary tab,
refusing to publish if a check fails. Document how to import and run it in Excel.

=====================================================================
STEP 11: SELF-CONTAINED HTML DASHBOARD
=====================================================================
src/build_dashboard.py writes ONE self-contained HTML file (outputs/dashboard.html) using Plotly, data
embedded directly, no server needed, opens by double-click. Sections: KPI summary (lift, p-value,
economics), exposure-band chart (conversion and budget-vs-payoff), timing charts (day and hour). Keep
the file small. Take a screenshot and save it as outputs/dashboard_screenshot.png.

=====================================================================
STEP 12: HONESTY RULES
=====================================================================
Only list a tool as used if code actually ran with it. Never invent numbers; every number in README and
memo must come from script output. In AI_USE.md, list every bug found and how it was caught, and what
remains unverified (e.g. if Excel recalculation couldn't be automated).

=====================================================================
STEP 13: FINAL CHECK AND SUMMARY
=====================================================================
Run `make all` and all tests from a clean state; confirm everything passes. Confirm every number in
README.md and docs/memo.md matches script output, and the Excel file has zero formula errors. Then give
me:
1. What was built and the exact commands to run it
2. Key findings in plain language
3. Data quality and test-validity issues found and how each was handled
4. Bugs caught during the build and how
5. Anything not run or not verified
6. A resume entry: project name, tools actually used, and two bullets (goal/build, then finding).
   Plain language, only a few key numbers, no em dashes.
