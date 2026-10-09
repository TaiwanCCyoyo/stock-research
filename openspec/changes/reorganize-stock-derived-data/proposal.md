## Why

The owner approved Claude's 2026-10-08 architecture review. Repeated research-specific price restoration, ATR and pivots have drifted in meaning; definitions and source labels must remain discoverable and reproducible instead of living only in scratch workspaces.

## What Changes

- Establish the responsibility boundary: producer acquisition/normalization and backups; Stock research price policy, indicators, patterns and derived-cache backups.
- Preserve exact historical HHHL rule bytes and index non-interchangeable versions and proxies. Historical studies continue reading their sealed sources.
- Provide explicitly named raw, permanent-adjusted and reference-factor-adjusted prices for new consumers, with quality reasons and ambiguity handling.
- Build on-demand immutable Stock cache versions, read directly by absolute path from worktrees, without copies or links. Include ATR14 and confirmed 1.5/4 ATR pivots.
- Add verified, additive D-drive backup and non-overwriting restore for Stock datasets/cache/labels.
- Update the Stock gitlink only to a verified merged producer release. Deprecate producer research indicators; actual removal follows replacement availability, consumer preservation and a separate producer PR.

## Capabilities

### New Capabilities

- `research-derived-data`: versioned pattern sources, explicit price bases, immutable derived-cache access, and verified backup/restore.

### Modified Capabilities

None. Existing historical execution and corporate-action accounting policies are unchanged; the new API is opt-in for new research.

## Impact

New Stock modules, CLI tools, tests and data-ownership documentation. No new dependencies, downloads, schedules, account backtests, holdout access, web features or worktree deletion. Owner labels are Claude's separate delivery; do not infer approval from imported source examples. Validate synthetic calculations, exact source hashes, cache reuse/invalidation, corruption rejection and restore. Docker is unnecessary and will not be run.
