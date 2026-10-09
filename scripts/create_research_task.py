import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.logging_utils import configure_logging
from StockProject.universe import UniverseError, resolve_codes

LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_ROOT = REPO_ROOT / "tasks"
TASK_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def fail(message: str):
    LOGGER.error("[FAIL] %s", message)
    sys.exit(1)


def validate_task_name(task: str):
    if Path(task).is_absolute() or "/" in task or "\\" in task:
        fail("--task must be a simple directory name under tasks/")
    if not TASK_NAME_PATTERN.match(task):
        fail("--task may only contain letters, numbers, underscore, and hyphen")


def parse_codes(codes: str):
    """Split a plain comma-separated code list, or expand an `@universe-name` reference."""
    try:
        parsed, _universe_name = resolve_codes(codes)
    except UniverseError as exc:
        fail(str(exc))
        return []
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


def render_mission(args: argparse.Namespace, codes: list[str]):
    end = args.end or "latest available local data"
    objective = args.objective or "Run a local K-line research task and produce summary/report artifacts."
    docker_line = "Use Docker for generated strategy execution" if args.use_docker else "Docker is optional for this task"
    return f"""# Mission

## Scope

- Market: Taiwan stocks
- Symbols: {", ".join(codes)}
- Data: {args.data}
- Start: {args.start}
- End: {end}

## Constraints

- No real trading
- No broker credentials
- No internet research
- Do not modify `StockProject/engine/`
- {docker_line}

## Objective

- {objective}
- Write machine-readable output under `runs/`.
- Promote the selected run to `summary.json`.
"""


def create_task(args: argparse.Namespace):
    validate_task_name(args.task)
    codes = parse_codes(args.codes)
    validate_date(args.start, "--start")
    validate_date(args.end, "--end")

    task_root = TASKS_ROOT / args.task
    if task_root.exists() and not args.force:
        fail(f"task already exists; pass --force to reuse it: {task_root}")

    (task_root / "candidates").mkdir(parents=True, exist_ok=True)
    (task_root / "runs").mkdir(parents=True, exist_ok=True)
    (task_root / "runs" / ".gitkeep").touch()

    mission_path = task_root / "mission.md"
    if mission_path.exists() and not args.force:
        fail(f"mission.md already exists; pass --force to overwrite it: {mission_path}")
    mission_path.write_text(render_mission(args, codes), encoding="utf-8")

    if args.name:
        title_path = task_root / "research_dashboard" / "title.txt"
        title_path.parent.mkdir(parents=True, exist_ok=True)
        title_path.write_text(args.name, encoding="utf-8")
        LOGGER.info("[WRITE] %s", title_path)

    LOGGER.info("[CREATE] %s", task_root)
    LOGGER.info("[WRITE] %s", mission_path)
    LOGGER.info("[READY] candidates=%s", task_root / "candidates")
    LOGGER.info("[READY] runs=%s", task_root / "runs")


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description="Create a standard research task folder.")
    parser.add_argument("--task", required=True, help="Task directory name under tasks/")
    parser.add_argument("--codes", required=True, help="Comma-separated stock codes")
    parser.add_argument("--start", default="2024-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--data", default="local K-line only", help="Data scope")
    parser.add_argument("--objective", default=None, help="Primary research objective")
    parser.add_argument("--name", default=None, help="Human-readable task title shown in the dashboard")
    parser.add_argument("--use-docker", action="store_true", help="Require Docker for generated strategy execution")
    parser.add_argument("--force", action="store_true", help="Reuse an existing task and overwrite mission.md")
    args = parser.parse_args()

    create_task(args)


if __name__ == "__main__":
    main()
