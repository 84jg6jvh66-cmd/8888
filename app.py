import io,re
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np,pandas as pd,requests,streamlit as st,yfinance as yf
st.set_page_config(page_title='US Stock Expectancy V4',page_icon='📈',layout='wide',initial_sidebar_state='collapsed')
st.markdown('''<style>.block-container{padding:1rem 1rem 2rem;max-width:1250px}@media(max-width:700px){.block-container{padding:.65rem .5rem 1.5rem}.stButton button{width:100%;min-height:48px;font-size:16px}.stDownloadButton button{width:100%;min-height:46px}}[data-testid="stMetricValue"]{font-size:1.2rem}</style>''',unsafe_allow_html=True)
UA={'User-Agent':'Mozilla/5.0 (compatible; USStockExpectancy/4.0)'}
@st.cache_data(ttl=3600,show_spinner=False)
def load_universe():
    frames=[]
    for u in ['https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt','https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt']:
        r=requests.get(u,headers=UA,timeout=20);r.raise_for_status();df=pd.read_csv(io.StringIO(r.text),sep='|',dtype=str)
        if 'Symbol' in df:
            df=df[df.Symbol.notna()&~df.Symbol.str.contains('File Creation|Symbol',na=False)].copy();df['Ticker']=df.Symbol;df['Exchange']='NASDAQ'
        else:
            df=df[df['ACT Symbol'].notna()&~df['ACT Symbol'].str.contains('File Creation|ACT Symbol',na=False)].copy();code=df.Exchange.fillna('');df=df[code.isin(['N','A'])].copy();df['Ticker']=df['ACT Symbol'];df['Exchange']=df.Exchange.map({'N':'NYSE','A':'NYSE American'})
        df['Security Name']=df.get('Security Name',df.get('Security Name',df.iloc[:,1]));frames.append(df[['Ticker','Exchange','Security Name']])
    out=pd.concat(frames,ignore_index=True);out.Ticker=out.Ticker.str.strip().str.upper().str.replace('.','-',regex=False);out=out.drop_duplicates('Ticker');bad=re.compile(r'(WARRANT|UNIT|RIGHT|NOTE|PREF|PREFERRED|DEBENTURE|BOND)',re.I);return out[~out['Security Name'].fillna('').str.contains(bad,na=False)].sort_values('Ticker').reset_index(drop=True)
@st.cache_data(ttl=900,show_spinner=False)
def data(ticker,period='5y'):
    try:
        d=yf.download(ticker,period=period,interval='1d',auto_adjust=True,progress=False,threads=False)
        if d is None or d.empty:return pd.DataFrame()
        if isinstance(d.columns,pd.MultiIndex):d=d.droplevel(1,axis=1)
        d.columns=[str(x).title() for x in d.columns];d=d[['Open','High','Low','Close','Volume']].dropna().copy()
        for n in [5,10,20,60,120]:d[f'MA{n}']=d.Close.rolling(n).mean()
        prev=d.Close.shift(1);tr=pd.concat([d.High-d.Low,(d.High-prev).abs(),(d.Low-prev).abs()],axis=1).max(axis=1);d['ATR14']=tr.rolling(14).mean();d['VolMA20']=d.Volume.rolling(20).mean();d['Ret20']=d.Close.pct_change(20);d['Ret60']=d.Close.pct_change(60);return d.dropna()
    except Exception:return pd.DataFrame()
def pivots(d,kind='low',end_i=None,right=3):
    end_i=len(d)-1 if end_i is None else min(end_i,len(d)-1);v=d.Low.values if kind=='low' else d.High.values;out=[]
    for p in range(3,end_i-right+1):
        w=v[p-3:p+4]
        if kind=='low' and v[p]==np.min(w) and v[p]<np.min(v[p-3:p]):out.append((p,float(v[p])))
        elif kind=='high' and v[p]==np.max(w) and v[p]>np.max(v[p+1:p+4]):out.append((p,float(v[p])))
    return out
def levels(d,tol=.012,end_i=None):
    i=len(d)-1 if end_i is None else end_i;p=float(d.Close.iloc[i])
    def cl(points):
        cs=[]
        for _,v in sorted(points,key=lambda x:x[1]):
            h=next((c for c in cs if abs(v-c[0])/c[0]<=tol),None)
            if h:h[1].append(v);h[0]=float(np.mean(h[1]))
            else:cs.append([v,[v]])
        return cs
    s=sorted([c[0] for c in cl(pivots(d,'low',i)) if c[0]<p],reverse=True);r=sorted([c[0] for c in cl(pivots(d,'high',i)) if c[0]>p]);return s,r
def analyze(ticker,near=.03,rrmin=1.5,tol=.012,period='5y'):
    d=data(ticker,period)
    if len(d)<130:return None
    x=d.iloc[-1];s,r=levels(d,tol);s1=s[0] if s else np.nan;r1=r[0] if r else np.nan;risk=(x.Close-s1)/x.Close if np.isfinite(s1) else np.nan;reward=(r1-x.Close)/x.Close if np.isfinite(r1) else np.nan;rr=reward/risk if np.isfinite(risk) and risk>0 and np.isfinite(reward) else np.nan
    return {'Ticker':ticker,'Price':float(x.Close),'S1':s1,'R1':r1,'Risk':risk,'Reward':reward,'RR':rr,'Trend':bool(x.Close>x.MA20>x.MA60>x.MA120),'Near':bool(np.isfinite(risk) and risk<=near),'RROK':bool(np.isfinite(rr) and rr>=rrmin),'Vol':float(x.Volume/x.VolMA20),'MA5':float(x.MA5),'MA10':float(x.MA10),'MA20':float(x.MA20),'MA60':float(x.MA60),'MA120':float(x.MA120),'Ret20':float(x.Ret20),'Ret60':float(x.Ret60)}
def backtest(d,near=.03,rr_mult=1.5,horizon=20,tol=.012):
    rows=[]
    for i in range(130,len(d)-horizon-1):
        h=d.iloc[:i+1];p=float(h.Close.iloc[-1]);s,r=levels(h,tol)
        if not s or not r or not(p>h.MA20.iloc[-1]>h.MA60.iloc[-1]>h.MA120.iloc[-1]):continue
        stop=float(s[0]);risk=(p-stop)/p
        if risk<=0 or risk>near:continue
        ent=float(d.Open.iloc[i+1])
        if ent<=stop:continue
        target=ent+rr_mult*(ent-stop);ex=None;out='timeout'
        for j in range(i+1,min(i+1+horizon,len(d))):
            lo,hi=float(d.Low.iloc[j]),float(d.High.iloc[j])
            if lo<=stop:ex=stop;out='loss';break
            if hi>=target:ex=target;out='win';break
        if ex is None:ex=float(d.Close.iloc[min(i+horizon,len(d)-1)])
        rows.append({'Date':d.index[i],'Entry':ent,'Stop':stop,'Target':target,'Exit':ex,'Return':ex/ent-1,'Outcome':out})
    return pd.DataFrame(rows)
def summary(bt):
    if bt.empty:return {}
    w=bt.Return>0;wr=float(w.mean());aw=float(bt.loc[w,'Return'].mean()) if w.any() else 0;al=float(-bt.loc[~w,'Return'].mean()) if (~w).any() else 0;eq=(1+bt.Return).cumprod();dd=float((eq/eq.cummax()-1).min());return {'samples':len(bt),'wr':wr,'aw':aw,'al':al,'exp':wr*aw-(1-wr)*al,'dd':dd}
st.title('📈 美股交易期望值 V4');st.caption('手機優先｜NASDAQ + NYSE 自動股票池｜條件掃描｜防未來洩漏回測｜交易期望值')
with st.sidebar:
    st.header('⚙️ V4 設定');period=st.selectbox('歷史資料',['2y','5y','10y','max'],1);near=st.slider('距離支撐 S1 最大',1,10,3)/100;rrmin=st.number_input('最低 Risk/Reward',.5,5.,1.5,.1);tol=st.slider('支撐/壓力聚類',.5,3.,1.2,.1)/100;horizon=st.slider('最長持有日',5,60,20,5);min_samples=st.number_input('回測最低樣本數',5,200,30,5)
single,scan,test=st.tabs(['🔎 單股','🚀 全市場掃描','📊 回測'])
with single:
    t=st.text_input('美股代號','AAPL').upper().strip();c1,c2=st.columns(2);entry=c1.number_input('計畫進場價',.01,100000.,250.,.01);capital=c2.number_input('投入資金',0.,100000000.,10000.,100.)
    if st.button('開始分析',type='primary'):
        a=analyze(t,near,rrmin,tol,period)
        if not a:st.error('找不到足夠歷史資料，請確認代號。')
        else:
            c=st.columns(4);c[0].metric('現價',f"${a['Price']:,.2f}");c[1].metric('S1',f"${a['S1']:,.2f}" if np.isfinite(a['S1']) else '—');c[2].metric('R1',f"${a['R1']:,.2f}" if np.isfinite(a['R1']) else '—');c[3].metric('R/R',f"1:{a['RR']:.2f}" if np.isfinite(a['RR']) else '—');c=st.columns(4);c[0].metric('下行風險',f"{a['Risk']*100:.2f}%" if np.isfinite(a['Risk']) else '—');c[1].metric('上行潛力',f"{a['Reward']*100:.2f}%" if np.isfinite(a['Reward']) else '—');c[2].metric('預估股數',f'{int(capital/entry):,}');c[3].metric('20日量能',f"{a['Vol']:.2f}x");st.write(f"均線：MA5 ${a['MA5']:.2f}｜MA10 ${a['MA10']:.2f}｜MA20 ${a['MA20']:.2f}｜MA60 ${a['MA60']:.2f}｜MA120 ${a['MA120']:.2f}");st.write(f"條件：趨勢 {'✓' if a['Trend'] else '✗'}｜接近支撐 {'✓' if a['Near'] else '✗'}｜R/R {'✓' if a['RROK'] else '✗'}｜20日報酬 {a['Ret20']*100:.1f}%｜60日報酬 {a['Ret60']*100:.1f}%");st.line_chart(data(t,period)[['Close','MA20','MA60','MA120']].tail(300))
with scan:
    st.subheader('🌎 NASDAQ + NYSE 自動掃描')
    try:
        uni=load_universe();c=st.columns(4);c[0].metric('股票池',f'{len(uni):,}');c[1].metric('NASDAQ',f'{(uni.Exchange=="NASDAQ").sum():,}');c[2].metric('NYSE',f'{(uni.Exchange.str.startswith("NYSE")).sum():,}');c[3].metric('資料週期',period)
    except Exception as e:uni=pd.DataFrame();st.error(f'無法取得股票清單：{e}')
    if not uni.empty:
        max_scan=st.slider('本次最多掃描檔數',50,min(3000,len(uni)),500,50);workers=st.slider('並行數',1,10,5);exs=st.multiselect('交易所',sorted(uni.Exchange.unique()),default=[x for x in ['NASDAQ','NYSE'] if x in uni.Exchange.unique()]);q=st.text_input('股票名稱關鍵字','');pool=uni[uni.Exchange.isin(exs)].copy();pool=pool[pool['Security Name'].str.contains(q,case=False,na=False)] if q else pool;pool=pool.head(max_scan);st.caption(f'本次掃描：{len(pool):,} 檔')
        if st.button('🚀 開始全市場掃描',type='primary'):
            out=[];bar=st.progress(0);fs={}
            with ThreadPoolExecutor(max_workers=workers) as ex:
                fs={ex.submit(analyze,s,near,rrmin,tol,period):s for s in pool.Ticker}
                for n,f in enumerate(as_completed(fs),1):
                    try:
                        z=f.result()
                        if z:out.append(z)
                    except Exception:pass
                    if n%10==0 or n==len(fs):bar.progress(n/len(fs))
            df=pd.DataFrame(out)
            if df.empty:st.warning('沒有取得有效行情資料。')
            else:
                df['Signal']=df.Trend&df.Near&df.RROK;hit=df[df.Signal].sort_values(['RR','Reward'],ascending=False);st.metric('符合條件',len(hit));st.dataframe(hit[['Ticker','Price','S1','R1','Risk','Reward','RR','Vol','MA20','MA60','MA120']],use_container_width=True,hide_index=True);st.download_button('下載掃描 CSV',hit.to_csv(index=False).encode('utf-8-sig'),'v4_market_scan.csv','text/csv')
with test:
    t2=st.text_input('回測代號','AAPL',key='bt').upper().strip()
    if st.button('執行回測',type='primary'):
        bt=backtest(data(t2,period),near,rrmin,horizon,tol);s=summary(bt)
        if bt.empty:st.warning('沒有符合條件的歷史案例。')
        else:
            if len(bt)<min_samples:st.warning(f'只有 {len(bt)} 個案例，低於最低樣本數 {min_samples}；數字僅供研究。')
            else:st.success(f'樣本數 {len(bt)} 已達最低門檻 {min_samples}。')
            c=st.columns(5);c[0].metric('案例',s['samples']);c[1].metric('勝率',f"{s['wr']*100:.2f}%");c[2].metric('平均獲利',f"{s['aw']*100:.2f}%");c[3].metric('平均虧損',f"{s['al']*100:.2f}%");c[4].metric('期望值',f"{s['exp']*100:.2f}%");st.metric('最大回撤',f"{s['dd']*100:.2f}%");st.dataframe(bt.tail(150),use_container_width=True,hide_index=True);st.download_button('下載回測 CSV',bt.to_csv(index=False).encode('utf-8-sig'),f'{t2}_v4_backtest.csv','text/csv')
st.divider();st.caption('V4 為研究工具，不是投資建議。歷史資料目前使用 Yahoo Finance / yfinance；大量正式部署建議改用有明確授權且穩定的行情 API，並加入滑價與交易成本。')
