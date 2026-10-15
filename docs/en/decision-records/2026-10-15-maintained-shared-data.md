# 2026-10-15: Maintained shared derived data outside the repository

**Status:** owner decision, 2026-10-15. Follows
[drop input sealing](2026-10-15-drop-input-sealing.md), which already declared caches
performance-only and rebuildable.

## Decision

Reusable derived research data is **one maintained copy per definition**, kept current
by whoever needs fresher data, instead of a new hash-named immutable version for every
input change.

- **Location.** A shared root outside every checkout, set by
  `STOCK_RESEARCH_SHARED_ROOT` in the process environment or the primary checkout's
  ignored `.env.local` (`research_core/shared_data.py`, same resolution as the producer
  root, no fallback). A root inside the primary checkout or a worktree is refused.
  Chosen location: `D:/StockData/stock-research`, beside the producer's
  `D:/StockData/stock-data-downloader`.
- **Layout.** `<root>/derived/<family>-v<N>/`. The definition version is in the family
  name; a changed definition gets a new family directory, never an in-place rewrite.
- **Updates.** An update builds a complete new generation, then flips `current.json`
  atomically. The previous generation is kept for rollback; older ones are deleted by the
  updater. A failed update leaves `current.json` untouched.
- **Studies.** Record the generation they read (family, generation id, as-of date, file
  SHA-256) in their `run_receipt`. They do not pin or copy the data. A later update does
  not invalidate a finished result; rerunning uses current data, per the sealing decision.

First family: `adjusted-daily-v1`, full-market daily prices in three bases (`raw`,
`permanent_adjusted`, `reference_factor_adjusted`) from `price_basis.prepare_prices`
(`price-basis.v2`), maintained by `uv run python -m scripts.maintain_adjusted_daily update`.
Contract: [research-derived-data.md](../research-derived-data.md#維護中的共用衍生資料).

## Why not hash-named versions

Measured 2026-10-15: one full-market generation is 6,764,521 rows per basis over 2,077
symbols, 768 MB in the new single-file-per-basis layout, built in 9.4 minutes. The old 25-symbol `price-bases` version was 23 MB, so a full-market copy in that
per-symbol layout would be about 3.3 GB. Every daily producer update changes the inputs,
so a hash-named version per update grows by roughly a gigabyte each time for data nobody needs to
recompute bit for bit. A new ex-dividend date also restates the whole earlier history of
that symbol, so "append only the new day" is not correct for adjusted prices anyway.

## What this retires

The owner approved deleting the existing hash-named `research_cache` versions on
2026-10-15:

| Path (primary checkout)                                    | What it was                                 | Cited by tracked files                                               |
| ---------------------------------------------------------- | ------------------------------------------- | -------------------------------------------------------------------- |
| `research_cache/price-bases/39c540d5…`, `…/71928e94…`      | 25 demonstration symbols, cutoff 2026-08-14 | none (catalog entries only, retired)                                 |
| `research_cache/input-snapshots/architecture-v1-25-cases/` | frozen inputs of those 25 cases             | `tasks/20261008-research-data-architecture/report.md`, as provenance |

That report's numbers stay readable as a historical record; they can no longer be
recomputed from the same bytes, which the sealing decision already accepts. Both
directories are Git-ignored, so the deletion is an owner-run step after merge, not part of
the pull request. `research_core/derived_cache.py` and `scripts/build_research_cache.py`
stay as code for reading any remaining or restored version.

## Not changed here

- The `research_data/` catalog of study bundles (annual-rotation, legacy task datasets)
  stays in the primary checkout. Worktrees already read it through
  `STOCK_RESEARCH_DATA_ROOT` without copies. Moving it under the shared root is a
  separate change because `DataRoots` ties it to the primary checkout.
- Producer acquisition data, its schedule and its backups.
- Frozen task evidence and SHA-pinned code.

## Setup after merge (owner or main session, outside 18:00-18:45)

```powershell
New-Item -ItemType Directory D:/StockData/stock-research
Add-Content D:/Project/stock-research/.env.local "STOCK_RESEARCH_SHARED_ROOT=D:/StockData/stock-research"
uv run python -m scripts.maintain_adjusted_daily update
uv run python -m scripts.maintain_adjusted_daily status
```

Then retire the two `price-bases` catalog entries with `scripts.research_data retire`
and delete the legacy directories listed above.
