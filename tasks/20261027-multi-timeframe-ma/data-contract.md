# S7 日／週均線資料契約

本契約服務 [mission](mission.md) 的固定設計。**尚無 runner、輸入世代、實際研究輸出或 run receipt。**
下列是後續 S7-B 的資料/驗收介面，非既有檔案可用性聲明；S7-A 不開真實資料或結果。

## 身分、輸入與依賴

| 項目                | 固定契約                                                                                                                                                                                                                                                                     |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| task / definition   | `20261027-multi-timeframe-ma` / `multi-timeframe-ma.v1`（擬定，尚未實作）                                                                                                                                                                                                    |
| universe            | PR61 1,942 ordinary-reference；沿 [PR61 contract](../20261021-momentum-only-doubling/data-contract.md) 的名單身分，不在本包讀取                                                                                                                                              |
| calendar            | PR61 4,110 common sessions，2010-01-04..2026-10-12；保留缺價日，不能壓縮交易日距離                                                                                                                                                                                           |
| generation          | 一次研究固定一個 G；實際值尚無，receipt 不捏造                                                                                                                                                                                                                               |
| price basis         | `reference_factor_adjusted` / price-basis.v2；同 G、同決策 cutoff 的還原價                                                                                                                                                                                                   |
| daily qualification | PR61 S6，沿 `pattern_scan_inputs_v1.daily_qualification`；不新增 universe/filter                                                                                                                                                                                             |
| baseline            | canonical `C-base-daily` 與 `CORE=A1&A2:daily`；cooled 是各自獨立 canonical 冷卻後的同口徑基準                                                                                                                                                                               |
| effective outcome   | PR61 原 t 的 effective-label、event_main_eligible、calendar_full 與品質 overlay                                                                                                                                                                                              |
| reuse               | [momentum_only_v1](../../research_core/momentum_only_v1.py)、[count_cube_v1](../../research_core/count_cube_v1.py)、[technical_daily_v1](../../research_core/technical_daily_v1.py)、[multiple_outcomes_v1](../../research_core/multiple_outcomes_v1.py)；不改 frozen kernel |
| boundaries          | owner mission merge、原 owner 去重、S1/S2 完成或明確重排、單一長計算 admission；本契約不批准資料/compute                                                                                                                                                                     |

先讀 [research program](../../docs/en/research-program.md)、[derived-data contract](../../docs/en/research-derived-data.md)及
[data operations](../../docs/en/stock-agent-operations.md)。後續資料讀取在原 canonical/shared root 原地進行，不複製或連結到 worktree。
本包既不讀 root，也不 inventory 市場 artifact、拿 hold 或更新 generation。

## cutoff 與價格一致性

未來訊號價格以公開 API [read_adjusted_daily](../../research_core/maintained_adjusted_daily.py) 的下列語義取得：

```text
read_adjusted_daily("reference_factor_adjusted", generation=G,
                    as_of=t, calendar=common_calendar[common_calendar<=t])
```

這是介面規格，不是本包要執行的命令。
在同 G 內，依 t 以前事件重建依賴價；不能直接截斷世代最新 technical 表。
缺合格 `as_of_inputs`、因子無效/衝突或 cutoff 超過 G 支援範圍，停止，不照 API 錯誤提示自動 update。
未知價格/因子與 known false 分開；不採 raw 價、前價、1 倍因子或另一世代作替代。

`as_of` 只界定計算範圍，未證明歷史來源/修訂/公司行動事實當時可取得。
任何後續 receipt 須公開來源可得性與 known_at 缺口；不能稱完整 PIT。
同一公式內的 Close、lag Close、全部 SMA/EMA 與密集分母都在同一決策 cutoff 尺度；
不能混用今天的 restatement 與過去另存的價格單位。

R 聚合的是過往各自決策 cutoff 所產生的 D **bool**，不是把不同還原尺度的數值平均。
W_prev 也保留其週確認 cutoff 的 bool；比較當週 Close/lag Close/EMA 時，數值 operands 仍用該次 cutoff 的共同尺度。
同 G、cutoff 前輸入/已知 calendar 相同時，未來 append 不改已知訊號；不同 G 的來源修訂不在此保證內，必須另列 lineage。

## 日期、有效列與數學狀態

- 唯一鍵 `(security_id, session_index)`，session_index 對共同 calendar；重複/倒序/無法對齊不得靜默修復。
  t、t−20、t+20、H252/H504 均用共同 session index，不找下一個有效報價替代。
- 時區 Asia/Taipei；week_id 為 ISO year/week（跨年不按曆年錯分）。
  須有截至 t 已知的官方 session calendar 覆蓋週末與休市狀態，與截斷的價格日曆分開。
- 缺日曆覆蓋、未完成週與缺股價是不同 reason。臨時停市以其可知時點處理；不能用事後 calendar 回填訊號當時的可知性。
- 真補行週六是 session；假週日排除。週內無 session 的已知休市不合成 price bar，也不算缺股價。
- 每個應有 session 缺價、非 finite/非正價格或 quality 無效則指標 unknown；不刪列、不填前價。
  完整週任一所需日列無效即該週無效，保留該週位置並重設週指標暖機。
- SMA_N 在連續 N 個有效 bars 才已知。EMA_N 第 N 個有效 bar 是 N-bar SMA seed；
  其後 `alpha=2/(N+1)` 遞推。gap 後重新計連續有效 bars，日/週 N 固定 20/60/120。
  EMA 暖機不是只保留最近 N 列：每一 cutoff 重算須包含 seed 後全部遞推歷史。
- 現有 technical-daily 無 EMA120；未來 study 模組可重用數學，不修改 shared family 或宣稱現有欄位已齊。

feature state 採 `true/false/unknown`（儲存時可用 1/0/−1，須明列編碼）；
unknown 原因另列，不把型態的 N/A、缺值或暖機不足壓成 false。
D、W 是所有 operands known 才 bool，即使已見一個 false 也不能短路掩蓋未知 operand。
R 需要當期 20 個 D 皆 known；cross 還需要 R_prev known。
完整週 W 序列與 provisional 診斷序列分離，provisional 永遠不更新完整週 EMA 狀態。

## 比較前的邏輯列（未承諾發布逐日表）

後續實作須能在合成資料檢視下列欄位；它們可以是 in-memory typed arrays，不能因此新增第二套逐日資料倉庫：

| 維度/欄位                                               | 語義                                                                       |
| ------------------------------------------------------- | -------------------------------------------------------------------------- |
| `security_id, t, session_index, t0_year`                | 原訊號日，原 t 曆年，不用 outcome 年或週 ISO year 分層                     |
| `generation, decision_cutoff, price_basis`              | 所有數值的計算 lineage；as_of 不冒稱 PIT                                   |
| `S6, D, R, R_prev`                                      | 當日資格、daily bull、20 日 bool 比例及前一共同 session 比例；unknown 分開 |
| `week_id, week_complete, week_confirmed_at, W, W_prev`  | 最近完整週與前週 bool；weekly-turn 只在新確認日                            |
| `weeklySMA20/60/120, weeklyEMA20/60/120, WeeklyClose`   | 同 cutoff、同尺度的六值與正分母；連續有效週暖機                            |
| `density, rank_percentile, rank_pool_stock_n, P_member` | std(ddof=0)/WeeklyClose；P 內 ascending average-tie percentile，含自己     |
| `M, mask_reasons`                                       | mission 四條共同可比較資格；total excluded 去重，reason 可重疊             |
| `weekly-turn, cross50, cross70, dense, CORE`            | raw feature states，不依 outcome/年代改寫；比較一律再交同 M                |
| `raw_member, cooled_member, admitted_member`            | 形成候選→canonical cooldown→品質/M 的順序可稽核，不補選                    |
| `effective_label, event_main_eligible, calendar_full`   | 各 target/horizon 的原 t 結果；沿 PR61，不重錨                             |

P_t 是當日 S6 且六週線/分母 known-valid 的全集；必須完成 1,942 檔母體的當日 barrier 才排名。
先 P 排名、後 M，比較/結果缺失不反向篩 P。空池或 barrier/池身分未知時 dense unknown。
M 需 S6、當日日 bull operands、R 當期 20 日序列與前值、最近/前週 W、六週均線/分母及可知 rank 池。
CORE 的 atoms 沿 canonical，不另造主遮罩；unknown membership 另列，不能當已知 false。
輸出須驗證所有 candidate 與兩 baseline 的 M identity 相同。

coverage 至少列 era×reason 的 S6_n、M_n、total_excluded_n、逐原因 count、candidate true/false/unknown、rank_pool_stock_n。
逐原因總和可大於 total_excluded_n；分母、reason_scope 與剩餘量清楚記錄，不相加成不實樣本數。

## canonical 冷卻、結果與守恆

canonical 入口沿 `momentum_only_v1.set_members / cooled / groups / group_counts` 與 PR61 outcome 語義；
不得另寫標籤或改分母迎合新訊號。

1. 每股/每 group 形成全期間 raw candidate membership，S6 canonical eligibility 後做 earliest-first 冷卻；
   下一保留 index 減上一保留 index `>20`。
2. 再套共同 M 與 quality/outcome overlays。拒絕的保留事件仍已佔冷卻位置；不補選、不依 label/era 重啟。
   [0,20,21]→[0,21]；若 0 後來被 M 排除，不能改成保留 20。
3. daily 不冷卻；cooled candidate 對各自 cooled C-base/CORE，不能拿 cooled candidate 對 daily baseline。
4. labels 為原 t 的倍數×H，effective label/eligibility 與 PR61 C-base-daily 一致；
   結果窗缺價/不明跳動沿 canonical 品質規則，不用訊號的 120 週暖機窗替換結果品質 lookback。

每一 group×target×horizon×stock×原 t 年保存整數：

```text
event_n, known_n, hit_n, loss_n, flat_win_n,
unknown_n, censored_n, full_unknown_n
known_n = hit_n + loss_n + flat_win_n
event_n = known_n + full_unknown_n + censored_n
unknown_n = full_unknown_n + censored_unknown_n
```

上述是本研究沿 PR61 `group_counts` 的 canonical partition；未知品質套 effective-label overlay，
不丟棄 event。若未來 adapter 出現 full-calendar known 卻非 main-eligible 的額外狀態，須明列
PR17 `excluded_known_n` 並停止查明契約不匹配；不能把它塞進 full_unknown 或默默破壞守恆。
unknown 與 censored 可重疊，因此不能用 `known+unknown+censored` 作互斥總數。
censored 即使已觀測 hit 仍不進 known/hit，另列 `censored_observed_hit_n`。

`hit_rate=hit_n/known_n`、`loss_rate=loss_n/known_n`；loss 是未到倍數且期末收低。
full-calendar hit bounds 為 `hit/(known+full_unknown)` 與 `(hit+full_unknown)/(known+full_unknown)`，
所有零分母率/界均 null。censored/unknown/full_unknown、observed-hit 與品質原因並列，不重標為主 hit。
distinct_stock_n 沿 canonical all-event stock 集合去重；另可保留 known-stock 數，不能偷換 30 股門檻的定義。
比較兩臂的 cooled known_n<100 或 distinct_stock_n<30 時 `insufficient` / `inseparable`，不宣告無優勢。

## 有限輸出矩陣與 paired bootstrap

未來最終結果僅小型聚合表，不發布逐日價格/指標；具體檔名由後續 bounded implementation 登記。

| 邏輯表                | 唯一列身分/必要欄位                                                                                                                                   |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| summary / annual      | candidate或baseline×cadence×target×horizon×era（annual 為原 t 年）×row_kind；全部整數 counts、distinct、rates/bounds、coverage、sample_sufficient     |
| contrasts             | candidate×baseline×target×horizon×cadence×era；primary/secondary、hit_diff/loss_diff、兩臂分母與缺值原因                                              |
| intervals             | contrast×bootstrap_type×statistic；seed、reps=2000、lower/upper、valid_replicate_n、null_replicate_n                                                  |
| coverage / mask audit | era×reason_scope×reason；重疊原因與去重總量、P/M 身分與小池分母                                                                                       |
| lead-lag              | cross50/70×era；trigger_n、turn_observed_n、false_lead_n、unknown_n、evaluable_n、false_lead_rate                                                     |
| episode timing        | 5x/10x H504×candidate×CORE 配對；episode counts、matched/unmatched/unknown、paired sample n、first offsets/price ratios/paired differences 與缺值原因 |

primary 是四 candidate×{2x/H252,5x/H504}=8 格，每格對 C-base-daily 與 CORE，16 contrasts。
secondary 是剩下六 labels×四 candidate=24 格、48 contrasts；六 labels 在 mission 完整列出。
cadence daily/cooled、era all/2010–2012/2013–2018/2019+ 是固定分層，不以切片另挑主格。
row_kind 為 full/drop_best_year/drop_best_stock；drop-best 依 canonical eligible hit 最多，平手年取最早、股取代號最小，
重組整數 counts/stock 集合，不平均率，不改主判讀。空格保留、null 分母不刪列。

累加使用足夠寬整數（跨 stock/year 至少 int64）；distinct stock 以集合重組，不能加總年度 distinct。
stock bootstrap seed=20261030，two_way seed=20261031，各 2,000 次，95% percentile。
固定 universe 股票索引及原 t 年索引，零事件 stock×year 仍保留；同 replicate 的所有 candidate/baseline 共用權重。
stock 抽股票 cluster；two_way 獨立抽股票與年份 cluster，格子權重是兩者次數乘積。
two_way 同 seed 的 RNG 固定先 stock 後 year，記錄實作/generator、排序與參數；不改 seed 選結果。
以加權總 counts 算率後相減；零分母該 statistic=null，percentile 只對有限有效 replicates 算，
逐 statistic 公開有效/無效次數，無有效 replicate 則 CI=null，不把 null 當 0。

## lead-lag 分母與可知性

對同 M 的 cross 原始每日觸發 t，在共同 index `(t,t+20]` 看完整週 turn；窗口不含 t。
三態優先序為：已有已觀測 turn→true；否則到期且所有所需週確認/turn 狀態 known→false；其餘→unknown。
未滿窗就算已經過某個週末仍不判 false；未知不可當未 turn。

```text
trigger_n = turn_observed_n + false_lead_n + unknown_n
evaluable_n = turn_observed_n + false_lead_n
false_lead_rate = false_lead_n / evaluable_n
```

零 evaluable_n 為 null。unknown 所需 calendar/feature 原因與截尾分列；已觀測 true 不因其餘未知降回 unknown。
本診斷不是倍數結果或交易訊號，也不添加主要 contrast。

## episode 配對與共同價格基準

只用 PR61 既有 H504 5/10 倍 episode，保持其 anchor/peak/episode_id 定義，不新選成功段、不重算 outcomes。
搜尋窗口為共同 session 的 `[anchor−20, peak]`（兩端含；calendar 起點不足明列截短/未知），
candidate 與 CORE 均在同一 M 上找首次訊號；無訊號與可能存在更早未知訊號分開。
已觀測 first 但前綴有 unknown 時，保留 observed match，first_timing_certain=false，不硬當確定最早。

兩臂已可判首次訊號且同價格基準才計 paired timing/price difference；
unmatched/unknown、不完整價與缺配對另列，不補零，也不只公布雙方成功的比率。
固定 episode 的價格參考 cutoff 為既有 peak 收盤，使用同 G、該 episode 共同還原基準內的
anchor/peak/兩臂訊號價；這是事後診斷，不能回流改訊號。
若無法在 anchor−20..peak 取得一致基準則該數值診斷 unknown，不能混各日期 as_of 價。

```text
offset_arm = first_signal_index_arm - anchor_index
entry_ratio_arm = common_basis_signal_close_arm / common_basis_anchor_close
remaining_ratio_arm = common_basis_peak_close / common_basis_signal_close_arm
earlier_diff = offset_candidate - offset_CORE
cheaper_diff = entry_ratio_candidate - entry_ratio_CORE
```

差為負才表示該 pair 更早/更便宜；率與分位數只取可判 pair，公開 paired_sample_n 與未配對總數。
成功 episode 的選擇偏差須在報告明示，不能據此單獨作預測力或帳戶賺錢證據。

## 未啟用 extension 與交付

minute/2B 在本 definition 的執行矩陣中為 inactive，沒有輸入、結果或 runtime。
未來 minute 須另核 timestamp 邊界、official session hours、完整 60/30 分鐘桶、零交易/遺失與因子 known_at；
全部依賴窗 minute OHLC（含 EMA seed/全遞推歷史）以同 cutoff 的
`AdjustedClose(d|as_of=t)/RawClose(d)` 正有效因子換算。
盤後資訊不能回標盤中，同週不能豁免還原；日內事件不能由單因子表示則 unknown/stop。
真週六/假週日依官方 calendar，不按 weekday 刪除。2B 僅未來字典 L3/pattern-scan.v1 確認日與 dense 交集一組，非 F20/F21/HHHL，不重跑家族。
獨立 task 與結果清單、owner/data/compute gate 皆未解除。

後續 synthetic acceptance 必須覆蓋 mission 表中全部案例。本包只驗文件/links/card schema 與正常 CI，
不宣稱通過未存在 runner 的驗收。任何實際結果須依 [artifact integrity](../../docs/en/artifact-integrity.md)
只對 final results 記 SHA-256，另記 code commit、定義/參數、輸入說明與固定 G 的 lineage；
不得 hash source/intermediate 來改寫 frozen evidence。新結果/可重用資產的發布與 program index 是後續 task 的責任，非擴大本包 allowlist。

[study card](study.json) 保持 `not_evaluated`；data_period、report、account_run、delivery_state、scratch_run 與無實物 provenance 為 null/空。
沒有市場結果、無研究報告/收據、無真實資料驗證、無部署；後續工作先回到 mission 的 owner/data/compute 關卡。
