# Momentum-only v1：不看型態，只看強勢條件，能解釋多少翻倍機率？

狀態：**mission 草稿，尚未合併；沒有任何本研究的市場計算。**
本研究承接 [PR17 pattern-scan](../20261013-pattern-scan/mission.md)（TaiwanCCyoyo/stock-research PR 17，
分支 `codex/pattern-scan-execution`，**未合併**）。PR17 的定義、分箱、母體與標籤全部沿用，
本 mission 不新增任何條件、型態或標籤定義。

## 給 owner 的白話摘要

- **要回答的問題：** PR17 發現「型態＋強勢條件」的股票，半年內翻倍的比例約 19–23%，
  但同樣條件下的一般股票日（PR17 的同條件 C-base-all）也有 13–17%（一年內：型態組 22–26%、一般組 20–21%）。這次直接量：**只用強勢條件、完全不看型態**，
  翻倍比例有多高？型態在強勢條件之外，到底多貢獻了多少？
- **為什麼歷史資料不能當新證據：** 這些條件本來就是從 2010–2026-10-12 的資料裡挑出來的。
  在同一段資料上再算一次，只能「描述」，不能「證明」。唯一沒看過的證據，是從
  2026-10-13 起每天記錄、之後再看結果的**前瞻紀錄**。
- **前瞻紀錄什麼時候才有意義：** 記錄一年（到 2027-10-12），等每筆都走完半年才評估，
  第一次評估約在 **2028 年 4 月**（252 日版本約 2028 年 10 月）。最嚴格的三條件組合，
  從 PR17 表粗估全市場一年至少二、三十個獨立事件（這是下限，正式計算會給實際年頻率）；
  若一年不夠，就再累積一年，規則不變。單一條件會快得多。
- **替 owner 預設的選擇**（理由見下方「預設決定」）：固定 24 組條件、不事後加減；
  `PAT_other_B4`（近期出現跳空突破型態）算「型態」，不算「強勢條件」；
  「沒有型態」只排除 9 個形狀型態，不排除 L1/L2/L3 這三個單根 K 線趨勢旗標
  （因為它們本身就近乎強勢條件，排除了會把強勢也一起拿掉）。

## 背景：PR17 已讀出的數字（只讀終表，未重算）

全市場、全期間、無冷卻的每日基準，讀自 PR17 `web-report/data/tables/B1-summary.parquet`
（`cohort_id=union, split=all, era=all, mkt=all, row_kind=full`）：

| 對照            | H126 hit / loss | H252 hit / loss | H126 known_n / hit_n | H252 known_n / hit_n |
| --------------- | --------------: | --------------: | -------------------: | -------------------: |
| `C-base-daily`  |   3.86% / 47.3% |   9.83% / 45.1% |  4,712,210 / 181,941 |  4,340,517 / 426,669 |
| `C-52w-daily`   |   7.53% / 43.5% |  13.85% / 42.4% |       81,945 / 6,170 |      76,778 / 10,632 |
| `C-52w`（冷卻） |   7.00% / 42.3% |  13.23% / 41.0% |       24,769 / 1,735 |       23,115 / 3,057 |

PR17 B1、H1 各自的 development-half selector 都選出幾乎相同的 atoms：
`C3=ge60`、`D2=ge250`、`G2_limit=true`、`H=ge90`、`RSI=ge70`、`F=gt100`、`PAT_other_B4=true`。
兩家族在 Q4–Q6 前十清單的第一列（依已暴露的 cross-check H252 排序，**不是**選擇結果）：

| 家族 | 第一列候選                               | cross-check H126 pattern / C-base-all / C-base-no-pattern | H252 同序         |
| ---- | ---------------------------------------- | --------------------------------------------------------- | ----------------- |
| B1   | `C3=ge60 & D2=ge250 & G2_limit=true`     | 23.0%（K=152）／17.3%（173）／22.2%（9）                  | 26.4／21.4／22.2% |
| H1   | `C3=ge60 & D2=ge250 & PAT_other_B4=true` | 18.6%（140）／13.5%（326）／12.4%（339）                  | 22.3／19.7／18.2% |

**這些 PR17 同條件對照不能直接回答本題。** PR17 的 `C-base-*` 是先對所有合格股票日做
20 session 冷卻、再篩條件的子樣本；B1 的 `C-base-no-pattern` 只剩 9 個已知事件。
可重複的證據：H1 cross-check 表中 `C-base-no-pattern`（397 事件）多於 `C-base-all`（381）。
最早優先的 20 session 冷卻在子集合上不可能選出比全集合更多的事件，所以只有「各自先冷卻、
後篩條件」才會出現這個順序。
本研究改在**全部合格股票日**上計算條件集合，並把「有型態／沒有型態」直接拆開。

## 已看過的期間與證據等級

- 2010-01-04..2026-10-12 **整段已看過**：atoms 由 PR17 development 半選出，候選又依
  cross-check 半的 H252 排序呈現。CRC development／cross-check 分半只作連續性對照，
  兩半都不是 holdout。本研究在這段期間的所有數字都是**描述**，不批准策略、不晉級、
  不當獨立確認，也不是帳戶報酬。
- 唯一未看過的證據是 2026-10-13 起的[前瞻紀錄](#前瞻紀錄2026-10-13-起)。
  其中 2026-10-13..2026-10-21 在本草稿撰寫時價格已存在、但結果（126 日後）尚未發生；
  這幾天的紀錄會以 `recorded_late=true` 補記，照實標示。
- 126 日 +10%、252 日 +20% 仍只是 owner 參考線，不設通過門檻。

## 開始條件與依賴

市場計算須同時滿足：

1. owner 合併本 mission。
2. **PR17 已合併進 `main`**。本研究需要的下列程式目前只在 PR17 分支：
   `pattern_scan_inputs_v1.daily_qualification`（S6 逐日資格）、
   `pattern_scan_controls_v1`（`C-52w`、`C-base`、`base_no_pattern`）、
   `pattern_scan_conditions_v1`（RSI／F／PAT 分箱 inventory）、
   `pattern_scan_cross_section_v1`（H 的全市場 barrier adapter）、
   `pattern_scan_indicators_v1`、`pattern_scan_cross_section_v1.recent_pattern_values`。
   已在 `main` 的核心：`hhhl_variants_daily.calculate_daily_features`（C3／D2／F／G2_limit）、
   `hhhl_variants_run.cross_section`（H）、`hhhl_variants_paths.outcomes_for_closes`（標籤）、
   `hhhl_variants_selection.split_for_code`（CRC 分半）、
   `pattern_scan_cohorts_v1.build_pattern_cohorts`（20 session 冷卻）、
   `pattern_scan_event_outcomes_v1.apply_event_overlay`。
3. [型態分解](#型態分解有型態沒有型態)另需 PR17 把**每日原始 union 候選狀態**
   （12 家族 × 股票 × 交易日，int8 −1/0/1，約 1,942×4,110×12 ≈ 96 MB）作為可重用產物發布並登記
   資料契約。若不可得，該節記 `not_evaluated`；**本 mission 不授權重跑 12 家族 detector**
   （估計約 97 小時串行，見成本估計）。這是對 PR17 交付的請求，不由本研究自行處理。

本 mission 不授權下載、排程、更改 producer、更新或釋放共用世代（包括 PR17 的
`pr17-pattern-scan` hold）、改寫 PR17 結果，或碰 PR17 執行中的程序。

## 輸入、母體與定義（全部沿用 PR17）

- **價格與指標：** 共用家族 `adjusted-daily-v1`（`STOCK_RESEARCH_SHARED_ROOT`）的
  `reference_factor_adjusted`（price-basis.v2）。以 `read_adjusted_daily(..., as_of=2026-10-12)`
  在執行當時的 current generation 內依截止日重算，`write_run_receipt(shared_data=[record])` 記錄
  generation；之後每次讀取都傳同一 `generation=`。執行跨過一天則先
  `maintain_adjusted_daily hold --holder momentum-only-doubling`，完成後 release。
  `technical-daily.v1` 的 RSI14／ATR 與 PR17 使用的 atlas／derived_features 版本逐位元相同，
  但 PR17 先遮罩品質無效的 OHLC 再算 RSI；20 檔探測須逐值比對共用 `RSI14` 與 PR17 adapter，
  全部相同才讀共用欄，任何一列不同就改用 PR17 adapter（`pattern_scan_indicators_v1`）；
  C3（MA240）、D2、F、G2_limit、H 不在共用家族，用上列 `research_core` 原程式計算，
  **不加入共用資料**（研究專屬條件留在研究）。
- **日曆與期間：** PR17 common calendar，2010-01-04..2026-10-12，4,110 sessions；年代 2010–2012、
  2013–2018、2019+。不得刪缺價縮短 H126／H252。
- **逐日母體：** PR17 S6 `base_eligible`（ordinary reference、60 個連續有效研究價、當日正量、
  前 20 日原始成交額均可知且平均 ≥ NT$1m）。新上市／下市依當日資格進出。
- **標籤：** `outcomes_for_closes`，t0+1..t0+H 首次 close ≥ 2×anchor 為 hit；完整路徑未 hit
  且末 close < anchor 為 loss，其餘 flat-win；缺價先發生為 unknown；截尾不進主分母。
  所有每日組別（條件集合、基準、有／無型態）一律使用 **PR17 `C-base-daily` 的 effective-label
  與 `event_main_eligible` 規則**，使組別間唯一差異是成員資格。分母、上下界、零分母 null、
  drop-best-year 與欄位語意照 PR17 [data dictionary](../20261013-pattern-scan/data-dictionary-v1.md)
  （PR17 分支）。

### 七個 atoms

| 代號 | feature_id／bin         | t0 收盤可知公式（PR17 原定義）                        | 類別     | 來源模組                                            |
| ---- | ----------------------- | ----------------------------------------------------- | -------- | --------------------------------------------------- |
| A1   | `C3` / `ge60`           | close／MA240 − 1 ≥ 0.60                               | 強勢     | `hhhl_variants_daily`                               |
| A2   | `D2` / `ge250`          | close／前 250 日最低 close ≥ 2.5                      | 強勢     | `hhhl_variants_daily`                               |
| A3   | `G2_limit` / `true`     | 原始 close／前日原始 close − 1 ≥ 0.095（漲停代理）    | 強勢     | `hhhl_variants_daily`                               |
| A4   | `H` / `ge90`            | 120 日報酬在同日 eligible／known 股的百分位 rank ≥ 90 | 強勢     | `hhhl_variants_run.cross_section`（全市場 barrier） |
| A5   | `RSI` / `ge70`          | Wilder RSI14 ≥ 70                                     | 強勢     | atlas `rsi14`（＝`technical-daily.v1` `RSI14`）     |
| A6   | `F` / `gt100`           | ATR14%[t0−1]／median(ATR14%[t0−120..t0−1]) > 1        | 強勢     | `hhhl_variants_daily`                               |
| A7   | `PAT_other_B4` / `true` | t0−10..t0 有 B4 union 原始候選（跳空突破）            | **型態** | `recent_pattern_values`（需 PR17 原始狀態）         |

缺值、暖機不足、不適用照 PR17 各自分開，不當 false、不當 0。

## 比較組

### 基準（本研究重算，與條件集合同一 generation）

- `C-base-daily`：所有合格股票日，無冷卻。
- `C-52w-daily`：close ≥ 前 250 日最高 close 且原始量 ≥ 前 20 日均量 × 1.5，無冷卻。
- 冷卻版 `C-base`、`C-52w`：PR17 原 20 session 冷卻，供冷卻口徑對照。

### 條件集合（事前固定 24 組，不事後增減）

| 群組                  | 集合                                                   |           數量 |
| --------------------- | ------------------------------------------------------ | -------------: |
| 純強勢單一            | A1、A2、A3、A4、A5、A6                                 |              6 |
| 純強勢兩兩            | A1–A6 所有兩兩交集                                     |             15 |
| 主集合 `CORE`         | A1∧A2（兩個領先候選共有的核心）                        | （已含於兩兩） |
| B1 領先集合 `LEAD_B1` | A1∧A2∧A3，即 PR17 B1 第一列原文                        |              1 |
| 含型態                | A7；A1∧A2∧A7（PR17 H1 第一列原文的條件部分 `LEAD_H1`） |              2 |

純強勢集合共 22 組；含 A7 的 2 組一律標 `pattern_involved=true`，**不算「只有條件」**。
A7 需要 B4 的每日原始 union 狀態（開始條件 3）；不可得時 A7 與 `LEAD_H1` 跟型態分解一起記
`not_evaluated`，前瞻紀錄中的對應旗標為 null 並附原因。

### 兩種計數口徑，各自只跟同口徑比

| 口徑 | 定義                                                                 | 只能比較的對象                                      |
| ---- | -------------------------------------------------------------------- | --------------------------------------------------- |
| 每日 | 條件成立的每個合格股票日，無冷卻                                     | `C-base-daily`、`C-52w-daily`（主要比較）           |
| 冷卻 | 每股、每集合各自獨立 20 session 冷卻（`build_pattern_cohorts` 規則） | 冷卻 `C-base`、`C-52w`、PR17 pattern 事件（連續性） |

每日口徑的同股連續日高度相依，原始列數遠大於有效樣本；不確定性一律用下方的 stock-cluster 區間。

## 型態分解：有型態／沒有型態

只在 PR17 原始 union 狀態可得時執行（見開始條件 3），仍為每日口徑：

- **型態集合：** 9 個形狀家族 B1、B2、B3、B4、H1、P1、R1、R2、R3（主要）；全部 12 家族（次要）。
- `Q_none`：條件集合成立，且 t0−10..t0 每日 9 個形狀家族原始 union 狀態皆已知為 0。
  任一已知 1 → 不屬 `Q_none`；無 1 但有 −1 → `pattern_unknown`，另列，**不歸入沒有型態**。
- `P_B1`：`LEAD_B1` 且 t0 有 B1 union 原始候選；`P_H1`：`LEAD_H1` 且 t0 有 H1 union 原始候選。
- 對 B1：`Q = LEAD_B1 ∧ Q_none`；對 H1：`Q = CORE ∧ Q_none`（排除了 B4，所以是純強勢）。
  另列 `CORE ∧ Q_none` 對 B1 的值作參考。
- 次要（12 家族）版本預期樣本很少；不足門檻時照實記 `inseparable`。

PR17 pattern-specific detection 回看 quality overlay 不套到每日 `P`；連續性表另引 PR17 原 pattern 列，不改其數字。

## 主要估計量與判讀規則（事前固定）

B = `C-base-daily`。對每個領先家族（B1、H1）× horizon（H126、H252），全期間每日口徑：

- `share = (Q − B) ／ (P − B)`，以 hit_rate 計；`P − B ≤ 0` 時不計 share。
- 不確定性：以股票為 cluster 的 bootstrap，2,000 次、seed 20261021、百分位 95% 區間；
  每次重抽同時計算 P、Q、B（配對），由每股整數 counts 重組，不重跑逐日計算。

| 判讀                | 條件（依序判定，先符合者為準）                                                                    |
| ------------------- | ------------------------------------------------------------------------------------------------- |
| `inseparable`       | P 或 Q 的**冷卻口徑** known_n < 100 或 distinct_stock_n < 30（PR17 最小樣本原本即以冷卻事件定義） |
| `no_pattern_lift`   | P − B ≤ 0                                                                                         |
| `momentum_dominant` | share ≥ 0.5，drop-best-year 後 share 仍 ≥ 0.5，且 (Q − B) 區間下界 > 0                            |
| `pattern_adds`      | share < 0.5 且 (P − Q) 區間下界 > 0                                                               |
| `unresolved`        | 其他                                                                                              |

型態分解 `not_evaluated` 時，主判讀改報核心問題：`CORE` 與 `LEAD_B1` 每日 hit_rate 相對
`C-base-daily` 的倍數與差距、相對 `C-52w-daily` 的差距，各附 stock-cluster 區間；
不另造 share。年代、分半與 drop-best-year 表全部呈現，但不進判讀規則（避免挑格）。
不在看到結果後改門檻、改集合或改 cluster 方式。

## 報表（每列都報，好壞都列）

- 每集合 × horizon × 口徑：`event_n`、`distinct_stock_n`、每股事件中位數／最大值、
  `known_n`、`unknown_n`、`censored_n`、`hit_n`／`loss_n`／`flat_win_n`、**hit_rate 與 loss_rate 並列**、
  full-calendar 上下界、相對 B 的倍數與差距、相對 `C-52w-daily` 的差距、前 10 檔股票占 hit 比例。
- 分層：全期 + 2010–2012 + 2013–2018 + 2019+；split all／development／cross-check；
  每格附 `drop_best_year`（PR17 規則：刪 eligible hit 最多的年，平手取早，重算全部 counts）及逐年表。
- 0050 市場背景分層不在本研究範圍（PR17 已有），不新增比較。
- 比較帳：24 集合 × 2 horizon × 2 口徑 × 4 年代 × 3 split，加 drop-best-year 與逐年，
  均為描述；只有上表 4 個（2 家族 × 2 horizon）判讀格是事前指定的主結論。
- 產出 tidy parquet：`set_summary`、`set_annual`、`decomposition_summary`、`bootstrap_intervals`、
  `parity_check`、`verdicts`；欄位語意引用 PR17 data dictionary，新增欄位在本 task data contract 說明。

## 計算前的對齊檢查（parity gate）

在計算任何條件集合之前，先用同一 generation 重算 `C-base-daily` 與 `C-52w-daily`
（split=all、era=all、row_kind=full），與上方 PR17 數字逐項比較 `known_n`、`hit_n`、`loss_n`。

- 完全相同：照常進行。
- 有差異但 known_n 差 ≤ 1% 且 hit_rate 差 ≤ 0.2 個百分點：多半是 PR17 generation 之後的公司行動
  改寫了歷史還原價。列出差異與受影響股票，**照實繼續**，報告以本研究重算的基準為準。
- 超過上述範圍：停下並報告原因，不繼續計算條件集合。
- 任何情況都不為了對上數字而調整定義。

## 前瞻紀錄（2026-10-13 起）

**本 mission 只定義紀錄方式，不建立排程或自動化。** 紀錄指令另行實作，人工執行。

- **時點：** 每個交易日在共用更新（平日 20:30 `StockResearch-SharedDerivedUpdate`）完成之後記錄，
  絕不在 18:00–18:45 或任何 `StockProject-*` 執行中讀取。漏記的日子以
  `read_adjusted_daily(as_of=該日)` 在當時 current generation 內依截止日重算補記，標 `recorded_late=true`。
- **每列凍結、只增不改：** 共用世代每天從 2010 全部重建，歷史還原價會因新公司行動改寫，
  所以紀錄當下的值就是證據，之後**不得重算覆寫**。
- **每日每檔合格股票一列**（約 1,900 列／日；基準也要前瞻），欄位：`t0`、`recorded_at_utc`、
  `generation`、`code_commit`、`security_id`、`base_eligible` 與原因、原始 close、當代還原 close、
  七個 atoms 的值／bin／status、24 集合成立旗標、`C-52w-daily` 狀態、
  B1／H1／B4／形狀家族原始狀態（PR17 detector 合併後且每日增量可在合理時間完成時才填；否則 null 加原因）、`recorded_late`。
- **位置與凍結：** primary checkout `tasks/20261021-momentum-only-doubling/forward-log/days/`，
  每個交易日一個小 parquet（約 1,900 列），以 `research_core.artifact_store` 的 no-replace 發布寫入，
  已存在的日子不能被覆寫；更正只能另寫帶原日期與原因的 correction 檔。每月經一般 task branch／PR
  交付，合併由 owner 決定，不直接 commit 到 `main`。
- **不偷看：** 評估日前只可看列數、資格、unknown 等營運計數，不可看任何 hit／loss。
- **評估：** 累積期 2026-10-13..2027-10-12。結果以評估當天的 generation 重算 anchor 與未來 close
  （與 PR17 標籤同一價格基礎）；atoms 用凍結值。
    - E1（H126）：累積期最後一筆走完 126 sessions 後（約 2028-04）。
    - E2（H252）：走完 252 sessions 後（約 2028-10）。
    - 每集合冷卻口徑 known_n ≥ 100 且 distinct_stock_n ≥ 30 才判讀；不足記 `insufficient`，
      累積期延長一年、同規則累計再評。
    - 前瞻主結論：`CORE` 與 `LEAD_B1` 每日 hit_rate 減同期 `C-base-daily` 的 stock-cluster 95%
      區間下界 > 0，記 `forward_lift_observed`；型態分解（若 detector 可用）沿用上表規則。
- **樣本現實：** 以 PR17 B1 cross-check 半的 `C-base-all`（約一半股票）223 個事件粗估，
  `LEAD_B1` 全市場約 450 個／16.8 年 ≈ 每年 27 個。這個表是「基準先冷卻、後篩條件」，
  漲停日又常連續出現，所以本研究的「每集合各自冷卻」次數應較多；**27／年只是下限**。
  核心計算會報每集合 2019+ 的逐年冷卻事件數，用來估前瞻需要多久，但不改上列前瞻規則。
  這是讀表粗估，不是本研究計算。前瞻期只涵蓋單一市場環境，結論受該期間行情左右。

## 成本估計（計算前）

| 階段                                  | 參考量測                                                           | 估計（未實測）                |
| ------------------------------------- | ------------------------------------------------------------------ | ----------------------------- |
| 讀共用價格＋指標                      | 讀一檔價格＋指標約 1.2 秒；整個 basis 三欄 0.31 秒（2026-10-19）   | 批次讀取 < 2 分鐘             |
| 逐股 atoms＋資格＋標籤                | 共用更新全市場指標重算 742 秒／2,065 檔（≈0.36 秒／檔，含寫入）    | 1,942 檔約 15–40 分鐘串行     |
| H 全市場 barrier                      | PR17 四股 barrier 2.39 秒；全市場未量測                            | 數分鐘，unknown               |
| 集合彙總、逐年、drop-best-year        | PR17 一組 integer feed 15.26 秒（含 92 候選）                      | < 10 分鐘                     |
| stock-cluster bootstrap               | 由每股 counts 重組，2,000 次                                       | 數分鐘                        |
| 型態分解（PR17 狀態可得）             | 讀約 96 MB int8 陣列                                               | 數分鐘                        |
| 型態分解（重跑 detector，**不授權**） | PR17 四股／48 targets event binding 721.83 秒                      | 約 97 小時串行                |
| 記憶體                                | 逐股處理，只保留 int8 bins、標籤與 counts（約 6.6M 列 × 20 bytes） | 主程序 < 1 GB，unknown        |
| 磁碟                                  | 終表小型 parquet                                                   | < 100 MB                      |
| 前瞻紀錄一天                          | 每股只讀尾段約 400 sessions 重算 atoms，加當日 H barrier；未量測   | 估數分鐘，unknown；探測時另量 |

核心合計估 30–90 分鐘串行。正式執行前先跑 20 檔探測：PR17 六個 strata
（1104、1416、1589、2330、6236、6986）加依 CRC 排序前 14 檔，記錄各階段 wall／CPU、RSS、I/O、
啟動與序列化時間；量不到者記 unknown。同輸入比較串行與 2、4 workers（PR17 實測設定上限），
結果須逐值相同，H barrier 與固定股票順序不變。停止規則：外推串行 > 4 小時且有限 workers 實測
更快才用 workers；外推 > 8 小時（含 workers）則停止並報告，不縮減定義。

## 交付

- `report.md`：開頭一段白話結論，回答「只看強勢條件能解釋多少」，附 4 個判讀格與基準對照表；
  附錄放全部表。
- `research_result.json`、`write_run_receipt` 收據（只對最終表計 SHA-256，記錄 generation、
  code commit、參數與本 mission；不對中間檔計 hash）。
- `data-contract.md` 與 `docs/en/research-program.md` 定位表一列（同一變更）。
- 前瞻紀錄指令與資料契約另行交付；第一次前瞻評估前不得改本 mission 的規則。

## 預設決定（owner 未指定，以下為本 mission 採用值）

| 決定               | 採用                                            | 理由                                                                              |
| ------------------ | ----------------------------------------------- | --------------------------------------------------------------------------------- |
| 條件集合           | 6 單一 + 15 兩兩 + `LEAD_B1` + 2 含型態 = 24 組 | 全部兩兩免挑選；三條件只取 PR17 已列的兩組，避免再搜尋                            |
| `PAT_other_B4`     | 視為型態 atom，含它的集合標 `pattern_involved`  | 它本身就是「最近出現 B4 跳空突破型態」，放進「只有條件」會自相矛盾                |
| 「沒有型態」的範圍 | 主要排除 9 個形狀家族；12 家族為次要            | L1／L2／L3 是新高、拉回、收復的單根旗標，幾乎等同強勢條件，全部排除會把強勢也拿掉 |
| 主要口徑           | 每日（與每日基準比）；冷卻只作 PR17 連續性      | owner 指定的兩個基準都是每日口徑，必須同口徑才可比                                |
| 不確定性           | stock-cluster bootstrap 2,000 次、seed 20261021 | 同一檔連續多日不是獨立樣本，按股票重抽才不會高估信心                              |
| 判讀門檻           | share ≥ 0.5、最小樣本冷卻 100 事件／30 檔       | 「解釋大部分」取過半；樣本門檻沿用 PR17 selector                                  |
| 前瞻累積期與評估   | 一年累積，H126 約 2028-04、H252 約 2028-10      | 半年累積幾乎只有個位數事件；一年讓單一及兩兩條件有機會達樣本門檻                  |
| 型態分解資料來源   | 只用 PR17 發布的原始狀態，不重跑 detector       | 重跑約 97 小時，與本題核心（只看條件）無關，不值得                                |
