# Local stock-research bootstrap

This is a local candidate, not a published repository or release clearance.
No old checkout/folder, Git history, remote setting or production schedule was changed.

## Selected source and preservation

- Pinned old main: `7f79585da2730fd01075839fbcc973d0090e1ae2`.
- Completed synthetic/private separation: `02ba5e2c2cd097acd8c1e4c7eb5b44dac2c3a9d1`.
- Initial-push CI overlay: `7dac8ecb1fe6182beb828db6172d792c11ea7396` (workflow,
  `scripts/ci_scope.py`, and its functional tests only).
- PR #38 and #40 are excluded from the initial source; their old branches/diffs
  remain untouched for the owner's later Codex PR requests.
- New public downloader: `TaiwanCCyoyo/stock-data-downloader`, root/main
  `8795859880eef99c0968fc6c3bca4863743003d2`; the compatibility submodule path
  remains `shioaji_stock_prices`. Only code is initialized; no live data is copied.
- PR #43 final scanner/docs corrections remain pending.
  Do not publish with an unverified scanner.

The original 1,526 regular source files (27,041,930 bytes) are individually hashed
in `D:/Project/Stock/StockProject/data/private-presentation/stock-research-bootstrap-20261009/preservation-manifest.json`.
The matching source-tree TAR preserves every original byte, including docs and
fixtures. Restore it only to a separate private directory and verify that inventory;
never overwrite another working tree. The nine earlier presentation originals
remain in `D:/Project/Stock/StockProject/data/private-presentation/20261008-first-stage/`.
Their preservation receipt remains valid. No ignored live producer data was copied.

## Minimum necessary content decisions

There is no evidence that all real market data must be excluded. Unknown source
rights are recorded as unknown, not relabeled as restricted. The source candidate
retains research methods/results, schemas, classifications, source URLs, hashes,
receipts and existing research archives unless a specific secret/private/restricted
content finding requires a narrower edit. No entire tasks or fixtures directory
is removed. The nine external presentation files are not copied back into served
public: this preserves the completed default-mode separation, and is not a finding
that these files are permanently prohibited from redistribution.

| Location/source chain                                           | Candidate decision                                                            | Evidence still needed                                                                                                             |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `fixtures/classification-v1/`                                   | Keep classification, references, short observations, source URLs and receipts | Do not alter raw source bytes without regenerating receipt contracts                                                              |
| sector-wave catalog `price_daily.parquet` provenance            | Keep existing research archive as a review candidate                          | Mixed official-priority/Shioaji-gap rows need row/source attribution; do not call it all official or all restricted               |
| market-context-v2 0050/calendar/source manifest                 | Keep existing context and provenance                                          | Specific archived price-feed attribution remains unknown                                                                          |
| native saved results and nine external presentation files       | Keep original private bytes, use synthetic default                            | Modeled research trades are not actual broker accounts; mixed inputs need source mapping before any later redistribution decision |
| official daily acquisition endpoints                            | Preserve code and source pointers                                             | Match exact retained artifacts/rows to the licensed feed before claiming coverage                                                 |
| `docs/en/fork-maintenance.md`                                   | Replace personal Windows account segment with `<user>` in candidate only      | Original file hash/bytes retained in preservation inventory                                                                       |
| credentials, ignored producer data, local caches and old `.git` | Not imported                                                                  | Existing old repository/data remain untouched                                                                                     |

Producer source pointers: `scripts/fetch_official_daily_price.py` uses TWSE
`exchangeReport/STOCK_DAY_ALL` and TPEx `tpex_mainboard_daily_close_quotes`;
historical backfill uses TWSE `STOCK_DAY` and TPEx `afterTrading/otc`.
Company identity uses `isin.twse.com.tw`; value-chain taxonomy uses `ic.tpex.org.tw`.
Those latter sources are not automatically covered by an OpenAPI license.

The official [TPEx stock quote dataset](https://data.gov.tw/dataset/11370)
lists Open Government Data License 1.0 and links its OpenAPI. The
[license](https://data.gov.tw/license) permits redistribution with attribution.
This does not establish that every mixed historical package belongs to that
licensed dataset. Retained relevant official facts should carry provider/year,
dataset/version and license attribution when concrete source matching is available.
Source review date: 2026-10-09 UTC.

## Interfaces and publication handoff

Existing Python modules, `StockProject`, research APIs and frontend interfaces
remain intact; the package identity is `stock-research`. Public-synthetic controls
do not require private inputs. For local-private viewing, configure absolute paths
to the preserved old data as described in `research_web/README.md`; do not copy
private packages into Vite public/dist. Missing inputs return unavailable.

Before an initial root commit is finalized for publication: integrate the final
scanner/doc result, verify the new downloader gitlink and URL, audit the actual candidate tree, verify root
push CI selection and relevant functionality, and obtain the separate publication
approval. No schedule or acquisition is started by this preparation.

## Initial commit verification blocker

The first normal commit attempt did not create a commit. All-files checks expose
existing archived-source type/lint issues, `.secrets.baseline` exceeding the 500 KiB
new-file cap, and formatter attempts to rewrite historical evidence. The 616
automatically modified unadapted files were restored from the verified original
TAR; all 1,518 unadapted source-file hashes now match. No hook was skipped.
The parent must settle the initial-root check boundary for immutable archived
sources before committing/publishing; do not silently rewrite research originals
or exempt them from secret scanning. Detailed local evidence is in
`.tmp/initial-commit-blockers.json`.

Verified candidate behavior before the all-files hook attempt: frontend 345 tests,
related Python/root-push CI 264 tests, lint/build and `uv lock --check` passed.
Existing frontend React dependency and JS chunk warnings remain.

## Follow-up verification and approval boundary

The removed studio package is now represented in the checksum regression by
invented bytes and a temporary approved baseline fixture. The actual secret hook
still accepts an approved checksum and rejects a new value; all four cases pass.
Minimal Python code-only Ruff corrections pass, and two scripts receive typing
declarations without changing their runtime objects (seven targeted tests pass).
No scientific results, methods snapshots or original private bytes were rewritten.

The all-files pyright hook reports 450 diagnostics across 132 files, primarily
historical task imports and pandas types. Mypy stops on duplicate historical
module names. A global search path for same-named task modules is not a safe fix.
These are recorded limitations, not a passing initial-push check.

Automatic approval review rejected broader evidence-format exclusions and a
large-file exception for `.secrets.baseline` as an unauthorized persistent
weakening of hooks. Neither change was applied. Existing checks remain in place;
commit/publication is pending explicit approval for that proposal or a separately
reviewed alternative retaining the checks. PR #43 final verified scanner/docs is
also pending. The new downloader gitlink is already verified and no remote is
configured for this local candidate.

Final Stock suite: 1 failed, 3817 passed, 4 skipped, 3 warnings in 489.36s (0:08:09). The single HHHL builder failure requires git rev-parse HEAD; this local candidate has no initial commit because existing hooks block it. Targeted scripts pyright reports 0 errors/0 warnings and all-files detect-secrets passes. Re-run the HEAD-dependent test after a legitimate initial commit; do not fabricate HEAD or skip the test.

## Removed duplicate legacy documents

Only the following 12 archived delta-spec documents were removed from this candidate. Every Requirement/Scenario is already contained in the linked current canonical spec. Proposal/design/tasks, unique decisions, unfinished items, research results and source originals remain. Exact original bytes and hashes are preserved by the private source TAR and preservation inventory above.

- `openspec/changes/archive/2026-07-06-add-capital-mode-comparison/specs/backtest-runtime/spec.md` → [openspec/specs/backtest-runtime/spec.md](../../openspec/specs/backtest-runtime/spec.md); 7 requirements verified.
- `openspec/changes/archive/2026-07-06-add-capital-mode-comparison/specs/research-dashboard/spec.md` → [openspec/specs/research-dashboard/spec.md](../../openspec/specs/research-dashboard/spec.md); 5 requirements verified.
- `openspec/changes/archive/2026-07-06-update-price-loading-performance/specs/research-dashboard/spec.md` → [openspec/specs/research-dashboard/spec.md](../../openspec/specs/research-dashboard/spec.md); 1 requirements verified.
- `openspec/changes/archive/2026-07-06-update-price-loading-performance/specs/research-trade-query/spec.md` → [openspec/specs/research-trade-query/spec.md](../../openspec/specs/research-trade-query/spec.md); 1 requirements verified.
- `openspec/changes/archive/2026-07-07-add-dashboard-v2/specs/research-dashboard-v2/spec.md` → [openspec/specs/research-dashboard-v2/spec.md](../../openspec/specs/research-dashboard-v2/spec.md); 4 requirements verified.
- `openspec/changes/archive/2026-07-14-add-universe-management/specs/research-dashboard/spec.md` → [openspec/specs/research-dashboard/spec.md](../../openspec/specs/research-dashboard/spec.md); 1 requirements verified.
- `openspec/changes/archive/2026-07-14-add-universe-management/specs/universe-management/spec.md` → [openspec/specs/universe-management/spec.md](../../openspec/specs/universe-management/spec.md); 4 requirements verified.
- `openspec/changes/archive/2026-07-15-add-dashboard-shutdown-control/specs/research-dashboard/spec.md` → [openspec/specs/research-dashboard/spec.md](../../openspec/specs/research-dashboard/spec.md); 2 requirements verified.
- `openspec/changes/archive/2026-07-20-add-data-integrity-checks/specs/backtest-runtime/spec.md` → [openspec/specs/backtest-runtime/spec.md](../../openspec/specs/backtest-runtime/spec.md); 1 requirements verified.
- `openspec/changes/archive/2026-07-20-add-data-integrity-checks/specs/research-api/spec.md` → [openspec/specs/research-api/spec.md](../../openspec/specs/research-api/spec.md); 1 requirements verified.
- `openspec/changes/archive/2026-07-20-add-data-integrity-checks/specs/research-dashboard-v2/spec.md` → [openspec/specs/research-dashboard-v2/spec.md](../../openspec/specs/research-dashboard-v2/spec.md); 1 requirements verified.
- `openspec/changes/archive/2026-08-08-retire-codex-notion-research-report/specs/research-task-workflow/spec.md` → [openspec/specs/research-task-workflow/spec.md](../../openspec/specs/research-task-workflow/spec.md); 1 requirements verified.

## Latest current-code verification and finite cap approval

Later owner approval is specific: only root `.secrets.baseline` is capped at 1 MiB, while other added files retain upstream 500 KiB and LFS behavior. The existing v6.0.0 hook now invokes `scripts/check_added_large_files.py` in its upstream Python environment. Supplied baseline modifications are also checked; nested same-named files receive no exception. Secret and formatter settings are unchanged. Dev tooling includes the same `pre-commit-hooks==6.0.0` for type checking; no existing package version was upgraded. No earlier broad formatting exclusions or unbounded file exceptions were applied.

Actual repository cap and all-files secret hooks pass. Nine real-hook cap regressions cover exact/over limits, nested paths, existing files and LFS, while four existing secret regressions still pass. New helper type checking passes. All five original affected current Python files now report zero pyright errors; 40 focused CLI/corporate-action/loader tests pass, including six invented missing-scalar/date-gap cases. Price arithmetic and policies are unchanged.

Only `research_web/src` was normally formatted (149 files). All 345 frontend tests, lint and build pass; existing React/chunk warnings remain. Under the latest preserve-method-bytes instruction, the nine earlier historical-task lint edits were reverted to verified original bytes. Those inherited checks remain diagnostic blockers, not rewritten research methods.

Six precise task environments were tested with a scratch-only config: 124 remaining type errors and zero missing imports. The first absolute-include attempt ignored all files and is invalid evidence. No formal execution-environment or historical check boundary was changed. The 23 ignored original files remain on disk: 22 artifact hashes match preservation, 14 have current consumers, eight have historical/provenance references, and credentials were not read or force-added. This is not a blanket redistribution-license approval.

The earlier initial-commit and full-suite results remain historical evidence; the new finite cap resolves only its size blocker. Final scanner/rights/index and historical-check decisions still precede the first legitimate commit. Re-run the HEAD-dependent HHHL test afterwards; later assertions remain unverified until that run.

## H05 retained-source portability

H05 now resolves its evidence default and retained rotation `features.py` /
`eligibility.py` from the active repository root. Original method bytes are preserved in the retained rotation
`original-source.zip`, with original and current typed-source identities in
`typed-source-provenance.json`. Type narrowing does not change the formulas; module-origin checks and packet SHA validation still apply. An isolated
checkout regression loads those exact files, checks their shared dependency, and
rejects a changed source. Historical source contracts and receipts retain their
original observed paths; they are not rewritten as new evidence.

This corrects code location only. The full H05 closure still requires its named
private scratch evidence under `.tmp/claude-kline`; absent sources fail explicitly.
No private evidence is copied, no market run is performed, and this does not make
the full H05 research packet Git-portable.

## Minimal current research code

The new checkout retains the shared PR36 infrastructure, H05 and its actual
retained dependencies, HHHL v4 definitions/readers, and Studio result readers.
It omits 163 Python files (1,234,695 bytes) from 32 earlier independent studies,
including their two task-local V14 tests. These runners are not needed to read
saved results or execute the current H05/HHHL closure. Reports, results, source
knowledge, raw downloads and private originals remain preserved. The two
unknown smoke/loop studies are retained pending a separate decision.

[The exact omission inventory](omitted-legacy-code.json) records each path,
byte count and SHA256, the original commit and verified private source archive.
The old `D:/Project/Stock` directory and remote Stock-legacy repository are
unchanged; no old-folder cleanup is scheduled. Historical source references in
reports and the draft first-candidate packet identify legacy evidence, not an
executable promise from this new checkout.

To restore an omitted file, obtain that path from `legacyPublishedBase` in Stock-legacy and verify its
`publishedGitBlobDigest`. Apply the individually recorded `restoreWorkingBytes`
line-ending rule to reproduce the saved working bytes, then verify the original
`digest` and byte count. Alternatively, read its exact member from the private
source TAR, which already preserves working bytes. The `sourceCommit` identifies
the local separation export; its branch has not been published.
Verify its byte count and SHA256 against the inventory before writing it under
the new checkout. Restore only the selected files and their documented
dependencies; never extract over an entire existing checkout. Imported legacy
code still needs current verification and a new explicit research packet before
any market execution.

## Retired OpenSpec workflow

The owner retired the 10 repository OpenSpec skills, five OPSX commands and
`openspec/config.yaml`. No pre-commit, CI, initialization or agent hook invokes
OpenSpec; other development checks remain enabled. Do not reinstall these
entrypoints during a starter sync. The exact retired-source inventory is in
[retired-openspec-entrypoints.json](retired-openspec-entrypoints.json); original
bytes remain in the preserved private source TAR. Old Stock and global settings
are unchanged.

Native planning and repository documentation now own durable implementation
handoff. Describe observable behavior, artifact contracts and safety boundaries;
state non-goals for execution, external services and generated artifacts, and
record verification with any skipped checks. Task artifacts remain canonical;
external summaries remain indexes. Research signals use adjusted prices while
execution/accounting use the declared raw-price policy. These existing
constraints remain in AGENTS and the research owner/foundation/data documents.

The 11 historical capability contracts under `openspec/specs/` and unique
archived or unfinished design records remain read-only knowledge references.
Their presence does not enable the retired CLI workflow, authorize market
evaluation or replace current research contracts. This entrypoint removal does
not migrate historical specifications or erase their evidence.

## Current bootstrap verification (2026-10-09)

The earlier diagnostic counts above describe intermediate states. The indexed
Python files now pass the normal Mypy, Pyright, Ruff and Ruff format hooks.
The last complete Python suite ran before the two test-only repairs and reported
3,874 passed, four skipped and two failed. The repaired test contracts now use
the actual configured Mypy entrypoint and a disposable, genuinely committed Git
fixture for the HHHL builder. All 19 related tests pass; production HHHL
provenance and every existing anchor, unknown-value and output-hash assertion
remain intact. This is targeted verification, not a claim that the later full
suite has already passed.

The owner subsequently approved normal formatting and recomputing affected
hashes while preserving originals. All 72 unique affected paths were formatted:
59 JSON, six Markdown, five HTML and two EOF-only title files. JSON objects and
Decimal numeric values are equivalent, with two explicitly recorded current
mission-hash updates. Markdown and embedded CSS/JavaScript parsed ASTs and HTML
DOM, visible text and literal preformatted content are equivalent. Original
bytes remain in the private source TAR and an independently verified local
backup. No new formatter or EOF exemption was added.

[The exact old/new identity mapping](evidence-format-migration.json) records
all 72 paths, semantic proofs, the two current input-hash updates, and why hashes
of unchanged original Git versions or ZIP/gzip members remain valid. Exact LF
checkout rules keep the new current-file identities stable on Windows. Original
catalog canonical hashes, completion receipts, research values and frozen
publication bundles remain unchanged. The normal all-files hooks and final
full-suite/HEAD scanner results are reported separately when completed. This
format migration does not establish redistribution rights or public readiness.

## Standalone canonical data configuration

The verified canonical producer copy is `D:/Project/stock-data-downloader/data`.
Stock does not duplicate this directory into its producer submodule or Vite
public. The local ignored `.env.local` contains only
`STOCK_PRODUCER_DATA_ROOT=D:/Project/stock-data-downloader/data`; it contains no
API credentials and changes no global environment or scheduler.

Load that configuration explicitly for a local API process:

```powershell
uv run --env-file .env.local python -m research_api
```

The shared producer-root setting supplies the query default, API data-quality
report and universe metadata. An explicit CLI `--data-path` also supplies
`symbol_meta.sqlite` from the same directory in both universe-selection paths.
An explicitly configured relative or missing root fails without fallback or
acquisition. With no setting, the existing submodule defaults and unconfigured
CLI loader behavior remain compatible.

Docker uses the same host override with a read-only mount; its process setting
is `/app/data`. Resolve configuration with
`docker compose --env-file .env.local config` before starting a service. No
container, API service or actual-market backtest was started by this setup.
Historical summary data paths remain their original recorded inputs; an
explicit query override retains its existing `explicit_override` provenance.
The presentation default stays public synthetic. Producer root configuration
does not activate private UI packages, download data or authorize a strategy.

The copy receipt at
`D:/Project/Stock/.tmp/new-local-data-copy-receipt-20261009.json` records
15,245 verified files and 42,570,473,861 bytes with zero source changes.
The tracked producer `stock_category.json5` was preserved without overwrite;
its original data copy is in the ignored research-private quarantine.
Original Stock data and backup destinations remain unchanged. Windows job and
downloader backup/environment migration are owned by the separate producer task.

## Public export availability

Source code, synthetic demonstrations and owner-produced research summaries
remain in the public export. Three original source-data artifacts are local
only while redistribution rights remain unconfirmed:

- `tasks/20261005-market-context-handoff/market-context-v2/inputs/0050.json.gz`:
  4,105 daily raw/adjusted prices, OHLC and volume values.
- `tasks/20261009-hhhl-pattern-probability/publication-v1/bundle.zip`:
  an audit sample containing real anchor-close prices.
- `tasks/20261010-hhhl-v4-probability/preparation-v1/bundle.zip`:
  32,848 source corporate-action-factor rows.

Original bytes remain in the old Stock source archive and current ignored local
paths. Independent copies and per-file SHA-256/byte-count restore records are
under `StockProject/data/public-export-originals-20261009/`. Public delivery
uses a fresh Git root, excluding these files and the private bootstrap history.
No scientific receipts or original package hashes are rewritten.

A public clone cannot activate the real 0050 context or reproduce these omitted
inputs. The reader continues requiring its complete 11-artifact package and
original SHA identities; missing inputs fail explicitly. Method/environment
execution requiring that context is unavailable without owner-provided local
inputs. HHHL's original fixed-input identities remain required for real runs.
Synthetic builder/publication tests create their own inputs and preserve their
hash/provenance assertions. Code-only source ZIPs and owner-produced summaries
remain included. HHHL v1's original full ZIP and its detailed summary payload
are not published; its report and manifest retain historical evidence identity.
