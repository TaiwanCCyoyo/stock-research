# Stock 研究資料架構重組

擁有者於 2026-10-08 指示依 Claude 的架構複審實施；此 task 不是新策略研究。
來源方案：`D:/Project/Stock/.tmp/claude-kline/20261010-claude-architecture-review.md`。
規格：[OpenSpec](../../openspec/changes/reorganize-stock-derived-data/design.md)。

範圍：型態版本字典、原 bytes 保存、三種明確價格基礎、ATR／均線／確認轉折、不可變快取、Stock 備份與契約同步。標註線上匯出由 Claude 負責；變體研究由獨立數據 session 負責。沒有新機率或帳戶回測、確認／holdout、下載、排程、目標恢復、網站功能或其他 worktree 刪除。

驗收先固定：合成案例正確、四版原 source hashes 相符、同日多事件不被靜默丟棄、相同快取重用、改輸入新版本、直接計算逐列一致、損壞／未完成版本拒絕、备份不刪與新目錄還原。用 v4 原 24＋1 source cases 比對 detector 搬移與新價格政策；任何差異列出，不用策略結果調整品質規則。舊結果與程式不回寫。

production 共用快取應在 `D:/Project/Stock/research_cache/`，備份在 `D:/StockResearchBackup/`；以原 atlas 已暴露窗與固定因子建立 bounded 25 檔版本，不以全市場建置為第一批前提。source code 正常 hooks 封存後才產生 canonical cache。冷 clone 有 code／契約／規則；大型資料取得限制與 hash 由 data-contract/完成收據明示。

producer SMA/EMA 與 technical_features 的刪除／遷移在 Stock 替代來源完成後另開 producer PR；先保留舊消費者輸入，通知正在使用的 session。未滿足這些依賴前不刪。
