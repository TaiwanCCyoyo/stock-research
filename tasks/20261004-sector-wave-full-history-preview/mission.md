# Local full-history opportunity preview

Registered 2026-10-04 before market calculation. Owner chose local calculation A
and corrected the start to 2010; website scope is pinned from
`all-market-2010-scope.md`. This is descriptive retrospective research, with
the visible status `初步辨識，規則未定`, not a trading strategy or acceptance gate.

## Fixed scope

- Target 2010-01-04..2026-10-02, each entire observed series, never annual resets.
- Pin physical `price_daily.parquet`, consistent SQLite actions and metadata,
  mapping and consumed classification chunks. Official is primary, Shioaji fills
  stored date/symbol gaps; preserve per-row Source, use no live CSV refresh.
- 1,942 metadata stocks plus 28 identified innovation-board stocks are analyzed,
  with separate cohorts. Preserve 104 unresolved identities and 0050 benchmark
  prices/coverage; neither contributes to stock opportunity counts.
- Keep all original inputs/results/tasks and other writers unchanged. No market
  downloads, pipeline rebuild, scheduler changes, sealed strategy artifacts,
  portfolio backtest, acceptance changes or retrospective parameter tuning.
- Price basis is permanent non-pure-cash reference-factor adjusted appreciation,
  four decimals, not SignalClose's five-row cash window or total return. Contract
  defines action selection, unknown-factor barriers and coverage caveats.
- Freeze the unchanged website `analysis.ts` and `types.ts` as method input.
  Two methods times three scales retain all native results. Non-mutating support
  aggregation preserves the original same-kind, same-method +/-20 calendar-index
  matching. Primary display remains segments/balanced.
- Retain all source waves, phases, candidates and method diagnostics, including
  failures, unresolved/unlinked candidates, no-wave and no-usable-run securities.
  Shared directional baseline is deduplicated per security/scale, not across
  distinct scales. 60% retention, direction thresholds and 5% ensuing outcomes
  remain exploratory; below-retention waves are not claimed to be exported.
- Source native ranges and comparison support bands are separate fields. Record
  all resolved numerical settings and code identities; no quiet scale/algorithm
  or window reduction for performance.

## Fixed presentation policy

- Membership starts at wave.start, irrespective of candidate launch; confirmed
  end is exclusive, unconfirmed end is bounded by observedThrough inclusive.
- Select active balanced baseline waves: large before small, start ascending,
  stable wave ID ascending. Precompute disjoint representative intervals.
- One security per day; gain base stays the selected wave.start. Preserve all
  representative transitions and their before/after gain bases and jumps.
- Earliest chronological candidate then stable ID is a reference indicator only:
  candidate, not manually selected or confirmed launch. Never filter by outcome
  or future peak gain. Save other candidates including failed/unresolved ones.
- Preserve native phase words and overlaps/containment/crossing relations. Do
  not silently rename them as validated lifecycle states. No market-cap area
  weighting or hidden area floor; geometry remains the website owner's domain.

## Delivery and verification

Canonical new outputs live under this task: contract, manifest/chunks, sources,
gaps, coverage, price-series identities, intervals and verification receipt.
Large physical inputs/native fit arrays stay local and ignored with explicit
recovery limits; compact event bundle is traceable to them. The website consumes
the same series and producer contract rather than re-adjusting prices itself.

Before full computation: immutable input receipt, numerical/continuity fixtures,
six-result support equivalence, overlap/empty/failure/unknown fixtures, exclusive
end/cutoff and deterministic intervals, overwrite refusal and CLI verification.
Performance preflight may use fixed mechanically chosen fixtures/series; only
timing controls execution, never tuning or acceptance. Report algorithm/scale
changes before doing them. Runtime failures retain coverage and reasons.

This window is descriptive exposure, not independent strategy validation. All
early-action, historical-identity/classification and availability gaps remain
visible. Backup/Git ownership beyond this bounded artifact policy remains a
separate owner discussion.
