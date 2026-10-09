# 執行、保存與 metadata 更正

工作 ID 使用擁有者指定的 20261009；本機執行／核對日為 2026-10-08。

## 結果前固定

準備提交 2ff0884 保存原來源與輸入案例；b84875c 固定 Claude 更正後的暫定定義、
狀態機與 558 格。35bd7778cda505f827b056f5666fb22ca178b9bf 只改同定義運算排程，
是完成批次的 code_commit。mission 與 data-contract 的當次 exact bytes 存於
publication-v1/bundle.zip 的 inputs，不能把結果後新版文件當成原預註冊。

## 兩次執行，不是兩個候選試驗

- hhhl-v1-descriptive-01：原單程序。最後觀察到的進度為 100/1,941 檔、283.1 秒；
  不是實際停止時刻／總耗時。主代理只停止確認屬於此 run 的程序，exit 1；原
  complete:false 紀錄保存。沒有輸出／讀取該批科學彙總。這是 incomplete，非 candidate_failed。
- hhhl-v1-descriptive-02：原 3,600 秒預算內，四程序有界排程，父程序仍按原股票順序
  取結果／seed=20261009 抽雜訊。未省略股票、切段、改價格／特徵／label／定義。
  1001.938 秒、exit 0；46,868 事件、93,736 轉態、558 格。執行前後 identity 不變；
  來源 manifest 驗證 1,948 檔與逐股／交叉欄位接合的 3,588,909 列。

## 完成紀錄自引用錯誤：只修 metadata，不修科學數據

原 builder 起跑時先寫 manifest.json 的未完成紀錄。完成時列檔案雜湊包含該 placeholder，
然後覆寫 manifest，因此其自身那筆雜湊不符合最終檔案。其他六筆全部通過 SHA-256／bytes。
不得宣稱原 manifest 的全部 inventory 通過；這項是 metadata defect，未觀察到數據改變。

原完成 manifest 原樣保留，SHA-256：
477d798ab3d1fbc61f203ef5801bf1bf3aac07a992543e4b95346d16c9dda5ed。
新增 manifest-corrected.json，僅移除錯誤的自身 inventory entry、加上更正原因、原檔雜湊、
被移除 entry 及 scientific_artifacts_unchanged:true。該紀錄不把自己列入 inventory。
可攜包同時保存原檔與更正檔；以更正檔驗證科學產物，原缺陷不能靜默消失。

未來 producer 將最初狀態寫為 attempt.json，完成 manifest 不再自列。
合成功能回歸測試核對每個宣告產物的實際雜湊。未為此 metadata 修正重跑市場，
原科學完成提交／輸入快照仍含當時程式 bytes；新版 producer 不冒充該次版本。

## 驗證與保存

相關三個測試檔合計 31 passed（最後重驗 3.27 秒）；原始案例來源驗算 54 筆、47 股票表
曾通過。十筆固定 code/date 順序抽查：8 筆完整結果手算 126 列最高收盤與門檻一致，
2 筆 missing_or_invalid_path，未填零。抽查都在 TW:1101，不作代表性樣本或勝率證明。

六個完成產物 SHA-256／bytes、原 manifest 綁定、可攜 ZIP 八個輸入身分／12 個成員及
完整 558 JSON 格已通過核對。壓縮只改 transport，不刪格子或更改精度。
完整大表留在 primary task canonical 路徑，從未只放 .tmp 或 worktree。
package 的八份 declared inputs 不包含整個 repo／資料／全部依賴，不能聲稱 standalone replay。

Git hooks 與 hosted checks 的狀態另於提交／PR 對話回報；不把本地測試當 hosted review。

提交檢查對可攜 manifest 的 18 個確切 checksum 誤報。全部對應已核對的 SHA／commit，
新增精確值到既有 baseline，未改 hook 或掃描範圍。既有功能測試追加此 manifest 案例，
確認已知 checksum 可通過、新值仍被拒絕。合併上述相關測試重驗 33 passed（5.97 秒）。
