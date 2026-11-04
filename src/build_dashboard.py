"""Build the self-contained Plotly dashboard (and optional screenshot).

Writes ONE self-contained HTML file (outputs/dashboard.html) with ALL data embedded
and plotly.js INLINED (no CDN / external references), so it opens by double-click
offline with no server. It only DISPLAYS values from outputs/analysis_results.json +
economics_results.json; it never recomputes.

Byte-stable: fixed Plotly div ids, a data-derived fingerprint in the footer, and no
wall-clock timestamp, so repeated builds are identical.

Screenshot (--screenshot): renders outputs/dashboard_screenshot.png via Playwright
(headless Chromium) if available; otherwise logs and skips gracefully (never crashes).

CLI:
    python src/build_dashboard.py               # build the HTML
    python src/build_dashboard.py --screenshot  # build HTML + PNG (best effort)
    python src/build_dashboard.py --config PATH
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import plotly.io as pio
from plotly.offline import get_plotlyjs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import load_config, setup_logging  # noqa: E402

logger = setup_logging(name="dashboard")

AD_COLOR = "#2563eb"
PSA_COLOR = "#9ca3af"
INCR_COLOR = "#059669"
IMPR_COLOR = "#f59e0b"
PLOT_CONFIG = {"displaylogo": False, "responsive": True}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Required results file not found: {path}. Run `make analyze` and "
            f"`make economics` first; the dashboard reads their JSON output."
        )
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _fig_layout(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=title,
        barmode="group",
        template="plotly_white",
        margin={"l": 60, "r": 20, "t": 50, "b": 50},
        height=380,
        legend={"orientation": "h", "y": -0.2},
    )
    return fig


def build_figures(analysis: dict[str, Any]) -> dict[str, go.Figure]:
    """Build the four dashboard figures from the analysis results."""
    ex = analysis["exposure"]
    bands = ex["bands"]
    labels = [b["band"] for b in bands]

    # 1. Conversion rate by band (ad vs psa), in percent.
    rate_fig = go.Figure()
    rate_fig.add_bar(
        x=labels, y=[b["rate_ad"] * 100 for b in bands], name="ad", marker_color=AD_COLOR
    )
    rate_fig.add_bar(
        x=labels, y=[b["rate_psa"] * 100 for b in bands], name="psa", marker_color=PSA_COLOR
    )
    rate_fig.update_yaxes(title_text="conversion rate (%)")
    rate_fig.update_xaxes(title_text="exposure band (total ads)")
    _fig_layout(rate_fig, "Conversion rate by exposure band (ad vs psa)")

    # 2. Budget vs payoff: impressions share vs incremental-conversion share.
    budget_fig = go.Figure()
    budget_fig.add_bar(
        x=labels,
        y=[(b["impressions_share"] or 0) * 100 for b in bands],
        name="share of ad impressions",
        marker_color=IMPR_COLOR,
    )
    budget_fig.add_bar(
        x=labels,
        y=[(b["incremental_share"] or 0) * 100 for b in bands],
        name="share of incremental conversions",
        marker_color=INCR_COLOR,
    )
    budget_fig.update_yaxes(title_text="share (%)")
    budget_fig.update_xaxes(title_text="exposure band (total ads)")
    _fig_layout(budget_fig, "Budget vs payoff: impressions share vs incremental share")

    # 3. Timing by day-of-week.
    day = analysis["timing"]["by_day"]
    day_fig = go.Figure()
    day_fig.add_bar(
        x=[d["key"] for d in day],
        y=[d["rate_ad"] * 100 for d in day],
        name="ad",
        marker_color=AD_COLOR,
    )
    day_fig.add_bar(
        x=[d["key"] for d in day],
        y=[d["rate_psa"] * 100 for d in day],
        name="psa",
        marker_color=PSA_COLOR,
    )
    day_fig.update_yaxes(title_text="conversion rate (%)")
    _fig_layout(day_fig, "Conversion rate by day-of-week (cross-sectional)")

    # 4. Timing by hour-of-day.
    hour = analysis["timing"]["by_hour"]
    hour_fig = go.Figure()
    hour_fig.add_bar(
        x=[h["key"] for h in hour],
        y=[h["rate_ad"] * 100 for h in hour],
        name="ad",
        marker_color=AD_COLOR,
    )
    hour_fig.add_bar(
        x=[h["key"] for h in hour],
        y=[h["rate_psa"] * 100 for h in hour],
        name="psa",
        marker_color=PSA_COLOR,
    )
    hour_fig.update_yaxes(title_text="conversion rate (%)")
    hour_fig.update_xaxes(title_text="hour of day (peak exposure)")
    _fig_layout(hour_fig, "Conversion rate by hour-of-day (cross-sectional)")

    return {
        "fig_rate_band": rate_fig,
        "fig_budget": budget_fig,
        "fig_day": day_fig,
        "fig_hour": hour_fig,
    }


def _kpi_card(label: str, value: str, sub: str = "") -> str:
    sub_html = f'<div class="kpi-sub">{sub}</div>' if sub else ""
    return (
        f'<div class="kpi"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>{sub_html}</div>'
    )


def render_html(analysis: dict[str, Any], econ: dict[str, Any]) -> str:
    """Assemble the self-contained HTML (plotly.js inlined, data embedded)."""
    o = analysis["overall"]
    h = econ["headline"]
    rc = econ["reallocation"]
    fp = analysis.get("data_fingerprint", "unknown")

    figs = build_figures(analysis)
    fig_divs = {
        name: pio.to_html(
            fig, include_plotlyjs=False, full_html=False, div_id=name, config=PLOT_CONFIG
        )
        for name, fig in figs.items()
    }

    kpis = "".join(
        [
            _kpi_card(
                "Absolute lift",
                f"+{o['abs_diff_pp']:.2f} pp",
                f"95% CI [{o['ci_low_pp']:.2f}, {o['ci_high_pp']:.2f}] pp",
            ),
            _kpi_card("Relative lift", f"+{o['relative_lift_pct']:.1f}%", "ad vs psa (causal)"),
            _kpi_card("p-value", f"{o['p_value']:.2e}", "two-proportion z-test"),
            _kpi_card("Total media cost", f"${h['total_media_cost']:,.0f}", "illustrative CPM"),
            _kpi_card(
                "Incremental conversions",
                f"{h['incremental_conversions_causal']:,.0f}",
                "from the randomized lift",
            ),
            _kpi_card(
                "Cost / incremental conv.",
                f"${h['cost_per_incremental_conversion']:,.2f}",
                f"break-even ${h['breakeven_value_per_conversion']:,.2f}/conv",
            ),
            _kpi_card(
                "ROAS",
                f"{h['roas']:.3f}",
                "NOT profitable at illustrative assumptions"
                if not h["profitable_at_assumptions"]
                else "profitable at illustrative assumptions",
            ),
            _kpi_card(
                "Break-even CPM",
                f"${h['breakeven_cpm']:.2f}",
                f"vs assumed ${h['cpm']:.2f}",
            ),
        ]
    )

    exposure_caveat = (
        "Exposure-band effects are <b>observational / endogenous</b> (engaged users "
        "both see more ads and convert more) — <b>not causal</b>; only the overall "
        "randomized lift is causal. After Benjamini-Hochberg correction <b>only the 32+ "
        "band is significant</b>; the low/mid bands are <b>not distinguishable from "
        "zero</b>. Bands 1 and 2-3 have too few control conversions to be reliable."
    )
    reco_caveat = (
        f"Budget reallocation (constant spend): the <b>conservative, defensible</b> figure "
        f"is <b>+{rc['net_conversion_change_conservative']:.1f} conversions / "
        f"+${rc['net_value_change_conservative']:,.0f}</b> (source effect set to 0, because "
        f"the source band's negative payoff is not statistically significant). The "
        f"optimistic <b>+{rc['net_conversion_change_optimistic']:.1f} conversions / "
        f"+${rc['net_value_change_optimistic']:,.0f}</b> is an upper bound only. Even the "
        f"conservative gain rests on the 32+ band's endogenous efficiency, so treat it as a "
        f"sketch, not a causal promise."
    )
    timing_caveat = (
        "Timing is a <b>cross-sectional</b> day-of-week / hour-of-day pattern of peak "
        "exposure, <b>not a time trend</b> — this dataset has no calendar/time axis, so a "
        "true novelty / drift check is not possible. Note some early hours show a psa rate "
        "of 0% simply because the small control group has very few users (and no "
        "conversions) in those hours, not because conversion is truly zero."
    )

    plotly_js = get_plotlyjs()

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Campaign A/B Test Audit — Dashboard</title>
<script>{plotly_js}</script>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         margin: 0; background: #f8fafc; color: #0f172a; }}
  header {{ background: #0f172a; color: #fff; padding: 20px 24px; }}
  header h1 {{ margin: 0 0 4px; font-size: 22px; }}
  header p {{ margin: 0; color: #cbd5e1; font-size: 13px; }}
  main {{ max-width: 1100px; margin: 0 auto; padding: 16px; }}
  h2 {{ font-size: 18px; margin: 28px 0 8px;
        border-bottom: 2px solid #e2e8f0; padding-bottom: 6px; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
  .kpi {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; }}
  .kpi-label {{ font-size: 12px; color: #64748b;
                text-transform: uppercase; letter-spacing: .03em; }}
  .kpi-value {{ font-size: 26px; font-weight: 700; margin: 4px 0; }}
  .kpi-sub {{ font-size: 12px; color: #475569; }}
  .caveat {{ background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px;
             padding: 12px 14px; font-size: 13px; line-height: 1.5; margin: 10px 0; }}
  .chart {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
            padding: 8px; margin: 12px 0; }}
  footer {{ max-width: 1100px; margin: 0 auto; padding: 16px; color: #64748b; font-size: 12px; }}
  .banner {{ background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px;
             padding: 10px 14px; font-size: 13px; margin: 12px 0; }}
</style>
</head>
<body>
<header>
  <h1>Campaign A/B Test Audit — Dashboard</h1>
  <p>Marketing A/B test: ad (treatment) vs psa (control). Self-contained, offline.</p>
</header>
<main>
  <div class="banner">All monetary figures are <b>illustrative and editable</b> (no real
  spend). The overall ad-vs-psa lift is the only <b>causal</b> estimate; band and timing
  views are descriptive.</div>

  <h2>Key results</h2>
  <div class="kpis">{kpis}</div>

  <h2>Exposure-band response</h2>
  <div class="caveat">{exposure_caveat}</div>
  <div class="caveat">{reco_caveat}</div>
  <div class="chart">{fig_divs["fig_rate_band"]}</div>
  <div class="chart">{fig_divs["fig_budget"]}</div>

  <h2>Timing (cross-sectional)</h2>
  <div class="caveat">{timing_caveat}</div>
  <div class="chart">{fig_divs["fig_day"]}</div>
  <div class="chart">{fig_divs["fig_hour"]}</div>
</main>
<footer>
  Generated by src/build_dashboard.py · data fingerprint: {fp} · plotly.js inlined
  (no external requests).
</footer>
</body>
</html>
"""


def take_screenshot(html_path: Path, png_path: Path) -> bool:
    """Render the dashboard to PNG via Playwright; skip gracefully if unavailable."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning(
            "Playwright not installed; skipping screenshot. Install with "
            "`pip install playwright && playwright install chromium` to enable it."
        )
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1200, "height": 2200})
            page.goto(html_path.resolve().as_uri())
            page.wait_for_timeout(1200)  # let Plotly render
            page.screenshot(path=str(png_path), full_page=True)
            browser.close()
    except Exception as exc:  # noqa: BLE001 - any Playwright/browser failure => skip
        logger.warning("Screenshot skipped (Playwright/browser unavailable): %s", exc)
        return False
    logger.info("Wrote %s", png_path)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the self-contained Plotly dashboard.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--screenshot", action="store_true", help="Also render a PNG screenshot.")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    outputs_dir = Path(config["resolved_paths"]["outputs_dir"])
    analysis = _load_json(outputs_dir / "analysis_results.json")
    econ = _load_json(outputs_dir / "economics_results.json")

    html = render_html(analysis, econ)
    html_path = Path(config["resolved_paths"]["dashboard_html"])
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    size_mb = html_path.stat().st_size / 1e6
    logger.info("Wrote %s (%.2f MB, self-contained, plotly.js inlined)", html_path, size_mb)

    if args.screenshot:
        png_path = Path(config["resolved_paths"]["dashboard_screenshot"])
        take_screenshot(html_path, png_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
