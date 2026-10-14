"""Resolve the local producer input root without acquiring or replacing data."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def producer_data_root() -> Path:
    configured = os.environ.get("STOCK_PRODUCER_DATA_ROOT")
    if configured is None:
        return REPO_ROOT / "stock-data-downloader" / "data"
    root = Path(configured)
    if not configured.strip() or not root.is_absolute():
        raise ValueError("STOCK_PRODUCER_DATA_ROOT must be an absolute directory path")
    if not root.is_dir():
        raise FileNotFoundError(f"STOCK_PRODUCER_DATA_ROOT directory is unavailable: {root}; no automatic fallback")
    return root.resolve()
