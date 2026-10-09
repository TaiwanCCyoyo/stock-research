from __future__ import annotations

# ruff: noqa: E501
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from research_core.producer_data import producer_data_root

REPO_ROOT = Path(__file__).resolve().parents[1]
SYMBOL_MAPPING_PATH = producer_data_root() / "stock_symbol_mapping.json5"

FIELD_LABELS = {
    "rank": "排名",
    "code": "股票",
    "stock": "股票",
    "total_pnl": "損益",
    "pnl": "損益",
    "max_drawdown_rate": "最大回撤",
    "max_dd": "最大回撤",
    "trade_count": "交易次數",
    "trades": "交易次數",
    "win_rate": "勝率",
    "final_qty": "期末股數",
    "price": "成交價",
    "qty": "股數",
    "total": "交易總額",
    "action": "動作",
    "date": "日期",
    "trade_id": "交易 ID",
    "signal_reason": "訊號原因",
}

FIELD_HELP = {
    "rank": "依個股累計損益由高到低排列，用來快速找出主要貢獻與拖累來源。",
    "stock": "回測股票代號與名稱。",
    "total_pnl": "已實現與回測紀錄中的個股累計損益，正數代表這檔股票對策略有貢獻，負數代表拖累。",
    "pnl": "已實現與回測紀錄中的個股累計損益，正數代表這檔股票對策略有貢獻，負數代表拖累。",
    "max_drawdown_rate": "該股票在回測期間從高點往下回落的最大幅度，用來看曾經承受多少浮動風險。",
    "max_dd": "該股票在回測期間從高點往下回落的最大幅度，用來看曾經承受多少浮動風險。",
    "trade_count": "這檔股票發生的買進、賣出與部分賣出紀錄數量；越高代表策略越頻繁進出。",
    "trades": "這檔股票發生的買進、賣出與部分賣出紀錄數量；越高代表策略越頻繁進出。",
    "win_rate": "已結束交易中賺錢交易的比例；沒有完成交易時會顯示 n/a。",
    "final_qty": "回測結束時仍持有的股數。",
}

ACTION_LABELS = {
    "BUY": "買進",
    "SELL": "賣出",
    "DIVIDEND": "股利",
}

SIGNAL_REASON_LABELS = {
    "ma_convergence": "均線收斂",
    "ma_convergence_price_strength": "均線收斂後價格轉強",
    "bottom_2b": "底部 2B 收復",
    "bottom_2b_ma_convergence": "底部 2B 收復且均線收斂",
    "bottom_2b_add": "底部 2B 收復，加碼",
    "top_2b": "頂部 2B 反轉",
    "top_2b_exit": "頂部 2B 反轉，全部出場",
    "stop_loss_exit": "觸發停損，全部出場",
    "ma_break_partial_exit": "跌破出場均線，部分賣出",
}

SIGNAL_PRICE_POLICY_LABELS = {
    "raw": "原始價",
    "split_adjusted": "分割調整價",
    "cash_dividend_window": "除息短期還原價",
}

CORPORATE_ACTION_LABELS = {
    "CASH_DIVIDEND": "現金股利",
    "STOCK_DIVIDEND": "股票股利",
    "EX_RIGHT": "除權",
    "ETF_SPLIT": "ETF 分割",
    "ETF_REVERSE_SPLIT": "ETF 反分割",
    "CASH_CAPITAL_REDUCTION": "現金減資",
    "LOSS_OFFSET_CAPITAL_REDUCTION": "彌補虧損減資",
    "CAPITAL_REDUCTION": "減資",
}


def field_label(key: str):
    return FIELD_LABELS.get(str(key), str(key))


def field_help(key: str):
    return FIELD_HELP.get(str(key), "")


def action_label(action: str):
    value = str(action or "").upper()
    return ACTION_LABELS.get(value, value or "n/a")


def signal_reason_label(reason: str):
    value = str(reason or "").strip()
    if not value:
        return "未記錄"
    if value in SIGNAL_REASON_LABELS:
        return SIGNAL_REASON_LABELS[value]
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) > 1:
        return " + ".join(SIGNAL_REASON_LABELS.get(part, part.replace("_", " ")) for part in parts)
    return value.replace("_", " ")


def signal_price_policy_label(policy: str):
    value = str(policy or "").strip()
    return SIGNAL_PRICE_POLICY_LABELS.get(value, value.replace("_", " ") if value else "未記錄")


def corporate_action_label(action: str):
    value = str(action or "").upper()
    return CORPORATE_ACTION_LABELS.get(value, value.replace("_", " ") if value else "無")


def corporate_action_labels(actions: list[Any] | str | None):
    if not actions:
        return "無"
    if isinstance(actions, str):
        actions = [a.strip() for a in actions.split(",") if a.strip()]
    return "、".join(corporate_action_label(action) for action in actions)


@lru_cache(maxsize=1)
def stock_names():
    if not SYMBOL_MAPPING_PATH.is_file():
        return {}
    text = SYMBOL_MAPPING_PATH.read_text(encoding="utf-8", errors="ignore")
    pattern = re.compile(r'"([0-9A-Z]{4,6})"\s*:\s*"([^"]*)"')
    return {code: name for code, name in pattern.findall(text)}


def stock_name(code: str):
    return stock_names().get(str(code), "")


def stock_label(code: str):
    code_text = str(code)
    name = stock_name(code_text)
    return f"{code_text} {name}" if name else code_text
