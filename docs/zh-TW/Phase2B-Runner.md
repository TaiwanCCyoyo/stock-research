# Phase 2-B 夜間 Runner

Phase 2-B runner 是任務準備器，不是 AI 研究員。日常使用時，使用者不需要自己記這些指令；Codex 可以在需要時代為執行。

它只做機械性工作：

- 建立 `tasks/<task-id>/`。
- 寫入 `mission.md`。
- 檢查本地 K 線資料並寫入 `data_audit.json`。

這是舊版任務準備工具，不代表目前研究已獲准執行；新研究先依 [擁有者契約](../en/research-owner-contract.md) 與 [研究基礎設施](../en/research-foundation.md) 決定準備與執行範圍。

它不做：

- 不呼叫 LLM。
- 不自行設計策略。
- 不取代 Codex 的 Notion 摘要整理。
- 不連網研究。
- 不下單。

## PowerShell 用法

```powershell
.\scripts\run_nightly_research.ps1 `
  -Task 20260505-nightly-research `
  -Codes "2330,2454,2317,2303,2881" `
  -Start 2022-01-01 `
  -Objective "Prepare a nightly 2B moving-average-convergence research task."
```

注意：`-Codes` 必須加引號。PowerShell 會把未加引號的逗號清單解析成陣列。

## Python 用法

```powershell
uv run python scripts\prepare_nightly_research.py `
  --task 20260505-nightly-research `
  --codes 2330,2454,2317,2303,2881 `
  --start 2022-01-01 `
  --objective "Prepare a nightly 2B moving-average-convergence research task."
```

## 已退役的 experiment.json 迭代迴圈

已刪除的 `scripts/run_experiment_iteration.py` 曾在每個通過 train 的迭代中執行 holdout，並把結果寫回供後續選擇的 journal。這會反覆使用保留期，不符合目前 train-only 迭代與最終評估的界線。

不要沿用該 harness 執行目前研究，也不要只隱藏 holdout 數字後繼續呼叫。新研究使用 [研究基礎設施](../en/research-foundation.md) 的登記執行與曝光管理；舊 journal、mission 和 report 保留供歷史解讀；`scripts.generate_nightly_report` 可獨立讀取既有 journal，無須舊迭代器。
