import os, json, time, urllib.request, datetime as dt
import pandas as pd, pyarrow.parquet as pq
T = "/Users/ggraham/.claude/jobs/13faca64/tmp/"
K = os.environ["ALPHAVANTAGE_API_KEY"]; B = "https://www.alphavantage.co/query"

# --- hard OI bound test: |dOI| <= vol on the day between the two snapshots
o = json.load(open(T + "oi_timing.json"))
days = ["2021-06-14", "2021-06-15", "2021-06-16", "2021-06-17"]
for t in ["AAPL", "TXG"]:
    fr = {}
    for d in days:
        df = pd.DataFrame(o[f"{t}_{d}"])
        df = df[df.expiration.astype(str) != "2021-06-18"]
        fr[d] = df.set_index("contractID")[["volume", "open_interest"]].astype(float)
    for a, b in zip(days, days[1:]):
        j = fr[a].join(fr[b], lsuffix="_a", rsuffix="_b", how="inner")
        doi = (j.open_interest_b - j.open_interest_a).abs()
        ch = doi > 0
        print(f"{t} {a}->{b} changed={ch.sum():4d}  violate |dOI|<=vol_a: {(doi > j.volume_a)[ch].mean():.1%}"
              f"   violate |dOI|<=vol_b: {(doi > j.volume_b)[ch].mean():.1%}")

# --- more DoltHub overlap days
f = "/Users/ggraham/pipe_dream/final/data/options_raw/expanded/option_chain_expanded_merged.parquet"
def q(**p):
    p["apikey"] = K; u = B + "?" + "&".join(f"{k}={v}" for k, v in p.items())
    r = json.loads(urllib.request.urlopen(u, timeout=60).read()); time.sleep(1.0); return r
for s, day in [("AAPL", None), ("AMD", None), ("ETSY", None)]:
    dts = pq.read_table(f, columns=["date"], filters=[("act_symbol", "==", s)]).to_pandas().date.unique()
    day = sorted(dts)[len(dts) // 3]
    t = pq.read_table(f, filters=[("act_symbol", "==", s), ("date", "==", day)]).to_pandas()
    a = pd.DataFrame(q(function="HISTORICAL_OPTIONS", symbol=s, date=str(day)).get("data") or [])
    if a.empty or t.empty: print(s, day, "AV", len(a), "DH", len(t)); continue
    for c in ["strike", "bid", "ask"]: a[c] = pd.to_numeric(a[c])
    a["cp"] = a.type.str[0].str.upper(); t["cp"] = t.call_put.str[0].str.upper()
    t["expiration"] = t.expiration.astype(str)
    m = a.merge(t, on=["expiration", "strike", "cp"], suffixes=("_av", "_dh"))
    ex = ((m.bid_av == m.bid_dh) & (m.ask_av == m.ask_dh)).mean()
    print(f"{s} {day}: AV {len(a)} DH {len(t)} matched {len(m)} exact bid&ask {ex:.0%}")
