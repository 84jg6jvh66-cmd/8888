# US Stock Expectancy V5

Mobile-first U.S. stock research dashboard with:
- Live quote center with automatic refresh
- Regular / extended / overnight session selector
- Alpaca Market Data integration
- Yahoo Finance fallback for historical analysis
- Technical levels, moving averages, volume, risk/reward
- Scanner and backtest

## Live market data setup
Create Streamlit secrets:

```toml
ALPACA_API_KEY = "your_key"
ALPACA_API_SECRET = "your_secret"
```

The app prefers Alpaca for live quotes. Without keys, it falls back to Yahoo Finance where available.

Alpaca's current 24/5 documentation describes overnight trading from Sunday 8 PM ET through Friday 4 AM ET, plus pre-market 4-9:30 AM ET, regular 9:30 AM-4 PM ET, and after-hours 4-8 PM ET. Data-feed availability and delay depend on the account/feed plan.

## Deploy
Upload `app.py` and `requirements.txt` to GitHub, then deploy the repo on Streamlit Community Cloud. Add the two Alpaca secrets in the app's Secrets settings.
