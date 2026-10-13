# Pattern-scan v1 準備報告

**研究尚未執行；本次完成handoff盤點、mission提案、原始來源覆蓋與snapshot準備，
以及兩個pure helper版本。** [逐項狀態](handoff-status.md)保留每項證據與未完成限制。

已確認raw來源有2010-01-04..2026-10-12的6,653,745列／2,076代碼／4,110日期；
不是合格股票數或完整還原價認證。既有catalog七筆中，唯一2010起complete是0050背景；
本次全市場universe/prices/pivots/features/patterns/labels/episodes尚未發布。
期間不得縮成2019；之前任務固定2019並不證明搬遷造成資料範圍遺失。

## Q1–Q6：目前沒有研究結論

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
研究與audit順序。owner圖形／補充提案未定前不開始市場計算。

已另外核實4110個raw日期鍵皆存在official來源，沒有nonofficial-only日期。
原始input pins及synthetic source pins分开，兩者都不宣稱全市場研究完成。
