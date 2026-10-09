# H05 source and feature binding — prospective refinement

2026-10-05. Selected before H05 market features or account results are calculated.
This extends the [mission](mission.md), not any prior experiment. The broader
research objective is unchanged. There is still no approved market-run packet.

## First development slice and why

The intended broader stock window remains 2019-01-02..2026-08-14. The first H05
account slice is **2019-01-02..2023-12-29**, because an already-verified daily
identity / raw-price / reference-factor join exists for that interval. It is not
chosen from H05 returns. Do not wait for a full rebuild through 2026 before this
conditional developmental test. A later longer-window run needs its own source
binding and comparison record; neither slice is independent confirmation.

The retained readset also contains 2018. Exclude it before H05 feature calculation:
this mission's warmup begins at 2019-01-02, with no carry-in holdings or earlier
feature history. Do not reuse a precomputed six-feature panel with 2018 warmup.
2010–2018 and stock outcomes after 2023-12-29 are not evaluated in this slice.
The current task does not add unobserved stock outcome periods to the registry.

## Reused evidence, not a new source reconstruction

Paths in this table are relative to `D:/Project/Stock/.tmp/claude-kline/`.
These are preserved local inputs; their presence is not Git or offsite backup.

| Component               | Existing authority / reader                                                                           | Meaning and limit                                                                                                                                                                              |
| ----------------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Type and board          | `021-development-universe-policy.md`, `022-daily-membership/projected-v2/observed-identities.parquet` | Dated source provenance, historical discovery, rule-derived ordinary-stock type and explicit board/transfer overlay; not today's survivors, nor complete external historical PIT certification |
| Raw observations        | `026-market-runtime/readset.py::load_market_readset`, `source-binding-v1.json`                        | Exact one-to-one join of three fixed 009 price exports and the 022 daily identities; missing OHLC retained; Volume in shares                                                                   |
| Signal reference events | `025-signal-factor-inputs/signal-factor-readset-v1.json`, `model.py`                                  | Named effective-evening factor timing; original historical publication time remains unknown                                                                                                    |
| Signal representation   | `026-market-runtime/feature_panel.py::forward_signal`                                                 | Forward causal reference index with an explicit, source-bounded factor-coverage assertion; not executable price, economic entitlement or total return                                          |
| Cash evidence           | `015-cash-source-readset/cash-readset-v2.json`, `027-cash-runtime`                                    | Existing source priority and cash terms; no implicit share/principal-domain coverage                                                                                                           |
| Issuer continuity       | `010-membership-signal/transfer-continuity.json`                                                      | Only the individually supported cross-market continuities; equal code strings alone do not prove continuity                                                                                    |

026's recorded join contains 2,528,056 keys / 1,463 dates / 1,895 codes for
2018–2023, including 32,350 rows with missing OHLC. These are existing whole-input
inventory counts, not counts for the new H05 slice. Daily source availability is
modeled at 18:00 Taipei for a 20:00 review; historical availability stays null.
The new October producer repair is **not** silently included in this old readset.
Any known material population omission must be assessed before promotion; this
conditional source choice cannot support an unqualified universe-completeness claim.

The independent calendar is retained at
`D:/Project/Stock/shioaji_stock_prices/.worktrees/codex-workspace/.tmp/data-gap-repair-20261004/calendar_results/calendar-audit-20261004T135812-6c324a25.json`,
schema `calendar-audit.v1`. Its `calendar_dates` contains **1,216** dates in the
selected H05 interval. The 2018–2023 dates equal all 1,463 keys in 022 v2's
`receipt.json.daily_observed_counts`, with zero differences; this check reads
dates, not prices or outcomes. The audit retains monthly raw paths and hashes.
Its observed SHA256 is recorded in the later packet rather than copied as a
new source of authority. It is TWSE FMTQIK, not a separately verified TPEx
calendar: equivalence for the two markets remains a disclosed development
assumption. Date equality does not prove individual-stock coverage or tradeability.

## Thin feature adapter, no old eligibility inherited

The adapter consumes separately supplied raw and causal signal OHLC with exact
Code/Date key agreement, one market per key, an explicit ordered calendar and a
daily ordinary-stock set. It does not download, choose factors, infer source
completeness, query outcomes or rebuild membership.

- A usable observation requires finite, positive and internally consistent raw
  and signal OHLC. Missing observations remain missing; absent calendar rows
  break contiguous history. No filling or compressing short gaps is allowed.
- Ordinary-stock membership on that date plus 60 consecutive usable observations
  defines the ranking-history gate. Sixty-session return requires 61 contiguous
  closes, `signal_close[t] / signal_close[t-60] - 1`; it is unknown at 60.
- SMA20/SMA60 include the current close on that same signal series, with complete
  windows required. A membership change does not erase observed price history or
  held-stock exit features. It does exclude the current nonmember from peer ranks.
- Rank known ret60 within the day's eligible ordinary-stock pool using average
  ties divided by the pool size. Apply no liquidity gate before this ranking.
- Entry liquidity is the inclusive trailing-20-session median of raw close times
  raw share volume, in TWD. All 20 values must be known, volume nonnegative;
  unknown is not zero. Require at least NT$20 million after computing ranks.
- Preserve raw `source_id` and availability, plus a separate `panel_source_id`
  for the declared derived-input identity. Dates and timestamps cannot be future,
  late or silently inferred by the adapter. Causal arithmetic alone is not PIT
  source proof. No rounding or data-dependent epsilon is added to signal values.

For this first source binding, the signal index follows 026's reference factors,
including its cash-event reference treatment. It is **not** the atlas's
permanent-noncash-only price basis. The return/percentile formulas are reused, not
the atlas's numerical features, eligibility set or performance. This declared
basis change is prospective and requires its own run identity. Raw prices and
separately source-bound cash/share economics remain authoritative for the account.

## Runtime seam and market-run boundary

The thin runtime maps this panel to `PolicyFeature`, raw cents plus signal closes
to `CloseObservation`, and the supplied calendar to existing chronology frames.
TWSE and TPEX share the same cash/holding capacity. Review is 20:00; following
session submission is 08:55, regular-open observation 09:00 and expiry 13:30.
The first frame has no earlier orders. The final close marks the terminal account
but produces no unreachable next-session advice; it does not liquidate positions.

Execution and corporate callbacks are explicitly supplied, fresh per scenario,
and remain responsible for their domain evidence. Current-day market routing is
checked again at execution. No callback, empty event list or unit test grants
historical completeness. Missing held marks or unsupported residual odd shares
must remain incomplete, not disappear from the account. Ordinary order sizing,
limits, five-issuer occupancy and latest-information resumption stay as fixed
in the mission; the runtime does not reconstruct a second portfolio engine.

Before a real run, bind source terms, reference limits, actual open observations
and modeled allocation, costs, residual-share venue and material halt marks.
Reuse the existing cash/share/principal and execution leaf adapters, including
their named corrections. Freeze provisional captured-hit / nonhit measurement,
endpoint treatment, sensitivity arms and advancement rules in the registered
packet. Neither the source audit nor synthetic integration releases market
execution or substitutes for eventual owner loss-budget approval.

## Incremental adapter source binding — 2026-10-05

`source_modules.py` imports named libraries, never the old `runner`, `account`
or strategy launchers. The current worktree's `research_core` must supply every
core submodule; conflicting module origins fail. A later registered job will use
the primary Stock directory as its explicit evidence root, with the active task
entrypoint below `.worktrees/research-workspace-20261003/`. This accommodates the
preserved local inputs without copying caches or changing their historical paths.
All consumed code, including the two primary-checkout rotation feature library
imports required by `forward_signal`, must appear in the packet's byte-hash map.
Importing those libraries does not authorize calling the old six-feature policy.
`require_declared_imports` rejects omitted or changed local imports; use it before
and after real execution, in addition to the existing registered-job verifier.

Twenty-one economic/quote leaf source files and named JSON evidence were restored
at their original task-relative locations from retained commit
`919aef7211255e54b6f22b94d4ab7e698641fcca`. Their original Git blob identities and
working hashes are in `adapter-provenance.json`. No old launcher, strategy,
account result or verdict was restored or changed. The scratch adapters remain
explicit local dependencies rather than a claim of portable full-market replay.

`source_bindings.py` reuses the original binders and their exact source checks:
one 2316 capital return, three free-share distributions (2915/2823/6472), two
mixed distributions (3588/3617), and six paid offers deliberately declined
(3363/4768/6438/2641/3680/6443). Paid refusal is a prospective standing behavior,
not a claim that those rights had zero value. No subscription cash or shares are
fabricated. Mixed distributions require one independently bound matching cash
leg; their share composers never mint a duplicate dividend. Event-day bounds for
9945 remain quote-only evidence, not supported economic rights.

The previously missing-looking 6472 and 6443 captures are preserved under
`D:/Project/Stock/.worktrees/codex-workspace/.tmp/`; the loader names their actual
locations but never rewrites original `raw_path` provenance inside their bytes.
No new acquisition was necessary. Source payment/delivery dates retain the
explicit old modeled timing (including the 45-calendar-day baseline); unknown
historical publication/credit dates remain unknown. This does not certify all
fractions, economic events or investor-specific income taxes.

`economics.py` composes fresh cash, capital, share, mixed and paid providers per
scenario and retains their notices/backdated evidence. Only exact successfully
bound event triples are removed from the unsupported set. Other issuers are not
pre-excluded: an unsupported right stops a path when actually held or claimed.
The selected source records contain 7,989 cash terms and 4,087 remaining
unsupported noncash identities after the twelve named bindings. These are source
inventory counts, not H05 encounters, lost trades or demonstrated data coverage.

Source-only preflight also binds the three preserved single-session halt cases
and the named 4192 no-trade record. Actual missing-mark/resumption handling,
residual odd-share routing, costs and account measurement still require explicit
H05 integration before a market packet. Restoring a leaf is not evidence that
the policy has exercised it. No H05 price features or portfolio results were
calculated by this source binding.

## Named session and residual execution binding — prospective refinement

`sessions.py` binds injected raw/panel rows to the already selected interruption
evidence. It emits separate accounting marks and source-identified review states,
never filled raw/signal bars. Single-session cases require their exact price
source IDs and reference close, a null-price/zero-volume halt row and the stated
calendar adjacency. The capital case retains old-share valuation only over its
bound suspension interval; its existing economic provider performs the exchange.
Recovery exceptions stop at another unknown gap or after 60 contiguous closes.
The profile-specific missing-MA response is fixed in the prospective mission.

`execution.py` freezes caller-supplied observations and uses the supplied
calendar's strictly previous session. Compose the retained native no-trade
provider, then its named resumption correction, then H05's execution-day market
route guard. Event bounds, unknown evidence and expiry retain their original
semantics. Named proof of a regular no-trade session does not imply an odd-lot
quote or a usable valuation mark. Neither source-only binding nor a present
opening price proves actual queue allocation.

The residual adapter is opt-in, inside the terminal decision guard. Add its
separate after-hours window; do not wrap the terminal guard with a shadow
whole-lot holding. Terminal residuals are supported marked assets only when the
adapter is enabled, not realized exits. The packet must declare the regular-close
odd-lot proxy and modeled small-order allocation, together with cost and
material sensitivity assumptions. These integrations do not complete that packet
or authorize a market evaluation on their own.

The minimal native execution code closure is now Git-portable under
`retained_execution/`, with original ignored-source identities recorded in
`execution-source-provenance.json`. Use `source_modules.load_execution_adapters()`
for synthetic execution integration; it does not require producer price, feature
or measurement files. Full `load_adapters()` reuses these same modules and still
requires the remaining declared local source closure. This fixes test portability,
not full market replay portability or unknown historical source availability.

## New-checkout code-location correction — 2026-10-09

The preceding source locations record the historical H05 evidence binding. In
the new stock-research checkout, `source_modules.py` now defaults the evidence
root to its active repository and loads the retained rotation `eligibility.py`
and `features.py` from that same repository. Their executable formulas are unchanged. Type annotations and explicit
type narrowing are recorded separately in the retained rotation
`typed-source-provenance.json`; `original-source.zip` preserves the historical
source bytes. New runtime source identities must be declared for new packets; source-origin checks and packet byte-hash validation remain.
This is a location correction, not a replacement by a different shared method
or a new sealed execution packet.

The private `.tmp/claude-kline` closure is not included in the new checkout.
Missing private sources still fail explicitly; no fallback to the old primary
folder, download, evidence copying or account run is performed. Original
receipts, observed paths and historical results above remain unchanged.
