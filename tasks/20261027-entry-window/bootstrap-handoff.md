# E1-B2a：paired count cube 與 bootstrap 交接

工程定義：`entry-window-bootstrap.v1`；研究定義仍為 `entry-window.v1`。
本包完成純記憶體核心、合成驗證與本機 shared CI／program 接線，**尚非 merge-ready**：
最終整合的 Astra SHA-bound review、hosted CI 及 parent ready／merge 仍為獨立關卡。
沒有真實市場結果、reader、runner、CLI、result、receipt 或研究結論。

## 所有權、基準與契約

- Owner：本次 E1-B2a task-16；branch `codex/entry-window-bootstrap`。
- 隔離 checkout：`C:/Users/xjp01/Documents/Codex/2026-10-27/task-16/repo`。
  本 session 僅建立這一個 worktree，因本機交付／待審查而保留；不清理其他 session 的資源。
- Fetch 後 base：`9945d6878e1b3be530e4790ef8fd3a5db6dbcc7a`（已合併 PR105）。
  開工 GitHub open PR collection 為空；worktree／branch metadata 未出現其他 bootstrap owner。
  S7-B1 的 `multi_timeframe_ma_core_v1` 為平行獨立 owner。
- 核心套件三檔：`research_core/entry_window_bootstrap_v1.py`、
  `scripts/tests/test_entry_window_bootstrap_v1.py`、本 handoff。
  後續 shared integration 另獲唯一 writer 授權，僅追加下節列明的 CI manifest、selector tests 與 program asset row。
- 唯一研究契約：[mission](mission.md)、[data-contract](data-contract.md)。
  B1 公開 API：[entry_window_v1.py](../../research_core/entry_window_v1.py) 的
  `CountRow`、`SummaryKey`、`Summary`、`Comparison`、`COMPARISONS`、`METRICS`、`comparison_rates`。
  公開共享 oracle：[count_cube_v1.py](../../research_core/count_cube_v1.py) 的
  `bootstrap_weights`、`resampled_totals`、`percentile_interval`。
  不修改 B1、frozen helper、原 label、studycard 或 roadmap。

## 公開 API 與固定行為

`research_core.entry_window_bootstrap_v1` 提供：

```python
CountAxes(codes: tuple[str, ...], years: tuple[int, ...], era: str)
build_cell_cube(rows, *, axes, cell, cadence) -> CellCube
paired_weights(axes, *, method, reps=2000) -> PairedWeights
bootstrap_cell(cube, weights) -> tuple[IntervalRow, ...]
```

`CellCube.counts` 是 `[stock, year, arm, metric]` 的 exact int64 copy，預設不可寫；
arm 固定 `M, accepted, rejected, above, below`，metric 沿 B1 `METRICS`。
`cube.axes/cell/cadence/era` 保存完整身分，`cube.summaries` 提供 B1 `SummaryKey -> Summary`；
stock／known stock 均按 ID 聯集，不加總年度 distinct。沒有重抽 distinct 或套 sufficiency 門檻。

caller 須先選好同 cell、cadence、era 的 rows；M 的 band 必須為 None，四個價帶臂必須是
該 cell 的 band。每個固定 stock×year×arm 都須明列，包括零 counts；漏傳不是零。
拒絕 duplicate、外來維度／股票／年份、bool／float／NaN／負 counts、非守恆數字。
`known=hit+loss+flat`、`event=known+full_unknown+censored` 與 unknown/censored 重疊語義沿 B1；
各 metric 都驗 `M=A+R`、`R=above+below`，轉 int64 前先查範圍。

axes 必須非空、排序且唯一；年份必須在明傳 era 內，all 也從 2010 起。
未來正式母體應為 mission 固定 1,942 普通股與該 era 固定 calendar 年份，不能從有事件 rows
推母體。本包只使用 `FAKE_A` 等小型人工母體，沒有載入名單或正式 calendar。

`PairedWeights.stock` 是 `[rep, stock]`；`year` 僅 two_way 使用，為 `[rep, year]`。
每 rep 的 draw counts 非負且分別和為 n_stock／n_year，保存 axes、method、seed、reps、
generator、order、NumPy version。weights 是自有不可寫 copy；可手造合成 weights，但仍驗
固定 method seed、維度及 row sums。bootstrap 再核對 axes 身分，shape 相同也不能換股票／era。

固定 `Generator(PCG64(seed))`：stock seed `20261028`，two_way seed `20261029`。
先一次抽完 `[reps,n_stock]`，two_way 再從同 RNG 抽 `[reps,n_year]`，各自轉 multinomial 次數。
有序 stock draws 跨 era 相同；各 era 不宣稱互相獨立。相同 weights 共用於全部臂／六帶／兩口徑。
標準 2,000 reps；小 reps 只供合成驗證。沒有另設可調 seed 或研究參數。

先用 Python integers 加總，再驗 `max_stock_weight × max_year_weight × unweighted_total`
這個保守加權界限（逐臂逐 metric）不超過 `2**53-1`，才呼叫公開 `resampled_totals`。
stock-only 的 year multiplier 為 1。超界直接 OverflowError，不 silent round；
這個保守 guard 可能拒絕個別實際加權總數仍小於界限的輸入，屬明列 unsupported 範圍。
五臂一起攤平成 metric 軸，單次 public helper 共用權重，之後每 rep 呼叫 B1 `comparison_rates`。

十項統計量沿 B1 固定順序：quote_accept_rate、quote_reject_above_rate、quote_reject_below_rate、
all_hit_rate、all_loss_rate、accepted_hit_rate、accepted_loss_rate、accepted_hit_diff、
accepted_loss_diff、rejected_hit_share。差為 accepted 減同 M all；rejected_hit_share 分母是 M hit。
point estimate 由原整數 totals／stock unions 交 B1 計算，不平均逐股率。

`IntervalRow` 含 cell_id／primary、cadence／era／method、statistic／point_estimate、seed／reps、
lower／upper、valid_replicate_n／null_replicate_n，以及 generator／order／NumPy version。
95% 線性 percentile 沿公開 `percentile_interval`，僅有限 reps 進區間；零分母為 null，
全 null 兩端均 None，每項 valid+null=reps，`dataclasses.asdict` 可用 `allow_nan=False` 序列化。
內部暫存 NaN 僅表示未定 replicate，從不輸出成結果。兩種方法均保留，不選較窄者、排名、p 值或 verdict。

## 後續 orchestrator 的精確迴圈（本包不執行）

future caller 在 owner／data／compute gate 通過後才提供完整固定 `codes`、每 era 的
`years` 與所有明列 rows；不得把缺年／缺股補零。逐 cell，不建立全 36 格×全市場大型 cube：

```python
for era in entry_window_v1.ERAS:
    axes = CountAxes(codes=fixed_sorted_codes, years=fixed_year_axes[era], era=era)
    weights = {method: paired_weights(axes, method=method) for method in ("stock", "two_way")}
    for cell in entry_window_v1.COMPARISONS:  # 24 primary + 12 secondary
        for cadence in entry_window_v1.CADENCES:  # daily + cooled20
            rows = selected_complete_rows[(cell.cell_id, cadence, era)]
            cube = build_cell_cube(rows, axes=axes, cell=cell, cadence=cadence)
            for method in ("stock", "two_way"):
                intervals = bootstrap_cell(cube, weights[method])
                # Retain every row, including all-null intervals, plus axes metadata.
```

總矩陣為 36×2×4×2×10 項 interval rows。沒有研究比較格遺漏，空格保留。
若未來展示 sufficiency，引用**同 cell/era 的 cooled20** known_n／distinct 與兩臂分母，
不能用 daily 樣本替代，也不能由 CI 重抽 distinct 門檻。

## Shared integration (completed locally; final review pending)

Parent assigned task-16 sole shared-file ownership after S7 PR107 merged at
`32965822fcba8d107a072cf9596c8d2df6fb08fc`. That main was fetched and merged
without conflicts into the existing bootstrap branch, preserving S7's domain,
selector cases and asset row. No history was rewritten. The bootstrap core and
its original 57-test suite remain byte-identical to the independently reviewed
`ce18f604fdb55ac187a348e0d6436656b0c007d7`.

- `scripts/ci_test_domains.json`: existing `entry_window` paths now include this
  bootstrap module/handoff and the public `count_cube_v1.py` dependency. The
  bootstrap test is in both domain tests and `reviewed_tests`. All B1 paths,
  upstream consumers and fallback rules remain; B2b inputs are a later package.
- `scripts/tests/test_ci_scope.py`: the existing exact owned-path case now checks
  B1 and bootstrap module/test/handoff for both added and modified status. Each
  selects the two E1 tests; changed test files also select the selector test.
  Canonical dependency cases retain complete exact domain/test-set assertions,
  add `count_cube_v1.py`, and explicitly require the bootstrap test. Existing
  unknown-path full fallback and S7 cases remain unchanged.
- `docs/en/research-program.md`: adds `entry-window-bootstrap.v1`, linking the
  E1 data contract and this handoff, with the public CountAxes/builder/weights/
  bootstrap access path. It states pure/synthetic scope and pending real reader,
  runner, market and owner/data/compute admission.

Local verification covers the selector suite plus the unchanged bootstrap
suite, normal commit hooks and a read-only actual-diff selector plan. The final
report binds exact results, integration HEAD/base and saved logs. The actual diff
selects 23 test files across ci/entry_window/hooks/producer_link/prose with
full=false and frontend=false. Unknown-path full-suite fallback rules remain
unchanged. The read-only plan is recorded without executing unrelated tests locally. Publication is
explicitly authorized, but final Astra review and hosted validation remain
parent-coordinated gates. This package remains a draft and must not be merged
by its author.

## 合成驗證與待辦

聚焦命令：`uv run pytest scripts/tests/test_entry_window_bootstrap_v1.py -q`。
最終合成套件：**57 passed in 1.67s**。包括 public B1 censored bridge、literal PCG64 goldens、
year-weight malformed 與大整數聚合邊界。正常 commit hooks 及最終 HEAD 由本機完成報告綁定；
Shared selector／bootstrap 的整合驗證與 hooks 結果由最終報告綁定；hosted CI 待發布後核實。

驗收包括手算 stock／two_way counts／率／差、public helpers／B1 oracle、一份 weights 跨六帶、
A=M 配對差零、row-order 不變、固定 seed／先 stock 再 year literal golden、跨 era 股票 draws、
保留零事件 stock/year、混合／全 null、拒絕錯維度與不守恆、>int32／int64／exact float64 guards、
unknown/censored 重疊與 public B1 三種 censored 合成例、跨年 stock unions、完整矩陣，
以及兩 method 的 default 2,000 reps 可重現小格。沒有大 memory benchmark 或真實資料。

Shared integration 與發布已獲 parent／owner 明確授權。剩餘 gate：Astra 對最終 SHA 審查、
SHA-bound hosted CI／review、parent ready／merge；本包不 merge。
未來真實 reader、calendar／generation／label parity、owner/data/compute admission、單次研究成本、
執行與完整結果交付全部仍未解除。沒有市場資料讀取、labels／holdout／forward outcomes、
下載、generation hold/release、production root／部署／scheduler 變更。
