# Pattern-scan v1 資料與存取契約

目前可直接使用的是純函數，不是正式market pattern-scan dataset：

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
- merge_hit_episodes：caller提供既有label API認定的calendar-full known H126hit起點；
  20session鏈合併，anchor只在起點集合挑，不用所有間隔價。輸出known/unknown、
  reason、原始start_indices、anchor/peak；不算label、不read檔。
- describe_price_path：只描述caller一股aligned closes，unknown不當false，
  完整未缺價窗才報max/min/first threshold與互斥類別；hit outcome另欄，不代表策略。

所有新增函式不讀市場／producer，亦不更動舊selection/episode/evidence。
[mission](mission.md)固定public caller規格；[input pins](params/input-pins-v1.json.gz)
是UTF-8 JSON的gzip，包含原handoff、原始footers/date-key projection、physical snapshot
identity及catalog snapshot。解壓取得metadata，不需要Library。source/SQLite main-only
observations與frozen snapshot身份分開；不是跨來源PIT認證。

## 後續正式資料（尚未生成）

公用資料由primary research_data/catalog固定版本取得，底層research_cache或
既有task dataset原位保存；外部STOCK_RESEARCH_DATA_ROOT，不copy/link共享版本。
fixed-input snapshots是可變producer來源的物理副本，與共享衍生資料不是同一層。

正式manifest必須包含definition_id、input/source/raw-byte implementation hashes、
calendar、price-basis及quality/missing/warmup/availability policy、參數、runtime、
stock set、raw/valid/label-eligible三種期間、unknown原因及backup狀態。
原catalog的legacy/partial/0050 scope不滿足本次全市場新版本。
讀取指定version+manifest_sha；missing/mismatch報錯、不read latest、不silent recompute。

| tidy table                          | 最低穩定鍵／內容                                                                                                                             | 存放                            |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| universe、prices、features、pivots  | security_id/asof_date；eligibility reason、Quality、value／state；pivot extreme/confirm                                                      | formal共享新版本                |
| patterns                            | event_id、pattern_id、subtype_id、t0、pivot、S、L、confirm、source mapping、reason                                                           | formal共享新版本                |
| labels                              | security_id/t0/horizon、calendar_full、main_eligible、outcome、first_hit、unknown_reason、quality_overlay                                    | formal共享新版本                |
| episodes                            | episode_id、security_id、start_indices/anchor/peak、known/unknown reason                                                                     | formal共享新版本                |
| context                             | asof_date/layer，past_only與retrospective分開、coverage unknown                                                                              | formal共享版本                  |
| condition_values                    | event_id/condition_id、bin_id、status、reason、available_at                                                                                  | task本地逐筆                    |
| development_selection               | pattern_id/candidate_id/condition_ids、開發integer counts、固定rank                                                                          | task小表                        |
| pattern/condition/candidate_summary | pattern_id/subtype_id/condition_id/candidate_id/horizon/split/era/mkt/control_id、known/unknown/censored/hit/loss/stock_n/rates/removed_year | task tidy parquet               |
| episode_coverage/timing/examples    | pattern/candidate/episode_id、matched/missed/unknown、offset／returns／quartiles                                                             | task tidy parquet＋可核對事件例 |
| path/first_flag/holding_context     | event或group、horizon、path_category、first_flag/offset、peer known_n、0050 retrospective占比                                                | task tidy parquet               |
| flag/landmark/tradeoff              | pattern/candidate/flag_id/landmark/horizon/riskset/return_bin/split/era/mkt、trigger/cost/unknown/counts                                     | task tidy parquet               |

每張表附schema/欄位字典、完整rows/counts/digest及filters；不僅Markdown。
大型quote-bearing/逐筆輸出在primary本地、小aggregate進Git，receipt說明取得缺口。
未知價格／unknown分類／warming／not_applicable不混成0；不將多次事件比例稱股票比例。
資料／field身分、sources、已暴露期間和synthetic／market證據分開記，report不得越界。

Q4隨機對照保存pattern/candidate、stock/year quota、pool manifest pin、seed、drawn日期及shortfall，
從全期C-base已冷卻池抽取，不能在episode窗口內抽取。matched/unmatched/unknown分母與界、
peak/timing各別known_n遵mission；不以缺峰值或未知detector假裝沒有匹配。

Union同日member的完整metadata另存，representative按mission固定subtype順序，不按後來結果挑。
Q1 subtype與union都有獨立的事件／label母體，不相加，不把union冷卻後樣本當子型全部事件。
