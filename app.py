import os
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except Exception:
    go = None

st.set_page_config(page_title='US Stock Watch V7', page_icon='📈', layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container{padding:.45rem .75rem 2rem;max-width:1500px}.hero{padding:14px 16px;border-radius:16px;background:linear-gradient(135deg,#0f172a,#1e293b);color:#fff;margin-bottom:10px}.hero h1{margin:0;font-size:1.45rem}.muted{color:#94a3b8}.price{font-size:2.25rem;font-weight:800;line-height:1.05}.card{padding:12px;border:1px solid #334155;border-radius:14px;background:#0b1220}.small{font-size:.82rem;color:#94a3b8}@media(max-width:700px){.block-container{padding:.3rem}.price{font-size:1.9rem}.stButton button{min-height:44px;width:100%}.stTabs [data-baseweb="tab"]{font-size:.82rem}}
</style>''', unsafe_allow_html=True)

def secret(name, default=''):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

ALPACA_KEY = os.getenv('ALPACA_API_KEY', secret('ALPACA_API_KEY', ''))
ALPACA_SECRET = os.getenv('ALPACA_API_SECRET', secret('ALPACA_API_SECRET', ''))
ALPACA_DATA_URL = os.getenv('ALPACA_DATA_URL', secret('ALPACA_DATA_URL', 'https://data.alpaca.markets'))
ALPACA_FEED = os.getenv('ALPACA_FEED', secret('ALPACA_FEED', 'iex'))


def alpaca_headers():
    return {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}


def alpaca_ready():
    return bool(ALPACA_KEY and ALPACA_SECRET)


def alpaca_get(path, params=None, timeout=8):
    if not alpaca_ready():
        return None, '尚未設定 Alpaca API Key / Secret'
    try:
        r = requests.get(ALPACA_DATA_URL.rstrip('/') + path, headers=alpaca_headers(), params=params or {}, timeout=timeout)
        if r.status_code >= 400:
            return None, f'HTTP {r.status_code}: {r.text[:240]}'
        return r.json(), None
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=15, show_spinner=False)
def alpaca_snapshot(symbol, feed='iex'):
    data, err = alpaca_get(f'/v2/stocks/{symbol.upper()}/snapshot', {'feed': feed})
    if err or not data:
        return None, err
    q = data.get('latestQuote') or {}
    t = data.get('latestTrade') or {}
    daily = data.get('dailyBar') or {}
    prev = data.get('prevDailyBar') or {}
    price = t.get('p')
    if price is None:
        price = q.get('ap') or q.get('bp')
    return {
        'price': float(price) if price is not None else np.nan,
        'bid': float(q['bp']) if q.get('bp') is not None else np.nan,
        'ask': float(q['ap']) if q.get('ap') is not None else np.nan,
        'bid_size': q.get('bs'), 'ask_size': q.get('as'),
        'volume': float(daily['v']) if daily.get('v') is not None else np.nan,
        'open': float(daily['o']) if daily.get('o') is not None else np.nan,
        'high': float(daily['h']) if daily.get('h') is not None else np.nan,
        'low': float(daily['l']) if daily.get('l') is not None else np.nan,
        'prev': float(prev['c']) if prev.get('c') is not None else np.nan,
        'quote_time': q.get('t'), 'trade_time': t.get('t'),
        'source': f'Alpaca {feed}'
    }, None


@st.cache_data(ttl=30, show_spinner=False)
def alpaca_bars(symbol, timeframe='1Day', limit=500, feed='iex'):
    data, err = alpaca_get('/v2/stocks/bars', {'symbols': symbol.upper(), 'timeframe': timeframe, 'limit': limit, 'feed': feed, 'adjustment': 'all', 'sort': 'asc'})
    if err or not data:
        return pd.DataFrame(), err
    rows = (data.get('bars') or {}).get(symbol.upper(), [])
    if not rows:
        return pd.DataFrame(), 'Alpaca 沒有回傳 K 線'
    d = pd.DataFrame(rows)
    d['Date'] = pd.to_datetime(d['t'], utc=True).dt.tz_convert('America/New_York').dt.tz_localize(None)
    d = d.rename(columns={'o':'Open','h':'High','l':'Low','c':'Close','v':'Volume'})
    return d.set_index('Date')[['Open','High','Low','Close','Volume']], None


@st.cache_data(ttl=60, show_spinner=False)
def yf_history(symbol, period='1y', interval='1d'):
    try:
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False, threads=False)
        if isinstance(df.columns, pd.MultiIndex):
            df = df.xs(symbol, axis=1, level=1)
        df = df.rename(columns=str.title)
        return df.dropna(subset=['Open','High','Low','Close']).copy()
    except Exception:
        return pd.DataFrame()


def add_indicators(df):
    d = df.copy()
    for n in [5,10,20,60,120]: d[f'MA{n}'] = d['Close'].rolling(n).mean()
    tr = pd.concat([d['High']-d['Low'], (d['High']-d['Close'].shift()).abs(), (d['Low']-d['Close'].shift()).abs()], axis=1).max(axis=1)
    d['ATR14'] = tr.rolling(14).mean()
    d['VolMA20'] = d['Volume'].rolling(20).mean()
    delta = d['Close'].diff(); gain = delta.clip(lower=0).rolling(14).mean(); loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan); d['RSI14'] = 100 - (100/(1+rs))
    ema12 = d['Close'].ewm(span=12, adjust=False).mean(); ema26 = d['Close'].ewm(span=26, adjust=False).mean()
    d['MACD'] = ema12-ema26; d['MACDSignal'] = d['MACD'].ewm(span=9, adjust=False).mean()
    return d


def levels(df, lookback=180, tolerance=0.012):
    d = df.tail(lookback).copy(); hi=d['High'].values; lo=d['Low'].values; piv=[]
    for i in range(2, len(d)-2):
        if hi[i] >= hi[i-2:i+3].max(): piv.append(('R', float(hi[i])))
        if lo[i] <= lo[i-2:i+3].min(): piv.append(('S', float(lo[i])))
    clusters=[]
    for typ,p in sorted(piv, key=lambda x:x[1]):
        hit=None
        for c in clusters:
            if c['type']==typ and abs(p-c['price'])/c['price']<=tolerance: hit=c; break
        if hit:
            hit['prices'].append(p); hit['price']=float(np.mean(hit['prices'])); hit['touches']+=1
        else: clusters.append({'type':typ,'price':p,'prices':[p],'touches':1})
    price=float(d['Close'].iloc[-1])
    ss=[c for c in clusters if c['type']=='S' and c['price']<price]
    rr=[c for c in clusters if c['type']=='R' and c['price']>price]
    ss=sorted(ss,key=lambda c:(-c['touches'],abs(price-c['price'])))[:3]
    rr=sorted(rr,key=lambda c:(-c['touches'],abs(price-c['price'])))[:3]
    return sorted(ss,key=lambda c:c['price'],reverse=True), sorted(rr,key=lambda c:c['price'])


def chart(df, supports, resists, symbol):
    if go is None: return
    d=df.tail(220); fig=make_subplots(rows=2,cols=1,shared_xaxes=True,row_heights=[.78,.22],vertical_spacing=.03)
    fig.add_trace(go.Candlestick(x=d.index,open=d.Open,high=d.High,low=d.Low,close=d.Close,name='K線'),row=1,col=1)
    for n in [20,60,120]: fig.add_trace(go.Scatter(x=d.index,y=d[f'MA{n}'],name=f'MA{n}',mode='lines'),row=1,col=1)
    for c in supports: fig.add_hline(y=c['price'],line_dash='dot',annotation_text=f"S {c['price']:.2f} ×{c['touches']}",row=1,col=1)
    for c in resists: fig.add_hline(y=c['price'],line_dash='dot',annotation_text=f"R {c['price']:.2f} ×{c['touches']}",row=1,col=1)
    fig.add_trace(go.Bar(x=d.index,y=d.Volume,name='成交量'),row=2,col=1)
    fig.update_layout(height=650,margin=dict(l=10,r=10,t=25,b=10),xaxis_rangeslider_visible=False,legend_orientation='h',template='plotly_dark')
    st.plotly_chart(fig,use_container_width=True,config={'displaylogo':False,'scrollZoom':True})


@st.cache_data(ttl=30, show_spinner=False)
def historical_analysis(symbol):
    df, err = alpaca_bars(symbol, '1Day', 500, ALPACA_FEED)
    source='Alpaca'
    if df.empty:
        df=yf_history(symbol,'1y','1d'); source='Yahoo 備援'
    if df.empty: return None
    df=add_indicators(df); ss,rr=levels(df); price=float(df['Close'].iloc[-1])
    s1=ss[0]['price'] if ss else np.nan; r1=rr[0]['price'] if rr else np.nan
    risk=price-s1 if np.isfinite(s1) else np.nan; reward=r1-price if np.isfinite(r1) else np.nan
    rr_ratio=reward/risk if risk>0 and reward>0 else np.nan
    trend='多頭' if df['MA20'].iloc[-1]>df['MA60'].iloc[-1]>df['MA120'].iloc[-1] else ('空頭' if df['MA20'].iloc[-1]<df['MA60'].iloc[-1]<df['MA120'].iloc[-1] else '盤整')
    return {'df':df,'supports':ss,'resists':rr,'price':price,'s1':s1,'r1':r1,'rr':rr_ratio,'trend':trend,'source':source}


def analyze(symbol, feed):
    base=historical_analysis(symbol)
    if base is None: return None
    q, err=alpaca_snapshot(symbol, feed)
    if q and np.isfinite(q.get('price',np.nan)): base['price']=q['price']; base['quote']=q; base['quote_error']=None
    else: base['quote']={}; base['quote_error']=err
    base['symbol']=symbol
    return base


def backtest(df, hold=10, target_r=2.0):
    trades=[]
    for i in range(len(df)-2):
        hist=df.iloc[:i+1]
        ss,rr=levels(hist)
        if not ss or not rr: continue
        e=float(df['Open'].iloc[i+1]); stop=float(ss[0]['price']); target=e+(e-stop)*target_r
        if not (stop<e<target): continue
        end=min(i+1+int(hold),len(df)-1); outcome=None; exit_price=None; exit_idx=end
        for j in range(i+1,end+1):
            lo=float(df['Low'].iloc[j]); hi=float(df['High'].iloc[j])
            if lo<=stop and hi>=target: outcome='同日同時觸發（保守停損）'; exit_price=stop; exit_idx=j; break
            if lo<=stop: outcome='停損'; exit_price=stop; exit_idx=j; break
            if hi>=target: outcome='停利'; exit_price=target; exit_idx=j; break
        if exit_price is None: exit_price=float(df['Close'].iloc[exit_idx]); outcome='持有期結束'
        trades.append({'進場日':str(df.index[i+1].date()),'進場':e,'停損':stop,'目標':target,'出場日':str(df.index[exit_idx].date()),'出場':exit_price,'報酬%':(exit_price-e)/e*100,'結果':outcome})
    return pd.DataFrame(trades)


def show_quote(q, a, feed):
    prev=q.get('prev',np.nan); price=a['price']; ch=price-prev if np.isfinite(prev) else np.nan; pct=ch/prev*100 if np.isfinite(ch) and prev else np.nan
    c=st.columns(5); c[0].metric('現價',f'${price:.2f}',f'{pct:+.2f}%' if np.isfinite(pct) else None); c[1].metric('Bid',f"${q.get('bid',np.nan):.2f}" if np.isfinite(q.get('bid',np.nan)) else '—'); c[2].metric('Ask',f"${q.get('ask',np.nan):.2f}" if np.isfinite(q.get('ask',np.nan)) else '—'); c[3].metric('S1',f"${a['s1']:.2f}" if np.isfinite(a['s1']) else '—'); c[4].metric('R1',f"${a['r1']:.2f}" if np.isfinite(a['r1']) else '—')
    st.caption(f"行情：{q.get('source','—')}｜Feed：{feed}｜最後更新：{q.get('trade_time') or q.get('quote_time') or '—'}")


st.markdown('<div class="hero"><h1>📈 US Stock Watch V7</h1><div class="muted">Alpaca 24/5 行情 × K線 × 自動支撐壓力 × 自動選股 × 回測</div></div>', unsafe_allow_html=True)

with st.sidebar:
    st.subheader('⚙️ 行情設定')
    feed=st.selectbox('即時 Feed',['iex','sip','overnight','boats'],index=['iex','sip','overnight','boats'].index(ALPACA_FEED) if ALPACA_FEED in ['iex','sip','overnight','boats'] else 0)
    st.caption('免費測試可先用 IEX；夜盤選 overnight。是否可用取決於 Alpaca 帳戶方案。')
    st.success('Alpaca API 已設定' if alpaca_ready() else '尚未設定 Alpaca API')

symbol=st.text_input('🔎 輸入美股代碼',value=st.session_state.get('symbol','NVDA'),placeholder='NVDA / AAPL / TSLA').strip().upper(); st.session_state['symbol']=symbol
if not symbol: st.stop()

with st.spinner('載入 K 線與行情…'):
    a=analyze(symbol,feed)

if a is None:
    st.error('找不到行情。請確認股票代碼，或設定 Alpaca API Key / Secret。')
else:
    q=a.get('quote') or {}
    tabs=st.tabs(['📺 看盤','🧠 技術分析','🚀 自動選股','📊 回測'])
    with tabs[0]:
        if q: show_quote(q,a,feed)
        else:
            st.warning(f"即時行情目前無法取得：{a.get('quote_error','未知錯誤')}。技術分析仍可正常使用。")
            st.metric('歷史收盤',f"${a['price']:.2f}")
        chart(a['df'],a['supports'],a['resists'],symbol)
        st.caption('支撐/壓力是依歷史價格反覆反應自動聚類的區域，不是未來反轉保證。')

    with tabs[1]:
        d=a['df'].iloc[-1]; cols=st.columns(7)
        for col,n in zip(cols,['MA5','MA10','MA20','MA60','MA120','RSI14','ATR14']): col.metric(n,f"{d[n]:.2f}" if np.isfinite(d[n]) else '—')
        st.subheader('自動支撐 / 壓力'); x,y=st.columns(2)
        with x: st.dataframe(pd.DataFrame([{'價位':c['price'],'反應次數':c['touches']} for c in a['supports']]),hide_index=True,use_container_width=True)
        with y: st.dataframe(pd.DataFrame([{'價位':c['price'],'反應次數':c['touches']} for c in a['resists']]),hide_index=True,use_container_width=True)
        st.subheader('MACD'); st.line_chart(a['df'][['MACD','MACDSignal']].tail(120))

    with tabs[2]:
        st.subheader('🚀 自動選股')
        c=st.columns(4); min_rr=c[0].number_input('最低 R/R',1.0,10.0,2.0,.5); max_dist=c[1].number_input('距離支撐最大 %',1.0,30.0,6.0,1.0); min_vol=c[2].number_input('量 / 20日均量 ≥',0.5,10.0,1.2,.1); only_bull=c[3].checkbox('只看多頭排列',True)
        symbols=st.text_area('股票清單（每行或逗號分隔）','NVDA\nAAPL\nMSFT\nAMZN\nMETA\nTSLA\nAMD\nAVGO\nPLTR\nGOOGL').replace(',','\n')
        if st.button('開始掃描',type='primary'):
            rows=[]
            for s in [x.strip().upper() for x in symbols.splitlines() if x.strip()]:
                try:
                    z=analyze(s,feed)
                    if not z: continue
                    dd=z['df'].iloc[-1]; dist=(z['price']-z['s1'])/z['price']*100 if np.isfinite(z['s1']) and z['price'] else np.nan; volr=dd['Volume']/dd['VolMA20'] if np.isfinite(dd['VolMA20']) and dd['VolMA20'] else np.nan
                    if np.isfinite(z['rr']) and z['rr']>=min_rr and np.isfinite(dist) and dist<=max_dist and np.isfinite(volr) and volr>=min_vol and (not only_bull or z['trend']=='多頭'):
                        rows.append({'股票':s,'價格':z['price'],'S1':z['s1'],'R1':z['r1'],'距支撐%':dist,'量比':volr,'R/R':z['rr'],'趨勢':z['trend']})
                except Exception: continue
            st.session_state['scan']=pd.DataFrame(rows)
        if 'scan' in st.session_state: st.dataframe(st.session_state['scan'],hide_index=True,use_container_width=True)

    with tabs[3]:
        st.subheader('📊 歷史條件回測')
        hold=st.number_input('最多持有交易日',1,60,10,1); target_r=st.number_input('目標 R',0.5,10.0,2.0,0.5); min_samples=st.number_input('最低樣本數',5,1000,30,5)
        if st.button('開始回測',type='primary'):
            bt=backtest(a['df'].copy(),hold,target_r)
            if len(bt)<min_samples: st.warning(f'有效樣本只有 {len(bt)} 筆，低於你設定的最低樣本數 {min_samples}；不顯示勝率結論。'); st.dataframe(bt.tail(100),hide_index=True,use_container_width=True)
            elif bt.empty: st.warning('沒有有效樣本。')
            else:
                wins=bt['報酬%']>0; losses=bt['報酬%']<0; avg_win=bt.loc[wins,'報酬%'].mean() if wins.any() else 0; avg_loss=abs(bt.loc[losses,'報酬%'].mean()) if losses.any() else 0; winrate=wins.mean(); expectancy=winrate*avg_win-(1-winrate)*avg_loss
                equity=(1+bt['報酬%']/100).cumprod(); dd=(equity/equity.cummax()-1)*100
                c=st.columns(5); c[0].metric('樣本數',len(bt)); c[1].metric('勝率',f'{winrate*100:.1f}%'); c[2].metric('平均盈利',f'{avg_win:.2f}%'); c[3].metric('平均虧損',f'-{avg_loss:.2f}%'); c[4].metric('期望值',f'{expectancy:.2f}%')
                st.metric('最大回撤',f'{dd.min():.2f}%'); st.dataframe(bt.tail(100),hide_index=True,use_container_width=True)
        st.caption('回測只使用當時已知的歷史資料；同一根 K 線同時碰到停損/停利時採保守停損。歷史結果不代表未來。')

with st.expander('🔑 Alpaca 設定說明'):
    st.code('ALPACA_API_KEY = "你的 Key"\nALPACA_API_SECRET = "你的 Secret"\nALPACA_FEED = "iex"', language='toml')
    st.write('Streamlit Cloud：把上述三項放到 App 的 Secrets；不要把 Key/Secret 寫進 GitHub。')
