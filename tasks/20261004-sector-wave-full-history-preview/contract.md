# Opportunity local history preview contract

Schema: `opportunity-local-history-preview.v1`; price basis:
`permanent-reference-factor-close.preview.v1`; method rule:
`wave-lab-exploratory.v1`; selector: `wave-start-representative.preview.v1`.
All are provisional descriptive identities, not approved trading rules.

## Inputs and price series

Freeze physical inputs in `inputs/`, never links, never overwrite. Parquet hash
must match `67ee9e48260d0ffe73180d0628d6a7f60238a3c576afce30b1ff6537c6ac8003`;
action source hash `3d53a4a7b9790ea2c2b5c4818523abcff530e8750b77db63428244eec30bfffc`.
Record actual snapshot hashes, source observation times and SQLite backup/quick
check; metadata/classification vintages need not equal the price cutoff.

Calendar is the sorted unique date union of the pinned Parquet within the target
window, named `source-date-union`, not an asserted exchange calendar. Keep null
positions; no forward fill, interpolation, annual reset or compact quote index.
Prices TWD, volume lots, date timezone Asia/Taipei. Source is retained per row.

Permanent event set: ETF_SPLIT, ETF_REVERSE_SPLIT, EX_RIGHT,
EX_RIGHT_AND_DIVIDEND, CASH_CAPITAL_REDUCTION, LOSS_OFFSET_CAPITAL_REDUCTION,
CAPITAL_REDUCTION. Only finite positive factors with ex_date <= price cutoff
participate. Multiply factors for events strictly after each quote date through
cutoff, round adjusted OHLC to four decimals; raw OHLCV remains available.
CASH_DIVIDEND is recorded but not permanently applied; no five-row signal fill.
Mixed rights/dividend factors are reference-price bridges, not total return or
share/cash accounting. Events before window start cannot adjust later quotes.

Duplicate permanent records for a security/date must be identical in type/factor
to apply once; contradictory records block that continuity edge rather than
silently multiply two feeds. Unknown/unsupported/nonpositive/nonfinite/null
permanent factors create an explicit action barrier at the first quote on/after
the event when quotes exist on both sides of that event; events before the first
observed quote retain a caveat without blocking it. Valid raw quotes remain
viewable. No invented factor or share ratio.

`coverage_caveats` are nonblocking: early action coverage incomplete, retrospective
capture, unknown first availability, board history, classification snapshot and
delisted coverage. They never become every-day LabPoint.flags.
`numeric_flags[index]` only holds specific quote-level blockers: invalid close,
unusable adjusted value, or the first quote affected by a known unresolved action
barrier. Null/flagged points stay at their calendar index but do not enter fits.
The existing abs(log ratio)>log(1.35) rule cuts a run while retaining both valid
quotes; it is a continuity warning, not a missing close. Cross-barrier gain is
null with a reason. Volume issues are separate from close-only numeric usability.

Price export per security is `opportunity-series.v1`, compressed JSON with
security_id/code/name/cohort/instrument_role, calendar_id, series_id, aligned
`raw`, `adjusted`, `sources`, raw and adjusted OHLC arrays, Volume, sparse
numeric_flags, action_barriers and coverage_caveats. Hash actual serialized bytes.
`LabCase` is generated from precisely these arrays, preserving all null slots.
Price series and native dense results are canonical local artifacts with manifest
references but remain ignored because their backup policy is not established.

## Native methods and comparison support

Pinned unchanged method source has analysis SHA-256
`550c277df28c7ac0b2d4deb69b67eb137b500c0f8b2c80c78880fda79aef1a25`
and types SHA-256
`9ee6c25365f2acbaf889151fa29727457e70319277aa60cca64bcadd38a675cb`.
Consumer wrapper identity is separate. Six native results are produced exactly
once, invoking analyzeCase for segments/filter times fine/balanced/coarse.

Store native launches with their original ensuing-segment range. Comparison
records separately match each target launch against each scale of the same
method, same kind, distance <=20 original calendar indices, nearest then original
candidate order. No outcome or run filter. Self scale participates; record matched
IDs, count and min/max indices. Matches are not independent probabilities.

Native artifact `opportunity-native-results.v1` contains security_id, series_id,
calendar_id, input identity, six `{method,scale,status,result,error}` records and
support_records. Valid nonconverged filter output is preserved with diagnostics,
not dropped. Unexpected runtime/nonfinite-output failures retain method error
status and coverage, never masquerade as empty successful detection.

## Compact event bundle

`catalog-v1/manifest.json` contains task/schema/window/status, all input/code/rule/
config/price/calendar identities and relative table paths/hashes/counts. Chunks
retain finite JSON and use `rows`; native dense fit files are referenced by hash.

- securities/coverage: every one of the 2,075 input codes, role/cohort, observed
  first/last/date count/source counts, eligibility/status, caveats/exclusions.
- baseline_waves: shared per security/scale directional source waves, with stable
  version-scoped ID, native IDs/aliases, small/large, start/peak/end-confirmation,
  observed-through, censored flags, gain/drawdown units. Preserve all three scales.
- methods/phases: security x method x scale, diagnostics/status; every native
  segment with original inclusive endpoints, source phase, log slope and run
  boundary cross-reference where provable. Preserve the original single-point
  phase postprocessing; flag any crossing, do not silently repair the detector.
- candidates: every native candidate, including failed/unresolved/unlinked;
  ensuing range and forward end are distinct from support band. No unique true
  launch is fabricated. earliest_candidate is a reference and manual_selection
  remains null/not_selected.
  Candidate-to-wave membership uses the candidate index within the wave's
  start-inclusive/end-exclusive interval (unconfirmed through observedThrough).
  Ensuing-segment intersection is a separate relation and never establishes
  candidate membership or makes a pre-start/end-day candidate the reference.
- support_records and relations: native references, matching, equality aliases,
  containment, partial overlap/crossing and shared endpoints. Relations name their
  span domain; phase intersection never truncates the native phase record.
- representative_intervals and transitions: precomputed primary selector output,
  start inclusive/end exclusive, nullable next-calendar boundary at final cutoff,
  wave ID/gain base and switch reason. No candidate-launch membership gate.
- classifications: official broad label/code, chain memberships, research group,
  business assertions and sources are separate. Known label survives unknown
  code/effective/first availability; multi-membership is retained. Annual covered
  period is not official effective interval. No present-snapshot history backfill.
- sources/gaps: actual locators/hash bases and availability/membership/action/
  universe/recovery gaps, never treat missing as zero.

Native wave gain/maxDrawdown and candidate forwardGain/drawdown are percentages
(60 means 60%); compact copies preserve these values with explicit percent units.
Representative-day gains and transition jumps are fractions (0.6 means 60%)
with explicit units. Phase slope is per original source
quote interval. First-knowable/detected timestamps remain null with reasons.
Unknown identities and benchmark series are never stock opportunity counts.
Successful methods at the same scale must agree on the shared directional wave
geometry, finite gains/drawdowns and parent geometry. Disagreement is a producer
error; a failed method is preserved without inventing its missing wave list.

## Representative policy

Use baseline waves for primary scale balanced, attributed to primary method
segments for candidate/phase inspection. Active from wave.start to exclusive
confirmed end; unconfirmed through observedThrough inclusive. Order large first,
start date ascending, stable wave ID ascending. First active wins; coalesce equal
representative adjacent sessions. Preserve other waves and overlap relations.

Gain is adjusted[D]/adjusted[wave.start]-1, only with finite usable endpoints and
no numeric/continuity barrier between them. Missing day and numeric blockers are
unknown, not exits; do not erase their membership history. At each switch retain
old/new gain bases and available gains. Earliest linked candidate sorted date/ID
is only a chronological reference, regardless of outcome; membership never uses
it. Confirmed end day is inactive. Native phase shared-boundary ambiguity is kept
and flagged, not relabeled as validated lifecycle.
The JavaScript wrapper also saves run indices using the pinned source's exact
log-difference boundary expression. Compact continuity runs and phase boundary
flags use these saved indices, including floating-point threshold boundaries;
Python reconstruction is explicitly marked fallback and is not full-run evidence.

## Preservation, CLI and fixtures

Only new task outputs, exclusive creation/refuse overwrite. Manifest validation
checks hashes/references/count conservation; CLI and website share intervals and
series. Synthetic fixtures verify action factor/date/rounding, cash distinction,
coverage nonblocking vs date blockers, missing slots, official/fallback source,
six-result legacy-support equivalence, shared baseline, empty/failure/unresolved,
unlinked candidates, overlap/crossing, start membership/end exclusivity/cutoff,
deterministic ascending selector and switch gains. Do not rerun old studies.
