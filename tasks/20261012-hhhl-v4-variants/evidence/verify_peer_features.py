"""Read-only independent H/K3/J integrity checks for the fixed audit cases.

Run after publication: uv run python tasks/20261012-hhhl-v4-variants/evidence/
verify_peer_features.py --dataset <absolute published dataset directory>
Only case identities, assertions and input/code hashes are emitted.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from research_core.artifact_store import file_digest, read_json, relative_name, safe_path, verify_files  # noqa: E402
from research_core.feature_atlas_dataset import load_analysis  # noqa: E402
from research_core.hhhl_variants_features import classify_feature  # noqa: E402
from research_core.hhhl_variants_inputs import calendar_identity  # noqa: E402

_UNCLASSIFIED = {"", "unknown", "unclassified", "(missing)", "未分類", "未分类", "None", "nan"}
_RAW = ["RawOpen", "RawHigh", "RawLow", "RawClose", "VolumeLots"]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def numeric_equal(left: Any, right: Any) -> bool:
    if left is None or cast(bool, pd.isna(left)):
        return right is None or cast(bool, pd.isna(right))
    return right is not None and not cast(bool, pd.isna(right)) and math.isclose(float(left), float(right), rel_tol=1e-11, abs_tol=1e-11)


def population_equal(expected: int, recorded: Any) -> bool:
    # A groupby size joined onto all dates has a null when that date has no
    # eligible finite observations. The independent census must also be zero.
    return expected == 0 if recorded is None or cast(bool, pd.isna(recorded)) else numeric_equal(expected, recorded)


def verify(dataset: Path) -> dict[str, Any]:
    require(dataset.is_absolute(), "--dataset must be absolute")
    dataset = safe_path(dataset)
    pins_path = safe_path(Path(__file__).resolve().parents[1] / "params/input-pins-v1.json")
    pins = read_json(pins_path)
    manifest = read_json(dataset / "manifest.json")
    require(manifest.get("schema_version") == "hhhl-variants-dataset.v1", "dataset schema differs")
    require(manifest["identity"]["input_pins_sha256"] == file_digest(pins_path), "published input pin identity differs")
    descriptors = manifest["artifacts"]
    by_path = {entry["path"]: entry for entry in descriptors}
    require(len(by_path) == len(descriptors), "duplicate dataset descriptors")
    required = ["audit/ten-events.json", "daily-boundaries.parquet"]
    require(all(name in by_path for name in required), "required audit/boundary descriptor absent")
    verify_files(dataset, [by_path[name] for name in required])
    audit = read_json(dataset / "audit/ten-events.json", max_bytes=128_000_000)
    cases = audit["cases"]
    require(0 < len(cases) <= 10 and audit["rows"] == len(cases), "fixed audit case count differs")
    require(len({case["event_id"] for case in cases}) == len(cases), "audit event IDs duplicate")
    atlas, bulk = safe_path(Path(pins["atlas"]["path"])), safe_path(Path(pins["v4_bulk"]["path"]))
    for name, location in (("atlas", atlas), ("v4_bulk", bulk)):
        require(file_digest(location / "manifest.json") == pins[name]["manifest_sha256"], f"{name} manifest pin differs")
    bulk_manifest = read_json(bulk / "manifest.json")
    control_descriptor = bulk_manifest["artifacts"]["controls.parquet"]
    verify_files(bulk, [dict(control_descriptor, path="controls.parquet")])
    atlas_data = load_analysis(atlas, columns=["base_eligible", "industry_ref", *_RAW], verify_hashes=True)
    groups = atlas_data.groupby("security_id", sort=True).indices
    daily_descriptors = [entry for entry in descriptors if entry["path"].startswith("daily/") and entry["path"].endswith(".parquet")]
    require(len({entry["code"] for entry in daily_descriptors}) == len(daily_descriptors) == len(groups), "daily stock routing differs")
    verify_files(dataset, daily_descriptors)
    selected_indices = sorted({int(case["original_source_event"]["calendar_index"]) for case in cases})
    peer_days: dict[int, dict[str, dict[str, Any]]] = {index: {} for index in selected_indices}
    industries_by_day: dict[int, dict[str, Any]] = {}
    calendar: pd.DatetimeIndex | None = None
    route = {cast(str, security).split(":", 1)[1]: security for security in groups}
    require(len(route) == len(groups), "code maps to more than one security")
    for descriptor in daily_descriptors:
        code = descriptor["code"]
        require(code in route, "daily code absent from atlas")
        raw = atlas_data.iloc[groups[route[code]]].sort_values("asof_date").reset_index(drop=True)
        dates = pd.DatetimeIndex(raw["asof_date"])
        if calendar is None:
            calendar = dates
        require(dates.equals(calendar), "atlas common calendar differs")
        identity = calendar_identity(dates)
        require(all(identity[name] == pins["calendar"][name] for name in identity), "atlas common calendar pin differs")
        daily = pd.read_parquet(safe_path(dataset / relative_name(descriptor["path"])), columns=["ret120", "turnover20"])
        require(len(daily) == len(raw), "daily ordinal row count differs from common calendar")
        eligible = raw["base_eligible"].eq(True).fillna(False).to_numpy(dtype=bool)
        # Reconstruct the frozen drop-missing OHLC valid-row liquidity gate.
        valid_positions = np.flatnonzero(raw[_RAW[:4]].notna().all(axis=1).to_numpy())
        amount = (raw["RawClose"].iloc[valid_positions].astype(float) * raw["VolumeLots"].iloc[valid_positions].astype(float)).reset_index(drop=True)
        compressed_liquid = amount.shift(1).rolling(20, min_periods=20).mean().ge(1000).to_numpy(dtype=bool)
        liquid = np.zeros(len(raw), dtype=bool)
        liquid[valid_positions] = compressed_liquid
        for index in selected_indices:
            require(0 <= index < len(raw), "audit index outside calendar")
            peer_days[index][code] = {
                "eligible": bool(eligible[index]),
                "liquid": bool(liquid[index]),
                "ret120": float(daily["ret120"].iloc[index]),
                "turnover20": float(daily["turnover20"].iloc[index]),
            }
            for window_index in range(max(0, index - 10), index + 1):
                industries_by_day.setdefault(window_index, {})[code] = raw["industry_ref"].iloc[window_index]
    if calendar is None:
        raise ValueError("common calendar absent")
    controls = pd.read_parquet(bulk / "controls.parquet", columns=["security_id", "asof_date", "base_eligible", "control_no_event"])
    controls = controls.loc[controls["base_eligible"].eq(True) & controls["control_no_event"].eq(True)]
    signals: dict[int, set[str]] = {}
    for security, day in controls[["security_id", "asof_date"]].itertuples(index=False, name=None):
        index = int(calendar.get_indexer([pd.Timestamp(day)])[0])
        require(index >= 0, "control date outside calendar")
        if index in industries_by_day:
            signals.setdefault(index, set()).add(security.split(":", 1)[1])
    boundaries = pd.read_parquet(dataset / "daily-boundaries.parquet").set_index("calendar_index")
    checked = []
    for case in cases:
        index, code = int(case["original_source_event"]["calendar_index"]), case["code"]
        require(pd.Timestamp(case["asof_date"]) == calendar[index], "audit case date/index differs")
        peers = peer_days[index]
        require(code in peers, "audit code absent from peer universe")
        own = peers[code]
        ranks = np.array([peer["ret120"] for peer in peers.values() if peer["eligible"] and math.isfinite(peer["ret120"])], dtype=float)
        rank_value = own["ret120"]
        h_value = None
        if own["eligible"] and math.isfinite(rank_value):
            require(len(ranks) > 0, "finite own return missing from eligible universe")
            h_value = float((np.count_nonzero(ranks < rank_value) + (np.count_nonzero(ranks == rank_value) + 1) / 2) / len(ranks) * 100)
        amounts = np.array(
            [peer["turnover20"] for peer in peers.values() if peer["eligible"] and peer["liquid"] and math.isfinite(peer["turnover20"])], dtype=float
        )
        q1, q2 = np.quantile(amounts, [1 / 3, 2 / 3], method="linear") if len(amounts) else (None, None)
        boundary = boundaries.loc[index]
        require(numeric_equal(q1, boundary["q1"]) and numeric_equal(q2, boundary["q2"]), "K3 independent cutpoints differ")
        require(
            population_equal(len(amounts), boundary["k3_security_n"]) and population_equal(len(ranks), boundary["h_security_n"]),
            "peer population counts differ",
        )
        k3_applicable = own["eligible"] and own["liquid"]
        k3_value = None
        if k3_applicable and math.isfinite(own["turnover20"]):
            require(q1 is not None and q2 is not None, "K3 eligible observation missing from universe")
            k3_value = "low" if own["turnover20"] <= q1 else "middle" if own["turnover20"] <= q2 else "high"
        own_industry = industries_by_day[index][code]
        j_value = None
        if index >= 10 and cast(bool, pd.notna(own_industry)) and str(own_industry) not in _UNCLASSIFIED:
            others: set[str] = set()
            for day_index in range(index - 10, index + 1):
                for peer_code in signals.get(day_index, ()):
                    peer_industry = industries_by_day[day_index].get(peer_code)
                    if peer_code != code and cast(bool, pd.notna(peer_industry)) and peer_industry == own_industry:
                        others.add(peer_code)
            j_value = int(len(others))
        observed = case["feature_inputs_asof_t0"]["computed_features_asof_t0"]
        for feature, value, applicable in (("H", h_value, own["eligible"]), ("K3", k3_value, k3_applicable), ("J", j_value, True)):
            actual = observed[feature]
            equal = numeric_equal(value, actual) if feature != "K3" else value == actual
            require(equal, f"{case['event_id']}: {feature} independent value differs")
            classification = classify_feature(feature, value, applicable=applicable)
            require(
                classification.bin_id == observed[f"{feature}_bin"] and classification.status == observed[f"{feature}_status"],
                f"{case['event_id']}: {feature} bin/status differs",
            )
        checked.append({"event_id": case["event_id"], "checked_features": ["H", "K3", "J"], "assertions": "passed"})
    return {
        "schema_version": "hhhl-peer-feature-integrity.v1",
        "cases": checked,
        "script_sha256": file_digest(Path(__file__)),
        "feature_definition_sha256": file_digest(ROOT / "research_core/hhhl_variants_features.py"),
        "input_pins_sha256": file_digest(pins_path),
        "input_manifest_sha256": {"atlas": pins["atlas"]["manifest_sha256"], "v4_bulk": pins["v4_bulk"]["manifest_sha256"]},
        "dataset_manifest_sha256": file_digest(dataset / "manifest.json"),
        "audit_sha256": by_path["audit/ten-events.json"]["sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.dataset), ensure_ascii=False, sort_keys=True))  # noqa: T201 -- CLI assertion summary


if __name__ == "__main__":
    main()
