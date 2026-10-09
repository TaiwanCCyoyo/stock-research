from __future__ import annotations

import argparse
import itertools
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

try:
    from run_task_backtest import APP_ROOT, assert_task_contract, fail, path_under, resolve_strategy_path, resolve_task_root, run_backtest
except ModuleNotFoundError:
    from scripts.run_task_backtest import APP_ROOT, assert_task_contract, fail, path_under, resolve_strategy_path, resolve_task_root, run_backtest

SLUG_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")


def load_sweep_spec(task_root: Path, grid_file: str):
    spec_path = path_under(task_root, Path(grid_file), "--grid-file")
    if not spec_path.is_file():
        fail(f"grid file does not exist: {spec_path.relative_to(APP_ROOT)}")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        fail("--grid-file must decode to a JSON object")
    return spec_path, spec


def make_slug(value: Any):
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = text.strip('"').replace(",", "_")
    text = text.replace("[", "").replace("]", "").replace("{", "").replace("}", "")
    text = SLUG_PATTERN.sub("_", text)
    return text.strip("_") or "value"


def validate_params(params: dict[str, Any], label: str):
    if not isinstance(params, dict):
        fail(f"{label} params must be a JSON object")
    return params


def iter_named_param_sets(spec: dict[str, Any]):
    base = validate_params(spec.get("base", {}), "base")

    if "runs" in spec:
        runs = spec["runs"]
        if not isinstance(runs, list) or not runs:
            fail("runs must be a non-empty list")
        for index, item in enumerate(runs, start=1):
            if not isinstance(item, dict):
                fail("each runs item must be a JSON object")
            params = dict(base)
            params.update(validate_params(item.get("params", {}), f"runs[{index}]"))
            name = item.get("name") or f"run_{index:03d}"
            yield str(name), params
        return

    grid = spec.get("grid")
    if not isinstance(grid, dict) or not grid:
        fail("grid must be a non-empty object when runs is not provided")

    assert isinstance(grid, dict)
    keys = list(grid)
    values = []
    for key in keys:
        options = grid[key]
        if not isinstance(options, list) or not options:
            fail(f"grid.{key} must be a non-empty list")
        values.append(options)

    for index, combo in enumerate(itertools.product(*values), start=1):
        params = dict(base)
        params.update(dict(zip(keys, combo)))
        name_parts = [f"{key}_{make_slug(value)}" for key, value in zip(keys, combo)]
        yield f"{index:03d}_{'_'.join(name_parts)}", params


def metric_value(summary: dict[str, Any], key: str):
    metrics = summary.get("metrics", {})
    if key not in metrics:
        fail(f"rank metric not found in summary metrics: {key}")
    value = metrics[key]
    if value is None:
        return float("-inf")
    return value


def build_run_args(args: argparse.Namespace, params: dict[str, Any]) -> argparse.Namespace:
    return cast(
        argparse.Namespace,
        SimpleNamespace(
            codes=args.codes,
            start=args.start,
            end=args.end,
            cash=args.cash,
            capital_mode=args.capital_mode,
            benchmark_code=args.benchmark_code,
            data_path=args.data_path,
            params_json=json.dumps(params),
            params_file=None,
            promote_summary=False,
        ),
    )


def run_sweep(args: argparse.Namespace):
    task_root = resolve_task_root(args.task)
    assert_task_contract(task_root)
    strategy_path = resolve_strategy_path(task_root, args.strategy)
    spec_path, spec = load_sweep_spec(task_root, args.grid_file)

    raw_results = []
    for name, params in iter_named_param_sets(spec):
        run_name = f"{args.run_prefix}_{name}" if args.run_prefix else name
        output_path = task_root / "runs" / f"{run_name}.json"
        summary = run_backtest(build_run_args(args, params), task_root, strategy_path, output_path)
        signal_events_path = output_path.with_suffix(".signal_events.json")
        stock_rankings_path = output_path.with_suffix(".stock_rankings.json")
        raw_results.append({
            "name": name,
            "run_name": run_name,
            "params": params,
            "output_path": str(output_path.relative_to(APP_ROOT)),
            "signal_events_path": str(signal_events_path.relative_to(APP_ROOT)) if signal_events_path.is_file() else None,
            "stock_rankings_path": str(stock_rankings_path.relative_to(APP_ROOT)) if stock_rankings_path.is_file() else None,
            "metrics": summary.get("metrics", {}),
            "symbols": summary.get("symbols", {}),
            "summary": summary,
        })

    reverse = args.rank_direction == "max"
    ranked = sorted(raw_results, key=lambda item: metric_value(item["summary"], args.rank_metric), reverse=reverse)
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank

    best = ranked[0] if ranked else None
    output = {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "task": str(task_root.relative_to(APP_ROOT)),
        "strategy": str(strategy_path.relative_to(APP_ROOT)),
        "grid_file": str(spec_path.relative_to(APP_ROOT)),
        "rank_metric": args.rank_metric,
        "rank_direction": args.rank_direction,
        "best": {
            key: best[key] for key in ["rank", "name", "run_name", "params", "output_path", "signal_events_path", "stock_rankings_path", "metrics", "symbols"]
        }
        if best
        else None,
        "runs": [
            {key: item[key] for key in ["rank", "name", "run_name", "params", "output_path", "signal_events_path", "stock_rankings_path", "metrics", "symbols"]}
            for item in ranked
        ],
    }

    output_path = path_under(task_root, Path(args.output), "--output")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=4), encoding="utf-8")
    if args.promote_best and best:
        (task_root / "summary.json").write_text(
            json.dumps(best["summary"], indent=4),
            encoding="utf-8",
        )
        if best.get("signal_events_path"):
            shutil.copyfile(APP_ROOT / best["signal_events_path"], task_root / "signal_events.json")
        if best.get("stock_rankings_path"):
            shutil.copyfile(APP_ROOT / best["stock_rankings_path"], task_root / "stock_rankings.json")

    sys.stdout.write(
        json.dumps(
            {
                "output": str(output_path.relative_to(APP_ROOT)),
                "runs": len(ranked),
                "rank_metric": args.rank_metric,
                "best": output["best"],
            },
            indent=2,
        )
        + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description="Run a task-local strategy parameter sweep.")
    parser.add_argument("--task", required=True, help="Task path under /app/tasks, such as sample or tasks/sample")
    parser.add_argument("--strategy", required=True, help="Strategy path relative to the task, under candidates/")
    parser.add_argument("--grid-file", required=True, help="Sweep JSON path relative to the task")
    parser.add_argument("--codes", required=True, help="Comma-separated stock codes")
    parser.add_argument("--start", default="2024-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--cash", type=float, default=1000000.0, help="Initial cash")
    parser.add_argument(
        "--capital-mode",
        choices=["shared", "per_stock", "unconstrained", "all"],
        default="shared",
        help="Capital allocation mode",
    )
    parser.add_argument("--benchmark-code", default="0050", help="Market benchmark symbol for portfolio-level comparison")
    parser.add_argument("--data-path", default="data", help="Data path inside the container")
    parser.add_argument("--run-prefix", default="sweep", help="Prefix for run output file names")
    parser.add_argument("--output", default="sweep_summary.json", help="Sweep summary path relative to the task")
    parser.add_argument("--rank-metric", default="return_rate", help="Metric key under summary.metrics used for ranking")
    parser.add_argument("--rank-direction", choices=["max", "min"], default="max", help="Ranking direction")
    parser.add_argument("--promote-best", action="store_true", help="Copy the best run summary to task/summary.json")
    args = parser.parse_args()

    try:
        run_sweep(args)
    except subprocess.CalledProcessError as e:
        fail(f"backtest command failed: {e}")


if __name__ == "__main__":
    main()
