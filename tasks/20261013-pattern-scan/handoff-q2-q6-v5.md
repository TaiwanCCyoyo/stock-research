# PR17 Q2–Q6 交接：2026-10-24

**狀態**：程式已合併（PR #17、#57），研究**未完成**，成果**部分交付**，worktree
`.worktrees/pr17-retention-review` **不可清理**。四種狀態的定義見
[研究計畫的交付狀態](../../docs/en/research-program.md#delivery-states)。

12 個型態家族中，只有 B1、H1 完成 Q2–Q6 全部三個階段（conditions、q4、followup），
各有終端收據。其餘 10 個家族未完成，續跑程序在 2026-10-22 晚上中斷，沒有正常結束。
Q1 已完成並在 [web-report](web-report/README.md) 呈現。

## 每個家族的狀態

conditions 階段每個家族有 18 個對照分組，加上每個型態（union 與各子型）各 2 個期限的分組；
B1、H1 各 24 組。「已完成分組」是暫存目錄中已發布、續跑時會直接沿用的分組。

| 家族 | conditions                  | q4     | followup | 結果所在（全部在 `.worktrees/pr17-retention-review/.tmp/`） |
| ---- | --------------------------- | ------ | -------- | ----------------------------------------------------------- |
| B1   | 完成，24 組                 | 完成   | 完成     | `pr17-q2-q6-local-20261020/B1/`                             |
| H1   | 完成，24 組                 | 完成   | 完成     | `pr17-q2-q6-local-20261020/H1/`                             |
| B2   | 部分：19 組已完成，1 組中斷 | 未開始 | 未開始   | `pr17-q2-q6-local-20261020/B2/.staging-conditions/`         |
| B3   | 未開始                      | 未開始 | 未開始   | 排在 `pr17-q2-q6-local-20261020`，B2 之後                   |
| B4   | 部分：6 組已完成，1 組中斷  | 未開始 | 未開始   | `pr17-parallel-20261022-p1-b4-l1/B4/.staging-conditions/`   |
| L1   | 未開始                      | 未開始 | 未開始   | 排在 `pr17-parallel-20261022-p1-b4-l1`，B4 之後             |
| P1   | 部分：6 組已完成，1 組中斷  | 未開始 | 未開始   | `pr17-parallel-20261022-p2-p1-l2/P1/.staging-conditions/`   |
| L2   | 未開始                      | 未開始 | 未開始   | 排在 `pr17-parallel-20261022-p2-p1-l2`，P1 之後             |
| R1   | 部分：9 組已完成，1 組中斷  | 未開始 | 未開始   | `pr17-parallel-20261022-p3-r1-r2/R1/.staging-conditions/`   |
| R2   | 未開始                      | 未開始 | 未開始   | 排在 `pr17-parallel-20261022-p3-r1-r2`，R1 之後             |
| R3   | 部分：9 組已完成，1 組中斷  | 未開始 | 未開始   | `pr17-parallel-20261022-p4-r3-l3/R3/.staging-conditions/`   |
| L3   | 未開始                      | 未開始 | 未開始   | 排在 `pr17-parallel-20261022-p4-r3-l3`，R3 之後             |

完整家族清單來自 `research_core.pattern_scan_local_remaining_v5.PATTERNS`，分配來自
[`q2-q6-v5-receipts.zip`](q2-q6-v5-receipts.zip) 內的 `parallel-plan-20261022.json`。

## 已交付到 Git 的部分

[`q2-q6-v5-receipts.zip`](q2-q6-v5-receipts.zip) 無損保存 B1、H1 六個階段的原始終端收據、selection、
top-candidates，以及中斷時的進度檔 `progress-20261020.json` 和平行計畫，zip 內路徑為
`<家族>/<階段>/<檔名>`。沿用 Q1 `q1-receipts.zip` 的收據交付方式，不增加 secret-scanner baseline。
下表是 zip 內檔案的 SHA-256，與 worktree 原檔相同：

| 檔案                             | SHA-256 前 12 碼 |
| -------------------------------- | ---------------- |
| `B1/conditions/run-receipt.json` | `64375ee768c7`   |
| `B1/q4/run-receipt.json`         | `4fa49dbc5274`   |
| `B1/followup/run-receipt.json`   | `653729d473e5`   |
| `H1/conditions/run-receipt.json` | `c7575c22cf12`   |
| `H1/q4/run-receipt.json`         | `ad9a728fdbec`   |
| `H1/followup/run-receipt.json`   | `825ca1eef139`   |

每份收據列出它的最終表檔名與 SHA-256、執行 commit、定義、參數與輸入指紋。
執行 commit 為 `40bf6fd`（B1 conditions 為 `4f5daaad`），兩者都包含在 PR #17 的最終
head `171f106` 裡，可從 `refs/pull/17/head` 取得。

**尚未交付**：B1、H1 的最終表本身（約 211 MB 的 parquet）還在 worktree 的 `.tmp/`。
大型研究成果的正式位置正由資料架構工作提案（`D:/StockData/stock-research/tasks/<task-id>/`），
owner 尚未決定；定案前不搬，避免先搬一次再搬一次。定案後搬一份到新位置、
依收據核對 SHA，再把 [web-report README](web-report/README.md) 與本文件的路徑改過去。

## 續跑依賴

續跑需要以下全部保留，任何一項不見都要重新計算：

1. **原始輸入**：`D:/Project/stock-research/.tmp/pattern-scan-execution/full-2010-20261016-retention-v3/`
   （約 6.1 GB，primary checkout 的 `.tmp/`，沒有其他保護）。收據的 `input_fingerprint`
   記錄其中 `phase-stock-result.json`、`derived-preparation.json`、`global/receipt.json`。
2. **共用資料 generation**：`adjusted-daily-v1` 的 `2026-10-15-20261015T161626Z`，由
   `pr17-pattern-scan` hold 保留。Q2–Q6 全部完成前不能 `release`。
3. **已完成分組**：各家族 `.staging-conditions/` 內已發布的分組，合計約 200 MB。
   每組要算 1–3 小時，續跑時同名分組直接沿用。
4. **worktree 本身**：`run_pattern_scan_remaining` 拒絕寫到「呼叫它的 checkout 的 `.tmp/`」
   以外，進度檔記的是這個 worktree 內的絕對路徑，所以續跑必須在同一個 worktree 執行，
   或另行把輸出位置改成可配置。

`_temporary/events/`（每個執行目錄約 1.7 GB，合計約 9.5 GB）是每個家族從第 1 項投影出的事件，
可以重算，每個家族約 45 分鐘。放棄續跑或全部完成後就不需要。
四個平行目錄的 `.active` 與 `.active.lock` 是 2026-10-22 中斷時留下的，記錄的 PID 已不存在。

## 續跑要多久

依收據與 log 量測：

- 單一程序約每小時完成 1.6 組 conditions 分組。H1 的 conditions 約 12 小時、q4 約 40 分鐘、followup 約 2 小時。
- 2026-10-22 的 4 路平行在 19 小時內合計完成 30 組，總吞吐量和單一程序差不多，沒有加速。
- 剩下約 180 組 conditions 分組，加上 10 個家族的 q4 與 followup，連續執行約 **5–6 天**。

## 下一步（需要 owner 決定）

1. 是否續跑剩下的 10 個家族；續跑會佔用機器約 5–6 天，且要避開下載排程。
2. 大型成果的正式位置定案後，搬 B1、H1 最終表並更新引用。
3. 研究完成後才 `release --holder pr17-pattern-scan`，再依
   [交付狀態](../../docs/en/research-program.md#delivery-states) 確認可安全清理 worktree 與 primary `.tmp` 的原始輸入。

## 這次為什麼會發生

程式合併時，報告頁把成果位置寫成「local-only，維持原處」，而執行程式本身又要求輸出必須在 worktree 的 `.tmp/`；
規則沒有區分「程式合併」與「成果交付」，清理時只能靠人工發現。這次的修正是定義四種狀態，並讓
`scripts/worktree_inventory.py` 列出 `main` 上仍引用某個 worktree 的追蹤文件，讓「可安全清理」可以檢查。
