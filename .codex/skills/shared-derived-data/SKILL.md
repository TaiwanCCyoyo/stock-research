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
- Official source quotes for a study that runs its own price model (custom corporate-action
  terms, holding-window economics): `read_official_quotes(codes=, as_of=)` returns the
  generation's verified official quotes and session calendar, so the study does not scan
  `price_daily.parquet`. Cash, share and source columns of corporate actions are not in this
  family; read them from the producer's `corporate_actions.sqlite`.
- Record the returned `record` with `write_run_receipt(..., shared_data=[record])`; it says which
  generation was read and never blocks saving a result. Pass its `generation=` to every later read
  so the study stays on one generation; a later read of a pruned generation fails loudly.
- Earlier cutoff: `read_adjusted_daily(..., as_of=)` then `technical_daily_v1.compute_technical`.
  Never truncate the latest table to fake a cutoff.

## Refresh

Updated automatically every weekday at 20:30 by the Windows task
`StockResearch-SharedDerivedUpdate`, after the producer's daily download; check `status` before
running `uv run python -m scripts.maintain_adjusted_daily update` by hand (timing: `measure --codes N`).
It rebuilds everything from 2010 in about 13 minutes and flips `current.json`; it is the only writer.
Weekday 18:00-18:45 and running `StockProject-*` tasks are refused at load.

A study that reads one generation for more than a day holds it, or the next update deletes it:
`uv run python -m scripts.maintain_adjusted_daily hold --generation <id> --holder <study> --reason <why>`,
then `uv run python -m scripts.maintain_adjusted_daily release --holder <study>` when done. Unheld old generations are deleted. A finished
result stays valid after its generation is gone; only a step that still needs it is redone.

## Extend

- New column on an existing family: add it in that family's computation module, bump its
  definition version, document formula, unit, missing/warmup rule and availability time, test it,
  and update the doc table and the asset-index row in `docs/en/research-program.md` in the same PR.
- Never change a published column's meaning; use a new column name or a new family (`-v2`).
- Study-specific conditions, pattern flags and future-outcome labels stay with the study.
- Do not stage a second copy in a worktree, `.tmp/` or `research_cache/` as the shared version;
  a preview is evidence for an equivalence check, then removed with the owner's agreement.
