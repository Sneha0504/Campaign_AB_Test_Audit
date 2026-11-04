"""Build the self-service Excel report with LIVE FORMULAS (openpyxl).

Reads outputs/analysis_results.json + outputs/economics_results.json and writes
outputs/Campaign_Test_Report.xlsx. The only *values* in the workbook are the raw
Python-computed aggregates on the Data tab and the editable cells on the Inputs tab;
every headline metric on the Summary / Exposure / Recommendation tabs is a LIVE EXCEL
FORMULA referencing those cells, so editing a count or an input recomputes everything.

Zero-formula-errors verification (HONEST): there is no LibreOffice/Excel in this
environment to force a recalculation, and openpyxl does not evaluate formulas. So this
module includes a small formula evaluator (`--verify`, run by default) that parses the
workbook, recursively evaluates each key formula cell by substituting the referenced
Data/Inputs cells, and compares the result to the authoritative JSON values. It reports
cells-checked / mismatches. It does NOT claim Excel recalculated the file.

Byte-stability: workbook core timestamps are pinned so two `make excel` runs produce a
byte-identical .xlsx (verified by sha256), keeping `make all` trees clean.

CLI:
    python src/build_excel_report.py              # build + verify + write doc
    python src/build_excel_report.py --no-verify
    python src/build_excel_report.py --config PATH
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.workbook.properties import CalcProperties
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import load_config, setup_logging  # noqa: E402

logger = setup_logging(name="excel")

# Pinned timestamp so the .xlsx is byte-reproducible (fixed, not wall-clock).
_FIXED_TS = dt.datetime(2020, 1, 1, 0, 0, 0)

HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
TITLE_FONT = Font(bold=True, size=13)
BOLD = Font(bold=True)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Required results file not found: {path}. Run `make analyze` and "
            f"`make economics` first; the Excel report reads their JSON output."
        )
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- build


def _build_inputs(wb: Workbook, econ: dict[str, Any], config: dict[str, Any]) -> None:
    ws = wb.create_sheet("Inputs")
    ws["A1"] = "Inputs (EDITABLE — shaded cells)"
    ws["A1"].font = TITLE_FONT
    h = econ["headline"]
    rc = econ["reallocation"]
    planned_control_share = float(config.get("validity", {}).get("intended_control_share", 0.04))
    rows = [
        ("cpm", h["cpm"]),
        ("value_per_conversion", h["value_per_conversion"]),
        ("planned_control_share", planned_control_share),
        ("reallocation_share", rc["reallocation_share"]),
    ]
    for i, (label, value) in enumerate(rows, start=2):
        ws[f"A{i}"] = label
        ws[f"A{i}"].font = BOLD
        ws[f"B{i}"] = value
        ws[f"B{i}"].fill = INPUT_FILL
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 14


def _build_data(wb: Workbook, analysis: dict[str, Any]) -> dict[str, int]:
    """Write raw aggregates as plain numbers; return band-row bookkeeping."""
    ws = wb.create_sheet("Data")
    ws["A1"] = "RAW AGGREGATES (Python-computed values; do not edit)"
    ws["A1"].font = TITLE_FONT
    o = analysis["overall"]
    ex = analysis["exposure"]

    ws["A3"] = "metric"
    ws["B3"] = "value"
    ws["A3"].font = ws["B3"].font = BOLD
    overall = [
        ("n_ad", o["n_ad"]),
        ("conv_ad", o["conv_ad"]),
        ("n_psa", o["n_psa"]),
        ("conv_psa", o["conv_psa"]),
        ("total_ad_impressions", ex["total_ad_impressions"]),
    ]
    for i, (label, value) in enumerate(overall, start=4):
        ws[f"A{i}"] = label
        ws[f"B{i}"] = value

    # Per-band block.
    ws["A10"] = "Per-band aggregates"
    ws["A10"].font = BOLD
    headers = ["band", "n_ad", "conv_ad", "n_psa", "conv_psa", "ad_impressions"]
    for col, head in enumerate(headers, start=1):
        c = ws.cell(row=11, column=col, value=head)
        c.font = BOLD
        c.fill = HEADER_FILL
    first_band_row = 12
    for j, b in enumerate(ex["bands"]):
        r = first_band_row + j
        ws.cell(row=r, column=1, value=b["band"])
        ws.cell(row=r, column=2, value=b["n_ad"])
        ws.cell(row=r, column=3, value=b["conv_ad"])
        ws.cell(row=r, column=4, value=b["n_psa"])
        ws.cell(row=r, column=5, value=b["conv_psa"])
        ws.cell(row=r, column=6, value=b["ad_impressions"])
    ws.column_dimensions["A"].width = 22
    return {"first_band_row": first_band_row, "n_bands": len(ex["bands"])}


def _build_summary(wb: Workbook) -> None:
    ws = wb.create_sheet("Summary")
    ws["A1"] = "Summary — live formulas over Data + Inputs"
    ws["A1"].font = TITLE_FONT

    def lab(cell: str, text: str) -> None:
        ws[cell] = text
        ws[cell].font = BOLD

    # Groups block.
    for col, head in zip("ABCD", ["group", "users", "conversions", "conv rate"], strict=True):
        c = ws[f"{col}3"]
        c.value = head
        c.font = BOLD
        c.fill = HEADER_FILL
    ws["A4"] = "ad"
    ws["B4"] = "=Data!B4"
    ws["C4"] = "=Data!B5"
    ws["D4"] = "=C4/B4"
    ws["A5"] = "psa"
    ws["B5"] = "=Data!B6"
    ws["C5"] = "=Data!B7"
    ws["D5"] = "=C5/B5"

    lab("A7", "absolute lift (pp)")
    ws["B7"] = "=(D4-D5)*100"
    lab("A8", "relative lift (%)")
    ws["B8"] = "=(D4-D5)/D5*100"
    lab("A9", "pooled proportion")
    ws["B9"] = "=(C4+C5)/(B4+B5)"
    lab("A10", "pooled SE")
    ws["B10"] = "=SQRT(B9*(1-B9)*(1/B4+1/B5))"
    lab("A11", "z-statistic")
    ws["B11"] = "=(D4-D5)/B10"
    lab("A12", "p-value (two-sided)")
    # Use the lower tail of -|z| (NOT 1 - upper tail) to avoid catastrophic
    # cancellation for small p-values; this matches scipy's survival function.
    ws["B12"] = "=2*NORM.S.DIST(-ABS(B11),TRUE)"
    lab("A13", "unpooled SE")
    ws["B13"] = "=SQRT(D4*(1-D4)/B4+D5*(1-D5)/B5)"
    lab("A14", "z critical (95%)")
    ws["B14"] = "=NORM.S.INV(0.975)"
    lab("A15", "95% CI low (pp)")
    ws["B15"] = "=((D4-D5)-B14*B13)*100"
    lab("A16", "95% CI high (pp)")
    ws["B16"] = "=((D4-D5)+B14*B13)*100"

    lab("A18", "SRM check")
    lab("A19", "intended control share")
    ws["B19"] = "=Inputs!B4"
    lab("A20", "expected ad")
    ws["B20"] = "=(B4+B5)*(1-B19)"
    lab("A21", "expected psa")
    ws["B21"] = "=(B4+B5)*B19"
    lab("A22", "chi-square (df=1)")
    ws["B22"] = "=(B4-B20)^2/B20+(B5-B21)^2/B21"
    lab("A23", "SRM p-value")
    ws["B23"] = "=CHISQ.DIST.RT(B22,1)"
    lab("A24", "SRM verdict")
    ws["B24"] = '=IF(B23<0.05,"FAIL (SRM)","PASS")'

    lab("A26", "Economics (illustrative)")
    lab("A27", "CPM")
    ws["B27"] = "=Inputs!B2"
    lab("A28", "value per conversion")
    ws["B28"] = "=Inputs!B3"
    lab("A29", "total ad impressions")
    ws["B29"] = "=Data!B8"
    lab("A30", "total media cost")
    ws["B30"] = "=B29*B27/1000"
    lab("A31", "incremental conversions (causal)")
    ws["B31"] = "=B4*(D4-D5)"
    lab("A32", "cost per incremental conversion")
    ws["B32"] = "=B30/B31"
    lab("A33", "value of incremental")
    ws["B33"] = "=B31*B28"
    lab("A34", "ROAS")
    ws["B34"] = "=B33/B30"
    lab("A35", "break-even value/conversion")
    ws["B35"] = "=B30/B31"
    lab("A36", "break-even CPM")
    ws["B36"] = "=B33*1000/B29"

    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 16


def _build_exposure(wb: Workbook, book: dict[str, int]) -> None:
    ws = wb.create_sheet("Exposure")
    ws["A1"] = "Exposure bands — live formulas over Data (observational)"
    ws["A1"].font = TITLE_FONT
    headers = [
        "band",
        "n_ad",
        "conv_ad",
        "rate_ad",
        "n_psa",
        "conv_psa",
        "rate_psa",
        "abs lift (pp)",
        "pooled SE",
        "z",
        "p",
        "ad_impr",
        "impr share",
        "incremental",
        "incr share",
    ]
    hdr_row = 2
    for col, head in enumerate(headers, start=1):
        c = ws.cell(row=hdr_row, column=col, value=head)
        c.font = BOLD
        c.fill = HEADER_FILL

    first = hdr_row + 1  # data starts row 3
    n = book["n_bands"]
    last = first + n - 1
    for j in range(n):
        r = first + j
        dr = book["first_band_row"] + j  # matching Data row
        ws[f"A{r}"] = f"=Data!A{dr}"
        ws[f"B{r}"] = f"=Data!B{dr}"
        ws[f"C{r}"] = f"=Data!C{dr}"
        ws[f"D{r}"] = f"=C{r}/B{r}"
        ws[f"E{r}"] = f"=Data!D{dr}"
        ws[f"F{r}"] = f"=Data!E{dr}"
        ws[f"G{r}"] = f"=F{r}/E{r}"
        ws[f"H{r}"] = f"=(D{r}-G{r})*100"
        ws[f"I{r}"] = (
            f"=SQRT(((C{r}+F{r})/(B{r}+E{r}))*(1-((C{r}+F{r})/(B{r}+E{r})))*(1/B{r}+1/E{r}))"
        )
        ws[f"J{r}"] = f"=(D{r}-G{r})/I{r}"
        ws[f"K{r}"] = f"=2*NORM.S.DIST(-ABS(J{r}),TRUE)"
        ws[f"L{r}"] = f"=Data!F{dr}"
        ws[f"M{r}"] = f"=L{r}/Data!$B$8"
        ws[f"N{r}"] = f"=B{r}*(D{r}-G{r})"
        ws[f"O{r}"] = f"=N{r}/SUM($N${first}:$N${last})"

    # Charts.
    cats = Reference(ws, min_col=1, min_row=first, max_row=last)
    chart1 = BarChart()
    chart1.title = "Conversion rate by band (ad vs psa)"
    chart1.type = "col"
    rate_ref = Reference(ws, min_col=4, max_col=4, min_row=hdr_row, max_row=last)
    psa_ref = Reference(ws, min_col=7, max_col=7, min_row=hdr_row, max_row=last)
    chart1.add_data(rate_ref, titles_from_data=True)
    chart1.add_data(psa_ref, titles_from_data=True)
    chart1.set_categories(cats)
    ws.add_chart(chart1, f"A{last + 3}")

    chart2 = BarChart()
    chart2.title = "Impressions share vs incremental share by band"
    chart2.type = "col"
    impr_ref = Reference(ws, min_col=13, max_col=13, min_row=hdr_row, max_row=last)
    incr_ref = Reference(ws, min_col=15, max_col=15, min_row=hdr_row, max_row=last)
    chart2.add_data(impr_ref, titles_from_data=True)
    chart2.add_data(incr_ref, titles_from_data=True)
    chart2.set_categories(cats)
    ws.add_chart(chart2, f"A{last + 20}")

    ws.column_dimensions["A"].width = 10


def _build_recommendation(
    wb: Workbook, econ: dict[str, Any], analysis: dict[str, Any], book: dict[str, int]
) -> None:
    ws = wb.create_sheet("Recommendation")
    ws["A1"] = "Recommendation — budget reallocation (live formulas, Inputs-driven)"
    ws["A1"].font = TITLE_FONT

    rc = econ["reallocation"]
    labels = list(analysis["exposure"]["band_labels"])
    src_idx = labels.index(rc["source_band"])
    dst_idx = labels.index(rc["dest_band"])
    first = 3  # Exposure data first row
    src_row = first + src_idx
    dst_row = first + dst_idx

    def lab(cell: str, text: str) -> None:
        ws[cell] = text
        ws[cell].font = BOLD

    lab("A3", "source band (least-efficient reliable)")
    ws["B3"] = rc["source_band"]
    lab("A4", "destination band (most-efficient reliable)")
    ws["B4"] = rc["dest_band"]
    lab("A5", "source ad impressions")
    ws["B5"] = f"=Exposure!L{src_row}"
    lab("A6", "destination efficiency (conv/impr)")
    ws["B6"] = f"=Exposure!N{dst_row}/Exposure!L{dst_row}"
    lab("A7", "source efficiency (conv/impr)")
    ws["B7"] = f"=Exposure!N{src_row}/Exposure!L{src_row}"
    lab("A8", "impressions moved")
    ws["B8"] = "=Inputs!B5*B5"
    lab("A9", "CONSERVATIVE net conversions (defensible)")
    ws["B9"] = "=B8*B6"
    lab("A10", "CONSERVATIVE net value")
    ws["B10"] = "=B9*Inputs!B3"
    lab("A11", "optimistic net conversions (upper bound)")
    ws["B11"] = "=B8*(B6-B7)"
    lab("A12", "optimistic net value")
    ws["B12"] = "=B11*Inputs!B3"

    caveat = (
        "HONESTY: lead with the conservative figure. The source band's negative payoff "
        "is NOT statistically significant (its 95% CI includes 0), so crediting the "
        "'source removal' treats noise as signal (plus a winner's-curse selection). The "
        "32+ destination efficiency is OBSERVATIONAL and ENDOGENOUS — high-exposure "
        "users are self-selected, not buyable — so even the conservative gain is an "
        "upper-bound-style sketch, not a causal promise. Base the real call on the "
        "causal headline economics (ROAS < 1 at the illustrative assumptions)."
    )
    ws["A14"] = "Caveat"
    ws["A14"].font = BOLD
    ws["A15"] = caveat
    ws["A15"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells("A15:H24")
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 18


def build_workbook(
    analysis: dict[str, Any], econ: dict[str, Any], config: dict[str, Any]
) -> tuple[Workbook, dict[str, int]]:
    """Assemble the workbook; return it plus band bookkeeping for verification."""
    wb = Workbook()
    wb.remove(wb.active)  # drop default sheet
    _build_inputs(wb, econ, config)
    book = _build_data(wb, analysis)
    _build_summary(wb)
    _build_exposure(wb, book)
    _build_recommendation(wb, econ, analysis, book)

    wb.properties.created = _FIXED_TS
    wb.properties.modified = _FIXED_TS
    wb.properties.creator = ""
    wb.properties.lastModifiedBy = ""
    wb.calculation = CalcProperties(fullCalcOnLoad=True)
    return wb, book


# ----------------------------------------------------------------- formula verify

_CELLREF = re.compile(r"(?:([A-Za-z]+)!)?\$?([A-Z]{1,3})\$?(\d+)")


def _normsdist(x: float, _cum: bool = True) -> float:
    return float(stats.norm.cdf(x))


def _normsinv(p: float) -> float:
    return float(stats.norm.ppf(p))


def _chisq_rt(x: float, df: float) -> float:
    return float(stats.chi2.sf(x, df))


class _Evaluator:
    """Minimal recursive evaluator for the formula subset used in this workbook."""

    def __init__(self, wb: Workbook) -> None:
        self.wb = wb
        self.memo: dict[tuple[str, str], float] = {}

    def value(self, sheet: str, coord: str) -> float:
        key = (sheet, coord.replace("$", ""))
        if key in self.memo:
            return self.memo[key]
        raw = self.wb[sheet][key[1]].value
        if isinstance(raw, int | float):
            result = float(raw)
        elif isinstance(raw, str) and raw.startswith("="):
            result = self._eval(raw[1:], sheet)
        else:
            raise ValueError(f"Cell {sheet}!{coord} is not numeric: {raw!r}")
        self.memo[key] = result
        return result

    def _eval(self, expr: str, sheet: str) -> float:
        expr = expr.replace("CHISQ.DIST.RT(", "_chisq_rt(")
        expr = expr.replace("NORM.S.DIST(", "_normsdist(")
        expr = expr.replace("NORM.S.INV(", "_normsinv(")
        expr = expr.replace("SQRT(", "math.sqrt(")
        expr = expr.replace("ABS(", "abs(")
        expr = expr.replace("TRUE", "True").replace("FALSE", "False")
        expr = expr.replace("^", "**")
        expr = re.sub(r"SUM\(([^)]+)\)", lambda m: self._sum(m.group(1), sheet), expr)
        expr = _CELLREF.sub(lambda m: repr(self._ref(m, sheet)), expr)
        return float(
            eval(
                expr,
                {  # noqa: S307 - trusted, self-generated formulas only
                    "math": math,
                    "_normsdist": _normsdist,
                    "_normsinv": _normsinv,
                    "_chisq_rt": _chisq_rt,
                },
            )
        )

    def _ref(self, m: re.Match, sheet: str) -> float:
        ref_sheet = m.group(1) or sheet
        coord = f"{m.group(2)}{m.group(3)}"
        return self.value(ref_sheet, coord)

    def _sum(self, rng: str, sheet: str) -> str:
        start, end = rng.replace("$", "").split(":")
        col = re.match(r"([A-Z]+)(\d+)", start)
        col2 = re.match(r"([A-Z]+)(\d+)", end)
        assert col and col2
        c = col.group(1)
        total = sum(
            self.value(sheet, f"{c}{row}")
            for row in range(int(col.group(2)), int(col2.group(2)) + 1)
        )
        return f"({total!r})"


def verify_workbook(
    wb: Workbook, analysis: dict[str, Any], econ: dict[str, Any], config: dict[str, Any]
) -> tuple[int, list[str]]:
    """Evaluate key formula cells and compare to authoritative JSON values.

    Returns (cells_checked, mismatches). A mismatch string names the cell + values.
    """
    ev = _Evaluator(wb)
    o = analysis["overall"]
    ex = analysis["exposure"]
    h = econ["headline"]
    rc = econ["reallocation"]
    checks: list[tuple[str, str, float]] = []

    # Summary.
    checks += [
        ("Summary", "D4", o["rate_ad"]),
        ("Summary", "D5", o["rate_psa"]),
        ("Summary", "B7", o["abs_diff_pp"]),
        ("Summary", "B8", o["relative_lift_pct"]),
        ("Summary", "B11", o["z"]),
        ("Summary", "B12", o["p_value"]),
        ("Summary", "B15", o["ci_low_pp"]),
        ("Summary", "B16", o["ci_high_pp"]),
        ("Summary", "B30", h["total_media_cost"]),
        ("Summary", "B31", h["incremental_conversions_causal"]),
        ("Summary", "B32", h["cost_per_incremental_conversion"]),
        ("Summary", "B33", h["value_of_incremental"]),
        ("Summary", "B34", h["roas"]),
        ("Summary", "B35", h["breakeven_value_per_conversion"]),
        ("Summary", "B36", h["breakeven_cpm"]),
    ]
    # SRM chi-square / p from the same raw counts + the configured intended split
    # (the share that Inputs!B4 holds), authoritative via scipy.
    control_share = float(config.get("validity", {}).get("intended_control_share", 0.04))
    total = o["n_ad"] + o["n_psa"]
    srm = stats.chisquare(
        f_obs=[o["n_ad"], o["n_psa"]],
        f_exp=[total * (1 - control_share), total * control_share],
    )
    checks += [("Summary", "B22", float(srm.statistic)), ("Summary", "B23", float(srm.pvalue))]

    # Exposure per band.
    first = 3
    for j, b in enumerate(ex["bands"]):
        r = first + j
        checks += [
            ("Exposure", f"D{r}", b["rate_ad"]),
            ("Exposure", f"G{r}", b["rate_psa"]),
            ("Exposure", f"H{r}", b["abs_diff_pp"]),
            ("Exposure", f"J{r}", b["z"]),
            ("Exposure", f"K{r}", b["p_raw"]),
            ("Exposure", f"M{r}", b["impressions_share"]),
            ("Exposure", f"N{r}", b["incremental_conversions"]),
            ("Exposure", f"O{r}", b["incremental_share"]),
        ]

    # Recommendation.
    checks += [
        ("Recommendation", "B8", rc["impressions_moved"]),
        ("Recommendation", "B9", rc["net_conversion_change_conservative"]),
        ("Recommendation", "B10", rc["net_value_change_conservative"]),
        ("Recommendation", "B11", rc["net_conversion_change_optimistic"]),
        ("Recommendation", "B12", rc["net_value_change_optimistic"]),
    ]

    mismatches: list[str] = []
    for sheet, coord, expected in checks:
        actual = ev.value(sheet, coord)
        # Relative tolerance (abs_tol=0) so tiny p-values are tested meaningfully, not
        # swamped by a large absolute floor. No checked value is legitimately zero.
        if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=0.0):
            mismatches.append(f"{sheet}!{coord}: formula={actual!r} json={expected!r}")
    return len(checks), mismatches


# ----------------------------------------------------------------------- outputs


def render_doc(
    config: dict[str, Any],
    analysis: dict[str, Any],
    checked: int,
    mismatches: list[str],
    formula_count: int,
) -> str:
    fp = analysis.get("data_fingerprint", "unknown")
    status = "0 mismatches" if not mismatches else f"{len(mismatches)} MISMATCHES"
    return f"""# Excel Report & VBA Macro — Campaign_AB_Test_Audit

_Auto-generated by `src/build_excel_report.py`. Data fingerprint: {fp}._

## What the workbook contains (`outputs/Campaign_Test_Report.xlsx`)

- **Inputs** (editable, shaded): `cpm`, `value_per_conversion`, `planned_control_share`,
  `reallocation_share`.
- **Data**: the only *values* — Python-computed raw aggregates (group counts and
  conversions, per-band counts and ad impressions). Do not edit.
- **Summary** (LIVE FORMULAS): conversion rates, absolute/relative lift, pooled-SE
  two-proportion z, p-value, 95% CI, SRM chi-square + PASS/FAIL, and economics
  (media cost, incremental, cost/incremental, value, ROAS, break-evens).
- **Exposure** (LIVE FORMULAS + charts): per-band rates, lift, z/p, impressions share
  vs incremental share, with two column charts.
- **Recommendation** (LIVE FORMULAS, Inputs-driven): the reallocation scenario with
  the conservative (defensible) figure led, the optimistic upper bound, and the honesty
  caveat as cell text.

There are **{formula_count} live-formula cells**. Editing any Data count or any Inputs
cell recomputes every dependent metric in Excel.

## Formula verification (HONEST)

There is **no LibreOffice/Excel in the build environment**, and openpyxl does not
evaluate formulas, so the workbook was **NOT recalculated by Excel here**. Instead,
correctness was verified two ways:

1. **Cell-reference construction** — formulas reference the Inputs/Data cells by address.
2. **Python spot-verification** — a small evaluator parses the workbook, recursively
   evaluates each key formula cell by substituting the referenced cells, and compares the
   result to the authoritative values in `analysis_results.json` /
   `economics_results.json`. Result: **{checked} formula cells checked, {status}**.

`wb.calculation.fullCalcOnLoad` is set, so Excel will recalculate on open. We do **not**
claim Excel recalculated the file in this environment.

## VBA macro (`vba/RefreshReport.bas`)

The macro reloads the Data tabs from the committed `outputs/*.csv`, runs integrity checks
(all rates in [0,1]; no missing/blank counts), forces a recalculation, exports the
Summary tab to PDF, and **refuses to publish** (MsgBox + exit) if any check fails.

**Import & run:** Excel → Developer → Visual Basic → File → Import File… → select
`vba/RefreshReport.bas` → close the editor → Developer → Macros → `RefreshReport` → Run.
(Enable the Developer ribbon via File → Options → Customize Ribbon → Developer.)

The VBA was **NOT executed** in this environment (no automatable Excel); it is shipped
and verified by code review only. This is stated honestly and will be recorded in
`AI_USE.md`.

## Byte-stability

Workbook core timestamps are pinned to a fixed value, so repeated `make excel` runs
produce a byte-identical `.xlsx` (verified by sha256), keeping `make all` trees clean.
"""


def _rewrite_zip_stable(path: Path) -> None:
    """Rewrite the .xlsx zip with fixed entry timestamps for byte-reproducibility.

    openpyxl stamps each zip entry with the current time, so two saves differ. This
    re-zips the same entries (same order, same bytes) with a fixed 1980-01-01 date_time.
    """
    original = path.read_bytes()
    fixed_iso = b"2020-01-01T00:00:00Z"
    with zipfile.ZipFile(io.BytesIO(original)) as zin:
        names = zin.namelist()
        entries = [(name, zin.read(name)) for name in names]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in entries:
            if name == "docProps/core.xml":
                # openpyxl resets 'modified' to the wall clock at save; pin it here.
                data = re.sub(rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", fixed_iso, data)
            info = zipfile.ZipInfo(name)  # date_time defaults to (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            zout.writestr(info, data)
    path.write_bytes(buf.getvalue())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the live-formula Excel report.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--no-verify", action="store_true", help="Skip formula verification.")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    outputs_dir = Path(config["resolved_paths"]["outputs_dir"])
    docs_dir = Path(config["resolved_paths"]["docs_dir"])
    analysis = _load_json(outputs_dir / "analysis_results.json")
    econ = _load_json(outputs_dir / "economics_results.json")

    wb, _ = build_workbook(analysis, econ, config)

    formula_count = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    formula_count += 1

    checked, mismatches = 0, []
    if not args.no_verify:
        checked, mismatches = verify_workbook(wb, analysis, econ, config)
        if mismatches:
            for m in mismatches:
                logger.error("Formula mismatch: %s", m)
            logger.error("Formula verification FAILED: %d/%d mismatched", len(mismatches), checked)
            return 1
        logger.info("Formula verification: %d cells checked, 0 mismatches", checked)
    logger.info("Live-formula cells: %d", formula_count)
    logger.info(
        "NOTE: Excel/LibreOffice recalc not available here; formulas verified by Python "
        "spot-check + cell references (NOT claimed recalculated in Excel)."
    )

    out_path = Path(config["resolved_paths"]["excel_report"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    _rewrite_zip_stable(out_path)
    logger.info("Wrote %s", out_path)

    doc_path = docs_dir / "excel_report.md"
    doc_path.write_text(render_doc(config, analysis, checked, mismatches, formula_count), "utf-8")
    logger.info("Wrote %s", doc_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
