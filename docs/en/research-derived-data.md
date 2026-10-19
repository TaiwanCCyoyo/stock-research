# stock-research 衍生資料與快取

## 責任邊界（擁有者 2026-10-08 決定）

| 層                      | 正本與寫入責任                                                                                      | 消費方式                                                     |
| ----------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `stock-data-downloader` | 下載、永豐分 K 轉日 K、官方行情整合、正規化、公司事件原始事實、股票資料、日曆、法人、月營收及其備份 | stock-research 唯讀；live 檔案不是不可變快照                 |
| stock-research          | 價格政策、均線／ATR／支撐壓力／型態、新衍生快取與研究資料備份                                       | [型態字典](pattern-definitions.md)與下列明確版本 API         |
| worktree／網站          | 消費共用資料、任務特有證據；不另定義同名公式                                                        | 經共用根目錄設定唯讀；不複製、不連結；receipt 記錄讀到的世代 |

舊 producer SMA／EMA 欄位與 `technical_features` 暫時保存相容，新研究不得當作 stock-research 的新研究正本。終點是移入 stock-research；刪欄須待替代來源、舊消費者輸入凍結及全面消費者通知，再以隔離 producer PR 發布新版 parquet。不要原地刪旧資料。

`stock-data-downloader/data/adjusted_prices/daily` 已不存在（2026-10-15 查證：repo 與 `D:/StockData/stock-data-downloader` 都沒有），舊 sample runtime／dashboard help 對它的引用已失效。全市場還原日價改由下方[維護中的共用衍生資料](#維護中的共用衍生資料)提供。

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

## 特徵區塊重用與有限執行 v1

`research_core.derived_features_selective_v1.compute_selected` 延用 `derived-features.v1` 的數值定義與缺價重新暖機，只計算要求欄位及必要依賴；不是原 HHHL v4 的 G／X4 替代品。`feature_identity_v1` 固定輸入、程式、日曆、股票、定義、政策與 runtime 的完整身分；`feature_block_store_v1` 驗證後重用，缺少或毀損只新增 generation，保存舊資料與失敗診斷，不用 mutable latest。

尚未建立任何市場區塊（只用合成資料測試）。依 2026-10-15 決定，第一次建正式市場特徵時應放在共用根目錄的 `derived/` 下，並把 `research_core/research_data_builder.py` 目前寫入 primary `research_cache/feature-blocks-v1/` 的路徑一併改掉（後續工作）；不要再在 `research_cache/` 新增版本。查詢入口 `uv run python -m scripts.feature_blocks plan/query`、取得與 manifest 外部 pin 規則見 [資料契約](../../tasks/20261012-research-feature-reuse/data-contract.md)。單股 scheduler 使用 `stock_feature_pool_v2`；全重用時不要求 worker admission。它用有限 Windows Job Objects，完整 barrier 後才讓上層做全域運算；橫斷面 rank 與選擇不可拆成單股工作。記憶體限制是 admission estimate 加事後程序峰值核對，不是 OS 記憶體沙箱；小工作可能以直接計算較快，見 [固定合成實測](../../tasks/20261012-research-feature-reuse/report.md)。

## 維護中的共用衍生資料

擁有者 2026-10-15 決定（[決策紀錄](decision-records/2026-10-15-maintained-shared-data.md)）：可重用的衍生資料每個定義只維護**一份現行資料**，誰需要較新的資料就去更新；不再為每次輸入變動建立以雜湊命名的不可變版本。

**位置。** 共用根目錄在所有 checkout 之外，由 `STOCK_RESEARCH_SHARED_ROOT` 設定（行程環境變數，否則讀 primary checkout 被忽略的 `.env.local`），解析邏輯在 `research_core/shared_data.py`，沒有 fallback；放在 checkout 或 worktree 裡會被拒絕。根目錄本身或其上層若是 symlink、junction 或 hardlink，或與任何已登記的 worktree 重疊，也會拒絕。選定位置：`D:/StockData/stock-research`。

**`adjusted-daily-v1`：全市場還原日價。** 路徑 `<root>/derived/adjusted-daily-v1/`：

| 檔案                                                                          | 內容                                                                                                                                              |
| ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `current.json`                                                                | 現行世代 id 與其 `status.json` 的 SHA-256                                                                                                         |
| `generations/<asof>-<UTC時間>/status.json`                                    | as-of 日、定義版本（`price-basis.v2`）、日曆、輸入指紋（`run_receipt`）、程式 commit、各 basis 列數／有效列數／品質原因統計、`as_of_inputs`、耗時 |
| `generations/<id>/{raw,permanent_adjusted,reference_factor_adjusted}.parquet` | 依 `Code, Date` 排序，每檔股票一個 row group                                                                                                      |
| `generations/<id>/actions.parquet`                                            | 建置當下讀到的全部除權息事件（`code, ex_date, event_type, price_factor`，含 asof 之後的），供截止日讀取重算                                       |
| `generations/<id>/calendar.parquet`                                           | 該世代的交易日曆（官方報價日期聯集）                                                                                                              |
| `generations/<id>/technical_daily.parquet`                                    | `technical-daily.v1` 每日指標，與 `reference_factor_adjusted.parquet` 一列對一列（同 `Code, Date`），見下方「技術指標」                           |
| `generations/<id>/technical_pivots.parquet`                                   | 已確認的 1.5／4 ATR 高低點，一個轉折一列                                                                                                          |

- **欄位**：`Code, Date, Open, High, Low, Close`（研究價，無效為 NaN）、`RawOpen..RawClose`、`VolumeLots`、`Turnover`、`Quality`、`quality_reason`、`volume_status`、`corporate_action_types`、`restatement_factor`；語意同上方 `prepare_prices`。
- **來源政策**：只用 `Source == "official"` 的報價，**在計算前**就篩掉 `shioaji`（永豐分 K 轉日 K）列；若先混合計算再篩，非官方列仍會影響相鄰官方列的跳幅與品質判斷。2026-10-15 時被排除 152,631 列、351 檔，其中 12 檔完全沒有官方報價，因此不在本家族。排除數量與這些代號記在 `status.json` 的 `source_policy`。日曆也只取官方列的日期。
- **輸入**：live producer 的 `price_daily.parquet`（只取 OHLCV，忽略舊 SMA／EMA）與 `corporate_actions.sqlite`（唯讀）。as-of 是價格最大日期；之後的除權息事件不納入，數量記在 `actions.after_asof_excluded`。
- **日曆與列範圍**：日曆是 `price_daily.parquet` 所有日期的聯集，不是交易所公告日曆；每檔從第一筆到最後一筆報價，中間缺的交易日保留為無效列。
- **更新**：`uv run python -m scripts.maintain_adjusted_daily update`。避開平日 18:00–18:45，producer 有工作在跑時會拒絕。每次建完整新世代：新的除權息會改寫該股整段較早歷史，所以只附加新一天並不正確。建完先核對輸入沒變，再以 `os.replace` 原子切換 `current.json`；保留前一世代以便回退、也讓正在讀的人讀完，以及研究標記「使用中」的世代（見下方），其餘更舊的由 updater 刪除。失敗不動 `current.json`，未完成的 staging 會刪除。同時只允許一個 writer（`.writer.lock`）。
- **實測（2026-10-15，真實資料完整建置一次）**：2,077 檔、4,113 個交易日，每個 basis 6,764,521 列。讀輸入 6.5 秒，計算加寫入 556.6 秒，總共約 9.4 分鐘（單程序）。一個世代 768 MB（raw 223 MB、permanent 250 MB、reference 293 MB）；更新期間新舊兩世代並存，峰值約 1.5 GB。讀一檔 0.12 秒，整個 basis 讀三個欄位 0.31 秒。permanent 與 reference 各有 22,590 列標為 `ambiguous_or_missing_action_factor`：依上方價格政策，事件因子缺漏或不一致時，該事件日以前的還原歷史標為不明，而不是猜一個因子。這些列的來源分布尚未逐一核對。要不寫入就重測，用 `measure --codes N`。這個耗時目前不需要平行化；若之後成為瓶頸，再依 AGENTS.md 先量測有界的單股平行。
- **讀取**：`frame, record = read_adjusted_daily("reference_factor_adjusted", codes=["2330"])`（`research_core.maintained_adjusted_daily`）。`record` 有 family、generation、asof、檔案路徑與 SHA-256，請以 `write_run_receipt(..., shared_data=[record])` 記進研究的 receipt；它只說明讀了哪一版，不是之後保存結果的檢查條件。同一研究的後續讀取請傳入第一次拿到的 `generation=`，整個研究就會固定在同一版；那一版被刪除後會直接報錯，不會悄悄改讀新版。擁有者 2026-10-15 原決定舊版直接刪除；2026-10-19 因改為每天自動更新而修訂：跑超過一天、需要固定一版的研究，開始時用 `uv run python -m scripts.maintain_adjusted_daily hold --generation <id> --holder <研究代號> --reason <原因>` 標記使用中，更新就不會刪那一版；研究讀完立刻 `release --holder <研究代號>`，下次更新才刪。每保留一版約多佔 1–2 GB，`status` 會列出目前所有使用中標記。沒有標記的舊版照舊會被刪。已完成的研究結果不會因為共用區更新或舊版被刪而失效；只有還需要讀的步驟遇到那一版已不在時，才處理那一步（改讀目前版本或重算那一步），不必整批重算。讀取時共用區會把 parquet 的大小與 SHA-256 跟它自己的 `status.json` 核對（每個行程、每個檔案只核對一次），檔案被換掉或損毀時直接拒絕：這是共用區檢查自己算出的成果，研究不必另外雜湊或驗證來源。`uv run python -m scripts.maintain_adjusted_daily status` 可看現行世代。
- **截止日讀取（`as_of`，擁有者 2026-10-15 核准）**：`read_adjusted_daily(basis, codes=..., as_of="2026-10-12", calendar=fixed_calendar, generation=...)` 回傳每檔股票在該截止日、以 `price_basis.prepare_prices(官方報價 <= 截止日, 事件 <= 截止日, 日曆, basis, 截止日)` 算出的結果，欄位與 dtype 都和直接呼叫一致。`calendar` 省略時用該世代截止日以前的交易日。輸出涵蓋日曆上每個位置，包括股票首筆報價以前、末筆報價以後的位置（缺報價列，`missing_official_quote`），所以家族本身照舊只存首末報價之間的列。
    - **為什麼要重算，而不是截斷最新世代。** 截止日之後的事件會改寫更早的整段歷史：因子正常時是乘上去，因子缺漏、同日多種事件或未知事件時則把整段標成 NaN、品質原因也一併串進去，事後拆不回來。換日曆後，非交易日事件掛到哪一列、跳幅以哪兩列計算也會跟著變。`factor(t) / factor(cutoff)` 只能當起點，不是定義。因此 reader 用 raw basis 的 `Raw*`／`VolumeLots` 還原官方報價（`missing_official_quote` 列視為沒有報價，`duplicate_date` 列補回一筆重複），配上同一世代的 `actions.parquet`，在截止日直接重算。
    - **拒絕條件**：截止日晚於世代 asof（之後的報價與事件對該世代未知）；世代沒有 `actions.parquet`（本功能之前建的世代，請 update）；指定的股票在截止日以前沒有官方報價；日曆含截止日之後的日期。不指定 `codes` 時，只回傳截止日以前有官方報價的股票。所有讀到的檔案都先核對 SHA-256。
    - **record** 另外記 `as_of`、`actions_sha256`、日曆來源／筆數／起訖與日期清單的 SHA-256，請放進 receipt。`as_of` 是計算截止日，不是當時可得資料的時點證明；ordinary-reference 名單、產業等其他 metadata 不在這個家族裡，要另外記錄。
    - **成本**：每檔每個 basis 重算一次，等於 `prepare_prices` 的單股耗時；2026-10-16 實測，全市場 2,064 檔、4,110 個交易日的一個 basis，以每批 200 檔讀取共約 2.5–5 分鐘（單程序）。
    - **真實資料等價驗證**：`uv run python -m scripts.check_adjusted_daily_asof --root <共用根> [--build] --cutoff ... --calendar-pins <pins> --out <report.json>` 對每個截止日、每個 basis、每檔股票逐欄比對 reader 與直接呼叫 `prepare_prices`（同一份 live 輸入，指紋必須與世代一致），並統計截斷最新世代會錯幾列。2026-10-16 對世代 `2026-10-15-20261015T161626Z` 跑過一次，四個截止日 × 三個 basis 全部逐欄相等（含 dtype、NaN 位置）：

        | 截止日     | 日曆                                      | 股票數 | 每 basis 列數 | 首末報價以外的列 | 截斷最新世代會不同的列（permanent / reference） |
        | ---------- | ----------------------------------------- | ------ | ------------- | ---------------- | ----------------------------------------------- |
        | 2026-10-12 | PR17 核准日曆（4,110 日，與世代日曆相同） | 2,064  | 8,483,040     | 1,891,177        | 4,110 / 14,800                                  |
        | 2023-06-30 | 世代日曆                                  | 1,848  | 6,122,424     | 1,029,601        | 1,605,592 / 4,365,656                           |
        | 2020-12-31 | 世代日曆                                  | 1,753  | 4,750,630     | 718,528          | 1,750,174 / 3,702,200                           |
        | 2015-12-31 | 世代日曆                                  | 1,529  | 2,272,094     | 256,853          | 1,250,698 / 1,961,415                           |

        較早的截止日各有 6,707–8,534 列在最新世代裡因子已是 NaN、但在截止日其實可知：依 `prepare_prices` 的規則離線核對 `actions.parquet`，這來自截止日後 1 筆未知種類事件，以及 4（2023-06-30）、5（2020-12-31）、10（2015-12-31）檔股票的不可用因子事件（方向不符或值不一致）。PR17 的截止日離 asof 只有三天，之後只有 6 筆可用事件，所以它單獨相等證明不了多少，較早截止日才是主要證據。真實資料裡沒有截止日後同日多種事件、截止日當天沒有可用因子，或日曆與世代不同的例子；這些由 `scripts/tests/test_maintained_adjusted_daily.py` 的合成資料覆蓋。
- **每日自動更新（擁有者 2026-10-19 同意）**：Windows 排程 `StockResearch-SharedDerivedUpdate`，週一至週五 20:30 在 primary checkout（`main`）執行 `update`，排在 producer 18:00 的每日下載之後；producer 還在跑（例如每月 1 日的長補檔）時 `update` 會拒絕，排程每 30 分鐘重試、最多 3 次。名稱刻意不用 `StockProject-*`，因為 `update` 會拒絕任何執行中的 `StockProject-*` 工作，包括它自己。紀錄寫到 `D:/StockData/stock-research/logs/adjusted-daily-update.log`。一次約 13 分鐘、每天寫一份新世代（約 1.8 GB）並刪掉最舊且未被標記使用中的一份。註冊指令（先建立 logs 目錄）：

    ```powershell
    New-Item -ItemType Directory -Force D:\StockData\stock-research\logs | Out-Null
    $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c cd /d D:\Project\stock-research && C:\Users\xjp01\.local\bin\uv.exe run python -m scripts.maintain_adjusted_daily update >> D:\StockData\stock-research\logs\adjusted-daily-update.log 2>&1'
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 20:30
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 30) -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName 'StockResearch-SharedDerivedUpdate' -Action $action -Trigger $trigger -Settings $settings
    ```

- **定義變更**：開新家族 `adjusted-daily-v2`，不在原家族裡改寫。

**技術指標（`technical-daily.v1`，2026-10-17 起每個新世代都有）。** 由同一次 `update` 從該世代的 `reference_factor_adjusted` 列計算（`research_core/technical_daily_v1.py`），所以指標與價格永遠出自同一世代、同一 as-of，且每次都從 2010-01-04（每檔第一筆報價）完整重算，不是只附加新的一天。公式全部沿用既有正本，不另定義：

| 欄位                                                                             | 定義來源                                                                                                        | 何時可知                                                                |
| -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `ATR14`, `atr14_pct`, `SMA5..SMA120`, `EMA5..EMA60`, `BB20_Middle/Upper/Lower`   | `derived_features.compute_features`（`derived-features.v1`）                                                    | 當日收盤                                                                |
| `SMA240`, `MACDHist`（原始價格單位）                                             | 整段序列的 240 列 rolling 平均（窗內有無效列即 NaN）；MACD 用 atlas EMA kernel；與 PR17 pattern-scan 指標同算法 | 當日收盤                                                                |
| `BBWidth`, `RSI14`, `ADX14`                                                      | `feature_atlas_features.compute_features` 的 `bb_width20`／`rsi14`／`adx14`                                     | 當日收盤                                                                |
| `ConfirmedHigh_k15`, `ConfirmedLow_k15`, `ConfirmedHigh_k40`, `ConfirmedLow_k40` | 當天是否**確認**了一個 1.5／4 ATR 高／低點（布林，沒有就是 False）                                              | 當日收盤                                                                |
| `LastHigh_k15`, `LastLow_k15`, `LastHigh_k40`, `LastLow_k40`                     | 截至當天最近一個已確認高／低點的價格；第一次確認前為 NaN                                                        | 當日收盤                                                                |
| `technical_pivots`：`Code, k, kind, extreme_date, confirmed_at, price`           | `derived_features` 的轉折                                                                                       | **只能從 `confirmed_at` 起使用**；`extreme_date` 是事後才知道的極值位置 |

- **缺值**：任何無效列（`Quality` 為 False、OHLC 不合理）讓所有指標重新暖機；無效列本身是 NaN，不補值、不刪列。`Last*` 例外：已確認的轉折是既成事實，跨過缺口仍保留。NaN 是「未知／暖機中」，不是 0 或 False。
- **讀取**：`daily, record = read_technical(codes=["2330"], columns=["SMA20", "BB20_Upper", "LastLow_k15"], prices=["Close", "Quality"])` 回傳指標並在 `Code, Date` 併入同世代的價格欄，就是一張「每天一列：價格＋指標」的寬表；`read_technical("pivots", codes=[...])` 讀轉折長表。`record` 記 generation、`technical-daily.v1`、檔案 SHA-256（`prices=` 時另含價格的 record），放進 receipt；`generation=` 用法同上。本功能之前建的世代沒有這兩個檔，讀取會直接報錯，請 `update`。
- **截止日**：表內數值以世代 asof 計算。需要較早截止日時，用 `read_adjusted_daily(..., as_of=)` 取價格再呼叫 `technical_daily_v1.compute_technical`，不要截斷本表（截止日後的除權息會改寫整段還原價，指標跟著變）。
- **實作與正本的關係**：`derived_features.py` 與 `feature_atlas_features.py` 被既有證據以 SHA-256 鎖定，本功能不改它們。`technical_daily_v1` 對 SMA／EMA／BB 與 RSI／ADX／BBWidth 用逐位元相同的精簡版（同樣的 pandas 運算與順序，不逐列 `iloc`、不算用不到的 atlas 特徵），測試對原函式做精確比對；2026-10-17 在 207 檔真實資料上也逐位元相同。ATR 與轉折直接呼叫 `derived_features` 的 kernel。
- **實測（2026-10-17，真實資料 `measure --codes 100`，不寫入）**：3 個 basis 加技術指標，全市場 2,065 檔估計計算約 22 分鐘（單程序；同一次量測的機器比 10-15 慢，只算價格的部分也較慢）。寫入、雜湊與檔案大小待第一次 `update` 實測；兩世代並存的磁碟峰值會高於上方的 1.5 GB。平行化未評估；平日請在 17:00 前開始，避免撞到 18:00 的 producer 寫入。

### 共用資料的擴充規則

這些規則適用於所有維護中的共用家族；新 session 要放資料到共用區、或幫既有家族加欄位時照做。

1. **一份正本、一個更新指令。** 共用資料只由家族自己的 `update` 寫入（單一 writer、完整新世代、驗證後原子切換 `current.json`），研究只讀。不要在 worktree、`.tmp/` 或 `research_cache/` 另存一份當正本。
2. **每次從頭算，標記算到哪天。** 還原價格會因新的除權息改寫整段歷史，依賴它的指標也一樣；所以每個世代都從起始日完整重算，`status.json` 的 `asof` 就是算到哪天。
3. **加欄位可以，改欄位不行。** 新增欄位就是在計算模組加一欄、遞增 `DEFINITION_VERSION`、更新上表；下次 `update` 起就有。既有欄位的公式、單位、暖機或缺值意義一旦發布就不改：要不同算法就用新欄名，或為價格本身開新家族（`adjusted-daily-v2`）。刪除欄位需要擁有者同意。
4. **每欄寫清楚四件事**：公式（或指向的正本函式）、單位、缺值／暖機規則、何時可知。會偷看未來的值（例如極值日）不放成每日欄位。
5. **每天一列放寬表，事件放長表。** 一檔股票每天一個值的放在 `technical_daily` 這類寬表；數量不固定的事件（轉折）放長表，以 `Code` 與可知日期對齊。格式一律 Parquet（zstd、依 `Code, Date` 排序、每檔一個 row group），JSON 只放小型 metadata。
6. **研究專用的定義不進共用家族。** 帶有特定研究假設的條件、型態旗標、未來報酬標籤留在該研究自己的資料裡。
7. **同一個 PR 更新文件與索引**：本節表格、`docs/en/research-program.md` 資產索引列、測試。

## 舊的不可變快取 v1（legacy）

以下是 2026-10-15 之前的設計，只保留給既有版本讀取；新的共用衍生資料請用上一節。擁有者已同意刪除現有的 `research_cache` 雜湊版本（見決策紀錄）。

2026-10-12：正式共用研究版本由 primary `research_data/` catalog 定位，
`research_cache/` 保留底層區塊。設定、固定版本讀取、原位 legacy 登記與備份範圍見
[共用入口契約](../../tasks/20261012-research-data-entry/data-contract.md)。既有資料與 pinned 原始碼
保留原位置及 bytes；入口完成不代表 2010 全市場版本或高效率每日延伸已完成。

主目錄：`D:/Project/stock-research/research_cache/price-bases/<version_sha256>/`（Git 忽略）。每版本保留 `inputs/`、`implementation/`、各價格基礎／股票的 `daily.parquet`、`pivots.parquet` 與完成 `manifest.json`。身分包含所有來源 bytes、公式 bytes、參數、cutoff、日曆／缺值政策及 Python／套件版本。來源變了就產生新版本；相同身分先驗證後重用，不覆寫。

```powershell
uv run python -m scripts.build_research_cache build --prices FROZEN/prices.parquet --actions FROZEN/actions.parquet --calendar FROZEN/calendar.json --root D:/Project/stock-research/research_cache --cutoff 2026-08-14
uv run python -m scripts.build_research_cache verify D:/Project/stock-research/research_cache/price-bases/EXPLICIT_DIGEST
```

新 worktree 可以直接 `read_cached(Path(absolute_version), "reference_factor_adjusted", "2330")`，或指定 `part="pivots"`。預設驗證全部產物 hash；大量連續查詢應先量測，而不是繞過完整性或另做一套公式。mission 記下絕對路徑、版本及 manifest hash。沒有版本或驗證失败時明確停止，不回落到 live data 或另一版本。

讀取驗證按該版本封存的非空實作清單、`identity.parameters.bases` 與 schema 核對，不依目前程式檔名或 `BASES`；未來新增／移除／改名公式檔或 basis 不會讓完整舊版本失效。讀取只允許該版本確實封存的 basis。這與「目前實作能否精確重算」是不同問題：直接重算工具在計算前及成功收據前另核對目前完整實作清單的名稱與 hash（含 cache／事件類型，不只價格／指標），不能把檔案可讀或局部數值相同說成新版實作等價。

正式 `build_cache`、`recompute` 與相容性 `validate` 入口均啟動新 Python 子程序，直接編譯所觀察的 stock-research 來源 bytes、不使用舊 `.pyc`，並在開始／發布前核對載入 bytes 與封存身分。notebook／長駐程序不能用舊記憶體函式搭配新磁碟 hash 發布完成快取。建置身分也包含執行邊界及 artifact-store；private in-process helpers 僅供 worker／隔離 fault-injection 測試，不是正式入口。相容性收據的「原始 25 例」必須匹配原封存 cases hash；其他案例可診斷，不得借同樣數量冒充原例。

子程序協定固定 UTF-8，bootstrap／worker 都設定串流編碼，包含 Windows cp950 下的中文路徑與錯誤診斷；不靠使用者改全域環境設定。

HHHL 相容性驗算每次只擷取並驗證一份封存程式；archive hash 與 ZIP 成員從同一份 bytes 核對，detector 與所有股票的 legacy adapter 都使用該次已驗證 texts，不在迴圈中重讀來源。收據的 `source_sha256` 描述實際執行的捕獲內容；驗算中來源檔更新，不會讓報告混用多個版本。這仍是明確的 trusted-source AST 執行，不是安全沙箱或新策略批准。

建置採獨占 lock 與新 staging，完成才發布；crash 的 staging／lock 保留診斷，不自動當作完成或清除其他人的鎖。這是應用層不可變契約，不是防系統管理員修改的安全沙箱。不新增排程、保留清理或每日累積。

## 保存／備份

執行時的 raw parquet 每天可能變，仍採實體快照；不可變快取本身在 worktree 外。stock-research 備份由 `scripts.backup_research_data` 管理，詳見 [備份程序](price-cache-backup.md#stock-research-data-backup)。D 槽的只增不刪內容物與快照可以防誤刪，不能防 D 磁碟損壞。

`scripts.prepare_derived_cache_inputs` 先在獨立 sibling staging 完成來源複驗、四個輸入 artifacts 及 `input-receipt.json`，核對完成後才在 per-output lock 下發布整個新目錄。失敗保留 staging、不留下看似可用的正式三檔目錄；可重試相同 final 路徑，不覆寫既有目錄。staging 是失敗／診斷資料，不是已發布輸入，不得拿它冒充通過來源驗證的快照。

cache、輸入、worktree 穩定檔及備份／還原皆用 `artifact_store.publish_noreplace` 發布 sibling staging，不依賴 `exists()`／lock 當作跨平台不可覆寫保證。Windows 使用原生 no-replace rename，Linux 使用 `renameat2(RENAME_NOREPLACE)`；其他平台／不支援的 kernel／檔案系統明確失敗並保留 staging，不退回可能覆寫的 rename。WSL 的 Windows 掛載磁碟可能不支援該旗標；這不代表 Ubuntu 原生檔案系統也不支援。平台語意見 [Python rename](https://docs.python.org/3/library/os.html#os.rename) 與 [Linux renameat2](https://man7.org/linux/man-pages/man2/rename.2.html)。

完成收據索引、覆蓋／缺值／時間／容量、實際還原演練及仍待交付項目放在 `tasks/20261008-research-data-architecture/`。API 可用不是全市場已建，也不是策略已驗證。
