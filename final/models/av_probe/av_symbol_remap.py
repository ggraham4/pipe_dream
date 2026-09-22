"""Re-query uncovered coverage rows under the symbol the name traded as on that date."""
import os, json, time, urllib.request
import numpy as np, pandas as pd
K = os.environ["ALPHAVANTAGE_API_KEY"]; B = "https://www.alphavantage.co/query"
T = "/Users/ggraham/.claude/jobs/13faca64/tmp/"
S = "/Users/ggraham/pipe_dream/final/data/sharadar/"

def q(**p):
    p["apikey"] = K; u = B + "?" + "&".join(f"{k}={v}" for k, v in p.items())
    for _ in range(4):
        try:
            r = json.loads(urllib.request.urlopen(u, timeout=60).read()); time.sleep(0.85)
            if "Information" in r: time.sleep(10); continue
            return r
        except Exception: time.sleep(3)
    return {}

def implied_spot(x):
    df = pd.DataFrame(x)
    for c in ["strike", "bid", "ask"]: df[c] = pd.to_numeric(df[c], errors="coerce")
    df["mid"] = (df.bid + df.ask) / 2
    ex = sorted(df.expiration.unique()); e = ex[1] if len(ex) > 1 else ex[0]
    s = df[df.expiration == e].pivot_table(index="strike", columns="type", values="mid")
    if not {"call", "put"} <= set(s.columns): return np.nan
    s = s.dropna()
    if s.empty: return np.nan
    k = (s.call - s.put).abs().idxmin(); return k + s.loc[k, "call"] - s.loc[k, "put"]

a = pd.read_csv(S + "actions.csv")
chg = a[a.action == "tickerchangefrom"][["date", "ticker", "contraticker"]]
tm = pd.read_csv(S + "tickers_master.csv", usecols=["ticker", "relatedtickers"]).drop_duplicates("ticker").set_index("ticker")

def as_of_symbol(t, d):
    sym = t
    for _ in range(10):
        c = chg[(chg.ticker == sym) & (chg.date > d)].sort_values("date")
        if c.empty: break
        sym = c.contraticker.iloc[0]   # earliest change after d: symbol before it
    return sym

cov = pd.read_csv(T + "coverage.csv")
miss = cov[cov.n == 0]
out = []
for r in miss.itertuples():
    cands = []
    s = as_of_symbol(r.ticker, r.date)
    if s != r.ticker: cands.append(("actions", s))
    rel = tm.relatedtickers.get(r.ticker)
    if isinstance(rel, str):
        cands += [("related", x) for x in rel.split() if x and x != r.ticker]
    if r.ticker.endswith("Q") and len(r.ticker) >= 4: cands.append(("stripQ", r.ticker[:-1]))
    seen, hit = set(), None
    for src, c in cands:
        if c in seen: continue
        seen.add(c)
        x = q(function="HISTORICAL_OPTIONS", symbol=c, date=r.date).get("data") or []
        if x:
            sp = implied_spot(x)
            ok = abs(sp / r.close_unadj - 1) < 0.10 if r.close_unadj and sp == sp else False
            hit = dict(sym=c, src=src, n=len(x), implied_spot=sp, identity_ok=ok)
            if ok: break
    out.append(dict(ticker=r.ticker, tier=r.tier, dead=r.dead, date=r.date, close_unadj=r.close_unadj,
                    n_cands=len(seen), cands=" ".join(seen), **(hit or {})))
res = pd.DataFrame(out); res.to_csv(T + "remap.csv", index=False)
print(res.groupby(["tier", "dead"]).agg(missed=("ticker", "size"), had_cand=("n_cands", lambda s: (s > 0).sum()),
      recovered=("identity_ok", lambda s: s.fillna(False).astype(bool).sum())))
print(res[res.n_cands > 0].to_string())
