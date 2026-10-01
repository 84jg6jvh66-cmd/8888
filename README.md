# US Stock Watch V8.1｜Futu 單機版

這一版專門給「只有一台 Windows 電腦」的使用方式。

## 使用方式（最簡單）

1. 安裝並開啟 Futu OpenD。
2. 在 Futu OpenD 登入你的 Futu/牛牛帳號。
3. 確認 OpenD 使用預設 `127.0.0.1:11111`。
4. 雙擊 `啟動V8.1.bat`。
5. 程式會自動安裝 Python 套件並啟動 Streamlit 網站。

程式預設已永久啟用 Futu：

```text
FUTU_ENABLED=true
FUTU_HOST=127.0.0.1
FUTU_PORT=11111
FUTU_CONNECT_TIMEOUT=3
```

## 如果看到「Futu OpenD 尚未啟用」

請先確認：
- Futu OpenD 有開著
- 已登入
- OpenD 沒有被防火牆/安全軟體阻擋
- Port 是 11111

網站即使沒有即時行情，Yahoo 歷史資料仍會作為技術分析備援，因此技術分析不會因 OpenD 暫時離線而整個失效。

## 注意

此版本是「網站與 OpenD 同一台電腦」架構。不要把 `11111` 直接公開到 Internet。
