# small-probe 歷史追溯

2026-10-24，資料整理 A 補記。Owner 決定保留 `kind: study`，只作來源缺失的歷史紀錄，
不列為有效研究成果，也不是必須重建的待辦。卡片維持 `not_evaluated`、沒有結論數字，
API 保留 `source_unavailable`。本文件是新補的追溯說明，不是找回的原研究報告，
因此不填入卡片的 `report` 或 `answer_source`。

## 仍被引用的程式

| 檔案                                 | 可由現存程式確認的用途                                                                                                                                     |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [declined_6438.py](declined_6438.py) | 把指定的 6438 現金增資來源列與事件資料綁定為 `BoundOffer`；`build_declining_provider` 記錄模型中放棄付費認購的決策，保留原帳務事件，不把認股權價值當成零。 |
| [declined_2641.py](declined_2641.py) | 綁定指定的 2641 現金增資來源列，並沿用前一支程式的型別、事件限制與拒絕認購提供者。                                                                         |

這些用途只描述支援程式，不足以還原原研究的股票範圍、題目、參數或結果。
兩支程式原樣保留；本次沒有執行它們或讀取其指向的 producer 輸入。

## 引用任務與間接分類證據

| 任務／檔案                                                                                               | 可確認的引用關係                                                                                                                                                 |
| -------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [one-lot-delay-resumption / declined_3680.py](../20261002-one-lot-delay-resumption/declined_3680.py)     | 從本目錄載入 `declined_6438`，核對模組路徑，重用 `BoundOffer` 與 `event_limits`。                                                                                |
| [one-lot-delay-resumption / declined_6443.py](../20261002-one-lot-delay-resumption/declined_6443.py)     | 把本目錄加入來源路徑，並透過 `declined_3680` 使用上述型別與限制，是間接依賴。                                                                                    |
| [relative-strength-holding / source_modules.py](../20261005-relative-strength-holding/source_modules.py) | `RESTORED_SOURCES` 明列本目錄兩支程式。這是靜態來源清單，不是本次執行或研究通過的證明。                                                                          |
| [pool-breadth-admission / execution-v1.md](../20261002-pool-breadth-admission/execution-v1.md)           | 「Every prospective criterion and verdict」第 3 點提及 earlier small-probe card's insufficient verdict。這是它曾有研究卡片的間接證據，不能代替原卡或重建其判定。 |

## Commit 與未知範圍

本次唯讀核對基準為本 repo commit
`5d916551252b26e8640b287fd66d48a04a04af87`。
上述程式與引用文件在本 repo 最近一筆內容提交均為
`493fa49d738e00e5c59bd118192669c86065adf4`
（PR #6，目錄／名稱整理）；**這不是已確認的原研究 PR**。

目前仍未知：原始研究 PR、正式研究題目、研究參數，以及原研究報告與判定依據。
程式內已知的現金增資事件常數不等於研究參數；目錄名稱及其他任務的轉述也不構成原結論。
現有可讀範圍未找到原任務的 mission、report、research_result 或 presentation，
舊 studio 包的 53 筆 `researchHistory` 亦無同 ID 記錄。

本次只讀本 repo 的現有程式、文件及 Git 記錄；不讀寫前身 repo，
不重算、不補造結論、不刪程式，也不修改原報告、打包檔或固定證據。
