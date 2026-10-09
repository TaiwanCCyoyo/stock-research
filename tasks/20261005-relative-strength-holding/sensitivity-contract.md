# H05 bounded assumption screen v1

Prospective parent-owned development rules, before any H05 market outcome.
This extends the mission and measurement contract; it does not approve a market
job until the exact input/code/runtime packet is committed and its digest is
recorded. It is not final strategy acceptance or statistical confirmation.

## Fixed comparison budget and execution order

Two unchanged policies, `rs-ma20` and `rs-ma60`, use the same 2019-01-02 through
2023-12-29 calendar and source restrictions. There are at most ten complete
account paths: the following five assumptions for each policy, in table order,
with `rs-ma20` then `rs-ma60` within each assumption. No additional MA, entry,
industry, market-regime or date selection is allowed in this packet.

| Assumption ID      | Extra cash friction each side | Cash dividend payment         | Native fill allocation                          |
| ------------------ | ----------------------------- | ----------------------------- | ----------------------------------------------- |
| baseline           | 0.1%                          | Ex-date plus 45 calendar days | Unchanged                                       |
| high-friction      | 0.3%                          | Plus 45 days                  | Unchanged                                       |
| late-cash          | 0.1%                          | Plus 90 days                  | Unchanged                                       |
| partial-allocation | 0.1%                          | Plus 45 days                  | Half requested quantity, subject to rules below |
| joint              | 0.3%                          | Plus 90 days                  | Same half-allocation rule                       |

First run the two baselines. A profile supplies a development lead only if its
path and daily measurement are complete, endpoint account net return is positive,
at least two settled attempts meet the already-fixed captured-hit definition,
and the sum of all settled attempts' net paid profit is positive. Open/unpaid
attempts remain unknown and their economic contribution remains in account NAV.
These are provisional evidence requirements, not owner-approved loss limits.
Two hits do not establish adequate profit diversification; best-attempt reruns
and concentration review remain necessary later.

Also retain a paired relative lead when one complete baseline has no lower return,
no greater account drawdown and no greater known-non-hit erosion than the other,
with at least one strict improvement. If either erosion is unavailable this
relative conclusion is unavailable. A partial known-settled subset remains
descriptive evidence but cannot establish relative leadership or whole-study
dominance; lack of a comparison is not evidence that a profile failed. A relative lead can justify the remaining
assumption paths even if neither policy meets the absolute lead requirements;
it is not evidence of profitability or an exception to final acceptance.

If neither an absolute nor a paired relative lead exists, stop after the two baselines.
Do not perfect extra assumptions for a direction that has not established even
this bounded reason for further work. Distinguish an incomplete/data-blocked
path from a completed weak path. If the control also fails a particular absolute
requirement, that requirement is a shared diagnostic, not grounds to label the
candidate rejected. Retain all paired relative differences and any relative lead;
the stop means no account lead established for further expenditure, not proof
that SMA20 or the entire method class is ineffective.

If at least one baseline supplies either kind of lead, run all four remaining assumptions for
both policies, not only the better-looking policy. Every path gets fresh decision,
execution and corporate providers and reruns advice, cash/slots, fills and rights.
No subtraction of costs/profits, deletion of events or reused baseline orders.
Each distinct model path has its own scenario identity; identical advice IDs
across separate paths are not an assertion of equal quantities or prices.

## Scope of the assumptions

The partial-allocation model changes the retained TRADED quote's capacity before
the shared lifecycle computes actual fills and end-of-window termination. For a
regular-open request q, the cap is max(1000, floor(q/2000)*1000); for after-hours
odd shares it is max(1, floor(q/2)). In both cases use min(native capacity, cap).
The minimum unit permits the final lot/share to exit and also applies to a
one-lot buy; native zero stays zero. Unfilled remainders expire/cancel under the
existing model, and the next attended review generates fresh advice. No automatic
top-up is introduced. Both buys and sells use this rule. Quotes, price limits,
HALT/NO_TRADE/UNKNOWN evidence and costs are otherwise unchanged. This is a
deliberate partial-fill sensitivity, not an empirical queue model or a guaranteed
performance lower bound. The supported native seam allows one route per code
within a window; an incompatible route cohort is an explicit error.

The 90-day arm changes both pure cash dividends and the cash leg of supported
mixed events. It does not change entitlements or shift the fixed capital/share
delivery assumptions. Payment timing is modeled, not observed. Cash still unpaid
at the endpoint is a receivable and cannot fund a buy or count as captured cash.
The retained share/right and after-hours close proxies keep their disclosed
limitations; the five arms do not claim to cover every possible model uncertainty.

Personal dividend income tax/insurance is still outside these gross-dividend
development paths. A promising screen is only permission to investigate the
net-dividend effect, not promotion to manual stress or final acceptance. Before
such promotion, bind a justified investor-net-dividend assumption/range and
rerun the full account, or restrict the claim. Do not subtract endpoint dividends
and call that an executable tax sensitivity or a return lower bound.

## Interpretation after the fixed paths

Compare full-period net return, close-account drawdown, non-hit contribution
erosion, actual captured hits and paid profits under each matched assumption.
Unknown non-hit windows are unavailable, not zero. Retain the complete daily and
attempt evidence and the existing annual breakdown; do not mine a favorable year,
issuer or background slice to override the whole-period result.

An assumption-sensitive profile (positive baseline but any complete alternative
with negative account return) has insufficient robustness; it is not an approved
strategy. If both policies have the same absolute failure, record the shared
limitation separately and do not convert it into a candidate-only rejection.
Any incomplete matched path makes the corresponding comparison unavailable.

Do not combine return, drawdown and non-hit erosion into a fitted score. Mark a
profile dominated only if the other has no lower return, no greater account
drawdown and no greater whole-study non-hit peak-to-trough erosion in every one
of the five complete matched paths, and is strictly better in at least one of
those comparisons. Report nondominated tradeoffs without declaring a winner.
At most two baseline-lead, assumption-robust, nondominated profiles can proceed
to the next bounded net-dividend/remaining-materiality investigation. Unknown
measurements or sensitivity failures remain explicit; no parameter rescue in
this packet. None of these statuses is `candidate_passed` under the owner goal.

The owner's final non-hit loss budget, manual missed-opportunity recovery,
best-attempt reruns, independent confirmation and final test remain outstanding.
The 70% retention rule concerns the later manual-resilience tests, not these
assumption arms. The historical 20-attempt/about-20% warning, turnover and costs
are reported without reinstating an unapproved absolute veto.

## Burden and interpretability

Keep logical signal identities, order legs, route legs and actual fill legs
separate, including venue, annual counts and maximum legs per advice date. A
missing signal identity remains unknown. Label slots descriptively by assigning
each actual new ledger attempt the lowest free slot in actual event order; retain
the slot through partial exits and undelivered stock rights, but not unpaid cash
alone. Report entries, subsequent attempts and issuer changes separately. These
labels do not change sizing, ownership or portfolio decisions.

Waiting distributions retain entry-order intervals between captured hits and
leading/trailing censoring; unknown attempts are not non-hits. Profit concentration
uses settled positive paid profits as its named denominator, not account net
profit; it is not a best-trade-removal simulation. Loss streaks and non-hit runs
are different: a small settled win breaks a loss streak but remains a non-hit.
Actual holding lengths use the measurement contract. None of these diagnostics
adds a new numerical acceptance threshold.
