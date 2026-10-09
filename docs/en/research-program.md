# 研究總覽與跨 session 交接

> Current public-export availability (2026-10-09): source-data packages containing
> real quote vectors, anchor-close samples or corporate-action factors are retained
> locally, not distributed in the public repository. Historical receipts and fixed
> hashes retain their original identity. The 0050 context cannot be activated without
> its complete original input package; readers fail closed and do not download or
> recompute missing data. See [the bootstrap availability record](bootstrap-stock-research.md#public-export-availability).

更新：2026-10-05。這是工作入口與索引，不是回測結果、預註冊鎖或第二份暴露紀錄。

## 一分鐘接續

- **方向已核准：** 廣泛蒐集方法，分批建立「方法 × 產業／角色 × 個股強弱 × 市場狀態」證據，再組成每天收盤檢視一次的操作。200 萬、最多 5 檔純股票與非命中侵蝕要求不變。
- **人工韌性已澄清：** 漏做後依最新資訊與實際持倉／現金恢復，不機械補做過期委託。舊整批延遲測試不代表新情境；數值要求未自行取消，抽樣及驗收對應仍須於測試前固定。
- **目前完成：** 方法來源及舊實驗盤點後，已完成 [feature-discrimination-atlas](../../tasks/20261004-feature-discrimination-atlas/report.md)：38 特徵、1,941 檔、3,588,909 股票日期列、7,144 比較，包含 0050 狀態、目前產業與年度切片；不是可交易策略驗證。
- **增量完成：** [第一批方法／相對強弱／0050 交互比較](../../tasks/20261005-method-environment-interactions/report.md)：624 比較，一次完成；F10/F32/F33 單獨與加 F37 共六個候選均未通過事前晉級條件。沒有新帳戶回測、獨立確認或最終檢驗，不改舊 atlas 的結果。
- **可重用交接：** [市場背景與資料發布](../../tasks/20261005-market-context-handoff/report.md) 提供 Git 可攜的全部 7,144 比較、公式與 0050 雙層背景；大型逐股資料仍為明列位置的本機檔案。網站端已獨立複製並驗證可讀，不代表頁面已接入或策略有效。
- **最新完成：** [H03 產業角色／排除自身的同儕強弱](../../tasks/20261005-industry-role-comparison/report.md) 一次完成 1,316 比較，三候選未晉級。落後轉強者未較容易翻倍，但非命中價格跌幅較小；這個取捨保留，不改事前規則救回。
- **目前接續：** [相對強度／固定均線出場 mission](../../tasks/20261005-relative-strength-holding/mission.md) 只比較 SMA20／SMA60 出場，市場績效仍為零。[來源契約](../../tasks/20261005-relative-strength-holding/source-contract.md) 重用 022／026 的 2019–2023 已暴露範圍及 1,216 日獨立日曆核對；來源、特徵、經濟事件、停牌／恢復、零股、成交、成本與收盤量測已接合。[敏感契約](../../tasks/20261005-relative-strength-holding/sensitivity-contract.md) 新固定最多十條路徑、雙方適用的停止規則與操作負擔定義；97 項相關合成測試通過。下一步為單次 runner、來源範圍斷言、輸入／程式／環境封存及核准 packet，不重做上述接線或補抓無關資料。不把假設當完整 PIT，不啟動 paused automation 或確認／holdout。

## 固定入口與權責

2026-10-08 架構入口：[型態字典](pattern-definitions.md)集中 HHHL v1～v4 與 F20/F21/F33/M04 的差異、來源與批准狀態；[Stock 衍生資料](research-derived-data.md)說明 producer 與 Stock 的分工。[架構交付](../../tasks/20261008-research-data-architecture/report.md)含 25 原例／75 組重算、可攜收據及備份演練；價格品質 v2 修正另存 publication-v2，不覆寫原 v1 相容性證據。Claude 完整標註仍待接收，不把 25 正例當全部正反標註，也不自動改接既有研究。

| 要找什麼                         | 正式位置／責任                                                                                                          |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| 最新需求、人工操作與接受邊界     | [owner contract](research-owner-contract.md)、[目標文字](research-goal.md)；主代理維護，App 不會因 Git 文件變動自動同步 |
| 方法來源、交互假設、查過或測過   | [本輪方法與假設登記](../../tasks/20261004-method-environment-map/report.md)；每筆有穩定 ID、狀態、來源、限制及下一步    |
| 本輪範圍與尚未批准的批次         | [mission](../../tasks/20261004-method-environment-map/mission.md)                                                       |
| 決定、協作回覆與完成收據         | [工作紀錄](../../tasks/20261004-method-environment-map/daily_research_log.md)，新批次回到各自 `tasks/<task-id>/`        |
| 某次實驗原規則、結果、程式與收據 | 該 task 的 `mission.md`、`report.md`／`execution-*.md`、`research_result.json`（若有）及固定 run；不得用此索引取代      |
| 可重用資料、特徵與共用計算       | [產物管理規範](#reusable-research-artifacts)；本頁定位表連到各任務的資料說明，再連到正式產物、產生程式與使用關係        |
| 期間暴露與量測更正               | [既有 research-registry.json](research-registry.json)；缺記錄是未知，不是未看過                                         |
| 檔案可用性查詢與單次執行         | [research foundation](research-foundation.md) 的既有 catalog／registered-job；catalog 只列檔案存在，不證明已通過        |

歷史 `research-objective.md` 與 2026-09-09 launch/first-candidate 文件保留作原時點證據，不是永遠重新啟動那個「下一步」的指令。目前方向以上方入口及明確日期的擁有者更新為準；歷史任務仍依各自封存規則解讀。

## 怎麼記，才不會下一個 session 重做

1. **先找舊工作。** 搜尋方法 ID、同義名稱、機制、產業及環境；查任務索引與下方舊報告。找不到檔案時標記缺口，不能宣稱第一次研究。
2. **分開三種狀態。** 來源可為待查／已查／有爭議；假設可為提議／待資料定義／已預註冊／進行中／已評估／暫停；執行結果沿用既有 `candidate_failed`、`invalid_measurement`、`data_blocked`、`incomplete` 等口徑。基礎設施完成與文獻看過都不算策略通過。
3. **每次變更可追溯。** 記錄方法／假設 ID、別名、來源及查閱日、版本、相較前版改了什麼與為什麼、相關 task/run、主責與下一步。不覆蓋負面結果或把重試當新獨立證據。
4. **評估前固定比較單位。** 規則／參數、特徵可知時點、股票母體、日期與選期理由、未納入年份、結果期限、產業／市場條件、控制組、比較次數、分數與分層定義、停止／晉級規則。來源查閱不算市場試驗；改參數或條件再看同一資料則要記入比較帳。
5. **評估後連回證據。** 完整記錄符合與不符合的成功／失敗數、未定／缺值數及分母；再連到原始報告與收據。結果對照不同年份／產業，標示相依樣本與小樣本不確定性，不只保留最佳格子。
6. **收尾交接。** 更新本頁的當前狀態／下一步、方法登記、該任務工作紀錄；若新增期間暴露或更正，再更新既有 registry。保留舊項目，以日期事件說明取代／暫停原因。`.tmp` 可以協作，但需要延續的決定必須提升為正式紀錄。

不新增排程、資料庫、dispatcher、UI 或強制全市場重算作為上述管理的前提。下游展示可消費方法／假設 ID 與既有結果契約；文字索引不冒充已實作的新 API。

## Reusable research artifacts

2026-10-08 v4 完成：[HHHL v4 機率／早期越線](../../tasks/20261010-hhhl-v4-probability/report.md)
一次 1,941 檔、1,080 個固定描述性比較完成。126 日 E-all 8.49%、同日無事件主控制
8.86%；無線 9.68%、有線 6.22%。早期越線總比例較高，但同漲幅分層未呈一致加分，
2026 截尾與未知差異不能略過；未評估帳戶、停損、獨立驗證或策略通過。
[資料契約](../../tasks/20261010-hhhl-v4-probability/data-contract.md) 與
[可攜全部結果目錄](../../tasks/20261010-hhhl-v4-probability/publication-v2/)
提供完整 1,080 格、原完成紀錄、診斷／覆蓋／抽查、19 份結果前原始 inputs。
請取得整個目錄：
[publication.zip](../../tasks/20261010-hhhl-v4-probability/publication-v2/publication.zip)、
[bundle.001.bin](../../tasks/20261010-hhhl-v4-probability/publication-v2/bundle.001.bin)、
[bundle.002.bin](../../tasks/20261010-hhhl-v4-probability/publication-v2/bundle.002.bin)、
[bundle.003.bin](../../tasks/20261010-hhhl-v4-probability/publication-v2/bundle.003.bin)
四檔都必要；只有 publication.zip 的 metadata 不能驗讀完整結果。
reader `scripts/publish_hhhl_v4_probability.py --publication ...` 不依賴原行情 checkout。
另有 [可重算地標未知原因補件](../../tasks/20261010-hhhl-v4-probability/diagnostics-supplement-v2.zip)，
保留缺價／窗未滿分桶；由既有表補交、不覆寫原包，讀取入口見資料契約。
v2 保存五欄來源投影並重算各原因及不同股票數；原 v1 保留歷史，不作最新完整驗證。
另有 [雜訊首筆可重算更正目錄](../../tasks/20261010-hhhl-v4-probability/noise-first-correction-v2/)，
取代原四個noise首筆格；原包保留稽核，其餘1076格相同。最新全格消費須依資料契約
明確讀取overlay，不以原noise首筆值當最新結果；不重跑型態或重抽日期。
v2 保存已選事件、來源選取索引與程式快照，可離線核對首筆及全部四格統計；
原 v1 補件仍保存為歷史紀錄，不再作為最新查詢的充分驗證。
目錄內 correction-transport.zip、correction.001.bin、correction.002.bin 三檔都必要；
分片組回原補件 bytes，不單獨交付 metadata。
另有 [同十筆原事件的L20抽查](../../tasks/20261010-hhhl-v4-probability/landmark-audit-v1.zip)，
補交t0／Z2／bonus與L20狀態、越線、日期、漲幅區及剩餘段欄位；原包不重寫。
reader與來源限制見資料契約；不挑成功案例、不當代表性樣本，不讀新行情。
原 [準備包](../../tasks/20261010-hhhl-v4-probability/preparation-v1/bundle.zip) 與 25/25 驗算
仍保留；四題依 Claude 事前暫定回覆封存，不自動開始下一研究、下載或 H05。
與下方 v1 是不同版本，不能把 v1 數字當作 v4 結果；原 v1 仍完整保留。

`hhhl-pattern-sources.v1`、`stock-derived-cache.v1`、`stock-research-backup.v1` 的固定描述與取得路徑在[架構資料契約](../../tasks/20261008-research-data-architecture/data-contract.md)，驗算／容量／限制在[完成報告](../../tasks/20261008-research-data-architecture/report.md)。Git 有規則及可攜證據；25 檔大型快取在 primary research_cache、不可變且絕對路徑唯讀，不隨 worktree 複製。未完成標註及 producer 移除依賴仍明示。

2026-10-08 增量完成：[`hhhl-probability.v1`](../../tasks/20261009-hhhl-pattern-probability/report.md)
保存擁有者「頭頭高／底底高」原 v1、54 案例來源驗算與 558 個固定描述性彙總。
原突破 126 日翻倍 7.86%，同日新高爆量無事件對照 7.88%；沒有顯示明顯額外優勢。
這不是 F21/F33 假跌破 2B，也非帳戶績效；v1 未過辨識涵蓋率、Claude 定義仍暫定。
[可攜索引](../../tasks/20261009-hhhl-pattern-probability/publication-v1/manifest.json)
含完整彙總、原／更正完成紀錄、十筆抽查與八份結果前輸入快照。
[資料契約](../../tasks/20261009-hhhl-pattern-probability/data-contract.md) 說明大表的
primary 本機位置、查詢／重算與未知／相依／current-reference 限制；不新增期間、
不換 v2/v3、下載或自動啟動下一研究，原 H05 接續狀態未因此改變。

| Stable asset                 | Questions and formal description                                                                                                            | Availability                                                                                                                                                                                                                                                                                                              |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `opportunity-history-web.v1` | [2010 onward wave membership, price basis, saved trend/candidate detail](../../tasks/20261005-market-full-history-web/report.md)            | Local physical producer bundle required; preliminary rules and current snapshot grouping, not a complete historical universe or backup                                                                                                                                                                                    |
| `saved-research-studio.v1`   | [Saved trade/account audits, daily map participation and research-history discovery](../../tasks/20261008-strategy-studio/data-contract.md) | Private external package retains original modeled runs, frozen OHLC and 0050 comparison; preservation receipt: `<primary-checkout>/StockProject/data/private-presentation/20261008-first-stage/restore-manifest.json`; default public mode generates fictional controls; live participation requires pinned local catalog |

設計實驗與累積策略時，優先考慮整個專案的可讀性、可維護性與後續用途。A 策略沒有晉級，其特徵、標籤、診斷或失敗比較仍可能幫助 B 策略；應讓未參與 A 的 session 能從正式入口找到並理解這些資產。

### 開始前查既有資產

先從本頁定位表、方法／假設登記與既有 task catalog，依研究問題、資料用途、欄位／特徵、方法別名及來源尋找可用資料與共用計算。讀取對應資料說明並確認版本、覆蓋、取得方式與限制，再決定直接重用、延伸或新建；在新 task 記錄採用或不採用的理由。catalog 的檔案存在狀態不代表資料已完整、可取得或適用。

計算特徵、標籤或還原價格前，查[型態字典](pattern-definitions.md)及[Stock 衍生資料](research-derived-data.md)的定義與共用實作。適用時直接引用；公式、參數或缺值政策有差異時登記新版本及差異，不以同名副本默默替換，亦不自動改接已封存結果。

### 新增或延伸產物要留下的說明

對具有後續研究價值的資料、特徵、標籤、診斷及結果，在產生它的 task 的 `report.md` 或既有 manifest 留下下列資訊。本頁定位表登記其穩定 ID／名稱、可回答的問題與資料說明連結，讓其他策略能依用途找到它；詳細定義只維護一份，消費任務連回原定義。可用既有格式承載，無須新增平行資料庫。

| 資訊           | 必須能回答的問題                                                                                          |
| -------------- | --------------------------------------------------------------------------------------------------------- |
| 識別與用途     | 穩定 ID、名稱／別名、版本；能回答哪些問題，哪些用途尚未驗證？                                             |
| 資料語意       | 格式／schema 版本、欄位意義與單位、主鍵／關聯、缺值語意；哪些是當日可知特徵，哪些是事後標籤？             |
| 覆蓋與來源     | 日期、股票母體、排除範圍、選期理由；來源／輸入快照版本或 hash、可知時點與已知限制？                       |
| 產生與使用關係 | producer task/run、程式入口、參數與重算方式、輸入依賴；已知 consumer task／策略及其引用版本？             |
| 保存與取得     | 正式路徑、Git 是否追蹤、所屬分支／提交／worktree、已驗證的取得或恢復方式；新 clone／worktree 是否能取得？ |
| 維護與狀態     | 責任模組／維護角色、目前可用／不完整／失效／被取代狀態、相容性及替代版本連結？                            |

未知或未驗證項目明列缺口。只有重算指令不代表原產物已保存或已備份；只在本機／忽略中的檔案必須標示取得限制。可重用也不代表策略通過，或已看過的期間能作獨立驗證。

### 放置與維護

- 通用行情擷取與正規化沿用 `shioaji_stock_prices` 的責任；任務特有證據沿用 `tasks/<task-id>/`，暫存探查沿用 `.tmp/`。持續需要的資料說明與決定回到正式任務紀錄，並從本頁連入。
- 可跨任務重用的資料放在 primary checkout 的 `tasks/<task-id>/datasets/<dataset-id>/`，不可變衍生快取沿用 primary 的版本化 `research_cache/`，擷取產物沿用 producer canonical data。消費端記錄並讀取明確絕對路徑、版本及 hash；不讓 worktree 忽略檔成為唯一正式位置。固定的可變來源快照仍依[工作區資料契約](stock-agent-operations.md#data-and-worktrees)實體保存，不用 live data 取代；此規則不授權搬動其他 session 的產物或去重既有封存資料。
- 確認計算會跨任務使用時，優先延伸既有共用研究模組或 `scripts/`，由任務引用；維持清楚的輸入／輸出契約，避免各策略維護互相漂移的副本。
- 依既有 Git、大小、敏感性與備份契約選擇保存方式，並記錄實際可取得的範圍。搬移、清理或版本替換前，先查 producer／consumer 與固定 run 引用，保留歷史結果的可讀性；破壞性操作仍需另行授權。

### 收尾條件

新建或延伸實驗的交接需讓未參與該實驗的 session，從研究總覽找到相關資產、取得其記錄版本、理解語意與限制，並判斷能否用於另一策略。完成時更新資料說明、定位表及已知使用關係，保留正面、負面與不完整結果；取得或說明仍有缺口時，明列未完成部分，不能宣稱交接完整。

這是後續工作的交付要求，不改寫歷史 mission、結果或驗收規則，也不授權為補索引而開啟封存期間、重跑研究、搬移舊資料或擴大備份範圍。舊資產在後續需要時補定位與缺口說明，保留原始證據。

## 已做研究的定位表：非完整清單

波段的時間調整展示：[`wave-growth-display.v1` 契約](opportunity-presentation.md#time-adjusted-wave-display)、[預先記錄的規則](../../tasks/20261005-opportunity-growth-display/mission.md)、[共享計算](../../research_core/wave_growth.py)、[CLI](../../scripts/score_wave_growth.py)。滿一年採 CAGR，未滿一年採實際漲幅，初始門檻 100%；完整事後波段不刪除。此為同一保存波段的查詢日投影，非新回測、PIT 訊號或完整市場認證；程式／契約可由 Git 取得，原價格快照仍沿用原取得限制。

2026-10-05 可攜消費入口（不需來源 worktree 或行情 submodule）：

| 資產                                                                 | 正式 manifest／使用說明                                                                                                                                            | 邊界                                                                                    |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| 原 atlas 全部比較與定義 `feature-atlas-publication.v2`               | [manifest](../../tasks/20261004-feature-discrimination-atlas/publication-v2/manifest.json)、[查詢例](../../tasks/20261005-market-context-handoff/report.md#讀取例) | Git 可取得全部 7,144 比較；逐股 drilldown 仍需下述 bulk，不重估原結果                   |
| 0050 背景 `benchmark-context.rules.v1`／`market-context-manifest.v2` | [manifest](../../tasks/20261005-market-context-handoff/market-context-v2/manifest.json)、[唯一契約](../../tasks/20261005-market-context-handoff/data-contract.md)  | 2010-01-04..2026-10-02；past-only 與事後層分開，非歷史 PIT 認證、native wave 或含息報酬 |

後續聯合實驗：[method-environment-publication.v1](../../tasks/20261005-method-environment-interactions/publication-v1/manifest.json)
保存全部 624 比較、1,872 路徑摘要、配對結果、六個未晉級原因及原 packet／程式／契約。
[唯一資料契約與 reader](../../tasks/20261005-method-environment-interactions/data-contract.md)
可供網站或研究 session 直接讀取 Git 可攜結果，不需原 bulk 或價格 submodule。
它明示跨來源版本與 past-only 可知性限制；不改寫原 atlas／0050 包，也不代表網站已接入。

H03 後續資產：[industry-role-transport.v2](../../tasks/20261005-industry-role-comparison/publication-v2/manifest.json)
無損保存全部 1,316 比較、3,948 路徑摘要、2,256 配對與三個未晉級判定。
[報告／資料入口](../../tasks/20261005-industry-role-comparison/report.md)、
[分片傳輸契約與 reader](../../tasks/20261005-industry-role-comparison/publication-v2.md)
供其他 session 使用。原 v1 完成包保留本機，v2 只改傳輸，不重算市場結果。
純函式 build_roles 可從指定 atlas 重建逐列角色，Git 包不假裝包含逐股 bulk。

H05 帳戶決策元件：[relative-strength-holding 報告](../../tasks/20261005-relative-strength-holding/report.md)
連到固定政策、特徵／runtime、合成使用例及最新來源契約。211 項測試驗證共用 chronology
與具名來源／停牌／恢復／零股成交接合，市場評估仍為零；尚不是可直接給使用者下單的
工具或已驗證的市場績效。原來源／空前綴 smoke 通過，重用 7,989 現金條款及 12 個
非現金事件，不重抓來源。未綁定事件仍保留；成本與每日量測已新增並通過相關合成測試，
敏感／配置假設、開發停止規則及委託／槽位診斷已固定並通過合成測試；下一步為單次 runner 與市場封包，不重做完成接線。零股盤後成交採明示代理價格，券商預約送單
能力與最終人工負擔仍需驗證，不能以合成測試推定已可每天收盤一次實際操作。

以下是接續時優先查的原報告，不是把舊方法永久淘汰，也不是本輪重驗績效。

最新可重用資產：**feature-discrimination-atlas.v1 / atlas-v2** 可回答「特徵涵蓋多少未來大漲觀察、選中多少未達標觀察」，含所有負例與未知值。入口為 [報告](../../tasks/20261004-feature-discrimination-atlas/report.md)、[唯一資料契約](../../tasks/20261004-feature-discrimination-atlas/data-contract.md) 與 [查詢程式](../../scripts/query_feature_discrimination_atlas.py)。固定 2019-01-02..2026-08-14；不是 PIT 完整股票池、獨立波段或帳戶績效。實體冗餘位於 `D:/Project/Stock/tasks/20261004-feature-discrimination-atlas/datasets/atlas-v2`，重算輸入另存 `atlas-v2-inputs`；已核驗雜湊但同機同碟，Git clone 不含這些大型資料。不可用最新快取默默取代。

| 類別                                                                              | 任務／原報告                                                                                                                                                                                                                                                                                                                            | 接續時的界線                                                                          |
| --------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 2B 與原進場分支分解                                                               | [20260821-2b-entry-decomposition](../../tasks/20260821-2b-entry-decomposition/mission.md)                                                                                                                                                                                                                                               | 特定條件及分支比較，不涵蓋所有 2B、產業或市場環境                                     |
| 產業鏈啟動                                                                        | [20260824-value-chain-ignition](../../tasks/20260824-value-chain-ignition/report.md)                                                                                                                                                                                                                                                    | 舊描述性線索；靜態分類與重疊期間限制不可略過                                          |
| 產業波段與同期間同儕比較（sector-wave-catalog.v1）                                | [資料說明](sector-wave-catalog.md)、[固定 manifest](../../tasks/20261002-sector-wave-catalog/catalog-v1/manifest.json)                                                                                                                                                                                                                  | 可重用的事後標籤；覆蓋、輸入快照、取得與重算依原說明，不作當日可知訊號                |
| 2010 起連續波段與族群證據（20261004-sector-wave-full-history-preview/catalog-v2） | [資料與重用說明](../../tasks/20261004-sector-wave-full-history-preview/report.md)、[固定契約](../../tasks/20261004-sector-wave-full-history-preview/contract.md)、[metadata 恢復索引](../../tasks/20261004-sector-wave-full-history-preview/catalog-v2/bundle-index.json)、[saved rebuild 發布條件](opportunity-catalog-publication.md) | 事後描述；完整 tables／價格／fits 限保留工作目錄，Git 只可還原 metadata；不是交易訊號 |
| 延長持有／出場                                                                    | [20260826-runner-retention](../../tasks/20260826-runner-retention/mission.md)                                                                                                                                                                                                                                                           | 舊資金／容量與資料版本，不直接等同目前帳戶                                            |
| 舊委託整批多等一天                                                                | `20261002-one-lot-delay-resumption/execution-v4.md`                                                                                                                                                                                                                                                                                     | 原固定診斷失敗；不是新的缺席後重評估測試                                              |
| 連續進場確認／市場廣度                                                            | `20261002-entry-persistence/execution-v3.md`；`20261002-pool-breadth-admission/execution-v1.md`                                                                                                                                                                                                                                         | 已有完成且未過原篩選的報告，不應只因改名就重跑                                        |
| 每週排名出場／限制已漲幅度                                                        | `20261002-weekly-rank-exit/execution-v2.md`；`20261002-entry-extension-cap/execution-v1.md`                                                                                                                                                                                                                                             | 原具體設定未晉級，不是整類方法無效                                                    |
| 加碼後退出／加碼重試                                                              | `20261002-failed-confirmation-exit/execution-v1.md`；`20261002-add-retry/execution-normal-v1.md`                                                                                                                                                                                                                                        | 前者失敗；後者僅正常路徑值得後續測試，非策略批准                                      |
| 參與波段／加碼階段診斷                                                            | `20261002-catalog-participation/report.md`；`20261002-add-stage-diagnostic/report.md`                                                                                                                                                                                                                                                   | 描述性診斷，不是新可交易訊號或獨立驗證                                                |

表中的 2026-10-02 九份報告目前不在此 main 衍生 checkout。2026-10-04 已核對它們存在於本機保留提交 `919aef7211255e54b6f22b94d4ab7e698641fcca`，每個表列路徑前加 `tasks/`。例如：

```powershell
git show 919aef7211255e54b6f22b94d4ab7e698641fcca:tasks/20261002-add-retry/execution-normal-v1.md
```

現有實體位置：`D:/Project/Stock/.worktrees/codex-workspace/tasks/`。**這是本機 Git／資料可用性，不是已確認遠端備份或可從全新 clone 取得。** 不清除此保存分支／worktree；遠端不存在該物件或忽略中的 run 不在時，先報告證據缺口，不重跑或捏造歷史。整合舊分支與大產物保存是另行定範圍的工作。

## 下一個有界工作與依賴

| 順序 | 工作                            | 主責／目前狀態                                    | 完成條件                                                                   |
| ---- | ------------------------------- | ------------------------------------------------- | -------------------------------------------------------------------------- |
| 1    | 接收分類 session 的四類資料提案 | 分類端已交付；研究端已讀並保留關鍵限制於本輪報告  | 分清事後標籤、當日特徵、每日合格母體、分類證據；提案不冒充已實作契約       |
| 2    | 選第一批比較的最小資料範圍      | 已在 atlas mission／packet 固定並完成             | 2019-01-02..2026-08-14；缺值、排除範圍與存活偏差限制均保留，不假裝新驗證期 |
| 3    | 建立特徵與未來結果的完整比較    | atlas-v2 完成；38 特徵                            | 已保存所有 7,144 比較並重算一致；單格優勢不等於組合策略或可執行收益        |
| 4    | 少量方法／環境交互比較          | 624 方法交互及 1,316 H03 比較完成；共九候選未晉級 | 完整共同分母、失敗與未知保留；不挑市場單格救回未晉級者                     |
| 5    | 有優勢線索才進帳戶設計／模擬    | relative-strength-holding：量測／敏感／負擔已定義 | 單次 runner 整合與完整 packet 封存核准後才評估市場；合成驗證不是報酬       |

本頁與文件提交不自動啟動行情實驗、開啟確認／holdout、修改 App 目標或恢復 automation。後續可在擁有者已核准的研究方向內由主代理準備有界批次，不需因換 session 重問已確認偏好。
