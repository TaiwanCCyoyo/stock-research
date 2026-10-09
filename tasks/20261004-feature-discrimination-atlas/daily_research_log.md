# Work log

## 2026-10-04 — authorized preparation

- Owner clarified feature discrimination precedes choosing a strategy and requires
  both winner coverage and non-winners among feature-positive samples.
- Owner authorized bounded routine choices and completion without repeated
  confirmation; unresolved scientific concerns are to be reported together afterward.
- Refreshed origin and began `codex/feature-discrimination-atlas` from main
  `076e4c6`, preserving the old archive worktree and existing submodule difference.
- Read-only code inventory identified reusable MA, stateful 2B, breakout, VCP,
  RSI2, candle and cross-sectional mechanisms. Legacy price/volume semantics differ;
  their original runs are not modified or treated as directly comparable.
- Initial metadata/schema inventory only; no new feature/outcome comparisons yet.
  Local snapshot is physical. Parent verified submodule HEAD
  `fc6e565c9db40b1218eb1330814756fa0e888d68` after sandbox Git access failed.
- Sandbox uv interpreter-cache permissions prevented one read-only inventory
  invocation. Parent repeated in the authorized environment successfully without
  changing ACLs, cache locations or checks. No market-data download occurred.
- Pure feature and outcome modules delegated separately; main owns this contract,
  data interpretation, run authorization and final judgement.

## 2026-10-04 — first packet approval, before results

- Core code and unchanged exploratory mission committed as `3060e36` with normal
  hooks passing. Synthetic verification: 76 passed, 1 Windows symlink-permission
  skip; no market comparison was used to choose or repair the calculations.
- Parent reviewed `params/atlas-v1.json` and authorizes exactly this one bounded
  exploratory execution under the owner's instruction to finish organizing data.
  Canonical packet SHA256:
  `7f77af3fdd61f4f00f83ce9f1d7627b8b6858c1a89f0266448fe384a9882bfc1`.
- This approval fixes 38 binary features, 20 continuous components, both outcome
  definitions, daily and grid126 panels, context comparisons, runtime, input bytes
  and the 3600-second cap. It does not authorize parameter tuning or a strategy.
- Review found no HIGH causal/cohort defect. Current metadata, overlapping daily
  samples and price-versus-account-return limitations remain explicit; code review
  is not independent financial validation.

## 2026-10-04 — runtime-only retry diagnosis

- `atlas-v1` began with verified input identities but was stopped before aggregate
  comparisons completed. This is **execution incomplete**, not candidate failure
  or evidence of a weak feature. All partially written tables and runner state
  remain in the original run directory; no completed receipt is fabricated.
- Progress projected beyond the fixed 3600-second budget. Timed already-written
  quality examples without selecting on outcomes: 1101 feature calculation 0.081s;
  1213 with 248 missing calendar quotes 3.073s. Many tiny valid segments incurred
  repeated calculations whose outputs were entirely unknown at those lengths.
- The sole retry change skips impossible warmup computations: legacy components
  before 20 observations, general features before 3, and directly computes only
  the existing 3-bar inside-bar flag for segments shorter than 14. No threshold,
  cohort, price, label, context, sparse grid or unknown-data rule changes.
- Add exact short-segment equivalence fixtures before a new packet. This is one
  diagnosed implementation retry within the original three-attempt limit.

- Retry code committed `3b74e38`; 48 scoped tests passed. Already-written 1213
  values matched exactly after optimization, with combined feature/legacy time
  falling to 0.705s. No aggregate outcome comparisons were inspected to choose it.
- Parent approves only `params/atlas-v2.json`, canonical SHA256
  `728a9659c8ef94f7d2858d354a4af2b329edb5a5ff070b94f169ecb35788a4a3`.
  Compared to v1, only the job ID/argument and those two implementation hashes
  change. The source bytes, scientific definitions, runtime and budget are identical.

## 2026-10-04 — atlas-v2 完成與證據保存

- atlas-v1 於 509.187 秒停止，保留原部分輸出及 failed 狀態；這是執行不完整，
  不是特徵或策略的否決。atlas-v2 僅以相同定義的暖機快速路徑重試，於
  704.36 秒完成，沒有因彙總結果更動條件。
- 完成固定 2019-01-02..2026-08-14 現行普通股參考母體：1,941 檔、
  3,588,909 筆股票日期列、2,788,023 筆合格列、38 項特徵、7,144 筆比較。
  label_63 正標籤 192,232 筆、label_126 正標籤 130,112 筆，均不是獨立交易。
- F37 每日主標籤精度 9.43%，同母體基準 5.46%；選中且後續已知列中
  90.57% 未達兩倍，不能稱為虧損。2B／K 線的每日與 grid126 相對結果反向，
  完整 38 項及限制已寫入 report.md，未挑選有利列或宣稱優勝策略。
- parent 完成 95 passed、1 Windows symlink 權限 skip，全部比較重算一致，
  receipt 重用核驗及 finalizer 輸出／重播輸入雜湊保存核驗通過。
  完成 dataset_id 為
  `fda-86245f2e223fc45c9f84afb0dcf77c1fff7ab22d0a1b0b4a4c8800972ce9327e`。
- 第二份輸出位於主 checkout 的 `tasks/20261004-feature-discrimination-atlas/datasets/atlas-v2`，
  精確宣告輸入封存為 `atlas-v2-inputs`。兩者是同實體磁碟冗餘，不是災難備份。
- 稽核時序補充：v2 canonical packet 雜湊及核准存在於開始前，但 packet 的
  Git 提交在開始後不久、彙總完成前才完成；不宣稱執行前已提交。
- 資料整理完成；策略評估仍為 not_evaluated。報告沿用已驗證保存證據，
  沒有再次執行研究、讀市場來源、擴展視窗或新增策略授權。
