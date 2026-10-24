# Codex handoff：逐頁換裝與全站文案（C1 + C2）

先讀 [mission.md](mission.md)。這份是它的 C1、C2 兩個階段。

## 開工條件

**P1（`claude/dashboard-redesign` 的 PR）合併進 `main` 後才開始。** P1 提供的實際名稱：

| 類別                              | 名稱                                                                                                                                                                                                      | 位置                                            |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| 顏色 token（8 主題 × 日光／夜色） | `--paper` `--surface` `--ink` `--muted` `--line` `--chip` `--accent` `--accent-soft` `--positive` `--negative` `--gain`（上漲紅）`--loss`（下跌綠）`--cell-light/mid/deep/warm` `--membrane`              | `research_web/src/app/themes.css`               |
| 形狀 token                        | `--radius-lg` `--radius-md` `--radius-pill` `--shadow-card` `--shadow-lift`                                                                                                                               | 同上                                            |
| CSS 元件                          | `u-page` `u-card` `u-btn` `u-btn-primary` `u-chip`（`aria-pressed`）`u-chips` `u-verdict` `u-bars` `u-list` `u-segmented` `u-notice` `u-source` `u-title` `u-eyebrow` `u-section-title` `u-big` `u-muted` | `research_web/src/app/ui.css`                   |
| React 元件                        | `VerdictBadge`、`CompareBars`、`SourceInfo`（收合的「資料來源」）                                                                                                                                         | `research_web/src/components/ui/primitives.tsx` |
| 已改好的示範                      | 首頁、研究頁（時間軸）、`SourceNotice`（已改成收合）                                                                                                                                                      | `features/home/`、`features/studies/`           |

`features/research-history/ResearchHistoryPage.tsx` 與 `features/report-library/ReportsPage.tsx`
已不再顯示（`#history`、`#reports` 導向 `#studies`），**不要換裝**；它們的移除留給研究資料改讀
`study.json` 的工作。

## 目標（只有一個）

讓 P1 以外的每個頁面改用 P1 的 token 與元件，並依文案規則清理文字，使整站在 8 個主題、
日光／夜色、手機與桌機下看起來是同一個網站。

## 範圍

| 可以改                                                                                                                           | 不可以改                                                                                      |
| -------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `research_web/src/features/{strategies,shared-data,funds,report-library,full-history,market,opportunities}/` 的 `.tsx` 與 `.css` | `research_web/src/visualizations/`（地圖繪製，P2 負責）                                       |
| 這些頁面用到的 `research_web/src/components/` 呈現元件                                                                           | 資料讀取與轉接層：`src/api/`、各 feature 的 `model.ts`、`api.ts`、`useHistory.ts` 這類        |
| 對應的前端測試（文字斷言跟著文案更新）                                                                                           | `research-history/`、`report-library/ReportsPage`、`home/`、`studies/`、`src/app/`（P1 負責） |
|                                                                                                                                  | `tasks/*/web-report/`、`report-kit/`、任何報告與釘選證據                                      |
|                                                                                                                                  | `research_api/`、`research_core/`、Python 端                                                  |

頁面清單：策略總覽、策略詳情（含交易、稽核抽屜）、策略比較、共用資料、ETF 圖鑑、
報告檢視外框、飆股地圖頁的控制項與側欄（地圖畫布本身除外）、`#market-preview`。

## C1 換裝要求

- 移除寫死的顏色，改用 token。上漲／下跌、買／賣這類有語意的顏色也要由 token 提供，
  且在 8 個主題下都清楚可辨。
- 卡片、按鈕、篩選標籤、結論標籤、長條改用 P1 元件，不另做一套。
- 每頁在 375px 寬時是單欄，沒有左右捲動。寬表格在手機上改成每列一張卡，或只留關鍵欄位。
- 字級與層次：頁面標題、區塊標題、內文、輔助說明各一級，關鍵數字比內文明顯大。

## C2 文案要求（驗收標準）

| 拿掉（或收進「ⓘ 資料來源」展開）                                              | 縮成一句白話，但**保留意思**                   |
| ----------------------------------------------------------------------------- | ---------------------------------------------- |
| 版本代號、SHA-256、研究代號（task ID）                                        | 非投資建議提醒，例：「歷史統計，不是買賣訊號」 |
| 「固定快照」「共用資料世代」「登錄需更新」「checkout」「manifest」「receipt」 | 合成示範模式：「示範資料，不是真實結果」       |
| 一大段來源與完整性說明                                                        | 研究限制，例：「事後描述，不是可交易報酬」     |
|                                                                               | 資料期間，例：「資料期間 2010/01 – 2026/10」   |

範例：「固定歷史目錄 · 2010-01-04 至 2026-10-02 · 版本 c7848ae7ad17。此範圍為已保存的歷史快照，
不代表最新共用資料世代。」→「資料期間 2010/01 – 2026/10」，其餘收進「ⓘ 資料來源」。

右欄的提醒是 `openspec/specs/research-output-safety` 要求的，**縮短不刪除**。
不確定某句屬於哪一欄時，放進「ⓘ 資料來源」，不要刪。資料讀取失敗的錯誤訊息保留，但改成白話。

## 驗證

```powershell
cd research_web
npm test
npm run lint
$env:RESEARCH_WEB_BUILD_OUT_DIR = "../.tmp/build-check"; npm run build:stage
```

`npm run build:stage` 一定要設定 `RESEARCH_WEB_BUILD_OUT_DIR`（寫到暫存資料夾）；不要跑會發佈
`dist/` 的 `npm run build`。

預覽（新 worktree 第一次要先裝 API 相依，否則 history-api 會缺 fastapi）：

```powershell
uv sync --group viewer
$env:UV_NO_SYNC = "1"; uv run python scripts/start_research_web.py --api-port 18517 --web-port 15177 --no-browser
```

飆股地圖與首頁市場區塊在 API 第一次啟動時要先核對約 2,000 個檔案，等幾分鐘才會出現。
對清單上每頁截圖：375px 與 1440px、日光與夜色，至少用霧林綠、櫻花粉、墨色極簡三個主題。
主題在右上角「主題」切換。確認沒有左右捲動、手機底部分頁列沒有蓋住頁面最下方的控制項，
並在頁面內搜尋「版本」「快照」「世代」「登錄」「SHA」「task」不出現在一般畫面（「資料來源」
展開內容除外）。

## 交付

- 從最新 `main` 開 `codex/dashboard-restyle` 分支，依 `docs/en/git-workflow.md` 開 PR，
  合併由 owner 決定。
- PR 說明附上每頁的前後截圖（375px、1440px 各一）與文案改寫對照。
- 同一失敗重試最多 3 次；遇到權限或沙箱錯誤立即停下，回報錯誤、步驟與路徑。
- 發現必須改上面「不可以改」的檔案才能完成時，停下回報，不要自行擴大範圍。
