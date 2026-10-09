from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from stock_research_query import QueryError, inspect_task_trade


def print_text(report: dict[str, Any]):
    lines = [
        f"Task: {report['task']}",
        f"Trade ID: {report['trade_id']}",
        f"Trade: {json.dumps(report['trade'], ensure_ascii=False, default=str)}",
        f"Signal events: {json.dumps(report['signal_events'], ensure_ascii=False, default=str)}",
        f"Cash context: {json.dumps(report['cash_context'], ensure_ascii=False, default=str)}",
        f"Price context: {json.dumps(report['price_context'], ensure_ascii=False, default=str)}",
        f"Data provenance: {json.dumps(report.get('data_provenance'), ensure_ascii=False, default=str)}",
    ]
    sys.stdout.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Inspect one task trade with nearby price and signal context.")
    parser.add_argument("--task", required=True, help="Task directory under tasks/")
    parser.add_argument("--code", default=None, help="Stock code")
    parser.add_argument("--date", default=None, help="Trade date as YYYY-MM-DD")
    parser.add_argument("--action", default="BUY", help="Trade action, usually BUY or SELL")
    parser.add_argument("--occurrence", type=int, default=0, help="Zero-based match index when multiple trades match")
    parser.add_argument("--trade-id", default=None, help="Stable task-local trade id such as T098")
    parser.add_argument("--data-path", default=None, help="Override price data directory")
    parser.add_argument("--summary-file", default="summary.json", help="Summary JSON file inside the task directory")
    parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format")
    args = parser.parse_args()

    try:
        report = inspect_task_trade(
            task=args.task,
            code=args.code,
            date=args.date,
            action=args.action,
            occurrence=args.occurrence,
            trade_id=args.trade_id,
            data_path=args.data_path,
            summary_file=args.summary_file,
        )
    except QueryError as exc:
        raise SystemExit(f"[!] {exc}") from exc

    if args.format == "text":
        print_text(report)
    else:
        sys.stdout.write(json.dumps(report, indent=4, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    main()
