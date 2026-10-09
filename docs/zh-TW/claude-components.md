# Claude Code 元件參考

現行契約為 `AGENTS.md`；擁有者已要求刪除 `CLAUDE.md`。Claude Code 使用 2.1.281 以上版本並啟用內建 `agents-md` 支援，且專案或祖先目錄沒有優先載入的 `CLAUDE.md`／`CLAUDE.local.md` 時，會原生載入根契約；本專案不新增 import 或注入 hook。本機 implementation／security review 前先在 `/context` 或 `/memory` 確認根契約；若原生載入不可用或被覆蓋，先明確讀取根目錄 `AGENTS.md`，再依其嚴重程度、secret 分類與授權邊界審查。詳見[官方載入規則](https://code.claude.com/docs/en/memory#agentsmd)。下方舊移除紀錄不代表目前的規則載入方式。

本文件列出 `.claude/` 目錄中所有啟用的 agents、commands、skills、hooks 與 rules。

**ECC 來源**：[affaan-m/ECC](https://github.com/affaan-m/ECC) v2.0.0-rc.1
**ECC 整合日期**：2026-06-02
**記憶**：Claude 僅使用 Claude Code 的內建記憶；必要 repository guidance 仍納入版本控制——詳見 `AGENTS.md` §Working With The Owner。

本專案設定刻意停用外部的 Superpowers、Ponytail 與 Karpathy plugins（`.claude/settings.json` 的 `enabledPlugins` 皆為 `false`，並由 `test_claude_native_workflow_does_not_require_external_workflow_plugins` 測試斷言）。本參考文件描述 repository-owned 的 Claude 元件與 Claude 原生能力；GitHub、skill-creator 與 Pyright LSP 仍在 `.claude/settings.json` 中啟用。

---

## Agents

Agents 是由主要 Claude 工作階段呼叫的專用子代理，用於執行特定任務。

Claude 的自動分派主要由各 agent 的 description 與目前任務脈絡決定。`signal-miner` 是最低成本的原生唯讀工具，負責有界的高輸出指令；tests、benchmarks、廣泛搜尋、verbose diagnostics、dependency traces 或大型 diff/log inspections 的輸出隔離值得一次委派時才使用。短小且聚焦的檢查由 main session 直接執行，一般程式碼定位使用內建 Explore agent。`task-worker` 則是只供高階 main session 降級執行有界修改的中價選項，任務必須有明確目標、範圍、驗收條件與驗證方式。最低階 main session 應自行處理簡單工作，或視情況使用內建 Explore 或 general-purpose，不升級到 `task-worker`。模糊、跨領域、security-sensitive、architecture 與 planning 工作應留給 main session 或適合的內建 agent。

Claude 在 `.claude/settings.json` 維持 `model: "opusplan"`：原生 Plan Mode 使用 opus，執行階段使用 sonnet。自訂 agents 不用於把計畫傳回 main session。

### 工作流程（原創——非來自 ECC）

| Agent               | 模型            | 工具                                | 用途                                                                                                                                            |
| ------------------- | --------------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `commit-specialist` | haiku           | Bash, Read                          | 審查已暫存的變更並草擬 commit 訊息                                                                                                              |
| `doc-translator`    | haiku           | Read, Write, Edit                   | 低階文件翻譯與同步者：將任何需寫入檔案的翻譯處理到單一明確的非 canonical 目標；main session 決定來源與目標，衝突時以其維護的 canonical 文件為準 |
| `signal-miner`      | haiku           | Read, Grep, Glob, Bash              | 以最低成本隔離預期會產生大量 log 或 stdout 的指令，僅回傳精簡訊號而非原始輸出                                                                   |
| `task-worker`       | sonnet (medium) | Read, Grep, Glob, Write, Edit, Bash | 執行已有明確範圍、驗收條件與驗證方式的低至中風險修改；當範圍或風險擴大時停止並回報                                                              |

### Stock 專屬（非來自 ECC，upstream 沒有對應項目）

| Agent                    | 模型 | 工具                    | 用途                                                        |
| ------------------------ | ---- | ----------------------- | ----------------------------------------------------------- |
| `strategy-diagnostician` | opus | Read, Grep, Glob, Write | 依 mission 與既有證據診斷；不自訂門檻、不依保留期結果調參。 |

### 未從 ECC 移植（含原因）

| Agent                                                                                                                                              | 原因                                                                                                                                                                                    |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `planner`                                                                                                                                          | 2026-06-08 移除——已由 Native Plan Mode（`EnterPlanMode`/`ExitPlanMode`）取代。Stock 曾殘留一份未套用此移除的舊檔（一般用途 ECC 範本，內容含 Stripe 訂閱範例），已於 2026-08-08 一併刪除 |
| `architect`、`code-reviewer`、`code-simplifier`、`loop-operator`、`performance-optimizer`、`python-reviewer`、`silent-failure-hunter`、`tdd-guide` | 2026-07-13 移除——原生 Claude 功能與聚焦 reviewer 已涵蓋其責任，無須重複委派。                                                                                                           |
| `implementation-reviewer`、`plan-reviewer`、`security-reviewer`                                                                                    | 2026-10-02 移除——目前模型、Native Plan Mode、內建 `/code-review`、hosted Codex PR review 與 pre-commit gates 已涵蓋其責任；其餘 agents 的存在是為了節省成本。                           |
| `refactor-cleaner`                                                                                                                                 | 依賴 Node.js 工具（knip、depcheck、ts-prune）；本專案使用 Python                                                                                                                        |
| `harness-optimizer`                                                                                                                                | 需要 ECC 內部的 `/harness-audit`；無法移植                                                                                                                                              |
| 所有 `*-build-resolver`（共 11 個 agents）                                                                                                         | 未使用非 Python 語言                                                                                                                                                                    |
| 非 Python 語言的程式碼審查器                                                                                                                       | 未使用的語言                                                                                                                                                                            |
| `gan-*`、`seo-specialist`                                                                                                                          | 超出範疇                                                                                                                                                                                |
| `homelab-*`、`network-*`、`healthcare-reviewer`                                                                                                    | 領域不符                                                                                                                                                                                |
| `marketing-agent`                                                                                                                                  | 延後——待短片製作規劃啟動時新增                                                                                                                                                          |

---

## 互動、自動化與公司內部使用

- 互動工作：進入 Native Plan Mode，核准計畫後再回到執行模式。
- 無人值守工作：使用分離的 planning 與 execution sessions。planning session 寫入受維護的 plan artifact；execution session 讀取已核准 artifact。不要以 planner subagent 作為 main-session handoff。
- Claude-only 公司移植：保留 instructions、rules、agents、skills 與 hygiene hooks。使用公司核准的固定模型 ID 或 alias mapping，不依賴本 repo 個人 Pro 的預設。

`REVIEW.md` 不屬於本地基準線的一部分，僅在 repo 註冊 Claude 的 managed Team 或 Enterprise Code Review 服務時才新增。

---

## Commands（斜線指令）

### 工作流程（原創——非來自 ECC）

| Command       | 用途                                                            |
| ------------- | --------------------------------------------------------------- |
| `/gen-commit` | 透過 `commit-specialist` 產生符合 Conventional Commits 格式訊息 |
| `/worktree`   | 建立、接續與完成隔離的任務 worktree                             |

原生 Git／GitHub 操作遵守[共用 Git 工作契約](../en/git-workflow.md)。預設只做本地交付；擁有者啟用 PR 交付後，可推送任務分支與更新 PR，合併仍需另外授權。

### Stock 專屬（非來自 ECC，upstream 沒有對應項目）

| Command                  | 用途                                                                                                          |
| ------------------------ | ------------------------------------------------------------------------------------------------------------- |
| `/check-daily-log`       | 檢查今天排程的資料管線 log；實際程序在 `shioaji_stock_prices` submodule 自己的同名指令，本 repo 只是指向它    |
| `/check-data-progress`   | 檢查 `data/official_daily.sqlite` 更新到哪個日期、各市場的缺口與 backfill 進度；同樣指向 submodule 自己的指令 |
| `/diagnose-strategy`     | 依 mission 與既有證據診斷；不自訂門檻、不依保留期結果調參。                                                   |
| `/dev-log`               | 透過 `notion-dev-log` skill 把今天的開發進度記錄到 Notion                                                     |
| `/fork-maintenance-sync` | 依照 `docs/en/fork-maintenance.md`，從本機的 `.tmp/agent-starter-kit` clone 同步 agent infrastructure         |

### 已移除（2026-06-10 清理——agents 與內建 `/code-review` 已涵蓋）

| Command          | 替代方案                                                              |
| ---------------- | --------------------------------------------------------------------- |
| `/build-fix`     | 原生 evidence-driven debugging + `python-testing` skill               |
| `/code-review`   | 內建 `/code-review`（含 `ultra` 雲端 review）+ hosted Codex PR review |
| `/feature-dev`   | Native Plan Mode + 原生 test-first workflow + `signal-miner` agent    |
| `/python-review` | `python-testing` skill 與內建 `/code-review`                          |
| `/security-scan` | 內建 `/security-review` + `detect-secrets` gate                       |
| `/test-coverage` | `python-testing` skill（`pytest --cov`）                              |

### 未從 ECC 移植（含原因）

| Command                                         | 原因                                                                                                      |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `/pr`、`/review-pr`                             | 不需要 PR 工作流程                                                                                        |
| `/multi-*`（共 5 個指令）                       | 多代理協作尚未成熟                                                                                        |
| `/learn`、`/skill-create`                       | 依賴 ECC observation hooks 與完整 instinct pipeline；由 `skill-authoring` 規則與 `skill-creator` 外掛取代 |
| `/evolve`                                       | 由 `skill-authoring` 規則與 `skill-creator` 外掛取代                                                      |
| `/hookify-*`（共 4 個指令）                     | ECC 內部 hook 管理                                                                                        |
| `/sessions`、`/save-session`、`/resume-session` | 已由 Claude Code 內建記憶與 session history 取代                                                          |
| 語言專屬的建構／測試／審查指令                  | Go/Rust/Kotlin/Java 等語言未使用                                                                          |
| `/cost-report`、`/model-route`                  | 有需要時再新增                                                                                            |
| `/jira`、`/prp-*`、`/plan-prd`                  | 未規劃 PM 整合                                                                                            |

---

## Skills

Skills 是內部工作流程文件，在對應的 command 或 agent 需要時載入。

### 工作流程（原創——非來自 ECC）

| Skill                    | 用途                                              |
| ------------------------ | ------------------------------------------------- |
| `commit-helper`          | Conventional Commits 格式、限定範圍的 commit 執行 |
| `dependabot-remediation` | 唯讀警示擷取、最小安全升級與完成證據              |

### 開發（從 ECC v2.0.0-rc.1 移植）

| Skill            | 用途                                                                                                         |
| ---------------- | ------------------------------------------------------------------------------------------------------------ |
| `python-testing` | Repository-specific 行為測試、hook JSON fixtures 與 Windows path 行為。Test-first 決策使用 Claude 原生能力。 |

### 已移除（2026-08-23 清理——原生 GitHub 操作與聚焦的安全工作流）

| Skill        | 原因                                                                                                                                                                      |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `github-ops` | 通用 Issue、PR、CI 與 release 指令重複 Claude 原生 `gh` 能力，並強加多人協作的 stale 政策。Dependabot 工作已移至 `dependabot-remediation`；PR 交付遵守共用 Git 工作契約。 |

### 已移除（2026-08-19 清理——`/learn-eval` 未曾在實務中觸發）

| Skill / Command                | 原因                                                                                                                                                                                                                                                                 |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `skill-curator`、`/learn-eval` | ECC 整體品質門與 Hermes curator 生命週期的手動移植未曾被觸發——唯一提示是每週的 Stop hook 提醒。已由常駐載入的 `AGENTS.md` §Skill Authoring 規則取代，該規則陳述耐用的意圖（當任務類別會重複出現時，撰寫 project skill），加上已啟用的 `skill-creator` 外掛用於撰寫。 |

### Stock 專屬（非來自 ECC，upstream 沒有對應項目）

| Skill                     | 用途                                                                        |
| ------------------------- | --------------------------------------------------------------------------- |
| `check-daily-log`         | 指向 `shioaji_stock_prices` submodule 自己的 check-daily-log 程序           |
| `check-data-progress`     | 指向 submodule 自己的 check-data-progress 程序                              |
| `notion-dev-log`          | 把開發日誌寫入 Notion：讀取 git log、詢問脈絡、建立當日子頁面並更新每日頁面 |
| `openspec-apply-change`   | 實作 OpenSpec change 中的 tasks                                             |
| `openspec-archive-change` | 在 experimental workflow 中歸檔已完成的 change                              |
| `openspec-explore`        | 進入 explore 模式：在動手改之前或改動途中，作為釐清需求與探索想法的思考夥伴 |
| `openspec-propose`        | 一次產生完整 change 提案（含 design、specs、tasks）                         |
| `openspec-sync-specs`     | 把 change 的 delta specs 同步進 main specs，不歸檔 change                   |

### 已移除（2026-08-07 清理——待機設計的 ECC demo skills，無下游使用方）

| Skill                        | 原因                                                                                                                                                                                                                                                         |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `cost-aware-llm-pipeline`    | 本 repo 未呼叫任何 LLM API（僅為 meta-tooling），因此此 skill 只能透過描述在下游專案中符合條件；其硬編碼了陳舊的模型 ID（`claude-sonnet-4-6`）與 2025-2026 年度價格表，可能滲入產生的程式碼。待有實際呼叫 LLM API 的專案建置自此 kit 時，再從 ECC 重新加入。 |
| `llm-trading-agent-security` | 本 repo 無交易代理功能。移除它會縮小下方 `security-review` 的涵蓋聲明——若開始交易代理工作，可視需要恢復。                                                                                                                                                    |

### 未從 ECC 移植（含原因）

| Skill                                      | 原因                                                                                                                                                     |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `python-patterns`                          | Automated formatting 屬於 repository gates；semantic guidance 位於 Python rules                                                                          |
| `deep-research`                            | 需要 firecrawl + exa MCP——延後至 MCP 設定完成                                                                                                            |
| `api-design`、`backend-patterns`           | 本股票專案非 web backend                                                                                                                                 |
| `security-review`                          | 已由內建 `/security-review` 與 hosted Codex PR review 涵蓋；交易相關模式（消費上限、斷路器）因 `llm-trading-agent-security` 於 2026-08-07 移除而不再涵蓋 |
| 非 Python 語言模式                         | 未使用的語言                                                                                                                                             |
| `homelab-*`、`network-*`、`healthcare-*`   | 領域不符                                                                                                                                                 |
| `angular-developer`、`react-*`、`nextjs-*` | 未規劃前端                                                                                                                                               |
| `eval-harness`                             | 2026-06-09 移除：引用不存在的 `/eval` commands，且沒有 runner、graders、baseline format、Python commands 或 CI integration。具備這些能力後才恢復。       |

### 已移除（2026-06-08 清理——Claude 原生 verification 現已涵蓋這些功能）

| Skill               | 原因                                                                                                                 |
| ------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `coding-standards`  | Claude 原生 guidance 與縮減後的 `coding-style` rule 已涵蓋                                                           |
| `tdd-workflow`      | 由原生 test-first workflow 取代                                                                                      |
| `verification-loop` | 由原生 testing、review 與 pre-commit verification 取代                                                               |
| `git-workflow`      | 716 行 Git 教科書；repo 提交規範現在僅在 `commit-helper` skill（`git-workflow` rule 也於 2026-06-13 清理中一併移除） |

---

## Hooks

Hooks 是由 Claude Code harness 自動執行的 Python 腳本。

| Hook                              | 觸發時機               | 執行內容                                                                              |
| --------------------------------- | ---------------------- | ------------------------------------------------------------------------------------- |
| `claude_post_tool_use_hygiene.py` | Python Edit/Write 之後 | 執行唯讀的 Ruff `E722,F601,F602,F634` 診斷，作為 Pyright 的補充；不會格式化或修改檔案 |

Workspace editor defaults 放在 `.vscode/settings.json`：移除行尾空白、保留單一 final newline、使用 Ruff 進行 Python formatting 與 explicit code actions，並將產生的 cache 與本機 agent state 排除於 search、watchers 與 local history 之外。

驗證依變更行為選擇既有測試並重用證據；正常 commit 執行 `.githooks/pre-commit`，Python skills 提供測試命令。

Claude Code 使用官方 Pyright plugin 提供即時型別導覽與 diagnostics；其 PostToolUse hook 額外對修改後的 Python 檔案執行唯讀的 Ruff `E722`、`F601`、`F602`、`F634` check，補足 Pyright 不負責的問題並避免重複回報 undefined-name 與 unused-symbol diagnostics。hook 指令本身與其內部的 Ruff 呼叫都使用 `uv run --no-sync`，避免每次編輯都觸發環境 resync。完整 Ruff linting 與 formatting 延後由 pre-commit 負責，因此正常編輯期間不會觸發 repository-wide formatting。Installed commit hooks 與 PR CI 負責自動化檢查；skills 與 reviewers 不要求另外執行一次手動。

### 已注意但未從 ECC 移植的 hook 概念

| 概念                 | 狀態       | 原因                                                                                           |
| -------------------- | ---------- | ---------------------------------------------------------------------------------------------- |
| PostToolUse 持續學習 | **未實作** | Hook-based 觀察管線（instinct YAML、背景 Haiku agent）未移植——在沒有持久程序的情況下過於重量級 |
| Stop 治理捕捉        | 延後       | ECC 在 session 結束時記錄安全事件——若專案發展到包含自主交易代理時將有其相關性                  |

---

## Rules

Rules 是依路徑範圍載入的 Markdown 檔案，當 Claude 處理符合的檔案類型時生效。

| 規則集                            | 路徑                  | 來源                      | 備註                                                                  |
| --------------------------------- | --------------------- | ------------------------- | --------------------------------------------------------------------- |
| `rules/python/`                   | `**/*.py`、`**/*.pyi` | ECC v2.0.0-rc.1（已修改） | Logging 與以 log 輔助除錯、pytest 指引                                |
| `rules/common/data-structures.md` | 所有檔案              | Stock 專屬                | `shioaji_stock_prices` 資料形狀變更、排程與不可破壞既有研究結果的邊界 |

詳細流程放在 skills 或 agent definitions。

### 已移除（2026-08-23 清理——併入 CLAUDE.md）

`rules/common/` 原有檔案的 `paths` 都是 `"*"`，因此會在 session 第一次存取任何檔案時注入，與 CLAUDE.md 相比實際上沒有真正的路徑範圍效益，只是載入時機不同。其路由內容（review severity、security triggers、phase routing、skill authoring、memory routing、風險導向測試基線）已直接併入 `CLAUDE.md`；Stock 專屬的 `data-structures.md` 保留。

| 規則                     | 原因                                                       |
| ------------------------ | ---------------------------------------------------------- |
| `rules/common/*`（全部） | 實務上並非路徑範圍限定（`paths: "*"`）；已併入 `CLAUDE.md` |

### 已移除（2026-06-13 清理——由 skills 與 CLAUDE.md 擁有）

| 規則                        | 原因                                                                                            |
| --------------------------- | ----------------------------------------------------------------------------------------------- |
| `rules/common/git-workflow` | 共用權限定義於 [git-workflow.md](../en/git-workflow.md)；`commit-helper` 負責本地 commit 檢查。 |
| `rules/common/agents`       | agent 索引由 CLAUDE.md `Subagents` 擁有；parallel-execution 指引已遷移至此                      |

### 已移除（2026-08-07 清理——模型先驗與 CLAUDE.md 已涵蓋）

由於 `rules/common/` 每個檔案的 `paths` 都是 `"*"`，整組會在 session 第一次存取任何檔案時注入，因此其內容是在與 CLAUDE.md 競爭 context，而非延後成本。此次移除通用工程常識，只保留無法推導的路由決策。

| 規則                                      | 原因                                                                                                                   |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `rules/common/coding-style`               | 通用工程常識，與 CLAUDE.md `Engineering Discipline` 重複；結構性 review heuristic 已移至 `rules/common/code-review.md` |
| `development-workflow` §Research & Reuse  | 與 CLAUDE.md `Engineering Discipline` 逐字重複                                                                         |
| `development-workflow` §Pre-Review Checks | 通用 pre-merge 常識，由 CI 與原生 GitHub 操作負責                                                                      |
| `testing` §AAA 與 §Test Naming            | 通用 pytest 結構與命名範例，由 `skill: python-testing` 擁有                                                            |
| `code-review` §Security Review Triggers   | 純指標區塊；reviewer routing 清單已連結 `security.md`                                                                  |

### 未從 ECC 移植（含原因）

| 規則集                                 | 原因                                                                       |
| -------------------------------------- | -------------------------------------------------------------------------- |
| `rules/typescript/`、`rules/react/` 等 | 未使用的語言                                                               |
| `rules/cpp/`                           | SV/UVM 與 C++ 差異過大；延後——待 UVM 專案啟動時建立 `rules/systemverilog/` |

---

## 延後項目

| 項目                            | 類型                    | 前提條件                                                                                               |
| ------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------ |
| `deep-research` skill           | ECC 移植                | 先設定 firecrawl + exa MCP                                                                             |
| `marketing-agent` agent         | ECC 移植                | 確認短片製作規劃啟動                                                                                   |
| `uvm-patterns` skill            | 自訂建置                | UVM 專案啟動                                                                                           |
| `rules/systemverilog/`          | 自訂建置                | UVM 專案啟動                                                                                           |
| Eval-driven development harness | Workflow infrastructure | 加入真實 runner、deterministic graders、baselines、重複執行 metrics、Python commands 與 CI integration |
