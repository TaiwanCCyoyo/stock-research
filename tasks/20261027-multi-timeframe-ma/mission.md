# S7：日／週多週期均線與大漲機會

狀態：**S7-A mission 草稿，等待 owner 合併；`not_evaluated`。**
本包只交付本文件、[資料契約](data-contract.md)與 [study card](study.json)，沒有 runner、資料讀取、標籤計算或市場結果。

日線轉強、整週轉強及週均線密集，能否比同樣可比較的一般股票日與 CORE 更早找到大漲機會？
本研究比較訊號的歷史機會分布，不模擬成交、帳戶報酬或策略核准。
研究母體全期已暴露；任何後續歷史評估都是描述，不能當成新的確認集。

## 來源與交付界線

本設計承接 [research roadmap 的 S7](../../docs/en/research-roadmap.md)、
[PR61 momentum-only mission](../20261021-momentum-only-doubling/mission.md)與其
[data contract](../20261021-momentum-only-doubling/data-contract.md)，依
[owner contract](../../docs/en/research-owner-contract.md)及 [research foundation](../../docs/en/research-foundation.md)保留證據與授權邊界。
價格、指標、型態先查 [既有資產](../../docs/en/research-program.md)、
[衍生資料定義](../../docs/en/research-derived-data.md)與 [pattern dictionary](../../docs/en/pattern-definitions.md)。

- 唯一寫入範圍：`tasks/20261027-multi-timeframe-ma/{mission.md,data-contract.md,study.json}`。
- 不改 roadmap、program、CI、shared family、PR17、S1/S2、歷史 mission 或 frozen evidence。
- 本包不讀市場價格、minute、labels、holdout、forward outcomes 或正式研究 root；不作 parity/probe、下載、hold、世代更新、研究計算、排程或部署。
- 只核對文件、相對連結、card schema 與正常 hooks/CI；下列合成案例是後續 S7-B 的驗收規格，並非本包已執行的結果。
- 不因缺 coverage 改 raw 價、縮到 2013、拼接世代、增加 threshold 或私造 shared cache。

## 啟動關卡

S7-A 合併僅代表研究定義存在。任何實際資料、labels 或 evaluation 之前須重新確認：

1. owner 已合併本 mission，parent 已完成 Astra 方法審查，後續 implementation 是另開的 bounded task。
2. 原 owner 無同範圍工作衝突，S1/S2 長計算已完成，或 owner 明確重新排序；未知 session/程序狀態不能當作空閒。
3. 通過單一長計算 admission：先有有界合成驗收與時間、CPU、記憶體、I/O、序列化成本量測，再明定 worker、in-flight、記憶體及 scratch 範圍。
4. 可合法讀取同一固定 generation 的合格 `as_of_inputs`、PR61 母體與日曆，且必要歷史來源/品質/可得性限制已公開。
5. 實際讀取遵守 [producer/shared 操作規則](../../docs/en/stock-agent-operations.md)；owner/data/compute 三道 gate 不因 mission、程式或 CI 合併而解除。

本 mission 不建立新的前瞻 cohort，也不開啟 PR61 的確認樣本。

## 固定母體與決策時鐘

- PR61 的 1,942 檔 ordinary-reference；共同 calendar 為 2010-01-04..2026-10-12 的 4,110 sessions。
  母體定義沿其 [凍結名單](../20261021-momentum-only-doubling/pr17-universe-v1.json)，本包不讀該名單內容。
- 所有期間已暴露，只作描述；年代固定 `all`、`2010-2012`、`2013-2018`、`2019+`。
  保留 2010–2012 品質、存活偏差與暖機造成的樣本損失。舊 cache 建議從 2013 開始不覆蓋本 mission。
- S6 沿 PR61：ordinary-reference、60 個連續有效研究價、當日正量、前 20 日原始成交額皆可知且均值至少 NT$1m；上市/下市依當日資格。
- 決策 t 為 Asia/Taipei 的共同 session 收盤。所有數值依同一固定 generation 的
  `read_adjusted_daily("reference_factor_adjusted", generation=G, as_of=t, calendar=calendar[calendar<=t])`
  語義重算，只納入 cutoff 前事件；不截斷最新 technical 表充作歷史值。
- `as_of` 是計算截止，不是來源在歷史當下已公開的完整 PIT 證明。來源修訂、known_at 不足與 calendar 可知性須另記；無合格 `as_of_inputs` 就停止，不自動 update。

## 固定數學與日線訊號

日與週使用同一套 N=20/60/120 數學：SMA_N 為最近 N 個連續有效 bars 的平均；
EMA_N 先用 N-bar SMA 為種子，再以 `alpha=2/(N+1)`、`EMA=alpha*Close+(1-alpha)*EMA_prev` 遞推。
缺價或品質無效重設暖機，不刪共同 session、不填前價、不把 unknown 當 0。
延用 [technical_daily_v1](../../research_core/technical_daily_v1.py) 的數學運算語義；
現有 technical-daily 只有 EMA5..EMA60，沒有現成 EMA120。後續新 study 模組補足 EMA120，不改既有 family 或 pinned kernel。

```text
D_t = (Close_t > SMA20_t)
      AND (Close_t > Close_{t-20})
      AND (EMA20_t > EMA20_{t-1})
R_t = sum(D_{t-19}, ..., D_t) / 20
cross50_t = (R_{t-1} < 0.50) AND (R_t >= 0.50)
cross70_t = (R_{t-1} < 0.70) AND (R_t >= 0.70)
```

D 的所有 operands known 才有 bool；R 的 20 個 D 全 known 才有數值。
每個過往 D 依其自身決策 cutoff 的定義保留，不能用未來公司行動重寫歷史 bool。
cross 的任一 R 未知則 unknown；等於門檻的前值不構成由下往上穿越。
強 bull 額外要求 `SMA20>SMA60>SMA120`，只作次要描述，不增加主要 candidate。

## 完整週與週轉強

- 用 Asia/Taipei ISO week 和共同交易日曆分組，不用資料中最後一列猜週末。
  截止時可知 calendar 必須覆蓋該週結束，且該週最後交易 session 已收盤，才是完整週。
  若資料在週三截止但 calendar 尚不能確認本週結束，該週仍未完成；calendar coverage 不足為 unknown。
- 真正補行週六保留；已知非交易假週日排除。臨時停市只有在截止時已可知才影響週確認，不能預知未來停市。
- WeeklyClose 取完整週最後 session 收盤；該週所需日列缺價/quality 無效則整週 unknown，並重設週均線暖機。
  已確認零交易日不偽造成遺失或虛構價格；資格與價格品質分別保留。

```text
W_w = (WeeklyClose_w > weeklySMA20_w)
      AND (WeeklyClose_w > WeeklyClose_{w-20})
      AND (weeklyEMA20_w > weeklyEMA20_{w-1})
weekly-turn_t = 本日確認新完整週 w AND W_{w-1}=false AND W_w=true
```

W 所有 operands known 才有 bool；前週未知不能視作 false。
weekly-turn 僅於週確認日觸發一次；下週每日不能重複沿用 true。
完整週與週內暫算分開。若保留週內診斷，每天從上一完整週 EMA 狀態複製後更新一次；
不把同週每天的暫算串成五次/六次週 EMA 更新。暫算不進本次四 candidate。

## 週均線密集與共同遮罩

最近完整週的六值為 `weeklySMA20/60/120`、`weeklyEMA20/60/120`。
`density_t=std(六值, ddof=0)/WeeklyClose`，六值與分母必須在同一決策 cutoff 的共同還原尺度上，且 finite、分母為正。

當日 rank 池 `P_t` 是 S6 合格且六週均線及分母全 known-valid 的股票；跨股 barrier 完成後，
在 P_t 內 ascending `rank(method="average", pct=True)`，含自己，`percentile<=0.10` 為 dense。
先在 P_t 排名，再套 M；不因 outcome 或某 candidate 改 rank 池。
平手不硬湊 10%，小池可能沒有 dense；公開 `rank_pool_stock_n`。空池或無法得知完整池則 unknown。
dense 每日可連續 true，輔助冷卻仍按下述 canonical 規則。

主比較唯一共同遮罩 `M_t` 同時要求：

1. 當日 S6 合格。
2. 當日日 bull 所需 operands，以及 20 日 R 序列與 R 前值可知。
3. 最近完整週與前完整週 bull 可知。
4. 六個週均線及密集分母全 known-valid，當日 rank 池可知。

四 candidate、C-base-daily、CORE 均使用同一 M。CORE 為 canonical `A1&A2`，不另選 atoms 或門檻。
baseline 不是直接搬 PR61 的未遮罩總表；必須在相同 M 上重組。
逐原因、逐年代列 S6→M 的 coverage 損失，原因可重疊，總排除數只算一次。
120 週暖機按連續有效完整週計，不保證某年所有股票可用。
較早可用的日線結果只可附描述，不能拿較寬 mask 的日線與主週線作優劣比較。

## 主要與次要比較帳

四個 candidate 固定為 `weekly-turn`、`cross50`、`cross70`、`dense`。

| candidate   | 2x/H252 | 5x/H504 | 每格 baseline              |
| ----------- | ------- | ------- | -------------------------- |
| weekly-turn | primary | primary | 同 M 的 C-base-daily、CORE |
| cross50     | primary | primary | 同 M 的 C-base-daily、CORE |
| cross70     | primary | primary | 同 M 的 C-base-daily、CORE |
| dense       | primary | primary | 同 M 的 C-base-daily、CORE |

**8 個 primary signal-label 格，對兩 baseline 共 16 個 primary contrasts。**
secondary labels 固定為 `3x/H252, 5x/H252, 10x/H252, 2x/H504, 3x/H504, 10x/H504`：
4×6=24 格、48 個 secondary contrasts。沒有 H126 或臨時新 threshold。
daily 是主要口徑；cooled 與上述四年代均為預定分層，不事後挑表或重新當成額外主要格。
每個 contrast 同時報 hit 差與 loss 差等指標，不把指標數誤稱為 signal-label 格數。

## 原 t 標籤、冷卻與計數

沿 PR61 原 t 的 effective-label / event_main_eligible，使用
[momentum_only_v1](../../research_core/momentum_only_v1.py) 與
[PR17 dictionary](../20261013-pattern-scan/data-dictionary-v1.md) 的語義。
不重錨週初、確認後一日或較便宜價；hit 是觀察窗內曾到倍數，loss 是未達倍數且期末收低，均非帳戶損益。
known/full_unknown/censored 守恆；unknown 保留與 censored 重疊，censored-hit 不進 known 或主 hit。
比率分母為 0 時 null；完整 counts、品質覆蓋與上下界依 [資料契約](data-contract.md)保留。

cooled 每股、每 group 最早優先，下一保留 index 與上次保留 index 必須 `>20`。
先形成完整候選並做 S6 canonical 冷卻，再套品質/比較 M，拒絕不補選、不重啟冷卻；
不能先篩 M、結果或年代後重做冷卻。各 group 的冷卻獨立，daily 基準對 daily，cooled 對 cooled 基準。

每項比較另報兩臂冷卻口徑 known_n 與 distinct_stock_n；任一臂 known_n<100 或 distinct_stock_n<30，
記 `sample_sufficient=false`、`insufficient`（樣本不足），解讀為 `inseparable`（分不開）。
這是 PR61/PR17 的最小樣本語義，不是新的策略失敗或無優勢結論；daily 巨量列數不能豁免。

## 不確定性與事前資源建議

- 先建立 stock×原 t 曆年整數 counts，再跨股/跨年相加後算率，不能平均股票率或年份率。
  distinct stock 用集合去重，不加總年度 distinct 數。
- paired stock bootstrap 2,000 次，seed `20261030`；paired two_way 2,000 次，seed `20261031`。
  stock 整檔歷史重抽；two_way 將股票、原 t 年各自重抽的次數相乘為 stock×year 權重。
  每 replicate 的全部 candidate/baseline 共用同一組權重，從同一固定股票/年份索引重組。
  同一 two_way RNG 以固定次序抽 stock 再 year；正式實作須記錄 generator/演算法與索引順序，不另挑 seed。
- 報 95% percentile CI；zero-denominator replicate 為 null，逐統計量公開有效/無效 replicate 數。
  沒有有效 replicate 時 CI=null。兩種 CI 都列，不採較窄者；跨年重疊 outcome 與稀疏年份的殘餘相關照實揭露。
- 年代、loss/unknown/censored/full_unknown、樣本與 coverage 全列；`drop_best_year/stock` 僅作預定集中度描述，不改主判讀。
- 事前資源建議：若沒有任何候選至少一 primary 格，相對匹配 C-base 的兩種 CI 均滿足
  hit 差下界>0 且 loss 差上界<=0，建議不擴張方法；CORE 差仍完整報告。
  這是事前研究規劃建議，不是 owner 策略 pass/fail，不宣稱多重比較校正後顯著，也不因結果改格子/門檻。

## lead-lag 與成功 episode 描述

cross50/70 的原 t 後 `(t,t+20]` 共同 sessions 內，是否出現完整週 turn：
已觀測到 turn 為 true；到 t+20 所需週確認狀態皆 known 且未 turn 才是 false lead；
未滿窗或窗內有 unknown 而無已觀測 turn 為 unknown。false-lead 分母只含可判觸發事件，未知另列。
同日 t 的 turn 不算後續 turn，不延長到下一個有報價日。

更早/更便宜只用 PR61 既有 5x/10x H504 episode，在固定 `anchor−20..peak` 內首次訊號與 CORE 配對。
未出現訊號另列，不補 0；更早距離以共同 session 計。
訊號價、anchor 價及 peak 價在同一 episode anchor/peak 限定的共同還原基準比較，
不能將不同日期各自 as_of 價直接相除。更便宜為各臂訊號價/同一 anchor 價的配對差；完整定義見 data contract。
這是只挑成功段的事後描述，不能單獨證明預測力；unknown、缺配對與未出現的分母完整公開。

## 未啟用延伸：minute 與 2B

minute 與 2B **不進本次矩陣**。任何延伸先另開 bounded task，明定結果比較清單，再過 owner/data/資源 gate。

- minute 先核實 timestamp 是起點或終點、official calendar/session hours、零交易 vs 遺失、完整桶與因子 known_at；未確認就停止。
  預定 09–10、10–11、11–12、12–13 各完整 60 分鐘桶；13–13:30 另列 30 分鐘，不能混稱第五個 60 分鐘桶。
  只用 cutoff 前完整桶，不造分鐘，不把收盤後因子回標成盤中可知。
- 所有 MA/EMA 依賴窗內的 minute OHLC，包含 EMA seed 與全遞推歷史，均需以
  `AdjustedClose(d|as_of=t)/RawClose(d)` 的正且有效因子換算至相同基準。
  同週比較也不能豁免公司行動；因子未知/衝突，或日內事件無法由單一日因子表示時 unknown/stop。
  已知假週日排除、真補行週六保留，不能只按 weekday 清洗。
- 2B 僅允許未來沿字典 `L3/pattern-scan.v1`（legacy F33 後續收復）的確認日定義，與 dense 交集一組；
  不換成 F20/F21/HHHL，不重跑 12 家族。本階段不讀 minute 或 pattern outcome，也不聲稱延伸可執行。

## 後續 S7-B 合成驗收規格

以下均使用人工小型 fixture、記憶體及 task 自建暫存 child，不接真實資料。實作包須逐項交證據：

| 邊界                     | 必要斷言                                                                                                                                       |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| 除息/分割跨 20/60/120 窗 | 同 cutoff 一致正比例還原，SMA/EMA 同比例、bull/cross/rank 與 density 不變；事件 cutoff 後不得影響當時訊號                                      |
| 因子未知/衝突            | 不用 raw/1/最新因子替代；unknown 或 fail closed，完整原因保留                                                                                  |
| EMA120                   | 第 119 個連續有效 bar 未知，第 120 個以 SMA seed，第 121 個按 alpha 遞推；週版同理                                                             |
| missing/quality reset    | 無效列保留共同 index，SMA/EMA 重暖機，R 及 W 不跨 gap 偷接                                                                                     |
| 週三截尾/缺 calendar     | 未完成週不變成完整週，coverage 不足為 unknown                                                                                                  |
| 週六/臨時停市            | 真週六納入；停市公告可知前後分開，不預知；假週日不納入                                                                                         |
| 同週 EMA                 | 每日 provisional 都從上一完整週複製，只在確認完整週時提交一次                                                                                  |
| cross/weekly-turn        | 未知前值不當 false；R 前值等於門檻不重觸發；turn 確認日一次，下週不重複                                                                        |
| tie/small pool           | average-tie percentile 含自己；單股 rank=1、十股全平手 rank=0.55 均無 dense；不強制 top-k                                                      |
| 共同 M 與 P              | 四 candidate 和兩 baseline 同 M；先 P 排名，再 M；改 outcome 或 candidate 不變 rank，逐年代 coverage 可重組                                    |
| future append            | 固定 G 與既有 cutoff 前輸入/已知 calendar 不變時，append 未來價格/事件不得改既有已知訊號；不冒稱跨世代來源修訂不變                             |
| canonical counts         | full known hit/loss/flat-win、full unknown、censored unknown/hit 逐格守恆；censored-hit 不入 known，unknown 可與 censored 重疊；空格 rate=null |
| 冷卻 20/21               | 候選 [0,20,21] 保留 [0,21]；若 0 後被 M/quality 排除，不補 20、不重算冷卻；跨年代不重啟                                                        |
| paired counts/CI         | 分塊與一次整數聚合相同；兩臂共用權重、stock 去重；零分母 replicate=null；兩 seed 重現                                                          |
| lead-lag                 | 20 session 到期全 known 無 turn=false；未滿或 unknown 無 turn=unknown；即使其餘未知，已觀測 turn=true；t 不算窗內                              |
| episode                  | anchor−20..peak 首次訊號、未出現/unknown 分開；兩臂同 episode/同 mask，所有價格同還原尺度；不以 0 補缺配對                                     |

任何定義無法用既有公開 API 與上述合成資料表達、as_of/calendar 可得性不足、需修改 frozen code 或超出 allowlist 時，停止該動作回報 parent。
本包卡片保持 `not_evaluated`，不存在的報告、結果、收據、scratch、世代與 provenance 留 null/空；
owner 合併前不宣稱 mission 已核准，市場研究開始前不宣稱任何比較已通過。
