# 互動討論介面

先讓使用者看懂正在決定什麼，再讓他操作選項、看差別，最後保留選擇與理由。
GitHub 的確認紀錄與互動頁互補；不以大量文字取代本來可以操作理解的討論。
簡單問題仍直接對話，不要求每次做大型頁面。

## 現在可以用什麼

[直接開啟示例](../../research_web/discussion-kit/v1/index.html)：不用 build 或市場資料。
切換「成立／不成立／分不出來」，比較「只看錯殺比例」與「再比較報酬、回撤」會改變的研究承諾，
展開前作問題，填入選擇與備註，再整理成可貼回對話／PR 的文字或下載 JSON。
這是教學示例，沒有連到實際研究草稿，全部數字保持佔位；不宣稱已算出結果。

共用程式位於 `research_web/discussion-kit/v1/`，`discussion.js` 與 `discussion.css`
負責互動與呈現，`index.html` 是可操作的 authoring 範例。來源契約與回饋契約定義在本頁。
獨立頁與未來 dashboard 使用同一份 model 與 renderer，不維護兩套問題或批准狀態。

## 作者如何準備一次討論

1. 先寫正式 `direction-draft.md`，在 ③ 記錄要幫使用者理解的差別：操作什麼、看見什麼、回填哪個 C／Q。
   互動有資訊價值時直接提供；若只需一句回答，簡短說明即可。
2. 依示例準備 presentation model。正式 view 的原話、三分支假頭條與選項必須逐項對照草稿；
   記錄 task、草稿相對路徑與確切 Git revision。相同 C／Q 保持相同 ID。
   畫面可增加白話解釋與選項影響，不能擅自改變研究承諾或捏造擁有者原話。
3. 在新的研究 `preview/` 使用共用 renderer，或由開發環境載入同一版本資源。
   不改已凍結草稿，不覆寫既有 report-kit，不把 preview 塞入正式 web-report discovery。
   當前沒有 Markdown→model 自動產生器；作者與 reviewer 必須人工核對來源一致性。
4. 對使用者給一個具體操作邀請，例如「切換這兩個研究範圍，看看哪個真正回答你的停損問題」。
   同時保留目的總覽、未完成項目與可展開細節。不能只交一個網址要求自行摸索。
5. 在桌機、窄視窗與鍵盤操作下核對情境切換、選項影響、備註、匯出，以及來源/草稿狀態可見。
   確認匯出資料沒有遺失未選項與版本。簡單文字 fallback 及原始草稿始終可取得。
6. 收到匯出後核對 `source` 三欄與目前草稿。舊版回饋保留為提議，逐項對照變更，不自動套用。
   回填 C、⑪ 分岔與⑫問題、顯示差異，再走正式 owner 確認；不把互動偏好當作同意計算。

## Presentation model：direction-discussion.v1

此 model 是顯示用資料，不是另一份正式方向紀錄或 strategy schema。必填欄位：

| 欄位                                     | 定義                                                                                            |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `schema`                                 | `direction-discussion.v1`                                                                       |
| `demo`                                   | 是否為示例；示例顯著標示，不能用於正式批准                                                      |
| `source.taskId`, `draftPath`, `revision` | 研究 ID、來源草稿路徑、對應版本；正式 view 使用 Git commit，示例用明確 demo 版本                |
| `ownerPurpose`, `purposeStatus`          | 草稿目的文字與 `pending`／`confirmed`；confirmed 僅展示已有紀錄，renderer 不產生批准            |
| `outcomes`                               | 三個 `{id,title,headline,decision,limitation}`；ID 為 `supports`、`does-not-support`、`unclear` |
| `choices`                                | `{id,question,options}`，穩定 C ID；每個 option 為 `{id,label,impact}`，說明選了會改變什麼      |
| `questions`                              | `{reference,question,status,reason,source}`；完整 `task-id#Qn`、狀態、卡點與來源說明            |

`DirectionDiscussion.validateModel(model)` 檢查結構與 ID；正式 model 要求完整 40 位 Git commit，
拒絕 `main` 等會變動的別名。百分比只能寫成 `▢▢%`（或全形百分號），不能換成中文數字規避。
這仍無法驗證文字是否忠於來源，或任意自然語言是否暗藏結果，需 reviewer 核對。
`DirectionDiscussion.mount(element, model)` 建立同一套 view，回傳 `destroy()` 與
`exportFeedback()`。容器卸載、切換研究或草稿版本時先 destroy 再 mount，新實例不恢復舊選擇。
資料以 DOM textContent 呈現；不把內容當 HTML 執行。此版不使用 localStorage、遠端服務或市場 API。

示例用 `application/json` 嵌入 model，再讀取其 textContent。作者嵌入 JSON 時須將 `<` 編碼為
`\u003c`，避免資料內的 `</script>` 提前結束元素；不要直接串接任意來源文字成 HTML。
外部資料接入時由 adapter 載入物件再 mount，不讓 renderer 讀檔或存取工作樹。

## Proposed feedback：direction-feedback.v1

匯出保留來源、每個選項（未選為 `null`）與多行備註，狀態始終是 `proposed`。
情境切換只是探索，不會被記成偏好的研究結果。Markdown 是便於溝通的副本，JSON 保留結構化識別。
回饋不得直接寫入 `owner_purpose_confirmed`、`fake_headline_approved` 或 `stage`。

使用者主動複製／下載後再送回對話或 PR。此版不自動外送、不自動保存、不直接改檔，也不啟動計算。
重新載入或切換版本會清除未匯出的選擇，頁面需明示這項限制。

## 後續 dashboard 接點

Dashboard 的後續切片應新增草稿專用 discovery／route，再將已核對 model 交給同一 renderer，
或承載同一 standalone page。保持正式 report discovery 只讀已交付報告，不能靠假 study-card 欄位混入草稿。
`study-card.v2` 和 report-kit v1 都不需要加欄位。

目前 `ReportViewer` 的 iframe 契約只有來源 frame 的 `rk:height` 與發送 `rk:theme`；
本分支沒有 `rk:navigate` handler，也尚無 discussion route。未來 adapter 若增加高度、主題或導航，
須實作來源與訊息驗證及解除 listener，不能只在文件宣稱已有支援。
此版 mount／destroy 與 feedback 契約是已交付接點；dashboard 註冊和完整 iframe adapter 是後續工作。

來源規則見 [direction drafts](direction-drafts.md)；本次需求見 [決策紀錄](decision-records/2026-11-02-interactive-direction-discussion.md)。
