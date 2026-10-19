"""Check `read_adjusted_daily(as_of=...)` against `prepare_prices` on real producer data.

For each cutoff and basis, every symbol with an official quote on or before the cutoff is
read through the shared family as of that cutoff and compared, column by column with exact
equality (NaN equal to NaN, dtypes included), against

    price_basis.prepare_prices(official quotes <= cutoff, actions <= cutoff, calendar, basis, cutoff)

built from the same live producer inputs the generation fingerprinted. The calendar is the
approved fixed calendar from `--calendar-pins` for its own cutoff and the generation's
sessions up to the cutoff otherwise. The report also counts how often truncating the latest
generation would have given a different answer, which is why the reader recomputes.

    uv run python -m scripts.check_adjusted_daily_asof --root D:/scratch/shared --build \\
        --cutoff 2026-10-12 --cutoff 2020-12-31 \\
        --calendar-pins tasks/20261013-pattern-scan/params/input-pins-v1.json.gz --out .tmp/asof-check.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import time
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core import maintained_adjusted_daily as family
from research_core import price_basis
from research_core.producer_data import producer_data_root
from research_core.run_receipt import assert_inputs_unchanged

LOGGER = logging.getLogger(__name__)
CHUNK = 200


def _pins_calendar(path: Path) -> tuple[str, pd.DatetimeIndex]:
    pins = json.loads(gzip.decompress(path.read_bytes()))
    return str(pins["cutoff"]), pd.DatetimeIndex(pd.to_datetime(pins["price_observation"]["calendar"]["dates"]))


def _same(left: Any, right: Any) -> pd.Series:
    """Row-wise exact equality where two missing values are equal."""
    return (left == right) | (left.isna() & right.isna())


def _situations(actions: pd.DataFrame, sessions: pd.DatetimeIndex, cutoff: pd.Timestamp, asof: pd.Timestamp) -> dict[str, int]:
    """How many post-cutoff actions could mislead a reader that truncates the latest generation."""
    dates = pd.to_datetime(actions["ex_date"])
    later = actions.loc[dates.gt(cutoff) & dates.le(asof)]
    known = later["event_type"].isin(sorted(price_basis.PERMANENT_FACTOR_EVENTS | price_basis.CASH_WINDOW_EVENTS))
    kinds_per_day = later.groupby(["code", "ex_date"])["event_type"].nunique()
    return {
        "post_cutoff_actions": len(later),
        "post_cutoff_codes": int(later["code"].nunique()),
        "post_cutoff_unknown_kind": int((~known).sum()),
        "post_cutoff_multi_kind_days": int(kinds_per_day.gt(1).sum()),
        "post_cutoff_noncalendar_ex_dates": int((~pd.to_datetime(later["ex_date"]).isin(sessions)).sum()),
    }


def check_cutoff(
    bars_by_code: dict[str, pd.DataFrame],
    actions: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    calendar_source: str,
    cutoff: pd.Timestamp,
    root: Path,
    generation: str,
) -> dict[str, Any]:
    events_by_code = {str(code): frame for code, frame in actions.groupby("code", sort=False)}
    empty_events = cast(pd.DataFrame, actions.iloc[0:0])
    codes = sorted(code for code, frame in bars_by_code.items() if bool(frame["Date"].le(cutoff).any()))
    result: dict[str, Any] = {"cutoff": cutoff.date().isoformat(), "calendar": {"source": calendar_source, "sessions": len(calendar)}, "codes": len(codes)}
    for basis in family.BASES:
        started = time.monotonic()
        mismatches: dict[str, int] = {}
        examples: list[dict[str, Any]] = []
        rows = outside_span = masked_in_latest = differs_from_truncated = 0
        masked_codes: set[str] = set()
        reader_seconds = 0.0
        calendar_sha256 = None
        for start in range(0, len(codes), CHUNK):
            chunk = codes[start : start + CHUNK]
            began = time.monotonic()
            got, record = family.read_adjusted_daily(basis, codes=chunk, as_of=cutoff, calendar=calendar, root=root, generation=generation)
            reader_seconds += time.monotonic() - began
            calendar_sha256 = record["calendar"]["sha256"]
            latest, _ = family.read_adjusted_daily(basis, codes=chunk, root=root, generation=generation)
            for code, frame in got.groupby("Code", sort=True):
                raw = bars_by_code[str(code)]
                official = raw.loc[raw["Date"].le(cutoff)]
                events = cast(pd.DataFrame, events_by_code.get(str(code), empty_events))
                events = events.loc[pd.to_datetime(events["ex_date"]).le(cutoff)]
                expected = price_basis.prepare_prices(official, events, calendar, basis=basis, cutoff=cutoff).rename_axis("Date").reset_index()
                expected.insert(0, "Code", str(code))
                frame = frame.reset_index(drop=True)
                rows += len(frame)
                span = frame["Date"].between(official["Date"].min(), official["Date"].max())
                outside_span += int((~span).sum())
                for column in expected.columns:
                    if str(frame[column].dtype) != str(expected[column].dtype):
                        mismatches[f"{column}:dtype"] = mismatches.get(f"{column}:dtype", 0) + 1
                        continue
                    unequal = ~_same(frame[column], expected[column])
                    if bool(unequal.any()):
                        mismatches[column] = mismatches.get(column, 0) + int(unequal.sum())
                        if len(examples) < 10:
                            where = int(unequal.to_numpy().nonzero()[0][0])
                            examples.append({"code": str(code), "date": str(frame["Date"].iloc[where].date()), "column": column})
            merged = got.merge(latest, on=["Code", "Date"], suffixes=("", "_latest"))
            masked = merged["restatement_factor_latest"].isna() & merged["restatement_factor"].notna()
            masked_in_latest += int(masked.sum())
            masked_codes.update(merged.loc[masked, "Code"].astype(str))
            different = ~_same(merged["restatement_factor"], merged["restatement_factor_latest"]) | ~_same(
                merged["quality_reason"], merged["quality_reason_latest"]
            )
            differs_from_truncated += int(different.sum())
            LOGGER.info("cutoff=%s basis=%s codes %d/%d mismatching_columns=%s", cutoff.date(), basis, min(start + CHUNK, len(codes)), len(codes), mismatches)
        result[basis] = {
            "rows": rows,
            "rows_outside_first_last_quote": outside_span,
            "mismatching_cells": mismatches,
            "mismatch_examples": examples,
            "equal": not mismatches,
            "truncation_rows_masked_in_latest_known_at_cutoff": masked_in_latest,
            "truncation_codes_masked_in_latest_known_at_cutoff": len(masked_codes),
            "truncation_rows_with_other_factor_or_reason": differs_from_truncated,
            "reader_seconds": round(reader_seconds, 1),
            "seconds": round(time.monotonic() - started, 1),
            "record_calendar_sha256": calendar_sha256,
        }
    return result


def _described(inputs: dict[str, Any]) -> dict[str, Any]:
    """Input descriptions without file hashes: generations built before 2026-10-19 also stored a SHA-256."""
    return {name: {key: value for key, value in row.items() if key != "sha256"} for name, row in inputs.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True, help="shared root holding derived/adjusted-daily-v1 (a scratch root is fine)")
    parser.add_argument("--build", action="store_true", help="build a new generation from the live producer under --root first")
    parser.add_argument("--cutoff", action="append", required=True)
    parser.add_argument("--calendar-pins", type=Path, help="approved preparation pins whose fixed calendar is used for its own cutoff")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    producer = producer_data_root()
    if args.build:
        LOGGER.info("Built %s", family.update(producer_root=producer, root=args.root))
    status = family.current_generation(args.root)
    bars, actions, fingerprint, _ = family.load_inputs(producer)
    # The fingerprint is taken before the reads; recheck so a writer that started in between fails the check.
    assert_inputs_unchanged(fingerprint)
    if _described(fingerprint["inputs"]) != _described(status["input_fingerprint"]["inputs"]):
        raise SystemExit("live producer inputs changed since the generation was built; rebuild with --build")
    sessions = family.session_calendar(bars)
    pinned = _pins_calendar(args.calendar_pins) if args.calendar_pins else None
    bars_by_code = {str(code): frame for code, frame in bars.groupby("Code", sort=True)}
    report: dict[str, Any] = {"generation": status["generation"], "asof": status["asof"], "input_fingerprint": fingerprint["inputs"], "cutoffs": []}
    for text in args.cutoff:
        cutoff = cast(pd.Timestamp, pd.Timestamp(text))
        if pinned and pinned[0] == text:
            calendar, source = pinned[1], f"pins:{args.calendar_pins.as_posix()}"
            extra = calendar.difference(sessions)
            missing = sessions[sessions <= cutoff].difference(calendar)
            LOGGER.info("Pinned calendar vs generation sessions: %d extra, %d missing", len(extra), len(missing))
        else:
            calendar, source = cast(pd.DatetimeIndex, sessions[sessions <= cutoff]), "generation"
        entry = check_cutoff(bars_by_code, actions, calendar, source, cutoff, args.root, status["generation"])
        entry["situations"] = _situations(actions, sessions, cutoff, cast(pd.Timestamp, pd.Timestamp(status["asof"])))
        report["cutoffs"].append(entry)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    assert_inputs_unchanged(fingerprint)
    equal = all(entry[basis]["equal"] for entry in report["cutoffs"] for basis in family.BASES)
    print(json.dumps({"equal": equal, "out": str(args.out)}))  # noqa: T201 - CLI result on stdout
    return 0 if equal else 1


if __name__ == "__main__":
    raise SystemExit(main())
