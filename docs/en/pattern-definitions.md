# 型態定義字典

這是新研究與網站的查找入口，不是核准策略清單。版本與價格基礎都必須明示；「2B」不能單獨充當程式定義。原文日期有交接命名與實際執行日期不同的情形，不能据此推定首次可知時間。

## HHHL：擁有者討論的高過高／底底高

原始 bytes 集中在 [`research_core/patterns/hhhl/`](../../research_core/patterns/hhhl/sources.json)，每版本一個 `sources.zip`；manifest 同時列 ZIP 與各原檔的 SHA256。ZIP 是為了防止 formatter 改掉歷史原始碼，不是只保存文字摘要。舊 task 繼續讀自己的來源 ZIP；不回寫舊結果。

| ID／版本  | 白話規則／差異                                                                                | 價格及可知時點                                          | 批准／驗收狀態                                                                          | 不能互換的名稱／已用研究                                                                                    |
| --------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `HHHL:v1` | 1.5 ATR 轉折形成高低區域；收盤突破最近確認高區，並創前 20 日收盤新高及放量；90 日大區間可阻擋 | 原 atlas 永久事件還原；轉折須在訊號日前已確認           | 依擁有者標註討論形成；batch3 召回未通過，非策略批准                                     | owner HHHL v1，不是 F21/F33；[v1 機率研究](../../tasks/20261009-hhhl-pattern-probability/report.md)         |
| `HHHL:v2` | 保留結構，突破未放量可再等 5 日；大區間改標籤、不再直接阻擋                                   | 原參考因子還原程式；不是含息帳戶報酬                    | batch4 精確率未通過；非正式最終批准                                                     | pending-volume HHHL v2，不可當 v1 的同一規則                                                                |
| `HHHL:v3` | 大尺度較高低點可重啟；漲停免量；加入 4 ATR 實體邊界壓力線、近線阻擋、成交額下限               | 同前；轉折確認日與極值日分開                            | batch5 精確率階段通過，召回尚未定；非完整驗收                                           | drawn-resistance HHHL v3；不代表完整 Wyckoff 或底部假跌破                                                   |
| `HHHL:v4` | 壓力線站上後結束；只由近期且距離近的線阻擋；舊線／遠線另列 bonus                              | 原參考因子還原；`leg_start=min(最近確認大低點,restart)` | 擁有者討論研究方向；四個機率口徑由 Claude 事前暫定，25 原例重現不是新辨識驗收或策略批准 | recent-line HHHL v4；[PR33 原研究](https://github.com/TaiwanCCyoyo/Stock/pull/33)，價格基礎更換必須另列差異 |

每列的完整規則以保存程式為準，摘要不創造新定義。`load_detector("v4")` 明確載入核對過的純偵測函式；不執行原例生成器或 `adjprice` 的 live 讀取。呼叫者必須明示價格政策與 ATR。舊版本可能仍含「total-return」用語，原 bytes 保留，但新的索引不沿用這個錯誤名稱。

## Legacy／文獻代理：不是擁有者 HHHL

| ID    | 實際方法與正本                                                                                                        | 狀態／不能互換的名稱                                       | 結果與關聯                                                                                                                                                                 |
| ----- | --------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `F21` | [`three_session_2b_proxy`](../../research_core/feature_atlas_features.py)：舊支撐、近三日破低、前收在支撐下而本日收復 | 研究代理，非擁有者確認；不是 F33、HHHL 或所有 2B           | [atlas](../../tasks/20261004-feature-discrimination-atlas/report.md)；定義版本與程式身分在原 manifest                                                                      |
| `F33` | [`legacy_bottom_2b`](../../research_core/feature_atlas_legacy.py)：破前 20 日低點後，等待 5 根內後續非新低 K 線收復   | 舊策略元件，非擁有者 HHHL；不含原持倉／出場／部位          | [atlas](../../tasks/20261004-feature-discrimination-atlas/report.md)、[交互比較](../../tasks/20261005-method-environment-interactions/report.md)；失敗不淘汰不同 HHHL 定義 |
| `F20` | [`spring_proxy`](../../research_core/feature_atlas_features.py)：同日低於前 20 日低點，收盤回到其上                   | 當日 spring 代理；不是完整 Wyckoff，不是等待後續收復的 F33 | [atlas](../../tasks/20261004-feature-discrimination-atlas/report.md)                                                                                                       |
| `M04` | [方法來源索引](../../tasks/20261004-method-environment-map/report.md)：spring／假跌破收復的機制                       | 文獻方法 ID，不是可計算旗標，也不是 F20 的同義 ID          | F20 引用其方法來源，不能由某個代理結果宣稱整套理論有效／無效                                                                                                               |

## 新定義與保存

### Pattern-scan v1：尚待mission合併的固定規格

以下均為[完整mission提案](../../tasks/20261013-pattern-scan/mission.md)，
不是已完成偵測器、正式資料或策略批准；各S/L與confirm補充須先merge再市場計算。
2010全期還原價與品質政策有新身份；不改原HHHL/F10/F32/F33來源或結果。
「低過低」尚無獨立owner規格，不默認等同以下任何一列。

| pattern_id／definition | 規則與不能互換之處                                                      | 狀態／t0                                           |
| ---------------------- | ----------------------------------------------------------------------- | -------------------------------------------------- |
| H1／pattern-scan.v1    | 原HHHL v4 pattern，clean/over/union；新2010完整日曆adapter與品質處理    | proposed；原v4等待量／confirm時點，不只是字面HH/HL |
| B1／pattern-scan.v1    | 固定杯柄／無柄，杯深12–35%、柄5–15日及量1.4，有限搜尋／S/L補充見mission | proposed；收盤突破                                 |
| B2／pattern-scan.v1    | BB20收縮前5日＋當日上軌突破，量1.5另子型；不是原F14兩收盤＋前20日       | proposed；單日突破                                 |
| B3／pattern-scan.v1    | 平台25–65日／15%振幅，量1.5，量縮與振幅收斂子型                         | proposed；平台突破                                 |
| B4／pattern-scan.v1    | 2% gap未補、60日close高與量2                                            | proposed；當日收盤                                 |
| R1／pattern-scan.v1    | 60日區間、兩touch、後1–5日收復與二測；不是同日F20或5根F33               | proposed；收復／二测確認                           |
| R2／pattern-scan.v1    | F22–25實際旗標（含原MA前置）＋下跌/近低；下一日確認另子型               | proposed；完成／次日确认                           |
| R3／pattern-scan.v1    | Wilder RSI背離，固定[i−5,i+3]低點＋i+3確認、20日failure-swing           | proposed；不是1.5ATR pivot                         |
| P1／pattern-scan.v1    | 60日突破後3–20日回測，再1–5日突破前High，保留b配對控制                  | proposed；等待確認                                 |
| L1／pattern-scan.v1    | 原F10 close>前60日High；事件metadata/cooldown另版                       | proposed；原flag當日                               |
| L2／pattern-scan.v1    | 原F32 close>MA60且ret5<0；S/L補充不改原flag                             | proposed；原flag當日                               |
| L3／pattern-scan.v1    | 原F33後續非新低收復；新增pending/S/L metadata須逐日parity               | proposed；不是新owner「低過低」                    |

新增版本須保留父版本、差異、原始來源／hash、批准證據、正反例及 `known_at`；未核准標註不能改成擁有者確認。過去期間暴露與比較次數仍沿用原紀錄，不因改名或共用快取變成未見樣本。完整 owner 標註匯出由 Claude 的獨立 task 交付；這裡的 25 原例不是那批標註的替代品。
