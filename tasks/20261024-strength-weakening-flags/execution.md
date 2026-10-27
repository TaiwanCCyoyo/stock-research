# C：全量執行紀錄

全量計算於 2026-10-27 18:20（台北時間）完成，`run.json` 為 `complete`。
這只表示計算完成；報告、展示頁、研究卡片與正式移交屬工作包 D，尚未交付。
本研究仍為已看過歷史上的描述，不批准停損規則或帳戶交易。

## 授權、定義與輸出

- A：[PR 91](https://github.com/TaiwanCCyoyo/stock-research/pull/91)，合併 commit `ee92738c7c45c1295bd6f9b23182a4eab73480bd`。
- B：[PR 93](https://github.com/TaiwanCCyoyo/stock-research/pull/93)，合併 commit `d09dd4c98e52512b4e8978332462b52969be9abb`。
- 執行 commit：`b1926ad248d671e8719a5b19c24da882a8ffc666`；W1–W10 原樣執行，沒有替代版本。
- Run：`c-20261027-main-b1926ad`，完整命令為 `uv run --no-sync python -u -m scripts.run_strength_flags --mission-pr 91 --code-pr 93 --run c-20261027-main-b1926ad --owner codex-strength-weakening-flags --memory-limit-mib 4096`。
- 價格：`adjusted-daily-v1`，讀取 `2026-10-22-20261026T123020Z`，`reference_factor_adjusted`，`as_of=2026-10-12`。
- 固定 2010-01-04..2026-10-12、4,110 sessions、1,942 檔；S6、組別與 effective-label 沿用 PR61。
- 共用 technical 表的計算截止日不同，沒有執行逐值比較，也沒有採用其欄位；改用原先指定的 PR17 cutoff adapter。詳見 [來源選擇](results/indicator-probe.json)。
- [結果目錄](results/) 有 36 張分組終表、3 份對齊證據、來源選擇及階段量測，共 41 個收據列管結果；另附 [原始收據](results/run-receipt.json)。
- `summary` 共 13,824 切片列；其中 pooled/full 共 1,728 格，主要 28 格。欄位與分母見[資料契約](data-contract.md)。

## C-2 與結果完整性

四組 × H126／H252 × known／hit／loss 的 24 個整數完全相同，差均為零。
以 seed 20261024 抽取的 200 個 CORE 事件，診斷與實際計數快速路徑均逐值對齊。
沒有對齊失敗、沒有調整規則；證據為 [總數](results/alignment-totals.parquet)、[樣本](results/alignment-sample.parquet)、[狀態](results/alignment.json)。

2026-10-28 報告前以 `run_receipt.changed_results` 核對一次，41 個結果全部吻合，
changed results 為空；驗證 wall 0.522 秒、CPU 0.094 秒。沒有重新計算市場結果。

### 程式來源觀測限制

原收據保留 `code_drift` 警示：起迄 commit 相同，且兩端均記錄 `dirty=false`，
但 runner 起跑時呼叫 `code_identity` 沒有帶 `sources`，未保存來源檔的起始 size／mtime。
依 `run_receipt._code_drift`，缺少這項觀測會得到 `sources_changed=null`、
`sources_unchanged_observed=false`；這不是已證實程式有變動，也不能據此證明中途沒有改寫後復原。
`runtime_code_verified=false` 是收據對所有執行一律採用的誠實邊界。
沒有補造起始觀測、改寫收據或重跑。上述限制須隨結果保留。

## 預先固定的主要判讀

主要 28 格中，26 格為 `weakens_with_drop`，2 格為 `weakens_beyond_drop`。
後者都是 X5_MA60、H252、L20、2 倍，分別屬 CORE 與 LEAD_B1。
這些是保存終表的判讀，沒有改門檻、補選格子或加入停損模擬。
完整 28 格、次要方向、年代／CRC／drop-best 切片與錯殺代價由 D 報告呈現。
`weakens_with_drop` 不表示已證明訊號完全沒有額外資訊；只是分層差未通過兩種區間的固定條件。
錯殺代價的分母為 calendar-full 最終達標事件，觀測到首次達標前，不是 L20 風險集合的停損績效。

## 成本與資源

20 檔相同輸入的串行／2／4 workers 整數表一致；wall 為 123.27／78.83／65.34 秒。
採 4 workers、max-in-flight 4、記憶體准入預算 4 GiB；這是准入預算，不是作業系統硬上限。
探測以股票／格數線性外推約 20.3 小時，未含 C-2；不當作完成時間保證。

| 正式階段                 |         Wall |  協調程序 CPU | 程序存活期 peak working set |
| ------------------------ | -----------: | ------------: | --------------------------: |
| 準備、對齊與逐股 counts  | 15,043.42 秒 |   6,634.31 秒 |                   673.5 MiB |
| 全域彙總與兩種 bootstrap | 47,209.50 秒 | 119,255.98 秒 |                 1,740.0 MiB |

兩階段 wall 合計約 17 小時 18 分。CPU 為父程序，沒有包含 worker CPU；
記憶體是階段結束觀測的程序存活期 peak，並非各階段獨立峰值，也不是整個 process tree 的同時峰值。
Windows I/O counters 包含 cache，不能當實體磁碟吞吐；pool startup 僅包含在 makespan，未單獨量到。
完整串行／worker、每股、寫檔、序列化、RSS／I/O 與外推限制保存在 [timings](results/timings.json)。

## 已核實的密鑰掃描誤報

Owner 於 2026-10-28 同意精確登記本批 46 個雜湊誤報：41 個最終結果 SHA-256、
4 個共用家族原有的已發布檔校驗值、1 個 Git commit；沒有逐股中間檔或 checkpoint 雜湊。
`.secrets.baseline` 只新增兩個 JSON 結果路徑的 Windows／POSIX 精確紀錄，共 92 筆，
既有紀錄與掃描設定保持原值。檔案由 1,000,345 增至 1,028,277 bytes，低於 1 MiB。

## 移交與保留

正式取得路徑是本任務 Git 的 `results/`，定義與讀法為 [data-contract](data-contract.md)，
程式由收據記錄的 Git commit 取得；不依賴原執行 worktree 或 producer 輸入副本。
此 C PR 尚待 owner 合併；D 完成與正式移交前不宣稱 `delivered`。

續接的 scratch 為 `D:/StockData/stock-research/scratch/20261024-strength-weakening-flags/c-20261027-main-b1926ad/`，
狀態 `complete`。`strength-weakening-flags` hold 仍保護上述共用讀取，
reason 為 `20261024-strength-weakening-flags/c-20261027-main-b1926ad: preserve until report delivery`。
待 D 正式移交、保存位置滿足 delivered 條件後，再依 API 登記並僅釋放自己的 hold；不先清 scratch。
沒有下載、部署或變更排程，沒有修改 PR17／PR61 的舊程式、結果、收據、前瞻紀錄或其 hold／程序。
