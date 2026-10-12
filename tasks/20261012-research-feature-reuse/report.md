# 特徵重用與有限單股執行

已完成共用特徵身分、不可變區塊查詢與部分重用、選擇性 SMA／EMA／ATR／BB／pivot 計算，以及有限 Windows 單股程序。固定小型合成實測中，選擇性直接計算約快 2.41 倍；兩個程序相對一個約快 1.20 倍，但完整驗證／發布協定的成本明顯高於直接計算，全重用也不是最快。因此保留可用 API 與成本證據，不自動改接或啟用所有研究的平行／區塊快取。這份基礎建設接續已完成並經 PR #9 合併的 HHHL 結果；沒有重跑市場研究、建立市場特徵快取或更動 producer／排程。

## 實測範圍

固定 16 個虛構股票、每股 1,849 個 weekday 日曆列；SMA20／ATR14／1.5 ATR pivots。比較直接完整／選擇性計算，以及相同 owned-process 協定的一個／兩個程序，每程序四股。再只為第一股增加 EMA20，驗證 48 個既有區塊重用、只補一個；最後全重用啟動零程序。數值／bytes 一致性是驗收，速度沒有及格門檻。

從通過正常 hooks 的程式提交 `0c2cae1dcf91b32a10efc20d507394d3dc79fad8` 單獨執行一次正式量測，完整數值／bytes 一致性全部通過。原始輸入共 1,435,584 bytes，要求的 48 個 feature payload 共 1,190,664 bytes；沒有真實行情。Git 保存 [完整 portable receipt](benchmark-v1.json.gz)，包含所有來源／實作 hash、runtime、逐階段 CPU／RAM／I/O 與輸出 hash。

| 執行方式                   | Wall 秒 | Parent CPU 秒 | 子程序計算／序列化 CPU 秒合計 | 計算／重用區塊 | 最多同時程序 |
| -------------------------- | ------: | ------------: | ----------------------------: | -------------- | -----------: |
| 直接完整特徵，只寫指定輸出 |   5.223 |         5.047 |                             — | 48／0          |            0 |
| 直接選擇性特徵             |   2.170 |         2.109 |                             — | 48／0          |            0 |
| 一個 owned process         |  21.736 |        11.906 |                         0.891 | 48／0          |            1 |
| 兩個 owned processes       |  18.162 |        11.766 |                         1.000 | 48／0          |            2 |
| 只增加第一股 EMA20         |  17.729 |        15.203 |                         0.047 | 1／48          |            1 |
| 全部重用                   |  16.228 |        15.734 |                             0 | 0／49          |            0 |

直接完整計算的 read／calculate／serialize 為 0.255／4.710／0.254 秒；選擇性為 0.077／1.785／0.302 秒。直接比較都寫相同三種輸出。程序協定另含完整 identity／輸入／來源／artifact 驗證與不可覆寫發布，與直接計算的語義工作不同，不能把差距全算成程序啟動；隔離的 startup 與 worker serialization 時間沒有記錄，不從重疊的 child wall 反推。這批小型廉價特徵宜先評估直接 selective API；更長／更昂貴的正式研究仍需自己的代表性量測。

Parent process lifetime peak 最高 116,256,768 bytes；child lifetime peak 最高 98,205,696 bytes（約 93.7 MiB），低於 512 MiB admission estimate。這些是 phase end 觀察到的程序累積峰值，不是獨立階段峰值。兩程序 parent 邏輯讀／寫 transfer 為 17,189,689／1,636,303 bytes，children 為 7,147,664／1,190,664 bytes。全重用仍有 14,680,358 bytes parent 邏輯 read transfer，以及 226,118 次 OtherOperationCount，顯示驗證成本；不等同實體磁碟吞吐。Parent 各 measured phase 啟用 tracemalloc，也會影響時間；兩程序的 worker CPU 包含計算／序列化、排除 import/startup。因此這是單次固定診斷，不是市場工作量的 throughput 預估。

事前機器觀察：20 logical processors、實體總記憶體 68,448,337,920 bytes，可用 41,870,671,872 bytes。選用兩個程序、512 MiB 各別估計、1 GiB admission budget，並非盡用 CPU；memory admission 與事後峰值核對不是 OS hard limit。Windows I/O counters 包含 cached transfer，不能解讀為實體磁碟吞吐。

事前小型完整特徵 baseline：16×1,849 合成列，wall 0.829 秒、CPU 0.750 秒、process lifetime peak 85,733,376 bytes。這是新的合成 microbenchmark，沒有替已完成的 HHHL 計算補做 CPU／RAM／I/O profiling。

## 已完成 HHHL 的可觀察邊界

既有 continuation log 的 Taipei 時間為：13:09:48.814 輸入 hash、13:19:17.078 daily 1900/1941、15:13:12.223 開發期選出五條件／16候選、15:57:42.314 cached candidate 1900/1941、16:00:55.324 抽樣 audit、16:02:03.917 後驗輸入 hash、16:12:08.570 完成發布 159,609 列。相鄰時間之間含多個操作與 barrier，不能當成單一函式耗時；歷史 CPU／RAM／I/O 未記錄，維持 unknown。

原 worktree 的 136 份診斷檔逐檔驗證後封存於 primary `tasks/20261012-hhhl-v4-variants/execution-logs/diagnostics-01/diagnostics.zip`（1,976,222 bytes），SHA-256 `69ce99e4ce414ef2cbcfcf1ef8bdf7be30bb67223c6454837bdd0fec208d0b31`；同目錄 manifest 保留逐檔 hash。ZIP 內 `hhhl-market-continue-01.txt` 的 SHA-256 為 `c99362a5e4c0b8ec946f1f7f6a94c7ffb73f67881542de4703846bb67a74f571`。`source-history.bundle` 已通過 Git bundle verify，保留 mission/results 分支原歷史與所需 main ancestors。無程序／排程依賴、無 reparse 及 initialized submodule、工作目錄 clean 後，已正常移除 own HHHL worktree 與兩個 local branch；remote branches 已不存在。市場資料與舊 staging 留在 primary。

第一份 synthetic receipt 因與回歸測試同時執行而排除時間比較，仍留 scratch 作診斷；在看速度數字前決定排除，未改參數。正式量測等測試結束後單獨執行相同固定規格，不按結果選最快一次。

## 使用與限制

資產入口為 [資料契約](data-contract.md)、`research_core.feature_block_store_v1`／`stock_feature_pool_v1` 和 `scripts.feature_blocks`。先比完整身分與 bytes，再重用；缺少／失效只增加新 generation，不能覆寫舊檔。缺少 pivot 時重算必要 ATR 中間值有明確理由；沒有「任何情況都不能重算」規則。

全域 rank／選擇仍在完整 barrier 後，由上層依批准 mission 處理，先合併整數 count 與 distinct stock set 再算率。本 API 拒絕把橫斷面特徵塞進單股程序。凍結 v4 G／X4 的缺價語義不同，沒有改接新 gap-reset API；原始結果與執行來源 bytes 保持不變。

250 個新增功能測試通過，另外 80 個 CLI／CI 範圍測試通過（其中四個 CLI 測試重疊，不能相加當 unique test 數）。覆蓋數值一致性、缺價重新暖機、確認日、部分重用、錯誤／毀損身分、外部 manifest pin、只增不覆寫、失敗／逾時 teardown 與直接／serial／parallel bytes 一致性；正常 hooks 全部通過。PR current-head CI 結果於交付時核對；程式可用與合成實測都不代表市場加速或策略驗證。

本次 task worktree 保留供 PR：`D:/Project/stock-research/.worktrees/research-feature-reuse`。正常建置 hook 建立了 initialized producer submodule 與約 4.98 GB 實體快照；本研究沒有讀取它們。未來清理須依既有 initialized-submodule／資料保存流程，不得 force removal。原 HHHL worktree 已合併、保存後正常移除。

Portable receipt: compressed 6984 bytes, expanded 28354 bytes; SHA-256 `e9f5dcfe0651928ded3075537b457d9e0122631dcbc023260732cf8460d006d2`.
