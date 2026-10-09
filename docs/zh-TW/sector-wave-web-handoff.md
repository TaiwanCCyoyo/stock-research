# 飆股分類與網站：已對齊語意及展示交接

2026-10-02，提案階段。已與「飆股分類」session 雙向討論並收到 producer 的欄位／命名確認；網站提案與未來 adapter 由本 worktree 負責，producer、分類研究與 catalog 由原 session 維護。本文件記錄已確認事實與尚未實作的補充契約，不改寫歷史研究 mission 或產物。

## 來源固定點

- Producer worktree：`D:/Project/Stock/.worktrees/sector-wave-catalog`；head `9913d4eb891454a69b05cf4fa4d1541a0d60af11`。
- 契約：`docs/en/sector-wave-catalog.md`；研究：`tasks/20261002-sector-wave-catalog/report.md`、`classification-review.md`。
- 產物：`tasks/20261002-sector-wave-catalog/catalog-v1/manifest.json` 及 `completion-receipt.json`；280 個 gzip chunks。
- `schema_version=sector-wave-catalog.v1`；`run_id=catalog-v1-2019-20260814`。
- `manifest_canonical_sha256=384ee53d22b70dc1650bf84e1887e8515565189c975c29c77ef5e6273c5138c9`。先重建 canonical JSON hash 並核對 receipt，再採用該身分；receipt 不是策略採用證書。
- 觀察期間 2019-01-02～2026-08-14；分類快照 2026-10-01。文字身分處理換行差異，二進位資料仍核對原始 bytes；保留 identity、metadata、quality amendments 與前一版關聯。

本提案 worktree 未合併 producer 分支。實作時以固定、已獲准的 bundle 作輸入，不依賴另一台機器上固定的 worktree 路徑；index 可重建，原產物及舊身分要保留。

## 已確認可用資料

| 表               | 網頁用途與 join                                                                                |
| ---------------- | ---------------------------------------------------------------------------------------------- |
| securities       | `security_id=TW:code`；目前名稱、分類／行情覆蓋、多重 group_ids                                |
| groups           | 官方鏈與研究群分開；member_security_ids，不存在獨立 member_id                                  |
| episodes         | 個股自己的低點、＋25%、翻倍、峰值、確認／觀察截止、截尾與品質                                  |
| waves            | group_id、共同窗口、episode_ids、peer_ids、最大漲幅者、最早＋25%者                             |
| peers            | wave_id＋security_id；共同窗口要求／實際日期、期末／峰值漲幅、峰值日、成交額、可比較狀態與原因 |
| taxonomy_nodes   | 官方樹的身分用 chain_code＋node_code；父子節點展開一致                                         |
| quality_findings | 日期／股票／原因與資料品質；保留與其他表的旗標關係                                             |

來源含 1,942 檔普通股、2,561 episodes、884 waves、64,180 peers。33 研究群與 47 官方鏈可以有相依與重疊視角，不能把 884 當獨立事件樣本數。123 檔缺分類的股票仍保留，82 檔有合格 episodes。來源研究指出 165 個窗口超過 366 日、21 episodes 尚未確認結束。

## Adapter 語意，不改 producer

以下展示 schema 名稱與路由均為提議。

| 來源                 | 展示投影                  | 必須保留的差異                                                                                                   |
| -------------------- | ------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| episode              | market_episode.v1         | 沿用 source episode_id；明列 start、first25、qualification、peak、confirmation、observed_end，而非模糊 start/end |
| wave                 | group_comparison_view.v1  | 族群共同窗口，不轉成個股 episode 或新聞題材事件                                                                  |
| peer                 | comparison_observation.v1 | 同期窗口數值；不混成個股自身波段報酬或帳戶收益                                                                   |
| group / taxonomy     | 分類與導航投影            | 保留 research_group／official_chain、多重歸屬、父子結構與 config 身分                                            |
| provenance / quality | 來源抽屜與行狀態          | 檔案／chunk hash、來源欄位、修正關聯、品質／缺值原因                                                             |

- `catalog_ref=(schema_version, manifest_canonical_sha256)`，`entity_ref=(catalog_ref, entity_type, entity_id)`。run_id 只作可讀名稱，不作唯一 cache key。
- episode_id 取 security、低點、峰值、翻倍及 definition 身分；wave_id 取 group 與有序 episode_ids；peer_id 取 wave＋security。ID 未包含所有來源 hash；相同 ID 跨 run 不保證內容相同。改名／旗標可能保留 ID 卻改 manifest；分段變更另需 mapping。
- `label_kind=retrospective`、`label_available_at=null`、`missing_reason=not_pit_reconstructed`。generated_at、qualification_date 與 first25 都不等於當年真實可用時間。
- `end_date=peak_date`，confirmation 是從最終最高收盤回落 25% 的確認日期；未確認時保留 right_censored／censor_reason。股價止跌、真正買點與新聞啟動未被此定義驗證。
- earliest_qualifying_25pct 只看該 wave 的翻倍 episode 成員，seeds 排除有品質旗標者，不掃全部 peers。ascent_max_drawdown 是低點到峰值的整段統計，不能改名為＋25%後回落。
- winner 是全部可比較 peers 中共同窗口的最大峰值漲幅者，可能不在 episode seeds。官方鏈 seeds 只用未被研究細群覆蓋者，peers 卻是全鏈成員；官方鏈波數不是全鏈普查，不能直接與細群波數比高低。
- `appreciation_fraction=1` 是＋100%，`price_multiple=2` 是 2 倍。永久公司行動調整價格不含現金股息；不是總報酬或可執行帳戶損益。價格 TWD、成交額 thousand TWD，日期 ISO、timestamps UTC；目前股票名稱不證明歷史名稱。
- 保留 coverage、price coverage、comparability_status、quality_flags、null_reason、right_censored/censor_reason。unavailable 使用 null＋原因；quarantined 即使有數字也不進排名，不直接丟棄明細。
- TW:code 不保證已解決全部歷史代碼重用；基金與其他市場命名空間另由 adapter 明確解析。

## 第一版即可呈現

2026-10-02 owner 修正為**先拉全市場時間，再由族群／個股自行浮現與退場**。族群視角／共同窗口比較為點進去後的明細，不是時間軸入口的必要篩選。每股日期軌；共同窗口的期末、峰值、峰值日；兩種分開命名的 descriptor；未分類／單成員／截尾／品質狀態及固定版本證據仍可呈現。只讀保存數值，不由展示層重算官方漲幅。

真實摘錄可作概念樣本：記憶體 `wave-fac5adcc1da105b8`、貨櫃 `wave-2c1a29cc28583ced`、長窗口 PCB `wave-cd364e4c140a4ece`。每個窗口取四筆 peers；金像電在所選 PCB 視角沒有對應的 seed episode，不能替它創造日期軌。

貨櫃例子特別能說明日期差異：長榮在該 wave 的自身 episode 峰值為 2021-05-11，但共同窗口 peer 峰值為 2021-07-06；陽明相應為 2021-05-10 與 2021-07-06。兩者都保留，各自說明問題，不能用共同窗口的漲幅搭配個股 episode 日期，拼成虛構回測。

完整日 K、達＋25%後路徑、新聞因果、歷史業務、真實 PIT 標籤、ETF／策略參與均尚未接入；不是做時間軸 MVP 的必要條件。畫面顯示缺少能力，不生成替代資料。

## 全市場生命周期投影：網站責任

33 研究群由 parent_id 推導 25 根；8 子群會員都是父群子集，不能將父子計數相加。835 檔有研究群，其中 160 檔跨多根；其餘股票從官方產業、官方鏈或未知入口浮現。官方產業大類不等於價值鏈或題材細分類；缺細分類的狀態要保留。分類 producer 不必替網站建立互斥領土。

目前概念使用 25 研究根，對無研究群者由 securities.official_industry 建立補充桶，來源未知則保留 unknown 桶；共 58 個展示群。這是唯讀投影，不新增原 catalog 的正式 group_id，不推論歷史業務。角色研究仍由另一個 session 維護。

全市場按日期讀取全部 episode，不先用 group_id 篩掉資料。生命周期界線是 first25／qualification／peak／confirmation／observed_end；不使用 wave 起迄當族群每日狀態。概念中的三段為「達25%～翻倍前」「翻倍日～峰值」「已過峰值」，確認日退場；截尾者保留到最後觀察並標示未確認，不生成死亡事件。

概念展示聚合按 security_id 去重，保留所有相交 episode refs。多段相交時，以仍在翻倍日～峰值者優先，其次達25%～翻倍前，再其次過峰值；相同階段取較新的 first25 作明細代表，其餘 refs 不丟棄。這是展示合併政策，不是選股／策略規則。圈圈大小隨上升區間股數變化，群內與全市場各自去重；跨群股數不可累加。品質7段保留來源但隔離於一般計數。

新增 proposed global_market_scene.v1 應保存 source catalog、所選日、security／episode refs、分群來源層／版本、生命周期、去重政策、缺值及品質。點圈圈只改選取明細，不能變成全市場查詢的 group filter。來源版本、日期、口徑為索引／cache身分；手機顯示層級或標籤裁減不等於真實退場。

若要真正的逐日強權／疆域，另接 strength_observation：固定定義、視窗、母體、來源可用時間、分群有效期、單位與缺值，保存相對強度等已核准量測。原最終倍數、winner、每日線性插值與動畫座標均不能替代。現有概念只是事後波段生命周期，不提供每日強弱排名。

Owner 進一步要求連續的細胞壁版圖與泡泡融合／破裂消長；網站將主圖改為彼此貼合的膜網，保留原族群身分、來源數字與全部可查清單。面積是股數視覺權重加最小可見面積，不是精確占比。幾何膜吸收只表示畫面重分配，不合併原 group、episode 或會員；動畫過渡幀不新增行情觀測、歷史日期或強度分數。來源仍只提供已保存的生命周期，幾何／動效與可切換配色均由網站 renderer 負責。

## 分類改善：討論後的最小補充

### 已收到第一批角色補證

2026-10-02 分類 session 提供固定的補證入口；本次已唯讀核對 packet、published receipt 與所綁定 catalog。此處保存的是審查中的版本，不代表 PR 已通過 hosted review 或合併，也不代表正式網站已接入。

- Producer worktree：`D:/Project/Stock/.worktrees/sector-role-evidence`；本輪核對 head `dff0902370ed93b23e9572f5582a750cd59d9381`；[PR #14](https://github.com/TaiwanCCyoyo/Stock/pull/14)。本次不查核 hosted 狀態，由原 session 負責後續交付。
- 契約：`docs/en/sector-role-evidence.md`；packet：`tasks/20261002-sector-role-evidence/evidence-v1.json`，receipt：同目錄 `completion-receipt.json`。
- `schema_version=sector-classification-evidence.v1`；`packet_id=sector-role-evidence-20261002-batch01`；`packet_canonical_sha256=a57f081300b1bdd1ff600e0501fb7e7fc511041ba557ac57bf3f5a3fdef944e8`。本輪審查修正版取代原 `1753ab...` 草稿；後續審查修正須重新核對 identity，不能只憑相同 packet_id 重用。
- `scope_profile_id=sector-role-review-20261002.v1`，固定入口為 `research_core/sector_role_review_scopes.v1.json`。validator 依原 catalog 及既定規則重建完整 218 檔 queue；pending 成員不能被省略後變成 scope 外。
- `base_catalog` 精確綁定上文的 `sector-wave-catalog.v1` 與 canonical SHA；原 1,942 securities、2,561 episodes 及 280 chunks 未改。
- 218 檔 review queue，18 檔有至少一個已核對角色，200 檔 pending；21 來源、23 筆角色 assertions、3 筆原 membership 複核註記。這是補證範圍與進度，不是全市場角色覆蓋率或股票排名。

### 全市場接入政策：網站責任

先載入並核對原 catalog，再按 `security_id` **left join 全部股票**。原分類、波段與品質仍保留；缺補證不能讓股票從地圖、事件或明細消失。原 82 檔有 episode 卻缺細分類者仍可浮現，官方產業大類已知不等於業務角色已知。

| 補證狀態                                     | 展示語意                                                         |
| -------------------------------------------- | ---------------------------------------------------------------- |
| packet 未載入／驗證不通過／綁定 catalog 不符 | 補證尚未接入或不可用，保存原因；不能推成股票沒有角色             |
| 已核對 packet，股票不在 scope                | `not_in_review_scope`：不在本批核對範圍，不是負面分類結果        |
| 股票在 scope，尚無 assertion                 | `pending`：待核實，保存 unknown_reason，不是零曝險               |
| 股票有 source_verified assertion             | 來源支持此一角色／產品；其他角色、完整業務與歷史適用期仍可能未知 |

Role 與 product taxonomy 是原研究群、官方產業／鏈以外的獨立補證層，不把 role_id 當成原 group_id，也不從產品自動推出全部角色。保留多角色；群內與全市場摘要按 security_id 去重。`membership_reviews` 只呈現來源及複核原因，不能自動新增／刪除群會員、改 winner 或重算地圖股數。

來源以 `assertion.evidence_refs → sources.evidence_id` 連接；來源鍵不是 source_id。角色／產品標籤使用本 packet 內嵌 taxonomy，各 assertion 的 product_tag_ids 分別保留，不將整家公司的產品套用到每個角色。即使 taxonomy 同樣標成 sector-roles.v1，也須隨 packet canonical 身分固定，不能只取本機最新同名檔案。

審查修正版要求來源的 `supported_products_by_role` 明確關聯 role 與 product；flat `supported_tag_ids` 僅是摘要。assertion 的產品須由該 role 的來源 mapping 支持，不能跨角色套用。產品型錄即使有 mapping，若 `supported_role_ids` 為空仍不能證明企業擔任該角色；同 security/role 重複會被拒絕。

本批全部 23 assertions 的 `effective_from/to` 為 null；`business_relevance` 與 `exposure_path` 也各自未知。個股明細可顯示「事後補證，歷史有效期未知」與來源，不能隨時間拖曳假造角色成立／失效事件，或把今日角色套入當年強度計算。`retrieved_at`、文件年度／covered_period 均不替代角色有效期或公開可用時間；核心／次要業務與直接／間接關聯不互推，不拿缺值作零或分數。

補證來源明細保留 URL、title、locator、inspection_method、短摘錄及 `retained_excerpt_sha256`、時間與 unknown reasons。摘錄 hash 證明保存文字的身分，不證明完整頁面／PDF 已封存、來源現時新鮮或業務／行情因果成立。

展示／cache／deep link 身分增加 `packet_ref=(schema_version, packet_canonical_sha256)`；assertion_ref 必須含 packet_ref 與 assertion_id，因 assertion ID 跨版本可能重複。場景另保留原 catalog_ref、日期、投影政策及補證模式；未載入和已載入不同 packet 不能共用結果。維持相同股票與原分群節點身分，補證更新不製造歷史浮現／退場。正式接入以核准的固定產物及可重建索引為入口，不依賴此機器的 worktree 絕對路徑。

### 後續補充契約

獨立、版本化的 assertion／evidence 補充表，不覆寫 v1。下列是後續展示／歷史補充提議，不能要求第一批 packet 假填未有的欄位。

展示 assertion 保留 assertion_id、security_id、role_id、role taxonomy 版本、effective_from/to、assertion_status、evidence_refs 與 unknown reasons；若另證實群關係，保存明確的 group ref，而不是從 role 推造 group_id。role 區別設計、製造、控制晶片、模組、通路等；來源不足就保留未知。有效年份不能拿 retrieved_at 代替。

Evidence 另記來源 URL／hash、published_at、available_at、retrieved_at、covered_period、來源類型與核實狀態。不用沒有校準的可信機率；只讀當前網頁不能推成過去已成立的業務。

雙方修正了單一 core/secondary/direct/indirect enum：**業務主次與關聯路徑是兩個可同時成立的維度。** 後續可加 business_relevance=core/secondary、exposure_path=direct/indirect，各自有 basis／evidence／適用期間；未核實為 null，unresolved 放在 assertion_status／unknown_reason。主要業務需財報、公司業務或產品來源；直接／間接關係亦需可核對來源，不從官方泛稱節點或股價大漲反推。兩維度不轉成飆股分數或排名權重。

營收占比後續若取得，附財報期間、分母與口徑；不是 MVP 阻擋項。歷史題材事件另表管理，不把當前業務分類當作當波原因。

| 優先 | 工作                                                        | 是否阻擋 MVP                              |
| ---- | ----------------------------------------------------------- | ----------------------------------------- |
| P0   | 固定資料身分、日期／排名語意、長窗口、缺值與品質傳遞        | 必須在 adapter／UX 完成，不需重算 catalog |
| P1   | 記憶體、散熱、PCB／載板角色來源；82 檔有 episode 卻缺分類者 | 可續補，未核實先標未知                    |
| P2   | 歷史業務有效期與當波題材證據，原始頁面保存                  | 可續補，不先開 PIT 模式                   |
| P3   | 預登記短波 definition v2，規則與 mapping 後再評估           | 獨立研究，不在本次挑參數                  |

短波 mapping 保留 old/new catalog refs、wave IDs、split/merge/overlap 與 shared episode IDs；不把同股不同 episode、父子視角直接去重成同一事件。

## 策略／ETF 參與另接證據

獨立記錄精確 catalog／episode／security refs，再連 run／attempt 或 fund／snapshot 身分。訊號、委託、成交持有、披露快照與帳戶收益歸屬分開。

保存 as_of、published_at／available_at、retrieved_at、來源／hash、coverage、missing_reason。快照只證明該披露日觀察到的持股，不代表整段持有；沒有歷史快照不等於未持有。實際帳戶持有來自事件 ledger，不能從訊號推定。ETF 績效口徑仍依 [ETF 比較研究](etf-benchmark-research.md) 對齊。

## 驗證與責任

`scripts.build_sector_wave_catalog.validate_bundle()` 是已存 bundle 的 manifest/chunk/receipt、筆數、跨表參照、品質、完整 peer 與已存 winner 一致性驗證；不讀原始行情，不重算策略。`build_bundle/main` 會讀行情並重新計算，不是展示讀取入口。

本次使用上述驗證入口及真實摘錄 hash 核對，另驗證概念的日期拖曳、群切換、個股來源、不同窗口／episode 日期、缺參與狀態與響應式顯示。第一批角色補證另外以 `scripts.validate_sector_role_evidence` 搭配固定 packet、catalog、既有 receipt 唯讀驗證通過，回報 280 原始 chunks、218 scope、18 verified securities、23 assertions、21 sources、3 membership reviews 及上述 canonical SHA；未使用 authoring 的 `--write-receipt`。

正式前端/API、角色補證展示接入、歷史有效期、策略／ETF join 尚未實作；既有概念仍只使用原 catalog。文件／來源驗證不代替正式 join 與互動驗收；接入時需核對完整 1,942 股票不減少、pending／scope 外／不可用分開、不同 packet 不串台，以及拖日期不創造未知角色事件。
