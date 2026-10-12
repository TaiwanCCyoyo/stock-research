# 特徵重用與有限單股執行

已完成共用特徵身分、不可變區塊查詢與部分重用、選擇性 SMA／EMA／ATR／BB／pivot 計算，以及有限 Windows 單股程序。這份基礎建設接續已完成並經 PR #9 合併的 HHHL 結果；沒有重跑市場研究、建立市場特徵快取或更動 producer／排程。

## 實測範圍

固定 16 個虛構股票、每股 1,849 個 weekday 日曆列；SMA20／ATR14／1.5 ATR pivots。比較直接完整／選擇性計算，以及相同 owned-process 協定的一個／兩個程序，每程序四股。再只為第一股增加 EMA20，驗證 48 個既有區塊重用、只補一個；最後全重用應啟動零程序。數值／bytes 一致性是驗收，速度没有及格門檻。完整實測數字待程式通過正常 hooks 後，從提交版本執行一次寫入 portable receipt。

事前機器觀察：20 logical processors、實體總記憶體 68,448,337,920 bytes，可用 41,870,671,872 bytes。選用兩個程序、512 MiB 各別估計、1 GiB admission budget，並非盡用 CPU；memory admission 與事後峰值核對不是 OS hard limit。Windows I/O counters 包含 cached transfer，不能解讀為實體磁碟吞吐。

事前小型完整特徵 baseline：16×1,849 合成列，wall 0.829 秒、CPU 0.750 秒、process lifetime peak 85,733,376 bytes。這是新的合成 microbenchmark，沒有替已完成的 HHHL 計算補做 CPU／RAM／I/O profiling。

## 已完成 HHHL 的可觀察邊界

既有 continuation log 的 Taipei 時間為：13:09:48.814 輸入 hash、13:19:17.078 daily 1900/1941、15:13:12.223 開發期選出五條件／16候選、15:57:42.314 cached candidate 1900/1941、16:00:55.324 抽樣 audit、16:02:03.917 後驗輸入 hash、16:12:08.570 完成發布 159,609 列。相鄰時間之間含多個操作與 barrier，不能當成單一函式耗時；歷史 CPU／RAM／I/O 未記錄，維持 unknown。保存日誌的身分與取得路徑會隨本次保存核對記錄。

## 使用與限制

資產入口為 [資料契約](data-contract.md)、`research_core.feature_block_store_v1`／`stock_feature_pool_v1` 和 `scripts.feature_blocks`。先比完整身分與 bytes，再重用；缺少／失效只增加新 generation，不能覆寫舊檔。缺少 pivot 時重算必要 ATR 中間值有明確理由；沒有「任何情況都不能重算」規則。

全域 rank／選擇仍在完整 barrier 後，由上層依批准 mission 處理，先合併整數 count 與 distinct stock set 再算率。本 API 拒絕把橫斷面特徵塞進單股程序。凍結 v4 G／X4 的缺價語義不同，沒有改接新 gap-reset API；原始結果與執行來源 bytes 保持不變。

測試涵蓋數值一致性、缺價重新暖機、確認日、部分重用、錯誤／毀損身分、外部 manifest pin、只增不覆寫、失敗／逾時 teardown 與直接／serial／parallel bytes 一致性。正常 hooks 與 PR current-head CI 結果於交付時核對；程式可用與合成實測都不代表市場加速或策略驗證。
