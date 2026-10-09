from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research_core.producer_data import producer_data_root  # noqa: E402

TASKS_ROOT = REPO_ROOT / "tasks"
DEFAULT_DATA_PATH = producer_data_root()
TASK_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
ELECTRONICS_LARGE_CODES = [
    "2330",
    "2308",
    "2454",
    "2317",
    "3711",
    "2383",
    "2345",
    "3017",
    "3037",
    "2360",
    "2382",
    "2303",
    "6669",
    "2357",
    "3008",
    "3034",
    "3231",
    "2301",
    "2324",
    "2352",
    "2353",
    "2356",
]


def fail(message: Any):
    sys.stderr.write(f"[FAIL] {message}\n")
    sys.exit(1)


def parse_codes(codes: str):
    if codes.strip().lower() in {"electronics-large", "electronics"}:
        return ELECTRONICS_LARGE_CODES
    parsed = [item.strip() for item in codes.split(",") if item.strip()]
    if not parsed:
        fail("--codes must contain at least one symbol")
    return parsed


def validate_date(value: Any, label: str):
    if not value:
        return
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        fail(f"{label} must use YYYY-MM-DD format")


def validate_task_name(task: str):
    if Path(task).is_absolute() or "/" in task or "\\" in task:
        fail("--task must be a simple directory name under tasks/")
    if not TASK_NAME_PATTERN.match(task):
        fail("--task may only contain letters, numbers, underscore, and hyphen")


def artifact_path(value: Any) -> str:
    path = Path(value)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path)


def read_price_data(data_path: Path, requested_codes: list[str]):
    price_path = data_path / "price_daily.parquet"
    if not price_path.is_file():
        dfs = []
        for code in requested_codes:
            csv_path = data_path / f"{code}_day.csv"
            if not csv_path.is_file():
                continue
            df = pd.read_csv(csv_path)
            df.columns = [column.strip() for column in df.columns]
            if "Date" not in df.columns and "ts" in df.columns:
                df["Date"] = pd.to_datetime(df["ts"])
            elif "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"])
            else:
                continue
            df["Code"] = code
            dfs.append(df)
        if not dfs:
            return price_path, None
        return data_path, pd.concat(dfs, ignore_index=True)
    return price_path, pd.read_parquet(price_path)


def build_data_audit(data_path: Path, requested_codes: list[str]):
    price_path, df = read_price_data(data_path, requested_codes)
    audit = {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_path": artifact_path(data_path),
        "price_file": artifact_path(price_path),
        "price_file_exists": price_path.is_file(),
        "requested_codes": requested_codes,
        "available_codes": [],
        "missing_codes": requested_codes,
        "date_min": None,
        "date_max": None,
        "rows": 0,
        "warnings": [],
    }

    if df is None:
        audit["warnings"].append("No price_daily.parquet or requested *_day.csv files were found")
        return audit

    required_columns = {"Date", "Code", "Close"}
    missing_columns = sorted(required_columns.difference(df.columns))
    if missing_columns:
        audit["warnings"].append(f"price_daily.parquet is missing required columns: {missing_columns}")
        return audit

    available_codes = sorted(str(code) for code in df["Code"].dropna().unique())
    missing_codes = [code for code in requested_codes if code not in available_codes]
    audit.update({
        "available_codes": available_codes,
        "missing_codes": missing_codes,
        "date_min": df["Date"].min().date().isoformat(),
        "date_max": df["Date"].max().date().isoformat(),
        "rows": int(len(df)),
    })
    for code in missing_codes:
        audit["warnings"].append(f"No loaded price data for requested symbol: {code}")
    return audit


def render_mission(args: argparse.Namespace, codes: list[str], audit: dict[str, Any]):
    end = args.end or "latest available local data"
    objective = args.objective or (
        "Prepare a local K-line research task. Codex should inspect this mission, choose or create candidate strategies, "
        "run Docker backtests when needed, and write summary/report artifacts."
    )
    warnings = audit.get("warnings", [])
    warning_lines = "\n".join(f"- {item}" for item in warnings) if warnings else "- No data warnings from runner preflight."
    return f"""# Mission

## Scope

- Market: Taiwan stocks
- Symbols: {", ".join(codes)}
- Data: local K-line only
- Start: {args.start}
- End: {end}
- Prepared by: `scripts/prepare_nightly_research.py`

## Constraints

- No real trading
- No broker credentials
- No internet research
- Do not modify `StockProject/engine/`
- Use Docker for generated strategy execution
- Runner only prepares this task; Codex remains responsible for strategy design and interpretation

## Data Preflight

- Data path: `{audit["data_path"]}`
- Price file exists: `{audit["price_file_exists"]}`
- Loaded date range: `{audit["date_min"] or "n/a"}` to `{audit["date_max"] or "n/a"}`
- Available requested symbols: {", ".join(code for code in codes if code not in audit["missing_codes"]) or "none"}
- Missing requested symbols: {", ".join(audit["missing_codes"]) or "none"}

Warnings:
{warning_lines}

## Objective

- {objective}
- Use `data_audit.json` before interpreting results.
- Write machine-readable output under `runs/`.
- Promote the selected run to `summary.json`.
- Prepare a Notion-ready daily research summary from local artifacts when Notion is configured.
"""


def reject_retired_template_flag(template: Any):
    if template is not None:
        fail(
            "--template has been retired. The legacy experiment loop repeatedly evaluates holdout "
            "and is not supported for current studies. Follow docs/en/research-owner-contract.md "
            "and docs/en/research-foundation.md for authorized preparation and execution."
        )


def create_nightly_task(args: argparse.Namespace):
    reject_retired_template_flag(args.template)
    validate_task_name(args.task)
    validate_date(args.start, "--start")
    validate_date(args.end, "--end")
    codes = parse_codes(args.codes)
    data_path = Path(args.data_path).resolve()

    task_root = TASKS_ROOT / args.task
    if task_root.exists() and not args.force:
        fail(f"task already exists; pass --force to reuse it: {task_root}")

    (task_root / "candidates").mkdir(parents=True, exist_ok=True)
    (task_root / "params").mkdir(parents=True, exist_ok=True)
    (task_root / "runs").mkdir(parents=True, exist_ok=True)
    (task_root / "runs" / ".gitkeep").touch()

    audit = build_data_audit(data_path, codes)
    (task_root / "data_audit.json").write_text(json.dumps(audit, indent=4), encoding="utf-8")
    (task_root / "mission.md").write_text(render_mission(args, codes, audit), encoding="utf-8")

    title_path = None
    if args.name:
        title_path = task_root / "research_dashboard" / "title.txt"
        title_path.parent.mkdir(parents=True, exist_ok=True)
        title_path.write_text(args.name, encoding="utf-8")

    output = json.dumps(
        {
            "task": str(task_root.relative_to(REPO_ROOT)),
            "mission": str((task_root / "mission.md").relative_to(REPO_ROOT)),
            "data_audit": str((task_root / "data_audit.json").relative_to(REPO_ROOT)),
            "warnings": audit["warnings"],
            **({"title": str(title_path.relative_to(REPO_ROOT))} if title_path else {}),
        },
        indent=2,
    )
    sys.stdout.write(f"{output}\n")


def main():
    today = date.today().strftime("%Y%m%d")
    parser = argparse.ArgumentParser(description="Prepare a nightly research task for Codex to continue.")
    parser.add_argument("--task", default=f"{today}-nightly-research", help="Task directory name under tasks/")
    parser.add_argument(
        "--codes",
        default="electronics-large",
        help="Comma-separated stock codes, or electronics-large for the default electronics pool",
    )
    parser.add_argument("--start", default="2022-01-01", help="Research start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="Research end date (YYYY-MM-DD)")
    parser.add_argument("--data-path", default=str(DEFAULT_DATA_PATH), help="Directory containing price_daily.parquet")
    parser.add_argument("--objective", default=None, help="Research objective written into mission.md")
    parser.add_argument("--name", default=None, help="Human-readable task title shown in the dashboard")
    parser.add_argument(
        "--template",
        default=None,
        help="Retired: follow the current research owner contract and research-foundation workflow.",
    )
    parser.add_argument("--force", action="store_true", help="Reuse an existing task and overwrite runner-owned files")
    args = parser.parse_args()

    create_nightly_task(args)


if __name__ == "__main__":
    main()
