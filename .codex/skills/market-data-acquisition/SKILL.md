---
name: market-data-acquisition
description: How to add or extend a market-data source in the shioaji_stock_prices pipeline without shipping a silently wrong artifact - probing an endpoint for its observed values before writing a parser, measuring whether two feeds actually agree, and the seam that appears whenever a daily bulk fetch and a historical backfill write the same rows. Use before writing or changing a fetcher, backfiller, or normalizer for TWSE/TPEx data, wiring a new step into run_daily.py, backfilling history for any source, or explaining why two sources disagree about the same day. The failures it prevents do not raise exceptions; they produce plausible numbers.
---

# Market Data Acquisition

This skill covers writing into `shioaji_stock_prices/data/`. For reading those artifacts
correctly, use `market-data-cache` instead.

1. Read [`.claude/skills/market-data-acquisition/SKILL.md`](../../../.claude/skills/market-data-acquisition/SKILL.md)
   completely before writing or changing any fetcher, backfiller, or normalizer.

    That file is the single source for this method rather than a copy maintained in
    parallel. The neighbouring `market-data-cache` skill is duplicated between `.codex/` and
    `.claude/`, and on 2026-08-30 that duplication left the Codex half describing an
    artifact five days out of date — stale enough to produce wrong answers rather than
    merely incomplete ones. One file avoids repeating that.

2. Treat `.claude/rules/common/data-structures.md` as the hard constraints that sit under
   the method: never destroy existing cache data, never break stored-result readability,
   check the scheduled-task state before writing under `shioaji_stock_prices/data/`, and
   kill only processes you started and only by PID.

3. Report measured numbers rather than impressions when declaring acquisition work done,
   and state the comparability boundary any change to acquisition creates.
