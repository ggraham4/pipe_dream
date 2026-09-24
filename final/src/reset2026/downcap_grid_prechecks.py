"""
WO-6 read-only pre-checks, run before the v2 grid build.

1. Is on-disk SF1 COMPLETE in time for the missing tickers (not just present)?
   Compare per-ticker SF1 ARQ/ARY date span against tickers_master
   firstquarter/lastquarter for a random sample of 40 missing non-SPAC names.
2. What are the 14 names without ARY/ARQ (category)?
3. FINRA short-interest symbol coverage of the missing names, pre/post 2020.
4. Is composite_panel.parquet (Sep 18) still equal to TODAY's intermediates
   (features_with_fundamentals_sharadar_pit, rebuilt Sep 22) on 20 dates
   2007-2019? If not, a bit-identical reproduction is impossible with today's
   inputs and the baseline has to be named explicitly.

Reads no returns-as-test. Output: out/reset2026/downcap_v2/prechecks.json
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq

MAIN = Path("/Users/ggraham/pipe_dream/final")
SH = MAIN / "data" / "sharadar"
V2 = MAIN / "out" / "reset2026" / "downcap_v2"
RNG = np.random.default_rng(6)


def sample_dates():
    d = pq.read_table(MAIN / "out" / "reset2026" / "composite_panel.parquet",
                      columns=["date"], filters=[("ticker", "=", "AAPL")]
                      ).column("date").to_pylist()
    d = sorted(x for x in d if "2007-01-01" <= x < "2020-01-01")
    idx = np.linspace(0, len(d) - 1, 20).round().astype(int)
    return [d[i] for i in idx]


def main():
    out = {}
    m = pd.read_csv(V2 / "missing_tickers.csv")
    ns = m[~m.spac]
    tm = pd.read_csv(SH / "tickers_master.csv", dtype=str).drop_duplicates("ticker").set_index("ticker")

    # 1. SF1 span
    sf1 = pq.read_table(SH / "sf1_fundamentals.parquet",
                        columns=["ticker", "dimension", "calendardate"]).to_pandas()
    sf1["calendardate"] = pd.to_datetime(sf1["calendardate"])
    samp = RNG.choice(ns.ticker.to_numpy(), 40, replace=False)
    rows = []
    for t in samp:
        g = sf1[(sf1.ticker == t) & (sf1.dimension == "ARQ")]
        fq, lq = tm.loc[t, "firstquarter"], tm.loc[t, "lastquarter"]
        rows.append(dict(ticker=t, n_arq=len(g),
                         sf1_first=str(g.calendardate.min().date()) if len(g) else None,
                         sf1_last=str(g.calendardate.max().date()) if len(g) else None,
                         master_firstq=fq, master_lastq=lq))
    span = pd.DataFrame(rows)
    ok = ((span.sf1_first == span.master_firstq) | (span.sf1_first.fillna("9") <= "2005-01-01")) & (span.sf1_last == span.master_lastq)
    span["span_matches_master"] = ok
    out["sf1_span_sample"] = span.to_dict("records")
    out["sf1_span_match_rate"] = float(ok.mean())

    # 2. the 14
    lack = ns[~ns.sf1_ary | ~ns.sf1_arq].ticker.tolist()
    out["no_full_sf1"] = [dict(ticker=t, category=tm.loc[t, "category"] if t in tm.index else None,
                               ary=bool(ns.set_index("ticker").loc[t, "sf1_ary"]),
                               arq=bool(ns.set_index("ticker").loc[t, "sf1_arq"]))
                          for t in lack]

    # 3. FINRA
    fin_cols = pd.read_csv(MAIN / "data" / "finra" / "short_interest_raw.csv", nrows=0).columns.tolist()
    sym = [c for c in fin_cols if c.lower() in ("symbolcode", "symbol", "issuesymbolidentifier")][0]
    dcol = [c for c in fin_cols if "settlement" in c.lower() and "date" in c.lower()][0]
    fin = pd.read_csv(MAIN / "data" / "finra" / "short_interest_raw.csv", usecols=[sym, dcol])
    out["finra_cols"] = [sym, dcol]
    out["finra_date_range"] = [str(fin[dcol].min()), str(fin[dcol].max())]
    fs = set(fin[sym].astype(str))
    old = set(pq.read_table(MAIN / "out" / "features_sharadar_pit.parquet", columns=["ticker"]).column("ticker").unique().to_pylist())
    out["finra_symbols"] = len(fs)
    out["finra_cover_old_grid"] = len(fs & old) / len(old)
    out["finra_cover_missing_non_spac"] = len(fs & set(ns.ticker)) / len(ns)
    out["finra_cover_missing_non_spac_alive"] = len(fs & set(ns[ns.isdelisted == "N"].ticker)) / max(1, (ns.isdelisted == "N").sum())

    # 4. staleness of the reproduction target
    dates = sample_dates()
    out["repro_dates"] = dates
    cp = pq.read_table(MAIN / "out" / "reset2026" / "composite_panel.parquet",
                       columns=["ticker", "date", "open", "close", "market_cap", "volatility_60",
                                "pct_from_high_252", "forward_return_tradable_40"],
                       filters=[("date", "in", dates)]).to_pandas()
    fwf = ds.dataset(MAIN / "out" / "features_with_fundamentals_sharadar_pit.parquet")
    ts = [pd.Timestamp(d) for d in dates]
    cur = fwf.to_table(columns=["ticker", "date", "open", "close", "market_cap", "volatility_60",
                                "pct_from_high_252", "forward_return_tradable_40"],
                       filter=ds.field("date").isin(ts)).to_pandas()
    cur["date"] = cur["date"].dt.strftime("%Y-%m-%d")
    j = cp.merge(cur, on=["ticker", "date"], how="outer", suffixes=("_cp", "_cur"), indicator=True)
    out["stale_rows"] = j["_merge"].value_counts().to_dict()
    both = j[j["_merge"] == "both"]
    diff = {}
    for c in ["open", "close", "market_cap", "volatility_60", "pct_from_high_252", "forward_return_tradable_40"]:
        a, b = both[c + "_cp"].to_numpy(), both[c + "_cur"].to_numpy()
        same = (a == b) | (np.isnan(a) & np.isnan(b))
        diff[c] = int((~same).sum())
    out["stale_value_mismatches"] = diff
    out["stale_rows_compared"] = int(len(both))
    only = j[j["_merge"] != "both"]
    out["stale_only_examples"] = only[["ticker", "date", "_merge"]].head(10).astype(str).to_dict("records")

    (V2 / "prechecks.json").write_text(json.dumps(out, indent=2, default=str))
    s = {k: v for k, v in out.items() if k != "sf1_span_sample"}
    print(json.dumps(s, indent=2, default=str))
    print(span.to_string())


if __name__ == "__main__":
    main()
