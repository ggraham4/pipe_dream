# WO-63 pre-freeze probe: SI coverage of the CRSP cap2000/cap150 universe by exchange and year (no returns read).
import pandas as pd, numpy as np
W='/Users/ggraham/pipe_dream/final/data/wrds/'
sn=pd.read_parquet(W+'crsp/stocknames.parquet')
lk=pd.read_parquet(W+'comp/ccmxpf_lnkhist.parquet')
si=pd.read_parquet(W+'comp/sec_shortint_legacy_1996_2007.parquet'); si['datadate']=pd.to_datetime(si['datadate'])
cur=pd.read_parquet(W+'comp/sec_shortint_2006_2019.parquet'); cur['datadate']=pd.to_datetime(cur['datadate'])
si=pd.concat([si[si.datadate<'2006-10-01'],cur[cur.datadate>='2006-10-01']])
lk['linkdt']=pd.to_datetime(lk.linkdt); lk['linkenddt']=pd.to_datetime(lk.linkenddt).fillna(pd.Timestamp('2099-12-31'))
rows=[]
for y in range(1998,2010):
    d=pd.read_parquet(W+f'crsp/dsf_{y}.parquet',columns=['permno','date','prc','shrout'])
    d['date']=pd.to_datetime(d.date)
    # one probe date per year: last trading day of June
    dt=d.loc[d.date.dt.month==6,'date'].max(); x=d[(d.date==dt)&d.prc.notna()&(d.prc!=0)].copy()
    s=sn.copy(); s['namedt']=pd.to_datetime(s.namedt); s['nameenddt']=pd.to_datetime(s.nameenddt)
    s=s[(s.namedt<=dt)&(s.nameenddt>=dt)&s.shrcd.isin([10,11])&s.exchcd.isin([1,2,3])&(s.siccd!=6770)]
    x=x.merge(s[['permno','permco','exchcd']].drop_duplicates('permno'),on='permno')
    x['cap']=x.prc.abs()*x.shrout/1000; x['capco']=x.groupby('permco').cap.transform('sum')
    l=lk[(lk.linkdt<=dt)&(lk.linkenddt>=dt)][['gvkey','liid','lpermno']]
    sw=si[(si.datadate<=dt)&(si.datadate>=dt-pd.Timedelta(days=45))]
    have=set(sw.merge(l,left_on=['gvkey','iid'],right_on=['gvkey','liid']).lpermno.astype(int))
    x['si']=x.permno.isin(have)
    for tier,m in [('cap2000',(x.capco>=2000)&(x.prc.abs()>10)),('cap150',x.capco>=150)]:
        for ex,nm in [(1,'NYSE'),(2,'AMEX'),(3,'NASDAQ')]:
            g=x[m&(x.exchcd==ex)]
            rows.append(dict(date=str(dt.date()),tier=tier,exch=nm,n=len(g),si_cov=round(g.si.mean(),3) if len(g) else None))
r=pd.DataFrame(rows)
print(r.pivot_table(index='date',columns=['tier','exch'],values=['n','si_cov']).to_string())
r.to_csv('/Users/ggraham/pipe_dream/.claude/worktrees/agent-a13dd78d07eafa165/final/out/shortbook1998/prefreeze_si_coverage.csv',index=False)
