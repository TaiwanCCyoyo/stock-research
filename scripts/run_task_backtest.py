from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.logging_utils import configure_logging

LOGGER = logging.getLogger(__name__)

APP_ROOT = Path(os.environ.get("APP_ROOT", "/app"))
if not APP_ROOT.exists():
    APP_ROOT = Path(__file__).resolve().parents[1]
TASKS_ROOT = APP_ROOT / "tasks"
DEFAULT_DATA_PATH = "data"
REQUIRED_SUMMARY_KEYS = {
    "schema_version",
    "generated_at",
    "run",
    "strategy",
    "data",
    "metrics",
    "portfolio",
    "trades",
    "warnings",
}


def fail(message: str):
    LOGGER.error("[FAIL] %s", message)
    sys.exit(1)


def path_under(root: Path, value: str | Path, label: str):
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        fail(f"{label} must stay under {root}: {value}")
    return path


def resolve_task_root(task: str):
    raw_task = Path(task)
    if raw_task.is_absolute():
        fail("--task must be a relative path")

    if raw_task.parts and raw_task.parts[0] == "tasks":
        task_root = path_under(APP_ROOT, raw_task, "--task")
    else:
        task_root = path_under(TASKS_ROOT, raw_task, "--task")

    if not task_root.is_dir():
        fail(f"task directory does not exist: {task_root.relative_to(APP_ROOT)}")
    return task_root


def resolve_strategy_path(task_root: Path, strategy: str):
    raw_strategy = Path(strategy)
    if raw_strategy.is_absolute():
        fail("--strategy must be relative to the task directory")

    strategy_path = path_under(task_root, raw_strategy, "--strategy")
    candidates_root = task_root / "candidates"
    if not strategy_path.is_relative_to(candidates_root.resolve()):
        fail("--strategy must stay under the task candidates directory")
    if not strategy_path.is_file():
        fail(f"strategy file does not exist: {strategy_path.relative_to(APP_ROOT)}")
    return strategy_path


def assert_task_contract(task_root: Path):
    required_paths = [
        task_root / "mission.md",
        task_root / "candidates",
        task_root / "runs",
    ]
    missing = [str(path.relative_to(APP_ROOT)) for path in required_paths if not path.exists()]
    if missing:
        fail(f"task contract missing paths: {missing}")


def make_run_name(strategy_path: Path, codes: str):
    clean_codes = codes.replace(",", "_").replace(" ", "").replace("@", "")
    return f"{strategy_path.stem}_{clean_codes}"


def summarize_signal_counts(signal_events: dict[str, Any]):
    counts: dict[str, dict[str, int]] = {}
    for event in signal_events.get("events", []):
        code = event.get("code")
        name = event.get("event")
        if not code or not name:
            continue
        item = counts.setdefault(code, {})
        item[name] = item.get(name, 0) + 1
    return counts


def write_stock_rankings(summary: dict[str, Any], signal_events: dict[str, Any], output_path: Path):
    signal_counts = summarize_signal_counts(signal_events or {})
    rows: list[dict[str, Any]] = []
    for code, metrics in summary.get("symbols", {}).items():
        rows.append({
            "code": code,
            "total_pnl": metrics.get("total_pnl"),
            "max_drawdown_rate": metrics.get("max_drawdown_rate"),
            "trade_count": metrics.get("trade_count"),
            "win_rate": metrics.get("win_rate"),
            "final_qty": metrics.get("final_qty"),
            "signal_counts": signal_counts.get(code, {}),
        })
    rows.sort(key=lambda item: float(item.get("total_pnl") or float("-inf")), reverse=True)
    payload = {
        "schema_version": "1.0",
        "run_output": str(output_path.relative_to(APP_ROOT)),
        "rank_metric": "total_pnl",
        "rank_direction": "max",
        "stocks": rows,
    }
    return payload


def collect_run_artifacts(task_root: Path, output_path: Path, summary: dict[str, Any]):
    generic_signal_path = task_root / "signal_events.json"
    run_signal_path = output_path.with_suffix(".signal_events.json")
    run_ranking_path = output_path.with_suffix(".stock_rankings.json")
    signal_events: dict[str, Any] = {}

    if generic_signal_path.is_file():
        signal_events = json.loads(generic_signal_path.read_text(encoding="utf-8"))
        shutil.copyfile(generic_signal_path, run_signal_path)

    rankings = write_stock_rankings(summary, signal_events, output_path)
    run_ranking_path.write_text(json.dumps(rankings, indent=4, ensure_ascii=False), encoding="utf-8")
    (task_root / "stock_rankings.json").write_text(json.dumps(rankings, indent=4, ensure_ascii=False), encoding="utf-8")
    return {
        "signal_events_path": str(run_signal_path.relative_to(APP_ROOT)) if run_signal_path.is_file() else None,
        "stock_rankings_path": str(run_ranking_path.relative_to(APP_ROOT)),
    }


def promote_comparison_artifacts(task_root: Path, output_path: Path) -> None:
    """Promote Option-A capital-mode comparison artifacts next to task summary.json."""
    if output_path.parent == task_root:
        return
    for name in ["summary_shared.json", "summary_per_stock.json", "summary_unconstrained.json", "comparison.json"]:
        source = output_path.parent / name
        if source.is_file():
            shutil.copyfile(source, task_root / name)


def run_backtest(args: argparse.Namespace, task_root: Path, strategy_path: Path, output_path: Path):
    output_path = path_under(task_root / "runs", output_path, "--run-name")
    command = [
        sys.executable,
        "StockProject/backtest_cli.py",
        "--strategy",
        str(strategy_path.relative_to(APP_ROOT)),
        "--codes",
        args.codes,
        "--start",
        args.start,
        "--cash",
        str(args.cash),
        "--capital-mode",
        args.capital_mode,
        "--benchmark-code",
        args.benchmark_code,
        "--data-path",
        args.data_path,
        "--output",
        str(output_path.relative_to(APP_ROOT)),
    ]
    if args.params_json:
        command.extend(["--params-json", args.params_json])
    if args.params_file:
        params_path = path_under(task_root, Path(args.params_file), "--params-file")
        command.extend(["--params-file", str(params_path.relative_to(APP_ROOT))])
    if args.end:
        command.extend(["--end", args.end])

    subprocess.run(command, cwd=APP_ROOT, check=True)
    summary = json.loads(output_path.read_text(encoding="utf-8"))
    missing = REQUIRED_SUMMARY_KEYS.difference(summary)
    if missing:
        fail(f"summary schema missing keys: {sorted(missing)}")
    if summary["schema_version"] != "1.0":
        fail(f"unexpected schema version: {summary['schema_version']}")
    collect_run_artifacts(task_root, output_path, summary)
    if args.promote_summary:
        (task_root / "summary.json").write_text(json.dumps(summary, indent=4), encoding="utf-8")
        if args.capital_mode == "all":
            promote_comparison_artifacts(task_root, output_path)
    return summary


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description="Run a task-local candidate strategy through the backtest CLI.")
    parser.add_argument("--task", required=True, help="Task path under /app/tasks, such as sample or tasks/sample")
    parser.add_argument("--strategy", required=True, help="Strategy path relative to the task, under candidates/")
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
    parser.add_argument("--data-path", default=DEFAULT_DATA_PATH, help="Data path inside the container")
    parser.add_argument("--params-json", default=None, help="Inline strategy params JSON object")
    parser.add_argument("--params-file", default=None, help="Strategy params JSON path relative to the task")
    parser.add_argument("--run-name", default=None, help="Output file name without extension")
    parser.add_argument("--promote-summary", action="store_true", help="Copy the run summary to task/summary.json")
    args = parser.parse_args()

    task_root = resolve_task_root(args.task)
    assert_task_contract(task_root)
    strategy_path = resolve_strategy_path(task_root, args.strategy)
    run_name = args.run_name or make_run_name(strategy_path, args.codes)
    if "/" in run_name or "\\" in run_name:
        fail("--run-name must be a plain file name without path separators")
    runs_root = task_root / "runs"
    output_path = path_under(runs_root, f"{run_name}.json", "--run-name")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary = run_backtest(args, task_root, strategy_path, output_path)
    LOGGER.info(
        "%s",
        json.dumps(
            {
                "output": str(output_path.relative_to(APP_ROOT)),
                "strategy": summary["strategy"]["name"],
                "return_rate": summary["metrics"]["return_rate"],
                "final_value": summary["metrics"]["final_value"],
                "trade_count": summary["metrics"]["trade_count"],
            },
            indent=2,
        ),
    )


if __name__ == "__main__":
    main()
