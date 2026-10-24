# 強勢條件成立後，哪些轉弱訊號讓 2／3／5／10 倍機率下降？

狀態：**規劃中；尚未執行市場計算，沒有研究結論。**
工作包 A 固定本 mission；工作包 B 只交程式與合成測試。A、B 都由 owner 合併進 `main` 後，
才可開始工作包 C（包含真實市場探測、對齊檢查及全量執行）。合併由 owner 決定。

## 給 owner 的白話摘要

PR 61 已發現，符合強勢條件的股票比較容易翻倍，但最後沒有翻倍、收盤反而變低的比例也較高。
這次問：**強勢條件成立後的頭幾週，哪些轉弱訊號伴隨較低的後續大漲機率？如果看見訊號就放棄，
又會錯過多少最後真的漲上去的股票？**

會交付七個適用訊號在兩組強勢條件下的主要比較表：看見／沒看見訊號後，期限內達標的比例、
兩者差距、把當時已漲跌幅調整到相同分布後的差距，以及會錯過多少後來達標事件。
全市場與創高股票日作對照，其他倍數、期限與觀察時間全部附表，不只挑顯著格子。

2010-01-04..2026-10-12 整段資料已看過，強勢條件與訊號也來自這段歷史。結果只能描述關聯，
不能證明訊號造成下跌，不能充當獨立確認。達標只指收盤曾到達目標倍數，並非實際賺到的帳戶報酬。
本研究**不批准停損規則、不模擬買賣或帳戶**；錯殺比例提供 owner 判斷取捨，不另設通過門檻。

## 已看過的期間與證據等級

- 研究期間固定 2010-01-04..2026-10-12，全部為已暴露的描述性資料；不得改從 2019 起算。
- CRC development／cross-check 分半只作連續性描述，兩半皆非未看過的驗證資料。
- W1–W10 已經 owner 同意，以下原樣納入。不得事後換訊號、改格子、調門檻或並跑替代版本。
- 前序依據：[PR 61 mission](../20261021-momentum-only-doubling/mission.md) 的條件、標籤與 bootstrap，
  以及 [PR17 mission](../20261013-pattern-scan/mission.md#q4-episode漏抓q5路徑與q6旗標時間) 的旗標定義與時鐘。
  既有程式、結果、收據保持原樣；本研究的新行為放在新版本模組。

## 固定的設計決定（W1–W10）

| ID  | 決定                                                                                                                                                                                                                                                                                       | 理由                                                                                                                    |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| W1  | **條件組合**：主要是 PR 61 的 `CORE`（A1∧A2）與 `LEAD_B1`（A1∧A2∧A3）。對照是 `C-base-daily`、`C-52w-daily`，用來看同一個訊號在一般股票日上是不是也一樣                                                                                                                                    | 沿用 PR 61 主結論的兩組，不重新搜尋條件                                                                                 |
| W2  | **計數口徑**：每日口徑（PR 61 主口徑），所有組別使用 PR 61 的 effective-label 與 `event_main_eligible`；樣本是否足夠用冷卻口徑判定：先對組別成員資格照 PR 61 做 20 session 冷卻，**再**把冷卻後的事件依觀察點的訊號狀態拆成已觸發／未觸發，不在拆分後各自冷卻                              | 和 PR 61 的數字直接可比                                                                                                 |
| W3  | **訊號**：沿用 PR17 九個訊號的定義（`research_core/pattern_scan_flags_v1.py`）。適用的 7 個：`Y3`、`X5_MA20`、`X5_MA60`、`X6_10`、`X6_15`、`X7`、`X8`。`Y1`（close < 型態支撐 S）與 `Y2`（close < 型態下緣 L）需要型態給的 S／L，強勢條件沒有型態，**記 `not_applicable`，不另造替代價位** | 不新增定義；Y3 用 t0 當時已確認、價格低於 t0 收盤的 1.5ATR 低點中**價格最高**的一個（`event_flags` 的預設），不依賴型態 |
| W4  | **時鐘**：觀察點 L5／L10／L20／L40（小於期限者），期限 H126／H252／H504；目標 2／3／5／10 倍（與 PR 61 的 12 格相同）。訊號在 t0+1..tL 內首次出現算「已觸發」，到 L 都已知且未出現算「未觸發」，其餘 unknown                                                                               | PR17 時鐘加上 PR 61 的倍數與 H504                                                                                       |
| W5  | **風險集合**：PR17 `new_no_hit_valid_prefix` 推廣到每個倍數：t0..tL 價格完整、到 L 還沒達到**該倍數**的事件；L 當天達標不在集合內。跌破任何價位都不排除                                                                                                                                    | 只比較「到觀察點時還沒結束」的事件，避免把已經達標的算進來                                                              |
| W6  | **主要格子**：2 倍 × H126／H252 × L20 × 7 個訊號 × 2 組 = 28 格。其他倍數、期限、觀察點是次要格，用同一規則判讀、分開呈現                                                                                                                                                                  | 約一個月是實務上會做決定的時間點；先固定主格避免挑格                                                                    |
| W7  | **估計量**：風險集合內，「已觸發」與「未觸發」的後續達標比例差（與倍數）。另外依 L 當時已漲跌幅分層（PR17 `rise_bin`：<1、1–1.1、1.1–1.25、≥1.25 倍），以「已觸發」的分層分布為權重，算分層標準化差，用來分開「訊號本身」和「只是已經跌了」                                                | X6 本身就是跌幅；不分層就看不出其他訊號有沒有額外資訊                                                                   |
| W8  | **錯殺代價**：所有最後達標（calendar-full hit）的事件中，在首次達標前就觸發的比例，附 unknown 上下界（PR17 定義）。只報告，不設門檻                                                                                                                                                        | owner 判斷取捨用                                                                                                        |
| W9  | **不確定性**：同 PR 61，`stock`（seed 20261024）與 `two_way`（seed 20261025）bootstrap 各 2,000 次，由「股票 × t0 曆年」整數 counts 重組                                                                                                                                                   | 同股連續日相依、同一段行情同時影響許多股票                                                                              |
| W10 | **判讀**（依序，先符合者為準）見下表                                                                                                                                                                                                                                                       | 事前固定                                                                                                                |

| 判讀                  | 條件                                                                              |
| --------------------- | --------------------------------------------------------------------------------- |
| `not_applicable`      | Y1、Y2                                                                            |
| `inseparable`         | 已觸發或未觸發任一邊，冷卻口徑（W2 的順序）known_n < 100 或 distinct_stock_n < 30 |
| `weakens_beyond_drop` | 合併差與分層標準化差，**兩種 bootstrap 的區間上界都 < 0**                         |
| `weakens_with_drop`   | 只有合併差兩種區間上界都 < 0，分層標準化差不成立（訊號主要反映「已經跌了」）      |
| `opposite`            | 合併差兩種區間下界都 > 0（觸發後反而更常達標）                                    |
| `unresolved`          | 其他                                                                              |

報告列出全部格子；次要格個別出現 `weakens_*` 不能單獨當結論，要說明不同倍數、期限、觀察點之間方向是否一致。
年代（2010–2012、2013–2018、2019+）、CRC 分半、`drop_best_year`、`drop_best_stock` 全部呈現，但不進判讀規則。
LEAD_B1 只涵蓋 2015-06 以後（漲停代理 9.5% 在 7% 漲跌幅時代不可能成立），報告照 PR 61 說明。

## 輸入、母體與定義

沿用 PR 61「輸入、母體與定義」，只擴展本研究所需的倍數風險集合與旗標比較：

- 價格為共用 `adjusted-daily-v1` 的 `reference_factor_adjusted`（price-basis.v2），使用
  `read_adjusted_daily(..., as_of=2026-10-12, generation=固定值, calendar=pr17_calendar())`。
  每次讀取使用同一 generation，透過共用根目錄設定原地讀取，不複製或建立檔案系統連結。
- `momentum_only_v1.pr17_calendar()` 固定 4,110 sessions，自 2010-01-04 至 2026-10-12；
  三個年代 session 數為 748／1,475／1,887。`pr17_codes()` 固定 1,942 檔 ordinary-reference。
  缺少早期資料或日曆不同立即停止，不拼接、補價、縮短期限或替換母體。
- 逐日 S6 `base_eligible`：ordinary reference、60 個連續有效研究價、當日正量、前 20 日原始成交額
  全部可知且平均 ≥ NT$1m；依當日資格進出。沿用 `pattern_scan_inputs_v1.daily_qualification`。
- 強勢條件與對照成員資格、有效標籤、結果窗口品質與 `event_main_eligible` 全部沿用
  `momentum_only_v1`。`CORE` 即 A1∧A2（既有集合識別 `A1&A2`），`LEAD_B1` 即 A1∧A2∧A3。
  每日為主；冷卻先對每股每集合全部成員做 20 session earliest-first 冷卻，之後才依觀察點狀態分組。
- SMA20／SMA60／BB 下軌、1.5ATR 已確認高低點用
  `pattern_scan_indicators_v1.prepare_detector_frame` 與同一呼叫回傳的 pivots，與 PR 61 相同。
  若讀取的共用家族已存在相應數值欄，沿用 PR 61 的 20 檔逐值探測：1104、1416、1589、2330、
  6236、6986，加排除上述六檔後依 CRC 排序前 14 檔；每欄全部逐值相同才讀共用欄，否則用 PR17 adapter。
  只比較數值來源，不更動任何定義；pivot 依 `confirmation_index`／`confirmed_at` 判定當時是否可知。
- A1：close／MA240−1 ≥ 0.60；A2：close／前 250 日最低 close ≥ 2.5；
  A3：原始 close／前一日原始 close−1 ≥ 0.095。完全重用 PR 61 分箱與缺值規則。
- `multiple_outcomes_v1.outcomes_for_targets` 給 12 格標籤：t0+1..t0+H 首次 close ≥ 倍數×anchor 為 hit；
  完整路徑未 hit 且期末 close < anchor 為 loss，其餘 flat-win；缺價先於 hit 為 unknown。
  已知 hit 吸收後續缺價，但 calendar-full 與品質有效仍依 PR 61 主分母；截尾另列。
- Y3 選 t0 已確認、嚴格低於 anchor 的 1.5ATR 低點中價格最高者，並固定於 t0；無低點為 unknown。
  X5、X7 用當日均線或布林下軌，嚴格小於；X6 用固定 anchor 的 ≤90%／≤85%；
  X8 以確認日的新 high 與前一已確認 high 比較，嚴格較低才觸發。同日多個 high 的順序、
  缺值與首次決定吸收語意沿用 `pattern_scan_flags_v1.event_flag_observations`，不跨缺價補判。
  Y1／Y2 不適用，既不當 false，也不造型態支撐價。

## 比較、估計與輸出語意

- 每個組別 × 倍數 × H × L × 訊號皆保留已觸發／未觸發／unknown，輸出 known／hit／loss／flat-win、
  unknown／censored、事件數與股票數；零分母的率與比值為 null，不當零。
- 風險集合按各倍數分別判定；t0..tL 全部有效、L 當天尚未達標才比較後續結果。
  訊號只讀 t0+1..tL，結果終點始終為 t0+H，不從 L 重新起算期限。
- 合併差為已觸發達標率減未觸發達標率，比值為前者除後者。分層差以已觸發已知結果的四個
  `rise_bin` 分布為權重，對同層的兩組達標率相減後加權。已觸發有權重的層若沒有可比較的未觸發樣本，
  標準化差為不可估計，不刪層重正規化，也不宣稱 `weakens_beyond_drop`。
- Bootstrap 每次由相同股票／年份抽樣權重重組兩組整數 counts，重算合併差及分層差；
  `stock` 與 `two_way` 各 2,000 次、百分位 95% 區間，兩者分開保留。
  樣本不足先依 W10 判 `inseparable`；不可估計的區間不能視為跨過判讀門檻。
- 錯殺代價是所有最後達標的 calendar-full hit 中，訊號嚴格早於首次達標觸發的比例；
  同日達標不算達標前觸發。首次缺值先於觸發者為 unknown，另附分母、未知數及上下界。
- 所有格子、三個年代、CRC 分半與 `drop_best_year`／`drop_best_stock` 均完整保留。
  沿用 PR 61 集中度口徑：移除 eligible hit 最多的年（平手取早）或股票（平手取代號字典序小），
  從剩餘 counts 重算，不把這些描述加進 W10 判讀。
- 欄位語意引用 [PR17 data dictionary](../20261013-pattern-scan/data-dictionary-v1.md)；
  新增欄位與新模組 API 由工作包 B 的 `data-contract.md` 說明。主要 28 格單獨呈現，
  其餘完整表保存在 `results/`，次要格需報方向一致性，不以個別格作主結論。

## 計算前的對齊檢查（C-2）

A、B 都由 owner 合併後，先在含兩個合併的最新 `origin/main` 上確認 producer 閒置、
記錄 `adjusted-daily-v1` generation 並 hold（holder `strength-weakening-flags`），再做：

1. 使用本研究程式重算四組 `C-base-daily`、`C-52w-daily`、`CORE`、`LEAD_B1` 的
   2 倍 H126／H252 `known_n`／`hit_n`／`loss_n`，與 PR 61 已保存的
   `tasks/20261021-momentum-only-doubling/results/set_summary-all-full.parquet` **逐項完全相同**。
   `CORE` 對應原表 `A1&A2`；不把冷卻、年代或 CRC 子表混進每日全期比較。
2. 以固定 seed 20261024 隨機抽 200 個 CORE 事件，新模組與
   `pattern_scan_flags_v1.event_flag_observations` 在 2 倍格的適用訊號逐值比較：狀態、
   首次觸發 offset、riskset 與 rise_bin。Y1／Y2 記不適用，不拿它們當 false 對齊。

**任何一項不符就停止並回報，不調整規則。** 若是 generation 不同引起差異，列出差異、
受影響股票與原因，再交 owner 決定。本研究不沿用 PR 61「小差異可繼續」的容忍門檻，
也不在未通過對齊前產生全量旗標結論。

## 成本估計與資源量測

目前沒有本研究實測成本；PR 61 的量測只能作規劃參考，不能當成本保證。
正式全量執行前，在同一 generation、同一固定股票順序與資料上量測代表股票：

| 階段                     | 須記錄的成本／驗證                                                   |
| ------------------------ | -------------------------------------------------------------------- |
| 啟動、讀取價格與指標     | wall／CPU、RSS、I/O，啟動與序列化分開                                |
| 成員資格、標籤與旗標     | 每股 wall／CPU、峰值 RSS、輸入與輸出量；重用整股序列後再取事件       |
| 整數 counts 與 bootstrap | 依股票 × t0 年份彙總，再重組 counts；不重跑每日計算                  |
| 串行與有限 workers       | 相同 20 檔比較串行、2、4 workers，結果逐值相同；記錄傳輸／序列化成本 |
| 全量估算                 | 依代表樣本外推時間與磁碟；選定明確 worker、in-flight 與記憶體上限    |

量不到的項目明記 unknown；有其他研究同時使用機器時記下量測干擾。
依量測選資源上限，不追求 CPU 全開，不省略跨股／全域必要 barrier 或更動整數彙總順序。
任何市場 `--probe` 也屬工作包 C，不能於 A、B 合併前偷跑。

## 工作包、保存與停止條件

| 工作包 | 可交付內容                                                     | 下一步條件                      |
| ------ | -------------------------------------------------------------- | ------------------------------- |
| A      | 本 mission 與「規劃中」的 v2 研究卡片，同一 PR                 | owner 合併                      |
| B      | 新版模組、薄入口、合成測試、資料契約與資產索引，獨立 PR        | owner 合併；不含市場結果        |
| C      | 閒置／hold、對齊檢查、成本量測、全量運算與收據                 | A、B 皆已合併，C-2 全數完全相符 |
| D      | `report.md`、report-kit 網頁、卡片、研究歷史登記與共享資料引用 | C 完成並通過驗證                |

- 每包從最新 `origin/main` 開 task branch，使用 primary `.worktrees/` 下的獨立 worktree。
  本次 A 的 session-owned worktree 為 `.worktrees/strength-flags-mission`，B 為 `.worktrees/strength-flags-code`；
  owner 合併前保留。每包回報 PR、驗證結果、待 owner 決定事項。
- 不在平日 18:00–18:45 或任何 `StockProject-*` 執行中讀 producer；入口執行 `assert_producer_idle()`。
  不下載、不更動 producer、不新增或改動排程。
- 不改 PR 61／PR17 的程式、結果、收據；不碰 PR17 重跑程序及 `pr17-pattern-scan` hold。
  不碰 PR 61 primary 的 `forward-log/` 與 `StockResearch-MomentumForwardLog` 排程。
  只可終止自己啟動的 PID。
- 中間檔、checkpoint、續跑資訊一律用 `research_core/scratch_runs.py` 建立有標籤的共享 scratch run，
  不寫 worktree `.tmp/`；成功運算標 `complete`，最終結果交付後標 `delivered`。
  失敗時保留診斷與狀態，不覆寫已有成果。只處理本研究自己的 hold，完成交付後 release。
- 最終小表寫本 task `results/`；大型最終成果依研究資料根目錄規則保存，記錄取得位置。
  `write_run_receipt` 只對最終結果計 SHA-256，generation、code commit、定義、參數、
  mission 與輸入指紋是資訊紀錄；不對 sources／中間檔計 hash，不封存 producer 輸入副本。
- D 依 [study presentation](../../docs/en/study-presentation.md) 完成報告、網頁、歷史登錄及 shared-data 引用。
  網站可見文字不出現版本、雜湊、task ID、「快照」「世代」等技術識別字；證據與來源保留於 provenance。

## 本研究不做

不新增強勢條件或訊號、不跑替代版本、不重跑 pattern detector、不更動歷史研究，
不做前瞻紀錄、帳戶或停損模擬。訊號出現在 t0 之後，未來可另立研究評估 PR 61 的前瞻紀錄；
本 mission 不授權讀取該前瞻結果或改動它的記錄工作。
