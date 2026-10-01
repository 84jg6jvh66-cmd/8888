# US Stock Watch V8.1 FIXED3

這一版專門修正 Futu OpenD 即時行情連線問題。

## 重要修正
- 已完全移除舊版 `socket.create_connection()` TCP preflight，因此不會再產生舊版的「127.0.0.1:11111 無法連線：[Errno 111] Connection refused」訊息。
- 直接使用 `futu.OpenQuoteContext()` + `get_global_state()` + Quote/K-line API。
- 頁面版本明確標示為 `V8.1 FIXED3`。
- Streamlit 改用 `8511`，避免舊版仍占用 8501 導致瀏覽器開到舊程式。

## 啟動
1. 先登入並保持 Futu OpenD 開啟。
2. 雙擊 `啟動V8.1_FIXED3.bat`。
3. 瀏覽器應開啟 `http://localhost:8511`。
4. 左側按「🔌 測試 Futu OpenD（API）連線」。
5. 正常時會顯示：`🟢 Futu OpenD API 連線正常：Quote 已登入、OpenD READY`。

## 注意
網站與 Futu OpenD 必須在同一台 Windows 電腦上，OpenD 預設為 `127.0.0.1:11111`。
