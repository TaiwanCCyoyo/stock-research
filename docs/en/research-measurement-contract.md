# Account measurement contract — draft 2026-09-08

Status: **design draft; principles A/B clarified by owner, quantitative definitions
not approved or sealed; no candidate run authorized by this document**.
The owner has resumed research; this is no longer a pause for
compression. Read the [goal](research-goal.md), [owner contract](research-owner-contract.md)
and [foundation](research-foundation.md) first. Historical missions retain their own
definitions and verdicts. Do not copy this draft into an old seal.

## What the first resumed stage must establish

1. Cash, holdings, receivables, corporate actions and marked equity reconcile on
   hand-calculable synthetic events; cash available to buy is not account equity.
2. Seal explicit provisional definitions and metric tests for development; final
   acceptance still requires the owner's loss-budget decision. This follows the
   2026-09-09 staged-research update, not approval of these draft numbers.
3. Reuse existing execution pieces where their actual semantics fit, then implement
   the missing order/cash/fill behavior with synthetic tests before any market run.
4. Finalize the measurement/execution contract, exposure inventory and one bounded
   discovery mission before declaring code/data/runtime identities immutable.

The current main checkout already contains the shared foundation and Claude's
`1d77eb9` correction. The older `codex/kline-sizing` checkout is not an execution
environment for this draft. Its existing backfill edit is not owned by this work.
No market cache or historical result needs to be changed for this stage.

## Decisions that change the meaning of the owner's requirement

The owner answered both questions during resumed work. Record those answers rather
than treating the initially recommended full-account interpretation as approved.

### A. Selection success versus money actually captured

Keep two separate labels. A stock that rises after we sold it can demonstrate a
selection opportunity, but it has not paid for our account's failed attempts.

- **Selection opportunity:** price reaches a frozen threshold within a frozen
  forward trading-day horizon from achievable entry. This is an ex-post diagnostic,
  never an input to a decision that occurred earlier.
- **Account hit (owner-approved principle):** the completed flat-to-flat attempt's
  actually captured profit, including costs and properly attributed dividends, reaches a
  frozen return threshold on gross buy cash committed. Adds and partial exits stay
  inside the attempt; a tiny remaining position's price doubling is not a doubling
  of the whole attempt. An unrealized or briefly touched gain does not count as
  captured cash profit. Unpaid receivables belong in economic equity but must not
  by themselves turn an unpaid profit into a captured hit; settlement/as-of handling
  remains to be fixed, with unknowns disclosed instead of classified as misses.

Owner confirmed **account hit**, with selection opportunity reported separately.
Neither a numerical threshold nor an observation limit is approved by this draft.
The old institutional card uses a nominated 60-trading-day price threshold; that
does not automatically define a realized account hit for the current mandate.
Do not choose +30%, +50%, +100%, or a horizon after seeing which gives a pass.

### B. Non-hit erosion must not be masked by other winners

The owner rejected using full-account drawdown as the only answer: a large profit
on another holding must not excuse many small non-hit losses accumulating into a
large loss. They also clarified that **20% is an approximate warning reference**.
Twenty attempts remains a useful reporting window, not permission to hide a longer
erosion run by resetting every 20 trades.

Measure **non-hit PnL attribution/capital erosion** and full-account equity as two
different series. The attribution keeps the observed quantities, fees, cash-flow
dates and marked PnL of the selected non-hit attempts, including small wins. It
excludes profits and losses of hit attempts; do not change positions or reinvest a
fictional misses-only cash balance. It answers what those attempts contributed,
not whether a stand-alone strategy would have generated identical orders.

Multiplying trade returns is still not account drawdown. The existing
`synthetic_non_hit_effect.v1` remains diagnostic. No exact replacement numerical veto
is approved. Development may report a presealed provisional definition without
pretending it is an approved veto; confirm the loss budget before final acceptance.

## Proposed complete window convention (not yet an acceptance gate)

- An attempt begins at the first executed buy from zero holdings and ends at the
  final sale back to zero. Recommendations, rejected orders and adds are not new
  attempts. A later re-entry is a new attempt with a new identity.
- Order attempts by first executed entry timestamp, then the actual execution
  sequence index; do not sort by PnL, name, or exit timestamp. Preserve the full
  ordered stream, including open/unclassifiable attempts.
- A hit interrupts a non-hit run. A positive non-hit stays in it. An unknown must
  not be removed or converted into a miss. Any potentially worst unresolved window
  prevents a complete gate verdict, even if some fully observed windows exist.
- Examine every contiguous window of exactly 20 known non-hits. Its time interval
  starts immediately before its first buy and ends at the latest flat exit among
  its 20 attempts. Include the initial mark, each session close, and documented
  executable valuation checkpoints; do not create synthetic intraday lows from
  different stocks' daily lows. Entitled but unpaid cash remains a receivable at
  the end, rather than extending the window to an arbitrary payment date.
- Proposed denominator `E0`: the full account's marked equity immediately before
  the first entry of the selected window, fixed throughout the window. Also report
  TWD amounts and fractions of initial NT$2m so growth of the account cannot make
  an absolute loss invisible. This normalization is proposed, not owner approval
  of a new 20% gate.
- For each attempt `i`, compute its cumulative net PnL `p_i(t)` from its actual
  buys, sells, attributed paid dividends, remaining marked shares and unpaid
  entitlements. It is zero before entry; buy fees produce immediate negative PnL.
  Payout converts receivable to cash without changing economic PnL. Do not add
  both raw-price dividends and an adjusted-price total return.
- Let `A(t) = sum(p_i(t))` for only the selected non-hit attempts. Report terminal
  contribution `A(end)`, worst cumulative loss `max(0, -min(A(t))) / E0`, and
  peak-to-trough erosion `max(max(A(u): u <= t) - A(t)) / E0`. Use a zero initial
  contribution checkpoint. Never divide by a changing `E0 + A(t)` and present that
  as an observed account. The actual account may remain profitable while this
  attribution shows unacceptable erosion; it cannot rescue the attribution result.
- Separately, actual account equity is `cash + marked stock value + receivables`;
  report its peak-to-trough drawdown and underwater duration. Also report the
  entire study's non-hit TWD contribution, each uninterrupted non-hit run, and
  overlapping 20-attempt windows. The presence of hits does not erase accumulated
  non-hit costs in the whole-study attribution.
- This is **ex-post attribution of actual exposure**, not a tradable isolated
  account or a claim about losses under different selection/cash decisions.
- No eligible window means **insufficient evidence**, not 0% and not an automatic
  pass. Open/unknown attempts are right-censored, not guaranteed future failures.
  The final metric contract must fix censoring/as-of rules, required independent
  window support and how inference handles overlapping windows; these are not
  independent observations suitable for a naive binomial confidence interval.

Hand calculations (not market data): twenty non-hit attempts with ten losses of
NT$20,000 and ten wins of NT$5,000 contribute **-NT$150,000**, or 7.5% of a fixed
NT$2m denominator. A different hit earning NT$500,000 makes the total +NT$350,000,
but does not change that 7.5% erosion. Their temporal order/marks determine the
worst interim erosion; the endpoint alone cannot prove it. Separately, an actual
account path 200, 220, 180, 210 in units of NT$10,000 has 18.18% drawdown despite
ending +5%. These are different quantities, and neither replaces the other.

## Corporate-action accounting prerequisite

Claude's latest correction identifies payments after exit and non-hit windows
bridging an intervening hit. Its report is evidence of the correction, not proof
that an executable account model is complete. In particular, assigning a payment
to the latest closed attempt is ambiguous when the same stock has been re-entered.

The explicit replay protocol separates:

- entitlement: an authoritative identified net amount belongs to the attempt that
  earned it; it adds a receivable, not spendable cash;
- payment: the same entitlement is settled once on the recorded payment date,
  regardless of whether the stock is still held or has since been bought again;
- valuation: unpaid receivables are included once in equity and cannot finance
  orders until paid. Price adjustments for signals never create cash payments.

Synthetic acceptance case: initial cash 1,000; buy one share for 100; earn a 10
dividend; mark at 90. Equity remains 1,000 but spendable cash is 900. Sell at 90,
then buy the same stock for 80. Paying the old dividend changes cash from 910 to
920 and receivables from 10 to zero; equity remains 1,000 if the new share marks
at 80. The old attempt has zero economic PnL, and the new attempt earns no part
of that dividend. Duplicate payment and spending the receivable must fail.

This protocol cannot invent missing entitlement or payment dates. Legacy unlinked
events preserve recorded replay compatibility but are not PIT cash-timing evidence.
If actual source dates/amounts are missing, mark the required measurement unavailable;
the parent may resolve acquisition gaps directly under the owner's 2026-09-09
authorization. Missing evidence remains unavailable until verified; external
assistance is optional, not a prerequisite for Codex acquisition work.

## Counterfactual execution contract still to finalize

Keep the owner's independent scenarios: omission 10%, delay one extra trading day,
and suppress the best one complete attempt; separately report omission 20%, delay
three days, and best three. The unperturbed net account return must be positive;
each primary scenario must remain nonnegative and omission/delay retain at least
70% of that same-window simple net return. Not a CAGR ratio or gross-PnL ratio.

Before execution, fix:

- stable actionable-order/signal identities, not just dates; define repeat advice,
  buys versus sells, partial fills, persistence/cancellation, and omission sampling
  with seeds and a predetermined multi-seed aggregation rule;
- delay relative to the already-next-session baseline, order expiry, pending sells,
  cash reservations and competition, plus treatment when a newer signal disagrees;
- best-attempt rank by net account-PnL contribution in the baseline, tie break and
  exact suppressed entry identity. Keep the stock eligible for other distinct
  attempts; baseline future outcomes may select the stress target but may never
  enter the trading strategy as a prediction feature;
- full rerun of subsequent decisions, quantities and fills. Removing a whole symbol,
  filtering recorded trades or subtracting PnL is not this test;
- actual market/session-specific round-lot and odd-lot execution, fees, taxes,
  slippage, price limits, suspensions, partial/unfilled orders and missing marks.
  Daily regular-session open alone is not an odd-lot fill observation.

No thresholds for underwater duration or odd-lot share are added. All controls must
obey the same NT$2m/five-holding capacity and executable costs. A 30-holding legacy
control may be context, not permission to expand the feasible candidate set.

## Evidence and implementation sequence

The registry already records viewed price-strategy history from 2019-01-02 through
2026-08-14. Earlier dates or additional features are **unknown**, not certified
unseen. Do not inspect additional economics simply to decide which period might
make a usable holdout. Final confirmation requires an exposure audit, adequate
independent evidence and, if necessary, a prospective observation arrangement.

The entitlement/replay prerequisite is implemented and synthetic-tested. Current
implementation adds a policy-free non-hit attribution reducer and hand-calculable
fixtures; it accepts explicit hit labels but never chooses a hit threshold or
promotes a candidate. Next: seal provisional development definitions and connect
the selected candidate's required metric fixtures to the existing account output.
Do not restart a generic engine audit or wait for final owner metrics before
bounded development exploration. Reuse
`tasks/20260829-rank-debounce-next-open/candidates/rotation_ranker_v10.py` in the
older sizing worktree as design evidence for next-open/slippage/shared cash, not
as proof of odd-lot or pending-order execution. The independently maintained
`tasks/20260908-executable-fills/` card now adds a queued next-open implementation;
it is not owned by this measurement work. Coordinate before duplicating or editing
that model, and do not adopt its modeling assumptions as exchange facts.
No new UI,
parameter grid, automatic holdout opening, seal migration or download is needed
for this preparation. A passing plumbing test never promotes a strategy.

## Attribution helper interface

`research_core.attribution` operates on supplied as-of evidence, without reading
market data, deciding trades or opening research outputs. This interface makes the
proposed arithmetic testable; it does not turn the draft's normalization or warning
reference into an approved acceptance policy.

`mark_attempt_pnl(ledger, raw_marks)` consumes a `replay_ledger` snapshot of only
the event prefix through the checkpoint being measured. Closed attempts contribute
net cash flow plus unpaid entitlements; open attempts also contribute remaining
shares at explicit raw marks. Missing marks fail. Do not repeatedly feed a final
ledger with different historical prices: that would put future cash flows into
the past. The function does not infer a hit from unrealized PnL.

`non_hit_attribution(attempts, checkpoints, initial_equity=..., span=20)` consumes:

- attempts with unique IDs, explicit `hit` (`true`, `false`, or `null`),
  `entry_index`, and `exit_index` (`null` for an open attempt); a claimed hit also
  supplies `captured_pnl_twd`, derived from the settled attempt's actual net cash
  flow, not its marked gain or unpaid entitlement;
- a chronological checkpoint sequence with explicit ISO date/time, actual account
  `equity` and the `attempt_pnl` mapping, including zeros before each attempt enters;
- initial account equity for the fixed-initial-capital normalization, separately
  from each window's observed start equity. The production owner account is NT$2m;
  smaller synthetic fixtures do not change that requirement.

Each entry must have its own checkpoint index in strictly increasing actual
execution order. Index `entry_index - 1` must be the valuation immediately before
that entry, not yesterday's close or an earlier snapshot of the day's cash. Equal
timestamps are allowed; indices preserve the execution ordering. The adapter must
also supply every session close and the required event checkpoints. Index/date
validation does not certify the provenance or sampling completeness of marks.

A classified attempt must be closed. Closed-but-unclassified attempts can remain
`hit=null` while the observation/settlement policy is unresolved. Every before-entry
PnL supplied must be zero; every known after-exit economic PnL must remain unchanged
under the explicit entitlement protocol (absolute comparison tolerance `1e-8` TWD,
no relative tolerance). A legacy delayed cash payment without an
entitlement cannot silently become an ex-date economic accrual in this interface.

A claimed hit requires positive captured PnL, positive stable closed economic PnL,
and captured PnL no larger than economic PnL. Contradictory values fail validation.
Missing captured/closed evidence makes the claimed hit unresolved in the diagnostic
and records the reason; it cannot break a non-hit run as a verified hit. Supplied
labels are not mutated. This is a necessary consistency check, not certification
of the still-pending large-return threshold or the source cash-flow evidence.

Missing PnL keys/`null` for any attempt inside a measured path make its metrics
unavailable with a reason, including missing PnL on a hit excluded from the sum.
When all PnL values and account equity are present, require
`equity = initial_equity + sum(all attempt_pnl)` within `1e-8` TWD absolute
tolerance. This interface assumes no external deposits/withdrawals and a complete
attempt inventory; a different account convention needs an explicit contract.
Missing equity leaves computable TWD attribution visible but partial, and prevents
a complete worst-window result. Missing values never become zero.
A finite zero account equity is a legitimate
observed total loss, but zero/unknown start equity cannot be a ratio denominator.
In that case available TWD contributions remain visible and start-equity ratios
remain unavailable. The helper does not manufacture a favourable shorter path by
dropping checkpoints.

Outputs separate whole-study known non-hit attribution, unclassified-attempt
attribution, maximal known non-hit runs, every overlapping `span`-attempt window,
and window-summary completeness. An unknown label that could conceal a worst
window prevents a complete worst-window result. Known subsets are labelled partial;
open/unclassified losses remain separately visible, never labelled completed misses.
No eligible window is insufficient support or no eligible window, not a zero-loss
pass. Returned TWD metrics distinguish signed terminal contribution, nonnegative
worst loss from zero and nonnegative peak-to-trough erosion. Fractions use fixed
start or initial equity, never a compounded fictional misses-only account.

The helper has no pass/fail threshold, choice of 50% versus 100% hit, observation
horizon, statistical significance test, automatic period advance, executable
counterfactual or market-adapter certification. Those remain prerequisites for a
future credible strategy claim, not conclusions from its unit tests.

## Recorded-prefix attribution input bridge

`research_core.attribution_inputs.build_attribution_inputs` connects recorded
executions and explicit valuations to the reducer above. This is reference
accounting integration, not a new trading engine or a policy acceptance gate.
It takes `initial_cash`, the complete supplied `events`, `checkpoints` containing
`date`, `event_count` and `raw_marks`, explicit attempt-ID `classifications`, and
a positive position limit (default five).

Checkpoint counts start at zero, end at the supplied event count, and advance
by zero or one. Every event therefore has an after-event valuation; additional
session-close valuations may repeat the count. Dates must be timezone-aware and
ordered. A checkpoint cannot precede its last included event or pass its next
unconsumed event; the first post-event checkpoint matches the event timestamp.
Each new flat-to-flat buy also needs a same-timestamp immediately preceding
pre-event valuation, so the window denominator is not yesterday's equity.
Equal timestamps retain explicit event/checkpoint ordering.

Each valuation uses only its `replay_ledger` prefix, `mark_equity` and
`mark_attempt_pnl`. Final attempt inventory supplies IDs and ordering, not past
cash flows. Zeros are filled only before that attempt's observed first entry;
missing marks for an existing holding fail. Entries and flat exits derive from
the ledger; adds, splits and partial sales do not start/end another attempt.
No independent trade-pairing or PnL calculation is introduced. Repeated marks
of the same prefix reuse one replay; this reference still replays successive
prefixes and is not claimed to be an optimized full-history runner.

The result `attribution-inputs.v1` supplies the reducer's attempts, checkpoints
and initial equity. Closed `captured_pnl_twd` is final-as-of settled cash flow,
not economic PnL including unpaid entitlements. Legacy unlinked dividends are
rejected; explicit old entitlements remain attributed correctly after re-entry.
Classifications must explicitly cover every attempt; open attempts must remain
unknown. Neither the bridge nor those labels prove the owner's still-unfinalized
large-return threshold, horizon or loss budget. The reducer retains its own
consistency checks; callers must not treat merely building its inputs as passing
the non-hit requirement.

The evidence basis is `caller_supplied_complete_recorded_events_and_marks`.
Chronology checks cannot establish that all real sessions/events were supplied,
that marks are executable/PIT, or that a final classification was known earlier.
The output is ex-post attribution and must not be used as a strategy's historical
decision input. Attempt IDs remain specific to the supplied event stream, not
stable omitted/delayed signal identities. No market data or candidate outcome
was read to implement these rules.

The end-to-end hand calculation starts at NT$2m, records ten NT$20,000 losses
and ten NT$5,000 small wins as twenty non-hits, with one concurrent NT$500,000
hit. The reconstructed final account is NT$2.35m, while non-hit terminal
contribution remains -NT$150,000 and interim erosion reaches NT$200,000 (10%
of the fixed NT$2m start). A separate fixture verifies partial exits, a split,
and an old dividend paid after same-stock re-entry. These are invented test
transactions with explicit classifications, not market results or approved gates.

## Execution integration boundary observed during this stage

The other line's `execution_model.execute` remains measurement evidence to review,
not automatically this goal's approved execution model. A fixed-number probe of
its current code uses previous close 100 and its own declared limits `(110, 90)`:
buy open 109.95 plus 50 bps returns a filled price `110.49974999999999`; sell open
90.05 minus 50 bps returns `89.59975`. Thus its recorded adverse fill can cross its
own declared bound because the limit check occurs before the slippage adjustment.
This is a code-level synthetic observation, not market data or a candidate verdict.

Before integration, decide whether slippage is an execution price or a separately
identified conservative cash penalty, and enforce the corresponding rules. Also
verify the actual reference-price/tick/venue rules from official sources; copying
the current `previous_close * 1.10` assumption is not such verification. The
optional odd-lot branch currently uses the same regular-session open, so it cannot
serve as evidence for the owner's prohibition on idealized odd-lot open fills.
No files belonging to that study were edited and no market result was opened for
this check. Coordinate the correction before using its output for promotion.

The [execution contract draft](research-execution-contract.md) records the verified
stock price grid, daily-reference exceptions and separate odd-lot sessions. The
shared price-feasibility helper prevents impossible modeled prices; it does not
replace the pending-order, venue/capacity, cash-reservation and checkpoint adapter.
Do not report a feasible adjusted price as an observed opening-auction fill.
