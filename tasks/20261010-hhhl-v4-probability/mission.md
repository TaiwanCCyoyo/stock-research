# 頭頭高／底底高 v4：突破、上方壓力與早期越線的描述性比較

任务 ID 沿用擁有者交接的 20261010，本機開始日期為 2026-10-08（Asia/Taipei）。
交接日期不是執行時間證據。來源為
`D:/Project/Stock/.tmp/claude-kline/20261010-codex-handoff-hhhl-v4-probability.md`，
SHA-256：2653c95adb14a665dd453326b4cce34cf6e7853b1ada8d002d9a8489eed42844。

## 本批三個問題

1. 突破當天起算，126 個共用交易觀察內達到原收盤兩倍的比例，相對固定控制如何？
2. 上方無線／有舊壓力／有近期遠壓力／兩者皆有，比例及未達標路徑如何？
3. 原突破後 L=20 內越線，相對同時點、同漲幅但未越線者，是否仍較容易達原兩倍目標？

L=10/40 僅固定敏感度，不擇优改主值。只有原 t0 時鐘，期限 t0+126、目標 2×close[t0]；
越線不另建突破事件，不重起半年。不另做可選的 Z1／Z2 站穩分析。
這是擁有者定義的頭頭高／底底高，**不是** Sperandeo 假跌破 2B。

## 啟動狀態：已獲執行授權，機率口徑待確認

v4 來源與交接文字存在近期壓力起點差異；新還原價格结果與原 atlas 的未知语意也須明訂。
擁有者已授權本批測試；這是口徑澄清，不是要求再授權、重新啟動目標或等待補抓資料。
待確認項目及建議已交至
`D:/Project/Stock/.tmp/claude-kline/20261010-codex-v4-definition-questions.md`。
不得用看到的機率選擇解釋。此階段只做移植、合成測試、固定輸入與 25 筆原例來源驗算，
不讀 forward label、不計算市場命中或地標结果。四個口徑確認後以追加段落定案、提交，
才可執行一次固定範圍計算。

## 固定來源與資料

原始完整 bytes 置於 `sources/hhhl_rule_v4.zip`；規則 ID 參數為 `hhhl_rule_v4`。
不改原數學或 source 常數，只把 imports 與檔案輸入綁到已驗證的固定來源／DataFrame。
保留既有 v1 程式、產物、mission 與更正紀錄。

| 原始成員                 | SHA-256                                                          |
| ------------------------ | ---------------------------------------------------------------- |
| hhhl_rule_v4.py          | 6390e5a61519c041a6989257af59599e71ae1c24ba5d6d70c96c5c7ea8f8d5c8 |
| bigrange_v4.py           | 59634879c7e0358b57baa98a2187eb7de928de7df229c3053ba905f91a6dd574 |
| adjprice.py              | cb8d7a53b8362c51292795eefd90e9cdb8353b38fa81695779bf6e7b7fe777ef |
| detect.py                | fba922502f8d34c2c928c7accca9baa17b1e9c83dae8be398b8b4fa773ee8eeb |
| set_b5b.json（驗算來源） | 4cd3eab10b14ee8063b62e3a7e520f5bcbb922f16293896199613876700efc2d |

僅使用 atlas-v2 的 2019-01-02..2026-08-14，原 dataset ID
`fda-86245f2e223fc45c9f84afb0dcf77c1fff7ab22d0a1b0b4a4c8800972ce9327e`。
原產物在 primary `tasks/20261004-feature-discrimination-atlas/datasets/atlas-v2`。
沿用全部原股票與共用日曆，原 `base_eligible` 不換；目前參考股票池、有倖存者限制，
不是歷史 PIT 全上市櫃母體。這是已暴露開發期，不因換 v4 變成獨立確認。

價格由 RawOHLC 與固定 corporate_actions 因子輸入得到；原 OHLC 缺值的 dropna 只用於
偵測器，事件索引映回完整共用日曆。不把有效報價列數稱為連續交易日，不跨缺價補造。
還原價格不是可執行帳戶的現金含息總報酬，亦非實際取得的翻倍獲利。
只讀 SQL 的一致性查詢另存 `inputs`，primary producer、排程及原 atlas 不改。

## 來源驗算與停止條件

先验证 `set_b5b.json` 的 24 筆 kind=rule 在同一日有真 pattern、bonus_levels 為空，
另驗 2527／2023-04-07 有真 pattern、small_range、old bonus 約 20.48。
只投影本次需要的價格、量與资格欄位，不讀市場 forward results。
核對來源與實際消費表的 hash；來源改變、病例不一致、定義未定或執行錯誤，
停止該項計算並保留證據，不能稱候選失敗或私改規則求過。

本階段没有市場結果、没有新策略通過判斷。v4 沒有擁有者盲測；交接的開發資料
85% 涵蓋／54% 同意及有線 6/29、無線 46/67 是 Claude 所報、已暴露，
不冒充本次獨立驗算或新機率結果。

## 後續必交範圍（待口徑固定，不自動開算）

E-clean／E-overhead（old-only、recent_far-only、both）／E-all、X-inside 只報告，
同日新高爆量無任何事件為主要控制、同日無真 pattern 次要控制、全部合格日基準。
cat、limit_up、年度切片分開完整保留；原 atlas label 另欄、同母體比較基礎與不一致原因明示。
63 日 1.5 倍、126 日兩倍、未知上下界、每組每股首筆、同股固定种子日期平移雜訊、
未達標價格路徑、達標等待、三個 L 的同漲幅比較與提前達標／失敗／缺值數皆須交付。
跨事件／跨股票市場相依不能當 IID 推論，不挑最佳組宣稱策略有效。

大表與本次固定輸入保存於 primary `tasks/20261010-hhhl-v4-probability`，不是只留 `.tmp`
或 worktree。Git 保存原 bytes、程式、定義、驗算、全部彙總及查詢路線，索引研究總覽。
不啟動下載、不動帳戶回測／holdout／目標／automation。驗算完成與定義阻塞分開報告。

## 來源驗算完成 — 2026-10-08

18 項合成與舊 v1 回歸通過。25 個原案例全部重現：24 個指定 rule 同日真 pattern 且
bonus 空；2527／2023-04-07 為真 pattern、small_range，old 壓力 20.483011145774455。
原 atlas manifest、實際消費的 25 檔表及固定因子輸入前後身分一致。
來源驗算不讀 forward labels，也沒有 v4 市場翻倍率；下一步仍是四題回覆後追加固定口徑。

## 計算口徑定案（結果前追加，2026-10-08）

Claude 的 `20261010-claude-v4-definition-response.md` 已回覆四題，原 bytes 新存
`sources/definition-response.zip`，原文 SHA-256
`5cfbf3589ce07ef03fd4c2a0cf2f9906430fb4e9e690ddf13db5b471a7253151`。
以下是 **Claude 的事前暫定定義，不是擁有者逐項核准的最終策略門檻**；本批開發期描述
依此執行。此追加取代前文「待確認」與交接原含息總報酬／近期起點的不精確文字，
不覆寫舊 v1 结果、原 atlas 或既有暴露紀錄。

- `leg_start = min(leg[-1], rs)` 保持原程式：最近已確認 4 ATR 低點與 restart 中較早者。
- 主要名稱為「參考價因子還原收盤的翻倍率」。還原的原始有效 OHLC 列映回完整共用日曆，
  被原 loader 丟棄的缺 OHLC 列，其主要 Close 仍缺值；不以部分 RawClose 補造有效列。
  同時保存 atlas 原價格基礎 label（永久事件已調整，未還原現金股息），不改原定義。
  比較例：前收 100、股利 10、參考價 90、除息收 95，還原變動 95/90−1=5.56%，
  股票加現金變動 (95+10)/100−1=5%；兩者不是同一個可執行總報酬。
- 主要 63 日／1.5 倍、126 日／2 倍採首次決定：t0+1 起，在達標之前首個缺／無效收盤
  使 label 未知且不能跨過；先達標則保留 hit，之後缺價／截尾不撤回。完整期限未達標才
  nonhit，未達標且窗不完整則 unknown。anchor 無效亦 unknown。
- 路徑最低／最高漲幅、最大回落與期末漲幅，只有包含 anchor 的完整有效期限才計算。
  min/max 為未來收盤相對 anchor，最大回落為包含 anchor 的 running-peak 正損失比例。
  complete 與 label 已知分開；hit 不保證路徑完整。保存兩種 label 不一致數及原因。
- 原事件 t0 資格沿用 atlas `base_eligible`，不看未来決定入組。第一筆模式先挑各固定組中
  每股最早合格事件，首筆 unknown 不以後來已知者代換。全部股票／未知／負例皆保留。
  完全沒有有效 OHLC 的股票留在覆蓋紀錄；若仍有合格 anchor，停止為量測錯誤。
- 控制依相同還原有效列計算：收盤高於前 20 有效列最高收盤、量 ≥ 前 20 有效列平均的
  1.5 倍，平均量沿用舊比較 `min_periods=1`（最高價需要 20 列）；主控制排除當天任何
  v4 事件，次控制排除任何真 pattern。原則固定，不採未來 ±3 日排除，也不套漲停免量。
- 雜訊對每筆合格 E-all，按股票 ID／突破日穩定排序，以 Random(20261010) 從同股
  ±60 共用日曆內非原日的合格日期均勻取一筆，可重複；無可選日仍保留 unknown。

### 固定地標，不重起算

L=20 主、L=10/40 敏感度。從 t0+1 到 t0+L 依第一個缺價／達原兩倍／收盤嚴格跌破
固定 Z2，記 unknown／early_hit／early_failed；先決定即吸收後續缺價。未發生且完整到 L
才 active。未到 L 且未決定則 unknown。Z2 為原 seq 最後一個 L 的 p，不更新。
僅 active E 進地標比較；t0 資格不因 L 時的新資格再篩。缺价、失敗、提前達標完整報數。

bonus 價位只用原 t0 的 old／recent_far：在 t0+1..t0+L 收盤嚴格大於固定線才算越線，
保留各類第一次越線日；不以未來新增線追認。分 cross_any、cross_old_only、
cross_recent_far_only、cross_both、uncrossed_overhead、clean_reference。
active 比較 pooled 及固定 close[tL]/close[t0] 四區：<1、[1,1.10)、[1.10,1.25)、≥1.25。
不用事後分位數、不合併小格、不挑最佳格。known <30 或 known_securities <10 僅標樣本少。
地標結果只掃 tL+1..原 t0+126，目標仍為 2×close[t0]，適用上述首次決定；L 後跌破 Z2
不終止、不停損。等待同時留原 t0／L 兩種偏移。路徑統計以完整剩餘段收盤相對原 t0、
最大回落包含 L 收盤起點，不當成完整原 126 日路徑或交易損失。

### 比較次數、預算與收尾

固定 E-all／E-clean／E-overhead／old-only／recent_far-only／both／X-inside 七組，
各 pooled、三 cat、兩 limit_up、2019..2026 八年度，共 14 切片，乘兩抽樣、兩期限、
兩價格基礎＝784；雜訊 pooled 同樣兩抽樣／期限／基礎＝8；全部日／兩控制 pooled 加
八年度乘兩期限／基礎＝108。原日起算 **900 格**。地標三 L、六組、pooled 加四漲幅區、
兩抽樣＝**180 格**，僅主要還原基礎／原 126 日期限。總 **1,080 格**，空格照留。
這是描述性多重比較，不作 IID 顯著性、通過線或策略晉級判斷；固定四區仍不是因果配對。

本次只核准一次 `hhhl-v4-descriptive-01`，最多四個確定性 worker、3,600 秒；超時／錯誤
保留未完成 attempt，不當作候選失敗，不自動換參數或重跑。全部 1,941 個原表前後核對
hash、calendar、rows，來源範圍不變。先提交此定義、producer 與合成測試，才讀结果。
完成記錄保存實際日期、commit、消費程式／依賴／原文／因子／manifest 身分，完整事件、
基準、控制、雜訊、地標、覆蓋診斷、十筆固定抽查及全部 1,080 比較；大型表存 primary
task，Git 保留可攜全部彙總、契約／索引與取得路線。來源改變不宣稱一致性完成。
