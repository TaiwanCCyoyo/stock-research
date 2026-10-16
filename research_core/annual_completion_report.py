"""Render the small saved annual-completion publication without market-data access."""

from __future__ import annotations

import argparse
import html
import json
import logging
import math
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from research_core.annual_completion_publication import load_publication
from research_core.artifact_store import relative_name, safe_path

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "research_web/report-kit/v1"
TASK = ROOT / "tasks/20261013-annual-winner-rotation"
DEFAULT_PUBLICATION_PATH = "tasks/20261013-annual-winner-rotation/publications/completion-v2"
SCHEMA = "annual-completion-result.v2"
MAX_BYTES = 500 * 1024
SCENARIOS = {"lapse": "認股權放棄", "realize": "認股權價值實現"}


def _publication_path(value: str) -> tuple[str, str]:
    validated = relative_name(value)
    match = re.fullmatch(r"tasks/([a-z0-9][a-z0-9_-]*)/publications/([a-z0-9][a-z0-9_-]*)", validated)
    if match is None:
        raise ValueError("publication_path must be tasks/<safe-task-id>/publications/<safe-version>")
    return validated, match[1]


def _text(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _number(value: Any, *, percent: bool = False) -> str:
    if value is None:
        return "未知"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("report metrics must be finite numbers or null")
    return f"{value * 100:+.2f}%" if percent else f"{value:.4f} 倍"


def _metric(label: str, value: Any, *, percent: bool = False) -> str:
    colour = ""
    if percent and value is not None:
        colour = ' class="rk-gain"' if value >= 0 else ' class="rk-loss"'
    return f"<div><dt>{_text(label)}</dt><dd{colour}>{_number(value, percent=percent)}</dd></div>"


def _overview(windows: list[dict[str, Any]]) -> tuple[str, str]:
    if not windows:
        raise ValueError("saved report requires at least one window")
    primary = next((window for window in windows if window["id"] == "2011-2025"), windows[0])
    values = [(label, primary["scenarios"][scenario]["net_terminal_multiple"]) for scenario, label in SCENARIOS.items()]
    benchmark = primary["benchmark"]["net_terminal_multiple"]
    values.append(("連續持有 0050", benchmark))
    known = all(primary["scenarios"][scenario]["complete"] for scenario in SCENARIOS) and all(value is not None for _, value in values)
    period = _text(primary["id"])
    if known and all(value < benchmark for _, value in values[:2]):
        lede = f"{period} 的固定選股序列，兩種情境扣成本後均落後連續持有 0050。"
    elif known:
        lede = f"{period} 的固定持有期模型已可計；扣成本後結果如下。"
    else:
        lede = f"{period} 仍有未解決持有期；完整期間總報酬保持未知。"
    cards = []
    for label, value in values:
        total_return = None if value is None else value - 1
        cards.append(
            f'<li class="rk-finding"><p>{_text(label)}</p><b>{_number(value)}</b><dl class="metrics">{_metric("總報酬", total_return, percent=True)}</dl></li>'
        )
    overview = (
        f'<section class="rk-section" aria-labelledby="overview-title"><h2 id="overview-title">{period} · 扣成本後的答案</h2>'
        f'<ul class="rk-findings">{"".join(cards)}</ul>'
        '<p class="rk-foot">倍數包含初始本金；總報酬為終值倍數減一。這是原固定選股序列的模型結果，不推論所有追漲策略，也不代表完整每日風險已知。</p></section>'
    )
    return lede, overview


def _reasons(values: Sequence[str]) -> str:
    translations = {
        "unresolved_fixed_holding": "至少一個固定持有年度尚未解決",
        "missing_fixed_holding_year": "缺少固定持有年度",
        "nonadjacent_rotation_dates": "年度換股日期未銜接",
        "missing_fixed_issuer_history": "缺少原選股票的歷史資料",
        "missing_or_unordered_fixed_endpoints": "原訂買賣端點缺失或日期不符",
        "missing_benchmark_history": "缺少 0050 歷史資料",
    }
    return "；".join(_text(translations.get(reason, reason)) for reason in values)


def _window(window: dict[str, Any], scenario: str) -> str:
    strategy, benchmark = window["scenarios"][scenario], window["benchmark"]
    state = "完整持有期模型可計" if strategy["complete"] else "完整持有期仍未知"
    metrics = "".join(
        _metric(label, strategy[key], percent=percent)
        for label, key, percent in (
            ("策略扣成本後", "net_terminal_multiple", False),
            ("策略未扣成本", "gross_terminal_multiple", False),
            ("策略扣成本後 CAGR", "cagr", True),
        )
    )
    comparison = "".join(
        _metric(label, benchmark[key], percent=percent)
        for label, key, percent in (
            ("連續持有 0050 扣成本後", "net_terminal_multiple", False),
            ("連續持有 0050 未扣成本", "gross_terminal_multiple", False),
            ("0050 扣成本後 CAGR", "cagr", True),
        )
    )
    drawdown = _metric("完整每日最大回撤", strategy["max_drawdown"], percent=True)
    drawdown += _metric("沿用前值標記的參考回撤", strategy["carried_mark_reference_drawdown"], percent=True)
    reason = "" if not strategy.get("reason") else f'<p class="rk-note">{_reasons([strategy["reason"]])}</p>'
    diagnostics = strategy.get("paired_diagnostics")
    diagnostics_html = "<p>未提供完整配對診斷；不以可計年度子集推論顯著性。</p>"
    if diagnostics:
        interval = diagnostics["bootstrap_ci_95"]
        diagnostics_html = f"<p>配對年數 {_text(diagnostics['n_years'])}；勝過同期年度 0050 {_text(diagnostics['win_count'])} 年。</p>"
        diagnostics_html += (
            f"<p>單側 sign-flip p 值：{_text(format(diagnostics['sign_flip_p_value'], '.4f'))}；"
            f"年化幾何相對超額的 bootstrap 95% 區間：{_number(interval[0], percent=True)} 至 {_number(interval[1], percent=True)}。</p>"
            "<p>這些配對診斷比較每年同日期進出，不是上方連續長抱基準。對稱／可交換與年度獨立同分布假設、已看過的歷史及選股範圍限制仍成立，不能據此認證無偏顯著勝出。</p>"
        )
    return (
        f'<article class="rk-card window-card"><h3>{_text(window["id"])}</h3>'
        f'<p class="rk-foot">{_text(window["start_date"])} → {_text(window["end_date"])} · {state}</p>'
        f'<dl class="metrics">{metrics}</dl><dl class="metrics comparison">{comparison}</dl>{reason}'
        f'<details class="rk-details"><summary>回撤與配對診斷</summary><dl class="metrics">{drawdown}</dl>'
        "<p>若有停牌／無報價資訊日沿用前值（carry），終值仍可能可計，但完整每日實際回撤仍未知。參考回撤不能當作完整最大回撤。</p>"
        f"{diagnostics_html}</details></article>"
    )


def _annual_row(row: dict[str, Any], scenario: str) -> str:
    current = row[scenario]
    status = "模型可計" if current["status"] == "modeled" else "未解決"
    if current.get("reasons"):
        status += "；" + _reasons(current["reasons"])
    carry = current.get("carried_days")
    carry_text = "未記錄" if carry is None else f"{_text(carry)} 日"
    fields = [
        ("買入 → 退出／估值", f"{_text(row['entry_date'])} → {_text(row['exit_date'])}"),
        ("前一年排名報酬", _number(row["ranking_return"], percent=True)),
        ("策略扣成本後", _number(current["net_return"], percent=True)),
        ("策略未扣成本", _number(current["gross_return"], percent=True)),
        ("同期 0050 扣成本後", _number(row["benchmark"]["net_return"], percent=True)),
        ("v1 原扣成本後", _number(row["v1"]["net_return"], percent=True)),
        ("v1 原未扣成本", _number(row["v1"]["gross_return"], percent=True)),
        ("沿用前值標記", carry_text),
        ("狀態／缺口", status),
    ]
    year_label = f"{_text(row['year'])}" + (" YTD" if row["is_ytd"] else "")
    cells = "".join(f'<td data-label="{_text(label)}">{value}</td>' for label, value in fields)
    return f'<tr><th scope="row">{year_label}<span>{_text(row["code"])}</span></th>{cells}</tr>'


def _annual(rows: list[dict[str, Any]], scenario: str, *, ytd: bool) -> str:
    labels = [
        "持有年／代碼",
        "買入 → 退出／估值",
        "前一年排名報酬",
        "策略扣成本後",
        "策略未扣成本",
        "同期 0050 扣成本後",
        "v1 原扣成本後",
        "v1 原未扣成本",
        "沿用前值標記",
        "狀態／缺口",
    ]
    headers = "".join(f'<th scope="col">{_text(label)}</th>' for label in labels)
    body = "".join(_annual_row(row, scenario) for row in rows if row["is_ytd"] is ytd)
    caption = "未完成年度：截止日收盤假設清算，不年化、不併入完整年度" if ytd else "每列獨立持有期；v1 原值與本次輸入版本分開保留"
    return f'<table class="rk-table annual"><caption>{caption}</caption><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table>'


STYLE = """
:root{--font-ui:system-ui,"Microsoft JhengHei",sans-serif;
--font-serif:var(--font-ui)}

body{font-size:15px;
overflow-wrap:anywhere}
.rk-page{max-width:1180px}
h3{margin:0;
font-size:21px}

.scenario-radio{position:absolute;
width:1px;
height:1px;
opacity:0}
.scenario-switch{display:flex;
flex-wrap:wrap;
gap:8px;
margin:18px 0}

.scenario-switch label{padding:9px 15px;
border:1px solid var(--line-strong);
border-radius:7px;
cursor:pointer;
background:var(--surface)}

#lapse:checked~main label[for=lapse],#realize:checked~main label[for=realize]{background:var(--accent);
color:var(--paper)}

#lapse:focus-visible~main label[for=lapse],#realize:focus-visible~main label[for=realize]{outline:3px solid var(--accent);
outline-offset:3px}

#lapse:checked~main [data-scenario=realize],#realize:checked~main [data-scenario=lapse]{display:none}

.window-grid{display:grid;
grid-template-columns:repeat(3,minmax(0,1fr));
gap:12px}
.metrics{display:grid;
gap:8px;
margin:16px 0}

.metrics div{display:flex;
align-items:baseline;
justify-content:space-between;
gap:10px}
.metrics dt{font-size:12px;
color:var(--muted)}

.metrics dd{margin:0;
font-size:20px;
font-variant-numeric:tabular-nums;
font-weight:600}
.comparison{border-top:1px solid var(--line);
padding-top:12px}

.comparison dd{font-size:16px}
.rk-details{font-size:13px}
summary{padding:6px 0}
summary:focus-visible{outline:3px solid var(--accent)}

.annual{table-layout:fixed}
.annual caption{text-align:left;
padding:8px 0;
color:var(--muted);
font-size:12px}

.annual th,.annual td{white-space:normal;
padding:8px 5px;
font-size:11px;
vertical-align:top}
.annual thead th{position:static}

.annual th:nth-child(2){width:16%}
.annual th:last-child{width:16%}
.annual td:last-child{text-align:left}

.annual tbody th{color:var(--ink);
font-weight:600;
background:transparent;
font-size:13px}
.annual th span{display:block;
font-size:12px;
font-weight:400;
color:var(--muted)}

footer{border-top:1px solid var(--line);
padding-top:18px;
color:var(--muted);
font-size:13px}
.source-list{display:flex;
flex-wrap:wrap;
gap:10px 18px}

@media(max-width:980px){.window-grid{grid-template-columns:1fr}
.metrics{grid-template-columns:repeat(3,minmax(0,1fr))}
.metrics div{display:block}
.metrics dd{margin-top:4px}

.annual,.annual tbody,.annual caption{display:block}
.annual thead{position:absolute;
width:1px;
height:1px;
overflow:hidden;
clip-path:inset(50%)}

.annual tr{display:block;
padding:10px 12px;
border:1px solid var(--line);
border-radius:8px;
background:var(--surface);
margin-bottom:12px}

.annual tbody th{display:flex;
gap:12px;
align-items:baseline;
width:100%;
font-size:21px;
padding:0 0 8px}

.annual tbody th span{font-size:14px}
.annual td{display:grid;
grid-template-columns:minmax(115px,40%) minmax(0,1fr);
gap:10px;
padding:6px 0;
text-align:right;
font-size:13px}

.annual td::before{content:attr(data-label);
text-align:left;
color:var(--muted);
font-size:12px}
.annual td:last-child{text-align:right;
border:0}
}

@media(max-width:540px){.metrics{grid-template-columns:1fr}
.metrics div{display:flex}
.metrics dd{margin:0}
.rk-hero h1{font-size:29px}
.rk-lede{font-size:16px}
}

@page{size:A4 landscape;
margin:12mm}
@media print{.scenario-switch{display:none}
#lapse:checked~main [data-scenario],#realize:checked~main [data-scenario]{display:block}

:root{--paper:white;
--surface:white;
--ink:#111;
--muted:#444;
--line:#ccc;
--accent:#234e3d;
--warn:#765000;
--warn-soft:white;
color-scheme:light}

.rk-page{padding:0}
.rk-section{margin-bottom:18px}
.window-card,tr{break-inside:avoid}
.window-grid{grid-template-columns:repeat(3,minmax(0,1fr))}

details::details-content{display:block;
content-visibility:visible}
.rk-toc{display:none}
}

"""


def render_report(
    result: dict[str, Any],
    *,
    receipt: dict[str, Any],
    audit: dict[str, Any],
    performance: dict[str, Any],
    presentation_date: str,
    publication_ref: str = "main",
    publication_path: str = DEFAULT_PUBLICATION_PATH,
) -> str:
    """Format saved metrics only; never reconstruct returns, rankings or equity."""
    if result.get("schema") != SCHEMA:
        raise ValueError(f"expected {SCHEMA}")
    for companion in (receipt, audit, performance):
        if companion.get("run_id") != result["run_id"]:
            raise ValueError("publication companion run_id mismatch")
    date.fromisoformat(presentation_date)
    if re.fullmatch(r"main|[0-9a-fA-F]{40}", publication_ref) is None:
        raise ValueError("publication_ref must be main or a full 40-hex commit")
    publication_path, task_id = _publication_path(publication_path)
    if result.get("study_id") != task_id:
        raise ValueError("publication_path task must match result study_id")
    publication_url = f"https://github.com/TaiwanCCyoyo/stock-research/blob/{publication_ref.lower()}/{publication_path}/"
    sources = "".join(
        f'<a href="{publication_url}{name}">{label}</a>'
        for name, label in (
            ("report.md", "研究結論"),
            ("results.json", "已存結果"),
            ("publication.zip", "收據與來源稽核 ZIP"),
            ("storage-audit.md", "儲存與保留稽核"),
            ("performance.json", "效能紀錄"),
            ("preregistration.md", "事前規則"),
            ("data-contract.md", "資料契約"),
        )
    )
    css = re.sub(r"@import\s+url\([^;]+;", "", (KIT / "report-kit.css").read_text(encoding="utf-8"))
    kit_script = (KIT / "report-kit.js").read_text(encoding="utf-8")
    panels = []
    for scenario, label in SCENARIOS.items():
        windows = "".join(_window(window, scenario) for window in result["windows"])
        panels.append(
            f'<div data-scenario="{scenario}"><section class="rk-section"><h2>{label} · 完整期間</h2>'
            f'<div class="window-grid">{windows}</div></section>'
            f'<section class="rk-section"><h2>逐年比較 · {label}</h2>{_annual(result["rows"], scenario, ytd=False)}</section>'
            f'<section class="rk-section"><h2>另列 YTD · {label}</h2>{_annual(result["rows"], scenario, ytd=True)}</section></div>'
        )
    status, overview = _overview(result["windows"])
    parameters = receipt.get("parameters", {})
    costs = "；".join(
        f"{label} {'未知' if parameters.get(key) is None else format(parameters[key] * 100, '.4f').rstrip('0').rstrip('.') + '%'}"
        for label, key in (("雙邊各收佣金", "commission"), ("各邊不利滑價", "slippage"), ("股票賣方稅", "stock_sell_tax"), ("ETF 賣方稅", "etf_sell_tax"))
    )
    commit = str(receipt.get("code", {}).get("commit", ""))
    code_link = "版本未記錄"
    if re.fullmatch(r"[0-9a-f]{40}", commit):
        code_link = f'<a href="https://github.com/TaiwanCCyoyo/stock-research/commit/{commit}">{commit[:8]}</a>'
    unresolved = (
        "".join(
            f"<li>{_text(row.get('year', ''))} · {_text(row.get('code', ''))}：{_reasons(row.get('reasons', []))}</li>" for row in audit.get("unresolved", [])
        )
        or "<li>來源准入稽核未列未解決項目；仍以各期模型狀態為準。</li>"
    )
    execution = performance.get("execution", {})
    reuse = (
        f"<p>已存執行紀錄：全市場重新排名呼叫 {_text(execution.get('full_ranking_calls', '未記錄'))}；"
        f"載入股票數 {_text(performance.get('loaded_issuer_count', '未記錄'))}。</p>"
    )
    embedded = (
        json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )
    rendered = f'''<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>每年買進前一年領先股：持有期補全 v2</title>
<meta name="report:title" content="每年買進前一年領先股：持有期補全 v2">
<meta name="report:summary" content="已存 v2 固定選股持有期結果；認股權雙情境、完整窗口與 v1 原值分開呈現。">
<meta name="report:date" content="{presentation_date}">
<meta name="report:status" content="exploratory">
<meta name="report:period" content="2011-2025">
<meta name="report:tags" content="台股,固定領先股,持有期補全,0050">
<meta name="report:kit" content="v1">
<style>{css}\n{STYLE}</style>
</head>
<body>
<input class="scenario-radio" type="radio" name="scenario" id="lapse" checked aria-label="認股權放棄情境">
<input class="scenario-radio" type="radio" name="scenario" id="realize" aria-label="認股權價值實現情境">
<main class="rk-page">
<header class="rk-hero">
<div class="rk-eyebrow">已存結果閱讀版 · 持有期補全 v2</div>
<h1>每年買進前一年領先股，<br>補齊持有期後結果如何？</h1>
<p class="rk-lede">{status}</p>
<div class="rk-meta">
<span class="rk-badge is-warn">探索研究 · 固定 v1 選股</span>
<span class="rk-badge">2011–2025 · YTD 另列</span>
<span class="rk-badge">閱讀版 {presentation_date}</span>
</div>
</header>
{overview}
<div class="rk-banner">
<strong>這是補全原選股的持有期，不是重新選全市場冠軍。</strong>未知排名候選仍未重建。終值模型可計不等於完整每日回撤可知，也不構成策略優越或顯著勝出的認證。</div>
<p>每年仍持有 v1 選定的同一股票與同一交易日期。完整期間比較採連續長抱 0050；逐年表則採同日期各自進出 0050。倍數包含初始本金，CAGR 是扣成本後的年化複利報酬。</p>
<nav aria-label="報告導覽">
<ul class="rk-toc">
<li>
<a href="#explore">情境與結果</a>
</li>
<li>
<a href="#details">限制與來源</a>
</li>
<li>
<a href="v1.html">閱讀 v1 原版</a>
</li>
</ul>
</nav>
<section id="explore" aria-labelledby="scenario-title">
<h2 id="scenario-title">切換認股權情境</h2>
<div class="scenario-switch">
<label for="lapse">認股權放棄</label>
<label for="realize">認股權價值實現</label>
</div>
<p class="rk-foot">兩者是事前列明的情境，不是實際行使紀錄，也不是報酬上下界。無認股權的持有期會共用同一結果。列印時同時保留兩種情境。</p>
</section>
{"".join(panels)}
<section id="details" class="rk-section">
<h2>理解結果的邊界</h2>
<details class="rk-details">
<summary>固定選股與 v1 比較</summary>
<p>選股範圍：{_text(result["selection_scope"])}。只補全 v1 報酬可計候選中的原領先股，沒有重排全市場；未知候選仍可能更好。</p>
<p>表內 v1 是原報告的四捨五入值；v2 使用本次資料版本。兩者不是同一批輸入的精確相等測試。原來未知的值仍以「未知」保留，不補成零。</p>
<p>
<a href="v1.html">開啟未改寫的 v1 閱讀版</a>
</p>
</details>
<details class="rk-details">
<summary>股利、認股權與成本假設</summary>
<p>現金股利仍為估值，假設除息日收盤立刻再投入分數單位；不代表實際付款日或歷史零股可成交性。認股權價值實現屬模型情境，並非實際行使或外部資金注入。</p>
<p>{costs}。再投入另收佣金；未充分處理個人稅負、最小佣金及整股資金限制。未扣成本／扣成本後分別對應原資料 gross／net。</p>
</details>
<details class="rk-details">
<summary>沿用前值標記與資料缺口</summary>
<p>沿用前值標記僅支援終值建模；停牌或無報價資訊日不代表能以該價成交。無報價資訊（N）表示缺少開高低收，不據此推論成交筆數一定為零。只要每日路徑不完整，完整每日最大回撤便維持未知，參考回撤另列。</p>
<ul>{unresolved}</ul>
</details>
<details class="rk-details">
<summary>保存、版本與執行範圍</summary>
<p>本頁只讀取已存小型 JSON 排版，未觸發市場計算。
定義 {_text(result["definition"])}；執行 {_text(result["run_id"])}；
資料截止 {_text(result["cutoff"])}；運算程式版本 {code_link}。</p>
{reuse}
<p>來源價格與權利證據仍在 producer；本頁不攜帶原始資料或私有輸入指紋。
完整重現仍需資料來源與收據所列輸入，不能只靠 HTML。</p>
</details>
</section>
<footer>
<p>這是已存 v2 結果的呈現，不是一次新評估。保留 <a href="v1.html">v1 原版</a> 供歷史比較。</p>
<p>在網站內嵌閱讀時，可先用上方「在新分頁開啟」查看外部來源。</p>
<div class="source-list">{sources}</div>
</footer>
</main>
<script type="application/json" id="report-data">{embedded}</script>
<script>{kit_script}</script>
</body>
</html>'''
    if len(rendered.encode("utf-8")) > MAX_BYTES:
        raise ValueError("rendered report exceeds 500 KiB")
    return rendered


def main(argv: Sequence[str] | None = None) -> int:
    """Build from the saved publication; absent inputs leave the old report intact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication", type=Path, default=TASK / "publications/completion-v2")
    parser.add_argument("--output", type=Path, default=TASK / "web-report/index.html")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--publication-ref", default="main")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    LOGGER.info("Reading saved completion publication from %s", args.publication)
    source = safe_path(args.publication).resolve()
    try:
        source_relative = source.relative_to(safe_path(ROOT).resolve()).as_posix()
    except ValueError as error:
        raise ValueError("publication must be inside the repository root") from error
    publication_path, _ = _publication_path(source_relative)
    publication = load_publication(source)
    rendered = render_report(
        publication["results.json"],
        receipt=publication["run-receipt.json"],
        audit=publication["admission-audit.json"],
        performance=publication["performance.json"],
        presentation_date=args.date,
        publication_ref=args.publication_ref,
        publication_path=publication_path,
    )
    if args.output.name == "index.html" and not (args.output.parent / "v1.html").is_file():
        raise ValueError("preserve the original report as v1.html before replacing index.html")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    LOGGER.info("Wrote %d bytes of saved-result HTML to %s", len(rendered.encode("utf-8")), args.output)
    return 0
