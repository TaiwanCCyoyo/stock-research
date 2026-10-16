# Codex 元件參考

Codex 使用 Native Plan Mode、原生 local memories、repo-scoped skills、內建 subagents、project hooks 與已安裝 plugins。它讀取共用的根目錄 `AGENTS.md`，這是 Codex 原生會尋找的檔案；repository 層級的規則放在該檔，巢狀 `AGENTS.md` 只涵蓋自己所在的目錄。

## 原生與 Plugin 對應

| 能力                                         | Codex 實作                                                |
| :------------------------------------------- | :-------------------------------------------------------- |
| 規劃                                         | Native Plan Mode 與 `<proposed_plan>`                     |
| TDD、除錯、worktree、完成前驗證              | Codex 原生能力、project skills 與明確檢查                 |
| GitHub issues、PR、CI、review comments、發布 | 已安裝的 GitHub plugin                                    |
| Slash commands                               | 自然語言 skill triggers                                   |
| 跨 session planning                          | Native planning 加上受維護的 plan artifacts               |
| 跨 session recall                            | 由 project configuration 啟用的 Codex 原生 local memories |

Codex 將 planning 與 implementation 權責保留在 main agent。Read-only agents 負責從大範圍搜尋、logs、test output、diffs，或任何 stdout 會淹沒 main context 的指令中整理 context-isolated evidence summaries；它們不取代 Codex Native Plan Mode，也不擁有發布與整合權限。主 agent 遵守[共用 Git 工作契約](../en/git-workflow.md)。

## 委派

有界工作使用內建 general-purpose subagent；聚焦程式碼探索使用原生 `explorer`。一般工作使用內建代理；以下保留專案特定的研究角色。共用委派原則由 `AGENTS.md` 管理；skills 保留各任務專屬的工作流程細節。

當大量輸入、輸出、雜訊或重複作業使隔離脈絡有具體效益時，優先使用 `gpt-6-luna` 處理簡單工作，包括長篇翻譯、文件同步、大型 diff/log 檢視與機械式 hook 修復。若 handoff 沒有實際助益，短檢查直接執行。需要較多判斷的實作則選用合適模型，並保留使用者選擇主要模型的權限。

先確認目前 runtime 實際提供的模型控制；本機 Codex client 與 API orchestration 不一定有相同介面。[本機 Codex subagent 文件](https://learn.chatgpt.com/docs/agent-configuration/subagents#choosing-models-and-reasoning) 說明逐次建立時的模型設定與組態預設值。使用支援的控制選取 Luna。若只能繼承主模型，明確回報限制並直接執行；或只在隔離 context、平行處理有具體效益時委派，不宣稱已切換模型或降低成本。若模型選擇需使用新 context，明確提供任務、相關指示、範圍與證據。回傳精簡結果，不複製原始輸出。需要時要求實際的平台限制；只描述唯讀任務並不能強制 sandbox。除非實際 workload 證明需要，否則維持已設定的並行數與深度限制。

文件翻譯或同步由 main agent 選定權威來源與明確目標。保留結構、連結、程式碼與識別字；遇到來源衝突或術語不明時回報。這是共用衍生輸出原則的應用。

### stock-research 研究執行

`researcher` 保留專案特定的有界執行角色（`gpt-6-luna`、max、workspace-write）。主代理擁有研究方向、預先登記、授權與驗收權；此角色不得下載、調整驗收門檻、發布或整合變更。既有角色指示與 point-in-time 驗證維持不變。

## Skills

| Skill                | 用途                                                                  |
| :------------------- | :-------------------------------------------------------------------- |
| `python-development` | Python logging 與以 log 輔助除錯                                      |
| `gen-commit`         | 有界 local commit、內建委派協助大量 diff 檢視與簡單 hook 修復，並回報 |

## Claude 能力取捨

| Claude 能力                                                     | Codex 決策               | 原因                                                                                                                                                           |
| :-------------------------------------------------------------- | :----------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/plan`                                                         | 原生／選用 artifact 取代 | 對話式規劃由原生 Plan Mode 提供。持久化的跨 session handoff 使用受維護的 plan artifact。                                                                       |
| `plan-reviewer`、`implementation-reviewer`、`security-reviewer` | 2026-10-02 移除          | Native Plan Mode、目前模型能力、hosted Codex PR review 與 pre-commit gates 已涵蓋其責任；成本導向的委派改用內建 agents。                                       |
| `/feature-dev`                                                  | 原生取代                 | Brainstorming、Plan Mode、test-first development、verification 與 review 已構成完整流程。                                                                      |
| `/build-fix`                                                    | 原生取代                 | Evidence-driven debugging 加 repository verification 已涵蓋逐步診斷與修復。                                                                                    |
| `/code-review`                                                  | 原生／plugin 取代        | Local review 使用原生 Codex review stance；PR review 使用 GitHub plugin。                                                                                      |
| `/python-review`                                                | 原生能力取代             | 由原生 Python review 與既有 repository checks 處理。                                                                                                           |
| `/security-scan`                                                | Agent 與 gates 取代      | 已安裝 detect-secrets、hooks、pre-commit 與 hosted PR review；未安裝 AgentShield。                                                                             |
| `/test-coverage`                                                | 原生能力取代             | 標準 pytest-cov 用法不需要獨立 skill 或 command wrapper。                                                                                                      |
| `github-ops`                                                    | Plugin 取代              | GitHub plugin 提供 repo、issue、PR、CI、comment 與發布流程，且 connector semantics 可維持更新。                                                                |
| `cost-aware-llm-pipeline`                                       | 不移植                   | 它是 application-domain 指引，含 provider-specific model names 與易變價格，不是 Codex 工作流。待 repo 真正建立 LLM API pipeline 時，再依官方資料做共享 skill。 |
| `eval-harness`                                                  | 已移除／延後             | 它引用不存在的 `/eval` commands，且沒有 runner、grader、baseline format、Python commands 或 CI integration。具備這些能力後才恢復。                             |
| `llm-trading-agent-security`                                    | 不移植                   | 僅適用會簽交易或有 wallet authority 的 agents；repo 出現該執行面時再共享。                                                                                     |
| `architect`、`code-simplifier`、`loop-operator`、`tdd-guide`    | 不鏡像                   | Codex 由 main agent 負責 planning/implementation，並使用 project-scoped skills；複製 write-capable specialists 會造成權責重疊。                                |
| `code-reviewer`、`silent-failure-hunter`、`python-reviewer`     | 已整併                   | 原生 review、hosted PR review、Python skills 與 systematic debugging 已涵蓋有效的 review 面向。                                                                |
| `performance-optimizer`                                         | 主代理審查               | 僅在有量測到的瓶頸時，才要求針對性的效能分析。                                                                                                                 |

## 共享政策對齊

| 共享行為                                                          | Codex owner                                             |
| :---------------------------------------------------------------- | :------------------------------------------------------ |
| Operating contract、scoped changes                                | `AGENTS.md`                                             |
| 專案慣例與工具偏好                                                | `AGENTS.md` project conventions                         |
| Review severity 與 CRITICAL/HIGH completion policy                | `AGENTS.md` review and security section                 |
| Verification scope                                                | `AGENTS.md` verification section                        |
| Python development rules                                          | `python-development`                                    |
| Planning、TDD、debugging、review、verification、branch completion | Native Codex、project agents 與 repository verification |

共享開發行為現在與 Claude common-rule routing layer 對齊：plan 透過 Native Plan Mode；test/debug 透過原生 workflow、task-specific tests 與 project skills；delivery review 透過 hosted PR integration；PR 準備在可用時交給 GitHub plugin；交付與整合權限則遵守[共用 Git 工作契約](../en/git-workflow.md)。

## Plans、原生 Memory 與 Commits

- `.references/` 是唯讀的本機參考儲存區，用於存放 upstream clones 與比較材料。
- Codex 原生 local memories 位於 repository 外的使用者 Codex home，並提供選用 recall；必要 repository 規則仍放在 checked-in guidance。
- 盡可能將適用的 workflow 修正納入已驗證的 commit。常駐授權允許在不重複請求核准的情況下，改善專案內的 skills、hooks、rules 與 agent configuration：先驗證、在本地 commit，並回報變更內容與原因。外部操作、全域設定與平台權限不在此授權內。
- 寫入 memory 不需事前核准；若儲存內容會改變日後行為，事後回報。

## Hooks 與 Gates

| 元件                                          | 用途                                                                                         |
| :-------------------------------------------- | :------------------------------------------------------------------------------------------- |
| `.codex/hooks/codex_post_tool_use_hygiene.py` | 修改 Python 檔案後執行唯讀的精簡 Ruff `F` diagnostics                                        |
| `.pre-commit-config.yaml`                     | Formatting、file hygiene、detect-secrets、Ruff T201 與目標檔案 mypy/Pyright（包含兩套 hook） |
| `.vscode/settings.json`                       | Final newline、trailing whitespace hygiene，以及 Python Ruff formatter defaults              |

Repository 驗證依變更行為選擇既有測試，重用未受影響的證據。正常 commit 透過 `.githooks/pre-commit` 執行設定的檢查。

`gen-commit` 沿用共用委派原則：內建 Luna agent 可協助檢視大量 diff，並處理範圍明確的簡單 hook 修復；main agent 負責範圍與最終結果。若提供的 commit 訊息完整，除非有具體疑慮要求檢視，否則不重複讀取 diff；若只有粗略意圖，則檢視核准範圍內的 diff。代理回報精簡驗證證據，遇到 sandbox 或權限失敗立即停止。可編輯路徑範圍與復原限制詳見 skill。

## 延後能力

- 目前專案以外的無人值守背景 curation 或變更；在授權工作期間，專案內改善可使用上述常駐授權。
- Eval-driven development infrastructure，直到有真實 runner、deterministic graders、baselines、重複執行 metrics 與 CI integration。
- LLM API cost routing 或 transaction-authorized agent 的領域 skills，直到 repo 採用這些 application surfaces。

## Runtime Verification

編輯後 hook 保留 Ruff `F`，排除 `F401,F841,F842`，只檢查該次事件指明的 Python 檔案。完整 lint 與排版留給 pre-commit；此 hook 不會自動 fix，也沒有擴大 lint 規則範圍。

Codex 不使用 SessionStart hook。根目錄的 `AGENTS.md` 由 Codex 原生讀取，branch 與 worktree 資訊跑一行 Git 指令即可取得，兩者都不需要注入。Hooks 使用已準備好的環境與 `uv run --no-sync`；使用前需先建立 dependencies。PostToolUse 每次 edit event 執行一次帶有 `--no-fix` 與 timeout 的 Ruff，回報 warnings 而不取代原始 tool result。

Entrypoint tests 驗證 protocol output 與真實 Ruff 執行，不驗證每個 desktop tool path 的 dispatch。將 hooks 視為 enforcement 前，必須在目標 runtime 檢查 live matcher coverage。一般 commit hooks 與 PR CI 提供自動化檢查。

[官方 model guidance](https://developers.openai.com/api/docs/guides/latest-model) 建議審查互相衝突的 skill instructions。[Hook reference](https://learn.chatgpt.com/docs/hooks) 說明 `continue: false` 會取代正常的 PostToolUse result；此處的 diagnostic-only feedback 使用 `systemMessage`。
