# Codex 元件參考

Codex 使用 Native Plan Mode、原生 local memories、repo-scoped skills、專用 subagents、project hooks 與已安裝 plugins。它讀取共用的根目錄 `AGENTS.md`，這是 Codex 原生會尋找的檔案；repository 層級的規則放在該檔，巢狀 `AGENTS.md` 只涵蓋自己所在的目錄。

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

## Agents

| Agent               | 權限     | 用途                                                                                                                                          |
| :------------------ | :------- | :-------------------------------------------------------------------------------------------------------------------------------------------- |
| `signal_miner`      | 唯讀     | 低成本的大量輸出隔離工具；委派有具體收益時使用，只回傳精簡證據                                                                                |
| `task_worker`       | 有界寫入 | 執行已有明確範圍、驗收條件與驗證方式的低至中風險修改；當範圍或風險擴大時停止並回報                                                            |
| `doc_translator`    | 有界寫入 | 低階文件翻譯與同步者：將任何需寫入檔案的翻譯處理到單一明確的非 canonical 目標；main agent 決定來源與目標，衝突時以其維護的 canonical 文件為準 |
| `commit-specialist` | 有界寫入 | 選用的 commit 代理；依 mode 審查 staged diff、執行 commit，sandbox 失敗時交還 main agent                                                      |
| `researcher`        | 有界寫入 | 在隔離 worktree 中執行由 parent 登記的 Stock 實驗；不得改變方向、下載資料或調整 gates                                                         |

### 模型路由

| 層級           | 模型                   | 角色                                                           |
| -------------- | ---------------------- | -------------------------------------------------------------- |
| 有界實作       | `gpt-6.1-sol` / medium | 由 `task_worker` 執行明確限定範圍的一般實作                    |
| 高流量機械工作 | `gpt-6-luna` / medium  | Signal mining 與 commit                                        |
| 翻譯           | `gpt-6-luna` / low     | 單一明確的非 canonical 文件                                    |
| 已登記研究執行 | `gpt-5.6-luna` / max   | 透過 `researcher` 執行固定命令、deterministic gates 與指標擷取 |

一般程式碼定位使用 `explorer`；需要隔離大量輸出、能節省 context 時使用 `signal_miner`。短檢查直接在本地執行；沒有具體收益時避免同層級 handoff。`task_worker` 讓高階 main agent 將有界實作降級給 Sol，而 Luna 處理機械式工作。模糊、架構與 security-sensitive 的判斷應留給 main agent；pull request 也會經過 hosted Codex review。

四個共用角色、內建 `explorer` 與 Stock `researcher` 已涵蓋目前的持續工作。只有在證明存在缺口時才新增角色。主要模型仍由使用者選擇；角色的模型預設不代表已量測的成本節省或品質。除非實際 workload 證明需要，否則維持既有的並行數與深度預設。

主 agent 擁有研究方向、owner constraints 與最終驗收權；`researcher` 保留既有模型與有界的預先登記執行方式，共用 helper 的更新不會改變其授權。維持研究 enforcement 與 point-in-time validation。委派時提供明確路徑、命令、停止條件與精簡 context；重用已通過的證據與既有 agents。若 helper 遇到 usage limit，主 agent 在安全範圍內完成工作並回報剩餘依賴。模型或設定變更只套用到新載入的 agents；已在執行中的 helper 可能保留較早設定。

## Skills

| Skill                | 用途                                                                         |
| :------------------- | :--------------------------------------------------------------------------- |
| `python-development` | Python logging 與以 log 輔助除錯                                             |
| `python-testing`     | Targeted behavioral tests、選配 coverage、hook fixtures 與 Windows path 要求 |
| `gen-commit`         | 有界 local commit、選用 specialist review 與執行、sandbox handoff 及回報     |

## Claude 能力取捨

| Claude 能力                                                     | Codex 決策               | 原因                                                                                                                                                           |
| :-------------------------------------------------------------- | :----------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/plan`                                                         | 原生／選用 artifact 取代 | 對話式規劃由原生 Plan Mode 提供。持久化的跨 session handoff 使用受維護的 plan artifact。                                                                       |
| `plan-reviewer`、`implementation-reviewer`、`security-reviewer` | 2026-10-02 移除          | Native Plan Mode、目前模型能力、hosted Codex PR review 與 pre-commit gates 已涵蓋其責任；其餘 agents 的存在是為了節省成本。                                    |
| `/feature-dev`                                                  | 原生取代                 | Brainstorming、Plan Mode、test-first development、verification 與 review 已構成完整流程。                                                                      |
| `/build-fix`                                                    | 原生取代                 | Evidence-driven debugging 加 repository verification 已涵蓋逐步診斷與修復。                                                                                    |
| `/code-review`                                                  | 原生／plugin 取代        | Local review 使用原生 Codex review stance；PR review 使用 GitHub plugin。                                                                                      |
| `/python-review`                                                | Skill 取代               | `python-testing` 提供 repository-specific behavioral tests 與選配 coverage 指引。                                                                              |
| `/security-scan`                                                | Agent 與 gates 取代      | 已安裝 detect-secrets、hooks、pre-commit 與 hosted PR review；未安裝 AgentShield。                                                                             |
| `/test-coverage`                                                | Skill 取代               | 選配 coverage 已在 `python-testing`；Codex 不需要 command wrapper。                                                                                            |
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
| Risk-based test scope                                             | `AGENTS.md` verification section                        |
| Python development rules                                          | `python-development`                                    |
| Repository Python verification                                    | `python-testing`                                        |
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

`gen-commit` 在需要實質審查、訊息粗略或缺漏，以及明確要求獨立檢查時使用 `commit-specialist`。主 agent 可在變更小、已驗證且訊息完整時直接提交，並確保沒有暫存無關檔案；使用相同驗證與有界 hook recovery。委派遇到 sandbox 或 cache 權限問題時回報確切錯誤，由主代理依既有授權處理。

是否檢查 diff 由明確 mode 決定，不會自動發生。沒有訊息或只有粗略目標時，specialist 會讀 staged diff 並完成訊息；若 main agent 對乾淨且明確的 scope 已提供完整訊息，specialist 不讀 diff，重點是 commit 執行與有界 hook recovery。只有 main agent 因具體疑慮明確要求 double-check 時，完整訊息才會搭配額外 diff 檢查；specialist 不得自行升級到該 review mode。

## 延後能力

- 目前專案以外的無人值守背景 curation 或變更；在授權工作期間，專案內改善可使用上述常駐授權。
- Eval-driven development infrastructure，直到有真實 runner、deterministic graders、baselines、重複執行 metrics 與 CI integration。
- LLM API cost routing 或 transaction-authorized agent 的領域 skills，直到 repo 採用這些 application surfaces。

## Runtime Verification

編輯後 hook 保留 Ruff `F`，排除 `F401,F841,F842`，只檢查該次事件指明的 Python 檔案。完整 lint 與排版留給 pre-commit；此 hook 不會自動 fix，也沒有擴大 lint 規則範圍。

Codex 不使用 SessionStart hook。根目錄的 `AGENTS.md` 由 Codex 原生讀取，branch 與 worktree 資訊跑一行 Git 指令即可取得，兩者都不需要注入。Hooks 使用已準備好的環境與 `uv run --no-sync`；使用前需先建立 dependencies。PostToolUse 每次 edit event 執行一次帶有 `--no-fix` 與 timeout 的 Ruff，回報 warnings 而不取代原始 tool result。

Entrypoint tests 驗證 protocol output 與真實 Ruff 執行，不驗證每個 desktop tool path 的 dispatch。將 hooks 視為 enforcement 前，必須在目標 runtime 檢查 live matcher coverage。一般 commit hooks 與 PR CI 提供自動化檢查。

[官方 model guidance](https://developers.openai.com/api/docs/guides/latest-model) 建議審查互相衝突的 skill instructions。[Hook reference](https://learn.chatgpt.com/docs/hooks) 說明 `continue: false` 會取代正常的 PostToolUse result；此處的 diagnostic-only feedback 使用 `systemMessage`。
