US Stock Watch V8.1｜Futu 單機修正版 2

1. 先開啟並登入 Futu OpenD。
2. 確認 OpenD 使用 127.0.0.1:11111。
3. 雙擊 啟動V8.1.bat。
4. 進入網站後，左側按「測試 Futu OpenD（API）連線」。
5. 若顯示 READY / Quote 已登入，即可輸入美股代碼看盤。

本版不再用單純 TCP preflight 判斷 Futu 狀態，而是直接透過 Futu Python API 呼叫 get_global_state() 驗證 OpenD。
