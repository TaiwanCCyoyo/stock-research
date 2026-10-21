# Pattern-scan v1 階段報告

**2026-10-21：研究已執行，尚未全部完成。** 主要成果入口是
[HTML 報告](web-report/index.html)，不是以下歷史準備紀錄。

- Q1：12 家族全部完成；首頁以同一個全體、無額外條件口徑，比較 C-base-daily 倍數、C-base-all 差距／K 與虧損率。
- Q2–Q6：B1、H1 已完成；B2 原程序計算中，其餘家族接續。不重跑已完成工作。
- 候選：沿用固定 top-10，重點是型態減去同條件排除型態的百分點差距，並列包含型態的 C-base-all 與各自 K。小樣本及已暴露 cross-check 不支持直接宣稱策略優勢。
- Q4：原型態及各候選逐列並列自己的同配額 random；其他控制、上下界、未知與時機留在附錄。
- 稽核：十事件及固定五個 B1 候選 40/40 cases 已完成。引用[既有完成確認](https://github.com/TaiwanCCyoyo/stock-research/pull/17#issuecomment-6316134172)，不再加新稽核、收據或分批檢查。
- 待完成：其餘家族終表、全家族判讀／final handoff，以及 iframe 實際下載人工驗收。全研究完成前不 release hold，不清理原始執行目錄／Q1。

Owner 指定 B2 後依 B4 → B3 → L1 → P1 → 其餘排序，不改定義、不略過家族。
交付程式的新呼叫預設已採用此順序；目前執行中的 worker 在啟動時就固定整個 targets tuple，
沒有熱切換入口，因此尚未套用到該程序。遵守不中斷／不重啟的指示，保留原程序；
任何需要停止它才能切換的處理留給 owner 決定，不自行注入或另開運算。

Claude 以剩餘約十家族、每家族約 16 小時估算約 6–7 日；這是工作量級估計，
不是承諾完成時間。不同家族耗時與既有 48 小時程序上限可能影響實際日程。

本次只整理既有終表的呈現。Q2–Q6 沿用原輸入、原選取與定義，沒有接入更新的共用 generation。
來源表、checkpoint、原收據與全部既有明細繼續保留，沒有資料刪除、共用區寫入或正式部署。
價格品質、公司行動、reference industry 非 PIT、多重候選與事件重疊等原限制仍適用。

<details>
<summary>歷史準備紀錄（截至 2026-10-13；不是目前研究狀態）</summary>

當時完成 handoff 盤點、mission 提案、原始來源覆蓋與 snapshot 準備，
以及 pure helper、獨立 cohort 與 event overlay。[逐項狀態](handoff-status.md)保留當時證據與限制。

已確認raw來源有2010-01-04..2026-10-12的6,653,745列／2,076代碼／4,110日期；
不是合格股票數或完整還原價認證。既有catalog七筆中，唯一2010起complete是0050背景；
本次全市場universe/prices/pivots/features/patterns/labels/episodes尚未發布。
期間不得縮成2019；之前任務固定2019並不證明搬遷造成資料範圍遺失。

## Q1–Q6：準備階段當時的待辦

| 問題 | 尚需產出                                                               |
| ---- | ---------------------------------------------------------------------- |
| Q1   | 12型態及subtype／union、H126/H252、全部樣本／未知／控制／年代／MKT總表 |
| Q2   | 全condition區間及每型態最多92候選全部確認表                            |
| Q3   | 同條件C-base／primary-control及不適用說明，不造型態專屬線的對照        |
| Q4   | H126hit起點episode、matches/misses/unknown、首出現時機及對照           |
| Q5   | hit/nonhit並列路徑、首flag、最大漲幅、同行／0050及頭頭低               |
| Q6   | nine flags的nonhit觸發率／hit代價／同return層與X6、tradeoff圖          |

純合成驗證已通過 **40 tests**：cooldown/episodes/path 31、selection 9。
測試使用invented價格和事件，不讀市場、沒有新型態detector的全數驗收，也不是收益結果。
新selection重用原public types／CRC，保留舊5/300/60/16-candidate版本；
新episode機制不改原25%-drawdown sector wave，二者不互相冒充。
新helper＋原selection API＋CI scope focused regression合計 **135 passed**；
正常formatter／mypy／pyright／hygiene hooks均通過。
正常hooks及hostedCI狀態以本PR實際head報告；[合成來源pins與重現收據](synthetic-evidence-v1.json.gz)固定本次已測raw source bytes，
不能用PR12的4852測試當新程式的current-head完整驗證。

本session沿用worktree research-data-entry，新branch codex/pattern-scan-mission；
原branch與初始化producer／舊物理seed輸入保留。本次新增5個約243MB物理input snapshots，
沒有copy/link formal shared versions、沒有改producer source、下載或排程。
[execution plan](execution-plan.md)列出mission合併後的detector、成本、封存、正式builder、
研究與audit順序。市場計算等owner mission merge。

已另外核實4110個raw日期鍵皆存在official來源，沒有nonofficial-only日期。
原始input pins及synthetic source pins分开，兩者都不宣稱全市場研究完成。

## PR14 P1：確認子型的獨立母體

初版mission的union保留集合反向篩subtype會刪掉後續確認訊號；此契約已修正。
新增build_pattern_cohorts從raw候選分別形成獨立subtype及union母體，沒有回寫已SHA固定的
舊events/selection source或v1 evidence。R2a(100)→R2e(101)、R1a(100)→R1b(108)、
R3a(100)→R3b(110)兩邊各自保留，union仍只有100；A(10,30)/B(0)案例證明union必須
從raw候選取得0,30，而不是由已冷卻subtype重建成只有0。

19個新cohort cases＋原直接依賴／CI focused regressions合計 **154 passed**。
這是接線／母體驗證，不是detector确认或市場樣本結果。新head hosted checks另讀，
舊f212296的95项draft contracts及full pending gate是歷史CI，不能當新cohort驗證。

[P1來源與合成收據 v2](cohort-evidence-v2.json.gz)固定新增cohort source/test及原v1依賴身份，
原synthetic-evidence-v1保持原bytes，不以新source重釘舊驗證。

## PR14 P2：同日型態品質的獨立投影

shared labels移除pattern-specific quality_overlay；base outcome仍以固定版本內stock/t0/horizon保存。
新增apply_event_overlay，以event_id/horizon保存detection/result品質、事件資格及有效label，
不修改base或同日其他型態。B1長回看含jump與L1短回看無jump共用base hit，
有效主分母分別0與1；不同horizon、子型、definition/input身分各自保存。
品質原因使事件unknown；資格排除保留原label並只移出主分母；截尾hit仍保留且不進主分母。
正式shared bundle與summary consumer契約同步；尚未建立真實overlay或完成detector接線。

42個新overlay cases通過；包含舊helper／selection／CI scope的focused regression合計
**196 passed**。[v3來源與合成收據](event-overlay-evidence-v3.json.gz)保存新增source/test、
shared dependency及原7份source／v1/v2 packet身份；舊bytes保持不變，不重新固定舊證據。

## Owner型態決定與ready準備

Owner 2026-10-13明確要求沿用handoff已列型態，H1=HHHL v4、L3=legacy F33，
不另加口述「低過低」。mission／status／索引與字典同步，型態問題已完成、不再重問。
其餘S1–S7補充以具體建議值、備選與影響交mission review；不把型態答覆當全部批准。
本PR準備可轉ready接正常CI／review，完整研究仍依合併後execution plan。
本次只改文件；既有196 focused結果及v1–v3 source pins保持原驗證身份，
正常完整hosted CI依最新ready HEAD另核實，不能把draft 95測試當full suite。

</details>
