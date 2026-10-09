# Stock PR 審核

實作 agent 負責[PR 後續處理](../en/git-workflow.md#pr-follow-through)：評估審核意見，修正並驗證範圍內成立的問題，推送修正後立即解決已處理的審核討論，再等待當前 head 的 CI 與重新審核。解決討論不保證會啟動新的審核；回報完成前須確認實際狀態。合併權仍由擁有者保留。

目標為 `TaiwanCCyoyo/Stock` 的 `main`。CI 與託管 Codex review 已生效；PR #5 已驗證。分支保護尚未啟用：目前 private repository 的 GitHub 方案不支援。

- 上游同步及後續 agent 政策審查已獲准以 `TaiwanCCyoyo` 身分發布任務分支與 PR；其他工作的交付授權見 [Git 工作契約](../en/git-workflow.md)。合併及遠端設定仍由擁有者決定。
- 本機 pre-commit 保留 mypy 與 Pyright；GitHub `repository-checks` 只略過 mypy，保留 Pyright、格式、空白、YAML、大型檔案、秘密、編碼與 Ruff 檢查。
- 只有 Markdown／reStructuredText 文件變更時跳過 Python 測試；其他變更跑共用工具與兩套 hooks 測試。這不包含根目錄 `tests/` 的完整應用測試，也不下載行情或執行研究。
- 確認託管 review 已檢視目前 head，並處理發現；其結果不等於 GitHub approval 或合併授權。
- 規則仍要求透過 PR 交付，但目前沒有 GitHub 伺服器強制阻止直接 push 或 CI 失敗時合併。

2026-09-20 證據：[PR #5 審查](https://github.com/TaiwanCCyoyo/Stock/pull/5#issuecomment-5747122478)、[main CI](https://github.com/TaiwanCCyoyo/Stock/actions/runs/35485837491)。免費方案的 private repo 可以跑 CI；強制分支保護需要支援的方案，見 [PR 設定](pr-setup.md)。
