# Handoff逐項盤點：2026-10-13

基準：main 061cde2（PR #12合併）；原本機handoff的固定bytes見input pins。
「完成」僅在這一列宣稱的範圍；「部分」不能視為完成研究。
初版40個合成測試補selection/cooldown/episode/path；新增19個cohort及42個event overlay cases，
不產生市場數字，不重做PR12已完成的入口驗證。正式研究仍待mission merge。

Owner 2026-10-13已明確決定沿用handoff型態清單，H1=v4、L3=legacy F33，
不新增另一套口述「低過低」。型態選擇已完成；S1–S7補充的建議值／備選／影響
見mission review表，仍待最後mission合併批准，不阻擋本PR轉ready。

## 原始來源與已發布版本

raw價格現有2010-01-04..2026-10-12，6,653,745列／2,076代碼／4,110日期；
只有1,185代碼到2010起點，125代碼末日在cutoff以前。calendar存在不等於價完整。
本次只投影Code/Date/Source及footer並做raw身份／snapshot準備，沒有讀OHLC挑選條件。
corporate-action表跨2003..2026不能證明2010–2012公司行動完整；逐股quality待計算。

| catalog版本         | 狀態與範圍                                | 證據／限制                                                                                              |
| ------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| atlas-v2            | legacy，2019起                            | tasks/20261004-feature-discrimination-atlas/datasets/atlas-v2/manifest.json                             |
| hhhl-v1-descriptive | legacy，2019起                            | tasks/20261009-hhhl-pattern-probability/datasets/hhhl-v1-descriptive-02/manifest-corrected.json         |
| hhhl-v4-descriptive | legacy，2019起                            | tasks/20261010-hhhl-v4-probability/datasets/hhhl-v4-descriptive-01/manifest.json                        |
| hhhl-v4-variants    | legacy，原報告2019起，catalog期間unknown  | 原報告固定期間；primary raw input-pin不符保守不推導，不改舊receipt                                      |
| market-context      | complete僅TW:0050，2010-01-04..2026-10-02 | tasks/20261005-market-context-handoff/market-context-v2；4,105日／4,100 usable closes，兩層各45 unknown |
| price-bases/v2      | partial，25股／2019起                     | research_cache/price-bases/39c540.../manifest.json；不能當全市場                                        |
| price-bases/v1      | partial，25股／2019起                     | research_cache/price-bases/71928e.../manifest.json；舊數值身份保留                                      |

七manifest存在且catalog外部hash核實；metadata-only註冊不是新payload認證。
catalog snapshot固定在input pins；兩個price-base完整ID由catalog取得，這裡只是短名稱。

## 第0–8節：研究實際工作

| handoff ID                  | 完成度       | 已有／本次證據                                                                         | 尚缺／限制                                                        |
| --------------------------- | ------------ | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| 0.Q1                        | 未完成       | 舊HHHL與atlas報告可核對                                                                | 本次全型態單獨表、各horizon率及控制                               |
| 0.Q2                        | 未完成       | 新92候選selector純合成測試通過                                                         | 每型態全部單條件、真實開發選擇／確認全部組合                      |
| 0.Q3                        | 未完成       | mission列同條件控制與pattern-only不適用                                                | 真實同条件C-base/primary-control、no-pattern/all分母待批准        |
| 0.Q4                        | 未完成       | 新hit起點20日鏈合併primitive                                                           | 2010episode版本、符合/錯失、時機與例子                            |
| 0.Q5                        | 未完成       | 新互斥path primitive                                                                   | hit/nonhit並列、首flag、同行/MKT/頭頭低                           |
| 0.Q6                        | 未完成       | 既有public landmark/riskset/flag clocks                                                | 泛化Y1–Y3/X7/X8、同漲幅/X6、tradeoff圖                            |
| 0.hit/reference             | 部分         | H126/H252標籤API存在，mission保留描述性與10/20參考線                                   | 本次標籤新版本與正式報告                                          |
| 1.位置/task                 | 完成準備     | 同session既有worktree，新mission branch從fetched main建；新task為20261013-pattern-scan | 沒有市場run                                                       |
| 1.重用原碼                  | 部分         | price_basis、feature blocks、hhhl_variants/atlas/patterns API盤點                      | 2019硬coded loader/YEARS/selector不能直接重用；新adapter/统计尚缺 |
| 1.2010期間                  | 部分         | raw日期鍵与snapshot確認，cutoff固定2026-10-12                                          | adjusted有效coverage、每股缺漏、正式版本及所有報表待計算          |
| 1.因子/0050                 | 部分         | 原始action snapshot涵蓋2010，已保存identity                                            | price-basis.v2正式全市场、0050新cutoff相容性／split驗證           |
| 1.逐日股票池                | 部分         | mission明列逐日資格、保留新上市／下市；原算法可參考                                    | 新universe builder及逐日eligible資料；門檻提案待merge             |
| 1.早期quality               | 部分         | 原jump規則；event_id/horizon overlay純合成隔離通過，不改shared base label              | 真實detection/result窗口adapter、正式overlay與年代分表            |
| 1.timing/cooldown           | 部分         | confirmed_pivot_view；新20/21session cooldown合成通過                                  | 各detector完整confirmed metadata與no-future合成                   |
| 2.outcome                   | 部分         | 原first-decision API；base/event分離契約與B1/L1分母合成驗證                            | 新2010base labels/event_outcomes、rates全期版本                   |
| 2.controls                  | 部分         | C-nh/C-52w原式盤點                                                                     | C-dip/C-trend/P1-b、原控coldown/同條件完整資料                    |
| 3.H1                        | 部分         | public load_detector v4；S=Z2/L=restart映射有原例                                      | 2010全段、cooldown、与2019原事件比對及品質原因                    |
| 3.B1a/B1b                   | 未完成       | mission寫完整定義及有限搜尋提案                                                        | 新cup/handle detector、全部正反合成案例、正式事件                 |
| 3.B2a/B2b                   | 部分         | BB20原核；atlas F14差異已列                                                            | 新單日／前5收縮事件；不能直接改F14名稱                            |
| 3.B3a/b/c                   | 未完成       | mission完整平台/量縮/收斂規格                                                          | 新detector與正反邊界案例                                          |
| 3.B4                        | 未完成       | mission缺口規格                                                                        | 新detector與平手／等號案例                                        |
| 3.R1a/R1b                   | 部分         | 原F20/F33可參考，確認不同規格                                                          | 60日區間/2touch/後收復/二測confirm及狀態                          |
| 3.R2a..e                    | 部分         | public F22–F25含前MA20条件                                                             | ret20/近低附加、确认日及S/L adapter／合成                         |
| 3.R3a/R3b                   | 部分         | Wilder RSI原核可用                                                                     | i+3固定pivot／divergence/failure swing與ties                      |
| 3.L3                        | 部分         | 原F33公開旗標完整                                                                      | pending-level/break-day/S/L metadata parity與2010資料             |
| 3.P1                        | 未完成       | mission明列b/回測/確認及paired control                                                 | 新stateful detector／expiry／missing驗證                          |
| 3.L2/L1                     | 部分         | 原F32/F10旗標可用                                                                      | S/L提案、完整event adapter與正式資料                              |
| 4.MA/BB                     | 部分         | 原MA/BB/C*公式／bins存在                                                               | MA-a/b、%B/percentile/新squeeze、2010正式表                       |
| 4.SR/HHHL                   | 部分         | 原D*/confirmed pivots/A/B/B2/E完整API                                                  | nearest SR/20價格帶/event support及全型態bins                     |
| 4.KL/IND/VOL/VOLA           | 部分         | 原K geometric／RSI/MACD/ADX/volume/ATR核                                               | 新條件bins／raw-hist比較／MACD及ADX缺值warmup契約與cache接線      |
| 4.RS/MKT/PAT/K              | 部分         | 原cross_section／0050兩層／K诊断                                                       | 所有eligible-stock barrier、新PAT、全期context identity；K不參選  |
| 4.1.context分層             | 部分         | 舊2010–10/02 benchmark context reader可用                                              | 新cutoff對齐/identity、每主表past-only／holding retrospective     |
| 5.1.summary                 | 未完成       | mission／schema設計                                                                    | 30row型態/子型union真實總表                                       |
| 5.2.all atoms               | 未完成       | mission保留全部bins，含零／未知／不適用                                                | 完整單条件＋同条件控制表                                          |
| 5.3.selection               | 部分         | 新100/30、8single+28pair+56triple／CRC確認隔離合成通過                                 | 真實開發选择、全部确认候選／K分布／drop-best-year                 |
| 6.episode/timing/control    | 部分         | 新鏈合併／anchor/peak ties/unknown primitive                                           | 全市場episode／matches/misses/時機quartiles、固定seedC-base對照   |
| 7.1.path/context/lower-high | 部分         | 新四路徑／边界unknown primitive                                                        | 完整未来path/firstflag/MKT/同行/confirmed lower-high資料与表      |
| 7.2.flags                   | 部分         | 原X5/X6及landmark clocks可用                                                           | 9flag全型態泛化、same-return/X6比較、tradeoff圖                   |
| 8.1.mission                 | 完成準備     | 型態清單owner已定；完整條件／上限／pins與S1–S7具体review選項齊備                       | 必要準備可轉ready；正常CI／review及owner mission merge            |
| 8.2.synthetic               | 部分         | 40 pure helper cases完成                                                               | 每個pattern成立/差一點/confirm/no-future/missing案例仍未實作      |
| 8.3.fixed run/resume        | 未完成本研究 | 原no-replace/fresh-source機制存在                                                      | 完整runner、input/source/runtime封存、單次run及resume receipt     |
| 8.4.report                  | 未完成       | 本report明确Q1–Q6尚無結果                                                              | 白話結論／主表及全部數字                                          |
| 8.5.web tables              | 未完成       | data-contract穩定鍵／schema設計                                                        | 所有tidy parquet、字典與逐筆例子                                  |
| 8.6.shared/index            | 部分         | 共用root/builders已合併；本mission索引與提案dictionary                                 | 2010全市場正式版本及runner固定讀取                                |
| 8.7.exclusions              | 完成目前邊界 | 沒有下載/排程/帳戶backtest/改舊結果                                                    | 後續仍需持續符合，不代表研究結果已完成                            |

## 第9節：19項驗收逐條

| ID                                  | 狀態   | 缺口／證據                                          |
| ----------------------------------- | ------ | --------------------------------------------------- |
| 9.1 mission先merge                  | 未完成 | 此mission PR尚待owner；没有本研究市場计算           |
| 9.2 所有patterns/conditions         | 部分   | 可重用舊核存在；新detector／全部条件待实作          |
| 9.3 Q1–Q6結論主表                   | 未完成 | 目前無研究结论                                      |
| 9.4 每型態每bin全列                 | 未完成 | mission已承諾、資料未計算                           |
| 9.5 開發選擇/全部確認/控制/K        | 部分   | selector合成完整、其餘未計算                        |
| 9.6 episode/coverage/timing/control | 部分   | episode pure机制，其餘未計算                        |
| 9.7 hit/nonhit全描述                | 部分   | path pure机制，其餘未計算                           |
| 9.8 flag/代價/同return/X6/圖        | 未完成 | 新泛化與正式表／圖缺                                |
| 9.9 samples/unknown                 | 部分   | 契約／既有label保留unknown，新全表缺                |
| 9.10 抽10事件                       | 未完成 | 尚无新事件可抽，不抽合成當實證                      |
| 9.11 全部從2010                     | 部分   | mission/source固定2010，新run／表缺                 |
| 9.12 H1與PR9重疊核對                | 未完成 | 新H1还未偵測                                        |
| 9.13 jump未知／年代表               | 部分   | v2quality可用，新overlay/表缺                       |
| 9.14 past_only／holding背景         | 部分   | reader及定義存在，表缺                              |
| 9.15 逐日資格                       | 部分   | 契約待批准、正式universe缺                          |
| 9.16 重用hhhl/feature blocks        | 部分   | 新selector重用public types，完整runner缺            |
| 9.17 每報表tidy data                | 未完成 | schema设计存在，真实表未生成                        |
| 9.18 索引／dictionary               | 部分   | 本mission和proposed IDs已登記，結果／正式版本未登記 |
| 9.19 builder/固定入口/禁拼接        | 部分   | PR12機制完成，本研究讀取與全期版本仍缺              |

## 第10–11節：共用能力與未交付研究產物

| 條目                                | 狀態             | 核實範圍／限制                                                                              |
| ----------------------------------- | ---------------- | ------------------------------------------------------------------------------------------- |
| 10.1–10.3 角色／重用                | 完成入口         | PR12 research_data/core/cache分工；artifact_store等重用，未搬舊資料                         |
| 10.4 首批2010全段                   | 未完成           | 2010全市場universe/prices/pivots/features/patterns/labels/episodes未存在，禁止2019拼接      |
| 10.5 外部absolute root              | 完成             | DataRoots、唯一primary research_data、沒有formal shared副本／link                           |
| 10.6 catalog三期間/限制             | 部分             | 7舊版本metadata及0050unknown，尚沒有本研究全市場coverage                                    |
| 10.7 inventory/build/fixed read     | 部分             | pinned讀取、缺欄feature builder/fresh worker/no-replace已完成；新families欠adapter          |
| 10.8 共用與task／S/L                | 部分             | 契約完成；新events/S/L與研究表尚缺                                                          |
| 10.9 原位登記                       | 完成目前7項      | 舊bytes／paths不變，legacy/partial/benchmark truthful                                       |
| 10.10.1 两worktree同檔              | 完成真實讀取     | PR12證據：兩真實worktree讀同0050、4105相同rows                                              |
| 10.10.2 同需求不重算                | 完成合成機制     | Windows invented stock adapter；不是第二個真實市場study                                     |
| 10.10.3 多一指標只算缺欄            | 完成合成機制     | 同input SMA20重用、BB新欄才計算；完整IND庫仍缺                                              |
| 10.10.4 拒绝不相容重用              | 完成機制         | source/factor/prefix/ancestor guards；新dependency整合待做                                  |
| 10.10.5 2010真实全市场coverage      | 未完成正式入口   | 本次raw inventory有覆蓋；catalog仍只有0050的2010                                            |
| 10.10.6 首批全市場整算              | 未完成           | 尚未獲本mission merge／計算                                                                 |
| 10.10.7 pattern-scan入口consumer    | 未完成           | 未有完整runner／正式输入versions                                                            |
| 10.10.8 增量等於全算                | 部分             | feature checkpoint、H126/H252、context合成相等；新pattern／episode缺                        |
| 10.10.9 Windows删除隔离             | 完成             | synthetic Git force removal及PowerShell遞迴、可寫/唯讀、文件names/counts/size/SHA unchanged |
| 10.10a.1 原价/past-only追加         | 部分             | 基本feature完成；完整RSI/ADX/MACD/cross-section新版本未接線                                 |
| 10.10a.2 pivot/pattern状态          | 部分             | pivots_1p5/4 checkpoint完成；本研究新型態state缺                                            |
| 10.10a.3 affected-stock重建         | 部分             | 基本feature/factor/correction机制完成；價格→全條件→pattern依賴传播缺                        |
| 10.10a.4 label/context/episode尾段  | 部分             | label/context完成；episode未完成tail reconcile                                              |
| 10.10a.版本/pins/writer/保留        | 完成基礎契約     | no-replace／固定研究／不設定排程；新實作仍要逐項符合                                        |
| 10.11同session順序                  | 部分             | 共用PR已merge；本session繼續mission，研究仍待merge才計算                                    |
| 10.12 owner no-link/delete          | 完成             | root/path guards、junction/hardlink拒絕、synthetic實刪，不只read-only                       |
| 11.schedule/context迁移/off-machine | 未完成、此次不做 | 各別owner授权／迁移验证／異機備份仍待，不隱含啟動                                           |

原證據：[PR12 report](../20261012-research-data-entry/report.md)及其四個compressed packets。
本次設計與邊界：[mission](mission.md)、[execution plan](execution-plan.md)、[data contract](data-contract.md)。
沒有用已發布PR12的測試數冒充本stage current-head CI，沒有將raw availability稱研究完整。

PR14初版union反篩subtype的P1已修訂：子型各自冷卻，union從全部raw候選獨立去重／冷卻。
新增cohort helper與19個合成案例保留R2a→R2e、R1a→R1b、R3a→R3b，旧40-case source packet不改。
這是母體接線驗證，不是新detector或市場樣本認證。
