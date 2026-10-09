# 移除前盤點，不是刪除清單

2026-10-08 只讀；沒有 prune、刪除、改其他分支。工作區用途由名稱推論，PR 交付／合併與唯一 ignored 資料仍須逐項確認。dirty=0 不表示可刪；squash merge 不可只靠祖先關係判定已交付。

## Producer 消費者

目前架構 branch 的 tracked Python production／formal-task 搜尋，未找到讀 producer 已存 SMA／EMA 或 technical_features 的 consumer。這不涵蓋其他 worktree／未追蹤／外部程式。

複審指名的 `tasks/20260816-kline-strategy-category-fit/candidates/tw_momentum_breakout.py` 在目前 main：on_bar 只取 OHLCV，moving_averages_stacked 從 history 自算 simple_average。說明提 SMA 不等於讀預存欄位；atlas／legacy 元件也自算。本次不改舊程式、報告或價格快照。

producer 仍有 convert_stock_price.py 的 rounded 四組 SMA／EMA、build_price_parquet.py 合併後重算及 shp_utils/technical_components.py 的 opt-in unrounded cache。刪欄前必須：

1. 檢查其他 active worktree／外部 consumer 並通知現用 session；本次未取得通知回執。
2. 保存舊 parquet／日 CSV／technical_features 所需輸入、版本與備份；本次 Stock 備份不涵蓋 producer 全資料。
3. 檢查 producer 命令／tests／backup，隔離 producer PR 交付；不能只從 Stock 搜不到就刪。
4. owner merge 後协调 writer／scheduler，以新版產物部署，不原地刪舊欄或覆寫歷史；再發 Stock gitlink PR。

## 46 個 Git 登記工作區

dirty 是 tracked status 數；日價只查實體 price_daily.parquet 存在，未比對內容。掃描時 primary 有 4 個 formal datasets 目錄，其他區沒有該層目錄。其他 .tmp、run、非 datasets 資料及其總量未全面檢查，**唯一資料全部未知**。本架構 dirty=2 是演練腳本的當時狀態，不是他人改動。

| 工作區                                    | 用途推論／狀態                 | dirty | 日價 |
| ----------------------------------------- | ------------------------------ | ----: | ---- |
| D:/Project/Stock                          | primary                        |     1 | 有   |
| C:4229/Stock                              | v4 變體研究                    |     0 | 無   |
| C:5472/Stock                              | 本架構 task                    |     2 | 無   |
| C:83b2/Stock                              | detached 檢查點                |     0 | 無   |
| C:8e3d/Stock                              | prunable，非有效 Git checkout  |  未知 | 無   |
| authorize-post-merge-cleanup-20261005     | 工作流程檢查點                 |     0 | 有   |
| claude-workspace                          | 保留工作區                     |     0 | 有   |
| codex-workspace                           | 舊研究／gitlink 保存區         |     0 | 有   |
| hhhl-pattern-probability-20261009         | v1 原研究                      |     0 | 有   |
| hhhl-v4-probability-20261010              | PR33 原研究，另一 session 活躍 |     2 | 有   |
| pr18-aggregation-2b0e023                  | PR18 檢查點                    |     0 | 無   |
| pr18-branch-sync-20261004-1015            | PR18 同步                      |     0 | 有   |
| pr18-builder-b36cae1                      | PR18 檢查點                    |     0 | 無   |
| pr18-calendar-bd912bb                     | PR18 檢查點                    |     0 | 無   |
| pr18-export-e86d94b                       | PR18 檢查點                    |     0 | 無   |
| pr18-frontend-219862b                     | PR18 檢查點                    |     0 | 無   |
| pr18-identity-ce06f85                     | PR18 檢查點                    |     0 | 無   |
| pr18-independent-ef0eec9                  | PR18 檢查點                    |     0 | 無   |
| pr18-independent-f8c4467                  | PR18 檢查點                    |     0 | 無   |
| pr18-main-sync-frontend-20261004          | PR18 同步                      |     0 | 無   |
| pr18-peakgain-ac9b29c                     | PR18 檢查點                    |     0 | 無   |
| pr18-portable-1023525                     | PR18 檢查點                    |     0 | 無   |
| pr18-publication-01e6fae                  | PR18 檢查點                    |     0 | 無   |
| pr18-restore-433706c                      | PR18 檢查點                    |     0 | 無   |
| pr18-shared-label-96ba600                 | PR18 檢查點                    |     0 | 無   |
| pr18-synced-7394557                       | PR18 檢查點                    |     0 | 無   |
| pr18-temporal-0e2d039                     | PR18 檢查點                    |     0 | 無   |
| pr18-unknown-49873e3                      | PR18 檢查點                    |     0 | 無   |
| pr21-build-verify-fixed-probe-20261004    | PR21 檢查點                    |     0 | 無   |
| pr21-build-verify-probe-20261004          | PR21 檢查點                    |     0 | 無   |
| pr21-sqlite-boundary-probe-20261004       | PR21 檢查點                    |     0 | 無   |
| price-history-origin-audit                | 價格來源調查                   |     0 | 有   |
| research-artifact-discovery-20261004      | 產物管理                       |     0 | 有   |
| research-handoff-delivery-20261005        | 研究交接                       |     3 | 有   |
| research-workspace-20261003               | 方法交互研究                   |     1 | 有   |
| sector-classification-eight-case-20261004 | 產業分類                       |     0 | 有   |
| sector-role-evidence                      | 產業角色                       |     1 | 有   |
| sector-wave-catalog                       | 族群 catalog                   |     0 | 有   |
| sector-wave-full-history-preview-20261004 | full-history preview           |     3 | 有   |
| sector-wave-web-contract-20261004         | 展示契約                       |     0 | 有   |
| slim-research-tooling                     | 工具瘦身檢查點                 |     0 | 無   |
| strategy-presentation                     | 展示工作                       |     0 | 有   |
| sync-agent-starter-kit-20261003           | upstream 同步                  |     0 | 有   |
| sync-starter-kit-cleanup-20261005         | cleanup 工作流程               |     0 | 有   |
| sync-starter-kit-communication-20261003   | 溝通流程                       |     0 | 有   |
| update-price-submodule-20261003           | gitlink 更新                   |     0 | 有   |

D 名稱相對 D:/Project/Stock/.worktrees/，C 名稱相對 C:/Users/xjp01/.codex/worktrees/。下一輪補各 PR 狀態、untracked／ignored 尺寸與唯一資料保存位置，再由擁有者逐項決定；本表不提供刪除保證。
