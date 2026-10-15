"""Fixed zero-cell inventories and bounded vectorized stock memberships."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from itertools import product
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.artifact_store import object_digest
from research_core.hhhl_variants_selection import Atom, split_for_code
from research_core.pattern_scan_conditions_v1 import FEATURES, PATTERNS
from research_core.pattern_scan_reporting_v1 import ERAS, MARKETS, SPLITS, candidate_membership, facet_masks

LOGGER = logging.getLogger(__name__)
MATCH_COLUMNS = ("feature_id", "bin_id", "condition_status", "split", "era", "mkt")
BASE_COLUMNS = ("pattern_id", "control_id", "cohort_id", "horizon")


def membership_inventory(base_metadata: Mapping[str, Any], candidates: Mapping[str, Sequence[Atom]] | None = None) -> tuple[dict[str, Any], ...]:
    """Register every approved bin and missing stratum across 72 fixed facets.

    Candidate definitions are retained as canonical atom dictionaries in their
    metadata so pure consumers can reconstruct the same conjunction. Candidate
    known cells admit true membership only; false coverage is separate.
    """
    base = dict(base_metadata)
    if not set(BASE_COLUMNS).issubset(base) or base["pattern_id"] not in PATTERNS:
        raise ValueError("base metadata requires approved pattern and group/horizon")
    for name in ("control_id", "cohort_id"):
        if not isinstance(base[name], str) or not base[name].strip():
            raise ValueError("group identities must be nonblank")
    horizon = base["horizon"]
    if isinstance(horizon, (bool, np.bool_)) or not isinstance(horizon, (int, np.integer)) or horizon < 1:
        raise ValueError("horizon must be a positive integer")
    base["horizon"] = int(horizon)
    if set(base) & {*MATCH_COLUMNS, "candidate_id", "candidate_atoms", "cell_id"}:
        raise ValueError("caller metadata cannot replace fixed condition facets")
    conditions: list[dict[str, Any]] = [{"feature_id": "unconditional", "bin_id": "all", "condition_status": "known"}]
    for feature, definition in FEATURES.items():
        conditions.extend({"feature_id": feature, "bin_id": bin_id, "condition_status": "known"} for bin_id in dict.fromkeys(definition.bin_ids))
        conditions.extend({"feature_id": feature, "bin_id": status, "condition_status": status} for status in ("feature_unknown", "not_applicable"))
    for candidate_id, supplied in sorted((candidates or {}).items()):
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ValueError("candidate IDs must be nonblank strings")
        atoms = tuple(supplied)
        if not atoms or any(not isinstance(atom, Atom) or not atom.selectable for atom in atoms) or len({atom.feature_id for atom in atoms}) != len(atoms):
            raise ValueError("candidate requires unique selectable atoms")
        for atom in atoms:
            if atom.feature_id not in FEATURES or atom.bin_id not in FEATURES[atom.feature_id].bin_ids or atom.family != FEATURES[atom.feature_id].family:
                raise ValueError("candidate atom is outside approved condition inventory")
        extra = {"candidate_id": candidate_id, "candidate_atoms": [asdict(atom) for atom in atoms]}
        conditions.extend(
            {"feature_id": "candidate", "bin_id": candidate_id, "condition_status": status, **extra}
            for status in ("known", "feature_unknown", "not_applicable")
        )
    return tuple(
        {**base, **condition, "split": split, "era": era, "mkt": market} for condition in conditions for split, era, market in product(SPLITS, ERAS, MARKETS)
    )


def _registry(inventory: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    records = [dict(row) for row in inventory]
    required = {*BASE_COLUMNS, *MATCH_COLUMNS}
    if not records or any(not required.issubset(row) for row in records):
        raise ValueError("inventory requires canonical condition metadata")
    table = pd.DataFrame(records)
    if any(cast(pd.Series, table[column]).nunique(dropna=False) != 1 for column in BASE_COLUMNS):
        raise ValueError("inventory requires one target/group/horizon")
    if table.duplicated(list(MATCH_COLUMNS)).any():
        raise ValueError("duplicate inventory condition facets")
    table["cell_id"] = [object_digest(row) for row in records]
    return table


def _candidates(registry: pd.DataFrame) -> dict[str, tuple[Atom, ...]]:
    result: dict[str, tuple[Atom, ...]] = {}
    definitions: dict[str, str] = {}
    for supplied in registry.loc[registry.feature_id.eq("candidate")].to_dict("records"):
        row = cast(dict[str, Any], supplied)
        identifier = row["candidate_id"]
        serialized = row["candidate_atoms"]
        digest = object_digest(serialized)
        if identifier in definitions and definitions[identifier] != digest:
            raise ValueError("candidate definition cannot vary across facets")
        if identifier not in result:
            result[identifier] = tuple(Atom(**item) for item in serialized)
            definitions[identifier] = digest
    return result


def candidate_coverage(frame: pd.DataFrame, inventory: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Return separate 1/0/-1/-2 true/false/unknown/N/A conjunction states."""
    registry = _registry(inventory)
    if "event_id" not in frame or frame.event_id.duplicated().any():
        raise ValueError("coverage requires unique event_id")
    chunks = [
        pd.DataFrame({"event_id": frame.event_id.to_numpy(), "candidate_id": identifier, "membership_state": candidate_membership(frame, atoms)})
        for identifier, atoms in _candidates(registry).items()
    ]
    return (
        pd.concat(chunks, ignore_index=True)
        if chunks
        else pd.DataFrame({"event_id": pd.Series(dtype=object), "candidate_id": pd.Series(dtype=object), "membership_state": pd.Series(dtype="int8")})
    )


def _validate_stock_frame(frame: pd.DataFrame, registry: pd.DataFrame) -> None:
    required = {"event_id", "security_id", "t0", "horizon", "mkt"}
    if not frame.columns.is_unique or not required.issubset(frame) or frame.event_id.duplicated().any():
        raise ValueError("stock frame requires unique event IDs and facet fields")
    tuple(facet_masks(frame))
    if not frame.empty and int(frame.horizon.iloc[0]) != int(registry.horizon.iloc[0]):
        raise ValueError("batch horizon differs from inventory")


def stock_memberships(frame: pd.DataFrame, inventory: Sequence[Mapping[str, Any]], *, max_membership_rows: int = 500_000) -> pd.DataFrame:
    """Expand only eight actual facets per event/condition and join fixed cells.

    max_membership_rows is an allocation guard, not a study threshold. The
    caller must process a smaller stock/group batch if the declared upper bound
    is exceeded. Only unique inventory metadata is hashed, never event rows.
    """
    registry = _registry(inventory)
    if isinstance(max_membership_rows, bool) or not isinstance(max_membership_rows, int) or max_membership_rows < 1:
        raise ValueError("max_membership_rows must be a positive integer")
    # The public validator fixes year, split and market semantics for this batch.
    _validate_stock_frame(frame, registry)
    candidates = _candidates(registry)
    return _stock_memberships(frame, registry, candidates, max_membership_rows=max_membership_rows)


def _stock_memberships(
    frame: pd.DataFrame,
    registry: pd.DataFrame,
    candidates: Mapping[str, Sequence[Atom]],
    *,
    max_membership_rows: int,
) -> pd.DataFrame:
    """Expand a validated stock slice using the caller's compiled registry."""
    upper_bound = len(frame) * 8 * (1 + len(FEATURES) + len(candidates))
    if upper_bound > max_membership_rows:
        raise ValueError(f"membership allocation bound {upper_bound} exceeds {max_membership_rows}")
    if frame.empty:
        return pd.DataFrame({"event_id": pd.Series(dtype=object), "cell_id": pd.Series(dtype=object)})
    for feature in FEATURES:
        if not {f"{feature}_bin", f"{feature}_status"}.issubset(frame):
            raise ValueError(f"missing wide condition columns for {feature}")
    codes = cast(pd.Series, frame["security_id"]).map(lambda value: value[3:] if value.startswith("TW:") else value[2:] if value.startswith("TW") else value)
    splits = codes.map(split_for_code).to_numpy(dtype=object)
    years = cast(pd.Series, frame["t0"]).str.slice(0, 4).astype(int).to_numpy()
    eras = np.where(years <= 2012, "2010-2012", np.where(years <= 2018, "2013-2018", "2019+"))
    markets = frame["mkt"].to_numpy(dtype=object)
    facets = pd.concat(
        [
            pd.DataFrame({
                "position": np.arange(len(frame)),
                "event_id": frame.event_id.to_numpy(),
                "split": splits if own_split else "all",
                "era": eras if own_era else "all",
                "mkt": markets if own_market else "all",
            })
            for own_split, own_era, own_market in product((False, True), repeat=3)
        ],
        ignore_index=True,
    )
    chunks: list[pd.DataFrame] = []

    def append(feature: str, bins: np.ndarray, statuses: np.ndarray) -> None:
        expanded = facets.copy(deep=False)
        positions = expanded.position.to_numpy(dtype=int)
        expanded = expanded.assign(feature_id=feature, bin_id=bins[positions], condition_status=statuses[positions])
        cells = registry.loc[registry.feature_id.eq(feature), [*MATCH_COLUMNS, "cell_id"]]
        matched = expanded.merge(cells, on=list(MATCH_COLUMNS), how="left", validate="many_to_one", sort=False)
        # Known false candidate rows are deliberately absent from the inventory.
        if feature != "candidate" and matched.cell_id.isna().any():
            raise ValueError(f"condition state/bin has no registered cell: {feature}")
        chunks.append(cast(pd.DataFrame, matched.loc[matched.cell_id.notna(), ["event_id", "cell_id"]]))

    append("unconditional", np.full(len(frame), "all", dtype=object), np.full(len(frame), "known", dtype=object))
    for feature, definition in FEATURES.items():
        statuses = frame[f"{feature}_status"].to_numpy(dtype=object)
        if not np.isin(statuses, ("known", "feature_unknown", "not_applicable")).all():
            raise ValueError("invalid condition status")
        bins = frame[f"{feature}_bin"].to_numpy(dtype=object).copy()
        known = statuses == "known"
        if not np.isin(bins[known], tuple(dict.fromkeys(definition.bin_ids))).all():
            raise ValueError("known condition bin is outside the approved inventory")
        bins[~known] = statuses[~known]
        append(feature, bins, statuses)
    for identifier, atoms in candidates.items():
        membership = candidate_membership(frame, atoms)
        statuses = np.where(membership == 1, "known", np.where(membership == 0, "false", np.where(membership == -1, "feature_unknown", "not_applicable")))
        append("candidate", np.full(len(frame), identifier, dtype=object), statuses)
    result = pd.concat(chunks, ignore_index=True)
    if result.duplicated(["event_id", "cell_id"]).any():
        raise ValueError("duplicate event/cell membership")
    LOGGER.debug("Built stock memberships events=%d cells=%d rows=%d bound=%d", len(frame), len(registry), len(result), upper_bound)
    return result


class StockCountPlan:
    """One compiled group/horizon registry reused across independent stock feeds."""

    def __init__(self, inventory: Sequence[Mapping[str, Any]], *, max_membership_rows: int = 500_000) -> None:
        self._registry = _registry(inventory)
        if isinstance(max_membership_rows, bool) or not isinstance(max_membership_rows, int) or max_membership_rows < 1:
            raise ValueError("max_membership_rows must be a positive integer")
        self._candidates = _candidates(self._registry)
        self._max_membership_rows = max_membership_rows
        self._rows_per_event = 8 * (1 + len(FEATURES) + len(self._candidates))
        self._batch_size = max_membership_rows // self._rows_per_event

    def matrix(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Validate and reduce one entire stock, without retaining stock state."""
        from research_core.pattern_scan_count_matrix_v1 import GROUP_COLUMNS, aggregate_memberships
        from research_core.pattern_scan_summary_store_v1 import COUNT_FIELDS

        _validate_stock_frame(frame, self._registry)
        if frame.empty:
            return aggregate_memberships(frame, _stock_memberships(frame, self._registry, self._candidates, max_membership_rows=self._max_membership_rows))
        if self._batch_size < 1:
            raise ValueError(f"membership allocation bound {self._rows_per_event} exceeds {self._max_membership_rows} for one event")
        matrix: pd.DataFrame | None = None
        batch_n = 0
        for start in range(0, len(frame), self._batch_size):
            batch = cast(pd.DataFrame, frame.iloc[start : start + self._batch_size])
            memberships = _stock_memberships(batch, self._registry, self._candidates, max_membership_rows=self._max_membership_rows)
            counts = aggregate_memberships(batch, memberships)
            if matrix is None:
                matrix = counts
            else:
                combined = pd.concat([matrix, counts], ignore_index=True)
                reduced = cast(pd.DataFrame, combined.groupby(list(GROUP_COLUMNS), sort=True, observed=True)[list(COUNT_FIELDS)].sum()).reset_index()
                reduced = cast(pd.DataFrame, reduced.loc[:, [*GROUP_COLUMNS, *COUNT_FIELDS]])
                for field in (*COUNT_FIELDS, "year", "horizon"):
                    reduced[field] = reduced[field].astype("int64")
                matrix = reduced
                del combined
            batch_n += 1
        assert matrix is not None
        LOGGER.debug(
            "Built complete stock count matrix events=%d batches=%d rows=%d allocation_cap=%d", len(frame), batch_n, len(matrix), self._max_membership_rows
        )
        return matrix


def stock_count_matrix(frame: pd.DataFrame, inventory: Sequence[Mapping[str, Any]], *, max_membership_rows: int = 500_000) -> pd.DataFrame:
    """Convenience wrapper for one complete stock with a fresh compiled plan."""
    return StockCountPlan(inventory, max_membership_rows=max_membership_rows).matrix(frame)
