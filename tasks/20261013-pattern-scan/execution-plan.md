# Pattern-scan 執行順序與邊界

本次只有mission準備與純合成 helper；市場計算需本mission owner merge。
沿用已保留的 D:/Project/stock-research/.worktrees/research-data-entry，
新branch codex/pattern-scan-mission從origin/main 061cde2開始，原PR12分支與producer
實體快照均保留。沒有新建worktree、沒有修改primary分支或producer。

1. 準備：核對handoff bytes；盤點7個catalog版本與每項缺口；收錄全部定義、
   未決事項、輸出、comparison上限；驗raw日期鍵／Code/Source projection而非OHLC結果。
   保存本次價格及4種metadata/action實體快照，不覆寫舊seed。
2. mission PR：交此設計、new-version純helper、合成測試與input observation pins。
   H1=v4／L3=F33依原handoff固定；另加「低過低」才需新定義。owner review／merge
   最後mission文字才核准計算，CI/review綠燈不自動啟動研究。
3. merge後從最新main接續同task checkout；實作每個detector/condition adapter、
   支持2010的統計、fresh-source thin runner、結果schemas與讀取／validation。
   重用price_basis／feature blocks／worker pool／HHHL public APIs；不import script private helper。
4. 執行前完成全pattern synthetic cases及no-future-read、parity、missing、controls、barriers。
   先正常formatter／hooks，再固定實際raw bytes與source dependency hashes、runtime/environment。
   從public source ZIP驗 HHHL來源。新增runner不能依賴舊atlas load_snapshot的2019常數、
   FrozenInputs原calendar或RateAccumulator舊YEARS。
5. 將fixed mutable input bundle verified-copy到primary本task inputs的new immutable版本，
   保存全部sources／各SQLite交易快照身份與sidecar檢查。source／snapshot不符則停止；
   不重新seed／覆寫producer、不用live fallback。確認現在的canonical writer／schedule狀態，
   不把既有18:00–18:45時段記憶當writer-idle證據，不暫停／重設排程。
6. 成本量測：先依2,076 raw code、4,110 calendar rows估每phase需求，
   common eligible數仍unknown。合併mission後用代表分層股票（長歷史、新上市、gap、
   action、短尾）量stock-independent phases，serial對1/2/4 worker（max4，
   in-flight≤worker）。比輸出身份／exact integer aggregation相等；測wall、CPU、
   peak RSS、read/write bytes、serialization與startup。可用memory減去至少4GiB
   host reserve，parallel cap≤8GiB；實際每worker預算及勝出worker由量測receipt固定，
   量不到memory/I/O不可假裝0，不足budget改serial或停。
7. 第一次正式版本從2010整段建；沒有2019時間拼接。既有同身份欄可重用，
   事前inventory完整definition/input/code/calendar/basis/policies/parameters/runtime；
   missing/invalid/incompatible理由給新version。先stage→verify→no-replace publish primary shared。
8. 各stock feature/pivot/pattern可有限平行；同日RS/J/K3等全stock barrier完成後才計算；
   PAT需所有pattern events，base labels→episodes；獨立cohorts→event_outcomes→development selection→全部confirmation
   candidates→Q4–Q6。重現性依input/source identity與deterministic ordering，不依完成順序。
   每event/horizon套自己的detection/result品質與資格，引用固定base-label version+manifest；
   shared labels不存型態回看理由。各summary只消費自己的effective_label/event_main_eligible，
   同日B1/L1及union members不得互相覆寫，base/effective／excluded counts可重算。
9. 單次fixed calculation；分phase／stock/version的receipt支援resume。中斷保留部分輸出，
   不覆寫已封存檔；stale source/input或missing/corrupt ancestor停止publication。
   rerun bug fix記暴露／reason／新source版本；spec改動先修mission merge，再看結果。
10. 報告／audit：Q1–Q6全部主表、每condition區間、完整candidate、K診斷、
    年代/MKT/unknown、lost/missed例、tradeoff圖、10事件/5candidate獨立核對。
    更新catalog、asset index與pattern定義、backup status與availability。
    結果PR由owner merge；本次不額外觸發付費review、不force push。

待本階段核准後的工作不是已完成項目。排程更新、market-context實體遷移及異機備份
仍是原handoff第11節的獨立to-do，不在本次mission計算的默認權限內。

Cohort接線必須用build_pattern_cohorts：raw candidates → independent subtype cooldown，
以及raw candidates → same-day union → independent union cooldown；確認子型不被前型態抑制。
