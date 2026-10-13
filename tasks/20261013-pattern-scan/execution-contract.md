# Pattern-scan 執行與重現契約

Owner 已合併 [mission PR14](https://github.com/TaiwanCCyoyo/stock-research/pull/14)，
merge commit `d2dea1e70b18b624ee2da0b69a63d5b2638f27f8`。
本階段接續同一 author worktree，branch 為 `codex/pattern-scan-execution`。
原 preparation packets、凍結 helper 與 producer 實體快照保留。
本檔描述執行契約；完成狀態及市場結果以之後的正式 receipt／結果報告為準。

## 唯一固定輸入與共用入口

Owner 指定的 handoff 是 primary `.tmp/claude-kline/20261012-claude-handoff-pattern-scan.md`，
raw-byte SHA-256 `153d4bfb8d99cfa5413dffca8a0f8c0b20c3b313b1a92dc25e3143688936b3be`。
它沒有被宣稱與另一份 Library 文件相同。

五份 frozen mutable inputs 已 verified-copy 交到 primary
`tasks/20261013-pattern-scan/inputs/observed-v1/`，總計 242,944,932 bytes；
manifest SHA-256 為
`78e5a5787aacd8eb4189b5f8eaddb691d89a008e6ea56cd5ec8b01f20fc45438`。
每次計算只讀該身份，不讀 producer live data，不重新 seed，沒有取得或刷新資料。
SQLite 使用 immutable/read-only URI，並驗證 sidecar 與原始 byte identity。

正式 shared versions 的 catalog 在 primary `research_data/`；
唯一 published payload 在 primary `research_cache/shared-bundles-v1/`。
Worktree 使用明示 absolute root 與 data/version/manifest pin 直接讀取，
不複製 published versions，也不建立 symlink、junction 或 hardlink。
Primary `.tmp/pattern-scan-execution/<run-id>/` 的計算 checkpoint 與 staging
是本次 task-owned 中間資料；它們不充當另一份正式共用入口。

## 公開入口與分階段 receipt

CLI 為 `uv run python -m scripts.pattern_scan`，所有 workflow logic 在 `research_core/`。
必須提供 `--primary-root`、`--data-root`、`--input-manifest-sha256`、`--run-id`
及 explicit `--calculation-authorized`；這個旗標記錄已有 owner 授權，不能自行授權研究。

| 階段             | 公開 library                                                                                 | 產物／停止語意                                                                                                       |
| ---------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| 固定來源         | `pattern_scan_execution_v1.source_identity`                                                  | AST project dependency closure、實際 raw bytes、runtime、numerical thread limits；deterministic source ZIP           |
| Input 與成本     | `pattern_scan_pipeline_v1`／`pattern_scan_run_v1.launch(mode="profile")`                     | 固定 coverage strata、serial reference 與 1/2/4 workers；相同 files／integer rows；資源觀察不代表 Q1–Q6 完成         |
| 單股             | `pattern_scan_stock_v1.stock_phase`                                                          | 12 detector families、raw members、獨立 cohorts、controls、base labels、qualification／unknown audits                |
| 全股票 barrier   | `pattern_scan_barrier_v1`                                                                    | 完整 supplied stock/calendar grid 後才算 H/J/K3、raw PAT、0050 past-only／retrospective context                      |
| Event projection | `pattern_scan_event_tables_v1`／`pattern_scan_analysis_v1`                                   | canonical event/horizon；controls aliases 另以 membership 記錄；固定唯一 base-label version＋manifest                |
| Q1–Q3            | `pattern_scan_membership_v1`／`pattern_scan_count_matrix_v1`／`pattern_scan_dense_counts_v1` | 零格 registry、整數母數與 stock sets、2010–2026 annual／same-cell drop-best-year；一次處理一個 group/horizon         |
| Q4               | `pattern_scan_episode_run_v1`                                                                | H126 admission／excluded starts、所有 matches、timing certainty、random quotas／pool pins、獨立 daily baseline       |
| Q5–Q6            | `pattern_scan_followup_v1`／`pattern_scan_followup_summary_v1`                               | 同一 original event clock 給 candidate 子集；streaming counts 與精確 quantile samples；48 fixed facets 與 zero cells |
| 完整流程         | `pattern_scan_run_v1.launch(mode="all")`                                                     | 同 source/input resource profile、明確有限資源設定、各階段固定版本與最終 complete-study receipt                      |

原 preparation 的 `pattern_scan_events_v1`、selection、cohorts、event-outcomes 等
SHA-pinned source 保持 byte-identical。新 API 不使用舊 atlas reader 的 2019 起點。
Frozen source ZIP 保存實際執行 dependency bytes；bug fix 另記 source／run identity，
不替舊結果重 pin，也不在看結果後放寬規格或 selection gate。

## 表格身份、未知與比較

- Daily prices／indicators／universe／pattern states 帶 `security_id`、`calendar_index`、
  `asof_date`；pivot 的 as-of 是 confirmed date，不能把 extreme date 當可知日期。
- Base labels 使用 `security_id/t0/horizon`，保留 first-decision 與 calendar fullness。
  Event outcomes 使用 `event_id/horizon`，另保存 detection/result 品質 scope、資格排除，
  同日不同 pattern 不覆寫共用 base label。
- Ordinary missing after hit 保留 base hit；全 result window 的 unexplained jump
  仍可使該 event/horizon effective unknown。Eligibility-only 不改 label。
- Raw states 為 `-1/0/1`；unknown 不歸入 no-pattern。Candidate known false 可吸收 unknown；
  not-applicable 另列。型態專屬欄不捏造 control comparison rate。
- CRC 使用原 code UTF-8，`TW:` 是 security namespace，leading zeros 保留。
  Q1–Q3 的 all/development/cross-check 與 Q4–Q6 的兩半 facets 不相加。
- Main C-base-all 使用自己的冷卻；Q4 的 daily C-base baseline 獨立命名。
  Random controls 使用全期冷卻 pool、固定 seed、stock/year quota；shortfall 保留 unknown。
- 每一單條件 bin、unknown／N-A、全部選定候選、zero cells、annual／drop-year 都保留。
  候選 confirmation 主表限 cross-check；development counts 保存在 selection packet。
  Q4–Q6 最多 132 groups；landmark 原點與終點仍為 t0 和 t0+H。

## 路徑、隔離與失敗

所有根與 lexical ancestor 先套既有 `research_data_paths` 防護：
拒絕重疊 worktree、reparse paths、hardlinked files、Windows unsafe artifact names。
Read-only attributes 只作附加措施；隔離的 Windows 刪除測試另由 PR12 保留。

計算在 fresh source-compiled、task-owned Windows Job 中執行；
stock workers ≤4、process batch ≤8，每個 process 同時只算一股。
每子 Job 與 coordinator 都有明示 committed-memory cap；它與 RSS 的觀察範圍不同。
總上限 ≤8GiB 並保留至少 4GiB host available memory；來源或 input identity 改變、
budget／完整 barrier 不成立、祖先缺失或檔案毀損時停止，不用 latest／live fallback。

Publication 沿用 verified physical copies、no-replace final 與 additive catalog。
Resume 只信完整、身份相同且 payload 再驗通過的 receipt；partial staging 保留供診斷。
同機 primary copy／計算 checkpoint 不算異機備份；未觀察到的 backup 或 PIT availability
明列 unknown，不以 infrastructure tests 證明策略可用。
