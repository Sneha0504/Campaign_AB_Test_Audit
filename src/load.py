"""Load, validate, and (optionally) download the Marketing A/B Testing dataset.

Expected LOGICAL schema (the loader is tolerant of the real header spelling and
of a leading unnamed index column):

    user_id       - unique user identifier
    test_group    - 'ad' (treatment) or 'psa' (control)
    converted     - bool, whether the user converted
    total_ads     - int, number of ads the user saw
    most_ads_day  - day of week of peak exposure
    most_ads_hour - int hour of day (0-23) of peak exposure

This module never fabricates data. If the CSV is missing it raises an actionable
error (library use) or prints clear instructions (CLI use); it does not create a
placeholder file.

CLI:
    python src/load.py --info       # row count / columns / dtypes, or a missing-file message
    python src/load.py --download   # Kaggle API if a token exists, else manual steps
    python src/load.py --config PATH
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

# Ensure the project root is importable when run as a script (python src/load.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import load_config, setup_logging  # noqa: E402

logger = setup_logging(name="load")

# Canonical column name -> accepted aliases (normalized: lowercased, single-spaced).
EXPECTED_SCHEMA: dict[str, list[str]] = {
    "user_id": ["user id", "user_id", "userid", "id"],
    "test_group": ["test group", "test_group", "group", "testgroup"],
    "converted": ["converted", "conversion"],
    "total_ads": ["total ads", "total_ads", "ads", "totalads"],
    "most_ads_day": ["most ads day", "most_ads_day", "day"],
    "most_ads_hour": ["most ads hour", "most_ads_hour", "hour"],
}

_BOOL_MAP = {
    "true": True,
    "false": False,
    "1": True,
    "0": False,
    "yes": True,
    "no": False,
    "t": True,
    "f": False,
}


def _normalize(name: Any) -> str:
    """Normalize a header for matching: strip, lowercase, collapse whitespace."""
    return " ".join(str(name).strip().lower().split())


def _download_instructions(path: Path, dataset: str, url: str) -> str:
    """Build the actionable 'how to get the data' message shared by all paths."""
    return (
        f"Dataset not found at: {path}\n"
        f"The Marketing A/B Testing CSV is NOT committed (data/raw is git-ignored).\n"
        f"Obtain it one of two ways:\n"
        f"  A) Kaggle API (requires ~/.kaggle/kaggle.json token + 'pip install kaggle'):\n"
        f"       make download          # or: python src/load.py --download\n"
        f"  B) Manual download:\n"
        f"       1. Sign in at {url}\n"
        f"       2. Click 'Download' ({dataset}) and unzip the archive\n"
        f"       3. Place 'marketing_AB.csv' at: {path}\n"
    )


def _drop_index_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Drop blank / 'Unnamed: N' columns that pandas emits for a saved index."""
    keep = [c for c in df.columns if _normalize(c) and not _normalize(c).startswith("unnamed")]
    return df.loc[:, keep]


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns to the canonical schema where an alias matches."""
    normalized = {col: _normalize(col) for col in df.columns}
    rename: dict[Any, str] = {}
    for canonical, aliases in EXPECTED_SCHEMA.items():
        alias_set = {_normalize(a) for a in aliases} | {canonical}
        for col, norm in normalized.items():
            if norm in alias_set and col not in rename:
                rename[col] = canonical
                break
    return df.rename(columns=rename)


def _validate_schema(df: pd.DataFrame) -> None:
    """Raise if any expected column is absent after standardization."""
    missing = [c for c in EXPECTED_SCHEMA if c not in df.columns]
    if missing:
        raise ValueError(
            f"CSV is missing expected columns {missing}. "
            f"Found columns: {list(df.columns)}. "
            f"Update EXPECTED_SCHEMA aliases in src/load.py if the real headers differ."
        )


def _coerce_bool(series: pd.Series) -> pd.Series:
    """Coerce a conversion column to clean bool, raising on unmappable values."""
    if series.dtype == bool:
        return series
    mapped = series.astype(str).str.strip().str.lower().map(_BOOL_MAP)
    if mapped.isna().any():
        bad = sorted(series[mapped.isna()].astype(str).str.strip().unique())[:10]
        raise ValueError(f"'converted' has non-boolean values, e.g. {bad}")
    return mapped.astype(bool)


def numeric_coercion_na_count(series: pd.Series) -> int:
    """Count values that are non-null in ``series`` but become NA under numeric coercion.

    ``pd.to_numeric(errors="coerce")`` silently turns unparseable values into NaN;
    this surfaces how many real values were lost so they are not hidden.
    """
    coerced = pd.to_numeric(series, errors="coerce")
    return int((coerced.isna() & series.notna()).sum())


def _coerce_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce known columns to tidy dtypes; leave categorical fields as-is.

    Numeric coercions that drop real (non-null) values to NA are logged as
    warnings rather than hidden, so downstream profiling can account for them.
    """
    df = df.copy()
    df["converted"] = _coerce_bool(df["converted"])
    for col in ("total_ads", "most_ads_hour"):
        lost = numeric_coercion_na_count(df[col])
        if lost:
            logger.warning(
                "%d non-null value(s) in '%s' could not be parsed as numeric and became NA",
                lost,
                col,
            )
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    df["test_group"] = df["test_group"].astype(str).str.strip().str.lower()
    df["most_ads_day"] = df["most_ads_day"].astype(str).str.strip()
    return df


def load_data(
    config: dict[str, Any] | None = None,
    path: str | Path | None = None,
    download_if_missing: bool = False,
) -> pd.DataFrame:
    """Load the dataset into a validated, type-coerced DataFrame.

    Args:
        config: Parsed config dict; loaded from the default location if omitted.
        path: Override for the CSV path; defaults to the configured raw path.
        download_if_missing: If True, attempt a Kaggle download before giving up.

    Returns:
        A DataFrame with the canonical schema.

    Raises:
        FileNotFoundError: If the CSV cannot be found (and could not be downloaded).
        ValueError: If the schema or data types are invalid.
    """
    config = config or load_config()
    data_cfg = config.get("data", {})
    if path is None:
        path = config["resolved_paths"]["data_raw"]
    path = Path(path)

    if not path.exists() and download_if_missing:
        download_dataset(config)

    if not path.exists():
        raise FileNotFoundError(
            _download_instructions(
                path,
                data_cfg.get("kaggle_dataset", "faviovaz/marketing-ab-testing"),
                data_cfg.get(
                    "kaggle_url", "https://www.kaggle.com/datasets/faviovaz/marketing-ab-testing"
                ),
            )
        )

    logger.info("Reading CSV: %s", path)
    df = pd.read_csv(path)
    df = _drop_index_columns(df)
    df = standardize_columns(df)
    _validate_schema(df)
    df = _coerce_dtypes(df)
    logger.info("Loaded %d rows x %d columns", len(df), df.shape[1])
    return df


def _kaggle_token_present() -> bool:
    """True if a Kaggle API token is configured (file or env vars)."""
    if (Path.home() / ".kaggle" / "kaggle.json").exists():
        return True
    return bool(os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"))


def download_dataset(config: dict[str, Any] | None = None) -> bool:
    """Attempt to download the dataset via the Kaggle API; never fail hard.

    If no token (or the ``kaggle`` package) is available, print the manual steps
    and return False.

    Returns:
        True if the CSV is present after the attempt, else False.
    """
    config = config or load_config()
    data_cfg = config.get("data", {})
    target = Path(config["resolved_paths"]["data_raw"])
    dataset = data_cfg.get("kaggle_dataset", "faviovaz/marketing-ab-testing")
    url = data_cfg.get(
        "kaggle_url", "https://www.kaggle.com/datasets/faviovaz/marketing-ab-testing"
    )

    if target.exists():
        logger.info("Dataset already present at %s", target)
        return True

    if not _kaggle_token_present():
        logger.warning("No Kaggle token found at ~/.kaggle/kaggle.json.")
        print(_download_instructions(target, dataset, url))
        return False

    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError:
        logger.warning("Kaggle token found, but the 'kaggle' package is not installed.")
        print("Install it with: pip install kaggle\n")
        print(_download_instructions(target, dataset, url))
        return False

    try:
        api = KaggleApi()
        api.authenticate()
        target.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading %s via Kaggle API into %s", dataset, target.parent)
        api.dataset_download_files(dataset, path=str(target.parent), unzip=True)
    except Exception as exc:  # noqa: BLE001 - surface any API failure as instructions
        logger.error("Kaggle API download failed: %s", exc)
        print(_download_instructions(target, dataset, url))
        return False

    if target.exists():
        logger.info("Download complete: %s", target)
        return True

    # Unzipped file may have a different name; look for a single CSV and rename.
    csvs = sorted(target.parent.glob("*.csv"))
    if len(csvs) == 1 and csvs[0] != target:
        csvs[0].rename(target)
        logger.info("Renamed %s -> %s", csvs[0].name, target.name)
    if not target.exists():
        logger.warning("Download ran but %s is not present; check %s", target, target.parent)
        print(_download_instructions(target, dataset, url))
    return target.exists()


def _print_info(df: pd.DataFrame) -> None:
    """Print row count, columns, and dtypes for the loaded DataFrame."""
    print(f"Rows: {len(df)}")
    print(f"Columns ({df.shape[1]}): {list(df.columns)}")
    print("Dtypes:")
    print(df.dtypes.to_string())


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        description="Load / inspect / download the Marketing A/B Testing dataset."
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Print row count, columns, and dtypes if the CSV exists.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download via the Kaggle API if a token exists, else print manual steps.",
    )
    parser.add_argument("--config", default=None, help="Path to config.yaml.")
    args = parser.parse_args(argv)

    config = load_config(args.config)

    if args.download:
        download_dataset(config)
        return 0

    # Default action and --info both inspect the file, degrading gracefully.
    path = Path(config["resolved_paths"]["data_raw"])
    if not path.exists():
        data_cfg = config.get("data", {})
        print(
            _download_instructions(
                path,
                data_cfg.get("kaggle_dataset", "faviovaz/marketing-ab-testing"),
                data_cfg.get(
                    "kaggle_url", "https://www.kaggle.com/datasets/faviovaz/marketing-ab-testing"
                ),
            )
        )
        return 1

    df = load_data(config, path=path)
    _print_info(df)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
