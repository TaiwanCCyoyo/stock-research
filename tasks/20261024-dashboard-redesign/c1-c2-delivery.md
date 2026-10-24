# C1 + C2：逐頁換裝與文案交付

2026-10-24（Asia/Taipei）。以已合併 P1 的 `origin/main`（`aea54fe0`）為基礎，
交付時再整合 P4 與當前 `main`（`6f50b32e`），保留法人與月營收疊圖功能。

## 完成範圍

- 策略總覽、詳情、比較、交易與帳戶稽核抽屜。
- 個股 K 線與資料目錄、ETF 圖鑑與並列比較、網頁報告外框。
- 歷史飆股地圖、`#market-preview` 與保留的 `#market-legacy`：控制項、側欄、資料來源與表格。

沿用 P1 的 `u-card`、`u-btn`、`u-chip`、`u-notice`、`u-track` 與 `SourceInfo`。
盈虧使用 `--gain`／`--loss`；卡片、指標線與其餘介面色彩來自主題 token。
手機表格改為保留欄名的卡片列，資料目錄的內容切換維持直接可見。

未修改 `src/app/`、`visualizations/`、API、資料轉接層、Python、價格、回測或釘選報告。
`research-history/` 與 `ReportsPage` 維持原狀。

## 文案對照

| 原畫面                                    | 改寫後的一般畫面                         | 保留的位置                                 |
| ----------------------------------------- | ---------------------------------------- | ------------------------------------------ |
| 固定目錄、版本識別及歷史資料說明          | 資料期間；歷史統計，不是買賣訊號         | 完整識別與來源放入「資料來源」             |
| adjusted-daily-v1、世代、Status SHA-256   | 個股；資料截至日期                       | 家族、世代及 SHA 放入「資料來源」          |
| 現行世代、manifest 未提供、資料包版本識別 | 持續維護；未提供；檢視內容               | 原始識別、定義、限制與 manifest 保留於來源 |
| 策略原始名稱與研究代號                    | 白話策略名稱                             | 來源展開內容                               |
| 合成示範模式的長段技術說明                | 示範資料，不是真實結果                   | 詳細設定或來源資訊可展開                   |
| 找不到報告時顯示 task 路徑                | 找不到這份報告，請返回研究頁選擇其他報告 | 識別與預期路徑放入來源                     |
| 歷史資料驗證或讀取錯誤的技術訊息          | 資料暫時無法讀取，請重試                 | 原錯誤仍保留於收合詳情                     |

非投資建議、事後描述、研究已看過該期間、非實際報酬、資料缺漏與比較基準限制仍保留。
更換主題後，持股標示以「有外框」描述，避免把主題重點色稱為金色。

## 驗證

- `npm test`：整合 P4 後 437 通過，0 失敗。
- `npm run lint`：0 錯誤；保留既有 React hooks 警告。
- 設定 `RESEARCH_WEB_BUILD_OUT_DIR=../.tmp/build-check` 後的 `npm run build:stage` 通過；未發佈 `dist/`。
- 375px／1440px、日光／夜色：10 個頁面或狀態 × 霧林綠、櫻花粉、墨色極簡，共 120 個畫面。
- 其餘 5 個主題以個股與地圖預覽補查，共 40 個畫面。
- 檢查頁面寬度、瀏覽器錯誤及一般可見文字；來源展開內容不列入技術文字排除。
- 18 項互動檢查通過：交易／帳戶抽屜、個股價格基準與圖層、資料內容切換、ETF 最多三檔並列、報告缺失狀態、地圖日期與股票選取，以及手機頁尾連結避開底部分頁列。
- 歷史地圖等待既有 2,075 份檔案核對完成後，另驗收已載入的地圖與控制項。
- Hosted review 修正：手機交易表另設排序選單與方向按鈕，保留原有八種排序；地圖目錄的卡片樣式只套用於具備欄名的表格。375px／1440px 實測損益雙向排序，並確認研究者工具的事件表頭仍可見。

真實資料的截圖與機器檢查結果保留在本工作樹的 `.tmp/dashboard-restyle-qa/`；不提交公開。
其中 `after-final/` 是完整頁面矩陣，`after-extra/` 是其餘主題，`interactions/` 是互動結果。
`before/` 與 `before-map/` 保留 P1 的畫面比較。

## 公開截圖

以下圖片皆使用合成示範模式或已公開的 ETF 摘錄／釘選報告。
每張左側為 P1、右側為 C1+C2，均為霧林綠日光。
公開示範不提供個股行情與資料目錄；歷史地圖採資料不可用狀態；策略比較只有一個虛構策略。
這些限制避免把真實研究資料放進公開 PR；完整狀態另以本機真實資料驗證。

| 頁面         | 手機 375px                                 | 桌機 1440px                                 |
| ------------ | ------------------------------------------ | ------------------------------------------- |
| 策略總覽     | [前後比較](review/strategies-375.webp)     | [前後比較](review/strategies-1440.webp)     |
| 策略詳情     | [前後比較](review/strategy-375.webp)       | [前後比較](review/strategy-1440.webp)       |
| 策略比較     | [前後比較](review/compare-375.webp)        | [前後比較](review/compare-1440.webp)        |
| 個股         | [前後比較](review/data-375.webp)           | [前後比較](review/data-1440.webp)           |
| 資料目錄     | [前後比較](review/catalog-375.webp)        | [前後比較](review/catalog-1440.webp)        |
| ETF 圖鑑     | [前後比較](review/funds-375.webp)          | [前後比較](review/funds-1440.webp)          |
| 報告外框     | [前後比較](review/report-375.webp)         | [前後比較](review/report-1440.webp)         |
| 歷史飆股地圖 | [前後比較](review/market-375.webp)         | [前後比較](review/market-1440.webp)         |
| 地圖預覽     | [前後比較](review/market-preview-375.webp) | [前後比較](review/market-preview-1440.webp) |
| 舊版地圖     | [前後比較](review/market-legacy-375.webp)  | [前後比較](review/market-legacy-1440.webp)  |

## 工作樹歸屬

本 session 建立並擁有 `D:/Project/stock-research/.worktrees/dashboard-restyle`，分支
`codex/dashboard-restyle`。交付 PR 未合併前保留，供 owner 檢視與後續修正；合併仍由 owner 決定。
其他工作樹與主 checkout 的未追蹤研究紀錄未修改。
