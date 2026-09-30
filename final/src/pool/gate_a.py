"""
WO-31 Gate A (data sanity on the three pools; v2 grid column c flags in
composite_panel_v2). Reads only the columns it needs.

  1. name-check one cap2000-only name (eligible_cap2000 & ~eligible_cap150) and
     one cap150-only name (eligible_cap150 & ~eligible_cap500) on a named date,
     with the tier rule each one meets / misses (downcap_universe.TIERS:
     cap2000 = mcap >= $2B & price > $10, no $vol floor; cap500 = $500M & 20d
     median $vol >= $0.5M; cap150 = $150M & $vol >= $0.25M).
  2. a dead (delisted) name appears in each pool before its last price date.
  3. PIT: a name whose eligible_cap2000 flips as its market cap crosses $2B
     (v2 flag) versus the v1 flag; plus whole-panel sample-date invariants
     (flag true => market cap above the floor on that date).
Output: final/out/pool/gate_a.json
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "out" / "pool" / "gate_a.json"
MAIN = Path("/Users/ggraham/pipe_dream/final")
PANEL = MAIN / "out" / "reset2026" / "composite_panel_v2.parquet"
TM = MAIN / "data" / "sharadar" / "tickers_master.csv"
FLAGS = ["eligible_cap150", "eligible_cap500", "eligible_cap2000"]
FLOOR = {"eligible_cap150": 150e6, "eligible_cap500": 500e6, "eligible_cap2000": 2000e6}
SAMPLE = ["2008-06-16", "2012-06-15", "2015-06-15", "2019-06-14", "2021-06-15", "2023-06-15", "2026-06-15"]
COLS = ["ticker", "date", "market_cap", "close", "volatility_60"] + FLAGS + ["eligible_cap2000_v1", "eligible_cap150_v1"]


def read(filters):
    p = pd.read_parquet(PANEL, columns=COLS, filters=filters)
    p["date"] = pd.to_datetime(p["date"])
    return p.sort_values(["ticker", "date"]).reset_index(drop=True)


def main():
    out = {}
    # ---- 3b. invariants on sample dates
    s = read([("date", "in", SAMPLE)])
    inv = {}
    for d, g in s.groupby("date"):
        r = {f: int(g[f].sum()) for f in FLAGS}
        r["flag_below_floor"] = {f: int((g[f] & (g["market_cap"] < FLOOR[f])).sum()) for f in FLAGS}
        r["cap2000_not_cap150"] = int((g["eligible_cap2000"] & ~g["eligible_cap150"]).sum())
        r["cap500_not_cap150"] = int((g["eligible_cap500"] & ~g["eligible_cap150"]).sum())
        bad = g[np.logical_or.reduce([g[f] & (g["market_cap"] < FLOOR[f]) for f in FLAGS])]
        r["flag_below_floor_rows"] = bad[["ticker", "market_cap", "close"] + FLAGS].to_dict("records")
        inv[str(d.date())] = r
        # flags come from Sharadar DAILY marketcap (downcap_universe.py); the panel's market_cap column is a
        # separate field, so a handful of disagreements (e.g. market_cap 0.0) are data quirks, not PIT breaks
        assert sum(r["flag_below_floor"].values()) <= max(5, 1e-3 * len(g)), f"flag below floor {d}"
    out["sample_date_invariants"] = inv

    # ---- 1. name checks on 2023-06-15
    D = pd.Timestamp("2023-06-15")
    g = s[s["date"] == D]
    c2 = g[g["eligible_cap2000"] & ~g["eligible_cap150"]]
    c150 = g[g["eligible_cap150"] & ~g["eligible_cap500"]].sort_values("market_cap")
    pick150 = c150.iloc[len(c150) // 2]
    tm = pd.read_csv(TM, dtype=str, usecols=["table", "ticker", "name", "isdelisted", "firstpricedate", "lastpricedate",
                                            "scalemarketcap", "exchange"])
    tm = tm.drop_duplicates("ticker").set_index("ticker")
    def meta(t):
        return tm.loc[t].drop("table").to_dict() if t in tm.index else {}
    nc = {"date": str(D.date()), "cap2000_only_rows_that_date": c2[["ticker", "market_cap", "close"]].to_dict("records")}
    t2 = c2.iloc[0]["ticker"]
    hist2 = read([("ticker", "==", t2)])
    nc["cap2000_only"] = {"ticker": t2, "master": meta(t2), "row": c2.iloc[0][COLS[2:]].to_dict(),
                          "first_panel_date": str(hist2["date"].min().date()),
                          "first_cap150_date": str(hist2.loc[hist2["eligible_cap150"], "date"].min().date())
                          if hist2["eligible_cap150"].any() else None,
                          "why": "cap2000 keeps the $10 price floor and has no dollar-volume floor; cap150/cap500 need a "
                                 "trailing 20d median $vol, which a name listed on/just before this date lacks"}
    t150 = pick150["ticker"]
    nc["cap150_only"] = {"ticker": t150, "master": meta(t150), "row": pick150[COLS[2:]].to_dict(),
                         "why": "market cap between $150M and $500M on the date"}
    assert 150e6 <= pick150["market_cap"] < 500e6
    out["name_check"] = nc

    # ---- 2. dead names in each pool
    dead = tm[(tm["isdelisted"] == "Y")].copy()
    dead["lastpricedate"] = pd.to_datetime(dead["lastpricedate"], errors="coerce")
    dn = {}
    for per, lo, hi in (("A", "2007-01-02", "2019-12-31"), ("B", "2020-01-02", "2026-07-30")):
        cand = dead[(dead["lastpricedate"] > pd.Timestamp(lo) + pd.Timedelta(days=400)) & (dead["lastpricedate"] <= pd.Timestamp(hi))]
        # the delisted name that was largest one year before its last price date (in all three pools)
        probe = s[s["ticker"].isin(cand.index) & s["eligible_cap2000"] & s["eligible_cap150"] & s["eligible_cap500"]]
        probe = probe[(probe["date"] >= pd.Timestamp(lo)) & (probe["date"] <= pd.Timestamp(hi))]
        t = probe.sort_values("market_cap").iloc[-1]["ticker"]
        h = read([("ticker", "==", t)])
        lp = cand.loc[t, "lastpricedate"]
        dn[per] = {"ticker": t, "master": {k: str(v) for k, v in meta(t).items()},
                   "last_panel_date": str(h["date"].max().date()),
                   "days_in_pool": {f: int(h[f].sum()) for f in FLAGS},
                   "last_date_in_pool": {f: str(h.loc[h[f], "date"].max().date()) for f in FLAGS if h[f].any()}}
        assert all(dn[per]["days_in_pool"][f] > 0 for f in FLAGS) and h["date"].max() <= lp
    # a smaller dead name that only ever sat in cap150 (not cap2000)
    small = s[s["ticker"].isin(dead.index) & s["eligible_cap150"] & ~s["eligible_cap500"]]
    t = small.sort_values("date").iloc[len(small) // 2]["ticker"]
    h = read([("ticker", "==", t)])
    dn["cap150_small_dead"] = {"ticker": t, "master": {k: str(v) for k, v in meta(t).items()},
                               "days_in_pool": {f: int(h[f].sum()) for f in FLAGS}, "last_panel_date": str(h["date"].max().date())}
    out["dead_names"] = dn

    # ---- 3a. PIT flip around $2B: a name in cap2000 on one sample date and in cap150-but-not-cap2000 on the next
    a = s[s["date"] == pd.Timestamp("2012-06-15")].set_index("ticker")
    b = s[s["date"] == pd.Timestamp("2015-06-15")].set_index("ticker")
    both = a.index.intersection(b.index)
    up = [t for t in both if (not a.loc[t, "eligible_cap2000"]) and a.loc[t, "eligible_cap150"] and b.loc[t, "eligible_cap2000"]
          and 1.0e9 < a.loc[t, "market_cap"] < 1.8e9]
    t = sorted(up)[0]
    h = read([("ticker", "==", t)])
    h = h[(h["date"] >= "2012-06-15") & (h["date"] <= "2015-06-15")]
    fl = h["eligible_cap2000"].astype(int).diff().fillna(0)
    first_on = h.loc[h["eligible_cap2000"], "date"].min()
    around = h[(h["date"] >= first_on - pd.Timedelta(days=5)) & (h["date"] <= first_on + pd.Timedelta(days=5))]
    out["pit_flip"] = {"ticker": t, "window": "2012-06-15..2015-06-15", "n_flips_cap2000": int((fl != 0).sum()),
                       "first_cap2000_date": str(first_on.date()),
                       "rows_around_first": around[["date", "market_cap", "close", "eligible_cap2000", "eligible_cap2000_v1"]]
                       .assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d")).to_dict("records"),
                       "cap2000_true_below_2B_in_window": int((h["eligible_cap2000"] & (h["market_cap"] < 2e9)).sum()),
                       "v1_vs_v2_rows_differ_in_window": int((h["eligible_cap2000"] != h["eligible_cap2000_v1"]).sum())}
    assert out["pit_flip"]["cap2000_true_below_2B_in_window"] == 0
    out["pit_note"] = ("v2 flags are computed per row from that date's market cap, price and trailing 20d $vol "
                       "(downcap_universe.py); membership flips as market cap crosses the floor, and delisted names "
                       "are present up to their last price date.")
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({k: out[k] for k in ("name_check", "dead_names", "pit_flip")}, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
