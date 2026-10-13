"""Bounded integer candidate coverage across the fixed public event facets."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import numpy as np
import pandas as pd

from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_reporting_v1 import candidate_membership, facet_masks

LOGGER = logging.getLogger(__name__)
MAX_CELLS = 100_000
INT64_MAX = np.iinfo(np.int64).max
COUNTS = ("true_n", "false_n", "feature_unknown_n", "not_applicable_n", "event_n", "distinct_stock_n")
FACETS = ("split", "era", "mkt")
BASE_FIELDS = ("pattern_id", "control_id", "cohort_id", "horizon")


class CandidateCoverage:
    """One complete stock feed per group/horizon; false coverage stays visible."""

    def __init__(self, base_metadata: Mapping[str, Any], candidates: Mapping[str, tuple[Atom, ...]]) -> None:
        self._base = deepcopy(dict(base_metadata))
        if not set(BASE_FIELDS).issubset(self._base) or set(self._base) & {*FACETS, *COUNTS, "candidate_id"}:
            raise ValueError("coverage requires fixed group metadata without output field overrides")
        if any(not isinstance(self._base[name], str) or not self._base[name].strip() for name in BASE_FIELDS[:-1]):
            raise ValueError("coverage group identities must be nonblank strings")
        horizon = self._base["horizon"]
        if type(horizon) is not int or horizon <= 0:
            raise ValueError("coverage horizon must be a positive integer")
        if not isinstance(candidates, Mapping) or any(not isinstance(identifier, str) or not identifier.strip() for identifier in candidates):
            raise ValueError("coverage candidate IDs must be nonblank strings")
        empty = pd.DataFrame(columns=pd.Index(("security_id", "t0", "horizon", "mkt")))
        self._facets = tuple(metadata for metadata, _ in facet_masks(empty))
        if len(candidates) * len(self._facets) > MAX_CELLS:
            raise ValueError("candidate coverage exceeds fixed cell capacity")
        self._candidates = {}
        for identifier, supplied in sorted(candidates.items()):
            if not isinstance(supplied, tuple):
                raise ValueError("coverage candidates must supply immutable Atom tuples")
            columns = [column for atom in supplied if isinstance(atom, Atom) for column in (f"{atom.feature_id}_bin", f"{atom.feature_id}_status")]
            candidate_membership(pd.DataFrame(columns=pd.Index(dict.fromkeys(columns))), supplied)
            self._candidates[identifier] = supplied
        self._counts = np.zeros((len(self._candidates), len(self._facets), len(COUNTS)), dtype=np.int64)
        self._stocks: set[str] = set()

    @property
    def memory_nbytes(self) -> int:
        """Numeric storage only; stock identities have separate Python overhead."""
        return self._counts.nbytes

    def add_stock(self, frame: pd.DataFrame) -> None:
        """Validate a complete immutable stock batch before changing any count."""
        required = {"event_id", "security_id", "t0", "horizon", "mkt"}
        if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique or not required.issubset(frame):
            raise ValueError("coverage requires unique event identity and public facet columns")
        if frame.event_id.duplicated().any() or not frame.event_id.map(lambda value: isinstance(value, str) and bool(value.strip())).all():
            raise ValueError("coverage event IDs must be unique nonblank strings")
        facets = tuple(facet_masks(frame))
        if not frame.empty and not frame.horizon.eq(self._base["horizon"]).all():
            raise ValueError("coverage stock horizon differs from fixed group")
        if frame.empty:
            for atoms in self._candidates.values():
                candidate_membership(frame, atoms)
            return
        stock = frame.security_id.iloc[0]
        if stock in self._stocks:
            raise ValueError("duplicate complete stock coverage feed")
        delta = np.zeros_like(self._counts)
        for candidate_index, atoms in enumerate(self._candidates.values()):
            membership = candidate_membership(frame, atoms)
            for facet_index, (metadata, mask) in enumerate(facets):
                if metadata != self._facets[facet_index]:
                    raise ValueError("public coverage facet inventory changed")
                event_n = int(np.count_nonzero(mask))
                values = membership[mask]
                delta[candidate_index, facet_index] = (
                    np.count_nonzero(values == 1),
                    np.count_nonzero(values == 0),
                    np.count_nonzero(values == -1),
                    np.count_nonzero(values == -2),
                    event_n,
                    int(event_n > 0),
                )
        if np.any(delta > INT64_MAX - self._counts):
            raise OverflowError("candidate coverage int64 overflow")
        self._counts += delta
        self._stocks.add(stock)
        LOGGER.debug("Added candidate coverage stock=%s events=%d candidates=%d bytes=%d", stock, len(frame), len(self._candidates), self.memory_nbytes)

    def finalize(self) -> pd.DataFrame:
        """Retain every candidate/facet zero row and raw integer observation counts."""
        rows = [
            {
                **deepcopy(self._base),
                "candidate_id": candidate,
                **metadata,
                **dict(zip(COUNTS, (int(value) for value in self._counts[candidate_index, facet_index]), strict=True)),
            }
            for candidate_index, candidate in enumerate(self._candidates)
            for facet_index, metadata in enumerate(self._facets)
        ]
        result = pd.DataFrame(rows, columns=pd.Index((*self._base, "candidate_id", *FACETS, *COUNTS)))
        for name in COUNTS:
            result[name] = result[name].astype("int64")
        return result
