# 完整彙總的查詢 schema v1

公式與選擇規則以 [mission](mission.md) 為準；本檔只說明結果欄位與查詢。完整邏輯 parquet 以 `publication-v1/receipt.json` 宣告，Git 分段由 `research_core.hhhl_variants_query.load_summary()` 在記憶體驗 hash 後重建。單片不是可獨立查詢的 parquet，不能混入其他版本分片。

## 列的身分

`row_kind` 的基本列是 `baseline`、`single`、`candidate`、`Kdistribution`、`flag`、`reverse_flag`、`legacy_cross`、`near_high`。`year` 與 `drop_best_year` 是同一基本列的固定切片，原種類在 `base_row_kind`；年度空列保留。`near_high` 是 t0 的描述比例，沒有 horizon、結局或年度搜尋。

邏輯身分依基本列使用 `cohort_id/split_id/horizon/candidate_id/feature_id/bin_id/flag_id/landmark/flag_state/return_bin`，再加 `row_kind/year/removed_year`。不適用的身分欄為 null；不能只用 candidate_id join 全表。P-all 是 clean／over 的聯集報告，不能與兩子群相加。旗標的 `return_bin=pooled` 與四個互斥漲幅層也是同一群體的兩種切片，不能相加。

| 欄位                                             | 分母與解讀                                                                                             |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| `calendar_full_n`                                | t0+H 不晚於共同日曆末日；不等同 full price path。                                                      |
| `hit_n/loss_n/flat_win_n/unknown_n`              | 完整日曆事件的互斥結局，四者之和為 calendar_full_n。hit 後缺價不撤銷已知 hit。                         |
| `known_n/known_security_n`                       | hit+loss+flat-win 的事件數／該分母的 distinct original code。事件率不能稱股票率。                      |
| `hit_rate/loss_rate`                             | 分母 known_n；零分母 null。loss 是從未翻倍且期末低於 anchor 的價格描述，沒有交易成本或進出場。         |
| `hit_lower/hit_upper/loss_lower/loss_upper`      | 完整日曆總數含 unknown 的界；不把 unknown 當失敗。                                                     |
| `censored_n/censored_hit_n/censored_unknown_n`   | 不完整日曆窗口；不返回主率分母。截尾 observed hit 只作診斷。                                           |
| `reason_counts/outcome_reason_counts`            | 互斥特徵原因／原結局未知原因的 JSON 子帳；兩者不混用。                                                 |
| `drawdown10_full_* / drawdown20_full_*`          | 全 H 內 close≤.90／.80 anchor 的三態計數、自己的 known_n/all_n/rate/lower/upper；僅完整日曆。          |
| `before_hit10_* / before_hit20_*`                | 同門檻、首次 hit 前的歷史，nonhit 看全 H；自己的分母不能用全期限分母替代。                             |
| `hit_then_below_anchor_n/hit_endpoint_unknown_n` | 已知 hit 後期末低於 anchor／末價未知，保留為 hit 的子診斷。                                            |
| `reference_cnh_* / reference_c52w_*`             | 同 split/H/條件/年度的控制計數、率與差值；pattern-only 或混合條件用未加條件控制，reference_kind 明列。 |
| `reference_pall_*`                               | pattern-only 條件對未加條件 P-all 的輔助比較。                                                         |
| `removed_year/reference_removed_year`            | 目標列刪除 hit 最多的 t0 年；控制移除同一年，不能拿控制自己最好的年替代。                              |
| `small_sample/high_loss`                         | known<300／比可算 C-nh loss rate 高至少10pp 的註記；沒有淘汰或策略及格意義。                           |

## 三種旗標表

| 列／riskset                            | 分母                                                                                                                                                 |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `flag/new_no_hit_valid_prefix`         | 到 L 尚未首次翻倍，且 t0..L close 可觀察。跌破支撐仍保留；三個 flag_state 各報最終結局。riskset_n 含本狀態的完整及截尾事件，主率仍只用完整已知結局。 |
| `reverse_flag/all_calendar_full_known` | 全部完整日曆且結局已知的 P；hit 看首次 hit 前，nonhit 看 L 或 H。hit_flag__／nonhit_flag__ 各有 known/all 三態及界，旗標未知另外報告。               |
| `legacy_cross/legacy_active`           | 原 active 時序口徑，只作 old／recent_far 上方線延伸。不能與新 riskset 合併；無上方線列為不適用。                                                     |

`cost_denominator_n` 是全部完整窗口最終 hit，旗標 unknown 也留在分母；`cost_lower/cost_upper` 是嚴格早於首次 hit 的觸發比例界。這是未來停損研究的素材代價，不是模擬交易損益。`trigger_return_p10/median/p90` 是首次有效觸發日 close/anchor−1 的 linear quantile，缺價格另報。`scope=full` 的 L 恰等於 H，其他 scope=landmark 的 L 固定5／10／20／40。

## 逐筆版本

primary 的版本位置及外部 manifest pin 在 publication receipt。所有 relative paths、bytes、hash、Parquet rows、original code 都由 manifest 宣告。`observations/` 的鍵是 `(cohort_id,event_id,horizon)`；`features/` 每個 common-calendar 股票日一列，24個值及各自 `_bin/_status/_reason`；`flags/` 只存原 clean／over 事件，P-all 是彙總時的聯集；`pivots/` 保留低點 extreme／confirmed 兩個 index。`daily/` 是同日曆順序的計算輸出，不能把缺日壓縮。

使用 `python -m scripts.query_hhhl_variants --verify` 驗完整彙總，exact filters 與逐筆 `--event/--part` 見 [data contract](data-contract.md)。小型彙總不依賴本機逐筆資料；逐筆缺件或 hash 不符明確失敗，不補下載。
