# Package D 完整成果交付（2026-10-31）

十二家族 Q1–Q6 計算完成。展示與文件為本次交付候選，正式 main 部署仍待 owner 合併；不是策略批准。

## 取得完整成果

- Catalog data ID：`pattern-scan-d-results-v1`
- 固定版本：`e54f8fea56898863a3b94ca40057f4fb66f41e0aa22cd3cfbc49ae67a89fe708`
- 完整位置：`D:/StockData/stock-research/catalog/tasks/20261013-pattern-scan/d-results-v1/e54f8fea56898863a3b94ca40057f4fb66f41e0aa22cd3cfbc49ae67a89fe708`
- `manifest.json`：外層完整性入口；`pattern-scan-d-finals.zip`：1,056 個終檔、48 份原收據與完成證據；`inventory.json`：各終檔原 SHA、列數、壓縮與 codec。
- ZIP 配置為 `Q1/<family>/...`、`Q2-Q6/<family>/<phase>/...`。原收據 absolute paths 僅為歷史來源，以 results dictionary key 相對該 ZIP 收據目錄定位。
- 網頁 8,268 列與 11 份 CSV 是完整展示切片；所有候選、年代、市場、年度及敏感度列在完整 ZIP，並未被刪除。

使用既有 reader 保留 SR-a 的 unknown、none 與數字語義：

```python
from io import BytesIO
from zipfile import ZipFile
from research_core.pattern_scan_parquet_v1 import read_frame

with ZipFile(archive_path) as archive:
    frame = read_frame(BytesIO(archive.read(member_name)))
```

## 完成與保存證據

Q2–Q6 36 terminal receipts／1,032 final files 通過既有終檔、universe、selection、input identity 驗證；加 Q1 的 24 終檔，共 1,056。ZIP 的 `provenance/` 保存 completion-verification 與 matching Job receipt。

最後 attempt `continuation-20261030T151115Z` 於 2026-10-31 10:09:56 Asia/Taipei 結束：exit=0、timed_out=false、wall=39,518.984 秒、Job peak=4,200,226,816 bytes（3.91 GiB／8 GiB）。沿用原 1,942 stocks，計算 code `3d978cf0e06a676af4a33eed88bcb3095b21db9c`；PR121 未套用。

發布只讀原終檔，逐檔對原收據驗證，ZIP reopen/CRC 與 catalog 登錄驗證通過。沒有重算研究、複製輸入或新增來源／中間資料 hashes。保存原位置與 adjusted-daily hold；不清理 scratch/worktree。這是本機耐久副本，沒有 offsite backup 證明。

## 展示與重現

- [完整報告](final-report.md)、[互動成果頁](../../index.html)。
- `web-report/data/final-v1/scripts-manifest.json` 固定分片順序；每片小於 500 KiB。舊 `data/summary.js` 保留歷史內容。
- `evidence/summarize_d_results_20261031.py --q1-root <原Q1目錄> --remaining-root <原Q2-Q6目錄> --output <新檔>` 只讀終表，產生結論計數與篩選依據；已保留輸出 `web-report/data/final-v1/interpretation-evidence.json`。
- `evidence/publish_d_results_20261031.py` 是本次 no-replace catalog 發布程式；不需為閱讀重新發布。
- 匯出器 `scripts.export_pattern_scan_report` 使用 `--split-scripts --display-csv --data-prefix data/final-v1`；輸出新目錄，不能覆蓋既有結果。

結論屬已暴露期間描述研究：確認半不代表獨立 holdout；沒有交易成本、組合資金與帳戶模擬。主報告列出每項分母、未知與比較限制。

## 展示驗證

2026-10-31：隔離 Edge 實際載入預覽 iframe，六題 complete，無 page error；Parquet 下載成功、逐題報告 HTTP 200；1440px 桌面與390px手機版已檢視，外頁無水平溢出。完整分片/11 CSV內容與分頁測試通過；原發布成果驗證基線通過。預覽註冊 ID `pr17-d-results`，閒置會正常關閉，可由開發預覽重新開啟。返回正式版維持既有流程，本次未重做正式版啟停驗收。

## 本機閱讀改版（待 owner review）

首屏改為研究問題與三個主要發現；十二型態代號表及各題完整表格改為預設收合。126／252交易日互動顯示既有1,104候選方向計數，不改研究或重選候選。未參與撰稿的獨立代理複核問題、答案與分母，並修正B1應包含有柄及無柄杯形的名稱。

隔離Edge實際檢查1440×1000及390×844：首屏無表格、兩期限數字與說明同步、dashboard iframe證據可展開，無頁面錯誤或手機水平溢出。11項展示/全8,268列/下載測試與格式驗證通過。這些檢查不代表owner已接受呈現；依owner指示保留未提交候選，不建立PR。

## 研究脈絡補充（2026-11-01，待 owner review）

報告前段新增三步研究承接，並同步final-report與study卡；永久來源記錄於research-lineage.md及研究索引。獨立代理核對保存答案、較早設計與較晚完整結果的時間差、各研究不同起點與分母。Edge實際驗證三段、強勢條件報告連結及390px寬度；11項既有資料/展示測試通過。轉弱訊號報告仍另在審閱，沒有把其未發布閱讀稿或臨時預覽連結當永久來源。依owner指示，本次仍只提供本機預覽，不發PR。
