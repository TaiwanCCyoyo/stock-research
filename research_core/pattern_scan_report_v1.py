"""Export the stored PR17 Q1 tables for a truthful partial web report."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from io import BytesIO
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research_core.artifact_store import publish_new_directory, relative_name, safe_path
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_groups_v1 import PRIMARY
from research_core.pattern_scan_parquet_v1 import read_frame
from research_core.run_receipt import SCHEMA as RECEIPT_SCHEMA

HORIZONS = (126, 252)
COUNTS = ("event_n", "known_n", "hit_n", "loss_n", "unknown_n", "censored_n", "distinct_stock_n")
RATES = ("hit_rate", "loss_rate")
LOGGER = logging.getLogger(__name__)
PROJECTION = (*COUNTS, *RATES)
FACETS = {
    "split": "cross-check",
    "era": "all",
    "mkt": "all",
    "row_kind": "full",
    "cohort_id": "union",
    "feature_id": "unconditional",
    "bin_id": "all",
    "condition_status": "known",
}


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, Integral)):
        return int(value)
    if isinstance(value, (np.floating, Real)):
        number = float(value)
        return number if np.isfinite(number) else None
    if pd.isna(value):
        return None
    return value


def _code_provenance(value: Any, *, label: str, historical: bool) -> str:
    """Render code identity objects as readable provenance, preserving dirty state."""
    if isinstance(value, dict):
        commit = value.get("commit") or value.get("code_commit") or value.get("sha")
        dirty = value.get("dirty")
        if isinstance(commit, str) and commit:
            state = (
                "dirty=true（歷史來源）"
                if dirty is True and historical
                else "dirty=false"
                if dirty is False
                else f"dirty={str(dirty).lower()}"
                if isinstance(dirty, bool)
                else "dirty狀態未記錄"
            )
            history = "；此為歷史數值來源，不代表本次匯出執行者" if historical else ""
            return f"{label}：{commit}（{state}{history}）"
    if isinstance(value, str) and value:
        return f"{label}：{value}" + ("（歷史數值來源，不代表本次匯出執行者）" if historical else "")
    raise ValueError(f"{label}: unsupported code provenance shape")


def _read_receipt(root: Path, target: str) -> tuple[dict[str, Any], bytes, dict[str, bytes]]:
    directory = safe_path(root / target)
    receipt_path = safe_path(directory / f"{target}-receipt.json")
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    if not isinstance(receipt, dict):
        raise ValueError(f"{target}: receipt must be an object")
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValueError(f"{target}: expected {RECEIPT_SCHEMA}")
    declared = receipt.get("results")
    expected = {f"{target}-summary.parquet", f"{target}-annual.parquet"}
    if not isinstance(declared, dict) or set(declared) != expected:
        raise ValueError(f"{target}: receipt must name exactly the final summary and annual tables")
    tables: dict[str, bytes] = {}
    for name in sorted(expected):
        relative_name(name)
        descriptor = declared[name]
        if not isinstance(descriptor, dict) or descriptor.get("path") != name:
            raise ValueError(f"{target}: result path must remain relative to its family directory: {name}")
        raw = safe_path(directory / name).read_bytes()
        # Verify each final table once, against the very bytes decoded and exported.
        if len(raw) != descriptor.get("bytes") or hashlib.sha256(raw).hexdigest() != descriptor.get("sha256"):
            raise ValueError(f"artifact hash/size mismatch: {name}")
        tables[name] = raw
    return receipt, receipt_bytes, tables


def _source_identity(receipt: dict[str, Any], target: str) -> tuple[Any, Any, Any, Any]:
    parameters = receipt.get("parameters")
    if not isinstance(parameters, dict) or parameters.get("target") != target:
        raise ValueError(f"{target}: receipt target/parameters invalid")
    source = parameters.get("numerical_source")
    source_code = source.get("code") if isinstance(source, dict) else None
    source_id = source.get("source_id") if isinstance(source, dict) else None
    input_id = parameters.get("input_id")
    stock_count = parameters.get("stock_count")
    code = receipt.get("code")
    if not isinstance(source_id, str) or not source_id or not isinstance(input_id, str) or not input_id:
        raise ValueError(f"{target}: source_id and input_id are required")
    if not isinstance(source_code, (str, dict)) or not source_code:
        raise ValueError(f"{target}: numerical source code is required")
    if isinstance(stock_count, bool) or not isinstance(stock_count, int) or stock_count < 1:
        raise ValueError(f"{target}: stock_count must be positive")
    if not isinstance(code, dict):
        raise ValueError(f"{target}: projection executor code identity is missing")
    return input_id, source_id, source_code, (stock_count, code)


def build_q1_report_data(q1_root: Path, *, as_of: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Build JSON-safe report metadata and byte-identical final-table payloads."""
    if date.fromisoformat(as_of).isoformat() != as_of:
        raise ValueError("as_of must be a canonical ISO date")
    root = safe_path(Path(q1_root))
    identities: list[tuple[Any, Any, Any, Any]] = []
    family_rows: dict[str, list[dict[str, Any]]] = {}
    files: dict[str, bytes] = {}
    receipts: dict[str, bytes] = {}
    table_meta: dict[str, dict[str, Any]] = {}

    for target in PATTERNS:
        receipt, receipt_bytes, paths = _read_receipt(root, target)
        identities.append(_source_identity(receipt, target))
        receipts[target] = receipt_bytes
        summary_name = f"{target}-summary.parquet"
        annual_name = f"{target}-annual.parquet"
        summary_bytes, annual_bytes = paths[summary_name], paths[annual_name]
        # Use the same retained final bytes for presentation and downloads.
        summary = read_frame(BytesIO(summary_bytes))
        annual = read_frame(BytesIO(annual_bytes))
        required = {"pattern_id", "horizon", "control_id", *FACETS, *PROJECTION}
        if not required.issubset(summary.columns):
            raise ValueError(f"{target}: summary schema lacks {sorted(required - set(summary.columns))}")
        selected = summary
        for key, value in FACETS.items():
            selected = selected.loc[selected[key].eq(value)]
        selected = selected.loc[
            selected["pattern_id"].eq(target) & selected["horizon"].isin(HORIZONS) & selected["control_id"].isin(("pattern", PRIMARY[target]))
        ]
        order = [(horizon, control) for horizon in HORIZONS for control in ("pattern", PRIMARY[target])]
        indexed = {(int(row.horizon), row.control_id): row for row in selected.itertuples(index=False)}
        if len(selected) != 4 or set(indexed) != set(order):
            raise ValueError(f"{target}: expected exactly four Q1 rows in fixed horizon/control scope")
        rows: list[dict[str, Any]] = []
        for horizon, control in order:
            record = {"target": target, "horizon": horizon, "control_id": control}
            source_row = indexed[(horizon, control)]
            for column in PROJECTION:
                record[column] = _json_value(getattr(source_row, column))
            rows.append(record)
        family_rows[target] = rows
        for kind, raw in (("summary", summary_bytes), ("annual", annual_bytes)):
            name = f"{target}-{kind}.parquet"
            output_name = relative_name(f"tables/{name}")
            files[output_name] = raw
            table_meta[output_name] = {"rows": len(summary if kind == "summary" else annual), "bytes": len(raw)}

    if len(set(json.dumps(item, sort_keys=True, default=str) for item in identities)) != 1:
        raise ValueError("Q1 receipts have inconsistent input/source/stock/code identities")
    input_id, source_id, numerical_source_code, (stock_count, executor_code) = identities[0]

    for target in PATTERNS:
        files[relative_name(f"receipts/{target}-receipt.json")] = receipts[target]
    downloads = [
        {
            "label": f"{name.rsplit('/', 1)[-1].split('-', 1)[0]} {'摘要表' if '-summary.' in name else '年度表'}（Parquet）",
            "href": f"data/{name}",
            **table_meta[name],
        }
        for name in sorted(table_meta)
    ]
    columns = [
        {"key": "target", "label": "型態", "kind": "text"},
        {"key": "horizon", "label": "觀察期（交易日）", "kind": "integer"},
        {"key": "control_id", "label": "比較組", "kind": "text"},
        *[
            {
                "key": key,
                "label": {
                    "event_n": "事件數",
                    "known_n": "已知樣本分母（known_n）",
                    "hit_n": "命中數",
                    "loss_n": "虧損數",
                    "unknown_n": "未知數",
                    "censored_n": "設限數",
                    "distinct_stock_n": "不同股票數",
                }[key],
                "kind": "integer",
            }
            for key in COUNTS
        ],
        *[{"key": key, "label": "命中率" if key == "hit_rate" else "虧損率", "kind": "percent"} for key in RATES],
    ]
    report = {
        "schema": "pattern-scan-web-report.v1",
        "title": "2010起全市場型態掃描",
        "asOf": as_of,
        "status": "partial",
        "study": {
            "period": ["2010-01-04", "2026-10-12"],
            "stockN": stock_count,
            "horizons": list(HORIZONS),
            "generation": "2026-10-15-20261015T161626Z",
            "cutoff": "2026-10-12",
        },
        "overview": [
            {"label": "Q1", "value": "12 種型態均有完整結果", "note": "既有無條件交叉檢核統計，僅供描述。"},
            {"label": "涵蓋範圍", "value": f"{stock_count} 檔股票", "note": "已核對 12 種型態的輸入與來源識別一致。"},
        ],
        "questions": [
            {
                "id": f"Q{i}",
                "title": ("無條件型態結果" if i == 1 else ("條件與組合", "同條件對照", "飆股段落覆蓋與時間", "命中與未命中路徑", "失效訊號與代價")[i - 2]),
                "status": "complete" if i == 1 else "pending",
                "conclusion": "12 種型態的 Q1 表格均已存在。這些描述性統計不代表策略獲准，也不構成超額表現證據。"
                if i == 1
                else "尚未完成；獨立重建 10 個事件／5 個候選的確認程序仍待進行。",
                "notes": [
                    (
                        "範圍：12 種型態；交叉檢核 split=cross-check、全期間 era=all、"
                        "全市場 mkt=all、row_kind=full、union cohort、unconditional feature 與 known 狀態；"
                        "各型態比較 pattern 組及其主要 control，觀察期為 126 與 252 個交易日。"
                    ),
                    "命中定義為 126／252 個交易日內收盤價達錨點的 2 倍；虧損定義為完整觀察期未命中且期末收盤價低於錨點。",
                    "分母為已知樣本 known_n；缺失與設限樣本不納入，unknown_n 與 censored_n 可能重疊。",
                    "10%／20% 僅為負責人參考線；Q4–Q6 僅作描述。來源表保留 2010–2012 年品質分層。",
                    "顯示的 generation 是歷史價格等價交接參考；本匯出讀取已完成的原始衍生表，未重新讀取共用資料。",
                ]
                if i == 1
                else [],
                "tables": [
                    {
                        "id": "q1",
                        "title": "既有 Q1 摘要列",
                        "scope": "交叉檢核、全期間、全市場、完整列、union cohort、無條件且 known；包含 pattern 與主要比較組，觀察期 126／252 日",
                        "denominator": "分母為 known_n；unknown_n 與 censored_n 排除於分母且可能重疊",
                        "columns": columns,
                        "rows": [row for target in PATTERNS for row in family_rows[target]],
                        "downloads": downloads,
                    }
                ]
                if i == 1
                else [],
            }
            for i in range(1, 7)
        ],
        "audit": {"status": "pending", "notes": ["Q2–Q6 尚未完成；獨立重建 10 個事件／5 個候選的確認程序仍待進行。"]},
        "provenance": [
            {"label": "輸入識別", "value": input_id},
            {"label": "數值來源識別", "value": source_id},
            {"label": "數值來源程式", "value": _code_provenance(numerical_source_code, label="歷史數值來源程式", historical=True)},
            {"label": "投影執行程式", "value": _code_provenance(executor_code, label="本次投影執行程式", historical=False)},
            *[
                {"label": f"{target} 原始收據", "value": "原始 Q1 收據；內含最終表格路徑與來源中繼資料。", "href": f"data/receipts/{target}-receipt.json"}
                for target in PATTERNS
            ],
            {
                "label": "資料沿革",
                "value": "數值結果早於本報告匯出；投影執行程式僅作來源紀錄。Generation 為歷史價格等價交接參考，不表示本次匯出重新讀取共用資料。",
            },
        ],
        "limitations": ["目前僅完成 Q1；Q2–Q6 尚待完成。", "匯出不重新計算或重排研究統計。"],
        "downloads": downloads,
    }
    files["summary.js"] = ("window.REPORT_DATA = " + json.dumps(report, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + ";\n").encode("utf-8")
    return report, files


def export_q1_report_data(q1_root: Path, output: Path, *, as_of: str) -> dict[str, Any]:
    """Build and publish a new report data directory without replacing an existing one."""
    output = safe_path(Path(output))
    root = safe_path(Path(q1_root))
    if output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("report output must not overlap original Q1 results")
    if output.exists():
        raise FileExistsError(f"report data destination already exists: {output}")
    report, files = build_q1_report_data(q1_root, as_of=as_of)
    publish_new_directory(output, files)
    LOGGER.info("Published partial Q1 report data families=%d tables=%d output=%s", len(PATTERNS), len(files) - len(PATTERNS) - 1, output)
    return report
