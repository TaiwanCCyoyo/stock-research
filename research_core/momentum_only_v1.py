"""Per-stock inputs and integer counts for the momentum-only study (`momentum-only.v1`).

Mission: tasks/20261021-momentum-only-doubling/mission.md. Every definition is PR17's:
S6 eligibility (`daily_qualification`), C-52w/C-base (`scan_controls`), condition values
(`calculate_common_values`) and their bins (`classify_column`), and the result-window
quality overlay of `pattern_scan_projection_v1`. Labels come from
`multiple_outcomes_v1.outcomes_for_targets`, which equals PR17's `outcomes_for_closes`
at 2x. Nothing here changes a PR17 rule; this module only wires them for daily groups.

A daily group's event is an eligible day on which its condition holds. Its effective
label is unknown when an unexplained jump lies in the detection window
`[t0 - lookback, t0]` or the result window `[t0 + 1, min(t0 + H, n - 1)]`
(`pattern_scan_groups_v1.LOOKBACK`: 0 for C-base and every condition set, 250 for C-52w).
The main denominator holds events whose base label is main-eligible and not unknown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import combinations
from typing import cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from research_core.hhhl_variants_selection import split_for_code as split_for_code
from research_core.multiple_outcomes_v1 import outcomes_for_targets
from research_core.pattern_scan_conditions_v1 import classify_column
from research_core.pattern_scan_controls_v1 import scan_controls
from research_core.pattern_scan_daily_values_v1 import calculate_common_values
from research_core.pattern_scan_events_v1 import per_group_cooldown
from research_core.pattern_scan_groups_v1 import LOOKBACK
from research_core.pattern_scan_indicators_v1 import prepare_detector_frame
from research_core.pattern_scan_inputs_v1 import daily_qualification
from research_core.patterns.scan_contract_v1 import Bars

LOGGER = logging.getLogger(__name__)
DEFINITION_ID = "momentum-only.v1"
TARGETS = (2.0, 3.0, 5.0, 10.0)
HORIZONS = (126, 252, 504)
# Label codes: 0 unknown, 1 hit, 2 loss, 3 flat-win.
LABEL_CODES = {"unknown": 0, "hit": 1, "loss": 2, "flat-win": 3}
JUMP_REASONS = frozenset(("unexplained_adjusted_jump", "unexplained_jump"))
# Atom -> (PR17 feature_id, bin_id, common_values column). H is ranked across stocks.
ATOMS: dict[str, tuple[str, str, str]] = {
    "A1": ("C3", "ge60", "C3"),
    "A2": ("D2", "ge250", "D2"),
    "A3": ("G2_limit", "true", "G2_limit"),
    "A4": ("H", "ge90", "H"),
    "A5": ("RSI", "ge70", "RSI"),
    "A6": ("F", "gt100", "F"),
}
LOCAL_ATOMS = ("A1", "A2", "A3", "A5", "A6")


def condition_sets() -> dict[str, tuple[str, ...]]:
    """The 22 pure-momentum sets fixed by the mission (A7 sets are not_evaluated)."""
    singles = {atom: (atom,) for atom in ATOMS}
    pairs = {f"{a}&{b}": (a, b) for a, b in combinations(ATOMS, 2)}
    return {**singles, **pairs, "LEAD_B1": ("A1", "A2", "A3")}


@dataclass(frozen=True)
class StockDaily:
    """One stock on the fixed common calendar; every array has the calendar's length."""

    code: str
    split: str
    eligible: NDArray[np.bool_]
    jump: NDArray[np.bool_]
    c52w: NDArray[np.bool_]
    atoms: dict[str, NDArray[np.int8]]  # 1 matched bin, 0 known other bin, -1 unknown
    ret120: NDArray[np.float64]
    labels: dict[tuple[int, float], NDArray[np.int8]]
    main_eligible: dict[tuple[int, float], NDArray[np.bool_]]
    calendar_full: dict[int, NDArray[np.bool_]]


def _jump_flags(quality_reason: pd.Series) -> NDArray[np.bool_]:
    def flagged(value: object) -> bool:
        if not isinstance(value, str):
            return False
        return bool({token.strip() for token in value.split("|")} & JUMP_REASONS)

    return np.fromiter((flagged(value) for value in quality_reason), dtype=bool, count=len(quality_reason))


def _atom_state(feature_id: str, bin_id: str, values: pd.Series) -> NDArray[np.int8]:
    classified = classify_column(feature_id, values)
    known = classified["status"].eq("known").to_numpy()
    matched = classified["bin_id"].eq(bin_id).to_numpy()
    return np.where(known, matched.astype(np.int8), np.int8(-1)).astype(np.int8)


def stock_daily(code: str, prepared: pd.DataFrame, *, ordinary_reference: bool = True) -> StockDaily:
    """Eligibility, C-52w, local atoms, ret120 and labels for one padded stock frame.

    `prepared` is `read_adjusted_daily(reference_factor_adjusted, as_of=, calendar=)`
    for one code, indexed by the fixed calendar (every position present).
    """
    indicators, pivots = prepare_detector_frame(prepared)
    qualification = daily_qualification(prepared, ordinary_reference=ordinary_reference)
    eligible = qualification["base_eligible"].to_numpy(dtype=bool)
    controls = scan_controls(Bars.from_frame(indicators), base_eligible=eligible, h1_source_events=(), p1_events=())
    common = calculate_common_values(indicators, pivots)
    atoms = {atom: _atom_state(ATOMS[atom][0], ATOMS[atom][1], cast(pd.Series, common[ATOMS[atom][2]])) for atom in LOCAL_ATOMS}
    close = indicators["Close"].to_numpy(dtype=float, na_value=np.nan)
    labels: dict[tuple[int, float], NDArray[np.int8]] = {}
    main: dict[tuple[int, float], NDArray[np.bool_]] = {}
    full: dict[int, NDArray[np.bool_]] = {}
    for horizon in HORIZONS:
        outcomes = outcomes_for_targets(close, horizon, TARGETS)
        for target, frame in outcomes.items():
            labels[horizon, target] = np.fromiter((LABEL_CODES[value] for value in frame["label"]), dtype=np.int8, count=len(frame))
            main[horizon, target] = frame["main_eligible"].to_numpy(dtype=bool)
            full[horizon] = frame["calendar_full"].to_numpy(dtype=bool)
    return StockDaily(
        code=code,
        split=split_for_code(code),
        eligible=eligible,
        jump=_jump_flags(cast(pd.Series, prepared["quality_reason"])),
        c52w=np.asarray(controls["C-52w"].admitted_states == 1, dtype=bool),
        atoms=atoms,
        ret120=common["ret120"].to_numpy(dtype=float, na_value=np.nan),
        labels=labels,
        main_eligible=main,
        calendar_full=full,
    )


def quality_unknown(jump: NDArray[np.bool_], lookback: int, horizon: int) -> NDArray[np.bool_]:
    """True where the detection or result window of a t0 holds an unexplained jump."""
    n = len(jump)
    prefix = np.concatenate([[0], np.cumsum(jump, dtype=np.int64)])
    t = np.arange(n)
    detection = prefix[t + 1] - prefix[np.maximum(0, t - lookback)] > 0
    end = np.minimum(t + horizon, n - 1)
    result = prefix[end + 1] - prefix[np.minimum(t + 1, n)] > 0
    return cast(NDArray[np.bool_], detection | result)


LABELS = tuple((horizon, target) for horizon in HORIZONS for target in TARGETS)
METRICS = ("event_n", "known_n", "hit_n", "loss_n", "flat_win_n", "unknown_n", "censored_n", "full_unknown_n")
FIRST_YEAR = 2010


def group_counts(stock: StockDaily, members: NDArray[np.bool_], *, lookback: int, year_index: NDArray[np.intp], n_years: int) -> NDArray[np.int32]:
    """Integer counts `[label, year, metric]` for one stock and one daily group.

    `members` marks days whose condition holds; events are those days that are also
    eligible. Metrics follow PR17's `summarize_events`: known is main-eligible and not
    quality-unknown; unknown counts every event whose effective label is unknown;
    censored counts events whose calendar window is incomplete.
    """
    counts = np.zeros((len(LABELS), n_years, len(METRICS)), dtype=np.int32)
    events = members & stock.eligible
    if not events.any():
        return counts
    event_years = year_index[events]
    counts[:, :, 0] = np.bincount(event_years, minlength=n_years)
    for horizon in HORIZONS:
        quality = quality_unknown(stock.jump, lookback, horizon)[events]
        censored = ~stock.calendar_full[horizon][events]
        censored_n = np.bincount(event_years[censored], minlength=n_years)
        for target in TARGETS:
            row = LABELS.index((horizon, target))
            label = np.where(quality, np.int8(0), stock.labels[horizon, target][events])
            known = stock.main_eligible[horizon, target][events] & ~quality
            for column, mask in ((1, known), (2, known & (label == 1)), (3, known & (label == 2)), (4, known & (label == 3)), (5, label == 0)):
                counts[row, :, column] = np.bincount(event_years[mask], minlength=n_years)
            counts[row, :, 6] = censored_n
            counts[row, :, 7] = np.bincount(event_years[(label == 0) & ~censored], minlength=n_years)
    return counts


def cooled(members: NDArray[np.bool_], eligible: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """PR17 20-session cooldown over one stock's eligible condition days."""
    retained = np.zeros(len(members), dtype=bool)
    retained[list(per_group_cooldown(int(i) for i in np.flatnonzero(members & eligible)))] = True
    return retained


BASELINE_LOOKBACK = {"C-base-daily": LOOKBACK["C-base"], "C-52w-daily": LOOKBACK["C-52w"]}


def h_states(stocks: list[StockDaily]) -> list[NDArray[np.int8]]:
    """A4 for every stock: PR17's H (120-day return percentile among same-day eligible stocks) >= 90.

    Same pandas expression as `hhhl_variants_run.cross_section`: rank(method="average",
    pct=True) * 100 within each calendar position over eligible stocks with a finite ret120.
    Days outside that pool are unknown. The pool is the whole fixed universe, so this is a
    full-market barrier and must see every stock.
    """
    n = len(stocks[0].eligible)
    frames = []
    for position, stock in enumerate(stocks):
        mask = stock.eligible & np.isfinite(stock.ret120)
        days = np.flatnonzero(mask)
        frames.append(pd.DataFrame({"stock": position, "calendar_index": days, "ret120": stock.ret120[days]}))
    pool = pd.concat(frames, ignore_index=True)
    pool["H"] = pool.groupby("calendar_index")["ret120"].rank(method="average", pct=True) * 100
    states = []
    for position, rows in pool.groupby("stock", sort=True):
        values = np.full(n, np.nan)
        values[rows["calendar_index"].to_numpy()] = rows["H"].to_numpy()
        states.append((int(cast(int, position)), _atom_state("H", "ge90", pd.Series(values))))
    by_stock = dict(states)
    return [by_stock.get(position, np.full(n, -1, dtype=np.int8)) for position in range(len(stocks))]


def set_members(atoms: dict[str, NDArray[np.int8]], names: tuple[str, ...]) -> NDArray[np.bool_]:
    """Days on which every atom of the set is known and in its bin."""
    members = np.ones(len(next(iter(atoms.values()))), dtype=bool)
    for name in names:
        members &= atoms[name] == 1
    return members


def groups() -> dict[str, tuple[str, int, bool]]:
    """Group id -> (membership key, quality lookback, cooled)."""
    result: dict[str, tuple[str, int, bool]] = {
        "C-base-daily": ("C-base", LOOKBACK["C-base"], False),
        "C-52w-daily": ("C-52w", LOOKBACK["C-52w"], False),
        "C-base": ("C-base", LOOKBACK["C-base"], True),
        "C-52w": ("C-52w", LOOKBACK["C-52w"], True),
    }
    for name in condition_sets():
        result[f"{name}:daily"] = (name, LOOKBACK["C-base"], False)
        result[f"{name}:cooled"] = (name, LOOKBACK["C-base"], True)
    return result


def stock_group_counts(stock: StockDaily, a4: NDArray[np.int8], *, year_index: NDArray[np.intp], n_years: int) -> NDArray[np.int32]:
    """Counts `[group, label, year, metric]` for every group of `groups()` for one stock."""
    atoms = {**stock.atoms, "A4": a4}
    sets = condition_sets()
    everything = np.ones(len(stock.eligible), dtype=bool)
    out = np.zeros((len(groups()), len(LABELS), n_years, len(METRICS)), dtype=np.int32)
    for position, (key, lookback, cool) in enumerate(groups().values()):
        members = everything if key == "C-base" else stock.c52w if key == "C-52w" else set_members(atoms, sets[key])
        if cool:
            members = cooled(members, stock.eligible)
        out[position] = group_counts(stock, members, lookback=lookback, year_index=year_index, n_years=n_years)
    return out


EPISODE_LABELS = ((504, 5.0), (504, 10.0))
COVERAGE_SEED = 20261021


def _valid_rows(prepared: pd.DataFrame) -> NDArray[np.bool_]:
    """`prepare_detector_frame`'s validity: Quality, finite positive OHLC, consistent bar."""
    prices = prepared.loc[:, ["Open", "High", "Low", "Close"]].to_numpy(dtype=float, na_value=np.nan)
    valid = prepared["Quality"].eq(True).fillna(False).to_numpy(dtype=bool)
    valid &= np.isfinite(prices).all(axis=1) & (prices > 0).all(axis=1)
    opening, high, low, close = prices.T
    return cast(NDArray[np.bool_], valid & (high >= low) & (opening >= low) & (opening <= high) & (close >= low) & (close <= high))


def masked_close(prepared: pd.DataFrame) -> NDArray[np.float64]:
    """The research close PR17 labels use: NaN unless Quality and OHLC are valid."""
    close = prepared["Close"].to_numpy(dtype=float, na_value=np.nan)
    return np.where(_valid_rows(prepared), close, np.nan)


@dataclass(frozen=True)
class LongEpisode:
    start_indices: tuple[int, ...]
    anchor_index: int | None
    peak_index: int | None
    status: str
    reason: str | None = None


def episode_starts(stock: StockDaily, horizon: int, target: float) -> list[int]:
    """PR17 Q4 admission for one label: base hit, full calendar, no result-window jump."""
    n = len(stock.jump)
    hits = stock.labels[horizon, target] == 1
    full = stock.calendar_full[horizon]
    jump = quality_unknown(stock.jump, -1, horizon)  # lookback -1: result window only
    days = np.arange(n)
    return [int(t) for t in np.flatnonzero(hits & full & ~jump & (days + horizon < n))]


def merge_episodes(starts: list[int], closes: NDArray[np.float64], horizon: int) -> list[LongEpisode]:
    """`pattern_scan_events_v1.merge_hit_episodes` with the peak window set to `horizon`.

    Starts <=20 sessions apart merge transitively; the anchor is the lowest start close
    (earliest on ties); the peak is the highest close in anchor+1..anchor+horizon
    (earliest on ties). A missing anchor close or an incomplete/invalid peak window is
    unknown. At horizon 126 this equals PR17's function.
    """
    groups: list[list[int]] = []
    for index in sorted(set(starts)):
        if not groups or index - groups[-1][-1] > 20:
            groups.append([])
        groups[-1].append(index)
    result: list[LongEpisode] = []
    for group in groups:
        values = closes[group]
        if not np.isfinite(values).all() or (values <= 0).any():
            result.append(LongEpisode(tuple(group), None, None, "unknown", "missing_or_invalid_anchor"))
            continue
        anchor = min(zip(group, values, strict=True), key=lambda item: (item[1], item[0]))[0]
        if anchor + horizon >= len(closes):
            result.append(LongEpisode(tuple(group), anchor, None, "unknown", "incomplete_window"))
            continue
        window = closes[anchor : anchor + horizon + 1]
        if not np.isfinite(window).all() or (window <= 0).any():
            result.append(LongEpisode(tuple(group), anchor, None, "unknown", "missing_or_invalid_price"))
            continue
        peak = anchor + 1 + int(np.argmax(window[1:]))  # argmax picks the earliest maximum
        result.append(LongEpisode(tuple(group), anchor, peak, "known"))
    return result


def observe_to_peak(episode: LongEpisode, closes: NDArray[np.float64], states: NDArray[np.int8]) -> dict[str, object]:
    """PR17 Q4 observation with the window anchor-20..peak instead of anchor-20..anchor+40.

    `states` is 1 on days the set holds on an eligible day, 0 when known not to, -1 when
    unknown. An observed match is never erased by unknown days; unmatched needs every
    window day known. Timing is certain only when no unknown day precedes the first match.
    """
    anchor, peak = episode.anchor_index, episode.peak_index
    if anchor is None or peak is None:
        return {"coverage_status": "unknown", "reason": episode.reason or "unknown_episode", "anchor_index": anchor, "peak_index": peak}
    start = anchor - 20
    if start < 0:
        window = states[: peak + 1]
        complete = False
    else:
        window = states[start : peak + 1]
        complete = True
    offset = max(start, 0)
    matches = np.flatnonzero(window == 1)
    first = int(offset + matches[0]) if len(matches) else None
    known = complete and bool((window != -1).all())
    certain = first is not None and complete and bool((states[start:first] != -1).all())
    status = "matched" if first is not None else "unmatched" if known else "unknown"
    anchor_price, peak_price = float(closes[anchor]), float(closes[peak])
    first_price = None if first is None else float(closes[first])
    return {
        "coverage_status": status,
        "reason": None,
        "anchor_index": anchor,
        "peak_index": peak,
        "window_calendar_full": complete,
        "first_matching_index": first,
        "first_timing_certain": certain,
        "observed_offset": None if first is None else first - anchor,
        "entry_return": None if first_price is None else first_price / anchor_price - 1,
        "remaining_return": None if first_price is None else peak_price / first_price - 1,
        "episode_peak_return": peak_price / anchor_price - 1,
    }


def set_states(atoms: dict[str, NDArray[np.int8]], names: tuple[str, ...], eligible: NDArray[np.bool_]) -> NDArray[np.int8]:
    """1 on eligible days where every atom is in its bin; 0 if ineligible or any atom known out; else -1."""
    stacked = np.stack([atoms[name] for name in names])
    holds = (stacked == 1).all(axis=0)
    out = (stacked == 0).any(axis=0)
    return np.where(~eligible | out, np.int8(0), np.where(holds, np.int8(1), np.int8(-1))).astype(np.int8)


def random_daily_draws(
    eligible_days: NDArray[np.bool_], quota_days: NDArray[np.bool_], years: NDArray[np.integer], *, group_id: str, code: str
) -> tuple[NDArray[np.bool_], list[dict[str, object]]]:
    """Per stock x year, draw as many eligible days as the set held, without replacement.

    The daily-pool analogue of `pattern_scan_episode_coverage_v1.random_matched_control`:
    each group/stock/year has its own seed derived from (20261021, group, code, year);
    outcomes and episode windows are never read; a shortfall stays in its year and marks
    that stratum unknown.
    """
    drawn = np.zeros(len(eligible_days), dtype=bool)
    quotas: list[dict[str, object]] = []
    for year in np.unique(years[quota_days]):
        pool = np.flatnonzero(eligible_days & (years == year))
        quota = int((quota_days & (years == year)).sum())
        take = min(quota, len(pool))
        seed = int.from_bytes(f"{COVERAGE_SEED}|{group_id}|{code}|{int(year)}".encode(), "big") % (2**63)
        chosen = np.random.default_rng(seed).choice(len(pool), size=take, replace=False)
        drawn[pool[np.sort(chosen)]] = True
        quotas.append({
            "group_id": group_id,
            "code": code,
            "year": int(year),
            "quota_n": quota,
            "available_n": len(pool),
            "drawn_n": take,
            "shortfall_n": quota - take,
        })
    return drawn, quotas
