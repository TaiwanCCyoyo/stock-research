# CI Test Scope Audit — 2026-10-24

## 結論

檢查最近建立的 30 個 PR（#82 至 #52；#53 是 issue，不是 PR）。其中 29 個在精確 PR head 上有 GitHub Actions `PR validation` run，找到的最新 run 全部成功；#80 沒有 hosted CI run。

測試選取大致能覆蓋主要程式改動，但不是每個數量都相稱。#55 是明確的歷史過量案例，後續 #59 已改善同類 Vite 相依更新的選測規則。仍可看到純前端 PR 選入約 1,200–1,400 個 Python cases，以及文件／交接 PR 選入 2,200 個以上 Python cases。另有既有 task 的 `web-report/` 路徑未觸發文件承諾的前端檢查。

## 範圍與方法

- 以 GitHub `created_at` 由新到舊取 30 個 PR；查核日期為 2026-10-24。
- 對每個 PR head SHA 查 `PR validation` workflow、job steps 及 job logs。表格列同一 head 的最新成功 run；#81、#82 各有較早一輪被取消的 run。
- `Python` 是 pytest log 的通過數及略過數；`前端` 是 `npm test` 報告的測試數。`—` 代表該 job step 被跳過。變更檔數取 PR file list。
- CI logs 提供實際通過數；`Select test scope` step 也會輸出完整的 scope summary JSON，包括 `python_tests`、`domains`、`reasons`、`inventory_count`，可用來核對檔級選取證據。因此「偏多」是依 PR 變更路徑、當時的 CI 結果及 selector 設定判斷；對特定 pytest 檔案是否完全無關，仍需以該 run 的 scope summary 再核實。

## 最近 30 個 PR

| PR / hosted run                                                                                                                               | 變更檔 | Python（通過 / 略過） | 前端 `npm test` |
| --------------------------------------------------------------------------------------------------------------------------------------------- | -----: | --------------------: | --------------: |
| [#82](https://github.com/TaiwanCCyoyo/stock-research/pull/82) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40077516823) |      5 |             2,255 / 0 |               — |
| [#81](https://github.com/TaiwanCCyoyo/stock-research/pull/81) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40075952159) |     16 |             2,410 / 0 |               — |
| [#80](https://github.com/TaiwanCCyoyo/stock-research/pull/80)                                                                                 |     10 |         無 hosted run |   無 hosted run |
| [#79](https://github.com/TaiwanCCyoyo/stock-research/pull/79) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40071837470) |     21 |             1,347 / 0 |             453 |
| [#78](https://github.com/TaiwanCCyoyo/stock-research/pull/78) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40069732516) |      2 |             3,527 / 0 |             445 |
| [#77](https://github.com/TaiwanCCyoyo/stock-research/pull/77) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40069704817) |      9 |               130 / 0 |             452 |
| [#76](https://github.com/TaiwanCCyoyo/stock-research/pull/76) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40069312236) |      4 |                     — |             445 |
| [#75](https://github.com/TaiwanCCyoyo/stock-research/pull/75) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40067750484) |      1 |             8,096 / 2 |             445 |
| [#74](https://github.com/TaiwanCCyoyo/stock-research/pull/74) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40066321638) |     18 |             1,416 / 0 |             445 |
| [#73](https://github.com/TaiwanCCyoyo/stock-research/pull/73) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40063161447) |     90 |             8,096 / 2 |             437 |
| [#72](https://github.com/TaiwanCCyoyo/stock-research/pull/72) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40059379188) |     54 |             1,362 / 0 |             437 |
| [#71](https://github.com/TaiwanCCyoyo/stock-research/pull/71) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40057656457) |      7 |             2,180 / 0 |               — |
| [#70](https://github.com/TaiwanCCyoyo/stock-research/pull/70) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40057910855) |     17 |               130 / 0 |             437 |
| [#69](https://github.com/TaiwanCCyoyo/stock-research/pull/69) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40053496185) |      2 |               463 / 2 |               — |
| [#68](https://github.com/TaiwanCCyoyo/stock-research/pull/68) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40052620907) |     30 |               501 / 0 |             428 |
| [#67](https://github.com/TaiwanCCyoyo/stock-research/pull/67) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40049391084) |     12 |             4,615 / 2 |             416 |
| [#66](https://github.com/TaiwanCCyoyo/stock-research/pull/66) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40052626027) |     17 |             3,681 / 2 |               — |
| [#65](https://github.com/TaiwanCCyoyo/stock-research/pull/65) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40032581718) |      2 |             7,940 / 2 |             416 |
| [#64](https://github.com/TaiwanCCyoyo/stock-research/pull/64) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40045332635) |     10 |             2,533 / 0 |               — |
| [#63](https://github.com/TaiwanCCyoyo/stock-research/pull/63) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40020892837) |      1 |               410 / 2 |               — |
| [#62](https://github.com/TaiwanCCyoyo/stock-research/pull/62) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40011304838) |      5 |             7,927 / 2 |             416 |
| [#61](https://github.com/TaiwanCCyoyo/stock-research/pull/61) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/39740605383) |     40 |             7,914 / 2 |             416 |
| [#60](https://github.com/TaiwanCCyoyo/stock-research/pull/60) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40011876725) |      5 |             7,927 / 2 |             416 |
| [#59](https://github.com/TaiwanCCyoyo/stock-research/pull/59) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/39802450298) |      4 |               567 / 2 |               — |
| [#58](https://github.com/TaiwanCCyoyo/stock-research/pull/58) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/39662861044) |      3 |               294 / 0 |               — |
| [#57](https://github.com/TaiwanCCyoyo/stock-research/pull/57) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/40011369162) |      4 |             2,237 / 0 |               — |
| [#56](https://github.com/TaiwanCCyoyo/stock-research/pull/56) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/39665893038) |      9 |             3,485 / 2 |               — |
| [#55](https://github.com/TaiwanCCyoyo/stock-research/pull/55) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/39654369932) |      2 |             5,736 / 2 |             404 |
| [#54](https://github.com/TaiwanCCyoyo/stock-research/pull/54) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/39656570977) |      9 |             7,874 / 2 |             416 |
| [#52](https://github.com/TaiwanCCyoyo/stock-research/pull/52) · [CI](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/39651518997) |      1 |             1,212 / 0 |             404 |

## 判讀

### 明確的過量案例

- **#55：** 只更新 Vite 的 `package.json`／`package-lock.json`，卻跑了 5,736 個 Python cases 加 404 個前端測試。後續 [#59 的回溯](https://github.com/TaiwanCCyoyo/stock-research/pull/59) 把 Vite 相依更新從全套 Python 測試改為 5 個 Python 測試檔 加前端驗證；這項選測效率問題後來已改善。
- **跨語言的額外執行候選：** #75 只改 `uv.lock`，#65 只改 Python 版本與 producer gitlink；Python 全套與這些 runtime／相依變更相稱，但兩者同時執行 445／416 個前端測試。是否能略過前端仍需依跨語言 API 與建置契約驗證，不能僅因 Python 走 full fallback 就直接設定 `frontend=false`。

### 仍偏寬的選測候選

- **純前端 PR：** #52 只有一個 `ResearchHistoryPage.tsx` 變更，跑 1,212 個 Python cases；#72、#74、#79 只改前端頁面及視覺／播放邏輯，分別跑 1,362、1,416、1,347 個 Python cases。現行 [`opportunity` domain](https://github.com/TaiwanCCyoyo/stock-research/blob/2dd6ef4aa3c97f920962483db96543134181c185/scripts/ci_test_domains.json#L136-L193) 同時涵蓋 `full-history`、`research-history`、`strategies` UI 路徑與多組 Python API tests。對只改視覺、文案、導覽的 PR，這些 Python 測試很可能多於必要；若改動前端資料模型或請求行為，相關少量 API contract tests 仍有價值。
- **文件／交接 PR：** #57 只改 4 份文件，跑 2,237 個 Python cases、耗時 838 秒；#64 改 inventory 程式和測試並更新多份 handoff，跑 2,533 個 cases、耗時 379 秒。#78 只改 2 份 task record／handoff 檔，跑 3,527 個 Python cases及 445 個前端 tests。#78 的 `study.json` 被 studies API 讀取，較廣驗證有其理由；前三者值得從 scope summary 核對是否不必要地帶入 pattern-scan 測試閉包。

### 前端檢查漏選

- [#58 的 selector 規則](https://github.com/TaiwanCCyoyo/stock-research/pull/58) 說 `tasks/*/web-report/` 變更會加跑前端檢查，但 #57、#64 都改了 `tasks/20261013-pattern-scan/web-report/README.md`，Actions 中 Frontend validation 卻是 skipped。
- 目前 [`ci_scope.py`](https://github.com/TaiwanCCyoyo/stock-research/blob/2dd6ef4aa3c97f920962483db96543134181c185/scripts/ci_scope.py#L153-L171) 先按路徑取得 domain owner；`route_by_reference()` 只有在路徑沒有 owner 時才會判斷 `web-report/`。由於 [pattern_scan domain 覆蓋整個 task 目錄](https://github.com/TaiwanCCyoyo/stock-research/blob/2dd6ef4aa3c97f920962483db96543134181c185/scripts/ci_test_domains.json#L429-L453)，此路徑不會套用 frontend 判斷。這兩個 PR 改的是 README，功能風險較低；同一條邏輯也可能使既有 pattern-scan task 下的實際報告檔變更漏掉前端驗證。
- 建議在取得 domain owner 前，依 `/web-report/` 路徑獨立設定 frontend scope，並補一個「既有 pattern_scan domain 下的 web-report 檔」選測合約案例。

### 尚未取得 CI 的 PR

- **#80：** PR 仍以 `claude/dashboard-visual-v2` 為 base；目前 workflow 僅對 base 為 `main` 的 PR 觸發（[workflow 設定](https://github.com/TaiwanCCyoyo/stock-research/blob/2dd6ef4aa3c97f920962483db96543134181c185/.github/workflows/ci.yml#L4-L6)），且未監聽 `edited` 事件，因此 retarget 到 `main` 不保證會產生 check run。PR 說明提到的 457 個本地前端測試不等於 hosted CI；待 #79 合併並將 #80 retarget 至 `main` 後，仍需確認受支援事件或明確 dispatch 確實產生最新 HEAD 的 Actions 結果。

### 合理的全套驗證

- #73 新增 studies API／reader 並更新大量 task records（90 檔），跑 8,096 Python cases及 437 前端 tests，範圍合理。
- #60 修改 CI 執行方式並更新 Python test dependencies；#75 更新 `uv.lock`；#65 更新 Python runtime。這些變更跑全套 Python 測試有合理的相容性理由。
- #81／#82 變更 pattern-scan worker、timeout 與 process cleanup，分別跑 2,410／2,255 個 Python cases，沒有前端 diff，且前端 step 正確跳過。

本文件只整理既有 PR／CI 證據；沒有重跑研究或測試，也沒有改動測試範圍設定。
