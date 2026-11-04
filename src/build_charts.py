"""Render static matplotlib charts (PNG) into outputs/charts/ from the analysis output.

This genuinely exercises matplotlib (a required tool). It reads
outputs/analysis_results.json and renders:
  - conversion_by_band.png   conversion rate by exposure band (ad vs psa)
  - conversion_by_day.png     conversion rate by day-of-week (ad vs psa)
  - conversion_by_hour.png    conversion rate by hour-of-day (ad vs psa)

PNGs are made as reproducible as matplotlib allows (fixed figure size/dpi, no
embedded creation-time metadata). This target is NOT part of `make all`, so any
residual PNG non-determinism cannot dirty the `make all` tree.

CLI:
    python src/build_charts.py
    python src/build_charts.py --config PATH
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless, no display
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import load_config, setup_logging  # noqa: E402

logger = setup_logging(name="charts")

AD_COLOR = "#2563eb"
PSA_COLOR = "#9ca3af"
# Deterministic PNG: do not embed matplotlib's version/creation-time metadata.
_PNG_METADATA = {"Software": None}


def _load_analysis(config: dict[str, Any]) -> dict[str, Any]:
    path = Path(config["resolved_paths"]["outputs_dir"]) / "analysis_results.json"
    if not path.exists():
        raise FileNotFoundError(f"Analysis results not found at {path}. Run `make analyze` first.")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _grouped_bar(
    labels: list[str],
    ad_vals: list[float],
    psa_vals: list[float],
    title: str,
    xlabel: str,
    out_path: Path,
    rotate: bool = False,
) -> None:
    """Render one grouped ad-vs-psa bar chart to a PNG."""
    x = range(len(labels))
    width = 0.4
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar([i - width / 2 for i in x], ad_vals, width, label="ad", color=AD_COLOR)
    ax.bar([i + width / 2 for i in x], psa_vals, width, label="psa", color=PSA_COLOR)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("conversion rate (%)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45 if rotate else 0, ha="right" if rotate else "center")
    ax.legend()
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(out_path, dpi=100, metadata=_PNG_METADATA)
    plt.close(fig)
    logger.info("Wrote %s", out_path)


def build_charts(config: dict[str, Any]) -> list[Path]:
    """Render all static charts; return the written paths."""
    analysis = _load_analysis(config)
    charts_dir = Path(config["resolved_paths"]["charts_dir"])
    charts_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    bands = analysis["exposure"]["bands"]
    p = charts_dir / "conversion_by_band.png"
    _grouped_bar(
        [b["band"] for b in bands],
        [b["rate_ad"] * 100 for b in bands],
        [b["rate_psa"] * 100 for b in bands],
        "Conversion rate by exposure band (ad vs psa)",
        "exposure band (total ads)",
        p,
    )
    written.append(p)

    day = analysis["timing"]["by_day"]
    p = charts_dir / "conversion_by_day.png"
    _grouped_bar(
        [d["key"] for d in day],
        [d["rate_ad"] * 100 for d in day],
        [d["rate_psa"] * 100 for d in day],
        "Conversion rate by day-of-week (cross-sectional)",
        "day of week (peak exposure)",
        p,
        rotate=True,
    )
    written.append(p)

    hour = analysis["timing"]["by_hour"]
    p = charts_dir / "conversion_by_hour.png"
    _grouped_bar(
        [str(h["key"]) for h in hour],
        [h["rate_ad"] * 100 for h in hour],
        [h["rate_psa"] * 100 for h in hour],
        "Conversion rate by hour-of-day (cross-sectional)",
        "hour of day (peak exposure)",
        p,
    )
    written.append(p)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render static matplotlib charts.")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    build_charts(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
