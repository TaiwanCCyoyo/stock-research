"""Build one frozen descriptive batch, or prepare its explicit execution packet.

Preparation hashes inputs only. Market execution belongs to run_registered_job.
This is not a trading backtest and never decides whether a strategy passes.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research_core.feature_atlas_features import CONTINUOUS_COLUMNS, FEATURE_SPECS, compute_features  # noqa: E402
from research_core.feature_atlas_io import (  # noqa: E402
    DEFINITION,
    END,
    SCHEMA,
    START,
    TASK_ID,
    continuous_distributions,
    cross_sectional_features,
    digest_json,
    input_paths,
    load_snapshot,
    market_regime,
    prepare_prices,
    security_inventory,
    write_json,
)
from research_core.feature_atlas_legacy import LEGACY_SPECS, compute_legacy_features  # noqa: E402
from research_core.feature_atlas_outcomes import binary_comparison, labels  # noqa: E402
from research_core.jobs import confined, digest, file_digest, runtime_identity, validate_packet  # noqa: E402

LOGGER = logging.getLogger(__name__)
FEATURES = [f"F{i:02}" for i in range(1, 39)]
CONTEXTS = ["year", "regime", "industry_ref"]
CONTINUOUS = [*CONTINUOUS_COLUMNS, "ma_convergence_fraction", "rs20_percentile", "rs60_percentile", "relative_ret60_0050"]
WARNINGS = [
    "Descriptive explored cohort, not survivorship-complete or independent confirmation.",
    "Current industry references are retrospective, not PIT historical classifications.",
    "Forward close-price rises are not captured account profit or executable returns.",
    "Overlapping daily observations and cross-stock dependence preclude IID inference.",
    "Incomplete future paths remain unknown, not failed opportunities.",
    "Permanent-factor research prices exclude cash dividends and accounting entitlements.",
]


def definitions() -> dict[str, Any]:
    extra: dict[str, dict[str, Any]] = {
        "F36": {"name": "rs20_top_quintile", "family": "relative_strength", "formula": "contemporaneous eligible ret20 rank(pct=True, average ties) >= 0.8"},
        "F37": {"name": "rs60_top_quintile", "family": "relative_strength", "formula": "contemporaneous eligible ret60 rank(pct=True, average ties) >= 0.8"},
        "F38": {"name": "outperform_0050_60", "family": "relative_strength", "formula": "ret60 > same-date 0050 ret60"},
    }
    for spec in extra.values():
        spec["source_method_ids"] = ["LEGACY-RS"]
    return {
        "feature_definition_id": DEFINITION,
        "features": FEATURE_SPECS | LEGACY_SPECS | extra,
        "outcome_definition_id": "future-close-1.5x-63-2x-126-fullpath.v1",
        "continuous": CONTINUOUS,
        "full_methods_not_implemented": ["cup_and_handle", "full_Wyckoff_phases", "RSI_divergence"],
        "thresholds_status": "fixed_provisional_exploration_not_owner_account_hit_gate",
    }


def prepare_packet(root: Path, job_id: str) -> tuple[Path, str]:
    """Create a fresh reviewable packet, without loading any market rows."""
    code = [
        "scripts/build_feature_discrimination_atlas.py",
        "scripts/run_registered_job.py",
        "research_core/__init__.py",
        "research_core/jobs.py",
        "research_core/evidence.py",
        "StockProject/engine/data_loader.py",
        "StockProject/engine/__init__.py",
    ]
    code += [f"research_core/feature_atlas_{name}.py" for name in ("features", "outcomes", "legacy", "io", "dataset")]
    # Package initializer is part of the executable import read-set when present.
    if (root / "StockProject/__init__.py").is_file():
        code.append("StockProject/__init__.py")
    contracts = [f"tasks/{TASK_ID}/mission.md", "docs/en/research-owner-contract.md", "docs/en/research-registry.json"]
    packet = {
        "schema_version": "research-job.v1",
        "job_id": job_id,
        "task_id": TASK_ID,
        "phase": "exploration",
        "window": {"start": START, "end": END},
        "candidate_id": DEFINITION,
        "owner_contract_id": "research-owner-contract-current",
        "metric_contract_id": DEFINITION,
        "execution_contract_id": "descriptive-no-trades.v1",
        "scenario_id": "daily-and-fixed-grid126",
        "params": {
            "features": FEATURES,
            "contexts": CONTEXTS,
            "labels": [63, 126],
            "sparse_stride": 126,
            "maximum_industry_groups": 100,
            "maximum_attempts": 3,
        },
        "timeout_seconds": 3600,
        "runtime": runtime_identity(),
        "inputs": {
            "code": {name: file_digest(root / name) for name in code},
            "contracts": {name: file_digest(root / name) for name in contracts},
            "data": {path.relative_to(root).as_posix(): file_digest(path) for path in input_paths(root).values()},
        },
        "script": code[0],
        "args": ["--output-dir", "{output_dir}", "--run-id", job_id],
        "outputs": ["summary.json", "manifest.json", "comparisons.json", "continuous.json", "inventory.json", "definitions.json"],
        "summary": "summary.json",
    }
    validate_packet(packet)
    path = confined(root, f"tasks/{TASK_ID}/params/{job_id}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, packet)
    return path, digest(packet)


def build_atlas(root: Path, output: Path, run_id: str) -> None:
    """Materialize complete positive/negative/unknown evidence and fixed panels."""
    prices, meta, actions, inventory = load_snapshot(root)
    securities = security_inventory(prices, meta)
    included = [row for row in securities if row["included"]]
    if not included or len({row["industry_ref"] for row in included}) > 100:
        raise ValueError("Empty cohort or industry comparison budget exceeded")
    calendar = pd.DatetimeIndex(cast(pd.Series, prices["Date"]).drop_duplicates().sort_values())
    groups = {str(code): group for code, group in prices.groupby("Code", sort=False)}
    event_groups = {str(code): group for code, group in actions.groupby("code", sort=False)}
    empty_actions = pd.DataFrame(actions.iloc[:0])
    if "0050" not in groups:
        raise ValueError("Required 0050 benchmark missing; do not invent regime")
    benchmark = prepare_prices(groups["0050"], event_groups.get("0050", empty_actions), calendar)
    benchmark_features = compute_features(benchmark)
    regime = market_regime(benchmark_features)
    specs = definitions()
    identity = {
        "schema_version": SCHEMA,
        "definitions": specs,
        "source_sha256": inventory["source_sha256"],
        "window": inventory["read_window"],
        "code_sha256": {
            name: file_digest(root / name)
            for name in [
                "scripts/build_feature_discrimination_atlas.py",
                *[f"research_core/feature_atlas_{part}.py" for part in ("features", "legacy", "outcomes", "io")],
                "StockProject/engine/data_loader.py",
                f"tasks/{TASK_ID}/mission.md",
            ]
        },
    }
    dataset_id = "fda-" + digest_json(identity)
    table_dir = output / "tables"
    table_dir.mkdir(exist_ok=False)
    chunks: list[dict[str, Any]] = []
    analyses: list[pd.DataFrame] = []
    quality: list[dict[str, Any]] = []
    analysis_columns = ["security_id", "asof_date", "calendar_index", "base_eligible", *CONTEXTS, *FEATURES[:35], "label_63", "label_126", *CONTINUOUS[:17]]
    for number, security in enumerate(included, 1):
        code = security["code"]
        panel = prepare_prices(groups[code], event_groups.get(code, empty_actions), calendar)
        computed = pd.concat([panel, compute_features(panel), compute_legacy_features(panel), labels(panel)], axis=1)
        streak = cast(pd.Series, cast(pd.Series, panel["Quality"]).astype(int).rolling(60, min_periods=60).sum()).eq(60)
        computed["base_eligible"] = streak & panel["VolumeLots"].gt(0)
        computed["eligibility_reason"] = np.select(
            [~panel["Quality"], ~streak, ~panel["VolumeLots"].gt(0)],
            ["invalid_or_missing_price", "fewer_than_60_consecutive_prices", "no_positive_observed_volume"],
            default="eligible",
        )
        computed["dataset_id"] = dataset_id
        computed["security_id"] = security["security_id"]
        computed["asof_date"] = calendar
        computed["calendar_index"] = np.arange(len(calendar))
        computed["sample_id"] = [f"{dataset_id}:{security['security_id']}@{day.date()}" for day in calendar]
        computed["year"] = [day.year for day in calendar]
        computed["industry_ref"] = security["industry_ref"]
        computed["classification_basis"] = "current_metadata_reference_not_PIT"
        computed["regime"] = regime
        path = table_dir / f"{code}.parquet"
        computed.reset_index(drop=True).to_parquet(path, index=False)
        chunks.append({"path": path.relative_to(output).as_posix(), "sha256": file_digest(path), "rows": len(computed), "security_id": security["security_id"]})
        # Float32 is enough for binary states, but keep continuous calculations
        # in float64 so percentile ties are not introduced by storage rounding.
        small = pd.DataFrame(computed[analysis_columns].copy().reset_index(drop=True))
        small[FEATURES[:35] + ["label_63", "label_126"]] = small[FEATURES[:35] + ["label_63", "label_126"]].astype("float32")
        analyses.append(small)
        quality.append({
            "security_id": security["security_id"],
            "valid_price_rows": int(panel["Quality"].sum()),
            "eligible_rows": int(computed["base_eligible"].sum()),
            "quality_reasons": {str(k): int(v) for k, v in panel["quality_reason"].dropna().value_counts().items()},
            "known_labels": {str(h): int(computed.loc[computed["base_eligible"], f"label_{h}"].notna().sum()) for h in (63, 126)},
        })
        if number % 50 == 0 or number == len(included):
            LOGGER.info("Completed %d/%d securities", number, len(included))
    frame = pd.concat(analyses, ignore_index=True)
    del analyses, prices, groups
    for column in ["security_id", *CONTEXTS]:
        frame[column] = frame[column].astype("category")
    cross = cross_sectional_features(frame, cast(pd.Series, benchmark_features["ret60"]))
    frame = pd.concat([frame, cross], axis=1)
    cross_path = output / "cross_section.parquet"
    pd.concat([frame[["security_id", "asof_date"]], cross], axis=1).to_parquet(cross_path, index=False)
    benchmark_path = output / "benchmark.parquet"
    pd.concat([benchmark, benchmark_features, regime.rename("regime")], axis=1).rename_axis("asof_date").reset_index().to_parquet(benchmark_path, index=False)
    LOGGER.info("Computing fixed comparison panels from %d rows", len(frame))
    comparisons: list[dict[str, Any]] = []
    for name, subset in (("daily", frame), ("grid126", frame.loc[frame["calendar_index"].mod(126).eq(0)])):
        rows = binary_comparison(subset, FEATURES, CONTEXTS)
        comparisons.extend({"panel": name, **row} for row in rows)
    inventory.update(
        securities=securities,
        quality=quality,
        calendar_sessions=len(calendar),
        included_securities=len(included),
        analysis_rows=len(frame),
        base_eligible_rows=int(frame["base_eligible"].sum()),
    )
    write_json(output / "inventory.json", inventory)
    write_json(output / "definitions.json", specs)
    write_json(output / "comparisons.json", {"dataset_id": dataset_id, "comparisons": comparisons})
    write_json(output / "continuous.json", {"dataset_id": dataset_id, "distributions": continuous_distributions(frame, CONTINUOUS)})
    # A source changed during the read makes the entire run incomplete, not a
    # new silent snapshot. The caller retains the attempted run for diagnosis.
    for name, path in input_paths(root).items():
        if file_digest(path) != inventory["source_sha256"][name]:
            raise ValueError(f"Source changed during calculation: {name}")
    eligible = frame.loc[frame["base_eligible"]]
    counts = {
        str(h): {
            "known": int(eligible[f"label_{h}"].notna().sum()),
            "positive": int(eligible[f"label_{h}"].eq(1).sum()),
            "unknown": int(eligible[f"label_{h}"].isna().sum()),
        }
        for h in (63, 126)
    }
    summary = {
        "schema_version": "1.0",
        "run": {"id": run_id, "dataset_id": dataset_id, "phase": "exploration"},
        "strategy": {"kind": "descriptive_features_not_strategy", "definition_id": DEFINITION},
        "data": {"window": inventory["read_window"], "securities": len(included), "calendar_sessions": len(calendar)},
        "metrics": {
            "rows": len(frame),
            "eligible_rows": len(eligible),
            "label_counts": counts,
            "comparison_rows": len(comparisons),
            "feature_count": len(FEATURES),
        },
        "portfolio": {"evaluated": False},
        "trades": [],
        "warnings": WARNINGS,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output / "summary.json", summary)
    artifact_names = ["inventory.json", "definitions.json", "comparisons.json", "continuous.json", "summary.json", "benchmark.parquet"]
    manifest = {
        "schema_version": SCHEMA,
        "dataset_id": dataset_id,
        "run_id": run_id,
        "identity": identity,
        "feature_definition_id": DEFINITION,
        "outcome_definition_id": specs["outcome_definition_id"],
        "tables": chunks,
        "cross_section": {"path": cross_path.name, "sha256": file_digest(cross_path), "rows": len(frame)},
        "artifacts": [{"path": name, "sha256": file_digest(output / name)} for name in artifact_names],
        "join_keys": ["security_id", "asof_date"],
        "join_cardinality": "one_to_one_full_match",
        "notes": WARNINGS,
        "catalog_episode_crosswalk": None,
    }
    write_json(output / "manifest.json", manifest)
    LOGGER.info("Completed dataset %s", dataset_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-packet", action="store_true")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.prepare_packet:
        path, sha = prepare_packet(REPO_ROOT, args.run_id)
        sys.stdout.write(f"packet={path}\napproved_digest_requires_parent_review={sha}\n")
        return
    expected = confined(REPO_ROOT, f"tasks/{TASK_ID}/runs/registered/{args.run_id}")
    if args.output_dir is None or args.output_dir.resolve() != expected.resolve():
        parser.error("execute only in this registered job's fresh output directory")
    build_atlas(REPO_ROOT, expected, args.run_id)


if __name__ == "__main__":
    main()
