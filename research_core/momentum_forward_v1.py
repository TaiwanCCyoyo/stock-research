"""Forward log for the momentum-only study (mission section 前瞻紀錄).

One frozen Parquet file per trading day, one row per PR17-universe stock, written once
with no-replace publication and never recomputed. Values are what the shared generation
said on the evening of that day: the same PR17 eligibility, atoms, C-52w and H as the
historical study (`momentum_only_v1`), evaluated on full history up to the day.

Every day is read with `read_adjusted_daily(..., as_of=day)` on the current generation, so
each stock has the full calendar up to that day (a stock without a quote that day is
ineligible). A day is `recorded_late=False` only when it is the current generation's
as-of day at recording time (after that day's 20:30 shared update, before the next one).
Outcomes are never read here.

Every invocation appends one line to `attempts.jsonl` (`record_with_ledger`): on time, late,
cohort recovered, already frozen, refused (producer busy, uncommitted code) or failed,
with the generation it saw and any error, plus the trading days of the current calendar
that still have no frozen file (inside the cohort's own confirmatory window once it exists). A missed or failed day therefore leaves
a dated trace instead of silence, and a later backfill cannot pass for an on-time row.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeAlias, cast

import numpy as np
import pandas as pd

from research_core import momentum_only_v1 as study
from research_core.artifact_store import publish_noreplace, read_json
from research_core.maintained_adjusted_daily import current_generation, read_adjusted_daily
from research_core.pattern_scan_controls_v1 import scan_controls
from research_core.pattern_scan_daily_values_v1 import calculate_common_values
from research_core.pattern_scan_indicators_v1 import prepare_detector_frame
from research_core.pattern_scan_inputs_v1 import daily_qualification
from research_core.patterns.scan_contract_v1 import Bars

LOGGER = logging.getLogger(__name__)
DEFINITION_ID = "momentum-only-forward.v1"
MISSION_MERGED_UTC = "2026-10-21T19:48:47+00:00"
# The merge happened at 2026-10-22 03:48 Asia/Taipei, so 2026-10-21 and earlier are the
# mission's prereg_backfill days even when one of them is still the current generation.
FIRST_CONFIRMATORY_DAY = "2026-10-22"
TAIPEI = "Asia/Taipei"


def freeze_deadline(day: str) -> pd.Timestamp:
    """Latest on-time recording moment for `day`: 09:00 Asia/Taipei on the next weekday.

    The next session cannot open earlier, so a row frozen before then has seen no later
    price. A holiday only makes the window conservative (an earlier deadline), never longer.
    """
    next_weekday = cast(pd.Timestamp, pd.Timestamp(day) + pd.offsets.BDay(1))
    return cast(pd.Timestamp, pd.Timestamp(next_weekday.strftime("%Y-%m-%d") + " 09:00", tz=TAIPEI))


def is_on_time(day: str, generation_asof: str, now: pd.Timestamp) -> bool:
    """On time: the current generation is that day, the mission was merged, and the next session has not opened."""
    return day == generation_asof and day >= FIRST_CONFIRMATORY_DAY and now < freeze_deadline(day)


VALUE_COLUMNS = {"A1": "C3", "A2": "D2", "A3": "G2_limit", "A5": "RSI", "A6": "F"}
PATTERN_NULL_REASON = "PR17 daily raw union pattern states are not maintained incrementally; A7, LEAD_H1 and pattern states are null"


@dataclass(frozen=True)
class StockDay:
    code: str
    row: dict[str, Any]
    eligible: bool
    ret120: float
    atoms: dict[str, int]


def stock_day(code: str, prepared: pd.DataFrame) -> StockDay:
    """Last-row values of one stock's full-history PR17 computations."""
    indicators, pivots = prepare_detector_frame(prepared)
    qualification = daily_qualification(prepared, ordinary_reference=True)
    eligible = qualification["base_eligible"].to_numpy(dtype=bool)
    controls = scan_controls(Bars.from_frame(indicators), base_eligible=eligible, h1_source_events=(), p1_events=())
    common = calculate_common_values(indicators, pivots)
    last = len(prepared) - 1
    atoms = {name: int(study._atom_state(*study.ATOMS[name][:2], cast(pd.Series, common[study.ATOMS[name][2]]))[last]) for name in study.LOCAL_ATOMS}
    row: dict[str, Any] = {
        "security_id": f"TW:{code}",
        "base_eligible": bool(eligible[last]),
        "eligibility_reason": qualification["eligibility_reason"].iloc[last],
        "raw_close": float(prepared["RawClose"].iloc[last]),
        "adjusted_close": float(indicators["Close"].iloc[last]),
        "c52w_state": int(controls["C-52w"].formula_states[last]),
        "c52w_daily": bool(controls["C-52w"].admitted_states[last] == 1),
    }
    for name, column in VALUE_COLUMNS.items():
        value = common[column].iloc[last]
        row[f"{name}_value"] = None if pd.isna(value) else (bool(value) if name == "A3" else float(value))
        row[f"{name}_state"] = atoms[name]
    return StockDay(code, row, bool(eligible[last]), float(common["ret120"].iloc[last]), atoms)


def _one(arguments: tuple[str, str, str]) -> StockDay:
    code, generation, as_of = arguments
    prices, _ = read_adjusted_daily(
        "reference_factor_adjusted",
        codes=[code],
        generation=generation,
        as_of=as_of,
    )
    return stock_day(code, prices.drop(columns="Code").set_index("Date"))


def day_frame(codes: Sequence[str], *, generation: str, day: str, late: bool, workers: int = 1) -> pd.DataFrame:
    """Rows for every code quoted on `day`, with the cross-sectional H and all set flags."""
    status = current_generation(generation=generation)
    if not late and status["asof"] != day:
        raise ValueError(f"an on-time record needs the generation as-of {status['asof']} to equal {day}")
    jobs = [(code, generation, day) for code in codes]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            computed = list(pool.map(_one, jobs, chunksize=8))
    else:
        computed = [_one(job) for job in jobs]
    days = computed
    pool_mask = np.array([item.eligible and np.isfinite(item.ret120) for item in days])
    ranks = pd.Series([item.ret120 for item in days]).where(pool_mask).rank(method="average", pct=True) * 100
    h_states = study._atom_state("H", "ge90", ranks)
    rows = []
    sets = study.condition_sets()
    for item, h_value, h_state in zip(days, ranks, h_states, strict=True):
        atoms = {name: np.array([state], dtype=np.int8) for name, state in item.atoms.items()}
        atoms["A4"] = np.array([h_state], dtype=np.int8)
        eligible = np.array([item.eligible])
        flags = {f"set_{name}": int(study.set_states(atoms, members, eligible)[0]) for name, members in sets.items()}
        rows.append({**item.row, "A4_value": None if pd.isna(h_value) else float(h_value), "A4_state": int(h_state), **flags})
    frame = pd.DataFrame(rows)
    frame.insert(0, "t0", day)
    frame["A7_state"] = None
    frame["set_A7"] = None
    frame["set_LEAD_H1"] = None
    frame["pattern_states"] = None
    frame["pattern_null_reason"] = PATTERN_NULL_REASON
    frame["generation"] = generation
    frame["recorded_late"] = late
    return frame


Clock: TypeAlias = pd.Timestamp | Callable[[], pd.Timestamp] | None


def _clock(now: Clock) -> Callable[[], pd.Timestamp]:
    """A fixed `Timestamp` (tests), a callable clock, or the wall clock in Asia/Taipei."""
    if callable(now):
        return now
    if now is not None:
        fixed = now
        return lambda: fixed
    return lambda: cast(pd.Timestamp, pd.Timestamp.now(tz=TAIPEI))


def record_day(root: Path, codes: Sequence[str], *, day: str | None, code_commit: str, workers: int = 1, now: Clock = None) -> Path:
    """Freeze one day under `root/days/<day>.parquet`; never overwrite an existing day.

    A day is on time only while `is_on_time` holds at the start and again just before
    publication; anything else, including a stale current generation, is recorded late.
    """
    clock = _clock(now)
    status = current_generation()
    target_day = day or status["asof"]
    late = not is_on_time(target_day, status["asof"], clock())
    destination = root / "days" / f"{target_day}.parquet"
    if destination.exists():
        if _recover_cohort(root, destination, target_day):
            return destination
        raise FileExistsError(f"{destination} is already frozen; corrections go to a separate correction file")
    frame = day_frame(codes, generation=status["generation"], day=target_day, late=late, workers=workers)
    if not late and not is_on_time(target_day, status["asof"], clock()):
        late = True  # the window closed while computing
        frame["recorded_late"] = True
    recorded = datetime.now(timezone.utc).isoformat(timespec="seconds")
    frame["recorded_at_utc"] = recorded
    frame["code_commit"] = code_commit
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".staging-{destination.name}")
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False, compression="zstd")
    staging.write_bytes(buffer.getvalue())
    publish_noreplace(staging, destination)
    _write_cohort(root, target_day, late=late, recorded=recorded)
    LOGGER.info("Froze forward day %s rows=%d late=%s generation=%s", target_day, len(frame), late, status["generation"])
    return destination


def _recover_cohort(root: Path, destination: Path, day: str) -> bool:
    """Start the cohort from an already frozen on-time day if a crash skipped `cohort.json`."""
    if (root / "cohort.json").exists():
        return False
    frozen = pd.read_parquet(destination, columns=["recorded_late", "recorded_at_utc"])
    if frozen.empty or bool(frozen["recorded_late"].any()):
        return False
    recorded = str(frozen["recorded_at_utc"].iloc[0])
    _write_cohort(root, day, late=False, recorded=recorded)
    return (root / "cohort.json").exists()


def _write_cohort(root: Path, day: str, *, late: bool, recorded: str) -> None:
    """The first on-time day after the mission merge starts the 12-month confirmatory sample."""
    path = root / "cohort.json"
    if path.exists() or late or recorded < MISSION_MERGED_UTC or day < FIRST_CONFIRMATORY_DAY:
        return
    start = pd.Timestamp(day)
    end = start + pd.DateOffset(months=12) - pd.Timedelta(days=1)
    cohort = {
        "schema": "momentum-only-forward-cohort.v1",
        "definition": DEFINITION_ID,
        "mission_merged_utc": MISSION_MERGED_UTC,
        "confirmatory_start": day,
        "confirmatory_end": str(cast(pd.Timestamp, end).strftime("%Y-%m-%d")),
        "first_frozen_at_utc": recorded,
        "prereg_backfill": "days before confirmatory_start are descriptive only",
    }
    staging = path.with_name(".staging-cohort.json")
    staging.write_text(json.dumps(cohort, indent=2) + "\n", encoding="utf-8")
    publish_noreplace(staging, path)


def read_cohort(root: Path) -> dict[str, Any] | None:
    path = root / "cohort.json"
    return read_json(path) if path.exists() else None


ATTEMPTS = "attempts.jsonl"


def append_attempt(root: Path, entry: dict[str, Any]) -> None:
    """Append one JSON line to the attempt ledger; earlier lines are never rewritten."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ATTEMPTS).open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_attempts(root: Path) -> list[dict[str, Any]]:
    path = root / ATTEMPTS
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def missing_days(root: Path, status: dict[str, Any], first: str, last: str) -> list[str]:
    """Sessions of the generation calendar in [first, min(last, as-of)] without a frozen file."""
    upper = min(last, status["asof"])
    calendar = pd.read_parquet(Path(status["path"]) / "calendar.parquet")["Date"]
    days = [str(day) for day in pd.Series(calendar).dt.strftime("%Y-%m-%d") if first <= str(day) <= upper]
    return [day for day in days if not (root / "days" / f"{day}.parquet").exists()]


def missing_entry(root: Path, status: dict[str, Any]) -> dict[str, Any]:
    """Ledger fields for unfrozen sessions, split by whether the confirmatory cohort exists.

    Once `cohort.json` exists only its own [confirmatory_start, confirmatory_end] window counts
    (`missing_confirmatory_days`). Before that there is no confirmatory sample yet, so the gaps
    since the mission merge are operational only (`missing_days_before_cohort`).
    """
    cohort = read_cohort(root)
    if cohort is None:
        return {"missing_days_before_cohort": missing_days(root, status, FIRST_CONFIRMATORY_DAY, status["asof"])}
    first, last = cohort["confirmatory_start"], cohort["confirmatory_end"]
    return {"confirmatory_window": [first, last], "missing_confirmatory_days": missing_days(root, status, first, last)}


def record_with_ledger(
    root: Path,
    codes: Sequence[str],
    *,
    day: str | None,
    code_commit: str,
    workers: int = 1,
    now: Clock = None,
    refusal: str | None = None,
) -> Path | None:
    """`record_day` with an attempt line written whatever happens.

    `refusal` lets the caller log a precondition it already refused (producer busy,
    uncommitted code) without recording. Exceptions are logged and re-raised.
    """
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry: dict[str, Any] = {"attempted_at_utc": started, "requested_day": day, "code_commit": code_commit}
    try:
        status = current_generation()
        entry.update({"generation": status["generation"], "generation_asof": status["asof"]})
        entry["target_day"] = day or status["asof"]
        clock_now = _clock(now)()
        if day is None and clock_now >= freeze_deadline(status["asof"]):
            entry["stale_generation"] = f"current generation as-of {status['asof']} was not refreshed before {freeze_deadline(status['asof'])}"
        if refusal is not None:
            entry.update({"outcome": "refused", "reason": refusal})
            return None
        destination = root / "days" / f"{entry['target_day']}.parquet"
        existed = destination.exists()
        had_cohort = (root / "cohort.json").exists()
        try:
            path = record_day(root, codes, day=day, code_commit=code_commit, workers=workers, now=now)
        except FileExistsError as error:
            entry.update({"outcome": "already_frozen", "reason": str(error)})
            raise
        if existed:
            entry["outcome"] = "cohort_recovered" if not had_cohort else "already_frozen"
        else:
            frozen = pd.read_parquet(path, columns=["recorded_late"])
            entry.update({"outcome": "late" if bool(frozen["recorded_late"].any()) else "on_time", "rows": len(frozen)})
        return path
    except BaseException as error:
        entry.setdefault("outcome", "failed")
        entry.setdefault("reason", f"{type(error).__name__}: {error}")
        raise
    finally:
        entry["finished_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            entry.update(missing_entry(root, current_generation()))
        except Exception as error:  # noqa: BLE001 - the ledger line must still be written
            entry["missing_days_error"] = f"{type(error).__name__}: {error}"
        append_attempt(root, entry)
        LOGGER.info("Forward attempt %s day=%s", entry.get("outcome"), entry.get("target_day"))


def scheduled_record(
    root: Path,
    codes: Sequence[str],
    *,
    code_commit: str,
    workers: int = 1,
    poll_seconds: float = 900.0,
    max_wait_seconds: float = 12 * 3600.0,
    clock: Callable[[], pd.Timestamp] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    producer_idle: Callable[[], None] | None = None,
    refusal: str | None = None,
) -> Path | None:
    """Wait for today's shared generation, then record it once; never guess a day.

    Started after the weekday 20:30 shared update, it polls until the current generation's
    as-of is today (Asia/Taipei) and the producer is idle, then calls `record_with_ledger`
    with a clock that keeps moving, so a run that finishes after the deadline is late. It
    waits until `freeze_deadline(today)` or `max_wait_seconds`: the generation calendar is
    the union of producer quote dates, not an exchange calendar, so a stale generation is
    never read as a holiday. Whatever happens, the invocation leaves exactly one ledger
    line: `record_with_ledger`'s own, or a `not_recorded`/`failed` line with the last
    generation seen. An already frozen day is a success; `refusal` (uncommitted code) is
    logged as `refused` without waiting.
    """
    now = clock or (lambda: cast(pd.Timestamp, pd.Timestamp.now(tz=TAIPEI)))
    start = now()
    today = str(start.strftime("%Y-%m-%d"))
    if refusal is not None:
        return record_with_ledger(root, codes, day=None, code_commit=code_commit, workers=workers, now=now, refusal=refusal)
    last: dict[str, Any] | None = None
    try:
        while True:
            last = current_generation()
            busy = None
            if producer_idle is not None:
                try:
                    producer_idle()
                except RuntimeError as error:
                    busy = str(error)
            if last["asof"] >= today and busy is None:
                break
            built = last.get("built_at_utc")
            reason = f"producer busy: {busy}" if busy else f"generation not refreshed: current {last['generation']} as-of {last['asof']} built {built}"
            if now() >= freeze_deadline(today) or (now() - start).total_seconds() + poll_seconds > max_wait_seconds:
                _append_terminal(root, start, today, code_commit, last, "not_recorded", reason)
                LOGGER.warning("Forward day %s not recorded: %s", today, reason)
                return None
            LOGGER.info("Waiting for today's generation (%s); next check in %.0fs", reason, poll_seconds)
            sleep(poll_seconds)
    except BaseException as error:
        _append_terminal(root, start, today, code_commit, last, "failed", f"{type(error).__name__}: {error}")
        raise
    try:
        return record_with_ledger(root, codes, day=None, code_commit=code_commit, workers=workers, now=now)
    except FileExistsError:
        return root / "days" / f"{last['asof']}.parquet"


def _append_terminal(root: Path, start: pd.Timestamp, today: str, code_commit: str, status: dict[str, Any] | None, outcome: str, reason: str) -> None:
    """The scheduled run's own ledger line, with the last generation it saw or why that is unavailable."""
    entry: dict[str, Any] = {
        "attempted_at_utc": start.tz_convert("UTC").isoformat(timespec="seconds"),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target_day": today,
        "outcome": outcome,
        "reason": reason,
        "code_commit": code_commit,
        "generation": None if status is None else status["generation"],
        "generation_asof": None if status is None else status["asof"],
    }
    if status is None:
        entry["missing_days_error"] = "unavailable: no generation was read"
    else:
        try:
            entry.update(missing_entry(root, status))
        except Exception as error:  # noqa: BLE001 - the ledger line must still be written
            entry["missing_days_error"] = f"{type(error).__name__}: {error}"
    append_attempt(root, entry)
