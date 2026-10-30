# 修正：前瞻紀錄的存放位置（2026-10-31）

**類型：** 營運修正，只改存放位置。owner 於 2026-10-31 同意。
**不改：** 判定規則、樣本分組、`cohort.json` 的起訖日、準時／補記的定義、欄位與檔案格式、評估方法。
**寫這份修正時沒看過：** 任何日檔的 hit／loss 或報酬欄位。只看了目錄大小（12 個日檔、約 1.5 MB）和 `attempts.jsonl` 的 outcome。

## 改什麼

|      | 原本（mission「位置與凍結」）                                            | 修正後                                                                                                                                       |
| ---- | ------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 目錄 | primary checkout 的 `tasks/20261021-momentum-only-doubling/forward-log/` | 研究資料根目錄 `<STOCK_RESEARCH_SHARED_ROOT>/tasks/20261021-momentum-only-doubling/forward-log/`（本機是 `D:/StockData/stock-research/...`） |
| 交付 | 每月經 task branch／PR 把日檔提交進 repository                           | repository 不再收日檔，只保留 mission、資料契約和這份修正；日檔一直留在資料根目錄                                                            |
| 排程 | `StockResearch-MomentumForwardLog` 寫入 checkout 內                      | 排程指令不變，程式預設寫到新位置                                                                                                             |

## 為什麼改

- 原本的目錄要等每月交付才進 git，這段時間是**未追蹤**檔案：
    - main 的 `git status` 一直顯示 `?? .../forward-log/`，其他 session 容易把它當成可刪的暫存；
    - `git clean -fdx` 這類清理也會把它刪掉；
    - 而它是確認期唯一的一份資料。
- owner 2026-10-24 的決定（[資料的三個家](../../../docs/en/decision-records/2026-10-24-data-homes-and-scratch.md)）把持續累積的研究結果放在研究資料根目錄的 `tasks/<id>/`，不放在任何 checkout 裡。前瞻紀錄是在這之前建立的，這次是補上對齊。

## 怎麼搬

- **自動搬：** 新版程式第一次執行時，把舊目錄每個檔案以「驗證過才發布、不覆寫」的方式複製到新位置，複製前後比對 SHA-256。
- **再次執行：** 已存在的檔案必須逐位元相同；`attempts.jsonl` 只能比舊檔更長，舊檔內容必須是它的開頭。任何不一致都會讓程式停下、不做紀錄，等人處理。
- **舊目錄：** 不改、不刪，等 owner 另外同意後才清理。
- **時間：** 搬遷在 09:00 以後、21:00 以前進行，避開紀錄器等待資料的時段。

## 對判讀的影響

沒有影響。檔案內容逐位元不變，`recorded_at_utc`、`generation`、`code_commit`、`recorded_late` 都保留原值；
確認期的缺漏仍依 `cohort.json` 的 `confirmatory_start`～`confirmatory_end` 計算。
