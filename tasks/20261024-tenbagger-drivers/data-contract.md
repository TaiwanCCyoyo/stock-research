# Tenbagger drivers 資料與執行契約

狀態：工作包 B，只有程式與合成測試；沒有本研究的市場結果。設計依
[codex-handoff](codex-handoff.md) T1–T9、R1–R6、F1–F6，mission 由工作包 A
另行交付。程式通過不代表研究完成，也不批准策略。

## 定義與重用

| 身分                    | 入口                                                                             | 固定語意                                                                                                                                                                                    |
| ----------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `industry-breadth.v1`   | `research_core.industry_breadth_v1.industry_daily`                               | 當日 S6 合格、同官方產業、排除自身；A4 已知 peers 至少五檔才有 BREADTH。分母只含已知 A4 的同業，未知不當零。HOT 為 BREADTH ≥25%。                                                           |
| `industry-breadth.v1`   | `prior_turnover` / `IndustryDaily.size_percentile`                               | `official_daily_price.value` 的前 20 個 sessions 均額，排除 t；在當日合格、同產業、金額已知的股票中平均百分位排名，包含自己、平手取平均。SMALL 為百分位 <50。這是交易規模，不是市值。       |
| `institutional-flow.v1` | `research_core.institutional_flow_v1.read_institutional` / `institutional_daily` | producer 唯讀法人股數；t−60..t−1 完整 60 sessions，淨買超日比 ≥0.6 且累計淨買超／同期成交股數 ≥5% 為 INST。t 日資料不進條件。缺列、缺淨額或成交量不足皆 unknown，負淨額保留。               |
| `tenbagger-drivers.v1`  | `research_core.tenbagger_drivers_v1`                                             | PR61 逐股 inputs、A4、S6、2／3／5／10 倍標籤、effective-label、event main eligibility、episode merge、20 session cooldown 與整數計數；stock／two_way 各 2,000 次，seed 20261026／20261027。 |
| 執行接線                | `research_core.tenbagger_drivers_run_v1` / `scripts.run_tenbagger_drivers`       | owner 合併檢查、producer idle、固定世代、原始 PR61 checkpoint 對齊、scratch、最終表及 receipt。                                                                                             |

PR17 `pattern_scan_local_inputs_v5.industry_holding` 與 MKT／J 實作已檢查；
它們分別是未來 holding 報酬、其他條件與先前 11 日事件數，並非本次
「當日 S6 同業的 A4 比例」。本次保留它們，不把事後 holding 報酬當 t 日條件。
新 reduction 使用相同完整參考產業與排除自身原則，明確套用本次逐日資格。

## 輸入位置、單位與缺值

- 價格：`adjusted-daily-v1`，`reference_factor_adjusted`，`as_of=2026-10-12`；
  `momentum_only_v1.pr17_calendar()` 的 4,110 sessions，自 2010-01-04 起，
  `pr17_codes()` 的 1,942 檔。從 current 解出一次 generation 後每次明傳相同值。
- 原始成交金額與成交股數：`producer_data_root()/official_daily.sqlite`，
  `official_daily_price.value`（新臺幣元）與 `volume`（股）。不從還原價估計交易金額，
  也不把 `price_daily.parquet.Volume` 的張數直接當股。沒有來源數值就維持 unknown。
  S6 資格仍完整沿用 PR61 既有 raw-close × lots 的流動性門檻；本次 T5
  actual value 與法人分母的 shares 並不改寫 S6。
- 產業：`producer_data_root()/symbol_meta.sqlite` 的 `symbol_meta.industry_category`。
  這是目前官方分類，不是歷史當時可得分類；缺分類 unknown。它無法代表題材，
  不使用事後 sector-wave 族群清單。
- 法人：同 producer 根目錄 `institutional.sqlite`，`institutional_daily` 的
  `three_institutions_net`（主要）、`foreign_total_net`、`trust_net`（次要），
  搭配 `institutional_fetch_log` 的 `market/date/status/row_count`。
- 連續覆蓋按 TWSE、TPEx 分開：一日必須有 `ok` checkpoint、正確實際列數及單一來源。
  缺日、失敗、列數不符或來源切換會切斷區段；只使用截至執行截止日最後一段連續區間，
  早期孤島排除。後端若仍有尾端缺日，缺日保持 unknown，不延伸覆蓋。
  每股再要求自己的 60 日列與該淨額完整，市場覆蓋不代表每股已知。
  每市場起訖、sessions、被排除的早期完整 sessions 隨結果保存。若回補不足 2010，
  法人部分僅在實際期間內成立，產業仍從 2010 起算。
- 只透過 `producer_data_root()` 設定的原位唯讀來源；不 import producer code，
  不建立資料副本、symlink、junction 或 hardlink。讀前拒絕寫入時窗、
  `StockProject-*` 執行及法人手動回補程序；讀後檢查 DB/WAL size/mtime。
  發現 active writer 就停止等待其 owner 完成，不終止程序或觸碰其 lock。

## 對齊與前置條件

任何 probe 或全量讀取前，`execution_gate` 以唯讀 `gh pr view` 驗證 A、B
的實際狀態為 owner 合併到 `TaiwanCCyoyo/stock-research` 的 `main`，且其
merge commit 在已 fetch 的 `origin/main`。工作目錄 mission 與本次 executor
必須和 `origin/main` 相同。不得用 CLI allow 旗標替代合併。

`--pr61-work` 必須明確指定 PR61 原始工作目錄，含 `stocks.json` 與全部
`stocks/<code>.npz`；只讀，缺任何檔案就停。checkpoint 的 cutoff、股票數與
generation 必須符合 PR61 已發布歷史結果。從這些原始 checkpoint 重算 PR61 A4，
和本次世代的完整全市場 A4 每格比較；不以本次算出的同一陣列作自己的對照。
PR61 原始 checkpoint 的位置不由本研究猜測，也不重建代用品。

再以 PR61 episode 程式算 H504 的 10／5 倍段落，必須同時等於
已發布 `results/big_runner_coverage.parquet` 與固定 139／900。
正式步驟另將 C-base-daily、CORE 在 3／5／10 倍 × H252／H504
全部整數 counts 與 PR61 `set_summary-all-full.parquet`
（all split、all era、full）逐項比較。

任一差異寫入 scratch 的 `alignment.json`，`AlignmentError` 停止；
不沿用 PR61 另一研究的容忍區間、不改門檻、不縮短日期。

第二步另需本 task 內的 owner decision 記錄：

```json
{
    "step": "formal",
    "decision": "continue",
    "decided_by": "TaiwanCCyoyo",
    "retro_receipt": "tasks/20261024-tenbagger-drivers/results/retro/<run>/run-receipt.json"
}
```

此記錄由執行主 session 收到 owner 的直接繼續指示後保存，不要求另一次合併。
receipt 必須是本研究完成的 retro，最終結果 SHA-256 驗證無變動，並含同目錄
`r6-recommendation.json`。R6 無論支持或不支持繼續都只是建議；程式不從建議
自行推論批准，第一步也不能改第二步的條件或門檻。

## 計算、抽樣與報表語意

- R1 用同一個 2 倍／H504 episode anchor 與最高收盤倍數分 ≥10、5–10、2–5。
  anchor、首次 2×、首次 3×各自取 contemporaneous 特徵；不到 3×就沒有該時點。
  PR61 `audit-decisions.json` 中 `audit_price_error` 的段落排除，不更動原檔。
- R4 對每個 cohort（≥10、5–10、2–5，以及 ≥5 合併組）各自按比較時點的
  股票 × t0 曆年配額，seed 20261024，從該股該年 S6 合格日不放回抽樣。
  random rows 與 quota 都帶 `matched_group`，每個 cohort 只與自己的
  `random:<cohort>` 基準比較；不讓 2–5 樣本的股票／年份組成主導 10 倍段的基準。
  不讀結果決定抽法，不跨 cohort、股票或年度補缺額，配額／缺額另列。
- R5 對法人變數先套同一個主要 INST-known 遮罩，再排除次要欄位自身缺值。
  所有組別、所有時點都用同規則，unknown 數與比例保留。
  `retro_distributions` 包含各分箱比例與原值中位數；`retro_intervals`
  包含相對 2–5 與各自 `random:<cohort>` 的各分箱比例差及中位數差的兩種區間。
  分箱及分母用 stock × t0 年整數 counts；中位數用
  `(stock, t0 year, exact value)` 稀疏整數直方圖重組，非按 episode iid 重抽。
- R6 使用首次 2×時點的 ≥5 合併組 true 比例減 2–5 組 true 比例。
  HOT∧SMALL 或 INST 任一差值為正且兩種區間下界都 >0 才建議繼續。
  輸出 point difference、stock/two_way 各自上下界與 owner decision required。
- F1 八組固定；F2 中含 INST 的組，只和 `C-base-daily|INST-known` 比，
  含 CORE 的另比 `CORE|INST-known`。不含 INST 的用全期 C-base-daily／CORE。
  全期 PR61 counts 僅作 alignment，不能拿來判讀法人組。
- F3 冷卻 known_n <100 或 distinct_stock_n <30 為 `inseparable`；每日 hit/loss
  分母與未知／截尾全部由 PR61 `group_counts` 重用。F5 hit 與 loss 各自判讀，
  兩種下界都 >0 為 above_base、兩種上界都 <0 為 below_base，否則 unresolved。
  loss 的 above_base 代表期末收低比例更高，不能寫成優勢。
- F4 主格為 3 倍 H252、5 倍 H504，10 倍 H504 單列且必報；其餘為次要。
  F6 三年代、逐年、drop_best_year／stock 與前十檔 hit 占比均從原整數 counts
  重組，只作描述，不進判讀。所有歷史結果都是已看過期間的描述，非帳戶報酬。

## 成本量測、儲存與命令

入口（從 repository 根目錄執行；PR 數與原始位置由執行 session 提供）：

```text
uv run python -m scripts.run_tenbagger_drivers --step retro --probe --mission-pr <A> --code-pr <B> --pr61-work <original-pr61-work> --run-id <new-probe> --owner <session>
uv run python -m scripts.run_tenbagger_drivers --step retro --probe-record <probe.json> --mission-pr <A> --code-pr <B> --pr61-work <original-pr61-work> --run-id <new-retro> --owner <session>
```

probe 只量固定 20 檔的 stock-local 階段，串行與 2／4 個 thread workers
用相同輸入逐值比對；**不計算子樣本 A4、不宣稱 parity 通過**。
原始 inputs 讀取及各次 trial 記 wall／CPU、Windows process memory/I/O、
啟動與排程成本；非 Windows 無 native counter 時記 unavailable。
thread 不跨程序序列化，明確註記。全量保留完整跨股 barrier，固定股票順序，
最多四個 workers、每批 workers 個任務。probe 估 stock-local >8 小時就停，
不縮減定義。完整研究另需記錄 barrier／bootstrap 成本，probe 不假稱已量到它們。

scratch 一律由 `research_core.scratch_runs.create_run` 建立，在設定的 shared
research root 的 `scratch/<task>/<run>/`，不放 worktree `.tmp/`。
所有 run-id 與 checkout 先取得同一個 `scratch/<task>/.execution.lock` 的原生 OS 鎖，
持有至本次 hold release 完成；第二個執行在碰到 hold 前即拒絕。程序結束由 OS 釋放鎖，
不依檔案存在或時間判斷，也不刪鎖檔。只有本研究自己的 `tenbagger-drivers` hold 可建立與 release，既有同名 hold
會拒絕新 run；絕不接觸 PR17 或 PR61 的 hold、程序、前瞻紀錄或排程。

最終小表放 `tasks/20261024-tenbagger-drivers/results/<step>/<run>/`，
先以 `copy_verified` 複製最終小表到目的地同層 staging，核對前後 SHA-256，
再以 `publish_noreplace` 原子發布、拒絕覆寫；支援 scratch 與 checkout 在不同檔案系統，
不搬動或刪除 scratch，失敗保留 staging 供復原。retro：`retro_distributions.parquet`、
`retro_intervals.parquet`、`tenbagger_episodes.parquet`、`retro_quotas.parquet`、
`r6-recommendation.json`；formal：`formal_summary.parquet`、
`formal_intervals.parquet`、`formal_verdicts.parquet`。兩者都有 `execution.json`
及 `run-receipt.json`。只有最終結果檔 SHA-256，inputs、generation、commit、
mission、定義與固定參數作說明；輸入日後更新不使完成結果失效。

scratch 完成標記 `complete`，尚待本工作包 C 的中文報告、HTML 與交付確認，
不會冒稱 `delivered` 或自動清理。正式執行與收尾依 owner 決定另交 PR。
本研究不直接發布新的 maintained BREADTH／SMALL／INST 共用家族。
