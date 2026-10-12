"""Fixed flag tables with explicit unknown counts and pre-hit cost bounds."""

from __future__ import annotations

from collections import defaultdict
from itertools import product
from typing import Any

import pandas as pd

from research_core.hhhl_variants_rates import RateAccumulator, descriptive_flag_rates, trigger_return_summary

FLAGS = ("X1", "X2", "X3", "X4", "X5_MA20", "X5_MA60", "X6_10", "X6_15")
HORIZONS = (126, 252)
LANDMARKS = (5, 10, 20, 40)
SPLITS = ("development", "cross-check")
COHORTS = ("P-clean", "P-over", "P-all")
STATES = ("triggered", "all_false", "unknown")
RISE_BINS = ("lt1", "b1_1p10", "b1p10_1p25", "ge1p25")
_EXTRA_COUNTS = tuple(f"{label}_flag_{state}_n" for label in ("hit", "nonhit") for state in STATES) + ("excluded_unknown_label_n", "excluded_censored_n")


class FlagSummaries:
    """Accumulate the preregistered 5,760 riskset and 480 reverse cells.

    Input frames already contain explicit P-all copies for reporting. This
    class does not select events, duplicate cohorts, or recalculate outcomes.
    Trigger returns retain missing values independently of flag-known counts.
    """

    def __init__(self) -> None:
        self._rates = RateAccumulator()
        self._returns: dict[tuple[Any, ...], dict[int, list[float | None]]] = defaultdict(lambda: defaultdict(list))
        self.add_zero_groups()

    @staticmethod
    def _metadata(
        row_kind: str, flag: str, landmark: int, horizon: int, split: str, cohort: str, state: str = "pooled", rise: str = "pooled"
    ) -> dict[str, Any]:
        return {
            "row_kind": row_kind,
            "flag_id": flag,
            "landmark": landmark,
            "horizon": horizon,
            "split_id": split,
            "cohort_id": cohort,
            "flag_state": state,
            "return_bin": rise,
            "scope": "full" if landmark == horizon else "landmark",
            "riskset_id": "new_no_hit_valid_prefix" if row_kind == "flag" else "all_calendar_full_known",
            "feature_price_basis": "frozen_v4_factor",
        }

    @staticmethod
    def _key(metadata: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(metadata[name] for name in ("row_kind", "flag_id", "landmark", "horizon", "split_id", "cohort_id", "flag_state", "return_bin"))

    def add_zero_groups(self) -> None:
        """Initialize all prescribed cells, including unobserved combinations."""
        for flag, landmark, horizon, split, cohort, state, rise in product(FLAGS, LANDMARKS, HORIZONS, SPLITS, COHORTS, STATES, ("pooled", *RISE_BINS)):
            metadata = self._metadata("flag", flag, landmark, horizon, split, cohort, state, rise)
            self._rates.add(self._key(metadata), metadata, 2019, {})
        for flag, horizon, split, cohort in product(FLAGS, HORIZONS, SPLITS, COHORTS):
            for landmark in (*LANDMARKS, horizon):
                metadata = self._metadata("reverse_flag", flag, landmark, horizon, split, cohort)
                self._rates.add(self._key(metadata), metadata, 2019, dict.fromkeys(_EXTRA_COUNTS, 0))

    @staticmethod
    def _counts(record: dict[str, Any]) -> dict[str, int]:
        label = record["label"]
        if bool(record["calendar_full"]):
            return {"calendar_full_n": 1, {"hit": "hit_n", "loss": "loss_n", "flat-win": "flat_win_n", "unknown": "unknown_n"}[label]: 1}
        return {"censored_n": 1, "censored_hit_n" if label == "hit" else "censored_unknown_n": 1}

    def _add(self, metadata: dict[str, Any], record: dict[str, Any], counts: dict[str, int], *, include_return: bool) -> None:
        key = self._key(metadata)
        known = bool(record["calendar_full"]) and record["label"] != "unknown"
        self._rates.add(key, metadata, record["year"], counts, (record["code"],) if known and counts.get("calendar_full_n", 0) else ())
        if include_return and known and record["flag_state"] == "triggered":
            value = record["trigger_return"]
            self._returns[key][int(record["year"])].append(None if pd.isna(value) else float(value))

    def add_flags(self, frame: pd.DataFrame) -> None:
        """Add event flag observations; controls are invalid in this P-only table."""
        required = {
            "cohort_id",
            "split_id",
            "year",
            "code",
            "event_id",
            "flag_id",
            "landmark",
            "horizon",
            "calendar_full",
            "label",
            "riskset_eligible",
            "raw_flag_state",
            "flag_state",
            "rise_bin",
            "trigger_return",
        }
        if not required.issubset(frame.columns):
            raise ValueError(f"missing flag columns: {sorted(required - set(frame.columns))}")
        records = frame.to_dict("records")
        # Validate the whole frame before adding counts to avoid partial batches.
        for record in records:
            if record["cohort_id"] not in COHORTS or record["split_id"] not in SPLITS:
                raise ValueError("flags require a P cohort and a fixed split")
            if record["flag_id"] not in FLAGS or record["horizon"] not in HORIZONS or record["landmark"] not in (*LANDMARKS, record["horizon"]):
                raise ValueError("flag, horizon or landmark outside preregistered inventory")
            if record["flag_state"] not in STATES or record["raw_flag_state"] not in STATES or record["label"] not in ("hit", "loss", "flat-win", "unknown"):
                raise ValueError("invalid flag state or label")
            if bool(record["riskset_eligible"]) and record["landmark"] < record["horizon"] and record["rise_bin"] not in RISE_BINS:
                raise ValueError("eligible landmark requires a valid rise bin")
            if record["year"] not in range(2019, 2027) or isinstance(record["year"], bool):
                raise ValueError("year must be in 2019..2026")
            if not isinstance(record["code"], str) or not record["code"].strip():
                raise ValueError("code must preserve its nonempty original string")
        for record in records:
            flag, landmark, horizon, split, cohort = (record[name] for name in ("flag_id", "landmark", "horizon", "split_id", "cohort_id"))
            if landmark < horizon and bool(record["riskset_eligible"]):
                for rise in ("pooled", record["rise_bin"]):
                    metadata = self._metadata("flag", flag, landmark, horizon, split, cohort, record["raw_flag_state"], rise)
                    self._add(metadata, record, self._counts(record), include_return=True)
            metadata = self._metadata("reverse_flag", flag, landmark, horizon, split, cohort)
            if not bool(record["calendar_full"]):
                counts = {"excluded_censored_n": 1}
            elif record["label"] == "unknown":
                counts = {"excluded_unknown_label_n": 1}
            else:
                label_class = "hit" if record["label"] == "hit" else "nonhit"
                counts = {**self._counts(record), f"{label_class}_flag_{record['flag_state']}_n": 1}
            self._add(metadata, record, counts, include_return=True)

    def finalize(self) -> pd.DataFrame:
        """Return fixed-year tables, cost bounds and descriptive return quantiles."""
        rows = self._rates.finalize()
        for row in rows:
            metadata = {**row, "row_kind": row["base_row_kind"]}
            key = self._key(metadata)
            years: tuple[Any, ...]
            if row["row_kind"] == "year":
                years = (row["year"],)
            else:
                years = tuple(year for year in range(2019, 2027) if row["row_kind"] != "drop_best_year" or year != row["removed_year"])
            year_returns = self._returns.get(key, {})
            row.update(trigger_return_summary(value for year in years for value in year_returns.get(year, ())))
            if row["base_row_kind"] == "reverse_flag":
                for label_class in ("hit", "nonhit"):
                    rates = descriptive_flag_rates(*(row[f"{label_class}_flag_{state}_n"] for state in STATES))
                    row.update({f"{label_class}_flag_{name}": value for name, value in rates.items()})
                # All full-window hits remain in this denominator, including
                # flag-unknown events. Unknown flags widen the cost bounds.
                row["cost_denominator_n"] = row["hit_flag_all_n"]
                row["cost_lower"] = row["hit_flag_lower"]
                row["cost_upper"] = row["hit_flag_upper"]
                row["riskset_n"] = None
                for state in STATES:
                    row[f"flag_{state}_n"] = row[f"hit_flag_{state}_n"] + row[f"nonhit_flag_{state}_n"]
                row["flag_denominator_n"] = sum(row[f"flag_{state}_n"] for state in STATES)
            else:
                riskset_n = row["calendar_full_n"] + row["censored_n"]
                row["riskset_n"] = riskset_n
                for state in STATES:
                    row[f"flag_{state}_n"] = riskset_n if row["flag_state"] == state else 0
                row["flag_denominator_n"] = riskset_n
        return pd.DataFrame(rows)
