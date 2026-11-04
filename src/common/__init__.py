"""Shared helpers: configuration loading, path resolution, and logging setup.

These are the building blocks the rest of the pipeline imports. Paths declared in
``config/config.yaml`` are stored relative to the project root and resolved to
absolute paths here, so no module hard-codes a filesystem location.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import yaml

# Project root is two levels up from this file: <root>/src/common/__init__.py
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

_LOG_INITIALIZED = False


def resolve_path(rel_path: str | Path) -> Path:
    """Resolve a (possibly relative) path against the project root.

    Absolute paths are returned unchanged.
    """
    p = Path(rel_path)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load the YAML config and resolve every ``paths`` entry to an absolute path.

    Args:
        config_path: Optional path to a config file. Defaults to
            ``config/config.yaml`` under the project root.

    Returns:
        The parsed config dict, with an added ``resolved_paths`` mapping of each
        ``paths`` key to an absolute :class:`pathlib.Path`.

    Raises:
        FileNotFoundError: If the config file does not exist.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        config: dict[str, Any] = yaml.safe_load(fh) or {}
    paths = config.get("paths", {}) or {}
    config["resolved_paths"] = {key: resolve_path(value) for key, value in paths.items()}
    return config


def file_sha256_short(path: str | Path, length: int = 12) -> str:
    """Return a short hex SHA-256 of a file's bytes, streamed in chunks.

    Used as a DATA-DERIVED stamp for generated docs so regeneration is
    byte-identical whenever the input is unchanged (no wall-clock timestamps).
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:length]


def setup_logging(level: int | str = logging.INFO, name: str | None = None) -> logging.Logger:
    """Configure root logging once and return a named logger.

    Args:
        level: Logging level (int or level name such as ``"INFO"``).
        name: Logger name. Defaults to the project logger.

    Returns:
        A configured :class:`logging.Logger`.
    """
    global _LOG_INITIALIZED
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())
    if not _LOG_INITIALIZED:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        _LOG_INITIALIZED = True
    return logging.getLogger(name or "campaign_ab_test_audit")
