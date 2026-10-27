# Entry-window v1 資料契約

狀態：**規劃契約，尚未建立 runner、讀取本研究價格／標籤或產生結果。**
研究定義在 [mission](mission.md)，卡片為 [study.json](study.json)。本 PR 只有這三檔。
下列欄位／位置是未來獲准實作的要求，不表示產物已存在。

## 來源與讀取邊界

| 角色           | 來源／固定定義                                                                                                                                                                     | 限制                                                                    |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| 母體／日曆     | [PR61 契約](../20261021-momentum-only-doubling/data-contract.md)、[1,942 股清單](../20261021-momentum-only-doubling/pr17-universe-v1.json)，2010-01-04..2026-10-12、4,110 sessions | 不延長 cutoff、不刪缺價日、不依個股報價推日曆                           |
| 原訊號         | PR61 S6、CORE=A1∧A2、LEAD_B1=A1∧A2∧A3；[原 mission](../20261021-momentum-only-doubling/mission.md)                                                                                 | 缺值／暖機沿用，LEAD_B1 的 2015-06 前限制明列；無 S1/S2/S7              |
| 研究價         | adjusted-daily-v1 的 reference_factor_adjusted、price-basis.v2 與 PR61／PR17 品質                                                                                                  | 記固定 generation／as-of／日曆；不是完整歷史 PIT，不改舊研究            |
| 隔日報價       | RawClose_t 與固定 t+1 raw Open/High/Low                                                                                                                                            | 不還原、不重錨、不跳到下個有交易的個股日                                |
| 公司行動／品質 | 既有事件／報價品質來源，判定 (t,t+1] 的事件及覆蓋                                                                                                                                  | 有事件或不明排除主比較並報損失；不是盤前 PIT 過濾器                     |
| 官方限價       | 可用且合格的官方歷史參考價／上下限及來源                                                                                                                                           | 不足 unknown；one-price 不等於鎖漲停，不以 9.5% 補判                    |
| 原 t outcomes  | [PR17 字典](../20261013-pattern-scan/data-dictionary-v1.md)，PR61 C-base-daily effective-label／event_main_eligible；2x/H126、2x/H252、5x/H504                                     | 原 label gate、吸收式 hit/loss、unknown/censored 保留；不是開盤買入收益 |

後續先核對可重用來源／模組身份，不自建另一套訊號或標籤，不改 shared family。
不能為確認可用性提前開市場資料；母體、日曆、品質或標籤不能相容就停止回報。
依 [producer/worktree 安全規則](../../docs/en/stock-agent-operations.md)及
[artifact integrity](../../docs/en/artifact-integrity.md)，資料在正式位置原地唯讀，
不初始化子模組、不複製／連結資料到 worktree。
獲准執行時記輸入 fingerprint、generation、code commit／dirty／drift、定義及參數；
只雜湊最終結果，不雜湊或封存新 sources／中間檔。本任務不授權更新資料或 hold/release。

## 邏輯事件、共同遮罩與守恆

鍵為 `(set_id, cadence, security_id, t)`，set_id 為 CORE／LEAD_B1，cadence 為 daily／cooled20。
cooled20 先在完整原訊號集合 earliest-first 選出，再接報價及六帶。
t1 永遠是共同日曆下一 session；期末 no_next_session，停牌／缺開盤 no_open，不歸 above/below。
對每個集合、口徑及原 t 年代定義：

- `S`：所有訊號，`signal_n=|S|`。
- `Q`：有固定 t1、有效 RawClose_t／RawOpen_t1 且開盤比值可判的列，
  `next_quote_known_n=|Q|`；S 中其餘為 `next_quote_unknown_n`，
  附 no_next_session、no_open、invalid_raw_close 等互斥主要原因，可另有多重診斷。
- `M`：Q 中 `(t,t1]` 無公司行動，事件覆蓋與報價品質已知合格的共同乾淨遮罩，
  `clean_quote_n=|M|`，`quality_excluded_n=|Q\M|`。
  排除原因 corporate_action、event_quality_unknown、quote_quality_invalid_or_unknown 可重疊，
  去重總損失須獨立列出，不把原因加總誤當總排除數。
- 各帶 b 將 M 拆成接受 `A_b`、above `Rhi_b`、below `Rlo_b`，互斥且聯集為 M；
  六帶均使用 mission 固定端點與同一 M，不依帶改品質遮罩。
- 各原標籤 L 將 M 拆成 effective-label 的 known、unknown、censored，沿用原互斥分類；
  known 再拆 hit、loss、flat-win。保留原 outcome 與品質原因以供追溯。
  無價帶對照、接受、拒絕的 known 比較都從同一 `M∩K_L` 切出。

```text
signal_n = next_quote_known_n + next_quote_unknown_n
next_quote_known_n = clean_quote_n + quality_excluded_n
clean_quote_n = accepted_n + rejected_above_n + rejected_below_n
clean_quote_n = known_n + unknown_n + censored_n  (per label)
known_n = hit_n + loss_n + flat_win_n
known_n = accepted_known_n + rejected_known_n
hit_n = accepted_hit_n + rejected_hit_n
```

accepted／rejected 以及 above／below 各報 known、hit、loss、flat-win、unknown、censored。
另報 S、Q 的標籤狀態及 Q\M、S\Q 的 hit／unknown／censored 損失；
不能把遮罩外未知視為非 hit，也不能只在乾淨分母報漏失而隱藏排除部分。
distinct stocks 以股票集合聯集重組，不加總各年份 distinct 數。

## 比率與差距

| 欄位                                             | 分子／分母及語意                                                                  |
| ------------------------------------------------ | --------------------------------------------------------------------------------- |
| quote_accept_rate                                | accepted_n / clean_quote_n，開盤報價落帶比例，不是成交率                          |
| quote_reject_above_rate／quote_reject_below_rate | 各拒絕數 / clean_quote_n，不因 H/L 觸價改寫                                       |
| all_hit_rate／all_loss_rate                      | hit_n / known_n、loss_n / known_n，同 M 無價帶對照                                |
| accepted_hit_rate／accepted_loss_rate            | accepted_hit_n / accepted_known_n、accepted_loss_n / accepted_known_n             |
| accepted_hit_diff／accepted_loss_diff            | accepted 率減同 M、同標籤的 all 率；任一不可計即 null                             |
| rejected_hit_share                               | rejected_hit_n / hit_n，拒絕 hit 占同 M 所有 known hit，不是 rejected 組內 hit 率 |

缺值保留；分母零為 null，不補 0 或製造假觀察。
loss 是未先達標且期末收低，不是接受報價後的實際交易虧損。
H/L 的 range_touch、one_price、官方 limit_status 分列診斷，不能名為 filled／executable。

## 聚合、paired 區間與門檻

先存 `(set_id, cadence, band_id, label, security_id, t0_year)` 的整數 counts，再合計計率，
無價帶對照以同 M counts 配對。mission 的 24 主格與 12 次格在 all、2010-2012、2013-2018、2019+
全數保留；年代依原 t 年份，daily 主、cooled20 輔助。空格、零 hit、未知及截尾不省略。

paired stock／two_way 各 2,000 次，seed 分別 20261028／20261029。
股票母體為固定 1,942 股，年份為該年代固定日曆涵蓋的 t 年；無事件格為零 counts。
stock 整股重抽；two_way 的股票與年份獨立重抽，stock×year 權重為兩者次數乘積。
每 replicate 對六帶、接受／拒絕及無價帶對照共用權重，先重組 counts 再求率與差距。
各方法報 95% percentile 區間、有效 replicate 數及零分母 replicate 數；
零分母 replicate 值為 null、不補 0，全部不可判時區間兩端 null。
後續實作須固定權重生成次序並通過合成 paired 驗收，不能各臂獨立重抽。

每格列同年代、遮罩與標籤的 daily／cooled20 known_n、distinct_stock_n。
冷卻對應格 known_n<100 或 distinct_stock_n<30 記 insufficient；接受／拒絕各臂分母與股票數亦展示。
門檻只限制可判讀性，不用小樣本率排名，不形成策略 pass/fail。

## 後續產物（尚未建立）

未來獲准 runner 的逐股／逐筆中間資料進 shared root labelled scratch，
不把 worktree .tmp 當實驗資料家。大型最終結果依既有三個資料家規則存放並索引；
小型完整 counts／摘要可於本 task 的 results/ 交付，不公開 raw 每日價格向量。

| 預定產物          | 一列／必要資訊                                                                          |
| ----------------- | --------------------------------------------------------------------------------------- |
| 分母與損失表      | set×cadence×era；S/Q/M、互斥報價缺失、品質原因與去重損失、股票數、各階段標籤狀態        |
| 完整比較表        | cell_id×cadence×era；全部 counts、接受／拒絕 rates、原 hit/loss、配對差距、insufficient |
| stock×year 整數表 | 固定鍵與全部分子／分母／標籤狀態，可重組完整表與區間，不含 raw 價格向量                 |
| bootstrap 表      | cell_id×cadence×era×方法×統計量；seed、2,000 次、95% percentile 區間及可判次數          |
| 診斷表            | H/L range_touch、one_price、官方限價 known/unknown 與來源／未知原因，不列假成交         |
| 收據與報告        | 全部比較、年代／暴露限制、最終檔 SHA-256、code、generation／輸入說明及停止原因          |

未來結果須完整交付，不能只交最有利格或只有卡片。
當前沒有 report、receipt、published result 或 scratch，卡片相關欄位為 null／空陣列；
verdict=not_evaluated，data_period=null 表示尚未評估，計畫期間只寫在 mission。
無原始報告時 reader 的 source_unavailable 提示是如實狀態，不虛構 excerpt 來消除它。

## Gate 與本次驗證

本次只驗三檔、相對連結、六帶及 24／12 格、既有卡片 schema、正常 hooks／相稱 CI。
mission「後續 runner 的合成驗收」列出的案例是後續前置要求，本 PR 不宣稱已跑或已通過。
owner 合併 mission 且原 label／研究 gate 允許前，不讀 t+1 實際價格、labels 或 gap distribution。
合併 mission 也不取消後續 runner、對齊、資源與正式單次計算關卡。
矛盾／缺口就停止回報，不探索參數、不寫正式資料、不改排程、不部署、不跑長研究計算。
