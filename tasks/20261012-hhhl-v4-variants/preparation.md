# 準備收據

PR #6 已合併，mission PR 尚待 owner merge。本階段只做輸入身分驗證與合成測試，沒有新的市場特徵、控制、label、選擇或達標率結果。

- primary最新main：`493fa49d738e00e5c59bd118192669c86065adf4`；盤點時只有primary，tracked/untracked clean；本session建立一個task worktree，沒有初始化producer、複製mutable inputs或建立links。
- 既有 `uv run python -m scripts.verify_published_artifacts --only atlas-v2 hhhl-v4`：四個檢查pass（公開v4、完整v4封裝、diagnostics/landmark audit、atlas-v2）。
- bulk全artifact、factor bundle內外、source registry／原task source與common-calendar Date projection另驗；身分與scope見 [input pins](params/input-pins-v1.json)。沒有使用未來label選條件。
- 共用定義／候選選擇／時間觀察的純合成fixture：`uv run python -m pytest scripts/tests/test_hhhl_variants_selection.py scripts/tests/test_hhhl_variants_observations.py scripts/tests/test_hhhl_variants_features.py -q`，**84 passed**。測試曾抓出fixture誤認不同股票碼必有不同CRC parity，已修正fixture再驗；選擇公式未改。正常commit hooks及hosted CI／review另由PR狀態提供，合成通過不代表型態或策略有效。

- 加上CI domain registration驗證的同次測試為 **153 passed**。程式pin使用UTF-8／LF正規化以避免Windows checkout換行改變身分；市場輸入／zip仍驗原bytes。receipt中38個checksum／commit hash逐值核對後僅加入exact secret baseline；新值仍須被擋，6項checksum回歸測試通過。

保留 worktree `D:/Project/stock-research/.worktrees/hhhl-v4-variants-mission` 作mission PR及後續同task計算。只有這個session擁有的變更會commit；合併由owner。
