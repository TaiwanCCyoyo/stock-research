# HHHL v4 條件關聯與失效訊號：預先登記 v1

狀態：**mission 待 owner merge；尚未計算新的市場結果。**

研究問題是「高過高型態及哪些條件較常伴隨後來翻倍」，以及「未翻倍者較常先出現哪些支撐或結構失效訊號」。結果供其他策略 session 查用；不判策略通過、不模擬停損或帳戶。10%／20% 是舊參考線，owner 提到的 20% 是例子，均不是及格門檻。

## 授權與階段

- PR #6 已於 2026-10-11 18:05:33 UTC 合併到 `TaiwanCCyoyo/stock-research:main`，merge commit `493fa49d738e00e5c59bd118192669c86065adf4`。本 mission 建於該 main。
- 此 PR 只登記契約、驗證既有輸入身分及做合成測試。**owner 將此 mission PR merge 到 main 後，才實作和執行新的市場計算。** 準備階段不讀逐筆價格／結局來選條件；可驗 hash、Parquet footer 與日曆日期鍵。
- 合併後從最新 main 接續同一 task worktree，完成 runner 的合成驗證並封存程式／環境 receipt，再做一次固定計算。結果 PR 仍由 owner merge。
- task：`20261012-hhhl-v4-variants`；chat：`01a12bfc-b535-7352-bef7-68fe3a56901e`；branch：`codex/hhhl-v4-variants-mission`；worktree：`D:/Project/stock-research/.worktrees/hhhl-v4-variants-mission`。mission 開放 PR 期間保留；計算接續使用它，避免重複開工。
- 來源：owner 的本 chat 澄清與 2026-10-12 Claude handoff；handoff SHA 在 [input pins](params/input-pins-v1.json)。本文件收錄全部執行契約，不要求其他 session 尋找 chat 或 `.tmp`。

## 凍結輸入與停止規則

[input-pins-v1.json](params/input-pins-v1.json) 是完整來源身分、內外 hash、schema、日曆與環境的機器入口。所有路徑明指 primary `D:/Project/stock-research`；既有 mutable 輸入不改、不連結到 worktree。新 clone 必須取得相同版本本機輸入，缺少時停止，不下載補件。

| 輸入                                                                             | 用途／契約                                                                                                                                   |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `tasks/20261010-hhhl-v4-probability/datasets/hhhl-v4-descriptive-01`             | 沿用原事件、控制、地標、baseline 日曆；原 code commit `70a6872037e9ad5a9d2296c282dc583a698523b4`。全部 manifest artifact 驗 hash／bytes。    |
| `research_core/patterns/hhhl/v4/sources.zip`，原 task `sources/hhhl_rule_v4.zip` | 驗四個 member；沿用價格還原及 1.5 ATR pivot 計算，**不呼叫 detector、不重新產生 v4 事件**。                                                  |
| primary `preparation-v1/bundle.zip` 的 `corporate_action_factors.parquet`        | 固定參考日價基；內檔 SHA `427b81a70d3548a0595a80c547544cf4da8824ddcbda2dbb366032e68ba5df7a`。不查今日資料庫。                                |
| primary atlas-v2                                                                 | ID `fda-e712fc9408c147ae410a2fc0a687ef6f1dba785cab8cfb0312f79c504c6c5206`；沿用原 raw OHLC、volume、eligibility、industry 與 causal regime。 |
| Git `publication-v2-public`                                                      | 既有 1,080 格只引用；其 bulk manifest 外部 pin 亦核對，不改封裝或舊結果。                                                                    |

固定市場範圍 2019-01-02～2026-08-14。common-calendar ISO 日期向量 SHA、長度與首末日固定在 input pins；正式計算時所有逐股日期必須與該向量一對一相等。日期、事件身分、factor mapping、hash、schema 或價格還原相容性不符即停止並報告，不改規則、重抓或跳過壞股。數值計算前再次驗輸入與 code receipt；完成後再驗輸入未變。正常 commit hooks／CI 不省略。

允許修實作錯誤並重跑同一固定規格，記錄每次原因、程式 hash、暴露與失敗；不得因結果不好而改 bins、分半、候選數量、選擇、缺值或停止規則。實質規格變更須另版 mission 在評估前 merge；不能稱已看過期間是未暴露／獨立驗證。

## 群體、事件與結果

| cohort_id | 定義                                                                                                                                                |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `P-clean` | 原 v4 pattern、無上方線；原合格事件全部保留。                                                                                                       |
| `P-over`  | 原 v4 pattern、有不擋的上方線；與 clean 互斥。                                                                                                      |
| `P-all`   | 前兩者聯集，作報告／選擇母體；不得複製到選擇輸入而重計。                                                                                            |
| `C-nh`    | 原同日新高＋爆量且無任何 v4 事件，保留原有效列定義。                                                                                                |
| `C-52w`   | 新控制：t0 close ≥ 前 250 個 common-calendar 日 close 最大值，volume ≥ 前 20 日均量 ×1.5，兩窗口皆完整有效、atlas 合格；可與 P 重疊，不另排除型態。 |
| `C-base`  | 原 atlas 全部合格股票日。                                                                                                                           |

選擇主體是**事件比例**；同股可多次出現、窗口可重疊，不能稱為股票成為飆股的比例。各 horizon 報 distinct stock 數、每股事件數分布與最大貢獻，沒有把多次事件當獨立試驗。本版不另作每股挑一事件的比例，避免另增選擇規則。

H=126／252 都以 common-calendar t0+H ≤ cutoff 為 `calendar_full`。**日曆完整與價格路徑完整分欄**；不能用原 v4 `complete126` 直接替代。起點 close 有效且 >0；t0 不可能算首次翻倍。

- `hit`：首次 t0+1..t0+H close ≥ 2×anchor，若更早缺价则 unknown，不跨缺價找後來 hit。已先 hit 則後續缺價不撤銷 hit。
- 未 hit 且全路徑可觀察，期限最後 close < anchor 為 `loss`，否則 `flat-win`。未知原因分列缺價／無效起點／窗口截尾。
- 主要率分母 `known_n = hit_n + loss_n + flat_win_n`，僅 calendar_full；hit/known 與 loss/known 並列。日曆完整但後段缺價的已 hit 仍納入；任何截尾 hit 只作截尾診斷。
- 完整日曆事件的率界：`hit/full` 到 `(hit+unknown)/full`，loss 同理；截尾另列 observed hit 與未定數及界，不混回主表。
- hit 後期限末日低於 anchor 的數量另列，末價未知另列，不重新標為 loss。
- close ≤0.90／0.80 anchor 的「全期限曾發生」與「首次 hit 前曾發生」各有 triggered／all_false／unknown、自己的已知分母。先 true 吸收後續缺值；在 true 前遇缺價則 unknown，不能向後跳過。全部診斷限定 calendar_full，截尾另列。

## 特徵 inventory 與可知時點

正式機器定義：[`research_core/hhhl_variants_features.py`](../../research_core/hhhl_variants_features.py)，ID `hhhl-variants-features.v1`。24 個 feature、76 個不同有效 bins，含 66 個可選原子／10 族與 10 個 K 診斷 bins；另固定 `feature_unknown`、`not_applicable` 兩狀態，原因獨立分布。負連續值進首格；離散計數不接受負值／小數。布林不能用 0 代替 false。區間左閉右開，F/C2 邊界例外如下。

| ID／族         | t0 定義                                                                   | 有效 bins                              |
| -------------- | ------------------------------------------------------------------------- | -------------------------------------- |
| A／A           | P-over 最近上方 bonus level / close −1                                    | <.10，.10–.20，.20–.40，≥.40           |
| B／B           | close / 固定 Z2 −1；Z2 為最後 L 影線低點                                  | <.05，.05–.10，.10–.20，≥.20           |
| B2／B          | close / 固定 hz_top −1                                                    | <.03，.03–.08，≥.08                    |
| C／C           | close>MA20>MA60>MA120>MA240 的四個嚴格不等式真數；任一未知則未知          | 0=none，1..3=partial，4=all            |
| C2／C          | MA240[t0]/MA240[t0−20]−1                                                  | ≤0，>0                                 |
| C3／C          | close/MA240−1                                                             | <.10，.10–.30，.30–.60，≥.60           |
| C4／C          | 上一完整交易週 close>週 MA10 且 MA10>前週 MA10                            | false，true                            |
| D／D           | close/前 250 日 max close                                                 | <.90，.90–1，≥1                        |
| D2／D          | close/前 250 日 min close                                                 | <1.5，1.5–2.5，≥2.5                    |
| E／E           | calendar_index[t0]−calendar_index[restart]                                | <20，20–60，60–120，≥120               |
| E2／E          | (hz_top−restart low)/hz_top                                               | <.15，.15–.30，≥.30                    |
| E3／E          | 原 seq 中 rel=higher 且 k∈{H,L} 的點數                                    | 0，1，2，3，≥4；0／1 也可選            |
| E4_cat／E      | 原 cat                                                                    | bottom，hhhl，range                    |
| E4_big／E      | 原 big_hhhl                                                               | false，true                            |
| F／F           | ATR%[t0−1]/前 120 日 ATR% 中位數                                          | ≤.7，(.7,1]，>1                        |
| G／G           | 原凍結 v4 vx（volume/前20有效列均量）                                     | <1.5，1.5–2，2–3，3–5，≥5；首格也可選  |
| G2_limit／G    | 原價相鄰 common-calendar 日 close 報酬 ≥9.5%                              | false，true；僅漲停代理                |
| G2_position／G | (close−low)/(high−low) ≥.75                                               | false，true；high=low 未知             |
| H／H           | close[t0]/close[t0−120]−1 在同日合格股中 rank(average,pct)×100            | <70，70–90，≥90                        |
| I／I           | 原 atlas causal regime                                                    | down，mixed，up；source unknown 報未知 |
| J／J           | t0−10..t0 共11日內、同 current-reference 產業有 C-nh 的其他 distinct code | 0，1–2，≥3；未分類未知                 |
| K／K           | ATR%[t0]                                                                  | <.03，.03–.05，≥.05；只診斷            |
| K2／K          | RawClose 元                                                               | <20，20–50，50–150，≥150；只診斷       |
| K3／K          | 前20日平均成交金額之每日 tercile                                          | low，middle，high；只診斷              |

價格還原用固定 v4 factor；新 OHLC／ATR／均線／報酬只用此一價基，不另造 atlas 價基的同名條件。ATR14 沿用 `derived_features` Wilder 算法及缺價後重新暖機，SMA20/60/120/240 要滿 n 日。ATR%=ATR/close；F 要完整120個有效 ATR%、中位數>0。不得用 producer SMA／EMA／technical_features。無 2019 前暖機；長窗口與未知原因須報告。

新的 F/K 與其它新日價特徵使用 common-calendar、不壓縮缺日、缺價後重新暖機；H 要完整121日 close 前綴，不只驗兩端。C4 排除 t0 所在 ISO 週，週五亦同；首個不完整週／任一週內缺價無效，需11個連續已觀察完整交易週比較兩個MA10，沒有交易日的假期週不虛造價格。X4 與 G 是既有 frozen 語義的明列例外：X4完整保留原 drop-missing／ATR／pivot 程式；G直接保留原 vx，控制亦用同一 frozen 有效列公式與原暖機，不偷偷改原事件的 vx。此差異不能稱兩種價格基礎或 PIT。

成交金額用 RawClose×VolumeLots，單位千元；v4 `MIN_TURNOVER=1000` 即每日新台幣100萬元。K3 每日群體是 atlas 合格且通過原 v4 流動性門檻者，有效20日均額以 quantile(linear) 的 1/3、2/3 分界，≤q1 low，q1<值≤q2 middle，其餘 high；同值不依 code 拆組，可能空組，保存分界與群體數。H 只對當日合格且有效120日报酬者排名，保存有效分母。J 的11日 common-calendar 窗口不足也未知。H／J／factor basis 是 current-reference，不宣稱歷史 PIT。

A 只 P-over；B/B2/E* 只 P；控制為 not_applicable，不替控制畫線。共同可算 C*/D*/F/G*/H/I/J/K* 同公式同 bins 對照；型態專屬條件／混合候選以同 horizon 未加條件 P-all、未加條件 C-nh 與 C-52w 比較，控制候選列 not_applicable。不是因果效應或顯著性檢定。

## 選擇與比較次數

[`hhhl_variants_selection.py`](../../research_core/hhhl_variants_selection.py) 固定 original code UTF-8 crc32%2；偶數 development、奇數 cross-check，保留前導零，不加前綴。事件 ID+horizon 不得重複，P-all 不另加入。未知／不適用／K族禁止參選。

開發半 P-all、126 日 calendar_full 且 label known 的66原子，先以 known≥300、distinct code≥60 篩選，再按精確 Fraction(hit,known) 降序及 feature_id/bin_id 字典序，greedy 每族最多1項、至多5項。不降门槛或另挑不同族。每個候選在 clean/over/all 同一份條件，不分層重新選擇。

產生 k 單項、k(k−1)/2 全部兩項及至多1三項，k≤5，最多16。兩項 known=0 照列、率 null，不參與最佳率排序；全部兩項零已知或沒有剩餘單項時不建三項。其餘最優兩項按精確率再 canonical candidate_id 字典序，加入原單項排名最高的剩餘原子。組合不另設300／60門檻，known<300標樣本少；known stock數照列。candidate_id=`hhhl-v4-variants.v1:`+按 feature/bin 排序後逐項 URL-encode 的 `feature=bin`、用 `&` 串接；不含任何結果或排名。

| 固定比較帳本             | 最大基本列数／限制                                                                                                                             |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| 不加條件 baseline        | 6群體×2 split×2H=24，不另選股；unknown及截尾是同列欄。                                                                                         |
| 階段1有效單項            | 76 bins ×5原群體×2 split×2H =1,520；全列，含零樣本／not_applicable。                                                                           |
| 階段1未知／不適用        | 24 features×2狀態×5群體×2 split×2H =960；不參與選擇。原因只作上述狀態的子帳，不是額外候選。                                                    |
| P-all 階段1輔助          | (76+48)×2 split×2H=496，為聯集報告，不增加搜索。                                                                                               |
| 階段2                    | ≤16固定候選×6報告群體×2 split×2H =384；兩半全部候選，不重選。                                                                                  |
| K 分布                   | 每候選×6群體×2 split×2H，每個 K/K2/K3 的全部10 bins 及6未知／不適用狀態；最多6,144，diagnostic only。                                          |
| 新 riskset 旗標組        | 8 flags×4L×2H×2 split×3P群體×3旗標狀態×5漲幅層=5,760；5層是 pooled及下列4互斥區，不能相加。                                                    |
| 反向比例／代價／觸發報酬 | 8 flags×(4L×2H+2全期限)×2 split×3P=480；全期限只保存L=H的對應H。hit／nonhit 是同列分母欄，不加搜索。                                           |
| 舊 active 越線           | 4L×2H×2 split×2P×2線別×3 crossed狀態=384；old／recent_far分別保留，有／無／未知分列，clean不適用。保留既有126比較、標 extension=新增L5或H252。 |

每一基本率列另固定逐 t0 年度切片（2019..2026最多8）、年度全集 pooled，以及移除 hit 最多的 t0 年（平手最早）全部事件的敏感率。年度資料與移除最好一年不參與選擇；零hit選最早有事件年，無事件無可刪年。實際列數、缺少候選及每種 row_kind 計数写 receipt；不得額外搜尋窗口、門檻、年度、組合或改分半。跨半共享市場波動，非獨立驗證。

每率列並列樣本／股票數、同口徑 C-nh/C-52w，差值只點估計；loss rate 比可算 C-nh 高≥10pp只註記，不淘汰。固定追加 P-clean D≥1與≥.95、C-52w同日P-clean比例；D未知另列、不當否，並給全體上下界，分開兩半與 pooled。不依未知補0。

## 失效旗標与時間順序

L=5/10/20/40，H=126/252，目標一直是 t0 的2×close、終點一直是 t0+H，不改成 tL+H。8 flags：X1 close<hz_top、X2 close<Z2、X3 close<restart low、X4已確認新L<Z2、X5_MA20/MA60、X6_10/15 close≤.90/.85 anchor。前三支持價固定在t0；X5是逐日動態gap-reset SMA。

X4 只還原 frozen 1.5 ATR pivots 的 (extreme_index,confirmed_index,price)，確認日在 (t0,tL] 且低點<固定Z2；**不要求 extreme>t0**。只能使用當時confirmed者，原 pivot_sequence.date 是 extreme、不能代替確認日；不可沿用另模組要求 extreme>t0 的 transition。保存兩日期與來源index。合成案例保留 extreme≤t0、confirmed>t0。

`riskset_id=new_no_hit_valid_prefix` 收 t0..tL 價格完整且到L未hit，跌破支持不排除。`legacy_active` 保留原按時間首次 hit／missing／close<Z2 的吸收口徑，僅越線延伸使用，分母完全分離。新riskset失格原因独立保留。

旗標第一次 true 前如果所需資料缺失，整個旗標歷史是 unknown，不能跳過缺日找之後true；已true吸收後來缺值；全false需完整所需前綴。t0旗標忽略。L端點若嚴格早於首次hit可算，同日hit一律不算。支撐資料本身未知則旗標未知，不填0。由 [`hhhl_variants_observations.py`](../../research_core/hhhl_variants_observations.py) 固定時間觀察。

| 報告                 | 分母／時間                                                                                                                                                                                                    |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| owner要的逆向描述    | **所有calendar_full且label known的P事件**，包括L前已hit者。nonhit=loss+flat-win，hit只看首次hit前旗標。各L及額外H126／252完整歷史都報；旗標已知率、unknown數、全分母上下界並列。                              |
| 有／無／未知的最終率 | 新riskset；最終label仍看t0+H。所有旗標狀態報hit/loss/flat-win/unknown，不只旗標有者。                                                                                                                         |
| 同漲幅比較           | 同新riskset，close[tL]/anchor分<1、[1,1.10)、[1.10,1.25)、≥1.25，加pooled；X6作純跌幅基準。                                                                                                                   |
| 停損素材代價         | 分母**所有calendar_full最終hit**，不限制為riskset。分子 firstflag∈(t0,min(tL,firsthit)]且firstflag<firsthit。未知留在全hit分母，報旗標known率、lower=triggered/allhit、upper=(triggered+flagunknown)/allhit。 |
| 第一次觸發日報酬     | close[firstflag]/anchor−1，linear quantile .1/.5/.9，值缺另報，不是成交、損益或停損效果。                                                                                                                     |
| 越上方線延伸         | 只P-over（clean列not_applicable）、legacy_active，固定t0 bonus線、cross狀態按原語義；不與新riskset合併。                                                                                                      |

H完整歷史：nonhit觀察t0+1..H，hit觀察t0+1..firsthit−1。即使hit後缺價也不能憑hit填補整期跌幅；反向比例的beforehit歷史與整期路徑診斷分開。

## 驗證、共用資產與完成條件

準備 PR 的小型合成測試涵蓋首次缺價／hit後缺價／截尾、全部 bins 邊界、週線排除當週、pivot確認晚於t0、兩種riskset、L端點／同日hit、旗標缺值吸收、精確平手／族去重／不足5項／零交集／16上限。準備驗證記錄在 [preparation.md](preparation.md)，不是市場結果。

合併後 runner 再以合成 bundle 驗整條讀取／輸出／可重算鏈，固定抽查規則：按 code/t0/event_id 排序取P最早5及按event_id SHA字典序取5個不重複事件，人工核對全部已算值与时间；不足10照實。不得以這10筆選規則。開發半選擇收據必須與cross-check候選列表完全相同；分母與所有不適用列守恆；hash不變；未使用detector。

共用核心放 `research_core/hhhl_variants_*`，CLI 放 `scripts/*hhhl_variants*`，測試 `scripts/tests/test_hhhl_variants_*`。task只存mission、收據、契約、結果。大型逐筆資料由合併後runner additive出版到 **primary** `tasks/20261012-hhhl-v4-variants/datasets/hhhl-v4-variants-01/`，exclusive/no-replace，輸入不覆寫。完整小型 summary parquet、schema、receipt進Git；舊結果與負面結果保留。

[data-contract.md](data-contract.md) 定義逐筆與彙總查詢欄位、未知與分母、取得／重算入口；[research-program](../../docs/en/research-program.md#reusable-research-artifacts) 登記 available code與尚未產生結果。只有其他 session 能由索引找到、取得、理解、查詢並重算，才算交接完成。

不下載、不變更 producer 排程或共享輸入、不改原v4／atlas／cache、不讀前身private資料、不做帳戶回測／停損模擬、不操作其他chat。自動等待只維護本chat同一heartbeat；正式計算開始即停止等待追蹤。merge／formal approval／repo權限由owner。
