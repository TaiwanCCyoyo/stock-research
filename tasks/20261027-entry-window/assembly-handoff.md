# E1: complete in-memory comparison assembly

Engineering definition: `entry-window-assembly.v1`. Research definition remains
`entry-window.v1`; the [mission](mission.md) and [data contract](data-contract.md)
are unchanged. This package connects the existing [input staging](reader-staging-handoff.md),
[integer counting](implementation-handoff.md) and [paired bootstrap](bootstrap-handoff.md)
APIs using artificial packets. It is not a market reader, study result or compute admission.

## Access and ownership

```python
from research_core.entry_window_assembly_v1 import (
    AssemblyRequest, StockPackets, assemble_study,
)

# Explicit common identity, complete sorted codes and full common calendar.
request = AssemblyRequest(
    codes=codes, generation=generation, study_as_of=study_as_of,
    common_calendar=calendar, universe_id=universe_id, calendar_id=calendar_id,
)
result = assemble_study(request, packet_bundles)
```

Every `StockPackets` contains an `InputRequest`, `CanonicalPacket`,
`RawQuotePacket`, `IntervalPacket` and optional `OfficialLimitsPacket`.
Supply exactly one bundle per declared stock, including zero-event stocks.
All original arrays and metadata are supplied by the caller; the assembler has
no path, root fallback, loader, CLI, label construction or persistence API.
The caller must not mutate borrowed inputs during assembly.

The complete inventory, common generation/as-of/universe/calendar identity and
every packet's staging validation pass before any stock is counted. Counting
runs once per stock on its full history, preserving cross-year cooldown.
Packet order does not affect output order. Common calendar years determine the
four era axes; a calendar missing an era is rejected, never expanded with invented
years or inferred from nonzero events. Tiny synthetic calendars must therefore
include dates in each of the three disjoint historical eras, plus their union.
This does not certify an official calendar or complete real-market coverage.

## Outputs and fixed comparison matrix

`StudyAssembly` retains stock/year integer rows and diagnostics, all B1 summaries,
288 `ComparisonSummary` entries, 5,760 `IntervalRow` entries, four `CountAxes`
and each stock's complete alignment record. A comparison includes its fixed
cell/set/band/label identity, primary flag, cadence, era and ten B1 rates.

- Comparison order is era, cell, cadence; interval order adds method and statistic.
- The fixed matrix is 36 comparisons (24 primary, 12 secondary) × 2 cadences ×
  4 eras × 2 bootstrap methods × 10 statistics. Zero and all-null cells remain.
- Each era/method creates one paired weight object, reused across all 72 cells;
  only one cell cube is built at a time. Seeds, RNG draw order and default 2,000
  replicates remain those of the bootstrap contract. Smaller `reps` are for
  synthetic verification, not a new market-evaluation setting.
- B1 aggregates integer counts and stock-ID unions before rates. Annual distinct
  stock counts are never summed; common M is not multiplied across the six bands.
- Zero denominators remain `None`, and valid plus null replicates equals `reps`.
  Censored and unknown semantics remain B1's, including their allowed overlap.
- Metadata mappings are read-only views. For JSON inspection, convert mappings
  with `dict(...)` and interval dataclasses with `dataclasses.asdict`; the whole
  assembly is not a serialized artifact or a publication format.

The alignment record's source/basis/notes and validation-scope disclaimer remain
intact. Declaration consistency is not source verification, event-coverage proof,
historical PIT certification, strategy validity or a fill claim. No sufficiency
verdict is introduced; any later display must use the contract's matching
cooled20 known counts and distinct-stock definition, not daily sample sizes.

## Verification and remaining gates

Executed on 2026-11-02:

```text
uv run pytest scripts/tests/test_entry_window_assembly_v1.py scripts/tests/test_entry_window_v1.py scripts/tests/test_entry_window_inputs_v1.py scripts/tests/test_entry_window_bootstrap_v1.py scripts/tests/test_ci_scope.py -q
672 passed in 87.50s (0:01:27)
```

After replacing direct pandas date access with the existing typed date helpers,
the new assembly suite passed again: **39 passed in 3.25s**. Implementation
commit `170799376feebb5d02cd42f947858571040300da` passed every applicable normal
commit hook, including Mypy, Pyright and Ruff. Delivery is
[draft PR #146](https://github.com/TaiwanCCyoyo/stock-research/pull/146).

The new artificial-packet tests cover the full matrix, direct public B1/selected
bootstrap oracles, cross-year stock unions and cooldown, zero/null cells,
provenance, exact weights reuse, input immutability, deterministic order and
forbidden reader/file/database/network/label construction paths. Invalid or
missing identities and a malformed later packet fail before any stock count.
An independent Terra review of all eight delivery files found no actionable
defects. This is local evidence, not hosted review or owner acceptance. Normal
hooks and current-head CI status are recorded in the delivery PR. The CI domain
includes the new module, handoff and test alongside the existing three E1 suites.

Real source/event-coverage adapters, original label admission, official calendar
and generation checks, resource measurement and a separately admitted market
runner remain outside this package. No input or result hashes are rewritten.
No research-data scratch run or study-card result is created.

The [2026-11-02 engineering record](../../docs/en/decision-records/2026-11-02-long-term-research-engineering.md)
separates this preparation from report presentation, owner acceptance and product
use. #113/#128 and all report holds remain; #137's interactive discussion contract
is being developed by its existing owner. S7 and O2 pending gates are unchanged.

This session owns only `D:/Project/stock-research/.worktrees/entry-window-assembly`,
branch `codex/entry-window-assembly`, based on fetched main
`2f8a7d906410958d9fda67021a0cfc84a53ec06b`. The 40-worktree inventory completed;
the prior E1 core/bootstrap/inputs worktrees were clean. Other sessions' resources
were not modified. This worktree is retained for its draft PR and follow-through.
