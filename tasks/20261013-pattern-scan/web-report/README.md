# 全市場型態掃描：可讀成果頁

此目錄呈現 PR17 已產生的結果，不會讀取即時行情或啟動研究計算。
目前是階段成果：Q2–Q6 的未完成範圍須依實際資料標示，
不能以報告頁存在、程式測試通過或某一題完成，宣稱整份研究已完成或策略通過。

目前交付 Q1：12 種型態、48 列交叉檢核主表，附上全部 24 張 Q1
摘要／年度 Parquet 終表。其他條件、年代、市場切片及 drop-best-year 列仍在
完整下載表中；主表的固定範圍不代表那些列被刪除。另呈現 B1／H1 既有
Q2–Q6 切片，其他家族仍由原程序接續，整份研究尚未完整交付。

首頁另外採 Q1 全體（split=all、era=all、mkt=all、full、union、unconditional、known）
的統一口徑，不混用 cross-check 候選數字。每家族顯示相對 C-base-daily 倍數、
相對同條件 C-base-all 的百分點差距及各自 K、loss rate。候選的主要比較是
同條件 C-base-no-pattern；C-base-all 包含型態，兩種對照不互稱。

`research_core.pattern_scan_report_v1.add_stored_comparisons` 只讀既有終表並整理顯示，
不新增稽核、收據、雜湊、抽樣或完整表副本。現有 phase 的原終端收據作為完成標記；
不把未完成 checkpoint 的數字填進報告。Q4 各原型態／候選只配自己的
`:C-base-random`；C-52w／daily 診斷留於展開附錄，不冒稱有獨立同配額 random。

原始終表位置（local-only，維持原處）：

- `D:/Project/stock-research/.worktrees/pr17-retention-review/.tmp/pr17-q1-local-20261016/<family>/`
- `D:/Project/stock-research/.worktrees/pr17-retention-review/.tmp/pr17-q2-q6-local-20261020/<family>/conditions/`
- 同家族 `q4/coverage.parquet` 及 `followup/*.parquet`。

Q2–Q3 保留原固定 top-10 的四組／兩期限與上下界；Q4 的完整主切片也留在展開區。
Q5–Q6 網頁附錄限原型態 union，landmark 限第 10 日；其他候選、landmark、年代、
市場與敏感度列仍在上述完整終表，沒有刪除。這些 local-only 表尚未正式引用移交。
十事件與固定五候選 40-case audit 已完成，只引用既有證據，不再加驗證流程。
其唯一正式位置、原收據與讀取方式見 [保存的稽核證據](../audit-evidence.md)；
資料已從 delivery worktree 單份搬到 primary task 的 `evidence/audits-20261021/`。

## 從已存成果匯出

在 PR17 交付 checkout 執行已提交的 `scripts.export_pattern_scan_report`：

```powershell
uv run python -m scripts.export_pattern_scan_report --q1-root <原有Q1根目錄> --remaining-root <原有Q2–Q6根目錄> --output <尚不存在的report-data目錄> --as-of 2026-10-21
```

輸出目錄必須尚不存在，也不得與原 Q1 根目錄重疊。匯出器只讀 12 份原收據及
其 24 張最終表，對最終表各驗證一次，從相同 bytes 讀出主表並提供下載；
不讀原價格、逐筆事件、舊 manifest 或共用資料，也不重算研究統計。
正式 CLI 在序列化前接入 `add_stored_comparisons`，因此首頁比較與已完成的 Q2–Q6
不會退回 Q1-only。各題狀態與 overview 由同一次已讀終表的家族產生；缺少既有 phase
完成收據就列待完成，不推定程序正在跑。全家族終表齊備只代表數值階段，完整交付、
owner 驗收、final handoff 與 hold 釋放仍分開確認。
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
  `number`、`percent`、`percentage_points`、`multiple`）；`rows` 是以欄位名稱為鍵的物件。
- `comparisonSummary`：首頁固定口徑、兩期限 rows 與基準率；`delta_pp` 已乘 100，不能再乘一次。
- 表格 `collapsible=true` 時置於原生展開區，全部提供的列仍可分頁讀取。
- `audit`：`status` 與 `notes`。本題完成與整份稽核完成分開呈現。
  通用匯出未提供稽核紀錄時為 `unrecorded`；不能由終表存在推定完成，
  也不能把它解讀成要重做既有稽核。本次頁面保留已提供的既定範圍完成證據。
- `provenance`：`label`、`value` 與可選的本報告 `data/` 內連結。
- 表格與報告層可有 `downloads`，每筆為 `label`、`href`、`rows`、`bytes`。
  連結只接受本目錄下的 `data/` 相對路徑；匯出方負責確認檔案存在、列數與
  大小正確，並提供所有應交付的成果表。展示層不產生假下載檔。

百分比欄位的來源值是比例，例如 `0.125` 顯示為 `12.5%`，原始比例與換算值
保留在儲存格提示。`null`、缺值、非有限數字與不適用數值顯示為 `—`，
不轉成零。零則照實顯示。表格預設每頁 50 列，可切換頁次與每頁列數，
全部提供的列都能存取；沒有挑選「最佳」幾列或隱藏其他列。

## 更新與驗證

更新時沿用已完成成果與原收據，不新增分批稽核。報告不改寫原輸入、checkpoint、
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

## iframe 實際下載人工驗收（已完成）

Claude 於 **2026-10-22** 使用 Claude 桌面 app 內建瀏覽器（Chromium）開啟
<http://127.0.0.1:8503/#report/20261013-pattern-scan>，從報告 iframe 點擊下載。
以下為 owner 提供的 Claude 實際下載驗收紀錄，完成時間為台北時間：

| 檔案                 | 下載完成時間 | 精確大小      | 儲存位置               | SHA-256 核對         |
| -------------------- | ------------ | ------------- | ---------------------- | -------------------- |
| `B1-summary.parquet` | 02:05:55     | 241,139 bytes | 使用者的「下載」資料夾 | 與 repo 對應檔案相同 |
| `q1-receipts.zip`    | 02:07:56     | 14,361 bytes  | 使用者的「下載」資料夾 | 與 repo 對應檔案相同 |

ZIP 首次點擊的暫存檔消失、未留下檔案，第二次才正常完成。差異推測與連結缺少
`download` 屬性有關，尚未證實因果；本次已替「原始 Q1 收據」ZIP 連結補上該屬性，
與其他 Parquet 下載連結一致。

上述紀錄確認實際檔案已下載完成；DOM、按鈕點擊、SSR、連結存在或 HTTP 回應
本身不能代替這項證據。本次程式修正未改 iframe 安全設定、部署或重啟下載排程。
