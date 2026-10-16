"""Explicit long-term scan outputs and bounded Q4 audit examples.

Collection returns references only. It never discovers files, reads market
payloads, copies data, or deletes the execution-time detailed tables.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core.research_data_paths import _artifact_name, _checked_path

LOGGER = logging.getLogger(__name__)


def select_q4_examples(rows: pd.DataFrame) -> pd.DataFrame:
    """Keep at most three full rows per group/effective coverage status.

    Effective coverage can differ from observed coverage due to random quota
    shortfall. The original observed status and every other chosen field remain
    unchanged in the retained row; no price diagnostic is calculated here.
    """
    required = {"group_id", "coverage_status", "security_id", "anchor_t0", "anchor_index", "episode_id"}
    if not rows.columns.is_unique or not required.issubset(rows):
        raise ValueError("Q4 examples require canonical coverage identity fields")
    for column in ("group_id", "security_id", "episode_id"):
        if not bool(cast(pd.Series, rows[column]).map(lambda value: isinstance(value, str) and bool(value.strip())).all()):
            raise ValueError("Q4 example identities must be nonblank strings")
    if not rows.coverage_status.isin(("matched", "unmatched", "unknown")).all():
        raise ValueError("invalid Q4 effective coverage status")
    if rows.duplicated(["group_id", "episode_id"]).any():
        raise ValueError("duplicate Q4 group/episode identity")
    ordered = rows.sort_values(
        ["group_id", "coverage_status", "security_id", "anchor_t0", "anchor_index", "episode_id"],
        kind="stable",
        na_position="last",
    )
    examples = ordered.groupby(["group_id", "coverage_status"], sort=False).head(3).reset_index(drop=True)
    LOGGER.info("Selected bounded Q4 examples original=%d retained=%d", len(rows), len(examples))
    return examples


def collect_retained_files(
    summaries: dict[str, Any],
    followup: dict[str, Any],
    audits: dict[str, Any],
    *,
    selection_path: Path,
    execution_files: dict[str, Path],
) -> dict[str, Path]:
    """Collect explicit completed outputs, excluding expanded intermediate data.

    Q4 coverage is a result table; examples and the full narrow draws/quotas are
    audit evidence. Missing coverage/examples fail instead of losing a promised
    deliverable. Callers own completion verification and reference handoff.
    """
    retained: dict[str, Path] = {}
    names: set[str] = set()
    paths: set[str] = set()

    def checked(name: str, value: str | Path) -> tuple[str, Path]:
        name = _artifact_name(name)
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("retained source paths must be explicit absolute paths")
        path = _checked_path(path)
        if not path.is_file():
            raise ValueError(f"retained source file missing: {path}")
        return name, path

    def add(name: str, path: Path) -> None:
        name, path = checked(name, path)
        folded = name.casefold()
        if folded in names or any(folded.startswith(other + "/") or other.startswith(folded + "/") for other in names):
            raise ValueError(f"retained logical name collision: {name}")
        physical = str(path).casefold()
        if physical in paths:
            raise ValueError(f"retained source path collision: {path}")
        names.add(folded)
        paths.add(physical)
        retained[name] = path

    for name, value in summaries["files"].items():
        name, path = checked(name, value)
        add(f"q1-q3/{name}", path)
    for name, value in followup["files"].items():
        name, path = checked(name, value)
        if not name.casefold().startswith("observations/") and name.casefold() != "holding_context.parquet":
            add(f"q5-q6/{name}", path)
    episode_files = followup["episodes"]["files"]
    if not {"coverage.parquet", "examples.parquet"}.issubset(episode_files):
        raise ValueError("retained Q4 coverage and bounded examples are required")
    for name, value in episode_files.items():
        name, path = checked(name, value)
        if name == "coverage.parquet":
            add("q4/coverage.parquet", path)
        elif name == "examples.parquet" or name.endswith(("-draws.parquet", "-quotas.parquet")):
            add(f"audits/q4/{name}", path)
    for name, value in audits["files"].items():
        name, path = checked(name, value)
        add(f"audits/events/{name}", path)
    add("selection.json", selection_path)
    for name, value in execution_files.items():
        add(name, value)
    LOGGER.info("Collected explicit retained scan files=%d", len(retained))
    return retained
