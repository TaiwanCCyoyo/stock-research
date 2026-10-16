# 年度冠軍輪動：HTML 報告契約與放置盤點

盤點日期：2026-10-16。這是既有 PR #15 結果的閱讀版，不是新實驗；觀測終點仍為
2026-10-12。原有 mission、報告、結果與凍結資料均不改寫。

## 報告保存與使用

- 入口是本目錄的 `index.html`。直接從磁碟開啟即可閱讀，也由網站的
  `/#reports` 自動列出；正式網站需重新 build 才會包含新增報告。
- `index.html`、本報告樣式與 `kit/` 都進 Git。沒有原始行情、完整每日持倉路徑、
  私有展示包、主機絕對路徑或瀏覽器呼叫研究資料 API 的需求。
- `kit/` 是 `research_web/report-kit/v1/` 的原樣副本，依既有報告契約固定外觀，
  不是另一套共用元件。上游 kit 的字型下載不可用時使用系統字型。
- 數字只轉載同一 task 的 `report.md` 與 `research_result.json`。完整年度與
  2026 YTD 分開；七個未知年度不補成零、不串接已知年度為完整財富曲線。
- 這一組小型文字檔適合 Git 備份，能保存本頁結論與閱讀外觀；**不代表 Git 已保存
  本研究的全部輸入、完整結果定位檔，或足以從乾淨 clone 重跑研究**。

正式來源為 [PR #15](https://github.com/TaiwanCCyoyo/stock-research/pull/15) 的
[文字報告](https://github.com/TaiwanCCyoyo/stock-research/blob/4706cc4b26ba77e1c6d059adb307173d059f9194/tasks/20261013-annual-winner-rotation/report.md)、
[研究契約](https://github.com/TaiwanCCyoyo/stock-research/blob/4706cc4b26ba77e1c6d059adb307173d059f9194/tasks/20261013-annual-winner-rotation/mission.md) 與
[機器結論](https://github.com/TaiwanCCyoyo/stock-research/blob/4706cc4b26ba77e1c6d059adb307173d059f9194/tasks/20261013-annual-winner-rotation/research_result.json)。
HTML 是其展示投影，不取代正式驗證入口。

## 目前資料與程式放在哪裡

下表記錄既有狀態，不授權搬移、刪除、重新發布或重算。短版本前綴只供人工查找；
不是完整 pin 或完整性證明。正式版本從 primary 的 `research_data/catalog.json` 定位。

| 內容                                   | 正式位置                                                                                                                     | Git／備份方式                    | 判斷                                                              |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | -------------------------------- | ----------------------------------------------------------------- |
| 研究問題、規則、結論、資料限制         | `tasks/20261013-annual-winner-rotation/` 的 mission、report、data-contract、verification、research_result 與 params/study-v1 | Git                              | 研究專屬紀錄，位置正確                                            |
| 共用經濟計算、年度排名、統計與發布驗證 | `research_core/annual_rotation.py`、`annual_ranking_pool.py`、`annual_statistics.py`、`annual_publication.py`                | Git；測試在 `scripts/tests/`     | 已放共用程式庫，沒有把這些算法留在某個報告或 task 私有函式裡      |
| 這次研究自己的執行、歷史格式化入口     | task 內的 `run_study.py`、`finalize_delivery.py`                                                                             | Git                              | 一次性入口可留 task；不是新研究的通用模板                         |
| 舊版凍結輸入                           | primary `research_data/prices/annual-rotation-inputs/de7a91ec…/`                                                             | 共用 catalog 與獨立資料備份      | 是歷史研究輸入，保留原位；不是新的維護中衍生家族                  |
| 原始／審查後的候選、持有路徑與結果     | primary `research_data/episodes/annual-rotation-process/463b9f10…/`、`256e51aa…/`                                            | 共用 catalog 與獨立資料備份      | 兩版有明確血緣；報告使用審查後結果，不另複製進 worktree           |
| 歷史原件、格式化副本與交付收據         | primary `research_data/episodes/annual-rotation-delivery/1f66442e…/`、`62999248…/`、`7293ac31…/`                             | 共用 catalog 與獨立資料備份      | 有意保留的舊證據；不是應自動去重的雜檔，也不再新增 delivery-vN    |
| 本 HTML 與其固定外觀                   | `tasks/20261013-annual-winner-rotation/web-report/`；共用 kit 原本在 `research_web/report-kit/v1/`                           | Git                              | 補齊這次缺少的展示交付；網站只收集，不重新計算                    |
| 持續更新的原始行情                     | `D:/StockData/stock-data-downloader`，經 `producer_data_root()`                                                              | producer 的來源備份              | repo 外的正式擷取資料，研究唯讀；不是本次舊輸入的替代品           |
| 維護中的共用衍生價格                   | `D:/StockData/stock-research/derived/adjusted-daily-v1/`，經 `shared_data_root()`                                            | 可重建的維護中家族，研究記錄世代 | 與歷史 study bundles 分層；不能因搬到此處就替換 v1 的經濟報酬模型 |

年度研究的 catalog 目前登記一個 input、兩個 process、三個 delivery；狀態均為
`partial`。本次盤點只核對來源、catalog 與 manifest 清單，沒有重新驗證全部資料的
SHA-256，也不宣稱現有備份已逐位元覆蓋每個最新版本。

其他研究沿用同一責任界線：救回的歷史地圖在
`research_data/patterns/opportunity-history-web/`；已登記的舊 HHHL study datasets
仍可保留在 `tasks/<task-id>/datasets/`。這些固定成果與 repo 外維護中的衍生資料
不是同一種資料，不能只為了路徑一致而搬移或改寫。

## 仍需知道的交付缺口

1. **可讀結論已在 Git，完整重跑定位資訊仍未交付。** task 本身沒有被追蹤的
   `input-pin-v1.json`、`measurement-v2.json`、`sweep_results.json` 或 delivery pins；
   既有報告已標明 local-only。共用 catalog 中有資料，不等於乾淨 clone 能直接重跑。
   本次 HTML 不增加 checksum 例外、不改 secret scanner，也不以短前綴冒充正式 pin。
2. **v2 還是草案。** `holding-policy-v2.md` 不是已完成結果；其舊輸入封存流程早於
   PR #20 的 live-input fingerprint 決策。若日後接續，先另行核准新執行契約，不能
   把舊 prepare／seeder 範例直接當作目前流程。
3. **補證不等於已交付資料。** `data-gaps.md` 記錄的 producer 暫存補證未納入 v1
   結果，catalog 沒有相應的正式 supplement 項目；本次未確認那些暫存檔仍存在，
   不把它們當作可用的共用資產。
4. **研究歷程仍使用展示包。** 本 HTML 會出現在報告庫；首頁近期研究與研究歷程的
   舊 package 讀取方式未在本次改動，不能推定它們會同步出現新報告。

整體判斷：年度研究的共用算法與資料分層已有正式位置。主要缺口是展示與定位資訊
交付不完整，而非需要再建一套資料庫、搬動舊證據，或在每個實驗複製共用算法。
