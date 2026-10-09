# Opportunity reader UX review follow-up

## Result

The historical map states its eight-case coverage beside the observation date,
qualifies stock counts and uses readable date/gain labels. Technical provenance,
complete original limitations, import/export and research parameters remain
accessible in research tools. Unavailable phases no longer generate empty
badges or legends. Identical one-day launch bounds are not repeated.

Seven map controls were replaced by pointer/touch gestures, existing keyboard
controls and a reset shown only after camera movement. Unclassified historical
stocks use independent packing groups with no shared sector background; known
snapshot labels remain available without inventing historical membership.

Strategies have readable display names, rules, verdicts and event dates/actions;
the complete original event timestamp and record remain accessible on request.
ETF gap explanations preserve the distinction between partial and absent data.

## Decisions retained

- Positive-return overlap is labelled "持股日上漲占比", not a percentage of
  profit captured. The explanation preserves close-holding timing, equal-stock
  aggregation and its exclusion of execution price, size and costs.
- Yang Ming's February 2021 wave start is unchanged. The existing balanced
  large-scale detector split the prior rally after its declared drawdown;
  it was not an accidentally selected small-scale wave. New wave definitions
  require their own version and cannot be repaired by changing shipping dates.
- The existing eight-case period still starts in 2019. The owner-selected
  preliminary all-market catalog must instead use local history from 2010,
  pin source snapshots and disclose early action, identity and delisting gaps.
  The classification producer has delivered a separate 2010-01-04 to
  2026-10-02 catalog; the website is not yet connected to that catalog.
- Main was merged to include PR #19 research-method/evidence organization.
  Its proposed shared dataset manifest is not an implemented general registry.

## Verification

- Default frontend suite: 205 passed, 0 failed; production build and lint passed.
- Python atlas exporter regressions: 31 passed, including metadata rejection
  before loading sources and preserving valid local-date timezone snapshots.
- Explicit local-data checks: 2 passed. These require the ignored generated
  atlas/case files and are separate from the default checkout-reproducible suite.
- Camera regressions cover ordinary wheel passthrough, anchored zoom/inversion,
  one-pointer pan, two-pointer pinch, mobile letterboxing, zoom limits,
  degenerate input and default-camera detection.
- In-app browser: date entry to 2021-07-23, keyboard pan, conditional reset and
  Yang Ming stock selection/showing shipping with dated cumulative gains.
  Strategy switching retained the failed verdict; original event drilldown
  exposed the saved timestamp and action. ETF partial-data wording checked.
- At a 390px viewport, the page had no horizontal overflow (document width
  375px); controls and qualified coverage remained visible. Viewport restored.
- Actual physical two-finger gestures and modified wheel events were not
  exercised by the DOM-only browser surface. Their camera math is tested;
  device-level gesture verification remains a limitation.

No price, wave, classification packet, native ledger or research fixture was
changed. Original Claude review is preserved in the ignored handoff directory.

## Hosted review follow-up

Three valid findings on the merged-main PR head were corrected:

- Both wave-start and launch-start returns now use the selected wave's start,
  confirmed end and observation cutoff. Dates beyond it remain unknown rather
  than absorbing a later rally. Standalone launch inspection remains available
  when there is no selected wave. Real Yang Ming/3017 and unfinished, shorter
  observation and flagged-price regressions cover these boundaries.
- Saved research events require real complete Asia/Taipei timestamps, dates
  within the declared run and nondecreasing chronology. Equal-time events are
  allowed; nothing is sorted or rewritten. This matches the native exporter.
- Optional source paths/URLs/publication/hash and method-path fields are checked
  before conversion to renderable records; object-valued fields fail validation
  instead of crashing the research page. Unknown extensions remain retained.

Browser inspection of 3017 at 2026-08-14, after its selected 2025-03-31 end,
confirmed both observed gains show unknown with the boundary explanation while
the saved peak remains visible. The two original strategy fixtures remain valid.

Renewed reader review also corrected the timeline caption: its colored strip
represents recorded holding dates, including falling days, rather than the
positive-return overlap metric. Built-in fetch errors now only describe the
built-in source; a successful custom import clears its stale error/loading
state. These display corrections leave the recorded intervals and calculations
unchanged; the production build passed after them.

Four additional MEDIUM import findings were corrected without changing source
artifacts. Event summaries now reconcile date, action, code, quantity, price and
cash flow against the exact native exporter mapping; missing/null values stay
null and zero values remain zero. Legacy atlas prices and optional market caps
accept only finite positive numbers or null, preventing string coercion. Browser
catalog imports reject a declared peak contradicted by a higher valid quote in
its start-to-observation interval. Tied maxima remain valid; incomplete or flagged
intervals retain the catalog entry but cannot display a verified highest return.
The real eight-case catalog and both saved research bundles still validate.
End confirmation must also belong to the saved quote calendar; a weekend date
can no longer show a confirmed exit while producing an uncomputable interval.
Missing quotes on a legitimate calendar date remain unknown without filling.

Further MEDIUM reader-validation findings were addressed: atlas calendars must
be real, unique and strictly increasing; renderable stock/group/metadata fields
are checked before use; saved-research asOf cannot precede any run's through.
Wave-start/launch gains and participation stop after confirmation even when a
bundle retains later prices. Launch-range endpoints must belong to the source
calendar. The suggestion to crop them to one wave was not adopted: the preserved
2002 cross-scale range starts on 2020-03-13, before its selected 2020-03-19 wave.
This is method disagreement evidence, not a return anchor. The stock card now
labels different-scale estimates and explains a range crossing the wave boundary;
original dates remain unchanged and exact Wave Lab matching is preserved.

The saved Wave Lab loader now validates complete case JSON before updating the
library: unique IDs, ordered real dates, finite positive/null prices, flags,
readable source fields and calendar endpoints, and optional saved-wave structure.
Malformed cases retain the synthetic library and expose the loading error instead
of reaching chart/analysis code. Single-day/null-price cases, extra fields and
cross-wave scale ranges remain supported; the saved real case library is unchanged.

Peak-mode atlas observations now retain unknown gain and zero map weight if any
adjusted quote in the selected interval is missing, including its start or final
day. Endpoint mode retains its existing endpoint-only treatment of interior gaps.
Complete peak intervals retain tied maxima and their earliest recorded date.
Saved Wave Lab selections also reject a declared peak contradicted by a known
higher valid adjusted quote in the wave interval. Partial/null/flagged prices
remain readable without filling them; the original eight-case library is unchanged.
Unverified peak dates now also remain null, with unknown date/price labels and an
explicit null gainObservedAt in the real download path. Source-quality blockers
likewise cannot present a confirmed peak date or market cap. Endpoint observation
dates remain known even when their returns are unknown; missing market cap alone
does not remove a verified peak date. Export and quality regressions cover these
distinctions without changing quotes or the selected interval.

Two generated-artifact checks were removed from the default suite and retained
under the explicit test:local-data command. A new checkout no longer needs the
author's ignored public data to run default tests; local checks fail if their
required files are absent rather than skipping or generating substitutes.
Classification snapshot dates must be real calendar dates, independently of the
price calendar; valid later snapshots remain accepted with their original dates.

Positive-quantity positions now require a positive source mark, even when zero
valuation can otherwise reconcile NAV, cash and weights. Zero-quantity rows may
retain zero marks without creating holdings. Both real native-ledger exports
remain identical to their saved outputs (2,432 daily states and 1,017 events).
Matching receipt declarations already passed through the ledger's row/event
count and original-field-retention checks; regressions now demonstrate rejection
of mutually matching but false declarations without treating unrelated diagnostic
flags as approval requirements.

Explicit launch selections also require the producer's exact non-provisional
candidate-to-wave relation; matching dates and methods alone cannot substitute
for that link. Null launch selections remain supported. Every saved research run
requires at least one valid source reference. The legacy Wave Lab exporter now
uses the reader's real-calendar validation, rejecting impossible dates before
creating an artifact while preserving valid leap days and aligned prices.

Subsequent review corrected dated quality events, blank legacy names/hashes and
Python ISO metadata. Invalid dated warnings fail instead of disappearing; valid
out-of-calendar warnings remain retained without creating quotes. Classification
timestamps require real full ISO timestamps with a timezone; compact/week dates
and normalized invalid offset minutes reject before reading price sources.

Saved-ledger adapter v2 validates consistent observed and explicitly named modeled
mark declarations, rejecting execution-price or contradictory flags. The real
ledgers contain eight/two named modeled marks; rejecting every modeled mark would
discard preserved evidence. Their original values, NAV, events and accounting
remain intact, while Chinese basis text and limitations identify their dates and
stocks. Full allocation means all recorded weights are present; it does not claim
every price was observed that day. Observed marks also require a nonempty source
identity that does not declare modeling.

New packages were exported into `public/data/research-evidence-v2-classified/`
after applying the existing reviewed classification packet to the base preview.
The shared loader selects that directory. Prior root packages and native ledgers
remain untouched. Browser checks confirm the visible modeled-mark explanation,
the original exploratory/failed verdicts and Yang Ming's 2021 annual-report group
with the same +663.8% return. No browser errors were captured. The map still uses
the eight-case 2019 window; this package revision is not the pending 2010 catalog
integration.
