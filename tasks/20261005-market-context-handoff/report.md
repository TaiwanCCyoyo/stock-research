# 研究資產交接與 0050 市場背景

> Current public-export availability (2026-10-09): source-data packages containing
> real quote vectors, anchor-close samples or corporate-action factors are retained
> locally, not distributed in the public repository. Historical receipts and fixed
> hashes retain their original identity. The 0050 context cannot be activated without
> its complete original input package; readers fail closed and do not download or
> recompute missing data. See [the bootstrap availability record](../../docs/en/bootstrap-stock-research.md#public-export-availability).

時點說明（2026-10-05 補記）：以下保留本次交接完成時的狀態與建議。
後續研究進度以 [研究總覽](../../docs/en/research-program.md) 為準；其中方法交互
與 H03 比較已有完成紀錄，勿把本報告末段的當時建議當成待重做清單。

已完成既有圖譜的可攜發布包，以及一版可重算的 0050 背景資料。沒有新選股
實驗、特徵組合校準、帳戶回測或策略通過結論。明確恢復後可做小批次研究，
不必等網站、全部產業分類或所有下載缺口。App 目標與研究排程未啟動。

## 其他 session 從哪裡開始

固定入口是 [research-program.md](../../docs/en/research-program.md)，不是聊天或 `.tmp`。

| 需要                                                 | 正式位置                                                                                                                                              | 能否從新 clone 取得                  |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| 38 個特徵的公式、全部 7,144 比較、正負結果及未知分母 | [atlas manifest](../20261004-feature-discrimination-atlas/publication-v2/manifest.json)、[原報告](../20261004-feature-discrimination-atlas/report.md) | PR 整合後可取得，不是只留最佳摘要    |
| 0050 狀態／轉換事件與原始輸入證據                    | [market context manifest](market-context-v2/manifest.json)、[本次契約](data-contract.md)                                                              | PR 整合後可取得，不依賴來源 worktree |
| 逐股逐日特徵／前瞻結果及比較重算                     | 原 atlas [契約](../20261004-feature-discrimination-atlas/data-contract.md) 中的 bulk 路徑                                                             | 否；為本機同碟副本，不是異地備份     |
| 方法來源、未完成組合假設、下一批理由                 | [method-environment-map](../20261004-method-environment-map/report.md)                                                                                | 文件可取得；提案不等於已評估         |

資料包分別約 0.81 MB、0.79 MB，保留自己的版本化契約，沒有新增資料庫或
強迫改用帳戶績效 schema。讀者驗證所有宣告檔案及身分。網站頁面未因本交接
而實作；獨立試讀不代表 UI 已整合。

## 0050 本版是什麼

採分類端已有的 catalog-v2，2010-01-04..2026-10-02，4,105 個共享觀察日，
4,100 個有效收盤、5 個缺價。這是現有來源涵蓋，不是資料最早可能年份或
未曾看過的驗證期間。未下載行情，未擴張舊 atlas 的 2019–2026 視窗。

事前固定一種月尺度描述：20 個日曆步驟、21 個收盤；端點漲至少 3% 為 up，
跌至少 3% 為 down，其他情況若最大／最小價差不超過 8% 為 consolidation，
再其他為 mixed；不足觀察或缺值保留 unknown。這是暫定描述規則，不是擁有者
核准的交易門檻，沒有看報酬後調參。

- `past_only`：當日以前的 21 點；未來價格變化不改寫保存列。
- `retrospective`：以前 10 點至以後 10 點；有未來資訊截止日，禁止用作當日訊號。
- `launch`／`resumption`：依固定狀態轉換定義的事件，不是 native wave、真正行情
  起點或買賣建議；首次已知／重置規則見契約。

| 層次          |  上升 | 下降 |  整理 | 混合 | 未知 | launch | resumption |
| ------------- | ----: | ---: | ----: | ---: | ---: | -----: | ---------: |
| past_only     | 1,351 |  796 | 1,803 |  110 |   45 |     61 |        109 |
| retrospective | 1,351 |  796 | 1,803 |  110 |   45 |     61 |        109 |

總數相同是相同完整 21 點視窗標在不同日期，**不是兩份獨立證據**。past_only
未知包含暖機 20 日及缺價影響 25 日；retrospective 包含暖機 10 日、未來不足
10 日及缺價影響 25 日。整段摘要本身是事後資訊。

0050 是大型上市股代理，不代表全台股。價格為來源的永久非純現金參考因子
調整收盤，不是含息總報酬。向後計算不代表歷史 PIT 已驗證；來源是回溯快照，
歷史公布時點仍未知。這些限制隨資料一同交付。

## 讀取例

從含本 PR 的 checkout 執行，不啟動新研究：

```powershell
uv run --no-sync python scripts/query_feature_atlas_publication.py --publication tasks/20261004-feature-discrimination-atlas/publication-v2 --verify
uv run --no-sync python scripts/query_feature_atlas_publication.py --publication tasks/20261004-feature-discrimination-atlas/publication-v2 --feature F33 --panel daily --context regime
uv run --no-sync python scripts/query_market_context.py --dataset tasks/20261005-market-context-handoff/market-context-v2 --verify
uv run --no-sync python scripts/query_market_context.py --dataset tasks/20261005-market-context-handoff/market-context-v2 --layer past_only --date 2026-10-02
```

Python：`research_core.feature_atlas_publication.load_publication`／`query_comparisons`；
`research_core.market_context_artifact.read_dataset`／`load_context_rows`。
使用明確版本，不自動找「最新資料」替換固定結果。

## 驗證、版本與交付狀態

- 合成及真實 CLI 入口測試 **100 passed**，涵蓋邊界、缺值、時間、事件、前綴
  不變性、可攜讀取、路徑、毀損、覆寫拒絕及重新雜湊後的語意矛盾。
- benchmark `--verify --recompute` 通過；atlas 發布包 hash／身分／計數通過。
  本次沒有重跑舊市場圖譜的逐股比較，沿用原先完整重算收據。
- 首份 gzip 封裝已算對，但其中大型文字壓縮檔超過正常單檔大小限制。原
  `publication-v1`、`market-context-v1` 保留本機；正式 v2 只改 XZ 無損封存形式。
  全部 0050 定義／結果／選定來源與原比較 JSON 位元組核對相同，沒有重選規則。
  公開 reader 支援正式 v2；舊封裝及產生提交保留，沒有默默替換。
- 原 atlas dataset：`fda-86245f2e223fc45c9f84afb0dcf77c1fff7ab22d0a1b0b4a4c8800972ce9327e`。
- Atlas publication：`feature-atlas-publication.v2-97453fbe244299c1d8a375a71eeb7811d825d081e3aff46309027988391a1e3a`。
- Benchmark dataset：`sha256:df2879f7f91e687dfb85f839e7ca8919af6b363b8038825d15d3f5f4796c8ed2`。
- 來源 manifest 前後 hash 均為 mission 固定的 `c7848ae7…0dfe140`。其他股票在
  來源 manifest 有列出，不代表其資料隨本包保存。
- 網站端獨立試讀通過：原位置及複製到 `strategy-presentation/.tmp/research-handoff-smoke-20261005-1916`
  的 17 檔／1,600,369 bytes 都可驗證與查詢，ID／列數一致，無 consumer 阻塞。
  F33 分層查詢保留 FP/FN、未知結果與未知背景；0050 缺值及截止日期正常。
  沒有修改產物、重算策略或接入 UI；此回交由主代理保存於本正式報告。
- 本地程式／mission／資料已正常 hooks 提交，17 個 Git blob 與驗證位元組一致。
  交付 [PR #26](https://github.com/TaiwanCCyoyo/Stock/pull/26)；以該 PR 的目前 head
  checks／review 為線上狀態依據，文件存在不等於 review 已完成。合併由擁有者處理。

詳見 [execution.md](execution.md)。這是交接及描述性資料驗證，不是策略批准。

PR 審查後補強完整封包／收據驗證、備份路徑限制、完整規則身分與 Windows
換行相容。另修正現金除息下跌被誤標缺值的條件；唯讀核對舊圖譜僅有的兩筆
跳價缺值均非現金事件，因此本次修正不影響保存結果。沒有重跑或覆寫舊成果；
後續執行須使用新的程式身分。影響範圍與證據見 execution 的更正紀錄。
包含後續資料集身分修正的相關測試為 **177 passed、1 skipped**；跳過項是主機
未允許建立符號連結的 Windows 測試，不代表該能力已驗證。既有兩個資料包仍通過讀取驗證。

## 本次交接當時建議的第一批

先從方法登記與完整正負比較選少量交互假設，固定比較數及停止條件，例如
強勢整理後突破、弱勢反轉在不同市場背景的差異。H03 同產業落後補漲仍需
明定同業、排除自身、相對強弱及分類可知性，不能說已被本資料證明。新 0050
標籤與舊 atlas 日期／價格口徑須先對齊，再立新批次，不修改舊比較。

擁有者可參考 [goal-proposal.md](goal-proposal.md) 更新並恢復 App 目標。本次不代為
啟動研究、排程或確認／holdout，也不要求所有資料問題解決才開始有界探索。
