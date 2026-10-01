# US Stock Expectancy V6.1

V6.1 fixes the slow-loading issue when Futu OpenD is unavailable. The app now renders historical K-lines/technical analysis first and only contacts Futu when `FUTU_ENABLED=true`.

## Futu live mode
Set Streamlit secrets:
```toml
FUTU_ENABLED = true
FUTU_HOST = "127.0.0.1"
FUTU_PORT = 11111
```
Run Futu OpenD and log in before starting the app. If Futu is not enabled, the app uses cached Yahoo historical data so entering a ticker does not hang waiting for OpenD.

## Features
- Watch-style stock page
- K-line chart and volume
- MA5/10/20/60/120, RSI, MACD
- Automatic support/resistance clustering
- Risk/reward
- Scanner and backtest shell
