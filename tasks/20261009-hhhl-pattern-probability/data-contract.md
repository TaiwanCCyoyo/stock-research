# hhhl-probability.v1 — 暫定描述性事件與結果

> Current public-export availability (2026-10-09): source-data packages containing
> real quote vectors, anchor-close samples or corporate-action factors are retained
> locally, not distributed in the public repository. Historical receipts and fixed
> hashes retain their original identity. The 0050 context cannot be activated without
> its complete original input package; readers fail closed and do not download or
> recompute missing data. See [the bootstrap availability record](../../docs/en/bootstrap-stock-research.md#public-export-availability).

此任務消費既有 atlas-v2，不產生新的市場價格／前瞻標籤；原型態 v1 沒通過擁有者
涵蓋率驗收。本版採 mission 末段的事前暫定定義，包含 breakthrough 及 Z1/Z2
站穩／失敗的真正起算日；先前準備提交未計算市場結果，沒有舊結果被改寫。

## 來源、取得與重算

- 規則原始 bytes：本任務 `sources/hhhl_rule_v1.zip`，內含原樣的 `hhhl_rule_v1.py` 與 `detect.py`；載入前核對各成員的 SHA-256。
  [mission](mission.md) 記錄原 SHA-256。正常 Python adapter 只重綁 import seam。
- 原資料：`D:/Project/Stock/tasks/20261004-feature-discrimination-atlas/datasets/atlas-v2`，
  完整 schema／缺值／公司事件定義沿用 [原資料契約](../20261004-feature-discrimination-atlas/data-contract.md)。
  不用最新 producer 快取替换。完整输入 manifest 驗算後使用；期間不擴張。
- 結果保存：primary `D:/Project/Stock/tasks/20261009-hhhl-pattern-probability/datasets/<run-id>/`。
  Parquet 被 Git 忽略；本機實體、非 junction、非災難備份，新 clone 無法取得。
  Git 保存 sources、adapter、此契約、報告及 `publication-v1/bundle.zip` 全彙總。
- Producer：`scripts/build_hhhl_probability.py`；consumer：本研究報告、其他 session 的
  pandas/Parquet 讀者。尚無網站接入或策略整合。維護責任是 Stock research_core，不是行情下載端。

```powershell
uv run python -m scripts.validate_hhhl_rule_source --dataset D:/Project/Stock/tasks/20261004-feature-discrimination-atlas/datasets/atlas-v2 --sources tasks/20261009-hhhl-pattern-probability/sources --cases tasks/20261009-hhhl-pattern-probability/sources/validation-cases.json
uv run python -m scripts.build_hhhl_probability --dataset D:/Project/Stock/tasks/20261004-feature-discrimination-atlas/datasets/atlas-v2 --task-root tasks/20261009-hhhl-pattern-probability --output D:/Project/Stock/tasks/20261009-hhhl-pattern-probability/datasets/EXPLICIT_NEW_RUN --rule hhhl_rule_v1 --workers 4
```

只在固定 mission、移植驗算及必要測試完成後手動執行一次；原 run 不覆盖。
沒有自動 phase advance、下載或帳戶模擬。Z1/Z2 的定義是 Claude 暫定選擇，不是最終驗收規則。

## 表與關聯

| 產物                 | 主鍵／語意                                                                                                                          |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| events.parquet       | event_id = rule + security + 突破日；包含真 pattern 與 inside；每个高區最多一次                                                     |
| controls.parquet     | security_id + asof_date，爆量新高但無真 pattern；no_event 另標完全無 detector 事件                                                  |
| noise.parquet        | event_id 關聯原 base-eligible 真 pattern，固定種子同股票 ±60 共用日曆偏移，不依未來選日期                                           |
| transitions.parquet  | event_id + zone_name；每突破各兩列，status 含 stood/failed/unresolved/unknown_missing_close/unknown_window_end；只有前兩者有 anchor |
| summaries.json       | family、slice、value、sampling、horizon；所有預定格子含空格，非獨立樣本檢驗                                                         |
| audit-sample.parquet | code/日期排序之前十筆合格真 pattern，不挑贏家；重用起算日原標籤及路徑                                                               |
| manifest.json        | 一層完成紀錄，來源身分、程式／契約／環境、檔案 bytes/hash；不是新密封期間或交易證據                                                 |

`security_id=TW:<code>`；`asof_date/anchor_date/breakout_date` 為台灣觀察日，非歷史
發布時間證明。`calendar_index` 指完整 atlas 日曆；`detector_index` 是刪缺 OHLC
後的原 v1 有效報價索引，兩者不可混用。每個 event 的 seq 保存原 pivot 價格、
關係与映回的日期；`restart_date` 是原規則重啟，不是事後挑最低價。

`cat/context/pattern/vx/hz_top/Z2` 依原規則；Z2 固定為突破前已確認 seq 最後 L。
價格是永久公司因子重述之新臺幣，不是 raw 可成交價或含息收益；vx 是成交量（張）
相對前 20 個有效報價觀察均量倍數。沒有改以成交值代理或再做因子校正。

`structure_cash_dividend` 記 restart 到突破含端點的 CASH_DIVIDEND /
EX_RIGHT_AND_DIVIDEND；`structure_missing_ohlc` 是這段完整日曆缺 OHLC 的點數。
不 silently 排掉跨缺口事件。除息敏感版只是固定排除 tagged 事件，不宣稱解决所有
除息／未收錄事件偏差。前後公司因子与 current industry 仍不是完整 PIT 證明。

## 結果／未知與數字

所有 `label_63/126`、`complete_*`、`unknown_reason_*`、`max/min/forward_return_*`、
`max_drawdown_*`、`wait_to_threshold_*` 按 **anchor 日**原樣引用；h=63 為 1.5倍，
h=126 為 2倍，搜尋從 anchor 後開始。完整觀察條件下才有二元 label；null 不是 0。
報酬／價格回落是 fraction，drawdown 是正下降 fraction，等待为共用日曆觀察數。
這些不是有本金／成本的實際交易、損失預算或帳戶回撤。

先 base_eligible 再 label-known。summaries 中 unknown 只含 eligible 缺結果，
ineligible 另列，不能塞進失敗分母；rate=hits/known。未知下／上界依 eligible
全集分別全不達標／全達標，非信賴區間，也不包括未出現在股票清單的公司。
每股首筆按 eligible 起算順序取、再檢 label-known；第一筆未知不替換成後來已知。

lift 使用相同股票／期間、同起算年度的全部合格股票日及固定控制條件。
候選的事件抽樣与 baseline 股票日權重不同；cat/context 不存在於普通股票日，
所以這两種切片只與同一全窗 baseline 比，不稱同 category 市場基準。
有高度重疊与共同市場相依，不能解讀為未來已校準機率／統計策略證明。

## 狀態機欄位與保存限制

`zone_name` 為 z1/z2，zone_value 固定；anchor_index 是完整日曆 u 或 f，
first_low_index / first_low_confirm_index 為 i/cf。threshold 是 t..i 最高收盤。
confirmation_day_excluded 是仍未失敗／缺價時，cf 已過門檻但嚴格翌日規則不准當天站穩；
不等於比較另一規則的完整績效。wait_to_transition 是 anchor-t 的共用日曆觀察數。
transition_cash_dividend 標 t..anchor 含端點的除息，無 anchor 則 null。
狀態判斷不是交易成交或反映低點 extreme 當天已知；必須等 cf 才使用低點。

transitions 中 KEY／OUTCOME 欄位一律取真正 anchor；無 anchor 時為 null，
security_id、事件結構及 breakout_base_eligible 仍保存。狀態 unknown 不等於
anchor 未來結果 unknown；前者沒有起算日，後者有起算日但未來結果不完整。
兩者在 manifest 狀態計數及機率彙總分開報告，不拿它們充作零。

主要 high_volume_no_event 與次要 high_volume_no_pattern 都只看當天，沒有 ±3 選樣。
558 個固定彙總包含零事件格，沒有複合格／參數掃描；YEAR 依各組真正 anchor。

本次僅保留 2019-01-02..2026-08-14 原已暴露視窗；未重建消失股票、historical
產業、raw 可執行交易或含息權益。規則 v1 未過盲測，後續 v2 應新來源／mission／run。
mission 末段記錄 Claude 追加回覆與雜湊，取代早先站穩待定記錄。
後續規則更改須新來源／mission／run，不能只靠聊天或 tmp 回覆替換保存結果。

## 完成產物與可攜查詢 — 2026-10-08，結果後追加

唯一完成 run：`hhhl-v1-descriptive-02`，code_commit
`35bd7778cda505f827b056f5666fb22ca178b9bf`；46,868 事件、93,736 轉態、558 格。
`hhhl-v1-descriptive-01` 未完成紀錄仍保存，不是另一個科學比較。
當次 mission／契約／程式／uv.lock／規則 ZIP 共八個 declared-input 快照已保留；
這段結果後 availability 記錄不是原封存規則，原契約 bytes 在包內 inputs。

[可攜 manifest](publication-v1/manifest.json) 指定 ZIP bytes/hash 及每個成員雜湊；
`bundle.zip` 含全部彙總、十筆抽查、原及更正 manifest、八個輸入快照。
其他 session / 新 clone 不需下載資料就可讀彙總，無須網站或新增查詢服務。

```python
import json
from pathlib import Path
from zipfile import ZipFile

root = Path("tasks/20261009-hhhl-pattern-probability/publication-v1")
with ZipFile(root / "bundle.zip") as package:
    summaries = json.loads(package.read("outputs/summaries.json"))
    completion = json.loads(package.read("outputs/manifest-corrected.json"))
result = [
    row for row in summaries
    if row["family"] == "pattern" and row["slice"] == "pooled"
    and row["horizon"] == 126 and row["sampling"] == "all_events"
]
print(result)
```

取逐筆表需上述 primary canonical run 的實體 Parquet，或取得相應物理快照並核對
completion.artifacts；大表與原 atlas 不在 Git。來源快照不是整個環境，完整重算仍需
該 code_commit 其餘 repo helpers、相應依賴及同一 atlas-v2，不聲稱 standalone replay。

**metadata 更正：** 原 manifest inventory 錯含起跑 placeholder 的自身 hash；
原檔保留，新增 `manifest-corrected.json` 明確綁定原 manifest SHA-256，只移除該 entry。
以更正檔驗證六個科學產物，非直接信任原 self-entry。六檔未變／通過核對；
完整原因與原 entry 見 [execution](execution.md)。未來 producer 改用 attempt.json
作起跑狀態；沒有為修此 metadata 重跑市場、改規則或覆蓋原數據。
