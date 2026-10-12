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

`build_feature_blocks` delegates to the existing `stock_feature_pool_v2` and
`FeatureBlockStore`, including complete identities, bounded owned Windows
workers and their barrier. It requires explicit calculation authorization and
disposable `.tmp` staging outside shared versions. Identical requests calculate
zero blocks; adding one feature computes only that missing block. This adapter
does not implement a second scheduler, formula library or hash verifier.

## Extension bridge and remaining requirement

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

**This bridge is not the efficient daily continuation requested in handoff
10.10a.** The retained numerical API has no state checkpoint, and repeating its
full calendar is necessary for this exact bridge. Checkpoint continuation, actual
retrospective-tail execution, price-factor rebuild orchestration and immutable
extended-bundle publication remain to be implemented and verified together.
No daily increment performance claim or all-kind extension completion is made.

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
