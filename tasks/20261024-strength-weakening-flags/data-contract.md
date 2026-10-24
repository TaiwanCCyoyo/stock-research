# 強勢條件成立後的轉弱訊號：資料與執行契約

工作包 B 只交付程式與合成測試；尚未讀取本研究的市場資料或產生市場結果。
本契約補充 [交接規格](codex-handoff.md) 的 B、C，不改 W1–W10。
研究 mission 由獨立的工作包 A／PR 91 交付，兩個 PR 都由 owner 合併後才能開始 C。

## 入口與保存位置

- `research_core.multiple_observations_v1`（`multiple-observations.v1`）：
  `classify_window(closes, horizon, target_multiple=2)` 與
  `landmark_riskset(closes, landmark, z2=1, target_multiple=2)`。
  回傳原 `WindowObservation`／`LandmarkRiskset`，只把固定兩倍改為參數。
  日曆列不刪除；hit 吸收其後缺價，但 landmark 必須整段前綴完整；L 當天 hit 不入 riskset。
- `research_core.strength_flags_v1`（`strength-flags.v1`）：
  `BatchFlagIndex(frame, pivots, max_horizon=504)` 只讀 caller 的已對齊資料；
  `histories(flag, t0s, cutoffs)` 是計數使用的批次 API，狀態編碼依 `FLAG_STATES`；
  `observations(...)`／`batch_event_observations(...)` 提供與 PR17 public API 同欄的診斷長表。
  新增 `t0_index`、`target_multiple`，Y1、Y2 為 `not_applicable`，其他欄位沿用 PR17 語意。
- `research_core.strength_flag_counts_v1`（`strength-flag-counts.v1`）：
  `count_stock` 產生整數 counts；`cell_cube`／`estimate`／`intervals`／`summarize_cell`
  從 counts 做估計，不再計算逐日特徵。
- `research_core.strength_flags_run_v1`（`strength-weakening-flags.v1`）集中市場入口、
  對齊檢查、資源量測與收據；`scripts/run_strength_flags.py` 為薄入口。
- 中間結果只存 `scratch_runs.create_run` 建立的
  `<STOCK_RESEARCH_SHARED_ROOT>/scratch/20261024-strength-weakening-flags/<run>/`。
  `stocks/*.npz` 是逐股衍生資格、atoms 與標籤；`counts/*.parquet` 是逐股整數統計。
  不保存 producer 輸入副本，不對中間檔或程式碼計 SHA-256。
- 最終小表位於 `tasks/20261024-strength-weakening-flags/results/`，no-replace 發布；
  只有最終檔記 SHA-256。收據另記共用讀取資訊、程式 commit、定義、參數及輸入指紋。
  JSON 使用 `artifact_store.write_json` 的 UTF-8 canonical 序列化，最終發布補單一 LF，先固定最終 bytes 再記 receipt；
  `.prettierignore` 只排除此任務 `results/**`，避免正常格式化改變已記錄的結果。
  任務目錄內沒有研究 runner，也沒有額外測試根目錄。

## 輸入與訊號時鐘

唯一價格來源是 `read_adjusted_daily("reference_factor_adjusted", as_of="2026-10-12", generation=...)`；
日曆與股票清單使用 PR61 `pr17_calendar()`／`pr17_codes()`，從 2010-01-04 起共 4,110 sessions、1,942 檔。
S6、C-52w、CORE、LEAD_B1 成員資格與 effective-label／main eligibility 引用 `momentum_only_v1`。
這四組不使用 H，因此沒有重新計算全市場橫斷面排名。

指標與 1.5ATR 已確認 pivots 來自 `prepare_detector_frame`。X5、X7、X8 的獨立日序列
由原 public `event_flags` 一次驗證／計算，再建立下一個 true／unknown 索引；
Y3 只取 t0 已確認、低於 anchor 的最高 low；X6 固定 t0 anchor。
Y1、Y2 沒有型態價位，永遠不適用。unknown 先於首次 true 時保留 unknown，不被之後 true 修復。
訊號在達標當天才出現不算「達標前觸發」。所有 cutoffs 必須在已建立索引的範圍內。

20 檔代表股票固定採 PR61 的六檔加 CRC 排序前 14 檔。
共用 technical 表的 asof 若不同於歷史 cutoff，不可截掉未來列冒充截止日重算，直接沿用 PR17 adapter。
asof 相同且存在對應欄時，逐欄、逐值比對 20 檔；全部相等的 SMA20、SMA60、BB 下軌、
C3、D2、G2_limit 數值在正式計算中實際讀共用欄，不相等的仍採 adapter。
G2_limit 由共用 `raw_return1 >= 0.095` 得到，缺值保持未知。
pivots 無論數值欄來源如何，都使用 adapter 回傳者，不讀不同確認政策的替代資料。

## Counts 與表格欄位

逐股 counts 一列的鍵為：
`code, group_id, basis, horizon, target_multiple, landmark, flag_id, year, flag_state, rise_bin`；
`split` 是 public `split_for_code` 的 `development`／`cross-check`。
`basis=daily|cooled`；冷卻先套組別成員資格與 S6，再拆訊號狀態。

所有計數為整數，率在完成加總後才計算：

| 欄位                            | 語意                                                            |
| ------------------------------- | --------------------------------------------------------------- |
| `event_n`                       | 本格保留的事件數；landmark 為有效前綴且尚未達到該倍數的 riskset |
| `known_n`                       | PR61 main-eligible 且 effective-label 已知                      |
| `hit_n`, `loss_n`, `flat_win_n` | 已知主分母的互斥結果                                            |
| `unknown_n`                     | effective-label unknown，保留缺價／品質不明                     |
| `censored_n`                    | 日曆期限尚未走完，不進主分母                                    |
| `full_hit_n`                    | calendar-full effective hit；full-scope 用來算達標前觸發代價    |

`landmark=H` 為 full-scope，保留所有成員事件而不套尚未 hit 的 riskset；
此列不是額外觀察點，只供首次達標前的錯殺代價。
rise 層為 `lt1, b1_1p10, b1p10_1p25, ge1p25`；full-scope 末價未知另保留 `unknown`。

正式輸出按組別與期限分成：

| 終表                                         | 一列與內容                                                                                                                                |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `summary-<group>-H<h>.parquet`               | 組別 × 倍數 × 觀察點 × 訊號 × 切片；觸發／未觸發達標率、比、合併差、分層差、各狀態 counts、每日股票數、冷卻已知數／股票數、錯殺代價與判讀 |
| `intervals-<group>-H<h>.parquet`             | 同格 × 方法 × 估計量；seed、重抽 2,000 次、可定義次數、95% 百分位區間                                                                     |
| `rise-strata-<group>-H<h>.parquet`           | 同格 × 每日／冷卻 × 訊號狀態 × rise 層；整數 counts                                                                                       |
| `alignment-totals.parquet`                   | 四組 × 2 倍 × H126／H252 的 known／hit／loss、PR61 值與整數差                                                                             |
| `alignment-sample.parquet`, `alignment.json` | seed 20261024 抽的 200 個 CORE 事件及逐值對齊完成狀態                                                                                     |
| `indicator-probe.json`, `timings.json`       | 20 檔逐值來源選擇、階段資源量測、worker／in-flight／記憶體上限及外推限制                                                                  |

全格明列，包括沒有成員或沒有 riskset 的格子；不從 full-scope 推測其觀察點。
主格只為 CORE／LEAD_B1 × 2 倍 × H126／H252 × L20 × 7 適用訊號，共 28 格。
其他格及 Y1／Y2 均保留。年代、CRC、drop-best-year／stock 的切片列出估計，不自行套入主判讀。
drop-best 先按本格主分母 hit 找最多年份／股票，ties 取較早年／字典序較小股票，再重加總剩餘 counts。

分層權重為 triggered 的已知結果分布；有正權重的層缺 untriggered 已知結果時，分層差為 null，
不刪除該層後重新正規化。bootstrap 成對重抽完整 stock／stock×year counts；
stock seed 20261024；two_way 股票 seed 20261025、年份 seed 20261026，均 2,000 次。
任何估計量若有不能定義的重抽，其區間為 null 並列可定義次數，不用刪掉無法定義的重抽取得結論。
零分母率與倍數為 null，不把 unknown 當 0。

## 執行邊界與 C-2 停止

```text
uv run python -m scripts.run_strength_flags --mission-pr 91 --code-pr <B PR> --run <label>
uv run python -m scripts.run_strength_flags --mission-pr 91 --code-pr <B PR> --run <probe-label> --probe
```

所有市場入口都以 GitHub 即時檢查：兩個不同 PR 已合併入指定 repository 的 `main`，
A 必須包含此任務 mission、B 必須包含此 runner；缺失即拒絕，不提供 skip override。
執行 checkout 先 fetch，乾淨且包含最新 origin/main 與兩個 merge commit。
每次讀資料前檢查 producer idle；固定並 hold 本研究自己的世代，遇同 holder 的其他 run 就停止。
不下載、不改排程、不觸碰 PR17 的 hold／執行程序或 PR61 前瞻紀錄。

正式執行先重算四組基準與 PR61 終表完全對齊，任何一個整數不同就保留差異並停止。
200 個 CORE 樣本同時比對診斷表和實際計數的 `histories` 快速路徑，含所有狀態、offset、riskset、rise_bin。
scratch 保存逐股對齊 totals；若只有 PR61 公開的彙總可用，不能據此推知受影響股票或宣稱原因已證實，
差異報告會並列當次世代、PR61 收據記錄及尚待 owner 釐清的原因，絕不調規則。

`--probe` 只量 20 檔，不偷偷執行全市場對齊或發布正式結果；標 `alignment_pending`、
`research_complete=false`，它的 scratch complete 僅代表資源探測完成。
正式執行仍強制全套 C-2。相同輸入測串行及可准入的 2／4 workers，逐值比較整數表；
明列 wall、CPU、RSS、I/O、序列化及啟動觀測限制，量不到記 unavailable。
另量 counts 存檔與一格 bootstrap，以股票數／格數外推，說明稀疏程度、壓縮及不同格的差異限制。
採用量測最快且符合明確記憶體上限的 worker 數，in-flight 不超過 workers；
磁碟或 summary 記憶體外推超出上限就停止，不縮小股票、訊號或規則。

正式小表與收據寫完才將正式 scratch run 標 complete；報告、卡片、網站與 owner 交付仍屬工作包 D。
正式執行不自動標 delivered 或釋放 hold；資源探測在所有讀取完成且 holder、generation、run reason 都吻合後釋放自己的 hold。
D 經正式移交後用既有 `scratch_runs` API 登記保存位置，
再只 release `strength-weakening-flags`，最後依 scratch 規則處理本研究暫存。
