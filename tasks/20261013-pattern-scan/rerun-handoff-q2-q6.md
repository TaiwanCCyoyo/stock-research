# PR17 Q2–Q6 重跑交接（給 Codex）

Owner 2026-10-24 新指示：單程序已停止；後續必須採用有界平行化，最多十個計算 worker，
留兩個實體核心的餘裕。下方單程序／四路限制保留為先前量測紀錄；目前執行與量測規格以
[平行化補充](parallel-execution-v5.md)為準。完整續跑在新程式與量測通過前保持暫停。

2026-10-24 補充：程式修改改由 Codex 處理；以
[工作包 D](../20261024-data-homes-and-scratch/codex-handoff.md#d-pr17-續跑程式修改與重跑)
為最新規格，計算定義維持 v5，不另立定義。程式行為、資料盤點與尚未開跑的前置條件見
[scratch continuation](scratch-continuation-v5.md)。下文保留原始交接。

> **狀態：未完成。** PR17 的程式已合併，但研究沒有跑完。12 個家族只有 B1、H1 完成 Q2–Q6；
> 其餘 10 個家族的 Q2–Q6 還要算，預計連續約 6 天。不要把任何 PR、報告頁或 Q1 結果當成整份研究已完成。
> 四種狀態的定義見 [交付狀態](../../docs/en/research-program.md#delivery-states)：目前是「程式合併」，
> 尚未「研究完成」，成果只「部分交付」，worktree 與暫存都還「不可清理」。

Owner 決定（2026-10-24）：Q2–Q6 要跑完，由 Codex 執行，但要等下面的前置 PR 合併後才開始；
執行輸出寫到新暫存區 `D:/StockData/stock-research/scratch/20261013-pattern-scan/<run>/`，
成果交付到 `D:/StockData/stock-research/tasks/20261013-pattern-scan/`。逐家族現況見 [Q2–Q6 交接](handoff-q2-q6-v5.md)。

## 1. 還要算什麼

conditions 每個家族有 9 個對照組 × 2 個期限，加上 union 與各子型 × 2 個期限。已完成分組在續跑時會直接沿用。

| 家族 | conditions 分組  | 已完成 | 剩下  | q4   | followup |
| ---- | ---------------- | ------ | ----- | ---- | -------- |
| B1   | 24               | 24     | 0     | 完成 | 完成     |
| H1   | 24               | 24     | 0     | 完成 | 完成     |
| B2   | 24               | 19     | 5     | 要算 | 要算     |
| B4   | 20               | 6      | 14    | 要算 | 要算     |
| P1   | 20               | 6      | 14    | 要算 | 要算     |
| R1   | 24               | 9      | 15    | 要算 | 要算     |
| R3   | 24               | 9      | 15    | 要算 | 要算     |
| B3   | 約 26（B3a/b/c） | 0      | 約 26 | 要算 | 要算     |
| R2   | 約 30（R2a–e）   | 0      | 約 30 | 要算 | 要算     |
| L1   | 約 20            | 0      | 約 20 | 要算 | 要算     |
| L2   | 約 20            | 0      | 約 20 | 要算 | 要算     |
| L3   | 約 20            | 0      | 約 20 | 要算 | 要算     |

已開始家族的分組數來自各自的 `conditions-progress/<家族>.json`；未開始家族的分組數依子型數估計，
實際以第一次執行時偵測器登記的分組為準。合計約 180 組 conditions，加上 10 個家族的 q4 與 followup。

**時間**：單一程序約每小時 1.6 組，H1 的 q4 約 40 分鐘、followup 約 2 小時，每個家族開始前投影事件約 45 分鐘。
2026-10-22 試過 4 路平行，總吞吐量和單一程序差不多，所以**用單一程序依序跑**。合計約 6 天，
期間要避開平日 18:00–18:45 的下載排程（runner 啟動時會檢查）。

## 2. 必須保住的東西（不准刪、不准覆寫）

| 項目            | 目前位置                                                                                 | 大小      | 用途                                                                        |
| --------------- | ---------------------------------------------------------------------------------------- | --------- | --------------------------------------------------------------------------- |
| 原始輸入        | `D:/Project/stock-research/.tmp/pattern-scan-execution/full-2010-20261016-retention-v3/` | 6.1 GB    | 所有家族的續跑輸入（`--stock-result` 指向其中的 `phase-stock-result.json`） |
| B1、H1 最終表   | `.worktrees/pr17-retention-review/.tmp/pr17-q2-q6-local-20261020/{B1,H1}/`               | 約 203 MB | 已完成成果；收據在 Git 的 `q2-q6-v5-receipts.zip`                           |
| 已完成分組      | 同 worktree 各家族 `.staging-conditions/`（B2、B4、P1、R1、R3）                          | 約 200 MB | 每組 1–3 小時，續跑直接沿用                                                 |
| Q1 最終表       | 同 worktree `.tmp/pr17-q1-local-20261016/`                                               | 8.7 MB    | web-report 的 Q1 來源                                                       |
| generation hold | `adjusted-daily-v1` 的 `2026-10-15-20261015T161626Z`，holder `pr17-pattern-scan`         | —         | 原始價格來源；Q2–Q6 全部完成前不能 `release`                                |

可以重建、不必搬的：各執行目錄的 `_temporary/`（合計約 9.5 GB，每家族事件投影約 45 分鐘）、
`.active`／`.active.lock`（2026-10-22 中斷留下，PID 已不存在）、`.staging-<group>-<uuid>`（中斷的半組）。
這些在新位置的續跑跑完、成果交付後才請 owner 同意刪除。

## 3. 前置 PR（合併後才能開始重跑）

1. **資料架構 session 的 PR**：決策紀錄 `2026-10-24-data-homes-and-scratch`，以及建立
   `scratch/<task-id>/<run-id>/run.json` 的共用 helper。
2. **runner 修改 PR（Claude 負責，等第 1 項合併後開）**：`research_core/pattern_scan_local_remaining_v5.py`
   與 `scripts/run_pattern_scan_remaining.py` 目前有三個限制，會擋住在新位置續跑：
    - 輸出只能在「呼叫它的 checkout 的 `.tmp/`」（`run_remaining`、`launch_remaining` 的檢查）。
      改成也接受 scratch helper 建立的 run 目錄。
    - `progress.json` 的身分比對包含 `stock_result` 的路徑字串，輸入一搬就對不上。
      改成只比對 `source_id`、`input_id`，這兩個是輸入內容的身分。
    - 收據裡的最終表路徑是 worktree 內的絕對路徑，`_published_files` 要求它在目前 phase 目錄下。
      改成以收據 `results` 的相對路徑鍵（例如 `pattern%3Aunion-h126/B1-pattern%3Aunion-h126-summary.parquet`，保留分組子目錄）
      接到目前 phase 根目錄，檢查結果仍在 phase 根目錄內，再用收據的 SHA-256 驗證；不能只取檔名。
    - 未完成階段的原始執行紀錄 `<家族>/.phase-start-<階段>.json`（`pattern-scan-local-phase-start.v5`，記錄原執行 commit `40bf6fd`）。
      `_phase_start` 遇到已有內容的 working 目錄卻沒有這份紀錄會拒絕續跑，遇到 definition 不同也會拒絕；
      新版本要接受搬來的 v5 紀錄，保留原 `code`，把新執行 commit 追加到 `execution_codes`。
    - `launch_remaining` 在 12 個家族全部算完時會自動執行 `maintain_adjusted_daily release --holder pr17-pattern-scan`，
      早於成果交付。改成預設不釋放，由交付完成後明確執行（或加明確的選用參數）。
    - 新版本另立定義名稱，舊收據不改寫，維持可讀。

## 4. 重跑步驟（Codex）

1. 確認前置 PR 都已合併、primary `main` 已更新，執行 `git worktree list` 與 `scripts/worktree_inventory.py`，不要另開一份 PR17 worktree。
2. 用 scratch helper 建立 run（例如 `q2-q6-v6-<日期>`），`run.json` 從 `running` 開始，執行中定期 heartbeat；6.1 GB 原始輸入用 `create_run(..., depends_on=[...])` 登記成依賴。
   run 只有 `running`／`complete`／`delivered`／`abandoned` 四種狀態；「程式合併」是 task 層級的狀態，不是 run 狀態。
3. **原始輸入留在原處直接讀，不複製**：它的 `phase-stock-result.json` 把每檔股票的 part 記成 primary `.tmp/` 下的絕對路徑，
   搬走後 runner 仍會讀舊路徑；run.json 要把它列為依賴。**複製**（不是搬移）B1/H1 最終表與五個家族已完成的分組到 run 目錄，逐檔比對 SHA-256，
   不要複製舊的頂層 `progress.json`（裡面是舊 worktree 的絕對收據路徑），讓 runner 依已存在的 final 目錄重建。
   每個家族要連同家族目錄下的 `.phase-start-*.json` 一起複製（B2、B4、P1、R1、R3 的 `.phase-start-conditions.json`，
   B1、H1 的三份），只複製 `.staging-conditions/` 會讓續跑被拒絕；
   原位置的檔案一律保留，不要跳過驗證就刪。`_temporary/` 不要複製，讓 runner 重建。
4. 以單一程序依 `DEFAULT_TARGET_ORDER` 續跑剩下的 10 個家族。中斷後用同一個 run 目錄重跑即可，已完成分組會沿用。
5. 全部 12 個家族都有三個階段的終端收據後，才算「研究完成」：
    - 把最終表複製到 `D:/StockData/stock-research/tasks/20261013-pattern-scan/q2-q6/`，依收據驗證 SHA-256。
    - 收據、selection 與進度檔仿照 `q2-q6-v5-receipts.zip` 進 Git。
    - 更新 `web-report/`（重新匯出）、`handoff-q2-q6-v5.md`、`handoff-status.md`、`presentation.json`（資料架構改版後為 `study.json`）與研究定位表，
      把所有 worktree 路徑改成新位置。
6. 以上都進 `main` 後才 `release --holder pr17-pattern-scan`，並把 `run.json` 標為 `delivered`（對應 task 層級的「成果交付」），`results` 填交付位置。
7. 最後請 owner 同意，才刪除 `pr17-retention-review` worktree、primary `.tmp/pattern-scan-execution/` 與 scratch run。
   刪前 `worktree_inventory.py` 不應再列出任何 `cited_by`。

## 5. 不要做

- 不要重算 B1、H1 或 Q1，不要改既有收據、hold 或已發布的表。
- 不要用 4 路平行加速，也不要在 18:00–18:45 或 `StockProject-*` 執行中讀 live producer。
- 不要在研究完成前把報告、`study.json` 或任何 PR 描述寫成「已完成」。
- 不要自行刪除任何暫存或 worktree；`taskkill` 只能針對自己啟動的 PID。
