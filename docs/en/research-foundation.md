# Research foundation

This is infrastructure, not an approved strategy or a replacement owner objective.
For current work, start at the [research program](research-program.md) and current
owner contract. The 2026-09-08 restart began with the
[measurement contract draft](research-measurement-contract.md); that dated restart
does not require each later session to repeat completed preparation. Existing
missions, seals, outputs, and their original verdicts remain historical evidence.

The subsequent 2026-09-09 owner update permits staged development under presealed
provisional metrics. This infrastructure document is not a requirement to finish
every helper, final owner threshold or venue before that development run. Use
the updated owner contract and validate the paths the selected experiment uses.
Unobservable payment/fill timing may be modelled explicitly with full rerun
sensitivities, never represented as observed evidence or used to invent entitlements.

## Responsibility and scope

The parent owns the hypothesis, statistical design, exposure review, acceptance
policy and final interpretation. Under the owner's 2026-09-09 authorization, Codex
may handle research-required acquisition/backfill and downloader fixes directly;
Claude assistance is optional. Pipeline code remains in `stock-data-downloader` and
the owner contract's data-protection boundaries still apply. A bounded
research worker executes one approved packet, returns evidence, and stops.
Long-running deterministic code does not require continuous model reasoning.

Chat reports are the primary review interface. Existing K-line/trade viewers remain
optional evidence drilldowns; dashboard feature expansion is paused. Figures must
be rendered from traceable artifacts, never model-invented price/equity paths.

## Measurement before gates

`research_core.ledger` reconstructs **recorded executions**, not hypothetical
orders. Signed `total` already includes fees/tax: do not subtract them twice.
Input event order is authoritative, including same-day sells and re-entries.
For a sale with minimum costs exceeding its gross proceeds, net `total` may be
zero or negative. Such a `SELL` must include positive `gross_proceeds` and
nonnegative `cost_total`, reconciled to `total = gross_proceeds - cost_total`
within `1e-9` TWD absolute tolerance using exact fractions of the original integer
or float's decimal text, before ledger float arithmetic. Whenever either component is supplied, both
are required and checked, including positive-net sales. Any net debit requires
spendable cash; unpaid dividends do not finance it. Positive legacy sales without
components retain their previous replay semantics. This prevents small costly
exits being erased because their net cash flow has the wrong sign for a naive model.
Economically flat-to-flat attempts aggregate adds, partial exits, splits and dividends;
an open position or undelivered share claim is not a completed failed attempt. Buy/sell-only PnL and total
cash-flow PnL including dividends are different named quantities.

For explicit accrual accounting, `DIVIDEND_ENTITLEMENT` has zero cash `total`, a
unique nonempty `entitlement_id`, and a positive finite net `amount`. It binds the
receivable to the currently held attempt. A later `DIVIDEND` supplies that ID and
the same amount in `total`, even after exit/re-entry; it settles once. Payment
amount matching uses no relative tolerance and absolute tolerance `1e-9` TWD,
not the account's cash tolerance. Neither entitlement nor receipt dates are inferred.
Unknown payment/entitlement evidence cannot be repaired by guessing a date.

Returned `dividend_total` is paid cash; `dividend_receivable` is still unpaid.
Closed attempts expose `net_cash_flow` and economic `net_pnl` (cash flow plus
receivables). Marked equity includes account receivables once, but available cash
does not. Audit rows retain the original attempt ID, amount and payment state.
For time-specific results replay the event prefix through the requested as-of
time; a final closed-attempt summary incorporates later payments and is not a
historical snapshot. The helper does not infer a captured-hit classification.

Legacy unlinked `DIVIDEND` events still require current holdings and describe only
recorded cash replay, not entitlement proof. Each code must use only one attribution
mode per replay; mixing legacy payments and explicit entitlements is rejected in
either chronological order. Explicit payments must supply IDs; missing/null IDs
cannot silently select another attempt or double-count a receivable. Existing
historical artifacts remain intact.

Principal refunds use separate `CAPITAL_RETURN_ENTITLEMENT` and `CAPITAL_RETURN`
events. The claim has zero `total` and positive net `amount`; payment has a positive
`total` matching its prior claim, same code and globally unique cash entitlement ID.
Cross-kind payment is rejected. There is no unlinked legacy principal-payment mode.
`capital_return_total`, `capital_return_receivable` and `capital_return_entitlements`
remain separate from dividend fields. Paid refunds contribute to net cash flow;
unpaid refunds contribute to equity but never spendable cash. Both stay attributed
to the original attempt after exit/re-entry, without reducing its purchase denominator.
Exact decision snapshots report all cash receivables in `receivable_cents` and
also break out `capital_return_receivable_cents`. Economic best-attempt ranking
includes unpaid refunds and is still distinct from captured-hit classification.
This cash support does not create bonus shares, fractional claims, or a tradability
model; those require explicit separate account events and evidence.

For a known same-class free-share right, `SHARE_ENTITLEMENT` records zero cash
and a positive exact `share_numerator / share_denominator`, with an entitlement
ID unique across cash and stock rights. It requires current tradable holdings.
`SHARE_DELIVERY` transfers a positive integer `qty` from that linked claim to
tradable stock, at zero cash. It cannot overdeliver or make fractions tradable.
Only when the remaining claim is strictly between zero and one share may
`SHARE_CASH_SETTLEMENT` extinguish it with an explicit nonnegative net `total`.
Known zero is permitted; missing is not zero. Fractional settlement cash remains
separate in `share_settlement_total` and belongs to the original attempt.
`share_claim_history` retains each original rational grant, whole shares delivered,
fraction settled and cash amount even after nothing remains outstanding.

Selling all tradable stock does not close an attempt while its stock claim remains.
Another purchase of that issuer joins the same attempt. The issuer reserves one
of the existing capacity slots until both stock and stock claims are zero; cash
receivables alone retain their existing closure semantics. Decision `holdings`
contains only tradable positive quantities; `occupied_issuer_codes` also includes
claims. Execution `reserved_position_codes` survives auction/lifecycle replay,
and final settlement releases the reservation when the account is reconstructed.
Claim value cannot fund purchases. Delivery invalidates previously sized pending
orders and is unsupported during live orders without explicit reconciliation.

The sole supported claim valuation policy is explicitly named
`same-class-raw-close-cent-half-up`: value each remaining exact rational right at
the supplied raw close and round half-up to cents independently. This is a modeled
economic proxy, not observed sellable proceeds. Missing marks fail, and
`share_claim_value_cents` is separately visible. Outstanding claims exclude the
attempt from closed-attempt stress ranking. A `SPLIT` while claims remain rejects
until a source-bound rebase exists. Paid subscriptions are not free-share rights.
These synthetic-tested mechanics do not establish historical entitlement, delivery
dates or availability, or approve this proxy for a market experiment. Preserved
006/014/016 source and report adapters need explicit versioned integration before
consuming the new share-event vocabulary.

Actual peak-to-trough account drawdown uses marked account equity, including the
initial account value. A compounded sequence of per-attempt effects is a
**synthetic diagnostic**, not that equity curve. The non-hit diagnostic takes
contiguous windows: small profitable non-hits stay in the window, a hit breaks
it, and an unknown classification cannot silently become a miss. No function
chooses a runaway threshold or acceptance cutoff.

The owner has now clarified that hits require actually captured large returns and
other winners cannot mask cumulative non-hit losses; about 20% is a warning reference,
not a finalized exact veto. The measurement draft separates non-hit PnL attribution
from full-account drawdown. Attempt ordering, hit threshold/horizon, denominator,
as-of rules and a loss budget still need finalization before any gate. Infrastructure
tests cannot approve them.

Recorded cash replay is **not** a counterfactual stress backtest. Missed signals,
delayed orders and removing a best attempt must rerun the strategy's decisions,
cash allocation and fills with an explicitly frozen scenario. Do not subtract
PnL, delete a winning symbol, filter completed trades, or call idealized daily
prices executable odd-lot fills. A shared executable next-open/odd-lot model is
still a prerequisite for a future strategy claim; this maintenance neither
invents nor approves that trading policy.

## Verification boundary

Use hand-calculable synthetic fixtures for infrastructure development. Do not
rerun historical research to test plumbing. Review changes to shared measurement
or execution boundaries; reuse unchanged test evidence. A completed losing run
is a valid execution result, not an infrastructure failure.

The institutional task's existing immutable dispatcher is unchanged. Portable
input/output receipts only check reproducibility of declared files and commands;
they are not a sandbox, tamper-proof security seal, or evidence of an unseen
sample. Hashing an incorrectly defined metric does not make it correct.

## Headless evidence and versioning

From the repository root:

```powershell
uv run --no-sync python -m scripts.research_evidence catalog
uv run --no-sync python -m scripts.research_evidence registry
uv run --no-sync python -m scripts.research_evidence exposure --scope taiwan-price-strategy --start 2024-01-01 --end 2026-08-14
```

The catalog checks only root artifact availability, including report-only cards;
it does not read performance JSON or run folders. The existing MCP/CLI task-list
function consumes the same catalog. The legacy dashboard is not rebuilt to show
new result types during this maintenance.

New cards may write `research_result.json` with schema `research-result.v1`:
`study_id`, `candidate_id`, `run_id`, `phase`, `window` (start/end), `identities`
(owner_contract, metric_contract, execution_contract, data_snapshot, code,
runtime), `outcome`, `metrics`, `artifacts`, `limitations`, `supersedes`.
Every metric is `{value, unit}`; an unavailable value is null plus
`unavailable_reason`, never zero. Valid units are fraction, percent, TWD, count,
trading_days and ratio. Outcome separates candidate_failed, candidate_passed,
invalid_measurement, data_blocked, incomplete and not_evaluated. Schema validation
does not certify the outcome or verify referenced file hashes.

```powershell
uv run --no-sync python -m scripts.research_evidence validate-result tasks/EXPLICIT_TASK/research_result.json
```

Precedence: current owner contract governs new design; each historical mission
governs its original verdict. A versioned result describes a specific run, not a
silent replacement of a legacy summary. Published correction records identify
the affected measure and original source, leaving both intact. Conflicts are
reported, not resolved by last-modified time. Malformed new evidence fails
validation; it must not fall back to a legacy pass. No result is opened merely
because it exists.

`docs/en/research-registry.json` is a deliberately incomplete, append-by-review
exposure/correction log shared by Claude and Codex. Preserve existing event IDs;
append corrections, never erase viewed history. Git preserves versions, not a
tamper-proof append-only guarantee. Absence means unknown, never unseen. A new
task/model/worktree and a new feature name cannot establish fresh market history;
the parent must review relevant scopes and overlap before prospective sealing.
Do not include unpublished economics, private data or invented first-seen times.

## One approved job and verified reuse

`scripts.run_registered_job` has no parameter search or automatic phase advance.
The legacy `run_experiment_iteration` loop was removed because its train-pass
path repeatedly opened holdout. Historical journals can still be read with
`scripts.generate_nightly_report`; their results do not authorize new studies.

A JSON packet (`research-job.v1`) must contain:

- task_id, job_id (safe identifiers), phase and window (start/end);
- candidate_id, owner_contract_id, metric_contract_id, execution_contract_id,
  scenario_id and the exact params object;
- inputs: nonempty code/data/contracts maps of repository-relative file -> SHA256;
  enumerate the entrypoint, imported helpers, engine, loader, universe, data files,
  corporate-action/metadata files, contract and dependency lock actually consumed;
- runtime from the identity command below (Python/platform/executable/package IDs);
- script (a declared hashed local `.py`), exact args list containing a literal
  `{output_dir}` token, timeout_seconds, outputs (JSON filenames), summary (one
  output using existing backtest summary schema 1.0).

The parent creates/reviews the packet and records its approved digest before
execution. IDs label the design; file hashes identify bytes. The runtime identity
is collected from the prepared environment without contacting a service. No
environment values/credentials should be put in packets or logs.

```powershell
uv run --no-sync python -m scripts.run_registered_job --identity
uv run --no-sync python -m scripts.run_registered_job --packet PATH --identity
uv run --no-sync python -m scripts.run_registered_job --packet PATH --approved-sha256 DIGEST
uv run --no-sync python -m scripts.run_registered_job --packet PATH --approved-sha256 DIGEST --execute
uv run --no-sync python -m scripts.run_registered_job --packet PATH --approved-sha256 DIGEST --verify-reuse
```

Default mode is preflight only. A digest is not authorization: confirmation and
holdout still require the parent's explicit finalization command and exposure
review. Entry programs must accept the provided output directory and use the
existing engine/CLI with explicit parameters. They must not spawn detached
processes or write outside that directory. This runner is not a sandbox.

Execution exclusively creates `tasks/<task>/runs/registered/<job>/`; existing
folders are never overwritten. Success requires process exit 0, unchanged declared
inputs/runtime, parseable finite output JSON, and structural summary validation.
An atomic completion receipt contains packet and output hashes plus elapsed time.
`--verify-reuse` rechecks them all; candidate profitability is irrelevant. A
failed/interrupted job stays on disk for diagnosis; use a new job_id for an
explicitly approved retry. Do not silently salvage a partial result. Receipts
attest only listed outputs; sidecars must be declared to be covered.

Input hashing does not detect an unlisted import/data read, changes restored
during execution, or a dishonest process. Use the existing stronger seal when
its registered study requires it. Never migrate an old seal implicitly.

## Worker packet and return

Delegate a meaningful batch only after the parent has fixed the question, allowed
files, packet identities, phase, budget and stop conditions. The deterministic
runner owns process time; Luna medium handles logs/evidence extraction, Luna max
handles bounded judgement already allowed by the mission, and Terra handles
scoped implementation. Keep these model choices until measured results justify
a change; wall-clock backtest duration alone is not a reason for max reasoning.

Return packet/run IDs, completion/validation state, failed command/error category,
output hashes/paths, metric-contract ID, and concise unresolved questions. Report
execution time separately from model usage; record model tokens only when
actually available, otherwise null. Count retries and redundant executions.
The parent decides direction once per completed batch, not after every grid cell.

Stop on malformed inputs, data blockers, permission failures or exhausted budget;
do not reinterpret an infrastructure failure as a negative strategy. Download
blockers from a bounded worker go to the parent with reproducible evidence. The
parent may resolve them directly under the owner contract; `.tmp` handoffs remain
available when external assistance is needed. Do not start another
research direction, update the App goal or resume automation from a worker return.
