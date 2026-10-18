---
name: shared-derived-data
description: Where reusable derived research data lives and how to read, refresh or extend it - adjusted daily prices, technical indicators (SMA, EMA, ATR, Bollinger bands, RSI, ADX, MACD), confirmed highs/lows (pivots) and any future shared family under STOCK_RESEARCH_SHARED_ROOT (D:/StockData/stock-research/derived/). Use whenever a task wants to put data "in the shared area", reuse indicators instead of recomputing them, add a column or a new indicator to shared data, update shared data to the latest day, read Bollinger/moving averages/past highs and lows for a study, or decide whether a study's own features belong in shared data - including requests phrased as "放到共用區", "更新共用資料", "加一個指標", "布林軌道", "過去的高低點", "refresh adjusted prices" or "why is my generation gone".
---

# Shared derived data

The rules are canonical in
[`docs/en/research-derived-data.md`](../../../docs/en/research-derived-data.md#維護中的共用衍生資料)
(section 維護中的共用衍生資料 and 共用資料的擴充規則). Read them before writing; this skill only
routes you there and names what a finished change must satisfy.

## Read

- Prices: `research_core.maintained_adjusted_daily.read_adjusted_daily(basis, codes=, columns=)`.
- Indicators and pivots: `read_technical("daily", codes=, columns=, prices=["Close", ...])`
  returns one row per price row with the prices joined from the same generation;
  `read_technical("pivots")` is the confirmed high/low long table, usable from `confirmed_at`.
- Put the returned `record` in the study's `run_receipt`; pass its `generation=` to every later
  read so the study stays on one generation. A pruned generation fails loudly by design.
- Earlier cutoff: `read_adjusted_daily(..., as_of=)` then `technical_daily_v1.compute_technical`.
  Never truncate the latest table to fake a cutoff.

## Refresh

`uv run python -m scripts.maintain_adjusted_daily update` (status: `status`, timing: `measure --codes N`).
It rebuilds everything from 2010 and flips `current.json`; it is the only writer. Check the
producer schedule first (weekday 18:00-18:45 and running `StockProject-*` tasks are refused at
load; compute alone measured about 22 minutes on 2026-10-17 and writes are not yet measured, so start
before about 17:00 on a weekday).

## Extend

- New column on an existing family: add it in that family's computation module, bump its
  definition version, document formula, unit, missing/warmup rule and availability time, test it,
  and update the doc table and the asset-index row in `docs/en/research-program.md` in the same PR.
- Never change a published column's meaning; use a new column name or a new family (`-v2`).
- Study-specific conditions, pattern flags and future-outcome labels stay with the study.
- Do not stage a second copy in a worktree, `.tmp/` or `research_cache/` as the shared version;
  a preview is evidence for an equivalence check, then removed with the owner's agreement.
