# Research data architecture v1

資產 ID：`stock-derived-cache.v1`、`hhhl-pattern-sources.v1`、`stock-research-backup.v1`。
目的為跨 task／網站重用同一明確定義，不是證明飆股策略有效。

入口：[型態字典](../../docs/en/pattern-definitions.md)、[衍生資料](../../docs/en/research-derived-data.md)、[備份](../../docs/en/price-cache-backup.md#stock-research-data-backup)。producer 是 Stock 的新純計算／cache／backup 模組；消費者是顯式採用該版本的新研究。原 atlas/v1/v4 機率與舊帳戶 loader 不自動遷移。

來源保存：`research_core/patterns/hhhl/v1..v4/sources.zip` 各 internal `.py` 原 bytes；v1/v4 ZIP 本身亦與其既有 task 相同，v2/v3 從原 bytes 新包裝，不聲稱原來已有同 ZIP。四版 hashes 与來源位置在唯一 sources.json。

cache `daily.parquet` 主鍵 Code/Date，OHLC 為明示 basis 的研究價格；RawOHLC 保留來源；VolumeLots 為張，Turnover 為新臺幣千元尺度；Quality 布林，quality_reason 空表示該觀察沒有這版發現的缺陷，不代表歷史 universe/PIT 完整。ATR14 為價格，atr14_pct 為比例；SMA/EMA/BB20 為同 basis 價格。pivot 主鍵 Code/k/kind/confirmation_index；extreme_index 與 confirmation_index 是原完整日曆位置，confirmed_at 是可知日，extreme_date 不是可知日。

快取 manifest 包含 all input hashes、保留輸入、公式 bytes、parameters/runtime、每股每basis rows/valid/missing/pivots 與逐檔 hashes。缺值不補零，股價參考因子不等於帳戶含息報酬。依 source cutoff 還原不認證來源當時已發布或無倖存者偏誤；原 atlas 目前參考母體限制繼承。

取得：Git 可取得原規則、程式、契約及後續保存的完成收據；canonical Parquet／cache objects／backup objects 是本機 ignored bytes，必須按具體完成收據路徑取得或從對應 backup 還原。不能只看到 manifest 就宣稱資料已在新 clone 可用。新的 cache reader 只消費顯式絕對版本，不讀 mutable latest。

owner 標註 task 尚未由本次工作匯出；25原例只是舊 source cases，不取代全部正反例、盲測 kind 對應或線上最新標註。這項依賴必須由 Claude 交付證據才可關閉。

具體版本、原 bytes 完成收據、快取／備份／還原路徑與兩個不相容案例見[交付報告](report.md)。publication-v1/bundle.zip 帶全部 metadata／原執行程式，不帶大型 Parquet；收到新標註後要另增 backup snapshot，不改此原收據。

[publication-v1/review2.zip](publication-v1/review2.zip) 另存第二輪修正後的 bounded 備份還原證據、原快取 manifest、當時 reader／backup 程式及演練程式。只含 25 檔快取範圍的 158 檔 backup inventory，不代替原全 4,103 檔備份或宣稱新公式重建；兩份封包都保留。

[publication-v2/bundle.zip](publication-v2/bundle.zip) 是價格品質規則 `price-basis.v2` 的獨立追加版本：同一原凍結 25 檔輸入、75 組目前完整實作重算、quality-only 差異、158 檔備份／實際還原收據與原實作 bytes。原輸入解析/hash/code 集合審核通過；本例品質差異 0 列不代表新規則對所有事件等價。舊 v1 的 detector／機率結果不自動成為 v2 結果。新版本 canonical／備份路徑在交付報告；容器 schema 仍為 stock-derived-cache.v1。

[publication-v2/review8.zip](publication-v2/review8.zip) 保存 098f2d4 封存備份程式的 bounded 實際演練：同一原 v2 快取，158 檔全重用／新目錄還原，原子完成紀錄連結 started attempt 與 verified snapshot。帶 exact execution／reader／backup bytes 與所有 metadata，不帶大型 objects，不宣稱市場快取重建或原 v2 公式被新版重新驗算；既有三份封包不動。
