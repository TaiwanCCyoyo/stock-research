"""List, label and clean experiment scratch runs on the shared root.

list    every run under <shared root>/scratch with its state and what may happen to it
mark    move a run to complete, delivered (with --result for each final result) or abandoned
clean   show deletable runs (delivered or abandoned); delete them only with --apply

Owner decision 2026-10-24: delivered and abandoned runs may be deleted by any session
without asking; everything listed as ask-owner needs the owner. See
docs/en/decision-records/2026-10-24-data-homes-and-scratch.md.
"""

from __future__ import annotations

import argparse
import logging
import sys

from research_core import scratch_runs

LABELS = {
    scratch_runs.IN_USE: "執行中，不可動",
    scratch_runs.PAUSED: "暫停，可續跑",
    scratch_runs.AWAITING_DELIVERY: "算完，待交付成果",
    scratch_runs.DELETABLE: "可清理",
    scratch_runs.ASK_OWNER: "需 owner 決定",
}


def _emit(text: str, *, error: bool = False) -> None:
    print(text, file=sys.stderr if error else sys.stdout)  # noqa: T201 - CLI output


def _print(statuses: list[scratch_runs.RunStatus]) -> None:
    if not statuses:
        _emit("scratch 區沒有任何 run。")
        return
    for status in statuses:
        progress = status.progress
        step = f" {progress['step']}/{progress['total']} {progress['label']}" if progress else ""
        _emit(f"{status.task}/{status.run}\t{status.state or '-'}\t{LABELS[status.verdict]}{step}\t{status.reason}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    mark = commands.add_parser("mark")
    mark.add_argument("task")
    mark.add_argument("run")
    mark.add_argument("--state", required=True, choices=["complete", "delivered", "abandoned"])
    mark.add_argument(
        "--result", action="append", default=[], help="repository-relative path already on origin/main, or absolute shared-root path; repeat per result"
    )
    mark.add_argument("--reason")
    clean = commands.add_parser("clean")
    clean.add_argument("--apply", action="store_true", help="actually delete; without it only lists")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        if args.command == "list":
            _print(scratch_runs.survey())
        elif args.command == "mark":
            with scratch_runs.open_run(args.task, args.run) as run:
                run.mark(args.state, results=args.result, reason=args.reason)
            _emit(f"{args.task}/{args.run} -> {args.state}")
        else:
            deletable = scratch_runs.clean(apply=args.apply)
            _print(deletable)
            if deletable and not args.apply:
                _emit("以上可清理；加 --apply 才會刪除。")
    except scratch_runs.ScratchRunError as error:
        _emit(f"錯誤：{error}", error=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
