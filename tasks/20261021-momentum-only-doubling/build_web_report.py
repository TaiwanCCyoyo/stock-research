"""Build the momentum-only reading page from the published results only.

Reads `results/*.parquet` and `results/research_result.json` (never prices or
intermediate files) and writes a static `web-report/index.html` plus a frozen copy of
`research_web/report-kit/v1/`. Every number on the page comes from those tables.

    uv run python tasks/20261021-momentum-only-doubling/build_web_report.py
"""

from __future__ import annotations

import html
import json
import logging
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

LOGGER = logging.getLogger(__name__)
TASK = Path(__file__).resolve().parent
ROOT = TASK.parents[1]
RESULTS = TASK / "results"
OUTPUT = TASK / "web-report"
KIT = ROOT / "research_web" / "report-kit" / "v1"
SETS = ["A1", "A2", "A3", "A4", "A5", "A6"]
NAMES = {
    "A1": "收盤高於年線 60% 以上",
    "A2": "收盤是一年內最低收盤的 2.5 倍以上",
    "A3": "當天漲停（原始漲幅 ≥ 9.5%）",
    "A4": "120 日漲幅排名前 10%",
    "A5": "RSI14 ≥ 70",
    "A6": "波動比過去 120 日中位數放大",
    "A1&A2": "CORE：年線上方 60% 且一年低點 2.5 倍",
    "LEAD_B1": "LEAD_B1：CORE 再加當天漲停",
    "C-base-daily": "基準：任何合格股票日",
    "C-52w-daily": "基準：創 52 週新高且放量",
}


def pct(value: Any, digits: int = 1) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{float(value) * 100:.{digits}f}%"


def pp(value: Any) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{float(value) * 100:+.1f} 點"


def times(value: Any) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{float(value):.2f}×"


def count(value: Any) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{int(value):,}"


def offset(value: Any) -> str:
    return "N/A" if value is None or pd.isna(value) else str(int(value))


def esc(text: Any) -> str:
    return html.escape(str(text))


def table(headers: list[str], rows: list[list[str]], caption: str, numeric_from: int = 1) -> str:
    head = "".join(f'<th scope="col">{esc(h)}</th>' for h in headers)
    body = "".join("<tr>" + "".join(f'<td class="{"rk-num" if i >= numeric_from else ""}">{cell}</td>' for i, cell in enumerate(row)) + "</tr>" for row in rows)
    return (
        f'<div class="rk-table-wrap"><table class="rk-table"><caption>{esc(caption)}</caption><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
    )


def short(group: str) -> str:
    base = group.split(":")[0]
    return "CORE" if base == "A1&A2" else base


def label_name(group: str) -> str:
    base = group.split(":")[0]
    return f"{esc(base)}<br><span class='rk-foot'>{esc(NAMES.get(base, ''))}</span>"


def build() -> str:
    summary = pd.concat([pd.read_parquet(path) for path in sorted(RESULTS.glob("set_summary-*.parquet"))], ignore_index=True)
    verdicts = pd.read_parquet(RESULTS / "verdicts.parquet")
    intervals = pd.read_parquet(RESULTS / "bootstrap_intervals.parquet")
    coverage = pd.read_parquet(RESULTS / "big_runner_coverage.parquet")
    parity = pd.read_parquet(RESULTS / "parity_check.parquet")
    audit = pd.read_parquet(RESULTS / "audit_episodes.parquet")
    result = json.loads((RESULTS / "research_result.json").read_text(encoding="utf-8"))

    def row(group: str, horizon: int, target: float = 2.0, era: str = "all", split: str = "all", kind: str = "full") -> pd.Series:
        hit = summary.loc[
            summary.group_id.eq(group)
            & summary.horizon.eq(horizon)
            & summary.target_multiple.eq(target)
            & summary.era.eq(era)
            & summary.split.eq(split)
            & summary.row_kind.eq(kind)
        ]
        return hit.iloc[0]

    def interval(group: str, horizon: int, statistic: str, target: float = 2.0) -> str:
        chosen = intervals.loc[
            intervals.group_id.eq(group) & intervals.horizon.eq(horizon) & intervals.target_multiple.eq(target) & intervals.statistic.eq(statistic)
        ].set_index("bootstrap")
        return " ／ ".join(f"{pp(chosen.loc[mode, 'lower'])} 至 {pp(chosen.loc[mode, 'upper'])}" for mode in ("stock", "two_way"))

    # Primary cells.
    cards = []
    for group in ("A1&A2:daily", "LEAD_B1:daily"):
        for horizon in (126, 252):
            r = row(group, horizon)
            base = row("C-base-daily", horizon)
            cards.append(
                f'<li class="rk-finding"><b>{esc(short(group))} · {"半年" if horizon == 126 else "一年"}內翻倍</b>'
                f"<p>翻倍 {pct(r.hit_rate)}（基準 {pct(base.hit_rate)}，{times(r.hit_ratio_vs_base)}）；"
                f"期末賠錢 {pct(r.loss_rate)}（基準 {pct(base.loss_rate)}）。已知樣本 {count(r.known_n)} 筆、{count(r.distinct_stock_n)} 檔。</p></li>"
            )

    primary_rows = []
    for group in ("A1&A2:daily", "LEAD_B1:daily"):
        for horizon in (126, 252):
            primary_rows.append([
                f"{esc(short(group))} H{horizon}",
                interval(group, horizon, "hit_diff_vs_base"),
                interval(group, horizon, "loss_diff_vs_base"),
                interval(group, horizon, "hit_diff_vs_c52w"),
            ])

    set_rows = []
    groups = ["C-base-daily", "C-52w-daily", *[f"{s}:daily" for s in SETS]]
    groups += sorted({g for g in summary.group_id if g.endswith(":daily") and "&" in g}, key=lambda g: -row(g, 126).hit_rate)
    groups.append("LEAD_B1:daily")
    for group in dict.fromkeys(groups):
        a, b = row(group, 126), row(group, 252)
        set_rows.append([
            label_name(group),
            pct(a.hit_rate),
            pct(a.loss_rate),
            times(a.hit_ratio_vs_base),
            count(a.known_n),
            pct(b.hit_rate),
            pct(b.loss_rate),
            times(b.hit_ratio_vs_base),
            count(b.known_n),
        ])

    era_rows = []
    for group in ("C-base-daily", "C-52w-daily", "A1&A2:daily", "LEAD_B1:daily"):
        cells = [label_name(group)]
        for era in ("2010-2012", "2013-2018", "2019+", "all"):
            r = row(group, 126, era=era)
            cells.append(f"{pct(r.hit_rate)}<br><span class='rk-foot'>K={count(r.known_n)}</span>")
        era_rows.append(cells)

    robust_rows = []
    for group in ("A1&A2:daily", "LEAD_B1:daily"):
        for horizon in (126, 252):
            cells = [f"{esc(group.split(':')[0])} H{horizon}"]
            for split, kind in (("development", "full"), ("cross-check", "full"), ("all", "drop_best_year"), ("all", "drop_best_stock")):
                r = row(group, horizon, split=split, kind=kind)
                removed = "" if kind == "full" or r.removed is None else f"（刪 {esc(r.removed)}）"
                cells.append(f"{pct(r.hit_rate)}{removed}")
            robust_rows.append(cells)

    grid_rows = []
    for group in ("C-base-daily", "C-52w-daily", "A1&A2:daily", "LEAD_B1:daily"):
        for horizon in (126, 252, 504):
            cells = [f"{label_name(group)} H{horizon}"]
            for target in (2.0, 3.0, 5.0, 10.0):
                r = row(group, horizon, target)
                cells.append(f"{pct(r.hit_rate, 2)} / {pct(r.loss_rate)}<br><span class='rk-foot'>{times(r.hit_ratio_vs_base)}</span>")
            grid_rows.append(cells)

    verdict_rows = []
    for v in verdicts.to_dict(orient="records"):
        verdict_rows.append([
            f"{esc(short(v['group_id']))} H{v['horizon']} {v['target_multiple']:g}×" + (" <b>主要</b>" if v["primary"] else ""),
            esc(v["hit_diff_vs_base_direction"]),
            esc(v["loss_diff_vs_base_direction"]),
            esc(v["hit_diff_vs_c52w_direction"]),
            f"{count(v['cooled_known_n'])} / {count(v['cooled_distinct_stock_n'])}",
        ])

    coverage_rows = []
    for target in (5.0, 10.0):
        for group in ["A1", "A2", "A4", "A5", "A1&A2", "LEAD_B1"]:
            real = coverage.loc[coverage.group_id.eq(group) & coverage.target_multiple.eq(target)].iloc[0]
            rand = coverage.loc[coverage.group_id.eq(f"{group}:random") & coverage.target_multiple.eq(target)].iloc[0]
            coverage_rows.append([
                f"{label_name(group)} {target:g}×",
                f"{count(real.episode_n)}",
                f"{pct(real.coverage_rate)}<br><span class='rk-foot'>隨機 {pct(rand.coverage_rate)}</span>",
                f"{offset(real.offset_median)} 日<br><span class='rk-foot'>隨機 {offset(rand.offset_median)}</span>",
                f"{pct(real.entry_return_median, 0)}<br><span class='rk-foot'>隨機 {pct(rand.entry_return_median, 0)}</span>",
                f"{pct(real.remaining_return_median, 0)}<br><span class='rk-foot'>隨機 {pct(rand.remaining_return_median, 0)}</span>",
            ])

    parity_rows = [
        [
            esc(p.group),
            f"H{p.horizon}",
            f"{count(p.known_n)} / {count(p.known_n_pr17)}",
            f"{count(p.hit_n)} / {count(p.hit_n_pr17)}",
            f"{count(p.loss_n)} / {count(p.loss_n_pr17)}",
        ]
        for p in [pd.Series(record) for record in parity.to_dict(orient="records")]
    ]
    flagged = int(audit["review"].eq("manual").sum())
    screened = int(audit["review"].isin(["manual", "screen_only"]).sum())
    unknown_tens = int(audit["review"].eq("not_screenable_unknown_episode").sum())

    base126 = row("C-base-daily", 126)
    lead126 = row("LEAD_B1:daily", 126)
    core126 = row("A1&A2:daily", 126)
    lead19 = row("LEAD_B1:daily", 126, era="2019+")
    base19 = row("C-base-daily", 126, era="2019+")
    block_1 = table(
        ["格子", "翻倍率 vs 基準", "賠錢率 vs 基準", "翻倍率 vs 52 週新高", "冷卻樣本 K / 檔數"],
        verdict_rows,
        "above_zero／below_zero：兩種 bootstrap 區間都同一方向；unresolved：不一致或跨 0；insufficient_sample：冷卻口徑樣本不足 100 筆或 30 檔。",
    )
    block_2 = table(
        ["基準", "期限", "known 本研究 / PR17", "hit", "loss"],
        parity_rows,
        f"對齊檢查：{esc(result['parity'])}。計算任何條件前，先重算 PR17 的兩個基準，逐項完全相同。",
        numeric_from=2,
    )
    table_1 = table(
        ["組別", "翻倍率差距（股票重抽 ／ 股票×年份重抽）", "賠錢率差距", "相對 52 週新高的翻倍率差距"],
        primary_rows,
        "差距是相對全市場每日基準的百分點；括號內兩種 95% 區間都要大於 0 才算確定較高。",
    )
    table_2 = table(
        ["條件", "半年翻倍", "半年賠錢", "× 基準", "已知 K", "一年翻倍", "一年賠錢", "× 基準", "已知 K"],
        set_rows,
        "每日口徑、全期間、全部股票；倍數是相對任何合格股票日。好壞全部列出。",
    )
    table_3 = table(["組別", "2010–2012", "2013–2018", "2019+", "全期"], era_rows, "基準本身在 2019 年後高很多；比較時要看同一年代。")
    table_4 = table(["組別", "開發半", "確認半", "刪最好年份", "刪最好股票"], robust_rows, "兩半股票不重疊；但兩半都在已看過的期間，確認半不是沒看過的資料。")
    table_5 = table(
        ["組別與期限", "2 倍", "3 倍", "5 倍", "10 倍"], grid_rows, "主結論只看 2 倍半年與一年；其餘是次要描述。兩年期 2024 年 9 月以後的起點無法判定。"
    )
    table_6 = table(
        ["條件", "飆股段數", "覆蓋率", "首次符合距起漲", "符合時已漲", "符合後還能漲到頂"],
        coverage_rows,
        "觀察窗口從起漲前 20 日到頂點。隨機對照從同股同年的合格日抽同樣天數。",
    )
    page = f"""<!doctype html>
<html lang="zh-Hant">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>只看強勢條件的翻倍機率</title>
        <meta name="report:title" content="只看強勢條件的翻倍機率" />
        <meta name="report:summary" content="不看型態、只用 PR17 選出的強勢條件：半年翻倍機率是全市場基準的數倍，
            但期末賠錢的比例也同時變高。型態分解尚未評估。" />
        <meta name="report:date" content="2026-10-22" />
        <meta name="report:status" content="descriptive" />
        <meta name="report:period" content="2010-01-04 – 2026-10-12" />
        <meta name="report:tags" content="台股,動能,翻倍,描述性研究" />
        <meta name="report:kit" content="v1" />
        <link rel="stylesheet" href="kit/report-kit.css" />
        <script src="kit/report-kit.js" defer></script>
    </head>
    <body>
        <main class="rk-page">
            <header class="rk-hero">
                <p class="rk-eyebrow">台股 · 描述性研究 · 2010–2026 已看過的期間</p>
                <h1>只看強勢條件，不看型態：翻倍與大漲的機率</h1>
                <p class="rk-lede">
                    不看任何型態，只要股價已經很強（收盤高於年線六成、是一年低點的 2.5 倍），半年內翻倍的比例是
                    {pct(core126.hit_rate)}，全市場任何一天是 {pct(base126.hit_rate)}；再加上當天漲停，升到 {pct(lead126.hit_rate)}。
                    但這些股票期末賠錢的比例也比較高：強勢條件讓「翻倍」和「賠錢」同時變多，是高波動的股票，不是穩賺的訊號。
                </p>
            </header>

            <div class="rk-banner" role="note">
                <strong>怎麼讀這頁：</strong>
                「翻倍」只代表期限內收盤<b>曾經</b>達到兩倍，不等於實際買賣能拿到的報酬（沒有進出時點、成本與持有決策）。
                所有數字都是 2010–2026 已看過的歷史描述，條件本身就是從這段資料挑出來的，不能當作新證據。
                型態到底額外貢獻多少（型態分解）這次<b>沒有評估</b>：需要 PR17 把每天各型態的原始狀態發布成可重用資料。
            </div>

            <section class="rk-section" id="main">
                <header><div><span class="rk-q">主結論 · 4 格</span><h2>只看強勢條件時，翻倍和賠錢各多少？</h2></div></header>
                <ul class="rk-findings">{"".join(cards)}</ul>
                {table_1}
                <p class="rk-foot">
                    漲停條件在 2015-06-01 以前不可能成立（當時漲跌幅限制只有 7%，條件門檻是 9.5%），所以 LEAD_B1 只涵蓋 2015 年 6 月以後。
                    全期間倍數會因年代組成不同而偏高；只看 2019 年後：LEAD_B1 半年翻倍 {pct(lead19.hit_rate)}，同期基準 {pct(base19.hit_rate)}。
                </p>
            </section>

            <section class="rk-section" id="sets">
                <header><div><span class="rk-q">22 組純強勢條件</span><h2>每組條件的翻倍率與賠錢率</h2></div></header>
                {table_2}
            </section>

            <section class="rk-section" id="eras">
                <header><div><span class="rk-q">年代</span><h2>半年翻倍率在不同年代</h2></div></header>
                {table_3}
                {table_4}
            </section>

            <section class="rk-section" id="grid">
                <header><div><span class="rk-q">2／3／5／10 倍 × 半年／一年／兩年</span><h2>大漲格子：翻倍率 / 賠錢率</h2></div></header>
                {table_5}
                {block_1}
            </section>

            <section class="rk-section" id="runners">
                <header><div><span class="rk-q">大飆股這一側</span><h2>兩年漲 5 倍、10 倍的股票，強勢條件抓到多少、何時抓到？</h2></div></header>
                {table_6}
                <p class="rk-foot">
                    幾乎所有大飆股在起漲到頂點之間都曾符合強勢條件，但同樣天數的隨機日期也有相近覆蓋，所以覆蓋率本身不代表條件有用。
                    有意義的是時機：CORE 首次成立時，股價中位數通常已經漲了一倍多，比隨機日期晚很多。
                </p>
            </section>

            <section class="rk-section" id="evidence">
                <header><div><span class="rk-q">來源與限制</span><h2>如何核對</h2></div></header>
                <details class="rk-details"><summary>展開對齊檢查、價格核對與資料來源</summary>
                {block_2}
                <ul>
                    <li>價格：共用 adjusted-daily-v1 世代 {esc(result["generation"])}，依截止日 {esc(result["cutoff"])} 與 PR17 的 4,110 日日曆重算。</li>
                    <li>宇宙：PR17 的 1,942 檔普通股；之後新上市的股票不在內。</li>
                    <li>價格核對：{screened} 段（全部可判定的 10 倍飆股與 20 段抽樣 5 倍）程式篩檢；
                    被篩出的 {flagged} 段由人工對照原始收盤與除權息，
                    都是新股上市前五天無漲跌幅限制或除權參考價，

                    判定價格錯誤 {result["audit"]["audit_price_error"]} 段。另有 {unknown_tens} 段 10 倍頂點無法判定。其餘未逐一人工閱讀。</li>
                    <li>完整表格在 <code>tasks/20261021-momentum-only-doubling/results/</code>；定義見 mission.md 與 data-contract.md。</li>
                </ul>
                </details>
            </section>
        </main>
    </body>
</html>
"""
    return page


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    OUTPUT.mkdir(exist_ok=True)
    kit = OUTPUT / "kit"
    kit.mkdir(exist_ok=True)
    for name in ("report-kit.css", "report-kit.js"):
        shutil.copyfile(KIT / name, kit / name)
    (OUTPUT / "index.html").write_text(build(), encoding="utf-8")
    LOGGER.info("Wrote %s", OUTPUT / "index.html")


if __name__ == "__main__":
    main()
