"""Read-only mathematical conservation of the fixed HHHL summary publication."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from itertools import product
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from research_core.artifact_store import file_digest, safe_path  # noqa: E402
from research_core.hhhl_variants_features import FEATURES  # noqa: E402
from research_core.hhhl_variants_query import load_summary  # noqa: E402

CORE = ("calendar_full_n", "hit_n", "loss_n", "flat_win_n", "unknown_n", "censored_n", "censored_hit_n", "censored_unknown_n")
IDENTITY = (
    "base_row_kind",
    "candidate_id",
    "feature_id",
    "bin_id",
    "cohort_id",
    "split_id",
    "horizon",
    "landmark",
    "riskset_id",
    "feature_price_basis",
    "not_applicable_reason",
    "flag_id",
    "flag_state",
    "return_bin",
    "scope",
)
YEARS = tuple(range(2019, 2027))
COHORTS = ("P-clean", "P-over", "P-all", "C-nh", "C-52w", "C-base")
SPLITS = ("development", "cross-check")
HORIZONS = (126, 252)
FLAGS = ("X1", "X2", "X3", "X4", "X5_MA20", "X5_MA60", "X6_10", "X6_15")
STATES = ("triggered", "all_false", "unknown")
RISES = ("lt1", "b1_1p10", "b1p10_1p25", "ge1p25")


def nullable(value: Any) -> Any:
    return None if value is None or pd.isna(value) else value


class Conservation:
    """Index only aggregate identities and integer count matrices."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.checked: Counter[str] = Counter()
        needed = set(CORE) | {"known_n", "known_security_n", "row_kind", "base_row_kind", "year", "removed_year"}
        self.require(needed.issubset(frame.columns), "required conservation columns missing")
        self.count_names = tuple(str(name) for name in frame.columns if str(name).endswith("_n"))
        self.count_index = {name: index for index, name in enumerate(self.count_names)}
        counts = []
        missing_masks = []
        for name in self.count_names:
            column = cast(pd.Series, frame[name])
            missing = column.isna().to_numpy(dtype=bool)
            self.require(not missing.any() or name == "riskset_n", f"unexpected null count: {name}")
            self.require(not pd.api.types.is_bool_dtype(column.dtype), f"boolean count: {name}")
            values = column.to_numpy(dtype=float, na_value=np.nan)
            observed = values[~missing]
            self.require(
                bool(np.isfinite(observed).all() and (observed >= 0).all() and (observed == np.floor(observed)).all()), f"nonintegral or negative count: {name}"
            )
            self.require(bool((observed < 2**63).all()), f"count exceeds integer representation: {name}")
            counts.append(column.fillna(0).astype("int64").to_numpy())
            missing_masks.append(missing)
            self.checked["count_columns"] += 1
        self.counts = np.column_stack(counts)
        self.missing_counts = np.column_stack(missing_masks)
        identity_frame = frame.reindex(columns=pd.Index(IDENTITY))
        self.keys = [tuple(nullable(value) for value in values) for values in identity_frame.itertuples(index=False, name=None)]
        self.kinds = cast(pd.Series, frame["row_kind"]).to_numpy()
        self.row_years = cast(pd.Series, frame["year"]).to_numpy()
        self.removed = cast(pd.Series, frame["removed_year"]).to_numpy()
        self.tables: dict[tuple[Any, ...], dict[Any, int]] = {}
        self.find_indices: dict[tuple[str, ...], dict[tuple[Any, ...], list[tuple[Any, ...]]]] = {}
        for index, key in enumerate(self.keys):
            slot = int(self.row_years[index]) if self.kinds[index] == "year" else "drop" if self.kinds[index] == "drop_best_year" else "main"
            table = self.tables.setdefault(key, {})
            self.require(slot not in table, "duplicate aggregate identity/slice")
            table[slot] = index
        self.core_positions = [self.count_index[name] for name in CORE]
        self.additive_positions = [index for name, index in self.count_index.items() if not name.endswith("security_n")]

    @staticmethod
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(message)

    def count(self, row: int, name: str) -> int:
        self.require(name in self.count_index, f"required count absent: {name}")
        return int(self.counts[row, self.count_index[name]])

    def values(self, row: int) -> dict[str, Any]:
        return dict(zip(IDENTITY, self.keys[row], strict=True))

    def rate(self, row: int, name: str, numerator: int, denominator: int) -> None:
        self.require(name in self.frame.columns, f"required rate absent: {name}")
        value = nullable(self.frame.at[self.frame.index[row], name])
        if denominator == 0:
            self.require(value is None, f"zero denominator has a rate: {name}")
        else:
            self.require(
                value is not None and math.isclose(float(value), numerator / denominator, rel_tol=1e-12, abs_tol=1e-12), f"rate formula differs: {name}"
            )
        self.checked["rate_formulas"] += 1

    def find(self, **condition: Any) -> tuple[Any, ...]:
        names = tuple(condition)
        if names not in self.find_indices:
            positions = [IDENTITY.index(name) for name in names]
            lookup: dict[tuple[Any, ...], list[tuple[Any, ...]]] = {}
            for key in self.tables:
                lookup.setdefault(tuple(key[position] for position in positions), []).append(key)
            self.find_indices[names] = lookup
        matches = self.find_indices[names].get(tuple(condition.values()), [])
        self.require(len(matches) == 1, "required comparison table missing or ambiguous")
        return matches[0]

    def same_slice(self, key: tuple[Any, ...], target: int) -> np.ndarray:
        table = self.tables[key]
        if self.kinds[target] == "year":
            return self.counts[table[int(self.row_years[target])]]
        if self.kinds[target] == "drop_best_year":
            excluded = nullable(self.removed[target])
            included = [table[year] for year in YEARS if year != excluded]
            return self.counts[included].sum(axis=0)
        return self.counts[table["main"]]

    def basic(self) -> None:
        for row, key in enumerate(self.keys):
            if key[0] == "near_high":
                continue
            self.require(
                self.count(row, "calendar_full_n") == sum(self.count(row, name) for name in ("hit_n", "loss_n", "flat_win_n", "unknown_n")),
                "full labels do not partition",
            )
            self.require(
                self.count(row, "censored_n") == self.count(row, "censored_hit_n") + self.count(row, "censored_unknown_n"), "censored labels do not partition"
            )
            known = sum(self.count(row, name) for name in ("hit_n", "loss_n", "flat_win_n"))
            self.require(self.count(row, "known_n") == known, "known_n does not partition")
            self.checked["core_rows"] += 1
            metadata = self.values(row)
            if metadata["not_applicable_reason"] is None and metadata["bin_id"] != "not_applicable":
                full, unknown = self.count(row, "calendar_full_n"), self.count(row, "unknown_n")
                for label in ("hit", "loss"):
                    numerator = self.count(row, f"{label}_n")
                    self.rate(row, f"{label}_rate", numerator, known)
                    self.rate(row, f"{label}_lower", numerator, full)
                    self.rate(row, f"{label}_upper", numerator + unknown, full)
        for key, table in self.tables.items():
            if key[0] == "near_high":
                self.require(set(table) == {"main"}, "near-high unexpectedly has annual rows")
                row = table["main"]
                total, known, unknown, matched = (
                    self.count(row, name) for name in ("near_high_all_n", "near_high_known_n", "near_high_unknown_n", "near_high_matched_n")
                )
                self.require(total == known + unknown and matched <= known, "near-high t0 counts do not partition")
                self.rate(row, "near_high_rate", matched, known)
                self.rate(row, "near_high_lower", matched, total)
                self.rate(row, "near_high_upper", matched + unknown, total)
                continue
            self.require(set(table) == {"main", "drop", *YEARS}, "fixed annual/drop table incomplete")
            main, drop = table["main"], table["drop"]
            positions = self.additive_positions
            annual = self.counts[[table[year] for year in YEARS]][:, positions].sum(axis=0)
            self.require(bool(np.array_equal(annual, self.counts[main, positions])), "annual additive counts differ from main")
            removed = nullable(self.removed[drop])
            self.require(removed is None or removed in YEARS, "invalid removed year")
            expected = annual if removed is None else annual - self.counts[table[int(removed)], positions]
            self.require(bool(np.array_equal(expected, self.counts[drop, positions])), "drop-year additive counts differ")
            self.checked["annual_tables"] += 1

    def baselines_and_features(self) -> dict[tuple[str, str, int], tuple[Any, ...]]:
        baselines = {
            (cohort, split, horizon): self.find(base_row_kind="baseline", cohort_id=cohort, split_id=split, horizon=horizon)
            for cohort, split, horizon in product(COHORTS, SPLITS, HORIZONS)
        }
        for split, horizon in product(SPLITS, HORIZONS):
            all_key = baselines[("P-all", split, horizon)]
            clean_key, over_key = baselines[("P-clean", split, horizon)], baselines[("P-over", split, horizon)]
            for slot, row in self.tables[all_key].items():
                clean, over = self.same_slice(clean_key, row), self.same_slice(over_key, row)
                self.require(
                    bool(np.array_equal(self.counts[row, self.core_positions], (clean + over)[self.core_positions])),
                    "P-all core counts differ from clean/over union",
                )
                if slot != "drop":
                    position = self.count_index["known_security_n"]
                    self.require(
                        max(clean[position], over[position]) <= self.counts[row, position] <= clean[position] + over[position],
                        "P-all distinct-security union bounds differ",
                    )
                self.checked["pattern_union_slices"] += 1
        # Match annual bins directly. A feature's independently chosen drop
        # year is not the same slice as the baseline's independently best year.
        for (cohort, split, horizon), base_key in baselines.items():
            for feature_id, definition in FEATURES.items():
                bins = (*sorted(set(definition.bin_ids)), "feature_unknown", "not_applicable")
                feature_keys = [
                    self.find(base_row_kind="single", cohort_id=cohort, split_id=split, horizon=horizon, feature_id=feature_id, bin_id=bin_id)
                    for bin_id in bins
                ]
                for slot, row in self.tables[base_key].items():
                    total = sum((self.same_slice(key, row)[self.core_positions] for key in feature_keys), np.zeros(len(CORE), dtype=np.int64))
                    self.require(bool(np.array_equal(total, self.counts[row, self.core_positions])), "single-bin core counts do not partition baseline")
                    self.checked["single_partitions"] += 1
        return baselines

    def flags(self, baselines: dict[tuple[str, str, int], tuple[Any, ...]]) -> None:
        for flag, horizon, split, cohort in product(FLAGS, HORIZONS, SPLITS, COHORTS[:3]):
            for landmark in (5, 10, 20, 40, horizon):
                key = self.find(base_row_kind="reverse_flag", flag_id=flag, horizon=horizon, landmark=landmark, split_id=split, cohort_id=cohort)
                for row in self.tables[key].values():
                    baseline = self.same_slice(baselines[(cohort, split, horizon)], row)
                    hit = int(baseline[self.count_index["hit_n"]])
                    nonhit = int(baseline[self.count_index["loss_n"]] + baseline[self.count_index["flat_win_n"]])
                    self.require(self.count(row, "known_n") == hit + nonhit, "reverse-flag known denominator differs from baseline")
                    for label, total in (("hit", hit), ("nonhit", nonhit)):
                        triggered, all_false, unknown = (self.count(row, f"{label}_flag_{state}_n") for state in STATES)
                        self.require(
                            triggered + all_false + unknown == total == self.count(row, f"{label}_flag_all_n"),
                            "reverse flag states do not partition label class",
                        )
                        self.require(self.count(row, f"{label}_flag_known_n") == triggered + all_false, "flag known denominator differs")
                        self.rate(row, f"{label}_flag_known_rate", triggered, triggered + all_false)
                        self.rate(row, f"{label}_flag_lower", triggered, total)
                        self.rate(row, f"{label}_flag_upper", triggered + unknown, total)
                    self.require(self.count(row, "cost_denominator_n") == hit, "cost denominator differs from all full-window hits")
                    numerator = self.count(row, "hit_flag_triggered_n")
                    self.rate(row, "cost_lower", numerator, hit)
                    self.rate(row, "cost_upper", numerator + self.count(row, "hit_flag_unknown_n"), hit)
                    self.require(self.count(row, "flag_denominator_n") == hit + nonhit, "reverse flag denominator differs")
                    for state in STATES:
                        self.require(
                            self.count(row, f"flag_{state}_n") == self.count(row, f"hit_flag_{state}_n") + self.count(row, f"nonhit_flag_{state}_n"),
                            "combined reverse flag states differ",
                        )
                    self.checked["reverse_flag_slices"] += 1
        for flag, horizon, landmark, split, cohort, state in product(FLAGS, HORIZONS, (5, 10, 20, 40), SPLITS, COHORTS[:3], STATES):
            condition = dict(base_row_kind="flag", flag_id=flag, horizon=horizon, landmark=landmark, split_id=split, cohort_id=cohort, flag_state=state)
            pooled = self.find(**condition, return_bin="pooled")
            rise_keys = [self.find(**condition, return_bin=rise) for rise in RISES]
            for row in self.tables[pooled].values():
                riskset = self.count(row, "riskset_n")
                self.require(riskset == self.count(row, "calendar_full_n") + self.count(row, "censored_n"), "riskset count differs from selected windows")
                positions = [*self.core_positions, self.count_index["riskset_n"]]
                partition_total = sum((self.same_slice(key, row)[positions] for key in rise_keys), np.zeros(len(positions), dtype=np.int64))
                self.require(bool(np.array_equal(partition_total, self.counts[row, positions])), "four rise bins do not partition pooled flag riskset")
                self.checked["rise_partitions"] += 1
        for cohort, split, horizon, landmark, age, state in product(COHORTS[:2], SPLITS, HORIZONS, (5, 10, 20, 40), ("old", "recent_far"), STATES):
            self.find(
                base_row_kind="legacy_cross", cohort_id=cohort, split_id=split, horizon=horizon, landmark=landmark, flag_id=f"legacy_{age}", flag_state=state
            )
            self.checked["legacy_inventory"] += 1
        for cohort, bins in (("P-clean", ("ge100", "ge095")), ("C-52w", ("clean_overlap",))):
            for split, bin_id in product((*SPLITS, "pooled"), bins):
                self.find(base_row_kind="near_high", cohort_id=cohort, split_id=split, bin_id=bin_id)
                self.checked["near_high_inventory"] += 1


def verify(publication: Path) -> dict[str, Any]:
    Conservation.require(publication.is_absolute(), "--publication must be absolute")
    publication = safe_path(publication)
    frame, receipt = load_summary(publication)
    frame = frame.reset_index(drop=True)
    checks = Conservation(frame)
    checks.basic()
    baselines = checks.baselines_and_features()
    checks.flags(baselines)
    return {
        "schema_version": "hhhl-summary-conservation.v1",
        "dataset_id": receipt["dataset_id"],
        "publication_receipt_sha256": file_digest(publication / "receipt.json"),
        "logical_summary_sha256": receipt["summary"]["sha256"],
        "verification_code_sha256": file_digest(Path(__file__)),
        "checked": dict(sorted(checks.checked.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.publication), sort_keys=True))  # noqa: T201 -- CLI integrity receipt


if __name__ == "__main__":
    main()
