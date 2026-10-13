# Annual rotation holding policy v2 (draft for owner review)

Drafted 2026-10-14. **Draft: binding only after the owner approves it in PR review;** the
approved commit is its identity. This document defines rules. It computes no return, reads
no held-path price field and changes no sealed result, input pin, parameter file or source.
`mission.md` and `params/study-v1.json` stay as registered; v1 results stay valid and readable.

## 決定摘要（給 owner，每一項都可以否決）

| #   | 預設                                                                                                                                                                     | 為什麼                                                                          | 你否決的後果                                                                    |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| 1   | **只重算 7 條持有路徑，領先股沿用 v1，不重新排名。**                                                                                                                     | 補資料只涵蓋這 7 檔；若用新規則重排，只有「領先股」被補到證據，會製造選擇偏誤。 | 要重排就是新研究，需新的 mission 與預先登記，且 2,061 檔排名要整批重算。        |
| 2   | **配股、減資（不退現金）、面額變更：有官方依據就計入股數；現金股利沿用 v1 的除權日再投資假設。**                                                                         | 這些都是股數變化，價格已反映；不計入會把正常事件當成虧損。                      | 維持 v1 就是這些年度永遠「未知」。                                              |
| 3   | **認股權利（3406、3205）給「區間」，不給單一數字；兩端結論一致才下結論。**                                                                                               | 是否認股、認股價值怎麼實現，官方資料無法決定；選一個會變成選結果。              | 要單一數字，就得由你指定一種實現方式。                                          |
| 4   | **「終端報酬」與「每日路徑」分開。** 中間日子沒有任何價格資訊（停牌、官方記錄零成交／無 OHLC）時，終端報酬照算，但每日路徑標記不完整、回撤只算參考。                     | 沒成交的日子不改變持股；v1 把它們一律當未知，太嚴。                             | 維持 v1：3162、5314 仍然未知。                                                  |
| 5   | **資料互相矛盾：數字用固定小數位判定，日級矛盾若沒有任何價格資訊就只標記，不影響終端報酬。** 3162 的 2018-09-26 **不會被當成零成交**，而是「無價格資訊、成交筆數矛盾」。 | 矛盾的是成交筆數，不是價格；價格兩邊都沒有。                                    | 嚴格一點就是 3162 未知。                                                        |
| 6   | **技術限制：不動 `annual_rotation.py` 前半、不改輸入版本 pin、不改 `study-v1.json`，新規則放新模組、新參數檔。**                                                         | 否則 `reuse_rank_rows` 會拒絕重用，7 條路徑會變成整批重新排名。                 | 破壞任何一項，就要重算約 2,061 檔的排名（上次約 6 分鐘到 8 分鐘，且資源吃緊）。 |
| 7   | **這份規則不能得出「全市場冠軍」。** 排名階段仍是 v1 嚴格版，每年仍有約 516–607 個候選未解。                                                                             | 補資料只解持有階段。                                                            | —                                                                               |

**看完規則後，7 個年度的證據狀況：5 個條件成立（各有一道執行時的檢查要過），2 個目前被擋住（3406、3205）。** 見第 7 節。

## 1. Scope and claim boundary

- **Changed:** economics of the held path for the leaders v1 already fixed (`annual_holding` side).
- **Unchanged:** universe, ranking (v1-strict), leader selection, entry and exit rules, fees and
  slippage, the 0050 benchmark and its dividend scenario, the fixed sensitivities, and every
  inference threshold in `mission.md`.
- **Asymmetry, stated on purpose.** Ranking stays v1-strict while holding becomes v2-lenient for the
  same event types. A candidate with a stock dividend in its ranking year is still _unknown_; the held
  leader's stock dividend becomes computable. v2 therefore completes the path of a _known-return
  leader_; it never states that the leader was the market champion.
- **Arms.** Rules apply to every arm, but the evidence covers only the main-arm leader of each year.
  Top5 holdings without supplement evidence stay unknown under these same rules. Completing the
  main arm does not complete every arm.

## 2. Evidence classes

| Class                    | Meaning                                                                 | May enter a computation                             |
| ------------------------ | ----------------------------------------------------------------------- | --------------------------------------------------- |
| `source_explicit`        | An official source states the value; raw text preserved                 | Yes                                                 |
| `derived_exact`          | Exact arithmetic on `source_explicit` values, formula recorded          | Yes                                                 |
| `inferred_official_rule` | Derived with a published exchange rule plus an observed confirming fact | Only for an **effective date** (rule R6), disclosed |
| `agreed_at_precision`    | Two sources agree after the rounding in R8                              | Yes, using the issuer's value                       |
| `conflict`               | Sources differ beyond that rounding                                     | No: unknown                                         |
| `unknown`                | Not found                                                               | No: unknown                                         |

## 3. Rules

**R1 Admission.** Supplement facts enter only as a published, immutable, hash-verified _held-path
evidence input_ with its own pin. Nothing is read from a `.tmp` candidate. The evidence input is separate
from the ranking input (see §6).

**R2 Cash dividend.** Unchanged from v1: the cash estimate is realized on the ex-date and reinvested at
that day's raw close into fractional units. Scheduled payment dates are not receipts.

**R3 Stock dividend, alone or with cash.** For ex-date `t`, raw close `P`, per-old-share cash `d`, bonus
ratio `b = bonus_per_1000 / 1000`, per-side brokerage `c`, current units `u`:

- gross: `u' = u·(1 + b) + u·d / P`
- net: `u' = u·(1 + b) + u·d / (P·(1 + c))`

With `b = 0` this is exactly v1. Admission requires `bonus_per_1000` and `d` to be `source_explicit`
and the bonus ratio to be **corroborated** by an exchange-published record: either the exchange's own
ex-right record states the ratio, or the first ex-date reference price equals
`(P_prev − d) / (1 + b)` to within one tick. An ex-date on the entry day confers nothing (v1). A
share-count-changing entitlement dated on the **exit** day is unknown (the sale and the entitlement
cannot be ordered without an assumption).

**R4 Share-count change without cash.**

- **R4a Loss-offset capital reduction, no refund:** `u' = u·f`, `f = (1000 − reduced_per_1000) / 1000`.
- **R4b Par-value exchange:** `u' = u·n`, `n` = new shares per old share.

Both apply on the first observed valid quote day on or after the official resumption / new-share start
date, with no cash and no cost. A reduction with any cash refund is unknown. Marks before that day use
the old units and the carried mark.

**R5 Optional subscription right** (per old share: `r = rights_per_1000 / 1000` at price `S`, ex-date
raw close `P`). Realization is not observable, so the path is an **interval**, never a point:

- lower bound: the right lapses, credit `0`;
- upper bound: the right is realized at intrinsic value, `V = r·max(0, P − S)`, credited as cash on the
  ex-date and reinvested at `P` exactly like a dividend (`u·V / P` gross; net with `(1 + c)`).

No scenario adds outside capital. An annual claim (beats paired net 0050 or not) is made only if it
holds at **both** bounds; otherwise the year is _indeterminate for that claim_. Aggregates (wealth, CAGR,
tests) are reported at both bounds. Admission also requires the disclosure to be **linked** to the
ex-date (the announced ex-date equals the pinned event date) and the field units to be verified.

**R6 Effective-date shift.** If the announced ex-date is a confirmed market-wide closure, the
entitlement takes effect on the first following trading day, provided (a) an official source confirms
the closure, (b) a published exchange rule carries the entitlement to the next business day, and (c)
quotes are observed on that day. The announced date is kept in the record and is not rewritten.

**R7 Quote availability, per day in `[entry, exit]`.**

| Class | Definition                                                                                                                                       | Path treatment                                                                               |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| `T`   | valid observed quote                                                                                                                             | normal                                                                                       |
| `H`   | no valid quote, and an official source states a halt or closure interval covering the day (inclusive ends as stated)                             | no mark; carry the previous mark; flagged `mark_observed = false`                            |
| `N`   | a row or record exists but **no official record shows OHLC** for that day, whatever the trade count                                              | same as `H`; any conflict about trade count is recorded and does not make the day zero-trade |
| `U`   | anything else (no row and no official explanation; an interval whose later days lack valid rows; a source showing OHLC where another shows none) | the path is **unknown** (v1)                                                                 |

Entry and exit are still "first positive-volume valid observed open on or after the boundary" (v1), so
`H`/`N` days cannot be endpoints. **Terminal return** needs only valid endpoints plus the entitlement
ledger. The **daily path** is reported `complete_equity = false` whenever any `H`/`N` day exists; daily
drawdown is then a carried-mark reference, with the count of carried days.

**R8 Source conflicts.** Compare numeric terms after rounding to **six decimal places per 1,000 shares**
(ratios) or per share (NT$). If equal at that representation, class `agreed_at_precision`; use the
issuer (MOPS) value rounded the same way. A difference at that representation is `conflict`: unknown.
The rule depends on how values are represented, never on what the difference does to a result.

**R9 Everything else is unknown:** cash-refund reductions, mergers, spin-offs, tender offers, warrants,
two actions on one day unless declared as one combined event, missing or negative cash, any event type
not named above.

## 4. Execution assumptions (unchanged)

Raw OHLC for entry, exit and marks; gross without fees; net with 0.1425% brokerage per side, 0.3% stock
sell tax (0.1% ETF), 10 bps adverse entry and exit, reinvestment brokerage; fractional units; no income
tax, health levy, odd-lot cash-in-lieu or lot-size claim. Bonus shares are credited economically at the
ex-date, not the later listing date.

## 5. Gates

- **G0 Admission:** the evidence input is published and verified, and its validator passes.
- **G1 Non-regression (per arm):** v2 reproduces every v1-modeled year of the main arm, the top5 arm,
  the one-price-avoidance arm and the 0050 benchmark **bit for bit** (multipliers, marks, applied
  events, reasons). Failure stops the work.
- **G2 Rank reuse:** `reuse_rank_rows` accepts the v1 ranking unchanged. Failure stops the work.
- **G3 Event gates:** linkage, units, corroboration (R3) or effective-date conditions (R6) per event.
- **G4 Path gates:** every day in `[entry, exit]` is `T`, `H` or `N`; any `U` day makes that path unknown.
- **G5 Interval gate:** rights events produce both bounds, or the path is unknown.

## 6. Implementation constraints (so v2 does not force a re-rank)

`reuse_rank_rows` (`research_core/annual_publication.py`) rejects reuse unless **all** hold:

1. `research_core/annual_rotation.py` is byte-identical before `def paired_benchmark_path`. The current
   `economic_path` sits inside that prefix: **do not edit it.** Put v2 economics in a new module or a
   new function. (`annual_holding` is after the boundary and may dispatch.)
2. `input_entry` equals the old one exactly: keep the ranking input `de7a91ec…`. Supplement facts are a
   _separate_ evidence input; never a new combined input version.
3. The stored `parameters` equal `params/study-v1.json`: leave it alone; the v2 policy gets its own file.
4. `annual_ranking_pool.py`, `price_basis.py` and `StockProject/engine/data_loader.py` match the old
   digests, and the AST of `run_study.py`'s `scope()` is unchanged.

The kernel also needs new code for the `N`/`H` split: v1 only tolerates `missing_official_quote` on days in
`known_halts`; `close_missing` rows fail a different quality check. G1 is what makes that change safe.

## 7. Evidence readiness (conditional; no return computed)

"Ready" always means _ready if the named gates pass at recompute time_. Facts are from the unpublished
candidate batch and become usable only through G0.

| Year / stock | Event and facts                                                                                                                                                                       | Rule            | Status                                                                           |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- | -------------------------------------------------------------------------------- |
| 2011 / 3406  | Rights offer (102.2076 per 1,000 at NT$235 recorded in the evidence ledger); linkage to the 2011-03-17 ex-right event and field units not confirmed                                   | R5              | **Blocked:** linkage and units                                                   |
| 2012 / 6276  | Loss-offset reduction, 528.4689042 per 1,000 reduced, so `f = 0.4715310958`; suspension 2012-07-16 to 2012-07-26 inclusive, resumption 2012-07-27                                     | R4a, R7 `H`     | Ready if **G3, G4** (a valid quote exists on or after 2012-07-27)                |
| 2016 / 3205  | Bonus 48.659339 per 1,000, rights 54.555950 per 1,000 at NT$133, cash NT$2.91956063; MOPS and TPEx differ only beyond the sixth decimal                                               | R3, R5, R8      | **Blocked:** field units unverified; then an interval                            |
| 2018 / 3162  | Six days with no OHLC in any official record (2018-09-26 also has a trade-count conflict, 3 versus 0); no non-cash event in the window per `data-gaps.md` and the frozen action table | R7 `N`          | Ready if **G4**                                                                  |
| 2020 / 6538  | Bonus 230 per 1,000 and cash NT$2.50 on 2020-08-27, in MOPS and in the TPEx ex-right record                                                                                           | R3              | Ready if **G3**                                                                  |
| 2024 / 1519  | Cash NT$6, bonus 100 per 1,000; announced ex-date 2024-07-25 fell in a market-wide closure; effective 2024-07-26; reference price consistent with the terms                           | R3 with R6      | Ready if **G3** (tick check)                                                     |
| 2025 / 5314  | 1 old share to 20 new on 2025-03-31 after a halt 2025-03-20 to 2025-03-28; one-day halts 2025-08-12 and 2025-12-08; suspension from 2025-10-14 with no official end found             | R4b, R7 `H`/`N` | Ready if **G3, G4** (every day after 2025-10-14 needs a valid row, else unknown) |

## 8. Exposure and inference

- 8 holding years were viewed under v1 (2 conditional wins). The 7 held returns were **not computed**, but
  they are partially exposed: the evidence ledger quotes some 2024 prices, and the sealed holding record
  stores raw entry and exit prices. These rules were written without reading those fields.
- v2 is a post hoc completion. Any 15-year statistic is exploratory, reported beside the v1 result and
  labelled by definition version. The v1 thresholds are unchanged and may not be adjusted after seeing
  results. With an incomplete ranking universe, "significant outperformance" cannot be established.

## 9. Order of work

1. Owner review of this draft (change anything in the 決定摘要 table).
2. Publish the supplement as an immutable held-path evidence input (producer-side contract and writer
   conditions are separate and still pending).
3. Implement v2 in a new module with synthetic tests for R3 to R8.
4. Pass G1 and G2 **before** touching any of the 7 paths.
5. Recompute the 7 held paths with owner authorization, then report v1 and v2 side by side.
