# Shared research data entry v1

`research-data-catalog.v1` is discovery metadata. Existing price, feature,
market-context and historical study readers remain the authority for payload
validity. This entry does not approve a strategy or a market calculation.

## Location and isolation

Set `STOCK_RESEARCH_DATA_ROOT` to an explicit absolute primary
`research_data` directory. In this installation it is
`D:/Project/stock-research/research_data`. No drive is hard-coded in the API.
Its parent must have a real `.git` directory. A linked worktree's `.git` file
cannot establish a primary root. Neither `.worktrees` nor `.tmp` can contain
the configured root. A worktree must not contain even an empty `research_data`.

`DataRoots` validates both its constructor and environment adapter. Artifact
paths use portable relative names, with additional Windows device-name and
trailing-dot/space restrictions. Every ancestor is checked before resolving any
alias; symlinks, NTFS reparse points and regular-file link counts above one fail.
The worktree check walks without following directory links and fails on scan
errors. It conservatively rejects all filesystem aliases, even unrelated ones.

These are application checks at the time of inspection. They are not OS access
control, protection against a concurrent malicious path replacement, or backup.
One writer owns a task worktree; inspect it again immediately before removal.
Removal must target that exact disposable checkout, never primary, a shared
root, or an ancestor containing either. Read-only published files are extra
protection: the Windows deletion test also passes with writable shared files.

Mutable producer inputs still use physical worktree snapshots. The existing
post-checkout hook, producer code, producer data and schedules are unchanged.

## Catalog and versions

The sole machine discovery source is `research_data/catalog.json`. It points to
an immutable `catalog-snapshots/<digest>/catalog.json`. That snapshot and its
generated README are published with the existing no-replace primitive. The root
README is a generated view, not a second hand-maintained list. Dataset reads
pin `data_id`, `version_id` and the external manifest SHA256. A changing catalog
pointer never changes a pinned dataset. There is no `latest` dataset read,
implicit computation, or silent fallback.

Each entry records kind, definition, parameters, input identities, declared
stock scope, raw-input period, indicator-valid period, complete-label period,
unknown/missing limitations, status, manifest scope/path/hash and backup status.
Unknown periods have explicit reasons rather than borrowing the input period.
`complete` means complete for the declared scope: the 0050 benchmark is not a
full-market dataset. The 25-stock price demonstrations are `partial`; 2019-start
study versions are `legacy` and cannot satisfy the new 2010 study or be joined
to a separately calculated 2010–2018 prefix.

Manifest paths are relative to either `data` or `primary`. The latter allows only
`tasks/` and `research_cache/` and is read-only registration of existing locations.
No dataset moves or duplicate data are needed. `metadata_only` registrations
verify the manifest pin only; their original contracts/readers remain necessary
to validate or read payloads. They are explicitly not a new certified read API.

Registry updates use an exclusive writer lock. Conflicting metadata for an
already registered version is rejected, with the unsuccessful lock retained for
diagnosis. No automatic lock removal or overwrite of immutable versions occurs.

## Interfaces

```powershell
$env:STOCK_RESEARCH_DATA_ROOT = 'D:/Project/stock-research/research_data'
uv run python -m scripts.research_data catalog
uv run python -m scripts.research_data register-existing
uv run python -m scripts.research_data verify DATA_ID VERSION_ID --manifest-sha256 EXPLICIT_SHA256
uv run python -m scripts.research_data context VERSION_ID --manifest-sha256 EXPLICIT_SHA256 --layer past_only
uv run python -m scripts.research_data check-worktree ABSOLUTE_TASK_WORKTREE
```

These are per-process settings, not machine/global changes. `DataCatalog.get`
also accepts expected input identities and a definition version and rejects any
mismatch. `read_market_context` delegates to the existing retained reader.
`publish_bundle` verifies and publishes already produced byte payloads under a
new immutable ID, then registers it. It does not calculate a market table.

Windows device-name rejection includes the COM/LPT superscript digit aliases
documented in [Microsoft's naming rules](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file).
All payload paths are validated before the shared data root or bundle is written.

`build_feature_blocks` delegates to the existing `stock_feature_pool_v2` and
`FeatureBlockStore`, including complete identities, bounded owned Windows
workers and their barrier. It requires explicit calculation authorization and
disposable `.tmp` staging outside shared versions. Identical requests calculate
zero blocks; adding one feature computes only that missing block. This adapter
does not implement a second scheduler, formula library or hash verifier.

## Checkpoint extensions and retained v1 bridge

`plan_extension` distinguishes unchanged stocks, appended dates, historical or
factor corrections requiring a full affected-stock rebuild, and definition
changes requiring all affected outputs to rebuild. It identifies retrospective
tail boundaries such as the last 252 or 10 rows. It never interprets them as
indicator warmup or complete future labels.

`extend_selected` verifies old prepared inputs and outputs against the existing
selected-feature API, replays its exact state, and retains only appended daily
rows and newly confirmed pivots. Old extreme dates can precede the boundary;
confirmation dates determine append membership. Global indices are preserved.
The receipt reports state and verification replay costs. `add_selected` computes
missing columns only; a caller must first verify the original stored manifest,
because schema checks alone do not certify reused values.

The v1 bridge remains available for exact legacy comparisons. New extensions use
`derived_features_chunk_v2.compute_selected_chunk` with JSON checkpoints and
`research_data_incremental.build_incremental_features`. Full initialization and
chunk continuation use the same kernel. EMA, ATR and pivot state carry forward;
SMA and BB reuse the existing v1 formula API on fixed per-period warm context,
at most 120 rows per period. Adding a feature cannot change another's values.
This is a new numerical identity: bounded pandas rolling accumulation can differ
in its last bits from full-history v1. Never reuse or concatenate v1 output under
the v2 identity; new formal studies must preregister and initialize v2 from their
full required input start.

Every stock/feature has a separate sealed checkpoint. Dates append only after
exact prefix-input, factor, implementation and basis checks. Historical or factor
corrections rebuild only the affected stock; implementation/basis changes rebuild
affected outputs. Same requests calculate zero, and a newly requested feature
initializes only itself. Published daily/pivot segments are referenced by fixed
version and manifest pins, not copied or linked. Readers verify declarations,
bounded Parquet framing and both payload and manifest bytes; read failure never
starts calculation. Discovery stays compact: detailed stock state and segment
lists live in the sealed bundle manifest, not the catalog.

Public feature and forward-series builders reuse `cache_execution.execute` to
start a fresh source-captured interpreter. Physical caller-input snapshots stay
in task-owned `.tmp/research-data-execution/`; no shared dataset is copied or
linked. The worker binds all loaded project dependencies to their compiled bytes
and checks them again before publication or reuse. Private in-process helpers
are worker and isolated fault-injection entry points only. A stale notebook
cannot publish old memory formulas with new disk source pins. Every retained
ancestor segment is verified before extending or returning an unchanged version.

`publish_forward_series` applies the original H126/H252 outcome definition or the
retained 0050 context definition. Labels recalculate the last horizon's anchors;
retrospective context revisits the last 10 anchors plus necessary warm observations.
Context event checkpoints preserve launch/resumption history. Unchanged prefixes
reference immutable old files with explicit slice bounds; each update has a new
version, external manifest pin and lineage. Source corrections force a whole-series
rebuild. Price basis, factor identity and calendar are recorded explicitly.

For newly published label bundles, `coverage.complete_label_period` means a
single consecutive calendar run of `main_eligible` rows: a full horizon calendar
and an outcome already resolved under the retained label definition. It is not
just a date-length calculation or a claim that every diagnostic price is known.
No eligible rows or multiple disjoint runs give null bounds with a reason;
`coverage.label_coverage.eligible_label_periods` lists every actual eligible run.
Separate calendar bounds/counts, eligible counts and unknown counts keep full
calendar windows distinct from missing-price outcomes. An early resolved hit
keeps its original eligibility even when a later price is missing. Old manifests
and numerical labels are not rewritten.

Prepared input identities use the existing validator's float normalization,
including nullable Float64/Int64 `pd.NA` as NaN. Original column dtypes remain in
the identity, and missing values remain distinct from zero. The existing feature
gap/reset behavior applies without filling observations.

This verifies mechanisms on invented inputs, including consecutive publication
and readback equal to whole-history recalculation. It is not a measured full-market
throughput claim. The adapters are sequential and do not add a second scheduler;
the existing bounded v2 block worker remains available. New study-specific pattern
states, episode reconciliation and first 2010 full-market datasets belong to the
subsequent approved mission. Bundle/catalog JSON reads are bounded at 64 MB and
Parquet uses the existing evidence limits; larger scopes require partitioning,
not disabling those limits.

## Preservation and backup

`artifact_backup.default_sources` now includes `research_data` alongside existing
cache and formal task scopes. The existing content-addressed backup and new-target
restore verify bytes. Catalog entries accurately retain unknown backup state for
their exact versions; backup scope inclusion is not a backup receipt. No new
backup run or schedule is implied. Same-disk backups do not protect disk failure.

## Retrieval and research boundary

Git carries code, this contract and the handoff record, not `research_data` or
bulk quote/feature tables. `register-existing` skips absent local artifacts and
does not manufacture data on a fresh clone. Acquisition remains producer-owned.

The first 2010-onward full-market versions and pattern-scan Q1–Q6 remain subsequent
research work. Owner merge of its fixed mission is required before any new market
feature, event, label or outcome calculation. The handoff's 2010 requirement is
new scope; existing PR #7 and #9 explicitly fixed a 2019 period, and this work
does not attribute that choice to migration data loss.
