from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research_core.evidence import task_catalog  # noqa: E402
from research_core.producer_data import producer_data_root  # noqa: E402
from StockProject.engine.data_loader import DataLoader  # noqa: E402

TASKS_ROOT = REPO_ROOT / "tasks"
DEFAULT_DATA_PATH = producer_data_root()


class QueryError(ValueError):
    """Expected query failure with a user-readable message."""


def read_json(path: Path):
    if not path.is_file():
        raise QueryError(f"missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_task_root(task: str):
    root = TASKS_ROOT / task
    if not root.resolve().is_relative_to(Path(TASKS_ROOT).resolve()):
        raise QueryError(f"task must stay under the tasks directory: {task}")
    if not root.is_dir():
        raise QueryError(f"task not found: {task}")
    return root


def resolve_summary_path(root: Path, summary_file: str) -> Path:
    path = (root / summary_file).resolve()
    if not path.is_relative_to(root.resolve()):
        raise QueryError("summary_file must stay inside the task")
    return path


def date_key(value: Any):
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value).split("T", 1)[0]


def trade_id_for_index(index: int):
    return f"T{index + 1:03d}"


def index_from_trade_id(trade_id: str | None):
    value = str(trade_id).strip().upper()
    if not value.startswith("T") or not value[1:].isdigit():
        raise QueryError(f"invalid trade_id: {trade_id}")
    index = int(value[1:]) - 1
    if index < 0:
        raise QueryError(f"invalid trade_id: {trade_id}")
    return index


def normalize_action(action: str | None):
    return str(action or "BUY").upper()


def find_trade(
    summary: dict[str, Any],
    code: str | None = None,
    trade_date: str | None = None,
    action: str | None = "BUY",
    occurrence: int = 0,
    trade_id: str | None = None,
):
    trades = summary.get("trades", [])
    if trade_id:
        index = index_from_trade_id(trade_id)
        if index >= len(trades):
            raise QueryError(f"trade_id {trade_id} out of range; found {len(trades)} trades")
        return index, trades[index]

    if not code or not trade_date:
        raise QueryError("code and date are required when trade_id is not provided")

    normalized_action = normalize_action(action)
    matches = []
    for index, trade in enumerate(trades):
        if str(trade.get("code")) != str(code):
            continue
        if normalize_action(trade.get("action")) != normalized_action:
            continue
        if date_key(trade.get("date")) != trade_date:
            continue
        matches.append((index, trade))

    if not matches:
        raise QueryError(f"no matching trade for {code} {trade_date} {normalized_action}")
    if occurrence >= len(matches):
        raise QueryError(f"occurrence {occurrence} out of range; found {len(matches)} matching trades")
    return matches[occurrence]


def resolve_price_data_root(data_path: Path | str | None) -> Path:
    if not isinstance(data_path, (str, Path)) or not str(data_path).strip():
        raise QueryError("recorded price data path is missing or invalid; supply an explicit data-path override, never infer the current snapshot")
    data_root = Path(data_path)
    if not data_root.is_absolute():
        data_root = REPO_ROOT / data_root
    data_root = data_root.resolve()
    if not data_root.exists():
        raise QueryError(f"recorded price data unavailable: {data_root}; no automatic fallback; supply an explicit data-path override for a non-original view")
    return data_root


def load_price_data(data_path: Path | str, code: str | None):
    data_root = resolve_price_data_root(data_path)
    if data_root.is_dir():
        loader = DataLoader(str(data_root))
        loader.load_symbols([str(code)])
        df = loader.get_stock_data(str(code))
        if not df.empty:
            return df.sort_values("Date").reset_index(drop=True)

    parquet_path = data_root / "price_daily.parquet"
    if parquet_path.is_file():
        df = pd.read_parquet(parquet_path)
        df = cast(pd.DataFrame, df[df["Code"].astype(str) == str(code)].copy())
    else:
        csv_path = data_root / f"{code}_day.csv"
        if not csv_path.is_file():
            raise QueryError(f"missing price data for {code}: {csv_path}")
        df = pd.read_csv(csv_path)
        df.columns = [column.strip() for column in df.columns]
        df["Code"] = str(code)
        if "Date" not in df.columns and "ts" in df.columns:
            df["Date"] = pd.to_datetime(df["ts"])
        elif "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
        else:
            raise QueryError(f"price data has no Date or ts column: {csv_path}")

    if df.empty:
        raise QueryError(f"no price rows found for {code}")
    df["Date"] = pd.to_datetime(cast(pd.Series, df["Date"])).dt.tz_localize(None)
    return df.sort_values("Date").reset_index(drop=True)


def price_context(df: pd.DataFrame, trade_date: str | None, params: dict[str, Any]):
    if not trade_date:
        raise QueryError("trade date is required for price context")
    current_date = pd.Timestamp(trade_date)
    normalized_dates = df["Date"].dt.normalize()
    history = df[normalized_dates <= current_date].copy()
    if history.empty or date_key(history.iloc[-1]["Date"]) != trade_date:
        raise QueryError(f"no price row for trade date: {trade_date}")

    current = history.iloc[-1]
    prior = history.iloc[:-1]
    windows = [int(value) for value in params.get("windows", [5, 10, 20])]
    swing_lookback = int(params.get("swing_lookback", 20))
    trend_window = int(params.get("trend_window", max(windows)))
    closes = [float(value) for value in history["Close"]]

    moving_averages = {}
    for window in windows:
        if len(closes) >= window:
            moving_averages[f"ma{window}"] = sum(closes[-window:]) / window

    ma_values = list(moving_averages.values())
    convergence_pct = None
    if ma_values:
        convergence_pct = ((max(ma_values) - min(ma_values)) / float(current["Close"])) * 100

    prior_close = float(prior.iloc[-1]["Close"]) if not prior.empty else None
    trend_ref_close = closes[-trend_window] if len(closes) >= trend_window else None
    prior_swing = prior.tail(swing_lookback)

    return {
        "bar": {
            "open": float(current["Open"]),
            "high": float(current["High"]),
            "low": float(current["Low"]),
            "close": float(current["Close"]),
        },
        "raw_bar": {
            "open": float(current.get("RawOpen", current["Open"])),
            "high": float(current.get("RawHigh", current["High"])),
            "low": float(current.get("RawLow", current["Low"])),
            "close": float(current.get("RawClose", current["Close"])),
        },
        "split_adjusted_bar": {
            "open": float(current.get("SplitAdjustedOpen", current.get("RawOpen", current["Open"]))),
            "high": float(current.get("SplitAdjustedHigh", current.get("RawHigh", current["High"]))),
            "low": float(current.get("SplitAdjustedLow", current.get("RawLow", current["Low"]))),
            "close": float(current.get("SplitAdjustedClose", current.get("RawClose", current["Close"]))),
        },
        "signal_price_policy": current.get("SignalPricePolicy", "legacy_adjusted_or_raw"),
        "dividend_window_active": bool(current.get("DividendWindowActive", False)),
        "dividend_filled": bool(current.get("DividendFilled", False)),
        "corporate_action_types": current.get("CorporateActionTypes", ""),
        "previous_close": prior_close,
        "moving_averages": moving_averages,
        "ma_max": max(ma_values) if ma_values else None,
        "ma_min": min(ma_values) if ma_values else None,
        "convergence_pct": convergence_pct,
        "convergence_threshold": params.get("convergence_pct"),
        "converged": (convergence_pct is not None and params.get("convergence_pct") is not None and convergence_pct <= float(params["convergence_pct"])),
        "trend_window": trend_window,
        "trend_ref_close": trend_ref_close,
        "trend_ready": trend_ref_close is not None and float(current["Close"]) >= trend_ref_close,
        "price_strength": (bool(ma_values) and prior_close is not None and float(current["Close"]) > max(ma_values) and float(current["Close"]) > prior_close),
        "swing_lookback": swing_lookback,
        "prior_swing_low": float(prior_swing["Low"].min()) if not prior_swing.empty else None,
        "prior_swing_high": float(prior_swing["High"].max()) if not prior_swing.empty else None,
        "low_broke_prior_swing": (not prior_swing.empty and float(current["Low"]) < float(prior_swing["Low"].min())),
        "high_broke_prior_swing": (not prior_swing.empty and float(current["High"]) > float(prior_swing["High"].max())),
    }


def load_signal_events(task_root_path: Path):
    path = task_root_path / "signal_events.json"
    if not path.is_file():
        return {"events": []}
    return read_json(path)


def matching_events(task_root_path: Path, code: str | None, trade_date: str | None, action: str | None):
    payload = load_signal_events(task_root_path)
    action_map = {
        "BUY": {"buy", "add"},
        "SELL": {"sell", "partial_sell"},
        "DIVIDEND": {"dividend"},
    }
    names = action_map.get(normalize_action(action), {str(action).lower()})
    return [
        event
        for event in payload.get("events", [])
        if str(event.get("code")) == str(code) and date_key(event.get("date")) == trade_date and str(event.get("event")) in names
    ]


def signal_reason_for_trade(events: list[dict[str, Any]], trade: dict[str, Any]):
    code = str(trade.get("code"))
    trade_date = date_key(trade.get("date"))
    action = normalize_action(trade.get("action"))
    action_map = {
        "BUY": {"buy", "add"},
        "SELL": {"sell", "partial_sell"},
        "DIVIDEND": {"dividend"},
    }
    names = action_map.get(action, {action.lower()})
    for event in events:
        if str(event.get("code")) == code and date_key(event.get("date")) == trade_date and event.get("event") in names:
            return event.get("reason")
    return None


def realized_pnl_by_index(trades: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Return per-trade PnL metadata keyed by original trade index.

    Uses the same proportional average-cost method as calculate_trade_stats
    in backtest_cli.py so values are consistent with summary metrics.

    Each entry contains:
      position_before        -- share count held before this trade
      is_add_on              -- True when a BUY is added to an existing position
      realized_pnl           -- round-trip profit/loss on a SELL (None otherwise)
      cumulative_realized_pnl -- running total of realized PnL for this code
    """
    positions: dict[str, int] = {}
    cost_basis: dict[str, float] = {}
    cumulative: dict[str, float] = {}
    result: dict[int, dict[str, Any]] = {}

    for idx, trade in enumerate(trades):
        code = str(trade.get("code", ""))
        action = str(trade.get("action", "")).upper()
        qty = int(trade.get("qty", 0))
        position_before = positions.get(code, 0)
        is_add_on = action == "BUY" and position_before > 0
        realized_pnl: float | None = None

        if action == "BUY":
            positions[code] = position_before + qty
            cost_basis[code] = cost_basis.get(code, 0.0) - float(trade.get("total", 0.0))
        elif action == "SELL":
            current_qty = positions.get(code, 0)
            current_basis = cost_basis.get(code, 0.0)
            if current_qty > 0:
                sold_basis = current_basis * (qty / current_qty)
                realized_pnl = float(trade.get("total", 0.0)) - sold_basis
                positions[code] = current_qty - qty
                cost_basis[code] = current_basis - sold_basis
                cumulative[code] = cumulative.get(code, 0.0) + realized_pnl
        elif action == "SPLIT":
            positions[code] = int(trade.get("new_qty", position_before))

        result[idx] = {
            "position_before": position_before,
            "is_add_on": is_add_on,
            "realized_pnl": realized_pnl,
            "cumulative_realized_pnl": cumulative.get(code, 0.0),
        }

    return result


def cash_context(summary: dict[str, Any], trade_index: Any, trade: dict[str, Any]):
    run = summary.get("run", {})
    capital_mode = run.get("capital_mode", "shared")
    code = str(trade.get("code"))

    if capital_mode == "per_stock":
        cash = float(run.get("per_stock_initial_cash", run.get("initial_cash", 0.0)))
    else:
        cash = float(run.get("initial_cash", 0.0))

    position = 0
    for prior_trade in summary.get("trades", [])[:trade_index]:
        if capital_mode == "per_stock":
            if str(prior_trade.get("code")) == code:
                cash += float(prior_trade.get("total", 0.0))
        else:
            cash += float(prior_trade.get("total", 0.0))
        if str(prior_trade.get("code")) != code:
            continue
        qty = int(prior_trade.get("qty", 0))
        if prior_trade.get("action") == "BUY":
            position += qty
        elif prior_trade.get("action") == "SELL":
            position -= qty
        elif prior_trade.get("action") == "SPLIT":
            position = int(prior_trade.get("new_qty", position))

    price = float(trade.get("price", 0.0))
    qty = int(trade.get("qty", 0))
    fee = float(trade.get("fee", 0.0))
    recorded_total = float(trade.get("total", 0.0))

    pnl_index = realized_pnl_by_index(summary.get("trades", []))
    pnl_entry = pnl_index.get(int(trade_index), {})

    return {
        "cash_before_trade": cash,
        "cash_after_trade": cash + recorded_total,
        "position_before_trade": position,
        "gross_amount": price * qty,
        "fee": fee,
        "tax": float(trade.get("tax", 0.0)),
        "recorded_total": recorded_total,
        "is_add_on": pnl_entry.get("is_add_on", False),
        "realized_pnl": pnl_entry.get("realized_pnl"),
        "cumulative_realized_pnl": pnl_entry.get("cumulative_realized_pnl", 0.0),
    }


def inspect_task_trade(
    task: str,
    code: str | None = None,
    date: str | None = None,
    action: str = "BUY",
    occurrence: int = 0,
    trade_id: str | None = None,
    data_path: str | Path | None = None,
    summary_file: str = "summary.json",
):
    root = resolve_task_root(task)
    summary_path = resolve_summary_path(root, summary_file)
    summary = read_json(summary_path)
    trade_index, trade = find_trade(
        summary,
        code=code,
        trade_date=date,
        action=action,
        occurrence=occurrence,
        trade_id=trade_id,
    )
    resolved_code = str(trade.get("code"))
    resolved_date = date_key(trade.get("date"))
    resolved_action = normalize_action(trade.get("action"))
    params = summary.get("strategy", {}).get("params", {})
    summary_data_path = summary.get("data", {}).get("path")
    resolved_data_path = resolve_price_data_root(data_path if data_path is not None else summary_data_path)
    df = load_price_data(resolved_data_path, resolved_code)

    return {
        "task": task,
        "query": {
            "code": code,
            "date": date,
            "action": normalize_action(action),
            "occurrence": occurrence,
            "trade_id": trade_id,
        },
        "trade_id": trade_id_for_index(trade_index),
        "trade_index": trade_index,
        "trade": trade,
        "signal_events": matching_events(root, resolved_code, resolved_date, resolved_action),
        "cash_context": cash_context(summary, trade_index, trade),
        "price_context": price_context(df, resolved_date, params),
        "strategy": summary.get("strategy", {}),
        "strategy_params": params,
        "price_policy": summary.get("price_policy", {}),
        "data_path": str(resolved_data_path),
        "data_provenance": {
            "recorded_path": summary_data_path,
            "resolved_path": str(resolved_data_path),
            "mode": "explicit_override" if data_path is not None else "recorded_path",
            "snapshot_verified": False,
            "note": "Path resolution is not snapshot hash verification; an override is not an original-snapshot reproduction.",
        },
    }


def list_task_trades(task: str, code: str | None = None, action: str | None = None, limit: int = 50, summary_file: str = "summary.json"):
    root = resolve_task_root(task)
    summary = read_json(resolve_summary_path(root, summary_file))
    events = load_signal_events(root).get("events", [])
    normalized_action = normalize_action(action) if action else None
    all_trades = summary.get("trades", [])
    pnl_index = realized_pnl_by_index(all_trades)
    rows = []

    for index, trade in enumerate(all_trades):
        if code and str(trade.get("code")) != str(code):
            continue
        if normalized_action and normalize_action(trade.get("action")) != normalized_action:
            continue
        pnl_entry = pnl_index.get(index, {})
        rows.append({
            "trade_id": trade_id_for_index(index),
            "date": trade.get("date"),
            "code": trade.get("code"),
            "action": trade.get("action"),
            "price": trade.get("price"),
            "qty": trade.get("qty"),
            "total": trade.get("total"),
            "signal_reason": signal_reason_for_trade(events, trade),
            "realized_pnl": pnl_entry.get("realized_pnl"),
            "cumulative_realized_pnl": pnl_entry.get("cumulative_realized_pnl", 0.0),
            "is_add_on": pnl_entry.get("is_add_on", False),
        })
        if limit and len(rows) >= int(limit):
            break

    return {
        "task": task,
        "query": {
            "code": code,
            "action": normalized_action,
            "limit": limit,
            "summary_file": summary_file,
        },
        "count": len(rows),
        "trades": rows,
    }


def list_research_tasks(limit: int = 20):
    if not TASKS_ROOT.is_dir():
        return {"count": 0, "tasks": []}

    catalog = task_catalog(TASKS_ROOT)
    rows = []
    for item in catalog[: int(limit)]:
        path = TASKS_ROOT / item["task"]
        rows.append({
            "task": path.name,
            "summary": (path / "summary.json").is_file(),
            "signal_events": (path / "signal_events.json").is_file(),
            "stock_rankings": (path / "stock_rankings.json").is_file(),
            "data_audit": (path / "data_audit.json").is_file(),
            "visual_report": (path / "visual_report.html").is_file(),
            "report": item["artifacts"]["report.md"],
            "mission": item["artifacts"]["mission.md"],
            "research_result": item["artifacts"]["research_result.json"],
            "evidence_state": item["evidence_state"],
            "outcome": "unknown",
        })
    return {
        "query": {"limit": limit},
        "count": len(rows),
        "tasks": rows,
    }
