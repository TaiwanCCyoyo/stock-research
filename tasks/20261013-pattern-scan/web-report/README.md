# 全市場型態掃描：可讀成果頁

此目錄呈現 PR17 已產生的結果，不會讀取即時行情或啟動研究計算。
初次交付是階段成果：Q2–Q6 與重建稽核的未完成範圍須依實際資料標示，
不能以報告頁存在、程式測試通過或某一題完成，宣稱整份研究已完成或策略通過。

本次僅交付 Q1：12 種型態、48 列交叉檢核主表，附上全部 24 張 Q1
摘要／年度 Parquet 終表。其他條件、年代、市場切片及 drop-best-year 列仍在
完整下載表中；主表的固定範圍不代表那些列被刪除。Q2–Q6 尚未完整交付。

## 從已存成果匯出

在 PR17 交付 checkout 執行已提交的 `scripts.export_pattern_scan_report`：

```powershell
uv run python -m scripts.export_pattern_scan_report --q1-root <原有Q1根目錄> --output tasks/20261013-pattern-scan/web-report/data --as-of 2026-10-21
```

輸出目錄必須尚不存在，也不得與原 Q1 根目錄重疊。匯出器只讀 12 份原收據及
其 24 張最終表，對最終表各驗證一次，從相同 bytes 讀出主表並提供下載；
不讀原價格、逐筆事件、舊 manifest 或共用資料，也不重算研究統計。
`publish_new_directory` 先寫 sibling staging，再以 no-replace 移交整個新目錄。

`data/q1-receipts.zip` 無損保留 12 份原始 `<型態>-receipt.json` bytes；不是新的
輸入快照或雜湊版本。這個小型傳輸包沿用專案既有的收據交付方式，不增加
secret-scanner baseline 或放寬檢查。原收據中的相對終表檔名，
對應本頁 `data/tables/<同名檔>`，不是收據目錄下另一份表。原數值來源 commit
與 Q1 投影 executor 分別呈現，歷史 dirty 狀態保留。顯示的 generation 是先前
價格等價移交的參考，不表示本次匯出重新讀了共用家族。

這些是供網站離線閱讀的精簡最終統計；不包含可重建快取、原始輸入或逐筆明細。
原 Q1 與執行目錄繼續保留，未進行清理，也未正式部署網站。

本地 HTTP 站已核對卡片、實際頁面、數值與 390px 版面。自動化瀏覽器禁止
`file://`，所以直接從磁碟開啟尚未完成瀏覽器實測；classic script 的載入與
資料呈現另有 Node 測試，並未繞過瀏覽器限制。

## 開啟方式

- 在研究網站開啟 `/#reports`，再選「2010 起全市場型態掃描」。
  索引由 `index.html` 的 `report:*` metadata 自動建立，不另填 catalog。
- 直接從磁碟開啟 `index.html`。`data/summary.js` 使用 classic script，
  不需要本機 API 或 `fetch`。資料檔未隨頁提供時，頁面會明示缺少資料。

## 資料契約

`data/summary.js` 由研究成果的匯出流程提供，設定 `window.REPORT_DATA`。
展示層只讀取既有摘要，不選候選、不計算研究統計，也不重新解讀原始價格。
資料來源、實際成果路徑、執行程式 commit、共用資料世代與限制由資料檔的
`provenance`、`study`、`limitations` 和 `audit` 欄位提供。

主要欄位如下：

- `schema`、`title`、`asOf`、`status`（`partial` 或 `complete`）。
- `study`：`period`、`stockN`、`horizons`、`generation`、`cutoff`。
- `overview`：`label`、`value`、`note`，由匯出流程提供可直接閱讀的文字。
- `questions`：Q1–Q6 各自的 `id`、`title`、`status`（`complete`、`partial`、
  `pending`）、`conclusion`、`notes`、`tables`。
- 每張表的 `columns` 指定 `key`、`label`、`kind`（`text`、`integer`、
  `number`、`percent`）；`rows` 是以欄位名稱為鍵的物件。
- `audit`：`status` 與 `notes`。本題完成與整份稽核完成分開呈現。
- `provenance`：`label`、`value` 與可選的本報告 `data/` 內連結。
- 表格與報告層可有 `downloads`，每筆為 `label`、`href`、`rows`、`bytes`。
  連結只接受本目錄下的 `data/` 相對路徑；匯出方負責確認檔案存在、列數與
  大小正確，並提供所有應交付的成果表。展示層不產生假下載檔。

百分比欄位的來源值是比例，例如 `0.125` 顯示為 `12.5%`，原始比例與換算值
保留在儲存格提示。`null`、缺值、非有限數字與不適用數值顯示為 `—`，
不轉成零。零則照實顯示。表格預設每頁 50 列，可切換頁次與每頁列數，
全部提供的列都能存取；沒有挑選「最佳」幾列或隱藏其他列。

## 更新與驗證

更新時先核對實際成果與收據，再匯出資料。報告不改寫原輸入、checkpoint、
既有成果或 hold，也不因共用資料更新而使歷史結果失效。
新階段尚未完成時，保留部分結果狀態與明確缺口；整份研究及既定稽核完成後，
才同步更新資料狀態、頁首說明與 `report:summary`、`report:date`。
網站索引用的 `report:status` 依研究性質維持 `exploratory`，不是執行進度。

交付驗證由主研究工作完成：確認研究卡片與連到的實際頁面、數值和成果來源
一致、下載檔存在，以及 390px 手機寬度下頁面不橫向溢出。寬表只在自己的
可捲動區域內水平捲動。直接開檔與網站 iframe 都應可讀；不自行正式部署。

`kit/report-kit.css` 與 `kit/report-kit.js` 是
`research_web/report-kit/v1/` 的原封副本；主題與 iframe 自動高度沿用原套件。
研究專屬版面在 `report.css`，資料呈現在 `report.js`。外觀修正不修改固定 kit。
