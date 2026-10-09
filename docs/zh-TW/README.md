[English Version](../../README.md)

# Stock Research Copilot

2026-10-08 的資料分工：submodule 負責下載、日 K 轉換、來源正規化與來源備份；Stock 負責研究價格、指標、型態、自己的不可變快取及研究資料備份。worktree 用明確絕對路徑唯讀共用快取，不複製、不連結；每日變動的原始行情仍保留實體快照。入口為[衍生資料契約](../en/research-derived-data.md)與[型態定義字典](../en/pattern-definitions.md)。舊均線欄位先保留歷史相容，不能默默替换舊實驗定義。

這是台股策略研究專案，以有資料證據的對話報告為主要介面；既有 dashboard 保留為 K 線與逐筆交易的選用檢視工具，暫停一般功能擴充。完整研究流程見[英文主文件](../../README.md)。

[研究基礎設施契約](../en/research-foundation.md) 說明共用帳本與指標、無畫面的結果目錄、期間曝光／更正登記，以及有身分驗證的單次執行與續用。這些工具不代表策略已通過。每次接續先讀[研究總覽與交接入口](../en/research-program.md)：查過的方法、待驗證假設、舊實驗位置及下一步都由此進入；已驗證且未改變的基礎能力可重用，不必因換 session 全面重建。

設計實驗時優先考慮專案可讀性、可維護性與跨策略重用。[研究產物管理規範](../en/research-program.md#reusable-research-artifacts) 要求先查既有資產，並為有後續價值的產物登記用途、欄位語意、涵蓋範圍、來源版本、取得／重算入口及使用關係；收尾須讓下一個 session 能找到、取得並理解資料，未完成的保存或說明缺口須明列。

擁有者授權代理在有具體研究效益時主動改善 `shioaji_stock_prices` 的資料結構、索引與衍生產物，讓資料好找、好懂、好重用，不因它是子模組而迴避修改。程式在獨立 worktree 開發，維持既有資料、讀取相容性、備份／還原及排程更新功能。依[子模組開發與交付流程](../en/stock-agent-operations.md#submodule-development-and-delivery)，由擁有者合併子模組 PR 後，安全更新其主要 checkout 的 `main`，再更新 Stock gitlink 並交付另一份 PR；主要 checkout 的分支不作實驗用途。下載前先查共用資料，獲授權的下載／更新使用[主要資料位置](../en/stock-agent-operations.md#canonical-data-updates)，留下其他 session 可查到的紀錄，避免資料只留在 `.tmp/` 或 worktree 造成重工；既有 worktree 快照不會自動同步。

## Agent 工作流程與 GitHub

共用規則以根目錄 `AGENTS.md` 為準。Codex 原生載入根目錄規則；Claude Code 請使用 2.1.281 以上版本並啟用內建 `agents-md` 支援，在沒有專案或祖先 `CLAUDE.md`／`CLAUDE.local.md` 優先覆寫時原生載入 `AGENTS.md`。本 repo 不提供 `CLAUDE.md` import 或注入 hook；進行 Claude 本機 review 前，請在 `/context` 或 `/memory` 確認根目錄 `AGENTS.md` 已載入，若原生載入不可用或遭覆寫，請先明確讀取根目錄契約。詳見[官方指令載入文件](https://code.claude.com/docs/en/memory#agentsmd)。兩者保留修改 Python 後的唯讀 PostToolUse 診斷，pre-commit 負責格式、lint、型別與 secrets checks。Antigravity 配置已隨上游移除。

研究仍以對話報告為主、dashboard 為選用工具；使用[英文 README](../../README.md)的現行研究入口，以及 `research-owner-contract.md`、`research-foundation.md` 的授權與證據界線。

根目錄 `AGENTS.md` 除了授權與專案慣例，也負責溝通偏好：簡單答案使用精簡文字；關係型資訊使用表格、圖解或並排比較；篩選、參數調整或證據深入檢視有助決策時，再使用互動 HTML。結論、風險、不確定性與驗證摘要保持可見，細節按需提供。遵循使用者指定格式，長期文件維持既有 Markdown 或程式碼格式；若呈現物承載使用者的決定或編輯，提供複製或匯出回對話／正式檔案的途徑。這些偏好適用於任務說明與交付物，code-review findings 仍遵循審查契約。

所有變更在非預設分支完成，透過 PR 進入 `main`，不得直接 commit 或 push 到 `main`。本次同步及後續政策審查獲准建立 PR；CI 與自動 review 已生效，分支保護受目前 private repository 方案限制。

擁有者已授權 Stock [合併後自動清理](../en/git-workflow.md#post-merge-cleanup)：確認自己的任務 PR 已合併到 `main` 後，該 session 更新本機 `main`，並移除自己建立的任務 worktree、本機及對應 `origin` 分支，不必再次詢問。清理須保留研究產物與共用資料，維持既有子模組交付授權及生產更新條件，排程操作仍需另行授權。

- [Git 工作契約](../en/git-workflow.md)：分支、交付及合併權限。
- [PR 設定](pr-setup.md)：CI、託管 review 與 main 保護設定。
- [PR 審核狀態](pr-review.md)：哪些已完成、哪些仍待啟用。
- [Codex 元件](codex-components.md)與 [Claude 元件](claude-components.md)：skills、角色與 hooks。

`repository-checks` 在 Windows 對變更檔案執行 pre-commit 並跑共用工具測試，不需私有行情。Claude 不再另設 git push 的 ask／deny 規則；交付範圍由 Git 工作契約決定，GitHub 伺服器目前尚未保護 main。

## 設計來源

本 starter kit 的架構設計受到一個開源專案的啟發：

- **[Everything Claude Code (ECC)](https://github.com/affaan-m/ECC)** — 提供生產就緒的 agents、skills、hooks、commands 與 rules。專職 reviewer roles（例如 `code-reviewer`、`tdd-guide`、`security-reviewer`）已退役，僅作為歷史來源記錄；目前 review 由 main session 的原生判斷與 hosted PR review 負責。程式碼規範，以及 `AGENTS.md` 中的共用安全契約，均移植或改編自 ECC v2.0.0-rc.1。大多數開發用 slash commands 已陸續退役，改以 Native Plan Mode 與 autoloaded project skills 取代。

## 初始化

純研究與 CLI／MCP 查詢使用 `uv sync --locked --no-dev`；開發使用 `uv sync --locked --group dev`。
K 線 viewer 由啟動器選用 `--group viewer`，舊 Panel 靜態匯出使用 `--group static-report`，一般研究不需安裝它們。
提交 hook 與 CI 會安裝選用群組以檢查型別和相容性。

瀏覽器啟動回測與背景工作管理已退役；K 線、交易明細及 viewer 關閉功能保留。
Docker 保留為選項，但既有掛載缺少必要模組且可寫範圍偏大，尚不能當成已驗證保障；修復前不執行，亦不列為研究前提。
資料、歷史結果與 `.tmp/backtest_jobs` 不搬移、不刪除。完整入口與限制見[英文主文件](../../README.md)。

設定 `git config core.hooksPath .githooks` 可啟用既有工作樹初始化 hook 與提交檢查。

文件採最清楚的語言；commit 訊息與程式識別字維持英文，檔案儲存為 UTF-8 without BOM。
