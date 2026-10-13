"""One fixed study: prepare, measure, run or verify pinned Taiwan annual evidence."""

# Direct script entry needs the repository on sys.path before project imports.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import gzip
import json
import logging
import platform
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow

REPO = Path(__file__).resolve().parents[2]
TASK = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from research_core.annual_ranking_pool import rank_panel
from research_core.annual_rotation import economic_path, first_observed_trade, paired_benchmark_path, select_leaders
from research_core.annual_statistics import equity_drawdown, summarize_annual_excess
from research_core.artifact_store import canonical, file_digest, object_digest, read_json, verify_files, write_json
from research_core.research_data_builder import publish_bundle
from research_core.research_data_catalog import DataCatalog, verify_entry
from research_core.research_data_paths import DataRoots
from research_core.research_measurement_v1 import phase_receipt, resource_sample

LOGGER = logging.getLogger(__name__)


def catalog() -> DataCatalog:
    roots = DataRoots.from_env(worktree=REPO)
    return DataCatalog(roots)


def period(start: str | None = None, end: str | None = None, reason: str | None = None) -> dict[str, Any]:
    return {"start": start, "end": end, "reason": reason}


def metadata(data_id: str, kind: str, inputs: dict[str, Any], params: dict[str, Any], start: str, end: str) -> dict[str, Any]:
    return {
        "data_id": data_id,
        "kind": kind,
        "definition_version": params["definition_version"],
        "parameters": params,
        "inputs": inputs,
        "coverage": {
            "scope": "cached historical TWSE/TPEx quote codes; incomplete PIT common-stock census; 0050 comparator",
            "raw_input_period": period(start, end),
            "valid_indicator_period": period(reason="not an indicator dataset"),
            "complete_label_period": period(reason="economic rights, fills and historical universe remain incomplete"),
        },
        "status": "partial",
        "limitations": [
            "TWSE pre-pipeline delistings absent; historical membership/security type unverified",
            "current source vintage is not historical publication evidence",
            "cash dividends estimated; payment-date and fill assumptions; rights/reductions unresolved",
            "early capital-reduction coverage incomplete; strict complete-quote ranking excludes suspensions/new listings",
        ],
        "backup": {"status": "unknown", "scope": "existing stock-research backup includes research_data; no new backup run"},
    }


def prepare(params: dict[str, Any], output: Path) -> dict[str, Any]:
    source = REPO / "stock-data-downloader/data"
    receipt_path = next((REPO / ".tmp").glob("worktree-seed-*/receipt.json"))
    receipt = read_json(receipt_path)
    if receipt["source_alignment_required"]:
        raise ValueError("input snapshot source alignment unresolved")
    names = ["price_daily.parquet", "corporate_actions.sqlite", "symbol_meta.sqlite"]
    records = {row["path"]: row for row in receipt["files"] if row["path"] in names}
    if set(records) != set(names):
        raise ValueError("consumed inputs missing seeder provenance")
    verify_files(source, list(records.values()))
    dates = pd.read_parquet(source / names[0], columns=["Date"]).Date
    pins = {name: records[name]["sha256"] for name in names}
    payloads = {name: (source / name).read_bytes() for name in names}
    payloads["seed-provenance.json"] = canonical({"receipt_sha256": file_digest(receipt_path), "source_alignment_required": False, "files": records})
    verify_files(source, list(records.values()))
    entry = publish_bundle(catalog(), metadata("annual-rotation-inputs", "prices", pins, params, str(dates.min().date()), str(dates.max().date())), payloads)
    write_json(output, entry)
    return entry


def load_inputs(pin: Path) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    entry = read_json(pin)
    cat = catalog()
    registered = cat.get(entry["data_id"], entry["version_id"], manifest_sha256=entry["manifest"]["sha256"])
    if entry != registered:
        raise ValueError("input registration differs from pinned entry")
    root = cat.roots.artifact_path(entry["manifest"]["scope"], entry["manifest"]["path"]).parent
    prices = pd.read_parquet(root / "price_daily.parquet", columns=["Code", "Date", "Open", "High", "Low", "Close", "Volume", "Source"])
    prices["Code"] = prices.Code.astype(str)
    prices["Date"] = pd.to_datetime(prices.Date)
    with sqlite3.connect((root / "corporate_actions.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True) as con:
        actions = pd.read_sql_query("SELECT code,ex_date,event_type,price_factor,cash_dividend_estimate,evidence_status,market FROM corporate_actions", con)
    actions["ex_date"] = pd.to_datetime(actions.ex_date)
    with sqlite3.connect((root / "symbol_meta.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True) as con:
        types = pd.read_sql_query("SELECT code,name,market,is_etf,cfi_code,listed_date,fetched_at FROM symbol_meta", con)
    calendar_days = pd.DatetimeIndex(sorted(prices.loc[prices.Source.eq("official"), "Date"].unique()))
    return entry, prices, actions, types, calendar_days


def scope(prices: pd.DataFrame, types: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    historical = sorted(prices.Code.unique())
    type_map = types.set_index("code").to_dict("index")
    included, exclusions, unknown = [], {}, []
    for code in historical:
        if not re.fullmatch(r"[1-9][0-9]{3}", code) or code.startswith("91"):
            exclusions[code] = "nonordinary_code_or_depositary_receipt"
            continue
        current = type_map.get(code)
        if current and (current["is_etf"] or not str(current["cfi_code"]).startswith("ES")):
            exclusions[code] = "current_security_type_nonordinary"
            continue
        if not current:
            unknown.append(code)
        included.append(code)
    return prices.loc[prices.Source.eq("official") & prices.Code.isin(included)], {
        "historical_codes": len(historical),
        "code_rule_scope": len(included),
        "current_type_unknown": unknown,
        "excluded": exclusions,
        "historical_venue_membership": "unknown; official quote occurrence only",
        "metadata_use": "current security type assumption, not present-day membership filter; historic reclassifications unverified",
    }


def source_identity(params_path: Path) -> dict[str, Any]:
    names = [
        "research_core/annual_rotation.py",
        "research_core/annual_statistics.py",
        "research_core/annual_ranking_pool.py",
        "research_core/price_basis.py",
        "research_core/artifact_store.py",
        "research_core/research_data_builder.py",
        "research_core/research_data_catalog.py",
        "research_core/research_data_paths.py",
        "research_core/research_measurement_v1.py",
        "StockProject/engine/data_loader.py",
        "uv.lock",
        "pyproject.toml",
    ]
    paths = [REPO / name for name in names] + [Path(__file__), TASK / "mission.md", params_path]
    return {
        "files": {path.relative_to(REPO).as_posix(): file_digest(path) for path in paths},
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "pyarrow": pyarrow.__version__,
            "platform": platform.platform(),
        },
    }


def measure(params: dict[str, Any], inputs: tuple, output: Path) -> dict[str, Any]:
    input_entry, prices, actions, types, calendar_days = inputs
    kernel_names = ["research_core/annual_rotation.py", "research_core/annual_ranking_pool.py", "research_core/price_basis.py"]
    kernel_pins = {name: file_digest(REPO / name) for name in kernel_names}
    selected, _ = scope(prices, types)
    codes = sorted(selected.Code.unique())
    sample = [codes[int(index)] for index in np.linspace(0, len(codes) - 1, min(20, len(codes)))]
    serial = rank_panel(selected, actions, calendar_days, params["ranking_years"], workers=1, codes=sample)
    parallel = rank_panel(selected, actions, calendar_days, params["ranking_years"], workers=2, codes=sample)
    if object_digest(serial["rows"]) != object_digest(parallel["rows"]):
        raise ValueError("serial/parallel ranking differs")
    if {name: file_digest(REPO / name) for name in kernel_names} != kernel_pins:
        raise ValueError("ranking source changed during measurement")
    s, p = serial["performance"], parallel["performance"]
    chosen = 2 if p["parent_total"]["wall_seconds"] < s["parent_total"]["wall_seconds"] else 1
    result = {
        "schema": "annual-ranking-measurement.v1",
        "sample_codes": sample,
        "serial": s,
        "parallel": p,
        "same_rows_sha256": object_digest(serial["rows"]),
        "selected_workers": chosen,
        "estimate_full_wall_seconds": min(s["parent_total"]["wall_seconds"], p["parent_total"]["wall_seconds"]) * len(codes) / len(sample),
        "estimate_scope": "linear stock-count extrapolation; year coverage differs; not a deadline",
        "memory_budget_bytes": params["memory_observation_budget_bytes"],
        "model_tokens": None,
        "kernel_sha256": kernel_pins,
        "input_version_id": input_entry["version_id"],
        "parameters_sha256": object_digest(params),
    }
    write_json(output, result)
    return result


def holding(
    raw: pd.DataFrame, actions: pd.DataFrame, days: pd.DatetimeIndex, year: int, params: dict[str, Any], *, avoid: bool, benchmark: bool = False
) -> dict[str, Any]:
    scheduled = cast(pd.Timestamp, days[np.array([cast(pd.Timestamp, day).year for day in days]) == year][0])
    entry = first_observed_trade(raw, days, on_or_after=scheduled, avoid_one_price=avoid)
    is_ytd = year > params["complete_through_year"]
    future = days[days >= pd.Timestamp(f"{year + 1}-01-01")]
    exit_day = (
        cast(pd.Timestamp, days[-1])
        if is_ytd
        else first_observed_trade(raw, days, on_or_after=cast(pd.Timestamp, future[0]), avoid_one_price=avoid)
        if len(future)
        else None
    )
    info: dict[str, Any] = {
        "code": str(raw.Code.iloc[0]),
        "year": year,
        "scheduled_entry": str(scheduled.date()),
        "entry_date": None if entry is None else str(entry.date()),
        "exit_date": None if exit_day is None else str(exit_day.date()),
        "is_ytd": is_ytd,
        "exit_kind": "mark_close_liquidation_scenario" if is_ytd else "observed_open_scenario",
    }
    if entry is None or exit_day is None or entry >= exit_day or entry.year != year:
        return {**info, "status": "unknown", "reasons": ["missing_or_unordered_execution_endpoints"], "gross_multiplier": None, "net_multiplier": None}
    result = economic_path(
        raw,
        actions,
        days,
        start=entry,
        end=exit_day,
        end_field="Close" if is_ytd else "Open",
        commission=params["commission"],
        sell_tax=params["etf_sell_tax"] if benchmark else params["stock_sell_tax"],
        slippage=params["slippage"],
        split_ratios=params["exact_benchmark_splits"] if benchmark else {},
        known_halts=set(params["known_benchmark_halts"]) if benchmark else set(),
    )
    # Preserve observed raw endpoint prices even when intermediate economics fail.
    result["raw_entry"] = float(raw.loc[raw.Date.eq(entry), "Open"].iloc[0])
    result["raw_exit"] = float(raw.loc[raw.Date.eq(exit_day), "Close" if is_ytd else "Open"].iloc[0])
    return {**info, **result}


def summary_window(years: list[dict[str, Any]], start_year: int, params: dict[str, Any]) -> dict[str, Any]:
    selected = [row for row in years if start_year <= row["year"] <= params["complete_through_year"]]
    expected = params["complete_through_year"] - start_year + 1
    complete = len(selected) == expected and all(
        row["gross_multiplier"] is not None and row["benchmark_gross"] is not None and row["on_schedule"] for row in selected
    )
    result: dict[str, Any] = {
        "start_year": start_year,
        "end_year": params["complete_through_year"],
        "expected_years": expected,
        "known_holding_years": sum(row["gross_multiplier"] is not None for row in selected),
        "complete": complete,
        "net_terminal_multiple": None,
        "benchmark_net_terminal_multiple": None,
        "statistics": None,
        "full_market_certified": False,
        "unavailable_reason": None if complete else "unresolved holding/benchmark or delayed rotation; no cherry-picked compound curve",
    }
    if complete:
        strategy = [row["net_multiplier"] for row in selected]
        bench = [row["benchmark_dividend_net_no_boundary_costs"] for row in selected]
        # Continuous benchmark pays initial and terminal fees/slippage once.
        bench[0] /= (1 + params["slippage"]) * (1 + params["commission"])
        bench[-1] *= (1 - params["slippage"]) * (1 - params["commission"] - params["etf_sell_tax"])
        result.update(
            net_terminal_multiple=float(np.prod(strategy)),
            gross_terminal_multiple=float(np.prod([row["gross_multiplier"] for row in selected])),
            benchmark_net_terminal_multiple=float(np.prod(bench)),
            statistics=summarize_annual_excess(strategy, bench, seed=params["seed"], resamples=params["bootstrap_resamples"]),
            net_cagr=float(np.prod(strategy) ** (1 / expected) - 1),
            worst_net_year=min(strategy) - 1,
        )
        curve = [1.0]
        for row in selected:
            base = curve[-1]
            curve.extend([base * value for value in row["combined_net_marks"]])
        result["daily_marked_max_drawdown"] = equity_drawdown(curve)
    return result


def run(params: dict[str, Any], inputs: tuple, measurement: dict[str, Any], output: Path, source: dict[str, Any]) -> dict[str, Any]:
    entry, prices, actions, types, days = inputs
    if measurement["input_version_id"] != entry["version_id"] or measurement["parameters_sha256"] != object_digest(params):
        raise ValueError("measurement used different inputs or settings")
    if any(file_digest(REPO / name) != digest for name, digest in measurement["kernel_sha256"].items()):
        raise ValueError("measurement used different ranking implementation")
    selected, scope_report = scope(prices, types)
    panel = rank_panel(selected, actions, days, params["ranking_years"], workers=measurement["selected_workers"])
    rows = panel["rows"]
    held_codes = {leader["code"] for year in params["ranking_years"] for leader in select_leaders([row for row in rows if row["year"] == year], count=5)}
    groups = {code: selected.loc[selected.Code.eq(code)] for code in sorted(held_codes)}
    action_groups = {code: frame for code, frame in actions.groupby("code", sort=True)}
    empty_actions = actions.iloc[:0]
    braw = prices.loc[prices.Code.eq(params["benchmark"])]
    bactions = action_groups.get(params["benchmark"], empty_actions)
    bpaths = {year: holding(braw, bactions, days, year, params, avoid=False, benchmark=True) for year in params["trade_years"]}
    annual_scope = []
    for year in params["ranking_years"]:
        candidates = [row for row in rows if row["year"] == year]
        eligible = [row for row in candidates if row["ranking_status"] != "ineligible"]
        known = [row for row in eligible if row["ranking_gross_return"] is not None]
        ref = [row for row in candidates if row["reference_factor_return_diagnostic"] is not None]
        reference_leader = max(ref, key=lambda row: (row["reference_factor_return_diagnostic"], -int(row["code"]))) if ref else None
        annual_scope.append({
            "year": year,
            "observed_stock_years": len(candidates),
            "observed_candidates": len(eligible),
            "ineligible_anchor_count": len(candidates) - len(eligible),
            "known_rank_candidates": len(known),
            "unknown_rank_candidates": len(eligible) - len(known),
            "unknown_reason_counts": dict(Counter(reason.split(":", 1)[-1] for row in candidates for reason in row["ranking_reasons"])),
            "reference_leader_diagnostic": None
            if reference_leader is None
            else {key: reference_leader[key] for key in ("code", "reference_factor_return_diagnostic", "ranking_status", "ranking_reasons")},
        })
    arm_results, details = {}, {}
    for arm in params["arms"]:
        annual = []
        for year in params["trade_years"]:
            candidates = [row for row in rows if row["year"] == year - 1]
            leaders = select_leaders(candidates, count=arm["count"])
            legs = [
                holding(groups[leader["code"]], action_groups.get(leader["code"], empty_actions), days, year, params, avoid=arm["avoid_one_price"])
                for leader in leaders
            ]
            paired = [
                paired_benchmark_path(
                    braw,
                    bactions,
                    days,
                    leg,
                    commission=params["commission"],
                    split_ratios=params["exact_benchmark_splits"],
                    known_halts=set(params["known_benchmark_halts"]),
                    entry_cost=False,
                    exit_cost=False,
                )
                for leg in legs
            ]
            paired_net = [
                paired_benchmark_path(
                    braw,
                    bactions,
                    days,
                    leg,
                    commission=params["commission"],
                    sell_tax=params["etf_sell_tax"],
                    slippage=params["slippage"],
                    split_ratios=params["exact_benchmark_splits"],
                    known_halts=set(params["known_benchmark_halts"]),
                )
                for leg in legs
            ]
            details[f"{arm['id']}/{year}"] = {
                "leaders": leaders,
                "legs": legs,
                "benchmark": bpaths[year],
                "paired_benchmarks": paired,
                "paired_benchmark_roundtrip": paired_net,
            }
            good = len(legs) == arm["count"] and all(leg["gross_multiplier"] is not None for leg in legs)
            bpath = bpaths[year]
            on_schedule = good and all(
                leg["entry_date"] == leg["scheduled_entry"] == bpath["entry_date"] and (leg["is_ytd"] or leg["exit_date"] == bpath["exit_date"]) for leg in legs
            )
            paired_known = len(paired) == arm["count"] and all(item["gross_multiplier"] is not None for item in paired)
            row = {
                "year": year,
                "is_ytd": year > params["complete_through_year"],
                "codes": [leader["code"] for leader in leaders],
                "ranking_returns": [leader["ranking_gross_return"] for leader in leaders],
                "entry_dates": [leg["entry_date"] for leg in legs],
                "exit_dates": [leg["exit_date"] for leg in legs],
                "gross_multiplier": float(np.mean([leg["gross_multiplier"] for leg in legs])) if good else None,
                "net_multiplier": float(np.mean([leg["net_multiplier"] for leg in legs])) if good else None,
                "benchmark_gross": float(np.mean([item["gross_multiplier"] for item in paired])) if paired_known else None,
                "benchmark_net_roundtrip": float(np.mean([item["net_multiplier"] for item in paired_net])) if paired_known else None,
                "benchmark_dividend_net_no_boundary_costs": float(np.mean([item["net_multiplier"] for item in paired])) if paired_known else None,
                "on_schedule": on_schedule,
                "reasons": [reason for leg in legs for reason in leg["reasons"]],
                "combined_net_marks": [],
            }
            if good and on_schedule:
                date_sets = [{mark["date"] for mark in leg["marks"]} for leg in legs]
                if all(dates == date_sets[0] for dates in date_sets):
                    row["combined_net_marks"] = np.mean([[mark["net"] for mark in leg["marks"]] for leg in legs], axis=0).tolist()
                else:
                    row["on_schedule"] = False
            annual.append(row)
        arm_results[arm["id"]] = {"years": annual, "windows": [summary_window(annual, year, params) for year in (2011, 2012, 2013)]}
    continuous_benchmarks = []
    for start_year in (2011, 2012, 2013):
        begin, finish = bpaths[start_year]["entry_date"], bpaths[params["complete_through_year"]]["exit_date"]
        model = paired_benchmark_path(
            braw,
            bactions,
            days,
            {"entry_date": begin, "exit_date": finish, "is_ytd": False},
            commission=params["commission"],
            sell_tax=params["etf_sell_tax"],
            slippage=params["slippage"],
            split_ratios=params["exact_benchmark_splits"],
            known_halts=set(params["known_benchmark_halts"]),
        )
        details[f"continuous-benchmark/{start_year}"] = model
        continuous_benchmarks.append({
            "start_year": start_year,
            "entry_date": begin,
            "exit_date": finish,
            **{key: model[key] for key in ("status", "reasons", "gross_multiplier", "net_multiplier")},
            "daily_marked_max_drawdown": equity_drawdown([1.0] + [mark["net"] for mark in model["marks"]]) if model["net_multiplier"] is not None else None,
        })
    public = {
        "schema": "annual-rotation-results.v1",
        "verdict": "insufficient_evidence_for_unbiased_full_market_significant_outperformance",
        "input_entry": entry,
        "source": source,
        "scope": scope_report,
        "annual_scope": annual_scope,
        "arms": arm_results,
        "continuous_benchmarks": continuous_benchmarks,
        "measurement": {key: measurement[key] for key in ("sample_codes", "selected_workers", "estimate_full_wall_seconds", "memory_budget_bytes")},
        "execution": {key: value for key, value in panel["performance"].items() if key != "worker_receipts"},
    }
    # The public summary omits quote vectors and detailed daily equity; shared bundle retains them.
    for arm in public["arms"].values():
        for year in arm["years"]:
            year.pop("combined_net_marks")

    def encode(value: Any) -> bytes:
        return gzip.compress(canonical(value), mtime=0)

    payloads = {
        "candidates.json.gz": encode(rows),
        "holding-paths.json.gz": encode(details),
        "results.json": canonical(public),
        "measurement.json": canonical(measurement),
        "execution.json": canonical(panel["performance"]),
        "study.json": canonical(params),
    }
    for name in source["files"]:
        payloads[f"implementation/{name}"] = (REPO / name).read_bytes()
    if source_identity(TASK / "params/study-v1.json") != source:
        raise ValueError("executed source changed; publication stopped")
    result_entry = publish_bundle(
        catalog(),
        metadata(
            "annual-rotation-process",
            "episodes",
            {"input_version": entry["version_id"], "input_manifest_sha256": entry["manifest"]["sha256"], "source": source},
            params,
            str(days[0].date()),
            str(days[-1].date()),
        ),
        payloads,
        lineage={"input_entry": entry},
    )
    result = {**public, "process_entry": result_entry}
    write_json(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "measure", "run", "verify"])
    parser.add_argument("--input-pin", type=Path, default=TASK / "params/input-pin-v1.json")
    parser.add_argument("--measurement", type=Path, default=TASK / "params/measurement-v2.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    params_path = TASK / "params/study-v1.json"
    params = read_json(params_path)
    source = source_identity(params_path)
    before = resource_sample()
    if args.mode == "prepare":
        result = prepare(params, args.output)
    elif args.mode == "verify":
        result = read_json(args.output)
        verify_entry(result["input_entry"], catalog().roots)
        verify_entry(result["process_entry"], catalog().roots)
        result = {"verified_input_version": result["input_entry"]["version_id"], "verified_process_version": result["process_entry"]["version_id"]}
    else:
        inputs = load_inputs(args.input_pin)
        result = measure(params, inputs, args.output) if args.mode == "measure" else run(params, inputs, read_json(args.measurement), args.output, source)
    LOGGER.info("Completed mode=%s receipt=%s", args.mode, phase_receipt(args.mode, before, resource_sample()))
    print(
        json.dumps(
            {"mode": args.mode, "output": str(args.output), "version_id": result.get("version_id", result.get("process_entry", {}).get("version_id"))},
            ensure_ascii=True,
        )
    )  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
