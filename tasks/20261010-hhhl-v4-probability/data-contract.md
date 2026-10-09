# HHHL v4 來源驗算資料契約

> Current public-export availability (2026-10-09): source-data packages containing
> real quote vectors, anchor-close samples or corporate-action factors are retained
> locally, not distributed in the public repository. Historical receipts and fixed
> hashes retain their original identity. The 0050 context cannot be activated without
> its complete original input package; readers fail closed and do not download or
> recompute missing data. See [the bootstrap availability record](../../docs/en/bootstrap-stock-research.md#public-export-availability).

準備資產 ID：`hhhl-v4-source-preparation.v1`，原來源驗算階段紀錄保留。
後續機率資產 `hhhl-probability.v4` 已完成，入口為下方追加契約與 [report](report.md)；
機率定義待確認的歷史狀態已解除，仍不是獨立確認、帳戶績效或策略通過。v1 舊結果不覆寫。

## 生產者、消費者與固定入口

- 生產者：`scripts/validate_hhhl_v4_source.py`；adapter 為 `research_core/hhhl_v4_source.py`，
  載入入口 `load_rule(sources, "hhhl_rule_v4")`，沒有匯入 `.tmp` 或讀取隱含價格資料庫。
- 消費者：主代理／Claude 驗算與後續 v4 機率 producer；網站可查來源狀態，
  **不能把此資產畫成成功率或帳戶報酬**，因為尚無此類數值。
- 原例／原始碼：[sources/hhhl_rule_v4.zip](sources/hhhl_rule_v4.zip) 的四個 exact members。
  [handoff-v4.zip](sources/handoff-v4.zip) 保存原交接、前次定義及四題提問的原 bytes。
- 可攜驗算證據：[preparation-v1/bundle.zip](preparation-v1/bundle.zip)，內含
  `corporate_action_factors.parquet`、`validation-cases.json`、`input-receipt.json`、`report.json`。
  沒有 forward labels、全市場機率表或完整價格歷史。

preparation bundle SHA-256：4908ef8588bd34483d7862d4052f4d236641090188eaaece5d316e12a15db549，
314,178 bytes。解開前先核對包身分；解開後由 receipt 與 validator 核對實際輸入。

primary 固定輸入位於
`D:/Project/Stock/tasks/20261010-hhhl-v4-probability/datasets/hhhl-v4-validation-inputs-01/`；
完整驗算報告位於
`D:/Project/Stock/tasks/20261010-hhhl-v4-probability/datasets/hhhl-v4-validation-01/report.json`。
大輸入不只存在 worktree 或 `.tmp`；Git 包提供異地取得本次固定因子的路徑。
本機與 worktree 同碟副本不是完整備份，不保證 canonical atlas 在其他機器已存在。

## 欄位與時間語意

`corporate_action_factors.parquet` 為 SQLite mode=ro 單一一致性 SELECT，32,848 列，
四欄：code（來源代碼）、ex_date（來源除權息日）、event_type（來源事件名）、
price_factor（參考價／前收等來源因子，未補缺值）。查詢含全資料庫，原 adjprice 的
正因子／非空日期／截至 2026-08-14 篩選仍適用；未使用的未來或無效列不能算本批輸入報價。
表內缺值仍是缺值，不改成零。該 SELECT 可一致性讀取有 WAL 的資料庫；不把主 DB
檔案 hash 當作涵蓋 WAL 的固定身分、不對 live DB 做檔案複製。

固定因子表 SHA-256：427b81a70d3548a0595a80c547544cf4da8824ddcbda2dbb366032e68ba5df7a。
cases SHA-256：8e2c2937c38fe276a00246b23b497b8f7f8a93b20ff9dca2be7a463453ec7abb。
receipt 逐檔指定路徑與 hash；重驗入口先檢查、不覆寫舊輸入或報告。
機率producer另以程式內的固定SHA綁定這兩個檔案與原input-receipt.json
（d4942a053b2df2328da5ef83d8854e1079ddd5c50507e48961e4488ec888e550），在parent
前置驗證與worker載入均讀前／讀後核對。這三個身分由上方原preparation包取得；
更換`--inputs`目錄只可搬移同一份bytes，不能另造自洽receipt替换因子並冒充本實驗。

`validation-cases.json` 每列 id/code/date/kind；24 個 kind=rule 與一個 old_pressure。
rule 要求同日真 pattern、bonus 空；old_pressure 要求 2527／2023-04-07、small_range、
old 線與 20.48 差不超過 0.05（驗算的四捨五入容差，不是策略參數）。

`report.json`：passed/checks、dataset_id、source_hashes、cases、consumed_tables、factor_input。
cases 保留 found/pattern/scale/bonus_levels/restart/leg_start；後兩欄是去缺 OHLC 後的偵測器索引，
不是完整日曆索引。每檔 preparation 記錄原列、缺 OHLC 列與適用因子數。
因子日期、重複鍵、非有限值有明示檢查；觀察到衝突則停止，不私改原公式。

## 價格基礎與母體限制

僅消費原 atlas 的 asof_date、RawOHLC、VolumeLots、atr14_pct 欄位；不讀 labels。
`RawOHLC × 後續 price_factor 乘積` 與原 Wilder ATR／dropna 保持一致，
這是參考價因子還原價格，不是精確的現金含息投資報酬。原 atlas Close 是另一價格基礎，
後續比較須保留兩套欄位與分母，不更正覆寫原 label。

原 atlas-v2 ID 為
`fda-86245f2e223fc45c9f84afb0dcf77c1fff7ab22d0a1b0b4a4c8800972ce9327e`，
2019-01-02..2026-08-14、目前參考股票池、已暴露期間，沿用其
[資料契約](../20261004-feature-discrimination-atlas/data-contract.md) 的倖存者與 PIT 限制。
驗算只消費 25 檔，不是只研究這 25 檔，也不是全 1,941 檔機率已算完。
尚缺的四個機率口徑見 [report](report.md)；不得自行選有利算法開算。

## 重驗路線

於新資料夾解開 `preparation-v1/bundle.zip`，即得到固定 `--inputs`。
取得上述 canonical atlas 或依其原可攜發布契約恢復資料；缺完整行情時可讀報告，不能宣稱重驗。
從 task branch 使用正常專案 Python 環境：

```powershell
uv run --group dev python -m scripts.validate_hhhl_v4_source `
  --dataset D:/Project/Stock/tasks/20261004-feature-discrimination-atlas/datasets/atlas-v2 `
  --sources tasks/20261010-hhhl-v4-probability/sources `
  --inputs D:/Project/Stock/tasks/20261010-hhhl-v4-probability/datasets/hhhl-v4-validation-inputs-01 `
  --report .tmp/hhhl-v4-validation-new/report.json
```

重驗是來源一致性，不核准另一個機率 run、下載、確認／holdout、排程或帳戶模擬。

## v4 機率契約追加：四題已回覆，結果前封存

機率資產 ID `hhhl-probability.v4`，來源準備包不改名或覆寫。完整定義維護在
[mission](mission.md)，原回覆 bytes 為 `sources/definition-response.zip`。
Claude 定義仍屬開發期暫定，非擁有者最終門檻。
producer `scripts/build_hhhl_v4_probability.py`，量測／彙總為 `research_core/hhhl_v4_outcomes.py`
及 `research_core/hhhl_v4_summary.py`，舊 v1 程式不改。

固定 run 位置 `D:/Project/Stock/tasks/20261010-hhhl-v4-probability/datasets/hhhl-v4-descriptive-01`。
不能覆寫既存目錄，輸入沿用上列固定因子與原 atlas-v2。`attempt.json` 為未完成啟動收據，
只有 `manifest.json` complete=true 且所有 artifact hash 可重驗才是完成；attempt 本身不會
靜默改為完成。manifest 記錄真正執行時刻、code_commit、前後完整輸入身分與局限。

| 表／檔案                         | 主鍵與用途                                                                                                                                    |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| events.parquet                   | event_id=rule:security_id:t0；所有原事件含 false／ineligible；原日資格、cat、scale、limit_up、bonus／blocking／seq JSON、完整日曆與有效列索引 |
| baseline/NNNN.parquet            | security_id/asof_date；全部原日曆（含不合格／缺價），按 manifest 股票 ID 順序分檔；保留 adjusted_close／atlas_close、兩套 outcome             |
| controls.parquet                 | security_id/asof_date；同日無真 pattern，control_no_event 旗標選主控制；資格不因事件排除而修改                                                |
| noise.parquet                    | event_id 連原合格 E 事件；anchor_date 為種子選定日、breakout_date 原日、calendar_offset；無可選日不丟樣本                                     |
| landmarks.parquet                | event_id/landmark，三個 L；status、reason、group、rise_bin、第一次越線索引／日期、固定 Z2／target／deadline、完整剩餘段 outcome               |
| summaries.json                   | 固定 1,080 格；family/slice/value/sampling/horizon/basis，地標另加 landmark；全部空組、未知上下界、known 與 known_securities 保留             |
| coverage.json／diagnostics.json  | 全部股票的缺價／loader 丟列／因子計數；地標狀態與兩 label 不一致數；非可交易帳戶驗證                                                          |
| label-discordance-63/126.parquet | 原事件兩套 label 不一致逐筆資料；原因是價格基礎與首次決定／完整期限語意差異，不當作 atlas 錯誤                                                |
| audit-sample.parquet             | 按 security_id、t0 的前十筆合格真事件；不是挑十筆成功案例                                                                                     |

`adjusted_*` 為參考價因子還原＋首次決定口徑；`atlas_*` 原值原語意。label 為 1／0／null，
complete 不等同 label 已知；路徑比率無單位、等待為共用日曆交易觀察數。
地標的 unprefixed 126 outcome 仍是原 t0 目標／期限，min/max 相對原 t0，mdd 由 L 起。
不能與原日起算的完整 126 日最大回落互換，亦不能當停損／帳戶回撤。地標對照僅同 L、
同固定漲幅區的未越線／無線組；不把原 t0 全期間基準率標成地標的相同風險集合。

只需讀取 Git 可攜結果的使用者，從 `publication-v2` 的 metadata ZIP 與三個分片讀所有摘要及原完成
manifest／診斷／抽查／覆蓋，不需要原行情 submodule。大型 parquet 僅在上述 primary
位置，Git clone 不含，尚無異地備份證據。重算需原 atlas bulk，不能用最新價格快取替代。
資料仍為已暴露 current-reference 母體，非 PIT 完整上市櫃、獨立確認、因果加分或帳戶績效。

## 完成可攜交付與查詢

`publication-v2/publication.zip` 只含 `publication.json`，schema `hhhl-v4-probability-publication.v1`，指定原 bundle 的
sha256／bytes、26 members、每 member 原路徑與 hash、source_code_commit、1,080 cells。
bulk_location_availability=local_only，bulk_location_verified=false：離線 reader 只驗包，
不冒充連到本機 470 MB 原大表。publisher 在製包時確實驗過原 1,952 artifacts。
原 manifest、mission／contract／code 的執行時 bytes 全保留，並非後改的這份契約。
`transport_schema=hhhl-v4-probability-transport.v2` 與 `bundle_parts` 指定三個有序分片的
path／sha256／bytes；分片依序合併即為原 1,002,805-byte ZIP，不改任何研究數字。
每片至多 400,000 bytes；metadata ZIP 為 2,410 bytes。原本機 publication-v1 原封不動保留，
Git 交付僅採 v2 分片以符合單檔限制。reader 在記憶體驗證與讀取，不必手動解壓／拼檔。

```python
from pathlib import Path
from scripts.publish_hhhl_v4_probability import verify_publication
saved = verify_publication(Path("tasks/20261010-hhhl-v4-probability/publication-v2"))
rows = saved["summaries"]
selected = [r for r in rows if r.get("landmark") == 20 and r["slice"] == "rise_bin"]
```

CLI 同模組 `--publication <directory> --family E-clean --horizon 126 --basis adjusted_reference_factor`
亦會先驗包。所有 rate／min_return／drawdown 為 **fraction**，UI 轉百分比時乘 100。
不得把 9.68% 翻倍率展示為帳戶報酬；unknown_lower/upper 不是信賴區間。
來源路徑允許 Windows 相對／絕對鍵，但包只用固定安全 member 名稱、不解壓執行原文。
會拒絕 hash／大小不符、缺成員、重複成員、路徑穿越、重複比較鍵及覆寫既存發布。
publication reader 另在解壓前核對descriptor與ZIP header：單成員展開上限32 MB、
全包展開上限64 MB，壓縮bundle仍最多10 MB；不能用低報descriptor避過header上限。
v1原始publication.json與v2 metadata的讀取上限均為100000 bytes；v1先查檔案大小，
再最多讀上限加一byte，拒絕檢查後增大的檔案，不無界載入metadata。
這是輸入資源限制，不改既有產物、統計或策略驗收門檻。

## 地標原因更正補件

歷史 `diagnostics-supplement-v1.zip` 是 additive 更正，不覆寫原 v2 包或完成 manifest。
內含 `manifest.json`（`hhhl-v4-diagnostics-supplement.v1`）與 `reason-census.json`。
後者每列含 `landmark`、`eligibility`（eligible/ineligible）、`status`、`reason`、
`rows`、`securities`；空原因標 `(missing)`，缺價格 `missing_before_landmark` 與
資料窗不足 `window_end` 分開。不是新增型態比較，也不能把 distinct securities 跨格相加。

補件 manifest 綁定原 run manifest／bundle／landmarks 的 hash、bytes，以及原 producer、
共用 census helper 與補件 script 的 code hash；只列 reason-census artifact，不列自己。
writer 讀既有 landmarks 的五欄，逐格核對原 24 格總數與每格 distinct securities；
讀取至封裝前後來源身分相同才成功，既存 output 拒絕覆寫。

最新改用 `diagnostics-supplement-v2.zip`（`hhhl-v4-diagnostics-supplement.v2`），
57686 bytes、解壓119096 bytes，SHA-256 2393f3658848d8792020006e20f243ff6e46789c007979f8dcbe5b7f225f151b。
除了原30格分桶，保存162864列上述五欄投影，以及census helper／補件script兩份
程式快照。reader 先驗各成員與程式身分，再重算每個完整reason格及distinct securities，
並核對舊24格事件／股票數；不執行嵌入程式。原v1 bytes與結果不變，但缺投影的v1
不能作充分驗證，最新reader明確拒收。原producer/helper身分與新補件程式身分分開。
helper整份檔案曾因noise首筆修正而改hash，但地標census公式未改，沒有追溯修改原run。
投影的來源hash提供身分與可重算性，不是惡意偽造認證；獨立核對投影確實來自原表，
仍需取得原hash-verified landmarks.parquet，而非只信補件自報hash。

```python
from pathlib import Path
from scripts.supplement_hhhl_v4_diagnostics import verify_supplement
task = Path("tasks/20261010-hhhl-v4-probability")
supplement = verify_supplement(task / "diagnostics-supplement-v2.zip", task / "publication-v2")
reason_rows = supplement["census"]
```

reader 只需 Git 補件與原 v2 包，不需要 470 MB 大表；核對原 source identities、補件 hash／
大小、投影及重算的30格各完整reason／不同股票數，不把保存收據當獨立樣本驗證。
最新正式本機位置為 `D:/Project/Stock/tasks/20261010-hhhl-v4-probability/diagnostics-supplement-v2.zip`，
Git 保存一份相同 bytes；原大表的本機／備份限制不因補件而解除。

## 雜訊首筆量測更正

原包仍是原始完成收據，但四個 `family=noise, sampling=first_per_security` 格已被更正：
原程式錯按平移後 anchor_date 選首筆，應依原 breakout_date 選每股最早合格事件，再
評估其已保存的平移結果。未知首筆不以後來已知事件取代；seed／平移日期不重抽。

歷史補件 `noise-first-correction-v1.zip`（`hhhl-v4-noise-first-correction.v1`）保存
manifest.json 與四格 cells.json，2074 bytes；primary 與 Git 副本相同。
receipt 綁定原 run manifest／bundle／四格、noise.parquet hash／bytes／51731 rows、
更正程式身分與1864個已選 event_id 的 digest。只讀原已保存 labels，不偵測或下載行情。
原來源與封裝未覆寫；其餘1076格（含 noise all_events）逐格相同。

最新消費改用 `noise-first-correction-v2/` 完整目錄，內部仍為
`noise-first-correction-v2.zip`（`hhhl-v4-noise-first-correction.v2`）的原 bytes：
713815 bytes，SHA-256 `c91f27a43a2ef98ebc87bc41a7d94e8b8ed1eaa820eb882299ee5464b7615a94`，
解壓成員合計973133 bytes；最大允許4 MB封包／32 MB成員。primary ZIP 與 Git
分片組回 bytes 相同，不覆寫原713815-byte ZIP。
為遵守正常500 KB單檔門檻，Git保存 correction-transport.zip（420 bytes）、correction.001.bin
（400000 bytes）、correction.002.bin（313815 bytes）；三檔都必須取得。reader 有界
核對每片及整體 hash 後組回原補件，再做以下驗證，不單獨把 metadata 當結果。
metadata ZIP 只含 publication.json；使用既有有界、單成員 ZIP reader，公開 hash
不需要擴大秘密偵測 allowlist。primary 未發布的 plain metadata 仍留存、不覆寫。
保留同一四格數字，追加已選 1864 個事件的保存 outcome 欄位、51731 列來源選取索引
及三份更正程式快照。reader 核對每個成員 bytes／hash、程式身分與已選 event_id
digest，依原 breakout_date 重驗首筆，再從保存欄位重算四格的全部統計，包括未知
原因、等待及價格路徑分位數；不執行封包內的程式、不讀價格或重新抽樣。
原 v1 缺這些重算材料，保留歷史但最新 reader 拒絕將其當作充分驗證。

來源 hash 仍綁原 noise.parquet 與原 manifest。這是可重算及 byte provenance，
不是對惡意偽造的密碼學認證；部分欄位的索引不能逆推或驗證整份原 Parquet bytes。
若要獨立核對索引／outcome 確實來自該來源，須取得明列的 hash-verified 原 noise 表。
不以補件內自己宣告的 hash 代替外部可信版本、原表或原始證據。

```python
from pathlib import Path
from scripts.publish_hhhl_v4_probability import verify_publication
from scripts.correct_hhhl_v4_noise_first import read_correction
task = Path("tasks/20261010-hhhl-v4-probability")
publication = task / "publication-v2"
original = verify_publication(publication)  # 原始包，不自動宣稱是最新更正觀點
current = read_correction(task / "noise-first-correction-v2", original, publication)
rows = current["summaries"]  # 全1080格，僅替換四個指定格
old_rows = current["original_summaries"]  # 稽核用，不是最新數字
correction_receipt = current["metadata"]
```

CLI 加 `--noise-first-correction tasks/20261010-hhhl-v4-probability/noise-first-correction-v2`。
對這次原 run，查 noise 首筆或未限定的全格卻不帶補件，CLI 明確失敗，不默默交付舊格。
僅查 E-clean／地標等未受影響格可不帶補件。Python 原包 reader 保留歷史原值；需要
全部目前可用格的網站／研究端必須採上方 overlay reader。補件可只靠 Git 原包驗讀，
不依賴本機 noise 大表；hash／分母／原來源不符或多改其他格則拒絕。

更正 writer：`scripts.correct_hhhl_v4_noise_first --run <原run> --publication <原v2> --output <新zip>`。
已有 output 拒絕覆寫；重算需先取得明列的原 noise 表，並依研究更正／執行授權規則進行。
`write_correction_transport(packet, new_directory)` 只將既有 ZIP 無損分片；已有目錄拒絕
覆寫。這個 transport 不重新計算統計；primary 原 ZIP 仍可由相同 reader 核驗。
這不是新候選或獨立驗證；原邊界、倖存者與價格基礎限制不因更正解除。

## 修正後 runner 的完成界線

新 public runner 以自有子程序執行並受同一 3600 秒 deadline 監督。child 的
manifest.pending.json 是待父層確認的內部產物，不是可接受的完成紀錄；成功 exit
與剩餘時間檢查後才發布原 schema 的 manifest.json。逾時／失敗的 output 保留，
不得被 catalog 或網站當作成功結果。Windows 子程序樹清理有有限收尾等待；若不能
確認清理完成，明示失敗，不修改其他 session／排程／共用資料。這只改未來執行路徑，
原完成 run 的 522.563 秒、封存 code_commit／inputs、收據及研究數字維持原樣。

未來 public runner 在 child 啟動前，先原子發布最小 attempt.json 及不可變
attempt-start.json；preflight 未通過時 code_commit／identity 為 null，並標
identity_complete=false。核驗與 Git seal 通過後才原子補入 attempt 身分，原 start
snapshot 仍保存並列入新 manifest 的 artifact inventory。兩份 attempt 均維持
complete=false；成功與否依正式 manifest 界線，不把前置失敗誤記成沒有啟動。
原已完成 run 沒有這個新增起始 snapshot，不追溯補造或改寫其歷史收據。

## PR #33 追加的驗讀與執行邊界 — 2026-10-08

摘要的固定 1,080 格不只核對列數與重複鍵：publisher 與 reader 均須核對完整
family/slice/value/sampling/horizon/basis/landmark 的事前固定鍵集合及型別。
缺格、額外方法、錯誤年度／期限或以另一個唯一鍵替換一格，都不能作為本次結果。
這不新增比較，不改既有統計；原 publication 與 noise overlay 已通過新檢查。

每格另按既有 describe 定義核對必要統計 payload：非負整數分母／命中／未知／證券數、
rows=eligible+ineligible、eligible=known+unknown、known=hits+nonhits、比例與未知上下界、
unknown_reasons 加總、命中／非命中分位數的母體計數、small_sample 與 lift 公式。
未知原因只接受原 producer 的非空正計數桶：adjusted 一般格為 invalid_anchor／
missing_before_hit／window_end，atlas 一般格為 missing_or_invalid_path／window_end；
noise 各自另允許 no_shift_candidate，active 地標格只允許 missing_before_hit／window_end。
缺原因的 (missing)、拼錯、自創或跨基礎／族群的原因拒收，不從現有資料反推放寬集合。
有限數值或 null 不接受字串、bool、NaN／Inf；零分母的比例必須是 null。六個分位數
依本次固定 outcome 公式均須完整：hit-wait 的 known=hits，nonhit 路徑的 known=nonhits，
unknown 都為0；只有空母體的 value 是 null，非空母體必為有限值。共用 quantile 函式
雖可能把非有限計算值轉 null，此研究的已知命中／非命中卻不能據此接受缺漏證據。
等待從原 t0 算起，一般格為1..horizon、地標格為L+1..126；分位數因插值可非整數，
但必須 p10<=median<=p90，非命中最低報酬的 p10<=median。原正價格公式的非命中
最低報酬分位數不得低於-1，最大回落中位數須在[0,1]，保留浮點捨入的極限端點。
已知非命中的最低報酬也必須小於原命中門檻減1（H63為0.5、H126為1），沿用原標籤公式。
這是欄位完整性與
算術自洽檢查，不是從摘要還原全部來源個案、核准策略或證明摘要未被惡意同步改造。
同一份完整 grid 也會核對每格的基準率引用：年度格用同年度，其餘原事件格用 pooled
的相同期限／價格基礎 all_stock_days 與 high_volume_no_event；地標格依原定義沒有
這兩個 t0 基準率或 lift。跨格核对仍不是獨立來源重算或獨立確認。

可攜補件的 Parquet 在讀資料頁前，先核對 PAR1 framing、footer 至多 1,000,000 bytes、
Thrift 字串／容器配置限制、精確列數及扁平欄位集合；至多 250,000 列、64 個 row groups，
宣告的展開頁大小合計至多 32,000,000 bytes。拒絕巢狀／extension 欄位，不執行封包
內程式，資料頁單執行緒解碼後仍照原規則驗型別、來源及重算統計。這是 metadata
preflight，不是 OS 層 CPU／記憶體硬隔離，也不是任意外部內容的真實性認證。

Windows 的未來 runner 改用自有 Job Object：bootstrap 必須先用保留的原程序 handle
成功加入 job，才經啟動閘門執行工作。leader 正常退出、非零退出、native crash 或逾時
後均清理 job，並在有限收尾等待內確認 ActiveProcesses=0；無法確認即明示失敗。
不向已退出或可能重用的 PID 清理程序樹，不終止其他 session。Windows-only pywin32
改為直接宣告依賴，沿用原鎖定版本，未升降其他套件。單一 3600 秒運算 deadline 與
有界收尾等待仍分開，不能宣稱任何 OS 阻塞都在整點結束。

## 已保存地標的座標更正觀點

原 run 的 scanner 曾把超出可觀察日曆的計畫 t0+L 索引覆蓋掉量測 helper 的 null。
未來 producer 保留 helper 的實際 landmark_index，沒有觀察到 L 時，索引／日期都為 null。
原已完成 landmarks.parquet 不覆寫；消費原表座標時須明確啟用
`hhhl-v4-observed-landmark-coordinates.v1` 更正觀點，不能把原計畫索引稱為觀察日。

```python
import pandas as pd
from research_core.hhhl_v4_landmark_view import observed_landmark_coordinates

raw = pd.read_parquet(original_hash_verified_landmark_path)
view = observed_landmark_coordinates(raw)
coordinate_receipt = view.attrs  # 觀點版本與此次 nullified 列數
```

這個函式複製輸入，不改原表；只將 landmark_date 缺值的 landmark_index 設為 nullable
Int64 的 null，所有 status／reason／outcome 不動。本次原表 162,864 列，其中 1,532 列
需 nullify；原 SHA-256 d57bb1e0925d1eea096205a992903e66ff4383978005ce5e6dbd6de158bd5957
在讀取前後一致。此觀點不是替換原完成收據或完整的新資料表；Git clone 仍須另取得
原 hash-verified 大表才能查座標。摘要與兩個更正補件的研究數字不受影響。

## 同十筆原事件的 L20 抽查補件

原 publication 的 audit-sample.parquet 只含 t0 事件。新 `landmark-audit-v1.zip`
（schema `hhhl-v4-l20-audit-supplement.v1`）補交同十個 event_id 的全部 L20 原欄位與
joined audit，不取代原包或增加樣本。future builder 在相同前十筆排序後直接保存
`l20_` 欄位；這份 additive reader 只針對原完成包的舊 ten-case schema。

`audit` 保留原 t0 價格／Z2／bonus JSON 等全部欄位；`l20_` 前綴包含實際地標日／索引、
status／reason、越舊線／近期遠線的旗標與首次索引／日期、group、rise_ratio／rise_bin、
固定原目標／deadline、剩餘段 label／unknown／complete、等待與路徑欄位。
`l20_wait_to_threshold_126` 仍由原 t0 起算，`l20_wait_from_landmark` 才由 L20 起算；
目標與126日期限不重新開始。只有 active 有剩餘段；其他status的 null不是非命中0。
`landmark_rows` 保留原表投影，joined audit明確套座標view；未觀察到地標日的index
才改null，不能把計畫日當實際日。JSON nullable scalar／ISO timestamp保持可辨識。

```python
from pathlib import Path
from scripts.supplement_hhhl_v4_audit import verify_supplement

task = Path("tasks/20261010-hhhl-v4-probability")
saved = verify_supplement(task / "landmark-audit-v1.zip", task / "publication-v2")
audit = saved["audit"]  # 10 rows; original fields plus l20_ fields
receipt = saved["metadata"]
```

reader只需Git ZIP與原v2四個檔案。ZIP只含publication.json，原JSON55680 bytes與hash
不變；primary原JSON仍保留。使用既有單成員reader，ZIP壓縮及展開均上限100000 bytes，
不解壓至磁碟、不執行內容。核對原manifest／bundle及audit／landmarks完整表
hash／bytes、原事件逐值及one-to-one join；不解壓執行程式、不讀行情。JSON上限
500000 bytes，原audit Parquet沿用footer／row／page限制，asof_date單獨允許無時區
timestamp[ns]，其他timestamp或extension拒收。原十筆恰好同一檔股票，按原排序保留，
不是代表性抽樣或成功案例集合；不能拿十筆估全市場率。補件可重算連接不是來源
真實性的密碼學認證；要獨立確認L20投影確實來自原表，仍需取得契約所列原大表。
writer只讀原來源，讀取前後核對hash，既有output拒覆寫。生成與大小hash收據見execution。

交付ZIP6861 bytes，SHA-256 26c7eff6196b706db5fba0f62b077093b51af8cbd3849e0293d6949f58e41617；
內部原JSON55680 bytes，SHA-256 f1ab85e00c4b36f372e2bd848579b5eb928833a7030f098dfcdb64fcb5e42f3d。
primary同名ZIP／原JSON在D:/Project/Stock/tasks/20261010-hhhl-v4-probability/，不只留在worktree。
writer的`--pack <原json> --publication <原v2> --output <新zip>`只無損包裝，不重新生成資料；
JSON公開hash的secret誤判未以放寬scanner／baseline處理，格式後未發布的本機JSON不當原副本。
