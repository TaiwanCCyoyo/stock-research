# Stock 衍生資料與快取

## 責任邊界（擁有者 2026-10-08 決定）

| 層                      | 正本與寫入責任                                                                                      | 消費方式                                                      |
| ----------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `stock-data-downloader` | 下載、永豐分 K 轉日 K、官方行情整合、正規化、公司事件原始事實、股票資料、日曆、法人、月營收及其備份 | Stock 唯讀；live 檔案不是不可變快照                           |
| Stock                   | 價格政策、均線／ATR／支撐壓力／型態、新衍生快取與研究資料備份                                       | [型態字典](pattern-definitions.md)與下列明確版本 API          |
| worktree／網站          | 指定版本消費、任務特有證據；不另定義同名公式                                                        | 不可變快取用絕對路徑唯讀；不複製、不連結、不用 mutable latest |

舊 producer SMA／EMA 欄位與 `technical_features` 暫時保存相容，新研究不得當作 Stock 的新研究正本。終點是移入 Stock；刪欄須待替代來源、舊消費者輸入凍結及全面消費者通知，再以隔離 producer PR 發布新版 parquet。不要原地刪旧資料。

尚未遷移的 sample runtime／dashboard help 仍使用 `stock-data-downloader/data/adjusted_prices/daily`。新 worktree 明確保存其既有正式日價檔案為實體快照，連同來源時間與收據，不重算、不改 basis，也不冒充新的 Stock 快取；其他 producer 衍生目錄及 `research_cache` 仍不複製。

## 價格與計算正本

`research_core.price_basis.prepare_prices` 接收原始單股 OHLC、事件、明確日曆與 cutoff；`basis` 必填：

- `raw`：不還原，保留來源報價與品質。
- `permanent_adjusted`：分割、除權、減資等永久事件參考因子；現金股息不還原。
- `reference_factor_adjusted`：包含現金股息的參考因子；不是現金再投入、帳戶含息總報酬或 PIT 認證。

同一事件類型的重复因子須完全一致，只套一次；同日不同事件的組合未經證據釐清時，受影響的還原歷史標不明，不選第一筆、不猜因子相乘。缺價、不合理 OHLC、衝突因子、未知事件及無法解釋的大跳動保留原因。`Raw*` 保留來源值，無效研究價為 NaN，不插補也不把缺值當零。

價格定義從 `price-basis.v2` 起不再僅因事件日存在而豁免 ≥40% 跳幅：須有同一交易日、單一已知類型、全部一致的有限正因子；跳幅方向與因子一致，因子正規化後殘差仍須小於 40%。現金／除權息及分割因子不得大於 1，反分割不得小於 1；其餘永久事件依記錄因子方向。永久還原只容許尚未還原的純現金事件解釋跳幅，已還原的除權息不得再次豁免；全參考因子還原沒有額外豁免。這是明示的研究品質政策，不是成交限制模型或所有特殊事件的法律定義。raw 一般日不強求因子，但未知因子不能用來解釋大跳幅。

原 `price-basis.v1` 快取、驗算與收據保留原身分，仍能按封存版本讀取；不能把它們說成 v2 已重算或相容性再次通過。容器 schema `stock-derived-cache.v1` 不變，公式版本由 manifest 的 `identity.definitions.prices` 區分。

`research_core.derived_features.compute_features` 是新 ATR14、SMA、EMA、BB20 與 1.5／4 ATR 轉折的共用正本，完整公式由 `definition_metadata()` 回傳。無效日曆列重置暖身與轉折；無自然週末缺口推定。pivot 的 `extreme_date` 是事後極值位置，`confirmed_at` 才是確認可知日；尾端未確認極值不輸出。

舊 atlas／HHHL task 不改讀這個新模組。新基礎有更嚴格的缺值／事件處理，可能與舊程式去掉缺價後的結果不同；必須看差異紀錄，不能宣稱是逐筆等價替換。

## 不可變快取 v1

主目錄：`D:/Project/Stock/research_cache/price-bases/<version_sha256>/`（Git 忽略）。每版本保留 `inputs/`、`implementation/`、各價格基礎／股票的 `daily.parquet`、`pivots.parquet` 與完成 `manifest.json`。身分包含所有來源 bytes、公式 bytes、參數、cutoff、日曆／缺值政策及 Python／套件版本。來源變了就產生新版本；相同身分先驗證後重用，不覆寫。

```powershell
uv run python -m scripts.build_research_cache build --prices FROZEN/prices.parquet --actions FROZEN/actions.parquet --calendar FROZEN/calendar.json --root D:/Project/Stock/research_cache --cutoff 2026-08-14
uv run python -m scripts.build_research_cache verify D:/Project/Stock/research_cache/price-bases/EXPLICIT_DIGEST
```

新 worktree 可以直接 `read_cached(Path(absolute_version), "reference_factor_adjusted", "2330")`，或指定 `part="pivots"`。預設驗證全部產物 hash；大量連續查詢應先量測，而不是繞過完整性或另做一套公式。mission 記下絕對路徑、版本及 manifest hash。沒有版本或驗證失败時明確停止，不回落到 live data 或另一版本。

讀取驗證按該版本封存的非空實作清單、`identity.parameters.bases` 與 schema 核對，不依目前程式檔名或 `BASES`；未來新增／移除／改名公式檔或 basis 不會讓完整舊版本失效。讀取只允許該版本確實封存的 basis。這與「目前實作能否精確重算」是不同問題：直接重算工具在計算前及成功收據前另核對目前完整實作清單的名稱與 hash（含 cache／事件類型，不只價格／指標），不能把檔案可讀或局部數值相同說成新版實作等價。

正式 `build_cache`、`recompute` 與相容性 `validate` 入口均啟動新 Python 子程序，直接編譯所觀察的 Stock 來源 bytes、不使用舊 `.pyc`，並在開始／發布前核對載入 bytes 與封存身分。notebook／長駐程序不能用舊記憶體函式搭配新磁碟 hash 發布完成快取。建置身分也包含執行邊界及 artifact-store；private in-process helpers 僅供 worker／隔離 fault-injection 測試，不是正式入口。相容性收據的「原始 25 例」必須匹配原封存 cases hash；其他案例可診斷，不得借同樣數量冒充原例。

子程序協定固定 UTF-8，bootstrap／worker 都設定串流編碼，包含 Windows cp950 下的中文路徑與錯誤診斷；不靠使用者改全域環境設定。

HHHL 相容性驗算每次只擷取並驗證一份封存程式；archive hash 與 ZIP 成員從同一份 bytes 核對，detector 與所有股票的 legacy adapter 都使用該次已驗證 texts，不在迴圈中重讀來源。收據的 `source_sha256` 描述實際執行的捕獲內容；驗算中來源檔更新，不會讓報告混用多個版本。這仍是明確的 trusted-source AST 執行，不是安全沙箱或新策略批准。

建置採獨占 lock 與新 staging，完成才發布；crash 的 staging／lock 保留診斷，不自動當作完成或清除其他人的鎖。這是應用層不可變契約，不是防系統管理員修改的安全沙箱。不新增排程、保留清理或每日累積。

## 保存／備份

執行時的 raw parquet 每天可能變，仍採實體快照；不可變快取本身在 worktree 外。Stock 備份由 `scripts.backup_research_data` 管理，詳見 [備份程序](price-cache-backup.md#stock-research-data-backup)。D 槽的只增不刪內容物與快照可以防誤刪，不能防 D 磁碟損壞。

`scripts.prepare_derived_cache_inputs` 先在獨立 sibling staging 完成來源複驗、四個輸入 artifacts 及 `input-receipt.json`，核對完成後才在 per-output lock 下發布整個新目錄。失敗保留 staging、不留下看似可用的正式三檔目錄；可重試相同 final 路徑，不覆寫既有目錄。staging 是失敗／診斷資料，不是已發布輸入，不得拿它冒充通過來源驗證的快照。

cache、輸入、worktree 穩定檔及備份／還原皆用 `artifact_store.publish_noreplace` 發布 sibling staging，不依賴 `exists()`／lock 當作跨平台不可覆寫保證。Windows 使用原生 no-replace rename，Linux 使用 `renameat2(RENAME_NOREPLACE)`；其他平台／不支援的 kernel／檔案系統明確失敗並保留 staging，不退回可能覆寫的 rename。WSL 的 Windows 掛載磁碟可能不支援該旗標；這不代表 Ubuntu 原生檔案系統也不支援。平台語意見 [Python rename](https://docs.python.org/3/library/os.html#os.rename) 與 [Linux renameat2](https://man7.org/linux/man-pages/man2/rename.2.html)。

完成收據索引、覆蓋／缺值／時間／容量、實際還原演練及仍待交付項目放在 `tasks/20261008-research-data-architecture/`。API 可用不是全市場已建，也不是策略已驗證。
