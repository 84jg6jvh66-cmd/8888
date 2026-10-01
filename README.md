# US Stock Watch V6

V6 is a mobile-first US stock watch / technical-analysis dashboard inspired by professional brokerage watch screens.

## Core features
- Futu OpenD/API adapter for US real-time quotes and real-time K-lines
- Yahoo Finance fallback for historical data when Futu OpenD is not connected
- Candlestick chart with MA5/10/20/60/120 and volume
- Automatic support/resistance clustering from historical pivot reactions
- Support/resistance levels shown directly on the chart
- R/R calculation from entry, S1 and R1
- RSI14 and MACD
- Configurable scanner using trend, distance to support, volume ratio and R/R
- Mobile-first Streamlit UI

## Futu connection
Futu API requires OpenD running locally or on a cloud/server environment. Set:

```toml
FUTU_HOST = "127.0.0.1"
FUTU_PORT = 11111
```

OpenD must be logged in with the appropriate Futu account and the server running the Streamlit app must be able to reach it.

## Important
Futu real-time market data requires the relevant market-data subscription. This app does not bypass or redistribute Futu entitlements.

The automatic support/resistance engine is a quantitative heuristic based on historical pivot reactions and clustering. It is not a guarantee of future price behavior.
