"""Complete a previously published fixed annual sequence on current input data.

The engine never ranks stocks or chooses replacement issuers. Its publication
contains compact results and an input fingerprint, without price copies or daily
mark vectors. Source admission is owned by ``annual_completion_evidence``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import math
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from research_core.annual_completion_publication import ARCHIVE, pack_publication
from research_core.annual_rotation import economic_path
from research_core.annual_rotation_v2 import Entitlement, economic_path_v2
from research_core.annual_statistics import equity_drawdown, summarize_annual_excess
from research_core.artifact_store import canonical, read_json, safe_path, write_json
from research_core.live_producer import read_stable, readonly_sqlite
from research_core.producer_data import REPO_ROOT, producer_data_root
from research_core.research_measurement_v1 import phase_receipt, resource_sample
from research_core.run_receipt import InputSpec, code_identity, fingerprint_inputs, write_run_receipt

LOGGER = logging.getLogger(__name__)
SCHEMA = "annual-completion-result.v2"
STUDY_ID = "20261013-annual-winner-rotation"
DEFINITION = "annual-holding-completion.v2"
TASK = REPO_ROOT / "tasks" / STUDY_ID
OUTPUT_NAMES = ("results.json", "admission-audit.json", "performance.json", "run-receipt.json")


class Admission(Protocol):
    """The evidence adapter's already verified, source-admitted observations."""

    entitlements: tuple[Entitlement, ...]
    unavailable_by_code: dict[str, dict[str, str]]
    audit: list[dict[str, Any]]
    unresolved: list[dict[str, Any]]


def _date_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("fixed dates must be ISO strings or null")
    return value


def _daily_date(value: object) -> pd.Timestamp:
    text = _date_string(value)
    if text is None:
        raise ValueError("daily date required")
    parsed = dt.date.fromisoformat(text)
    if parsed.isoformat() != text:
        raise ValueError("ISO daily date required")
    result = pd.Timestamp(parsed)
    if not isinstance(result, pd.Timestamp):
        raise ValueError("daily date must not be NaT")
    return result


def _unknown(reasons: Sequence[str]) -> dict[str, Any]:
    return {
        "status": "unknown",
        "gross_multiplier": None,
        "net_multiplier": None,
        "reasons": list(reasons),
        "marks": [],
        "complete_equity": False,
        "carried_days": 0,
    }


def _unresolved_applies(event: dict[str, Any], start: pd.Timestamp | None, end: pd.Timestamp | None) -> bool:
    """Associate an economic uncertainty with held dates, never its label year."""
    supplied = event.get("event_dates")
    if not isinstance(supplied, list) or not supplied or start is None or end is None:
        return True
    dates: list[pd.Timestamp] = []
    for value in supplied:
        try:
            dates.append(_daily_date(value))
        except (TypeError, ValueError):
            continue
    return not dates or any(start < date <= end for date in dates)


def _compact(path: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": path["status"],
        "gross_return": None if path["gross_multiplier"] is None else path["gross_multiplier"] - 1,
        "net_return": None if path["net_multiplier"] is None else path["net_multiplier"] - 1,
        "carried_days": path.get("carried_days", 0),
        "complete_equity": path.get("complete_equity", False),
        "reasons": path["reasons"],
    }


def _endpoint_volume_reasons(raw: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    """Require observable trades on the fixed dates; never seek a replacement."""
    if "Volume" not in raw.columns:
        return ["missing_endpoint_volume_column"]
    reasons = []
    for label, day in (("entry", start), ("exit", end)):
        observations = raw.loc[raw.Date.eq(day), "Volume"]
        valid = False
        if len(observations) == 1 and not pd.api.types.is_bool_dtype(observations.dtype):
            value = observations.iloc[0]
            if not isinstance(value, bool):
                try:
                    volume = float(value)
                    valid = math.isfinite(volume) and volume > 0
                except (TypeError, ValueError, OverflowError):
                    pass
        if not valid:
            reasons.append(f"{day.date()}:invalid_{label}_endpoint_volume")
    return reasons


def _policy(parameters: dict[str, Any], *, benchmark: bool = False) -> dict[str, Any]:
    return {
        "commission": parameters["commission"],
        "sell_tax": parameters["etf_sell_tax"] if benchmark else parameters["stock_sell_tax"],
        "slippage": parameters["slippage"],
        "split_ratios": parameters.get("exact_benchmark_splits", {"2025-06-18": 4.0}) if benchmark else {},
        "known_halts": set(parameters.get("known_benchmark_halts", ["2025-06-11", "2025-06-12", "2025-06-13", "2025-06-16", "2025-06-17"]))
        if benchmark
        else set(),
    }


def _chained_marks(paths: list[dict[str, Any]]) -> list[float]:
    """Replace a rotation's exit-open mark with the new holding's close mark."""
    by_date: dict[str, float] = {}
    scale = 1.0
    for path in paths:
        for mark in path["marks"]:
            by_date[mark["date"]] = scale * mark["net"]
        scale *= path["net_multiplier"]
    return [1.0, *[value for _, value in sorted(by_date.items())]]


def _window_scenario(
    selections: list[dict[str, Any]], paths: list[dict[str, Any]], benchmarks: list[dict[str, Any]], *, expected_years: list[int], parameters: dict[str, Any]
) -> dict[str, Any]:
    reason = None
    if [row["year"] for row in selections] != expected_years:
        reason = "missing_fixed_holding_year"
    elif any(path["status"] != "modeled" for path in paths):
        reason = "unresolved_fixed_holding"
    elif any(left["exit_date"] != right["entry_date"] for left, right in zip(selections, selections[1:])):
        reason = "nonadjacent_rotation_dates"
    result: dict[str, Any] = {
        "complete": reason is None,
        "gross_terminal_multiple": None,
        "net_terminal_multiple": None,
        "cagr": None,
        "complete_equity": False,
        "max_drawdown": None,
        "carried_mark_reference_drawdown": None,
        "paired_diagnostics": None,
        "reason": reason,
    }
    if reason is not None:
        return result
    duration = (_daily_date(selections[-1]["exit_date"]) - _daily_date(selections[0]["entry_date"])).days
    gross = math.prod(path["gross_multiplier"] for path in paths)
    net = math.prod(path["net_multiplier"] for path in paths)
    complete_equity = all(path["complete_equity"] for path in paths)
    drawdown = equity_drawdown(_chained_marks(paths))
    result.update(
        gross_terminal_multiple=gross,
        net_terminal_multiple=net,
        cagr=net ** (365.2425 / duration) - 1,
        complete_equity=complete_equity,
        max_drawdown=drawdown if complete_equity else None,
        carried_mark_reference_drawdown=drawdown if not complete_equity else None,
    )
    if len(paths) >= 2 and all(path["status"] == "modeled" for path in benchmarks):
        result["paired_diagnostics"] = summarize_annual_excess(
            [path["net_multiplier"] for path in paths],
            [path["net_multiplier"] for path in benchmarks],
            seed=parameters.get("seed", 20261013),
            resamples=parameters.get("bootstrap_resamples", 20_000),
        )
    return result


def complete_fixed_sequence(
    prices: pd.DataFrame, actions: pd.DataFrame, calendar: pd.DatetimeIndex, selections: list[dict[str, Any]], admission: Admission, parameters: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate original codes and dates, keeping unknown years and v1 values."""
    selected = sorted(selections, key=lambda row: row["year"])
    if not selected or len({row["year"] for row in selected}) != len(selected):
        raise ValueError("nonempty selections with unique holding years required")
    cutoff = _daily_date(parameters.get("cutoff", "2026-10-12"))
    calendar = calendar[calendar <= cutoff]
    codes = {str(row["code"]) for row in selected} | {"0050"}
    by_code = {code: prices.loc[prices.Code.astype(str).eq(code) & prices.Date.le(cutoff)] for code in codes}
    counts = {"strategy_v2_calls": 0, "benchmark_calls": 0, "v1_comparison_calls": 0, "scenario_reuses": 0, "full_ranking_calls": 0}
    benchmark_cache: dict[tuple[str, str, bool], dict[str, Any]] = {}
    full_paths: dict[int, dict[str, dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    compatibility: list[dict[str, Any]] = []

    def benchmark(start: str | None, end: str | None, is_ytd: bool) -> dict[str, Any]:
        if start is None or end is None:
            return _unknown(["missing_or_unordered_fixed_endpoints"])
        start_day, end_day = _daily_date(start), _daily_date(end)
        if start_day not in calendar or end_day not in calendar or start_day >= end_day:
            return _unknown(["missing_or_unordered_fixed_endpoints"])
        key = (start, end, is_ytd)
        if key not in benchmark_cache:
            raw = by_code["0050"]
            if raw.empty:
                benchmark_cache[key] = _unknown(["missing_benchmark_history"])
            elif volume_reasons := _endpoint_volume_reasons(raw, start_day, end_day):
                benchmark_cache[key] = _unknown(volume_reasons)
            else:
                counts["benchmark_calls"] += 1
                benchmark_cache[key] = economic_path_v2(
                    raw,
                    actions,
                    calendar,
                    start=start_day,
                    end=end_day,
                    end_field="Close" if is_ytd else "Open",
                    **_policy(parameters, benchmark=True),
                )
        return benchmark_cache[key]

    for selection in selected:
        code, year = str(selection["code"]), selection["year"]
        start, end = _date_string(selection["entry_date"]), _date_string(selection["exit_date"])
        start_day = None if start is None else _daily_date(start)
        end_day = None if end is None else _daily_date(end)
        reasons = [
            reason for row in admission.unresolved if str(row["code"]) == code and _unresolved_applies(row, start_day, end_day) for reason in row["reasons"]
        ]
        if start_day is None or end_day is None or start_day not in calendar or end_day not in calendar or start_day >= end_day:
            reasons.append("missing_or_unordered_fixed_endpoints")
        if by_code[code].empty:
            reasons.append("missing_fixed_issuer_history")
        elif start_day is not None and end_day is not None:
            reasons.extend(_endpoint_volume_reasons(by_code[code], start_day, end_day))
        if reasons:
            lapse = realize = _unknown(reasons)
        else:
            assert start_day is not None and end_day is not None
            policy = {
                "start": start_day,
                "end": end_day,
                "end_field": "Close" if selection["is_ytd"] else "Open",
                "entitlements": admission.entitlements,
                "unavailable_days": admission.unavailable_by_code.get(code, {}),
                **_policy(parameters),
            }
            counts["strategy_v2_calls"] += 1
            lapse = economic_path_v2(by_code[code], actions, calendar, rights_scenario="lapse", **policy)
            active_rights = any(
                item.code == code and start_day < _daily_date(item.effective_date) <= end_day and item.rights_per_old_share > 0
                for item in admission.entitlements
            )
            if active_rights:
                counts["strategy_v2_calls"] += 1
                realize = economic_path_v2(by_code[code], actions, calendar, rights_scenario="realize", **policy)
            else:
                realize = lapse
                counts["scenario_reuses"] += 1
        paired = benchmark(start, end, selection["is_ytd"])
        full_paths[year] = {"lapse": lapse, "realize": realize, "benchmark": paired}
        rows.append({
            **{key: selection[key] for key in ("year", "code", "ranking_return", "entry_date", "exit_date", "is_ytd")},
            "v1": {"gross_return": selection.get("v1_gross_return"), "net_return": selection.get("v1_net_return")},
            "lapse": _compact(lapse),
            "realize": _compact(realize),
            "benchmark": _compact(paired),
        })
        if not selection["is_ytd"] and selection.get("v1_net_return") is not None and not reasons and start_day is not None and end_day is not None:
            counts["v1_comparison_calls"] += 1
            previous = economic_path(by_code[code], actions, calendar, start=start_day, end=end_day, **_policy(parameters))
            differences = [
                abs(previous[key] - lapse[key]) for key in ("gross_multiplier", "net_multiplier") if previous[key] is not None and lapse[key] is not None
            ]
            compatibility.append({
                "year": year,
                "code": code,
                "current_v1": _compact(previous),
                "current_v2": _compact(lapse),
                "common_multipliers_match": max(differences) <= 1e-12 if len(differences) == 2 else None,
                "max_absolute_difference": max(differences) if differences else None,
                "comparison_scope": "same current inputs; original rounded report values remain in rows.v1",
            })
    windows = []
    end_year = parameters.get("complete_through_year", 2025)
    for start_year in parameters.get("window_start_years", [2011, 2012, 2013]):
        period = [row for row in selected if start_year <= row["year"] <= end_year and not row["is_ytd"]]
        expected = list(range(start_year, end_year + 1))
        start_date = _date_string(period[0]["entry_date"]) if period and period[0]["year"] == start_year else None
        end_date = _date_string(period[-1]["exit_date"]) if period and period[-1]["year"] == end_year else None
        continuous = benchmark(start_date, end_date, False)
        duration = None if start_date is None or end_date is None else (_daily_date(end_date) - _daily_date(start_date)).days
        scenarios = {
            "lapse": _window_scenario(
                period,
                [full_paths[row["year"]]["lapse"] for row in period],
                [full_paths[row["year"]]["benchmark"] for row in period],
                expected_years=expected,
                parameters=parameters,
            )
        }
        scenarios["realize"] = (
            scenarios["lapse"]
            if all(full_paths[row["year"]]["lapse"] is full_paths[row["year"]]["realize"] for row in period)
            else _window_scenario(
                period,
                [full_paths[row["year"]]["realize"] for row in period],
                [full_paths[row["year"]]["benchmark"] for row in period],
                expected_years=expected,
                parameters=parameters,
            )
        )
        windows.append({
            "id": f"{start_year}-{end_year}",
            "start_year": start_year,
            "end_year": end_year,
            "start_date": start_date,
            "end_date": end_date,
            "scenarios": scenarios,
            "benchmark": {
                "status": continuous["status"],
                "gross_terminal_multiple": continuous["gross_multiplier"],
                "net_terminal_multiple": continuous["net_multiplier"],
                "cagr": None if continuous["net_multiplier"] is None or duration is None else continuous["net_multiplier"] ** (365.2425 / duration) - 1,
                "reasons": continuous["reasons"],
                "complete_equity": continuous.get("complete_equity", False),
            },
        })
    counts["kernel_calls"] = counts["strategy_v2_calls"] + counts["benchmark_calls"] + counts["v1_comparison_calls"]
    return {
        "schema": SCHEMA,
        "study_id": parameters.get("study_id", STUDY_ID),
        "run_id": parameters["run_id"],
        "definition": parameters.get("definition_version", DEFINITION),
        "cutoff": str(cutoff.date()),
        "selection_scope": parameters.get(
            "selection_scope", "original v1 calculable leaders, fixed codes and dates; not a reranking or full-market champion claim"
        ),
        "rows": rows,
        "windows": windows,
        "compatibility": compatibility,
        "limitations": [
            "Fixed v1 calculable leaders are reused; historical universe and unknown ranking candidates are not reconstructed.",
            "Current input vintage and original rounded report values are distinct observations.",
            "Cash dividends use the original immediate ex-date close fractional reinvestment estimate.",
            "Rights lapse and realize are stated scenarios, not actual exercise or return bounds.",
            "Carried marks permit terminal modeling only; actual complete daily drawdown remains unknown.",
            "Paired diagnostics assume symmetric exchangeable log excesses and iid bootstrap years; they do not certify significance or unseen data.",
        ],
        "execution": counts,
    }


def parse_fixed_selections(text: str) -> list[dict[str, Any]]:
    """Read the original public result table without importing a task runner."""
    if "## 固定單一領先股結果" not in text:
        raise ValueError("original fixed-leader result section missing")
    section = text.split("## 固定單一領先股結果", 1)[1].split("\n## ", 1)[0]
    selected = []
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 8 or re.fullmatch(r"\d{4}(?: YTD)?", cells[0]) is None:
            continue
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", cells[3])
        if re.fullmatch(r"\d{4}", cells[1]) is None or len(dates) != 2:
            raise ValueError("malformed original fixed-leader row")

        def percent(value: str) -> float | None:
            return float(value.removesuffix("%").replace(",", "")) / 100 if value.endswith("%") else None

        selected.append({
            "year": int(cells[0][:4]),
            "code": cells[1],
            "ranking_return": percent(cells[2]),
            "entry_date": dates[0],
            "exit_date": dates[1],
            "is_ytd": "YTD" in cells[0],
            "v1_gross_return": percent(cells[4]),
            "v1_net_return": percent(cells[5]),
        })
    if not selected or len({row["year"] for row in selected}) != len(selected):
        raise ValueError("original fixed-leader table must have unique holding years")
    return selected


def _require_code_identity(repo: Path, expected: dict[str, Any]) -> None:
    current = code_identity(repo)
    if current.get("dirty") is not False or current != expected:
        raise ValueError("run source identity changed; require the starting commit and a clean tracked tree")


def _require_committed_sources(repo: Path, paths: Sequence[Path]) -> dict[str, Any]:
    identity = dict(code_identity(repo))
    if identity["dirty"]:
        raise ValueError("commit the run's source and parameters before real-data execution")
    for path in paths:
        relative = path.resolve().relative_to(repo.resolve()).as_posix()
        result = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{identity['commit']}:{relative}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise ValueError(f"run source is not committed: {relative}")
    _require_code_identity(repo, identity)
    return identity


def _format_outputs(paths: Sequence[Path], repo: Path) -> float:
    started = time.perf_counter()
    command = [sys.executable, "-m", "pre_commit", "run", "prettier", "--files", *[str(path) for path in paths]]
    first = subprocess.run(command, cwd=repo, capture_output=True, text=True, check=False)
    if first.returncode and "files were modified by this hook" not in first.stdout + first.stderr:
        raise RuntimeError(f"output formatter failed: {first.stdout}\n{first.stderr}")
    second = subprocess.run(command, cwd=repo, capture_output=True, text=True, check=False)
    if second.returncode:
        raise RuntimeError(f"output formatter is not stable: {second.stdout}\n{second.stderr}")
    return time.perf_counter() - started


def _sample() -> dict[str, Any]:
    try:
        return resource_sample()
    except ImportError:
        return {"wall": time.perf_counter(), "cpu": time.process_time(), "native": None}


def main(argv: Sequence[str] | None = None) -> int:
    """Fingerprint once, load only fixed issuers, and publish compact fresh files."""
    from research_core.annual_completion_evidence import build_admission, load_verified_evidence

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params", type=Path, default=TASK / "params/completion-v2.json")
    parser.add_argument("--report", type=Path, default=TASK / "report.md")
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--output", type=Path, default=TASK / "publications/completion-v2")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    output = safe_path(args.output)
    if any((output / name).exists() or (output / name).is_symlink() for name in (*OUTPUT_NAMES, ARCHIVE)):
        raise FileExistsError("publication result filenames already exist; choose a fresh --output directory")
    repo = safe_path(REPO_ROOT)
    if output == repo or not output.is_relative_to(repo):
        raise ValueError("publication output must be a directory inside the repository")
    report = safe_path(args.report)
    if report.resolve() != safe_path(TASK / "report.md").resolve():
        raise ValueError("fixed PR15 selections require the canonical task report.md")
    starting_identity = _require_committed_sources(
        REPO_ROOT,
        [
            Path(__file__),
            REPO_ROOT / "research_core/annual_rotation_v2.py",
            REPO_ROOT / "research_core/annual_completion_evidence.py",
            REPO_ROOT / "research_core/json_integrity.py",
            REPO_ROOT / "scripts/complete_annual_rotation.py",
            args.params,
            report,
        ],
    )
    producer = producer_data_root()
    evidence_root = args.evidence_root or producer / "corporate_action_supplements/annual-winner-20261013-v1"
    price_path, action_path = producer / "price_daily.parquet", producer / "corporate_actions.sqlite"
    before = _sample()
    inputs = fingerprint_inputs([
        InputSpec("price_daily", price_path, live_producer=True),
        InputSpec("corporate_actions", action_path, tables={"corporate_actions": "ex_date"}, live_producer=True),
        InputSpec("supplement_publication", evidence_root / "publication.json", live_producer=True),
        InputSpec("original_report", report, live_producer=False),
        InputSpec("parameters", args.params, live_producer=False),
    ])
    fingerprint_phase = phase_receipt("fingerprint", before, _sample())
    before = _sample()
    params = read_json(args.params)
    preregistration = REPO_ROOT / params["preregistration"]
    if _require_committed_sources(REPO_ROOT, [preregistration]) != starting_identity:
        raise ValueError("run source identity changed before preregistration admission")
    selections = parse_fixed_selections(report.read_text(encoding="utf-8"))
    codes = sorted({row["code"] for row in selections} | {"0050"})
    cutoff = _daily_date(params.get("cutoff", "2026-10-12"))
    dates = read_stable(price_path, lambda path: pd.read_parquet(path, columns=["Date", "Source"]))
    calendar = pd.DatetimeIndex(sorted(pd.to_datetime(dates.loc[dates.Source.eq("official"), "Date"]).unique()))
    calendar = calendar[calendar <= cutoff]
    del dates
    columns = ["Code", "Date", "Open", "High", "Low", "Close", "Volume", "Source"]
    prices = read_stable(price_path, lambda path: pd.read_parquet(path, columns=columns, filters=[("Code", "in", codes), ("Source", "==", "official")]))
    prices["Code"] = prices.Code.astype(str)
    prices["Date"] = pd.to_datetime(prices.Date)
    prices = prices.loc[prices.Date.le(cutoff)]
    with closing(readonly_sqlite(action_path)) as connection:
        actions = pd.read_sql_query("SELECT source,market,code,ex_date,event_type,price_factor,cash_dividend_estimate FROM corporate_actions", connection)
    actions["code"] = actions.code.astype(str)
    actions["ex_date"] = pd.to_datetime(actions.ex_date)
    actions = actions.loc[actions.code.isin(codes) & actions.ex_date.le(cutoff)]
    load_phase = phase_receipt("load", before, _sample())
    before = _sample()
    evidence = load_verified_evidence(evidence_root)
    admission = build_admission(evidence, prices, actions, calendar)
    evidence_phase = phase_receipt("evidence", before, _sample())
    before = _sample()
    result = complete_fixed_sequence(prices, actions, calendar, selections, admission, params)
    compute_phase = phase_receipt("compute", before, _sample())
    audit = {
        "schema": "annual-completion-admission.v2",
        "run_id": params["run_id"],
        "source_publication": evidence.manifest,
        "audit": admission.audit,
        "unresolved": admission.unresolved,
    }
    performance = {
        "schema": "annual-completion-performance.v2",
        "run_id": params["run_id"],
        "phases": [fingerprint_phase, load_phase, evidence_phase, compute_phase],
        "evidence_verification_seconds": evidence.verification_seconds,
        "retained_evidence_bytes": evidence.retained_bytes,
        "input_copy_bytes": 0,
        "input_fingerprint_passes": 1,
        "market_calendar_scans": 1,
        "fixed_price_rows_loaded": len(prices),
        "loaded_issuer_count": prices.Code.nunique(),
        "retained_result_bytes_before_format": len(canonical(result)) + len(canonical(audit)),
        "execution": result["execution"],
        "unavailable_observations": [
            "physical disk I/O and isolated phase peak RSS are not measured",
            "formatting timing and final retained output bytes are reported on CLI stdout",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    outputs = {"results": output / "results.json", "admission": output / "admission-audit.json", "performance": output / "performance.json"}
    for key, value in (("results", result), ("admission", audit), ("performance", performance)):
        write_json(outputs[key], value)
    formatting_seconds = _format_outputs(list(outputs.values()), REPO_ROOT)
    _require_code_identity(REPO_ROOT, starting_identity)
    receipt = write_run_receipt(
        output / "run-receipt.json",
        run_id=params["run_id"],
        definition=result["definition"],
        parameters=params,
        inputs=inputs,
        results=outputs,
        preregistration=preregistration,
        repo_root=REPO_ROOT,
    )
    if receipt.get("code") != starting_identity:
        raise ValueError("run receipt code identity differs from the starting source identity")
    _require_code_identity(REPO_ROOT, starting_identity)
    packing_started = time.perf_counter()
    archive = pack_publication(output)
    packing_seconds = time.perf_counter() - packing_started
    print(  # noqa: T201 - CLI publication summary
        canonical({
            "output": str(output),
            "run_id": params["run_id"],
            "formatting_seconds": formatting_seconds,
            "packing_seconds": packing_seconds,
            "archive_bytes": archive.stat().st_size,
            "retained_output_bytes": sum((output / name).stat().st_size for name in OUTPUT_NAMES),
            "execution": result["execution"],
        }).decode("utf-8")
    )
    return 0
