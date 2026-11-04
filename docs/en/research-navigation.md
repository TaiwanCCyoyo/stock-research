# Research navigation contract

This is the maintained UX entry point for research → dataset → coverage → stock
navigation. Data schemas remain owned by [data status](data-status.md),
[shared-data viewer](shared-data-viewer.md), and
[study presentation](study-presentation.md); this document does not redefine them.

## Purpose and scope

Help a reader inspect the data behind a research claim and return to that claim.
The current priority is relationships between volume, patterns, candlesticks and
subsequent gains/losses, rather than account simulation. Navigation must never
start market calculations.

The owner approved parallel implementation on 2026-11-03. The discussion input is
Library file `libfile_c2578f2e75bc8191b5b9dac04f555d70`, version 1.
Its direct transfer failed in this executor. On 2026-11-03 the parent supplied
the verified v1 full text, which was reconciled against this slice. The draft's
historical "not yet approved" header describes its creation state; the later
owner approval governs this implementation. The full proposal is not copied here.
G1/G2 are this slice; G3/G4 and report-section return remain separate follow-ups.

## Current journey

| Action                               | Destination and identity                                                    | Return / failure behavior                                                                               |
| ------------------------------------ | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Open a study's shared-data reference | `#dataset?ref=…&back=…`; preserve the exact recorded string                 | Back contains only study query, filter and study ID                                                     |
| Open a catalog status entry          | Same route with the exact `catalog:<data-id>:<version>`                     | Return to overview                                                                                      |
| Reference without a version          | Show explicit choices from verified family/catalog metadata                 | Never choose the newest/recommended version automatically, even if only one exists                      |
| Select a version                     | Add `version` to URL                                                        | Refresh and history retain the selected version                                                         |
| Inspect frozen catalog version       | Reuse catalog metadata card for that exact version                          | Summary only; no stock button without a member reader                                                   |
| Inspect maintained family            | Require matching generation from the family response                        | Expired or unknown generation stops; never substitute current                                           |
| Separately inspect current coverage  | Existing `#overview/stocks` with dataset filter and bounded dataset context | Explicitly current data, not replay of the selected generation; source-dataset return remains available |
| Open a coverage security             | Existing opaque securityKey route                                           | Existing coverage filters, pagination and scroll return remain; nested source context survives          |
| Follow related research              | Exact equality against `study-card.v2.provenance.shared_data`               | Family references do not imply the selected version; do not infer relationships from titles             |

Explicit `catalog:` and `derived:` namespaces constrain resolution to that source.
When the catalog is unreadable, catalog and unqualified references are unavailable;
an explicit derived reference can still resolve without the catalog. Unqualified
same-ID references across both sources are ambiguous, even if versions match.

Dataset source links, browser Back/Forward and refresh use URL state. Study
selection focuses the original card after data loads. Return URLs are reconstructed
from bounded local route/parameter allowlists; no external return URL is accepted.
Search text stays a local draft until form submission; typing does not add history
entries. Enter or the search button commits the query, while filter selection
adds a navigation entry. This preserves the discussion's state-lifecycle rule.

Each dataset request has an AbortController and instance-specific cancellation
check, including A → B → A. Matching a textual key alone is insufficient:
an older request for A must not overwrite a newer request for A.
Public-synthetic mode does not request private dataset or related-study metadata.
Missing IDs, unavailable catalog, duplicate identities and expired versions have
distinct states. Retry is offered for transport failures. Unknown counts remain
unknown.

## Operation / verification matrix

| Status     | Concern                                   | Implementation / evidence                                                       | Remaining acceptance                                                             |
| ---------- | ----------------------------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| current    | G1 exact dataset destination              | datasetJourney, DatasetDetailPage, routes; identity and return unit tests       | Synthetic Edge direct URL, refresh and Back/Forward passed; real catalog pending |
| current    | G2 study references and return            | StudyCardView, StudiesPage URL filters and focused study                        | Synthetic round trip, query and focus passed; physical touch pending             |
| current    | No fake catalog stock entry               | CatalogCard reused with one version; summary notice                             | Synthetic catalog summary passed; real metadata pending                          |
| current    | Version loss / ambiguity                  | resolveDataset tests                                                            | Unit tests passed; real generation-change integration pending                    |
| current    | Related-study provenance                  | Exact recorded reference only; no name matching                                 | Synthetic exact-reference relation passed; private API integration pending       |
| current    | Obsolete response isolation               | Per-effect abort and aborted checks                                             | Synthetic 20-second delayed A/B/A passed; latest response remained visible       |
| current    | Public synthetic isolation                | Private-mode guard on both reads                                                | Public-mode notice verified in Edge; private-read guard retained                 |
| proposed   | G3 map segment context                    | Carry opaque security identity, interval, basis, source/version and safe return | Existing map route and chart API do not yet enforce this complete contract       |
| proposed   | Historical generation member/price reader | Need an API capable of honoring exact generation/version throughout             | Do not silently attach current coverage/chart to a historical claim              |
| superseded | Every study reference opens overview      | Replaced by exact reference resolution                                          | None                                                                             |
| superseded | Canonical routes are #data / #data/code   | Overview / coverage / opaque stock routes own current navigation                | Legacy routes remain compatibility resolvers                                     |

## Verification record (2026-11-03)

Edge on the Windows host exercised synthetic study search (typing left URL
unchanged; Enter submitted), study source disclosure, explicit family generation
selection, refresh, coverage, opaque-key stock, and the complete reverse path.
The return preserved the submitted query and focused the original study card.
Catalog v1 showed its identity and summary-only boundary without a stock link.
Browser Back/Forward returned to the study and then that same catalog version.
A 390px viewport showed no horizontal document overflow (375px content width);
keyboard Enter activated the return link. This is not physical-device touch QA.

For race validation, the first two family responses were delayed 20 seconds.
After A → B → A, the page displayed response 4 and retained it after both older
responses were released. The diagnostic server used only clearly labelled
synthetic fixtures, intercepted API endpoints, and had no producer/shared-data
reader or proxy. Public-mode notice was separately checked on the normal dev app.
The initial timeout was isolated to sandbox-host reachability: a formally approved
host-local dev server resolved it. No firewall or security setting changed.

Frontend tests: 568 passed; TypeScript passed. The earlier build's final dist
rename EPERM was not retried. Owner acceptance, physical touch, real catalog/API
integration, and integration with the separate reading PRs remain pending.

## G3 shared context contract

A future map-to-stock handoff must retain the API-provided opaque security key,
source record identity, start/end dates, price basis and exact dataset version or
generation, plus a bounded local return context. Missing identity, unsupported
historical generation, invalid interval or unavailable basis must remain explicit;
never turn a retrospective wave into a contemporaneous signal. The chart may
offer a separate current-data inspection, clearly labelled, but must not claim
to replay the old segment.

### Version-pinned map/stock boundary

`full-history/stockJourney.ts` carries a bounded `wave` URL context on the
existing `#stock/<encoded opaque key>` and `#market` routes. It preserves the
security, series and wave identities, catalog version, observation date,
interval, price basis, display mode and threshold. The saved history reader
must verify metadata, then the exact frame member, then detail provenance and
required interval prices before rendering. The code used by the existing detail
endpoint comes only from that verified member. No current coverage reader or
price fallback runs for a wave link, including malformed contexts.

Map departure pins its history entry; explicit return, reload and Back/Forward
restore the URL-owned selection. The stock chart starts at the source interval.
New map control interactions leave replay context so exploration cannot silently
claim to remain the original wave. No session storage is needed for identity.

**Availability boundary:** today's history producer has `securityId`, `seriesId`
and `waveId`, but no proven coverage `securityKey`. These are different identities.
The optional `HistoryRow.securityKey` is an adapter boundary for a future proven
mapping, not permission to derive a key from a ticker. Real rows without it show
an unavailable handoff. The existing reader also cannot select arbitrary historic
catalog generations: a version mismatch is unavailable, not a replay of current
data. This slice does not change producer data or claim a real-data end-to-end
journey. Synthetic tests supply explicit keys and fictional prices; they are
functional checks, not owner visual acceptance or market research.

Unit checks live in `full-history/stockJourney.test.ts`. The manual synthetic
browser harness is `node scripts/map-stock-browser.mjs` from `research_web`;
it mounts the real map and historical stock page with synthetic API responses.
No history data, downloads, saved drafts or market computations are required.

Verification for this slice: 7 new unit tests; complete frontend suite 596/596;
TypeScript and scoped lint passed. Edge synthetic checks passed normal and delayed
navigation, two Back/Forward cycles, explicit return/focus, keyboard entry, stock
refresh, missing key, version mismatch and missing prices. The manual harness is
not part of hosted CI. No real generation/member mapping or owner visual acceptance
was tested.

## Delivery boundaries

### Saved comparison navigation slice

After merged PRs #153 and #154, the research list and the L1 report viewer expose
an explicitly labelled **synthetic workflow example**. It is not the report's
research result. `#condition-comparison` selects an exact registered immutable
result; URL fields own horizon, cell, outcome filter, sort, page and selected/open
event. Source metadata comes from the registration, never from URL overrides.
Unknown result IDs, duplicate/unknown parameters, invalid pages and mismatched
case contexts show a recoverable error rather than substituting another result.

Opening a case replaces the current comparison entry with its selected event,
then pushes one case entry. Refresh, Back/Forward and the explicit return retain
the same comparison and restore focus to its case button. Return targets reuse
the bounded study-list context (query/filter/study) or an allowlisted report ID.
The original entrance receives focus on return; a bounded URL focus marker supports
this after reload, while missing storage never affects semantic URL state.
Report-section positioning is not claimed: the entrance is in the report shell.

The registry currently contains only the previously merged component fixture.
Its reader is explicitly a synthetic saved-event summary; it has no market chart
or invented dataset link. The formal producer contract in open PR #155 has not
been imported or copied into main by this slice. Integrating it must preserve
its not-evaluated synthetic/pilot status, unavailable-condition partitions, null
denominators and bounded references. Those references are not labelled outcomes
or a complete pageable case list. A∖B summaries are not supplied by that producer:
leave them unevaluated instead of subtracting counts or distinct-stock numbers.

Questions can be exported with saved source/settings and `discussion-only` intent.
No direction revision is guessed, no direction approval is recorded and no new
research is launched. Connecting to an actual same-revision direction draft,
formal L1 adapter, historical dataset/member readers and full owner journey
acceptance remain subsequent integration work.

Verification: 5 new registry/URL/identity tests plus the existing component and
route tests. Edge verified the research-query return, keyboard page-2 case entry,
refresh, Back/Forward, explicit return focus and rapid H252/H126/H252 selection.
These are synthetic functional checks, not research validity or user acceptance.
The complete frontend suite passed 579 tests locally; TypeScript and scoped lint
passed. A 375px Edge viewport had equal client/scroll widths (360px). The source
entrance regained focus after the explicit return. Export controls and draft
provenance rendered correctly; downloaded-file contents have not been verified.

The original dataset slice owns router, dataset detail, study source links and
return behavior. The comparison follow-up reuses the merged component through
the bounded navigation above; it does not import the unmerged L1 recovery pilot.
Existing unmerged reading PRs and owner acceptance restrictions remain separate.
No deployment, scheduling, permission, producer or research-data changes are
part of this work.

Comparison source focus takes precedence over a preserved `study` card target,
including cached cards, delayed initial loading and later refreshes. Ordinary
study returns still focus the selected card. Changing search/filter clears the
return-focus intent along with the selected study.

Mounted browser regression: from `research_web`, run
`node scripts/comparison-focus-browser.mjs` and open the printed localhost URL.
It mounts the actual StudiesPage and replaces only the data hook with a labelled
synthetic fixture. In Edge, all 11 focus assertions passed for cached/delayed
cards, two response generations and ordinary study navigation. This browser
harness is a manual regression and is not included in `npm test` or hosted CI.

### Comparison-to-discussion follow-up

[PR #158](https://github.com/TaiwanCCyoyo/stock-research/pull/158) follows merged
#156 with an explicit draft chooser and inline reuse of the existing direction
renderer. It pins the selected task and complete revision, verifies draftPath,
and carries the comparison question/provenance as proposed notes through the
existing feedback contract. This implements the handoff mechanism listed above;
real-draft integration, formal L1 data and owner usability acceptance remain
pending. No actual draft is authored or approved by this slice.

The [handoff contract and browser regression](direction-discussion-ui.md#saved-comparison-question-handoff)
record access, empty/error/stale states and manual export boundaries. Validation:
589 frontend tests passed; 20 final formatted handoff/kit tests passed; TypeScript,
scoped lint and normal hooks passed. Edge synthetic integration passed normal
handoff/edit/export/close, delayed target races, stale revisions, read errors and
empty lists. This does not claim physical mobile or keyboard usability acceptance.
