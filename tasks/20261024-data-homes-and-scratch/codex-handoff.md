# Codex handoff: data homes, study cards, data status, PR17 rerun

> **狀態：未完成。** 這份交接列出四個工作包，目前都還沒開始做。
> 「已合併的 PR」不等於「研究完成」，也不等於「成果已交付」；每個狀態的定義以
> [交付狀態](../../docs/en/research-program.md#delivery-states)為準。

背景與規則見[決策紀錄](../../docs/en/decision-records/2026-10-24-data-homes-and-scratch.md)，
開始前先讀 AGENTS.md 和 `docs/en/git-workflow.md`。四個工作包要分別開 PR，每個 PR 都從最新的
`origin/main` 開分支，並各自使用 `.worktrees/` 下的 worktree。

## 開工順序

| 工作包                 | 前置條件                | 可以平行嗎                   |
| ---------------------- | ----------------------- | ---------------------------- |
| A. 研究卡片            | PR #66 已合併           | 可以和 B、C 平行             |
| B. 研究資料搬出 repo   | PR #66 已合併           | 可以；但動手刪除前要等 owner |
| C. 資料狀態檔          | 無                      | 可以                         |
| D. PR17 續跑程式與重跑 | PR #64 和 PR #66 已合併 | 程式修改可以；重跑要等 A     |

所有工作包都要遵守：

- 不覆寫、不刪除既有資料。固定 SHA 的報告和證據一個位元組都不改。舊打包檔只能讀。
- 平日 18:00–18:45，以及任何 `StockProject-*` 排程執行中，都不讀 producer。
- 長時間計算一律用 `research_core/scratch_runs.py` 建立 run；不要寫到 worktree 的 `.tmp/`。
- 只能終止自己啟動的 PID。不要用 `taskkill /IM python.exe`。
- 網站上看得到的文字不出現版本、雜湊、task ID、「快照」「世代」這類字眼。

---

## A. 研究卡片（study.json v2）

**目標：** 網站的研究頁只讀每個 task 的 `study.json`。Dashboard session 會在前端接上；
這個工作包負責後端和資料。

格式以 [`study-card-v2.schema.json`](study-card-v2.schema.json) 為準，範例在
[`study-card-v2-examples/`](study-card-v2-examples/)。欄位語意已和 dashboard session 對齊：verdict
只能用 7 個值；技術資訊只放在 `provenance`；`progress` 不存在卡片裡，由 API 合併。

1. **讀取端** `research_core/study_cards.py`：
    - 用 schema 驗證每一份 `tasks/*/study.json`。
    - 檢查 `task_id` 等於所在資料夾名稱。
    - 檢查 `report` 的路徑在該 task 資料夾內，且檔案存在。
    - `provenance.answer_source` 和每個 `key_numbers[].source_excerpt`，必須是報告原文中連續的一段文字。
      舊研究改成比對打包檔 `researchHistory` 裡同一個 id 的原文。
    - `provenance.report_sha256` 有值時，比對報告目前的 SHA-256；不符就讓這張卡回傳 warning，不要讓整個 API 失敗。
    - `scratch_run` 有值時，用 `scratch_runs.read_run()` 讀 `<shared root>/scratch/<task_id>/<run>/run.json`，
      把 `progress` 和 run 的狀態合併進回應。讀不到時回傳 warning，不要讓 API 失敗。
2. **API**：在 `research_api/` 加 `GET /studies`，回傳 `{cards: [...], warnings: [...]}`。
   預設不回傳 `kind=tooling` 的卡片，加 `?include_tooling=1` 時才回傳。路由依照 `research_api/history.py`
   的寫法掛載，並沿用相同的模式檢查（private／public-synthetic）。
3. **示範資料**：public-synthetic 模式要回傳一組虛構卡片，至少涵蓋四種情況：已完成、執行中帶進度、開發工作、
   舊帳戶模擬。內容必須明顯是虛構的，不要用真實數字。
4. **補登**：替每個 `tasks/<id>/`（目前 77 個資料夾）寫一份 `study.json`。
    - 來源依序是：該 task 的 `presentation.json`（5 份）→ 打包檔 `researchHistory`（53 筆）→
      `research_result.json`／`report.md`。
    - 開發類工作標成 `kind: "tooling"`，例如 `*-ux`、`*-architecture`、`*-studio`、`*-separation`、
      `*-handoff`、`*-preview`、`*-dryrun`。判斷不了就列進 PR 描述，請 owner 決定，不要猜。
    - `question`、`answer`、`limitation` 用白話寫；但每一句都要能在 `answer_source` 或報告裡找到依據。
      報告裡沒有原文數字，就讓 `key_numbers` 留空。
    - 舊的兩個帳戶模擬寫入 `account_run`，run id 分別是 `stock:20261002-add-retry:normal-v1`
      和 `stock:20261002-entry-extension-cap:cap-v1`，`period_note` 一律寫「帳戶模擬 2019–2023（舊資料）」。
    - `20261010-hhhl-v4-probability` 現在顯示「登錄需更新」（v1 登錄的 SHA 和報告不符）。新卡片用報告目前的 SHA；
      不要改報告，`presentation.json` 也保持原樣。
    - `presentation.json` 和舊打包檔都不要刪、也不要改；它們留作來源。
    - `20261013-pattern-scan` 寫成 `verdict: "running"`、`delivery_state: "code_merged"`，`scratch_run` 先填 `null`，
      等工作包 D 建好 run 再補上。
5. **文件**：更新 `docs/en/study-presentation.md`，說明 v2 是新的登錄方式、v1 保留可讀；`research-program.md` 的
   「收尾條件」改成要求 `study.json`（這段在 PR #64 合併後才能改）。
6. **驗收**：
    - 新增測試：schema 驗證、原文比對、SHA 不符時回傳 warning、scratch 進度合併、示範模式。
    - 列出每個 task 的卡片來源，以及標成 tooling 的清單，附在 PR 描述。
    - 本機啟動網站，確認 `GET /studies` 回傳 77 張卡片、`warnings` 的內容可以解釋。
    - 完成後通知 dashboard session：`GET /studies` 已可用，以及欄位有沒有變動。

## B. 研究資料搬出 repo

**目標：** 把 `research_data/`（約 1.2 GB）搬到 `D:/StockData/stock-research/catalog/`，把
`StockProject/data/private-presentation/`（約 30 MB）搬到 `D:/StockData/stock-research/archive/`。

先知道會卡住的地方：

- `research_core/research_data_paths.py::DataRoots` 規定資料根目錄**必須叫 `research_data`，而且直接位於
  primary checkout 底下**。所以要先改程式，讓它接受 repo 外、位於 `shared_data_root()` 底下的 `catalog/`。
  同一套連結和 junction 檢查要保留，並增加一條：拒絕任何 worktree 內的路徑。
- catalog 裡 `scope: "primary"` 的項目指向 primary checkout 的 `tasks/` 和 `research_cache/`。這些是固定證據，
  **原地保留不搬**，`DataRoots` 仍然要能找到 primary checkout。
- `.env.local` 的 `STOCK_RESEARCH_DATA_ROOT`、`STOCK_PRIVATE_ARTIFACT_ROOT`、`STOCK_SAVED_STUDIO_PACKAGE` 要改指向新位置。
  這個檔案是 owner 的本機設定：改之前先備份成 `.env.local.bak-20261024`，改完在 PR 描述列出改了哪幾行。

步驟：

1. 改程式和測試。必須包含實際在 Windows 上刪除的測試，以及 junction 測試。
2. **複製**到新位置，不要搬移。逐檔比對大小與 SHA-256，比對報告存成 `catalog/MIGRATION-20261024.json`。
3. 切換 `.env.local`，執行 `uv run python scripts/start_research_web.py --check`，再
   `uv run python -m scripts.verify_published_artifacts`，兩者都要和切換前的結果一致。
4. 舊位置**保留**。在 PR 描述請 owner 同意刪除；owner 同意之前不准刪。
5. 更新 AGENTS.md「Owner update 2026-10-12」那一行、`stock-agent-operations.md` 的 Data And Worktrees、
   `tasks/20261012-research-data-entry/data-contract.md`，以及 `research_web/README.md` 的設定說明。

## C. 資料狀態檔（給「資料總覽」頁）

**目標：** Dashboard 不在讀頁面的當下查資料庫，改讀事先寫好的小檔，知道這台電腦上有哪些資料。

1. **Producer 端（submodule 獨立 PR）**：`run_daily.py` 每次跑完寫一份 `data-status.json`，放在 producer 資料根目錄。
    - 每個資料集一筆：`id`、`name`（白話中文）、`data_period {from, to}`、`last_updated`、`symbols`、`rows`、
      `status`（`ok | stale | missing`）。
    - 至少涵蓋：每日股價（official_daily）、`price_daily.parquet`、三大法人、月營收、除權息、股票名稱與產業。
    - 依 [submodule 交付流程](../../docs/en/stock-agent-operations.md#submodule-development-and-delivery)，
      先在 producer repo 開 PR，合併後再更新本 repo 的 gitlink。
    - 寫入要原子化（先寫暫存檔再 `os.replace`）。不要改動既有資料表。
2. **Research 端**：`GET /data-status` 合併三個來源：
    - producer 的 `data-status.json`；
    - 每個共用衍生資料的 `derived/<family>/current.json` 與 status；
    - catalog 的資料包。
      在 18:00–18:45 或排程執行中，回傳 `status: "updating"`，不要回傳錯誤。
      名稱一律用白話中文，不要包含路徑或雜湊。
3. **K 線疊圖的資料端點**：先量測 `institutional.sqlite`、`monthly_revenue.sqlite` 的起始年、粒度和缺漏，
   寫進 PR 描述，再提出端點設計：法人用日資料、月營收用月資料，都只讀不算。端點由這個工作包實作，
   前端畫面歸 dashboard session。完成後通知它端點與可用年份。

## D. PR17 續跑程式修改與重跑

**目標：** Pattern-scan Q2–Q6 剩下的 10 個家族照新規則跑完。

逐項規格以 [`tasks/20261013-pattern-scan/rerun-handoff-q2-q6.md`](../20261013-pattern-scan/rerun-handoff-q2-q6.md)
（PR #64）為準；那份文件原本把程式修改分給 Claude，現在改由 Codex 一起處理。以下是補充與更正：

1. **程式修改 PR**，涉及 `research_core/pattern_scan_local_remaining_v5.py` 和 `scripts/run_pattern_scan_remaining.py`：
    - 輸出可以寫到 `scratch_runs.create_run()`／`open_run()` 給的 `run.path`，不再限定 checkout 的 `.tmp/`。
    - CLI 整段執行要放在 `with scratch_runs.open_run(...)` 裡，持有鎖。每完成一組就呼叫
      `heartbeat(progress={"step": 已完成組數, "total": 總組數, "label": "<家族> conditions"})`，
      讓 dashboard 看得到進度。
    - `progress.json` 的身分比對只看 `source_id`、`input_id`。
    - 收據改用 `results` 的相對路徑鍵接到目前 phase 根目錄來重新定位最終表，保留分組子目錄（例如 `pattern%3Aunion-h126/...summary.parquet`），不能只取檔名；再用 SHA-256 驗證。
    - 接受複製過來的 `.phase-start-*.json`（v5），保留原本的 `code`，把新的 commit 追加到 `execution_codes`。
    - 不要在全部家族完成時自動 `release` hold。
    - DEFINITION 維持 v5，因為計算內容沒變；舊收據不改寫。
2. **建立 run**時，把原始輸入登記成依賴，不要複製：

    ```python
    scratch_runs.create_run(
        "20261013-pattern-scan", "q2-q6-v6",
        purpose="PR17 Q2-Q6 remaining families", owner="codex",
        depends_on=["D:/Project/stock-research/.tmp/pattern-scan-execution/full-2010-20261016-retention-v3"],
    )
    ```

    `run.json` 的狀態只有 `running → complete → delivered`。rerun handoff 第 4 步第 2 點寫的
    「從程式合併開始」是 task 層級的狀態，不是 run 的狀態。

3. **複製**（不是搬移）B1/H1 最終表、五個家族已完成的分組，以及各家族的 `.phase-start-*.json` 到 run 目錄，
   逐檔比對 SHA-256。不要複製 `_temporary/`，也不要複製舊的頂層 `progress.json`。
4. 用單一程序依序跑，總共約 6 天，中斷後用同一個 run 繼續。開跑後把 `20261013-pattern-scan/study.json` 的
   `scratch_run` 補成 `{"run": "q2-q6-v6"}`。
5. 全部完成後：
    - `mark("complete")`。
    - 把最終表複製到 `D:/StockData/stock-research/tasks/20261013-pattern-scan/q2-q6/`，收據進 Git，更新報告與
      `study.json`（`verdict` 依報告結論填、`delivery_state: "delivered"`）。
    - 以上都合併後，才執行 `maintain_adjusted_daily release --holder pr17-pattern-scan`，再用
      `uv run python -m scripts.scratch_runs mark 20261013-pattern-scan q2-q6-v6 --state delivered --result <各成果路徑>`
      標成已交付。
6. 刪除 `pr17-retention-review` worktree、primary 的 `.tmp/pattern-scan-execution/`，以及舊位置的暫存之前，
   都要先取得 owner 同意。scratch run 標成 delivered 之後可以用 `scratch_runs clean --apply` 清掉。

## 回報

每個工作包完成時，在 PR 描述寫：做了什麼、怎麼驗證（附輸出）、哪些沒做與原因、需要 owner 決定的事。
不要在 PR 描述或任何文件裡，把未完成的研究寫成「已完成」。
