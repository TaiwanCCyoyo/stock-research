# 在下游專案啟用 PR 交付

Stock 狀態（2026-09-20）：CI 與託管 review 已生效。GitHub Free 的 private repo 可在額度內使用 Actions；private repo 的分支 ruleset 需要 Pro 等支援方案。能跑 CI 不代表伺服器會強制通過。

重設[共用 Git 工作契約](../en/git-workflow.md)為 local-only 時採用本範本，然後按照本指南有意識地啟用交付。本指南供 repository 擁有者使用。它不授予 agent 設定、發布或管理權限，複製本範本也不會設定其中任何項目。

Stock 目前的設定狀態見[PR 審核](pr-review.md)。

## 1. 選擇身分模式

**共用身分（上游採用、Stock 預計採用的方式）。** Agent session 以擁有者的 GitHub 憑證推送任務分支並建立 pull request，因此 agent 編寫的 commit 會歸屬於擁有者。用 branch 前綴與 commit 訊息區分 agent 工作，不以身分區分。

這是最簡單的選項，不需要 App、不需要私鑰、也不需要 token helper。代價是明確的：**agent 與擁有者共用同一身分，所以沒有強制的角色分離。** 有意識地接納這個限制，或不要使用此模式。

**分離身分。** 如果您的專案需要強制分離 — 例如審核者的核准必須計入 required-review rule — 則需要開發 session 無法取得的獨立身分。同帳號的兩張 token 不是兩個審核者。稽核每條 authentication route，因為 Git HTTPS/SSH、`gh` 和 agent plugin 可能各自解析為不同身分，且分開的 worktree 不會隔離憑證。

## 2. 保護預設分支

在預設分支上建立 ruleset，要求 pull request、解決所有 review conversation、以及當前 revision 的通過 status check。禁止 force push 與 branch 刪除，並且**保持 bypass 清單為空** — bypass actor 會無聲地使下面所有規則失效。

在共用身分模式下，不要要求核准的 review：單一身分無法核准自己的 pull request，因此該規則會造成僵局。Conversation resolution 加上 required check 是共用身分下較弱的替代控制，不等於獨立核准；作者仍可能自行解決討論。

在選擇必要的 check 名稱之前先加入您的 CI，保持 job 名稱穩定，並確認 check 確實在 pull request 上執行。

## 3. 連線 review

為 repository 啟用託管 review 整合 — 本範本使用 Codex GitHub 整合，針對根目錄 `AGENTS.md` review 規則檢視每個 pull request。

連線時有兩個屬性很重要：

- Review 輸出是**建議性留言，不是 GitHub approval**，且它不會合併任何東西。
- Review 發現會建立 review conversation，所以未解決的發現會透過 conversation-resolution rule 而不是 approval rule 阻擋合併。

巢狀 `AGENTS.md` 檔案以自己的目錄為範圍。Repository 層級的 review 規則應放在根檔案。

## 4. 記錄並驗證

1. 在 `git-workflow.md` 的 current-state 項目記錄已核准的 repository、base branch 和發布身分，然後在該處啟用常設 PR 交付。不要記錄憑證。
2. 調整 agent 的執行時期權限以符合該範圍。修改文字不會移除執行時期確認提示。
3. 推送一個可丟棄的 branch 並建立小 pull request。驗證 CI 執行、review 發布，以及當 conversation 未解決或 check 失敗時拒絕合併。
4. 驗證對預設分支的直接 push 被拒絕。使用 test repository 或擁有者核准的探測；設定不當的正式 rule 可能會接受嘗試的寫入。

記錄證據和任何剩餘的缺口後再依賴此邊界。

## 5. 保持合併權限明確

合併是擁有者的決定，除非您有意委派。如果您自動化合併，使自動化重新檢查當前 head 而不是信任較早的結果：對 commit `ABC` 的 review 對 commit `DEF` 沒有說明作用。將缺少 review 發現視為「尚未審核」直到 review 被確認已完成當前 head。

絕不使用 admin 權限、force push 或削弱的 ruleset 進行合併。

## References

- [GitHub rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [Automatically merging a pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request)
- [Codex GitHub review integration](https://learn.chatgpt.com/docs/third-party/github)
