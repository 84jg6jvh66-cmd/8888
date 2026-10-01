import os
from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

try:
    import futu as ft
except Exception:
    ft = None

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except Exception:
    go = None

st.set_page_config(page_title='US Stock Watch V6', page_icon='📈', layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container{padding:.55rem .8rem 2rem;max-width:1500px}.hero{padding:14px 16px;border-radius:16px;background:linear-gradient(135deg,#0f172a,#1e293b);color:#fff;margin-bottom:10px}.hero h1{margin:0;font-size:1.45rem}.muted{color:#94a3b8}.price{font-size:2.25rem;font-weight:800;line-height:1.05}.up{color:#ef4444}.down{color:#22c55e}.card{padding:12px;border:1px solid #334155;border-radius:14px;background:#0b1220}.small{font-size:.82rem;color:#94a3b8}@media(max-width:700px){.block-container{padding:.35rem}.price{font-size:1.9rem}.stButton button{min-height:44px;width:100%}.stTabs [data-baseweb="tab"]{font-size:.85rem}}
</style>''', unsafe_allow_html=True)

def secret(name, default):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

FUTU_HOST=os.getenv('FUTU_HOST', secret('FUTU_HOST','127.0.0.1'))
FUTU_PORT=int(os.getenv('FUTU_PORT', secret('FUTU_PORT',11111)))
FUTU_ENABLED=str(os.getenv('FUTU_ENABLED', secret('FUTU_ENABLED','false'))).lower() in ('1','true','yes','on')

@st.cache_data(ttl=60, show_spinner=False)
def yf_history(symbol, period='1y', interval='1d'):
    try:
        df=yf.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False, threads=False)
        if isinstance(df.columns,pd.MultiIndex): df=df.xs(symbol, axis=1, level=1)
        df=df.rename(columns=str.title)
        return df.dropna(subset=['Open','High','Low','Close']).copy()
    except Exception:
        return pd.DataFrame()

class FutuProvider:
    def __init__(self): self.ctx=None
    def available(self): return ft is not None and FUTU_ENABLED
    def connect(self):
        if ft is None or not FUTU_ENABLED:return False
        try:
            self.ctx=ft.OpenQuoteContext(host=FUTU_HOST,port=FUTU_PORT)
            return True
        except Exception:return False
    def close(self):
        try:
            if self.ctx:self.ctx.close()
        except Exception:pass
    def quote(self,symbol):
        if not self.ctx and not self.connect(): return None
        code='US.'+symbol.upper()
        try:
            ret,data=self.ctx.get_stock_quote([code])
            if ret!=ft.RET_OK or data.empty:return None
            r=data.iloc[0]
            return {'price':float(r.get('last_price',np.nan)),'open':float(r.get('open_price',np.nan)),'high':float(r.get('high_price',np.nan)),'low':float(r.get('low_price',np.nan)),'volume':float(r.get('volume',np.nan)),'prev':float(r.get('last_close',np.nan)),'time':str(r.get('data_time','')),'source':'Futu API'}
        except Exception:return None
    def kline(self,symbol,ktype='K_DAY',num=500):
        if not self.ctx and not self.connect(): return pd.DataFrame()
        code='US.'+symbol.upper(); kt=getattr(ft.KLType,ktype,ft.KLType.K_DAY)
        try:
            ret,data=self.ctx.get_cur_kline(code,num,kt,ft.AuType.QFQ)
            if ret!=ft.RET_OK:return pd.DataFrame()
            d=data.rename(columns={'time_key':'Date','open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'})
            d['Date']=pd.to_datetime(d['Date']); d=d.set_index('Date')
            return d[['Open','High','Low','Close','Volume']].copy()
        except Exception:return pd.DataFrame()

provider=FutuProvider()

def add_indicators(df):
    d=df.copy()
    for n in [5,10,20,60,120]: d[f'MA{n}']=d['Close'].rolling(n).mean()
    tr=pd.concat([d['High']-d['Low'],(d['High']-d['Close'].shift()).abs(),(d['Low']-d['Close'].shift()).abs()],axis=1).max(axis=1)
    d['ATR14']=tr.rolling(14).mean(); d['VolMA20']=d['Volume'].rolling(20).mean()
    delta=d['Close'].diff(); gain=delta.clip(lower=0).rolling(14).mean(); loss=(-delta.clip(upper=0)).rolling(14).mean(); rs=gain/loss.replace(0,np.nan); d['RSI14']=100-(100/(1+rs))
    ema12=d['Close'].ewm(span=12,adjust=False).mean(); ema26=d['Close'].ewm(span=26,adjust=False).mean(); d['MACD']=ema12-ema26; d['MACDSignal']=d['MACD'].ewm(span=9,adjust=False).mean()
    return d

def levels(df,lookback=180,tolerance=0.012):
    d=df.tail(lookback).copy(); hi=d['High'].values; lo=d['Low'].values
    piv=[]
    for i in range(2,len(d)-2):
        if hi[i]>=hi[i-2:i+3].max(): piv.append(('R',float(hi[i])))
        if lo[i]<=lo[i-2:i+3].min(): piv.append(('S',float(lo[i])))
    if not piv:return [],[]
    clusters=[]
    for typ,p in sorted(piv,key=lambda x:x[1]):
        placed=False
        for c in clusters:
            if abs(p-c['price'])/c['price']<=tolerance and typ==c['type']:
                c['prices'].append(p); c['price']=float(np.mean(c['prices'])); c['touches']+=1; placed=True; break
        if not placed: clusters.append({'type':typ,'price':p,'prices':[p],'touches':1})
    price=float(d['Close'].iloc[-1]); ss=[c for c in clusters if c['type']=='S' and c['price']<price]; rr=[c for c in clusters if c['type']=='R' and c['price']>price]
    ss=sorted(ss,key=lambda c:(-c['touches'],abs(price-c['price'])))[:3]; rr=sorted(rr,key=lambda c:(-c['touches'],abs(price-c['price'])))[:3]
    return sorted(ss,key=lambda c:c['price'],reverse=True),sorted(rr,key=lambda c:c['price'])

def chart(df,supports,resists,symbol):
    if go is None:return
    d=df.tail(220); fig=make_subplots(rows=2,cols=1,shared_xaxes=True,row_heights=[.78,.22],vertical_spacing=.03)
    fig.add_trace(go.Candlestick(x=d.index,open=d.Open,high=d.High,low=d.Low,close=d.Close,name='K線'),row=1,col=1)
    for n in [20,60,120]:
        if f'MA{n}' in d: fig.add_trace(go.Scatter(x=d.index,y=d[f'MA{n}'],name=f'MA{n}',mode='lines'),row=1,col=1)
    for c in supports:
        fig.add_hline(y=c['price'],line_dash='dot',annotation_text=f"S {c['price']:.2f} ×{c['touches']}",row=1,col=1)
    for c in resists:
        fig.add_hline(y=c['price'],line_dash='dot',annotation_text=f"R {c['price']:.2f} ×{c['touches']}",row=1,col=1)
    fig.add_trace(go.Bar(x=d.index,y=d.Volume,name='成交量'),row=2,col=1)
    fig.update_layout(height=650,margin=dict(l=10,r=10,t=25,b=10),xaxis_rangeslider_visible=False,legend_orientation='h',template='plotly_dark')
    st.plotly_chart(fig,use_container_width=True,config={'displaylogo':False,'scrollZoom':True})

@st.cache_data(ttl=30, show_spinner=False)
def cached_analysis(symbol):
    # Fast path: historical data first, so the screen can render even when OpenD is not reachable.
    df=yf_history(symbol,'1y','1d')
    if df.empty and FUTU_ENABLED:
        df=provider.kline(symbol,'K_DAY',500)
    if df.empty:return None
    df=add_indicators(df); ss,rr=levels(df)
    price=float(df['Close'].iloc[-1]); s1=ss[0]['price'] if ss else np.nan; r1=rr[0]['price'] if rr else np.nan
    risk=price-s1 if np.isfinite(s1) else np.nan; reward=r1-price if np.isfinite(r1) else np.nan
    rr_ratio=reward/risk if risk>0 and reward>0 else np.nan
    trend='多頭' if df['MA20'].iloc[-1]>df['MA60'].iloc[-1]>df['MA120'].iloc[-1] else ('空頭' if df['MA20'].iloc[-1]<df['MA60'].iloc[-1]<df['MA120'].iloc[-1] else '盤整')
    return {'df':df,'supports':ss,'resists':rr,'price':price,'s1':s1,'r1':r1,'rr':rr_ratio,'trend':trend}

def analyze(symbol,entry=None):
    base=cached_analysis(symbol)
    if base is None:return None
    q=None
    # Only call Futu when explicitly enabled; this prevents a missing OpenD connection from blocking the UI.
    if FUTU_ENABLED:
        q=provider.quote(symbol)
        if q and np.isfinite(q.get('price',np.nan)):
            base['price']=float(q['price'])
    base['symbol']=symbol; base['quote']=q
    return base

st.markdown('<div class="hero"><h1>📈 US Stock Watch V6</h1><div class="muted">富途行情介面 × K線技術分析 × 自動支撐壓力 × 自動選股</div></div>',unsafe_allow_html=True)

symbol=st.text_input('🔎 輸入美股代碼',value=st.session_state.get('symbol','NVDA'),placeholder='例如 NVDA / AAPL / TSLA').strip().upper()
st.session_state['symbol']=symbol

with st.spinner('正在載入 K 線資料…'):
    a=analyze(symbol)

if a is None:
    st.error('找不到這支股票的行情資料。若要使用富途即時行情，請先啟動 OpenD 並登入富途帳號；未連線時系統會嘗試使用 Yahoo 歷史資料。')
else:
    q=a.get('quote') or {}
    if not isinstance(q, dict): q={}
    prev=q.get('prev', np.nan)
    ch=a['price']-prev if np.isfinite(prev) else np.nan
    pct=ch/prev*100 if np.isfinite(ch) and prev != 0 else np.nan
    tabs=st.tabs(['📺 看盤','🧠 技術分析','🚀 自動選股','📊 回測'])
    with tabs[0]:
        c1,c2,c3,c4,c5=st.columns(5)
        c1.metric('即時價格',f"${a['price']:.2f}",f"{pct:+.2f}%" if np.isfinite(pct) else None)
        c2.metric('支撐 S1',f"${a['s1']:.2f}" if np.isfinite(a['s1']) else '—')
        c3.metric('壓力 R1',f"${a['r1']:.2f}" if np.isfinite(a['r1']) else '—')
        c4.metric('Risk / Reward',f"1 : {a['rr']:.2f}" if np.isfinite(a['rr']) else '—')
        c5.metric('趨勢',a['trend'])
        st.caption(f"行情來源：{q.get('source', 'Yahoo 歷史/備援')}｜時間：{q.get('time', '—')}")
        chart(a['df'],a['supports'],a['resists'],symbol)
        st.caption('K線上的 S/R 為系統依歷史價格反覆反應自動聚類出的區域；不是保證未來價格會在該處反轉。')

    with tabs[1]:
        d=a['df'].iloc[-1]
        cols=st.columns(6)
        for col,n in zip(cols,['MA5','MA10','MA20','MA60','MA120','RSI14']): col.metric(n,f"{d[n]:.2f}" if np.isfinite(d[n]) else '—')
        st.subheader('自動支撐 / 壓力')
        x,y=st.columns(2)
        with x:
            st.markdown('**支撐區**')
            st.dataframe(pd.DataFrame([{'價位':c['price'],'反應次數':c['touches']} for c in a['supports']]),hide_index=True,use_container_width=True)
        with y:
            st.markdown('**壓力區**')
            st.dataframe(pd.DataFrame([{'價位':c['price'],'反應次數':c['touches']} for c in a['resists']]),hide_index=True,use_container_width=True)
        st.subheader('MACD')
        st.line_chart(a['df'][['MACD','MACDSignal']].tail(120))

    with tabs[2]:
        st.subheader('🚀 自動選股條件')
        col=st.columns(4)
        min_rr=col[0].number_input('最低 R/R',1.0,10.0,2.0,.5)
        max_dist=col[1].number_input('距離支撐最大 %',1.0,30.0,6.0,1.0)
        min_vol=col[2].number_input('量 / 20日均量 ≥',0.5,10.0,1.2,.1)
        only_bull=col[3].checkbox('只看多頭排列',True)
        symbols=st.text_area('掃描股票（每行或逗號分隔）','NVDA\nAAPL\nMSFT\nAMZN\nMETA\nTSLA\nAMD\nAVGO\nPLTR\nGOOGL').replace(',','\n')
        if st.button('開始掃描',type='primary'):
            rows=[]
            for s in [x.strip().upper() for x in symbols.splitlines() if x.strip()]:
                try:
                    z=analyze(s)
                    if not z: continue
                    dd=z['df'].iloc[-1]
                    dist=(z['price']-z['s1'])/z['price']*100 if np.isfinite(z['s1']) and z['price'] else np.nan
                    volr=dd['Volume']/dd['VolMA20'] if np.isfinite(dd['VolMA20']) and dd['VolMA20'] else np.nan
                    ok_rr=np.isfinite(z['rr']) and z['rr']>=min_rr
                    ok_dist=np.isfinite(dist) and dist<=max_dist
                    ok_vol=np.isfinite(volr) and volr>=min_vol
                    ok_tr=(z['trend']=='多頭') if only_bull else True
                    if ok_rr and ok_dist and ok_vol and ok_tr:
                        rows.append({'股票':s,'價格':z['price'],'S1':z['s1'],'R1':z['r1'],'距支撐%':dist,'量比':volr,'R/R':z['rr'],'趨勢':z['trend']})
                except Exception:
                    continue
            out=pd.DataFrame(rows)
            if not out.empty and 'R/R' in out.columns: out=out.sort_values('R/R',ascending=False)
            st.session_state['scan']=out
        if 'scan' in st.session_state:
            st.dataframe(st.session_state['scan'],hide_index=True,use_container_width=True)

    with tabs[3]:
        st.subheader('📊 歷史條件回測')
        entry=st.number_input('假設進場價',min_value=0.01,value=float(a['price']),step=.1)
        hold=st.number_input('最多持有交易日',1,60,10,1)
        target_r=st.number_input('目標 R',0.5,10.0,2.0,0.5)
        if np.isfinite(a['s1']): st.write(f"目前自動停損參考：**${a['s1']:.2f}**")
        if st.button('開始回測',type='primary'):
            d=a['df'].copy()
            trades=[]
            for i in range(len(d)-2):
                hist=d.iloc[:i+1]
                ss,rr=levels(hist)
                if not ss or not rr: continue
                e=float(d['Open'].iloc[i+1])
                stop=float(ss[0]['price']); target=e+(e-stop)*target_r
                if not (stop < e < target): continue
                end=min(i+1+int(hold),len(d)-1); outcome=None; exit_price=None; exit_idx=end
                for j in range(i+1,end+1):
                    lo=float(d['Low'].iloc[j]); hi=float(d['High'].iloc[j])
                    if lo<=stop and hi>=target:
                        outcome='先觸及停損（保守）'; exit_price=stop; exit_idx=j; break
                    if lo<=stop:
                        outcome='停損'; exit_price=stop; exit_idx=j; break
                    if hi>=target:
                        outcome='停利'; exit_price=target; exit_idx=j; break
                if exit_price is None:
                    exit_price=float(d['Close'].iloc[exit_idx]); outcome='持有期結束'
                ret=(exit_price-e)/e*100
                trades.append({'進場日':str(d.index[i+1].date()),'進場':e,'停損':stop,'目標':target,'出場日':str(d.index[exit_idx].date()),'出場':exit_price,'報酬%':ret,'結果':outcome})
            bt=pd.DataFrame(trades)
            if bt.empty:
                st.warning('目前條件沒有形成可回測的有效樣本。請增加歷史期間或降低條件限制。')
            else:
                wins=bt['報酬%']>0; losses=bt['報酬%']<0
                st.metric('樣本數',len(bt)); c1,c2,c3,c4=st.columns(4)
                c1.metric('勝率',f"{wins.mean()*100:.1f}%")
                c2.metric('平均盈利',f"{bt.loc[wins,'報酬%'].mean():.2f}%" if wins.any() else '—')
                c3.metric('平均虧損',f"{bt.loc[losses,'報酬%'].mean():.2f}%" if losses.any() else '—')
                c4.metric('平均報酬',f"{bt['報酬%'].mean():.2f}%")
                st.dataframe(bt.tail(100),hide_index=True,use_container_width=True)
        st.caption('回測只使用當時已知的歷史 K 線來尋找支撐/壓力；同一根 K 線同時觸及停損與停利時採保守的停損處理。歷史結果不代表未來。')

with st.expander('⚙️ 富途 OpenD 連線設定'):
    st.write(f'目前設定：{FUTU_HOST}:{FUTU_PORT}')
    st.write(f'富途即時行情：{"已啟用" if FUTU_ENABLED else "未啟用（預設快速模式）"}。要啟用請設定 FUTU_ENABLED=true，並在伺服器上啟動 OpenD、登入富途帳號。未啟用時先用 Yahoo 歷史資料快速畫出 K 線與技術分析，不會卡在 OpenD 連線。')
