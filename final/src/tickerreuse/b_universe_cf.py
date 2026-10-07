"""WO-47 B: counterfactual PIT-universe ticker sets, one input swapped at a time.

Same screen as build_pit_universe.py (domestic category from the master by ticker; daily marketcap
>= 2000 and closeunadj (fallback close) > 10; drop rows where marketcap > 10x close*sharesbas), run
on the raw panel with these inputs varied:
    master : tickers_master_through_2026-09-08.csv  vs  tickers_master.csv (2026-09-26, frozen)
    shares : sf1_shares_through_2026-09-08.csv      vs  sf1_shares.csv (current)
    through: 2026-09-10 (Sep-11 build)              vs  all dates (2026-10-05)
Writes final/out/tickerreuse/b_universe_cf.json and ~/.cache/wo47/universe_cf_sets.json.
"""
import itertools
import json

import pandas as pd
import pyarrow.parquet as pq

from common import OUT, SCRATCH, FROZEN, SHARADAR, MAIN
from build_pit_universe import DOMESTIC, MIN_MARKETCAP, MIN_PRICE, DISAGREE_FACTOR

PANEL = SHARADAR / "panel"
MASTER = {"sep": SHARADAR / "tickers_master_through_2026-09-08.csv", "cur": FROZEN / "tickers_master.csv"}
SHARES = {"sep": SHARADAR / "sf1_shares_through_2026-09-08.csv", "cur": SHARADAR / "sf1_shares.csv"}
THROUGH = {"sep": pd.Timestamp("2026-09-10"), "cur": pd.Timestamp("2026-12-31")}


def screened():
    fr = []
    for f in sorted((PANEL / "daily").glob("*.parquet")):
        d = pd.read_parquet(f, columns=["ticker", "date", "marketcap"])
        s = pd.read_parquet(PANEL / "stocks" / f.name, columns=["ticker", "date", "close", "closeunadj"])
        j = d.merge(s, on=["ticker", "date"], how="inner")
        j = j[j["marketcap"].notna() & j["close"].notna()]
        j = j[(j["marketcap"] >= MIN_MARKETCAP) & (j["closeunadj"].fillna(j["close"]) > MIN_PRICE)]
        fr.append(j)
    j = pd.concat(fr, ignore_index=True)
    j["date"] = pd.to_datetime(j["date"])
    j["ticker"] = j["ticker"].astype(str)
    return j.sort_values("date").reset_index(drop=True)


def shares(p):
    sh = pd.read_csv(p, dtype={"ticker": str})
    sh["date"] = pd.to_datetime(sh["date"], errors="coerce")
    sh["sharesbas"] = pd.to_numeric(sh["sharesbas"], errors="coerce")
    sh = sh[sh["date"].notna() & sh["sharesbas"].notna() & (sh["sharesbas"] > 0)]
    return sh.sort_values("date")[["ticker", "date", "sharesbas"]].reset_index(drop=True)


def universe(J, dom, sh, through):
    j = J[J["ticker"].isin(dom) & (J["date"] <= through)]
    j = pd.merge_asof(j, sh, on="date", by="ticker", direction="backward")
    cxs = j["close"] * j["sharesbas"] / 1e6
    has = j["sharesbas"].notna() & (cxs > 0)
    bad = has & (j["marketcap"] / cxs > DISAGREE_FACTOR)
    return set(j.loc[~bad, "ticker"])


def main():
    J = screened()
    print(f"screened rows {len(J):,}")
    doms = {k: set(pd.read_csv(p, dtype=str, keep_default_na=False).query("category in @DOMESTIC")["ticker"])
            for k, p in MASTER.items()}
    shs = {k: shares(p) for k, p in SHARES.items()}
    sets = {}
    for m, s, t in itertools.product(("sep", "cur"), repeat=3):
        sets[f"master={m},shares={s},through={t}"] = universe(J, doms[m], shs[s], THROUGH[t])
    sep11 = set(pq.read_table(MAIN / "out" / "features_with_rates_sharadar_pit.parquet", columns=["ticker"])
                .column("ticker").unique().to_pylist())
    cur = set(pq.read_table(FROZEN / "pit_universe.parquet", columns=["ticker"]).column("ticker").unique().to_pylist())
    res = {"sep11_panel_tickers": len(sep11), "current_universe_tickers": len(cur),
           "all_sep_reproduces_sep11": sets["master=sep,shares=sep,through=sep"] == sep11,
           "all_sep_diff": {"missing": sorted(sep11 - sets["master=sep,shares=sep,through=sep"]),
                            "extra": sorted(sets["master=sep,shares=sep,through=sep"] - sep11)},
           "all_cur_reproduces_current": sets["master=cur,shares=cur,through=cur"] == cur,
           "all_cur_diff": {"missing": sorted(cur - sets["master=cur,shares=cur,through=cur"]),
                            "extra": sorted(sets["master=cur,shares=cur,through=cur"] - cur)},
           "sizes": {k: len(v) for k, v in sets.items()}}
    base = sets["master=sep,shares=sep,through=sep"]
    res["single_swaps_from_sep"] = {}
    for k in ("master=cur,shares=sep,through=sep", "master=sep,shares=cur,through=sep", "master=sep,shares=sep,through=cur"):
        res["single_swaps_from_sep"][k] = {"removed": sorted(base - sets[k]), "added": sorted(sets[k] - base)}
    (OUT / "b_universe_cf.json").write_text(json.dumps(res, indent=2, default=str))
    (SCRATCH / "universe_cf_sets.json").write_text(json.dumps({k: sorted(v) for k, v in sets.items()}))
    print(json.dumps({k: v for k, v in res.items() if k != "sizes"}, indent=2, default=str))


if __name__ == "__main__":
    main()
