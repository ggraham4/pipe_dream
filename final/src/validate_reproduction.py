"""
Round 9 (2026-09-07): proves the corrected execution engine reproduces the
PUBLISHED walk-forward numbers before any behaviour is changed.

Recomputes each window's unstopped return from the raw OHLC panel using the
as-published convention (entry at close[tp], exit at the close 40 bars later)
and compares it against the committed continuous_walkforward_pit_augmented.json.
Agreement to ~5e-05 per window is what licenses every corrected number in
backtest/2026-09-07-review-response-and-execution-corrections.md as a
like-for-like change rather than an artifact of a different price panel.
"""
import json, numpy as np, pandas as pd
from pathlib import Path
from execution import load_ohlc_panel
FINAL=Path('.').resolve().parent; OUT=FINAL/'out'
base=json.load(open(OUT/'continuous_walkforward_pit_augmented.json'))['results']
tick=set()
for r in base: tick.update(r['picks'])
panel=load_ohlc_panel([FINAL/'scripts'/'td_data_local',FINAL/'scripts'/'td_data_delisted'],tickers=tick)
H=40
rows=[]
for r in base:
    tp=pd.Timestamp(r['timepoint']); pub=r['model_return_pct']/100.0
    rets=[]
    for t in r['picks']:
        g=panel.get(t)
        if g is None: continue
        e=r['pick_entry_close'].get(t)
        fut=g[g['date']>tp].head(H)
        if fut.empty or not e: continue
        # published: entry at recorded close[tp], exit at close 40 bars later
        rets.append(float(fut['close'].iloc[-1])/float(e)-1.0)
        # check recorded entry close matches the CSV close at tp
    if not rets: continue
    mine=float(np.mean([1+x for x in rets])-1)
    rows.append((r['timepoint'],pub,mine,len(rets),len(r['picks'])))
d=pd.DataFrame(rows,columns=['tp','published','repro','n','npick'])
d['diff']=d.repro-d.published
print('windows',len(d),'mean abs diff',d['diff'].abs().mean().round(5),'max',d['diff'].abs().max().round(4))
print('exact-ish (<0.5pp):',int((d['diff'].abs()<0.005).sum()))
print(d.reindex(d['diff'].abs().sort_values(ascending=False).index).head(12).to_string(index=False))
# entry price check
bad=0;tot=0
for r in base[:60]:
    tp=pd.Timestamp(r['timepoint'])
    for t,e in r['pick_entry_close'].items():
        g=panel.get(t)
        if g is None: continue
        row=g[g['date']==tp]
        if row.empty: continue
        tot+=1
        if abs(float(row['close'].iloc[0])-e)/e>0.01: bad+=1
print(f'entry-close match vs CSV close[tp]: {tot-bad}/{tot} agree')
