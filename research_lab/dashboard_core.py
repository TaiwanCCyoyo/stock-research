from __future__ import annotations

# ruff: noqa: E501
import json
import re
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pandas as pd

from research_lab.display import action_label, field_help, field_label, stock_label, stock_names

# Keep historical imports stable without loading the optional static renderer
# for the HTTP viewer, task catalog or pure presentation helpers.
if TYPE_CHECKING:
    import panel as pn

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_ROOT = REPO_ROOT / "tasks"
SITE_ROOT = REPO_ROOT / "research_lab" / "site"

TXT = {
    "app_title": "本地策略研究 Dashboard",
    "subtitle": "用本地互動頁檢查策略規則、績效、交易與 K 線驗算。",
    "research_tasks": "研究任務",
    "latest_task": "最新任務",
    "return": "報酬",
    "benchmark": "基準",
    "gap": "差距",
    "max_dd": "最大回撤",
    "win_rate": "勝率",
    "trades": "交易次數",
    "final_value": "最終淨值",
    "equity": "淨值",
    "drawdown": "回撤",
    "stock_ranking": "個股排名",
    "field_help": "欄位說明",
    "key_trades": "關鍵交易",
    "trade_drilldown": "交易驗算",
    "artifacts": "本地 Artifacts",
    "task_select": "選擇任務",
    "symbol_select": "選擇股票",
    "trade_select": "選擇交易",
    "all_symbols": "全部股票",
    "no_tasks": "沒有可用的研究任務。",
    "open_detail": "打開詳細 Dashboard",
    "health_check": "策略體檢",
    "expectancy": "期望值/筆",
    "payoff_ratio": "盈虧比",
    "profit_factor": "Profit Factor",
    "calmar": "Calmar Ratio",
}

CSS = """
:root {
  --stock-bg: #f7f9fc;
  --stock-panel: #ffffff;
  --stock-border: #d8dee8;
  --stock-ink: #111827;
  --stock-muted: #4b5563;
  --stock-accent: #0f766e;
  --stock-accent-soft: #e6f4f1;
}
.bk-Column, .bk-Row { letter-spacing: 0; }
.dashboard-hero {
  background: #ffffff;
  color: var(--stock-ink);
  border: 1px solid var(--stock-border);
  border-left: 6px solid var(--stock-accent);
  border-radius: 8px;
  padding: 18px 22px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
}
.dashboard-hero h1 { margin: 0 0 6px; font-size: 30px; letter-spacing: 0; }
.dashboard-hero p { margin: 0; color: var(--stock-muted); line-height: 1.6; }
.capital-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--stock-panel);
  border: 1px solid var(--stock-border);
  border-radius: 8px;
  overflow: hidden;
  font-size: 14px;
}
.capital-table th {
  background: var(--stock-accent-soft);
  color: var(--stock-ink);
  text-align: left;
  padding: 10px 14px;
  font-weight: 600;
  border-bottom: 2px solid var(--stock-accent);
  white-space: nowrap;
}
.capital-table td {
  padding: 9px 14px;
  color: var(--stock-ink);
  border-bottom: 1px solid var(--stock-border);
  white-space: nowrap;
}
.capital-table tbody tr:nth-child(even) { background: var(--stock-bg); }
.capital-table tbody tr:hover { background: var(--stock-accent-soft); }
.capital-table td:first-child { font-weight: 600; }
.metric-card {
  background: var(--stock-panel);
  border: 1px solid var(--stock-border);
  border-radius: 8px;
  padding: 14px 16px;
  min-height: 82px;
  overflow: visible;
}
.bk-GridBox { overflow: visible !important; }
.explain-card {
  background: #ffffff;
  border: 1px solid var(--stock-border);
  border-radius: 8px;
  padding: 14px 16px;
}
.metric-card .label { color: var(--stock-muted); font-size: 13px; }
.metric-card .value { color: var(--stock-ink); font-size: 24px; font-weight: 700; margin-top: 6px; }
.metric-tooltip {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  margin-left: 6px;
  border-radius: 50%;
  border: 1px solid var(--stock-border);
  color: var(--stock-muted);
  font-size: 12px;
  font-weight: 700;
  cursor: help;
}
.metric-tooltip:hover::after {
  content: attr(data-tip);
  position: absolute;
  z-index: 2147483647;
  left: 0;
  bottom: 145%;
  transform: none;
  width: 280px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #111827;
  color: #ffffff;
  font-size: 13px;
  font-weight: 400;
  line-height: 1.55;
  box-shadow: 0 12px 28px rgba(17, 24, 39, 0.22);
  white-space: normal;
}
.metric-tooltip:hover::before {
  content: "";
  position: absolute;
  left: 9px;
  bottom: 118%;
  transform: none;
  border: 7px solid transparent;
  border-top-color: #111827;
}
.task-card {
  background: #ffffff;
  border: 1px solid var(--stock-border);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 10px;
}
.task-card h3 { margin: 0 0 8px; font-size: 18px; letter-spacing: 0; }
.task-card p { color: var(--stock-muted); margin: 0 0 10px; line-height: 1.55; }
.artifact-links a, .task-card a {
  display: inline-block;
  color: #155e75;
  background: #ecfeff;
  border: 1px solid #a5f3fc;
  border-radius: 6px;
  padding: 7px 10px;
  text-decoration: none;
  margin: 0 8px 8px 0;
}
.warning-card {
  background: #fffbeb;
  border: 1px solid #fbbf24;
  border-radius: 8px;
  color: #78350f;
  padding: 12px 14px;
}
.social-more {
  background: #ffffff;
  border: 1px solid var(--stock-border);
  border-radius: 8px;
  padding: 14px 16px;
}
.social-more summary {
  color: #155e75;
  cursor: pointer;
  font-weight: 700;
  list-style: none;
  margin-top: 4px;
  width: fit-content;
}
.social-more summary::-webkit-details-marker { display: none; }
.social-more summary::after { content: " ..."; }
.social-more[open] summary::after { content: ""; }
.social-more-content {
  border-top: 1px solid var(--stock-border);
  margin-top: 12px;
  padding-top: 12px;
  white-space: normal;
  line-height: 1.7;
}
.social-more-content h3 {
  font-size: 16px;
  margin: 14px 0 8px;
}
.social-more-content p {
  margin: 0 0 10px;
}
.social-more-content ul {
  margin: 0 0 12px 20px;
  padding: 0;
}
.social-more-content li {
  margin: 0 0 6px;
}
"""


def read_json(path: Path, default: Any = None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path, default: str = ""):
    if not path.is_file():
        return default
    return path.read_text(encoding="utf-8")


def task_title(task_id: str):
    title = read_text(task_root(task_id) / "research_dashboard" / "title.txt").strip()
    return title or task_id


def task_data_snapshot(task_id: str):
    return read_json(task_root(task_id) / "research_dashboard" / "data_snapshot.json", {})


def latest_data_date(task_id: str, summary: dict[str, Any]):
    snapshot = task_data_snapshot(task_id)
    if snapshot.get("latest_price_date"):
        return snapshot["latest_price_date"]
    return summary.get("run", {}).get("end") or "n/a"


def task_subtitle(task_id: str, summary: dict[str, Any]):
    run = summary.get("run", {})
    codes = run.get("codes", [])
    return f"期間：{run.get('start', 'n/a')} 至 {latest_data_date(task_id, summary)}，股票池：{len(codes)} 檔"


def safe_slug(value: Any):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-") or "task"


def task_root(task_id: str):
    return TASKS_ROOT / task_id


def site_relative(path: Path):
    return Path("..") / ".." / path.relative_to(REPO_ROOT)


def fmt_num(value: Any, digits: int = 0):
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):,.{digits}f}"


def fmt_pct(value: Any):
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):,.2f}%"


def fmt_pct_value(value: Any) -> str:
    """Format a percentage with 3 decimal places (e.g. convergence_pct display)."""
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):,.3f}%"


def fmt_ratio(value: float | None) -> str:
    """Format a ratio with two decimal places and an 'x' suffix (e.g. 2.50x)."""
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.2f}x"


def strategy_health_verdict(payoff_ratio: float | None, expectancy: float | None) -> str:
    """Return a one-line verdict string assessing the win-big-lose-small philosophy."""
    if payoff_ratio is None and expectancy is None:
        return "不適用（無已結束交易）"
    if expectancy is not None and expectancy > 0:
        if payoff_ratio is None:
            return "期望值正，盈虧比資料不足"
        if payoff_ratio >= 2:
            return "✓ 符合大賺小賠"
        if 1 <= payoff_ratio < 2:
            return "期望值正，盈虧比未達 2"
        if payoff_ratio < 1:
            return "⚠ 期望值正但盈虧比 < 1"
    if expectancy is not None and expectancy <= 0:
        if payoff_ratio is not None and payoff_ratio < 1:
            return "✗ 小賺大賠，與目標相反"
        return "⚠ 期望值為負"
    return "n/a"


def strategy_health_rows(summary: dict) -> dict:
    """Compute formatted health-check values from a task summary dict."""
    expectancy = metric(summary, "expectancy")
    payoff_ratio = metric(summary, "payoff_ratio")
    profit_factor = metric(summary, "profit_factor")
    calmar = metric(summary, "calmar_ratio")
    avg_win = metric(summary, "avg_win")
    avg_loss = metric(summary, "avg_loss")
    largest_win = metric(summary, "largest_win")
    largest_loss = metric(summary, "largest_loss")
    closed_trade_count = metric(summary, "closed_trade_count")

    # Calmar fallback: compute from return_rate / abs(max_drawdown_rate)
    if calmar is None:
        return_rate = metric(summary, "return_rate")
        max_dd = metric(summary, "max_drawdown_rate")
        if return_rate is not None and max_dd is not None and max_dd != 0:
            # Simplified Calmar: total return / abs(max_drawdown), not annualized
            calmar = return_rate / abs(max_dd)

    return {
        "expectancy_fmt": fmt_num(expectancy, digits=0),
        "payoff_ratio_fmt": fmt_ratio(payoff_ratio),
        "profit_factor_fmt": fmt_ratio(profit_factor),
        "calmar_fmt": fmt_ratio(calmar),
        "avg_win_fmt": fmt_num(avg_win, digits=0),
        "avg_loss_fmt": fmt_num(avg_loss, digits=0),
        "largest_win_fmt": fmt_num(largest_win, digits=0),
        "largest_loss_fmt": fmt_num(largest_loss, digits=0),
        "closed_trade_count": closed_trade_count if closed_trade_count is not None else 0,
        "verdict": strategy_health_verdict(payoff_ratio, expectancy),
    }


def metric(summary: dict[str, Any], key: str):
    return summary.get("metrics", {}).get(key)


def discover_tasks():
    if not TASKS_ROOT.is_dir():
        return []
    rows = []
    for path in TASKS_ROOT.iterdir():
        if not path.is_dir() or not (path / "summary.json").is_file():
            continue
        summary = read_json(path / "summary.json", {})
        rows.append({
            "task": path.name,
            "path": path,
            "summary": summary,
            "mtime": path.stat().st_mtime,
            "return_rate": metric(summary, "return_rate"),
            "benchmark_return": metric(summary, "buy_and_hold_return_rate"),
            "max_drawdown_rate": metric(summary, "max_drawdown_rate"),
            "trade_count": metric(summary, "trade_count"),
            "win_rate": metric(summary, "win_rate"),
        })
    return sorted(rows, key=lambda item: (item["mtime"], item["task"]), reverse=True)


def discover_task_index():
    """List available tasks without parsing any summary.json.

    Rebuilt from the directory listing on every call, so new or removed task
    directories are always reflected. Use load_task_summary/load_task_bundle
    for the selected task's content.
    """
    if not TASKS_ROOT.is_dir():
        return []
    rows = []
    for path in TASKS_ROOT.iterdir():
        if not path.is_dir() or not (path / "summary.json").is_file():
            continue
        rows.append({"task": path.name, "path": path, "mtime": path.stat().st_mtime, "title": task_title(path.name)})
    return sorted(rows, key=lambda item: (item["mtime"], item["task"]), reverse=True)


def load_task_summary(task_id: str):
    """Load only the selected task's summary.json."""
    return read_json(task_root(task_id) / "summary.json", {})


def bundle_stock_codes(bundle: dict[str, Any]):
    """Union of stock codes referenced anywhere in a task bundle."""
    codes: set[str] = set()
    for summary in [bundle.get("summary", {}), *bundle.get("mode_summaries", {}).values()]:
        codes.update(summary.get("run", {}).get("codes") or [])
        codes.update(trade.get("code") for trade in summary.get("trades", []) if trade.get("code"))
    codes.update(row.get("code") for row in bundle.get("rankings", {}).get("stocks", []) if row.get("code"))
    codes.update(event.get("code") for event in bundle.get("events", {}).get("events", []) if event.get("code"))
    return codes


def bundle_stock_names(bundle: dict[str, Any]):
    """Code -> name for the bundle's referenced codes, using the current name snapshot."""
    names = stock_names()
    return {code: names[code] for code in sorted(bundle_stock_codes(bundle)) if code in names}


SYMBOL_META_DB = REPO_ROOT / "shioaji_stock_prices" / "data" / "symbol_meta.sqlite"


def symbol_classification(codes: Any, db_path: Path = SYMBOL_META_DB) -> dict[str, str | None]:
    """Code -> industry_category for the given codes; {} when no classification data is available."""
    code_list = [str(code) for code in codes if code]
    if not code_list or not db_path.is_file():
        return {}
    placeholders = ",".join("?" for _ in code_list)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT code, industry_category FROM symbol_meta WHERE code IN ({placeholders})",
            code_list,
        ).fetchall()
    return dict(rows)


def rankings_with_classification(rankings: dict[str, Any], db_path: Path = SYMBOL_META_DB) -> dict[str, Any]:
    """Attach industry_category to each ranking row when classification data is available."""
    stocks = rankings.get("stocks", [])
    classification = symbol_classification((row.get("code") for row in stocks), db_path)
    enriched_stocks = [{**row, "industry_category": classification.get(row.get("code"))} for row in stocks]
    return {**rankings, "stocks": enriched_stocks}


def load_task_bundle(task_id: str):
    root = task_root(task_id)
    summary = read_json(root / "summary.json", {})
    mode_summaries = {mode: read_json(root / f"summary_{mode}.json", None) for mode in ("shared", "per_stock", "unconstrained")}
    bundle = {
        "task": task_id,
        "root": root,
        "title": task_title(task_id),
        "summary": summary,
        "mode_summaries": {mode: item for mode, item in mode_summaries.items() if item},
        "rankings": read_json(root / "stock_rankings.json", {"stocks": []}),
        "events": read_json(root / "signal_events.json", {"events": []}),
        "comparison": read_json(root / "comparison.json", None),
        "diagnosis": read_text(root / "strategy_diagnosis.md"),
    }
    bundle["stock_names"] = bundle_stock_names(bundle)
    return bundle


def html_escape(value: Any):
    return str(value).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def html_escape_text(value: Any):
    return html_escape(value).replace("\n", "<br>")


def simple_markdown_html(value: Any):
    blocks = []
    in_list = False
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            if in_list:
                blocks.append("</ul>")
                in_list = False
            continue
        if line.startswith("### "):
            if in_list:
                blocks.append("</ul>")
                in_list = False
            blocks.append(f"<h3>{html_escape(line[4:])}</h3>")
        elif line.startswith("- "):
            if not in_list:
                blocks.append("<ul>")
                in_list = True
            blocks.append(f"<li>{html_escape(line[2:])}</li>")
        else:
            if in_list:
                blocks.append("</ul>")
                in_list = False
            blocks.append(f"<p>{html_escape(line)}</p>")
    if in_list:
        blocks.append("</ul>")
    return "\n".join(blocks)


def metric_card_with_tip(label: str, value: Any, tip: Any = ""):
    import panel as pn

    tooltip = ""
    if tip:
        tooltip = f'<span class="metric-tooltip" data-tip="{html_escape(tip)}">?</span>'
    html = f'<div class="metric-card"><div class="label">{html_escape(label)}{tooltip}</div><div class="value">{html_escape(value)}</div></div>'
    return pn.pane.HTML(html, sizing_mode="stretch_width")


def plain_card(body: Any):
    import panel as pn

    return pn.Card(
        pn.pane.Markdown(body, sizing_mode="stretch_width"),
        hide_header=True,
        styles={"border": "1px solid #d8dee8", "border-radius": "8px", "background": "#ffffff"},
        sizing_mode="stretch_width",
    )


def _win_rate_display(summary: dict) -> str:
    """Return the win-rate card value.

    SimpleBuyHold never closes positions, so there are no completed trades to
    measure win rate against. The returned value is a localized not-applicable
    showing bare 'n/a' which implies missing data.
    """
    strategy_name = str(summary.get("strategy", {}).get("name", ""))
    if "SimpleBuyHold" in strategy_name:
        return "不適用"
    return fmt_pct(metric(summary, "win_rate"))


def metrics_row(summary: dict[str, Any]):
    import panel as pn

    definitions = metric_definition_map(summary)
    benchmark_name = benchmark_label(summary)
    cards = [
        metric_card_with_tip(TXT["return"], fmt_pct(metric(summary, "return_rate")), definitions[TXT["return"]]),
        metric_card_with_tip(benchmark_name, fmt_pct(metric(summary, "buy_and_hold_return_rate")), definitions[benchmark_name]),
        metric_card_with_tip(TXT["gap"], fmt_pct(metric(summary, "excess_return_rate")), definitions[TXT["gap"]]),
        metric_card_with_tip(TXT["max_dd"], fmt_pct(metric(summary, "max_drawdown_rate")), definitions[TXT["max_dd"]]),
        metric_card_with_tip(TXT["win_rate"], _win_rate_display(summary), definitions[TXT["win_rate"]]),
        metric_card_with_tip(TXT["trades"], fmt_num(metric(summary, "trade_count")), definitions[TXT["trades"]]),
    ]
    return pn.GridBox(*cards, ncols=3, sizing_mode="stretch_width")


def benchmark_label(summary: dict[str, Any]):
    benchmark_code = summary.get("benchmark", {}).get("benchmark_code")
    if benchmark_code:
        return f"{benchmark_code} 市場基準"
    return "舊股票池基準"


def metric_definition_map(summary: dict[str, Any]):
    label_key = "指標"
    definition_key = "定義"
    reading_key = "讀法"
    return {row[label_key]: f"{row[definition_key]} {row[reading_key]}" for row in metric_definition_rows(summary)}


def metric_definition_rows(summary: dict[str, Any]):
    initial_cash = fmt_num(summary.get("run", {}).get("initial_cash"))
    benchmark_name = benchmark_label(summary)
    benchmark_code = summary.get("benchmark", {}).get("benchmark_code")
    strategy_name = str(summary.get("strategy", {}).get("name", ""))
    if benchmark_code:
        benchmark_definition = f"指定市場標的 {benchmark_code} 的買進持有報酬。"
        benchmark_reading = "用來回答：這個多股組合策略有沒有跑贏可投資的市場代表？若顯示 n/a，代表目前缺少這檔基準的價格資料。"
    else:
        benchmark_definition = "舊版 summary 的等金額股票池買進持有報酬，不是大盤或 0050。"
        benchmark_reading = "這個值只能當成舊版參考；要做市場比較需重跑回測並提供 0050 資料。"
    return [
        {
            "指標": TXT["return"],
            "定義": "策略從初始資金到回測結束的總報酬率。",
            "讀法": f"本次是用同一個組合現金池回測，初始資金 {initial_cash}。",
        },
        {
            "指標": benchmark_name,
            "定義": benchmark_definition,
            "讀法": benchmark_reading,
        },
        {
            "指標": TXT["gap"],
            "定義": f"策略報酬 - {benchmark_name}報酬。",
            "讀法": "負數代表策略跑輸基準；這個值應該當成百分點差距來看。",
        },
        {
            "指標": TXT["max_dd"],
            "定義": "淨值曾經從歷史高點往下掉的最大幅度。",
            "讀法": "用來看過程中最痛的浮動處境；越負表示回測中曾經跌得越深。",
        },
        {
            "指標": TXT["win_rate"],
            "定義": ("已結束交易中，賺錢交易的比例。" + (" 此策略不主動賣出，無已結束交易可算勝率。" if "SimpleBuyHold" in strategy_name else "")),
            "讀法": "勝率高不代表策略一定好，還要搭配賠賺比和回撤一起看。",
        },
        {
            "指標": TXT["trades"],
            "定義": "回測期間總共產生的買進、賣出、部分賣出等交易紀錄數量。",
            "讀法": "交易次數太高時，要特別注意策略是不是在震盪裡過度進出。",
        },
        {
            "指標": TXT["expectancy"],
            "定義": "每筆已結束交易平均損益（已實現損益 / 已結束交易數）。",
            "讀法": "> 0 才有正期望值；獨立於勝率。",
        },
        {
            "指標": TXT["payoff_ratio"],
            "定義": "平均獲利 / |平均虧損|。",
            "讀法": ">= 2 符合大賺小賠目標；< 1 代表小賺大賠。",
        },
        {
            "指標": TXT["profit_factor"],
            "定義": "總獲利 / 總虧損絕對值。",
            "讀法": "> 1 才有正邊際；越高越穩健。",
        },
        {
            "指標": TXT["calmar"],
            "定義": "報酬率 / |最大回撤|。",
            "讀法": "越高代表以更少回撤換到同等報酬。",
        },
    ]


def metric_definitions(summary: dict[str, Any]):
    import panel as pn

    return pn.Column(
        pn.pane.Markdown("### 績效指標怎麼讀"),
        pn.pane.DataFrame(pd.DataFrame(metric_definition_rows(summary)), sizing_mode="stretch_width", height=190),
        sizing_mode="stretch_width",
    )


def strategy_health_panel(summary: dict) -> "pn.viewable.Viewable | None":
    """Build the strategy health-check panel or return None when not applicable."""
    import panel as pn

    strategy_name = str(summary.get("strategy", {}).get("name", ""))
    if "SimpleBuyHold" in strategy_name:
        return None
    if not metric(summary, "closed_trade_count"):
        return None

    rows = strategy_health_rows(summary)
    closed_count = rows["closed_trade_count"]

    heading = section_heading_with_tip(
        TXT["health_check"],
        "「大賺小賠」哲學體檢：盈虧比 ≥ 2 且期望值 > 0 是目標，勝率可低但停損要小、大波段要賺到。",
    )

    metric_grid = pn.GridBox(
        metric_card_with_tip(
            TXT["expectancy"],
            rows["expectancy_fmt"],
            "每筆已結束交易平均損益，> 0 代表策略有正邊際。",
        ),
        metric_card_with_tip(
            TXT["payoff_ratio"],
            rows["payoff_ratio_fmt"],
            "平均獲利 / 平均虧損（絕對值）。≥ 2 符合大賺小賠目標。",
        ),
        metric_card_with_tip(
            TXT["profit_factor"],
            rows["profit_factor_fmt"],
            "總獲利 / 總虧損（絕對值）。> 1 代表整體有獲利。",
        ),
        metric_card_with_tip(
            TXT["calmar"],
            rows["calmar_fmt"],
            "報酬率 / |最大回撤|。越高代表以更少回撤換到同等報酬。",
        ),
        ncols=4,
        sizing_mode="stretch_width",
    )

    table_md = (
        "| 項目 | 獲利方 | 虧損方 |\n"
        "|------|-------|-------|\n"
        f"| 平均 | {rows['avg_win_fmt']} | {rows['avg_loss_fmt']} |\n"
        f"| 最大單筆 | {rows['largest_win_fmt']} | {rows['largest_loss_fmt']} |\n"
        f"| 已結束交易 | {closed_count} 筆 | — |"
    )
    detail_card = plain_card(table_md)

    verdict = rows["verdict"]
    if "✓" in verdict:
        color = "green"
    elif "⚠" in verdict:
        color = "orange"
    elif "✗" in verdict:
        color = "red"
    else:
        color = "gray"
    verdict_html = pn.pane.HTML(
        f'<p style="color: {color}; font-weight: bold;">{html_escape(verdict)}</p>',
        sizing_mode="stretch_width",
    )

    return pn.Column(heading, metric_grid, detail_card, verdict_html, sizing_mode="stretch_width")


def capital_mode_comparison_rows(
    comparison: dict[str, Any],
    mode_summaries: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return formatted capital-mode comparison rows without constructing Panel objects."""
    modes = comparison.get("modes", {})
    symbols = comparison.get("symbols", {})
    affected = [code for code, item in symbols.items() if item.get("contention_affected")]
    affected_text = ", ".join(affected) if affected else "n/a"
    rows = []
    for mode in ["shared", "per_stock", "unconstrained"]:
        metrics = modes.get(mode, {})
        summary = (mode_summaries or {}).get(mode, {})
        max_drawdown_rate = metrics.get("max_drawdown_rate")
        if max_drawdown_rate is None and summary:
            max_drawdown_rate = metric(summary, "max_drawdown_rate")
        rows.append({
            "模式": mode,
            "報酬率": fmt_pct(metrics.get("return_rate")),
            "最大回撤": fmt_pct(max_drawdown_rate),
            "勝率": fmt_pct(metrics.get("win_rate")),
            "盈虧比": fmt_ratio(metrics.get("payoff_ratio")),
            "期望值": fmt_num(metrics.get("expectancy"), digits=0),
            "現金阻擋": metrics.get("cash_blocked_entry_count", 0),
            "資金排擠股票": affected_text if mode == "shared" else "",
        })
    return rows


def comparison_table_html(rows: list[dict[str, Any]]) -> str:
    """Render comparison rows as a styled, escaped HTML table."""
    if not rows:
        return ""
    headers = list(rows[0].keys())
    header_html = "".join(f"<th>{html_escape(header)}</th>" for header in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{html_escape(row.get(header, ''))}</td>" for header in headers)
        body_rows.append(f"<tr>{cells}</tr>")
    return f'<table class="capital-table"><thead><tr>{header_html}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>'


def capital_mode_comparison_panel(comparison: dict[str, Any] | None) -> "pn.viewable.Viewable | None":
    """Build the capital-mode comparison panel or return None when unavailable."""
    import panel as pn

    if not comparison:
        return None
    rows = capital_mode_comparison_rows(comparison)
    if not rows:
        return None
    return pn.Column(
        pn.pane.Markdown("## 資金模式比較"),
        pn.pane.HTML(comparison_table_html(rows), sizing_mode="stretch_width"),
        sizing_mode="stretch_width",
    )


def capital_mode_pool_verdict(mode: str, summary_mode: dict[str, Any]) -> str:
    """Return a pure per-pool interpretation string."""
    health = strategy_health_verdict(metric(summary_mode, "payoff_ratio"), metric(summary_mode, "expectancy"))
    if mode == "unconstrained":
        return f"信號品質檢查：unconstrained 不受現金限制，return/max drawdown 為診斷用空值，不可視為真實報酬。交易品質判讀：{health}"
    return f"{_strategy_verdict(summary_mode)} 交易品質判讀：{health}"


def capital_mode_comparative_verdict(
    comparison: dict[str, Any],
    mode_summaries: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Return a pure cross-pool verdict for capital allocation diagnosis."""
    modes = comparison.get("modes", {})
    summaries = mode_summaries or {}
    shared = modes.get("shared", {})
    per_stock = modes.get("per_stock", {})
    unconstrained = modes.get("unconstrained", {})
    shared_return = shared.get("return_rate", metric(summaries.get("shared", {}), "return_rate"))
    per_stock_return = per_stock.get("return_rate", metric(summaries.get("per_stock", {}), "return_rate"))
    affected = [code for code, item in comparison.get("symbols", {}).items() if item.get("contention_affected")]
    cash_blocked = float(shared.get("cash_blocked_entry_count") or metric(summaries.get("shared", {}), "cash_blocked_entry_count") or 0)
    payoff_ratio = unconstrained.get("payoff_ratio", metric(summaries.get("unconstrained", {}), "payoff_ratio"))
    expectancy = unconstrained.get("expectancy", metric(summaries.get("unconstrained", {}), "expectancy"))

    if shared_return is not None and per_stock_return is not None and per_stock_return > shared_return and (affected or cash_blocked > 0):
        symbol_text = ", ".join(affected) if affected else "無特定股票旗標"
        return (
            "資金分配可能是主要瓶頸：per_stock 明顯優於 shared，且 shared 有現金阻擋或資金排擠股票。"
            f"建議後續研究輪動策略，在進場訊號競合時先釋放或轉移資金。受影響股票：{symbol_text}。"
        )
    if per_stock_return is not None and per_stock_return <= 0:
        return (
            "信號品質需要優先檢查：per_stock 解除跨股票資金排擠後仍未轉強，"
            f"unconstrained 的盈虧比/期望值為 {fmt_ratio(payoff_ratio)} / {fmt_num(expectancy, digits=0)}。"
        )
    return "shared 與 per_stock 結果接近，暫未看到明顯資金池瓶頸；可先聚焦參數穩健度與交易品質。"


def _capital_mode_debug_block(
    mode: str,
    summary_mode: dict[str, Any],
    comparison: dict[str, Any] | None = None,
) -> "pn.viewable.Viewable":
    symbols = (comparison or {}).get("symbols", {})
    affected = [code for code, item in symbols.items() if item.get("contention_affected")]
    lines = [
        f"- capital_mode: `{mode}`",
        f"- cash_blocked_entry_count: `{fmt_num(metric(summary_mode, 'cash_blocked_entry_count'))}`",
    ]
    if mode == "shared":
        lines.append(f"- contention_affected_symbols: `{', '.join(affected) if affected else 'n/a'}`")
    if mode == "unconstrained":
        lines.append("- return-scale fields: signal-quality-only; null does not mean missing execution data.")
    return plain_card("### Debug\n\n" + "\n".join(lines))


def capital_mode_pool_tab(
    mode: str,
    summary_mode: dict[str, Any],
    comparison: dict[str, Any] | None = None,
) -> "pn.viewable.Viewable":
    """Build one capital-pool tab from a full per-mode summary."""
    import panel as pn

    content: list[Any] = [
        pn.pane.Markdown(f"### {mode}"),
        metrics_row(summary_mode),
    ]
    health = strategy_health_panel(summary_mode)
    if health is not None:
        content.append(health)
    content.extend([
        pn.pane.Markdown(capital_mode_pool_verdict(mode, summary_mode)),
        pn.pane.Plotly(make_equity_drawdown_figure(summary_mode), config={"displaylogo": False, "responsive": True}, sizing_mode="stretch_width"),
        _capital_mode_debug_block(mode, summary_mode, comparison),
    ])
    return pn.Column(*content, sizing_mode="stretch_width")


def capital_mode_tabs_panel(bundle: dict[str, Any]) -> "pn.Tabs | None":
    """Build capital-mode comparison tabs or return None for single-mode tasks."""
    import panel as pn

    comparison = bundle.get("comparison")
    mode_summaries = bundle.get("mode_summaries") or {}
    if not comparison or not mode_summaries:
        return None
    rows = capital_mode_comparison_rows(comparison, mode_summaries)
    overview = pn.Column(
        pn.pane.Markdown("### 資金池比較總覽"),
        pn.pane.Markdown(capital_mode_comparative_verdict(comparison, mode_summaries)),
        pn.pane.HTML(comparison_table_html(rows), sizing_mode="stretch_width"),
        sizing_mode="stretch_width",
    )
    tabs: list[tuple[str, Any]] = [("比較總覽", overview)]
    labels = {
        "shared": "Shared",
        "per_stock": "PerStock",
        "unconstrained": "Unconstrained",
    }
    for mode in ["shared", "per_stock", "unconstrained"]:
        summary_mode = mode_summaries.get(mode)
        if not summary_mode:
            return None
        tabs.append((labels[mode], capital_mode_pool_tab(mode, summary_mode, comparison)))
    return pn.Tabs(*tabs, sizing_mode="stretch_width")


def strategy_diagnosis_panel(diagnosis_text: str) -> "pn.viewable.Viewable | None":
    """Return a panel displaying the strategy diagnosis Markdown, or None if absent."""
    import panel as pn

    if not diagnosis_text or not diagnosis_text.strip():
        return None
    heading = section_heading_with_tip(
        "策略改進建議",
        "由 /diagnose-strategy 指令產生。重跑回測後可重新執行以更新建議。",
    )
    return pn.Column(heading, plain_card(diagnosis_text), sizing_mode="stretch_width")


def strategy_rule_rows(summary: dict[str, Any]):
    strategy_name = str(summary.get("strategy", {}).get("name", ""))
    params = summary.get("strategy", {}).get("params", {})
    if "SimpleBuyHold" in strategy_name:
        return [
            {
                "類別": "進場",
                "規則": "回測開始時買進目標股票。",
                "參數": "使用可用現金與設定交易單位",
            },
            {
                "類別": "持有",
                "規則": "買進後持有到回測結束，期間不主動賣出。",
                "參數": "無主動賣出條件",
            },
            {
                "類別": "股利",
                "規則": "持有期間的現金股利計入現金。",
                "參數": "依公司行動資料入帳",
            },
            {
                "類別": "資金",
                "規則": "所有交易使用同一個組合現金池。",
                "參數": f"initial cash {fmt_num(summary.get('run', {}).get('initial_cash'))}",
            },
        ]
    return [
        {
            "類別": "進場",
            "規則": "均線收斂後轉強，或出現底部 2B 收復訊號時買進。",
            "參數": (f"MA {params.get('windows', 'n/a')} 的最大值與最小值差距 <= 收盤價的 {params.get('convergence_pct', 'n/a')}%"),
        },
        {
            "類別": "均線收斂",
            "規則": "短中期均線很接近，表示股價可能在壓縮、整理、等待方向。",
            "參數": (f"程式算法：(max(MA) - min(MA)) / close * 100。本次門檻為 {params.get('convergence_pct', 'n/a')}%。"),
        },
        {
            "類別": "加碼",
            "規則": "持倉中再出現底部 2B 收復時加碼。",
            "參數": f"initial {params.get('initial_allocation_pct', 'n/a')} / add {params.get('add_allocation_pct', 'n/a')}",
        },
        {
            "類別": "出場",
            "規則": "遇到頂部 2B、停損、或跌破慢速出場均線時賣出或部分賣出。",
            "參數": f"stop {params.get('stop_loss_pct', 'n/a')}% / exit MA {params.get('exit_window', 'n/a')}/{params.get('slow_exit_window', 'n/a')}",
        },
        {
            "類別": "資金",
            "規則": "每次回測從同一個組合現金池扣款，不是每檔股票各有一筆本金。",
            "參數": f"initial cash {fmt_num(summary.get('run', {}).get('initial_cash'))} / lot {params.get('lot_size', 'n/a')}",
        },
    ]


def _ma_rows_for_windows(price_context: dict, windows: list) -> list:
    """Return formatted market-table rows for moving-average data.

    Uses the strategy's actual ``windows`` parameter so non-default window
    configurations (e.g. [8, 21]) are shown correctly instead of hardcoded
    MA5/MA10/MA20 placeholders.
    """
    mas = price_context.get("moving_averages", {})
    rows = [{"欄位": f"MA{w}", "數值": fmt_num(mas.get(f"ma{w}"), 2)} for w in windows]
    rows.append({"欄位": "均線最高值", "數值": fmt_num(price_context.get("ma_max"), 2)})
    rows.append({"欄位": "均線最低值", "數值": fmt_num(price_context.get("ma_min"), 2)})
    return rows


def trade_verification_mode(report: dict[str, Any]):
    strategy_name = str(report.get("strategy", {}).get("name", ""))
    if "SimpleBuyHold" in strategy_name:
        return "buy_hold"
    if "TwoB" in strategy_name:
        return "two_b"
    return "generic"


def trade_price_section_title(report: dict[str, Any]):
    if trade_verification_mode(report) == "two_b":
        return "當日價格與均線"
    return "當日價格資料"


def strategy_plain_language(task_id: str, summary: dict[str, Any]):
    import panel as pn

    strategy_name = str(summary.get("strategy", {}).get("name", ""))
    if "TwoB" not in strategy_name:
        return None
    params = summary.get("strategy", {}).get("params", {})
    note = read_text(task_root(task_id) / "research_dashboard" / "two_b_ma_convergence_notes.md").format(
        swing=params.get("swing_lookback", "n/a"),
        reclaim=params.get("reclaim_window", "n/a"),
    )
    intro, _, details = note.partition("<!-- more -->")
    html = (
        '<div class="social-more">'
        f"<div>{html_escape_text(intro.strip())}</div>"
        "<details>"
        "<summary>更多</summary>"
        f'<div class="social-more-content">{simple_markdown_html(details.strip())}</div>'
        "</details>"
        "</div>"
    )
    return pn.pane.HTML(html, sizing_mode="stretch_width")


def _strategy_verdict(summary: dict) -> str:
    """One-line verdict for the strategy overview panel.

    Uses '落後 X 個百分點' rather than '跑輸 X%' to make clear that the gap
    is a percentage-point difference, not the benchmark's absolute return value.
    """
    metrics = summary.get("metrics", {})
    excess_return = metrics.get("excess_return_rate")
    name = benchmark_label(summary)
    if excess_return is None:
        return ("目前先看策略本身：策略報酬為 {ret}，但 {name} 尚未算出，通常代表本機缺少基準的價格資料。").format(
            ret=fmt_pct(metrics.get("return_rate")), name=name
        )
    if excess_return < 0:
        return ("目前不適合直接推進：策略報酬為 {ret}，落後 {name} {gap} 個百分點。").format(
            ret=fmt_pct(metrics.get("return_rate")),
            gap=fmt_pct(abs(excess_return)),
            name=name,
        )
    return ("本輪策略報酬為 {ret}，跑贏 {name} {gap} 個百分點；還需搭配回撤、交易次數與個股歸因一起看。").format(
        ret=fmt_pct(metrics.get("return_rate")),
        gap=fmt_pct(excess_return),
        name=name,
    )


def strategy_overview(task_id: str, summary: dict[str, Any]):
    import panel as pn

    strategy = summary.get("strategy", {})
    verdict = _strategy_verdict(summary)
    content: list[pn.viewable.Viewable] = [
        pn.pane.Markdown(
            f"## 策略規則與本輪判讀\n\n**{strategy.get('name', 'n/a')}**\n\n{verdict}",
            sizing_mode="stretch_width",
        )
    ]
    plain_language = strategy_plain_language(task_id, summary)
    if plain_language is not None:
        content.append(plain_language)
    content.append(pn.pane.DataFrame(pd.DataFrame(strategy_rule_rows(summary)), sizing_mode="stretch_width", height=210))
    return pn.Column(*content, sizing_mode="stretch_width")


WARNING_PATTERN = re.compile(r"Unsupported corporate action for (?P<code>\S+) on (?P<date>\d{4}-\d{2}-\d{2}): (?P<event>\S+)")

CORPORATE_ACTION_LABELS = {
    "EX_RIGHT": "除權",
    "EX_RIGHT_AND_DIVIDEND": "除權息",
    "CASH_CAPITAL_REDUCTION": "現金減資",
    "LOSS_OFFSET_CAPITAL_REDUCTION": "彌補虧損減資",
    "CAPITAL_REDUCTION": "減資",
}


def warning_is_in_run(summary: dict[str, Any], warning: Any):
    match = WARNING_PATTERN.fullmatch(str(warning))
    if not match:
        return True
    event_date = pd.Timestamp(match.group("date"))
    run = summary.get("run", {})
    start = pd.Timestamp(run["start"]) if run.get("start") else None
    end_value = run.get("end")
    end = pd.Timestamp(end_value) if end_value else None
    return (
        isinstance(event_date, pd.Timestamp)
        and (start is None or (isinstance(start, pd.Timestamp) and event_date >= start))
        and (end is None or (isinstance(end, pd.Timestamp) and event_date <= end))
    )


def relevant_warnings(summary: dict[str, Any]):
    return [warning for warning in summary.get("warnings") or [] if warning_is_in_run(summary, warning)]


def format_corporate_action_warning(warning: Any):
    match = WARNING_PATTERN.fullmatch(str(warning))
    if not match:
        return str(warning)
    code = match.group("code")
    event = CORPORATE_ACTION_LABELS.get(match.group("event"), match.group("event"))
    return f"{stock_label(code)} 於 {match.group('date')} 發生{event}；本版回測尚未自動調整股數與成本，該股票的績效可能失真。"


def warning_panel(summary: dict[str, Any]):
    import panel as pn

    warnings = relevant_warnings(summary)
    if not warnings:
        return None
    items = "".join(f"<li>{html_escape(format_corporate_action_warning(item))}</li>" for item in warnings)
    html = f'<div class="warning-card"><strong>需要留意的公司行動</strong><ul>{items}</ul></div>'
    return pn.pane.HTML(html, sizing_mode="stretch_width")


def data_quality_panel(summary: dict[str, Any]):
    import panel as pn

    policy = summary.get("price_policy") or {}
    if not policy:
        return None
    benchmark_code = summary.get("benchmark", {}).get("benchmark_code") or "未設定"
    warning_count = len(relevant_warnings(summary))
    status = "有未處理事件，請查看下方提醒" if warning_count else "本輪未發現影響績效的未處理事件"
    details = (
        '<div class="social-more">'
        "<div><strong>資料可信度</strong></div>"
        f"<p>策略訊號已處理分割與除息短期價差；成交、現金與損益使用原始價。整體基準為 {html_escape(benchmark_code)}。</p>"
        f"<p>{html_escape(status)}。</p>"
        "<details><summary>技術設定</summary>"
        '<div class="social-more-content">'
        f"<p>Policy: {html_escape(policy.get('name', 'n/a'))}</p>"
        f"<p>除息訊號視窗：{html_escape(policy.get('dividend_signal_window_days', 'n/a'))} 個交易日；"
        f"填息後提前結束。</p>"
        f"<p>Corporate action DB: {html_escape(policy.get('corporate_action_db_path') or 'n/a')}</p>"
        "</div></details></div>"
    )
    return pn.pane.HTML(details, sizing_mode="stretch_width")


def equity_frame(summary: dict[str, Any]):
    rows = summary.get("portfolio", {}).get("equity_curve", [])
    if not rows:
        return pd.DataFrame(columns=pd.Index(["date", "equity"]))
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df["equity"] = pd.to_numeric(df["equity"], errors="coerce")
    return cast(pd.DataFrame, df[["date", "equity"]]).dropna().sort_values("date")


def add_drawdown(df: pd.DataFrame, value_col: Any):
    if df.empty:
        return pd.Series(dtype=float)
    peak = df[value_col].cummax()
    return ((df[value_col] - peak) / peak) * 100


def make_equity_drawdown_figure(summary: dict[str, Any]):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    df = equity_frame(summary)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.68, 0.32])
    if not df.empty:
        df["drawdown"] = add_drawdown(df, "equity")
        fig.add_trace(go.Scatter(x=df["date"], y=df["equity"], name=TXT["equity"], line={"color": "#0f766e", "width": 2.5}), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["date"], y=df["drawdown"], name=TXT["drawdown"], fill="tozeroy", line={"color": "#b91c1c", "width": 1.5}), row=2, col=1)
    fig.update_layout(template="plotly_white", height=520, margin={"l": 30, "r": 20, "t": 30, "b": 20}, legend={"orientation": "h"})
    fig.update_yaxes(title_text=TXT["equity"], row=1, col=1)
    fig.update_yaxes(title_text=TXT["drawdown"], ticksuffix="%", row=2, col=1)
    return fig


def ranking_frame(rankings: dict[str, Any]):
    rows = []
    for item in rankings.get("stocks", []):
        rows.append({
            field_label("stock"): stock_label(item.get("code")),
            field_label("total_pnl"): item.get("total_pnl"),
            field_label("max_drawdown_rate"): item.get("max_drawdown_rate"),
            field_label("trade_count"): item.get("trade_count"),
            field_label("win_rate"): item.get("win_rate"),
        })
    frame = pd.DataFrame(rows)
    frame.index = range(1, len(frame) + 1)
    return frame


def ranking_display_frame(rankings: dict[str, Any]):
    frame = ranking_frame(rankings).copy()
    if frame.empty:
        return frame
    frame[field_label("total_pnl")] = frame[field_label("total_pnl")].map(fmt_num)
    frame[field_label("max_drawdown_rate")] = frame[field_label("max_drawdown_rate")].map(fmt_pct)
    frame[field_label("trade_count")] = frame[field_label("trade_count")].map(fmt_num)
    frame[field_label("win_rate")] = frame[field_label("win_rate")].map(fmt_pct)
    return frame


def ranking_table(rankings: dict[str, Any]):
    import panel as pn

    frame = ranking_display_frame(rankings)
    help_keys = ["total_pnl", "max_drawdown_rate", "trade_count", "win_rate"]
    tooltips = {field_label(key): field_help(key) for key in help_keys}
    titles = {field_label(key): f"{field_label(key)} ?" for key in help_keys}
    return pn.widgets.Tabulator(
        frame,
        editors={column: None for column in frame.columns},
        header_tooltips=tooltips,
        titles=titles,
        layout="fit_columns",
        selectable=False,
        show_index=True,
        sizing_mode="stretch_width",
        height=320,
    )


def section_heading_with_tip(title: str, tip: Any, level: int = 2):
    import panel as pn

    html = f'<h{level}>{html_escape(title)}<span class="metric-tooltip" data-tip="{html_escape(tip)}">?</span></h{level}>'
    return pn.pane.HTML(html, sizing_mode="stretch_width")


def make_ranking_figure(rankings: dict[str, Any]):
    import plotly.graph_objects as go

    df = ranking_frame(rankings).head(18)
    fig = go.Figure()
    if not df.empty:
        pnl_col = field_label("total_pnl")
        stock_col = field_label("stock")
        colors = ["#0f766e" if value >= 0 else "#b91c1c" for value in df[pnl_col].fillna(0)]
        fig.add_bar(x=df[stock_col], y=df[pnl_col], marker_color=colors)
    fig.update_layout(template="plotly_white", height=360, margin={"l": 30, "r": 20, "t": 20, "b": 30})
    return fig


def trades_frame(summary: dict[str, Any]):
    rows = []
    for index, trade in enumerate(summary.get("trades", []), start=1):
        rows.append({
            "trade_id": f"T{index:03d}",
            "date": trade.get("date"),
            "code": trade.get("code"),
            "action": trade.get("action"),
            "price": trade.get("price"),
            "qty": trade.get("qty"),
            "total": trade.get("total"),
        })
    return pd.DataFrame(rows)


def trades_display_frame(summary: dict[str, Any]):
    frame = trades_frame(summary)
    if frame.empty:
        return pd.DataFrame(
            columns=pd.Index([
                field_label("trade_id"),
                field_label("date"),
                field_label("stock"),
                field_label("action"),
                field_label("price"),
                field_label("qty"),
                field_label("total"),
            ])
        )
    return pd.DataFrame({
        field_label("trade_id"): frame["trade_id"],
        field_label("date"): frame["date"].astype(str).str[:10],
        field_label("stock"): frame["code"].map(stock_label),
        field_label("action"): frame["action"].map(action_label),
        field_label("price"): frame["price"].map(lambda value: f"{float(value):,.2f}"),
        field_label("qty"): frame["qty"].map(fmt_num),
        field_label("total"): frame["total"].map(fmt_num),
    })


def key_trades_table(summary: dict[str, Any]):
    import panel as pn

    frame = trades_display_frame(summary).tail(40)
    return pn.widgets.Tabulator(
        frame,
        editors={column: None for column in frame.columns},
        layout="fit_columns",
        selectable=False,
        show_index=False,
        sizing_mode="stretch_width",
        height=320,
    )


def task_options(tasks: list[Any]):
    return {item["task"]: item["task"] for item in tasks}


def symbol_options(summary: dict[str, Any]):
    codes = [str(code) for code in summary.get("run", {}).get("codes", [])]
    return {TXT["all_symbols"]: "", **{stock_label(code): code for code in codes}}


def artifact_link_targets(task_id: str, mode: str = "static"):
    root = task_root(task_id)
    candidates = [
        ("visual_report.html", root / "visual_report.html"),
        ("complete_report.md", root / "research_report" / "complete_report.md"),
        ("summary.json", root / "summary.json"),
        ("stock_rankings.json", root / "stock_rankings.json"),
        ("signal_events.json", root / "signal_events.json"),
    ]
    targets = {}
    for label, path in candidates:
        if path.is_file():
            if mode == "server":
                targets[label] = f"/artifacts/{path.relative_to(TASKS_ROOT).as_posix()}"
            else:
                targets[label] = site_relative(path).as_posix()
    return targets


def artifact_links(task_id: str, mode: str = "static"):
    import panel as pn

    links = [f"- [{label}]({target})" for label, target in artifact_link_targets(task_id, mode=mode).items()]
    return pn.pane.Markdown("\n".join(links) if links else "No artifacts found.", sizing_mode="stretch_width")


def hero(title: str | None = None, subtitle: str | None = None):
    import panel as pn

    title = title or TXT["app_title"]
    subtitle = subtitle or TXT["subtitle"]
    return pn.Card(
        pn.pane.Markdown(f"# {title}\n\n{subtitle}", sizing_mode="stretch_width"),
        hide_header=True,
        styles={
            "background": "#ffffff",
            "color": "#111827",
            "border": "1px solid #d8dee8",
            "border-left": "6px solid #0f766e",
            "border-radius": "8px",
            "padding": "14px",
        },
        sizing_mode="stretch_width",
    )


def task_card(task_item: Any, detail_href: str | None = None):
    import panel as pn

    summary = task_item["summary"]
    detail = f"\n\n[{TXT['open_detail']}]({detail_href})" if detail_href else ""
    body = (
        f"### {task_title(task_item['task'])}\n\n"
        f"`{task_item['task']}`\n\n"
        f"{TXT['return']}: `{fmt_pct(metric(summary, 'return_rate'))}`  "
        f"{benchmark_label(summary)}: `{fmt_pct(metric(summary, 'buy_and_hold_return_rate'))}`  "
        f"{TXT['trades']}: `{fmt_num(metric(summary, 'trade_count'))}`"
        f"{detail}"
    )
    return pn.Card(
        pn.pane.Markdown(body, sizing_mode="stretch_width"),
        hide_header=True,
        styles={"border": "1px solid #d8dee8", "border-radius": "8px", "background": "#ffffff"},
        sizing_mode="stretch_width",
    )


def build_index_view(static: bool = True):
    import panel as pn

    tasks = discover_tasks()
    content: list[pn.viewable.Viewable] = [hero()]
    if not tasks:
        content.append(pn.pane.Markdown(TXT["no_tasks"]))
    else:
        content.append(metrics_row(tasks[0]["summary"]))
        content.append(pn.pane.Markdown(f"## {TXT['research_tasks']}"))
        for item in tasks:
            href = f"{safe_slug(item['task'])}.html" if static else None
            content.append(task_card(item, detail_href=href))
    return pn.Column(*content, sizing_mode="stretch_width")


def build_help_view() -> "pn.Column":
    """Build the dashboard usage/help view."""
    import panel as pn

    body = """
## 使用說明

### Artifact 位置
- 任務資料放在 `tasks/<task-id>/`。
- 單一模式相容檔：`summary.json`。
- 資金池比較檔：`comparison.json`、`summary_shared.json`、`summary_per_stock.json`、`summary_unconstrained.json`。
- 其他常用資料：`stock_rankings.json`、`signal_events.json`、`research_report/complete_report.md`、`visual_report.html`。

### 重跑 2B 回測
```bash
uv run python -m scripts.run_task_backtest --task <task-id> --strategy candidates/<file>.py --codes <codes> --capital-mode all --promote-summary --data-path shioaji_stock_prices/data/adjusted_prices/daily
```

### 參數掃描
```bash
uv run python -m scripts.run_task_param_sweep --task <task-id> --strategy candidates/<file>.py --grid-file params/<file>.json --capital-mode all --promote-best --data-path shioaji_stock_prices/data/adjusted_prices/daily
```

### Dashboard
```bash
uv run --group static-report python -m scripts.build_research_dashboard
.\\scripts\\research\\open_research_dashboard.cmd
```

### 資料路徑提醒
`--data-path` 要指到調整後日 K 資料目錄；若改用不同資料集，請先確認同一任務的 `summary.json` 與 per-mode summary 都來自同一批價格資料。
"""
    return pn.Column(hero("使用說明", "任務 artifact、資金池比較與重跑指令"), pn.pane.Markdown(body), sizing_mode="stretch_width")


def build_task_view(task_id: str, artifact_mode: str = "static"):
    import panel as pn

    bundle = load_task_bundle(task_id)
    summary = bundle["summary"]
    rankings = bundle["rankings"]
    content = [
        hero(task_title(task_id), task_subtitle(task_id, summary)),
        strategy_overview(task_id, summary),
        metrics_row(summary),
    ]
    health = strategy_health_panel(summary)
    if health is not None:
        content.append(health)
    comparison = capital_mode_tabs_panel(bundle)
    if comparison is not None:
        content.append(comparison)
    quality = data_quality_panel(summary)
    if quality is not None:
        content.append(quality)
    warning = warning_panel(summary)
    if warning is not None:
        content.append(warning)
    content.extend([
        section_heading_with_tip(
            f"{TXT['equity']} / {TXT['drawdown']}",
            "上圖的淨值是當日現金加持股市值；下圖的回撤是相對過去最高淨值的跌幅，0% 代表位於新高。",
        ),
        pn.pane.Plotly(make_equity_drawdown_figure(summary), config={"displaylogo": False, "responsive": True}, sizing_mode="stretch_width"),
        pn.pane.Markdown(f"## {TXT['stock_ranking']}"),
        pn.pane.Plotly(make_ranking_figure(rankings), config={"displaylogo": False, "responsive": True}, sizing_mode="stretch_width"),
        ranking_table(rankings),
        pn.pane.Markdown(f"## {TXT['key_trades']}"),
        key_trades_table(summary),
    ])
    diagnosis = strategy_diagnosis_panel(bundle.get("diagnosis", ""))
    if diagnosis is not None:
        content.append(diagnosis)
    return pn.Column(*content, sizing_mode="stretch_width")


def marks_for_trade(code_trades: list, selected_trade_id: str, *, show_all: bool = False) -> list:
    """Return the subset of a symbol's trades to mark on the candlestick chart.

    code_trades: chronological list of trade dicts for one symbol
        (trade_id/date/action/price/qty), as returned by list_task_trades()["trades"].
    show_all=True  -> return all code_trades (skip episode detection).
    show_all=False -> return only the trades in the same position episode as
        selected_trade_id.

    A position episode starts when a BUY opens a flat position and ends when
    the running quantity returns to zero or below.  DIVIDEND and unknown actions
    do not open or close episodes; SPLIT resets the running quantity directly.
    """
    if not code_trades:
        return []
    if show_all:
        return list(code_trades)

    # Split trades into position episodes.
    episodes: list[list] = []
    current: list = []
    running_qty: int = 0

    for trade in code_trades:
        action = str(trade.get("action", "")).upper()
        qty = int(trade.get("qty", 0))
        current.append(trade)
        if action == "BUY":
            running_qty += qty
        elif action == "SELL":
            running_qty -= qty
        elif action == "SPLIT":
            running_qty = int(trade.get("new_qty", running_qty))
        # DIVIDEND and unknown actions: no position change
        if running_qty <= 0:
            episodes.append(current)
            current = []
            running_qty = 0

    if current:  # unclosed / open episode at end of data
        episodes.append(current)

    # Return the episode that contains the selected trade.
    for episode in episodes:
        if any(t.get("trade_id") == selected_trade_id for t in episode):
            return episode

    # Fallback: return just the selected trade if not found in any episode.
    for trade in code_trades:
        if trade.get("trade_id") == selected_trade_id:
            return [trade]
    return []


def make_template(title: str, main: Any):
    import panel as pn

    pn.extension("plotly", "tabulator", raw_css=[CSS], sizing_mode="stretch_width")
    template = pn.template.FastListTemplate(
        title=title,
        accent_base_color="#0f766e",
        header_background="#0f172a",
        sidebar_width=260,
        theme_toggle=False,
        busy_indicator=None,
        main=[main],
    )
    return template
