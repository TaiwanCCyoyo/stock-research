"""Export the published HHHL v4 variants summary into the web report's data files.

Reads only the Git-portable publication (verified by ``load_summary``) and writes
``web-report/data/*.js``; each file stays under the repository's 500 KiB limit.
Development and cross-check halves hold disjoint stocks, so a "merged" row is the
sum of the two halves' integer counts and its rates are recomputed from those sums.
Quantiles cannot be merged and are kept per half.

    uv run python -c "import runpy; runpy.run_path('tasks/20261012-hhhl-v4-variants/build_web_report_data.py', run_name='__main__')"
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core.hhhl_variants_query import load_summary

LOGGER = logging.getLogger(__name__)
TASK = Path(__file__).resolve().parent
PUBLICATION = TASK / "publication-v1"
OUTPUT = TASK / "web-report" / "data"
# One script file per group keeps each file below the 500 KiB commit limit.
FILES = {
    "summary.js": ["schema", "source", "baseline", "candidate", "reverse", "flags", "year", "drop_best_year", "near_high"],
    "single-126.js": ["single_126"],
    "single-252.js": ["single_252"],
    "kdist.js": ["kdist"],
}
SPLITS = {"development": "dev", "cross-check": "cross"}
OUTCOME_COUNTS = ["known_n", "hit_n", "loss_n", "flat_win_n", "unknown_n", "censored_n", "known_security_n"]
REFERENCE_COUNTS = [f"reference_{name}_{count}_n" for name in ("cnh", "c52w", "pall") for count in ("known", "hit", "loss")]
COUNT_COLUMNS = OUTCOME_COUNTS + REFERENCE_COUNTS
REVERSE_COUNTS = [
    "nonhit_flag_triggered_n",
    "nonhit_flag_known_n",
    "hit_flag_triggered_n",
    "hit_flag_known_n",
    "cost_denominator_n",
    "trigger_return_n",
]
QUANTILES = [f"trigger_return_{stat}_{split}" for stat in ("median", "p10", "p90") for split in ("dev", "cross")]
TEXT_COLUMNS = [
    "cohort_id",
    "feature_id",
    "bin_id",
    "candidate_id",
    "reference_kind",
    "flag_id",
    "return_bin",
    "flag_state",
    "split",
    "split_id",
    "scope",
    "base_row_kind",
]

Converter = Callable[[Any], Any]


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and not math.isfinite(value))


def _int(value: Any) -> int | None:
    return None if _missing(value) else int(value)


def _num(value: Any) -> float | None:
    return None if _missing(value) else round(float(value), 6)


def _text(value: Any) -> str | None:
    return None if _missing(value) else str(value)


CONVERTERS: dict[str, Converter] = {
    **{name: _int for name in [*COUNT_COLUMNS, *REVERSE_COUNTS, "horizon", "landmark", "year", "removed_year"]},
    **{name: _int for name in ["riskset_n", "near_high_known_n", "near_high_matched_n", "near_high_unknown_n"]},
    **{name: _num for name in [*QUANTILES, "near_high_rate"]},
    **{name: _text for name in TEXT_COLUMNS},
}


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    return cast(pd.Series, frame[name])


def _where(frame: pd.DataFrame, **equals: Any) -> pd.DataFrame:
    """Rows whose columns equal the given values (a list means "any of")."""
    mask = pd.Series(True, index=frame.index)
    for name, value in equals.items():
        column = _column(frame, name)
        mask &= column.isin(value) if isinstance(value, list) else column.eq(value)
    return cast(pd.DataFrame, frame.loc[mask])


def _with_merged(frame: pd.DataFrame, keys: list[str], counts: list[str]) -> pd.DataFrame:
    """Append a ``merged`` split whose counts are the sum of the two disjoint halves."""
    halves = _where(frame, split_id=list(SPLITS)).copy()
    halves["split"] = [SPLITS[str(value)] for value in _column(halves, "split_id").tolist()]
    merged = cast(pd.DataFrame, halves.groupby(keys, dropna=False, as_index=False)[counts].sum(min_count=1))
    merged["split"] = "merged"
    return pd.concat([halves, merged], ignore_index=True)


def _keep_reference_kind(merged: pd.DataFrame, source: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Restore the per-condition reference kind that summing cannot carry."""
    kinds = cast(pd.DataFrame, source.groupby(keys, dropna=False)["reference_kind"].first().reset_index())
    return merged.drop(columns=["reference_kind"], errors="ignore").merge(kinds, on=keys, how="left")


def _table(frame: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    rows = [
        [CONVERTERS.get(name, lambda v: v)(value) for name, value in zip(columns, record, strict=True)] for record in frame[columns].itertuples(index=False)
    ]
    return {"columns": columns, "rows": rows}


def build(summary: pd.DataFrame, meta: dict[str, Any]) -> dict[str, Any]:
    baseline = _with_merged(_where(summary, row_kind="baseline"), ["cohort_id", "horizon"], OUTCOME_COUNTS)

    single_rows = _where(summary, row_kind="single")
    single = _keep_reference_kind(
        _with_merged(single_rows, ["cohort_id", "horizon", "feature_id", "bin_id"], COUNT_COLUMNS),
        single_rows,
        ["feature_id", "bin_id"],
    )
    candidate_rows = _where(summary, row_kind="candidate")
    candidate = _keep_reference_kind(
        _with_merged(candidate_rows, ["cohort_id", "horizon", "candidate_id"], COUNT_COLUMNS),
        candidate_rows,
        ["candidate_id"],
    )
    kdist = _where(
        _with_merged(
            _where(summary, row_kind="Kdistribution"),
            ["cohort_id", "horizon", "candidate_id", "feature_id", "bin_id"],
            ["known_n", "hit_n"],
        ),
        split="merged",
    )

    reverse_rows = _where(summary, row_kind="reverse_flag", cohort_id="P-all")
    flag_keys = ["horizon", "landmark", "scope", "flag_id"]
    halves = _where(reverse_rows, split_id=list(SPLITS)).copy()
    halves["split"] = [SPLITS[str(value)] for value in _column(halves, "split_id").tolist()]
    quantiles = cast(
        pd.DataFrame,
        halves.pivot_table(
            index=flag_keys,
            columns="split",
            values=["trigger_return_median", "trigger_return_p10", "trigger_return_p90"],
            aggfunc="first",
        ),
    )
    quantiles.columns = [f"{value}_{split}" for value, split in quantiles.columns]
    reverse = _where(_with_merged(reverse_rows, flag_keys, REVERSE_COUNTS), split="merged").merge(quantiles.reset_index(), on=flag_keys, how="left")

    flags = _where(
        _with_merged(
            _where(summary, row_kind="flag", cohort_id="P-all", flag_state=["triggered", "all_false"]),
            ["horizon", "landmark", "flag_id", "return_bin", "flag_state"],
            ["known_n", "hit_n", "loss_n", "riskset_n"],
        ),
        split="merged",
    )
    year = _where(
        _with_merged(
            _where(summary, row_kind="year", base_row_kind="baseline"),
            ["cohort_id", "horizon", "year"],
            ["known_n", "hit_n", "loss_n"],
        ),
        split="merged",
    )
    drop = _where(summary, row_kind="drop_best_year", base_row_kind=["candidate", "baseline"], cohort_id="P-all").copy()
    drop["split"] = [SPLITS.get(str(value)) for value in _column(drop, "split_id").tolist()]
    near = _where(summary, row_kind="near_high")
    LOGGER.info("exporting %d summary rows from %s", len(summary), meta["dataset_id"])

    return {
        "schema": "hhhl-v4-variants-web-report.v1",
        "source": {
            "dataset_id": meta["dataset_id"],
            "publication": "tasks/20261012-hhhl-v4-variants/publication-v1/receipt.json",
            "summary_rows": int(len(summary)),
            "period": "2019-01-02..2026-08-14",
        },
        "baseline": _table(baseline, ["cohort_id", "split", "horizon", *OUTCOME_COUNTS]),
        "single": _table(single, ["cohort_id", "split", "horizon", "feature_id", "bin_id", "reference_kind", *COUNT_COLUMNS]),
        "candidate": _table(candidate, ["cohort_id", "split", "horizon", "candidate_id", "reference_kind", *COUNT_COLUMNS]),
        "kdist": _table(kdist, ["cohort_id", "horizon", "candidate_id", "feature_id", "bin_id", "known_n"]),
        "reverse": _table(reverse, [*flag_keys, *REVERSE_COUNTS, *QUANTILES]),
        "flags": _table(flags, ["horizon", "landmark", "flag_id", "return_bin", "flag_state", "known_n", "hit_n", "loss_n", "riskset_n"]),
        "year": _table(year, ["cohort_id", "horizon", "year", "known_n", "hit_n", "loss_n"]),
        "drop_best_year": _table(drop, ["base_row_kind", "candidate_id", "split", "horizon", "removed_year", "known_n", "hit_n", "loss_n"]),
        "near_high": _table(
            near,
            [
                "cohort_id",
                "split_id",
                "bin_id",
                "near_high_known_n",
                "near_high_matched_n",
                "near_high_unknown_n",
                "near_high_rate",
            ],
        ),
    }


def _split_single(data: dict[str, Any]) -> None:
    single = data.pop("single")
    index = single["columns"].index("horizon")
    for horizon in (126, 252):
        data[f"single_{horizon}"] = {
            "columns": single["columns"],
            "rows": [row for row in single["rows"] if row[index] == horizon],
        }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary, receipt = load_summary(PUBLICATION)
    data = build(summary, receipt)
    _split_single(data)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, keys in FILES.items():
        payload = json.dumps({key: data[key] for key in keys}, ensure_ascii=False, separators=(",", ":"))
        target = OUTPUT / name
        target.write_text(
            "// Generated by tasks/20261012-hhhl-v4-variants/build_web_report_data.py; do not edit.\n"
            f"window.REPORT_DATA = Object.assign(window.REPORT_DATA || {{}}, {payload});\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"wrote {target} ({target.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
