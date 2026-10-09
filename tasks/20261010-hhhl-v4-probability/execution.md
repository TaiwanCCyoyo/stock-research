# HHHL v4 單次執行收據與交付

交接 ID 20261010；实际本機日期 2026-10-08，不把檔名作時間證據。

1. source preparation `e90c54e`：18 項來源／v1 回歸、25/25 原例通過，沒有讀市場 labels。
2. 讀取 Claude 四題回覆，保存 exact bytes 並追加 mission；核心量測、地標、彙總、producer
   39 項合成測試通過。一般 hooks 修格式／pandas 型別後通過，沒有繞過檢查、改套件或改算法。
3. 結果前封存提交 `70a6872037e9ad5a9d2296c282dc583a698523b4`，乾淨 task branch，
   據此執行一次 `hhhl-v4-descriptive-01`。2026-10-08 13:26:08 寫啟動收據、13:34:39 完成，
   runtime 522.563 秒、四個有界確定性 worker。没有 failed 市場 attempt 或第二次試驗。
4. 來源所有表、資料／程式／定義／因子前後一致，全部 1,080 格保存；完成 manifest
   不列自己為 artifact，attempt 未覆寫。大型結果新增於 primary task，原來源資料庫不動。
5. publisher 首次於寫入前因 Windows 相對 identity path 反斜線而停止；相對鍵原文保持，
   由固定 builder 身分定位 checkout，安全解析檔案，不重跑科學計算。八項合成回歸通過。
6. 新 publication-v1 核對 1,952 原 artifacts 與 19 原 inputs，包內 26 members 重驗通過。
   原定義／程式／契約先封存入包後才更新報告與索引，原 run 的 input identity 不换成新文字。
7. 正常提交檢查指出原包超過 500 KB、明文 SHA-256 被誤認為高熵密鑰。未改 hooks／安全基線，
   原包保留；新增 publication-v2 三個至多 400,000-byte 分片與 metadata ZIP，合併核對原
   bytes/hash 完全相同、1,080 格重驗通過。13 項交付合成測試通過，包括無原 v1 的獨立讀取、
   分片竄改／穿越／重複／過大拒絕；沒有科學重算或修改研究定義。

## 一次核准執行命令（保存重算入口，不核准第二次開算）

```powershell
uv run --no-sync python -m scripts.build_hhhl_v4_probability `
  --dataset D:/Project/Stock/tasks/20261004-feature-discrimination-atlas/datasets/atlas-v2 `
  --task-root tasks/20261010-hhhl-v4-probability `
  --inputs D:/Project/Stock/tasks/20261010-hhhl-v4-probability/datasets/hhhl-v4-validation-inputs-01 `
  --output D:/Project/Stock/tasks/20261010-hhhl-v4-probability/datasets/hhhl-v4-descriptive-01 `
  --workers 4
```

已有 output 會拒絕覆寫。新 clone 欲重算應先取得原 atlas bulk、封存版 code/定義／inputs
與適當執行核准；不能用目前更新後的 report／contract 冒充原 packet。
沒有策略／擁有者損失預算通過判斷、PIT 完整母體認證、獨立確認或 holdout 開啟。

## PR #33 原因診斷更正 — 2026-10-08

- 審查 MEDIUM：原地標 census 未把 missing_before_landmark／window_end 分開，
  而原 landmarks 大表不在 Git 發布包。接受並補交原因彙總，不改原結果／計算定義。
- producer 新增 `landmark_reason_census`，保留原 24 格 key/shape；補件 script 只讀已保存
  landmarks 的五欄，核對原表與 completion manifest 前後 hash、每格事件／股票數。
- 9 項相关合成測試通過；normal hooks 首次自動修格式／未用 import，重暫存後全部通過。
  提交 `671b8cf` 後才產生正式 primary ZIP，並與 Git task 副本核對相同 SHA-256。
- 補件 1,321 bytes、30 格、總 162,864 rows；L20 合格 unknown 238 缺價＋292 窗未滿＝530。
  原 publication-v1/v2、manifest、行情與 1,080 格彙總未覆寫，沒有第二次市場 run。
- 方法索引的模糊「M04 假跌破 2B」名稱改為 M04 spring／F21/F33 2B 代理分列；
  不改原來源、實驗或公式，不把其結果當作擁有者 HHHL 定義的測試。
- 這項修正不改 Stock／submodule 資料分工或備份流程；架構仍只討論。

## PR #33 worker 截止時間更正 — 2026-10-08

- 新一輪 MEDIUM：原 worker 結果等待沒有剩餘時間上限，executor 的離開流程也會等待
  未完成工作；因此原本每檔後檢查 3,600 秒不能中止卡住的 worker。
- 修正僅限執行停止／資源清理：單 worker 與四 worker 均由本次專屬子程序處理，依同一
  monotonic deadline 等待結果，超時／錯誤／消費端中止只終止自己的 pool。
  每批最多原 worker 數、結果順序及雜訊 seed 不變，不改偵測／量測公式。
- 核對與彙總等主程序同步階段在界線檢查剩餘預算；這不宣稱能在系統 I/O 或同步函式
  卡住時硬切整個主程序。超過預算不得寫 complete manifest，未完成產物保留。
- 只用合成案例驗證，不重跑市場或改原 522.563 秒完成收據；原結果與 publication 的
  code_commit／inputs 維持結果前封存版本。這項修正不構成新市場試驗或策略證據。
- producer／補件 14 項相關合成測試通過（35.12 秒），涵蓋 Windows spawn 下的單／四
  worker 超時回收、結果順序、跨批不重設時限、worker 例外、提早 close 及補件完整性。

## PR #33 雜訊首筆更正 — 2026-10-08

- 第三項 MEDIUM 接受：noise 首筆原按平移後 anchor 排序，違反原 mission 的最早原
  事件。只改 noise selector，先選合格最早 breakout_date，再讀該已保存結果；保留
  unknown／no-shift 首筆、不換 seed，其他 event／landmark selectors 不變。
- 27 項相關合成測試通過；補做6項目標測試含 Windows 來源定位跨平台辨識，亦通過。
  重複 ZIP 成員測試的 warning 為故意造負例，不是來源產物警告。
- normal hooks 初次修格式與指出公開 Git commit 前綴誤報；精確行內非密鑰註記後
  通過，沒有改 scanner／baseline／設定或略過 hooks。更正程式封存於 badc66e。
- 從 hash-verified 原51731列 noise 表生成 primary `noise-first-correction-v1.zip`，
  選1864個原事件、補交4格；2074 bytes，Git副本相同。原manifest／noise／v1／v2未改。
  獨立 reader 核對全部1080格，只有指定4格不同，其餘1076格相同；未偵測／重抽／下載。
- 原四格以 overlay 明確取代並記入 registry。CLI查原受影響格若缺補件會失敗；Python
  原包 verifier 仍提供歷史稽核值，最新消費契約要求讀明列補件，不把舊值冒充新結論。
- 附帶更正只讀 metadata 的 Windows 絕對路徑辨識，避免 Linux 離線讀取把來源位置
  誤當相對路徑；它仍是 local-only locator，並未核准連到來源或宣稱大表已取得／備份。
- 再補 reader 的首筆事件分母一致性檢查；造一份重算 hash 但 nonhits 矛盾的負例，
  1 項回歸測試通過（10.68 秒）。這只收緊驗讀，不改已封存的更正計算或補件 bytes。

## PR #33 可取得性文件更正 — 2026-10-08

- 第四項 MEDIUM 接受：canonical index 的「可攜全部結果」原連到僅含 metadata 的
  publication.zip，未讓使用者從入口取得必要三個分片。改指 publication-v2 目錄並
  明列四個必要檔案的個別連結；最新量測仍另讀上述更正補件。
- 核對目錄與四個檔案均存在並已納入 Git；原內容、hash、計算與 reader 不改。
  這是文件交接修正，不是新的研究或量測更正；未新增凍結文字的測試。

## PR #33 Windows CI 與方法入口補正 — 2026-10-08

- Windows CI 的 2540 項通過、1 項失敗，失敗是損壞 ZIP 測試：底層可能拋出
  zlib.error 而非 BadZipFile；補件 reader 未正規化成 ValueError。補齊同一 PR 的
  supplement／publication／correction 三個讀取邊界並保留拒絕損壞內容的語意。
  原失敗案例及四個固定解壓失敗分支測試共 5 項通過（9.82 秒）；不改封裝 bytes。
- 新 MEDIUM 接受：本輪方法總覽也有單獨 metadata 連結，已改連完整 transport 目錄
  並列必要四檔與量測更正配方。搜尋剩餘 metadata 連結均明示用途或完整相鄰清單；
  未把歷史報告內的「metadata ZIP」錯改成另一種產物。

## PR #33 整次執行監督 — 2026-10-08

- 新 MEDIUM 接受：worker deadline 之外，大型 Parquet 寫入／來源再核 hash／artifact
  掃描原仍可能阻塞父程序。public build 改在自有子程序內執行同一運算體，父層以
  單一 3600 秒 absolute monotonic deadline 監督，含 child 啟動及所有重工作；不重設
  worker 或階段預算，不調整型態／抽樣／比較公式。
- child 只寫 manifest.pending.json。成功 exit、收據基本結構／attempt 身分與剩餘
  時間通過後，parent 才發布 manifest.json；失敗或超時保留 incomplete／pending
  證據，不宣告完成、不覆寫舊 output。parent 不再重掃大表或逐 artifact 檔案。
- 超時只處理自有 process tree，Windows 已退出 PID 不送 taskkill，避免 PID 重用；
  無法確認 descendant 清理時明示未知／失敗。程序清理另有有限等待，不宣稱任意
  OS 阻塞都可在 3600.000 秒內收尾；微小父層 metadata 步驟仍逐段檢查 deadline。
- 19 項 producer／supervisor 合成測試通過（34.16 秒），含成功後發布、單一剩餘
  預算、blocked nested child 清理且 unrelated process 存活、非零 exit、不覆寫、
  過期 finalization、NaN／Inf 與不安全 artifact 名稱。未讀真實行情或重跑市場結果。

## PR #33 前置失敗也保留 attempt — 2026-10-08

- 第七項 MEDIUM 接受：昂貴的 dataset／input／identity／Git 前置核驗原在 attempt
  建立之前，若此時失敗或被 supervisor 停止會漏掉嘗試紀錄。parent 現在啟動 child
  前先原子發布最小 attempt.json 與不可變 attempt-start.json；code／identity 為
  null、identity_complete=false，明確未知，不偽裝已核驗身分。
- child 僅接受匹配父層 token／起始欄位的全新初始 output；preflight／Git seal
  通過後原子補入 attempt 身分，保存起始 bytes 並納入 artifact inventory。舊 output
  仍拒絕重用；失敗或逾時沒有 canonical 完成 manifest，不新建重試／授權／結果。
- 23 項 producer／supervisor 合成測試通過（35.68 秒）；原子發布後另核對4項前置
  失敗邊界（0.60 秒）。涵蓋立即 verify_dataset 失敗、child 啟動／timeout、錯誤
  parent token、既存 output 保護及原有成功／清理路徑；不讀實際 run 或市場資料。

## PR #33 更正補件可離線重算 — 2026-10-08

- 第八項 MEDIUM 接受：v1 補件雖綁原來源及核對分母，沒有保存可重算等待／路徑
  分位數的欄位，reader 也未驗完已選 event_id digest 與程式身分。新增 v2，原 v1
  2074 bytes 與 hash 保持不變；reader 拒絕把缺重算材料的 v1 當最新完整驗證。
- v2 保存1864筆已選 noise outcome、51731列來源選取索引及三份相對路徑程式快照。
  先核對精確成員集合與各 bytes／hash，再讀有界 Parquet，重驗原首筆選取、索引
  欄位／事件 digest／程式身分，重算並精確比對四格全部統計；不執行嵌入程式。
- 19項合成回歸通過（79.13秒）。normal hooks 先指出 pandas 型別註記／格式，補正
  後全數通過；程式先封存於 f1ba001。之後再核對1項完整成功路徑（4.10秒）。
- 只從原 hash-verified noise 表產生 primary `noise-first-correction-v2.zip`，713815
  bytes／解壓973133 bytes，SHA-256 c91f27a43a2ef98ebc87bc41a7d94e8b8ed1eaa820eb882299ee5464b7615a94。
  離線 reader 核對四格與v1更正完全相同、其餘1076格與原包相同，並
  再驗原noise／manifest及v1 hash；未偵測型態、重新算價格結果或重抽日期。
- 來源 hash 與程式快照是可重算／身分證據，不是惡意偽造的密碼學認證；部分欄位
  索引不能驗回整份原Parquet bytes。獨立核對來源欄位仍須取得原noise表。此補件
  不構成新候選、獨立樣本、策略通過或核准上方架構遷移。
- 正常500 KB大檔 hook 拒絕直接提交713815-byte ZIP；原件保留，不改 hook、不刪
  欄位／事件。新增無損 transport，封存於86369d5；兩項單片／多片、缺片／錯片／
  錯誤整體digest回歸通過（4.27／0.69秒），normal hooks通過。Git保存新目錄的
  correction-transport.zip 與400000／313815-byte兩片，全部bytes組回原c91f27a4
  ZIP；不生成另一組科學數字或更改f1ba001封存的原補件程式快照。
- 秘密偵測將plain metadata的公開hash誤報；依既有產物慣例改用420-byte metadata
  ZIP，只有publication.json一成員，沿用既有有界reader，不改scanner／baseline。
  修正封存於417373b，兩項transport回歸再通過（4.22秒），normal hooks通過。
  原未發布plain metadata仍保存；全部三檔組回原補件，原ZIP及科學數字不變。

## PR #33 地標原因／股票數可重算 — 2026-10-08

- 第十項MEDIUM接受：v1 reason補件只驗舊格總數，沒有可重算reason及distinct
  securities的欄位。新增v2，保存162864列五欄landmark投影與兩份程式快照；有界
  驗成員／hash／row/type identity後，重算全部30個完整reason格及舊24格事件／股票數。
- 修掉舊測試仍只期待單一artifact的斷言；11項合成回歸通過（3.30秒），normal
  hooks整理格式後通過，程式先封存於45fd594。包括原因改名／重分桶、股票數、
  投影、舊v1拒收及原來源／新補件helper身分分開的負例。未更改census公式。
- 僅從原hash-verified landmarks讀五欄生成 primary `diagnostics-supplement-v2.zip`，
  57686 bytes、解壓119096 bytes，SHA-256 2393f3658848d8792020006e20f243ff6e46789c007979f8dcbe5b7f225f151b。
  reader離線重算30格與v1全部相同，涵蓋162864列；原v1的1321 bytes／hash不變。
  無價格重算、型態偵測、新期間或比較。新程式身分不冒充原run的producer/helper。
- 全檔helper hash曾因noise更正而改變；核對原70a6872至今僅noise首筆相關改動，
  地標census函式及依賴未變。投影給可重算與來源身分，不宣稱能抵禦任意惡意偽造；
  獨立原始證據核驗仍需完整原表。舊v1及原完成收據完整保留。

## PR #33 外部 publication 展開大小限制 — 2026-10-08

- 第十一項MEDIUM接受：10 MB壓縮上限不能限制高壓縮率ZIP的展開量。reader現在
  於任何成員解壓前分別核對descriptor與ZipInfo：單成員32 MB、全包64 MB；內部
  member reader也核對單成員上限。低報descriptor不能避過實際header限制。
- 20項publication合成測試通過（3.33秒），包括四個單／總、descriptor／header
  邊界，確認拒收發生在任何member open之前。原封裝／科學數字不動，不重造產物。

## PR #33 v1 metadata 有界讀取 — 2026-10-08

- 第十二項MEDIUM接受：v1 publication.json不應在大小核對前無界read_bytes。
  沿用v2的100000-byte metadata上限，先stat拒收超大檔，再最多讀上限加一byte，
  讀後再核對，防止檢查後增大繞過限制。原封裝bytes／計算定義／科學結果不動。
- 22項publication合成測試通過（3.12秒）；新增過大檔在open前拒收及stat後增大
  仍僅讀有界大小兩個回歸。未下載、重跑市場、修改接受門檻或重造舊補件。

## PR #33 固定因子來源身分 — 2026-10-08

- 第十三項MEDIUM接受：generic receipt自洽不等於本實驗固定輸入。機率producer的
  parent與worker改讀固定wrapper，對原factor／cases／receipt三個SHA讀前及讀後
  核對。SHA取自事前preparation-v1包，重新核包4908ef85...db549與primary receipt
  相同；原32,848列因子及25個case通過新wrapper，未取新資料或重算事件／結果。
- 26項producer／supervisor合成回歸通過（30.65秒），新增正常固定快照、自洽改寫
  因子＋receipt拒收、generic reader中變動遭後驗拒收。子代理只改測試，在uv快取
  權限邊界停止，由主代理於已授權環境執行，不修改ACL／快取／環境或繞過hooks。

## PR #33 地標座標、程序所有權與完整驗讀 — 2026-10-08

- 第十四項 MEDIUM 接受：scan_frame 保留 landmark helper 的 nullable 索引，截尾
  地標不再被計畫 t0+L 覆蓋。合成案例涵蓋 window_end、地標前先命中／失敗與實際
  觀察到 L。原表不覆寫；新增明示 coordinate-view helper，複製並只修正缺日期的
  索引。原 162864 列有 1532 列需 nullify，讀前／讀後來源 hash 相同；座標更正
  不改 status／reason／outcome 或摘要，入口及版本在 data-contract／report。
- 第十五項 MEDIUM 接受：Windows 用自有 Job Object 與啟動閘門，在原程序 handle
  成功加入 job 後才執行工作；所有退出路徑均終止並有界確認 job 已空，leader
  native crash 後仍保留 descendant 所有權。失敗不降級成 PID 清理或警告繼續。
  真實 Windows 測試驗 native os._exit(7) 後自有 descendant 消失、無關程序存活，
  assignment 失敗前實際工作未啟動，及清理無法確認必須失敗。POSIX 非零退出
  同樣清理自有 group；不是授權終止下載 session 或排程。
- 第十六項 MEDIUM 接受：publisher／reader 精確比對事前 1080 格完整鍵集合及
  型別，不只列數／唯一性。測試含完整固定格、少一格、多一格、唯一但錯誤的
  比較鍵及同步重算 hash 的無效包；補件共用測試 fixture 一併採真固定網格。
- 第十七項 MEDIUM 接受：兩個 portable supplement reader 在資料頁解碼前核對
  Parquet framing、footer／Thrift、固定列數／扁平欄位及 row-group 展開大小。
  負例確認拒收發生在 read 資料頁前；不宣稱 metadata preflight 是 OS 硬隔離或
  防惡意偽造認證。decode 後既有來源、型別與全部統計重算驗證仍保留。
- 最終 focused suite 120 項通過（198.96 秒），唯一 warning 是刻意造重複 ZIP
  成員的負例。較早一次整合測試指出舊 synthetic grid fixture 與直接呼叫內部
  supervisor 未先建 attempt 的測試前提錯誤；修正 fixture，不放寬 production。
- 原 publication、目前 noise overlay 各 1080 格及 diagnostics-v2 均通過新 reader；
  上述地標座標核對只讀兩欄。未重算市場價格、事件、機率，未改原包／來源 bytes。
- Windows-only pywin32 沿用 lock 既有 311 版本，僅改為 root 直接依賴。offline
  resolution 初次意外提議其他套件降版，已完整撤回這次降版差異；最終 uv.lock
  只增兩行 root 依賴資訊，uv lock --check --offline 通過，不下載或改其他版本。
- 正常 hooks 首輪指出 pandas 型別多載與參數化測試的可能未初始化變數，已修正
  型別／fixture 並接受正常格式化；相關 20 項再驗通過（1.26 秒），未更動檢查規則。

## PR #33 摘要 payload 與更正索引 — 2026-10-08

- 21d987f 的線上 CI 通過，該 head 自動複審完成後新增第十八／十九項 MEDIUM；
  因仍有新發現，未把 CI 成功或舊 threads 清空當作 PR 最終通過。
- 第十八項接受：完整 key grid 還不足以驗收摘要。新增 shared validator，依原
  describe／quantile／comparison 公式驗必要 payload、非負整數分母、證券數界線、
  命中與非命中加總、未知原因加總、finite-or-null 數值、比例／未知上下界、
  分位數母體與 small_sample／lift；不從 null 分位數反推母體為空。另核對完整
  grid 內的年度／pooled、期限及價格基礎基準引用；地標依原公式没有 t0 基準。
  這些都是已固定欄位的自洽性，不是新增比較或從摘要重算全部來源個案。
- 第十九項接受：research-registry 追加明示 coordinate-view correction，supersedes
  僅原截尾 index-as-observed 語意；不替換整張原表。source 指正式資料契約並說明
  report／execution、原表位置、1532列、版本及局限。22事件registry驗式通過，
  文件入口均存在；沒有新增凍結文字的測試。
- 第一輪 payload 整合 224 項通過（171.77 秒），追加跨格基準引用後，最終 239 項
  通過（175.62 秒）。唯一 warning 是刻意重複 ZIP member 的負例。涵蓋完整空組、
  非空／unknown-only、原 producer 的合成1080格、漏欄位／bool／string／NaN／Inf、
  矛盾counts／rates／bounds／reasons／quantiles、錯基準但自洽lift，及同步重算hash
  的publisher／reader拒收。未放寬原缺值、分母或任何研究通過門檻。
- 新 validator 唯讀核驗既有原包與目前 noise overlay 各1080格、diagnostics 30格，
  全數通過；原產物與研究數字不變，未下载、偵測型態或重算市場outcomes。
- 子代理的一次 uv 驗證於快取權限邊界停止，由主代理在已授權環境執行上述測試；
  未修改ACL、套件環境、scanner、baseline或hook。最新head仍需自己的CI／複審。
- 正常 hooks 指出 optional 數值重複 dict lookup 的型別縮窄及測試 tuple 展開註記；
  改用局部變數／明確五元素鍵並接受正常格式化，173項相關測試再通過（10.45秒）。

## PR #33 分位數完整性 — 2026-10-08

- GitHub 將 main 的 PR #37 合併到本分支，形成 e503129；已保留其 web 修正並
  fast-forward 本地分支。該 head CI 成功，但自己的自動複審新增第二十項 MEDIUM，
  不沿用 d540b51 的舊通過狀態。
- 接受新發現：原固定 outcome 在標記命中時同時記錄等待，已知非命中則要求完整
  路徑。validator 因此要求六個分位數 known 等於各自 hits／nonhits、unknown=0；
  非空母體不可缺值，空母體仍保持 null。等待範圍依原 t0 時計為1..horizon、
  地標 L+1..126，保留小數插值，並核對原公式保證的分位數排序。未改研究定義。
- focused suite 325 項通過（211.91 秒）；唯一 warning 是刻意造重複 ZIP member
  的既有負例。涵蓋缺欄／null、計數加總自洽但缺成員、範圍／反序、合法邊界與
  插值，及重算 hash 後 publisher／reader 仍拒收不完整等待統計的端到端案例。
- 既有原 publication 與目前 noise overlay 各1080格、diagnostics 30格通過新 reader；
  核驗唯讀，研究數字與原產物不變。未下載、重算市場或新增比較／接受門檻。
- 子代理僅補測試，由主代理驗證與交付；最新修正 head 仍需自己的 CI／自動複審。
- 正常 hooks 的型別檢查通過，僅整理 import 與測試格式；接受格式差異後，293項
  摘要／發布讀取測試再通過（76.68秒），未改 hooks、環境或已封存產物。

## PR #33 非命中路徑數值界線 — 2026-10-08

- 00f4f8a 自動複審於15:06 UTC完成，新增第二十一項 MEDIUM：finite／母體／排序
  正確仍可能掩蓋不可能的最低報酬或回落。依兩個既有正價格公式要求最低報酬>=-1、
  最大回落在[0,1]，保留浮點極限端點。同步核對已知nonhit必未達原TARGETS，因此
  最低報酬也須<target-1（H63為0.5、H126為1）；直接重用outcome常數，不改命中定義。
- 367項摘要／發布讀取回歸通過（54.76秒）。新增一般與地標格的下界／標籤上界／
  回落負例、合法端點／正報酬，以及同步重算hash後publisher與reader仍拒收的案例。
- 原包及目前overlay各1080格、diagnostics30格通過新reader；唯讀核驗，不重造包
  或重算市場。子代理只補測試，主代理驗證與交付，尚需最新head自己的CI／複審。
- 正常hooks只格式化測試，型別檢查通過；格式後本次80項界線／發布拒收回歸再
  通過（4.38秒）。00f4f8a的CI亦成功，但有新finding，不能代替此修正head的驗收。

## PR #33 未知原因詞彙 — 2026-10-08

- 199c80d 的CI成功，15:19 UTC複審新增第二十二項 MEDIUM：unknown reason只驗字串
  與加總不能拒收拼字／缺原因。按原adjusted／atlas／noise／active landmark四個
  producer分支列舉集合，不從資料觀察結果反推；拒收(missing)、拼錯、自創及
  跨basis／family原因，非空Counter桶須正計數。缺值仍未知，不改成零或換原因。
- 428項發布／摘要／更正／補件整合回歸通過（223.05秒）；唯一warning是既有
  重複ZIP member負例。含scoped正負例、零桶及重算hash後的publisher／reader拒收。
- 原包／目前overlay各1080格、diagnostics30格唯讀重驗通過，數字与產物不變。
  新head自己的CI與複審仍是交付條件，既有成功head僅歷史收據。
- 正常hooks只整理測試格式，型別檢查通過；格式後46項原因／發布拒收測試再
  通過（3.97秒），不改hook規則或環境。

## PR #33 最新 main 整合 — 2026-10-08

- main 合併架構 PR #36，最新595f1fb；正常 merge，保留.gitignore及research-program
  兩邊入口。先前report的工作檔Git hash與HEAD相同，僅換行假差異；原bytes已在
  本worktree .tmp/pr33-main-merge-20261008/report-before-main.md備份，刷新索引後
  沒有任何report暫存差異，才合入主線新增的型態字典索引。
- 新registry四筆架構correction的空supersedes違反既有驗式，並會讓消費者失敗。
  核對原v1／v2 ZIP member後补明確引用，僅對原可執行行為或未限定重用解讀。
  archive fragment中的member及冒號後語意標籤不是HTML anchor，不代表整份原結果
  或收據被替換。四筆事件ID／原note／原封包不變，既有暴露與本PR更正全部保留。
- 合併後封存型態來源／reader相關90項回歸通過（6.13秒）。不初始化或刷新producer
  checkout、不新建Stock快取、不重跑機率；主線的新價格政策不默默替換本次舊结果。
- registry按既有驗式通過：26事件、原22事件全部保留、正式source入口無缺漏；
  11項研究evidence回歸通過（0.51秒），未放寬更正或暴露規則。
- 主線另合併純文件收據PR #39（204781a），再次正常merge，只更新架構report與
  OpenSpec完成標記。worker編碼引用核對PR36原review所指8fb2d46的cache_execution.py；
  該行為在第五輪後才出現，不誤指較早封包內沒有worker邊界的derived_cache快照。

## PR #33 固定來源與抽查補交 — 2026-10-09

- 4ee4d2f 的 CI 成功；該 head 複審三項 MEDIUM（第23～25項）仍需修正，不能將
  先前 CI 或 review 完成視為無問題。來源驗算先跑完整 atlas verifier、核對事前固定
  dataset_id，才讀 rule／案例／價格；原三個 preparation hashes 於讀取前後及完成前
  核驗。常數移到共用 source 模組，builder 仍沿用同一個固定身分，沒有新下載或開窗。
- 報告將原因 v1 明確標為歷史，並連結目前 v2 與其 reader；原 v1 大小／hash／原始
  生成紀錄不改，不能混指目前包含投影的可重算封包。
- 原十筆 audit 僅含 t0，future builder 依相同 security_id／breakout_date 排序與前十筆
  選取，再 one-to-one 連接同事件 L20 的全部已保存欄位，加 l20_ 前綴。不挑新案例，
  不把 early_hit／early_failed／unknown 當 active 剩餘段。明確座標 view 沿用 null 規則。
- 原完成包不重寫；另由 scripts/supplement_hhhl_v4_audit.py 只讀原 audit 與 landmarks
  產生 landmark-audit-v1.json。JSON 保存10筆 L20 原投影及 joined audit；reader 比較
  原包 ten-case bytes、驗原來源身分並重算 join。不讀行情／偵測型態／重新標籤。
  來源前後 hash 固定，JSON 至多500000 bytes，Parquet 仍有界預檢；僅明確允許原
  asof_date 的無時區 timestamp[ns]，其他 reader 不默默放寬日期或 extension。
- 56項來源／builder／座標／原source回歸通過（42.18秒）；50項補件／有界Parquet
  測試通過（3.98秒），涵蓋原日期型別、四種status、缺漏／重複／身份不符、篡改、
  來源中途異動、不可覆寫及 CLI。既有 adjprice warning 原樣保留，不改凍結程式。
  補件程式正常提交後才生成正式 artifact；驗讀收據另補，尚未宣稱遠端新 head 通過。
- 0210c96 的正常hooks首先指出pandas型別與測試read override簽章，修正後50項再
  通過（4.81秒），mypy／pyright／全部正常hooks通過；沒有停用檢查或更改環境。
  61440b3另將新audit helper列入future runner前後identity清單，正常hooks亦通過。
- 61440b3已提交且worktree乾淨後，從原封存表生成primary
  D:/Project/Stock/tasks/20261010-hhhl-v4-probability/landmark-audit-v1.json；新建而非覆寫。
  同bytes原擬交Git task目錄；55680 bytes，SHA-256
  f1ab85e00c4b36f372e2bd848579b5eb928833a7030f098dfcdb64fcb5e42f3d。
  primary及交付副本的reader均通過：同10筆原ID、96欄，包含原t0及所有L20欄位。
  原audit／landmarks／manifest hash前後符合原publication；不改原封包或1080格。
- plain JSON正常hooks遇公開hash的秘密偵測誤判，且formatter改交付副本排版；
  primary原JSON55680 bytes未動，格式後本機副本不發布、不冒稱同hash。改採既有
  單成員 publication.json ZIP 的無損transport，壓縮及展開均100000 bytes上限。
  原內容／schema不變，不改scanner／baseline／檢查設定；ZIP讀取沿用相同join驗讀。
- transport55項回歸通過（5.80秒）；新增read測試簽章的型別問題經正常hooks回報後
  修正，45項補件測試再通過（5.55秒），06f672b的mypy／pyright／全部hooks通過。
  初次ZIP在局部測試後、transport提交完成前產生；06f672b封存後另新建校驗ZIP，
  與primary及Git交付副本逐bytes相同，沒有冒稱初次封裝已在封存程式下執行。
  ZIP6861 bytes，SHA-256 26c7eff6196b706db5fba0f62b077093b51af8cbd3849e0293d6949f58e41617；
  單一成員publication.json與原55680-byte JSON一致，三份ZIP及reader皆通過。
  registry27事件通過原驗式，11項evidence回歸通過（0.48秒）；原26事件保留。
