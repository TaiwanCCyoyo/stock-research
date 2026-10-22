"""Compare `daily-conditions.v1` with the values PR17 stored, on real data.

PR17 computed its per-stock condition values at cutoff 2026-10-12 on its approved
4,110-session calendar and kept them as `parts/<id>/common_values.parquet` in its
stock run directory. This check rebuilds the same stocks from a shared generation
with `read_adjusted_daily(..., as_of=cutoff, calendar=PR17 calendar)` (proven equal
to PR17's prices), runs `technical_daily_v1` and `daily_conditions_v1`, and compares
every mapped column cell by cell: values, NaN/null positions and, for PR17's
thresholded flags, the flag implied by the shared value. Read-only; writes one JSON
report.

    uv run python -m scripts.check_daily_conditions \
        --stock-run <PR17 full-2010-20261016-retention-v3 directory> \
        --calendar-pins tasks/20261013-pattern-scan/params/input-pins-v1.json.gz \
        --generation 2026-10-15-20261015T161626Z --codes 50 --out .tmp/daily-conditions-check.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from research_core import daily_conditions_v1, technical_daily_v1
from research_core.maintained_adjusted_daily import read_adjusted_daily
from research_core.pattern_scan_parquet_v1 import read_frame

LOGGER = logging.getLogger(__name__)
NUMERIC = {
    "ma_alignment": "C",
    "sma240_change20": "C2",
    "close_to_sma240": "C3",
    "close_to_prior250_high": "D",
    "close_to_prior250_low": "D2",
    "atr_ratio120": "F",
    "volume_ratio20": "G",
    "return120": "ret120",
    "volume20_prior": "prior_volume20",
    "turnover20_prior": "turnover20",
    "close_to_sma20": "MA_a",
    "bb_percent_b": "BB_a",
    "bb_width_rank125": "BB_b",
    "support_gap_k15": "SR_b",
    "candle_body_ratio": "KL_a",
    "candle_upper_shadow_ratio": "KL_b",
    "volume10_to_60_prior": "VOL_a",
}
FLAGS = {"weekly_ma10_up": "C4", "bb_squeeze_within5": "BB_c"}
THRESHOLDS = {"raw_return1": ("G2_limit", 0.095), "close_location": ("G2_position", 0.75)}


def _same(left: pd.Series | pd.DataFrame, right: pd.Series | pd.DataFrame) -> np.ndarray:
    """Exact equality where two missing values are equal."""
    a, b = left.to_numpy(dtype=object), right.to_numpy(dtype=object)
    missing_a, missing_b = pd.isna(a), pd.isna(b)
    equal = np.array([not (ma or mb) and bool(x == y) for x, y, ma, mb in zip(a, b, missing_a, missing_b)], dtype=bool)
    return equal | (missing_a & missing_b)


def _stored_parts(stock_run: Path) -> dict[str, Path]:
    parts: dict[str, Path] = {}
    for part in sorted((stock_run / "parts").iterdir()):
        path = part / "common_values.parquet"
        if path.is_file():
            security = str(pq.read_table(path, columns=["security_id"]).column(0)[0].as_py())
            parts[security.removeprefix("TW:")] = path
    return parts


def compare_code(code: str, stored_path: Path, calendar: pd.DatetimeIndex, cutoff: str, generation: str) -> dict[str, Any]:
    prices, _ = read_adjusted_daily("reference_factor_adjusted", codes=[code], as_of=cutoff, calendar=calendar, generation=generation)
    prepared = prices.drop(columns="Code").set_index("Date")
    technical, pivots = technical_daily_v1.compute_technical(code, prepared)
    shared = daily_conditions_v1.compute_conditions(code, prepared, technical, pivots).set_index("Date")
    stored = read_frame(stored_path)
    if not stored.index.equals(shared.index):
        return {"code": code, "error": "row dates differ", "stored_rows": len(stored), "shared_rows": len(shared)}
    mismatches: dict[str, int] = {}

    def record(name: str, equal: np.ndarray) -> None:
        if not equal.all():
            mismatches[name] = int((~equal).sum())

    for column, legacy in {**NUMERIC, **FLAGS}.items():
        record(column, _same(shared[column], stored[legacy]))
    for column, (legacy, threshold) in THRESHOLDS.items():
        values = shared[column]
        implied = pd.Series(values >= threshold, index=values.index, dtype="boolean").where(values.notna())
        record(column, _same(implied, stored[legacy]))
    resistance = shared["resistance_gap_k15"].astype(object).where(shared["resistance_gap_k15"].notna())
    resistance = resistance.where(~shared["no_resistance_k15"].fillna(False).astype(bool), "none")
    record("resistance_gap_k15/no_resistance_k15", _same(resistance, stored["SR_a"]))
    record("volume_profile120", _same(shared["volume_profile120"], stored["SR_c"]))
    return {"code": code, "rows": len(shared), "mismatches": mismatches}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stock-run", type=Path, required=True)
    parser.add_argument("--calendar-pins", type=Path, required=True)
    parser.add_argument("--generation", required=True)
    parser.add_argument("--codes", type=int, default=50, help="random sample size (seed 20261022); 0 checks every stored stock")
    parser.add_argument("--code", action="append", help="check these codes instead of a sample")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    pins = json.loads(gzip.decompress(args.calendar_pins.read_bytes()))
    cutoff = str(pins["cutoff"])
    calendar = pd.DatetimeIndex(pd.to_datetime(pins["price_observation"]["calendar"]["dates"]))
    parts = _stored_parts(args.stock_run)
    if args.code:
        selected = list(args.code)
    elif args.codes:
        selected = sorted(random.Random(20261022).sample(sorted(parts), min(args.codes, len(parts))))
    else:
        selected = sorted(parts)
    started = time.monotonic()
    results = []
    for position, code in enumerate(selected, 1):
        results.append(compare_code(code, parts[code], calendar, cutoff, args.generation))
        if position % 10 == 0:
            LOGGER.info("Checked %d/%d codes", position, len(selected))
    failed = [result for result in results if result.get("error") or result["mismatches"]]
    report = {
        "definition": daily_conditions_v1.DEFINITION_VERSION,
        "generation": args.generation,
        "cutoff": cutoff,
        "calendar_sessions": len(calendar),
        "stored_stocks": len(parts),
        "checked_codes": len(selected),
        "checked_rows": sum(result.get("rows", 0) for result in results),
        "codes_with_differences": len(failed),
        "wall_seconds": round(time.monotonic() - started, 1),
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    LOGGER.info("Checked %d codes, %d rows; %d with differences", len(selected), report["checked_rows"], len(failed))


if __name__ == "__main__":
    main()
