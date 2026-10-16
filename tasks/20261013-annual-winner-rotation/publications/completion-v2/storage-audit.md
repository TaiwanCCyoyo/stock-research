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

## 尚未解決的交接

canonical batch 已放在 producer recursive mirror 的涵蓋範圍，但**本次沒有觀測到它已完成備份**；
producer 的分類季度封存清單尚不包含這個新 family。不能把「被備份程式涵蓋」寫成「已有備份」。
原始資料備份仍由 producer 維護，這次沒有更改 scheduler 或偷偷複製整個 producer。

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
