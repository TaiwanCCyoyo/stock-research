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
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

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


def _report_slice(frame: pd.DataFrame, **facets: Any) -> pd.DataFrame:
    for key, value in facets.items():
        frame = frame.loc[frame[key].eq(value)]
    return frame


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{key: _json_value(value) for key, value in row.items()} for row in frame.to_dict("records")]


def _difference(left: Any, right: Any) -> float | None:
    left, right = _json_value(left), _json_value(right)
    return None if left is None or right is None else (left - right) * 100


def _report_table(table_id: str, title: str, frame: pd.DataFrame, *, collapsible: bool = False) -> dict[str, Any]:
    labels = {
        "target": "家族",
        "candidate": "原固定候選",
        "atoms": "原條件",
        "horizon": "觀察期（交易日）",
        "pattern_minus_no_pattern_pp": "型態 − 同條件排除型態（百分點）",
        "pattern_minus_all_pp": "型態 − 同條件全部（百分點）",
        "pattern_known_n": "型態 K",
        "no_pattern_known_n": "排除型態 K",
        "all_known_n": "全部 K",
        "loss_rate": "虧損率",
        "group": "型態／原固定候選",
        "episode_n": "段落數",
        "pattern_coverage_rate": "型態覆蓋率",
        "random_coverage_rate": "同配額 random 覆蓋率",
        "coverage_delta_pp": "覆蓋差距（百分點）",
        "pattern_matched_n": "型態命中段落",
        "pattern_unmatched_n": "型態未命中",
        "pattern_unknown_n": "型態未知",
        "random_matched_n": "random 命中段落",
        "random_unmatched_n": "random 未命中",
        "random_unknown_n": "random 未知",
    }

    def kind(column: str) -> str:
        if column.endswith("_pp"):
            return "percentage_points"
        if column.endswith(("_rate", "_bound")):
            return "percent"
        if column.endswith("_n") or column == "horizon":
            return "integer"
        return "number" if pd.api.types.is_numeric_dtype(frame[column]) else "text"

    return {
        "id": table_id,
        "title": title,
        "scope": "既有終表：cross-check、era=all、mkt=all；候選沿用原固定清單，未重新選取",
        "denominator": "known 分母排除未知／資格排除；unknown 與 censored 可重疊。零分母保留 N/A。",
        "collapsible": collapsible,
        "columns": [{"key": column, "label": labels.get(column, column), "kind": kind(column)} for column in frame.columns],
        "rows": _records(frame),
    }


def _set_available_status(report: dict[str, Any], provided: dict[str, list[str]]) -> None:
    """Describe supplied terminal tables, without inferring a running process."""
    for question in report["questions"]:
        if question["id"] not in provided:
            continue
        families = provided[question["id"]]
        missing = [target for target in PATTERNS if target not in families]
        question["status"] = "pending" if not families else "partial" if missing else "complete"
        question["conclusion"] = (
            f"已提供終表 {len(families)}/{len(PATTERNS)} 家族：{'／'.join(families) or '無'}。"
            + (f"待完成：{'／'.join(missing)}。" if missing else "此題數值階段終表齊備。")
            + "這是終表提供狀態，不代表程序正在執行、完整網頁交付、owner 驗收、final handoff 或 hold 可釋放。"
        )
    # Table availability alone cannot certify the study's final handoff.
    report["status"] = "partial"
    report["overview"] = [
        {
            "label": "已提供終表",
            "value": f"Q1 {len(PATTERNS)} 家族；Q2–Q3 {len(provided['Q2'])}；Q4 {len(provided['Q4'])}；Q5–Q6 {len(provided['Q5'])}",
            "note": "只根據同一讀表迴圈已取得的原終表；缺少 phase 收據的家族標為待完成。",
        },
        {"label": "交付狀態", "value": "完整報告／final handoff 與 owner 驗收仍分開確認", "note": "終表齊備不自動釋放 hold；iframe 實際下載仍待人工驗收。"},
    ]


def add_stored_comparisons(report: dict[str, Any], q1_root: Path, remaining_root: Path) -> None:
    """Present existing final statistics; no research, receipt creation or integrity pass.

    A phase's existing terminal receipt is its completion marker. Active phases
    are omitted, so a report never promotes a partially written checkpoint.
    """
    headline = []
    baselines = []
    for target in PATTERNS:
        summary = read_frame(q1_root / target / f"{target}-summary.parquet")
        selected = _report_slice(summary, **{**FACETS, "split": "all"})
        for horizon in HORIZONS:
            rows = selected.loc[selected["horizon"].eq(horizon)].set_index("control_id")
            pattern, daily, control = (rows.loc[key] for key in ("pattern", "C-base-daily", "C-base-all"))
            hit, base = _json_value(pattern["hit_rate"]), _json_value(daily["hit_rate"])
            headline.append({
                "target": target,
                "horizon": horizon,
                "baseline_multiple": None if hit is None or base is None or base == 0 else hit / base,
                "delta_pp": _difference(hit, control["hit_rate"]),
                "known_n": _json_value(pattern["known_n"]),
                "control_known_n": _json_value(control["known_n"]),
                "loss_rate": _json_value(pattern["loss_rate"]),
            })
            if target == PATTERNS[0]:
                baselines.append({"horizon": horizon, "hit_rate": base, "known_n": _json_value(daily["known_n"])})
    report["comparisonSummary"] = {
        "scope": "Q1 無額外條件，split=all／era=all／mkt=all、full、union、known；候選差距另見 Q2–Q3。倍數不是報酬倍數。",
        "rows": headline,
        "baselines": baselines,
    }
    for question in report["questions"]:
        if question["id"] != "Q1":
            question.update(tables=[], notes=[])
    candidate_rows, candidate_details, coverage_rows, coverage_details = [], [], [], []
    followups: dict[str, list[pd.DataFrame]] = {}
    provided: dict[str, list[str]] = {f"Q{i}": [] for i in range(2, 7)}
    for target in PATTERNS:
        root = remaining_root / target
        conditions = root / "conditions"
        if not (conditions / "run-receipt.json").is_file():
            continue
        candidates = json.loads((conditions / "top-candidates.json").read_text(encoding="utf-8"))
        for horizon in HORIZONS:
            controls = {}
            for control, folder in (
                ("pattern", "pattern%3Aunion"),
                ("C-base-no-pattern", "C-base-no-pattern"),
                ("C-base-all", "C-base-all"),
                (PRIMARY[target], PRIMARY[target]),
            ):
                name = f"{folder}-h{horizon}"
                frame = read_frame(conditions / name / f"{target}-{name}-summary.parquet")
                selected = _report_slice(frame, split="cross-check", era="all", mkt="all", row_kind="full", feature_id="candidate", condition_status="known")
                selected = selected.loc[selected["candidate_id"].isin(candidates)]
                controls[control] = selected.set_index("candidate_id")
                candidate_details.extend(_records(selected))
            for candidate, atoms in candidates.items():
                pattern, no_pattern, all_rows = (controls[key].loc[candidate] for key in ("pattern", "C-base-no-pattern", "C-base-all"))
                candidate_rows.append({
                    "target": target,
                    "candidate": candidate,
                    "atoms": " & ".join(f"{atom['feature_id']}={atom['bin_id']}" for atom in atoms),
                    "horizon": horizon,
                    "pattern_minus_no_pattern_pp": _difference(pattern["hit_rate"], no_pattern["hit_rate"]),
                    "pattern_minus_all_pp": _difference(pattern["hit_rate"], all_rows["hit_rate"]),
                    "pattern_known_n": pattern["known_n"],
                    "no_pattern_known_n": no_pattern["known_n"],
                    "all_known_n": all_rows["known_n"],
                    "loss_rate": pattern["loss_rate"],
                })
        provided["Q2"].append(target)
        provided["Q3"].append(target)
        if (root / "q4/run-receipt.json").is_file():
            coverage = _report_slice(read_frame(root / "q4/coverage.parquet"), split="cross-check", era="all", mkt="all")
            coverage_details.extend(_records(coverage))
            indexed = coverage.set_index("group_id")
            for group in (f"{target}:original", *(f"{target}:candidate:{candidate}" for candidate in candidates)):
                pattern, random = indexed.loc[group], indexed.loc[group + ":C-base-random"]
                coverage_rows.append({
                    "group": group,
                    "episode_n": pattern["episode_n"],
                    "pattern_coverage_rate": pattern["coverage_rate"],
                    "random_coverage_rate": random["coverage_rate"],
                    "coverage_delta_pp": _difference(pattern["coverage_rate"], random["coverage_rate"]),
                    "pattern_matched_n": pattern["matched_n"],
                    "pattern_unmatched_n": pattern["unmatched_n"],
                    "pattern_unknown_n": pattern["unknown_n"],
                    "random_matched_n": random["matched_n"],
                    "random_unmatched_n": random["unmatched_n"],
                    "random_unknown_n": random["unknown_n"],
                })
            provided["Q4"].append(target)
        if (root / "followup/run-receipt.json").is_file():
            for name in ("path_by_outcome", "holding_by_outcome", "first_flag_by_outcome", "flag_summary", "landmark_summary", "tradeoff_points"):
                frame = _report_slice(read_frame(root / f"followup/{name}.parquet"), split_id="cross-check", era="all", mkt="all")
                frame = frame.loc[frame["group_id"].eq(target)]
                if name == "landmark_summary":
                    # Keep the page bounded; every candidate landmark remains in
                    # the original final table, without a second table copy.
                    frame = frame.loc[frame["landmark"].eq(10)]
                followups.setdefault(name, []).append(frame)
            provided["Q5"].append(target)
            provided["Q6"].append(target)
    questions = {question["id"]: question for question in report["questions"]}
    if candidate_rows:
        questions["Q2"]["tables"] = [_report_table("candidate-deltas", "固定候選：型態減去同條件無型態（百分點）", pd.DataFrame(candidate_rows))]
        questions["Q2"]["notes"] = ["全部原固定 top-10 均保留原順序；不是重新選出的最佳組合。差距為描述，未作顯著性或策略通過宣稱。"]
        questions["Q3"]["tables"] = [
            _report_table("candidate-details", "附錄：候選四組絕對值、母數與上下界", pd.DataFrame(candidate_details), collapsible=True)
        ]
        questions["Q3"]["notes"] = ["C-base-no-pattern 排除該型態；C-base-all 包含型態，兩者不能互稱。上方同時並列兩種差距與各自 K。"]
    if coverage_rows:
        questions["Q4"]["tables"] = [
            _report_table("coverage-pairs", "每列型態／候選與自己的同配額 random", pd.DataFrame(coverage_rows)),
            _report_table("coverage-details", "附錄：完整覆蓋、時機、上下界與其他控制診斷", pd.DataFrame(coverage_details), collapsible=True),
        ]
        questions["Q4"]["notes"] = [
            "原型態配 original:C-base-random；各候選配自己的 :C-base-random，未重抽。"
            "C-52w／daily 診斷留在附錄；原資料未為它們提供獨立同配額 random，不混用候選對照。"
        ]
    for name, frames in followups.items():
        question = questions["Q6" if name in ("flag_summary", "landmark_summary", "tradeoff_points") else "Q5"]
        question["tables"].append(_report_table(name, f"既有終表附錄：{name}", pd.concat(frames, ignore_index=True), collapsible=True))
    questions["Q5"]["notes"] = ["此頁 Q5–Q6 附錄呈現原型態 union 群組；全部固定候選的終表仍在原 followup/，未刪除或重算。"]
    questions["Q6"]["notes"] = [
        "landmark 附錄固定呈現原型態群組第 10 日；其他 landmark、全部候選與年代／市場列仍在原 followup/landmark_summary.parquet。"
        "X8 的 earliest-flag 分布不代表全部高點降低事件。"
    ]
    _set_available_status(report, provided)
    report["limitations"] = [
        "Q2–Q6 目前只呈現已完成家族；其餘不填入檢查點的暫時數字。",
        "cross-check 已暴露，不是 unseen holdout；多重候選、重疊事件及小樣本使差距不能直接解讀為策略優勢。",
        "這是事件標籤率，不是投資組合報酬；價格與公司行動品質、reference industry 非 PIT 等原限制仍適用。",
        "Q4–Q6 為描述。未知與截尾可重疊；return bin 為價格比而非百分比，1.10 表示 +10%。",
        "Q2–Q6 附錄為 cross-check／全期／全市場切片；其他年代、市場、年度與敏感度列仍保留於原執行目錄，不另複製。",
        "iframe 實際檔案下載仍待人工驗收，DOM／點擊／SSR 測試不作下載完成證據。",
    ]
    LOGGER.info("Report presentation reads completed condition families: %s", ", ".join(provided["Q2"]))


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
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("definition") != "pattern-scan-local-q1.v1":
        raise ValueError(f"{target}: expected {RECEIPT_SCHEMA} for pattern-scan-local-q1.v1")
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

    # Bounded lossless transport of audited receipt metadata, as used by other
    # publications; no expansion of the owner's secret-scanner baseline.
    transport = BytesIO()
    with ZipFile(transport, "w") as archive:
        for target in PATTERNS:
            archive.writestr(ZipInfo(f"{target}-receipt.json"), receipts[target], compress_type=ZIP_DEFLATED)
    files["q1-receipts.zip"] = transport.getvalue()
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
                else "此 Q1 匯出未提供本題終表；完整報告請傳入既有 Q2–Q6 根目錄。",
                "notes": [
                    (
                        "範圍：12 種型態；交叉檢核 split=cross-check、全期間 era=all、"
                        "全部市場背景 mkt=all、row_kind=full、union cohort、unconditional feature 與 known 狀態；"
                        "各型態比較 pattern 組及其主要 control，觀察期為 126 與 252 個交易日。"
                    ),
                    "命中定義為 126／252 個交易日內收盤價達錨點的 2 倍；虧損定義為完整觀察期未命中且期末收盤價低於錨點。",
                    "分母 known_n 只納入已知且符合統計資格的樣本；缺失、設限與已知但排除資格者不納入。unknown_n 與 censored_n 可能重疊。",
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
        "audit": {"status": "unrecorded", "notes": ["此匯出未附稽核完成紀錄；沿用研究既有證據，不執行或重做稽核，也不由終表存在推定稽核完成。"]},
        "provenance": [
            {"label": "輸入識別", "value": input_id},
            {"label": "數值來源識別", "value": source_id},
            {"label": "數值來源程式", "value": _code_provenance(numerical_source_code, label="歷史數值來源程式", historical=True)},
            {"label": "投影執行程式", "value": _code_provenance(executor_code, label="本次投影執行程式", historical=False)},
            {"label": "原始 Q1 收據", "value": "12 份原始收據的無損壓縮包", "href": "data/q1-receipts.zip"},
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


def export_q1_report_data(q1_root: Path, output: Path, *, as_of: str, remaining_root: Path | None = None) -> dict[str, Any]:
    """Build and publish a new report data directory without replacing an existing one."""
    output = safe_path(Path(output))
    root = safe_path(Path(q1_root))
    if output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("report output must not overlap original Q1 results")
    if output.exists():
        raise FileExistsError(f"report data destination already exists: {output}")
    remaining = safe_path(Path(remaining_root)) if remaining_root is not None else None
    if remaining is not None and (output.is_relative_to(remaining) or remaining.is_relative_to(output)):
        raise ValueError("report output must not overlap original remaining results")
    report, files = build_q1_report_data(q1_root, as_of=as_of)
    if remaining is not None:
        add_stored_comparisons(report, root, remaining)
        files["summary.js"] = ("window.REPORT_DATA = " + json.dumps(report, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + ";\n").encode("utf-8")
    publish_new_directory(output, files)
    LOGGER.info("Published partial Q1 report data families=%d tables=%d output=%s", len(PATTERNS), 2 * len(PATTERNS), output)
    return report
