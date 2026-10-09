"""Compare frozen v4 definition/prices/events, never forward labels or outcomes."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import logging
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from research_core import cache_execution, derived_cache, derived_features, price_basis
from research_core.artifact_store import file_digest, safe_path, write_json
from research_core.patterns.hhhl import source

LOGGER = logging.getLogger(__name__)
OHLC = ["Open", "High", "Low", "Close"]
RAW_COLUMNS = ["Code", "Date", *OHLC, "Volume"]
ACTION_COLUMNS = ["code", "ex_date", "event_type", "price_factor"]
ORIGINAL_CASES_SHA256 = "8e2c2937c38fe276a00246b23b497b8f7f8a93b20ff9dca2be7a463453ec7abb"  # pragma: allowlist secret - archived validation-cases.json SHA256


def iso_day(value: Any) -> str:
    day = pd.Timestamp(value)
    if not isinstance(day, pd.Timestamp):
        raise ValueError("finite daily timestamp required")
    return day.date().isoformat()


def legacy_prices(raw: pd.DataFrame, actions: pd.DataFrame, code: str, cutoff: str) -> pd.DataFrame:
    """Execute only verified adjprice.load AST with explicit in-memory adapters.

    Original _factors filter/first-per-code-day semantics are reproduced below;
    its live SQLite reader, imports, decorator and examples never execute.
    The legacy source's total-return label is not adopted by this validator.
    """
    return _legacy_prices_from_source(raw, actions, code, cutoff, adjprice_text=source.verify_sources("v4")["adjprice.py"])


def _legacy_prices_from_source(raw: pd.DataFrame, actions: pd.DataFrame, code: str, cutoff: str, *, adjprice_text: str) -> pd.DataFrame:
    """Compile the caller's captured trusted adapter without filesystem reads."""
    nodes = [node for node in ast.parse(adjprice_text).body if isinstance(node, ast.FunctionDef) and node.name == "load"]
    if len(nodes) != 1 or nodes[0].decorator_list:
        raise ValueError("one undecorated frozen load function required")
    bars = raw.loc[raw["Code"].astype(str).eq(code)].copy()
    bars = bars.rename(columns={"Date": "asof_date", "Volume": "VolumeLots", **{name: f"Raw{name}" for name in OHLC}})
    bars["atr14_pct"] = np.nan  # Original load replaces this input entirely.
    factors = actions.copy()
    factors["ex_date"] = pd.to_datetime(factors["ex_date"]).dt.strftime("%Y-%m-%d")
    factors["price_factor"] = pd.to_numeric(factors["price_factor"], errors="coerce")
    factors = factors.loc[factors["ex_date"].notna() & factors["price_factor"].gt(0) & factors["ex_date"].le(cutoff)]
    factors["code"] = factors["code"].astype(str)
    factors = factors.drop_duplicates(["code", "ex_date"])

    def supplied_parquet(path: Path, *, columns: list[str]) -> pd.DataFrame:
        if path.name != f"{code}.parquet":
            raise ValueError("frozen loader requested an unexpected symbol")
        return bars.loc[:, columns].copy()

    namespace: dict[str, Any] = {
        "np": np,
        "pd": SimpleNamespace(DataFrame=pd.DataFrame, read_parquet=supplied_parquet),
        "TABLES": Path("supplied-in-memory-bars"),
        "_factors": lambda: factors.copy(),
    }
    statements: list[ast.stmt] = list(nodes)
    exec(compile(ast.Module(body=statements, type_ignores=[]), "verified-v4-adjprice-load", "exec"), namespace)
    if bars[[f"Raw{name}" for name in OHLC]].dropna().empty:
        return pd.DataFrame(columns=pd.Index(["asof_date", *OHLC, "RawClose", "VolumeLots", "atr14_pct", "div_factor"]))
    return namespace["load"](code)


def dated_events(daily: pd.DataFrame, detector: Any, *, reset_gaps: bool) -> dict[str, dict[str, Any]]:
    """Restart the unchanged detector on each consecutive quality-valid segment."""
    valid = daily["Quality"].eq(True).to_numpy() if reset_gaps else np.ones(len(daily), dtype=bool)
    starts = np.flatnonzero(valid & ~np.r_[False, valid[:-1]])
    stops = np.flatnonzero(valid & ~np.r_[valid[1:], False]) + 1
    result: dict[str, dict[str, Any]] = {}
    for start, stop in zip(starts, stops):
        segment = daily.iloc[start:stop].reset_index(drop=True)
        for event in detector(segment):
            position = int(start + event["t"])
            day = iso_day(daily.iloc[position]["asof_date"])
            result[day] = {
                "date": day,
                "pattern": bool(event["pattern"]),
                "scale": event["scale"],
                "cat": event["cat"],
                "blocking": event["blocking"],
                "bonus_levels": event["bonus_levels"],
                "hz_top": float(event["hz_top"]),
                "restart_date": iso_day(segment.iloc[event["restart"]]["asof_date"]),
            }
    return result


def expectation(case: dict[str, Any], event: dict[str, Any] | None) -> bool:
    if event is None or not event["pattern"]:
        return False
    if case["kind"] == "rule":
        return not event["bonus_levels"]
    return event["scale"] == "small_range" and any(
        bonus["age"] == "old" and math.isclose(float(bonus["level"]), 20.48, abs_tol=0.05) for bonus in event["bonus_levels"]
    )


def validate(*, inputs: Path, cutoff: str, cache_version: Path | None = None) -> dict[str, Any]:
    """Run evidence production in a fresh source-bound worker."""
    return cache_execution.execute(
        "validate", {"inputs": str(inputs.absolute()), "cutoff": cutoff, "cache_version": str(cache_version.absolute()) if cache_version is not None else None}
    )


def _validate_in_process(*, inputs: Path, cutoff: str, cache_version: Path | None = None) -> dict[str, Any]:
    """Produce a deterministic receipt; caller decides where to save it."""
    implementation = derived_cache._implementation_paths() | {"compatibility.py": Path(__file__), "source.py": Path(source.__file__)}
    cache_execution.require_loaded(implementation)
    inputs = safe_path(inputs)
    paths = {name: inputs / name for name in ("prices.parquet", "actions.parquet", "calendar.json", "cases.json")}
    cases_bytes = paths["cases.json"].read_bytes()
    hashes = {name: file_digest(path) for name, path in paths.items() if name != "cases.json"}
    hashes["cases.json"] = hashlib.sha256(cases_bytes).hexdigest()
    texts = source.verify_sources("v4")
    LOGGER.debug("Captured v4 source members=%d for compatibility execution", len(texts))
    detector = source._detector_from_sources("v4", texts)
    cases = json.loads(cases_bytes)
    if (
        not isinstance(cases, list)
        or not cases
        or any(set(case) != {"id", "code", "date", "kind"} or case["kind"] not in {"rule", "old_pressure"} for case in cases)
    ):
        raise ValueError("cases must contain only id/code/date/kind; no forward outcomes")
    if any(not str(case["code"]).isdigit() for case in cases) or len({(str(case["code"]), case["date"]) for case in cases}) != len(cases):
        raise ValueError("case symbols must be numeric and code/date pairs distinct")
    calendar = derived_cache._calendar(paths["calendar.json"])
    prices = pd.read_parquet(paths["prices.parquet"], columns=RAW_COLUMNS)
    actions = pd.read_parquet(paths["actions.parquet"], columns=ACTION_COLUMNS)
    prices["Date"] = pd.to_datetime(prices["Date"])
    if bool(prices["Date"].gt(pd.Timestamp(cutoff)).any()):
        raise ValueError("input prices exceed cutoff")
    cache_manifest = derived_cache.verify_cache(cache_version) if cache_version is not None else None
    if cache_manifest is not None:
        identity = cache_manifest["identity"]
        if (
            identity["inputs"] != {name: hashes[name] for name in ("prices.parquet", "actions.parquet", "calendar.json")}
            or identity["parameters"]["cutoff"] != cutoff
        ):
            raise ValueError("explicit cache inputs/cutoff differ from compatibility inputs")
        current = {name: file_digest(path) for name, path in derived_cache._implementation_paths().items()}
        if identity["implementation"] != current:
            raise ValueError("explicit cache implementation differs from current execution")
    results, symbols = [], []
    for code in sorted({str(case["code"]) for case in cases}):
        raw = prices.loc[prices["Code"].astype(str).eq(code)]
        if raw.empty:
            raise ValueError(f"case symbol absent: {code}")
        legacy = _legacy_prices_from_source(raw, actions, code, cutoff, adjprice_text=texts["adjprice.py"])
        if cache_version is None:
            new, _ = derived_features.compute_features(price_basis.prepare_prices(raw, actions, calendar, basis="reference_factor_adjusted", cutoff=cutoff))
            new = new.rename_axis("asof_date").reset_index()
        else:
            new = derived_cache.read_cached(cache_version, "reference_factor_adjusted", code).rename(columns={"Date": "asof_date"})
        old_events = dated_events(legacy, detector, reset_gaps=False)
        new_events = dated_events(new, detector, reset_gaps=True)
        old_aligned = legacy.set_index("asof_date").reindex(calendar)
        new_aligned = new.set_index("asof_date").reindex(calendar)
        differences = {}
        for name in [*OHLC, "atr14_pct"]:
            old_values, new_values = old_aligned[name].to_numpy(float), new_aligned[name].to_numpy(float)
            changed = ~np.isclose(old_values, new_values, equal_nan=True, rtol=1e-12, atol=1e-10)
            finite = np.isfinite(old_values) & np.isfinite(new_values)
            differences[name] = {
                "changed_rows": int(changed.sum()),
                "max_absolute_difference": float(np.abs(old_values[finite] - new_values[finite]).max()) if finite.any() else None,
            }
        changed_events = [
            {"date": day, "legacy": old_events.get(day), "new": new_events.get(day)}
            for day in sorted(set(old_events) | set(new_events))
            if old_events.get(day) != new_events.get(day)
        ]
        quality = [{"date": iso_day(row["asof_date"]), "reason": row["quality_reason"]} for _, row in new.loc[~new["Quality"]].iterrows()]
        event_inputs = actions.loc[actions["code"].astype(str).eq(code)].copy()
        event_inputs["ex_date"] = pd.to_datetime(event_inputs["ex_date"]).dt.strftime("%Y-%m-%d")
        event_inputs = event_inputs.loc[event_inputs["ex_date"].le(cutoff)]
        event_records = event_inputs.replace({np.nan: None}).to_dict("records")
        for record in event_records:
            factor = record["price_factor"]
            if isinstance(factor, (float, np.floating)) and not np.isfinite(factor):
                record["price_factor"] = str(factor)
        symbols.append({
            "code": code,
            "legacy_rows": len(legacy),
            "new_rows": len(new),
            "price_differences": differences,
            "quality_gaps": quality,
            "event_differences": changed_events,
            "actions": event_records,
        })
        for case in (case for case in cases if str(case["code"]) == code):
            old_event, new_event = old_events.get(case["date"]), new_events.get(case["date"])
            case_day = pd.Timestamp(case["date"])
            case_prices: dict[str, Any] = {}
            for name in [*OHLC, "atr14_pct"]:
                old_value = old_aligned.at[case_day, name] if case_day in calendar else np.nan
                new_value = new_aligned.at[case_day, name] if case_day in calendar else np.nan
                case_prices[name] = {
                    "legacy": float(old_value) if pd.notna(old_value) and np.isfinite(old_value) else None,
                    "new": float(new_value) if pd.notna(new_value) and np.isfinite(new_value) else None,
                }
            results.append({
                **case,
                "legacy_pass": expectation(case, old_event),
                "new_pass": expectation(case, new_event),
                "legacy_event": old_event,
                "new_event": new_event,
                "prices": case_prices,
                "new_quality_reason": new_aligned.at[case_day, "quality_reason"] if case_day in calendar else "outside_calendar",
            })
        LOGGER.info("Compared v4 code=%s legacy_events=%d new_events=%d gaps=%d", code, len(old_events), len(new_events), len(quality))
    if {name: file_digest(path) for name, path in paths.items()} != hashes:
        raise ValueError("compatibility inputs changed during evaluation")
    cache_execution.require_loaded(implementation)
    inventory = (
        hashes["cases.json"] == ORIGINAL_CASES_SHA256
        and len(cases) == 25
        and sum(case["kind"] == "rule" for case in cases) == 24
        and [(str(case["code"]), case["date"]) for case in cases if case["kind"] == "old_pressure"] == [("2527", "2023-04-07")]
    )
    return {
        "schema": "hhhl-v4-cache-compatibility.v1",
        "no_forward_outcomes_read": True,
        "cutoff": cutoff,
        "input_sha256": hashes,
        "source_sha256": {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in texts.items()},
        "implementation_sha256": {name: file_digest(path) for name, path in implementation.items()},
        "legacy_adapter": (
            "Verified original load AST; explicit in-memory bars; reproduced _factors first-per-code/ex-date filter, not byte-identical loader execution."
        ),
        "limitations": (
            "Factor-restated prices are not total return or PIT certified; historical validation examples are not fresh recognition or strategy approval."
        ),
        "cache_version": cache_manifest["version_id"] if cache_manifest else None,
        "expectations": {
            "rule": "pattern true and bonus_levels empty",
            "old_pressure": "pattern true, small_range, old bonus near 20.48",
            "old_level_absolute_tolerance": 0.05,
        },
        "checks": {"original_25_case_inventory": inventory, "legacy_all_expected": all(row["legacy_pass"] for row in results)},
        "legacy_passed": inventory and all(row["legacy_pass"] for row in results),
        "new_all_expected": inventory and all(row["new_pass"] for row in results),
        "cases": results,
        "symbols": symbols,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--cache-version", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    receipt = validate(inputs=args.inputs, cutoff=args.cutoff, cache_version=args.cache_version)
    safe_path(args.output).parent.mkdir(parents=True, exist_ok=True)
    write_json(safe_path(args.output), receipt)
    print(json.dumps({"output": str(args.output), "legacy_passed": receipt["legacy_passed"], "new_all_expected": receipt["new_all_expected"]}))  # noqa: T201 - CLI receipt
    return 0 if receipt["legacy_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
