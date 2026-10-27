# Entry-window v1：訊號後隔日開盤的固定價帶研究

狀態：**規劃中，等待 owner 審閱及合併 mission；沒有執行研究或讀取本研究的隔日價格／標籤。**
本 PR 只新增本檔、[資料契約](data-contract.md)與 [study-card.v2](study.json)。
不新增 runner，不改 roadmap、research program、CI 清單、既有研究或前瞻紀錄。

## 問題、證據等級與範圍

訊號後共同交易日曆的下一個交易日，有多少開盤報價落在事前固定價格帶？
被拒絕的報價機會中，有多少原訊號之後仍達到既有大漲標籤？
**報價機會不是已證實成交，達標不是帳戶報酬。**
沿用 [PR61 mission](../20261021-momentum-only-doubling/mission.md)、
[PR61 契約](../20261021-momentum-only-doubling/data-contract.md)與 PR17 原定義。
2010-01-04..2026-10-12 整段已暴露，全部結果僅作描述，不開確認集、holdout 或前瞻結果。
六帶是 Astra 事前指定的有限診斷網格，不是 owner 風險偏好或已選好的最優規則。
完整呈現全部比較，不選最佳、不排名推薦、不設策略 pass/fail。

不研究帳戶、成本後報酬、資金／部位／整張或零股配置、E2 停損、E5 停利、操作卡或實際委託。
不新增 S1／S2／S7 訊號；它們的合併不構成 E1 的讀取或執行授權。

## 固定母體、原訊號與冷卻

- 固定 PR61／PR17 的 1,942 檔 ordinary-reference、4,110 common sessions，
  2010-01-04..2026-10-12。不改從 2019 起、不接另一資料集、不加截止日後新股。
- 沿用 S6 `base_eligible`：ordinary reference、60 個連續有效研究價、當日正量，
  前 20 日原始成交額皆可知且平均至少 NT$1m。資格及條件只使用 t 收盤及以前資訊。
- `CORE = A1 ∧ A2`：A1 為 PR61 `C3/ge60`（close/MA240 − 1 ≥ 0.60），
  A2 為 `D2/ge250`（close/前 250 日最低 close ≥ 2.5）。
- `LEAD_B1 = A1 ∧ A2 ∧ A3`：A3 沿用 `G2_limit/true`，原始收盤漲幅 ≥ 9.5% 的歷史代理。
  **2015-06-01 前為 7% 限幅，A3 不可能成立，LEAD_B1 實際只涵蓋 2015-06 以後。**
  全期 all 與 CORE 的年代組成不同，不能當成完整 2010 起的同年代可比證據；另列固定年代，不改訊號補救。
  此 A3 不授權用 9.5% 判斷 t+1 官方漲停價或可成交性。
- 訊號及 outcome 沿用 `reference_factor_adjusted`、price-basis.v2 與 PR61 品質規則；
  隔日報價量測使用 raw 價格。current-reference 與歷史資料可得性限制保留，不宣稱完整歷史 PIT。

主要單位是各集合的合格股票日 `(security_id, t)`，每日、無冷卻。
輔助為每股、每集合獨立的 20-session earliest-first 冷卻，沿用 PR61／PR17 session 距離規則：
按原訊號 t 排序，保留後下一筆須距離至少 20 sessions。
**先對完整訊號集合冷卻，再接 t+1 報價、品質遮罩與六帶。**
缺價、公司行動、報價被拒或標籤未知仍消耗冷卻；不得補選或各帶各自冷卻。

## 時間、價格與品質

1. 決策時點為 t 收盤後。`t+1 = common_calendar[index(t)+1]`，不是下一個有報價的個股日。
   休市不生成假 bar；停牌／缺開盤不跳到復牌日。期末無下一 common session 記
   `unknown/no_next_session`，不延長截止日。
2. 以正且有效的 `RawClose_t` 為分母，量測 raw t+1 Open/High/Low 各自相對 `RawClose_t` 的比值。
   不還原 OHLC，不以 adjusted close 代替 raw close，不重錨到開盤或觸價日。
3. t+1 停牌、缺開盤／開盤無效為 `unknown/no_open`；基準價無效另記原因。
   所有訊號仍保留，未知不當 0 或價帶拒絕。
4. `(t,t+1]` 有公司行動，或事件覆蓋／報價品質不明或無效，排除主 raw 價帶比較，
   列各原因、筆數與去重後總損失。不能把除權息機械落差混入一般 gap。
   乾淨子樣本是事後描述範圍，**不是盤前可執行的 PIT 公司行動篩選器**；
   已公告事件日真實訂單如何換價另由產品契約處理。
5. 後續固定並記錄 generation、日曆與輸入 fingerprint；不得靜默更新原訊號。
   既定歷史輸入不變時，加入 t 後價格／事件不得改變 t 或更早資格與訊號；
   t+1 品質遮罩是獨立事後描述，不得回饋為 t 訊號條件。

## 六個固定價帶及成交語意

`A = a × RawClose_t`，`B = b × RawClose_t`，
`a ∈ {0.97, 1.00}`、`b ∈ {1.00, 1.02, 1.05}`，完整笛卡兒積，含端點。
這是報價比較，不加入 tick 四捨五入、成本或依結果變動邊界；尚未形成委託價格契約。

| band_id |    a |    b |
| ------- | ---: | ---: |
| B01     | 0.97 | 1.00 |
| B02     | 0.97 | 1.02 |
| B03     | 0.97 | 1.05 |
| B04     | 1.00 | 1.00 |
| B05     | 1.00 | 1.02 |
| B06     | 1.00 | 1.05 |

- `A ≤ RawOpen_t1 ≤ B`：`accepted_open_quote`，只表示開盤報價落帶。
- `RawOpen_t1 > B`：`rejected_above/no_chase`；`RawOpen_t1 < A`：`rejected_below/cancel`。
  不因日內之後回落或反彈改成接受。
- High/Low 和 `[A,B]` 相交僅為 `range_touch` 診斷；日 OHLC 無法辨識路徑、先後或排隊分配。
  觸價、有成交量都不能保證個別限價單成交。
- 官方歷史限價／參考價可用且品質合格時才辨識官方限價狀態；不足時記
  `limit_status=unknown`，可另列觀測 `one_price`。one-price 不等於鎖漲停，
  官方鎖價證據也不等於個別委託能分配成交。不用 9.5% 代理全年代限價或可成交規則。
  限價診斷缺資料不把已知開盤報價變成假成交或零報價。

## 原 t 標籤與完整比較清單

沿用 PR61／PR17 吸收式 outcome、`C-base-daily` effective-label 與 `event_main_eligible`。
全部固定在**原訊號 t** 的 reference-adjusted anchor；t+1..t+H 首次達倍數為 hit，
完整未 hit 且期末收低為 loss，其餘已知未 hit 為 flat-win；先 hit 後回落仍是 hit。
缺價／品質與截尾照原契約保留 unknown／censored，不進 known 分母。
不改錨到開盤、端點、接受或觸價日，不當開盤買入實際收益。
H504 晚期截尾及年代可觀測範圍必須列明，不延長價格截止日。

主要格 `{CORE, LEAD_B1} × {B01..B06} × {2x/H126, 2x/H252}`，共 24 格：

| cell_id | set_id  | band_id | label   |
| ------- | ------- | ------- | ------- |
| M01     | CORE    | B01     | 2x/H126 |
| M02     | CORE    | B01     | 2x/H252 |
| M03     | CORE    | B02     | 2x/H126 |
| M04     | CORE    | B02     | 2x/H252 |
| M05     | CORE    | B03     | 2x/H126 |
| M06     | CORE    | B03     | 2x/H252 |
| M07     | CORE    | B04     | 2x/H126 |
| M08     | CORE    | B04     | 2x/H252 |
| M09     | CORE    | B05     | 2x/H126 |
| M10     | CORE    | B05     | 2x/H252 |
| M11     | CORE    | B06     | 2x/H126 |
| M12     | CORE    | B06     | 2x/H252 |
| M13     | LEAD_B1 | B01     | 2x/H126 |
| M14     | LEAD_B1 | B01     | 2x/H252 |
| M15     | LEAD_B1 | B02     | 2x/H126 |
| M16     | LEAD_B1 | B02     | 2x/H252 |
| M17     | LEAD_B1 | B03     | 2x/H126 |
| M18     | LEAD_B1 | B03     | 2x/H252 |
| M19     | LEAD_B1 | B04     | 2x/H126 |
| M20     | LEAD_B1 | B04     | 2x/H252 |
| M21     | LEAD_B1 | B05     | 2x/H126 |
| M22     | LEAD_B1 | B05     | 2x/H252 |
| M23     | LEAD_B1 | B06     | 2x/H126 |
| M24     | LEAD_B1 | B06     | 2x/H252 |

次要格 `{CORE, LEAD_B1} × {B01..B06} × {5x/H504}`，共 12 格：

| cell_id | set_id  | band_id | label   |
| ------- | ------- | ------- | ------- |
| S01     | CORE    | B01     | 5x/H504 |
| S02     | CORE    | B02     | 5x/H504 |
| S03     | CORE    | B03     | 5x/H504 |
| S04     | CORE    | B04     | 5x/H504 |
| S05     | CORE    | B05     | 5x/H504 |
| S06     | CORE    | B06     | 5x/H504 |
| S07     | LEAD_B1 | B01     | 5x/H504 |
| S08     | LEAD_B1 | B02     | 5x/H504 |
| S09     | LEAD_B1 | B03     | 5x/H504 |
| S10     | LEAD_B1 | B04     | 5x/H504 |
| S11     | LEAD_B1 | B05     | 5x/H504 |
| S12     | LEAD_B1 | B06     | 5x/H504 |

24／12 是比較身份數。每格完整呈現 daily 主口徑、cooled20 輔助，
及 `all`、`2010-2012`、`2013-2018`、`2019+`；年代依原 t 年份，空格也輸出。
不把年代／冷卻／bootstrap 擴充宣稱為新的主要假設，不只報有利時段。

## 分母、估計量與區間

詳細守恆式見[資料契約](data-contract.md)。逐層列所有訊號、固定下一日報價可判、
公司行動／品質遮罩後、價帶接受／拒絕、原標籤已知；unknown／censored 與排除原因分開。
對照與六帶共享同一可知遮罩，未知不填 0；零分母與不可計差距為 null。
主要報可判乾淨報價的接受、above／below 拒絕比例，及 accepted known hit/loss 率與
同遮罩無價帶對照的差距；另報 `rejected_hit_n / same_mask_all_hit_n`。
此為拒絕 hit 占同遮罩全部已知 hit，不是 rejected 組內 hit 率。
分子、分母、分臂未知／截尾／股票數與遮罩外損失一起報，不能把遮罩外未知當非 hit。

- 先存 `stock × t0-year` 整數 counts，再合計求率，不平均逐股率、不重跑逐日路徑。
- paired `stock` bootstrap 2,000 次，seed `20261028`，股票整段歷史重抽。
- paired `two_way` bootstrap 2,000 次，seed `20261029`，股票與 t0 年份獨立重抽，
  stock×year 權重為抽樣次數乘積。
- 每 replicate 的股票／年份權重由共同母體產生，對六帶、無價帶對照、接受／拒絕臂共用；
  不做各帶／各臂獨立重抽。兩種方法各報 95% percentile 區間。
- 冷卻對應格 `known_n < 100` 或 `distinct_stock_n < 30` 標 `insufficient`；
  分臂分母及股票數亦展示，不用小樣本率排名，不以區間批准策略。

## 後續 runner 的合成驗收（本 PR 不執行研究）

| 案例                   | 必須成立                                                   |
| ---------------------- | ---------------------------------------------------------- |
| 固定 t+1 缺價／期末    | 缺價仍 unknown，不跳日；末日不延長截止日                   |
| 公司行動跨日／品質不明 | 排除主比較，原因與去重損失可核對；不改 t 訊號              |
| 停牌／休市             | 不找復牌開盤，休市無假 bar；以共同日曆取 t+1               |
| 價帶端點               | Open=A、Open=B 皆接受；B04 只接受相等；外側拒絕方向正確    |
| 官方限價／未知         | 真假 one-price、有／無官方證據皆正確，不用 9.5% 補判       |
| OHLC 順序              | 同 OHLC 可有不同日內順序，不輸出假成交或排隊分配           |
| 冷卻先後               | 先冷卻再價帶，首筆缺價／被拒仍消耗冷卻，不補選             |
| unknown／censored      | 共同遮罩、分母與守恆正確；缺值不當 0，零分母 null          |
| 原 t outcome           | 六帶共享原標籤，不重錨；先 hit 後跌仍為 hit                |
| 未來追加不變性         | 加入 t 後價格／事件不改 t 或更早訊號，品質遮罩不倒灌       |
| paired bootstrap       | 合成整數 counts 可手算，固定種子可重現；六帶及對照共用權重 |

## 本 PR 驗收及停止關卡

本 PR 只驗三檔範圍、相對文件連結、六帶與 24／12 格笛卡兒積、既有 study-card.v2 schema、
正常 commit hooks 及相稱既有 CI。不新增測試框架或重複 CI 清單。
卡片沿規劃慣例：not_evaluated、空 key_numbers，無報告／收據／scratch 的欄位為 null；
不把 mission 冒充 report，不虛構 report excerpt、hash、進度或研究數字。

1. **交付獨立 draft mission PR 後停止，等待 owner 合併；不合併 PR。**
   draft／CI 通過、S1／S2 合併或程式完成不代替 owner mission 關卡。
2. 後續 runner 須另有有界任務；先通過上述合成案例、原訊號／label 契約對齊，
   明列輸入、generation、原 label gate、資源與正式單次計算 admission，才依授權執行。
3. **mission 合併且原 label／研究關卡允許前，不讀實際 t+1 O/H/L、labels，連 gap distribution 也不讀。**
   本次不跑實際 parity／probe、研究或長計算，不下載、寫正式資料、更新世代或 hold/release、改排程或部署。
4. 定義矛盾、日曆／母體不符、品質未知、label gate 不允許或需要新參數時停止並回報 parent／owner；
   不自行探索選參數或縮期救研究。

未來獲准執行後，完整結果、排除損失、空格與停止原因依資料契約交付。
本次沒有研究結果，不改既有暴露登記或舊報告。
