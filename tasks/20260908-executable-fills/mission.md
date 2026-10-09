# 20260908-executable-fills — 可執行的次日開盤成交模型

**Sealed 2026-09-08, before any candidate run.** Written under the 2026-09-08 research
foundation (`docs/en/research-foundation.md`) and goal text (`docs/en/research-goal.md`),
after the owner explicitly resumed research.

## 1. Why this card exists, and why it is first

The goal text orders the work 量測正確性 → 可執行帳戶模擬 → 統計驗證, and requires
「訊號後次一交易日可實際成交的開盤執行模型」, explicitly forbidding
「以同日收盤價或理想化零股開盤成交替代」.

**Every number this research line has ever produced is same-bar close execution with zero
slippage.** `StockProject/engine/backtest_engine.py:91` sets the execution price to that
same bar's `RawClose`, and the strategy both decides on and trades at it. So the entire
line — including the five-slot candidate's 154.1% holdout — is currently inadmissible, not
because it is wrong but because it has never been measured against a price anyone could
actually have paid.

This card builds that execution model, verifies it on hand-calculable fixtures, and then
re-measures the existing candidate. **It is a measurement card. It cannot approve a
strategy**, and a good number here is not a pass.

## 2. The seam, and why the shared engine is not modified

`backtest_engine.py` builds `latest_prices` from `RawClose` **before** calling
`strategy.on_bar`, and marks the equity curve from that dict afterwards. A strategy may
therefore call `broker.set_execution_prices(...)` inside its own `on_bar` to override the
fill price **without disturbing the equity mark**. `RawOpen` is confirmed present in the
loader output and survives into `row_cache` (checked on 2330: 4,089 rows, `RawOpen` in the
record dict).

So the whole model lives in this card's `candidates/`, the shared engine is untouched, and
every historical card keeps reproducing its own stored numbers.

## 3. Policy choices — what is fact and what is mine

**The owner cannot weigh this card's result without knowing which of these I invented.**

### Exchange facts (not choices)

| Fact                                          | Value                                                                        |
| --------------------------------------------- | ---------------------------------------------------------------------------- |
| Board lot                                     | 1,000 shares                                                                 |
| Fee                                           | 0.1425% per side                                                             |
| Sell transaction tax                          | 0.3%                                                                         |
| Daily price limit                             | ±10% of the previous close                                                   |
| 盤中零股交易 (intraday odd-lot session) began | **2020-10-26**                                                               |
| Intraday odd-lot matching                     | from 09:10, every ~3 minutes — **there is no 09:00 open print for odd lots** |

### Owner requirements (not choices)

Initial capital NT$2,000,000; at most 5 simultaneous holdings; manual daily execution.

### My modelling choices — every one of these moves the answer

| #   | Choice                                                                                                                                                                                                                                                        | Value                                                                                         | Alternative I rejected                                                                                    |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| C1  | Signal from bar T's close fills at bar **T+1 `RawOpen`**                                                                                                                                                                                                      | fixed                                                                                         | fill at T+1 VWAP or close                                                                                 |
| C2  | A **buy does not fill** when T+1 open ≥ limit-up; a **sell does not fill** when ≤ limit-down                                                                                                                                                                  | fixed                                                                                         | partial fill, or fill anyway                                                                              |
| C3  | **No row for that code on T+1** (halt, suspension or delisting) → no fill. The data cannot distinguish these three, so they are counted together and reported.                                                                                                | fixed                                                                                         | carry the order forward                                                                                   |
| C4  | An unfilled order **expires at the end of that bar**                                                                                                                                                                                                          | fixed                                                                                         | carry to T+2, which is a different strategy (chasing)                                                     |
| C5  | Slippage, adverse to the trader                                                                                                                                                                                                                               | **swept 0 / 10 / 25 / 50 bps**                                                                | a single picked value                                                                                     |
| C6  | Order sizing is **rounded down to whole lots** (arm A)                                                                                                                                                                                                        | see arms                                                                                      | always allow odd lots                                                                                     |
| C7  | Before 2020-10-26 an odd-lot remainder **cannot fill at all**                                                                                                                                                                                                 | fixed                                                                                         | pretend the modern session existed                                                                        |
| C8  | After 2020-10-26 an odd-lot remainder fills at the same `RawOpen`                                                                                                                                                                                             | fixed, **and this is optimistic** — the real first odd-lot match is 09:10, not the 09:00 open | extra slippage on the odd leg                                                                             |
| C9  | Within a settlement bar, **sells run before buys** (Taiwan makes morning sale proceeds available for a morning purchase). A buy that would take the book past `top_k` — possible when a limit-down blocks an exit — is **skipped and counted as `book_full`** | fixed                                                                                         | let the book run wide whenever an exit is blocked, which is a different strategy rather than a fill model |

C5 is swept rather than chosen because a single slippage number picked after seeing the
result would decide the verdict. C8 is deliberately generous: if the candidate fails even
with an optimistic odd-lot fill, the failure is not caused by that assumption.

## 4. Arms

| Arm                          | Sizing                                                | Odd-lot                                       |
| ---------------------------- | ----------------------------------------------------- | --------------------------------------------- |
| **A — whole lots only**      | round every order down to whole lots; 0 lots ⇒ no buy | never used                                    |
| **B — venue-aware odd lots** | whole lots + remainder                                | remainder fills only on/after 2020-10-26 (C7) |

Arm A is what the owner has said they will actually do by hand. Arm B measures what the
odd-lot dependence was worth.

**Anchor (must pass before anything else is read):** with same-bar close execution, zero
slippage and no lot rounding, the arm must reproduce `rotation_ranker_v8` exactly — same
return to 1e-9 and the same buy count. If the anchor fails, the arm is broken and no other
number on this card means anything.

## 5. The window split, and why the headline is two numbers not one

The train window opens 2019-06-19; intraday odd-lot trading began 2020-10-26; the k5
candidate runs 11% sub-lot on train and 22% on holdout. **For roughly the first 16 months
of train, a meaningful share of the book's orders had no executable venue at the open at
all** — not a worse price, no venue.

A single full-span number would therefore mix "realistic fills cost this much" with
"2019–2020 could not be traded this way", and a collapse would not say which. So every
result is reported twice:

1. **2020-10-26 → window end** — the fills-only question.
2. **Full window** with C7 applied — fills plus the venue calendar.

**The gap between them is the answer to "was this line an execution artifact or a calendar
artifact".**

## 6. Pre-registered outcome table

Reported per arm × slippage × span, against the same-span close-fill baseline:

- net return, max drawdown (marked account equity, per `research_core.ledger.max_drawdown`)
- buy count, sub-lot share, **orders that did not fill, split by cause** (limit move / no row / cash / rounded to zero)
- the 20-consecutive-attempt synthetic diagnostic, reported **as a diagnostic, not a gate**
  (the goal text is explicit that 每筆效果的簡單複利 ≠ 實際帳戶回撤, and that its definition
  must be sealed with the owner before it becomes a gate)

**Verdict rule, fixed now:**

| Retention of the same-span close-fill baseline net return, arm A @ 25bps, post-2020-10-26 span | Verdict                                |
| ---------------------------------------------------------------------------------------------- | -------------------------------------- |
| ≥ 70%                                                                                          | execution survives                     |
| 30–70%                                                                                         | materially degraded                    |
| < 30%                                                                                          | **the line was an execution artifact** |

The 70% figure is **borrowed from the goal text's own stress-retention requirement**; the
30% floor is **mine**. Neither is the owner's. Baseline net return must be positive for
retention to mean anything (goal text §定義與啟動邊界).

## 7. Verification before any candidate runs

Hand-calculable synthetic fixtures, per the foundation's
「先用可手算的合成案例驗證」, in `tests/test_execution_model.py`:

1. buy signalled T, fills T+1 open, exact cash after fee
2. T+1 open at limit-up ⇒ buy does not fill; at limit-down ⇒ sell does not fill
3. T+1 row absent ⇒ no fill, counted as `no_row`
4. odd-lot remainder before 2020-10-26 ⇒ rounded down; on/after ⇒ filled
5. slippage is adverse in both directions (buy pays more, sell receives less)
6. insufficient cash ⇒ no fill, counted as `cash`
7. an unfilled order does not reappear on T+2

**No candidate run is read until all seven pass.**

## 7.1 The anchor passed, and it exposed a comparability boundary

`anchor__v14_close` and `anchor__v8` both return **230.5334% on 1,091 buys** over
2019-01-02..2023-12-31 — identical to the digit, so the execution rewrite does not disturb
V8's decisions.

**But this line published 228.0962% for the same configuration on 2026-09-06.** The two runs
are not in conflict and the difference is not noise:

|                     | worktree snapshot (09-06) | main snapshot (09-08) |
| ------------------- | ------------------------: | --------------------: |
| return              |                 228.0962% |         **230.5334%** |
| buys / sells        |               1091 / 1086 |           1091 / 1086 |
| codes traded        |             identical set |         identical set |
| first trade         |                2019-06-19 |            2019-06-19 |
| **dividend events** |                     **9** |                **14** |

**The trades are bit-identical; only the dividend records differ.** The extra five events are
worth NT$48,744, which is 2.4372pp on NT$2M — matching the published gap of 2.4372pp exactly.
A worktree's `shioaji_stock_prices/data` is a copy frozen at creation time, and the
corporate-action tables have been backfilled since.

**Consequence, and it is not small:** every figure this line published before 2026-09-08 came
from the older snapshot and is **slightly understated**. Cross-card comparisons against those
numbers are invalid at roughly this magnitude. That is why every baseline on this card is
re-run here rather than quoted, and why `identities.data_snapshot` exists in the result
envelope.

## 8. What this card cannot conclude

It cannot approve a strategy, restore an already-viewed period, or claim an out-of-sample
result: `docs/en/research-registry.json` records 2019-01-02→2026-08-14 as **viewed**, so
both spans here are re-measurement of seen data. It does not model intraday paths, queue
position, partial fills within a bar, borrow, or the 09:10 odd-lot session's own price.
A good number here means only that the line is worth continuing to measure.
