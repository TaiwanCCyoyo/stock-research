# Saved strategy studio contract

## Purpose and access

`saved-research-studio.v1` is an additive presentation package. It extends, and does
not overwrite, `saved-research-runs.v1`. The producer is
[`export_saved_research_studio.py`](../../scripts/export_saved_research_studio.py);
the shared reader is [`saved_research_studio.py`](../../research_core/saved_research_studio.py).
The consumer is `research_web/src/features/strategies/`, home and research history.

The original manifest and at-most-450-KiB binary parts are private external
evidence; their original hashes remain in `publication.json`. They are no longer
carried in the current Git tree or Vite public directory. The local preservation
receipt is `<primary-checkout>/StockProject/data/private-presentation/20261008-first-stage/restore-manifest.json`.
Git carries presentation metadata and this contract. Public mode independently
generates fictional controls in memory and does not present the two original runs.
The parts contain one unchanged gzip stream; the reader verifies every part and
the full compressed bytes against the transport manifest before decoding.
Viewing the two saved strategies requires the explicit absolute
`STOCK_SAVED_STUDIO_PACKAGE` path and `STOCK_RESEARCH_DATA_MODE=local-private`.
Missing private inputs return unavailable; no download or synthetic substitution
occurs. Re-exporting requires
the frozen input files listed in the package's `sources`; those large inputs are
local and not all Git portable. Source locations are evidence locators, never HTTP
path arguments. The web frontend reads the formal API, not study directories.

The API prefix is `/history-api/saved-research-studio/v1`:

| Route                                 | Result                                               |
| ------------------------------------- | ---------------------------------------------------- |
| `/runs`                               | Overview and saved NAV curves                        |
| `/run?run_id=...`                     | Detail, cycles, statistics, reconciliation and rules |
| `/trade?run_id=...&trade_id=...`      | OHLC, fills, decisions, costs and cash-flow formula  |
| `/account?run_id=...&date=YYYY-MM-DD` | Original evening holdings and account audit          |
| `/exposure?run_id=...`                | Every saved evening's allocation, including unknowns |
| `/research-history`                   | Packaged discovery of formal reports and missions    |

Run and trade IDs are opaque strings, not filesystem paths or path segments.
Consumers use standard query-parameter encoding once, including IDs containing
slashes, Unicode or punctuation. The original `/runs/{run_id}` detail and its
trade/account/exposure paths remain compatibility aliases for existing path-safe
IDs; new consumers use the query routes above. Every alias invokes the same
reader, validation, error classification and date rules.

`/history-api/opportunity-history/v1/membership?code=2609&date=2021-04-29`
provides the same daily map membership without a browser. `threshold` is percent,
default 100; `mode` defaults to `launched`, with `catalog` optional. Its `metric`
is a fraction (2 means +200%); `onMap=null` means outside covered stock/date inputs,
distinct from covered absence (`false`). History loading responds with explicit
503 `detail.state=loading` and Retry-After, never a fabricated empty market.

## Coverage and field meaning

Two original saved runs: `stock:20261002-add-retry:normal-v1` (303 holding cycles)
and `stock:20261002-entry-extension-cap:cap-v1` (120). Each has 1,216 evening states,
2019-01-02 through 2023-12-29, initial capital TWD 2,000,000. This interval is the
saved strategies' coverage, not the market catalog's 2010 start.

| Fields                                                           | Meaning                                                                                                                                                |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `positions[].fills`                                              | Original modeled events, exact order IDs, shares, price, costs, cash flows; not broker fills                                                           |
| `candles`                                                        | Frozen unadjusted OHLC; incomplete candles stay missing                                                                                                |
| `realizedPnl`, `unrealizedPnl`, `pnl`, `remainingCost`           | Original cash-flow cycles with average-cost partial exits, corporate entitlements and remaining marks                                                  |
| `accounts[].recordedEquity`, `reconstructedEquity`, `difference` | Original ledger NAV versus shares × saved ledger mark + cash + other assets; modeled/stale marks keep provenance                                       |
| `otherAssets`                                                    | Dividend/capital receivables and undelivered share claims; not spendable cash                                                                          |
| `reconciliation`                                                 | Closed-cycle PNL + open-cycle PNL versus account increase; open cycles can contain realized cash flows                                                 |
| `addSignal`                                                      | Saved probe economic return, including corporate rights, joined by exact order ID; raw-price +10% is only a chart reference                            |
| `dailyRank`                                                      | Unknown in old runs; exit rules do not prove actual daily rank                                                                                         |
| `pendingAssets`, `missingReasons`                                | Exact entitlement IDs for unpaid rights; cash-based cycle statistics exclude unpaid assets and retain unsupported-event limitations per affected trade |
| `capture.days`, `knownDays`, `totalDays`                         | Inclusive opening/closing saved trading-date participation; never weekly interpolation or full-wave capture                                            |
| `capture.bestMetric`, all returns and weights                    | Fractions, not percent numbers                                                                                                                         |
| `runawayWeight`, `unknownStockWeight`                            | Evening market value / recorded account equity; missing classification/marks stay unknown                                                              |
| `captureAvgWeight`                                               | Equal-weight average across saved evenings; unknown if an evening is incomplete                                                                        |
| `captureCoverage`                                                | Optional ready-provider projection of confirmed participation and complete-date allocation coverage; never modifies saved statistics                   |
| `topFiveProfitShare`                                             | Five largest profitable closed cycles / all profitable closed cycles; not net account profit                                                           |
| `underwater`                                                     | Consecutive saved dates below the previous account high, elapsed calendar days; open tail stays unfinished                                             |
| `nameBasis`, `nameSourceId`                                      | Verified catalog snapshot display names only; not proof of historical business roles                                                                   |

Strategy capture stays fixed at the approved +100% time-adjusted, launched-only
definition and does not follow a separate map threshold selected by the user.
The same `build_frame` projection and membership predicate are shared with the
market. A portfolio held on a day does not imply it captured the entire wave or
that its account outperformed.

### Partial-evidence projection

When the daily catalog provider is ready, `/runs` and `/run` add
`captureCoverage`. Loading or failed providers do not fabricate it. Its fields are:

| Field                                       | Meaning                                                                                                 |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `closedTradeTotal`                          | All closed holding cycles, including those without usable membership evidence; open cycles are excluded |
| `confirmedCapturedClosedTradeCount`         | At least one known positive membership day, even if other holding dates are unknown                     |
| `confirmedNotCapturedClosedTradeCount`      | A nonempty holding interval, every saved holding date known, and zero positive membership days          |
| `undeterminedClosedTradeCount`              | Remaining closed cycles; the three counts partition `closedTradeTotal`                                  |
| `completeExposureDays`, `totalExposureDays` | Complete evening allocation dates / all saved evening dates                                             |
| `knownDayAverageWeight`                     | Equal-date mean of `runawayWeight` over complete dates only; null when there are no complete dates      |

A complete allocation date has `known=true` and all five allocation weights
(`runawayWeight`, `otherStockWeight`, `unknownStockWeight`, `otherAssetsWeight`,
`cashWeight`) finite and present. Known zero contributes zero. Unknown dates,
missing marks and nonpositive-equity dates are excluded, never replaced by zero.
The UI labels this conditional mean with its numerator, denominator and excluded
date count. It cannot be called a full-period average: missing dates may be
systematically different. The existing nullable `captureAvgWeight` and
`capturedClosedTradeCount` retain their original exact-period meanings.

The comparison page first aligns saved NAV dates as before, then intersects the
complete allocation dates of every displayed strategy. Every allocation mean
uses that same intersection. If a displayed strategy's exposure is unavailable,
all allocation means remain unknown. Performance and NAV still use the full
aligned comparison period, not the smaller allocation subset. Daily allocation
plots continue to show gaps with account drill-down.

The 0050 line uses unadjusted close, **price only, no dividends**. The original
strategy price readset did not contain 0050: this line is explicitly from the
separate fixed history catalog, external manifest pin
`c7848ae7ad177770babfda774e07923f995ba2cb3fa4a83d77d02f77a0dfe140`.
Its price series and calendar are separately hashed. It must not be represented
as the strategy's original sealed benchmark or as a total-return comparison.

## Re-export and maintenance

```powershell
uv run --no-sync python -m scripts.export_saved_research_studio --benchmark-manifest tasks/20261005-market-full-history-web/inputs/producer-preview/catalog-v2/manifest.json --benchmark-manifest-sha c7848ae7ad177770babfda774e07923f995ba2cb3fa4a83d77d02f77a0dfe140 --split-output --output .tmp/saved-research-studio-next/saved-research-studio.manifest.json
```

The output must be new. The producer verifies original SHA receipts, ledger,
orders, entry/probe traces and frozen price bytes before projecting; it never
reruns a strategy. Normalized event identities, dates, quantities, prices and cash
flows are also checked against exact original events, not merely the total NAV.
Entry candidates join complete decision timestamps; absent candidates stay null.
The reader projects each ready run once under concurrent requests, while loading
does not block requests for the saved evidence. Publish a reviewed new package intentionally, preserve prior
versions and update the manifest/checksum and contract. On disk the package is
immutable during one reader's lifetime; restart the local API after publishing.
The exporter also supports a single gzip output for local audits. Transport
splitting changes no schema, study results or API response. Unsafe/duplicate part
paths, missing or corrupt bytes and excessive sizes are rejected; publication
does not bypass the repository's single-file size check.

History discovery uses `task_catalog`, report/mission and registry, optional
`research_result.json`. Re-export after a new report is published. New studies
appear without editing a frontend list. `research-presentation.v1` can add plain
title/conclusion to discovered tasks only. An optional `category` is `research`
or `infrastructure`; absent values preserve legacy research entries. The HTTP
history projection reads this presentation-only policy on each request and excludes explicitly
classified infrastructure tasks from investment research, while keeping their
original package rows, reports and verdicts intact. It also overlays display
titles/conclusions without regenerating the saved package. Every projection first
restores its baseline, then applies only the current metadata. Removing a metadata
entry or field removes the earlier display rewrite, section and draft judgement;
formal outcomes, report paths and evidence identities remain intact.
`originalSummary` is the unchanged saved summary. Future exports preserve
`originalTitle` before any display overlay; `savedTitle` exposes that baseline when
the current display name differs. Metadata cannot add a task absent from the package.

The legacy package lost 18 pre-overlay titles. It is not rewritten to invent them.
`research-history-title-origins.v1.json` supplies the headings of all 53 linked
reports/missions at Git revision `2bac4afbcbcf10833a7147686366a16f1204eb76`.
These are explicitly **report-version headings, not recovered legacy export titles**.
Each row contains `title`, exact `sourcePath` and SHA-256 of that revision's Git
blob. The sidecar includes `sourceRevision` and `historySha256` of the original
saved `researchHistory` encoded as UTF-8 JSON (`ensure_ascii=False`, sorted keys,
compact separators). The reader verifies the binding, complete linked-task set
and row shapes before using it. It is bounded by the transport part-size limit.
An explicitly requested missing or corrupt snapshot fails closed for history only.
Custom packages do not inherit the production snapshot implicitly.

Without a snapshot, a legacy title lacking a saved baseline is explicitly unknown;
the task ID is shown and its previous display name remains a search alias.
Mission-only entries restore the planning notice, never claim a result. The original
package bytes, statistics and financial records remain immutable. Rebuild a new
sidecar for a reviewed new package rather than reusing a mismatched one:

```powershell
uv run --no-sync python -m scripts.export_history_title_origins --package research_web/public/data/saved-research-studio.manifest.json --revision 2bac4afbcbcf10833a7147686366a16f1204eb76 --output .tmp/history-title-origins-next.json
```

The producer reads exact Git blobs, rejects paths outside each task's report/mission,
and refuses an existing output. Publish its bytes/checksum with the corresponding
package receipt after verification; the title snapshot is presentation provenance,
not newly computed research evidence.
An optional `section` is `method`, `market` or `design`; absent values default in
the UI to methods. Descriptive catalogs/classification and method-design tools
stay accessible in their own views. Search spans all views and saved summaries.
A specified missing or invalid
policy fails closed as 503. The source SHA at the top describes the imported plain
summaries; the infrastructure category is separately justified by its task mission
in `sourceNote`. Changing display categories does not require a backtest or package
re-export. Draft labels cannot change a formal
verdict or owner adoption. Main cards use formal outcomes only; missing formal
outcomes are explicitly unjudged, not inferred failures or completed studies.
Unconfirmed rewrites have a shared notice and pending detail in the expandable
evidence; original
summary/path and registry IDs are retained. Task-ID dates are labelled as research
record dates, not certified completion dates. Discovery is not certified complete.

Package readers validate required v1 containers and every row before caching;
this is a structure check, not a re-evaluation of original financial results.
Malformed shapes are `503` with `X-Research-Evidence-Error: integrity`;
filesystem read failures are `503` with `unavailable`. Missing run/trade/account
resources remain `404`. Failed reads do not cache partial state, allowing repaired
files to be retried. Nullable evidence and additional fields remain intact.
Exposure weights are null when recorded account equity is nonpositive, since a
meaningful allocation ratio cannot be calculated; the account record stays readable.
The allocation renderer treats a date with incomplete membership or any missing
required weight as a whole-date gap; it preserves its position and click-through
account audit. Known zero values remain zero. Area and expanded-line views do not
connect known observations across unknown dates or estimate the missing balance.
Links from saved participation and latest-market summaries explicitly specify
`threshold=100&mode=launched`; valid explicit map-link options override retained
controls, while absent or invalid options leave those controls unchanged.

Code-only display names may be supplemented from the verified market catalog
only when that provider supplies both a usable name and its catalog identity.
The supplemented name carries `security-name-catalog:<catalogId>` and the basis
`catalog-snapshot-display-name-not-historical-classification`. Existing named
source evidence, price provenance and the immutable saved package remain intact.

## Local startup memo

`.tmp/opportunity-web-startup-cache-v1` is disposable performance state. Before
reuse, the reader verifies 6,050 currently referenced source bytes against the
external pinned manifest, plus reader/native/bridge implementation and actual
runtime fingerprint. Only successful full-reader results mint an HMAC-bound
memo. Invalid source bytes fail closed; absent/corrupt/different memos rerun the
original semantic and exact query-table checks in one background worker.
Compressed files are bounded at 96 MiB and decoded content at 512 MiB.

The local authentication key belongs to this installation; the memo is not
independent scientific evidence or protection against an actor with control of
the installation. Neither memo nor key belongs in Git. CLI query/build gates do
not opt into this web cache. No shared source artifact, scheduler or producer
database is written.

## Limits

These periods have been viewed; development screening is not final validation or
owner adoption. Trades are simulations. Market labels are retrospective candidate
waves, with delisting/universe, early adjustments and classification limitations
from the existing catalog. Historical ETF holdings remain incomplete and are not
invented. Future daily-rank recording is delegated separately; current absence
remains visible. This package supports inspection, not claims of a validated new
strategy.
