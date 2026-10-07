"""WO-47 hand-checks: ADRX, CLGX, RSHCQ against raw SEP and Sharadar TICKERS, and their presence in
the Sep-11 and current XGB panels and the two v2 panels. Writes final/out/tickerreuse/hand_check.json."""
import json

import pandas as pd
import pyarrow.parquet as pq

from common import OUT, SEP_DIR, FROZEN, MAIN, MASTERS, SCRATCH

NAMES = ["ADRX", "CLGX", "RSHCQ"]
res = {}
sep = pd.concat([pd.read_parquet(f, columns=["ticker", "date", "close", "volume"], filters=[("ticker", "in", NAMES)])
                 for f in sorted(SEP_DIR.glob("*.parquet"))])
sep["date"] = pd.to_datetime(sep["date"])
tk = []
for p in MASTERS:
    m = pd.read_csv(p, dtype=str, keep_default_na=False)
    m = m[(m.table == "stocks") & m.ticker.str.match(r"^(ADRX|CLGX|RSHCQ)\d*$")]
    tk.append(m.assign(src=p.name)[["src", "permaticker", "ticker", "name", "category", "firstpricedate", "lastpricedate"]])
tk = pd.concat(tk)
panels = {"xgb_sep11": MAIN / "out" / "features_with_rates_sharadar_pit.parquet",
          "xgb_current": FROZEN / "features_with_fundamentals_sharadar_pit.parquet",
          "v2_sep08": MAIN / "out" / "reset2026" / "composite_panel_v2_through_2026-09-08.parquet",
          "v2_current": FROZEN / "composite_panel_v2.parquet"}
pres = {}
for k, p in panels.items():
    t = pq.read_table(p, columns=["ticker", "date", "close"], filters=[("ticker", "in", NAMES)]).to_pandas()
    t["date"] = pd.to_datetime(t["date"])
    pres[k] = t
xd = pd.read_parquet(SCRATCH / "b_xgb_rowdiff.parquet", columns=["ticker", "side"])
vd = pd.read_parquet(SCRATCH / "b_v2_rowdiff.parquet", columns=["ticker", "side"])
for n in NAMES:
    s = sep[sep.ticker == n].sort_values("date")
    gaps = s.date.diff().dt.days
    r = {"sep_rows": int(len(s)), "sep_first": str(s.date.min().date()), "sep_last": str(s.date.max().date()),
         "sep_largest_gap_days": int(gaps.max()) if len(s) > 1 else None,
         "sep_largest_gap_at": str(s.date.iloc[int(gaps.values.argmax())].date()) if len(s) > 1 else None,
         "tickers_entities": tk[tk.ticker.str.match(rf"^{n}\d*$")].drop_duplicates(["permaticker", "ticker", "src"]).to_dict("records"),
         "panels": {}}
    for k, t in pres.items():
        g = t[t.ticker == n]
        r["panels"][k] = {"rows": int(len(g)), "pre2020_rows": int((g.date < "2020-01-01").sum()),
                          "first": str(g.date.min().date()) if len(g) else None,
                          "last": str(g.date.max().date()) if len(g) else None}
        # closes match raw SEP on shared dates
        if len(g):
            mm = g.merge(s, on=["ticker", "date"], suffixes=("", "_sep"))
            r["panels"][k]["close_eq_sep"] = f"{int((mm.close == mm.close_sep).sum())}/{len(mm)}"
    r["xgb_pre2020_diff_rows"] = xd[xd.ticker == n].side.value_counts().to_dict()
    r["v2_pre2020_diff_rows"] = vd[vd.ticker == n].side.value_counts().to_dict()
    res[n] = r
(OUT / "hand_check.json").write_text(json.dumps(res, indent=2, default=str))
print(json.dumps(res, indent=1, default=str))
