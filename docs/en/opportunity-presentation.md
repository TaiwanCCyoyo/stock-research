# Retrospective opportunities and saved research

The local React application lives in `research_web/`. Its default `#home` page
summarizes the latest covered market date, saved strategies and recent research.
The `#market` page reads the frozen full-history preview described below. The original eight-case
review remains at `#market-preview`; neither is a completed market inventory
or a trading recommendation. Existing rolling-window atlas and task readers stay
available at their legacy routes. `#strategies`, `#strategy/<encoded-run-id>`,
`#compare` and `#history` inspect original saved results through
the additive [strategy studio contract](../../tasks/20261008-strategy-studio/data-contract.md).
Existing research missions and verdicts are not changed by presentation or account reconstruction.

## Full-history web reader

Run `uv run python scripts/start_research_web.py` from the checkout to start both
the website (5177) and its API (8517). `--check` checks their checkout identities;
`--no-browser` suppresses opening the browser. Occupied ports belonging to
another checkout are reported without terminating them. Logs belong to
`.tmp/research-web-launcher/`. Stopping the launcher stops only children it started;
this is not an operating-system startup registration.

The configured physical snapshot at
`tasks/20261005-market-full-history-web/inputs/producer-preview/` spans
2010-01-04 through 2026-10-02, with 1,970 eligible saved stocks. Its trusted
manifest digest and original methods stay unchanged. This universe does not
cover every issuer ever listed; early corporate-action adjustment, delistings,
historical membership and fine classification remain explicit limitations.

`opportunity-history-web.v1` now adds launch candidates, saved trend phases,
continuity-checked sparklines and separate wave-start/launch observation gains.
`/directory` returns every saved representative interval for timeline inspection.
`/options?date=...` compares counts from balanced/coarse saved segment results,
with no extra analysis fitting. `/status` reports nonblocking initialization
progress without reading sources or exposing paths.

The default map requires its saved candidate date to have begun; full-wave
membership, including pre-launch and no-launch records, stays in the directory
and an explicit alternate view. These dates and phase names are provisional
retrospective interpretations, not approved real-time signals. The phase mapping
is fast -> large rise, rising -> slow rise, flat -> pause, falling -> retreat;
it is labelled as candidate stages. Native launch `rangeStart/rangeEnd` describes
the ensuing segment, **not launch-date uncertainty**. The card uses the candidate
date as its launch return anchor. The existing fixed representative-selection
rule is retained. The owner-approved time-adjusted display policy below replaces
total-gain sizing on the full-history map; complete multiyear waves remain in the
catalog and searchable history even when below the display threshold.

The first positive map fits the full market; later date changes preserve the
camera and fixed world scale. The ten largest industry labels remain readable
in overview. The ranking, searchable timeline and individual price chart share
one displayed date. Date requests discard obsolete replies and never relabel an
older frame as the requested date. Packing keeps its existing worker and latest
request replacement, with territory shading as a decorative boundary.

Saved research portfolios may be matched to the full market by canonical stock
identity. The initial comparison reports only same-day holdings and same-day
allocation snapshots, with up to four pinned selections. It does not infer
continuous ETF ownership or full-wave gains. Unknown evidence uses hatching;
complete covered absence is distinct from unknown. Timeline holding bands use
recorded holdings, including omitted optional quantity, intersected with registered
coverage; explicitly nonfinite or nonpositive quantities are excluded. Whole-wave overlap,
account performance and compatible US opportunities remain separate future work.

The website alone opts into a small local semantic-receipt cache under
`.tmp/opportunity-native-verification-cache/`. Reuse requires the exact encoded
prices, native results and calendar, actual pinned method and bridge bytes,
validator/cache code bytes, Node executable bytes and Python runtime identity.
In addition, the web startup memo at `.tmp/opportunity-web-startup-cache-v1`
can reuse a successful compact query projection only after rechecking all current
required source bytes, implementation and runtime identities. It is authenticated
with a disposable installation-local key and bounds compressed/decoded sizes.
An absent, corrupt or mismatched memo runs the full structure, continuity,
semantic and exact query reconstruction checks in a background worker. API
requests report explicit loading while verification runs, keeping the shell and
saved-study pages usable. CLI/build verification defaults do not read this disk cache. No
method fitting, data download or source-result overwrite is performed by it.
This is a local performance cache, not independently authenticated evidence.

## Independent contracts

- `opportunity-catalog.preview.v1` is the sector-wave producer's bounded input.
  The physical gzip fixture preserves its methods, waves, launches, phases,
  relationships, quality events, classifications and source identities.
- `opportunity-explorer.v1` is a validated presentation projection. Price,
  wave-rule, fixed display-selection and classification versions are distinct.
  Each security has explicit representative intervals; overlapping selections
  are rejected. Renderers never choose the most profitable wave each day.
- `saved-research-runs.v1` preserves methods, verdicts, account NAV and original
  events. These are stored model accounts, not personal account transactions.
- `opportunity-comparison.v1` is CLI output; `opportunity-view-review.v1` is a
  selected browser view with the same model results and source identities.
- `opportunity-classification-evidence.v1` retains independent broad, value-chain,
  research-group and company-role observations. Its file receipt is checked before
  projection; a separate selection manifest controls document-period map groups.

The domain module owns validation and calculations without React dependencies.
Page components own interaction; packing/animation owns geometry only. New
agent results enter through versioned adapters, not executable HTML or arbitrary
source-path reads. A new method may add a renderer without changing comparison
definitions. All pages inherit shared appearance tokens.

Wave-chart annotations are bound to a SHA-256 digest of the actual case content
and rule version, including price points, flags and source metadata. Reusing a
case ID or a declared source hash cannot attach old feedback to changed prices.
An identity must be ready before editing or exporting feedback. Old browser
entries are preserved without automatic migration to an unverified new identity.

## Dates, membership and meaning

The accepted prototype separates the full retrospectively known wave from its
selected launch. The main map contains `launch <= D < confirmed end`; unlaunched
and no-launch cases remain in the directory. Confirmation absent at the snapshot
does not manufacture an exit. Missing/flagged prices and `observedThrough` are
hard observation boundaries. A confirmed earlier ending remains a dated
historical event; its end gain is never relabelled as a later observation gain.

The stock card distinguishes wave-start-to-D, launch-to-D, hindsight peak and
confirmed-end returns, with dates and price basis. Price gaps are not filled.
Wave-start/launch observation gains and participation become unknown after a
confirmed ending; the separate confirmed-end gain remains available. A selected
launch's cross-scale estimate range uses source-calendar dates and may cross
the selected wave boundary. It is labelled as scale disagreement, not cropped
into a different source range or used as the return anchor. For example, the
preserved 2002 estimate begins before that selected wave's start.
Known classification snapshots remain attached to each security, with their
original observation timestamp and source, even when historical applicability
is unverified. They are reference labels, not historical grouping membership.
Missing fine-role evidence must not erase a known broad classification.

Historical exchange membership and retrospective document-period business
grouping are separate bases. A unique date-valid historical membership takes
precedence; otherwise a unique `document-period` business group may be used for
the period explicitly described by its source. The UI labels that basis as
retrospective, exposes the source and covered period, and does not infer an
exchange-effective interval, publication date or contemporaneous availability.
Snapshots never fill missing historical periods. Unknown grouping keeps the
stock visible and its known reference classification inspectable.
Candidate statistical slopes are not automatically called launch/rest/retreat:
unapproved lifecycle mappings stay unlabelled in the historical map. The
exploratory detail chart can compare methods without replacing frozen choices.

The current historical package selects eight existing inspection cases and
eight explicit representative waves. It retains 86 source wave records. These
are neither 86 independent opportunities nor the planned complete 2010 inventory.
The separate synthetic mode has 36 fictional stocks and 21 fictional portfolios.
It exercises phases, geography and interactions without posing as market evidence.

## Area and motion

The legacy eight-case preview uses positive total percentage gain `g`. The
full-history map now uses the time-adjusted percentage-point metric `g` below.
In both cases, weight is `(g / 100)^2`. Doubling the displayed metric doubles
equivalent diameter and quadruples area. One world scale persists across dates;
centering and user pan/zoom do not alter relative geometry. Industry area derives
from constituent stocks, counted once. Zero gain has zero quantitative area;
an outline selection marker is separate. Curved stock cells preserve their
target area. Layout transitions are animation, not additional observations.

The requested historical-cap multiplier (100x cap -> 1.25x area) is reserved but
**not applied** until reliable dated cap inputs are available. Pure gain is
explicitly disclosed. No sector-specific boost or per-date auto-fit is used.
Packing runs in a worker with latest-request replacement; forward confirmed
exits may burst, backward scrubbing and reduced-motion mode do not.

## Time-adjusted wave display

The owner approved the initial 100% threshold in the
[2026-10-05 display mission](../../tasks/20261005-opportunity-growth-display/mission.md).
`wave-growth-display.v1` is a separate display rule, not a new detector, source
snapshot, strategy gate, or retrospective catalog rewrite.

`research_core/wave_growth.py` owns the shared calculation. Input `gain_pct` is
the continuity-checked wave-start-to-observation return in **percentage points**.
The history reader's `start` is the original wave start, matching its saved
`gain_base_index`, rather than the representative interval's later entry date.
Source query fractions are converted to percentage points by the existing view
adapter before this helper; native hindsight peak gain is not the observation gain.

Elapsed years are Gregorian date-only days / 365.25. Below one year, use actual
return and leave annualized return null. At or above one year, use
`100 * expm1(log1p(gain_pct / 100) / years)`. With integer days, the transition is
at day 366; this convention is not calendar-anniversary annualization. Zero days
use actual return without division. The default inclusive threshold is 100%,
with an absolute 1e-9 percentage-point comparison tolerance for floating error;
display rounding does not determine membership. The UI exposes alternate
thresholds and still applies its explicit saved-candidate appearance rule.

Frame rows add `growth` with schema `wave-growth.v1`, `startDate`,
`observationDate`, `yearDays`, `elapsedDays`, `elapsedYears`, `totalGainPct`,
`annualizedGainPct`, `sizingGainPct`, `basis` (`actual`, `annualized`, `unknown`)
and `reason`. Total returns, launch returns and hindsight peaks retain their
original meanings. Invalid dates, missing/nonfinite gains and left-censored
starts produce unknown display metrics; observed-fragment total return remains
inspectable without asserting the unknown full-wave duration. Right-censored
waves can use the valid current observation while retaining their unfinished flag.

Directory rows add `gainAtEndDate` and `growthAtEnd`. Confirmed end return uses
the wave's final included price date (`end - 1`), independently of earlier or
disjoint representative intervals. The confirmation date is a separate field;
unfinished waves have no confirmed-end return. Inclusive phase intervals fill
observed-session slots through their last date.

Map weight is `(max(sizingGainPct, 0) / 100)^2`; raw total gain is never overwritten.
Industry labels identify the individual stock leading this display metric and
its actual/annualized basis, rather than implying a sector portfolio return.
The full-history map retains hindsight peak return in dated text, but omits the
legacy raw-return peak outline because its area would not be comparable with
the time-adjusted observation circle. Legacy preview outlines remain unchanged.
The existing representative selector, original records and historical classification
limitations remain intact. Future price availability used to identify saved
waves does not make these retrospective labels known at their historical date.

The standalone CLI shares the Python helper, reads recorded returns only, and
writes JSON to stdout without changing input or fitting methods:

```powershell
uv run python scripts/score_wave_growth.py --input .tmp/wave-observations.json --threshold 100
```

Input is a JSON list or `rows` wrapper containing `{start, date, gain,
leftCensored}` with optional identities/provenance. Output
`wave-growth-evaluation.v1` retains each original input, its growth object and
`eligible` / `below-threshold` / `unknown`, plus rule and threshold. Consumers
must retain the source catalog/series/wave identity; this arithmetic receipt
does not authenticate supplied input or invent price history. Shared code,
contract and mission are tracked by Git; large source artifacts keep their
existing physical-snapshot access and backup limitations.

## Holdings, overlap and account capital

Coverage and holdings use half-open date intervals. Positive tradable quantity
is held. A complete covered snapshot without that stock means not held; absent
or partial evidence means unknown. Monthly holdings never forward-fill to daily
evidence. Missing is not zero, and unknown ETF rows have no performance rank.

`close_exposure_positive_return_overlap.v1` (收盤持倉與上漲日重疊率) measures,
for `wave start < d <= D`, the sum of positive simple adjusted-close returns on
dates whose close snapshot holds tradable shares, divided by all positive
returns. Positive-return dates with unknown holdings or invalid price paths
make the result unknown; no positive returns means undefined. The displayed
average is equal-weighted across calculable selected stocks with coverage counts.
This metric ignores execution timing, overnight exposure, position size and
costs. It is not profit, return capture, attribution, or an acceptance gate.

Capital uses same-date positions divided by account NAV. Known non-case stock
positions, cash, receivables/claims and unclassified amounts stay separate.
Receivables are not tradable shares or spendable cash. Account NAV uses the
native ledger's raw marks (including explicitly modelled marks), while the
opportunity diagnostic uses adjusted prices. Their returns are not interchangeable.

The two saved candidates contain 1,216 daily account states each. The native
adapter reports 2,432 NAV reconciliations with zero maximum TWD difference;
this checks accounting preservation, not strategy quality. The exploratory
normal run and failed cap run keep their original outcomes. All 1,017 events
retain original fields; display IDs are labelled derived. Six ETF method
references have no verified daily holdings here. US funds also require a
compatible US opportunity universe; unknown TW overlap is not a missed-opportunity
judgment on those funds.

Each native account snapshot is the declared 20:00 Asia/Taipei checkpoint. Its
event prefix must include every event at or before that instant and no later
event. Event order is preserved and timestamps must be nondecreasing. The final
snapshot must also account for the complete event ledger.

## Reproduction and source ownership

From `research_web`, run the preview exporter with the frozen selection file:

```powershell
node --experimental-strip-types scripts/export-opportunity-preview.mts --input fixtures/opportunity-catalog.preview.v1.json.gz --selections ../tasks/20261004-opportunity-explorer/preview-selections.json --output ../.tmp/new-opportunity-preview.json
```

The sector-wave chat owns detector candidates, classification evidence and
source-quality reconciliation. Its preview originated at local commit `fac041c`.
The research chat owns the native ledger adapter and its receipt. Given its
reviewed ledger directory, the website adapter verifies hashes, verdicts, event
counts and accounting before producing new compressed packages:

```powershell
node --experimental-strip-types scripts/apply-classification-evidence.mts --input ../.tmp/new-opportunity-preview.json --classification fixtures/classification-v1/classification-v1.json --sources fixtures/classification-v1/sources-v1.json --receipt fixtures/classification-v1/verification-receipt.json --selections ../tasks/20261004-opportunity-classification-fix/selections.json --output ../.tmp/new-classified-opportunities.json
node --experimental-strip-types scripts/export-research-evidence.mts --catalog ../.tmp/new-classified-opportunities.json --ledger-dir <reviewed-ledger-directory> --out-dir public/data/research-evidence-v2-classified --json
node --experimental-strip-types scripts/compare-opportunities.mts --input public/data/research-evidence-v2-classified/opportunity-explorer.json.gz --date 2021-04-29 --portfolio stock:20261002-add-retry:normal-v1 --output ../.tmp/new-comparison.json
```

Classification adapter v2 uses repository-relative, forward-slash locators for
its supplemental source references and identity calculation. Its repository
root comes from the script location, independently of the working directory;
CLI arguments still resolve relative to the caller's working directory. Input
files must physically reside inside that checkout. Copy required external
evidence into an explicit physical research snapshot at a stable repository
location, retaining its producer provenance, before exporting. Identical input
bytes at identical relative locations produce the same classification identity
across checkouts. Existing v1 bundles and receipts remain readable and unchanged.

Output files/directories must not exist. These operations do not run strategies,
download, modify prices, unseal periods or change old task outputs. Absolute
input paths in older or separate research receipts remain provenance, not
runtime dependencies. The bounded
compressed presentation packages and receipt are preserved in Git for viewing;
uncompressed generated payloads are ignored. The preview and classification
fixtures are also preserved, but rebuilding this joined package requires the research chat's
reviewed native-ledger directory and receipt. Those native exports currently
remain local, so Git alone does not restore them. Default frontend tests use
preserved presentation fixtures and synthetic ledgers; they need no generated
public files or live API.

Adapter v2 validates observed versus named modeled marks, retaining the ten
explicit modeled records with readable dates and stock identifiers. Its new
directory is selected by the shared static loader; previous root packages and
native results remain preserved. The data schema remains compatible with old
imports, and complete recorded allocations do not imply wholly observed prices.

The pre-classification presentation package is retained as a physical fixture;
its original task receipt remains unchanged. The classification follow-up's
receipt binds the updated browser package and separately confirms preserved
prices, waves, representative choices, account histories and numeric comparisons.
The three explicitly selected fiscal-2021 groups retain all supporting roles:
shipping/container operations, foundry operations and a composite phone/connected
device/VR group. They do not choose the highest-return business or infer each
role's contribution. Event-year observations and undated profiles remain references.

The map-to-Wave-Lab handoff resolves the case source by
`case:<detailCaseId>` and the catalog identity by `producer:catalog_hash`.
These are distinct evidence identities; source array order must not select either.
A missing binding stays unknown, including for imported historical cases.
The handoff also retains the selected wave's full date boundaries, scale,
censoring and chosen launch. Re-analysis selects only a unique matching wave;
another method or scale cannot reuse an unrelated local wave ID. An unmatched
saved wave remains explicitly unmatched until the user chooses another result.
Timeline interactions resolve the representative at the requested date rather
than the previously rendered date. Price summaries and detail explanations share
the same known-basis interpretation.
User-facing price explanations describe supported adjustment and dividend
assumptions in plain language; unfamiliar descriptions remain unconfirmed.
Source identifiers, hashes, paths and internal rule versions stay in the data
records and exports. Website evidence presents readable source titles, explicit
page references and safe external links. Securities with no price points remain in the directory, with detail
navigation disabled and the missing-price reason visible.

Full catalog work remains separately assigned: actual usable/adopted/excluded
dates and securities, 2010–2012 adjustments, official-first/Shioaji-gap policy,
delistings and universe coverage, historical classifications and the outstanding
evidence queue. Fixture delivery does not settle the full-data backup/storage
decision or authorize full recomputation. New research hypotheses from the
comparison require their own preregistered mission before evaluation.
