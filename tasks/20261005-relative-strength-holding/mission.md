# Relative strength with fixed trend exits: prospective design

2026-10-05. Parent-owned provisional development design, before any results from
these policies. Phase 0 implements and synthetically verifies the thin decision
rule only. This file is NOT an approved market execution packet or a final owner
acceptance rule. No account performance has been evaluated for this task.

Prospective source refinement (2026-10-05): [source-contract.md](source-contract.md)
selects 2019-01-02..2023-12-29 as the first conditional account slice of the intended
broader window, with warmup beginning in 2019. It records the retained daily
membership join, distinct reference-price basis and exact new feature gate.
This is fixed before H05 market calculations, not a response to its performance.

Prospective measurement refinement (still zero H05 market runs):
[measurement-contract.md](measurement-contract.md) fixes the provisional 50%
settled full-attempt hit, common observation endpoint, daily-close account and
non-hit attribution scale, ordering/censoring, monetary denominators and modeled
costs. This reuses the core ledger/attempt attribution, not invented intraday
marks or the older 018 event-checkpoint metric. Its final paragraph retains the
unfinished sensitivity/advancement/packet gate; no market run is approved yet.

Prospective interruption refinement (2026-10-05, still zero H05 market runs):
the named halt/resumption and residual-share rules below extend the initial
unsupported-state boundary. They apply identically to both exit profiles and
do not revise any already-evaluated policy or historical result.

Prospective bounded-model refinement (still zero H05 market runs):
[sensitivity-contract.md](sensitivity-contract.md) fixes the five matched model
arms, maximum ten account paths, baseline/relative-lead stopping rule and
control-aware interpretation before results. [screening.py](screening.py) applies
that rule without tuning; [diagnostics.py](diagnostics.py) records actual burden,
slot labels and realized-hit waiting separately from returns. The single market
runner, source-scope assertions and approved packet are still required. This is
not an owner loss-budget approval or a reason to open an independent period.

## Why this question

The preserved feature atlas and H03 comparison suggest relative strength is a
more useful starting point than the three tested industry roles. All nine exact
interaction/role candidates failed their own prospective screens; those verdicts
stay unchanged. H03 also shows why greater doubling frequency alone cannot choose
an account: nonwinners have different downside paths. This task investigates the
entry/holding tradeoff rather than promoting a failed role candidate.

Compare only two policies with identical entry, sizing and maximum holding time:
`rs-ma20` exits below SMA20; `rs-ma60` exits below SMA60. The longer average is a
control for allowing more ordinary fluctuations, not a presumed winner. This is
a simple moving-average holding test, not the full Wyckoff H04 theory. Do not add
industry filters, candlestick combinations, adaptive thresholds or a rank-based
rotation rule. Do not reuse old returns from differently sized/same-close accounts.

## Fixed decision policy v1

- Account target: NT$2,000,000; five occupied issuers maximum. Cash is allowed.
- One after-close review; orders issued then can first reach the following
  supplied session. No same-close execution, future-open sizing or leverage.
- A supplied eligible ordinary stock qualifies when rs60 percentile >= 0.8,
  ret60 > 0 and current signal close > SMA20. No industry or 0050 gate.
  Ranking is descending rs60, descending ret60, then ascending code.
- Planned market adapter: rank contemporaneous eligible ordinary stocks using
  the atlas ret60/average-tie percentile definition. Require 60 consecutive
  usable calendar closes, with no whole-history survival filter. Entry also
  requires a trailing 20-session median raw traded-value proxy >= NT$20 million.
  Calculate ranks before this liquidity admission. These are new provisional
  account choices, not a claim that the old atlas already used them. Exact
  universe/calendar/source binding must precede market execution.
- Each new position receives at most NT$400,000 including modeled purchase costs,
  or remaining spendable cash if lower. Keep this nominal budget fixed, not 20%
  of future equity. Use `buy_quantity_for_budget` and round down to 1,000-share
  lots. No adds, leverage, profit reinvestment sizing or periodic rebalancing.
- Reserve the entire assigned budget for each generated buy for that evening;
  unused lot-rounding capacity is not redistributed to later candidates in that
  same review. A zero-quantity candidate consumes no budget and is skipped with
  a reason. The execution layer still charges actual fills only.
- Existing positions and untradable stock claims reserve their issuer slots.
  A proposed sale releases neither a slot nor cash before execution. Do not
  finance purchases with projected sale proceeds or unpaid entitlements.
- Exit all held stock if signal close is strictly below the selected SMA, OR
  completed session closes since actual entry reach 252. Equality does not exit.
  Both policies share the 252-close cap. There is no intraday stop or promise of
  a maximum realized loss; an overnight gap or failed sale can exceed expectations.
- Fixed after-close BUY limit: current raw close times 1.02, rounded DOWN to the
  stock tick grid. SELL limit: raw close times 0.90, rounded UP. These are advice
  limits, not exchange reference-price bounds. The execution provider must supply
  the actual applicable bounds and observed price; an out-of-limit or unfilled
  order cannot be turned into a guaranteed fill.
- Generate sells in code order, then ranked buys. Stable advice IDs include
  profile, decision timestamp, code and side. Quantity/limit are fixed at that
  review. Day orders terminate at their declared window; at the next review,
  a still-qualified entry or necessary exit receives new advice based on current
  information. Do not replay yesterday's expired recommendation.
- No unresolved pending requests are supported by this first thin policy; fail
  explicitly if supplied. It is used with chronology `extra_delay=0`, never the
  old mechanical-delay stress. Unsupported residual odd shares also stop with
  their identity; they cannot be dropped, valued at zero or sold at a fictitious
  regular opening odd-lot price. A source-bound residual venue adapter is required
  before any market evaluation involving those positions.
- Features carry source IDs and same-review-day availability no later than the
  decision. Missing entry features/eligibility are skips, not zero. Malformed,
  nonfinite, future-dated or inconsistent inputs fail. Held-stock missing marks
  or required exit features stop measurement, rather than silently extending
  a position. Provider timestamps are assertions to bind to sources, not proof
  of historical PIT availability supplied by a unit test.

## Absence semantics and verification

The synthetic policy accepts an explicit fixed set of absent review dates. Such
dates generate no advice; the next attended review recomputes from its latest
features and actual account. Missed buys that cease to qualify are not bought
later. A missed sale can become a hold when the latest exit condition no longer
holds. Actual exposure/cash during absence remain in chronology and the ledger.

This tests the requested semantic behavior, NOT the final 10% signal omission,
one-day absence or 70% return-retention experiment. Sampling, signal-to-absence
mapping, seeds and severe scenarios need a separate pre-result execution packet;
do not silently equate a fraction of dates with a fraction of signals. Do not
implement a fake stress test by deleting trades or delaying all old requests.

Use hand-calculable cases for rankings/ties, both exits, common time cap, inclusive
cost budgeting, real cash/claim capacity, no speculative sale proceeds, no adds,
unfilled re-evaluation, missing/future inputs and absence/resumption. At least one
integration must use the existing `run_chronology` to demonstrate next-session
fills. Reuse unchanged ledger/auction evidence; do not build a parallel engine.

## Market execution gate and later account measurement

Intended development stock window remains 2019-01-02..2026-08-14, already exposed,
for continuity with the evidence that motivated this task. Warmup uses the same
window; earlier years and later outcomes are not implicitly opened. No date is
selected because these policies performed well there. The canonical source has
more years, but this task has not approved reading their strategy outcomes.

Before a market run, complete the versioned adapter binding and a single approved
registered-job packet: exact source files/snapshots, PIT stock membership and
survival scope, calendar, raw/signal price distinction, corporate economic events,
reference limits, fills/capacity assumptions, fees/tax/penalty, missing marks and
terminal positions. Reuse latest existing evidence first. Unknown event economics
or a missing held-security continuation cannot become a zero, a favorable exclusion,
or an assumed liquidation. Restrict unsupported claims transparently; never repair
history by inserting current industry/stock metadata as past knowledge.

The market packet must prospectively define captured-hit return/horizon, settled
versus unpaid claims, attempt order/censoring, non-hit attribution and all reporting
denominators, comparison budget and advancement rule. Use existing ledger and
attribution modules. Report complete account and non-hit contribution separately;
neither the historical 20% warning nor old turnover/cost ceilings is a new veto.
Final owner loss-budget acceptance, manual stress and independent confirmation
remain required. Phase 0 synthetic success cannot authorize market execution,
automatically open confirmation/holdout or establish investment readiness.

## Named interruptions and supported residuals — prospective v2

Reuse only the three source-bound one-session halts and the bound 2316 capital
suspension already enumerated in the source contract. During a confirmed halt,
keep the full actual holding, issuer reservation and cash; use the explicitly
modeled earlier-price mark for accounting only. Generate no advice for that
issuer, even at the holding-time cap. Do not insert that mark into the raw price
table or H05 signal/average calculation. Unknown gaps retain the original stop.

On resumption, features start their normal contiguous-history warmup again.
If an attended review has an observed current price but its profile's exit
average is unavailable specifically because of this named interruption, advise
a full exit at that review's ordinary SELL limit. This is a new fixed risk rule,
not a guess that the missing average would have triggered an exit. If that
average has recovered, evaluate the ordinary MA/time-cap rules instead. A missed
review produces no advice; no permanent liquidation flag or old order survives
to force a sale after the current condition has changed. A subsequent unknown
gap ends the named recovery exception. Both special states prohibit new entries.

When explicitly enabled with the retained residual adapter, split an already
advised full exit into its 1,000-share regular-open portion and remaining shares
at the following session's 14:00 submission / 14:30 after-hours odd-lot window.
Both legs retain the originating signal identity, review-time price limit and
actual total quantity. Buys remain whole lots. The regular close is an explicit
modeled after-hours price proxy, not an observed odd-lot auction price or a
guaranteed fill. Apply costs separately to each actual leg. Do not use a regular
opening price for odd shares, and do not release capacity until the real exits.

The terminal review emits no orders without a future session. Once this venue
capability is explicitly enabled, positive integer residual shares may remain
marked in the terminal account; they are not a closed/captured attempt or a
forced liquidation. Without the capability, the original residual stop remains.
Pending requests, malformed quantities, missing held marks and unknown rights
still stop. A clean terminal state is not a statement that everything was sold.
