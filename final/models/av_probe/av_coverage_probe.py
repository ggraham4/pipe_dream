import os, json, time, urllib.request
import pandas as pd, numpy as np
K=os.environ["ALPHAVANTAGE_API_KEY"]; B="https://www.alphavantage.co/query"
def q(**p):
    p["apikey"]=K; u=B+"?"+"&".join(f"{k}={v}" for k,v in p.items())
    for a in range(4):
        try:
            r=json.loads(urllib.request.urlopen(u,timeout=60).read()); time.sleep(0.85)
            if "Information" in r: time.sleep(10); continue
            return r
        except Exception: time.sleep(3)
    return {}
def chain(t,d):
    x=q(function="HISTORICAL_OPTIONS",symbol=t,date=d).get("data") or []
    df=pd.DataFrame(x)
    if len(df):
        for c in ["strike","bid","ask","volume","open_interest"]: df[c]=pd.to_numeric(df[c],errors='coerce')
    return df
def implied_spot(df):
    df=df.assign(mid=(df.bid+df.ask)/2)
    ex=sorted(df.expiration.unique()); e=ex[1] if len(ex)>1 else ex[0]
    s=df[df.expiration==e].pivot_table(index='strike',columns='type',values='mid')
    if not {'call','put'}<=set(s.columns): return np.nan
    s=s.dropna()
    if s.empty: return np.nan
    k=(s.call-s.put).abs().idxmin(); return k+s.loc[k,'call']-s.loc[k,'put']
tm=pd.read_csv('/Users/ggraham/pipe_dream/final/data/sharadar/tickers_master.csv',usecols=['table','ticker','isdelisted','category'])
tm=tm[tm.table=='SEP'] if 'SEP' in set(tm.table) else tm
dl=tm.drop_duplicates('ticker').set_index('ticker').isdelisted
u=pd.read_parquet('/Users/ggraham/pipe_dream/final/data/sharadar/downcap_universe.parquet',
   columns=['date','ticker','closeunadj','marketcap','eligible_cap2000','eligible_cap500','eligible_cap150'])
u=u[u.eligible_cap150 & (pd.to_datetime(u.date)>='2008-01-02')]
u['tier']=np.where(u.eligible_cap2000,'cap2000',np.where(u.eligible_cap500,'cap500','cap150'))
u['dead']=u.ticker.map(dl).eq('Y')
rng=np.random.default_rng(0); samp=[]
for (tier,dead),g in u.groupby(['tier','dead']):
    tick=rng.choice(g.ticker.unique(),50,replace=False)
    gg=g[g.ticker.isin(tick)]
    samp.append(gg.groupby('ticker').sample(1,random_state=0))
samp=pd.concat(samp); print(samp.groupby(['tier','dead']).size(),flush=True)
out=[]
for i,row in enumerate(samp.itertuples()):
    d=str(row.date)[:10]
    df=chain(row.ticker,d)
    rec=dict(ticker=row.ticker,tier=row.tier,dead=row.dead,date=d,close_unadj=row.closeunadj,mcap=row.marketcap,n=len(df))
    if len(df):
        rec.update(implied_spot=implied_spot(df),totvol=df.volume.sum(),totoi=df.open_interest.sum(),
                   n_oi_pos=(df.open_interest>0).sum(),zero_bid=(df.bid==0).mean(),
                   med_spread=((df.ask-df.bid)/((df.ask+df.bid)/2))[df.bid>0].median())
    e=q(function="EARNINGS",symbol=row.ticker).get("quarterlyEarnings",[])
    rec['earn_n']=len(e)
    if e: rec['earn_covers_date']=min(z['fiscalDateEnding'] for z in e)<=d<=max(z['reportedDate'] for z in e)
    out.append(rec)
    if i%30==0: print(i,rec,flush=True)
pd.DataFrame(out).to_csv('coverage.csv',index=False); print("coverage done",flush=True)
# OI timing: consecutive days
oit={}
for t in ["AAPL","TXG"]:
    for d in ["2021-06-14","2021-06-15","2021-06-16","2021-06-17"]:
        oit[f"{t}_{d}"]=chain(t,d).to_dict('records')
json.dump(oit,open("oi_timing.json","w"),default=str)
# DoltHub overlap
ov={}
for t,d in [("AAPL","2021-06-15"),("MSFT","2023-03-08"),("SIVB","2022-06-15"),("AMD","2019-06-12")]:
    ov[f"{t}_{d}"]=chain(t,d).to_dict('records')
json.dump(ov,open("overlap.json","w"),default=str); print("all done")
