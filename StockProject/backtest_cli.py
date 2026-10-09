# ruff: noqa: E501
from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

SCHEMA_VERSION = "1.0"

# A handful of quiet trading days (single-day suspension, late listing within the
# window) is normal; beyond this a symbol's local data is more likely stale or
# incomplete rather than genuinely inactive.
DEFAULT_PARTIAL_DATA_GAP_THRESHOLD = 3

# Add the current directory to sys.path so we can import internal modules
current_dir = Path(__file__).resolve().parent
sys.path.append(str(current_dir))
sys.path.insert(0, str(current_dir.parent))

from research_core.producer_data import producer_data_root  # noqa: E402

try:
    from engine.backtest_engine import BacktestEngine
    from engine.broker import Broker
    from engine.data_loader import DataLoader
    from engine.strategy_base import StrategyBase
    from universe import UniverseError, resolve_codes
except ImportError as e:
    sys.stderr.write("Error: Could not import engine modules. Make sure you are running from the StockProject directory.\n")
    sys.stderr.write(f"Details: {e}\n")
    sys.exit(1)


def load_strategy_class(file_path: Path | str):
    """Dynamically load the strategy class from a Python file."""
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Strategy file not found: {file_path}")

    spec = importlib.util.spec_from_file_location("DynamicStrategy", str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for strategy file: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for name, obj in inspect.getmembers(module):
        if inspect.isclass(obj) and issubclass(obj, StrategyBase) and obj is not StrategyBase:
            return obj

    raise ImportError(f"No valid StrategyBase subclass found in {file_path}")


def load_strategy_params(params_json: str | None, params_file: str | None):
    """Load strategy params from inline JSON and/or a JSON file."""
    params = {}
    if params_file:
        path = Path(params_file)
        if not path.exists():
            raise FileNotFoundError(f"Strategy params file not found: {params_file}")
        params.update(json.loads(path.read_text(encoding="utf-8")))
    if params_json:
        params.update(json.loads(params_json))
    if not isinstance(params, dict):
        raise ValueError("Strategy params must decode to a JSON object")
    return params


def make_json_safe(value: Any):
    """Convert common backtest result objects into JSON-safe values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: make_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [make_json_safe(item) for item in value]
    return value


CAPITAL_MODE_PASSES = ("shared", "per_stock", "unconstrained")


def artifact_path(value: Any) -> str:
    path = Path(value)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path)


def count_trades(trades: list[dict[str, Any]], action: str | None):
    """Count trades by action name."""
    return sum(1 for trade in trades if trade.get("action") == action)


def calculate_max_drawdown(equity_curve: list[dict[str, Any]]):
    """Calculate maximum drawdown as a negative percentage."""
    peak = None
    max_drawdown = 0.0
    for point in equity_curve:
        equity = point["equity"]
        if peak is None or equity > peak:
            peak = equity
        if peak:
            drawdown = ((equity - peak) / peak) * 100
            max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown


def calculate_position_max_drawdown(equity_curve: list[dict[str, Any]]):
    """Calculate drawdown only while a symbol position is open."""
    peak = None
    max_drawdown = 0.0
    for point in equity_curve:
        equity = point["equity"]
        if equity <= 0:
            peak = None
            continue
        if peak is None or equity > peak:
            peak = equity
        if peak:
            drawdown = ((equity - peak) / peak) * 100
            max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown


def calculate_trade_stats(trades: list[dict]) -> dict:
    """Calculate closed-trade win stats and per-trade pnl statistics from broker trade logs."""
    positions: dict = {}
    cost_basis: dict = {}
    closed_trade_count = 0
    win_count = 0
    wins: list[float] = []
    losses: list[float] = []

    for trade in trades:
        code = trade.get("code")
        qty = trade.get("qty", 0)
        if trade.get("action") == "BUY":
            positions[code] = positions.get(code, 0) + qty
            cost_basis[code] = cost_basis.get(code, 0.0) - trade.get("total", 0.0)
        elif trade.get("action") == "SELL":
            current_qty = positions.get(code, 0)
            current_basis = cost_basis.get(code, 0.0)
            if current_qty <= 0:
                continue
            sold_basis = current_basis * (qty / current_qty)
            pnl = trade.get("total", 0.0) - sold_basis
            positions[code] = current_qty - qty
            cost_basis[code] = current_basis - sold_basis
            closed_trade_count += 1
            if pnl > 0:
                win_count += 1
                wins.append(pnl)
            else:  # pnl <= 0; break-even trades (pnl == 0) count as losses
                losses.append(pnl)
        elif trade.get("action") == "SPLIT":
            positions[code] = trade.get("new_qty", positions.get(code, 0))

    win_rate = (win_count / closed_trade_count) * 100 if closed_trade_count else None

    avg_win: float | None = sum(wins) / len(wins) if wins else None
    avg_loss: float | None = sum(losses) / len(losses) if losses else None
    gross_profit: float | None = sum(wins) if wins else None
    gross_loss: float | None = sum(losses) if losses else None
    payoff_ratio: float | None = avg_win / abs(avg_loss) if avg_win is not None and avg_loss else None
    profit_factor: float | None = gross_profit / abs(gross_loss) if gross_profit is not None and gross_loss else None
    expectancy: float | None = (sum(wins) + sum(losses)) / closed_trade_count if closed_trade_count else None
    largest_win: float | None = max(wins) if wins else None
    largest_loss: float | None = min(losses) if losses else None

    return {
        "closed_trade_count": closed_trade_count,
        "win_count": win_count,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff_ratio,
        "expectancy": expectancy,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "largest_win": largest_win,
        "largest_loss": largest_loss,
    }


def calculate_symbol_metrics(trades: list[dict[str, Any]], engine: Any, broker: Any):
    """Calculate per-symbol contribution and trade-quality metrics."""
    metrics: dict[str, dict[str, Any]] = {}
    positions: dict[str, int] = {}
    cost_basis: dict[str, float] = {}
    symbol_equity: dict[str, list[dict[str, object]]] = {code: [] for code in engine.data_cache}

    for trade in trades:
        code = trade.get("code")
        if not code:
            continue
        item = metrics.setdefault(
            code,
            {
                "buy_count": 0,
                "sell_count": 0,
                "dividend_count": 0,
                "closed_trade_count": 0,
                "win_count": 0,
                "realized_pnl": 0.0,
                "dividend_total": 0.0,
            },
        )
        qty = trade.get("qty", 0)
        if trade.get("action") == "BUY":
            item["buy_count"] += 1
            positions[code] = positions.get(code, 0) + qty
            cost_basis[code] = cost_basis.get(code, 0.0) - trade.get("total", 0.0)
        elif trade.get("action") == "SELL":
            item["sell_count"] += 1
            current_qty = positions.get(code, 0)
            current_basis = cost_basis.get(code, 0.0)
            if current_qty <= 0:
                continue
            sold_basis = current_basis * (qty / current_qty)
            pnl = trade.get("total", 0.0) - sold_basis
            item["realized_pnl"] += pnl
            item["closed_trade_count"] += 1
            if pnl > 0:
                item["win_count"] += 1
            positions[code] = current_qty - qty
            cost_basis[code] = current_basis - sold_basis
        elif trade.get("action") == "SPLIT":
            positions[code] = trade.get("new_qty", positions.get(code, 0))
        elif trade.get("action") == "DIVIDEND":
            item["dividend_count"] += 1
            item["dividend_total"] += trade.get("total", 0.0)

    replay_positions: dict[str, int] = {}
    trade_index = 0
    ordered_trades = sorted(trades, key=lambda item: str(item.get("date") or ""))
    for point in engine.price_curve:
        point_date = point["date"]
        while trade_index < len(ordered_trades) and ordered_trades[trade_index].get("date") <= point_date:
            trade = ordered_trades[trade_index]
            code_value = trade.get("code")
            if not code_value:
                trade_index += 1
                continue
            code = str(code_value)
            qty = trade.get("qty", 0)
            if trade.get("action") == "BUY":
                replay_positions[code] = replay_positions.get(code, 0) + qty
            elif trade.get("action") == "SELL":
                replay_positions[code] = replay_positions.get(code, 0) - qty
            elif trade.get("action") == "SPLIT":
                replay_positions[code] = trade.get("new_qty", replay_positions.get(code, 0))
            trade_index += 1

        for code, price in point["prices"].items():
            equity = replay_positions.get(code, 0) * price
            symbol_equity.setdefault(code, []).append({"date": point_date, "equity": equity})

    for code in set(engine.data_cache) | set(metrics) | set(broker.positions):
        item = metrics.setdefault(
            code,
            {
                "buy_count": 0,
                "sell_count": 0,
                "dividend_count": 0,
                "closed_trade_count": 0,
                "win_count": 0,
                "realized_pnl": 0.0,
                "dividend_total": 0.0,
            },
        )
        final_qty = broker.positions.get(code, 0)
        df = engine.data_cache.get(code)
        final_price = float(df.iloc[-1].get("RawClose", df.iloc[-1]["Close"])) if df is not None and not df.empty else None
        market_value = final_qty * final_price if final_price is not None else 0.0
        remaining_basis = cost_basis.get(code, 0.0)
        unrealized_pnl = market_value - remaining_basis
        closed_trade_count = item["closed_trade_count"]
        item.update({
            "trade_count": item["buy_count"] + item["sell_count"] + item["dividend_count"],
            "win_rate": (item["win_count"] / closed_trade_count) * 100 if closed_trade_count else None,
            "max_drawdown_rate": calculate_position_max_drawdown(symbol_equity.get(code, [])),
            "final_qty": final_qty,
            "final_price": final_price,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": item["realized_pnl"] + item["dividend_total"] + unrealized_pnl,
        })

    return dict(sorted(metrics.items()))


def benchmark_limitations(share_model: str):
    if share_model == "integer_shares":
        return [
            "Benchmark buys whole shares to approximate Taiwan odd-lot buy-and-hold accessibility.",
            "It does not model intraday odd-lot execution quality or same-day trading restrictions.",
            "It is not a trade execution model.",
        ]
    return [
        "Benchmark allows fractional shares for comparability.",
        "It does not model Taiwan odd-lot intraday restrictions or day-trading constraints.",
        "It is not a trade execution model.",
    ]


def filtered_stock_data(loader: Any, code: str | None, start_date: str | None = None, end_date: str | None = None):
    df = loader.get_stock_data(code, adjust=True)
    if df.empty:
        return df
    if start_date:
        df = df[df["Date"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["Date"] <= pd.to_datetime(end_date)]
    return df


def calculate_buy_and_hold(
    args: argparse.Namespace, code_list: list[str], loader: Any, broker: Any, share_model: str = "fractional_shares", name: str = "buy_and_hold"
):
    """Calculate a simple equal-allocation buy-and-hold benchmark."""
    if not code_list:
        return None

    allocation = args.cash / len(code_list)
    cash = args.cash
    positions = {}

    for code in code_list:
        df = filtered_stock_data(loader, code, args.start, args.end)
        if df is None or df.empty:
            continue
        first_close = float(df.iloc[0].get("SplitAdjustedClose", df.iloc[0]["Close"]))
        qty = allocation / (first_close * (1 + broker.fee_rate))
        if share_model == "integer_shares":
            qty = int(qty)
        elif share_model != "fractional_shares":
            raise ValueError(f"Unsupported share model: {share_model}")
        if qty <= 0:
            continue
        cost = first_close * qty
        fee = cost * broker.fee_rate
        cash -= cost + fee
        positions[code] = {
            "qty": qty,
            "first_close": first_close,
            "last_close": float(df.iloc[-1].get("SplitAdjustedClose", df.iloc[-1]["Close"])),
        }

    if not positions:
        return None

    dividend_total = 0.0
    div_df = getattr(loader, "_div_df", None)
    if div_df is not None:
        for code, position in positions.items():
            df = filtered_stock_data(loader, code, args.start, args.end)
            if df is None or df.empty:
                continue
            start_date = df.iloc[0]["Date"]
            end_date = df.iloc[-1]["Date"]
            code_divs = div_df[(div_df["Code"] == code) & (div_df["Date"] >= start_date) & (div_df["Date"] <= end_date)]
            dividend_total += float((code_divs["Dividends"] * position["qty"]).sum())

    final_value = cash + dividend_total
    for position in positions.values():
        final_value += position["qty"] * position["last_close"]

    total_pnl = final_value - args.cash
    return {
        "name": name,
        "share_model": share_model,
        "trading_limitations": benchmark_limitations(share_model),
        "final_value": final_value,
        "total_pnl": total_pnl,
        "return_rate": (total_pnl / args.cash) * 100,
        "dividend_total": dividend_total,
        "positions": positions,
    }


def add_symbol_benchmarks(symbol_metrics: dict[str, Any], args: argparse.Namespace, loader: Any, broker: Any):
    for code, metrics in symbol_metrics.items():
        benchmark = calculate_buy_and_hold(
            args,
            [code],
            loader,
            broker,
            share_model="fractional_shares",
            name="single_symbol_buy_and_hold",
        )
        odd_lot_benchmark = calculate_buy_and_hold(
            args,
            [code],
            loader,
            broker,
            share_model="integer_shares",
            name="single_symbol_odd_lot_buy_and_hold",
        )
        benchmark_return = benchmark["return_rate"] if benchmark else None
        odd_lot_return = odd_lot_benchmark["return_rate"] if odd_lot_benchmark else None
        metrics["buy_and_hold_return_rate"] = benchmark_return
        metrics["excess_return_rate"] = metrics["total_pnl"] / args.cash * 100 - benchmark_return if benchmark_return is not None else None
        metrics["odd_lot_buy_and_hold_return_rate"] = odd_lot_return
        metrics["odd_lot_excess_return_rate"] = metrics["total_pnl"] / args.cash * 100 - odd_lot_return if odd_lot_return is not None else None
    return symbol_metrics


def compute_partial_data_symbols(engine: Any, code_list: list[str], threshold: int) -> list[dict[str, Any]]:
    """Flag loaded symbols missing more trading days than `threshold`, relative to the
    union of dates other loaded symbols traded on within the same backtest window.

    Complements `missing_symbols` (data entirely absent) with data that is present but
    partially incomplete. Computed from `engine.data_cache` -- the window-trimmed frames
    the engine already loaded -- independent of the stock-data-downloader submodule's
    report file, since only the engine knows the requested backtest window.
    """
    calendar: set[Any] = set()
    for df in engine.data_cache.values():
        calendar.update(df["Date"].tolist())
    if not calendar:
        return []
    partial_data_symbols = []
    for code in code_list:
        df = engine.data_cache.get(code)
        if df is None:
            continue  # fully missing; already covered by missing_symbols
        dates_in_file = set(df["Date"].tolist())
        # Clamp to this symbol's own trading span so a late listing or early delisting
        # within the window isn't mistaken for missing data (mirrors
        # check_data_integrity.py's _check_symbol in the stock-data-downloader submodule).
        min_date, max_date = df["Date"].min(), df["Date"].max()
        expected_days = {d for d in calendar if min_date <= d <= max_date}
        gap_count = len(expected_days - dates_in_file)
        if gap_count > threshold:
            partial_data_symbols.append({"code": code, "missing_trading_day_count": gap_count})
    return partial_data_symbols


def build_summary(args: argparse.Namespace, code_list: list[str], strategy_cls: Any, broker: Any, engine: Any, results: dict[str, Any]):
    """Build the stable JSON contract consumed by research agents."""
    trades = broker.trades
    output_path = artifact_path(args.output) if args.output else None
    raw_data_path = Path(args.data_path) if args.data_path else Path("/app/data/processed")
    data_path = artifact_path(raw_data_path)
    strategy_path = artifact_path(args.strategy)
    missing_symbols = [code for code in code_list if code not in engine.data_cache]
    partial_data_gap_threshold = getattr(args, "partial_data_gap_threshold", DEFAULT_PARTIAL_DATA_GAP_THRESHOLD)
    partial_data_symbols = compute_partial_data_symbols(engine, code_list, partial_data_gap_threshold)
    trade_stats = calculate_trade_stats(trades)
    market_benchmark = calculate_buy_and_hold(
        args,
        [args.benchmark_code],
        engine.loader,
        broker,
        name="market_buy_and_hold",
    )
    stock_pool_buy_and_hold = calculate_buy_and_hold(
        args,
        code_list,
        engine.loader,
        broker,
        name="stock_pool_equal_allocation_buy_and_hold",
    )
    odd_lot_stock_pool_buy_and_hold = calculate_buy_and_hold(
        args,
        code_list,
        engine.loader,
        broker,
        share_model="integer_shares",
        name="stock_pool_odd_lot_equal_allocation_buy_and_hold",
    )
    benchmark_return = market_benchmark["return_rate"] if market_benchmark else None
    stock_pool_return = stock_pool_buy_and_hold["return_rate"] if stock_pool_buy_and_hold else None
    odd_lot_stock_pool_return = odd_lot_stock_pool_buy_and_hold["return_rate"] if odd_lot_stock_pool_buy_and_hold else None
    symbol_metrics = add_symbol_benchmarks(calculate_symbol_metrics(trades, engine, broker), args, engine.loader, broker)
    warnings = [f"No loaded price data for requested symbol: {code}" for code in missing_symbols]
    warnings += [
        f"Loaded price data for {item['code']} is missing {item['missing_trading_day_count']} trading day(s) within the requested window"
        for item in partial_data_symbols
    ]
    if market_benchmark is None or not market_benchmark.get("positions"):
        warnings.append(f"No benchmark price data for market benchmark symbol: {args.benchmark_code}")

    max_dd = calculate_max_drawdown(engine.equity_curve)
    calmar_ratio = results["return_rate"] / abs(max_dd) if max_dd and max_dd != 0 else None
    return_rate = results["return_rate"]
    excess_return_rate = return_rate - benchmark_return if benchmark_return is not None else None
    benchmark_excess_return_rate = return_rate - benchmark_return if benchmark_return is not None else None
    stock_pool_excess_return_rate = return_rate - stock_pool_return if stock_pool_return is not None else None
    odd_lot_stock_pool_excess_return_rate = return_rate - odd_lot_stock_pool_return if odd_lot_stock_pool_return is not None else None
    if args.capital_mode == "unconstrained":
        return_rate = None
        max_dd = None
        calmar_ratio = None
        excess_return_rate = None
        benchmark_excess_return_rate = None
        stock_pool_excess_return_rate = None
        odd_lot_stock_pool_excess_return_rate = None
        for metrics in symbol_metrics.values():
            metrics["excess_return_rate"] = None
            metrics["odd_lot_excess_return_rate"] = None
    run = {
        "run_id": datetime.now().strftime("%Y%m%d%H%M%S"),
        "codes": code_list,
        "universe": getattr(args, "universe_name", None),
        "start": args.start,
        "end": args.end,
        "initial_cash": args.cash,
        "capital_mode": args.capital_mode,
        "output_path": output_path,
    }
    if args.capital_mode == "per_stock":
        run["per_stock_initial_cash"] = broker.per_stock_initial_cash

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "run": run,
        "strategy": {
            "name": strategy_cls.__name__,
            "path": strategy_path,
            "params": args.strategy_params,
        },
        "data": {
            "path": data_path,
            "price_file": artifact_path(raw_data_path / "price_daily.parquet"),
            "dividend_file": artifact_path(raw_data_path / "dividends.parquet"),
        },
        "metrics": {
            "final_value": results["final_value"],
            "total_pnl": results["total_pnl"],
            "return_rate": return_rate,
            "trade_count": len(trades),
            "cash_blocked_entry_count": getattr(broker, "cash_blocked_entry_count", 0),
            "buy_count": count_trades(trades, "BUY"),
            "sell_count": count_trades(trades, "SELL"),
            "dividend_count": count_trades(trades, "DIVIDEND"),
            "split_count": count_trades(trades, "SPLIT"),
            "closed_trade_count": trade_stats["closed_trade_count"],
            "win_count": trade_stats["win_count"],
            "win_rate": trade_stats["win_rate"],
            "avg_win": trade_stats["avg_win"],
            "avg_loss": trade_stats["avg_loss"],
            "payoff_ratio": trade_stats["payoff_ratio"],
            "expectancy": trade_stats["expectancy"],
            "gross_profit": trade_stats["gross_profit"],
            "gross_loss": trade_stats["gross_loss"],
            "profit_factor": trade_stats["profit_factor"],
            "largest_win": trade_stats["largest_win"],
            "largest_loss": trade_stats["largest_loss"],
            "max_drawdown_rate": max_dd,
            "calmar_ratio": calmar_ratio,
            "buy_and_hold_return_rate": benchmark_return,
            "excess_return_rate": excess_return_rate,
            "benchmark_return_rate": benchmark_return,
            "benchmark_excess_return_rate": benchmark_excess_return_rate,
            "stock_pool_buy_and_hold_return_rate": stock_pool_return,
            "stock_pool_excess_return_rate": stock_pool_excess_return_rate,
            "odd_lot_stock_pool_buy_and_hold_return_rate": odd_lot_stock_pool_return,
            "odd_lot_stock_pool_excess_return_rate": odd_lot_stock_pool_excess_return_rate,
        },
        "benchmark": {
            "market": market_benchmark,
            "stock_pool_equal_allocation": stock_pool_buy_and_hold,
            "odd_lot_stock_pool_equal_allocation": odd_lot_stock_pool_buy_and_hold,
            "method": "Portfolio-level benchmark uses the configured benchmark symbol buy-and-hold. Stock-pool buy-and-hold is kept as a reference only. Single-symbol benchmark fields compare each symbol's strategy result against that same symbol's buy-and-hold.",
            "benchmark_code": args.benchmark_code,
        },
        "price_policy": {
            "name": "corporate_action_aware_v2",
            "raw_price_usage": "execution_cash_positions_pnl",
            "signal_price_usage": "strategy_on_bar",
            "split_policy": "permanent_signal_price_adjustment",
            "dividend_signal_window_days": 5,
            "dividend_window_exit": "fill_recovery",
            "corporate_action_db_path": str(engine.loader.corporate_action_db) if engine.loader.corporate_action_db else None,
            "unsupported_corporate_action_warnings": engine.loader.get_warnings(),
        },
        "symbols": symbol_metrics,
        "partial_data_symbols": partial_data_symbols,
        "portfolio": {
            "cash": broker.cash,
            "positions": broker.positions,
            "equity_curve": engine.equity_curve,
        },
        "trades": trades,
        "warnings": warnings + engine.loader.get_warnings(),
    }


def build_capital_mode_comparison(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build a thin comparison artifact from full per-mode summaries."""
    headline_keys = ["return_rate", "max_drawdown_rate", "win_rate", "payoff_ratio", "expectancy", "cash_blocked_entry_count"]
    modes = {}
    for mode in CAPITAL_MODE_PASSES:
        summary = summaries.get(mode, {})
        metrics = summary.get("metrics", {})
        modes[mode] = {key: metrics.get(key) for key in headline_keys}

    symbols: dict[str, dict[str, Any]] = {}
    all_symbols = set(summaries.get("shared", {}).get("symbols", {})) | set(summaries.get("per_stock", {}).get("symbols", {}))
    for code in sorted(all_symbols):
        shared_pnl = summaries.get("shared", {}).get("symbols", {}).get(code, {}).get("total_pnl")
        per_stock_pnl = summaries.get("per_stock", {}).get("symbols", {}).get(code, {}).get("total_pnl")
        contention_affected = shared_pnl is not None and per_stock_pnl is not None and shared_pnl < 0 <= per_stock_pnl
        symbols[code] = {
            "shared_total_pnl": shared_pnl,
            "per_stock_total_pnl": per_stock_pnl,
            "contention_affected": contention_affected,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "modes": modes,
        "symbols": symbols,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(make_json_safe(payload), indent=4), encoding="utf-8")


def write_comparison_artifacts(output_path: Path, summaries: dict[str, dict[str, Any]]) -> None:
    """Write Option-A comparison artifacts next to the requested output path."""
    root = output_path.parent
    write_json(root / "summary_shared.json", summaries["shared"])
    write_json(root / "summary_per_stock.json", summaries["per_stock"])
    write_json(root / "summary_unconstrained.json", summaries["unconstrained"])
    write_json(root / "comparison.json", build_capital_mode_comparison(summaries))
    write_json(output_path, summaries["shared"])


def build_universe_comparison(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build a thin comparison artifact across universes (Option-A pattern)."""
    headline_keys = ["return_rate", "max_drawdown_rate", "win_rate", "payoff_ratio", "expectancy", "cash_blocked_entry_count"]
    universes = {}
    for name, summary in summaries.items():
        metrics = summary.get("metrics", {})
        universes[name] = {key: metrics.get(key) for key in headline_keys}
        universes[name]["codes"] = summary.get("run", {}).get("codes", [])

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "universes": universes,
    }


def write_universe_comparison_artifacts(output_path: Path, summaries: dict[str, dict[str, Any]], default_universe: str) -> None:
    """Write Option-A comparison artifacts across universes next to the requested output path."""
    root = output_path.parent
    for name, summary in summaries.items():
        write_json(root / f"summary_{name}.json", summary)
    write_json(root / "comparison.json", build_universe_comparison(summaries))
    write_json(output_path, summaries[default_universe])


def run_backtest_pass(args: argparse.Namespace, code_list: list[str], loader: Any, strategy_cls: Any, capital_mode: str) -> dict[str, Any] | None:
    pass_args = argparse.Namespace(**vars(args))
    pass_args.capital_mode = capital_mode
    broker = Broker(initial_cash=args.cash, capital_mode=capital_mode, codes=code_list)
    engine = BacktestEngine(broker, loader)
    results = engine.run(
        code_list=code_list,
        strategy_class=strategy_cls,
        start_date=args.start,
        end_date=args.end,
        strategy_context=args.strategy_params,
    )
    if not results:
        return None
    return build_summary(pass_args, code_list, strategy_cls, broker, engine, results)


def main():
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO, format="%(message)s")
    logger = _logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Nightly Strategy Factory: Backtest CLI")
    parser.add_argument("--strategy", required=True, help="Path to the strategy .py file")
    parser.add_argument("--codes", default=None, help="Comma-separated stock codes (e.g., 2330,2454) or @universe-name")
    parser.add_argument(
        "--universes",
        default=None,
        help="Comma-separated universe names to run and compare in one invocation (e.g. semiconductor,core_blue_chips)",
    )
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
    parser.add_argument(
        "--partial-data-gap-threshold",
        type=int,
        default=DEFAULT_PARTIAL_DATA_GAP_THRESHOLD,
        help="Trading-day gap count above which a loaded symbol is flagged in partial_data_symbols",
    )
    parser.add_argument(
        "--data-path",
        default=None,
        help="Directory containing price_daily.parquet and dividends.parquet",
    )
    parser.add_argument("--output", help="Path to save result JSON")
    parser.add_argument("--params-json", default=None, help="Inline strategy params JSON object")
    parser.add_argument("--params-file", default=None, help="Path to a strategy params JSON file")

    args = parser.parse_args()
    if args.data_path is None:
        try:
            args.data_path = str(producer_data_root())
        except (ValueError, FileNotFoundError) as e:
            logger.error("[!] %s", e)
            sys.exit(1)
    metadata_args = {"symbol_meta_db": Path(args.data_path) / "symbol_meta.sqlite"} if args.data_path else {}
    try:
        args.strategy_params = load_strategy_params(args.params_json, args.params_file)
    except Exception as e:
        logger.error("[!] Failed to load strategy params: %s", e)
        sys.exit(1)

    if bool(args.codes) == bool(args.universes):
        logger.error("[!] Exactly one of --codes or --universes must be provided.")
        sys.exit(1)
    if args.universes and args.capital_mode == "all":
        logger.error("[!] --capital-mode all cannot be combined with --universes in one invocation.")
        sys.exit(1)

    # 1. Setup Environment
    universe_names: list[str] = []
    code_list: list[str] = []
    if args.universes:
        universe_names = [name.strip() for name in args.universes.split(",") if name.strip()]
        if not universe_names:
            logger.error("[!] --universes must contain at least one universe name.")
            sys.exit(1)
        logger.info("[*] Initializing Backtest for universes: %s", universe_names)
    else:
        try:
            code_list, universe_name = resolve_codes(args.codes, **metadata_args)
        except UniverseError as e:
            logger.error("[!] %s", e)
            sys.exit(1)
        args.universe_name = universe_name
        logger.info("[*] Initializing Backtest for codes: %s", code_list)

    # 2. Load Data
    loader = DataLoader(data_path=args.data_path) if args.data_path else DataLoader()
    loader.load_all()  # In a real CLI, we might want to load only needed codes to save time
    if loader._price_df is None:
        data_hint = args.data_path or "/app/data/processed"
        logger.error("[!] No price_daily.parquet found under data path: %s", data_hint)
        sys.exit(1)

    # 3. Setup Strategy
    try:
        strategy_cls = load_strategy_class(args.strategy)
        logger.info("[*] Loaded strategy: %s", strategy_cls.__name__)
    except Exception as e:
        logger.error("[!] Failed to load strategy: %s", e)
        sys.exit(1)

    # 4. Run Backtest
    logger.info("[*] Running engine from %s to %s...", args.start, args.end or "Latest")
    universe_summaries: dict[str, dict[str, Any]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    summary: dict[str, Any]
    if universe_names:
        for universe_name in universe_names:
            try:
                universe_code_list, _ = resolve_codes(f"@{universe_name}", **metadata_args)
            except UniverseError as e:
                logger.error("[!] %s", e)
                sys.exit(1)
            args.universe_name = universe_name
            universe_summary = run_backtest_pass(args, universe_code_list, loader, strategy_cls, args.capital_mode)
            if universe_summary is None:
                logger.error("[!] Backtest returned no results for universe %s. Check codes, date range, and data availability.", universe_name)
                sys.exit(1)
            universe_summaries[universe_name] = universe_summary
        summary = universe_summaries[universe_names[0]]
    elif args.capital_mode == "all":
        for mode in CAPITAL_MODE_PASSES:
            mode_summary = run_backtest_pass(args, code_list, loader, strategy_cls, mode)
            if mode_summary is None:
                logger.error("[!] Backtest returned no results for %s. Check codes, date range, and data availability.", mode)
                sys.exit(1)
            summaries[mode] = mode_summary
        summary = summaries["shared"]
    else:
        result = run_backtest_pass(args, code_list, loader, strategy_cls, args.capital_mode)
        if result is None:
            logger.error("[!] Backtest returned no results. Check codes, date range, and data availability.")
            sys.exit(1)
        summary = result

    # 5. Output Results
    logger.info("\n" + "=" * 30)
    logger.info("BACKTEST RESULTS: %s", strategy_cls.__name__)
    return_rate = summary["metrics"]["return_rate"]
    max_drawdown_rate = summary["metrics"]["max_drawdown_rate"]
    logger.info("Return Rate: %s", "n/a" if return_rate is None else f"{return_rate:.2f}%")
    logger.info("Max DD:      %s", "n/a" if max_drawdown_rate is None else f"{max_drawdown_rate:.2f}%")
    if summary["metrics"]["win_rate"] is not None:
        logger.info("Win Rate:    %.2f%%", summary["metrics"]["win_rate"])
    logger.info("Total PnL:   $%s", f"{summary['metrics']['total_pnl']:,.0f}")
    logger.info("Final Value: $%s", f"{summary['metrics']['final_value']:,.0f}")
    logger.info("Trades:      %s", summary["metrics"]["trade_count"])
    logger.info("=" * 30)

    if args.output:
        output_path = Path(args.output)
        if universe_names:
            write_universe_comparison_artifacts(output_path, universe_summaries, default_universe=universe_names[0])
        elif args.capital_mode == "all":
            write_comparison_artifacts(output_path, summaries)
        else:
            write_json(output_path, summary)
        logger.info("[*] Results saved to %s", args.output)


if __name__ == "__main__":
    main()
