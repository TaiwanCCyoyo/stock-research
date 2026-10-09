# Executable account contract — working draft

Status: **design and synthetic verification only, 2026-09-09**. This is not a
sealed candidate, exchange simulator, or approval to open a new sample. Use the
[owner contract](research-owner-contract.md) and
[measurement contract](research-measurement-contract.md). Historical task models,
missions and outputs retain their identities; this document does not revise them.

## Verified rule boundaries

Sources below were checked on 2026-09-09. Current rules alone do not establish
historical applicability. The execution adapter must identify the security,
market, session and effective rule regime for each date, not apply an equity rule
to an ETF, emerging-board stock or an unknown historical listing state.

Ordinary TWSE and TPEx stocks use these price bands (TWD per share). This is a
price grid, not a fee schedule. [TWSE Article 62](https://twse-regulation.twse.com.tw/tw/law/DOC01.aspx?FLCODE=FL007304&FLNO=62),
[TPEx trading system](https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html).

| Price              | Tick |
| ------------------ | ---- |
| below 10           | 0.01 |
| 10 to below 50     | 0.05 |
| 50 to below 100    | 0.10 |
| 100 to below 500   | 0.50 |
| 500 to below 1,000 | 1    |
| 1,000 and above    | 5    |

The normal TWSE percentage limit uses the day's auction reference, with exceptions;
it is not universally the previous raw close. There are minimum-tick and new-listing
exceptions. The exchange's example with reference 40.60 gives upper 44.65 and lower
36.55, rounding inward on the price grid. A two-decimal rounding of the percentage
products gives the wrong bounds. [TWSE Article 63](https://twse-regulation.twse.com.tw/tw/law/DOC01.aspx?FLCODE=FL007304&FLNO=63),
[TWSE trading explanation](https://www.twse.com.tw/zh/products/system/trading.html).

Some corporate actions require different upper- and lower-bound calculation bases.
Consequently, even one adjusted reference is not a universal repair. Consume
authoritative daily limits, or a separately verified date-specific derivation with
its full inputs; never fall back silently to yesterday's close. [TWSE Article 67](https://twse-regulation.twse.com.tw/tw/law/DOC01.aspx?FLCODE=FL007304&FLNO=67).

Intraday odd-lot trading began on 2020-10-26; after-hours odd-lot trading already
existed. Intraday orders start at 09:00 but the first matching is 09:10; after-hours
orders are 13:40–14:30 with one 14:30 auction. Odd-lot orders are 1–999 shares,
limit orders valid for the day; unfilled intraday orders do not automatically
carry to the after-hours venue. Thus an ordinary daily open is not an observed
odd-lot execution. [TWSE odd-lot mechanism](https://accessibility.twse.com.tw/zh/products/system/intraday-odd-trading.html).

The intraday odd-lot matching interval changed from three minutes to one minute
on 2022-12-19 and to five seconds on 2024-12-02. The 2023-11-27 five-second change
concerned indicative information, not matching. Do not apply today's timetable to
the entire history. [TWSE change history](https://www.twse.com.tw/market_insights/zh/preview/8a8216d6933460a401936cfbd7b301ba),
[TPEx 2022 notice](https://www.tpex.org.tw/storage/eb_data/11108/1110064404.html),
[TPEx 2024 notice](https://www.tpex.org.tw/storage/eb_data/11303/11300555841.html).
The TPEx notices were available in official search-index excerpts; direct opens
returned HTTP 403. This is not evidence that local research downloads are blocked.

## Shared price feasibility component

`research_core.execution_prices` provides a deliberately narrow building block:

- `stock_tick` and `round_stock_price`: decimal stock-grid arithmetic, with explicit
  up/down rounding, including band boundaries;
- `PriceLimits(lower, upper)`: explicit supplied on-grid bounds. `upper=None`
  represents a caller-verified absence of an upper limit, not missing evidence;
- `adverse_stock_price(side=..., observed_price=..., slippage_bps=..., limits=...)`:
  a modeled adverse price, rounded up for buys and down for sells. Missing
  observations or limits produce an unavailable candidate and reason. Invalid
  observations fail validation. A modeled price outside the supplied bounds is
  unavailable, not capped to a convenient fill.

Neither a percentage-limit formula nor an implicit slippage default is provided.
Bounds are explicit to preserve special references and historical regimes. A
`price_feasible` result means **only that the modeled price fits the supplied grid
and bounds**. It does not certify an observation's source, venue, liquidity,
timestamp, order eligibility or actual execution. Nonzero adverse price adjustment
is not an observed opening-auction print and must never be reported as one.

Fixed-number examples: with supplied bounds 90–110, buy observation 109.50 plus
50 bps rounds above the upper bound and has no feasible candidate. Sell observation
90.10 minus 50 bps similarly falls below the lower bound. Observation 40.60 with
10 bps produces modeled buy 40.65 and sell 40.55. These are synthetic calculations,
not historical trades or evidence that orders would fill.

A print at a price limit does not by itself prove zero opposing liquidity. The
price helper permits equality with valid bounds. Any conservative no-fill-at-limit
assumption belongs in a named execution policy, not an invented exchange fact.
Likewise, rejecting infeasible modeled prices is not proof that the resulting
strategy is a performance lower bound: changed cash and holdings change later orders.

## Smallest complete integration still required

Reuse the existing queued-next-open design from
`tasks/20260908-executable-fills/candidates/rotation_ranker_v14.py`, without editing
that already-run card. Separate its decision recorder, execution resolution and
raw-close valuation. Do not treat its same-close replication as validation of the
new execution path. The new adapter needs the following explicit interfaces before
any new candidate evaluation:

1. **Order intent:** stable signal/order ID, code, side, decision time, submission
   time, venue, fixed limit and requested quantity, earliest eligible session,
   expiry and cancellation/replacement policy. The strategy sees only currently
   available data. A later opening gap cannot retroactively resize an already
   submitted order using the future print.
2. **Pre-submission resources:** cash/buying power actually usable at that time,
   reserved maximum cash including fees, shares reserved for sales, and five-stock
   capacity. An expected exit is not an already freed slot. Corporate-action
   receivables are not spendable. Broker settlement/buying-power assumptions must
   be explicit; a cash-ledger replay does not establish broker credit availability.
3. **Execution observation:** code/date/market/venue, actual observation time and
   source identity, valid daily bounds, price, quantity evidence and status. Keep
   missing data separate from a known suspension, known no-trade or failed order.
   Daily total volume cannot stand in for opening-auction capacity. A mixed
   1,234-share intent requires distinct regular/odd-lot children, not one ordinary
   opening-price fill. No observed odd-lot price means unavailable evidence, not
   permission to borrow the ordinary price.
4. **Fill and cash effects:** explicit partial/unfilled quantities, fill time,
   valid price, fees/minimums/rounding, tax and any separately identified modeled
   cash penalty. Charge each cost once in ledger totals. A price adjustment and
   a cash penalty must not duplicate the same slippage assumption. A hypothetical
   adjusted price remains modeled, not an actual auction observation.
5. **Event/checkpoint adapter:** fills and corporate actions feed shared replay;
   each actual entry has its own immediately-before/after valuation checkpoint,
   plus session closes. Derive as-of attempt PnL through `mark_attempt_pnl`, reconcile
   it with equity, and preserve open/unknown classifications for non-hit attribution.
6. **Counterfactual dispatcher:** omission/delay/suppressed-entry identities operate
   on actionable intents, not completed trades. Rerun the strategy and reservations
   under the frozen scenario. Do not open or rank fresh outcomes to choose the
   sampling rule, hit threshold or loss budget.

In particular, processing all sells before all buys in a loop is not evidence that
a manual trader can observe a 09:00 sell, then submit a replacement buy for that
same auction. Pre-submitted independent orders and a later contingent replacement
are different policies. The integration must use one causally possible policy;
otherwise it may borrow cash/slots from fills not yet known. This is a model-design
constraint, not a newly imposed owner preference for a particular extra delay.

Required small end-to-end fixtures: a gap that exceeds reserved cash, a blocked
exit with five occupied slots, a partially filled order, separate regular and
odd-lot execution times/prices, a missing opening observation, an old dividend paid
after re-entry, and an omitted/delayed intent changing subsequent cash allocation.
Use fixed events and hand calculations. Do not build a new parameter grid or UI
to test these mechanics, and do not add new acceptance cutoffs.

## One-auction synthetic integration

`research_core.auction` resolves one explicitly identified auction batch, not an entire
strategy. Its modeled policy is strict pre-submission reservation: ordered intents
reserve their full limit-price buy budget, sale shares and any possible sale-cost
shortfall before seeing auction observations. It does not reuse another order's
subsequent sale proceeds, cheaper execution or failure to admit a previously
unaffordable order in the same batch. New-symbol capacity is reserved as well;
an expected sale cannot free a slot at submission time. This is a deliberately
specified causal policy for prospective testing, not an exchange rule or a claim
that the owner approved whole-lot-only trading.

Currency is integer TWD cents with exact rational cost rates. Each cost's rounding
unit and rule must be supplied, including minimum commission and a separately
identified execution-stress cash penalty. Actual price comes from the supplied
auction observation and is checked on the stock grid and against the order limit
and known daily bounds; it is never replaced with a non-observed adverse price.
Cost sensitivity does not prove queue execution. Explicit allocated-capacity
evidence/assumptions remain necessary and must be recorded, not inferred from
daily total volume or the mere presence of an opening print.

One intent targets one auction and one venue. Regular and odd-lot children are
separate, with their own observation, priority and minimum costs. A partial fill
does not imply its residual was canceled. The result retains pending order IDs
for accepted partial/unfilled orders, except an order known invalid at the supplied
price bounds. An input state with unresolved orders cannot enter another batch.
Known post-auction holdings can still reconcile with the recorded fills, but
`continuation_allowed` remains false until order-lifecycle reconciliation resolves
fills/cancellations and reservations (the bounded helper below now supports this).
Missing execution evidence instead means the
holdings themselves are unknown: `state_complete=false` and `next_state=null`.
These are different reasons not to continue. This component never manufactures
an immediate manual cancellation of an exchange ROD order. Known no-trade/suspension
and unavailable observation/capacity remain distinct results.

Sale-cost reservation must cover small partial fills, not merely the full
requested sale: a full order can have positive proceeds while its tiny partial
loses money to a minimum charge. The shared ledger now accepts zero/negative-net
sales only with reconciled `gross_proceeds` and `cost_total`, and enough cash for
any net debit. This does not permit short selling or spending dividend receivables.

For the bounded cost schedule, commission is the maximum of the minimum charge
and the rounded proportional commission. Tax (sales only) and the separate cash
penalty are rounded independently. Rates are nonnegative exact fractions with
combined sale rate `R < 1`; each rounding rule/unit is explicit. A safe partial-sale
reserve uses `ceil(max(0, C - (1-R) * unit * sell_limit_cents))`, where `unit` is
one share or 1,000 regular shares. `C` is the maximum of minimum commission and
commission rounding-error bound, plus tax and penalty rounding-error bounds.
For a nonzero rate, ceil/half-up use one rounding quantum as a conservative error
bound; floor uses zero. Then costs are at most `R * gross + C`, and any valid
partial's gross is at least `unit * sell_limit_cents`. This is a reservation
upper bound, not an extra charged fee or an asserted broker rule.

The batch result exposes each intent's admission/reservation, per-auction
disposition, actual filled quantity, cost components and evidence IDs. Its
ending cash/holdings must reconcile with replaying the emitted fills when execution
evidence is complete. Input `cash_basis` is explicit; after any fill the returned
cash is labelled `trade_date_cash`, never newly certified as settled bank cash.
The label does not establish that a particular broker makes it available. Source
timestamps, the trading calendar, historical venue eligibility, cross-batch
reservations, broker settlement/buying-power rules and full omission/delay strategy
reruns still need their own integration; a passing batch fixture is not that proof.
In particular, `state_complete` describes supplied model evidence, not independent
certification that hypothetical historical orders really filled. Allocated-capacity
assumptions and the cost schedule still need prospective justification and sealing.

### Simultaneous cross-market reservation

`research_core.auction.resolve_auction_cohort` applies the same shared resolver
to a nonempty ordered sequence of `RoutedOrder(order, batch, costs)`. TWSE and
TPEx requests with the same submission time, auction time and venue reserve one
account's cash, sale shares and position capacity before either market's results
are processed. Later sale proceeds, lower fill prices or a rejected/unfilled
first-market order cannot retroactively admit another request. Input order is
the declared priority, not an inferred exchange sequence.

Each session ID identifies exactly one batch, each exchange/venue one session,
and each code one routed session. Quotes use `(session_id, code)` keys; capacity,
source evidence, original session IDs and per-route fee schedules remain distinct.
Unknown sessions, duplicate order IDs, opposite sides for a name, and mixed
submission/auction times fail validation. The route is caller-supplied evidence,
not verified historical market membership. Persist these routes with the run;
the resolver does not certify their source or replace them with a fictitious
combined exchange. The old single-batch API uses the same reservation/fill core,
including its explicit empty-batch clock and validation.

In the hand-calculable two-market fixture, TWD 1m cannot reserve both 1,000 A
shares at a TWD 600 limit and 1,000 B shares at a TWD 400 limit when each child
costs at least TWD 20. A later A fill at TWD 500 leaves enough cash to have bought
B, but B remains rejected because that money was unavailable at reservation.
Reversing declared priority fills B instead. Separate cases cover cross-market
sale proceeds, all five occupied slots, route-specific minimum fees, missing
evidence and shared capacity among same-session children.

This closes simultaneous initial-auction reservation only. Different-time regular
and odd-lot sessions must not be put in one cohort. Partial fills and unfilled
orders with unresolved residuals remain pending; orders outside supplied daily
bounds remain terminal, as in the single-batch API. Unknown execution still
prevents a complete account. Use the cohort lifecycle adapter below instead of
re-resolving each market separately, which would repeat reservations against
different cash states. Inter-session reservations and a full chronological
strategy runner are still required before claiming a complete stress run.
These synthetic checks neither select a candidate nor establish real fill capacity.

## Same-day residual-order reconciliation

### Shared cross-market lifecycle

`research_core.order_lifecycle.reconcile_cohort_lifecycle` resolves the simultaneous
cohort exactly once, then applies the same residual-report core as the single-batch
API. It takes one explicit common expiry and as-of cutoff on the auction date;
these are caller inputs, not inferred exchange rules. Initial admission and
reservations stay fixed. Later fills use the originating order's fee schedule,
session identity and price bounds; cumulative costs are tracked per child, so
neither a different market's rate nor another minimum fee is silently applied.

Reports form one globally ordered stream with unique IDs and sequence numbers.
An unavailable report that interrupts the visible prefix prevents a complete
continuation state even if another market's terminal is already visible. Missing
initial execution cannot be repaired by terminal reports. An initially rejected
request is not readmitted after another order fills or is canceled. As with the
single-batch helper, no external orders or corporate actions may interleave
inside this exclusive reconciliation interval. Once all residuals are reconciled,
the resulting account may feed a later session, not an already-submitted auction.

A synthetic end-to-end case starts with TWD 2m: 09:00 fills buy 1,000 A at 100
and 1,000 B at 200, with respective minimum fees 20 and 30. A further 1,000 A
fills at 101 at 09:02, B's remaining quantity is canceled at 09:03, and A's full
fill is confirmed at 09:04. Cash is TWD 1,598,950; the later A fill charges no
second minimum. Only then does a separate prior-close 250-share A instruction
enter the 09:05 submission/09:10 odd-lot auction at its own price 102 and minimum
fee 20. Cash becomes TWD 1,573,430, positions A 2,250 and B 1,000. Raw closes
103 and 202 yield equity TWD 2,007,180, reconciled through both shared ledger and
decision snapshot. At a 09:03 cutoff, or with B's terminal unavailable until
09:06, no complete account can seed the 09:05 submission.

This demonstrates chronological report-to-next-venue-to-close arithmetic using
supplied synthetic observations. It does not prove those cancellation timings,
allocated capacities or bank buying power in historical trading, and it does not
implement the complete missed-signal/delay strategy dispatcher.

### Single-batch API and common report rules

`research_core.order_lifecycle.reconcile_order_lifecycle` takes the original
account, intents, quotes and batch plus an explicit expiry, as-of time and ordered
fill/terminal reports. It resolves the initial auction internally, not from an
arbitrary caller-constructed result. This is a bounded pure adapter: **no other
orders, corporate actions or cash movements may be interleaved in that interval**.
The caller establishes that exclusivity and complete report coverage. There is
no market-data lookup, broker integration or inference of a missing report.

All event times and the as-of boundary are on the initial auction's date, with
aware +08:00 timestamps. Report sequence is explicitly increasing, event time
nondecreasing, and report IDs unique. Later fills occur strictly after the initial
auction and no later than the supplied expiry; a fill at expiry must precede its
terminal report in the explicit sequence. The sole after-hours odd-lot auction
has no later same-day fills in this model. Expiry is an input, not a hardcoded
universal closing time or evidence that an exchange session actually occurred.

Each initially pending child needs one terminal report. `FILLED` reconciles to
the full requested quantity; `CANCELLED` and `EXPIRED` reconcile to a smaller
cumulative quantity. The modeled `REJECTED` terminal requires zero fills.
`EXPIRED` occurs at the supplied expiry. No terminal can erase an earlier fill;
no fill can follow a terminal for the same child. Duplicate IDs, overfills,
conflicting daily bounds, invalid grid/venue quantities or violated order limits
are errors, not zero fills. Daily bounds must remain consistent for each code
across all visible reports, including when the initial quote had no bounds.

A report's state-dependent content cannot affect the known state before its
`available_at`: overfill, cross-report bounds and terminal-quantity reconciliation
apply only to the available causal prefix. Malformed packet structure (types,
duplicate report IDs or unordered timestamps/sequences) is rejected independently
of as-of time. A missing earlier report blocks reconstruction of the dependent
later prefix. Passing the
expiry time alone does not manufacture an expiry confirmation. Unknown initial
auction evidence likewise cannot be repaired by attaching later terminals to
its diagnostic fills; correct the missing initial evidence first. The helper
returns no next executable state until all residuals are explicitly reconciled.
Cancelling a sell releases its reservation, not the held shares or occupied slot.

Fees follow an explicit **per-child-order cumulative-notional** model: compute
each component on total filled notional to date, then charge only its increment.
No fill means no minimum charge; subsequent partials do not each incur a new
minimum. Different regular/odd children remain separate fee units. This is a
prospective test policy, not certification of every broker's fee aggregation.
Original per-order cash/share reservations remain constraints, and exact cash
must stay nonnegative after every applied fill. Currency calculations remain
integer cents. Later events retain exact gross/total/price cents and cost
components alongside legacy-compatible TWD replay fields and evidence IDs.

The result separates `initial_result.ledger_events` from `additional_events`:
append each once, after the prior account prefix, to feed shared replay and the
decision bridge. Incomplete-prefix events are diagnostic only, not an executable
account. `evidence_basis=caller_supplied_same_day_reports` does not certify PIT,
source authenticity or report completeness. This adapter does not carry a ROD
order into another day, model replacements or reconcile trade corrections.

Hand-calculable integration fixtures exercise multiple fills with one minimum
charge, partial exit plus cancellation retaining the entry identity/holding age,
and an expiry report unavailable at decision time. In the five-held-stock fixture,
later confirmation of an unfilled sell's expiry still leaves all five holdings;
a sixth-name buy remains rejected by the next batch's capacity check. These
are execution-path tests, not a new candidate or the required full-strategy
missed-signal/delay/best-attempt stress evaluation.

### Chronological counterfactual fixtures

`scripts/tests/test_research_causal_scenarios.py` supplies a small chronological
test harness around the same auction, lifecycle and decision helpers. Its toy
recommendation receives only the current snapshot and current ranked candidate;
it is rerun independently under each arm. There is no production strategy loader
or stress dispatcher in this fixture, and none of its prices are market evidence.

The fixed one-lot entry rule gives different later decisions when the first A
entry is omitted: B becomes affordable, and a distinct later A entry remains
eligible. Filtering the baseline event list produces neither entry. Delaying all
intents by one additional supplied trading-calendar position retains their
original quantity and limit but uses later execution observations. A later B
request is generated under that changed state, then correctly rejected when its
original cash reservation is 40 TWD above available cash. The fixture does not
repair this by looking at B's future fill price. Intents delayed beyond the fixture
horizon remain explicitly outstanding, not labeled expired or silently dropped.

These are hand-calculated causal examples, not omission-rate sampling, best-attempt
ranking, a complete liquidation study or approval of repeat-advice/expiry rules.
The toy retains queued intents unchanged and does not cancel an old intent merely
because a new recommendation exists. Before an actual stress study, finalize that
policy, stable signal identity, omission sampling/aggregation and the pending-
horizon convention in the preregistration. Open positions in these fixtures do
not establish captured hits. No numerical robustness gate is evaluated here.

## Chronological runner over supplied evidence

`research_core.chronology.run_chronology` now moves the chronological loop out
of the toy fixture into a reusable pure runner. It starts from explicitly named
initial cash and `history_start`/`initial_checkpoint_id`, with a caller-declared
complete, ordered `DayFrame` calendar. Each frame separates close observation
time from decision cutoff and declares simultaneous execution windows/routes.
Window, session and generated order IDs are unique within the run. Overlapping
exclusive lifecycle intervals, ambiguous routes and malformed clocks raise
`ChronologyError`; a missing due session is invalid calendar construction, never
permission to find a later available price.

Each invocation calls a decision factory once for a fresh rule. The rule receives
only its current `DecisionSnapshot` and immutable queued, not-yet-submitted
requests. It does not receive future frames, execution observations, a baseline
trade list or a scenario label. This allows a fixed rule to avoid duplicate
unsubmitted entries under delay. The returned prior-close requests have the exact
current decision timestamp and enter the next declared trading-day frame plus
the scenario's explicit extra-day delay, with original quantity and limit intact.
Omitted IDs are recorded before submission, not deleted from completed trades.
The result separately lists matched and unmatched omission targets. By default,
all targets are required. An otherwise finished horizon with unmatched required
targets is `incomplete/unapplied_omission_targets`:
a typo or a recommendation no longer generated cannot certify a fully applied
perturbation. Earlier data/queue incompleteness retains its original stop reason.
This is a perturbation-evidence issue, not a candidate-loss verdict.
An explicit `required_omission_ids` subset permits contingent targets to disappear
after an earlier intervention; all unmatched IDs remain in the result. It does
not certify that arbitrary optional targets were applied. The best-attempt
orchestrator below derives its required anchor before rerunning.

This low-level scenario interface accepts explicit omitted request IDs and the
explicit signal sampler described below; it does not select seeds, the strategy's
signal/retry policy, best-attempt mapping itself, or acceptance gates. The rule's stable cross-scenario
ID semantics still require preregistration and audit: within-run uniqueness alone
does not establish that ordinal IDs identify the same recommendation in reruns.
Already-viewed market periods are not opened by this component.

Corporate providers receive `(since, until, this_run_event_prefix)` and return
explicit completeness, source identity and recorded corporate events. Before
each used submission window and each decision cutoff, the runner admits only
ordered DIVIDEND_ENTITLEMENT/DIVIDEND/SPLIT events within `(since, until]` and
replays the proposed prefix. This includes nontrading overnight records returned
before the next trading cutoff. Entitlements must be derived from that scenario's
holdings, not copied from baseline. Empty execution windows do not request quotes
or advance the exclusive lifecycle cursor; corporate coverage still spans the gap.

Execution providers return session-keyed quotes, per-window ordered reports and
explicit completeness/exclusivity assertions for the selected routed requests.
Quote sessions must correspond to those active routes. Report IDs are unique
across the run; report sequence numbers restart per window. The runner invokes
the shared cohort lifecycle once, immediately replays its fills and reconciles
cash/positions, then admits later corporate events. Source evidence identities may
legitimately recur across intervals; interval records and full execution evidence
are retained. Runner-generated replay labels are not source authentication.

Incomplete corporate/execution evidence, unresolved orders, or missing held marks
stop the run before a later close or decision. Diagnostic fills remain in that
window's lifecycle result; the authoritative event tuple retains only the last
complete prefix. Routed requests of an incomplete window remain visible there,
separately from the still-unprocessed queue. Requests beyond the evaluation horizon
produce `status=incomplete`, not an expired/missed request or a passing stress run.
Conversely, `status=complete` means only the declared horizon and request queue
were processed: open holdings can remain and are not completed captured hits.

The tests reuse the original hand-calculated omission/delay paths and connect the
two-market partial/cancel example through a later odd-lot window and final close.
They also cover scenario-local dividends, post-lifecycle payments, queue-aware
duplicate avoidance, unavailable coverage, missing marks and report identity.
This is not yet a market-data adapter, registered candidate, statistical test or
research acceptance evaluator. Providers and decision factories
are trusted code requiring separate source/PIT review and sealed identities;
the runner is not a sandbox and cannot detect a callback secretly reading future
data or hiding an interleaved event behind a false completeness assertion.
Overlapping active orders across different-time windows remain unsupported by
the exclusive lifecycle contract and may not be silently skipped or counted as
a losing strategy.

## Baseline-ranked complete-attempt suppression

`research_core.attempt_stress.run_best_attempt_stresses` executes its own
unperturbed baseline, then independently reruns each explicit positive target
count from the same `StressInputs`. It does not accept a preconstructed baseline
as evidence. Provider factories and the decision factory are called afresh per
arm; their hidden state, data identity and determinism still require audit.
This is a fixed diagnostic implementation to preregister before use on candidate
results, not approval of an owner gate or permission to inspect a new period.

Shared ledger `cash_rows` now include `attempt_id` for every event. This uses
the existing flat-to-flat accounting: adds, partial fills/exits and splits remain
in one attempt; a linked dividend paid after re-entry still belongs to the old
attempt. The stress inventory uses these links, not a second trade-pairing engine.
Closed attempts rank by economic net PnL in exact cents, descending, with entry
event index breaking ties. Sum original signed trade/payment totals and only
unpaid entitlements; never count a paid dividend twice. Reconcile against shared
ledger economic PnL within `1e-8` TWD absolute tolerance. Unlinked dividends are
invalid, and unpaid amounts remain separately reported; economic contribution
ranking is not a captured-hit classification. Open attempts are listed but not
ranked as completed attempts. Fewer than the requested count returns unavailable,
not a smaller stress, and an incomplete baseline prevents target selection.

Each arm suppresses all baseline BUY request IDs belonging to the selected
complete attempts, including adds and distinct executed child requests. It does
not blacklist the stock, copy baseline sells, filter fills or subtract profits.
Later independent re-entries and alternative allocations are recomputed by the
strategy. The chronologically earliest generated request among the target union
is required to be intercepted: it precedes any omission-induced divergence.
Later target entries/adds can legitimately cease to be generated; report them as
unmatched contingent targets, not as applied omissions or execution failures.
Best-three uses the baseline top-three union in one fresh rerun, not the result
of best-one. Every arm retains its full chronology and incompleteness reason.

Across arms, a reused request ID must keep its code, side, decision timestamp,
exchange and venue. Quantity/limit may change with the recomputed state. This
necessary check cannot prove semantic identity: strategy code must still use
stable recommendation identities, not attempt indices or run-local ordinals.
Never feed baseline rankings into strategy callbacks. Suppression is at original
executed BUY-request identity, not an inferred signal-bundle or entire symbol;
the strategy's repeat-advice/child-request policy still needs prospective review.
This best-attempt service does not select omission samplers, hit thresholds,
statistical tests or promotion verdicts.

Synthetic integration covers a two-buy/partial-exit winner, later same-stock
re-entry, dependent adds that disappear, best-three paths where later target
entries vanish, old paid/unpaid dividends, changed request identities and missing
baseline evidence. These results validate orchestration only, not profitability.

## Fixed-seed signal-bundle omission

`research_core.signals.SignalIdentity` names a stock-specific BUY or SELL advice
with a nonempty `signal_id`, code, side and aware +08:00 `origin_at`. A
`PriorCloseRequest` may carry this identity; every generated request must carry
one in a signal-sampling arm, with matching code/side and origin no later than
the request decision. First sight of a signal must equal its origin decision.
Later children/retries may reuse it only without changing identity. Multiple
requests, venues or retry dates belonging to the same advice share one draw.
An independent re-entry needs a new signal identity; merely using a new child
order ID cannot redraw a missed signal. Strategy-specific rules for renewed
daily advice versus continuation remain to be fixed before candidate evaluation.

`SignalOmission(seed, rate)` requires a nonempty string seed and exact `Fraction`
in [0, 1]. Freeze this serialization as version `stock-signal-omission.v1`:
UTF-8 JSON array `[version, seed, signal_id, code, side, origin_at.isoformat()]`,
`ensure_ascii=False`, separators `(',', ':')`, no whitespace or extra fields.
The SHA-256 digest is interpreted as an unsigned big-endian integer `h`.
Omit exactly when `h * rate.denominator < rate.numerator * 2**256`.
Rate is excluded from the hash; 10% omissions are a subset of 20% omissions for
the same seed and identical signals common to both runs. The finite hash grid
discretizes the nominal probability by less than `2**-256`; no exact finite-path
10%/20% count or formal independent random sampling is claimed. Hashing prevents
draw-order drift, not dishonest signal naming or outcome-based seed selection.

Sampling occurs after request/identity validation and before queue/admission.
The trace retains every unique generated signal and its digest/decision, with
the seed/rate retained by the scenario; all draws are independently recomputable.
Signals later rejected for cash/capacity still count as generated advice. Missing
metadata cannot select a smaller denominator. Explicit request omissions and
sampled omissions retain separate ID sets; a request matching both is omitted
once and appears in both cause sets. `matched_omission_ids` remains explicit-only.

`research_core.signal_stress.run_signal_omission_stresses` runs its own baseline
and each distinct explicit seed/rate configuration independently through fresh
factories and shared inputs. These arms use no additional explicit omissions or
delay. Shared rerun checks validate request and signal identities across the
entire batch, including new signals absent from baseline. The original decision
callback never receives the seed, sampler, baseline ranking or this registry.
Factories/source completeness/semantic identity still require audit.

Each arm reports generated and sampled unique signals, generated and omitted
requests, and the actual sampled/generated signal fraction. A zero denominator
has null fraction. A completed chronology with zero sampled signals reports
`insufficient_perturbation`, not resilience evidence. Missing baseline evidence
prevents all arms; an incomplete arm preserves its partial trace and stop reason.
Different causal arms may generate different inventories: compare nesting only
on common identities, never by assuming their total omission counts are nested.
`observed` means the intervention occurred, not that return/cost/behavior gates
passed. The seed list, multi-seed aggregation, minimum support and numerical
return gates still need preregistration; no seed search or market run occurs here.

## Executed-prefix decision bridge

`research_core.decision.build_decision_snapshot` reconnects recorded executions
to close-based decision inputs without inheriting V14's mutable broker-price map
or its submit-equals-exit holding clock. It does not load market data or select
a strategy. The caller supplies a complete as-of event prefix from an initially
cash-only account, an explicit session-close calendar, and separately named raw
and signal closing observations. It is not an intraday decision interface.

- `initial_cash_cents`, returned cash/receivables/equity, and raw closing prices
  are integer cents. Event TWD totals, sale components and dividend entitlements
  must be cent-integral; no sub-cent value or cash deficit is rounded away to
  make a budget. Exact cash is checked at every event. Shared ledger replay
  remains the source of holdings and attempt membership; final cash/equity also
  reconcile to its float representation within absolute TWD `1e-8`, no relative
  tolerance. This bridge rejects incompatibility rather than replacing ledger
  accounting with a new independent trade-pairing algorithm.
- Cash is explicitly `trade_date_cash`, not broker buying power or newly settled
  money. A later order's permitted budget needs its own recorded broker/model
  assumption. Unpaid entitlements remain equity only. Linked dividends can pay
  after exit/re-entry; legacy unlinked dividend events are not accepted here.
- `execution_complete`, a nonempty `execution_checkpoint_id`, and
  `unresolved_order_ids` are required. Incomplete execution or any unresolved
  order prevents a snapshot. In particular, known diagnostic fills from an
  otherwise unknown auction batch cannot establish a complete subsequent book.
  These inputs are caller assertions; their source/lifecycle verification is
  still required. This function never invents a cancellation or expiry.
- Raw close is `raw_close_cents`; adjusted `signal_close` is a separate finite
  positive Decimal and need not fit the raw stock grid. Observations carry
  source, observed and available timestamps. Only the latest supplied session's
  closes available by the decision are accepted, with no raw/signal substitution
  or stale-price fallback. Every currently held name needs a raw mark. Auction
  prints do not mutate these frozen observations or replace another name's raw
  sizing reference.
- Holdings derive from executed BUY/SELL/SPLIT events. Adds, partial exits and
  share splits preserve the attempt and clock; a flat exit closes it, and a new
  fill from zero begins another. `attempt_id` is the ledger entry-event index,
  stable only for appending to the identical prefix. It is **not** a durable
  signal/order identity across omission or delay reruns.
- `completed_closes` counts supplied session closes at/after the actual first
  buy: an entry before that day's close has age one at the close; an after-hours
  entry has age zero that day. Calendar closes continue to count while a
  position is held, not just dates with a quoted bar. Missing current marks still
  prevent the decision snapshot. This is an explicit descriptive clock, not
  implicit adoption of V8's age convention or an approved hold20 rule. Peak-
  based exits and signal-scale rebasing are not implemented by this bridge.
- The ordered calendar must cover the event dates and end on the decision's
  date; future/unsorted/date-only event inputs fail. History start and the
  caller's calendar ID are explicit. Omitted sessions cannot be discovered
  from a list alone: returned `evidence_basis` is
  `caller_asserted_prefix_and_calendar`, not a certificate of completeness/PIT.
  Holdings and observation mappings are copied and immutable.

`research_core.auction.buy_quantity_for_budget` sizes one BUY child from an
explicit price, budget, venue and cost schedule. It reuses the resolver's exact
minimum/rounding/penalty costs and returns the largest budget-feasible multiple
of 1,000 for regular orders or quantity up to 999 for an odd child. No fill means
no fee, not a negative order size. This does not choose the limit-price policy,
assert future opening price/capacity, certify buying power, or price regular and
odd children at the same print. Using a raw close as a sizing reference does
not guarantee that the eventual limit-price reservation will admit the order.

Hand-calculable fixtures connect a real shared auction result to this snapshot
and the next sizing calculation: a fill in A leaves B's raw-100/signal-50
observation unchanged and its TWD 400,000 zero-cost budget at 4,000 shares.
Other fixtures cover unresolved exits, a batch with one known fill and another
unknown order, re-entry/partial exits/splits, old dividend payment, cent shortfall,
and immutable/future/missing input failures. These are synthetic integration
checks, not an executable market strategy or the full counterfactual dispatcher.

### Pre-submission recorded-event bridge

`research_core.decision.build_execution_account_snapshot` reconstructs the book
at an explicit submission-time cutoff without requiring closing marks or making
a fresh signal decision. Yesterday's close snapshot is not automatically today's
submission account: confirmed intervening dividend receipts or share splits may
change cash or quantities. The caller supplies the complete recorded prefix,
ordered unique trading dates ending on the cutoff date, calendar identity and
execution checkpoint. BUY/SELL dates must belong to that calendar; recorded
corporate events may occur on other dates. Future or unordered events, unresolved
orders and incomplete execution are rejected.

The bridge reuses the close snapshot's exact-cent prefix checks and the shared
ledger's holdings/entitlement accounting. It returns an immutable `AccountState`
plus separate unpaid receivables and evidence metadata. It supplies no marks,
equity valuation, new sizing rule or signal-price adjustment. Cash is still
`trade_date_cash`, not certified settled cash or broker buying power. The caller
must reconcile the complete prefix through the actual submission cutoff; the
snapshot does not discover omitted events or certify bank availability. No fixed
08:55 policy is imposed by this reusable interface.

The synthetic integration fixture starts with TWD 2m and a prior purchase costing
TWD 1,500,020. An unpaid TWD 10,000 entitlement leaves TWD 499,980 cash. The same
prior-close instruction to buy 1,000 B shares at a TWD 500 limit, with a TWD 20
minimum fee, is rejected because its reservation is TWD 40 short. An explicitly
recorded payment at 08:30 permits that identical instruction at 08:55; a supplied
synthetic 09:00 fill leaves TWD 9,960. A payment after the cutoff cannot finance
it. Separate fixtures verify stock splits without fabricated cash, duplicate
entitlement rejection, nontrading corporate events and a cash-only initial book.

These tests establish recorded-event-to-auction arithmetic, not real payment
timing, queue allocation or a complete manual strategy. MOPS announcement
projection is not connected directly to cash events: distribution identity,
conditional/revised dates and actual receipt or a prospectively approved modeled
payment rule still need adjudication. Duplicate-ID rejection does not itself
identify two distinct announcements about the same distribution.

## Data inspection boundary

Read-only SQLite schema inspection on 2026-09-09 verified `limit_up_price`,
`limit_down_price` and `auction_base_price` in the local `corporate_actions` table.
That establishes reusable fields, not complete coverage or PIT certification.
The local `official_daily_price` table has ordinary OHLCV, value/transaction counts,
raw JSON and fetch metadata, but no normalized daily-limit, session-specific
odd-lot price/time or opening-auction capacity columns. Historical TPEx raw layout
labels for next-day limits are not normalized daily-limit evidence.

The corporate-action table and dividend view have `ex_date` but no payment-date
column. A read-only distinct top-level-key query across existing
`corporate_actions.raw_fields_json` likewise found no payment-date key. It did
not inspect linked detail pages or every other local artifact, so it does not
establish that payment dates cannot be obtained. The missing usable payment timing
prevents treating accrued dividends as known spendable cash or captured profit.
These are evidence-availability findings, not proved downloader bugs. A bounded
local handoff to Claude records the exact probes and asks first about reuse/source
availability; it does not request blind full-history downloads. Never overwrite
cache data during this stage.

If a required source is genuinely missing for the registered design, record the
exact local check and affected field/period. Under the owner's 2026-09-09 acquisition
authorization, Codex may investigate and repair the gap directly, following the
acquisition skill and data-protection rules; a reproducible `.tmp` request is needed
when external assistance is required, not as a mandatory Claude gate. Do not solve
a missing-evidence problem by labeling a different market
price as the required one, and do not call an unimplemented adapter a download bug.

### Source-readiness qualification — 2026-09-09

The local Claude handback `claude-data-evidence-handback-20260909.md` identifies
usable raw fields and gaps; it is not certification of historical execution.
Its follow-up is `.tmp/codex-execution-evidence-followup-20260909.md`.
The acquisition skill's measured-source comparison rule governs that handoff:
retain observed values and unresolved differences before defining a normalizer.

- A 09:01 minute bar can supply a candidate first-trade price, not proof of a
  literal 09:00 auction or its capacity. Missing bars do not establish no trade.
  [Shioaji documents historical ticks separately from minute bars](https://sinotrade.github.io/tutor/market_data/historical/).
  This identifies a source to check, not verified account access, coverage,
  auction identification or allocated fill capacity. Its `tick_type` denotes
  inside/outside trading, not auction membership.
- [TWSE lists intraday odd-lot data products](https://eshop.twse.com.tw/zh/news/detail/0000000076a82f740176b1c8e86d0029),
  including a first-trade price. That announcement does not establish the first
  execution timestamp, first-auction volume, historical coverage or free access.
  Neither a daily first-trade price nor after-hours odd-lot data certifies a
  first intraday auction fill. No purchase or subscription has been authorized.
- TPEx previous-row next-day limits need source-specific effective-date
  reconciliation before normalization. Neither unconditional shifting to the
  next quote nor unconditional discarding after a cancelled session is approved.
  [TWSE's disaster FAQ](https://www.twse.com.tw/zh/about/suspended_faq.html) describes
  carry-forward treatment for affected ex-right/dividend prices; it is not by
  itself a ruling on the two TPEx discrepancies in the handback. Reconcile each
  market's calendar, event changes and published effective dates. Sentinel
  examples from ETFs do not establish a universal pure-stock decoder.
- A read-only count at submodule `32c1d916` found 10,334 TPEx and 13,854 TWSE
  cash-dividend-view rows: all have `cash_dividend_estimate`, none have
  `cash_per_share`. Existing source code derives the TWSE pure-ex-dividend
  estimate but reads TPEx's published cash-dividend field. The loader assigns
  these estimates to `ex_date`; this is not payment evidence or investor-net
  cash. Published payment dates, actual personal bank credits and an explicitly
  modeled payment rule remain distinct. An unsuccessful parameter guess does
  not prove that a MOPS payment-date source exists or is unavailable.

These are readiness restrictions, not a new numerical strategy verdict. No
historical market rerun, provider login, backfill, data rewrite or daily-retention
activation accompanied this qualification. The owner's later 2026-09-09 authorization
allows Codex to handle bounded source discovery and acquisition directly;
any later model approximation must be disclosed and fixed before evaluation,
not silently substituted for missing evidence. Synthetic execution work can
continue, but it cannot certify the missing historical inputs.

### Announced-payment source obtained — 2026-09-09

A later bounded Codex probe obtained MOPS `t108sb19` list and
`t108sb19_detail` responses for the two existing 6509/5511 discrepancy cases.
The details explicitly supply announced payment dates even when the list's revised
payment-date column is `無`. See [source evidence and raw hashes](research-mops-source-evidence.md).
This moves announced-payment acquisition from source-unknown to two verified samples,
not to a completed adapter or complete coverage. Displayed announcement dates differ
from detail lookup keys; neither those keys nor the current response timestamp is
certified historical availability. Actual credited cash, revision completeness and
exchange-session reconciliation remain separate requirements. Existing dividend
data and historical results were not rewritten.

## Legacy V14 reuse boundary — synthetic audit 2026-09-09

This is a prospective integration restriction, not a replacement verdict for
`tasks/20260908-executable-fills/`. The original mission, code and results remain
unchanged. Audited source version: parent commit `9fcb658` (V14 last modified in
`8372905`). No market backtest or new period was opened for this audit.

Two hand-calculable probes used the production `RotationRankerV14.on_bar` and
`Broker`, replacing only `_load_ranking` with a no-op and supplying synthetic
rankings. Initial cash was TWD 2m, five slots, zero fee/tax for transparent
arithmetic, rank exit 30. Zero fixture costs are not the research cost schedule.

1. **Settlement destroys the raw sizing-price map.** Set A and B raw close/open
   to 100, B signal close to 50, and B to the top rank. With no pending fill,
   the TWD 400,000 slot requests 4,000 B shares. With a pending buy of 1,000 A
   shares settled first at 100, the same close decision requests **8,000 B
   shares**. `_settle` calls `broker.set_execution_prices({code: fill.price})`;
   that setter replaces the whole map. B therefore falls back to signal close
   in V5's `equal_notional_quantity`. The engine initially supplied raw closes
   but the decision phase does not restore them after settlement. This affects
   even zero-slippage arms. The close-mode anchor bypasses this path, so matching
   aggregate return/buy count in that mode cannot validate it.
2. **An unfilled exit resets the holding clock.** Begin holding 1,000 A at 100
   with `bars_held[A]=20`, `min_hold_bars=20`, and A rank 31. At the first close,
   inherited V8 queues the sale through `_OrderRecorder`, then removes age/peak
   before any fill. At the next open of 90 against previous close 100, the
   legacy model rejects the sale as `limit_down`. A remains held, but the next
   close records age **1** and queues no rank exit. Rankings stay unchanged.
   A missing quote similarly cannot certify a completed sale. Future adapters
   must distinguish order intent from fills and must not reset a held attempt's
   age/peak merely because an exit was submitted. This is a concrete blocker to
   directly using V14 for the report's proposed hold20 comparison; its numerical
   impact on the published hold0 runs has not been measured.

These are source-level synthetic counterexamples, not estimates of the market
return correction. The local reproducible probe is
`.tmp/probe-v14-integration-20260909.py`; command
`uv run --no-sync python .tmp/probe-v14-integration-20260909.py` exited 0 and
asserted both results. Its full input construction is described above so an
ignored local probe is not the sole specification. The source files were not
patched. A new adapter must keep distinct signal, sizing, fill and valuation
prices, and update actual-holding state from fills. Test the settlement-to-next-
decision path, not only a free function given an already-selected opening price.

Evidence inventory found 29 local main results (two anchors, three baselines,
24 arm cells) and 24 diagnostic sidecars; tracked aggregates also contain all
24 cells. This is artifact completeness, not independently reproduced execution.
The seven test functions do not include the mission's T+2 order-expiry case;
the nominal next-open test checks a supplied price and cost, not chronological
strategy execution. `run_fills.py` does not enforce the stated anchor/test gate
before dispatching other jobs, and `--skip-existing` checks existence rather
than input identity. No historical execution ordering is inferred from that
omission. The result's identity fields are path descriptions, not hashes of all
consumed inputs/runtime. Do not certify immutable preregistration or verified
reuse from this envelope alone.

The report's claim that few rejected orders imply negligible return impact is
not established: fill changes affect shared cash, slots and subsequent decisions.
Nor is ideal odd-lot pricing a proved upper bound on an adaptive portfolio's
return. More friction need not monotonically lower the eventual portfolio result.
For example, preventing one losing entry may leave cash for another entry; this
does not make friction desirable, but defeats a general monotonicity claim.
Thus neither the strict model's future verdict nor a causal decomposition into
overnight gaps versus turnover follows from the old table. Its reported sharp
degradation remains an exploratory warning, not a corrected executable estimate.
Subtracting average raw/signal-price offsets across different trade sets also
does not prove that the adjustment offsets cancel; that needs matched events
and compatible price units. The raw-price gap diagnostic is a separate lead,
not an independent replication of full-account execution or a causal verdict.

The report's unfilled-order denominator also mixes buy counts with both-side
nonfills. The recorded arm-A holdout zero-bps sidecar has 1,352 filled orders and
335 unfilled orders: 330 `rounded_to_zero` events are 330/1,687 (about 19.6%) of
those total resolved orders, not about one third. A buy-only rate needs side-
specific order evidence. These counters are not a complete real order-lifecycle
measure. The promised 20-attempt diagnostic is absent from the analyzer/output;
do not substitute zero or the owner's still-unfinalized non-hit acceptance rule.

Next research use: preserve this card as already-viewed exploratory evidence,
do not run its proposed hold20 extension through unchanged V14, and require
synthetic integration correctness plus data and owner-contract readiness before
sealing a new bounded comparison. A hold20 hypothesis is not disproved by this
audit and is not a selected or approved strategy.

### Later V14 correction and reuse disposition — 2026-09-09

Read-only inspection through parent `18794fe` found that `707b83f` corrected the
two integration defects above and added production-strategy/Broker regression
fixtures, including the T+2 expiry case. The card's report records that evidence;
this follow-up did not rerun the tests or historical market jobs. Preserve the
earlier audit as a counterexample to the old version, not a claim that the same
two defects remain in the corrected version.

`294cb68` remeasured hold0 and added hold20 results; `18794fe` added the 0050
comparison. The hold20 prediction's direction, 60–85% band and <=35% refutation
condition were recorded in `8372905` before the new hold20 execution results.
That ordering supports a prospective prediction of this execution comparison;
it does not make hold20 selection independent of the old viewed market history,
nor provide immutable identities for all consumed inputs. The original hold0
verdict cell remains failed under its own mission. No rule is changed here.

The slower variant is a lead for the next policy design, not a validated account
strategy. Its higher reported retention does not isolate turnover as the sole
cause: holding rules change entries, exits, exposure and shared-capital paths.
The outstanding daily-limit, auction-capacity, dividend-cash, pre-submission
resource and counterfactual requirements above still apply. A zero-slippage run
or an aggregate close-mode anchor cannot close those gaps.

The reported 0050 comparison is contextual, not a new rejection gate or a
permitted ETF holding inside the pure-stock candidate. The CLI benchmark
(`StockProject/backtest_cli.py`, `calculate_buy_and_hold`) explicitly describes
itself as not an execution model: it uses first/last split-adjusted closes,
fractional or integer-share allocation, buy fees and available dividend records.
It does not establish a same-policy next-open, whole-lot, payment-timed control
account or zero execution/psychological burden. Preserve its published numbers
as that benchmark's estimates, not matched execution evidence.

Next use: retain the slow-turnover hypothesis without expanding a performance
grid. Complete a causally possible manual policy and its source/metric readiness
before a new registered candidate evaluation. Do not rerun old market cells merely
to clear the now-resolved code findings or relabel any viewed span as confirmation.
