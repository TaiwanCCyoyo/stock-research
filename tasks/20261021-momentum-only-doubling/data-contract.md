# Momentum-only v1 資料契約

本研究的定義、母體、分箱與標籤全部沿用 [PR17 pattern-scan](../20261013-pattern-scan/mission.md)
與本 task 的 [mission](mission.md)；這裡只說明輸出檔怎麼讀，以及執行時與 mission 文字不同或 mission 沒寫到的地方。

## 位置與讀法

- 最終表：`tasks/20261021-momentum-only-doubling/results/`，Parquet（zstd）＋ `research_result.json` ＋ `run-receipt.json`。
  只含整數計數與比率，沒有任何逐日價格、指標或逐筆事件。
- 收據只對最終檔計 SHA-256；輸入以說明欄位記錄（PR17 日曆 pins、PR17 宇宙清單、PR17 Q1 對照表、共用世代）。
  結果目錄排除在 Prettier 之外，避免格式化改動已記錄雜湊的檔案。
- 重現：`uv run python -m scripts.run_momentum_only stocks|parity|study|coverage|audit --work <dir>`，
  最後 `finalize --work <dir>`。`stocks` 讀共用 `adjusted-daily-v1` 的指定世代
  （`read_adjusted_daily(..., as_of=2026-10-12, calendar=PR17 日曆)`），每檔一個中間 `.npz`；中間檔不入 Git、不計 hash。
  `finalize` 只接受所有階段都出自同一個乾淨 commit 的工作目錄；收據記錄該 commit，之後才改的發布程式記在 `code_drift`。

## 表

| 檔案                                             | 一列是什麼                                                                                                                                                                           | 主要欄位                                                                                                                                                                                                                                                                                                                                                  |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `set_summary-<split>-<row_kind>.parquet`（9 檔） | 組別 × 期限 × 倍數 × 年代（all／2010-2012／2013-2018／2019+）；檔名分 split（all／development／cross-check）與 row_kind（full／drop_best_year／drop_best_stock），讓每檔低於 500 KiB | `event_n`、`known_n`、`hit_n`、`loss_n`、`flat_win_n`、`unknown_n`、`censored_n`、`full_unknown_n`、`distinct_stock_n`、每股事件中位數／最大值、`hit_rate`、`loss_rate`、full-calendar 上下界、`top10_stock_hit_share`、`removed`（被刪的年或股票）、相對同口徑基準的 `hit_ratio_vs_base`、`hit_diff_vs_base`、`loss_diff_vs_base`，及相對 `C-52w` 的差距 |
| `set_annual.parquet`                             | 組別 × 期限 × 倍數 × t0 年（split=all）                                                                                                                                              | 同上計數與比率                                                                                                                                                                                                                                                                                                                                            |
| `bootstrap_intervals.parquet`                    | `A1&A2:daily`（CORE）、`LEAD_B1:daily` × 期限 × 倍數 × bootstrap（`stock`／`two_way`）× 統計量                                                                                       | 95% 百分位區間 `lower`、`upper`；2,000 次                                                                                                                                                                                                                                                                                                                 |
| `verdicts.parquet`                               | CORE、LEAD_B1 × 12 個標籤                                                                                                                                                            | 比率、倍數、差距、冷卻口徑樣本數、`sample_sufficient`，以及三個差距各自的方向：`above_zero`／`below_zero`／`unresolved`（兩種 bootstrap 都同意才不是 unresolved）／`insufficient_sample`                                                                                                                                                                  |
| `decomposition_summary.parquet`                  | 型態分解各格                                                                                                                                                                         | 全部 `not_evaluated`，附原因                                                                                                                                                                                                                                                                                                                              |
| `big_runner_coverage.parquet`                    | 組別（22 個集合與各自的 `:random` 對照）× H504 × 5 倍／10 倍                                                                                                                         | episode 數、matched／unmatched／unknown、覆蓋率與上下界、首次符合距 anchor、已漲（entry）與剩餘（remaining）報酬的 Q25／中位數／Q75                                                                                                                                                                                                                       |
| `coverage_quotas.parquet`                        | 隨機對照的 集合 × 股票 × 年                                                                                                                                                          | 配額、可抽、實抽、不足數                                                                                                                                                                                                                                                                                                                                  |
| `audit_episodes.parquet`                         | 每一個 H504 10 倍 episode 與 20 個抽樣 5 倍 episode                                                                                                                                  | 調整後與原始價格比、窗口內除權息與因子、超過漲跌幅的單日變動、篩檢旗標、`review`（manual／screen_only／not_screenable_unknown_episode）、`audit_price_error`、人工註記                                                                                                                                                                                    |
| `parity_check.parquet`                           | `C-base-daily`、`C-52w-daily` × H126／H252（2 倍）                                                                                                                                   | 本研究與 PR17 的 known／hit／loss 與差距                                                                                                                                                                                                                                                                                                                  |

`loss_n`／`loss_rate` 沿用 PR17 吸收式標籤：期限內**未曾**達到倍數且期末收盤低於起點才算；先達倍數後跌回的仍是 hit。
報告稱之為「未翻倍收低」，不是持有到期末的虧損機率。

## 組別

- `C-base-daily`、`C-52w-daily`：每日、無冷卻基準；`C-base`、`C-52w`：PR17 的 20 session 冷卻版本。
- 22 個純強勢集合：`A1`..`A6`、15 個兩兩交集（例如 `A1&A2` 即 mission 的 CORE），`LEAD_B1` = A1∧A2∧A3。
  每個集合有 `:daily`（無冷卻）與 `:cooled`（每股每集合獨立 20 session 冷卻）兩種口徑；比較只在同口徑內做。
- A1 `C3≥60%`、A2 `D2≥2.5`、A3 `G2_limit`（原始收盤漲幅 ≥ 9.5%）、A4 `H≥90`、A5 `RSI≥70`、A6 `F>1`，
  全部用 PR17 `classify_column` 的原分箱。A7（`PAT_other_B4`）與含它的 `LEAD_H1` 未評估。
- 每日組別的結果品質規則沿用 PR17 `C-base-daily`：偵測窗只看 t0 當天（`C-52w` 為前 250 列，與 PR17 相同），
  結果窗 t0+1..t0+H 有不明跳動即 unknown。

## 執行時的決定（mission 未寫明或與文字不同）

- **宇宙固定為 PR17 的 1,942 檔 ordinary reference**（PR17 `derived-preparation.json`，`ordinary_reference=True`）。
  2026-10-12 以後才出現的新上市股不在歷史研究內。歷史執行讀的是 PR17 本機執行目錄裡的原檔；
  同一份清單已逐一核對後凍結為 [pr17-universe-v1.json](pr17-universe-v1.json)，之後的重現與前瞻紀錄都讀這個檔。
- **A3 在 2015-06-01 以前不可能成立。** 台股漲跌幅限制在那天由 7% 放寬為 10%，PR17 的漲停代理門檻是 9.5%。
  含 A3 的集合（包括 `LEAD_B1`）實際只涵蓋 2015-06 以後；全期間 `all` 列與從 2010 起算的基準比較時，
  會因年代組成不同而偏高。規則不改；報告另引事前就有的 `2019+` 年代列對照。
- **H（A4）** 用與 PR17 `hhhl_variants_run.cross_section` 相同的 pandas 運算重算；
  2026-10-22 對 PR17 存的 `global/*.parquet` 逐格比較 7,981,620 格，0 差異。
- **兩種 bootstrap 的種子：** `stock` 用 20261021；`two_way` 的股票抽樣用 20261022、年份抽樣用 20261023。
- **隨機對照的種子推導** 與 PR17 `random_matched_control` 不同：PR17 對已冷卻的池子用 `object_digest`；
  本研究的池子是每日合格日（未冷卻），種子由 `(20261021, 集合, 股票, 年)` 的字串位元組推導。
  抽法（每股每年、不放回、不足記 shortfall 並把該股票年份標為 unknown）相同。
- **10 倍 episode 核對：** 全部可判定的 10 倍 episode 與 20 個抽樣 5 倍 episode 逐段人工核對三項價格事實
  （調整前後比的差距等於窗口內除權息因子乘積、沒有品質旗標、每日調整後漲跌在當時漲跌幅限制內），
  超出限制的 4 段與落差最大的一段另對照原始收盤、上市日與除權參考價。`finalize` 要求每一段都有紀錄。
  頂點不可判定的 10 倍 episode 列為 `not_screenable_unknown_episode`。
  判定為 `audit_price_error` 的數量為 0，所以「移出前後」兩版相同。決定與理由見 [audit-decisions.json](audit-decisions.json)。
- **刪最好年份／股票的平手規則** 同 PR17 `drop_best_hit_year`：所有年份都沒有 hit 時刪最早的年份（股票則刪代號最小者）；
  只有完全沒有事件的切片不刪。
- **對齊檢查** 結果為逐項完全相同（見 `parity_check.parquet`），未使用容差。

## 前瞻紀錄

- 指令：`uv run python -m scripts.record_momentum_forward_day --workers 4`，每個交易日在 20:30 共用更新完成後人工執行；
  補記較早的日子加 `--date YYYY-MM-DD`。指令拒絕在平日 18:00–18:45 或任何 `StockProject-*` 執行中讀取，也拒絕從有未提交改動的程式執行。
- 位置（2026-10-31 起，見[位置修正](amendments/2026-10-31-forward-log-location.md)）：研究資料根目錄
  `<STOCK_RESEARCH_SHARED_ROOT>/tasks/20261021-momentum-only-doubling/forward-log/days/<t0>.parquet`
  （本機 `D:/StockData/stock-research/...`），一天一檔，no-replace；已存在的日子不能被覆寫，更正只能另寫 correction 檔。
  日檔不進 repository。舊位置 primary checkout `tasks/20261021-momentum-only-doubling/forward-log/` 由新版程式第一次執行時
  以 SHA-256 驗證複製過去（不覆寫、不一致就停），舊目錄保留到 owner 同意清理。
- 一列一檔 PR17 宇宙股票：`t0`、`security_id`、`base_eligible` 與原因、原始與當代還原收盤、A1–A6 的值與 state（1／0／−1）、
  22 個集合的 state、`C-52w` 狀態、`generation`、`recorded_at_utc`、`code_commit`、`recorded_late`。
  A7、`LEAD_H1` 與型態狀態為 null，附 `pattern_null_reason`。
- 每一天都以當時 current generation 的 `read_adjusted_daily(..., as_of=該日)` 計算到該日為止的完整歷史，
  與歷史研究同一套程式；2026-10-22 抽 25 檔以截止日 2026-10-12 重算，資格、C-52w 與 5 個個股條件都與歷史研究最後一天相同。
  A4 是當日全宇宙排名。
- `recorded_late=False` 只給記錄當下就是 current generation as-of 的那一天，而且必須在下一個平日 09:00（Asia/Taipei）以前開始並完成；共用世代停滯或超過時限一律記為 late，不啟動確認樣本。mission 合併（2026-10-21 19:48 UTC）後
  第一個準時凍結的日子寫入 `forward-log/cohort.json`（no-replace），開始 12 個月的確認樣本；之前與補記的日子只作描述。
- 評估前只能看列數、資格與 unknown 等營運計數，不看任何 hit／loss。
- **執行紀錄**：每次執行（含拒絕、失敗、等不到資料）都在 `forward-log/attempts.jsonl` 追加一行，只增不改：
  `outcome` 為 `on_time`／`late`／`cohort_recovered`／`already_frozen`／`refused`／`failed`／`not_recorded`，
  附 `reason`、看到的 generation 與 as-of、`code_commit`、起訖時間，以及目前日曆中仍沒有日檔的交易日：
  `cohort.json` 建立後只算其 `confirmatory_start`～`confirmatory_end` 內的（`missing_confirmatory_days`，附 `confirmatory_window`）；
  建立前列 2026-10-22 起的營運缺漏（`missing_days_before_cohort`），它們不屬於確認樣本。漏跑或失敗因此留下有日期的紀錄，事後補記也不會被當成準時。
- **排程**：Windows `StockResearch-MomentumForwardLog`，週一至週五 21:00 在 primary checkout 執行
  `record_momentum_forward_day --scheduled --workers 4`。它等到共用世代的 as-of 等於當天且 producer 閒置才記錄，
  最多等 12 小時且不超過隔日 09:00，判定準時用執行完成時的時間；等不到（含休市，世代日曆不是交易所行事曆，所以不從舊世代推論休市）
  就寫一行 `not_recorded`，附最後看到的世代與缺漏日。每次執行恰好一行紀錄，讀不到世代也記 `failed`。
  `momentum-forward.log` 結尾有 `exiting record_momentum_forward_day ... exit_code=N`，收到 Ctrl-C／終止訊號時另有 `received signal`；
  工作排程的結果碼（例如 0xC000013A）與它不一致時，以 `attempts.jsonl` 與這兩行為準。
  程式乾淨判定忽略 `stock-data-downloader` 子模組指標（前瞻紀錄不執行子模組程式）；`forward-log/` 已不在 checkout 內；
  不乾淨時寫一行 `refused` 後結束。紀錄寫到
  `D:/StockData/stock-research/logs/momentum-forward.log`。
