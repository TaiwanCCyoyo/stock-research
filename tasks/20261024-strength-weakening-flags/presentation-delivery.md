# D：報告與閱讀入口交付紀錄

## 2026-10-30 閱讀設計修訂

Owner 實際閱讀後指出：報告預設讀者記得整段討論，術語與表格過多，缺乏引導。本次以第一次接觸研究的讀者為對象，重整閱讀順序。

- Markdown 先解釋問題、強勢條件、起點100元對應200元目標、前20日觀察與後續期限，再說明主要發現及限制。原始核對段落及所有結果數值保留。
- 網頁先用時間線和白話例子建立背景，再提供兩組強勢條件、七種警訊、半年／一年的28種主要比較。切換時同步更新比例長條、差異、原研究判定與最終翻倍前曾出現警訊的比例。
- 首頁區分兩個問題所使用的觀察對象與時間範圍。兩組比例使用相同尺度；詳細定義、計數、完整表格與次要探索按需要展開。選取完整證據會打開折疊區並移動鍵盤焦點。
- 研究卡片改用白話問題與答案，原引文仍可在報告中逐字核對。數據 chunks、CSV、frozen kit、研究結果及收據未變。
- 新增正常前端測試入口中的離線互動回歸：切換全部28種主要比較並逐一核對保存值、兩組不同的最終達標母體、半年／一年切換、證據開啟與焦點、原1,728格的篩選、未知顯示與區間單位。卡片驗證無警告。

C #111 已於2026-10-29合併。本次直接更新仍開放的 D #113，正常同步最新 main；沒有另外建立工作目錄。以下較早日期的驗證與狀態保留為歷史紀錄。

本次離線互動驗證仍不是瀏覽器畫面驗收；既有工具預覽限制保留。新版桌面／手機排版及真實 iframe 互動仍須實際驗收，未因程式測試通過而標記完成。

本工作包只呈現 C 已完成的保存結果，沒有重跑研究、讀取新行情、下載、部署或變更排程。
正式結果由 [C PR #111](https://github.com/TaiwanCCyoyo/stock-research/pull/111)保存；
C 的 HEAD `3cf4411` 已通過 CI（673項 Python 測試，含本研究測試）與同 HEAD 的無 findings 審查。
這不代替 owner 合併。

## 三個閱讀入口

1. [研究報告](report.md)：白話結論、28主格、兩個較明確比較的區間與支持度、錯殺代價、次要方向及限制。
2. `web-report/index.html`：使用 frozen report-kit，讀取保存資料的24個 classic-script chunks；
   可查全部1,728格、兩種重抽樣的三種估計量區間、各狀態／冷卻支持數、年代／分半／drop-best與漲跌分層。
3. `study.json`：v2卡片，引用本次報告的連續原文與4個數字；由既有研究列表自動讀取，不修改舊 studio package。

[完整 CSV 附錄](appendix/index.md)保存全部13,824 summary切片列，沒有把未知變零或刪去不適用。
維護型家族沿用 `adjusted-daily-v1`；網頁有 dashboard `/#data` 連結並區分目前圖表與研究截止日。
結果小表放 Git，沒有另造 maintained family、行情副本或新的 catalog bundle。
資料與重建閱讀投影方式已補進 [data-contract](data-contract.md)及研究資產索引。

## 已完成驗證

- 重開機後、D報告前重新核對 C 的41個最終結果，changed results 為空；wall 0.110秒、CPU 0.063秒。來源檔及中間檔沒有新增雜湊。
- builder 已執行，只投影12張 summary、12張 intervals、12張 rise-strata終表；序列化 scalar／null逐值相同。各JS／CSV分檔均低於500 KiB。
- `read_study_card` 驗證通過、沒有警告；卡片未借用其他研究或歷史套餐的文字。
- 報告索引6項 Node測試通過；測試用的 Windows file symlink不允許，工具明列此限制，directory junction隔離測試仍有覆蓋。沒有更改系統安全設定。
- 離線 DOM smoke check 使用實際 kit、manifest、chunks 與 app：主要28列、全格1,728列、五個篩選、選取格的6列區間與7列切片、兩組專用T/F/U、ratio單位及不適用null顯示皆通過。
- kit與原專案版本相同；JS語法檢查通過。正常commit hooks與hosted CI／審查的最終結果另在PR交付回報。

### 尚未完成的畫面驗收

瀏覽器安全政策拒絕 `file:` 協定（該工具只允許HTTP／HTTPS），因此沒有完成本機頁面的實際畫面預覽。
沒有改用其他瀏覽器、間接執行或另開服務來迴避這項拒絕。
上述離線DOM檢查不模擬排版、字體、手機寬度或真實iframe，不能當成視覺驗收通過。
Owner可在自己的瀏覽器開啟 `web-report/index.html`，或在正常合併流程後以既有dashboard
`/#studies`、`/#report/20261024-strength-weakening-flags` 檢查；本工作包沒有部署到正式服務。

## 狀態與安全保留

原收據的來源起始狀態未觀測限制已在報告、網頁及卡片保留，沒有事後改成來源已驗證。
`study.json` 記 `research_complete`；scratch `c-20261027-main-b1926ad` 維持 `complete`。
C與D正式成果合併、符合研究交付條件後，才依 `scratch_runs` 登記正式保存位置、
僅釋放 `strength-weakening-flags` 的本run hold，再處理可清暫存；不觸碰 PR17的hold／程序、PR61前瞻紀錄／排程。

本session有四個worktrees（primary不計入）：

| 工作包                        | 狀態             | 保留原因                                                                                         |
| ----------------------------- | ---------------- | ------------------------------------------------------------------------------------------------ |
| `strength-flags-mission`      | PR91已合併、保留 | 本機HEAD與PR最終HEAD不同；mission仍有歷史引用，不能依該PR直接清理。                              |
| `strength-flags-code`         | PR93已合併、保留 | mission仍有歷史引用；primary有其他session的未提交內容，未更新／重置primary，也未進行跨任務清理。 |
| `strength-flags-execution`    | C PR111、保留    | 原結果及收據已推送，正式移交與owner合併仍待完成。                                                |
| `strength-flags-presentation` | D、保留          | 本工作包報告與閱讀入口的獨立checkout，待正常PR流程。                                             |

沒有建立新自動追蹤或排程，重開機後不會自動啟動C；後續只接續保存結果的交付。

## 2026-10-29 窄範圍審查修正

- `report.md` 的 CORE 兩項區間上界改為 -10.17、-1.92 pp，僅修正保存值的四捨五入文字。
- 共用資料入口在 iframe 中傳送固定 `rk:navigate`／`#data` 訊息；主頁只接受自己的 report frame 與這個固定路由，沿用既有 sandbox 權限。獨立頁保留一般 `/#data` 連結。沒有新增 top-navigation 或 popup 權限，也未改 frozen kit。
- 作者執行：report-library／主頁路由 12 項 Node 測試、既有報告服務與實際 viewer sandbox 等 17 項 Node 測試全部通過；`npm run build` 通過 TypeScript 與 Vite 建置。建置仍有 bundle 大小與既有 shell child-process deprecation 警告，沒有因此調整安全設定。
- 以上是程式與離線測試證據。實際桌面／手機的排版、字型、表格捲動、焦點、iframe 高度／主題與點擊導覽仍未驗收；既有 file 預覽安全拒絕維持，不以另一瀏覽器或服務迴避。未啟動預覽服務或部署。
- 本輪沒有重新產生資料 chunks、CSV 附錄、研究結果或收據，也沒有修改卡片引文、baseline、hold 或排程。C #111 必須先合併，D #113 才可合併；本輪不執行合併或正式 APPROVE。
