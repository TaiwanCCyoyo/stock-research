"""Pure independent candidate reconstruction over caller-owned slim events.

No stores, producer readers or optimized membership/count accumulators are used.
The caller pins source/input identities and supplies one group's own H126/H252
rows. This engine audits one candidate/group/horizon at a time.
"""

from __future__ import annotations

import json
import logging
import math
import zlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from datetime import date
from itertools import product
from numbers import Integral, Real
from typing import Any

import pandas as pd

from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_conditions_v1 import FEATURES, PATTERNS
from research_core.pattern_scan_rates_v1 import REQUIRED_COLUMNS, drop_best_hit_year, summarize_events

LOGGER = logging.getLogger(__name__)
YEARS = tuple(range(2010, 2027))
ERAS = ("all", "2010-2012", "2013-2018", "2019+")
MARKETS = ("all", "up", "down", "consolidation", "mixed", "unknown")
STATES = ((1, "known"), (-1, "feature_unknown"), (-2, "not_applicable"))
BASE = ("pattern_id", "control_id", "cohort_id", "horizon")
CELL = (*BASE, "feature_id", "bin_id", "condition_status", "candidate_id", "split", "era", "mkt")


def _atoms(supplied: Sequence[Atom | Mapping[str, Any]]) -> tuple[Atom, ...]:
    atoms = tuple(atom if isinstance(atom, Atom) else Atom(**dict(atom)) for atom in supplied)
    if not atoms or len({atom.feature_id for atom in atoms}) != len(atoms):
        raise ValueError("candidate requires nonempty unique feature atoms")
    for atom in atoms:
        definition = FEATURES.get(atom.feature_id)
        if (
            atom.selectable is not True
            or definition is None
            or atom.family != definition.family
            or atom.bin_id not in definition.bin_ids
            or any(not isinstance(value, str) or not value.strip() for value in (atom.feature_id, atom.family, atom.bin_id))
        ):
            raise ValueError("candidate atom fields differ from approved selectable inventory")
    return atoms


def select_audit_candidates(selections: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """The original audit sample: first five by target/candidate ID, no outcomes.

    Fewer declared candidates remain fewer; the caller must report that scope.
    """
    declared = []
    seen = set()
    for target, selection in selections.items():
        if target not in PATTERNS:
            raise ValueError("audit selection requires an approved target")
        for candidate in selection["candidates"]:
            identifier = candidate["candidate_id"]
            if not isinstance(identifier, str) or not identifier.strip() or (target, identifier) in seen:
                raise ValueError("audit selection candidate IDs must be unique nonblank strings per target")
            seen.add((target, identifier))
            declared.append({"target": target, "candidate_id": identifier, "atoms": [asdict(atom) for atom in _atoms(candidate["atoms"])]})
    selected = tuple(sorted(declared, key=lambda row: (row["target"], row["candidate_id"]))[:5])
    LOGGER.info("Selected independent candidate audit declared=%d selected=%d", len(declared), len(selected))
    return selected


def _scalar(row: Mapping[str, Any], atoms: tuple[Atom, ...]) -> int:
    unavailable = mismatch = unknown = False
    for atom in atoms:
        status = row.get(f"{atom.feature_id}_status")
        if not isinstance(status, str) or status not in {"known", "feature_unknown", "not_applicable"}:
            raise ValueError("invalid candidate condition status")
        if status == "known":
            value = row.get(f"{atom.feature_id}_bin")
            if not isinstance(value, str) or not value.strip():
                raise ValueError("known condition requires a nonblank bin")
            mismatch |= value != atom.bin_id
        unavailable |= status == "not_applicable"
        unknown |= status == "feature_unknown"
    return -2 if unavailable else 0 if mismatch else -1 if unknown else 1


def scalar_membership(row: Mapping[str, Any], atoms: Sequence[Atom | Mapping[str, Any]]) -> int:
    """Independent scalar conjunction: N/A dominates false, then unknown."""
    return _scalar(row, _atoms(atoms))


def _code(identity: str) -> str:
    code = identity[3:] if identity.startswith("TW:") else identity[2:] if identity.startswith("TW") else identity
    if not code.strip():
        raise ValueError("empty original code after canonical TW prefix removal")
    return code


def _masked_rates(values: dict[str, Any], status: str) -> dict[str, Any]:
    return {key: None if status == "not_applicable" and (key.endswith("_rate") or key.endswith("_bound")) else value for key, value in values.items()}


def reconstruct_candidate(
    frames: Iterable[pd.DataFrame],
    *,
    metadata: Mapping[str, Any],
    candidate_id: str,
    atoms: Sequence[Atom | Mapping[str, Any]],
) -> dict[str, pd.DataFrame]:
    """Rebuild 3 states x 24 cross-check facets x 19 rows for one group/H.

    Do not pass pooled patterns or both horizons. Rows may be controls: their
    original pattern IDs are deliberately never filtered by target pattern ID.
    Every retained population is sent unchanged to the public batch oracle.
    """
    resolved = _atoms(atoms)
    base = dict(metadata)
    if set(base) not in (set(BASE), {*BASE, "primary_control_id"}) or base.get("pattern_id") not in PATTERNS:
        raise ValueError("audit metadata requires exactly canonical group identity fields")
    if type(base["horizon"]) is not int or base["horizon"] not in (126, 252):
        raise ValueError("audit requires one approved horizon")
    if any(not isinstance(base[name], str) or not base[name].strip() for name in base if name != "horizon"):
        raise ValueError("audit metadata identities must be nonblank strings")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("audit candidate ID must be nonblank")
    tables = list(frames)
    if not tables:
        raise ValueError("audit requires explicit event frames, including an empty schema for zero populations")
    columns = {*REQUIRED_COLUMNS, "event_eligibility_excluded", "mkt", *(f"{atom.feature_id}_{suffix}" for atom in resolved for suffix in ("bin", "status"))}
    if any(not table.columns.is_unique or not columns.issubset(table.columns) for table in tables):
        raise ValueError("audit event frames lack canonical population/condition fields")
    rows = pd.concat(tables, ignore_index=True)
    summarize_events(rows)  # Validate the whole population before any membership/facet filtering.
    if not rows.horizon.eq(base["horizon"]).all() or not rows.mkt.isin(MARKETS[1:]).all():
        raise ValueError("audit event horizon or market differs from registered scope")
    records = rows.to_dict("records")
    years = [date.fromisoformat(row["t0"]).year for row in records]
    if any(year not in YEARS for year in years):
        raise ValueError("audit events require fixed 2010..2026 years")
    codes = [_code(row["security_id"]) for row in records]
    aliases: dict[str, str] = {}
    for code, row in zip(codes, records, strict=True):
        if code in aliases and aliases[code] != row["security_id"]:
            raise ValueError("one original stock code has inconsistent security identity aliases")
        aliases[code] = row["security_id"]
    states = pd.Series([_scalar(row, resolved) for row in records], index=rows.index, dtype="int8")
    cross = pd.Series([zlib.crc32(code.encode("utf-8")) % 2 == 1 for code in codes], index=rows.index, dtype=bool)
    era_values = pd.Series(["2010-2012" if year <= 2012 else "2013-2018" if year <= 2018 else "2019+" for year in years], index=rows.index, dtype=object)
    event_years = pd.Series(years, index=rows.index, dtype="int64")
    atom_json = json.dumps([asdict(atom) for atom in resolved], sort_keys=True)
    summary: list[dict[str, Any]] = []
    annual: list[dict[str, Any]] = []
    for (state, status), era, market in product(STATES, ERAS, MARKETS):
        mask = cross & states.eq(state)
        if era != "all":
            mask &= era_values.eq(era)
        if market != "all":
            mask &= rows.mkt.eq(market)
        subset = rows.loc[mask]
        meta = {
            **base,
            "feature_id": "candidate",
            "bin_id": candidate_id,
            "condition_status": status,
            "candidate_id": candidate_id,
            "candidate_atoms_json": atom_json,
            "split": "cross-check",
            "era": era,
            "mkt": market,
        }
        total = _masked_rates(summarize_events(subset), status)
        removed, dropped = drop_best_hit_year(subset, years=YEARS)
        summary.extend((
            {**meta, **total, "row_kind": "full", "removed_year": None},
            {**meta, **_masked_rates(dropped, status), "row_kind": "drop_best_year", "removed_year": removed},
        ))
        for year in YEARS:
            annual.append({**meta, **_masked_rates(summarize_events(subset.loc[event_years.loc[subset.index].eq(year)]), status), "year": year})
    evidence = rows.loc[
        :, ["security_id", "event_id", "t0", "horizon", "mkt", *(f"{atom.feature_id}_{suffix}" for atom in resolved for suffix in ("bin", "status"))]
    ].copy()
    evidence["membership_state"] = states
    evidence["split"] = pd.Series(["cross-check" if value else "development" for value in cross], index=rows.index, dtype=object)
    LOGGER.info(
        "Reconstructed independent candidate pattern=%s control=%s H=%d candidate=%s events=%d",
        base["pattern_id"],
        base["control_id"],
        base["horizon"],
        candidate_id,
        len(rows),
    )
    return {"summary": pd.DataFrame(summary), "annual": pd.DataFrame(annual), "memberships": evidence}


def _same(expected: Any, actual: Any, column: str) -> bool:
    if pd.isna(expected) or pd.isna(actual):
        return bool(pd.isna(expected) and pd.isna(actual))
    if column == "removed_year":
        return isinstance(actual, Real) and not isinstance(actual, bool) and actual == expected and float(actual).is_integer()
    if isinstance(expected, Integral):
        return isinstance(actual, Integral) and not isinstance(actual, bool) and int(expected) == int(actual)
    if isinstance(expected, Real):
        return isinstance(actual, Real) and not isinstance(actual, bool) and math.isclose(float(expected), float(actual), rel_tol=1e-12, abs_tol=1e-12)
    return type(actual) is type(expected) and actual == expected


def compare_candidate(
    reconstructed: Mapping[str, pd.DataFrame],
    *,
    stored_summary: pd.DataFrame,
    stored_annual: pd.DataFrame,
) -> dict[str, int]:
    """Require an exact candidate/group/H slice, unique complete keys and values."""
    checked = {}
    for family, stored, discriminator in (("summary", stored_summary, "row_kind"), ("annual", stored_annual, "year")):
        expected = reconstructed[family]
        if not stored.columns.is_unique or not set(expected.columns).issubset(stored.columns):
            raise ValueError(f"candidate {family} schema differs")
        keys = (*CELL, *(("primary_control_id",) if "primary_control_id" in expected else ()), discriminator)
        if expected.duplicated(list(keys)).any() or stored.duplicated(list(keys)).any():
            raise ValueError(f"duplicate candidate {family} row identity")
        expected_rows = {tuple(row[key] for key in keys): row for row in expected.to_dict("records")}
        stored_rows = {tuple(row[key] for key in keys): row for row in stored.to_dict("records")}
        if expected_rows.keys() != stored_rows.keys():
            raise ValueError(f"candidate {family} missing, extra or changed metadata rows")
        for key, row in expected_rows.items():
            actual = stored_rows[key]
            for column, value in row.items():
                if not _same(value, actual[column], column):
                    raise ValueError(f"candidate {family} mismatch column={column} cell={key}")
        checked[f"{family}_rows"] = len(expected_rows)
    checked["aggregate_checks"] = sum(checked.values())
    LOGGER.info("Verified independent candidate aggregate rows=%d", checked["aggregate_checks"])
    return checked
