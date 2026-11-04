"""Project saved final tables into a portable reading view; never run market calculations."""

from __future__ import annotations

import argparse
import json
import logging
import math
from numbers import Real
from pathlib import Path
from typing import Any, cast

import pandas as pd

LOGGER = logging.getLogger(__name__)
TASK = Path(__file__).resolve().parent
GROUPS = {
    "C-base-daily": "一般股票日",
    "C-52w-daily": "一年新高且放量",
    "CORE": "雙重強勢",
    "LEAD_B1": "雙重強勢＋大漲日",
}
FLAGS = {
    "Y1": "型態支撐（不適用）",
    "Y2": "型態下緣（不適用）",
    "Y3": "跌破起點固定支撐低點",
    "X5_MA20": "收盤低於20日均線",
    "X5_MA60": "收盤低於60日均線",
    "X6_10": "較起點跌至少10%",
    "X6_15": "較起點跌至少15%",
    "X7": "收盤低於布林下軌",
    "X8": "新確認較低高點",
}
VERDICTS = {
    "not_applicable": "不適用",
    "inseparable": "樣本不足以分開判讀",
    "weakens_beyond_drop": "分層後仍有下降證據",
    "weakens_with_drop": "合併下降，分層後未確立",
    "opposite": "合併反向上升",
    "unresolved": "尚無明確判讀",
}
KEYS = ["group_id", "horizon", "target_multiple", "landmark", "flag_id"]
CHUNK_LIMIT = 380_000
SOURCE_URL = "https://github.com/TaiwanCCyoyo/stock-research/tree/3cf4411fb7450c0c2d7fa100548d090e2615efbe/tasks/20261024-strength-weakening-flags/results"


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def load_tables(root: Path, kind: str) -> pd.DataFrame:
    paths = sorted(root.glob(f"{kind}-*.parquet"))
    if len(paths) != 12:
        raise ValueError(f"expected twelve saved {kind} tables, got {len(paths)}")
    frame = pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
    LOGGER.info("Read %s saved %s rows", len(frame), kind)
    return frame


def browser_chunks(frame: pd.DataFrame, kind: str, destination: Path) -> list[str]:
    """Keep original scalar values and nulls; split only the presentation transport."""
    columns = frame.columns.tolist()
    rows = frame.astype(object).where(frame.notna(), None).values.tolist()
    prefix = f'window.REPORT_TABLES.{kind}.push({{"columns":{encode(columns)},"rows":['
    suffix = "]});\n"
    paths: list[str] = []
    batch: list[str] = []
    length = len((prefix + suffix).encode("utf-8"))

    def save() -> None:
        path = destination / f"{kind}-{len(paths):03}.js"
        payload = prefix + ",".join(batch) + suffix
        if len(payload.encode("utf-8")) >= 500 * 1024:
            raise ValueError(f"presentation chunk exceeds repository limit: {path.name}")
        path.write_text(payload, encoding="utf-8", newline="\n")
        paths.append(path.name)

    for row in rows:
        payload = encode(row)
        size = len(payload.encode("utf-8")) + 1
        if batch and length + size > CHUNK_LIMIT:
            save()
            batch = []
            length = len((prefix + suffix).encode("utf-8"))
        batch.append(payload)
        length += size
    if batch:
        save()
    # This validates serialization of saved aggregates, not the study again.
    restored: list[list[Any]] = []
    for name in paths:
        payload = (destination / name).read_text(encoding="utf-8")
        table = json.loads(payload[payload.index("(") + 1 : -3])
        if table["columns"] != columns:
            raise ValueError("presentation columns changed during serialization")
        restored.extend(table["rows"])
    if restored != rows:
        raise ValueError("presentation scalar values changed during serialization")
    return paths


def number(value: object, *, percent: bool = False) -> str:
    if value is None:
        return "—"
    if not isinstance(value, Real):
        raise TypeError("a saved numerical result is required")
    numeric = float(value)
    if not math.isfinite(numeric):
        return "—"
    return f"{numeric * 100:.2f}" if percent else f"{int(numeric):,}"


def primary_markdown(primary: pd.DataFrame) -> str:
    lines = [
        "| 組別 | 期限 | 訊號 | 已觸發：hit/known（率） | 未觸發：hit/known（率） | 合併差 pp | 分層差 pp | 達標前觸發比例 | 判讀 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in primary.to_dict("records"):
        triggered = f"{number(row['triggered_hit_n'])}/{number(row['triggered_known_n'])}（{number(row['triggered_hit_rate'], percent=True)}%）"
        untriggered = f"{number(row['all_false_hit_n'])}/{number(row['all_false_known_n'])}（{number(row['untriggered_hit_rate'], percent=True)}%）"
        lines.append(
            f"| {GROUPS[str(row['group_id'])]} | {row['horizon']}日 | {FLAGS[str(row['flag_id'])]} | {triggered} | {untriggered} | "
            f"{number(row['pooled_difference'], percent=True)} | {number(row['standardized_difference'], percent=True)} | "
            f"{number(row['false_abandonment_rate'], percent=True)}% | {VERDICTS[str(row['verdict'])]} |"
        )
    return "\n".join(lines) + "\n"


def export_appendix(summary: pd.DataFrame, destination: Path) -> None:
    """All saved slices in bounded CSV parts, plus one table of all pooled cells."""
    destination.mkdir(exist_ok=True)
    lines = ["# 完整表格附錄", "", "數字直接來自 C 保存的終表，沒有重算行情、bootstrap 或判讀。CSV 比例欄採 0–1；差值乘 100 才是百分點。", ""]
    for identity, rows in summary.groupby(["group_id", "horizon"], sort=True):
        group, horizon = cast(tuple[str, int], identity)
        names = []
        for index, start in enumerate(range(0, len(rows), 350)):
            name = f"{group}-H{horizon}-{index + 1}.csv"
            path = destination / name
            rows.iloc[start : start + 350].to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
            if path.stat().st_size >= 500 * 1024:
                raise ValueError(f"appendix part exceeds limit: {name}")
            names.append(f"[第{index + 1}部分]({name})")
        lines.append(f"- {GROUPS[str(group)]}、{horizon} 交易日：{'、'.join(names)}（含全部 pooled、年代、分半、移除最大貢獻切片）。")
    lines.extend([
        "",
        f"逐格信賴區間與 rise 分層 counts 由展示頁完整提供；原始 Parquet 與收據仍以 [C 的正式結果]({SOURCE_URL}) 為準。",
        "",
    ])
    (destination / "index.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=TASK / "results", help="Existing C final tables; never producer data")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary = load_tables(args.results_root, "summary")
    intervals = load_tables(args.results_root, "intervals")
    strata = load_tables(args.results_root, "rise-strata")
    full = cast(pd.DataFrame, summary.loc[(summary["split"] == "all") & (summary["era"] == "all") & (summary["row_kind"] == "full")])
    primary = cast(pd.DataFrame, full.loc[full["primary"].eq(True)])
    if len(full) != 1728 or len(primary) != 28 or full.duplicated(subset=KEYS).any():
        raise ValueError("saved output grid is not the preregistered grid")
    data = TASK / "web-report" / "data"
    data.mkdir(parents=True, exist_ok=True)
    scripts = ["meta.js"]
    for kind, frame in [("summary", summary), ("intervals", intervals), ("strata", strata)]:
        scripts.extend(browser_chunks(frame, kind, data))
    meta = {
        "groupLabels": GROUPS,
        "flagLabels": FLAGS,
        "verdictLabels": VERDICTS,
        "sourceUrl": SOURCE_URL,
        "reportUrl": "https://github.com/TaiwanCCyoyo/stock-research/blob/main/tasks/20261024-strength-weakening-flags/report.md",
        "date": "2026-10-28",
        "period": "2010-01-04～2026-10-12",
        "fullCells": len(full),
        "primaryCells": len(primary),
    }
    (data / "meta.js").write_text(f"window.REPORT_META={encode(meta)};\n", encoding="utf-8", newline="\n")
    manifest = (
        '"use strict";\nwindow.REPORT_TABLES={summary:[],intervals:[],strata:[]};\n'
        "window.REPORT_READY=(async()=>{\n"
        "const base=new URL('.',document.currentScript.src);\n"
        f"for(const file of {encode(scripts)}){{\n"
        "await new Promise((resolve,reject)=>{const script=document.createElement('script');\n"
        "script.src=new URL(file,base).href;script.onload=resolve;script.onerror=()=>reject(new Error('報告資料載入失敗'));\n"
        "document.head.appendChild(script);});}\nreturn window.REPORT_TABLES;})();\n"
    )
    (data / "manifest.js").write_text(manifest, encoding="utf-8", newline="\n")
    export_appendix(summary, TASK / "appendix")
    diagnostic = TASK.parents[1] / ".tmp" / "strength-flags-presentation"
    diagnostic.mkdir(parents=True, exist_ok=True)
    (diagnostic / "primary-table.md").write_text(primary_markdown(primary), encoding="utf-8", newline="\n")
    LOGGER.info("Exported %s browser chunks and all saved slices; original results untouched", len(scripts) - 1)


if __name__ == "__main__":
    main()
