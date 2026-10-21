"""Fixed reporting facets over caller-owned event groups; no market readers."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping, Sequence
from datetime import date
from fractions import Fraction
from itertools import product
from numbers import Integral
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from research_core.hhhl_variants_selection import Atom, split_for_code
from research_core.pattern_scan_summary_store_v1 import YEARS, SummaryStore

LOGGER = logging.getLogger(__name__)
SPLITS = ("all", "development", "cross-check")
ERAS = ("all", "2010-2012", "2013-2018", "2019+")
MARKETS = ("all", "up", "down", "consolidation", "mixed", "unknown")


def facet_masks(frame: pd.DataFrame) -> Iterator[tuple[dict[str, str], NDArray[np.bool_]]]:
    """Yield all 72 masks, preserving unknown market as its own facet."""
    required = {"security_id", "t0", "horizon", "mkt"}
    if not frame.columns.is_unique or not required.issubset(frame.columns):
        raise ValueError("facet frame requires unique security_id/t0/horizon/mkt columns")
    codes: list[str] = []
    years: list[int] = []
    for code, t0, horizon, market in frame.loc[:, ["security_id", "t0", "horizon", "mkt"]].itertuples(index=False, name=None):
        if not isinstance(code, str) or not code.strip():
            raise ValueError("security_id requires nonblank strings preserving leading zeros")
        canonical_code = code[3:] if code.startswith("TW:") else code[2:] if code.startswith("TW") else code
        if not canonical_code.strip():
            raise ValueError("empty code after removing TW prefix")
        if not isinstance(t0, str) or date.fromisoformat(t0).isoformat() != t0:
            raise ValueError("t0 requires canonical ISO dates")
        if isinstance(horizon, (bool, np.bool_)) or not isinstance(horizon, Integral) or int(horizon) < 1:
            raise ValueError("horizon requires positive integers")
        if not isinstance(market, str) or market not in MARKETS[1:]:
            raise ValueError("invalid mkt category")
        codes.append(canonical_code)
        year = date.fromisoformat(t0).year
        if year not in YEARS:
            raise ValueError("facet years require 2010..2026")
        years.append(year)
    if frame["security_id"].nunique() > 1 or frame["horizon"].nunique() > 1:
        raise ValueError("facet frame requires one stock and horizon")
    split_values = np.asarray([split_for_code(code) for code in codes], dtype=object)
    era_values = np.asarray(["2010-2012" if year <= 2012 else "2013-2018" if year <= 2018 else "2019+" for year in years], dtype=object)
    markets = frame["mkt"].to_numpy(dtype=object)
    for split, era, market in product(SPLITS, ERAS, MARKETS):
        mask = np.ones(len(frame), dtype=np.bool_)
        if split != "all":
            mask &= split_values == split
        if era != "all":
            mask &= era_values == era
        if market != "all":
            mask &= markets == market
        yield {"split": split, "era": era, "mkt": market}, mask


def feed_facets(store: SummaryStore, frame: pd.DataFrame, *, metadata: Mapping[str, Any]) -> tuple[str, ...]:
    """Register zero cells and feed unchanged event rows to each matching cell."""
    if set(metadata) & {"split", "era", "mkt"}:
        raise ValueError("caller metadata cannot override fixed facets")
    masks = tuple(facet_masks(frame))
    horizon = metadata.get("horizon") if frame.empty else frame["horizon"].iloc[0]
    if isinstance(horizon, (bool, np.bool_)) or not isinstance(horizon, Integral) or int(horizon) < 1:
        raise ValueError("empty facets require metadata horizon as a positive integer")
    if "horizon" in metadata and metadata["horizon"] != horizon:
        raise ValueError("metadata horizon differs from event horizon")
    cell_ids: list[str] = []
    for facets, mask in masks:
        cell_id = store.register_cell({**metadata, **facets, "horizon": int(horizon)})
        cell_ids.append(cell_id)
        if bool(mask.any()):
            store.add_stock(cell_id, frame.loc[mask])
    LOGGER.debug("Fed %d events into %d fixed facet cells", len(frame), len(cell_ids))
    return tuple(cell_ids)


def collect_facets(store: SummaryStore, ids: Sequence[str]) -> Iterator[dict[str, object]]:
    """Yield full and same-cell year-excluded summaries without averaging rates."""
    for cell_id in ids:
        removed, dropped = store.drop_best_year(cell_id)
        yield {**store.metadata(cell_id), "cell_id": cell_id, "summary": store.summary(cell_id), "removed_year": removed, "drop_best_year_summary": dropped}


def collect_annual_facets(store: SummaryStore, ids: Sequence[str]) -> Iterator[dict[str, object]]:
    for cell_id in ids:
        for year, summary in zip(YEARS, store.annual_summary(cell_id), strict=True):
            yield {**store.metadata(cell_id), "cell_id": cell_id, "year": year, "summary": summary}


def flat_facets(store: SummaryStore, ids: Sequence[str]) -> Iterator[dict[str, object]]:
    """Tidy full and drop-best-year rows with all canonical cell facets."""
    for cell_id in ids:
        metadata = store.metadata(cell_id)
        removed, dropped = store.drop_best_year(cell_id)
        yield {**metadata, **store.summary(cell_id), "cell_id": cell_id, "row_kind": "full", "removed_year": None}
        yield {**metadata, **dropped, "cell_id": cell_id, "row_kind": "drop_best_year", "removed_year": removed}


def candidate_membership(bins: pd.DataFrame, candidate_atoms: Sequence[Atom]) -> NDArray[np.int8]:
    """Resolve known conjunctions; N/A dominates, then false, then unknown."""
    atoms = tuple(candidate_atoms)
    if not atoms or any(not isinstance(atom, Atom) or not atom.selectable for atom in atoms):
        raise ValueError("candidate requires nonempty selectable Atom members")
    if len({atom.feature_id for atom in atoms}) != len(atoms):
        raise ValueError("candidate features must be unique")
    if not bins.columns.is_unique:
        raise ValueError("condition columns must be unique")
    unknown, false, unavailable = (np.zeros(len(bins), dtype=np.bool_) for _ in range(3))
    for atom in atoms:
        bin_name, status_name = f"{atom.feature_id}_bin", f"{atom.feature_id}_status"
        if bin_name not in bins or status_name not in bins:
            raise ValueError(f"missing condition schema for {atom.feature_id}")
        statuses = bins[status_name]
        if not bool(statuses.isin(("known", "feature_unknown", "not_applicable")).all()):
            raise ValueError("invalid condition status")
        known = statuses.eq("known")
        known_bins = bins.loc[known, bin_name]
        if not bool(known_bins.map(lambda value: isinstance(value, str) and bool(value.strip())).all()):
            raise ValueError("known condition requires a nonblank bin")
        false |= (known & bins[bin_name].ne(atom.bin_id)).to_numpy(dtype=np.bool_)
        unknown |= statuses.eq("feature_unknown").to_numpy(dtype=np.bool_)
        unavailable |= statuses.eq("not_applicable").to_numpy(dtype=np.bool_)
    return np.where(unavailable, -2, np.where(false, 0, np.where(unknown, -1, 1))).astype(np.int8)


def top_confirmation_candidates(summary: pd.DataFrame) -> dict[str, tuple[str, ...]]:
    """Cross-check H252 union top ten per pattern by exact observed hit rate."""
    required = {"pattern_id", "candidate_id", "horizon", "split", "era", "mkt", "control_id", "cohort_id", "known_n", "hit_n"}
    if not summary.columns.is_unique or not required.issubset(summary.columns):
        raise ValueError("missing confirmation summary schema")
    selected = summary.loc[
        summary["horizon"].eq(252)
        & summary["split"].eq("cross-check")
        & summary["era"].eq("all")
        & summary["mkt"].eq("all")
        & summary["control_id"].eq("pattern")
        & summary["cohort_id"].eq("union")
    ]
    records: dict[str, list[tuple[str, int, int]]] = {}
    identities: set[tuple[str, str]] = set()
    for pattern, candidate, known, hit in selected.loc[:, ["pattern_id", "candidate_id", "known_n", "hit_n"]].itertuples(index=False, name=None):
        if not isinstance(pattern, str) or not pattern.strip() or not isinstance(candidate, str) or not candidate.strip():
            raise ValueError("pattern and candidate IDs require nonblank strings")
        if any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) for value in (known, hit)):
            raise ValueError("confirmation counts require integers")
        known_n, hit_n = int(known), int(hit)
        if known_n < 0 or not 0 <= hit_n <= known_n:
            raise ValueError("invalid hit/known counts")
        identity = pattern, candidate
        if identity in identities:
            raise ValueError("duplicate confirmation candidate summary")
        identities.add(identity)
        records.setdefault(pattern, [])
        if known_n:
            records[pattern].append((candidate, hit_n, known_n))
    return {
        pattern: tuple(candidate for candidate, _, _ in sorted(rows, key=lambda item: (-Fraction(item[1], item[2]), item[0]))[:10])
        for pattern, rows in sorted(records.items())
    }
