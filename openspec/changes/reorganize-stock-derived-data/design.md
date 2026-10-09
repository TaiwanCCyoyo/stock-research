## Context

Implementation is authorized by the owner referencing Claude's architecture review. The selected managed worktree is clean and starts at fetched main `f0cb177`. Claude owns online annotation export; a separate session owns HHHL variants. Architecture does not change historical rules, task results or acceptance criteria.

## Goals / Non-Goals

Goals: one discoverable definition registry, byte-preserved rule versions, one named price API for new research, a minimal reusable cache, and verified non-deleting backup/restore.

Non-goals: migrating every legacy loader; completing owner annotation export; rerunning probability studies; creating a generic trading engine; new schedules; deleting worktrees; overwriting producer data. Producer indicator retirement is a later release after this replacement exists and active consumers are notified.

## Decisions

- `research_core/price_basis.py` accepts one symbol's raw OHLC, normalized corporate-action records, an explicit sorted calendar and restoration cutoff. Output keeps raw values, adjusted values, factors, quality and reasons. Named bases are `raw`, `permanent_adjusted`, `reference_factor_adjusted`; none means captured or reinvested total return. Existing loaders are not rewired.
- Same-kind duplicate factors must agree; one agreed factor applies once. Distinct selected event types on the same ex-date are ambiguous until their combination is evidenced: retain every event and invalidate affected adjusted history, never silently keep the first or assume independent multiplication. Missing/unsupported factors similarly stay visible. Unexplained >=40% adjusted changes are invalid; cash declines on a cash event are explained for the permanent basis. Calendar gaps are not filled.
- ATR14 uses a 14-observation true-range arithmetic seed and Wilder recursion, resetting at invalid/gapped observations. Zigzag preserves the historical ATR reversal rules, emits both extreme and confirmation dates, resets at gaps, and never publishes an unconfirmed endpoint as a confirmed pivot. The no-gap path is checked against frozen source functions.
- Cache v1 is full-version, not incremental. Identity contains content hashes of price/actions/calendar snapshots, formula implementation, basis/cutoff/parameters, missing-data policy and runtime. Root is explicitly supplied, normally `D:/Project/Stock/research_cache/price-bases/<digest>/`. A staging folder is never a valid cache; a manifest is written last, verified, and published without replacing an existing version. Readers verify hashes and do not write. Identical completed versions are reused; incomplete/corrupt versions are rejected, not repaired in place.
- All dependency snapshots required for recomputation are retained inside each version, so worktree deletion does not invalidate the cache. The live producer parquet is never referenced as immutable; worktree research uses a physical frozen input or a verified cache version. Paths reject traversal and symlink/Windows reparse ancestors.
- Backup atomically publishes content objects and immutable inventory manifests with exclusive per-target locks and SHA256 evidence. A separate append-only completion links each retained started attempt to its verified snapshot. Scope includes complete cache versions and explicitly inventoried task datasets/owner annotations, not arbitrary checkout files or credentials. Moving inputs invalidate completion. Restore verifies a complete sibling staging tree before publishing a destination that did not exist; no deletion, replacement or live SQLite copying. D-drive backup protects accidents, not D-drive failure.
- Worktree seeding preserves unmigrated `adjusted_prices/daily` formal read inputs physically, not new immutable cache copies. Its receipts inventory both newly copied and all retained read-set files, including files whose current producer reference is missing. Unknown original provenance stays unknown; observed current producer bytes do not certify original identity or cross-source PIT coherence. Existing inputs are not silently overwritten to make a retry appear aligned.
- Pattern registry separates owners' HHHL versions from atlas proxies, records approval evidence and exact original hashes. Archived rules are inert evidence, loaded only through an explicit checked adapter; historical task zip readers remain unchanged.

## Risks / Trade-offs

- New quality rules can disagree with legacy v4 dropped-gap/unchecked-factor prices -> preserve both, produce bounded event-level compatibility differences, never overwrite old outputs or claim equivalence without checking.
- Full-version builds use more disk -> on-demand reuse and coverage/bytes receipts; no automatic retention deletion.
- Concurrent writers -> unique staging paths and exclusive immutable destination publication; source hashes before/after and fail-closed verification.
- Annotations may still be in flight -> track Claude dependency separately; do not mark label preservation complete without its recalculation evidence.

## Migration Plan

Confirm annotation handoff; add dictionary and exact sources; add synthetic-tested price API; verify the merged producer gitlink; build and verify cache v1 on existing frozen inputs; exercise backup/restore. Update shared indexes once from fresh main. Producer indicator migration/removal follows in its own isolated PR after consumer inventory and frozen legacy input preservation. Rollback means continuing to use old source packets, not rewriting saved data.

## Open Questions

Actual annotation delivery status, current merged producer release, and live writer availability are verified during execution. No missing approval state is promoted to owner-approved. Worktree cleanup requires an owner-reviewed inventory in a separate task.
