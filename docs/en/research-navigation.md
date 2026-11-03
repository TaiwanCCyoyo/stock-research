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

## G3 shared context contract (proposed)

A future map-to-stock handoff must retain the API-provided opaque security key,
source record identity, start/end dates, price basis and exact dataset version or
generation, plus a bounded local return context. Missing identity, unsupported
historical generation, invalid interval or unavailable basis must remain explicit;
never turn a retrospective wave into a contemporaneous signal. The chart may
offer a separate current-data inspection, clearly labelled, but must not claim
to replay the old segment. This slice does not add map routing or calculations.

## Delivery boundaries

This slice owns router, dataset detail, study source links and return behavior.
The separate saved-comparison component/fixture and L1 recovery pilot do not
depend on these internals and are not included. Existing unmerged reading PRs
remain separate. No deployment, scheduling, permission, producer or research-data
changes are part of this work.
