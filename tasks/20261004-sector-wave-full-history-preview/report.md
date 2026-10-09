# 2010 年起族群波段資料交付報告

本次使用本機既有資料，完成 **2010-01-04 至 2026-10-02** 的連續歷史辨識。
狀態維持「**初步辨識，規則未定**」。這是事後描述資料，供網站查詢、族群比較與後續
K 線研究使用；尚未驗證任何事前選股或交易策略。

## 為什麼原先只做到 2019

2019 是先前研究沿用的策略觀察視窗，並非官方資料的起始年，也不是永豐金資料
必須作為主要來源的規定。既有合併 Parquet 實際涵蓋 2010 年起，官方資料仍是主要
紀錄，Shioaji 用於缺口補充；本次直接固定這份 Parquet，每筆來源保留 `Source`。
沒有呼叫會以較新 CSV 覆蓋 Parquet 的一般 loader。

固定輸入共有 6,576,397 筆、2,075 個代碼：官方 6,391,446 筆，Shioaji 184,951 筆。
2010–2012 有 918,999 筆且全部為官方；2013–2018 有 2,165,851 筆；2019 起
3,491,547 筆。本次已納入範圍內的全部既有年份。2010 以前即使公司事件表有紀錄，
也不代表這份價格快取有完整價格可供本研究使用。

因此原來的 2019 範圍應被理解為研究選擇，不能拿來描述資料涵蓋率。舊報告與輸出
保留。本次沒有修改 submodule 的載入器、資料格式或排程。

## 分析範圍與資料結構

2,075 個代碼分開記錄：目前 metadata 標記股票的 1,942 檔、創新板 28 檔，合計
1,970 檔執行分析；104 個 metadata 身分未明的代碼保留價格與缺口，但不納入股票
統計；0050 作為基準保留，也不納入股票統計。這是目前 metadata 加上既有快取的
母體，不能宣稱為沒有存活者偏差的歷史全市場普通股母體。較晚首次出現價格不等於
上市日期，metadata 股票類型也可能包含特別股。

同一條完整序列使用網站固定的原方法：segments、filter 各三個尺度，不按年度重置。
方法設定與 TypeScript 原檔逐 byte 固定。代表波段採 segments/balanced，成員資格從
wave.start 開始；確認的 end 不包含當日，未確認終點則包含 observedThrough。
代表優先順序為大尺度、起點較早、穩定 ID，沒有加上啟動候選是否成功的門檻。
原方法目前保留累積漲幅至少 60% 的波段；這個暫定規則未經策略有效性驗證。

| 表格                     |      筆數 |  gzip bytes |
| ------------------------ | --------: | ----------: |
| securities               |     2,075 |     608,422 |
| methods                  |    11,820 |     655,715 |
| baseline_waves           |    53,188 |   5,674,033 |
| source_phases            | 2,579,106 | 103,175,406 |
| candidates               |   790,250 |  90,669,960 |
| support_records          |   790,250 |  64,010,335 |
| relations                | 4,328,518 | 136,832,989 |
| representative_intervals |     7,875 |     789,153 |
| transitions              |    14,528 |   1,085,054 |

表格以穩定 ID 關聯，保留方法、尺度、原始欄位、診斷、原生父子關係與證據來源。
全部候選，包括失敗、未解決和沒有連結的候選均保留。候選的成員關係依候選本身
所在日期判定；候選的後續觀察範圍與同類鄰近候選支持度分開保存。

原生 wave gain/drawdown、candidate forward gain/drawdown 使用百分比單位，60
表示 60%；日期查詢與代表切換的 gain/jump 使用比例，0.6 表示 60%。報酬基礎為
永久非純現金事件的參考價因子，並非含息總報酬，也不是現金股利五日訊號價格。
缺值與零值分開，無法跨越的事件或數值連續性缺口不製造漲幅。

## 分類仍需補完的內容

附加資料提供 2,075 筆分類、80 個研究群組、566 個產業鏈節點、29 個來源與
2,092 筆缺口。分類分成目前官方產業名稱、多重產業鏈歸屬、研究族群快照，以及
有明確來源的公司業務斷言。官方產業代碼不知道時保留未知，不從名稱推造代碼。
已保存的八家公司證據包直接沿用，沒有把目前分類倒填成 2010 年的已知分類。

先前 18 家初始人工審查不代表分類完成，**200 家證據隊列仍待處理**。
104 個身分未明代碼中，部分產業鏈資料有掛牌類型線索，仍不足以證明當時是股票、
下市股票或歷史有效母體。網站可用目前族群瀏覽，但須顯示分類日期、未知歷史有效日
與來源；K 線研究若要回答當時可否事前辨識，需另補可得時間與歷史母體。

2010–2012 的公司事件涵蓋仍有缺口，例如 TPEx 減資來源的回溯限制與 TWSE 舊年
查詢限制；缺紀錄不等於沒有事件。快取缺少歷史首次可得時間，較早期價格比較仍有
參考價調整風險。這些是整體涵蓋限制，沒有把它們變成每天都禁止計算的數值旗標。

## V2 修正與驗證結果

原固定 producer 的 Python log-ratio 漲幅防護，可能在浮點邊界與原 TypeScript
的個別 log 差值連續段判定不同。先以合成例子確認差異，登記
`compact-revision.md` 後，才從已保存結果另匯出 catalog-v2。
新的 `exact_pinned_js_run.preview.v2` 使用已保存的原生 run ID 判定連續性；
沒有重跑分析或改參數，catalog-v1 保留。

9 個固定輸入、2,075 個價格序列、1,970 個原生分析描述與 SHA 在兩版完全相同。
7,875 個代表區間與 14,528 筆切換紀錄相同；範圍法檢查 3,899,751 個成員日期查詢，
此次實際資料的受影響漲幅數為 **0**。合成邊界測試仍證明修正必要。

全量驗證確認筆數、檔案 SHA、ID、波段／階段／候選／支持度關聯、父子關係、
代表排序、終點包含規則與切換漲幅。方法失敗 0，未收斂方法 3，保留原結果與診斷；
跨 run 階段與未解決父子關係均為 0。第一份 `verification-receipt.json` 的原生證據
檢查僅涵蓋 SHA；PR 審查後另存 `verification-receipt-v2.json`，逐檔解析 1,970 份
原生結果，以固定 V2 adapter 重建全部 9 類 compact rows，比對完整欄位、筆數與
重複次數；另重建 105 個沒有原生分析的排除代碼。所有內容一致，未執行分析方法。
新增「修改 native 並同步更新 hash」仍會拒絕的測試。後續驗證亦強制九類表格的
每列都有有效歸屬，並核對所有列恰好被重建一次；保存的 exact run 則用原本
JavaScript 的純轉換核對，避免 Python 在已知浮點邊界上作出不同判斷。
`verification-receipt-v3.json` 確認 1,970 份 exact run 全部一致，沒有使用 Python
fallback；九類表格的重建筆數與保存筆數完全一致。404 項 Python 主流程、
14 項 publication audit 入口、6 項 Node 測試通過，正常提交檢查通過。

使用 catalog-v2 的 `manifest.json` 作為網站與 CLI 的共同入口：
SHA-256 `c7848ae7ad177770babfda774e07923f995ba2cb3fa4a83d77d02f77a0dfe140`。
原始計算固定於 `37cb418`，V2 adapter/export 固定於 `2ad557a`，metadata 封存工具
固定於 `1f10ddb`；後續提交保存本報告與收據，不改原始計算。

詳見各版 `verification-receipt*.json`（舊收據保留）、`gain-diff-receipt.json`、
`sqlite-snapshot-audit-receipt.json`、`artifact-size-receipt.json`、`publication-receipt.json`。
`provenance-chain-audit-receipt.json` 另外確認 2,075 檔查詢身分鏈、1,970 份 native
收據 context，以及原 producer／adapter 與固定提交 `37cb418` 的程式 bytes 一致。

## 重用入口與維護

| 項目                   | 正式入口與狀態                                                                                                                                                                                                                |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 穩定 artifact ID／版本 | `20261004-sector-wave-full-history-preview/catalog-v2`；manifest schema `opportunity-local-history-preview.v1`，revision `gain-continuity-v2`                                                                                 |
| canonical 檔案         | 本 task 的 `catalog-v2/manifest.json`；`contract.md` 與 `params.json` 定義欄位、關聯及固定設定                                                                                                                                |
| 分支／工作目錄         | `codex/sector-wave-full-history-preview-20261004`；`D:/Project/Stock/.worktrees/sector-wave-full-history-preview-20261004`                                                                                                    |
| 完整資料取得           | 保留工作目錄內的 `inputs/`、`catalog-v2/series/`、`catalog-v2/chunks/`、`runs/native/`；新 clone 只能取得 metadata 鏡像，完整備份／恢復未建立                                                                                 |
| producer／重算入口     | `scripts/prepare_opportunity_history.py` 固定輸入；`scripts/build_opportunity_history.py` 使用固定 `params.json` 與 TS 快照執行六方法；原計算提交 `37cb418`。只有具備相同 SHA 的全部依賴才能重現，重算指令不是備份            |
| saved-only 重匯出      | `scripts/rebuild_saved_opportunity_catalog.py --source-manifest <catalog-v1/manifest.json> --output-root <新的目錄>`；不執行 Node，V2 adapter 提交 `2ad557a`，輸出目錄必須尚未存在                                            |
| 查詢／驗證             | `scripts/query_opportunity_history.py` 與 `scripts/verify_opportunity_history.py`；需 hash 相符的完整價格、calendar、表格及原生檔案                                                                                           |
| 維護模組               | 主專案 `research_core/opportunity_history_*`、`scripts/*opportunity_history*` 維護衍生資料與契約；價格擷取／正規化仍由 `shioaji_stock_prices` 維護                                                                            |
| 已知 consumer          | 網站「規劃 AI 策略研究展示網站」，chat `01a0f85b-ed76-7153-947c-759892470507`，引用 catalog-v2 供索引／依代碼投影；研究 K 線策略 chat `01a03e40-a4b7-7142-99d3-8bd6b72ff7a3` 為後續使用方向，尚未有已執行的 consumer task/run |
| 限制與替代關係         | V2 取代 V1 的漲幅連續性政策，保留 V1；descriptive 可用，分類歷史有效日、200 家證據及完整備份仍不完整                                                                                                                          |

從此工作目錄執行以下已驗證的日期查詢：

```powershell
uv run python scripts/query_opportunity_history.py --manifest tasks/20261004-sector-wave-full-history-preview/catalog-v2/manifest.json --code 2330 --date 2020-01-02
```

metadata 恢復工具 `scripts/publish_opportunity_history.py` 已驗證完整 bytes 與 SHA，
例如恢復到尚不存在的暫存目錄：

```powershell
uv run python scripts/publish_opportunity_history.py restore --bundle-index tasks/20261004-sector-wave-full-history-preview/catalog-v2/bundle-index.json --target-root .tmp/catalog-v2-metadata-restore
```

查詢入口先檢查 schema、已知 adapter revision 與漲幅政策，所有結果均附 `evidence`，
包含實際讀取的 manifest／series／calendar SHA 與版本身份。V2 的 calendar、指定
股票序列及所讀表格，每個依賴均須提供有效的預期 SHA；缺少時在讀取任何依賴前
拒絕。網站可於 cache 初始化
共用 `validate_manifest_identity()` 與 `validate_manifest_trust()`，再使用同一個
`query_security()`。
完整驗證工具也共用相同身份檢查，在讀取依賴前拒絕未知 adapter、漲幅政策衝突或
compact 身份不一致，以及缺失或衝突的辨識／代表選擇規則。
本次固定 manifest 已通過該入口；這項入口修正未重跑全量掃描，
既有 v3 的內容重建收據與產物均保留。
查詢也核對指定代碼、series／security ID、共用 calendar ID 與陣列長度。
calendar 與 series 的內容定址 ID 會依原 exporter 的 canonical JSON 定義重算，
排除各自的 ID 欄位後核對完整內容；日期軸也必須排序且不重複。只更新檔案 SHA、
保留過期內容 ID 的日曆或價格序列會在進入查詢前拒絕。
每個日期另須通過真實 Gregorian `YYYY-MM-DD` 的解析與完全相同的回寫比對，
拒絕簡寫日期、ISO 週日期別名及不存在的日期；有效閏日可保留。
`calendar-date-audit-receipt.json` 確認固定目錄的 4,105 個日期均符合此規則，
既有 manifest、calendar 與價格／原生結果均保留；沒有重跑方法。
查詢使用的 security row 與該股票的全部代表 interval，也必須綁回已核對的
series ID；security row 另核對 calendar ID。既有 interval 透過 series 的內容 ID
綁定日曆，若另有 calendar ID 則一併核對，保留原始資料形狀。
是否計入機會數會依已核對序列的證券角色與 cohort 重算；連續區間也會由原本
JavaScript 的精確來源 run 重建。單檔查詢只轉換指定股票，完整驗證仍可一次批次
核對所有股票；這項純轉換不執行分析方法。排除角色保留原有 Python fallback
區間，且不能包含代表波段。代表 interval 也核對整數索引、合法界限與不重疊。
指定股票的原生檔與收據也須核對 SHA、輸入／程式身分與來源 context；查詢會以
原始 adapter 重建完整 security row 與所有代表 interval，逐欄比對並保留重複筆數。
因此仍在合法界限內的起訖日期、漲幅基準或波段／最早候選身分變動，也會拒絕。
重建前，查詢與完整驗證會共用原生語義檢查：失敗方法不能帶成功的波段／階段／
候選；波段須符合日曆界限、實際價格最高點與漲幅，階段、候選及支持事件也須
符合來源索引與匹配規則。即使同步改寫原生檔、收據與衍生表的 SHA，也不會
核准違反這些規則的結果。這些檢查只讀保存結果與價格，不執行分析方法。
V2 的可分析證券原生檔必須保留精確 JavaScript source runs；欠缺此欄位的程序
失敗診斷仍可保存，但不能取得 verified 收據。排除角色繼續使用既有 fallback。
來源 context 綁回實際 calendar、series manifest、canonical input receipt 與原始
params.json bytes／設定內容；每份 native 收據必須保持相同 context。V2 原計算來源
仍是 V1 身份，與新的 compact adapter 分開核對。新增檢查已掃描全部既有序列與
收據，未再掃描大型 compact 表格或執行分析。
新 build 與 saved-only rebuild 的 manifest 會記錄原始設定檔的路徑與 SHA，
驗證工具據此讀取；若明示另一個衝突的路徑則拒絕。既有固定版本未改寫，
可使用 `--params <原始設定檔>`，未提供時才保留原有相鄰目錄的讀取方式。
設定檔的 Windows 跨磁碟參照也會在建立輸出前拒絕。新增
`content-identity-audit-receipt.json` 核對既有 calendar、全部 2,075 個 series 的
內容 ID，以及原始設定檔的 bytes／設定內容，既有完整重建收據仍保留。
收據中的設定檔位置使用 manifest 宣告的參照、legacy 的 `../params.json`，或
明示外部設定檔的雜湊標記，避免工作目錄位置改變驗證證據；舊收據保留當時記錄。
`content-identity-v2-audit-receipt.json` 另核對全部查詢表格的身分連結，以及
790,250 筆候選與 790,250 筆支持度的日期界限。候選的 ensuing 範圍與 forwardEnd
依固定 `analyzeCase` 定義使用包含終點的索引，支持度範圍則涵蓋匹配事件點。
失敗、未決與空漲幅候選仍保留，未新增結果篩選門檻。
原生 phase 的 start／end 同樣核對包含終點的日曆界限。支持事件依原始 native
candidate 順序重新建立，距離相同時選第一筆，完整比對匹配清單、順序與範圍。
`query-native-contract-audit-receipt.json` 確認上述查詢語義、全部 2,579,106 個
phase 與 1,970 份原生檔案的 790,250 筆支持事件均相符；舊收據繼續保留。
`query-reconstruction-audit-receipt.json` 進一步重建全部 2,075 個完整 security rows
與 7,875 個完整代表區間，確認 1,970 份可分析原生檔均保留精確 runs，收據的
輸入身分與 context 相符；其餘 105 檔保留既有 fallback。目錄 SHA 未變，
沒有重跑方法或重新核對其餘七類大型表格；完整九表證據仍引用既有 v3 收據。
`query-native-semantics-audit-receipt.json` 再以共用驗證器檢查全部 1,970 份原生
結果，並重建 2,075 個 security rows 與 7,875 個代表區間；固定目錄 SHA 相符。
`pinned-pure-wave-launch-audit-receipt.json` 另直接使用固定 TypeScript 的純函式，
完整比對 11,820 份方法記錄中的 106,376 次波段出現、790,250 筆候選與價格
雜訊值，全部與原存結果完全相同。兩種方法共享波段，因此出現次數是表格中
53,188 個共享波段的兩倍。純函式只在記憶體中開放呼叫，來源檔未修改；沒有
執行 `analyzeCase`、曲線擬合或覆寫原生結果。
共用驗證器亦要求波段整段落在同一個非空的精確 source run，並直接使用這些
原始純函式核對全部大小尺度、狀態切換、波段父子／設限欄位，以及候選的價格
漲幅、回撤與結果。檢查腳本、wrapper 與固定 TypeScript 的 bytes 都納入成功
快取的身分；修改資料或程式後必須重新驗證。Python 改寫的浮點運算曾在少數
終點判斷與原 source 不同，因此沒有把該改寫作為正式驗證規則。兩個獨立邊界
回歸與 162 個方向性門檻案例確認原 JavaScript 語義得到保留。
`query-native-price-semantics-audit-receipt.json` 確認這個正式入口核對全部 1,970
份保存原生結果並重建 2,075 個證券列與 7,875 個代表區間，固定目錄 SHA 未變。
階段標籤另直接使用固定來源的 `phase(slope)` 核對，拒絕同步改寫 SHA 後仍不符合
原始斜率門檻的標籤。`pinned-pure-phase-audit-receipt.json` 確認 11,820 份方法
記錄的全部 2,579,106 個標籤一致；沒有重新擬合，前述波段與候選核對收據仍保留。
純函式重建不會證明保存的擬合斜率與端點來源。因此公開查詢／完整驗證會先將
原始 manifest bytes 綁到固定已發布的 `c7848ae7…`，再沿其 native 與 receipt SHA
核對完整原生 bytes，包括六方法的 status、全部 segments 與診斷。這個外部錨點
不能由待驗 manifest 或旁邊的收據自行更換。其他未登記版本必須由呼叫者明示
`expected_manifest_sha256`，CLI 為 `--expected-manifest-sha256`；預期值應來自
獨立保存的原始版本紀錄，不能臨時計算待驗檔案的 SHA 來當成認證。
`native-publication-anchor-audit-receipt.json` 核對 Git 保存的六個 manifest byte
parts 可精確還原固定原始版本，以及其全部 1,970 份 native／1,970 份 receipt
bytes 相符。斜率或端點連同候選、支持與 compact 表格一起重簽的回歸均被原 pin
拒絕。直接 JS 檢查也要求六個唯一且已知的方法／尺度；任何失敗 scope 僅回報
partial，Python 拒絕核發 verified 或加入成功快取。原始資料的失敗方法數仍為 0，
失敗診斷可以保存。這輪只核對認證鏈，原有純計算核對收據保持，沒有重跑擬合。
可重跑入口為 `scripts/audit_opportunity_publication.py`；需固定版本的完整 manifest、
同版本 `bundle-index.json`／有序 byte parts，以及 manifest 引用的 native 與
receipt 原始檔。它依固定發布 SHA 核對 metadata 鏡像與完整原生檔案身分，
不讀價格快取、不執行曲線方法。未指定 `--receipt` 時只輸出核對結果；指定時只能
建立新收據，原始收據保持。`native-publication-anchor-audit-receipt-v3.json` 記錄
入口、匯入的信任模組與註冊常數身分，以及索引與各分片的實際內容雜湊，讓其他
session 能識別同一輪的完整程式與輸入。通用入口核對分片 bytes，不宣稱任意
外部索引具有 Git provenance；v1／v2 保留各自的歷史紀錄。

```powershell
uv run python scripts/audit_opportunity_publication.py --manifest tasks/20261004-sector-wave-full-history-preview/catalog-v2/manifest.json
```

首次完整核對需啟動各證券的原始函式檢查，這輪約八分鐘；同一程序內的成功
結果可以依完整資料與程式身分快取。網站第一次初始化仍應呈現載入狀態並量測
實際耗時，不能把尚未核對的資料當成成功。
目前 CLI 支援 V2；原始 V1 明確拒絕並指出保留 producer `37cb418` 的精確查詢入口，
不會默用 V2 漲幅語義。保留 V1 表格、metadata 與原有收據，沒有改寫舊結果。

本次亦補上未來 producer 的跨磁碟 preflight 與來源缺值摘要：無法相對引用的 native
目錄在任何輸出前拒絕；`source_counts` 排除缺值，`source_missing_count` 僅計算
觀測到的價格列。固定價格輸入沒有 Source 缺值，這些修正未重匯出既有資料。

saved-only rebuild 也會在建立目錄或複製之前檢查所有原生證據與收據的相對路徑，
跨 Windows 磁碟的配置會明確拒絕。SQLite 快照會拒絕未由主檔 SHA 授權的非空 WAL，
並在 backup 前後檢查主檔與 WAL 身份；失敗保留部分產物，不核發成功收據。
另以四個實體複本核對本次固定來源主檔與既有 backup：兩份 SQLite 的 schema、
資料內容摘要與各表筆數均一致，原檔前後 SHA 未變。沒有開啟來源資料庫連線或
改動來源 WAL；目前 WAL 狀態不代表建立快照當時的狀態，但內容一致可確認本次
backup 未包含超出固定主檔的資料。

metadata 恢復指令只還原 root JSON，回傳 `tables_restored/prices_restored/fits_restored=false`。
不要把新 clone 的 metadata 視為完整資料可用；完整原產物的取得限制見下節。

## 待共同決定的備份與分工

完整 compact 表格共 **403,501,067 bytes（約 385 MiB）**、4,294 檔；原生分析
467,534,898 bytes（約 446 MiB）；每版價格序列另有 105,173,146 bytes。
沒有刪除原生階段或關係來縮小資料。網站宜使用小型首頁索引與依代碼讀取的投影，
這些展示投影應可從 canonical 資料重新產生。

本次 Git 保存程式、規則、收據、root metadata 的原始 byte 壓縮鏡像與索引。
每版 root metadata 鏡像約 1 MiB，超過單檔上限時明確拆成有序 byte parts；
還原會先驗證順序、每段與完整 SHA，再恢復原始 JSON。
**這只還原 metadata，不能從 Git 恢復完整 tables、價格、輸入或 fit。**
目前這些大型資料仍保留於本工作目錄，完整備份機制尚未建置。

建議下一輪共同討論三件事，再實作：

1. 小型、需人工審查的規則與分類證據留 Git；大型不可替代快照與計算結果使用
   以 hash 辨識的封存備份或 artifact storage，制定保留政策並做完整還原演練。
   Git LFS 也可比較，但本次沒有擅自啟用或假定有備份。
2. 官方／Shioaji 擷取、正規化、來源優先序與價格涵蓋資訊由
   `shioaji_stock_prices` 維護；族群研究標註、衍生波段與版本契約留主專案；
   網站負責展示投影。是否把公司業務分類證據也移到 submodule，需要確認使用者
   與其他研究是否共用，再決定所有權。
3. 改善 loader 的來源與涵蓋 API：讓呼叫者明確知道是 Parquet 全歷史、短期 CSV
   還是合併來源；傳回逐代碼日期涵蓋與來源優先政策，避免再次把研究視窗誤認為
   資料起始年。這是後續提案，本次未動 loader 或既有快取。

本次交付不代表上述備份、歷史分類補證或事前策略研究已完成。網站 session 接收
catalog-v2、各表筆數／大小及驗證收據；未來 K 線研究可引用這個固定版本，再另外
登記其問題、母體、資料可得時間與驗證方法。
