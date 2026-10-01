import os
import socket
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except Exception:
    go = None

try:
    import futu
    FUTU_IMPORT_OK = True
except Exception:
    futu = None
    FUTU_IMPORT_OK = False

st.set_page_config(page_title='US Stock Watch V8', page_icon='📈', layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container{padding:.45rem .75rem 2rem;max-width:1500px}.hero{padding:14px 16px;border-radius:16px;background:linear-gradient(135deg,#0f172a,#1e293b);color:#fff;margin-bottom:10px}.hero h1{margin:0;font-size:1.45rem}.muted{color:#94a3b8}.price{font-size:2.25rem;font-weight:800;line-height:1.05}.status{padding:8px 12px;border-radius:10px;margin:8px 0}.small{font-size:.82rem;color:#94a3b8}@media(max-width:700px){.block-container{padding:.3rem}.price{font-size:1.9rem}.stButton button{min-height:44px;width:100%}.stTabs [data-baseweb="tab"]{font-size:.82rem}}
</style>''', unsafe_allow_html=True)

def secret(name, default=''):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

# V8.1 單機版：永久啟用 Futu OpenD。若需要暫時關閉，可設定 FUTU_ENABLED=false。
FUTU_ENABLED = str(os.getenv('FUTU_ENABLED', secret('FUTU_ENABLED', 'true'))).lower() in ('1','true','yes','on')
FUTU_HOST = os.getenv('FUTU_HOST', secret('FUTU_HOST', '127.0.0.1'))
try:
    FUTU_PORT = int(os.getenv('FUTU_PORT', secret('FUTU_PORT', '11111')))
except Exception:
    FUTU_PORT = 11111
FUTU_TIMEOUT = float(os.getenv('FUTU_CONNECT_TIMEOUT', secret('FUTU_CONNECT_TIMEOUT', '3')))


@st.cache_data(ttl=5, show_spinner=False)
def futu_preflight_cached(host, port, timeout=3):
    return futu_preflight(host, port, timeout)

def futu_preflight(host, port, timeout=3):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, None
    except Exception as e:
        return False, f'{host}:{port} 無法連線：{e}'


class FutuProvider:
    def __init__(self, host, port):
        self.host, self.port = host, int(port)

    def available(self):
        return FUTU_ENABLED and FUTU_IMPORT_OK

    def quote(self, symbol):
        if not self.available():
            return None, 'Futu 模式未啟用或 futu-api 未安裝'
        ok, err = futu_preflight_cached(self.host, self.port, FUTU_TIMEOUT)
        if not ok:
            return None, err
        ctx = None
        try:
            ctx = futu.OpenQuoteContext(host=self.host, port=self.port)
            code = f'US.{symbol.upper()}'
            ret, msg = ctx.subscribe([code], [futu.SubType.QUOTE], subscribe_push=False, session=futu.Session.ALL)
            if ret != futu.RET_OK:
                return None, str(msg)
            ret, data = ctx.get_stock_quote([code])
            if ret != futu.RET_OK or data is None or data.empty:
                return None, str(data)
            r = data.iloc[0]
            return {
                'price': float(r.get('last_price', np.nan)),
                'open': float(r.get('open_price', np.nan)),
                'high': float(r.get('high_price', np.nan)),
                'low': float(r.get('low_price', np.nan)),
                'prev': float(r.get('prev_close_price', np.nan)),
                'volume': float(r.get('volume', np.nan)),
                'turnover': float(r.get('turnover', np.nan)),
                'overnight_change_rate': float(r.get('overnight_change_rate', np.nan)),
                'overnight_volume': float(r.get('overnight_volume', np.nan)),
                'time': str(r.get('data_time', '')),
                'source': 'Futu OpenD / Session.ALL'
            }, None
        except Exception as e:
            return None, f'Futu API：{e}'
        finally:
            try:
                if ctx is not None:
                    ctx.close()
            except Exception:
                pass

    def kline(self, symbol, subtype='K_DAY', limit=500):
        if not self.available():
            return pd.DataFrame(), 'Futu 模式未啟用或 futu-api 未安裝'
        ok, err = futu_preflight_cached(self.host, self.port, FUTU_TIMEOUT)
        if not ok:
            return pd.DataFrame(), err
        ctx = None
        try:
            ctx = futu.OpenQuoteContext(host=self.host, port=self.port)
            code = f'US.{symbol.upper()}'
            stype = getattr(futu.SubType, subtype)
            ret, msg = ctx.subscribe([code], [stype], subscribe_push=False, session=futu.Session.ALL)
            if ret != futu.RET_OK:
                return pd.DataFrame(), str(msg)
            ret, data = ctx.get_cur_kline(code, int(limit), stype, futu.AuType.QFQ)
            if ret != futu.RET_OK or data is None or data.empty:
                return pd.DataFrame(), str(data)
            d = data.copy()
            d['time_key'] = pd.to_datetime(d['time_key'])
            d = d.rename(columns={'time_key':'Date','open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'})
            return d.set_index('Date')[['Open','High','Low','Close','Volume']].sort_index(), None
        except Exception as e:
            return pd.DataFrame(), f'Futu K線：{e}'
        finally:
            try:
                if ctx is not None:
                    ctx.close()
            except Exception:
                pass


@st.cache_data(ttl=5, show_spinner=False)
def futu_health():
    if not FUTU_ENABLED:
        return {'tcp': False, 'api': False, 'ready': False, 'message': 'FUTU_ENABLED=false'}
    if not FUTU_IMPORT_OK:
        return {'tcp': False, 'api': False, 'ready': False, 'message': 'Python futu-api 尚未安裝'}
    tcp, err = futu_preflight(FUTU_HOST, FUTU_PORT, FUTU_TIMEOUT)
    if not tcp:
        return {'tcp': False, 'api': False, 'ready': False, 'message': err or 'OpenD TCP 無法連線'}
    ctx = None
    try:
        ctx = futu.OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
        ret, state = ctx.get_global_state()
        if ret != futu.RET_OK or not isinstance(state, dict):
            return {'tcp': True, 'api': False, 'ready': False, 'message': str(state)}
        ready = state.get('program_status_type') == 'READY' and bool(state.get('qot_logined'))
        msg = 'OpenD READY／Quote 已登入' if ready else f"OpenD 狀態：{state.get('program_status_type','未知')}／Quote 登入：{state.get('qot_logined')}"
        return {'tcp': True, 'api': True, 'ready': ready, 'message': msg, 'state': state}
    except Exception as e:
        return {'tcp': True, 'api': False, 'ready': False, 'message': f'Futu API：{e}'}
    finally:
        try:
            if ctx is not None:
                ctx.close()
        except Exception:
            pass

FUTU = FutuProvider(FUTU_HOST, FUTU_PORT)

@st.cache_data(ttl=20, show_spinner=False)
def futu_quote_cached(symbol):
    return FUTU.quote(symbol)

@st.cache_data(ttl=30, show_spinner=False)
def futu_kline_cached(symbol, subtype, limit=500):
    return FUTU.kline(symbol, subtype, limit)

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
    ss=sorted([c for c in clusters if c['type']=='S' and c['price']<price],key=lambda c:(-c['touches'],abs(price-c['price'])))[:3]
    rr=sorted([c for c in clusters if c['type']=='R' and c['price']>price],key=lambda c:(-c['touches'],abs(price-c['price'])))[:3]
    return sorted(ss,key=lambda c:c['price'],reverse=True), sorted(rr,key=lambda c:c['price'])


def chart(df, supports, resists):
    if go is None: return
    d=df.tail(240); fig=make_subplots(rows=2,cols=1,shared_xaxes=True,row_heights=[.78,.22],vertical_spacing=.03)
    fig.add_trace(go.Candlestick(x=d.index,open=d.Open,high=d.High,low=d.Low,close=d.Close,name='K線'),row=1,col=1)
    for n in [20,60,120]: fig.add_trace(go.Scatter(x=d.index,y=d[f'MA{n}'],name=f'MA{n}',mode='lines'),row=1,col=1)
    for c in supports: fig.add_hline(y=c['price'],line_dash='dot',annotation_text=f"S {c['price']:.2f} ×{c['touches']}",row=1,col=1)
    for c in resists: fig.add_hline(y=c['price'],line_dash='dot',annotation_text=f"R {c['price']:.2f} ×{c['touches']}",row=1,col=1)
    fig.add_trace(go.Bar(x=d.index,y=d.Volume,name='成交量'),row=2,col=1)
    fig.update_layout(height=650,margin=dict(l=10,r=10,t=25,b=10),xaxis_rangeslider_visible=False,legend_orientation='h',template='plotly_dark')
    st.plotly_chart(fig,use_container_width=True,config={'displaylogo':False,'scrollZoom':True})


@st.cache_data(ttl=30, show_spinner=False)
def historical_analysis(symbol, interval='1d'):
    df=pd.DataFrame(); source=''
    if FUTU.available():
        subtype={'1d':'K_DAY','60m':'K_60M','30m':'K_30M','15m':'K_15M','5m':'K_5M'}.get(interval,'K_DAY')
        df, ferr=futu_kline_cached(symbol, subtype, 500)
        if not df.empty: source='Futu OpenD'
    if df.empty:
        if interval=='1d': df=yf_history(symbol,'2y','1d')
        elif interval in ('60m','30m','15m','5m'): df=yf_history(symbol,'60d',interval)
        source='Yahoo 備援' if not df.empty else ''
    if df.empty: return None
    df=add_indicators(df); ss,rr=levels(df); price=float(df['Close'].iloc[-1])
    s1=ss[0]['price'] if ss else np.nan; r1=rr[0]['price'] if rr else np.nan
    risk=price-s1 if np.isfinite(s1) else np.nan; reward=r1-price if np.isfinite(r1) else np.nan
    rr_ratio=reward/risk if risk>0 and reward>0 else np.nan
    trend='多頭' if df['MA20'].iloc[-1]>df['MA60'].iloc[-1]>df['MA120'].iloc[-1] else ('空頭' if df['MA20'].iloc[-1]<df['MA60'].iloc[-1]<df['MA120'].iloc[-1] else '盤整')
    return {'df':df,'supports':ss,'resists':rr,'price':price,'s1':s1,'r1':r1,'rr':rr_ratio,'trend':trend,'source':source}


def analyze(symbol, interval):
    base=historical_analysis(symbol, interval)
    if base is None: return None
    q, err=futu_quote_cached(symbol) if FUTU.available() else (None, 'Futu OpenD 尚未啟用')
    if q and np.isfinite(q.get('price',np.nan)):
        base['price']=q['price']; base['quote']=q; base['quote_error']=None
    else:
        base['quote']={}; base['quote_error']=err
    base['symbol']=symbol
    return base


def backtest(df, hold=10, target_r=2.0):
    trades=[]
    for i in range(len(df)-2):
        hist=df.iloc[:i+1]; ss,rr=levels(hist)
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


def show_quote(q, a):
    prev=q.get('prev',np.nan); price=a['price']; ch=price-prev if np.isfinite(prev) else np.nan; pct=ch/prev*100 if np.isfinite(ch) and prev else np.nan
    c=st.columns(6); c[0].metric('現價',f'${price:.2f}',f'{pct:+.2f}%' if np.isfinite(pct) else None); c[1].metric('開盤',f"${q.get('open',np.nan):.2f}" if np.isfinite(q.get('open',np.nan)) else '—'); c[2].metric('最高',f"${q.get('high',np.nan):.2f}" if np.isfinite(q.get('high',np.nan)) else '—'); c[3].metric('最低',f"${q.get('low',np.nan):.2f}" if np.isfinite(q.get('low',np.nan)) else '—'); c[4].metric('S1',f"${a['s1']:.2f}" if np.isfinite(a['s1']) else '—'); c[5].metric('R1',f"${a['r1']:.2f}" if np.isfinite(a['r1']) else '—')
    st.caption(f"行情來源：{q.get('source','—')}｜最後更新：{q.get('time','—')}｜美股 Session.ALL")
    if np.isfinite(q.get('overnight_change_rate',np.nan)):
        st.caption(f"Overnight 漲跌幅：{q['overnight_change_rate']:+.2f}%｜Overnight 成交量：{q.get('overnight_volume','—')}")


st.markdown('<div class="hero"><h1>📈 US Stock Watch V8</h1><div class="muted">Futu OpenD 即時行情 × 美股 Session.ALL × K線 × 自動支撐壓力 × 自動選股 × 回測</div></div>', unsafe_allow_html=True)

with st.sidebar:
    st.subheader('⚙️ 富途行情設定')
    st.caption('Futu API 已放寬開戶限制：可用富途牛牛號／註冊手機或 Email 登入 OpenD；首次使用需完成 API 問卷與協議確認。')
    st.write(f'OpenD：`{FUTU_HOST}:{FUTU_PORT}`')
    st.write(f'Futu Python API：{"已安裝" if FUTU_IMPORT_OK else "未安裝"}')
    if st.button('🔌 測試 Futu OpenD'):
        futu_health.clear()
    health = futu_health()
    if health['ready']:
        st.success('🟢 Futu 即時行情：已連線')
        st.caption('OpenD：READY｜Quote：已登入｜Session.ALL 可用')
    elif health['tcp'] and health['api']:
        st.warning(f"🟡 Futu 已連線，但狀態尚未 READY：{health['message']}")
    else:
        st.error(f"🔴 Futu 尚未連線：{health['message']}")
    st.caption('V8.1 單機版預設：網站與 Futu OpenD 在同一台電腦，使用 127.0.0.1:11111。請先登入並保持 Futu OpenD 開啟。')

symbol=st.text_input('🔎 輸入美股代碼',value=st.session_state.get('symbol','NVDA'),placeholder='NVDA / AAPL / TSLA').strip().upper(); st.session_state['symbol']=symbol
interval=st.selectbox('K線週期',['1d','60m','30m','15m','5m'],index=0,format_func=lambda x:{'1d':'日K','60m':'60分鐘','30m':'30分鐘','15m':'15分鐘','5m':'5分鐘'}[x])
if not symbol: st.stop()

# Only call Futu when the user has explicitly enabled it in deployment secrets.
with st.spinner('載入 K 線與即時行情…'):
    a=analyze(symbol,interval)

if a is None:
    st.error('找不到行情。請確認股票代碼，以及 Futu OpenD 已開啟、已登入並顯示 READY。若 Futu 暫時無資料，技術分析會嘗試使用 Yahoo 歷史資料備援。')
else:
    q=a.get('quote') or {}
    tabs=st.tabs(['📺 看盤','🧠 技術分析','🚀 自動選股','📊 回測'])
    with tabs[0]:
        if q: show_quote(q,a)
        else:
            st.warning(f"即時行情目前無法取得：{a.get('quote_error','未知錯誤')}。技術分析仍可正常使用。")
            st.metric('最近 K 線收盤',f"${a['price']:.2f}")
        chart(a['df'],a['supports'],a['resists'])
        st.caption('支撐/壓力由歷史價格轉折與反覆反應自動聚類，不代表未來一定反轉。')

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
                    z=analyze(s,'1d')
                    if not z: continue
                    dd=z['df'].iloc[-1]; dist=(z['price']-z['s1'])/z['price']*100 if np.isfinite(z['s1']) and z['price'] else np.nan; volr=dd['Volume']/dd['VolMA20'] if np.isfinite(dd['VolMA20']) and dd['VolMA20'] else np.nan
                    if np.isfinite(z['rr']) and z['rr']>=min_rr and np.isfinite(dist) and dist<=max_dist and np.isfinite(volr) and volr>=min_vol and (not only_bull or z['trend']=='多頭'):
                        rows.append({'股票':s,'價格':z['price'],'S1':z['s1'],'R1':z['r1'],'距支撐%':dist,'量比':volr,'R/R':z['rr'],'趨勢':z['trend']})
                except Exception as e: continue
            st.session_state['scan']=pd.DataFrame(rows)
        if 'scan' in st.session_state: st.dataframe(st.session_state['scan'],hide_index=True,use_container_width=True)

    with tabs[3]:
        st.subheader('📊 歷史條件回測')
        hold=st.number_input('最多持有交易日',1,60,10,1); target_r=st.number_input('目標 R',0.5,10.0,2.0,0.5); min_samples=st.number_input('最低樣本數',5,1000,30,5)
        if st.button('開始回測',type='primary'):
            bt=backtest(a['df'].copy(),hold,target_r)
            if len(bt)<min_samples: st.warning(f'有效樣本只有 {len(bt)} 筆，低於最低樣本數 {min_samples}；不顯示勝率結論。')
            st.dataframe(bt.tail(100),hide_index=True,use_container_width=True)

st.divider(); st.caption('V8 資料架構：Futu OpenD 為即時行情/K線來源；Yahoo 僅作為歷史資料備援。技術分析與回測不等於投資建議。')
