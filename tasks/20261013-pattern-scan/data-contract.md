# Pattern-scan v1 資料與存取契約

以下是保留的 preparation public APIs。完整 fixed-input runner 與讀取／封存／續跑規格
已接線，見 [execution contract](execution-contract.md)；各彙總欄位與分母見
[data dictionary](data-dictionary-v1.md)。目前正在代表樣本的資源預檢，尚無正式
full-period pattern-scan completion 或 Q1–Q6 市場結論。

- research_core.pattern_scan_selection_v1.select_pattern_candidates：
  重用原Atom／SelectionEvent／CRC／counts／candidate編碼，新增100/30、8單項、
  全pair/triple，最多92；必須給單一pattern與explicit target_cohorts，
  union/subtype duplicate identity會fail，confirmation rows不参与選擇。
- research_core.pattern_scan_events_v1.per_group_cooldown：單一caller母體的20session冷卻primitive，
  不延長suppressed day。既有來源與v1證據保留byte-identical。
- research_core.pattern_scan_cohorts_v1.build_pattern_cohorts：caller按stock+pattern提供raw subtype
  mapping；每subtype獨立去重／冷卻，union另從全部raw indices去重／冷卻，兩母體不互相篩選。
  frozen dataclass保存stable subtype順序與各retained_indices/union_indices；future runner只能用這層接線，
  不以union反向刪R2e/R1b/R3b，也不由冷卻後subtypes重建union。
- research_core.pattern_scan_event_outcomes_v1.apply_event_overlay：以frozen BaseOutcome與
  EventIdentity投影，event_id重用artifact_store.object_digest，含stock/t0/pattern/subtype/
  definition/input身分，輸出鍵event_id+horizon。LabelReference固定base-label version。
  detection/result品質原因使該event effective_label unknown；eligibility-only原因只排除主分母。
  原base outcome／calendar_full／first-decision missing語意及其他event不變，理由排序去重並保留scope。
- merge_hit_episodes：caller提供既有label API認定且共通result-window品質通過的calendar-full
  known H126hit起點；先排除結果窗口jump，保存admission counts/reasons，不用pattern回看overlay；
  20session鏈合併，anchor只在起點集合挑，不用所有間隔價。輸出known/unknown、
  reason、原始start_indices、anchor/peak；不算label、不read檔。
- describe_price_path：只描述caller一股aligned closes，unknown不當false，
  完整未缺價窗才報max/min/first threshold與互斥類別；hit outcome另欄，不代表策略。

上述 pure APIs 不讀市場／producer，亦不更動舊selection/episode/evidence。
[mission](mission.md)固定public caller規格；[input pins](params/input-pins-v1.json.gz)
是UTF-8 JSON的gzip，包含原handoff、原始footers/date-key projection、physical snapshot
identity及catalog snapshot。解壓取得metadata，不需要Library。source/SQLite main-only
observations與frozen snapshot身份分開；不是跨來源PIT認證。

## 正式資料的發布與固定存取（完整研究尚未完成）

公用資料由primary research_data/catalog固定版本取得，底層research_cache或
既有task dataset原位保存；外部STOCK_RESEARCH_DATA_ROOT，不copy/link共享版本。
fixed-input snapshots是可變producer來源的物理副本，與共享衍生資料不是同一層。

本次 runner 的 universe/prices/pivots/features/patterns/labels/market bundles，以及
event-outcomes 與 episodes，使用 `research_cache/shared-bundles-v1/<kind>/<data-id>/<version>/`。
研究 report bundle 使用 primary `tasks/20261013-pattern-scan/datasets/<data-id>/<version>/`。
Catalog manifest 的明示 scope/path 才是存取依據，不由上述範例猜測檔名。
`DataCatalog.get_verified(data_id, version_id, manifest_sha256=...)` 在 process 初次使用時
驗證一次並回傳 manifest；caller 留存 descriptor，每次解碼核對實際同一 buffer。
不存在 latest、worktree copies、filesystem links 或 silent recomputation。

Git 中可交付明示 allowlist 的研究 aggregate reading copies，不能交付上述共享
inputs／features 的 worktree 副本。`pattern_scan_transport_v1.export_aggregates`
逐表保留原始 Parquet 全部列，以既有 `binary-chunks.v1` 的 480 KiB 分塊保存；
manifest 記錄 source/input IDs、原始 bytes/SHA/rows 與各 chunk descriptor。
`read_aggregate` 核對 inventory、重建 buffer 的 SHA/rows，再用同一 buffer 解碼，
支援既有 SR-a codec。逐筆 observations、audits、價格與 holding-context 名稱被拒絕。
此工具的合成驗證不代表本研究已有正式彙總結果。

正式manifest必須包含definition_id、input/source/raw-byte implementation hashes、
calendar、price-basis及quality/missing/warmup/availability policy、參數、runtime、
stock set、raw/valid/label-eligible三種期間、unknown原因及backup狀態。
原catalog的legacy/partial/0050 scope不滿足本次全市場新版本。
讀取指定version+manifest_sha；missing/mismatch報錯、不read latest、不silent recompute。

| tidy table                          | 最低穩定鍵／內容                                                                                                                                                    | 存放                            |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| universe、prices、features、pivots  | security_id/asof_date；eligibility reason、Quality、value／state；pivot extreme/confirm                                                                             | formal共享新版本                |
| patterns                            | event_id、pattern_id、subtype_id、t0、pivot、S、L、confirm、source mapping、reason                                                                                  | formal共享新版本                |
| labels                              | 固定label版本內security_id/t0/horizon、calendar_full、base_main_eligible、base_outcome、first_hit、base_unknown_reason；沒有pattern回看overlay                      | formal共享新版本                |
| event_outcomes                      | event_id/horizon、完整EventIdentity、base_label_version/manifest pin、base_outcome、effective_label、event_main_eligible、detection/result quality及eligibility理由 | patterns下formal共享新版本      |
| episodes                            | episode_id、security_id、start_indices/anchor/peak、known/unknown reason                                                                                            | formal共享新版本                |
| context                             | asof_date/layer，past_only與retrospective分開、coverage unknown                                                                                                     | formal共享版本                  |
| condition_values                    | event_id/condition_id、bin_id、status、reason、available_at                                                                                                         | task本地逐筆                    |
| development_selection               | pattern_id/candidate_id/condition_ids、開發integer counts、固定rank                                                                                                 | task小表                        |
| pattern/condition/candidate_summary | pattern_id/subtype_id/condition_id/candidate_id/horizon/split/era/mkt/control_id、known/unknown/censored/hit/loss/stock_n/rates/removed_year                        | task tidy parquet               |
| episode_coverage/timing/examples    | pattern/candidate/episode_id、matched/missed/unknown、offset／returns／quartiles                                                                                    | task tidy parquet＋可核對事件例 |
| path/first_flag/holding_context     | event或group、horizon、path_category、first_flag/offset、peer known_n、0050 retrospective占比                                                                       | task tidy parquet               |
| flag/landmark/tradeoff              | pattern/candidate/flag_id/landmark/horizon/riskset/return_bin/split/era/mkt、trigger/cost/unknown/counts                                                            | task tidy parquet               |

每張表附schema/欄位字典、完整rows/counts/digest及filters；不僅Markdown。
大型quote-bearing/逐筆輸出在primary本地、小aggregate進Git，receipt說明取得缺口。
未知價格／unknown分類／warming／not_applicable不混成0；不將多次事件比例稱股票比例。
資料／field身分、sources、已暴露期間和synthetic／market證據分開記，report不得越界。

Q4隨機對照保存pattern/candidate、stock/year quota、pool manifest pin、seed、drawn日期及shortfall，
從全期C-base已冷卻池抽取，不能在episode窗口內抽取。matched/unmatched/unknown分母與界、
peak/timing各別known_n遵mission；不以缺峰值或未知detector假裝沒有匹配。

Union同日member的完整metadata另存，representative按mission固定subtype順序，不按後來結果挑。
Q1 subtype與union都有獨立的事件／label母體，不相加，不把union冷卻後樣本當子型全部事件。

Event-outcomes 使用獨立、固定的 `pattern-scan-event-outcomes-full-2010-v1` catalog entry，
按 stock/target 分檔並保留 event_id/horizon 鍵；不假設單一 event-outcomes.parquet 檔名。
每bundle只引用唯一base-label version+manifest pin；改引用建立新bundle版本，
舊base及overlay不覆寫。reader驗foreign key的stock/t0/horizon及固定版本，mismatch停止。
同日B1長回看有jump、L1短回看無jump可引用同一base hit；兩個event鍵同時存在，
B1 effective unknown／主分母0，L1 effective hit／主分母1。不能在共用labels表存B1的理由。
raw union member各自的overlay與metadata保留，union另以其固定定義／代表回看形成自己的event投影。
condition/control/candidate summaries消費各自event有效label與資格；base/effective counts、
quality各scope、資格excluded_n分開。known_n是有效且主分母合格的事件數，unknown、censored、
資格排除另列，不能只按security_id/t0/horizon join後套用其他pattern overlay。
