"""Pure bounded unconditional Q1 aggregation over original projected events."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from research_core.artifact_store import object_digest
from research_core.pattern_scan_analysis_v1 import _group_metadata
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_dense_counts_v1 import DenseCounts
from research_core.pattern_scan_membership_v1 import StockCountPlan, membership_inventory
from research_core.pattern_scan_rates_v1 import REQUIRED_COLUMNS, summarize_events
from research_core.pattern_scan_summary_store_v1 import YEARS

LOGGER = logging.getLogger(__name__)
SUBTYPES = {
    "H1": ("P-clean", "P-over"),
    "B1": ("B1a", "B1b"),
    "B2": ("B2a", "B2b"),
    "B3": ("B3a", "B3b", "B3c"),
    "R1": ("R1a", "R1b"),
    "R2": ("R2a", "R2b", "R2c", "R2d", "R2e"),
    "R3": ("R3a", "R3b"),
}
CONTROLS = ("C-base-all", "C-base-no-pattern", "C-52w", "C-dip", "C-trend", "C-nh", "C-P1-breakout", "C-52w-daily", "C-base-daily")


class Q1Counts:
    """Retain integer counts and stock sets, never expanded event histories."""

    def __init__(self, target: str, groups: tuple[str, ...]) -> None:
        allowed = {"pattern:union", *(f"pattern:{subtype}" for subtype in SUBTYPES.get(target, ())), *CONTROLS}
        if target not in PATTERNS:
            raise ValueError("unregistered target")
        if (
            not isinstance(groups, tuple)
            or not groups
            or any(not isinstance(group, str) or group not in allowed for group in groups)
            or len(set(groups)) != len(groups)
        ):
            raise ValueError("groups require unique registered group IDs")
        self.target, self.groups = target, groups
        self._stocks: set[str] = set()
        self._cells: dict[tuple[str, int], tuple[tuple[dict[str, Any], ...], tuple[str, ...], StockCountPlan, DenseCounts]] = {}
        for group in groups:
            for horizon in (126, 252):
                inventory = tuple(row for row in membership_inventory(_group_metadata(target, group, horizon)) if row["feature_id"] == "unconditional")
                identifiers = tuple(object_digest(row) for row in inventory)
                self._cells[group, horizon] = inventory, identifiers, StockCountPlan(inventory), DenseCounts(identifiers, horizon)

    @property
    def memory_nbytes(self) -> int:
        """Numeric retained count storage; Python metadata overhead is separate."""
        return sum(accumulator.memory_nbytes for _, _, _, accumulator in self._cells.values())

    def add_stock(self, code: str, events: pd.DataFrame, memberships: pd.DataFrame, *, markets: pd.Series) -> None:
        """Validate a complete stock before committing any group/horizon feed."""
        if not isinstance(code, str) or not code.strip():
            raise ValueError("stock code requires a nonblank string")
        canonical = code[3:] if code.startswith("TW:") else code[2:] if code.startswith("TW") else code
        if not canonical.strip():
            raise ValueError("stock code requires a nonblank canonical identity")
        if canonical in self._stocks:
            raise ValueError("duplicate stock feed")
        if not events.columns.is_unique or not {*REQUIRED_COLUMNS, "event_eligibility_excluded"}.issubset(events):
            raise ValueError("incomplete projected event schema")
        if not memberships.columns.is_unique or set(memberships.columns) != {"group_id", "event_id"}:
            raise ValueError("membership schema requires group_id/event_id")
        if memberships.isna().to_numpy().any() or memberships.duplicated(["group_id", "event_id"]).any() or not memberships.group_id.isin(self.groups).all():
            raise ValueError("duplicate, null or mismatched group memberships")
        if not markets.index.is_unique:
            raise ValueError("market dates must be unique")
        summarize_events(events)
        securities = {f"TW:{canonical}", canonical, f"TW{canonical}"}
        if not events.security_id.isin(securities).all() or events.security_id.nunique() > 1:
            raise ValueError("stock identity differs")
        if not events.horizon.isin((126, 252)).all() or not events.groupby("event_id").horizon.nunique().eq(2).all():
            raise ValueError("projected events require both fixed horizons")
        if not events.groupby("event_id").t0.nunique().eq(1).all():
            raise ValueError("projected event dates differ across horizons")
        if set(memberships.event_id) != set(events.event_id):
            raise ValueError("membership and projected event IDs differ")
        matrices: dict[tuple[str, int], pd.DataFrame] = {}
        for (group, horizon), (_, _, plan, _) in self._cells.items():
            selected = memberships.loc[memberships.group_id.eq(group)]
            projected = events.loc[events.horizon.eq(horizon)]
            joined = selected.merge(projected, on="event_id", how="left", validate="one_to_one", indicator=True)
            if not joined["_merge"].eq("both").all():
                raise ValueError("membership has no projected event")
            joined = joined.drop(columns="_merge")
            joined["mkt"] = joined.t0.map(markets).fillna("unknown")
            matrices[group, horizon] = plan.matrix(joined)
        for key, matrix in matrices.items():
            self._cells[key][3].add_stock(matrix)
        self._stocks.add(canonical)
        LOGGER.debug("Q1 stock feed target=%s stock=%s events=%d", self.target, canonical, len(events))

    def finalize(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return every fixed facet, including zero cells and all seventeen years."""
        summaries: list[dict[str, Any]] = []
        annual: list[dict[str, Any]] = []
        for inventory, identifiers, _, accumulator in self._cells.values():
            for meta, cell in zip(inventory, identifiers, strict=True):
                removed, dropped = accumulator.drop_best_year(cell)
                summaries.append({**meta, **accumulator.summarize(cell), "row_kind": "full", "removed_year": None})
                summaries.append({**meta, **dropped, "row_kind": "drop_best_year", "removed_year": removed})
                annual.extend({**meta, **summary, "year": year} for year, summary in zip(YEARS, accumulator.annual_summary(cell), strict=True))
        return pd.DataFrame(summaries), pd.DataFrame(annual)
