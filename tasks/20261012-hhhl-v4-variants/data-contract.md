# HHHL v4 variants 共用資料契約 v1

定義 ID：`hhhl-variants-features.v1`；實驗／候選 ID 前綴：`hhhl-v4-variants.v1`。mission 已由 owner 合併，**固定計算完成，完整彙總及 primary 逐筆版本已發布**。[報告](report.md)、[數字附錄](result-tables-v1.md)、[驗證收據](verification-v1.json)與程式透過 PR #9 交付，merge 仍由 owner 決定。批准與固定公式在 [mission](mission.md)，來源身分在 [input pins](params/input-pins-v1.json)，執行與同規格性能延續方式在 [execution plan](execution-plan.md)，完整結果欄位在 [summary schema](summary-schema.md)。

## 已可取得的共用定義

| 模組／API                                                                | 提供內容                                                                                                                                              |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `research_core.hhhl_variants_features.feature_inventory()`               | 24特徵／76有效bins、數值邊界、族、pattern-only／overhead-only／diagnostic-only。                                                                      |
| `classify_feature(id, value, applicable=..., unknown_reason=...)`        | supplied value變成bin或feature_unknown／not_applicable，保留原因；不是市場feature runner。                                                            |
| `research_core.hhhl_variants_selection.select_candidates(events, atoms)` | development-half exactFraction、300／60單項門檻、族去重、全部交集與固定ID；不能直接丟P-all重複列。                                                    |
| `research_core.hhhl_variants_observations`                               | `classify_window`、`landmark_riskset`、`flag_history`、`previous_completed_week_signal`、`confirmed_pivot_view`。純輸入陣列觀察，不下載、不偵測事件。 |

取得：clone本repository後讀上列Git檔。測試：`uv run python -m pytest scripts/tests/test_hhhl_variants_*.py -q`（shell glob支援不同時請展開檔名）。inventory查詢：`uv run python -c "import json; from research_core.hhhl_variants_features import feature_inventory; print(json.dumps(feature_inventory(), ensure_ascii=False, indent=2))"`。既有frozen source／atlasreader仍是正式來源，不能將新bin分類器冒稱完整特徵計算。

## 已出版的逐筆資料

大型版本目錄固定 primary：`D:/Project/stock-research/tasks/20261012-hhhl-v4-variants/datasets/hhhl-v4-variants-01/`。worktree不作唯一存放處；每個artifact有relative portable path、bytes、SHA-256、schema／rowcount、keys與price basis，manifest及外部pin由Git小型receipt引用。新clone無本機逐筆輸入時回報missing；向owner取得該immutable版本，再以manifest驗证，不能重新下載或重造舊v4事件。

大型邏輯表以 `observations/<ordinal>.parquet`（事件／股票日×H）、`features/<ordinal>.parquet`（股票日×24特徵，值與bin／原因）、`flags/<ordinal>.parquet`（原P event×flag×L/H，firsttrigger／unknown）分片保存。`daily/<ordinal>.parquet` 存每日計算值，`pivots/<ordinal>.json` 存低點極值與確認 index；ordinal 依原 atlas security_id 排序，manifest 每片另列 original code，不能把檔名當股票代碼。另有 `daily-boundaries.parquet`（K3分界與H有效群體數）、`selection.json`（僅development選擇／候選）、`event-counts-by-stock.parquet`、固定10筆 `audit/ten-events.json` 與 `audit-digest.json`、`execution-start.json`、`manifest.json`。逐筆資料不混進小型Git封裝。

`observations`最低鍵 `(cohort_id,event_id,horizon)`，重複為錯誤；C控制event_id是固定cohort/code/ISO t0、可跨cohort重疊。原P event_id不改，逐筆亦存 P-all 聯集列：每個原事件在兩個 H 各有原群與 P-all 一列，通常共四列。取得原事件集時只選 P-clean／P-over，或只選 P-all，不能兩者相加。另存original code、t0、calendar_index、split_id、calendar_full、full_path、label、first_hit_offset、first_missing_offset、reason。數值null和狀態unknown與0分離。feature只用t0可知值；flag只用確認時點，來源pivot extreme與confirmed兩日期都存。

所有P事件的聯集率稱事件比例，不是股票比例；`known_security_n`是主known分母distinct code。同股重複與控制重疊不是獨立證據。2019暖機不足、current-reference行业／factor／rank、已暴露期間都須保留。

## 一份完整彙總 parquet

Git小型交付：task下完整邏輯 `publication-v1/summary.parquet` 的分片、`publication-v1/receipt.json` 與本 task 的 `summary-schema.md`。邏輯 parquet 共 159,609 列／8,941,105 bytes；為保留每個新增Git檔500KiB限制，原始 bytes 以每片480KiB的 `summary.parquet.part-00000.bin` 等19片依序保存。receipt 列每片 bytes／hash及重建後完整 parquet 的 bytes／hash／rows，query 在記憶體驗證並重建，沒有重新計算。primary dataset 亦保有單一實體 `summary.parquet`。全部基本切片／未知／不適用／候選／年度／旗標／敏感性在同一parquet，以row_kind區分；合法zero known列照列，率null。

逐筆 dataset ID 為 `hhhl-variants-8655494b7ed84915eda8468d1fe21f7d2903919f27ece0fd548137ba6573755c`；manifest 外部 pin 及完整 summary hash 由 Git receipt 固定。完整年度表 127,680 列、刪最好年表 15,960 列；legacy 基本表實際 192 列，為 4L×2H×2split×2cohort×2上方線×3state，完整庫存已核對。mission 的比較上界不作補造重複列的理由。本機資料不是異機備份；尚未聲稱有額外備份。

| 欄位                                                                                                                                      | 語義                                                                                                                            |
| ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `row_kind`, `candidate_id`, `feature_id`, `bin_id`                                                                                        | baseline／single／candidate／Kdistribution／flag／reverse_flag／legacy_cross／near_high／year／drop_best_year等；不適用欄null。 |
| `cohort_id`, `split_id`, `horizon`, `landmark`, `riskset_id`                                                                              | P-clean/P-over/P-all/C-nh/C-52w/C-base；development/cross-check（owner直接問題另pooled）；H126/252；不同riskset不可混分母。     |
| `feature_price_basis`, `definition_id`, `input_dataset_id`                                                                                | frozen-v4 reference、raw-volume／raw-price／source-regime等明列；共享版本與pin。                                                |
| `calendar_full_n`, `hit_n`, `loss_n`, `flat_win_n`, `unknown_n`, `censored_n`, `known_n`, `known_security_n`                              | 主結果五項計數與截尾分開；hit+loss+flatwin=known，known+unknown=calendarfull；censored不能返回主known。                         |
| `hit_rate`, `loss_rate`, `hit_lower`, `hit_upper`, `loss_lower`, `loss_upper`                                                             | 率使用列的明確分母；zero分母null，不填0。                                                                                       |
| `flag_state`, `flag_unknown_n`, `flag_triggered_n`, `flag_all_false_n`, `flag_denominator_n`, `riskset_n`                                 | flag比例分母可能是全部最終hit/nonhit，與新riskset已知最終label分母分離；unknown包含在allhit代價界。                             |
| `flag_lower`, `flag_upper`, `return_bin`, `trigger_return_p10`, `trigger_return_median`, `trigger_return_p90`, `trigger_return_unknown_n` | 時序依mission；分位數linear，非交易損益。                                                                                       |
| `year`, `removed_year`, `small_sample`, `not_applicable_reason`, `unknown_reason`, `reference_*`                                          | 年度／最好一年刪除、known<300註記、未知與控制參考及loss差≥10pp註記，不作晉級。                                                  |

reason breakdown若有多原因須按固定優先序互斥（invalid_anchor→missing_before_hit→window_end；feature先not_applicable再source缺值再warmup），另metadata保存全部validator diagnostics。receipt 列每種 row_kind 與 base_row_kind 的列數；keys 與分母見 summary-schema.md 及 summary 的 riskset 欄位，不依外觀合併不同比率。

固定執行入口：`uv run python -m scripts.run_hhhl_variants --primary D:/Project/stock-research --approved-mission-merge fcda359370cd81594451839d4e79e2216cbce255`。要求 clean committed code，逐筆版本或 publication 已存在即拒絕覆寫，不下載或重偵測事件。執行收據封存程式hash、環境與核准 merge。

同規格延續入口：`scripts.continue_hhhl_variants`，要求 primary 的完整 sealed daily cache，前後核對原 code、輸入、快取 hash 和股票身分。
其共用實作為 `hhhl_variants_continue_v1`、`hhhl_variants_continue_pipeline_v1`、`hhhl_variants_summary_fast_v1`；
`hhhl_variants_publication_v1.publish_result` 只序列化已驗證結果，不授予計算權限。
receipt 的 `execution.cache_lineage` 提供原 attempt 及 cache seal 取得路徑、hash；延續前須依 execution plan 停止原 writer，不能並行啟動同一版本。

出版後查詢：`uv run python -m scripts.query_hhhl_variants --publication tasks/20261012-hhhl-v4-variants/publication-v1 --verify`，或加 `--row-kind baseline --cohort P-all --horizon 252` 等 exact filter。`--event <original-event-id> --part observations`／`flags` 驗外部 manifest pin 及相關分片，只讀本機逐筆版本；新 clone 沒有本機版本會明確失敗。小型彙總查詢只需 Git publication。沒有參數搜尋、下載或缺資料補算功能。

## 核對與同規格重算

正式 CLI 的固定版本已存在時會拒絕執行。完整同規格重算可使用共用 API `research_core.hhhl_variants_run.run_study(inputs, staging)`：`inputs` 是 `FrozenInputs(primary, pins_path)`，`staging` 由呼叫端在自己的新 task 或 scratch 建立並確認為空。它回傳完整彙總與固定選擇清單，逐筆輸出寫入該新目錄；來源、24 特徵、控制與選擇規則都由固定實作提供。先取得 input pins 宣告的全部版本，核對發布 receipt 的程式與環境身分，完成後呼叫 `inputs.verify_after()`，再與發布的邏輯結果比對。publisher 新增的來源身分欄另行核對，不把它們當計算差異；重算資料亦不覆蓋原版本。

需要快取延續時，從 receipt 的 `execution.cache_lineage.path` 取得保留的 `daily-cache-seal.json` 與其來源目錄；先核對該 seal 的外部 hash，再呼叫 `research_core.hhhl_variants_continue_v1.verified_cache(source, seal_path, pins_path, inputs)`。傳回的 `seal["artifacts"]` 供 `run_cached_study(inputs, staging, source, seal["artifacts"])` 使用，完整名稱是 `research_core.hhhl_variants_continue_pipeline_v1.run_cached_study`。重算前後都驗 cache／輸入／程式身分；缺少原 cache 時使用上述無 cache API，不能製造 seal 或略過核對。這兩條路徑已有完整合成結果 parity；本 task 的正式執行採有封存來源的延續路徑。

只需核對既有結果時，task 的 `evidence/verify_ten_events.py`、`verify_peer_features.py` 與 `verify_summary.py` 分別獨立核對固定抽查、同日同儕特徵，以及完整彙總守恆／年度規則。前兩者接受絕對 `--dataset`，後者接受絕對 `--publication`；核對輸出只列身分、hash 與檢查數。其他研究延伸採用這些共用定義時，仍先在自己的 mission 記錄使用版本與 changed requirements，避免把本版描述結果冒稱新的策略驗證。
