import os, time
from datetime import datetime, timezone
import requests
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf

st.set_page_config(page_title='US Stock Expectancy V5', page_icon='📈', layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container{padding:.8rem 1rem 2rem;max-width:1400px}.hero{padding:18px;border-radius:18px;background:linear-gradient(135deg,#111827,#1f2937);color:white;margin-bottom:12px}.price{font-size:2.5rem;font-weight:800}.sub{opacity:.75}@media(max-width:700px){.block-container{padding:.55rem}.price{font-size:2rem}.stButton button{width:100%;min-height:46px}}
[data-testid="stMetricValue"]{font-size:1.18rem}
</style>''', unsafe_allow_html=True)

ALPACA_KEY = st.secrets.get('ALPACA_API_KEY', os.getenv('ALPACA_API_KEY',''))
ALPACA_SECRET = st.secrets.get('ALPACA_API_SECRET', os.getenv('ALPACA_API_SECRET',''))

@st.cache_data(ttl=30, show_spinner=False)
def alpaca_snapshot(symbol, feed='iex'):
    if not (ALPACA_KEY and ALPACA_SECRET): return None
    h={'APCA-API-KEY-ID':ALPACA_KEY,'APCA-API-SECRET-KEY':ALPACA_SECRET}
    try:
        u=f'https://data.alpaca.markets/v2/stocks/{symbol}/snapshot'
        r=requests.get(u,headers=h,params={'feed':feed},timeout=8); r.raise_for_status(); z=r.json()
        return z
    except Exception: return None

def quote_from_snapshot(z):
    if not z:return None
    t=z.get('latestTrade') or {}; q=z.get('latestQuote') or {}; d=z.get('dailyBar') or {}; p=z.get('prevDailyBar') or {}
    price=float(t.get('p') or d.get('c') or q.get('ap') or 0)
    prev=float(p.get('c') or 0); change=price-prev if prev else np.nan
    return {'price':price,'change':change,'pct':change/prev*100 if prev else np.nan,'bid':q.get('bp'),'ask':q.get('ap'),'open':d.get('o'),'high':d.get('h'),'low':d.get('l'),'volume':d.get('v'),'prev':prev,'ts':t.get('t')}

@st.cache_data(ttl=20, show_spinner=False)
def live_quote(symbol, session='regular'):
    # Prefer Alpaca. Overnight/extended feeds can be selected by the user.
    if ALPACA_KEY and ALPACA_SECRET:
        feed={'regular':'iex','extended':'iex','overnight':'overnight'}.get(session,'iex')
        q=quote_from_snapshot(alpaca_snapshot(symbol,feed));
        if q:return q|{'source':'Alpaca','feed':feed}
    try:
        z=yf.Ticker(symbol).fast_info
        p=float(z.get('last_price',0)); prev=float(z.get('previous_close',0))
        return {'price':p,'change':p-prev,'pct':(p-prev)/prev*100 if prev else np.nan,'bid':None,'ask':None,'open':z.get('open'),'high':z.get('day_high'),'low':z.get('day_low'),'volume':z.get('last_volume'),'prev':prev,'ts':datetime.now(timezone.utc).isoformat(),'source':'Yahoo fallback','feed':'delayed/availability varies'}
    except Exception:return None

@st.cache_data(ttl=900, show_spinner=False)
def data(ticker, period='5y'):
    try:
        d=yf.download(ticker,period=period,interval='1d',auto_adjust=True,progress=False,threads=False)
        if d is None or d.empty:return pd.DataFrame()
        if isinstance(d.columns,pd.MultiIndex):d.columns=d.columns.get_level_values(0)
        d.columns=[str(x).title() for x in d.columns]; d=d[['Open','High','Low','Close','Volume']].dropna().copy()
        for n in [5,10,20,60,120]:d[f'MA{n}']=d.Close.rolling(n).mean()
        prev=d.Close.shift(1); tr=pd.concat([d.High-d.Low,(d.High-prev).abs(),(d.Low-prev).abs()],axis=1).max(axis=1)
        d['ATR14']=tr.rolling(14).mean(); d['VolMA20']=d.Volume.rolling(20).mean(); return d.dropna()
    except Exception:return pd.DataFrame()

def piv(s,kind):
    a=s.values;o=[]
    for i in range(3,len(a)-3):
        w=a[i-3:i+4]
        if kind=='low' and a[i]==min(w) and a[i]<min(a[i-3:i]):o.append((i,float(a[i])))
        if kind=='high' and a[i]==max(w) and a[i]>max(a[i+1:i+4]):o.append((i,float(a[i])))
    return o

def levels(d,tol=.012):
    p=float(d.Close.iloc[-1])
    def cluster(points):
        cs=[]
        for _,v in sorted(points,key=lambda x:x[1]):
            hit=next((c for c in cs if abs(v-c[0])/c[0]<=tol),None)
            if hit:hit[1].append(v);hit[0]=float(np.mean(hit[1]))
            else:cs.append([v,[v]])
        return cs
    s=sorted([c[0] for c in cluster(piv(d.Low,'low')) if c[0]<p],reverse=True); r=sorted([c[0] for c in cluster(piv(d.High,'high')) if c[0]>p])
    return s,r

def analyze(ticker,near=.03,rrmin=1.5,tol=.012):
    d=data(ticker)
    if len(d)<130:return None
    x=d.iloc[-1];s,r=levels(d,tol);s1=s[0] if s else np.nan;r1=r[0] if r else np.nan
    risk=(x.Close-s1)/x.Close if np.isfinite(s1) else np.nan; reward=(r1-x.Close)/x.Close if np.isfinite(r1) else np.nan
    rr=reward/risk if np.isfinite(risk) and risk>0 and np.isfinite(reward) else np.nan
    return {'Ticker':ticker,'Price':float(x.Close),'S1':s1,'R1':r1,'Risk':risk,'Reward':reward,'RR':rr,'Trend':bool(x.Close>x.MA20>x.MA60>x.MA120),'Near':bool(np.isfinite(risk) and risk<=near),'RROK':bool(np.isfinite(rr) and rr>=rrmin),'Vol':float(x.Volume/x.VolMA20),'MA20':float(x.MA20),'MA60':float(x.MA60),'MA120':float(x.MA120)}

def backtest(d,near=.03,rr=1.5,horizon=20):
    rows=[]
    for i in range(130,len(d)-horizon-1):
        h=d.iloc[:i+1];p=float(h.Close.iloc[-1]);s,r=levels(h)
        if not s or not r or not(p>h.MA20.iloc[-1]>h.MA60.iloc[-1]>h.MA120.iloc[-1]):continue
        stop=s[0]
        if (p-stop)/p>near:continue
        ent=float(d.Open.iloc[i+1]);target=ent+rr*(ent-stop);ex=None;out='timeout'
        for j in range(i+1,min(i+1+horizon,len(d))):
            lo,hi=float(d.Low.iloc[j]),float(d.High.iloc[j])
            if lo<=stop:ex=stop;out='loss';break
            if hi>=target:ex=target;out='win';break
        if ex is None:ex=float(d.Close.iloc[min(i+horizon,len(d)-1)])
        rows.append({'Date':d.index[i],'Entry':ent,'Exit':ex,'Return':ex/ent-1,'Outcome':out})
    return pd.DataFrame(rows)

st.markdown('<div class="hero"><h1>📈 美股交易期望值 V5</h1><div class="sub">即時／延遲行情 · 24/5 時段架構 · 技術分析 · 掃描 · 回測 · 期望值</div></div>',unsafe_allow_html=True)
with st.sidebar:
    st.header('設定'); period=st.selectbox('歷史資料',['2y','5y','10y','max'],1); near=st.slider('距離支撐 S1 最大',1,10,3)/100; rrmin=st.number_input('最低 Risk/Reward',.5,5.,1.5,.1); tol=st.slider('支撐/壓力聚類',.5,3.,1.2,.1)/100; horizon=st.slider('最長持有日',5,60,20,5)
    st.divider(); st.caption('即時行情：Alpaca API 優先；未設定金鑰時使用 Yahoo fallback。')

tabs=st.tabs(['⚡ 即時行情','🔎 單股分析','🚀 全市場掃描','📊 回測'])

with tabs[0]:
    st.subheader('⚡ 即時行情中心')
    c1,c2,c3=st.columns([2,1,1]); symbol=c1.text_input('股票代號','AAPL',key='live').upper().strip(); session=c2.selectbox('行情時段',['regular','extended','overnight'],format_func=lambda x:{'regular':'正常盤','extended':'盤前／盤後','overnight':'隔夜 24/5'}[x]); refresh=c3.slider('刷新秒數',5,60,10)
    @st.fragment(run_every=f'{refresh}s')
    def live_panel():
        q=live_quote(symbol,session)
        if not q:st.error('目前無法取得行情。請設定 Alpaca API 金鑰。');return
        pct=q['pct']; arrow='▲' if pct>=0 else '▼'; cls='positive' if pct>=0 else 'negative'
        st.markdown(f'<div class="hero"><div class="sub">{symbol} · {q["source"]} · {q["feed"]}</div><div class="price">${q["price"]:,.2f}</div><div>{arrow} {q["change"]:+.2f} ({pct:+.2f}%)</div></div>',unsafe_allow_html=True)
        a,b,c,d,e,f=st.columns(6); a.metric('Bid',f'${q["bid"]:.2f}' if q['bid'] else '—');b.metric('Ask',f'${q["ask"]:.2f}' if q['ask'] else '—');c.metric('開盤',f'${q["open"]:.2f}' if q['open'] else '—');d.metric('最高',f'${q["high"]:.2f}' if q['high'] else '—');e.metric('最低',f'${q["low"]:.2f}' if q['low'] else '—');f.metric('成交量',f'{q["volume"]:,.0f}' if q['volume'] else '—')
        st.caption(f'更新：{q["ts"]} · 自動每 {refresh} 秒刷新')
    live_panel()
    st.info('24/5 模式依行情供應商的 overnight feed；不同方案可能有即時／延遲差異。')

with tabs[1]:
    t=st.text_input('美股代號','AAPL',key='single').upper().strip(); c1,c2=st.columns(2); entry=c1.number_input('計畫進場價',.01,100000.,250.,.01); capital=c2.number_input('投入資金',0.,100000000.,10000.,100.)
    if st.button('開始分析',type='primary',key='singlebtn'):
        a=analyze(t,near,rrmin,tol); q=live_quote(t,'regular')
        if not a:st.error('找不到足夠歷史資料。')
        else:
            price=q['price'] if q else a['Price']; cols=st.columns(5);cols[0].metric('即時現價',f'${price:,.2f}' if q else f'${a["Price"]:,.2f}');cols[1].metric('S1',f'${a["S1"]:,.2f}' if np.isfinite(a['S1']) else '—');cols[2].metric('R1',f'${a["R1"]:,.2f}' if np.isfinite(a['R1']) else '—');cols[3].metric('R/R',f'1:{a["RR"]:.2f}' if np.isfinite(a['RR']) else '—');cols[4].metric('即時漲跌',f'{q["pct"]:+.2f}%' if q else '—')
            shares=int(capital/entry);st.write(f'預估股數：{shares:,}｜MA20 ${a["MA20"]:.2f}｜MA60 ${a["MA60"]:.2f}｜MA120 ${a["MA120"]:.2f}｜20日量能 {a["Vol"]:.2f}x');d=data(t,period);st.line_chart(d[['Close','MA20','MA60','MA120']].tail(250))

with tabs[2]:
    st.subheader('🚀 即時／技術掃描'); raw=st.text_area('股票清單（每行一檔）','AAPL\nMSFT\nNVDA\nAMZN\nMETA\nGOOGL\nTSLA\nAVGO\nAMD\nNFLX'); workers=st.slider('並行數',1,10,5,key='workers')
    if st.button('開始掃描',type='primary',key='scanbtn'):
        syms=list(dict.fromkeys(x.strip().upper() for x in raw.splitlines() if x.strip()));out=[];bar=st.progress(0)
        from concurrent.futures import ThreadPoolExecutor,as_completed
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fs={ex.submit(analyze,s,near,rrmin,tol):s for s in syms}
            for n,f in enumerate(as_completed(fs),1):
                try:
                    z=f.result()
                    if z:
                        q=live_quote(z['Ticker'],'regular'); z['LivePrice']=q['price'] if q else z['Price']; z['LivePct']=q['pct'] if q else np.nan;out.append(z)
                except Exception:pass
                bar.progress(n/len(fs))
        df=pd.DataFrame(out)
        if not df.empty:
            hit=df[df.Trend&df.Near&df.RROK].sort_values(['RR','Reward'],ascending=False);st.metric('符合技術條件',len(hit));st.dataframe(hit[['Ticker','LivePrice','LivePct','S1','R1','Risk','Reward','RR','Vol']],use_container_width=True,hide_index=True);st.download_button('下載 CSV',hit.to_csv(index=False).encode('utf-8-sig'),'v5_scan.csv','text/csv')
        else:st.warning('沒有有效資料。')

with tabs[3]:
    t2=st.text_input('回測代號','AAPL',key='bt').upper().strip()
    if st.button('執行回測',type='primary',key='btbtn'):
        d=data(t2,period);bt=backtest(d,near,rrmin,horizon)
        if bt.empty:st.warning('沒有符合條件的歷史案例。')
        else:
            w=bt.Return>0;wr=w.mean();aw=bt.loc[w,'Return'].mean() if w.any() else 0;al=-bt.loc[~w,'Return'].mean() if (~w).any() else 0;ex=wr*aw-(1-wr)*al;eq=(1+bt.Return).cumprod();dd=(eq/eq.cummax()-1).min();c=st.columns(5);c[0].metric('案例',len(bt));c[1].metric('勝率',f'{wr*100:.2f}%');c[2].metric('平均獲利',f'{aw*100:.2f}%');c[3].metric('平均虧損',f'{al*100:.2f}%');c[4].metric('期望值',f'{ex*100:.2f}%');st.metric('最大回撤',f'{dd*100:.2f}%');st.dataframe(bt.tail(100),use_container_width=True,hide_index=True);st.download_button('下載回測 CSV',bt.to_csv(index=False).encode('utf-8-sig'),f'{t2}_backtest.csv','text/csv')

st.divider();st.caption('V5：即時行情由 Alpaca 優先提供；未設定金鑰時保留 Yahoo fallback。即時資料的覆蓋範圍、延遲與費用取決於行情供應商方案。技術分析與回測僅供研究。')
