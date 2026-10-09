# 台股夜間 AI 研究員計畫

## 1. 最終目標

這個專案的目標是建立一個安全、可審核、可持續改進的台股 AI 研究系統。

理想使用方式不是寫一支 Python 腳本去呼叫 LLM API，也不是讓未驗證的 agent 在主機上亂跑。理想狀態是：

1. 使用者在本機開啟 Codex。
2. Codex 作為研究員大腦，負責閱讀任務、設計策略、修改候選策略、分析結果與寫報告。
3. Docker 作為安全執行器，負責執行 Python 回測、讀取行情資料、產生 JSON/Markdown artifact。
4. Codex 的自動審核與 Docker 的檔案掛載邊界一起保護主機。
5. 策略研究可以自動反覆執行，但不能改壞電腦、讀取 secrets、修改核心引擎、改 Git 歷史或真實下單。

也就是：

```text
Codex on Host = Brain / Researcher / Reviewer
Docker Runtime = Safe Hands / Backtest Executor
Python = Tooling, not the researcher
```

## 2. 目前採用的主路線

主路線改為 **Host Codex + Docker Executor**。

這條路線符合目前需求：

- 不需要為 container 內另一個 Codex 額外準備 API key。
- 不需要把 host 的 `~/.codex`、ChatGPT session 或 `.env` 掛進 container。
- 可以繼續使用目前 Codex 的自動審核與互動能力。
- 風險較高的 Python 執行、策略回測與資料讀取放進 Docker。
- Docker 只掛載必要路徑，讓策略程式就算寫壞，也只能影響允許的研究輸出區。

這和「Codex CLI in Docker」不同。Codex CLI in Docker 仍然保留為未來可選方案，但不是短期主路線。

## 3. 使用者最後會怎麼使用

### 3.1 日常互動式研究

使用者打開這個 repo，直接對 Codex 討論今天的策略問題。日常入口是一句研究方向，不是 Docker 指令。

```text
今天我們來研究突破策略怎麼減少假訊號，請建立或接續今天的策略研究 task。
```

Codex 會做：

1. 在 `tasks/YYYYMMDD/` 建立任務資料夾。
2. 在允許的研究區建立候選策略。
3. 需要安全執行時，由 Codex 呼叫 Docker 執行回測。
4. 讀取 `reports/` 或 `tasks/YYYYMMDD/summary.json`。
5. 根據結果調整參數或策略。
6. 再跑一次回測。
7. 寫研究日誌、`walkthrough.md` 和 `nightly_report.md`。
8. Notion 設定完成時，同步每日研究摘要。
9. 等使用者審核與討論下一輪，不直接把策略上線。

### 3.2 夜間半自動研究

這裡的「半自動」不是要求使用者自己執行 Docker 指令，也不是寫一個 Python script 取代 Codex。

短期使用方式應該是：

```text
使用者提出研究任務
Codex 判斷需要哪些工具
Codex 依風險選擇直接執行或用 Docker 執行
Codex 讀取 summary
Codex 迭代策略與撰寫報告
```

也就是你不需要記得 Docker 指令。Docker 是 Codex 可使用的安全工具，不是使用者的日常操作負擔。

在互動式研究中，你只需要對 Codex 說：

```text
請執行 tasks/2026-05-03/mission.md，必要時用 Docker 跑回測，最後寫 walkthrough.md 和 nightly_report.md。
```

Codex 負責決定：

- 哪些步驟可以直接在目前工作區執行。
- 哪些候選策略或不確定程式碼應該放進 Docker 執行。
- 何時需要自動審核或人工審核。
- 何時停止並回報風險。

未來如果有 Windows Task Scheduler，它最多只負責提醒或建立任務資料夾，不負責策略研究，也不直接取代 Codex。

### 3.3 每日研究日誌與 Notion

成熟後的每日流程會是：

1. 讀取本地 K 線資料。
2. 選擇股票池。
3. 產生或修改候選策略。
4. 由 Codex 視風險在 Docker 裡跑回測。
5. 產生固定 schema 的 `summary.json`。
6. 寫 `walkthrough.md`。
7. 寫 `nightly_report.md`。
8. 寫每日策略研究日誌，記錄假設、實驗、結果、風險與下一輪方向。
9. 將摘要同步到 Notion。

本地 artifact 是正式紀錄。Notion 是每日研究索引與討論日誌，不是交易入口。

## 4. 安全模型

### 4.0 三個安全等級

本專案不應該把所有事情都強制放進 Docker，也不應該完全只靠 Codex 自動審核。應依任務風險選擇執行等級。

#### Level 0：Codex-only

適用：

- 修改文件。
- 修改 CLI、schema、測試。
- 人工明確審核過的小型策略。
- 不執行未知或大量生成的 Python code。

保護來源：

- Codex 自動審核。
- Git diff。
- hooks。
- 使用者互動審核。

這是最輕量的日常開發模式。

#### Level 1：Codex + Docker Executor

適用：

- 執行 Codex 產生的候選策略。
- 多輪參數搜尋。
- 需要讀行情資料並產生報告。
- 可能有 bug 的研究程式碼。

保護來源：

- Codex 負責研究判斷與審核。
- Docker 限制 Python runtime 能讀寫的檔案。
- `engine/` 與行情資料 read-only。
- `reports/`、`tasks/`、`research_lab/` writable。
- host `.env` 不掛載。

這是下一階段主線。

#### Level 2：Containerized Agent

適用：

- 真正無人夜間 agent。
- container 內另跑 Codex/Gemini/其他 CLI agent。
- 連網研究。
- 高自由度策略生成。

這是後期可選方案，不是目前主線。它可能需要額外 API key、網路 allowlist、額度限制與更完整的 credential 隔離。

### 4.1 主安全邊界

目前主安全策略不是「永遠用 Docker」，而是「依風險升級到 Docker」。

Level 0 可用 Codex-only。Level 1 開始使用 Docker 作為 Python 執行時邊界。Docker runtime 要保證：

- `StockProject/engine/` 是 read-only。
- 行情資料是 read-only。
- `reports/`、`tasks/`、`research_lab/` 是 writable。
- host `.env` 不掛進 container。
- host `~/.codex` 不掛進 container。
- container 預設不給一般網路。
- 真實下單與 broker credential 不進 container。

### 4.2 Codex 的角色

Codex 不直接把所有危險行為交給 Python。

Codex 負責：

- 決定研究步驟。
- 產生或修改候選策略。
- 呼叫 Docker 執行回測。
- 讀取 summary JSON。
- 根據結果迭代。
- 寫研究紀錄。
- 在高風險操作前依自動審核或人工審核停下來。

Codex 不應該：

- 直接把 secrets 寫進檔案。
- 把 `.env` 掛進 Docker。
- 修改 `.git/`。
- 自動修改核心引擎並直接視為完成。
- 執行真實下單。

### 4.3 Python 的角色

Python 是工具層，不是研究員本體。

Python 可以做：

- 回測。
- 資料讀取。
- 指標計算。
- 結果 schema 輸出。
- 報告生成。
- sandbox smoke test。

Python 不做：

- 直接呼叫 LLM API 自己假裝研究員。
- 自行決定長期研究方向。
- 自行修改核心架構。
- 自行處理 secrets 或外部帳號。

## 5. 目前已完成

### 5.1 Backtest CLI

已建立：

```text
StockProject/backtest_cli.py
```

它支援：

- `--strategy`
- `--codes`
- `--start`
- `--end`
- `--cash`
- `--data-path`
- `--output`

已驗證：

```powershell
uv run python StockProject\backtest_cli.py `
  --strategy StockProject\strategies\test_strategy.py `
  --codes 2330 `
  --start 2024-01-01 `
  --data-path shioaji_stock_prices\data `
  --output reports\smoke\2330_buy_hold.json
```

### 5.2 Summary Schema

回測輸出已固定為 schema version `1.0`。

主要欄位：

- `schema_version`
- `generated_at`
- `run`
- `strategy`
- `data`
- `metrics`
- `benchmark`
- `portfolio`
- `trades`
- `warnings`

這讓 Codex 或未來 agent 可以穩定讀取結果，而不是解析終端文字。

目前 `metrics` 已包含報告需要的第一批風險欄位：

- `max_drawdown_rate`
- `win_rate`
- `closed_trade_count`
- `buy_and_hold_return_rate`
- `excess_return_rate`

Benchmark policy：

- `buy_and_hold` 採用等額資金分配。
- 為了讓高價股與不同股票池可比較，benchmark 允許 fractional shares。
- 這個 benchmark 只用於研究比較，不是交易執行模型。
- 台股零股不能當沖、盤中/盤後零股成交限制與流動性限制，後續若要做真實交易模擬必須另外建模。

### 5.3 Docker Runtime Smoke

已建立：

```text
.dockerignore
docker-compose.yml
docker/research-runtime.Dockerfile
scripts/smoke_research_runtime.py
```

已通過：

```powershell
docker compose run --rm --build research-runtime-smoke
```

通過項目：

```text
[PASS] reports directory is writable
[PASS] engine directory is read-only
[PASS] host .env is not mounted
[PASS] backtest CLI completed
[PASS] summary schema is valid
[PASS] research runtime smoke test completed
```

## 6. 專案完成後的使用方式

### 6.1 使用者的日常操作

短期內，使用者不需要記 Docker 指令，也不需要自己啟動另一個 agent。

正常使用方式是：

```text
使用者打開本 repo
使用者對 Codex 說研究任務
Codex 建立任務資料夾
Codex 產生或修改候選策略
Codex 視風險使用 Docker 執行回測
Codex 讀取 summary JSON
Codex 迭代一次或多次
Codex 寫報告
使用者審核結果
```

例如：

```text
請針對 2330、2454、2317 做一個均線交叉策略研究。
限制只能用 K 線資料，不連網，不下單。
必要時用 Docker 跑回測。
最後輸出 walkthrough.md、nightly_report.md，以及 summary.json。
```

Codex 會自行判斷：

- 如果只是寫任務說明或調整報告格式，使用 Level 0。
- 如果要執行候選策略或跑參數搜尋，使用 Level 1。
- 如果牽涉 secrets、真實下單、改核心 engine、連網或大量未知程式碼，先停止並回報。

### 6.2 Codex 會替使用者執行什麼

Codex 可以替使用者執行：

- 建立 `tasks/YYYYMMDD-<topic>/`。
- 寫入 `mission.md`。
- 建立候選策略檔。
- 呼叫既有 backtest CLI。
- 必要時呼叫 Docker runtime。
- 讀取 `summary.json`。
- 比較多次回測結果。
- 寫研究過程與結論。

Codex 不應該替使用者執行：

- 真實下單。
- 把策略直接部署成交易程式。
- 在沒有審核下修改 `StockProject/engine/`。
- 把 `.env`、broker credential 或 host Codex session 掛入 container。
- 建立不可追蹤的大量背景程序。

### 6.3 Docker 在使用流程中的位置

Docker 是 Codex 的工具，不是使用者每天要操作的介面。

使用者可以說「必要時用 Docker」，然後由 Codex 決定是否執行：

```powershell
docker compose run --rm research-runtime-smoke
```

或未來的：

```powershell
docker compose run --rm research-runtime <task-id>
```

使用者要理解的是安全語意，不是記住指令：

- Docker 內可以跑候選策略。
- Docker 內可以寫 reports/tasks/research_lab。
- Docker 內不能讀 host `.env`。
- Docker 內不能改 engine。
- Docker 內預設不連網。

## 7. 任務與產物契約

### 7.1 任務資料夾

每次研究任務使用一個獨立資料夾：

```text
tasks/YYYYMMDD-<topic>/
  mission.md
  candidates/
  runs/
  summary.json
  walkthrough.md
  nightly_report.md
```

建議用途：

- `mission.md`：使用者需求、限制、股票池、時間範圍、風險規則。
- `candidates/`：Codex 產生的候選策略，允許 Docker 執行。
- `runs/`：每次回測的原始輸出。
- `summary.json`：本任務最後選定結果的機器可讀摘要。
- `walkthrough.md`：Codex 的研究過程、假設、嘗試、失敗原因。
- `nightly_report.md`：給使用者閱讀的結論報告。

任務資料夾應優先用 scaffolder 建立：

```powershell
uv run python scripts\create_research_task.py `
  --task 20260504-ma-convergence `
  --codes 2330,2454,2317 `
  --start 2024-01-01 `
  --objective "Research moving-average convergence plus breakout." `
  --use-docker
```

scaffolder 會建立 `mission.md`、`candidates/`、`runs/`，且預設不覆蓋既有 task。若要重寫 `mission.md`，必須明確加上 `--force`。

### 7.2 mission.md 基本格式

`mission.md` 至少應包含：

```markdown
# Mission

## Scope

- Market: Taiwan stocks
- Symbols: 2330, 2454, 2317
- Data: local K-line only
- Start: 2024-01-01
- End: latest available local data

## Constraints

- No real trading
- No broker credentials
- No internet research
- Do not modify StockProject/engine/
- Use Docker for generated strategy execution

## Objective

- Compare at least two simple K-line strategies
- Pick the best candidate by risk-adjusted return
- Write summary.json, walkthrough.md, nightly_report.md
```

### 7.3 summary.json 基本要求

`summary.json` 必須維持固定 schema，方便 Codex 與未來 Notion 整合讀取。

最低要求：

- schema version 固定可辨識。
- 包含策略名稱、股票池、資料範圍、初始資金。
- 包含 final value、total return、max drawdown 或明確 warning。
- 包含交易摘要。
- 包含 warning，不能把資料不足或計算失敗藏起來。

### 7.4 walkthrough.md 基本要求

`walkthrough.md` 是研究軌跡，不是漂亮報告。

它應記錄：

- 原始假設。
- 嘗試過哪些策略或參數。
- 每次回測的摘要。
- 為什麼調整。
- 為什麼停止。
- 哪些結果不能信。

### 7.5 nightly_report.md 基本要求

`nightly_report.md` 是給使用者看的結論。

它應包含：

- 本次研究結論。
- 最佳策略摘要。
- 關鍵數據。
- 主要風險。
- 不建議採用的原因，若結果不好。
- 下一步建議。

它不能包含：

- 下單指令。
- 保證獲利語氣。
- 未揭露資料不足的結論。

### 7.6 報告產生流程

> **已於 2026-08-08 下架**：本節描述的 Codex Notion 報告流程（`scripts/generate_task_report.py`
> 與 `.codex/skills/notion-research-report/`）經使用者確認判定不好用，已整支移除。以下內容保留
> 作為歷史記錄，不再是現況。

本地報告流程應先固定，再接 Notion MCP。

目前報告流程：

1. Docker task runner 產生 `summary.json`。
2. `scripts/generate_task_report.py` 讀取 `summary.json` 與 `mission.md`。
3. 產生機械式草稿：
    - `walkthrough.md`
    - `nightly_report.md`
4. Codex 再讀取草稿與 run artifacts，補上策略判斷、風險解讀與下一步。

這個 script 不取代 Codex 的研究判斷。它只負責把固定 schema 轉成一致的 Markdown 骨架，降低每次研究都從零開始寫報告的成本。

## 8. 下一階段計畫

### Phase 2-A：Host Codex + Docker Executor

這是下一個主要階段。

目標：讓目前這個 Codex session 可以安全地使用 Docker 進行策略研究。

要做的事情：

1. 建立標準任務資料夾格式：

```text
tasks/YYYYMMDD-<topic>/
  mission.md
  candidates/
  runs/
  summary.json
  walkthrough.md
  nightly_report.md
```

2. 建立一個可寫候選策略目錄，例如：

```text
tasks/YYYYMMDD/candidates/
```

3. 更新 Docker compose，允許 container 讀取候選策略並輸出報告。

4. 建立一個研究任務 smoke：

```text
Codex 產生候選策略
Docker 跑回測
Codex 讀 summary
Codex 調整參數
Docker 再跑一次
Codex 寫 walkthrough
```

這一步仍然不需要額外 API key。

驗收標準：

- 使用者只需要提出研究任務，不需要手動整理 Docker 指令。
- Codex 能建立任務資料夾。
- Codex 能產生一個候選策略。
- Docker 能執行該候選策略。
- Codex 能讀取回測 JSON。
- Codex 能根據結果做一次小幅策略或參數調整。
- 最後產生 `walkthrough.md` 與 `nightly_report.md`。
- Git diff 能清楚顯示本次研究改了哪些檔案。

### Phase 2-B：夜間 Runner

當 Phase 2-A 穩定後，再做半自動夜間 runner。

Runner 的角色不是取代 Codex，而是提供固定任務入口。它只做機械性工作，例如建立任務資料夾、檢查資料、呼叫既有工具。

可選入口可能是：

```powershell
scripts\run_nightly_research.ps1
```

它可以：

- 建立任務資料夾。
- 寫入初始 `mission.md`。
- 呼叫 Docker backtest。
- 保存 artifact。

但策略設計與迭代仍由 Codex 主導。

如果沒有辦法讓 Codex 自己在夜間醒來，Phase 2-B 仍然有價值，因為它可以把研究任務準備好。隔天使用者只要叫 Codex：

```text
請接續 tasks/2026-05-03-ma-cross 的 mission.md，完成研究與報告。
```

驗收標準：

- runner 不需要 LLM API key。
- runner 不自己生成策略。
- runner 不處理 secrets。
- runner 可以重跑且不覆蓋既有研究結果。
- Codex 可以接手 runner 產生的任務資料夾。

### Phase 2-C：Codex CLI in Docker（可選）

這是後期可選方案，不是目前主路線。

只有當我們真的需要「container 內有另一個 Codex agent 自己跑完整晚」時，才考慮這條路。

這條路可能需要：

- `CODEX_API_KEY`
- container network access to OpenAI
- 不掛 host `~/.codex`
- 更嚴格的 network allowlist
- 額度限制

目前先不做。

驗收標準：

- 先有明確原因證明 Host Codex + Docker Executor 不夠。
- 不能掛 host `~/.codex`。
- 不能掛 host `.env`。
- container network 必須可控。
- API key 必須可撤銷、限額、低權限。
- 先通過 sandbox smoke test，再允許長時間執行。

## 9. 後期研究能力

### 9.1 熱門股與熱門指數

K 線策略穩定後，可以建立熱門股研究：

- 成交量放大。
- 波動率變化。
- 價格突破。
- 產業或題材標籤。
- 新聞與論壇熱度。
- 長期熱門清單。

未來可定義 `hotness_score`，把熱門程度納入回測條件，而不是只用人工挑股。

### 9.2 連網研究

連網研究屬於後期能力，不能在安全模型穩定前開放。

原因：

- 需要網路 allowlist。
- 需要處理來源可信度。
- 需要避免 prompt injection。
- 需要避免把外部文字直接變成可執行策略。
- 需要保存來源與引用。

初期應先用本地資料。等 K 線研究流程穩定後，再設計新聞、論壇、熱門股資料入口。

### 9.3 Notion 報告

Notion 是報告發布與研究知識庫。

Notion 整合前，必須先有穩定的本地 artifact：

- `summary.json`
- `walkthrough.md`
- `nightly_report.md`

等本地格式穩定後，再由 Codex 或 MCP 把結果同步到 Notion。

Notion 不負責：

- 執行策略。
- 保存 secrets。
- 觸發下單。

### 9.4 外部參考專案

後續研究 agent 架構時，可以參考：

- Dexter: `https://github.com/virattt/dexter.git`

這個專案方向可能接近本專案想做的 AI 研究員。現階段先記錄為參考來源，不直接引入程式碼。若之後需要研究 source code，應 clone 到明確的研究參考目錄，例如 `research_lab/references/`，避免把第三方專案混進 `.agents/memory/`。

## 10. 近期待辦

- [x] 建立本地 backtest CLI。
- [x] 建立 summary schema v1.0。
- [x] 建立 Docker runtime smoke。
- [x] 驗證 Docker 可寫 reports、不可寫 engine、不可讀 host `.env`。
- [x] 建立 `tasks/YYYYMMDD-<topic>/` 任務格式的 sample contract。
- [x] 讓 Docker runtime 支援讀取 task candidates。
- [x] 建立 task-based Docker research smoke。
- [x] 建立 research task scaffolder。
- [x] 做第一個 Host Codex + Docker Executor 策略研究 smoke，包含一次策略調整。
- [x] 產出第一份 `walkthrough.md`。
- [x] 產出第一份 `nightly_report.md`。
- [x] 在 summary schema 補上報告需要的風險指標，例如最大回撤、勝率與 buy-and-hold comparison。
- [x] 擴充策略工具，支援 cash-aware position sizing。
- [x] 用小型股票池重跑 Host Codex + Docker Executor research smoke。
- [x] 在 summary schema 補上 per-symbol metrics，讓報告能看出哪檔股票貢獻報酬與交易品質。
- [x] 補上更清楚的 benchmark allocation policy。
- [x] 補上 per-symbol drawdown。
- [x] 建立 `summary.json` 到 `walkthrough.md` / `nightly_report.md` 的報告草稿產生器。
- [x] 支援策略參數化，讓同一個 candidate 可以透過 `--params-json` 或 `--params-file` 跑不同參數組合。
- [x] 建立 task-local 參數 sweep runner，輸出排序後的 `sweep_summary.json`，並可把最佳結果 promote 成 `summary.json`。
- [x] 建立第一個「均線聚集加突破、跌破 10 日均線賣出」candidate smoke，確認 MA/EMA 參數比較可以跑通。
- [x] 報告草稿支援顯示參數 sweep 排名與每組參數的核心指標。
- [x] Docker task smoke 覆蓋策略參數與參數 sweep summary schema。
- [x] 補上整數股 buy-and-hold benchmark，近似台股零股 buy-and-hold 可買性，並保留零股限制說明。
- [x] Summary/report 會標示請求股票沒有載入價格資料的 warning，避免報告誤以為股票池全數有效。
- [x] 建立 Phase 2-B 輕量夜間 runner，只負責準備 task、資料 preflight、next prompt，不取代 Codex 研究判斷。
- [x] 補上 Phase 2-B runner 使用文件：`docs/zh-TW/Phase2B-Runner.md`。
- [ ] 再評估是否需要 Codex CLI in Docker。

## 11. 暫緩事項

以下先不做：

- 真實下單。
- 自由連網研究。
- 自動修改核心引擎。
- Notion 自動寫入。
- Python-only LLM strategy generator。
- Container 內額外跑 Codex CLI。

這些不是不能做，而是要等 Host Codex + Docker Executor 這條主路線穩定後再評估。

## 12. 最終示範研究案例

整個計畫完成後，需要有一個具體範例，展示這套系統可以怎麼協助使用者做策略研究與報告呈現。

第一個示範案例先選擇「均線聚集加突破」策略，因為它足夠單純，但又能驗證本專案是否真的具備可用的研究能力。

### 12.1 策略想法

研究方向：

- 比較不同均線類型，例如 MA 與 EMA。
- 比較不同均線組合，例如短中長均線聚集。
- 當均線聚集後，價格向上突破時進場。
- 當價格跌破 10 日均線時出場。
- 比較不同股票族群或股票池中，這個策略在哪些類型效果較好。

這個案例不追求一開始就找到最佳策略，而是要求系統能處理這種程度的回測問題。

### 12.2 程式能力要求

程式碼至少要能支援：

- MA 與 EMA 計算。
- 多條均線聚集條件。
- 突破條件。
- 跌破 10 日均線出場。
- 多股票回測。
- 不同參數組合比較。
- 依股票、族群或股票池彙整結果。
- 輸出固定 schema 的 `summary.json`。

如果資料中沒有完整族群分類，初期可以先用手動股票池或簡單分類代替，不需要為了這個案例先做完整產業資料系統。

### 12.3 報告呈現要求

報告要能清楚呈現：

- 測試了哪些均線類型與參數。
- 哪些股票或股票池表現最好。
- 最佳結果是否來自少數個股，還是具有群體一致性。
- 進出場規則是否容易理解。
- 報酬、最大回撤、交易次數、勝率等關鍵數據。
- 策略失效或不建議使用的情境。
- 下一步可以怎麼改進。

這份報告不需要花大量 token 寫成研究論文，但要足夠清楚，讓使用者能判斷策略是否值得繼續研究。

### 12.4 Notion 最終呈現

本地 artifact 穩定後，這個示範案例的最終報告預期由 Notion MCP 寫入 Notion。

Notion 整合等使用者提供 MCP 設定後再做。屆時再一起討論：

- Notion 頁面要怎麼建立。
- 資料庫欄位要怎麼設計。
- 圖表、表格、結論區塊要怎麼排版才清楚。
- 哪些內容適合長期保存，哪些只適合留在本地 artifact。

在 Notion 整合完成前，仍先以 `summary.json`、`walkthrough.md`、`nightly_report.md` 作為標準輸出。
