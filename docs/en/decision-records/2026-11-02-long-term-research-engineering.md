# 長期研究工程接續與 UX 依賴對齊

日期：2026-11-02。狀態：有限工程範圍已授權；兩條工作線共同交付於
[draft PR #146](https://github.com/TaiwanCCyoyo/stock-research/pull/146)，尚未合併。
本紀錄追加當日範圍與依賴，不改寫歷史 mission、決策、結果或其接受狀態。

本機驗證：新整合器、既有 E1 三層與 CI selector 共 **672 passed in 87.50s**；
沿用既有日期 helper 解決型別相容問題後，新整合 suite 再驗 **39 passed in 3.25s**。
實作提交 `170799376feebb5d02cd42f947858571040300da` 的正常 hooks 全過，含 Mypy、Pyright、Ruff。
三個 SOL 子代理分別負責程式、合成測試與依賴文件；Terra 獨立審查八檔及最後增量，無可操作 findings。
以上是本機證據；hosted CI 與 review 以 PR 最新 HEAD 為準，不代表本人接受或市場 admission。

## Owner 意圖與本次範圍

以下是 owner 中文意圖的摘要，並非逐字引文：接續長期研究中可獨立推進的工程，整理與新版 UX、
報告閱讀及討論流程的依賴；互動介面要幫助理解與溝通，不能只剩文字。這個要求支持本次有限工程
與依賴對齊，不新增研究方法、結果門檻、資料取得、市場運算或產品部署授權。

| 工作線                   | 本次交付                                                                                                                              | 權威來源與界線                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A：E1 純記憶體整合       | 將已載入且宣告身份的 packets 經既有 staging、stock counts、整數聚合及 paired bootstrap 串成可測的單一路徑；交付合成驗證及整合 handoff | [mission](../../../tasks/20261027-entry-window/mission.md)、[資料契約](../../../tasks/20261027-entry-window/data-contract.md)、[B1 handoff](../../../tasks/20261027-entry-window/implementation-handoff.md)、[staging handoff](../../../tasks/20261027-entry-window/reader-staging-handoff.md)、[bootstrap handoff](../../../tasks/20261027-entry-window/bootstrap-handoff.md)；新[整合 handoff](../../../tasks/20261027-entry-window/assembly-handoff.md)記實際 API 與驗證 |
| B：長期研究／UX 依賴對齊 | roadmap 追加日期段落、研究總覽同步入口與本紀錄，清楚標出已完成工程、pending contract 與本人接受                                       | [roadmap 新補充](../research-roadmap.md#9-2026-11-02-補充工程接續與閱讀依賴)、[研究總覽](../research-program.md)；沿用既有 UX 與討論負責 session，不建立競爭介面                                                                                                                                                                                                                                                                                                            |

同一 draft PR 讓讀者能一起審查工程界線、可重用資產入口與後續依賴。它不交付市場研究報告，
不改研究卡片 verdict、既有來源 pins、收據或 frozen evidence。主 session 統一處理 Git index、
commit、PR 與後續驗證；各檔案維持唯一 writer。

## E1 的方法與資料邊界

整合只消費顯式記憶體輸入，重用既有公開 API。原訊號、母體、共同日曆、固定 t+1、六帶、
原 labels、Q／M 與整數守恆均由既有契約決定；配對重抽樣沿用既有定義，不另挑方法或比較門檻。
staging 對來源、generation／as-of 及日曆的宣告一致性驗證，不等於真實來源認證或完整歷史 PIT。

真實 canonical loading、事件整段覆蓋、報價品質、官方 bounds、原 label admission、PR61 相容性及
資料／資源／單次計算 admission 仍是另外的 reader／runner 工作包。`source_unavailable` 與
`adapter_pending` 不得以空事件、單位因子、補值或改日曆消除。沒有真實市場讀取、下載、世代更新／hold、
scratch research run、排程或部署。本次 E1 原訊號不含 S1／S2／S7，S7 未完成不阻止這個純記憶體工程包。

## UX 與討論契約的依賴

2026-11-02 交接狀態：#139–141 的 UI 已合併；#142、#143–145 的 reading/readiness 與閱讀版本待本人接受。
以下以未合併工作的 branch 文件及 PR 作為接口，不假設它們已存在於 main：

| 接口                                                                                                                                   | 目前邊界                                                                                                      | 後續處理                                                                                                                                                                                                                       |
| -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [#142 reading contract](https://github.com/TaiwanCCyoyo/stock-research/blob/codex/report-reading-readiness/docs/en/report-reading.md)  | `ready` 是編輯核對；與研究 verdict、本人接受分開                                                              | [P5–P7／#145、#143、#144](https://github.com/TaiwanCCyoyo/stock-research/blob/codex/report-reading-readiness/docs/en/decision-records/2026-11-02-dashboard-ux-and-report-readability.md)依賴 #142；維持本人最終閱讀／接受 hold |
| [#137 direction draft](https://github.com/TaiwanCCyoyo/stock-research/blob/claude/direction-draft-process/docs/en/direction-drafts.md) | 原 active session 正在處理互動理解與溝通的架構，接口仍 pending；D1–D6 只有 agent 敘述，尚未獨立取得使用者原文 | 本次只保留接口；GitHub 可記錄確認，純文字 PR 不是唯一討論介面。方向確認不能替代 mission／運算授權，流程合併也不能代替本人證據                                                                                                  |
| [#113 報告](https://github.com/TaiwanCCyoyo/stock-research/pull/113)                                                                   | 呈現與本人接受仍由既有負責 session 處理，#128 先合併條件保留                                                  | 不擴成全專案工程阻擋；E2／E3 新市場研究保留各自依賴及 gates，不由本次工程推進解鎖                                                                                                                                              |

上述是本次主 session 的狀態交接，不是重新驗收服務、報告、正式資料或本人確認證據。
當相關 PR 或 pending contract 改變，後續工作應讀其最新已核實版本；本紀錄不修改他人分支。

## Gates 與接受條件

| Gate       | 本次完成能證明什麼                                     | 仍不能據此推論                                              |
| ---------- | ------------------------------------------------------ | ----------------------------------------------------------- |
| 方法／方向 | 工程重用既有 E1 定義；討論接口及未定問題可找到         | #137 的 D1–D6 已獲本人確認、新研究方向或門檻獲准            |
| 資料       | 合成 packets 的身份、日曆、來源宣告與既有契約相容      | 正式來源可用、完整歷史 PIT、真實事件覆蓋或 labels 獲准      |
| 運算       | 純記憶體路徑與配對整數聚合／bootstrap 通過相稱合成驗證 | 市場 run、資源 admission、延長 cutoff 或重開 holdout 獲准   |
| 報告閱讀   | reading 契約與 P5–P7 依賴有明確入口                    | `ready` 表示策略有效或本人接受                              |
| 本人接受   | 尚無本次研究結果或報告接受事件                         | CI、review、程式合併代替 owner 接受，或解除 #113／#128 條件 |
| 產品使用   | 本次只交工程與文件                                     | 部署、排程恢復、前瞻起算、紙上操作或實盤獲准                |

本次工程接受須能由整合 handoff 找到實際 API、輸入身份與假設、相稱合成驗證及未解事項；
合成輸入應可對照既有分開呼叫路徑，確認計數／配對一致與拒絕不相容輸入。重用既有通過證據，
由正常 hooks／CI 執行適用檢查，不為文件對齊跑市場資料或重算已發表結果。
文件交付須連結可解析，清楚區分歷史快照、當日交接與未接受事項；資產與契約由研究總覽可發現。
實際驗證結果與 PR 連結在完成後追加，未執行的檢查不能寫成通過。

## 保留的 S7／O2 缺口

S7 的[計數交接](../../../tasks/20261027-multi-timeframe-ma/counts-handoff.md)及
[週曆交接](../../../tasks/20261027-multi-timeframe-ma/week-calendar-handoff.md)仍未定首次確認、延遲確認、
多週同日確認與空週接續。後續先以合成案例表明可得時間、首次確認事件及前後週狀態；
本次不寫 assembler，不選真實 calendar reader，也不產生 D／W 歷史序列或研究結果。
universal scale-invariance acceptance 仍為 **UNSATISFIED**，既有 bounded engineering disposition
不代表修復、豁免或量化市場影響。

O2 的 finite G／receipt event 限制保留；內容發布、receipt 可讀與 cohort 生效不能混稱同一事件。
[發布契約分支](https://github.com/TaiwanCCyoyo/stock-research/blob/codex/forward-publication-contract/tasks/20261027-forward-publication-deadline/data-contract.md)
及[既有恢復交接](../../../tasks/20261027-forward-attempt-recovery/codex-handoff.md)的缺口、部署 gate 與
首個未來準時日確認仍由原負責工作處理。本次不改變 G 的有限邊界或重新核實 production 狀態。
