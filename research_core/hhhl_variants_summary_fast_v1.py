"""Versioned sparse-mask adapter for the pinned HHHL summary v1 implementation.

This deliberately overrides that version's protected _record method. Count
predicates mirror its pinned formulas; metadata, bins, candidates and
finalization remain with its superclass.
It cannot be substituted for a changed summary implementation without parity
verification. The original sealed implementation remains byte-identical.
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.hhhl_variants_summary import StudySummaries


class FastStudySummaries(StudySummaries):
    """Cache pinned-v1 count predicates, then count masked true entries once."""

    def __init__(self, *, candidates_only: bool = False) -> None:
        super().__init__()
        # This optional second-pass mode leaves initialized baseline/single
        # placeholders untouched; callers retain only candidate/Kdistribution.
        self._candidates_only = candidates_only
        self._source_arrays: dict[str, np.ndarray] | None = None
        self._count_names: tuple[str, ...] = ()
        self._years = np.empty(0, dtype=np.int64)
        self._year_indices = np.empty(0, dtype=np.int64)
        self._entry_rows = np.empty(0, dtype=np.int64)
        self._entry_bins = np.empty(0, dtype=np.int64)
        self._known = np.empty(0, dtype=bool)
        self._single_code: str | None = None
        self._source_populations = np.empty(0, dtype=np.int64)

    def _prepare_counts(self, arrays: dict[str, np.ndarray]) -> None:
        """These predicates mirror the byte-preserved v1 _record formulas."""
        if self._source_arrays is arrays:
            return
        self._source_arrays = arrays
        full = arrays["calendar_full"].astype(bool)
        labels = arrays["label"]
        censored = ~full
        predicates = {
            "calendar_full_n": full,
            "hit_n": full & (labels == "hit"),
            "loss_n": full & (labels == "loss"),
            "flat_win_n": full & (labels == "flat-win"),
            "unknown_n": full & (labels == "unknown"),
            "censored_n": censored,
            "censored_hit_n": censored & (labels == "hit"),
            "censored_unknown_n": censored & (labels == "unknown"),
            "not_applicable_n": np.zeros(len(full), dtype=bool),
        }
        for name in ("hit_then_below_anchor", "hit_endpoint_unknown"):
            source = name if name in arrays else f"{name}_n"
            if source in arrays:
                predicates[f"{name}_n"] = full & (labels == "hit") & (arrays[source] == 1)
        for diagnostic in ("drawdown10_full_state", "drawdown20_full_state", "before_hit10_state", "before_hit20_state"):
            states = arrays.get(diagnostic)
            for state in ("triggered", "all_false", "unknown"):
                predicates[f"{diagnostic.removesuffix('_state')}_{state}_n"] = (
                    full & (states == state) if states is not None else full if state == "unknown" else np.zeros(len(full), dtype=bool)
                )
        self._count_names = tuple(predicates)
        year_parts = cast(tuple[np.ndarray, np.ndarray, np.ndarray], np.unique(arrays["year"], return_inverse=True, return_counts=True))
        self._years = year_parts[0]
        self._year_indices = year_parts[1]
        self._source_populations = year_parts[2]
        # Cache only true predicate entries. One integer bincount subsequently
        # computes every year/count cell without float weights or rounding.
        self._entry_rows, columns = np.nonzero(np.column_stack(tuple(predicates.values())))
        self._entry_bins = self._year_indices[self._entry_rows] * len(self._count_names) + columns
        self._known = full & (labels != "unknown")
        codes = np.unique(arrays["code"])
        self._single_code = str(codes[0]) if len(codes) == 1 else None

    def _record(
        self,
        key: tuple[Any, ...],
        metadata: dict[str, Any],
        arrays: dict[str, np.ndarray],
        mask: np.ndarray,
        diagnostics: list[str],
        inapplicable: bool,
        reasons: np.ndarray | None,
    ) -> None:
        if self._candidates_only and metadata["row_kind"] not in {"candidate", "Kdistribution"}:
            if mask.size:
                # Retain optional count names on the first placeholder rows so
                # DataFrame column order/dtypes remain the original global
                # schema even after callers filter to second-pass candidates.
                self._prepare_counts(arrays)
                self._rates.add(key, metadata, int(self._years[0]), dict.fromkeys(self._count_names, 0))
            return
        if mask.size == 0:
            super()._record(key, metadata, arrays, mask, diagnostics, inapplicable, reasons)
            return
        self._prepare_counts(arrays)
        zero_counts = dict.fromkeys(self._count_names, 0)
        if inapplicable:
            self._rates.add(key, metadata, int(self._years[0]), zero_counts)
            for source_year, population in zip(self._years, self._source_populations, strict=True):
                self._rates.add(key, metadata, int(source_year), {"not_applicable_n": int(population)})
            return
        if not mask.any():
            self._rates.add(key, metadata, int(self._years[0]), zero_counts)
            return
        count_width = len(self._count_names)
        count_grid = np.bincount(self._entry_bins[mask[self._entry_rows]], minlength=len(self._years) * count_width).reshape(len(self._years), count_width)
        selected_populations = np.bincount(self._year_indices[mask], minlength=len(self._years))
        if metadata["bin_id"] == "not_applicable":
            count_grid[:, self._count_names.index("not_applicable_n")] = selected_populations
        known_selected = mask & self._known
        for year_index in np.flatnonzero(selected_populations):
            year = int(self._years[year_index])
            counts = {name: int(value) for name, value in zip(self._count_names, count_grid[year_index], strict=True)}
            known_n = counts["hit_n"] + counts["loss_n"] + counts["flat_win_n"]
            year_mask = self._year_indices == year_index
            if self._single_code is not None:
                codes = (self._single_code,) if known_n else ()
            else:
                codes = tuple(np.unique(arrays["code"][known_selected & year_mask]).tolist())
            self._rates.add(key, metadata, year, counts, codes)
            selected_year = mask & year_mask
            if reasons is not None:
                self._reasons[key][year].update(str(value) for value in reasons[selected_year] if value is not None and not pd.isna(value))
            if "unknown_reason" in arrays:
                unresolved = selected_year & (arrays["label"] == "unknown")
                self._outcome_reasons[key][year].update(
                    str(value) for value in arrays["unknown_reason"][unresolved] if value is not None and not pd.isna(value)
                )
