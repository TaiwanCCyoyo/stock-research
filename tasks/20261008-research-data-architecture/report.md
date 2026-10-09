# Stock 研究資料架構：第一階段交付

執行日 2026-10-08，先從最新 `origin/main` f0cb177 建立獨立分支。這是架構／相容性驗算，不是策略研究；沒有在 main 提交、下载、機率重跑或開啟密封期間。

## 結論與邊界

Stock 已有型態字典、三種價格基礎、共用衍生計算、不可變快取及備份還原。下載／正規化／原始證據仍在 producer。原 HHHL v1～v4 bytes 保存，原 v4 24＋1 全重現；新缺口政策下 23／25 保留，不能默默取代舊结果。

Claude 的完整標註匯出／batch2～5 重算仍未接收，第 1 項未關閉，因此**不是整个 1→7 計畫全部驗收**。本 PR 先交付不依賴線上匯出的 Stock 元件，不代替全部正反標註。producer SMA／EMA 刪欄、technical_features 搬移與工作區清理另階段處理，本次不刪。

固定入口：[資料契約](data-contract.md)、[型態字典](../../docs/en/pattern-definitions.md)、[衍生資料](../../docs/en/research-derived-data.md)、[備份程序](../../docs/en/price-cache-backup.md#stock-research-data-backup)。

## 可攜證據及大型資料

[publication-v1/bundle.zip](publication-v1/bundle.zip)：243,419 bytes，SHA256：

7ddceebe615317ba854eede92eb0480357895af358a778b99a1e8ead58212477

| ZIP 內位置                                            | 內容                                                                 |
| ----------------------------------------------------- | -------------------------------------------------------------------- |
| `cache/manifest.json`                                 | 完整版本身分、75 組覆蓋、輸入／公式／產物 hashes                     |
| `inputs/input-receipt.json`                           | 25 原表的來源與 hashes，只讀 raw 六欄，沒有 forward outcome          |
| `validation/compatibility.json`                       | 全部原例、逐股品質日與 121 個事件差異                                |
| `validation/direct-parity.json`                       | 75 組所有欄、dtype、順序、NaN 與精確值的重算比對                     |
| `backup/snapshot.json`、`backup/restore-receipt.json` | 4,103 檔 inventory 與實際還原收據                                    |
| `execution-source/`、`cache-implementation/`          | 驗算／建置實際程式原 bytes，對應收據 hashes；不受後續 formatter 改變 |

Parquet／backup objects 不在 Git；新 clone 必須取得物件或還原，不能只看到 manifest 就宣稱資料已取得。

```text
D:/Project/Stock/research_cache/input-snapshots/architecture-v1-25-cases/
D:/Project/Stock/research_cache/price-bases/71928e94ce30c6bd1ceb7eee2d3a7a9955cea7d72a7e9e30fe9e45695a0f8907/
D:/Project/Stock/tasks/20261008-research-data-architecture/datasets/validation-01/
D:/StockResearchBackup/snapshots/940b6dae3c3271e91d5890f67e9c097800ca4ec07ecd40e431ef52e98162bf45.json
D:/StockResearchRestore/architecture-v1-20261008/
```

## 建置與相容性

來源為已暴露 atlas-v2 raw OHLCV、原 v4 固定公司事件因子及 25 cases；日曆沿用原 atlas 的 2019-01-02～2026-08-14，不冒充獨立交易所日曆／完整 PIT 母體。先準備 raw 快照，核心 e47fd0e 正常 hooks 封存後才建 canonical 衍生快取。

建置 computed=25／reused=0、13.641 秒、23,628,603 bytes；相同身分重用 computed=0／reused=25、0.297 秒，不覆寫。

| 基礎                      | 日資料列 | 有效列 | ATR 缺值 | 確認轉折 |
| ------------------------- | -------: | -----: | -------: | -------: |
| raw                       |   46,225 | 44,177 |    5,227 |    8,845 |
| permanent_adjusted        |   46,225 | 44,177 |    5,227 |    8,864 |
| reference_factor_adjusted |   46,225 | 44,177 |    5,227 |    8,890 |

75 組快取逐列直接重算完全一致。ATR 缺值包含暖身與品質中斷，不是零；不同 basis 不混用。參考因子還原不是帳戶含息報酬。同日多事件分支有合成回歸，不代表這 25 檔證明所有事件已釐清。

| 原例             | 舊結果                               | 新結果及逐筆原因                                                        |
| ---------------- | ------------------------------------ | ----------------------------------------------------------------------- |
| 5205／2024-07-22 | big_range HHHL，restart 2024-06-06   | 此前 06-13、06-14 raw OHLC 為 NaN；新流程重啟 ATR／轉折，不再產生該事件 |
| 8342／2024-06-03 | big_range bottom，restart 2024-04-16 | 此前 04-23 raw OHLC 為 NaN；新流程重啟，不再產生該事件                  |

兩例當天品質有效，差異來自此前路徑。舊 load 刪掉缺價列再連續計算，新政策保留並重啟；沒有用舊／新績效挑規則。完整 121 個事件差異不等於 121 個策略失敗；不宣稱舊研究全部無效。

## 備份與還原

事前 D 槽可用 158,370,217,984 bytes；兩 producer 排程均 Ready，下一次 10-09 18:00／18:25；未找到相符下載程序。沒有改其 action／啟用狀態。使用既有凍結 task，不讀 producer live SQLite。

- 範圍：當時存在的 research_cache、全部 formal tasks/*/datasets；owner labels task 尚不存在，不能宣稱已備份。
- 4,103 檔、1,812,517,508 bytes；4,063 個 objects 新增，40 檔內容相同重用。前後 inventory／hash 相同，全物件驗證通過。
- 兩個歷史 SQLite 與原 input-archive.json 封存 hash 完全相符且無 WAL／SHM／journal，才明確納入；不是 live DB 通行證。
- 全 4,103 檔還原到上列全新目錄、逐檔核對，正式資料沒有覆寫。演練副本仍保留，沒有自動清理。
- 同 D 槽可防誤刪，不能防磁碟毀損；沒有新增每日排程或異地備份。

## 驗證與下一步

最終合成與整合測試 132 passed，涵蓋缺口、同日事件、ATR／轉折、快取重用／損壞／來源變動、完整直接重算、備份／還原、WAL snapshot 與原 bytes。OpenSpec strict 通過。提交正常 secrets／mypy／Pyright／Ruff 等 hooks 通過，僅登記已核對的 checksum 誤報。未跑 Docker 或全 application suite，不把這些說成已通過。

PR #36 首輪 review 的兩項有效發現另行修正：worktree 穩定檔案保存來源 `mtime_ns`，避免較新 CSV 被新複製的舊 parquet 壓過；複製先進同目錄專屬 partial，驗證後才 rename 發布，中斷可重試且不覆蓋其他 writer 的既有檔。SQLite 沿用已完成 snapshot 的時間，不冒充 live DB／WAL 時間。新增 4 例、seeder 共 6 passed；全部相關測試重跑為 **136 passed／11.32 秒**。CLI 只印檔數／容量／保留數／收據路徑，完整證據仍在收據。原先 ZIP、快取、備份及相容性收據未覆寫，此修正不改研究公式或旧結果。

第二輪 review 修正備份物件的同類中斷問題，並主動把備份 JSON 清單納入相同的 partial／驗證／rename 保護；保留失敗 partial、拒絕覆寫既有損壞 final。快取驗證改依版本自身的非空實作身分清單及 schema，不因目前程式新增／移除／改名而拒絕完整舊版本；直接重算的公式相容性另外檢查。全部相關測試 **155 passed／18.44 秒**，原 canonical 25 檔快取仍能驗證，沒有重建或改其 manifest。

正常 hooks 封存 9dbc867 後，另對原不可變快取執行 bounded 演練：158 檔／23,662,788 bytes，copied=0／reused=158；新 snapshot `D:/StockResearchBackup/snapshots/d6aefd5cb23b0b60e5291a177441437ba736974d9f042c60786a3d5a301d99aa.json`，全 158 檔還原於 `D:/StockResearchRestore/architecture-review2-20261008/`，來源 manifest 前後 hash 相同。這次重用原 objects，原子新物件的失敗與重試由合成測試驗證；不是另一個全專案備份，也沒有重新建公式快取。新還原副本保留，原 4,103 檔收據不動。

[publication-v1/review2.zip](publication-v1/review2.zip) 保存本次 7 個 metadata／execution members，25,448 bytes，SHA256：427e22981cd26bc911195db74e6cb2f5d1bc3d1271ced1b0274ef1d4fa94b052。包含新 backup inventory／restore receipt、原 cache manifest 及當時 reader／backup／演練程式；仍不帶大型 objects。

第三輪 review 補齊直接重算身分檢查：計算前及成功收據前，完整核對封存／目前所有 implementation 名稱與 hashes，含 cache 建置邏輯和事件類型，不只兩個公式檔。相關測試 **158 passed／20.35 秒**，涵蓋未改數值卻改實作、清單變更及計算中身分改變。原 canonical 快取仍可讀，但目前實作不符時明確拒絕新重算收據；原 75 組直接驗證只代表其封存當時的實作，不冒充本次全部新版再次通過。兩份舊 ZIP／收據均保留，沒有為此重建快取或另跑策略。

第四輪 review 發現：raw 價格在已知公司事件日可能不當豁免任何大跳幅；cases 先解析再另外讀 hash 可能綁到不同內容。兩項均修正，相關測試 **209 passed／22.01 秒**，Ruff／Pyright 通過。輸入只讀一次 cases bytes，解析與 hash 共用，完成前再核對 cases／actions；失敗不發布完成收據。價格規則另立 `price-basis.v2`，要求因子／事件類型／跳幅方向與殘差證據，不再只看有事件或重複豁免已還原事件。原 v1 封包、快取及 23／25 相容性證據不覆寫，也不能被視為 v2 的證據。

正常 hooks 封存 3ace9d3 後，沿用原凍結輸入追加 v2 快取：

```text
D:/Project/Stock/research_cache/price-bases/39c540d511abb4438644e06dfe167162a601a863db28363f29d08e02fbc0d6e7/
D:/Project/Stock/tasks/20261008-research-data-architecture/datasets/validation-v2-01/
D:/StockResearchBackup/snapshots/be3e1c105266f06f65eaf661d2cbe2ad6e7b2e6df2dfcb9a15ce1b46287d1fd8.json
D:/StockResearchRestore/architecture-v2-20261008/
```

原 cases bytes/hash、25 codes、46,225 raw rows、actions hash 與初次封包 input receipt 全部相符，排除原快照实际发生解析／hash 不一致。新版本 computed=25／reused=0、14.922 秒、23,630,661 artifact bytes；再次 computed=0／reused=25、0.297 秒。全 **75 組**在完整目前實作身分下精確直接重算通過。這 25 檔的三 basis 品質旗標／原因與 v1 差異為 **0 列**，不能外推所有事件未受修正影響；新規則分支由合成回歸驗證。沒有重跑 v1 的 23／25 detector 相容性或機率，原相容性證據仍僅指 v1。

新版本 bounded 備份 158 檔／23,664,846 bytes，copied=3／reused=155；全新目錄還原 158 檔後再次驗證快取。備份 manifest SHA256：1a40674e54ec3d15aad088c87ee98a3132d359458e6b38a094523e7444215d68。固定輸入、兩份 v1 ZIP 與原 v1 cache manifest 前後 hash 均相同。事前 D 可用 154,651,275,264 bytes；排程仍 Ready 且下一次 10-09 18:00／18:25，程序查詢僅匹配查詢自身，沒有實際相關 writer。沒有改排程、下載或清理還原副本。

[publication-v2/bundle.zip](publication-v2/bundle.zip) 保存 15 個 metadata／實作／演練 members，45,659 bytes，SHA256：a7c4045fd1f35e0a8c42451e9d31a6df346dc01198663b70f85baf84ac10bafc。含 v2 完整 manifest、原輸入收據及 bytes/code 審核、75 組直接重算、品質差異、備份／還原與本次實際程式；不含大型 Parquet。全演練 33.188 秒，只增新版本，原 v1 歷史證據未覆寫。

第五輪 review 發現原始 25 例收據的身分檢查不足，以及長駐／notebook import 後來源更新可能產生記憶體程式與來源 hash 不符。原例現在必須匹配封存 cases SHA256，其他同數量案例即使全部期待通過，也不能取得原例成功收據。正式建置、直接重算及相容性入口改為 fresh-source 子程序；不用舊 `.pyc`，開始／發布前核對實際編譯的來源 bytes，並將執行邊界／artifact-store 納入身分。相關完整測試 **219 passed／35.58 秒**；公用入口端到端包含同尺寸同 mtime 的 SMA5→SMA6 更新、stale caller、舊版可讀但新版重算拒絕，以及公用 build／reuse／recompute／相容性。private fault-injection unit context 明確與正式入口區分。

公用相容性快取核對也採完整目前身分，不只價格／指標兩檔。最後針對此正反分支、fresh-source 公用入口及原例身分重跑 **15 passed／14.95 秒**，Ruff／Pyright 通過。

此輪沒有另外重建 canonical 市場快取或重跑 detector／機率；上列 v2 的 75 組證據仍僅代表封存 3ace9d3 的實作。新執行身分下若要簽發新直接重算／相容性收據，須使用新建身分匹配的快取；舊 v1／v2 快取仍可按原身分讀取，所有原收據／備份保留。不以同一數值或目前 reader 可讀冒充新版再次通過。

第六輪 review 修正 Windows cp950 等系統編碼下中文 worker 收據／診斷的 UTF-8 解碼錯誤（HIGH），以及還原中斷留下 partial final、不能重試的問題（MEDIUM）。bootstrap 與 fresh worker 都明確設定 stdin／stdout／stderr UTF-8，不改使用者環境；回歸包含仍持有舊 bootstrap 的 caller。還原改在獨立 sibling staging 完成所有複製、完整清單／hash／receipt 及來源 manifest 穩定性核對後，才原子 rename 發布目的目錄；失敗保留 staging，新重試可使用同一目的地，其他 writer 的鎖／final 不覆寫。全部相关測試 **227 passed／43.13 秒**，Ruff／Pyright 通過。沒有因此重跑實際 D 槽還原或 canonical 市場快取，舊實際演練收據仍指其當時封存版本。

第七輪 review 補齊真實 post-checkout 功能回歸：scratch superproject 現在追蹤實際 seeder 與相依模組，SQLite fixture 使用有效資料庫，不再以無效文字代替。測試實際執行 hook，核對成功收據、SQLite `quick_check`／內容、只複製 read-set、沒有 link／junction，以及來源 bytes 未改變。Windows 找不到 PATH 內的 `sh` 時使用已安裝 Git 的 shell，不修改系統 PATH；真正沒有 shell 時明確跳過，不冒充已驗證。本機五項 hook 測試全部通過；含先前架構測試合計 **232 passed／48.21 秒**，Ruff／Pyright 通過。僅修正測試 fixture，沒有改 hook 或正式資料；此前 CI 綠燈只代表其選定範圍，不能替代這次補驗。

下一步：接收 Claude 完整標註；新 consumer 明確評估新缺口政策，不替換舊結果；完成[移除前盤點](retirement-inventory.md)、保存舊輸入與通知使用者後，另發 producer PR。網站與研究 session 可以查字典／契約，但 API／還原通過不是策略批准。CI／hosted review 另以線上最新 head 為準。

第八輪 review 保留尚未遷移 consumer 的 `adjusted_prices/daily` 正式日價 read-set：只複製其直接子檔 `*_day.csv`、`price_daily.parquet`、`dividends.parquet`，沿用實體穩定快照／時間戳／hash／原子發布，不重算 basis、不複製其他衍生目錄或新 Stock 快取。來源 partial／lock、目的未知 partial／任何 lock、link／junction 均拒絕；目的本 seeder 的正式檔名加完整 UUID 診斷 partial 可保留且重試，不發布為輸入。真實 hook 回歸已包含該 legacy 路徑。

成功備份另加只增不改的 completion 紀錄，核對並連結該次 started attempt 與完成 snapshot 的路徑／hash／身分及執行統計；原始紀錄不覆寫。沒有完成紀錄只代表完成未確認，不能把旧 attempts 事後一律標成失敗。失敗／中斷不發布 completion，新的 attempt 可重試並保留舊診斷 partial。三項相關測試 **78 passed／18.29 秒**；含全部架構驗證 **253 passed／81.22 秒**，Ruff／Pyright 通過。另做 bounded 實際還原驗證後才新增該輪證據；不重建市場快取或重跑策略。

正常 hooks 封存 098f2d4 後，bounded 演練原不可變 v2 快取：158 檔／23,664,846 bytes，copied=0／reused=158；完成紀錄 `D:/StockResearchBackup/completions/803e64ecb7a947e4b307c709e7929d94.json` 明確連結同 ID started attempt 及原 snapshot。該 snapshot SHA256 仍為 1a40674e54ec3d15aad088c87ee98a3132d359458e6b38a094523e7444215d68。全 158 檔經 staging／receipt／逐檔 hash 核對後才發布於全新 `D:/StockResearchRestore/architecture-review8-20261008/`，還原快取也再次驗證通過。來源 cache manifest 及三份歷史 ZIP 前後 hash 相同，原 objects／snapshot／attempts／還原副本不覆寫。這次全部重用 objects，不將它說成新物件中斷的實際演練；該分支有合成測試。

完整收據在 `D:/Project/Stock/tasks/20261008-research-data-architecture/datasets/validation-review8-01/completion.json`；可攜 [publication-v2/review8.zip](publication-v2/review8.zip) 保存 10 個 metadata／程式原 bytes／演練 members，29,483 bytes，SHA256：285a52f4eb0883ff9c998f3e364f6cd67f374b9747ef5195bd59ea361a4076c9。全演練 8.646 秒。事前 D 可用 154,622,816,256 bytes，相關 writer 查詢為空；兩排程仍 Ready、`wscript.exe` 指向既有 cron launcher，下一次 10-09 18:00／18:25，沒有更動設定。這是有限還原／完成紀錄驗證，不是新公式或市場研究結果。

第九輪 review 補上既定 `price-basis.v2` 契約漏實作的純 `EX_RIGHT` 分支：調整價格的選定因子 >1 時，不再讓小於 40% 的變動規避 invalid-factor／歷史不明處理；raw 一般日原語意不改。13 項新增合成分支涵蓋兩種 adjusted basis、0.9／1／1.1、跳幅與日曆缺口；價格測試共 **100 passed**。不是事後另調門檻；實作 bytes 的改變會產生不同 cache identity，原 v1／v2 市場快取與封存證據不覆寫，也沒有新市場重算。

seeder 保留完整 `preserved_inventory`（path／bytes／SHA／mtime／來源狀態），包括目的端仍被 consumer 讀取、但 primary 已缺少同檔或整個 legacy 目錄的 orphan inputs。不補造原始來源；目前 producer 觀測另列且不冒充原始 provenance，SQLite main file 不做虛假 WAL 邏輯比對。已存在 SQLite 須是無 sidecar 的完整快照且通過唯讀 quick_check；成功收據前重新核對所有新增／保留檔案 hash／大小／mtime，期間變動即不發布收據。來源不明／不符有 `source_alignment_required` 旗標，整組時點一致性明確未認證。保留名稱 API 相容，不刪 orphan、不為消除旗標而覆寫。回歸包含後段失敗後 primary 更新、混合重試證據、途中檔案變動、closed SQLite／sidecars、來源缺失及真實 hook。最終完整相關測試 **277 passed／86.36 秒**，Ruff／Pyright 通過；既有對齊／研究封存門檻沒有被檔案存在或 checkout 成功取代。

第十輪 review 修正輸入準備中斷與舊 basis 清單相容性。`prepare_inputs` 在專屬鎖及 sibling staging 中完成四個輸入、收據、來源前後與 artifact／receipt hashes 核對後，才發布整個正式目錄；失敗保留 staging、正式路徑仍可重試，其他 writer 的鎖／final 不覆寫。快取 reader／完整性驗證改用版本自身的 `identity.parameters.bases`；當目前 basis 新增／移除／改名，完整舊版本仍可讀，只允許其封存選項。拒絕空、重複、非字串、不安全路徑與不符 artifact inventory 的 metadata；建置與新版直接重算的身分門檻不放寬。

兩個相關測試檔 **69 passed／52.44 秒**；完整十檔回歸 **302 passed／110.10 秒**，含五個真實 Windows checkout-hook 測試；Ruff／Pyright／OpenSpec strict 通過。唯讀驗證既有 v1、v2 各 25 檔三 basis 的完整快取，並從各自 inventory 選取 1340 的 raw 日資料（1,849 列）；manifest 前後 hashes 相同。初次指定 2330 不在這兩個封存版本內，reader 正確拒絕後改依 inventory 查詢，沒有把不存在的覆蓋算成成功。未重建 canonical 市場快取、重跑策略或改寫原收據。

本分支以正常 merge 整合新版 `origin/main` a08989f（PR #37），提交前再次 fetch 確認 `HEAD..origin/main=0`；沒有改寫已 push 歷史、提交 main 或修改其他 session 的網頁工作。Claude 完整標註 task 仍不存在，第 1 項與 producer 移除前依賴仍待交付；PR 最終檢查／複審依最新提交的線上狀態確認，不以先前綠燈取代。

第十一輪 review 修正 HHHL 封存程式的重讀競態：相容性驗算只驗證並捕獲一次 texts，detector 與每股 legacy adapter 均從同一份內容編譯，`source_sha256` 也由該捕獲內容計算。公用 `load_detector`／`legacy_prices` 保留驗證 wrapper，不新增可繞過驗證的公用來源入口；內部編譯器不再讀檔。archive 有界單次讀取，hash 與 ZIP 解析共用 bytes，避免先核 hash 再重新開啟不同 archive。

新增五個合成／scratch 回歸：私有 detector 不重讀、archive 捕獲後替換、大小上限、多股票在第二次驗證會取得不同可執行內容、第一股後替換 registry／archive；實際輸出與收據仍一致對應最初捕獲的來源。三個相關檔 **26 passed／26.21 秒**，完整十檔回歸 **307 passed／70.80 秒**；Ruff／Pyright／OpenSpec strict 通過。沒有改原 archive／registry、HHHL 公式、原例門檻或原成功收據，也沒有重跑 25 檔實際相容性／機率。原始 v1／v2 市場與 25 例證據仍指各自封存時的實作，不被這次來源邊界修正升級。再次 fetch，main 仍為 a08989f 且已包含在分支內；其他 HHHL PR 的更新未擅自整合。

第十二輪 review 保留既有 `/data-quality` consumer 的 `data_quality_report.json` 輸入；真實 checkout hook 與 standalone 回歸核對其實體 bytes／hash／mtime／來源狀態、來源未變及再次保留，沒有新增網頁功能。穩定檔案／cache／輸入／備份 object、manifest、completion 與 restore tree 的發布統一採 `publish_noreplace`，競爭目標在最後 exists 檢查後出現時，也不覆蓋。Windows 原生 rename；Linux 原生 `renameat2(RENAME_NOREPLACE)`；不支援的 API／kernel／檔案系統拒絕而不退回覆寫，失敗 staging／partial 與其他 writer 的 bytes 保留。跨目錄及 NUL 路徑也拒絕。

六個相關回歸檔 **186 passed／109.55 秒**，完整十一檔 **335 passed／106.04 秒**，含五個真實 Windows hook；Ruff／Pyright／OpenSpec strict 通過。WSL Ubuntu 的 Windows 掛載磁碟實際回 `EINVAL`，沒有 final、保留 staged file，不能說該掛載可正常建置。另在 Ubuntu 使用者 `.tmp` 的唯一新目錄實測 Linux native backend：**7／7**，涵蓋完整檔／目錄发布，以及既有檔、空／非空目錄競爭；原 staging 與 foreign bytes 均正確保存。這只驗證發布 primitive，不是整個專案的 Linux 驗收；未安装、修改 WSL 設定或刪除測試副本。

Linux 實際編譯 bytes 的 `artifact_store.py` SHA256：0705a3c5f01aeca33cd76fabc53c8b2aab798a5413f3afc3749527d1cd809047；前後相同。Python 3.10.12；保留合成副本 `/home/yenyu/.tmp/architecture-review12-linux-native-aaf4e9046c6948c0aa599fb289b093ed/`。可重做的 native file／directory 案例在 `scripts/tests/test_artifact_store.py`；失敗 ABI／平台／filesystem 分支另有 mock 回歸，不把 mock 當成 Linux 真實操作。Windows 與 Linux 的 rename 語意查核來源：[Python os.rename](https://docs.python.org/3/library/os.html#os.rename)、[Linux renameat2](https://man7.org/linux/man-pages/man2/rename.2.html)。

本輪不重跑 canonical 公式、D 槽備份或還原，先前實際 receipts 仍只對應其各自封存程式；新 artifact-store bytes 會改變新 cache 身分，不能沿用舊 parity 收據充當新實作通過。main 仍為 a08989f 且已整合；Claude 標註及 producer 退場依賴不變。

## Stock 獨立階段的交付確認

PR #36 實作 head `f58efc6d8e49c1a8286bc9225926c159873a6e35` 的 [CI run 37798526191](https://github.com/TaiwanCCyoyo/Stock/actions/runs/37798526191) 已成功；自動複審於 2026-10-08 15:14:31 UTC 完成，沒有新增問題，21 項既有發現均修正及 resolve。335 個相關回歸與正常 hooks 已通過。[PR #36](https://github.com/TaiwanCCyoyo/Stock/pull/36) 於 15:19:56 UTC 合併為 main 595f1fb，並非本 session 執行 merge。文件收尾提交剛好晚於合併，因此從最新 main 595f1fb 建立 `codex/research-architecture-delivery-record-20261008` 單獨交付；該文件 PR 的最新 CI／review 另行確認。

第 1 項 Claude 完整標註仍未交付，整份 OpenSpec 不 archive；producer 舊欄位／快取不移除，owner merge 不代辦，也不恢復研究目標或 automation。下一位 session 可直接由本報告／資料契約／型態字典取得方法、版本、可重算路徑及限制，不必回翻聊天。待獨立標註交付後，再做它自己的量測驗收，不把本次基础層通過當成策略通過。

primary `D:/Project/Stock` 的 main 仍有先前未提交的 submodule gitlink 及尚未套用新 ignore 規則的 `research_cache/`；因此未強制 pull、stash、reset 或覆蓋。現行 managed worktree 已从最新 origin/main 建分支，保留所有研究／測試資料。primary main 更新及 worktree 清理仍须滿足原潔淨／保存／host lifecycle 條件；不刪其他 session 的資源。
