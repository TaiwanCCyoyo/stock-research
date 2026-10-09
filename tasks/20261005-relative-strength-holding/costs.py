"""Preregistered H05 modeled costs; execution uses the shared auction engine.

These rates, minima and rounding rules are study assumptions, not legal or
broker fee claims. Penalty is a cash surcharge on both sides and never changes
the observed execution price. The minimum applies to each actual fill leg.
"""

import logging
from fractions import Fraction

from research_core.auction import CostSchedule

LOGGER = logging.getLogger(__name__)


def cost_schedule(scenario: str = "baseline") -> CostSchedule:
    """Return the fixed baseline or high-friction shared cost contract."""
    if scenario not in ("baseline", "high-friction"):
        raise ValueError(f"unknown H05 cost scenario: {scenario!r}")
    LOGGER.debug("Selecting H05 modeled cost scenario %s", scenario)
    return CostSchedule(
        commission_rate=Fraction(1425, 1_000_000),
        min_commission_cents=2000,
        commission_quantum_cents=100,
        commission_rounding="ceil",
        sell_tax_rate=Fraction(3, 1000),
        tax_quantum_cents=100,
        tax_rounding="ceil",
        penalty_rate=Fraction(1 if scenario == "baseline" else 3, 1000),
        penalty_quantum_cents=100,
        penalty_rounding="ceil",
    )
