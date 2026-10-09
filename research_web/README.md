# STOCK research studio

React + TypeScript + Vite. The default entry is the retrospective opportunity
explorer, a saved-research library and the dated ETF field guide. The earlier K-line viewer remains available at
`?legacy=1`. This is a local research interface; it does not run backtests.

## Start

The normal website entry is `http://127.0.0.1:5177/#home`; the opportunity map
is `http://127.0.0.1:5177/#market`. From the intended checkout root, use the
launcher to start both services or reuse verified services from that checkout:

```powershell
uv run python scripts/start_research_web.py
```

Keep the launcher running. Use `--no-browser` when the browser is already open,
or `--check` to inspect both services without starting anything. Logs are under
`.tmp/research-web-launcher/`. An old temporary preview URL on port 8518 is not
this launcher's entry; use 5177 instead. Do not terminate unknown listeners.

The default `#market` reads the frozen 2010-onward catalog through a dedicated,
read-only history API. Both the API and Vite must run during development.
`npm run dev` starts Vite only. A 502 response from `/history-api` means
the frontend cannot reach its separate API; first check that port 8517 is
listening in the intended checkout. Starting Vite again cannot restore it.
The saved-run library and retained eight-case preview use bundled static
artifacts and can be viewed without this API.

The large catalog/native bundle is local evidence, not restored by Git. If it
is missing, restore **the existing frozen producer task**, from the repository
root, before starting the API:

```powershell
uv run python -m scripts.restore_opportunity_history --source <existing-producer-task-directory>
```

The source must contain `catalog-v2` and `runs/native` for the pinned snapshot.
For this development handoff, that task is
`D:/Project/Stock/.worktrees/sector-wave-full-history-preview-20261004/tasks/20261004-sector-wave-full-history-preview`.
The command verifies all saved evidence before physically copying it to a new
consumer destination. It refuses an existing destination, links/junctions,
changed bytes and a different snapshot. It does not download prices, rerun
methods or alter the producer. Preserve the original producer copy; Git cannot
recreate it if both copies are lost. A failed copy stays visible for inspection.

In terminal 1, from the repository root:

```powershell
uv run --group viewer python -m uvicorn research_api.main:app --host 127.0.0.1 --port 8517
```

Keep that terminal running for the preview's lifetime. For an agent-delivered
Windows preview, start the API independently of a temporary command session.
From the repository root, after checking that 8517 is free:

```powershell
$historyRoot = (Get-Location).Path
New-Item -ItemType Directory -Force .tmp | Out-Null
$historyLog = Join-Path $historyRoot ('.tmp/history-api-' + [guid]::NewGuid().ToString())
$historyProcess = Start-Process -FilePath (Get-Command uv).Source -ArgumentList @('run', '--group', 'viewer', 'python', '-m', 'uvicorn', 'research_api.main:app', '--host', '127.0.0.1', '--port', '8517') -WorkingDirectory $historyRoot -WindowStyle Hidden -RedirectStandardOutput ($historyLog + '.out.log') -RedirectStandardError ($historyLog + '.err.log') -PassThru
$historyProcess.Id
```

This starts only the read-only API and does not register a scheduled task or
restart it after Windows exits. Preserve the process ID and logs in the local
handoff. Do not stop another checkout's process or reuse an unknown listener.
After startup, use the page's retry button; the first request still performs
the full saved-evidence verification described below.

In terminal 2, from this `research_web` directory (Node 24+):

```powershell
npm ci
npm run dev -- --host 127.0.0.1 --port 5177 --strictPort
```

Open http://127.0.0.1:5177/#market. Initial native-evidence verification can take
several minutes; the stronger original-source gate measured about eight minutes
locally. The page reports that state before opening the timeline. The accepted
snapshot remains in memory for subsequent frames; restarting the API repeats
the verification. This startup measurement is not a replay frame-rate estimate.
If the catalog is unavailable, its error panel links to `#market-preview`, the
bundled eight-case preview, with its separate scope. Restart the API after
restoring a previously missing bundle. Vite proxies `/history-api` to 8517.
A production build served by `research_api.main` uses the same routes directly.

For the optional old research query interface,
start `scripts/research/open_research_api.cmd` from the intended checkout.
The dev server proxies `/api` to port 8517 by default; set
`RESEARCH_WEB_API_TARGET=http://127.0.0.1:8503` for the optional old API.
`VITE_API_BASE` can override the frontend request base.

## Opportunity explorer and saved research

`/#market` covers the saved 2010-01-04 through 2026-10-02 snapshot: 1,970 eligible
stocks (1,942 main-board and 28 innovation-board). Membership and representative
waves come from the producer's saved retrospective intervals, including early
dates before a future qualifying wave has risen. Zero/unknown gain is retained
in the table without an invented positive map area. Areas use the same fixed
gain-squared scale across dates; overview changes the camera only. Colors show
observed gain, not an approved phase classification. Current industry grouping
is explicitly retrospective, with historical validity still unconfirmed.
Each stock opens its saved price path, six method/scale records and native
candidate/phase overlays. Saved trend fits are not recomputed. Initialization
checks saved evidence with the original pure source functions without writing
the producer's artifacts.
Rules remain preliminary; 2010–2012 adjustment quality, missing identities,
historical classification and full-market holdings comparison remain incomplete.
See the consumer [report](../tasks/20261005-market-full-history-web/report.md).

The retained `/#market-preview` uses launch-to-confirmed-end membership, fixed cross-date gain area,
organic industry/stock cells, shared-date history ribbons, pinned comparisons
and evidence drilldowns. Default historical input is **eight selected cases**,
not a full-market catalog. Its selected representatives/launches remain fixed
across dates. The data source control also exposes **36 fictional stocks and 21
fictional portfolios**, clearly marked synthetic, to review richer interactions.

`/#research` exposes two saved real candidates, their methods/verdicts, all
2,432 daily NAV observations and all 1,017 original events. The candidates remain
exploratory/failed. Replaying stored accounting does not rerun a strategy or
approve it. Version 2 explicitly retains the source's ten named modeled marks
(eight/two in the two runs); these estimates are not same-day observed quotes.
Raw account marks are not the adjusted price series used for the
opportunity overlap diagnostic. Receivables/claims remain separate from cash.

The website and CLI share `src/domain/opportunities/model.ts`:

```powershell
node --experimental-strip-types scripts/compare-opportunities.mts --input public/data/research-evidence-v2-classified/opportunity-explorer.json.gz --date 2021-04-29 --portfolio stock:20261002-add-retry:normal-v1 --output ../.tmp/inspection-new.json
```

Output paths must be new. The UI can export the same uncompressed bundle and a
dated review JSON; the CLI accepts JSON and gzip. Exact quote dates are required.
Unknown is not zero. The independently named
`close_exposure_positive_return_overlap.v1` is a close-holding/positive-return
date diagnostic, not actual profit, execution attribution or a research gate.
See [opportunity contract](../docs/en/opportunity-presentation.md) for semantics,
scope, source ownership and reproduction.

The explorer and saved-run packages formerly in `public/data/` and
`public/data/research-evidence-v2-classified/`, the split studio package, and the
two price fixtures are now private external inputs. Original bytes are preserved
outside Vite public/dist; hashes and restoration instructions are in
`<primary-checkout>/StockProject/data/private-presentation/20261008-first-stage/restore-manifest.json`.
The default `public-synthetic` mode generates deterministic fictional data from
code. It requires no private package or market download. This first separation
stage does not remove other research datasets or historical Git objects, and
does not establish that the repository is safe to make public.

For local private viewing, configure both processes explicitly before launch:

```powershell
$env:VITE_ARTIFACT_MODE = 'local-private'
$env:STOCK_RESEARCH_DATA_MODE = 'local-private'
$env:STOCK_PRIVATE_ARTIFACT_ROOT = 'D:/Project/Stock/StockProject/data/private-presentation/20261008-first-stage/research_web/public/data/research-evidence-v2-classified'
$env:STOCK_SAVED_STUDIO_PACKAGE = 'D:/Project/Stock/StockProject/data/private-presentation/20261008-first-stage/research_web/public/data/saved-research-studio.manifest.json'
```

These paths are server-side absolute external locations; their `public/data`
suffix records original relative paths and is outside the served Vite tree.
The frontend reads allowlisted JSON routes at `/api/private-artifacts/v1/`.
The studio reader verifies all split part sizes/SHA and the whole compressed
stream. Missing, corrupted or unconfigured private data returns unavailable;
private mode never substitutes demonstrations. Do not copy private packages
into Vite public. The build guard rejects the seven removed public candidates
even when Git ignores them. Restore only to an external private location after
verifying each manifest hash and size.

To reproduce the private research joins, apply the
reviewed classification packet to the base preview first, then export the saved
ledgers with `export-research-evidence.mts` into that new directory. Its receipt
records adapter version 2 and unchanged native-ledger identities. The input
preview preserved in the external backup retains its source identities.
Rebuilding the joined package additionally requires the reviewed native-ledger
directory and receipt supplied by the research chat; those exports remain local
and are not restored by a fresh Git checkout.
The HTML/JS application does not fetch arbitrary local paths or execute agent
HTML. New research enters through validated JSON adapters.

## Prepare the legacy historical atlas

The following window-based renderer remains available only at `/#market-legacy`.
Its selection and date-normalized areas are not the new explorer definition.

The versioned `market-atlas.v1` presentation projection lives at
`public/data/market-atlas.json` (ignored). It is generated from a verified
sector-wave catalog and the matching **read-only source snapshot**, never from
an arbitrary latest cache. From the repository root:

```powershell
python -m scripts.export_market_atlas --catalog <catalog-v1-directory> --source-root <matching-data-directory> --output research_web/public/data/market-atlas.json
```

The output must not exist and cannot be inside either input directory. Source
identities are checked before and after reading; the exporter validates the
manifest and chunks it consumes, not every table in the research bundle. It
does not download data, mutate caches, evaluate strategies or open sealed work.
Preserve an existing projection under another name before generating a new one.

The current local projection contains 1,942 catalog securities and 1,849 official
sessions, 2019-01-02 through 2026-08-14. It is not a point-in-time investable
universe. Its 2026-10-01 classification snapshot is retrospective. Dates without
quotes stay null, known dated quality findings suppress affected windows, and
permanent price adjustments do not include cash-dividend reinvestment. The
explicit demonstration mode uses invented names, prices and market caps.

## Legacy atlas presentation rules

- A common 63/126/252/504/756-session or custom start applies to every security.
  The map, evidence drawer and table display the exact calculation dates;
  peak mode identifies each security's highest-close date separately.
- Positive gain determines equivalent diameter: 2x gain means 4x area. With
  verified historical capitalization, every 100x cap multiplies area by 1.25.
  Missing historical cap disables weighted mode for the real projection.
- Sector area is the sum of constituent weights using one stable primary
  membership; its label shows the member with the largest gain. Multi-membership
  remains available in stock evidence. No sector is specially boosted.
- The atlas displays up to 28 groups or 32 securities at or above +100% by
  default (price doubles), with +60/+80/+100/+200/+400/+900% options. This is a
  visual filter, not a research acceptance threshold. The table/export retains
  all observations. The viewport is normalized separately for each date, so
  areas describe relative opportunity weight on that date.
- Rounded curved cells preserve final relative areas within 2%; interpolation
  is a transition, not a quantitatively exact intermediate frame. Disappearing
  cells collapse with a small burst; related newcomers grow from a shared
  neighbor. Reduced-motion preference and a user switch disable transitions.
- The outer silhouette is a nearly symmetric organic ellipse. Geometry runs in
  a module worker with one active calculation and one replaceable pending date;
  completed frames paint while rapid input replaces obsolete pending work.
  Labels are measured once per layout, not every animation frame. Pending maps
  identify their own date range and temporarily disable evidence selection.
- Peak mode explicitly means retrospective highest close within the window;
  it does not describe an achievable sale or known signal.

## Wave annotation laboratory

Open `/#wave-lab` for the bounded retrospective comparison. It starts with the
owner's synthetic consolidation/relaunch example. Eight real inspection cases
and eight explicit synthetic controls share a price chart, method overlays,
phase strips, candidate launch ranges and independent small/large waves.
The same chart is reached from a preview stock's detail button; full-history
stock details use its saved native methods instead of recomputing them. The old
hash remains valid; it is no longer a main navigation tab. Detail refits are
exploratory comparisons and do not replace the frozen map selections.

Reuse the verified atlas projection, without downloading or rebuilding it:

```powershell
node scripts/export-wave-lab.mjs --input public/data/market-atlas.json --output public/data/wave-lab-cases.json
```

The ignored output must not exist; preserve it under another name before
regeneration. Source SHA-256, catalog identity, exact case dates and quality
flags travel with each case. Missing real data leaves synthetic controls usable
with an explicit notice. This slice is not the planned 2010-onward inventory.

Methods are provisional: penalized independent log-price lines and first-order
trend filtering, with three declared sensitivity settings. Computation runs in a
module worker and stale case requests are terminated. Mouse/touch and keyboard
move the cursor; zoom, layers, price basis and axis controls remain client-side.
Feedback stays in browser storage; the download includes prices, source identity,
rule version, numerical results, view selection and that case's feedback.

Method code, contracts, synthetic controls, chart and page are separate under
`src/features/wave-lab/`. This is a development comparison, not the eventual
catalog schema. No historical ETF/strategy participation is inferred.

## Code ownership and extension

- `src/app/`: navigation, shared color/appearance tokens and shell. All pages
  inherit these tokens; components must not redefine global theme variables.
- `src/domain/opportunities/`: versioned portable contracts, validation and
  shared browser/CLI calculations; no React or layout dependencies.
- `src/features/opportunities/`: page interactions and evidence presentation.
- `src/visualizations/opportunity/`: pure fixed-area packing, worker queue and
  cancellable transitions; world translation is allowed, daily rescaling is not.
- `src/features/market/model.ts`: versioned projection and deterministic
  observation rules. Keep formulas outside rendering components.
- `src/visualizations/atlas/`: pure geometry, area constraints and animation.
  Replace or add renderers without changing evidence or performance metrics.
- `src/features/research/`: adapter to the existing read-only task API. Explicit
  task selection, saved metrics/equity, paged trade inspection and evidence.
- `src/features/funds/`: dated ETF research excerpts with direct official
  methodology, performance and holdings links. Not a live feed or ranking.
- `src/api/`: existing typed artifact client; `src/components/`, `src/lib/`
  and `src/index.css` support the legacy K-line workbench.

Future agent-generated methods should enter through versioned result contracts
and named renderer adapters (see the research-presentation proposal), rather than
injecting arbitrary HTML or duplicating a page. Keep source IDs, dates, missing
reasons and drilldowns in every adapter. New measures need their own displayed
definition; visual weights must never become investment returns or coverage.

## Current data boundaries

The 2019 start belongs to the pinned catalog mission, not the entire local
price archive. A read-only check on 2026-10-03 confirmed the primary archive's
official-source rows span 2010-01-04 through 2026-10-02; the matching catalog
snapshot ends 2026-10-01. All three shipping securities (2603/2609/2615) have
official history beginning 2010-01-04. Extending this atlas before 2019 requires
an explicit presentation projection and coverage/quality validation; it must
not silently expand the frozen research mission or imply a historical
point-in-time universe. The current website has not made that extension.

Historical cap and full daily ETF holdings are not available in this slice.
Known industry snapshots are retained with their original observation dates.
Three explicit fiscal-2021 business groups use company-document evidence, labelled
as retrospective and kept separate from historical exchange membership. Expand
the stock card's classification evidence to inspect broad labels, multiple roles,
document periods and source links. Undated and event-only observations remain
references. The receipt-checked supplement and consumer selections are documented
in `../docs/en/opportunity-presentation.md` and
`../tasks/20261004-opportunity-classification-fix/`.
The new explorer uses pure gain area; cap fields are reserved and not applied.
Six ETF references retain unknown holdings rather than fake zero allocations.
In explicitly configured `local-private` mode, the two native strategy histories
have reconciled daily positions; only
dates and securities supported by both contracts enter comparison. Six ETF excerpts are
dated 2026-10-01, with their individual source dates and definitions visible.
The optional old query interface still lists only tasks supported by its running
API. The default saved-run library uses independent fictional `public-synthetic`
controls. Viewing the two named native runs requires explicit `local-private`
mode and the external private data paths documented above. In that mode,
condensed rules link to their complete source missions; unrecorded decision
reasons are never generated.

Use `npm test`, `npm run build` and `npm run lint` for frontend verification.
The Python export fixtures are in `scripts/tests/test_export_market_atlas.py`.
Production assets must be rebuilt after source changes; an existing `dist/`
does not automatically refresh. This preview has no public deployment.
