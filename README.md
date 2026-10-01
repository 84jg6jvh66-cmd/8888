# US Stock Expectancy V7

Alpaca-first U.S. stock dashboard for 24/5 quotes, K-line technical analysis, automatic support/resistance, scanning and historical backtesting.

## Deploy

1. Upload this folder to GitHub.
2. Deploy `app.py` with Streamlit Community Cloud.
3. In Streamlit App → Settings → Secrets, add:

```toml
ALPACA_API_KEY = "YOUR_KEY"
ALPACA_API_SECRET = "YOUR_SECRET"
ALPACA_FEED = "iex"
```

For overnight use `ALPACA_FEED = "overnight"` if the account has access. For full U.S. exchange SIP data use `sip` if the subscription supports it.

## Important

- Alpaca supports U.S. equity 24/5 sessions, not general 24/7 weekend trading.
- Free testing may be limited to IEX and account entitlements.
- Overnight quotes/trades have plan-specific availability and characteristics.
- The app keeps historical technical analysis independent from the live quote request, so a live-data error does not prevent the K-line and backtest tabs from rendering.
- Backtests are designed to avoid using future bars to define historical support/resistance.
- This is a research tool, not investment advice or a guarantee of future performance.
