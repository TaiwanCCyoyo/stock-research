# First development measurement policy — 2026-09-09

Status: **selected provisional definitions; not a runnable or immutable seal**.
This resolves the measurement choices for the `price-volume-six-k5-er30`
development packet before new candidate outcomes. It does not approve the owner's
final loss budget, release confirmation/holdout or change any old result.
The immutable launch packet must include this file and its executable metric
implementation, input/runtime identities, comparator and advancement rules.

## Development question and comparison

Use the exposed 2019-01-02 through 2023-12-31 window already proposed in the
[candidate packet](research-first-candidate-packet.md); warm-up is input history
only. One six-feature candidate, no grid. Compare with one two-feature control:
equal-weight percentile ranks of trailing 20- and 60-session returns, with the
same PIT eligible population, top-five entry, rank-31 exit, tie handling, fixed
NT$400,000 gross target, NT$2m shared cash and five-holding ceiling. The control
is a deliberate specification, not inherited V5 defaults or a copied old result.
Both paths use the same finalized execution/corporate-action assumptions.

This tests whether the four extra price/volume features merit further work
beyond a simpler momentum rule. Do not select a control after seeing results.
Cash-at-zero-return is context, not a substitute for that control. Prior exposure
to overlapping configurations remains in the registry; this is not a first-ever
test or an independent comparison merely because it has a new identifier.

## Captured hit and attempts

- One attempt is flat-to-flat actual simulated exposure: first filled buy from
  zero through final disposal. Adds, partial exits, splits and attributed cash
  distributions remain within that attempt. Later re-entry is a new attempt.
- A provisional captured hit requires **net captured return >= 50%** on the sum
  of gross purchase consideration for the attempt. Define
  `G = sum(buy_quantity * modeled_execution_price)`, excluding commissions/taxes;
  `S` is gross sale consideration, `D` is attributed cash distributions available
  by the endpoint, and `C` is all charged fees, taxes and other separately charged
  trading costs. Captured net return is `(S + D - G - C) / G`. Slippage already
  embedded in execution prices is not subtracted again. Do not include unpaid
  receivables or a post-exit price rise in the captured numerator. `G` must be
  positive; empty attempts are not zero-return trades.
- 2026-09-18 clarification before candidate outcomes: `D` includes paid capital
  refunds, disclosed separately from paid dividends; returned principal is not
  dividend income. Keep the original `G`, never reduce it by the refund. A purchase
  of 1,000, later share disposal for 700 and principal refund of 300 therefore has
  zero captured PnL, not a hit. Unpaid principal refunds remain economic receivables,
  excluded from captured cash until credited. This also corrects the earlier
  malformed Markdown multiplication in the written `G` definition; it does not
  change the executable gross-purchase formula, threshold, or any prior outcome.
- There is no additional maximum holding-duration cutoff for this initial
  diagnostic: completion and capture must occur by the evaluation endpoint.
  Report holding duration separately. This is a declared endpoint convention,
  not permission to wait outside the window for a preferred hit classification.
- An open position is unresolved. Classify a closed attempt from known captured
  cash at the fixed endpoint, even if a known entitlement remains unpaid; report
  that unpaid economic entitlement separately. Missing material cash/entitlement
  evidence or indeterminate settlement status is unresolved, not a non-hit.
- All cash-determinate closed attempts below the threshold are non-hits, including
  small profitable trades. The 50% choice follows the prior owner-facing proposal
  but is **not** recorded as owner approval, nor will alternative thresholds be
  searched in this batch.
- Order attempts by first entry time, then actual fill sequence, with stable
  attempt ID as a final tie key. Hits and unresolved attempts prevent splicing
  two otherwise separated non-hit stretches together. Report all unresolved
  exposure and its separate contribution; a censored period is not a pass.
- Report disposition counts: closed cash-determinate hits/non-hits, open attempts,
  and source/settlement-indeterminate attempts; separately cross-tabulate known
  unpaid entitlements among closed hits/non-hits. These are endpoint labels,
  not a forecast of eventual cash capture or comparable equal-follow-up hit rates.

## Non-hit erosion, distinct from account drawdown

Adopt the existing measurement draft's path definition: for a chosen set of
non-hit attempts, sum their timestamped net PnL including remaining marked shares
and economic entitlements, with zero contribution before entry. Keep actual
quantities/costs and include small winners; do not compound isolated trade returns,
redistribute capital or offset with hit profits.

Primary normalization for this development report is fixed initial capital
**NT$2,000,000**, alongside TWD amounts. Also show each window's fixed pre-entry
account-equity denominator as a secondary diagnostic; it cannot hide an absolute
loss by account growth. Report terminal attribution, worst loss from zero and
peak-to-trough attribution erosion for the whole-study non-hit set, every
uninterrupted run and every overlapping 20-attempt non-hit window. Windows run
from immediately before first entry to the latest disposal in that window.
Use actual close checkpoints, not unrelated intraday lows joined together.

Open/unresolved attempts remain visible with a separate PnL contribution; no
fully known 20-attempt window means insufficient support, not zero erosion.
Overlapping windows are not independent statistical observations. Independently
report the full account's marked equity, drawdown and underwater time.

## Development triage is not final acceptance

Before launch, fix the finite execution-sensitivity scenarios and run the full
candidate and control account for each. The purpose of this first batch is to
decide whether further research is warranted, not to apply every final stress.

- Measurement/source failure or incomplete material execution is **invalid or
  unfinished**, not a losing candidate. Do not repair by deleting offending trades.
- Relative triage requires `R_candidate > R_control` separately in the baseline
  and every predeclared execution-sensitivity scenario, using the same fixed
  NT$2m net-return denominator and endpoint. A valid failure of that relative
  comparison stops this configuration; do not tune the just-viewed period.
  Check candidate positivity separately in every scenario. If a control is also
  negative, failure of the zero-return floor is not an absolute rejection gate;
  report any relative leader as **conditional lead / positive-return evidence
  insufficient**, not a failed candidate solely because of that floor. Only a
  relative leader with positive candidate returns throughout is described as
  worth the full next-stage validation. Neither label is a final pass or a
  statistical-significance claim. A control's own failure of any absolute
  threshold must not be used to reject the candidate.
- Captured-hit support and non-hit erosion remain required diagnostics. No
  approved loss veto is invented from the approximate 20% warning. If results
  warrant further work, show the owner this trade-off before final acceptance.
- Do not promote on one anecdote. Final best-attempt suppression, omission/delay
  tests, independent evidence and owner loss-budget approval remain necessary
  before claiming a good strategy. The final 70% retention rules are unchanged.

No job is released by this file: historical stock-type/board coverage, market
adapter, costs, corporate payment scenarios, execution scenarios and exact input
identities still need finalization in the single launch packet. These are bounded
candidate requirements, not an invitation to build a universal engine.
