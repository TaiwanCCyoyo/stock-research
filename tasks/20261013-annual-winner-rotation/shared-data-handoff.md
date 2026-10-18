# PR30 共用資料整併交接

更新：2026-10-19。這是 PR30 session 的現況與待確認事項，不代表已完成資料遷移。
本輪僅整理文件，沒有改程式、重算、搬移／刪除資料、推送或 merge。

## 2026-10-19 Claude review 結果

以下為本 handoff 之後的處理，下方原文保留作為當時待辦。

| 項目                         | 結果                                                                                                                                                                                                                                                                                                                                                                                                  |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 已整併：官方報價與交易日曆   | `maintained_adjusted_daily.read_official_quotes` 從共用世代讀驗證過的官方報價與日曆；runner 預設 `--quotes shared`，不再掃描 `price_daily.parquet`。對世代 `2026-10-16-20261018T161203Z` 兩種讀法重跑，`results.json`／`admission-audit.json` 與 completion-v2 逐值相等；load 階段 1.49 s／1.20 s CPU 對 2.76 s／3.03 s。見[資料契約](publications/completion-v2/data-contract.md#later-quote-source) |
| 已整併：receipt 記錄共用世代 | `write_run_receipt(..., shared_data=[record])` 記錄世代與 SHA-256，不重新雜湊大檔，並拒絕執行中被刪除或替換的世代                                                                                                                                                                                                                                                                                     |
| 保留在研究內                 | 經濟模型、認股權情境、來源採認、選股序列與結果。共用 `actions.parquet` 只有價格因子，現金／股數／來源欄位仍唯讀 producer `corporate_actions.sqlite`                                                                                                                                                                                                                                                   |
| 未做：官方補證併入正規化表   | 屬 producer 正規化，需獨立 submodule PR 與 writer 協調；補證正本已在 producer root，不另搬副本                                                                                                                                                                                                                                                                                                        |
| completion-v2 歷史結果       | 檔案、receipt、ZIP 未改；`--quotes producer` 於其 receipt commit 可原樣重現。`verify_published_artifacts` 17/17 通過                                                                                                                                                                                                                                                                                  |

PR17 中間資料（run `full-2010-20261016-retention-v3`，未改動）：每檔 `indicators.parquet` 共 1,493 MB，其中共用同名指標 66.8%、價格欄 18.1%、BB 別名 7.3%、研究專屬 F 欄 0.3%。隨機 40 檔以共用世代在 2026-10-12 截止重算，價格、指標與 pivots 全部逐值相等；全市場重算約 1 小時（單程序推估）。截止日不等於世代 asof，所以只能重算，不能直接讀 `technical_daily`。退場與否由 PR17 擁有者依下游讀取決定。

## 核對基準

- [PR30](https://github.com/TaiwanCCyoyo/stock-research/pull/30)：open，遠端 head `a2403a6`；本 session worktree 為 `D:/Project/stock-research/.worktrees/annual-winner-html-report`，branch `codex/annual-winner-refresh`。
- [PR17](https://github.com/TaiwanCCyoyo/stock-research/pull/17)：open，遠端 head `1848205`。PR 說明中的執行數字是作者記錄，本輪沒有獨立讀取本機研究 receipts。
- 已 fetch；`origin/main` 為 `8ae5182`，已包含 [PR32](https://github.com/TaiwanCCyoyo/stock-research/pull/32) 技術指標／確認高低點及 [PR33](https://github.com/TaiwanCCyoyo/stock-research/pull/33) 封存原碼還原。PR30 尚未納入這兩個更新，本輪遵照指示不 merge。
- 請與之前 review PR17 的 session 核對「PR 分支實作、main 共用能力、本機資料／研究執行」三層現況。不可把 PR17 舊 checkpoint 或前次討論，當成最新共用資料的完整盤點。

## PR30 現有資料與分工

| 項目                     | 現在的位置／狀態                                                                                          | 整併判斷                                                                                                         |
| ------------------------ | --------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| 原始行情與公司事件資料庫 | `D:/StockData/stock-data-downloader/`，透過 `producer_data_root()` 唯讀；v2 沒有新增行情／資料庫副本      | producer 維護來源事實；不能因改接共用價格就遺失股數、現金與認股權資訊                                            |
| 官方補證                 | 同一 producer root 的 `corporate_action_supplements/annual-winner-20261013-v1/`，185 檔、26,706,236 bytes | 已有 canonical 正本，不必再搬一份；尚未整合進 normalized `corporate_actions.sqlite`，可供通用來源事實整併 review |
| 共用還原價格／技術指標   | `D:/StockData/stock-research/derived/adjusted-daily-v1/`，由 `STOCK_RESEARCH_SHARED_ROOT` 定位            | main 已有價格及 `read_technical` 機制；本輪未確認目前實體 generation 是否含新指標，也未執行 update               |
| 經濟模型與來源採認       | `research_core/annual_rotation_v2.py`、`annual_completion_evidence.py`、`annual_completion.py`            | 通用事實讀取可抽離；現有 supplement adapter 仍含特定股票／證據判定，位於 library 不等於已是通用資料介面          |
| 定義、結果、報告         | 本 task 的 `publications/completion-v2/`、`publications.json`、`web-report/`                              | 小型結果、收據 ZIP、Markdown／HTML 適合 Git；保留 v1 與 v2 的獨立身份，不因接共用資料覆寫舊結果                  |

年度固定選股、持有期間、成本、現金再投入、認股權兩情境及 carry 規則，仍屬 PR30 的研究定義。`reference_factor_adjusted` 是參考因子還原價，不是含現金／股數權益的帳戶總報酬；不能直接取代經濟模型。若改用共用 raw reader，也要先核對欄位、品質、日曆、截止日及結果等價，不能只比較名稱。

詳見 [v2 資料契約](publications/completion-v2/data-contract.md)及[空間／成本盤點](publications/completion-v2/storage-audit.md)。其中備份與大小是既有 2026-10-16 記錄，本輪沒有重盤磁碟或重做雜湊。

## 請 Claude review 的範圍

1. **先分類再整併。** 查資產索引與最新共用契約，列出 PR30 哪些來源事實／讀取能力可重用或補進既有正本，哪些仍屬研究政策；不要另建同義 family 或只把資料搬到另一個資料夾。
2. **核對 PR17 後續處理。** main 已新增共享指標與 pivots，不代表 PR17 的歷史 checkpoint 已完成接線或等價移交。與 review session 確認哪些已處理、哪些仍待辦，再看 expanded events／conditions／groups 能否以單份基礎資料、引用或逐批聚合取代；用小範圍相同結果比較與容量量測支持判斷。64 GiB 是舊物化流程額度，不能當最低必要空間。
3. **保留研究與證據邊界。** 特定條件、未來報酬標籤、年度經濟情境不直接塞進共用指標。封存程式與結果不改寫、不重新宣稱來源身份；改接共用資料需要新版本／移交證據。
4. **完成可發現、可維護的交付。** 整併需有資料契約、更新入口、資產索引、消費端切換與驗證、receipt 身份及備份責任。每程序重用已驗證的 bytes，先量測再增加大檔掃描。不要把 worktree-only 檔案當交付完成。

已知待分類項目：舊 session `.tmp/annual-winner-supplement-20261013/` 約 26.7 MB 捕捉副本，與 v1 約 238 MB 固定輸入封存是不同保留義務。前者先確認原 session 所有權，後者維持歷史契約；本文件不授權刪除。共用 generation 沒有 lease，pin 不保證永久保留；研究不得自行清理共用資料。

## 專案目前的 SOP 與待 review 處

**已有明確規則，不是從零開始；但跨研究整併是否形成完整閉環，仍需 review，不能只因有規則就宣稱已完成。**

- [main 的共用資料契約與七項擴充規則](https://github.com/TaiwanCCyoyo/stock-research/blob/8ae5182c2c4d862514b855dfda3c3a5a73971c8f/docs/en/research-derived-data.md)：單一正本／writer、世代切換、定義版本、欄位語義、資料形狀、研究專用內容邊界、同 PR 文件／索引／測試。
- [資產發現與放置](https://github.com/TaiwanCCyoyo/stock-research/blob/8ae5182c2c4d862514b855dfda3c3a5a73971c8f/docs/en/research-program.md)、[producer／worktree／交接責任](https://github.com/TaiwanCCyoyo/stock-research/blob/8ae5182c2c4d862514b855dfda3c3a5a73971c8f/docs/en/stock-agent-operations.md)、[完整性與驗證成本](https://github.com/TaiwanCCyoyo/stock-research/blob/8ae5182c2c4d862514b855dfda3c3a5a73971c8f/docs/en/artifact-integrity.md)另外分別管理。

請 review 這些文件能否共同涵蓋「盤點／分類 → 定義與等價 → canonical 發布 → 消費端切換 → 備份／失敗回復 → 確認舊引用後清退」。已有規則直接引用；缺口再補，不新增互相矛盾的另一套 SOP。

本輪文件整理不解除 PR30 的 merge hold。後續共用整併是資料與程式的工作，不等於授權 merge GitHub PR；producer 程式、正式資料寫入及舊資料清退仍各自遵守現有權限與 writer 協調。
