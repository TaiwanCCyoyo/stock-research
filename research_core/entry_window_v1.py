"""Pure in-memory entry-window.v1 masks and integer counts (E1-B1 only).

Contract: tasks/20261027-entry-window/{mission,data-contract}.md. Callers supply
already aligned canonical StockDaily inputs; this module neither loads data nor
constructs signals/outcomes. Event/quality states at i describe (t_i, t_{i+1}].
No bootstrap, execution/fill model, source adapter, or research admission lives here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from research_core import momentum_only_v1 as canonical

DEFINITION_ID = "entry-window.v1"
SET_KEYS = {"CORE": "A1&A2", "LEAD_B1": "LEAD_B1"}
CADENCES = ("daily", "cooled20")
LABELS = ((126, 2.0), (252, 2.0), (504, 5.0))
ERAS = ("all", "2010-2012", "2013-2018", "2019+")
STAGES = ("S", "Q", "M", "S_minus_Q", "Q_minus_M")
ARMS = ("accepted", "rejected", "above", "below")
METRICS = canonical.METRICS
UNKNOWN, FALSE, TRUE = -1, 0, 1


@dataclass(frozen=True)
class Band:
    band_id: str
    lower: float
    upper: float


BANDS = tuple(Band(f"B{i:02}", a, b) for i, (a, b) in enumerate(((0.97, 1.0), (0.97, 1.02), (0.97, 1.05), (1.0, 1.0), (1.0, 1.02), (1.0, 1.05)), 1))


@dataclass(frozen=True)
class Comparison:
    cell_id: str
    set_id: str
    band_id: str
    label: tuple[int, float]
    primary: bool


COMPARISONS = tuple(
    Comparison(f"{prefix}{i:02}", set_id, band.band_id, label, primary)
    for prefix, primary, labels in (("M", True, LABELS[:2]), ("S", False, LABELS[2:]))
    for i, (set_id, band, label) in enumerate(((s, b, lab) for s in SET_KEYS for b in BANDS for lab in labels), 1)
)


@dataclass(frozen=True)
class OfficialLimits:
    """Explicit official limits on quote sessions; quality 1 alone qualifies a row.

    The caller verifies the source is official. Missing/invalid bounds or quality
    0/-1 stay unknown. This evidence never changes Q/M or implies a personal fill.
    """

    source: str
    lower: NDArray[np.float64]
    upper: NDArray[np.float64]
    quality: NDArray[np.int8]


@dataclass(frozen=True)
class Quotes:
    """Raw bars on calendar; three-state interval arrays indexed by signal day.

    action_to_next: 1 action, 0 no action, -1 unknown. Quality arrays: 1 known
    good, 0 known invalid, -1 unknown. They describe the entire (t,t1] interval
    and the fixed next-session quote, respectively, without any PIT assertion.
    """

    code: str
    calendar: pd.DatetimeIndex
    raw_open: NDArray[np.float64]
    raw_high: NDArray[np.float64]
    raw_low: NDArray[np.float64]
    raw_close: NDArray[np.float64]
    action_to_next: NDArray[np.int8]
    event_quality_to_next: NDArray[np.int8]
    quote_quality_to_next: NDArray[np.int8]
    official_limits: OfficialLimits | None = None


@dataclass(frozen=True)
class BandMasks:
    accepted: NDArray[np.bool_]
    above: NDArray[np.bool_]
    below: NDArray[np.bool_]
    range_touch: NDArray[np.int8]


@dataclass(frozen=True)
class QuoteMasks:
    quote_known: NDArray[np.bool_]
    clean: NDArray[np.bool_]
    primary_reason: tuple[str | None, ...]
    reasons: dict[str, NDArray[np.bool_]]
    bands: dict[str, BandMasks]
    one_price: NDArray[np.int8]
    limit_status: tuple[str, ...]


def _calendar(calendar: pd.DatetimeIndex) -> None:
    if not isinstance(calendar, pd.DatetimeIndex) or calendar.tz is not None or calendar.hasnans:
        raise ValueError("calendar must be an explicit timezone-naive DatetimeIndex without NaT")
    if not calendar.is_unique or not calendar.is_monotonic_increasing or not calendar.equals(pd.DatetimeIndex(pd.Series(calendar).dt.normalize())):
        raise ValueError("calendar must contain unique increasing session dates")
    if len(calendar) and canonical.calendar_years(calendar)[0] < 2010:
        raise ValueError("entry-window eras start in 2010")


def _vector(values: np.ndarray, n: int, name: str, kind: str, allowed: tuple[int, ...] | None = None) -> None:
    if not isinstance(values, np.ndarray) or values.ndim != 1 or len(values) != n or values.dtype.kind not in kind:
        raise ValueError(f"{name} must be an aligned one-dimensional {kind} array of length {n}")
    if allowed is not None and not np.isin(values, allowed).all():
        raise ValueError(f"{name} contains an unknown state")


def _valid(values: NDArray[np.float64]) -> NDArray[np.bool_]:
    return np.isfinite(values) & (values > 0)


def _next(values: NDArray[np.float64]) -> NDArray[np.float64]:
    result = np.full(len(values), np.nan, dtype=np.float64)
    result[:-1] = values[1:]
    return result


def classify_quotes(calendar: pd.DatetimeIndex, quotes: Quotes) -> QuoteMasks:
    """Fixed t+1 raw quote masks for every calendar position, independent of signals.

    Multi-diagnostics retain simultaneous failures. The mutually exclusive primary
    quote failure order is no_next_session, invalid_raw_close, no_open, then a
    non-finite/non-positive ratio. Range/one-price/official diagnostics are tri-state
    and do not certify fills or alter the opening classification.
    """
    _calendar(calendar)
    _calendar(quotes.calendar)
    if not quotes.calendar.equals(calendar) or not quotes.code:
        raise ValueError("quote code/calendar must explicitly align with the common calendar")
    n = len(calendar)
    for name in ("raw_open", "raw_high", "raw_low", "raw_close"):
        _vector(getattr(quotes, name), n, name, "f")
    for name in ("action_to_next", "event_quality_to_next", "quote_quality_to_next"):
        _vector(getattr(quotes, name), n, name, "iu", (UNKNOWN, FALSE, TRUE))
    opening, high, low, closing = (_next(getattr(quotes, name)) for name in ("raw_open", "raw_high", "raw_low", "raw_close"))
    has_next = np.arange(n) + 1 < n
    valid_close, valid_open = _valid(quotes.raw_close), _valid(opening)
    with np.errstate(over="ignore", under="ignore", invalid="ignore", divide="ignore"):
        ratio = opening / quotes.raw_close
    ratio_valid = _valid(ratio)
    q = has_next & valid_close & valid_open & ratio_valid
    reasons = {
        "no_next_session": ~has_next,
        "invalid_raw_close": ~valid_close,
        "no_open": has_next & ~valid_open,
        "invalid_quote_ratio": has_next & valid_close & valid_open & ~ratio_valid,
        "corporate_action": quotes.action_to_next == TRUE,
        "corporate_action_unknown": quotes.action_to_next == UNKNOWN,
        "event_quality_invalid": quotes.event_quality_to_next == FALSE,
        "event_quality_unknown": quotes.event_quality_to_next == UNKNOWN,
        "quote_quality_invalid": quotes.quote_quality_to_next == FALSE,
        "quote_quality_unknown": quotes.quote_quality_to_next == UNKNOWN,
    }
    clean = q & (quotes.action_to_next == FALSE) & (quotes.event_quality_to_next == TRUE) & (quotes.quote_quality_to_next == TRUE)
    primary: list[str | None] = [None] * n
    for reason in ("invalid_quote_ratio", "no_open", "invalid_raw_close", "no_next_session"):
        for i in np.flatnonzero(reasons[reason]):
            primary[int(i)] = reason
    one_valid = has_next & _valid(opening) & _valid(high) & _valid(low) & _valid(closing) & (quotes.quote_quality_to_next == TRUE)
    one_valid &= (low <= high) & (opening >= low) & (opening <= high) & (closing >= low) & (closing <= high)
    one = np.where(one_valid, ((opening == high) & (opening == low) & (opening == closing)).astype(np.int8), UNKNOWN).astype(np.int8)
    range_valid = has_next & valid_close & _valid(high) & _valid(low) & (low <= high) & (quotes.quote_quality_to_next == TRUE)
    bands = {}
    for band in BANDS:
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            a, b = quotes.raw_close * band.lower, quotes.raw_close * band.upper
        accepted = clean & (opening >= a) & (opening <= b)
        above, below = clean & (opening > b), clean & (opening < a)
        touch = np.where(range_valid, ((high >= a) & (low <= b)).astype(np.int8), UNKNOWN).astype(np.int8)
        bands[band.band_id] = BandMasks(accepted, above, below, touch)
    limit_status = ["unknown"] * n
    limits = quotes.official_limits
    if limits is not None:
        if not limits.source.strip():
            raise ValueError("official limits require an explicit official source")
        _vector(limits.lower, n, "official lower", "f")
        _vector(limits.upper, n, "official upper", "f")
        _vector(limits.quality, n, "official quality", "iu", (UNKNOWN, FALSE, TRUE))
        lower, upper = _next(limits.lower), _next(limits.upper)
        quality = np.full(n, UNKNOWN, dtype=np.int8)
        quality[:-1] = limits.quality[1:]
        valid = has_next & valid_open & _valid(lower) & _valid(upper) & (lower <= upper) & (quality == TRUE) & (quotes.quote_quality_to_next == TRUE)
        for i in np.flatnonzero(valid):
            limit_status[int(i)] = (
                "at_upper" if opening[i] == upper[i] else "at_lower" if opening[i] == lower[i] else "inside" if lower[i] < opening[i] < upper[i] else "outside"
            )
    return QuoteMasks(q, clean, tuple(primary), reasons, bands, one, tuple(limit_status))


@dataclass(frozen=True)
class CountRow:
    """One stock/year integer cell. band_id=None stores each common stage once."""

    set_id: str
    cadence: str
    band_id: str | None
    label: tuple[int, float]
    security_id: str
    t0_year: int
    arm: str
    counts: tuple[int, ...]  # canonical METRICS, unbounded Python integers


@dataclass(frozen=True)
class DiagnosticRow:
    set_id: str
    cadence: str
    security_id: str
    t0_year: int
    counts: dict[str, int]


@dataclass(frozen=True)
class StockCounts:
    rows: tuple[CountRow, ...]
    diagnostics: tuple[DiagnosticRow, ...]


def _validate_stock(stock: canonical.StockDaily, n: int) -> None:
    if not stock.code:
        raise ValueError("stock code must be explicit")
    for name in ("eligible", "jump", "c52w"):
        _vector(getattr(stock, name), n, name, "b")
    _vector(stock.ret120, n, "ret120", "f")
    for name in ("A1", "A2", "A3"):
        if name not in stock.atoms:
            raise ValueError(f"missing canonical atom {name}")
    for name, states in stock.atoms.items():
        _vector(states, n, name, "iu", (UNKNOWN, FALSE, TRUE))
    for horizon in canonical.HORIZONS:
        if horizon not in stock.calendar_full:
            raise ValueError(f"missing canonical calendar_full {horizon}")
        _vector(stock.calendar_full[horizon], n, f"calendar_full {horizon}", "b")
    for label in canonical.LABELS:
        if label not in stock.labels or label not in stock.main_eligible:
            raise ValueError(f"missing canonical label {label}")
        _vector(stock.labels[label], n, f"label {label}", "iu", (0, 1, 2, 3))
        _vector(stock.main_eligible[label], n, f"main_eligible {label}", "b")


def _check_counts(counts: tuple[int, ...]) -> None:
    if len(counts) != len(METRICS) or any(type(v) is not int or v < 0 for v in counts):
        raise ValueError("counts must be nonnegative Python integers in canonical METRICS order")
    event, known, hit, loss, flat, unknown, censored, full_unknown = counts
    if event != known + full_unknown + censored or known != hit + loss + flat or not full_unknown <= unknown <= full_unknown + censored:
        raise ValueError("canonical outcome counts do not conserve events")


def count_stock(calendar: pd.DatetimeIndex, stock: canonical.StockDaily, quotes: Quotes) -> StockCounts:
    """Count a whole stock history before partitioning rows by stock/t0 year.

    StockDaily is positional on the explicit calendar, as its canonical contract
    requires. Quote dates/code must match it. Never call this on independent time
    chunks: cooling runs over the complete eligible signal pool before any mask.
    """
    masks = classify_quotes(calendar, quotes)
    _validate_stock(stock, len(calendar))
    if stock.code != quotes.code:
        raise ValueError("stock and quote security IDs differ")
    session_years = canonical.calendar_years(calendar)
    years = tuple(sorted(set(int(y) for y in session_years)))
    year_index = np.searchsorted(years, session_years).astype(np.intp)
    rows: list[CountRow] = []
    diagnostics: list[DiagnosticRow] = []
    for set_id, key in SET_KEYS.items():
        for cadence in CADENCES:
            _, lookback, cool = canonical.groups()[f"{key}:{'cooled' if cadence == 'cooled20' else 'daily'}"]
            members = canonical.set_members(stock.atoms, canonical.condition_sets()[key])
            signal = canonical.cooled(members, stock.eligible) if cool else members & stock.eligible
            common = {
                "S": signal,
                "Q": signal & masks.quote_known,
                "M": signal & masks.clean,
                "S_minus_Q": signal & ~masks.quote_known,
                "Q_minus_M": signal & masks.quote_known & ~masks.clean,
            }
            memberships: list[tuple[str | None, str, NDArray[np.bool_]]] = [(None, name, common_members) for name, common_members in common.items()]
            for band_id, band in masks.bands.items():
                memberships.extend(
                    (band_id, arm, signal & values)
                    for arm, values in (("accepted", band.accepted), ("rejected", band.above | band.below), ("above", band.above), ("below", band.below))
                )
            for count_band_id, arm, membership in memberships:
                counts = canonical.group_counts(stock, membership, lookback=lookback, year_index=year_index, n_years=len(years)).astype(np.int64)
                for label in LABELS:
                    for yi, year in enumerate(years):
                        metric_values = tuple(int(v) for v in counts[canonical.LABELS.index(label), yi])
                        _check_counts(metric_values)
                        rows.append(CountRow(set_id, cadence, count_band_id, label, stock.code, year, arm, metric_values))
            for year in years:
                scope = signal & (session_years == year)
                diagnostic_counts = {name: int((scope & membership).sum()) for name, membership in common.items()}
                diagnostic_counts.update({f"reason:{name}": int((scope & reason).sum()) for name, reason in masks.reasons.items()})
                diagnostic_counts.update({
                    f"primary:{reason}": sum(bool(scope[i]) and value == reason for i, value in enumerate(masks.primary_reason))
                    for reason in ("no_next_session", "invalid_raw_close", "no_open", "invalid_quote_ratio")
                })
                for state, name in ((UNKNOWN, "unknown"), (FALSE, "false"), (TRUE, "true")):
                    diagnostic_counts[f"one_price:{name}"] = int((scope & (masks.one_price == state)).sum())
                    for band_id, band in masks.bands.items():
                        diagnostic_counts[f"range_touch:{band_id}:{name}"] = int((scope & (band.range_touch == state)).sum())
                for status in ("unknown", "at_upper", "at_lower", "inside", "outside"):
                    diagnostic_counts[f"limit_status:{status}"] = sum(bool(scope[i]) and value == status for i, value in enumerate(masks.limit_status))
                diagnostics.append(DiagnosticRow(set_id, cadence, stock.code, year, diagnostic_counts))
    return StockCounts(tuple(rows), tuple(diagnostics))


@dataclass(frozen=True)
class SummaryKey:
    set_id: str
    cadence: str
    band_id: str | None
    label: tuple[int, float]
    era: str
    arm: str


@dataclass(frozen=True)
class Summary:
    counts: tuple[int, ...]
    stock_ids: frozenset[str]
    known_stock_ids: frozenset[str]

    @property
    def distinct_stock_n(self) -> int:
        return len(self.stock_ids)


def _era(year: int) -> str:
    if year < 2010:
        raise ValueError("t0_year must be in entry-window eras (2010+)")
    return "2010-2012" if year <= 2012 else "2013-2018" if year <= 2018 else "2019+"


def aggregate_rows(rows: Iterable[CountRow]) -> dict[SummaryKey, Summary]:
    """Recombine disjoint stock/year rows, summing integers before rates.

    Common M appears only under band_id=None. Empty eras/cells remain explicit.
    Repeated stock/year keys are rejected rather than silently double-counted.
    Python integer sums cannot wrap at either int32 or int64 boundaries.
    """
    totals: dict[SummaryKey, list[int]] = {}
    stocks: dict[SummaryKey, set[str]] = {}
    known_stocks: dict[SummaryKey, set[str]] = {}
    for s in SET_KEYS:
        for cadence in CADENCES:
            for band_id, arm in [(None, stage) for stage in STAGES] + [(b.band_id, a) for b in BANDS for a in ARMS]:
                for label in LABELS:
                    for era in ERAS:
                        key = SummaryKey(s, cadence, band_id, label, era, arm)
                        totals[key], stocks[key], known_stocks[key] = [0] * len(METRICS), set(), set()
    seen = set()
    for row in rows:
        _check_counts(row.counts)
        identity = (row.set_id, row.cadence, row.band_id, row.label, row.security_id, row.t0_year, row.arm)
        if identity in seen:
            raise ValueError("duplicate stock/year count key")
        seen.add(identity)
        if not row.security_id or type(row.t0_year) is not int:
            raise ValueError("explicit stock/year identity required")
        for era in ("all", _era(row.t0_year)):
            key = SummaryKey(row.set_id, row.cadence, row.band_id, row.label, era, row.arm)
            if key not in totals:
                raise ValueError("unknown count dimension")
            totals[key] = [a + b for a, b in zip(totals[key], row.counts, strict=True)]
            if row.counts[0]:
                stocks[key].add(row.security_id)
            if row.counts[1]:
                known_stocks[key].add(row.security_id)
    return {key: Summary(tuple(values), frozenset(stocks[key]), frozenset(known_stocks[key])) for key, values in totals.items()}


def comparison_rates(summaries: dict[SummaryKey, Summary], cell: Comparison, cadence: str, era: str) -> dict[str, float | None]:
    """Mission point estimates only; no confidence interval or strategy verdict."""

    def counts(band: str | None, arm: str) -> dict[str, int]:
        key = SummaryKey(cell.set_id, cadence, band, cell.label, era, arm)
        _check_counts(summaries[key].counts)
        return dict(zip(METRICS, summaries[key].counts, strict=True))

    m, a, r, hi, lo = (
        counts(None, "M"),
        counts(cell.band_id, "accepted"),
        counts(cell.band_id, "rejected"),
        counts(cell.band_id, "above"),
        counts(cell.band_id, "below"),
    )
    for metric in METRICS:
        if m[metric] != a[metric] + r[metric] or r[metric] != hi[metric] + lo[metric]:
            raise ValueError("comparison arms do not conserve the shared M")

    def rate(n: int, d: int) -> float | None:
        return n / d if d else None

    ah, al = rate(a["hit_n"], a["known_n"]), rate(a["loss_n"], a["known_n"])
    mh, ml = rate(m["hit_n"], m["known_n"]), rate(m["loss_n"], m["known_n"])
    return {
        "quote_accept_rate": rate(a["event_n"], m["event_n"]),
        "quote_reject_above_rate": rate(hi["event_n"], m["event_n"]),
        "quote_reject_below_rate": rate(lo["event_n"], m["event_n"]),
        "all_hit_rate": mh,
        "all_loss_rate": ml,
        "accepted_hit_rate": ah,
        "accepted_loss_rate": al,
        "accepted_hit_diff": None if ah is None or mh is None else ah - mh,
        "accepted_loss_diff": None if al is None or ml is None else al - ml,
        "rejected_hit_share": rate(r["hit_n"], m["hit_n"]),
    }
