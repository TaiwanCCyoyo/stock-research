# D：報告與閱讀入口交付紀錄

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
