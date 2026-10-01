# US Stock Watch V8.1｜Futu 單機版

Windows 單機版：網站與 Futu OpenD 在同一台電腦。

## 使用
1. 安裝 Python 3.12.x 64-bit，安裝時勾選 Add python.exe to PATH。
2. 開啟並登入 Futu OpenD。
3. 確認 OpenD 使用 127.0.0.1:11111。
4. 雙擊 `啟動V8.1.bat`。

啟動程式會依序檢查 Python、Python 套件與 OpenD TCP，然後啟動 Streamlit。

網站側欄會顯示 Futu 狀態：TCP、Quote 登入與 OpenD READY。

技術分析優先使用 Futu K 線；若 Futu K 線暫時無法取得，會以 Yahoo 歷史資料作備援。即時行情只使用 Futu OpenD。

不要把 11111 直接公開到 Internet。
