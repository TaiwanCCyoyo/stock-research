# PR17 保存的稽核證據

2026-10-22 移交後，唯一正式位置為 primary checkout 的：

`D:/Project/stock-research/tasks/20261013-pattern-scan/evidence/audits-20261021/`

其他 worktree 直接讀這個絕對位置。內容只留本機，不放進共用衍生家族、
`research_cache/` 或每個 worktree。以下路徑均相對於此目錄。
`.tmp/` 子層沿用原收據的相對 locator；此層只保存下表內容，移交後不再寫入。

| 內容                                        | 保存位置                                                                                                                                      | 原有證據與範圍                                                                                                            |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| 十事件結構、條件與全市場 scalar 核對        | `.tmp/pr17-event-formula-readiness-20261021.json`、`pr17-event-condition-prefix-check-20261021.json`、`pr17-event-global-check-20261021.json` | 原有十事件、520 條件格、110 global 格及 150 event-global 格；原紀錄 mismatch 為零。                                       |
| 原 bounded adoption 收據與 15-case 歷史檢查 | `.tmp/pr17-bounded-audit-receipt-20261021.json`、`pr17-audit-final-inspection-20261021.json`                                                  | 原四檔終結果收據保持原樣；15-case 檢查仍是當時的部分進度。                                                                |
| 五個固定 B1 候選的完整比較                  | `.tmp/pr17-candidate-audit-local-20261021/<case>/`                                                                                            | 40 個案例，各有 `summary.parquet`、`annual.parquet` 及原 `run-receipt.json`；共 80 張 ZSTD 終表、54,720 comparison rows。 |
| 完整 40-case 完成記錄                       | `.tmp/pr17-candidate-audit-local-20261021/completion/`                                                                                        | 原 `audit-summary.json` 與原收據；原完整檢查另在 `.tmp/pr17-audit-full-completion-check-20261021.json`，mismatch 為零。   |
| 已完成檢查的引用鏈與資源紀錄                | 同層 `pr17-audit-new-cases-*.json`、`pr17-audit-inspected-coverage-20261021-2018.json`、候選目錄的 `job-memory.json`、原 exit JSON            | 保存既有完成證據，不再執行分批稽核。                                                                                      |
| 既有 B1／H1 判讀及原 checker                | 同層 `pr17-b1-reading-20261021.md`、`pr17-h1-reading-20261021.md`、原檢查 JSON／Python 及 lower-high 範例                                     | 日期固定的筆記、草稿與原始 scratch source；其中的舊工作位置及當時待辦保留為歷史資訊。                                     |

這些證據支持既定十事件及固定五候選稽核。全研究 Q2–Q6、完整報告、
final handoff 與策略驗收仍依各自完成條件處理。

## 讀取與歷史 locator

本次使用既有 `artifact_store.relocate_noreplace`／`publish_noreplace` 在同一磁碟
搬移，沒有資料複本。原收據、終表與原 checker bytes 未改寫；搬移前後的
檔案身分、大小及 mtime 相同。保存共 **151 檔、3,923,504 bytes**，其中
80 張候選 Parquet 為 **2,643,526 bytes**。工作 checkpoint、快取、失敗探針、
未採用的 handoff 程式及預覽建置不屬於保存內容。

舊收據中的唯一路徑對照是：

| 原執行位置前綴                                             | 現在的讀取位置前綴                                                                     |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `D:/Project/stock-research/.worktrees/pr17-delivery/.tmp/` | `D:/Project/stock-research/tasks/20261013-pattern-scan/evidence/audits-20261021/.tmp/` |

原 `input_fingerprint`、executor、dirty／drift、SHA-256 及路徑描述繼續記錄當時
怎麼執行。現行索引與本頁提供取得檔案的位置；沒有以新 receipt 取代歷史收據。

bounded adoption 的四個 `results` locator 是 repo-relative，既有 reader 可直接用
保存根目錄讀取，搬移後 `changed_results` 回傳空清單：

```python
from pathlib import Path
from research_core.run_receipt import changed_results

root = Path("D:/Project/stock-research/tasks/20261013-pattern-scan/evidence/audits-20261021")
changed = changed_results(root / ".tmp/pr17-bounded-audit-receipt-20261021.json", repo_root=root)
```

40-case 及 completion 收據的 `results.path` 是原工作目錄的絕對 locator。
讀取已保存案例時，使用上述對照及該案例目錄的 `summary.parquet`／`annual.parquet`；
讀取完整摘要則用新位置的 `completion/audit-summary.json`。原收據中的 digest
仍描述同一份終結果。通用 `changed_results` 不會自動翻譯這些歷史絕對路徑。
已保存的 audit 目錄不支援再交給舊 audit CLI 續跑；不因搬移而重做案例或 adoption。

## 程式與保留責任

`evidence/pr17-audits-20261021` 輕量 Git tag 保留 PR17 squash 前的 head
`171f106166a49b3a2e450a180def2a25d25ed1e2` 及其祖先，讓原 audit executor
commits 持續可取得。這只保留 Git 引用，不建立程式或資料 snapshot。
原 case 收據仍是各案例實際 executor 的來源；tag head 不被冒稱為全部案例的 executor。
早期 scratch checks 沒有記錄的執行 commit 仍是未知，保存原始 source 不補造來源。

本地檔案由本研究維護，長期保留稽核終表、原收據、完成記錄與必要判讀。
原 Q1、正在運算的 Q2–Q6、原始 stock-result 及 generation hold 不在這次搬移範圍。
移除 delivery worktree 不釋放 hold，也不改其他五組程序的程式、輸入或輸出。
