"""
WO-6 Phase 1 inventory: which cap500/cap150-eligible tickers
(downcap_universe_v2.parquet) are absent from the existing composite grid
(the 4,011-ticker features_*_sharadar_pit panels), and what raw data is
already on disk for them.

Writes (all new files, nothing overwritten):
    <MAIN>/out/reset2026/downcap_v2/inventory.json
    <MAIN>/out/reset2026/downcap_v2/missing_tickers.csv   (per-ticker flags)
    <MAIN>/out/reset2026/downcap_v2/pull_list.csv         (ticker, table)

Reads no returns. Usage: python3 downcap_grid_inventory.py
"""
import glob
import json
import os
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

MAIN = Path("/Users/ggraham/pipe_dream/final")
SH = MAIN / "data" / "sharadar"
OUT_DIR = MAIN / "out" / "reset2026" / "downcap_v2"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    u = pq.read_table(SH / "downcap_universe_v2.parquet",
                      columns=["ticker", "date", "eligible_cap500",
                               "eligible_cap150"]).to_pandas()
    dc = u[u.eligible_cap500 | u.eligible_cap150]
    v2t = set(dc.ticker.unique())
    old = set(pq.read_table(MAIN / "out" / "features_sharadar_pit.parquet",
                            columns=["ticker"]).column("ticker")
              .unique().to_pylist())
    miss = sorted(v2t - old)

    tm = pd.read_csv(SH / "tickers_master.csv", dtype=str,
                     usecols=["ticker", "name", "category", "isdelisted",
                              "sicindustry", "firstpricedate",
                              "lastpricedate"])
    tm = tm.drop_duplicates("ticker").set_index("ticker")

    stk = set()
    for f in sorted(glob.glob(str(SH / "panel" / "stocks" / "*.parquet"))):
        stk |= set(pq.read_table(f, columns=["ticker"]).column("ticker")
                   .unique().to_pylist())
    sf1 = pq.read_table(SH / "sf1_fundamentals.parquet",
                        columns=["ticker", "dimension"]).to_pandas()
    ary = set(sf1[sf1.dimension == "ARY"].ticker)
    arq = set(sf1[sf1.dimension == "ARQ"].ticker)
    shares = set(pd.read_csv(SH / "sf1_shares.csv", usecols=["ticker"]).ticker)
    act = pd.read_csv(SH / "actions.csv", usecols=["ticker"]).ticker
    act = set(act)
    tds = {os.path.splitext(x)[0]
           for x in os.listdir(MAIN / "scripts" / "td_data_sharadar")}

    rows = []
    for t in miss:
        r = tm.loc[t] if t in tm.index else None
        name = "" if r is None else str(r["name"])
        sic = "" if r is None else str(r["sicindustry"])
        rows.append(dict(
            ticker=t, name=name,
            in_master=r is not None,
            isdelisted=None if r is None else r["isdelisted"],
            spac=("Blank Check" in sic),
            sep_on_disk=t in stk, sf1_ary=t in ary, sf1_arq=t in arq,
            sf1_shares=t in shares, in_actions=t in act,
            td_data_sharadar_csv=t in tds))
    m = pd.DataFrame(rows)
    m.to_csv(OUT_DIR / "missing_tickers.csv", index=False)

    ns = m[~m.spac]
    pulls = []
    for t in ns.ticker[~ns.sf1_ary | ~ns.sf1_arq]:
        pulls.append((t, "SF1"))
    for t in ns.ticker[~ns.sep_on_disk]:
        pulls.append((t, "SEP"))
    pd.DataFrame(pulls, columns=["ticker", "table"]).to_csv(
        OUT_DIR / "pull_list.csv", index=False)

    # row-weighted coverage on v2 cap150 rows
    c150 = dc[dc.eligible_cap150][["ticker", "date"]]
    spac_t = set(m.ticker[m.spac])
    c150 = c150[~c150.ticker.isin(spac_t)]
    sf1_any = ary | arq
    inv = {
        "v2_cap500_or_cap150_tickers": len(v2t),
        "old_grid_tickers": len(old),
        "overlap": len(v2t & old),
        "missing_tickers": len(miss),
        "missing_spac": int(m.spac.sum()),
        "missing_non_spac": int((~m.spac).sum()),
        "missing_non_spac_delisted": int((ns.isdelisted == "Y").sum()),
        "non_spac_sep_on_disk": int(ns.sep_on_disk.sum()),
        "non_spac_sf1_ary": int(ns.sf1_ary.sum()),
        "non_spac_sf1_arq": int(ns.sf1_arq.sum()),
        "non_spac_sf1_shares": int(ns.sf1_shares.sum()),
        "non_spac_in_actions": int(ns.in_actions.sum()),
        "non_spac_td_data_sharadar_csv": int(ns.td_data_sharadar_csv.sum()),
        "pull_list_SF1": sum(1 for p in pulls if p[1] == "SF1"),
        "pull_list_SEP": sum(1 for p in pulls if p[1] == "SEP"),
        "cap150_rows_non_spac": int(len(c150)),
        "cap150_rows_in_old_grid_tickers": float(c150.ticker.isin(old).mean()),
        "cap150_rows_with_sf1_on_disk": float(c150.ticker.isin(sf1_any).mean()),
        "sf1_tickers_total": len(set(sf1.ticker)),
    }
    (OUT_DIR / "inventory.json").write_text(json.dumps(inv, indent=2))
    print(json.dumps(inv, indent=2))


if __name__ == "__main__":
    main()
