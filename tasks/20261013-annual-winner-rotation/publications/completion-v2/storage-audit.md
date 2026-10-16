# 更新研究時的放置與成本盤點

本次維持同一研究 task，把每次正式更新放進有名稱的 `publications/<version>/`。
根目錄 v1 mission／report／params 與 SHA 固定的舊證據不改寫；新版定義、結果、
receipt 和結論一起保存。報告首頁展示最新版，提供歷史版連結，避免用新數字覆蓋舊結論。

| 層                         | 放哪裡                                                                | 本次處理                                                                      |
| -------------------------- | --------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| 官方行情、公司事件資料庫   | `D:/StockData/stock-data-downloader/`                                 | 直接唯讀，不複製進 worktree                                                   |
| 這次補缺的官方原始證據     | producer 的 `corporate_action_supplements/annual-winner-20261013-v1/` | 正式發布一份，不再依賴舊 session 的 `.tmp`                                    |
| 可持續更新的共用衍生資料   | `D:/StockData/stock-research/derived/<family>-v<N>/`                  | 本次不新增價格／特徵快取；adjusted-daily 不包含這個經濟權益模型所需的完整資訊 |
| 共用演算法與來源 admission | `research_core/`                                                      | 新的版本化模組；CLI 在 `scripts/`，所有測試在既有 `scripts/tests/`            |
| 本研究小型結果、定義、結論 | 本目錄 `publications/completion-v2/`                                  | 適合 Git 保存，結果 SHA 與輸入 fingerprint 在 run receipt                     |
| 網頁                       | `../../web-report/index.html` 與 `v1.html`                            | 新版由已存結果產生，自含 CSS／JS／數字，不連行情 API 即時計算                 |

## 已量測的空間

僅以檔案清單與 size 盤點，未為此再 hash 大資料。

- 新 canonical 補證共 **185 檔，26,706,236 bytes**；包含原捕獲 182 檔、既有
  producer projector 的小型輸出、manifest 與 README。manifest 列 184 個成員，
  不把自己列成自身 digest。
- 舊 session 捕獲仍在 primary producer checkout 的
  `.tmp/annual-winner-supplement-20261013/`：**182 檔，26,656,453 bytes**。
  這是本次正式發布後仍保留的已知重複；原 session 產物未擅自刪除，後續可另行確認保留策略。
- capture 內另有 5 組相同 bytes 的檔案，屬來源回應／診斷的歷史保存；新流程沒有再展開成多份行情。
- v1 primary `research_data/prices/annual-rotation-inputs/de7a91ec…/`：
  **238,235,530 bytes**。這是政策更新前已固定的輸入，仍須保留，不能當成新研究範本。
- v1 兩份 process 合計 **7,016,862 bytes**；三份 delivery 合計
  **1,802,309 bytes**。它們有原始／審查／格式化的歷史用途，這次沒有重建或搬動。
- 本次 **行情／資料庫／衍生價格副本新增 0 bytes**。新結果的最終大小由執行輸出與 Git 檔案清單提供。

## 雜湊與流程

舊 runner 的 prepare／publish／register／delivery 有多段複製與重複驗證。它們是
已發表證據的相容程式，這次沒有為了整理而改寫。

新流程只 fingerprint 每份 live input 一次；整個價格檔的單次 SHA 是辨識輸入版本所需，
不是重建或複製價格。交易日曆只掃描一次，另限縮讀取固定股票的必要欄位。
補證各 member 在讀入時驗證一次，後續解析同一份記憶體 bytes。相同 benchmark 區間與
不含認股事件的第二情境直接重用。

結果先完成格式化再計 SHA；final receipt 只檢查 input size／mtime／SQLite WAL
有無變動，不重 hash 全部輸入。沒有載入模組原碼的逐檔複製／雜湊鏈。
`performance.json` 保留實際階段時間、可得記憶體觀測與未量測項目。

## 備份與交接

canonical batch 已由 producer 的本機 recursive mirror 備份。既有
`stock-data-downloader/logs/run_daily_20261016.log:4154` 記錄 2026-10-16
18:22:25.642（臺北）mirror 成功，18:22:25.661 作業結束；此批次實際位於
`D:/StockDataBackup/data/corporate_action_supplements/annual-winner-20261013-v1/`。
僅對此批次比對來源與備份的 metadata：兩邊均為 **185 檔、26,706,236 bytes**，
相對路徑、大小與 mtime 完全一致。備份檔建立於 18:20:21，晚於來源最後修改的
17:15:00，與日誌時間順序一致。

本次證據範圍是成功日誌及批次 metadata 對照，沒有再做內容 checksum 或還原演練，
也沒有啟動備份或遞迴掃描整個 producer。分類季度封存清單仍不包含這個 family，
目前沒有已觀測的季度或異地備份。原始資料備份仍由 producer 維護，這次沒有更改
scheduler 或偷偷複製整個 producer。

舊 v1 完整結果仍透過 primary 的固定 bundle／catalog 取得；新版小型閱讀結果則直接在 Git。
這個調整提升新版可攜性，並未補出完整全市場排名、退市資料或所有候選的公司事件。

## 本次實測

- 5 份輸入 fingerprint：2.94 秒；行情／actions 載入：1.49 秒；補證 admission：0.22 秒（member 驗證 0.19 秒）；計算：2.01 秒。
- 載入 17 檔、66,775 列；策略 18 次、benchmark 19 次、舊模型對照 8 次，共 45 次 kernel。無全市場重新排名，14 次無認股情境重用。
- 觀測到的 process lifetime peak working set 約 540 MB；不是各階段獨立峰值。Windows I/O counters 包含 cache，不能稱實體磁碟吞吐。
- 格式化約 1.67 秒；四份初始結果／receipt 共 103,288 bytes（後續 receipt 自身排版可能稍增）。

### Git 收據封裝

公開 SHA 清單觸發既有高熵字串檢查，因此使用既有的無損 ZIP 交付方式；未修改 scanner、baseline 或 formatter 例外。
`publication.zip` 保存原始四份 JSON，純讀呈現時在記憶體驗證，不解壓出另一份資料。
Git 另保留無大量雜湊的 results/performance 作閱讀與 diff；這個小型呈現副本有明確用途，不是行情或原始資料副本。

## Review 後的真實來源影響核對

2026-10-16 19:11（臺北）先確認 producer idle，再以穩定唯讀核對：64 個固定
股票／0050 端點要求，共 49 組不同股票日期，全部都有唯一觀測、有限且正值的
成交量。官方補證 manifest 與原 run 的 SHA-256 相同；184 個成員驗證一次。
43 個 source ID、11 個 event ID 均非空且唯一，6 個經濟事件的 issuer 皆有效。

價格檔已因日更換世代，SHA-256 與原 run 不同，不能把這次端點檢查說成讀到原始
輸入 bytes。因此 19:14 另以已提交、乾淨的 [c19a5c4 程式版本](https://github.com/TaiwanCCyoyo/stock-research/commit/c19a5c4060f5cd2134967d5bc4eafe28f9869ab9)
重跑相同參數、固定選股與 2026-10-12 截止日，做結果重現驗證：

- 16 列年度／YTD、3 個完整期間，以及整份 parsed `results.json` 物件與原
  publication **完全相同**，沒有改變的結果欄位；admission unresolved 仍為空。
- 只讀 17 檔的必要欄位，45 次 kernel，沒有全市場重新排名；本次驗證仍只有
  一次 input fingerprint，input copy bytes 為 0。
- Runner 已實際完成 no-replace ZIP；打包約 0.019 秒，沒有第二次 producer
  fingerprint。這是重現檢查，不是改寫或新增一版研究結論。

診斷輸出放在本 session 的 `.tmp/annual-review-reproduction-20261016/`，含本次
fingerprint、乾淨 code commit 與比較用結果；它是可丟棄的驗證輸出，不是新的共用
資料位置。正式原結果、效能與收據 ZIP bytes 均保留不動。重現入口為
`python -m scripts.complete_annual_rotation --output <fresh-directory-inside-repository>`；
須依 writer-idle 規則執行，並用原 publication 的已驗結果物件作完整比較。

隨後再以乾淨的 [67abbcf 程式版本](https://github.com/TaiwanCCyoyo/stock-research/commit/67abbcf8c0af7e27148f216da991033a8409e926)
驗證 carry 恢復跳幅與執行 identity 修正。整份結果物件仍完全相同，無 unresolved；
跨缺值後達到原 40% 品質門檻的大跳幅只有下列三組，均由明示股數條款解釋：

| 股票／恢復日     | 跨缺值原始收盤變動 | 明示條款                        | 去除機械變動後殘差 |
| ---------------- | -----------------: | ------------------------------- | -----------------: |
| 0050／2025-06-18 |            −74.78% | 精確 1:4 分割                   |             +0.86% |
| 5314／2025-03-31 |            −94.55% | 面額 10 → 0.5，每舊股換 20 新股 |             +9.06% |
| 6276／2012-07-27 |           +104.60% | 無退款減資，剩 0.4715310958 股  |             −3.52% |

其他已准許的 H/N carry 恢復日沒有達到 40% 原始跳幅；未用任意同日事件或價格
factor 推回股數。診斷來自同次實際 kernel 呼叫；結果在原則下可計，不代表完整每日
行情或實際最大回撤已知。本次診斷仍只有一次 input fingerprint，沒有全市場排名或
行情副本；完整診斷保留於本 session 的 `.tmp/annual-review-recovery-reproduction-20261016/`
及同名 log，作可丟棄驗證輸出。

一般認股事件的大跳幅也改用相同的明示條款與來源 factor 雙重品質關卡，
不以投資人選擇放棄或實現權利改變報價品質判定。以乾淨的
[dd48d08 程式版本](https://github.com/TaiwanCCyoyo/stock-research/commit/dd48d0842619b166a8cd62b65695c65b822f0afc)
再跑相同固定序列後，整份 parsed 結果仍與原 publication 完全相同，
admission unresolved 為空。仍為 45 次 kernel、一次 input fingerprint、
input copy bytes 0；no-replace ZIP 實際完成，打包約 0.020 秒。
診斷放在 `.tmp/annual-review-rights-reproduction-20261016/` 及同名 log，
用途仍是可丟棄的修正影響驗證，沒有增加正式研究版本或改寫原結果。

依 PR31 的實際影響原則，一般非認股權 share／cash 的跳價關卡也要求明示條款
能解釋跳幅，不能單靠來源 factor 放行矛盾條款。2026-10-16 22:08（臺北）只核查
原固定持有序列的 4 個非認股權事件：6538／1519 的相鄰交易日原始收盤變化為
−11.39%／−17.55%，沒有達到 40% override 門檻；6276／5314 的前交易日缺價，
走既有、此次未變的 carry 恢復關卡。沒有命中新修改的一般 override 分支，
因此未啟動策略重算，也未改寫正式結果。

核查只讀 115 列事件附近 OHLC，日曆只讀四個有限日期窗口的 Date 欄位
（218,792 個日期值），沒有全市場特徵或績效計算。一次價格 fingerprint 與
先前乾淨 dd48d08 重現紀錄相同；輸入穩定且 input copy bytes 為 0。
診斷位於 `.tmp/annual-pr31-impact-check.json`，總耗時約 5.97 秒，屬可丟棄核查。
版本發現另由 task root 小型 `publications.json` 明確選擇 v2，保留 v1 路徑；
catalog 不讀經濟結果，也不為列目錄重驗大資料。
