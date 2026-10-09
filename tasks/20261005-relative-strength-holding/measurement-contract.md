# H05 development account measurement v1

Prospective definition, fixed before any H05 market evaluation. This is a
development diagnostic, not the owner's final loss-budget approval. It extends
the mission without changing any retained experiment or the shared ledger.

## Observed scale and horizon

Use every successfully completed 20:00 review snapshot in the registered calendar,
including absent reviews. Marks are the raw close or the explicitly source-bound
halt/share-claim accounting proxy already declared in the source contract. Reuse
`replay_ledger` and `attribution.mark_attempt_pnl` at each snapshot's exact event
prefix, and reconcile cash, cash rights, stock claims, holdings and equity against
the saved snapshot. Do not mark an earlier prefix using post-split share units.
Missing dates, prices or unresolved execution cannot become a complete period.

This measures **daily close-to-close** account drawdown and non-hit erosion,
including initial capital. It does not claim intraday extrema. No fabricated
pre/post-event prices or synthetic account checkpoints are needed. The older 018
adapter's event-checkpoint metric remains unchanged and is not silently called
equivalent: H05 uses the same core ledger/attempt attribution with a separately
versioned daily aggregation. Repeated entries on one day retain their actual
event order, not an invented sequence of intraday valuations.

The first fixed observation endpoint is 2023-12-29 at 20:00 Taipei. An attempt is
one ledger-defined flat-to-flat exposure, including partial exits and share rights.
Sort by the original first BUY event index, including simultaneous fills. A
provisional captured hit requires a closed attempt, no unpaid dividend/principal
or undelivered share rights at the endpoint, and net paid cash profit divided by
gross stock purchases **at least 50%**. Net paid profit includes all actual costs,
paid dividends, principal refunds and fractional settlements. Principal refunds
do not reduce gross purchases. Open or unpaid attempts are unknown, not non-hits;
report their economic contribution separately. Small wins and losses are both
non-hits. Classifications are endpoint retrospective diagnostics, never inputs to
earlier decisions.

This is a full-attempt return captured by the common endpoint, **not** a claim of
50% within one year. The shared 252-close exit-advice cap is not a guaranteed fill
deadline. Report actual stock/claim exposure length and cash-resolution time;
late exits and unpaid claims cannot be relabeled as on-time captured returns.
No after-endpoint prices or payments are read to complete an attempt.

## Non-hit contribution, not another executable account

At each review, compute every attempt's economic PnL from that event prefix:
executed cash flow plus its unpaid cash rights and marked stock/share claims.
The sum plus initial capital must equal the actual account equity. Retain the
whole path, including open/unknown attempts. A dividend payment transfers a
receivable to cash; it cannot manufacture a second profit.

For all known non-hits, each maximal contiguous non-hit run, and every overlapping
20-attempt all-non-hit window, sum **only those attempts'** daily PnL. Start from
zero before their first entry and retain the path through the common endpoint.
Report terminal net contribution, maximum loss below zero, and largest decline
from that contribution's prior high. The primary denominator is the fixed initial
NT$2,000,000, not a balance inflated by other winners. No compounding of individual
trade returns and no winner offset. These are attribution/erosion fractions, not
actual account drawdown or a simulated misses-only portfolio.

A hit breaks a non-hit run. An unknown also breaks a _known_ run but does not prove
it was a hit: if a possible 20-attempt non-hit window contains unknowns and no known
hit, mark the worst-window conclusion unavailable. No eligible or too few windows
is not zero erosion. Keep small profitable non-hits in all counts and averages.
The 20-attempt/about-20% warning remains informational, never a new pass/fail gate.

Report actual daily account return/drawdown independently. Annual contribution is
year-end equity minus the previous year's endpoint (initial capital for the first
year); do not add dividends again. Costs are reported once from executed trade
components. Annual gross-buy turnover and half of two-sided turnover both use
fixed initial capital and clearly name their conventions; do not reinstate the
withdrawn 3-times/2% limits. Closed-attempt counts differ from sell-leg counts.

## Prospective modeled costs

Both exit profiles use commission 0.1425% each side, minimum NT$20 per actual fill
leg; ordinary-stock sell tax 0.3%; and an additional 0.1% cash friction charge on
each side. Each component rounds upward independently to NT$1. The high-friction
arm changes only the additional charge to 0.3%. Minimum commission is separate for
regular and odd-lot legs; unfilled requests incur no transaction cost. A fixed
slot budget includes buying costs. Neither arm changes an observed price or proves
a queue fill, and the higher charge is not claimed as a performance lower bound.

The commission/minimum/rounding/friction are explicit research assumptions, not
the user's broker tariff. [TWSE Article 94](https://twse-regulation.twse.com.tw/TW/law/DOC01.aspx?FLCODE=FL007304&FLNO=94)
allows broker-set fees; 0.1425% is not asserted to be a universal legal maximum.
[The ordinary stock transaction tax](https://www.etax.nat.gov.tw/etwmain/tax-info/understanding/tax-saving-manual/national/securities-transaction-tax/JNxPwlJ)
is distinct from commission. No day-trading concession is assumed. Investor-specific
dividend income tax/supplemental insurance is not yet modeled: expose this remaining
net-dividend uncertainty before promotion, never call gross cash final after-tax profit.

The subsequent [sensitivity contract](sensitivity-contract.md) fixes the bounded
allocation/payment/cost assumptions and control-aware development screen before
outcomes. The complete single-run packet still requires prospective sealing.
Neither contract alone authorizes running the market or waives later manual
recovery, best-attempt and independent-evidence requirements.
