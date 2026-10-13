# Pattern-scan v1：型態 × 條件與飆股關聯

狀態：**mission proposal，尚未合併；沒有本研究市場結果。**
研究期固定 **2010-01-04..2026-10-12**。這是已暴露期間的描述性研究，
股票 CRC 分半稱開發／確認，不能把確認半稱為未看過的獨立 holdout。
126 日 10%、252 日 20% 只作 owner 參考線，不設通過門檻、策略批准或帳戶損益。

## 來源、批准及停止邊界

- 同一 session 接續 owner 指定的本機 Claude handoff；來源 bytes、路徑與 SHA-256
  在 [input pins](params/input-pins-v1.json.gz)。不把本機 bytes 宣稱為 Library 下載核對。
- PR #12 已由 owner 合併，共用入口與 checkpoint 沿用；[逐項狀態](handoff-status.md)
  區分入口、合成機制、正式資料與研究結果，不把 API／綠燈當研究完成。
- 本 PR 準備契約、原始來源覆蓋、實體 frozen inputs 與純合成 primitive。
  **owner 合併此 mission 後，才實作／封存完整 runner 並開始任何市場計算。**
  新市場結果前仍須完成所有 detector 合成驗證、來源／環境 pins、成本量測及正式資料驗證。
- 原 handoff §3.1第124行明定 H1 = HHHL v4 pattern，§3.3第190行明定L3 = legacy F33；這兩項已定，不再要求重新確認。原檔沒有獨立「低過低」規格：
  **目前不以 F33、v4 bottom、R3 或任何 LL/LH 代理替代它**，見下列待確認事項。
  owner 若要新增，必須先固定圖形／確認語意並修訂本 mission，不在看過結果後添加。
- mission merge 不授權下載、排程、改 producer、重開封存期間或重寫舊結果。
  缺輸入／來源 pin 不符／無法保證價格品質或無法完成契約時停止，保留失敗 receipt。

## Q1–Q6 與交付

| 問題 | 必須直接回答的內容                                                   | tidy 主表                                                 |
| ---- | -------------------------------------------------------------------- | --------------------------------------------------------- |
| Q1   | 各型態及子型單獨和飆股的關係；同時列賠錢率、對照與未知               | pattern_summary                                           |
| Q2   | 每型態全部單條件區間；開發選定後的全部組合，好壞都列                 | condition_summary、candidate_summary                      |
| Q3   | 同條件 C-base／主要控制是否也一樣；型態專屬條件不能造假控制線        | condition_summary、candidate_summary                      |
| Q4   | 飆股段落有多少出現型態／前10組合；何時出現、已漲多少、剩餘漲幅與錯失 | episode_coverage、episode_timing、missed_episode_examples |
| Q5   | hit／nonhit 路徑、最高漲幅、首個失效、0050與同行、頭頭低有何差異     | path_summary、first_flag_summary、holding_context         |
| Q6   | 失效訊號抓到多少 nonhit、在 hit 前觸發的代價、同漲幅比較及 X6 對照   | flag_summary、landmark_summary、tradeoff_points           |

報告開頭依 Q1–Q6，每題一段白話結論及主表。附錄交全部表，不只好的列；
逐筆事件與完整 parquet／欄位字典可給未來 dashboard 使用，不只存 Markdown。

## 固定輸入、日曆及可用性

- 原始價格 footer／Code、Date、Source 投影核實：6,653,745 列、2,076 代碼、
  4,110 日期，2010-01-04..2026-10-12。1,185 代碼到達起點、295 在2019後才開始、
  125 在截止日前已無末日價格；這是來源覆蓋，不是合格股票数、還原價有效性或缺漏認證。
- 原始年代日期數：2010–2012 = 748、2013–2018 = 1,475、2019起 = 1,887。
  formal common calendar 固定此日期鍵向量與 hash；不能逐股刪掉缺價後縮短 H126／H252。
  official／shioaji 資料來源及差異分欄，主研究只取有 observed official quotes 的 ordinary TWSE／TPEx 股票日；
  emerging-board／ETF／index／不明分類留在 inventory 並列原因。0050 只作 benchmark。
- 原始 corporate-action 表有 32,853 列、2,528 代碼，2003-05-05..2026-10-12；
  日期存在不能證明每次公司行動完整。2010–2012 缺漏、歷史 TWSE survivor-only、
  現有 metadata／industry reference 非歷史 PIT 都必须明列，不能改起點。
- 本次 five-role physical snapshots 在 task checkout 的 inputs/observed-v1；
  parquet／JSON 用既有 verified copy，SQLite 用穩定來源 online backup，原檔沒有改變，
  不覆寫 worktree 舊 seed snapshots。pins 給每個 source／snapshot hash。
  這是原始資料準備；正式共用衍生版本尚未存在，也未做跨來源歷史 PIT 認證。
- 計算前把本次 frozen raw input bundle 以同 bytes、provenance、完整性及 no-replace
  交到 primary 本 task 的 inputs；保留原快照。未交接或 identity 不同不得開始。
  reader 只讀固定副本，不能默默使用 live producer 或 latest。
- 還原價重用 price_basis.prepare_prices 的 **price-basis.v2 / reference_factor_adjusted**，
  固定到本截止日的完整公司行動輸入；raw volume／turnover 不還原，Volume 為張，
  raw close × Volume 為千元成交額。這是參考日 restatement，不是含息帳戶報酬或歷史可得因子。
  0050 2025-06-18 一拆四必須納入相同價格政策。
- 不解釋的大幅跳動沿用 price-basis.v2 Quality/reason：原始單日絕對變動 ≥40%，
  無有效公司行動解釋者記 unexplained_jump。型態 detection 回看或結果全窗口跨此日，
  該事件的 effective_label 為 unknown / unexplained_jump（包括先 hit 的例子），事件保留。
  共用 base label 不改寫；detection 回看因型態而異，quality overlay／事件資格以
  event_id+horizon 另存，引用固定 base-label version。不能把 B1 的長回看 jump 寫入
  security_id/t0/horizon 共用列，影響同日 L1 的短回看。保存 base/effective 與各 scope 原因，
  不能靠 dropna 穿越缺口。
- 逐日資格提案：metadata reference 為 ordinary stock、當日完整有效價格／正量、
  最近60個 common sessions 的研究價皆有效；前20日 raw 成交額平均 ≥
  原v4門檻 **NT$1m（1,000千元）**，要求20日成交額均可知，
  不沿用原source np.nanmean穿越缺值。各型態再要求它實際使用的回看窗口完整。這是事前研究資格，
  並非 owner 已選定的交易門檻；mission merge 才核准，不掃門檻。
  新上市／期間下市皆能按當日資格加入／離開，沒有全期間最低K棒數。
  2019重疊核對另列共同 eligible 的數值差異與資格差異，不能假稱原C-base分母相同。

## 時點、事件與控制

所有 condition 只用 t0 收盤當下已知的資料；保存 extreme_date、confirmed_date，
不得拿極值日當確認日。v4 detector 原本的 pivot 可用截止 t0−1，保持 source 行為；
新 SR 條件用 confirmed_date ≤ t0 的公開 confirmed_pivot_view，不改 detector。
事件唯一鍵 security_id + pattern_id + subtype_id + t0 + definition/input identity。
每個事件保存 pivot、S、L、確認來源及日期、價格品質、適用／未知原因。
沒有支撐不能用0；HHHL／legacy 標記不能當新增 owner 定義。

每股的每個 subtype 各自以原始候選為母體，依已知觸發／確認t0排序去重後，
抑制自身保留事件之後20個 common sessions，第21個日子才可再記。不同subtype不共用冷卻；
R2a完成後次日R2e確認、R1a後R1b二測、R3a後R3b都保留各自樣本／t0／label。
Union另從同股、同pattern的**所有原始subtype候選**合併同日，再獨立套20session冷卻；
不從已冷卻subtype反推union，也不以union保留集合反向篩掉subtype。
兩種母體不是可相加的互斥群體：Q1各自報事件/stock/unknown，Q2–Q6家族union選擇按union口徑，
subtype獨立診斷按其自身口徑。被抑制事件不延長冷卻；各控制独立同樣冷卻，C-52w另報無冷卻。
接線用 research_core.pattern_scan_cohorts_v1.build_pattern_cohorts，返回各subtype及union indices，
保留原候選及兩種採用/抑制原因。Union同日保存全部raw member_subtype_ids與來源event_id；
需單組pivot/S/L/專屬condition時，按上表subtype列舉順序取第一個原始member為representative，
另存所有member metadata，不從subtype保留集合挑、不看結果挑support，不混合多組S/L。

| control_id    | 固定公式／用途                                                                                                                                                                    |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C-base        | 所有當日合格股票日的baseline；同條件主對照 C-base-no-pattern 排除當日该pattern原始候選，並列C-base-all診斷。型態判定unknown不能歸為no-pattern                                     |
| C-52w         | close ≥ 前250日最高close，raw量 ≥ 前20日均量×1.5；突破主要控制                                                                                                                    |
| C-nh          | close>前20 detector棒maxClose，量≥前20棒均量×1.5，無漲停免量；排除同日任何v4 detector event（不只pattern=True），原rolling量min_periods=1／價20，並通過本次base資格；突破次要控制 |
| C-dip         | close ≤ 前60日最高close×0.80 且 close > 前日close；反轉主要控制                                                                                                                   |
| C-trend       | close > MA60 且 MA60 > 20日前MA60；拉回主要控制                                                                                                                                   |
| C-P1-breakout | P1 的原 b，另列每一配對的等待回測差異，不冒充獨立隨機對照                                                                                                                         |

前N日均量／最高價／最低價指 t−N..t−1，未指定的當日均線／BB含t；
連續真旗標按每日候選後套冷卻，不擅自改成 rising edge。

## 全部型態（事前固定）

12 union families、最多30 subtype／union主報告列。方法是 handoff 的簡化固定規格，
不是 O'Neil／Wyckoff／Bollinger 文獻原文，不搜尋參數。新 detector 放
research_core/patterns/<pattern_id>/，entry 放 scripts，測試放 scripts/tests。

| ID／子型                   | 完整觸發規格                                                                                                                                                                                                                       | pivot／S／L                                                       |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| H1／P-clean、P-over、union | 原 load_detector("v4") 的 pattern=True；bonus上方無線／有線互斥。2010全段重新偵測，保留原等待量能、liq、blocking與確認日行為                                                                                                       | pivot=hz_top；S=Z2；L=Low[restart]，full-calendar映射             |
| B1a／杯柄                  | 左杯緣close ≥ 其前120日最低close×1.30；左緣至柄起點30..250日，杯深12..35%（左緣High基準）；柄5..15日，最高High在柄前3日，為左緣High的0.90..1.05；柄深≤12%，柄Low > 杯底+0.5×(左緣High−杯底)；t0 close>柄High且raw量≥前50日均量×1.4 | pivot=柄High；S=柄Low；L=杯底                                     |
| B1b／無柄、B1 union        | 同前置與杯限制；無柄時close>左杯緣High，不加未寫在handoff的量門檻                                                                                                                                                                  | pivot=左緣High；S=L=杯底（補充欄位提案）                          |
| B2a／B2b、union            | BB20,2：在t0前5日中存在帶寬≤該日之前125日最低帶寬；t0 close>當日上軌。b再要求量≥前20日均量×1.5                                                                                                                                     | pivot=上軌；S=L=前20日Low最小                                     |
| B3a／b／c、union           | 平台25..65日，start close ≥ start前60日最低close×1.25；(maxHigh−minLow)/maxHigh≤15%；t0 close>maxHigh且量≥前50均量×1.5；b最後10日均量≤平台均量×.8；c最後三分之一振幅<前三分之一×.6                                                 | pivot=maxHigh；S=L=minLow                                         |
| B4                         | open≥前High×1.02、low>前High；close≥前60日最高close且量≥前20均量×2                                                                                                                                                                 | pivot=S=前High；L=前20日Low最小                                   |
| R1a                        | tb前60日(maxHigh−minLow)/minLow≤35%，Sup=minLow；至少兩個距離≥10日的Low≤Sup×1.03；tb close<Sup且Sup−low[tb]≤1.5ATR14[tb]；後1..5日首次close>Sup為t0                                                                                | pivot=S=Sup；L=minLow[tb..t0]                                     |
| R1b／union                 | R1a後3..15日首次close≤Sup×1.03且此前沒有close<L；之後第一個close>open的日子t0。確認最多等5日是本mission補充提案，超期記expired                                                                                                     | pivot=S=原Sup；L=原R1a L，確認不得收破L                           |
| R2a..d                     | 前置ret20[t0−1]≤−10%、前close<前MA20、型態Low≤前60日minLow×1.03；重用F22/F23/F24/F25實際flag（含其原MA20前置），完成日t0                                                                                                           | pivot=型態High；S=L=原兩根K最小Low，hammer為一根                  |
| R2e／union                 | a..d完成的下一日close>原型態High，t0為該下一日；確認以前不觸發                                                                                                                                                                     | pivot／S／L固定原型態，不納入確認棒（補充提案）                   |
| R3a                        | Wilder RSI14；Low[i]為[i−5,i+3]最低，i+3才確認；兩低P1/P2距10..60日，Low2<Low1、RSI2>RSI1、RSI1≤30；t0=P2確認日且close[t0]>close[P2]                                                                                               | pivot=close[P2]；S=L=Low[P2]                                      |
| R3b／union                 | 同背離結構，確認後20日內首個RSI>兩低間最高RSI，該日t0，確認當日不算「後」                                                                                                                                                          | pivot=原兩低間RSI門檻另欄保存；S=L=Low[P2]                        |
| P1                         | b close>前60日maxHigh R且量≥前20均量×1.5；b後3..20日首次close進入R×[.97,1.03]且至回測無close<R×.97；其後1..5日首個close>前日High為t0                                                                                               | pivot=S=R；L=minLow[回測起..t0]                                   |
| L1                         | 原F10：close>前60日maxHigh，不改原flag                                                                                                                                                                                             | pivot=S=前60日maxHigh；L=前60日minLow（補充提案）                 |
| L2                         | 原F32：close>MA60且ret5<0，不改原flag                                                                                                                                                                                              | pivot=S=MA60[t0]固定；L=minLow[t0−5..t0]（補充提案）              |
| L3                         | 原F33：破前20日低後，五根內後續非新低K收復pending_level；同日不收復、新嚴格低重置、gap清pending，flag必須逐日對上原程式                                                                                                            | pivot=S=pending_level；L=minLow[破低..t0]（metadata adapter提案） |

所有窗口長度以完整 common sessions 計。缺價回報 unknown（附 detector/window reason），
不能當作沒有型態／false 或刪缺價後跨空洞偵測；對照同樣保留未可知狀態。

B1 搜尋補充提案：柄長h從5..15取首個成立；柄=t0−h..t0−1；
左緣候選=t0−h−250..t0−h−30，取最高close、平手較近，
杯底=minLow[左緣..柄起點−1]。柄最高價平手取最早，以判是否在前3日。
B1b用杯長30..250由短到長首個成立，同樣左緣平手較近。B3長度由25..65首個成立；
三分之一取floor(n/3)，剩餘只留中段。R3最低價平手選窗口最早，
兩點配對選最近合法P1（再以日期），避免一個t0重複所有組合。
這些補充填足 handoff 未寫的有限搜尋／欄位／期限語意，**須經本mission merge批准**。

## 全部條件庫與同條件控制

區間通常左閉右開，特定 ≤ 邊界照表。布林 false／true，unknown、warmup_insufficient、
not_applicable 各自列原因，不當0。既有條件重用原公式及 bin_values；映射到新族，
不能把舊I regime代替0050past_only。HHHL的A/B/E只在H1可算。

| 新族／ID                 | t0公式                                                                                                            | 有效區間                                                  |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| MA／C,C2,C3,C4           | 四個close>MA20>MA60>MA120>MA240不等式真數；MA240/20日前MA240−1；close/MA240−1；上一完整週close>週MA10且週MA10上彎 | none/partial/all；≤0/>0；<10/10–30/30–60/≥60%；false/true |
| MA／MA-a,MA-b            | close/MA20−1；MA20>5日前MA20                                                                                      | <0/0–5/5–15/≥15%；false/true                              |
| BB／BB-a                 | (close−lower)/(upper−lower)，零帶寬unknown                                                                        | <0/0–.5/.5–1/≥1                                           |
| BB／BB-b,BB-c            | 當日帶寬相對前125日的ECDF百分位（≤當日數/125×100）；前5日有各自前125日最低帶寬                                    | ≤10/10–50/>50；false/true                                 |
| SR／D,D2                 | close/前250maxClose；close/前250minClose                                                                          | ≥1/.9–1/<.9；<1.5/1.5–2.5/≥2.5                            |
| SR／SR-a,SR-b            | t0已確認1.5ATR pivot中最近的上方high price／close−1；close／下方low price−1，price距離最近、同價最近確認日        | 無/<10/10–20/≥20%；<5/5–10/10–20/≥20%，無下方unknown      |
| SR／SR-c                 | 前120日以同版本還原Close的min..max分20等寬價帶，raw量按各日還原Close累計；用收盤作量的價位代理，非逐筆成交profile | close在最大量帶上方/帶內/下方；平手低價帶，零寬unknown    |
| SR／support,A/B/B2/E*    | close/S−1；H1原A/B/B2/E/E2/E3/E4_cat/E4_big完整值與bins                                                           | <5/5–10/10–20/≥20%；H1照原定義下表                        |
| KL／G2_limit,G2_position | raw close/前raw close−1≥.095代理；(close−low)/(high−low)≥.75                                                      | 各false/true，zero-range unknown                          |
| KL／KL-a,KL-b,KL-c       | abs(close−open)/(high−low)；(high−max(open,close))/(high−low)；前5日及t0有F22..25                                 | <.3/.3–.7/≥.7；<.1/.1–.3/≥.3；false/true                  |
| IND／RSI,MACD,ADX        | Wilder RSI14；原始MACD histogram>0且大於前日（不可用hist/close比較大小）；Wilder ADX14                            | <50/50–70/≥70；false/true；<20/20–25/≥25                  |
| VOL／G,VOL-a             | H1用原vx（前20detector有效棒），其他型態用raw量/前20common均量；前10均量/前60均量                                 | <1.5/1.5–2/2–3/3–5/≥5；≤.7/(.7,1]/>1                      |
| VOLA／F                  | ATR14%[t0−1]/median(ATR14%[t0−120..t0−1])，原gap-reset formula                                                    | ≤.7/(.7,1]/>1                                             |
| RS／H                    | 原120日ret於同日eligible／known股rank(average,pct)×100，保留同值規則                                              | ≥90/70–90/<70                                             |
| MKT／context,J           | 0050 past_only；同industry reference前11個common sessions新高爆量stock distinct數、排除自己，沿用原實作           | up/down/consolidation/mixed；0/1–2/≥3；未知另列           |
| PAT／other_<id>          | t0−10..t0另一union pattern已確認出現，各別其他11個ID                                                              | 各false/true，另一detector不明則unknown                   |
| K診斷／K,K2,K3           | ATR14%；raw price；同日eligible成交額分位，原K3的三分之一分組                                                     | K<3/3–5/≥5%；K2<20/20–50/50–150/≥150；K3low/middle/high   |

SR-c 正式提案用 **同版本還原Close分箱、raw量累計**，
讓120日價格帶與t0 close直接可比；此提案與後述待決清單一起核准，不能混兩價基。
K診斷只報全部分布（含缺值），不選擇，KL可選。H/J/K3跨股票計算須等全eligible stock barrier，
每個族內最多選一atom；原A/B/E均映射SR，不延用舊selector的A/B/E獨立族。
所有條件每個區間逐一報，包括零樣本、未知與不適用。型態專屬support及H1線條在C-base沒有S：
該條件的同條件控制列 **not_applicable**，不虛構S，不用未加條件控制冒充同條件；共通atoms照常套用。

H1獨有值／bins完整沿用：
A=最近bonus/close−1：<.10/.10–.20/.20–.40/≥.40；
B=close/Z2−1：<.05/.05–.10/.10–.20/≥.20；
B2=close/hz_top−1：<.03/.03–.08/≥.08；
E=t0−restart日：<20/20–60/60–120/≥120；
E2=(hz_top−restart low)/hz_top：<.15/.15–.30/≥.30；
E3=原seq中rel=higher且k为H或L的点数：0/1/2/3/≥4；
E4_cat=bottom/hhhl/range；E4_big=false/true。逐值公式最终以既有 feature inventory
核對；有不符則在市場計算前修訂，不暗中改原版本。

0050雙層皆用21-session window：past_only=[t−20,t]，retrospective=[t−10,t+10]；
窗口首末close報酬≥3%為up、≤−3%為down，其他振幅(max/min−1)≤8%為consolidation（盤整），
其餘mixed；窗口缺價／不完整為unknown。重用既有benchmark-context.rules.v1實際實作及
完整邊界（原rules包含±3%等號；handoff的「超過」文字以此明示原API邊界，不暗改rules），已發布v2到2026-10-02
只在完整input/basis/definition身份匹配時重用／延伸；不同則新2010全段版本，不覆寫舊context。

## Label、完整性、統計與選擇

H126/H252重用 outcomes_for_closes。t0+1..t0+H首次close≥2×anchor為hit；
先缺價則unknown，先hit則其後普通缺價不撤銷已知hit；
完整路徑未hit且末close<anchor為loss，否则flat-win。這是共用 base outcome；
calendar_full、base_main_eligible與普通缺價的 first-decision 語意不變。
型態 detection／結果窗口品質及事件資格另由 apply_event_overlay 形成 event_id+horizon
投影；品質原因使 effective_label unknown，資格排除只改 event_main_eligible、不改 label。
每張型態／條件／控制彙總只用自己的 effective_label、event_main_eligible；主分母須
base calendar_full、effective known 且沒有事件資格排除。base/effective counts、各 scope
原因及 excluded_n 分開保留，不能以同股同日共用標籤覆寫不同型態分母。
hit與loss率並列。截尾hit及未知不混回主分母，
完整日曆及截尾各報上下界。零分母率null；整數counts及stock-set先合併再算rate。
新統計支持2010..2026，不直接用硬寫2019..2026的舊RateAccumulator。

每列：event_n、distinct_stock_n、每股事件中位數／最大值、known_n、unknown_n、
censored_n、hit_n/loss_n/flat_win_n、hit_rate/loss_rate、兩半、年代、t0背景、
刪最多hit年後的同口徑值（年平手較早；剩餘0則null，不換分母）。
分層是全期+2010–2012+2013–2018+2019起及all+up/down/consolidation/mixed/unknown；
不能把unknown regime併入mixed。

每12個pattern union各自按 **原code UTF-8 CRC32 parity** 分development／cross-check，
保留leading zeros，沿用 split_for_code。只在development、H126、calendar_full、known事件
排名單atom，至少100事件／30stock、每族最多1，選最多8。按exact Fraction hit/known排序，
平手feature_id、bin_id。產出全部single+pair+triple，最多8+28+56=92；
不足8不放寬門檻；交集0仍保留、率null。所有candidate在確認半報H126/H252、
同條件C-base/主要控制、刪最好年後值及K分布，不再選好才存。
確認半H252表排序只為呈現；前10限定有已知分母，平手candidate_id，
不足10照實；此排序及後續Q4–Q6是已暴露資料上的描述，不獨立確認。

固定上限：12 selection families、30 subtype/union rows、320有效atom上限
（**上限不是額外新增條件的授權**；正式inventory只含上表及原H1）；
single比較≤9,600，選出candidate≤1,104。兩horizon、3split、4era、6MKT、
4cohort（pattern/C-base-no-pattern/C-base-all/primary control）的主single表≤5,529,600列；
候選確認主表≤211,968列。逐年／drop-year與secondary controls另存稽核表，
每主格最多19年彙總派生列，上限明記輸出manifest；超限先停，不增加搜尋。
Q4–Q6使用12原pattern+每pattern前10candidate，最多132組，9個旗標
（Y1/Y2/Y3/X5_MA20/X5_MA60/X6_10/X6_15/X7/X8），4landmark，
2horizon、3state、5return层、2split、4era、6MKT，旗標格上限6,842,880，
所有rates共用整数母數，不能將重疊層相加。

## Q4 episode／漏抓、Q5路徑與Q6旗標時間

- Episode起點先由H126 base hit套用共通result-window品質：calendar-full、已知且無結果窗口jump
  才收，品質排除起點數與原因另存；不使用任何pattern的detection回看overlay，不改shared base。
  合格起點同股相鄰差≤20鏈式合併；
  段內起點集合最低close為anchor、平手較早。頂點為anchor後1..126最高close、平手較早；
  頂點窗缺價／不完整為unknown，保留段而不穿越空洞補峰。
- 各pattern／確認前10candidate在anchor−20..anchor+40是否出現；逐段保存所有匹配，
  主時機用窗口內首事件，不挑最漂亮事件。報matched/unmatched/unknown，
  offset、close[t0]/anchor−1、peak/close[t0]−1中位數/Q25/Q75，
  外加peak在訊號前的late flag。Q4同樣分年代與anchor日past_only背景。
- Q4符合率分母：所有本組H126 episode先保留；若窗口有已確認匹配，matched吸收後來unknown；
  無匹配且整個anchor−20..anchor+40的pattern/candidate判定皆可知為unmatched，其餘unknown。
  主率=matched/(matched+unmatched)，另列matched/total..(matched+unknown)/total界。
  peak unknown不撤銷已觀測pattern匹配；時機／剩餘漲幅各自附known_n/unknown_n，
  首觀測事件前有detector unknown時，first-timing標不確定而不宣稱真正第一事件。
- C-52w同窗口對照；C-base隨機基準固定seed=20261013，由全期C-base冷卻後事件池，
  每pattern/candidate依stock×year抽與其事件數同量的日期、不放回，不限定在episode窗口內，
  不用outcome挑日。pool不足時抽實際可用數、保留quota/drawn/shortfall並把該stock-year的
  隨機對照coverage標unknown，不換股票／年度或默默減門檻。pool已冷卻，子集不再引入近距離事件。
  使用排序stock/year/IDs與獨立seed identity、保存所有抽樣日期／pool pin，可重現。
  同一seed不得因結果改抽；所有matched/unmatched/unknown率用上式，C-base-all日頻baseline另列。
- nonhit互斥路徑依序：先−10%才+10%（或永無+10%）直接失敗；
  最高≥+20%先漲後回；最高<+20%且最低>−15%盤整；其餘慢跌。
  所有close均指期限future，不含anchor，缺價全路徑描述unknown。
  hit並列相同**價格路徑diagnostic**（第二格表示曾達+20%，不聲稱hit未翻倍或一定回落）；
  outcome始終另欄，此用詞補充需mission批准。
- 保存最高漲幅／第幾天、最早旗標（同日按固定flag_id排序但附全部同日旗標）、
  同期限0050及同industry其他股平均還原報酬（exclude自己、known peer數、unknown原因），
  retrospective各狀態持有日比例，不拿未來背景當進場條件；
  首個confirmed 1.5ATR lower-high及extreme/confirmed日期。
- Y1 close<S、Y2 close<L、Y3 close<t0最近confirmed下方low；三價固定t0。
  X5 close<當日MA20/MA60；X6 close≤anchor×.90/.85；X7 close<當日BB lower；
  X8 confirmed新high<前一confirmed high。等號嚴格照式；缺值保留flag unknown。
- 照前批 L5/L10/L20/L40、H126/H252，target仍anchor×2、終點仍t0+H；
  new_no_hit_valid_prefix riskset，只收t0..tL完整且未hit，跌破S不排除。
  hit在landmark當天則不在riskset，旗標可知只到L，缺值首次吸收語意沿用公開API。
  return層為pooled及<0/0–.1/.1–.25/≥.25（照前批RISE_BINS），不與legacy_active混合。
- 逐型態／旗標並列 nonhit觸發率、hit達標前觸發代價、unknown及上下界、
  觸發當日報酬median、同return層有／無／未知之hit/loss/flat-win/unknown，
  與X6純跌幅對照；横代價纵nonhit觸發率取捨圖，不模擬賣出或停損帳戶。

## 計算前與交付的必要驗證

每pattern/subtype至少成立及差一點未成立，涵蓋精確邊界、ties、窗口、
缺價、冷卻、R1b/R2e/R3b/P1確認前不触發；原F10/F32/F33／v4 API parity；
因子／jump、未來行插入不改past-only、週線完成、全市場barrier、CRC與92候選、
同條件控制not_applicable、episode合併、路徑與flag clocks。這些都須在市場運算前完成。
目前僅有純合成 primitive／cohort／event overlay 驗證，不能等同每pattern detector已測。

按 [execution plan](execution-plan.md) 先估成本、量測代表股票串行與有限worker
相同輸入的wall/CPU/RSS/I/O/啟動/serialization；觀測不到明列unknown。
選明確worker/in-flight/memory limits；全市場排名／產業／PAT barrier及deterministic
stock order不變。不把100% CPU當最佳，不在market結果出來後改selection。

Formal shared versions由既有builder no-replace發布：universe/prices/pivots/features/
patterns/labels/event-outcomes/episodes/context，manifest給raw期間、valid期間、eligible label periods、
known/unknown coverage、身份與backup狀態。研究固定其版本與manifest SHA，
read失敗明確停止，不靜默重算。不把2010–2018接到舊2019資料；
labels 以固定版本內 security_id/t0/horizon 保存 base outcome；每個 event-outcomes bundle
固定唯一 base-label version+manifest pin，鍵 event_id/horizon 包含型態、子型、definition/input
身分。引用 base 版本改變須新增 overlay bundle 版本，不覆寫舊投影。
2019舊事件只作重疊差異核對（input／factor／price-basis／warmup起點等原因明列）。
公用新pattern與episode增量狀態未完成；本研究固定cutoff，
後續增量要逐個版本證明append/tail=全算，不假稱PR12已包全部。

完成後primary保留大表、task小summary與源code receipt進Git，完整資產索引及
pattern字典更新。抽10個事件人工核對t0/pivot/S/L/confirm/conditions不看未來；
抽5candidate從逐筆資料重算。可攜包不足以取得大型原始資料時明列local-only。
同碟backup和異機backup分别report，不將hook/read-only當備份或安全證明。

## 待owner確認的實質補充

1. 只有另加原handoff未定的獨立「低過低」時，才需固定哪兩低／中間高、觸發價、
   extreme與confirm時點，不能由現有F33或HHHL猜測。選項是原清單H1=v4/L3=F33，或追加獨立新圖形版本；未有新增定義時保持原清單。市場計算仍等本mission merge，不以這個可能追加的圖形重問已定版本。
2. 上文標「補充提案」的S/L、有限搜尋、R1b確認5日上限、R3ties與SR-c還原Close分箱，
   以及逐日資格門檻／C-base-all與no-pattern分母／hit路徑診斷用詞：
   均在市場結果前列明，owner可在mission review調整；合併代表批准最後文字。
3. 不縮短2010起点；若fixed raw coverage內仍有因子／官方價／metadata缺口，
   按unknown／excluded inventory照實報告，需下載等額外行動時另外請owner判斷。
