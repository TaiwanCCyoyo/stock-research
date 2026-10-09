# Retrospective Taiwan sector-wave catalog v1

Preregistered 2026-10-02 before reading price outcomes for this task.

## Scope

Build a reusable historical catalog of fast-rising Taiwanese stocks, business
groups and contemporaneous peers. The owner permits hindsight classification
first and requests a classification review. Preserve producer data and previous
studies. This is descriptive research, not a trading backtest, predictive model,
ETF study or reconstruction of historical classification availability.

## Window and source identity

Price window: 2019-01-02 through 2026-08-14 inclusive, with no outside warmup.
Registry event `bootstrap-price-exposure-20260908` establishes viewed overlap.
Filter later prices at the Parquet read boundary and later corporate actions at
the SQL query boundary. The source file itself may contain later rows. Both
2019's opening boundary and 2026's ending boundary are incomplete years.
Use the physical worktree snapshot. Hash inputs, consumed code, grouping config
and this mission before the one descriptive calculation; never overwrite a run.

## Frozen inventory definition

`runaway-126-double-dd25.v1` is an analyst-chosen inventory rule, not a trading
threshold. Do not tune it after seeing this inventory.

1. Include Taiwan TWSE/TPEx ordinary stocks identified by metadata. Exclude
   ETF/index/other instruments and emerging-board `shioaji` rows. Preserve
   exclusion and coverage reasons; do not require survival until the final date.
2. Scan finite positive daily adjusted closes in date order. A close twice the
   lowest close in the trailing 126 observed stock sessions, including this
   session, qualifies an episode. Earliest date wins tied lows. Record trough
   and qualification dates.
3. Follow closing highs until the close falls at least 25% from the running peak.
   The peak ends the ascent; the drawdown session confirms its end. Restart the
   search at that confirmation session, preventing overlapping stock ascents.
   No confirmation by the data endpoint means right-censored, not completed.
4. Record trough/peak multiple, appreciation fraction, sessions to peak, first
   25%-above-trough milestone, maximum drawdown during ascent and raw boundaries.
   `price_multiple=3` means +200%; +100% means twice the price.
5. Keep zero-volume observations and mark liquidity. Duplicate dates, invalid
   prices, unexplained daily jumps >=40%, and unsupported action factors are
   data-quality issues. Quarantined paths cannot select a winner. Missing is
   never zero; do not interpolate prices or fabricate tradability.

## Price policy

Reuse the pinned existing `DataLoader` corporate-action adapter's permanent
`SplitAdjustedClose` layer, with corporate actions bounded to this window.
Do not use its temporary five-day cash-dividend signal correction as a historical
return series. Cash dividends are excluded. This is adjusted price appreciation,
not investment total return or rights-subscription execution PnL. Retain raw
closes and actions; unsupported factors and unexplained jumps are quarantined.

## Classification and common-period comparisons

- Keep official industry, chain/node membership and practical research groups
  distinct. Current official labels are retrospective business labels only.
- Research group mappings use `(chain_code, node_code)` pairs, expand descendants
  and deduplicate securities. IDs can recur across chains. Keep source evidence,
  multiple memberships and a visible unclassified state.
- Focused cohorts cover memory components/manufacturing/modules/controllers,
  cooling, servers, power equipment, shipping, passive components and other
  explicit source-node combinations. Official-chain fallback retains securities
  lacking a focused mapping. Official-chain waves are seeded only by those
  otherwise-unmapped episodes, while their comparisons retain the full chain.
  Focused family groups and their subgroups are alternative views, not independent
  observations. Broad semiconductor membership does not imply AI.
- Sort qualifying ascents by trough date within a group. Greedily cluster only
  when starts are within 90 calendar days of the first AND all ascent intervals
  retain a nonempty common intersection. Keep single-stock waves explicitly.
- The comparison window is earliest member trough to latest member peak. Include
  every available classified peer, including nonqualifiers and laggards. Align
  to first session on/after start and last on/before end. A boundary mismatch
  exceeding 7 calendar days yields null comparable returns with a reason.
- Record common-window endpoint/peak appreciation, aligned dates, liquidity,
  quality issues and qualifying episode references. The hindsight winner is the
  comparable, nonquarantined peer with highest common-window peak appreciation
  (code breaks ties), not highest incomparable own-trough gain.
- Record earliest 25%-milestone among qualifying episodes separately. This
  historical timing descriptor is not a daily ranking or early-detection claim.

## Deliverable and verification

Versioned JSON bundle: manifest, securities, groups, episodes, waves, peer
comparisons and coverage/quality findings. Stable IDs, explicit units, resolving
references, finite numbers, null reasons, chunked tables and input/output hashes.
One descriptive calculation; no parameter sweep or strategy-acceptance verdict.
Verify detection, censoring, clustering, matched-period comparisons and the
source-bound adapter using hand-calculable synthetic regression tests first.
Validate references, hashes and counts after generation. Use normal commit hooks.
Report actual results and limitations in Traditional Chinese.
