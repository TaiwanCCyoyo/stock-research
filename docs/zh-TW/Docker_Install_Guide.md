# Docker 安裝指南 (Windows)

這裡是最簡單的懶人包步驟：

1.  **下載**
    - 前往官網：[Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
    - 點擊大大的藍色按鈕 "Download for Windows"。

2.  **安裝**
    - 雙擊下載後的 `.exe` 檔。
    - 安裝過程中如果問你要不要用 "WSL 2"，請勾選 **Yes** (這是比較新的核心，速度快)。
    - 安裝完畢後，它會要求您 **重新開機**。

3.  **啟動**
    - 重開機後，點擊桌面上的鯨魚圖示 (Docker Desktop)。
    - 第一次打開可能要等個 1-2 分鐘讓它暖機。
    - 當左下角變成 **綠色 (Engine Running)** 就是成功了！

4.  **驗證**
    - 打開您的 CMD 或 PowerShell，輸入：
      `docker --version`
    - 如果有跑出版本號，恭喜！您的實驗室地基已經蓋好了。
