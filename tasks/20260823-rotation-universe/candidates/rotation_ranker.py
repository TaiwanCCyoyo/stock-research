"""Hold the top-K names by a weighted rank score, with hysteresis to bound turnover.

This is the first strategy in this repository that is cross-sectional. Every earlier
candidate answers "is this symbol moving?" for each symbol independently; this one answers
"of the names eligible today, which K do I own?", which is the question the owner's
objective actually poses (`docs/en/research-objective.md`).

**All the work happens before the backtest starts.** `features.py` writes percentile ranks
per date; `__init__` collapses them into one score per (date, symbol) and sorts each date
once. `on_bar` is then a dict lookup and a set comparison. The archetype strategies
recompute rolling windows from a growing Python list on every symbol-bar, which measured
about 1.5 seconds per symbol over a one-year cell -- roughly half an hour for this pool.
That cost is what forced the split, not a preference for tidiness.

**Turnover is bounded by hysteresis, not by a rebalance calendar.** A held name is sold only
when its rank falls past `exit_rank`, which is looser than the `top_k` needed to buy in. With
`top_k` 5 and `exit_rank` 15, a position survives drifting from 5th to 14th and is replaced
at 16th. Widening the band trades responsiveness for turnover directly, which is the knob the
objective names as a hard constraint: Taiwan round-trip cost is 0.44-0.6%, so a book that
turns over twenty times a year gives up something like 9-12% before anything else happens.

**No stop.** Deliberate, for the first study. Exits happen because something ranked higher,
so adding a stop would put two exit mechanisms in one arm and make the result unattributable
-- the mistake `20260820` made with Darvas and `20260821` had to unpick. A stop belongs in a
later arm, tested against this one.

Ranks are only defined among symbols eligible on that date, so ineligible names never enter
the ranking and a held name that loses eligibility drops out of the ranking and is sold.
"""

from __future__ import annotations

import zlib
from pathlib import Path
from typing import Any, cast

import pandas as pd
from engine.strategy_base import StrategyBase

TASK_ROOT = Path(__file__).resolve().parents[1]
FEATURES = TASK_ROOT / "features.parquet"

DEFAULT_WEIGHTS = {
    "r_ret_20": 1.0,
    "r_ret_60": 1.0,
    "r_ext_20": 1.0,
    "r_above_ma60": 0.0,
    "r_vol_ratio": 1.0,
    "r_contraction": 0.0,
    "r_cohort_ret_20": 0.0,
    "r_cohort_breadth": 0.0,
}


class RotationRanker(StrategyBase):
    def __init__(self, broker: Any, context: dict[str, Any] | None = None) -> None:
        super().__init__(broker, context=context)
        self.ranking: dict[str, list[str]] = {}
        self.rank_of: dict[str, dict[str, int]] = {}
        self._load_ranking()

    # -- parameters -------------------------------------------------------
    @property
    def top_k(self) -> int:
        return int(self.context.get("top_k", 5))

    @property
    def exit_rank(self) -> int:
        """Hold until the name falls past this rank. Must be >= top_k."""
        return max(int(self.context.get("exit_rank", 15)), self.top_k)

    @property
    def weights(self) -> dict[str, float]:
        supplied = self.context.get("weights")
        if not supplied:
            return DEFAULT_WEIGHTS
        if isinstance(supplied, str):
            pairs = [item.split(":") for item in supplied.split(",") if item]
            return {name.strip(): float(value) for name, value in pairs}
        return {str(k): float(v) for k, v in supplied.items()}

    # -- precomputation ---------------------------------------------------
    def _load_ranking(self) -> None:
        """One score per (date, symbol), each date sorted once, before any bar is seen."""
        table = pd.read_parquet(FEATURES)
        table = cast(pd.DataFrame, table[table["eligible"]])

        weights = self.weights
        score = None
        for column, weight in weights.items():
            if not weight:
                continue
            component = cast(pd.Series, table[column]).fillna(0.5) * weight
            score = component if score is None else score + component
        if score is None:
            raise ValueError("every weight is zero; nothing to rank on")
        table = table.assign(_score=score).dropna(subset=["_score"])

        # Ties are common once eight averaged percentile ranks are summed, and a stable sort
        # would resolve them by the parquet's own row order -- which is code order, so the
        # lowest ticker would win every tie for the life of the study. A CRC of the code is
        # arbitrary but fixed and reproducible, which makes the tiebreak a decision rather
        # than an artifact of file layout.
        table = table.assign(_tie=[zlib.crc32(code.encode()) for code in table["Code"]])
        table = table.sort_values(["Date", "_score", "_tie"], ascending=[True, False, True])
        for date, group in table.groupby("Date", sort=False):
            key = str(date)[:10]
            codes = group["Code"].tolist()
            self.ranking[key] = codes
            self.rank_of[key] = {code: index for index, code in enumerate(codes)}

    # -- engine hook ------------------------------------------------------
    def on_bar(self, date: Any, data_dict: dict[str, Any]) -> None:
        key = str(date)[:10]
        order = self.ranking.get(key)
        if not order:
            return
        ranks = self.rank_of[key]

        held = [code for code in data_dict if self.broker.get_position(code) > 0]

        # Sell first, so the proceeds are available to the buys below on this same bar.
        for code in held:
            rank = ranks.get(code)
            if rank is None or rank >= self.exit_rank:
                position = self.broker.get_position(code)
                self.broker.sell(code, float(data_dict[code]["Close"]), position, date)

        still_held = {code for code in data_dict if self.broker.get_position(code) > 0}
        room = self.top_k - len(still_held)
        if room <= 0:
            return

        for code in order[: self.top_k]:
            if room <= 0:
                break
            if code in still_held or code not in data_dict:
                continue
            price = float(data_dict[code]["Close"])
            qty = self.equal_notional_quantity(code, price)
            if qty > 0 and self.broker.buy(code, price, qty, date):
                room -= 1

    def warmup(self) -> int:
        """Ranks already encode their own history requirement, via eligibility."""
        return 0

    # -- helpers ----------------------------------------------------------
    def equal_notional_quantity(self, code: str, price: float) -> int:
        """Integer-share sizing at a fixed fraction of initial capital.

        Defaults to 1/`top_k` of initial cash so a full book is fully invested. Sizing uses
        the broker's execution (raw) price rather than the adjusted signal price: adjusted
        prices sit below raw prices by the dividends still to come, so sizing off the signal
        price would hand systematically larger positions to dividend-heavy names.
        """
        execution_price = self.broker.execution_price(code, price)
        if execution_price <= 0:
            return 0
        fraction = float(self.context.get("position_pct", 1.0 / self.top_k))
        budget = float(self.broker.initial_cash) * fraction
        qty = int(budget // (execution_price * (1 + self.broker.fee_rate)))
        return max(qty, 0)
