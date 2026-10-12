# HHHL v4 variants 固定執行記錄

PR #7 已於 2026-10-12T02:39:00Z 合併到本 repository 的 main，mission merge 為 `fcda359370cd81594451839d4e79e2216cbce255`。本記錄補充執行與儲存方式，沿用 [mission](mission.md) 的所有公式、分母、窗口、bins、300／60門檻與最多16候選；不新增研究搜尋。

## 執行前固定

- 只使用原 `base_eligible=true` 且 `pattern=true` 的 P 事件；P-all 為 clean／over 聯集。A 在 P-all 保留原 over 子群，clean 部分仍不適用。C-base、C-nh、C-52w 可同日重疊，控制即使同日有 P 事件，其 pattern-only 特徵仍不適用。
- 每股每天以原 common calendar 對齊；原始股票代碼保留前導零。每日 H 與 K3 的有效群體與分界保存為 `daily-boundaries.parquet`。K3 不拆同值、不参与候選選擇。
- 所有24特徵保存值、bin、status、互斥 reason。新暖機資料不足與缺價後暖機另標；原 vx 的缺值明列 frozen 語義。unknown／not_applicable 不當零，也不參選。
- 大型資料分為 ordinal 分片 `daily/`、`features/`、`observations/`、`flags/`、`pivots/`。ordinal 依 frozen atlas security_id 排序，manifest 每片列 original code；不能把 ordinal 當股票代碼。分片不改邏輯資料鍵或公式。
- 低點保留 common-calendar extreme_index 與 confirmed_index；旗標以 confirmed_index 觀察。控制不產生型態失效旗標。
- 舊 active 越線、反向描述、新 riskset 分開報，空群體與空狀態照列。所有年度及刪除最好一年切片固定保存；控制敏感性移除與目標列相同年份。
- 固定抽查最早5及 event_id SHA排序5個不重複原事件。逐筆價格及完整人工核對輸入只保存在 primary dataset，Git 保存抽樣 ID 與內容摘要，不按成功或失敗挑案例。

## 封存與出版

合成 bundle 使用虛構價格與事件，驗證全流程而不打開市場輸入。驗證及正常 commit hooks 通過後，runner 必須從 clean commit 的新 Python interpreter 啟動，記錄 approved mission merge、code SHA、逐檔 hash、Python／NumPy／pandas／PyArrow 環境及既有 input pins。

首次正式計算前停止本 chat 的等待 heartbeat。runner 先驗全部固定輸入，還原每股 close 必須與原 v4 baseline 逐值完全一致；只呼叫凍結價格及 pivot adapter，從不呼叫事件 detector。完成後再驗輸入與程式 hash，exclusive lock 與 no-replace 出版確保既有版本不被覆寫。失敗保留 staging 與起始收據，不能用失敗結果調整規格。

逐筆版本固定為 `D:/Project/stock-research/tasks/20261012-hhhl-v4-variants/datasets/hhhl-v4-variants-01/`。完整 summary、查詢入口、schema、外部 manifest pin 及正式報告共同交付，並更新共用資產索引。描述率是事件關聯；不宣稱因果、策略效果、停損效果或獨立驗證。
