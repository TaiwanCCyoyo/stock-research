# Codex handoff：強勢條件成立後，哪些轉弱訊號讓 2／5／10 倍機率下降

> **狀態：尚未開始。** 這份檔案只分工作包並固定設計決定；mission 還沒寫，沒有任何市場計算。
> 交付狀態的定義見[交付狀態](../../docs/en/research-program.md#delivery-states)。

開始前先讀 AGENTS.md、`docs/en/git-workflow.md`、`docs/en/research-owner-contract.md`，
以及前一份研究 [PR 61 momentum-only](../20261021-momentum-only-doubling/mission.md)（條件、標籤、bootstrap
全部沿用）和 [PR17 mission](../20261013-pattern-scan/mission.md) 的「Q4 episode／漏抓、Q5路徑與Q6旗標時間」一節
（訊號與時鐘全部沿用）。每個工作包各開一個 PR，從最新 `origin/main` 開分支，使用 `.worktrees/` 下的 worktree。

## 要回答的問題

PR 61 發現：強勢條件（CORE、LEAD_B1）成立的股票，翻倍比例明顯高於全市場，但「沒翻倍又收低」也更多。
這次問的是：**強勢條件成立之後的頭幾週，如果出現某個轉弱訊號，之後漲到 2／3／5／10 倍的比例會不會明顯下降？
用它提早放棄，又會錯殺多少最後真的漲上去的股票？**

這是 2010-01-04..2026-10-12 已看過資料上的描述，不批准停損規則、不模擬帳戶。

## 開工順序

| 工作包        | 前置條件             | 可以平行嗎                      |
| ------------- | -------------------- | ------------------------------- |
| A. Mission    | 無                   | 可以和 B 平行                   |
| B. 程式與測試 | 無                   | 可以和 A 平行；不得產生市場結果 |
| C. 執行       | A、B 都由 owner 合併 | 否                              |
| D. 報告與收尾 | C 完成               | 否                              |

共同規則：

- 不改寫、不刪除既有資料；PR 61、PR17 的程式、結果、收據一個位元組都不改。需要不同行為就加新版本模組。
- 平日 18:00–18:45 與任何 `StockProject-*` 排程執行中不讀 producer（`assert_producer_idle()`）。
- 長時間計算用 `research_core/scratch_runs.py` 建立 run，不寫 worktree 的 `.tmp/`。執行跨日就 hold 共用世代，完成後 release。
- 只能終止自己啟動的 PID，不准 `taskkill /IM python.exe`。
- 不下載、不改排程、不碰 PR17 的 `pr17-pattern-scan` hold 和 PR17 重跑中的程序，也不碰 PR 61 的前瞻紀錄
  （primary checkout 的 `tasks/20261021-momentum-only-doubling/forward-log/` 與 `StockResearch-MomentumForwardLog` 排程）。
- 網站上看得到的文字不出現版本、雜湊、task ID、「快照」「世代」等字眼。

---

## 固定的設計決定（A 必須原樣寫進 mission）

以下由主 session 依技術預設決定。owner 在 mission review 時可以改，改了就寫進 mission，
**不另外並跑替代版本**。

| ID  | 決定                                                                                                                                                                                                                                                                                       | 理由                                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| W1  | **條件組合**：主要是 PR 61 的 `CORE`（A1∧A2）與 `LEAD_B1`（A1∧A2∧A3）。對照是 `C-base-daily`、`C-52w-daily`，用來看同一個訊號在一般股票日上是不是也一樣                                                                                                                                    | 沿用 PR 61 主結論的兩組，不重新搜尋條件                                       |
| W2  | **計數口徑**：每日口徑（PR 61 主口徑），所有組別使用 PR 61 的 effective-label 與 `event_main_eligible`；樣本是否足夠用冷卻口徑判定（同 PR 61）                                                                                                                                             | 和 PR 61 的數字直接可比                                                       |
| W3  | **訊號**：沿用 PR17 九個訊號的定義（`research_core/pattern_scan_flags_v1.py`）。適用的 7 個：`Y3`、`X5_MA20`、`X5_MA60`、`X6_10`、`X6_15`、`X7`、`X8`。`Y1`（close < 型態支撐 S）與 `Y2`（close < 型態下緣 L）需要型態給的 S／L，強勢條件沒有型態，**記 `not_applicable`，不另造替代價位** | 不新增定義；Y3 用 t0 前最近一個已確認、低於 t0 收盤的 1.5ATR 低點，不依賴型態 |
| W4  | **時鐘**：觀察點 L5／L10／L20／L40（小於期限者），期限 H126／H252／H504；目標 2／3／5／10 倍（與 PR 61 的 12 格相同）。訊號在 t0+1..tL 內首次出現算「已觸發」，到 L 都已知且未出現算「未觸發」，其餘 unknown                                                                               | PR17 時鐘加上 PR 61 的倍數與 H504                                             |
| W5  | **風險集合**：PR17 `new_no_hit_valid_prefix` 推廣到每個倍數：t0..tL 價格完整、到 L 還沒達到**該倍數**的事件；L 當天達標不在集合內。跌破任何價位都不排除                                                                                                                                    | 只比較「到觀察點時還沒結束」的事件，避免把已經達標的算進來                    |
| W6  | **主要格子**：2 倍 × H126／H252 × L20 × 7 個訊號 × 2 組 = 28 格。其他倍數、期限、觀察點是次要格，用同一規則判讀、分開呈現                                                                                                                                                                  | 約一個月是實務上會做決定的時間點；先固定主格避免挑格                          |
| W7  | **估計量**：風險集合內，「已觸發」與「未觸發」的後續達標比例差（與倍數）。另外依 L 當時已漲跌幅分層（PR17 `rise_bin`：<1、1–1.1、1.1–1.25、≥1.25 倍），以「已觸發」的分層分布為權重，算分層標準化差，用來分開「訊號本身」和「只是已經跌了」                                                | X6 本身就是跌幅；不分層就看不出其他訊號有沒有額外資訊                         |
| W8  | **錯殺代價**：所有最後達標（calendar-full hit）的事件中，在首次達標前就觸發的比例，附 unknown 上下界（PR17 定義）。只報告，不設門檻                                                                                                                                                        | owner 判斷取捨用                                                              |
| W9  | **不確定性**：同 PR 61，`stock`（seed 20261024）與 `two_way`（seed 20261025）bootstrap 各 2,000 次，由「股票 × t0 曆年」整數 counts 重組                                                                                                                                                   | 同股連續日相依、同一段行情同時影響許多股票                                    |
| W10 | **判讀**（依序，先符合者為準）見下表                                                                                                                                                                                                                                                       | 事前固定                                                                      |

| 判讀                  | 條件                                                                         |
| --------------------- | ---------------------------------------------------------------------------- |
| `not_applicable`      | Y1、Y2                                                                       |
| `inseparable`         | 已觸發或未觸發任一邊，冷卻口徑 known_n < 100 或 distinct_stock_n < 30        |
| `weakens_beyond_drop` | 合併差與分層標準化差，**兩種 bootstrap 的區間上界都 < 0**                    |
| `weakens_with_drop`   | 只有合併差兩種區間上界都 < 0，分層標準化差不成立（訊號主要反映「已經跌了」） |
| `opposite`            | 合併差兩種區間下界都 > 0（觸發後反而更常達標）                               |
| `unresolved`          | 其他                                                                         |

報告列出全部格子；次要格個別出現 `weakens_*` 不能單獨當結論，要說明不同倍數、期限、觀察點之間方向是否一致。
年代（2010–2012、2013–2018、2019+）、CRC 分半、`drop_best_year`、`drop_best_stock` 全部呈現，但不進判讀規則。
LEAD_B1 只涵蓋 2015-06 以後（漲停代理 9.5% 在 7% 漲跌幅時代不可能成立），報告照 PR 61 說明。

---

## A. Mission

**產出：** `tasks/20261024-strength-weakening-flags/mission.md`（中文，格式參照 PR 61 mission）。

1. 開頭給 owner 的白話摘要：問題、為什麼歷史資料只能描述、會得到什麼、不會得到什麼（不批准停損規則）。
2. 把上面 W1–W10 原樣寫入；列出已看過期間與證據等級（整段 2010-01-04..2026-10-12 已看過）。
3. 輸入與定義沿用 PR 61「輸入、母體與定義」一節：`adjusted-daily-v1` 的 `reference_factor_adjusted`，
   `read_adjusted_daily(..., as_of=2026-10-12)`，`pr17_calendar()`（4,110 sessions，起點 2010-01-04，不得改 2019）、
   `pr17_codes()`（1,942 檔）、S6 資格。SMA20／SMA60／BB 下軌與 1.5ATR 已確認高低點用 PR17 adapter
   （`pattern_scan_indicators_v1.prepare_detector_frame` 與 PR17 pivot 程式）；若共用家族有對應欄，比照 PR 61 的 20 檔逐值探測規則決定讀哪個。
4. 列出計算前的對齊檢查（見 C-2）與成本估計要求。
5. 寫明本研究不做：前瞻紀錄（訊號發生在 t0 之後，可在之後另立研究用 PR 61 前瞻紀錄評估）、帳戶或停損模擬、新增條件或訊號。
6. 同 PR 交 `study.json`（v2 卡片，若 study-cards-v2 尚未合併就先交 `presentation.json` 的最小版本），狀態「規劃中」。

驗收：mission 不含任何市場數字以外的新計算結果；PR 描述列出 W1–W10 供 owner 逐項確認。

## B. 程式與測試

不改既有模組；新增版本化模組，放 `research_core/`，入口放 `scripts/`，測試放 `scripts/tests/`。

1. **`research_core/multiple_observations_v1.py`**：把 `hhhl_variants_observations.classify_window` 與
   `landmark_riskset`（兩處把 2 倍寫死）推廣成倍數參數。測試：倍數 2 時與原函式**逐值相同**（含缺價、截尾、L 當天達標）。
2. **`research_core/strength_flags_v1.py`**：對一檔股票的大量 t0 一次算出 7 個訊號在每個觀察點的
   已觸發／未觸發／unknown、首次觸發 offset、達標前是否觸發。X5／X7／X8 與 t0 無關，可先算整條日序列再對每個 t0 取「下一個 true」；
   X6 依 t0 收盤；Y3 依 t0 當時已確認的低點。Y1／Y2 一律輸出 `not_applicable`。
   測試：對合成資料與隨機抽樣的 t0，與 `pattern_scan_flags_v1.event_flag_observations` **逐值相同**
   （訊號狀態、首次觸發 offset、riskset、rise_bin）；涵蓋等號邊界、缺價、pivot 確認晚於 t0、同日多個 high。
3. **計數與 bootstrap**：沿用 `momentum_only_v1` 的組別成員資格與「股票 × 年份」整數 counts 結構，
   每格存已觸發／未觸發／unknown 的 known、hit、loss 與 rise_bin 分層 counts；bootstrap 從 counts 重組，不重跑逐日計算。
   有共用的就 import，需要新行為就放新模組，不從 `scripts/` 匯入私有 helper。
4. **入口 `scripts/run_strength_flags.py`**：薄包裝，支援 `--probe`（少量股票量測）與正式執行；輸出寫 scratch run，
   最終小表寫 `tasks/20261024-strength-weakening-flags/results/`，以 `write_run_receipt` 記錄 generation、commit、定義、參數與輸入指紋。
5. 在 `docs/en/research-program.md` 資產索引登記兩個新模組與資料契約。

驗收：所有測試在合成資料上通過；PR 不含任何真實市場結果。

## C. 執行（A、B 合併後）

1. 前置：檢查排程與 producer 閒置；記錄並 hold 讀取的 `adjusted-daily-v1` generation（holder `strength-weakening-flags`）。
2. **對齊檢查，任何一項不符就停下回報，不調整規則：**
    - 以本研究程式重算 `C-base-daily`、`C-52w-daily`、`CORE`、`LEAD_B1` 的 2 倍 H126／H252 known／hit／loss，與 PR 61
      `results/set_summary-all-full.parquet` 完全相同。若因 generation 不同而有差，列出差異與原因後停下問 owner。
    - 隨機抽 200 個 CORE 事件，新模組與 `event_flag_observations` 逐值相同。
3. 成本：代表股票上量測串行與有限 worker 的 wall／CPU／RSS／I/O，選明確 worker 與記憶體上限（AGENTS.md「Research And Data」）。
4. 全量執行；完成後 `run.json` 標 `complete`，結果交付後標 `delivered`。
5. 回報：主要 28 格的判讀、次要格方向一致性摘要、錯殺代價、執行時間與資源量測。

## D. 報告與收尾

依 `skill: study-presentation` 與 `docs/en/research-program.md#收尾條件`：

1. `report.md`：先白話結論，主表是 28 個主要格子（訊號 × 組別 × 期限：觸發後達標率、未觸發達標率、差、分層差、錯殺代價、判讀）；
   次要格與全部表放附錄與 `results/`。
2. `web-report/`（用 report kit），讀者看得懂的文字，不出現技術識別字。
3. 更新 `study.json`、研究歷史登記、`docs/en/research-program.md` 索引列。
4. release generation hold；scratch run 依規則交付後清理。
