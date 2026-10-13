# 補配股與年度研究資料的有界交接

先補 **7 個已選股票的持有期間**，能改善本次所選組合的可計性；要證明
「全台股前一年冠軍」，另須補全候選排名與 PIT 母體。兩者不可混稱資料完成。
本文件是供 parent 安排獨立資料任務的契約草案，沒有啟動新 worker、下載或改排程。

## 正式位置與責任

| 層                       | 目前位置                                                                                               | 內容與狀態                                                                                                                                                                                              |
| ------------------------ | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Producer canonical       | `D:/Project/stock-research/stock-data-downloader/data/corporate_actions.sqlite`                        | `corporate_actions`、`corporate_action_raw_ranges`；2026-10-13 唯讀盤點為 32,855 事件，2003-05-05 至 2026-10-13，`share_factor`／`cash_per_share` 非空皆 0。這是目前 live vintage，不等於本研究凍結版。 |
| 本研究 physical snapshot | `D:/Project/stock-research/.worktrees/annual-winner-taiwan/stock-data-downloader/data/`                | checkout hook 實體快照；保留 receipt，未連結 mutable producer。                                                                                                                                         |
| 本研究正式共享 input     | primary `research_data/prices/annual-rotation-inputs/`，由 `params/input-pin-v1.json` 指定 `de7a91ec…` | 32,853 事件與截至 2026-10-12 的原始價格／metadata；明確不可變 version，由 PR12 catalog 發現。                                                                                                           |
| 本次缺口證據             | 本 task `sweep_results.json`、共享 process 的 `holding-paths.json.gz`／`candidates.json.gz`            | 原始及 review-replay process 並存；完整缺口日期與事件來源可重讀，無需重算排名。                                                                                                                         |

核心欄位：`source, market, code, ex_date, event_type, previous_close,
reference_price, value_plus_dividend, cash_dividend_estimate, price_factor,
share_factor, cash_per_share, evidence_status, detail_key, raw_fields_json,
fetched_at`。raw range 表另保留 source/range/status/row_count/raw_path/sha256。

這些空欄位的判讀必須分層：

- `fetch_corporate_actions.py` 的 TWSE／TPEx normalizer **明確寫入**
  `share_factor=None`、`cash_per_share=None`。不是已證明官方資料為空。
  TPEx 原表現金股利會解析為 `cash_dividend_estimate`，TWSE 參考價資料也有
  權息估值，但 adapter 尚未建立精確、已連結事件的經濟權利欄位。
- 本機 `raw_fields_json` 與年度 raw JSON 可先離線重解析；檔名盤點有
  TWSE twt49u/twtauu/twtcau 約 68/65/65 檔，TPEx exdailyq/revivt 40/35 檔，
  DB 有 300 筆 raw ranges。檔名或 row count 不保證 payload 完整；需核 hash、
  status、日期／代碼／欄位並核對 revision。不得追讀 `<legacy-checkout>` 路徑。
- producer 已有純離線 MOPS `project_statement`、`project_rights_statement`：
  分開保存每仟股盈餘／公積配股、精確 Fraction bonus_per_share、現金息、
  stated record/ex/payment date 與 unresolved 狀態。這不是已完成 event linkage、
  最新修正選擇、實際入帳或歷史公開時點。
- 研究 `economic_path` 目前僅支持現金息估值與明確 ETF split；一般除權、
  混合權息、減資尚不支持。因此補 source 不會自動使研究結果可計，須新增
  versioned research entitlement policy／測試，保留舊結果。

## 主策略 7 個未解決完整持有年度

| 年／股票   | 精確已觀測缺口                                                      | 已有事件證據／尚需補證                                                                                                                                                            |
| ---------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2011／3406 | 2011-03-17 `EX_RIGHT`                                               | TWSE TWT49U、detail key `3406,20110317`，REFERENCE_PRICE_ONLY；精確普通股無償配股比例／種類與適用日期、必要時現增權利分開，`share_factor/cash_per_share` 皆 null，kernel 不支持。 |
| 2012／6276 | 2012-07-16、17、18、19、20、23、24、25、26 缺官方報價               | 凍結 action 表未見該持有窗的非現金事件。需判斷真停牌／無成交／資料漏取，查官方停復牌與原始 daily payload；不能一律補成價格不變。TPEx revivt 舊期 coverage 不可假設完整。          |
| 2016／3205 | 2016-08-17 `EX_RIGHT_AND_DIVIDEND`                                  | TPEx exDailyQ、REFERENCE_PRICE_ONLY、無 TWSE detail key；精確配股、每股現金息、權利／付款日期及公告連結，兩精確欄皆 null，kernel 不支持。                                         |
| 2018／3162 | 2018-09-26、10-08、10-31、11-05、12-06、12-13 缺官方報價            | action 表無該窗非現金事件；需官方原始報價及停牌／零成交分類，保留原值與查核狀態。                                                                                                 |
| 2020／6538 | 2020-08-27 `EX_RIGHT_AND_DIVIDEND`                                  | TPEx exDailyQ、REFERENCE_PRICE_ONLY；精確配股／現金息／權利及付款日期，兩精確欄皆 null，kernel 不支持。                                                                           |
| 2024／1519 | 2024-07-25 `noncalendar_action`；事件其實是 `EX_RIGHT_AND_DIVIDEND` | TWSE TWT49U detail key `1519,20240725`、REFERENCE_PRICE_ONLY；核官方事件改期／休市後生效與 MOPS 修正，再補配股／現金權利。不能擅自把事件移到下一交易日。                          |
| 2025／5314 | 2025-03-20、21、24、25、26、27、28，08-12，10-14，12-08 缺官方報價  | action 表無該窗非現金事件；需官方缺報價分類及停復牌原文。                                                                                                                         |

以上有 **4 個權利事件、25 個缺報價日期**。這是本次 kernel 已觀測到的 blockers，
不是已證明補好它們就沒有其他經濟或執行問題。仍須重新驗證整個持有窗。
8 個可計年度也有共同的 PIT 上市／上櫃普通股資格、歷史類型、下市 census、
source publication timing、估值現金息與分數股／成交性缺口；「可計」不是無偏。

## 補資料查證現況（暫存、尚未發布）

- 原補資料 session 把 4 個權利事件的官方條件與 25 個報價日期的官方回應，保存在
  `stock-data-downloader/.tmp/annual-winner-supplement-20261013/`。那是暫存目錄，
  不在 Git，也不是 canonical 資料。結構化候選資料（43 筆來源、11 個事件、27 筆逐日觀察、
  7 個年度案例）的入口是同目錄 `README.md`。本次審查（2026-10-14）獨立核對：收據
  `capture-receipt.json` 涵蓋 178 個證據檔，位元組數與 SHA-256 全數相符（0 缺漏、
  0 不符），候選資料引用的 104 個檔案都在其中；凍結輸入的 `corporate_actions.sqlite`
  也與本研究 pin 一致。我沒有執行對方的 PowerShell 驗證器。這只證明「擷取檔完整」，
  不證明內容已可用於計算。先前寫的 78 個檔案是舊範圍快照，以此為準。
- 狀態：6276、5314（3/20–3/28、8/12、12/08）的停牌、1519 的休市與 4 個事件的官方條件
  已有來源；仍未解：3162 的 2018-09-26（兩份官方資料成交筆數不一致，不能當零成交）、
  5314 的 10/14 復牌日、3406 與 3205 的欄位／單位與連結。尚未寫入正式資料庫，也未用補充
  資料重算；由原補資料 session 繼續查證。
- 這 7 個持有年度是「目前無法完整計算」（配股／認股處理加報價缺口），不是整年行情都缺。
- 補資料進來之後怎麼算，已寫成待 owner 審查的草稿：[holding-policy-v2.md](holding-policy-v2.md)（只定規則，未計算任何報酬）。
- 本 PR 的結論不使用這些暫存證據。要使用，須先成為新的版本化輸入（producer 另行交付、
  契約與寫入條件經 owner 核准，見其 `evidence-ledger.md` 末節），再依預先登記的事件與
  缺報價處理定義重算；舊結果保留。

## 工作量與官方來源

補 7 持有窗只針對 7 個股票年、4 個已知權利事件與 25 個報價日期。補全年度排名
則涉及 2,061 檔、16 排名年、25,883 個觀測 stock-year、8,413 個未知排名，還有
今日 dataset 完全未包含的下市股票；不是放大同一個 7 年清單即可完成。
先量測 offline reparse 覆蓋／missing counts，才估算網路請求和完整 backfill；
不預先承諾能補完，亦不重跑全市場來估算。

| 補證                       | 優先來源                                                                                                                                                                                                                                                                   |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 原始權息／參考價           | 本機 raw 先核 hash，再 [TWSE TWT49U](https://www.twse.com.tw/zh/announcement/ex-right/twt49u.html)、[TWT48U](https://www.twse.com.tw/zh/announcement/ex-right/twt48u.html)、TPEx exDailyQ／[官方資料目錄](https://data.gov.tw/dataset/11633)。混合參考價不是精確股數倍率。 |
| 配股、現金息、付款修正     | [MOPS](https://mops.twse.com.tw) 股東會及股利／除權息公告、issuer 原公告、重大訊息修正，保留每個公告版本、原文、request identity／retrieval time；不得把 stated payment date 當實際入帳。                                                                                  |
| 減資、停復牌、休市事件改期 | TWSE TWTauu、TPEx revivt 明細、MOPS 減資計畫；[TWSE 歷史暫停交易](https://www.twse.com.tw/zh/trading/historical/twtawu.html)、[TPEx 停復牌](https://www.tpex.org.tw/zh-tw/announce/market/halt.html)。                                                                     |
| PIT 上下市與歷史資格       | [TWSE 公文／終止上市公告](https://www.twse.com.tw/zh/announcement/announcement/list.html)、TPEx 終止上櫃公告及歷史名錄；不能拿今日清單補歷史。                                                                                                                             |

以上官方頁與本機 source config 已查核；MOPS 當前 HTTP route、所有歷史端點的
可取得性未逐筆實測。現有 bounded corporate detail capture 可每批限制
`--max-requests 5 --max-seconds 120`，無 redirect/retry；不是已授權本任務立即抓取。

## 建議獨立 Luna max 任務

以「7 個已選持有窗的經濟事件／缺報價補證」為第一階段，parent 若安排 Luna max，
worker 先讀 producer 操作規範、盤點現存 raw，不重算排名，不參與 PR14 或本 PR15。
先離線處理 4 個事件與 25 日期；只有本機缺證時，提出明確官方 request plan，
起始上限 20 requests／10 分鐘、每批遵循既有更小 capture limits，禁止大市場下載、
producer 重啟、排程／安全設定或額外付費。

輸出應包括：canonical producer retained raw + hash/request receipts、versioned
normalized event records（精確 decimal/rational 值、ordinary/share class、cash/bonus/
subscription 分開、有效日、付款日及狀態、revision/event linkage、來源公開／取得
時點）、每缺報價日分類及原文證據、仍 unresolved 清單與 parser synthetic tests。
原始取得／normalization 只在 stock-data-downloader 獨立 task worktree 開發，
不把事件數值私有硬編碼到研究 task。producer 由 owner merge 後依操作契約更新
primary canonical data，再由 research 建新不可變 input/version 與新的 kernel 結果。
舊 input／process／報告保留；需另登記來源／定義相容性與已看過 exposure。

## Writer／worktree 避讓（2026-10-13 本輪盤點）

- PR15：`.worktrees/annual-winner-taiwan`，本 session 所有；年度全市場計算已退出，
  held-path replay 已完成，共用 annual bundle 目前沒有本 session active writer。
- PR14：`.worktrees/research-data-entry`，`codex/pattern-scan-mission`，別的 session；
  不改檔、不使用其 mutable cache。其運算是否仍在執行未由本次盤點確認。
- 其他非本 session：`.worktrees/lf-text-policy`、`research-feature-reuse`、
  `research-report-shell`；primary inventory 已有五個非 primary checkout。
  五-worktree budget 按 session 所有權計算；其他 session 的 checkout 不算新 worker
  的持有量。新 worker 仍先做 lifecycle／自身預算盤點，不清他人 checkout。
- producer inventory另有 `stock-data-downloader/.worktrees/lf-text-policy`，不可重用。
  canonical actions 已比本研究 snapshot 多 2 筆，證明 mutable vintage 正在變動；
  寫入者／排程是否 active 未確認。新增 canonical 寫入前必須按既有 records 協調
  single writer，不以只讀 metadata 或檔名判斷無人使用。

安全 scanner 核准問題另行處理；本資料交接沒有更動 baseline、filter 或 hook。
