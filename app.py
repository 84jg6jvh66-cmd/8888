import time
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title='US Stock Expectancy V3', page_icon='📈', layout='wide', initial_sidebar_state='collapsed')

st.markdown('''<style>
.block-container{padding:1rem 1rem 2rem;max-width:1200px}
@media(max-width:700px){.block-container{padding:.7rem .55rem 1.5rem}.stMetric{padding:.35rem}.stButton button{width:100%;min-height:48px;font-size:16px}}
[data-testid="stMetricValue"]{font-size:1.25rem}
</style>''', unsafe_allow_html=True)

MIN_BARS = 130


# ---------------------------------------------------------------- 資料 ----
@st.cache_data(ttl=900, show_spinner=False)
def data(ticker, period='5y'):
    """下載日線並計算指標。失敗時丟出例外（例外不會被快取，下次會重試）。"""
    if not ticker:
        raise ValueError('請輸入股票代號')
    d, err = None, None
    for k in range(3):
        try:
            d = yf.Ticker(ticker).history(period=period, interval='1d', auto_adjust=True)
            if d is not None and not d.empty:
                break
            err = ValueError('Yahoo 沒有回傳資料（代號錯誤或被限流）')
        except Exception as e:
            err = e
        d = None
        if k < 2:
            time.sleep(1.5 * (k + 1))
    if d is None:
        raise err
    d.columns = [str(c).title() for c in d.columns]
    d = d[['Open', 'High', 'Low', 'Close', 'Volume']].dropna().copy()
    if getattr(d.index, 'tz', None) is not None:
        d.index = d.index.tz_localize(None)
    for n in (5, 10, 20, 60, 120):
        d[f'MA{n}'] = d.Close.rolling(n).mean()
    prev = d.Close.shift(1)
    tr = pd.concat([d.High - d.Low, (d.High - prev).abs(), (d.Low - prev).abs()], axis=1).max(axis=1)
    d['ATR14'] = tr.rolling(14).mean()
    d['VolMA20'] = d.Volume.rolling(20).mean()
    return d.dropna()


# ------------------------------------------------------ 支撐 / 壓力 ----
def pivots(a, kind):
    """回傳 [(index, value)]。第 i 根的 pivot 需要後面 3 根才能確認，所以 i 只在 i+3 之後才可使用。"""
    out = []
    for i in range(3, len(a) - 3):
        w = a[i - 3:i + 4]
        if kind == 'low' and a[i] == w.min() and a[i] < a[i - 3:i].min():
            out.append((i, float(a[i])))
        elif kind == 'high' and a[i] == w.max() and a[i] > a[i + 1:i + 4].max():
            out.append((i, float(a[i])))
    return out


def cluster(values, tol):
    cs = []  # [mean, total, count]
    for v in sorted(values):
        for c in cs:
            if abs(v - c[0]) / c[0] <= tol:
                c[1] += v
                c[2] += 1
                c[0] = c[1] / c[2]
                break
        else:
            cs.append([v, v, 1])
    return [c[0] for c in cs]


def levels(lows, highs, p, tol):
    s = sorted((c for c in cluster(lows, tol) if c < p), reverse=True)
    r = sorted(c for c in cluster(highs, tol) if c > p)
    return s, r


def rr_stats(p, s1, r1, near, rrmin):
    """以價格 p 為基準，計算下行風險、上行潛力、R/R 與兩個條件旗標。"""
    risk = (p - s1) / p if np.isfinite(s1) and p > s1 else np.nan
    reward = (r1 - p) / p if np.isfinite(r1) and r1 > p else np.nan
    rr = reward / risk if np.isfinite(risk) and np.isfinite(reward) and risk > 0 else np.nan
    return risk, reward, rr, bool(np.isfinite(risk) and risk <= near), bool(np.isfinite(rr) and rr >= rrmin)


# ------------------------------------------------------------ 分析 ----
def analyze(ticker, near, rrmin, tol, period):
    d = data(ticker, period)
    if len(d) < MIN_BARS:
        raise ValueError(f'歷史資料不足（{len(d)} 筆，至少需要 {MIN_BARS}）')
    lows = [v for _, v in pivots(d.Low.values, 'low')]
    highs = [v for _, v in pivots(d.High.values, 'high')]
    x = d.iloc[-1]
    p = float(x.Close)
    s, r = levels(lows, highs, p, tol)
    s1 = s[0] if s else np.nan
    r1 = r[0] if r else np.nan
    risk, reward, rr, near_ok, rr_ok = rr_stats(p, s1, r1, near, rrmin)
    return {
        'Ticker': ticker, 'Price': p, 'S1': s1, 'R1': r1,
        'Risk': risk, 'Reward': reward, 'RR': rr,
        'Trend': bool(x.Close > x.MA20 > x.MA60 > x.MA120),
        'Near': near_ok, 'RROK': rr_ok,
        'Vol': float(x.Volume / x.VolMA20) if x.VolMA20 > 0 else np.nan,
        'MA20': float(x.MA20), 'MA60': float(x.MA60), 'MA120': float(x.MA120),
    }


# ------------------------------------------------------------ 回測 ----
@st.cache_data(ttl=900, show_spinner=False)
def run_backtest(ticker, period, near, rrmin, tol, horizon, cost):
    """
    訊號與掃描完全相同：趨勢向上 + 距 S1 夠近 + R/R 達標。
    - 訊號日收盤判斷，隔日開盤進場；停損 = S1，停利 = R1。
    - 同一時間只持有一筆，出場後才會找下一個訊號（避免重疊交易）。
    - 開盤跳空越過停損/停利時，以開盤價成交。
    - 隔日開盤已跌破停損或已越過停利：訊號失效，不進場。
    - cost 為單邊成本（含滑價），買賣各扣一次。
    """
    d = data(ticker, period)
    n = len(d)
    o, h, l, c = (d[k].values for k in ('Open', 'High', 'Low', 'Close'))
    trend = ((d.Close > d.MA20) & (d.MA20 > d.MA60) & (d.MA60 > d.MA120)).values
    lp, hp = pivots(l, 'low'), pivots(h, 'high')
    li, lv = [i for i, _ in lp], [v for _, v in lp]
    hi, hv = [i for i, _ in hp], [v for _, v in hp]
    dates = d.index

    rows = []
    i = MIN_BARS
    while i <= n - horizon - 2:
        if not trend[i]:
            i += 1
            continue
        p = float(c[i])
        s, r = levels(lv[:bisect_right(li, i - 3)], hv[:bisect_right(hi, i - 3)], p, tol)
        if not s or not r:
            i += 1
            continue
        stop, target = s[0], r[0]
        _, _, _, near_ok, rr_ok = rr_stats(p, stop, target, near, rrmin)
        ent = float(o[i + 1])
        if not (near_ok and rr_ok) or ent <= stop or ent >= target:
            i += 1
            continue

        ex, out, exit_i = None, '逾時', min(i + horizon, n - 1)
        for j in range(i + 1, min(i + 1 + horizon, n)):
            if o[j] <= stop:
                ex, out, exit_i = float(o[j]), '跳空停損', j
                break
            if l[j] <= stop:
                ex, out, exit_i = stop, '停損', j
                break
            if o[j] >= target:
                ex, out, exit_i = float(o[j]), '跳空停利', j
                break
            if h[j] >= target:
                ex, out, exit_i = target, '停利', j
                break
        if ex is None:
            ex = float(c[exit_i])

        rows.append({
            'EntryDate': dates[i + 1].strftime('%Y-%m-%d'), 'ExitDate': dates[exit_i].strftime('%Y-%m-%d'),
            'Entry': ent, 'Stop': stop, 'Target': target, 'Exit': ex,
            'Days': exit_i - i, 'Return': ex * (1 - cost) / (ent * (1 + cost)) - 1, 'Outcome': out,
        })
        i = exit_i
    return pd.DataFrame(rows)


# ------------------------------------------------------------ 介面 ----
def show_df(df):
    try:
        st.dataframe(df, width='stretch', hide_index=True)
    except Exception:  # 舊版 Streamlit
        st.dataframe(df, use_container_width=True, hide_index=True)


def usd(x):
    return f'${x:,.2f}' if np.isfinite(x) else '—'


def pct(x):
    return f'{x * 100:.2f}%' if np.isfinite(x) else '—'


st.title('📈 美股交易期望值 V3')
st.caption('手機優先介面｜單股分析｜條件掃描｜歷史回測｜期望值')

with st.expander('⚙️ 參數設定（點此展開）'):
    c1, c2 = st.columns(2)
    period = c1.selectbox('歷史資料', ['2y', '5y', '10y', 'max'], 1)
    horizon = c2.slider('最長持有日', 5, 60, 20, 5)
    near = st.slider('距離支撐 S1 最大 (%)', 1, 10, 3) / 100
    rrmin = st.number_input('最低 Risk/Reward', 0.5, 5.0, 1.5, 0.1)
    tol = st.slider('支撐/壓力聚類 (%)', 0.5, 3.0, 1.2, 0.1) / 100
    cost = st.slider('單邊交易成本＋滑價 (%)（回測用）', 0.0, 0.5, 0.05, 0.01) / 100

single, scan, test = st.tabs(['🔎 單股', '🚀 掃描', '📊 回測'])

with single:
    t = st.text_input('美股代號', 'AAPL').upper().strip()
    c1, c2 = st.columns(2)
    entry = c1.number_input('計畫進場價（0 = 用現價）', 0.0, 100000.0, 0.0, 0.01)
    capital = c2.number_input('投入資金', 0.0, 100000000.0, 10000.0, 100.0)
    if st.button('開始分析', type='primary'):
        try:
            with st.spinner('下載資料中…'):
                a = analyze(t, near, rrmin, tol, period)
                d = data(t, period)
        except Exception as err:
            st.error(f'分析失敗：{err}')
        else:
            ep = entry if entry > 0 else a['Price']
            risk, reward, rr, near_ok, rr_ok = rr_stats(ep, a['S1'], a['R1'], near, rrmin)
            if np.isfinite(a['S1']) and ep <= a['S1']:
                st.warning('進場價已低於或等於 S1，支撐失效，風險/報酬無法計算。')
            elif np.isfinite(a['R1']) and ep >= a['R1']:
                st.warning('進場價已高於或等於 R1，上行空間不足。')
            cols = st.columns(4)
            cols[0].metric('現價', usd(a['Price']))
            cols[1].metric('S1', usd(a['S1']))
            cols[2].metric('R1', usd(a['R1']))
            cols[3].metric('R/R', f'1:{rr:.2f}' if np.isfinite(rr) else '—')
            cols = st.columns(4)
            cols[0].metric('下行風險', pct(risk))
            cols[1].metric('上行潛力', pct(reward))
            cols[2].metric('預估股數', f'{int(capital / ep):,}')
            cols[3].metric('20日量能', f"{a['Vol']:.2f}x" if np.isfinite(a['Vol']) else '—')
            st.caption(f'風險/報酬以{"計畫進場價 " + usd(ep) if entry > 0 else "現價"}計算。')
            st.write(f"均線結構：MA20 ${a['MA20']:.2f}｜MA60 ${a['MA60']:.2f}｜MA120 ${a['MA120']:.2f}")
            st.write(f"條件：趨勢 {'✓' if a['Trend'] else '✗'}｜接近支撐 {'✓' if near_ok else '✗'}｜R/R {'✓' if rr_ok else '✗'}")
            st.line_chart(d[['Close', 'MA20', 'MA60', 'MA120']].tail(250))

with scan:
    st.write('手機也能操作：貼入自選股代號，每行一檔。')
    raw = st.text_area('股票清單', 'AAPL\nMSFT\nNVDA\nAMZN\nMETA\nGOOGL\nTSLA\nAVGO\nAMD\nNFLX')
    workers = st.slider('並行數（被 Yahoo 限流時請調低）', 1, 8, 3)
    if st.button('開始掃描', type='primary'):
        syms = list(dict.fromkeys(x.strip().upper() for x in raw.splitlines() if x.strip()))
        if not syms:
            st.warning('請輸入至少一檔股票代號。')
        else:
            ok, failed = [], {}
            bar = st.progress(0.0)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                fs = {pool.submit(analyze, s, near, rrmin, tol, period): s for s in syms}
                for n, f in enumerate(as_completed(fs), 1):
                    try:
                        ok.append(f.result())
                    except Exception as err:
                        failed[fs[f]] = str(err)[:80]
                    bar.progress(n / len(fs))
            bar.empty()
            if ok:
                df = pd.DataFrame(ok)
                hit = df[df.Trend & df.Near & df.RROK].sort_values(['RR', 'Reward'], ascending=False)
                m1, m2 = st.columns(2)
                m1.metric('成功掃描', f'{len(df)} / {len(syms)}')
                m2.metric('符合條件', len(hit))
                if hit.empty:
                    st.info('沒有股票同時符合趨勢、接近支撐與 R/R 條件。')
                else:
                    show_df(hit[['Ticker', 'Price', 'S1', 'R1', 'Risk', 'Reward', 'RR', 'Vol']])
                    st.download_button('下載 CSV', hit.to_csv(index=False).encode('utf-8-sig'), 'v3_scan.csv', 'text/csv')
            else:
                st.warning('沒有有效資料。')
            if failed:
                with st.expander(f'⚠️ {len(failed)} 檔失敗'):
                    show_df(pd.DataFrame({'代號': list(failed), '原因': list(failed.values())}))

with test:
    t2 = st.text_input('回測代號', 'AAPL', key='bt').upper().strip()
    st.caption('同一時間只持有一筆｜訊號隔日開盤進場｜停損 = S1、停利 = R1｜跳空依開盤價成交｜已扣交易成本')
    if st.button('執行回測', type='primary'):
        try:
            with st.spinner('回測中，10y / max 會比較久…'):
                bt = run_backtest(t2, period, near, rrmin, tol, horizon, cost)
        except Exception as err:
            st.error(f'回測失敗：{err}')
        else:
            if bt.empty:
                st.warning('沒有符合條件的歷史案例。')
            else:
                w = bt.Return > 0
                wr = w.mean()
                aw = bt.loc[w, 'Return'].mean() if w.any() else 0.0
                al = -bt.loc[~w, 'Return'].mean() if (~w).any() else 0.0
                ex = wr * aw - (1 - wr) * al
                eqv = np.concatenate([[1.0], (1 + bt.Return).cumprod().values])
                dd = (eqv / np.maximum.accumulate(eqv) - 1).min()
                c = st.columns(5)
                c[0].metric('案例', len(bt))
                c[1].metric('勝率', f'{wr * 100:.2f}%')
                c[2].metric('平均獲利', f'{aw * 100:.2f}%')
                c[3].metric('平均虧損', f'{al * 100:.2f}%')
                c[4].metric('期望值', f'{ex * 100:.2f}%')
                c = st.columns(4)
                c[0].metric('損益比', f'{aw / al:.2f}' if al > 0 else '—')
                c[1].metric('最大回撤', f'{dd * 100:.2f}%')
                c[2].metric('累計報酬', f'{(eqv[-1] - 1) * 100:.1f}%')
                c[3].metric('平均持有日', f"{bt.Days.mean():.1f}")
                st.caption('出場結果：' + '｜'.join(f'{k} {v}' for k, v in bt.Outcome.value_counts().items()))
                eq = pd.Series(eqv[1:], index=pd.to_datetime(bt.ExitDate), name='權益曲線')
                st.line_chart(eq)
                show_df(bt.tail(100))
                st.download_button('下載回測 CSV', bt.to_csv(index=False).encode('utf-8-sig'), f'{t2}_backtest.csv', 'text/csv')

st.divider()
st.caption('V3 可部署成手機瀏覽器直接開啟的網址。歷史資料來自 Yahoo Finance / yfinance；正式交易前應加入正式行情供應商，並以實際成交資料檢驗滑價與交易成本。回測結果不代表未來績效，也不構成投資建議。')
