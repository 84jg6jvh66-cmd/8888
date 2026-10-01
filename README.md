# US Stock Expectancy V8 — Futu OpenD 即時看盤版

## 功能
- Futu OpenD 即時美股行情
- `Session.ALL` 美股全時段訂閱（夜盤行情需相應 LV1+ 權限）
- 日K / 60m / 30m / 15m / 5m
- K線 + MA5/10/20/60/120 + RSI + MACD + ATR
- 自動支撐 / 壓力區與反應次數
- R/R、技術分析、自動選股、歷史回測
- Futu 連線失敗時仍先用 Yahoo 歷史資料顯示分析畫面，不讓整個頁面卡死

## Futu OpenD
官方文件目前說明：Futu API 已放寬開戶限制，可使用富途牛牛號（或註冊手機/Email）登入 OpenD；首次使用 API 需要完成問卷與協議確認。美股 Overnight 訂閱需要 LV1 以上權限；美股即時 K 線/逐筆可用 `Session.ALL` 訂閱全時段。

## 本機使用
1. 安裝並登入 Futu OpenD。
2. 確認 OpenD 監聽 `11111`（預設）。
3. 安裝 Python 套件：`pip install -r requirements.txt`
4. 設定環境變數：

```bash
FUTU_ENABLED=true
FUTU_HOST=127.0.0.1
FUTU_PORT=11111
FUTU_CONNECT_TIMEOUT=3
```

5. `streamlit run app.py`

## Streamlit Cloud / 雲端
不能把 `FUTU_HOST=127.0.0.1` 指向你自己的家用電腦。雲端網站需要能在網路上安全連到一台正在登入的 OpenD。建議把 OpenD 與後端放在同一台雲端主機，或透過安全私有網路連線；不要把 OpenD 的 11111 直接裸露到公網。

Streamlit Secrets 範例：

```toml
FUTU_ENABLED = true
FUTU_HOST = "你的OpenD內網/私網位址"
FUTU_PORT = 11111
FUTU_CONNECT_TIMEOUT = 3
```

## 重要
- V8 不會把富途帳號密碼寫進網站程式碼。
- Futu OpenD 必須保持登入且行情權限有效。
- 即時行情與歷史分析分開處理；OpenD 斷線時，歷史分析仍可顯示。
