"""One provisional descriptive HHHL batch on the fixed, already-viewed atlas."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import platform
import random
import subprocess
import time
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research_core.feature_atlas_dataset import verify_dataset
from research_core.hhhl_probability import OUTCOME_COLUMNS, summarize
from research_core.hhhl_rule_source import SOURCE_HASHES, FrozenRule, load_rule
from research_core.hhhl_transition import classify_transition

LOGGER = logging.getLogger(__name__)
TASK = "20261009-hhhl-pattern-probability"
WINDOW = ("2019-01-02", "2026-08-14")
DATASET_ID = "fda-86245f2e223fc45c9f84afb0dcf77c1fff7ab22d0a1b0b4a4c8800972ce9327e"
KEY_COLUMNS = ["security_id", "asof_date", "year", "base_eligible", "eligibility_reason", "regime", "industry_ref"]
INPUT_COLUMNS = [*KEY_COLUMNS, "Open", "High", "Low", "Close", "VolumeLots", "atr14_pct", "corporate_action_types", *OUTCOME_COLUMNS]
SUMMARY_COLUMNS = ["security_id", "year", "base_eligible", *OUTCOME_COLUMNS]
STATE_FIELDS = ["status", "anchor_index", "first_low_index", "first_low_confirm_index", "threshold", "confirmation_day_excluded"]
DETECT_COLUMNS = ["Open", "High", "Low", "Close", "VolumeLots", "atr14_pct"]


@lru_cache(maxsize=2)
def worker_rule(sources: str, rule_id: str) -> FrozenRule:
    return load_rule(Path(sources), rule_id)


def detect_file(args: tuple[Path, str, str]) -> list[dict[str, Any]]:
    """Workers read only rule inputs; original detector bytes and semantics unchanged."""
    path, sources, rule_id = args
    bars = pd.read_parquet(path, columns=DETECT_COLUMNS).dropna(subset=["Open", "High", "Low", "Close"]).reset_index(drop=True)
    return worker_rule(sources, rule_id).detect(bars)


def detections(paths: list[Path], sources: Path, rule_id: str, workers: int) -> Iterator[list[dict[str, Any]]]:
    """Bounded batches, consumed in source order so random controls stay identical."""
    if workers not in (1, 4):
        raise ValueError("fixed resource options are one or four workers")
    args = [(path, str(sources), rule_id) for path in paths]
    if workers == 1:
        for item in args:
            yield detect_file(item)
        return
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(args), workers):
            for result in pool.map(detect_file, args[start : start + workers]):
                yield result


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def values(row: pd.Series) -> dict[str, Any]:
    return {name: row[name] for name in [*KEY_COLUMNS, *OUTCOME_COLUMNS]}


def build(dataset: Path, task_root: Path, output: Path, rule_id: str, workers: int = 1) -> dict[str, Any]:
    """No updates to inputs, labels, acceptance rules, or existing output directories."""
    started = time.monotonic()
    verified = verify_dataset(dataset)
    if verified["dataset_id"] != DATASET_ID:
        raise ValueError("this mission only authorizes the original atlas-v2 dataset")
    rule = load_rule(task_root / "sources", rule_id)
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    identity_paths = [
        task_root / "mission.md",
        task_root / "data-contract.md",
        Path(__file__),
        Path(__file__).parents[1] / "research_core/hhhl_probability.py",
        Path(__file__).parents[1] / "research_core/hhhl_rule_source.py",
        Path(__file__).parents[1] / "research_core/hhhl_transition.py",
        Path(__file__).parents[1] / "uv.lock",
        task_root / "sources" / f"{rule_id}.zip",
    ]
    before = {str(p): digest(p) for p in identity_paths}
    code_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parents[1], text=True).strip()
    source_manifest_digest = digest(dataset / "manifest.json")
    output.mkdir(parents=True, exist_ok=False)
    (output / "attempt.json").write_text(
        json.dumps({"complete": False, "phase": "descriptive_provisional", "code_commit": code_commit, "identity": before}, indent=2) + "\n", encoding="utf-8"
    )
    rng = random.Random(20261009)
    events: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    noises: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    baseline_parts = []
    entries = sorted(manifest["tables"], key=lambda x: x["security_id"])
    detected_batches = detections([dataset / entry["path"] for entry in entries], task_root / "sources", rule_id, workers)
    for n, (entry, detected) in enumerate(zip(entries, detected_batches, strict=True), 1):
        path = dataset / entry["path"]
        if digest(path) != entry["sha256"]:
            raise ValueError(f"source changed after validation: {entry['path']}")
        frame = pd.read_parquet(path, columns=INPUT_COLUMNS).reset_index(drop=True)
        if not frame["asof_date"].is_monotonic_increasing or frame["asof_date"].duplicated().any():
            raise ValueError("atlas calendar must be strictly increasing")
        dates = frame["asof_date"].dt.strftime("%Y-%m-%d")
        if dates.min() < WINDOW[0] or dates.max() > WINDOW[1]:
            raise ValueError("unauthorized date range")
        eligible = frame["base_eligible"].eq(True).fillna(False)
        baseline_parts.append(frame.loc[eligible, SUMMARY_COLUMNS])
        valid = frame.dropna(subset=["Open", "High", "Low", "Close"]).copy()
        raw_indices = np.asarray(valid.index)
        valid = valid.reset_index(drop=True)
        event_positions = {int(e["t"]) for e in detected}
        pattern_positions = {int(e["t"]) for e in detected if e["pattern"]}
        closes = valid["Close"].to_numpy(float)
        calendar_close = frame["Close"].to_numpy(float)
        volumes = valid["VolumeLots"].to_numpy(float)
        _, low_pivots = rule.pivots(valid["High"].to_numpy(float), valid["Low"].to_numpy(float), closes, valid["atr14_pct"].to_numpy(float) * closes, k=rule.k)
        calendar_lows = [(int(raw_indices[i]), int(raw_indices[cf]), float(p)) for i, cf, p in low_pivots]
        cash_dividend = (
            frame["corporate_action_types"].fillna("").astype(str).str.contains(r"(?:^|[|;,])(?:CASH_DIVIDEND|EX_RIGHT_AND_DIVIDEND)(?:$|[|;,])", regex=True)
        )
        cash_prefix = np.concatenate(([0], np.cumsum(cash_dividend.to_numpy(bool))))
        rolling_high = np.asarray(valid["Close"].shift(1).rolling(20, min_periods=20).max())
        rolling_volume = np.asarray(valid["VolumeLots"].shift(1).rolling(20, min_periods=1).mean())
        high_volume = (closes > rolling_high) & (rolling_volume > 0) & (volumes >= 1.5 * rolling_volume)
        for t in np.flatnonzero(high_volume):
            if int(t) in pattern_positions:
                continue
            raw_t = int(raw_indices[t])
            r = frame.iloc[raw_t]
            controls.append({
                **values(r),
                "anchor_date": dates.iloc[raw_t],
                "breakout_date": dates.iloc[raw_t],
                "control_no_event": int(t) not in event_positions,
                "control_no_pattern": True,
            })
        for event in detected:
            t, rs = int(event["t"]), int(event["restart"])
            raw_t, raw_rs = int(raw_indices[t]), int(raw_indices[rs])
            row = frame.iloc[raw_t]
            low = next(q for q in reversed(event["seq"]) if q["k"] == "L")
            dividend = cash_prefix[raw_t + 1] > cash_prefix[raw_rs]
            event_id = f"{rule_id}:{entry['security_id']}:{dates.iloc[raw_t]}"
            record = {
                **values(row),
                "event_id": event_id,
                "code": entry["security_id"].split(":", 1)[1],
                "rule_id": rule_id,
                "breakout_date": dates.iloc[raw_t],
                "anchor_date": dates.iloc[raw_t],
                "anchor_close": float(row["Close"]),
                "calendar_index": raw_t,
                "detector_index": t,
                "cat": event["cat"],
                "context": event["context"],
                "pattern": event["pattern"],
                "vx": event["vx"],
                "hz_top": event["hz_top"],
                "Z2": low["p"],
                "restart_date": dates.iloc[raw_rs],
                "structure_cash_dividend": bool(dividend),
                "structure_missing_ohlc": int(frame.iloc[raw_rs : raw_t + 1][["Open", "High", "Low", "Close"]].isna().any(axis=1).sum()),
                "pivot_sequence": json.dumps([{**q, "date": dates.iloc[int(raw_indices[q["i"]])]} for q in event["seq"]], ensure_ascii=False),
            }
            for zone_name, zone_value in (("z1", float(event["hz_top"])), ("z2", float(low["p"]))):
                state = classify_transition(calendar_close, raw_t, zone_value, calendar_lows)
                j = state.anchor_index
                anchor_date = dates.iloc[j] if j is not None else None
                record[f"{zone_name}_status"] = state.status
                record[f"{zone_name}_anchor_date"] = anchor_date
                transitions.append({
                    **{name: record[name] for name in ("event_id", "code", "rule_id", "breakout_date", "cat", "context", "pattern", "structure_cash_dividend")},
                    **(
                        values(frame.iloc[j])
                        if j is not None
                        else {**{name: None for name in [*KEY_COLUMNS, *OUTCOME_COLUMNS]}, "security_id": entry["security_id"]}
                    ),
                    **asdict(state),
                    "zone_name": zone_name,
                    "zone_value": zone_value,
                    "breakout_base_eligible": bool(eligible.iloc[raw_t]),
                    "anchor_date": anchor_date,
                    "anchor_close": float(calendar_close[j]) if j is not None else None,
                    "first_low_date": dates.iloc[state.first_low_index] if state.first_low_index is not None else None,
                    "first_low_confirm_date": dates.iloc[state.first_low_confirm_index] if state.first_low_confirm_index is not None else None,
                    "wait_to_transition": j - raw_t if j is not None else None,
                    "transition_cash_dividend": bool(cash_prefix[j + 1] > cash_prefix[raw_t]) if j is not None else None,
                })
            events.append(record)
            if event["pattern"] and bool(eligible.iloc[raw_t]):
                candidates = [j for j in range(max(0, raw_t - 60), min(len(frame), raw_t + 61)) if j != raw_t and bool(eligible.iloc[j])]
                if candidates:
                    j = rng.choice(candidates)
                    noises.append({
                        **values(frame.iloc[j]),
                        "event_id": event_id,
                        "anchor_date": dates.iloc[j],
                        "breakout_date": dates.iloc[raw_t],
                        "calendar_offset": j - raw_t,
                    })
                else:
                    noises.append({
                        **{c: None for c in OUTCOME_COLUMNS},
                        "security_id": entry["security_id"],
                        "year": row["year"],
                        "base_eligible": True,
                        "event_id": event_id,
                        "anchor_date": dates.iloc[raw_t],
                        "breakout_date": dates.iloc[raw_t],
                        "calendar_offset": None,
                        "unknown_reason_126": "no_shift_candidate",
                        "unknown_reason_63": "no_shift_candidate",
                    })
        if n % 100 == 0 or n == len(manifest["tables"]):
            LOGGER.info(
                "Progress stocks=%d/%d events=%d controls=%d elapsed=%.1fs", n, len(manifest["tables"]), len(events), len(controls), time.monotonic() - started
            )
        if time.monotonic() - started > 3600:
            raise TimeoutError("preregistered runtime budget exceeded; retain attempt, do not reinterpret as negative evidence")
    event_columns = [
        *KEY_COLUMNS,
        *OUTCOME_COLUMNS,
        "event_id",
        "code",
        "rule_id",
        "breakout_date",
        "anchor_date",
        "anchor_close",
        "calendar_index",
        "detector_index",
        "cat",
        "context",
        "pattern",
        "vx",
        "hz_top",
        "Z2",
        "restart_date",
        "structure_cash_dividend",
        "structure_missing_ohlc",
        "pivot_sequence",
        "z1_status",
        "z2_status",
        "z1_anchor_date",
        "z2_anchor_date",
    ]
    event_frame = pd.DataFrame(events, columns=pd.Index(event_columns))
    control_frame = pd.DataFrame(
        controls, columns=pd.Index([*KEY_COLUMNS, *OUTCOME_COLUMNS, "anchor_date", "breakout_date", "control_no_event", "control_no_pattern"])
    )
    noise_frame = pd.DataFrame(noises, columns=pd.Index([*KEY_COLUMNS, *OUTCOME_COLUMNS, "event_id", "anchor_date", "breakout_date", "calendar_offset"]))
    transition_frame = pd.DataFrame(
        transitions,
        columns=pd.Index([
            *KEY_COLUMNS,
            *OUTCOME_COLUMNS,
            "event_id",
            "code",
            "rule_id",
            "breakout_date",
            "cat",
            "context",
            "pattern",
            "structure_cash_dividend",
            *STATE_FIELDS,
            "zone_name",
            "zone_value",
            "breakout_base_eligible",
            "anchor_date",
            "anchor_close",
            "first_low_date",
            "first_low_confirm_date",
            "wait_to_transition",
            "transition_cash_dividend",
        ]),
    )
    baseline = pd.concat(baseline_parts, ignore_index=True)
    summaries = summarize(event_frame, baseline, control_frame, noise_frame, transition_frame)
    event_frame.to_parquet(output / "events.parquet", index=False)
    control_frame.to_parquet(output / "controls.parquet", index=False)
    noise_frame.to_parquet(output / "noise.parquet", index=False)
    transition_frame.to_parquet(output / "transitions.parquet", index=False)
    (output / "summaries.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    samples = event_frame.loc[event_frame["pattern"].eq(True) & event_frame["base_eligible"].eq(True)].sort_values(["code", "breakout_date"]).head(10)
    samples[
        ["event_id", "code", "breakout_date", "anchor_date", "anchor_close", "label_126", "max_return_126", "complete_126", "unknown_reason_126"]
    ].to_parquet(output / "audit-sample.parquet", index=False)
    if digest(dataset / "manifest.json") != source_manifest_digest or {str(p): digest(p) for p in identity_paths} != before:
        raise ValueError("declared input/code changed during execution; retain outputs but no completion claim")
    for entry in manifest["tables"]:
        if digest(dataset / entry["path"]) != entry["sha256"]:
            raise ValueError(f"atlas input changed during execution: {entry['path']}")
    result = {
        "schema_version": "hhhl-probability.v1",
        "phase": "descriptive_provisional",
        "rule": rule_id,
        "rule_acceptance": "failed_recall",
        "source_dataset_id": DATASET_ID,
        "source_manifest_sha256": source_manifest_digest,
        "source": str(dataset),
        "code_commit": code_commit,
        "window": {"start": WINDOW[0], "end": WINDOW[1]},
        "verified_input": verified,
        "identity": before,
        "source_hashes": SOURCE_HASHES[rule_id],
        "runtime": {"python": platform.python_version(), "platform": platform.platform(), "pandas": pd.__version__, "numpy": np.__version__},
        "standing_definition": "hhhl-state.v1-provisional-claude",
        "main_control": "same_day_no_any_v1_event",
        "secondary_control": "same_day_no_true_pattern",
        "transition_counts": [
            {
                "zone": zone,
                "pattern": pattern,
                "status": status,
                "rows": int(len(selected)),
                "breakout_eligible": int(selected["breakout_base_eligible"].eq(True).sum()),
                "confirmation_day_excluded": int(selected["confirmation_day_excluded"].eq(True).sum()),
            }
            for zone in ("z1", "z2")
            for pattern in (True, False)
            for status in ("stood", "failed", "unresolved", "unknown_missing_close", "unknown_window_end")
            for selected in [
                transition_frame.loc[transition_frame["zone_name"].eq(zone) & transition_frame["pattern"].eq(pattern) & transition_frame["status"].eq(status)]
            ]
        ],
        "noise_seed": 20261009,
        "noise_radius": 60,
        "workers": workers,
        "counts": {
            "events": len(event_frame),
            "pattern": int(event_frame["pattern"].eq(True).sum()),
            "controls_no_event": int(control_frame["control_no_event"].eq(True).sum()),
            "controls_no_pattern": len(control_frame),
            "noise": len(noise_frame),
            "transitions": len(transition_frame),
            "baseline_eligible_rows": len(baseline),
            "comparisons": len(summaries),
        },
        "elapsed_seconds": time.monotonic() - started,
        "artifacts": {p.name: {"sha256": digest(p), "bytes": p.stat().st_size} for p in sorted(output.iterdir()) if p.is_file()},
        "complete": True,
    }
    (output / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rule", choices=list(SOURCE_HASHES), default="hhhl_rule_v1")
    parser.add_argument("--workers", type=int, choices=(1, 4), default=4)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        result = build(args.dataset, args.task_root, args.output, args.rule, args.workers)
    except (ValueError, OSError, TimeoutError):
        LOGGER.exception("HHHL execution incomplete; original inputs untouched")
        return 1
    print(json.dumps({"complete": result["complete"], "counts": result["counts"], "elapsed_seconds": result["elapsed_seconds"]}, ensure_ascii=False))  # noqa: T201 - CLI result
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
