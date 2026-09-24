"""
WO-6 acceptance: the pre-registered checks in
final/models/2026-09-24-downcap-grid-rebuild.md, run against the v2 build.

  R   reproduction: old-grid tickers' rows from the FULL v2 build vs
      composite_panel.parquet / beta_feature.parquet / outcome_cache.parquet
      on 20 fixed dates, 2007-2019. Bit-identical, NaN masks included.
  C   row coverage and per-factor coverage (pre-registered thresholds)
  A1  never-large names present on 2014-06-30, market_cap plausible
  A2  dead names present through their last price date, outcomes truncated
  A3  cap150/cap500 counts per date vs downcap_universe_v2_report.txt

No returns are read as a test. Output: out/reset2026/downcap_v2/acceptance.json
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

MAIN = Path("/Users/ggraham/pipe_dream/final")
R26 = MAIN / "out" / "reset2026"
V2 = R26 / "downcap_v2"
SH = MAIN / "data" / "sharadar"

DATES = ["2007-01-03", "2007-09-10", "2008-05-15", "2009-01-21", "2009-09-28",
         "2010-06-04", "2011-02-08", "2011-10-13", "2012-06-20", "2013-02-28",
         "2013-11-04", "2014-07-14", "2015-03-19", "2015-11-20", "2016-07-29",
         "2017-04-05", "2017-12-11", "2018-08-17", "2019-04-26", "2019-12-31"]
FACTORS7 = ["momentum_12_1", "pct_from_high_252", "volatility_60",
            "gross_profitability", "accruals", "net_issuance_pct",
            "days_to_next_filing_seasonal"]
FLAGS = ["eligible_cap2000", "eligible_cap500", "eligible_cap150"]


def rd(path, cols=None, filters=None):
    df = pq.read_table(path, columns=cols, filters=filters).to_pandas()
    if "date" in df and not isinstance(df["date"].iloc[0], str):
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["ticker"] = df["ticker"].astype(str)
    return df


def compare(a, b, keys, cols, label):
    """a = reference (old), b = candidate (v2, restricted). Exact."""
    res = {"label": label}
    a = a.sort_values(keys).reset_index(drop=True)
    b = b.sort_values(keys).reset_index(drop=True)
    ka = a[keys].astype(str).agg("|".join, axis=1)
    kb = b[keys].astype(str).agg("|".join, axis=1)
    res["rows_ref"], res["rows_v2"] = len(a), len(b)
    res["row_sets_equal"] = bool(len(a) == len(b) and (ka.values == kb.values).all())
    if not res["row_sets_equal"]:
        sa, sb = set(ka), set(kb)
        res["only_ref"] = len(sa - sb)
        res["only_v2"] = len(sb - sa)
        res["only_ref_examples"] = sorted(sa - sb)[:5]
        res["only_v2_examples"] = sorted(sb - sa)[:5]
        m = a.merge(b, on=keys, suffixes=("_a", "_b"))
    else:
        m = a.join(b[cols].add_suffix("_b")).rename(columns={c: c + "_a" for c in cols})
    mism = {}
    for c in cols:
        x, y = m[c + "_a"], m[c + "_b"]
        if x.dtype.kind in "fc" or y.dtype.kind in "fc":
            xv, yv = x.to_numpy(np.float64), y.to_numpy(np.float64)
            same = (xv == yv) | (np.isnan(xv) & np.isnan(yv))
            if x.dtype != y.dtype:
                res.setdefault("dtype_diff", {})[c] = f"{x.dtype} vs {y.dtype}"
        else:
            same = (x.astype(str).to_numpy() == y.astype(str).to_numpy())
        mism[c] = int((~same).sum())
    res["compared_rows"] = int(len(m))
    res["mismatches"] = mism
    res["pass"] = bool(res["row_sets_equal"] and all(v == 0 for v in mism.values()))
    return res


def main():
    out = {}
    old_t = set(pq.read_table(R26 / "composite_panel.parquet", columns=["ticker"])
                .column("ticker").unique().to_pylist())
    tm = pd.read_csv(SH / "tickers_master.csv", dtype=str).drop_duplicates("ticker").set_index("ticker")
    spac = set(tm.index[tm["sicindustry"].fillna("").str.contains("Blank Check")])

    # ---------- R ----------
    ref = rd(R26 / "composite_panel.parquet", filters=[("date", "in", DATES)])
    cols_all = [c for c in ref.columns if c not in ("ticker", "date")]
    v2cols = ["ticker", "date"] + [c for c in cols_all if c not in FLAGS] + [f + "_v1" for f in FLAGS]
    cand = rd(R26 / "composite_panel_v2.parquet", cols=v2cols, filters=[("date", "in", DATES)])
    cand = cand[cand.ticker.isin(old_t)].rename(columns={f + "_v1": f for f in FLAGS})
    R = [compare(ref, cand, ["ticker", "date"], cols_all, "composite_panel")]

    bref = rd(R26 / "beta_feature.parquet", filters=[("date", "in", DATES)])
    bv2 = rd(R26 / "beta_feature_v2.parquet", filters=[("date", "in", DATES)])
    R.append(compare(bref, bv2[bv2.ticker.isin(old_t)], ["ticker", "date"],
                     ["beta_252", "market_return"], "beta_feature"))

    ts = [pd.Timestamp(d) for d in DATES]
    oref = rd(R26 / "outcome_cache.parquet", filters=[("date", "in", ts)])
    ov2 = rd(R26 / "outcome_cache_v2.parquet", filters=[("date", "in", ts)])
    keep = old_t | {"SPY", "USMV"}
    R.append(compare(oref, ov2[ov2.ticker.isin(keep)], ["ticker", "date"],
                     ["gross_return_40", "truncated"], "outcome_cache"))
    out["R"] = R
    out["R_pass"] = all(r["pass"] for r in R)

    # ---------- C ----------
    uni = rd(SH / "downcap_universe_v2.parquet",
             cols=["ticker", "date", "eligible_cap500", "eligible_cap150"])
    u150 = uni[uni.eligible_cap150 & ~uni.ticker.isin(spac)][["ticker", "date"]]
    p = rd(R26 / "composite_panel_v2.parquet",
           cols=["ticker", "date"] + FACTORS7 + FLAGS)
    keyp = pd.MultiIndex.from_frame(p[["ticker", "date"]])
    present = pd.MultiIndex.from_frame(u150).isin(keyp)
    nom = (u150.date < "2020-01-01").to_numpy()
    out["C_row_coverage_all"] = float(present.mean())
    out["C_row_coverage_2007_2019"] = float(present[nom & (u150.date >= "2007-01-01").to_numpy()].mean())
    out["C_missing_rows_by_year"] = (u150[~present].date.str[:4].value_counts().sort_index().to_dict())

    q = p[p.eligible_cap150 & ~p.ticker.isin(spac) & (p.date >= "2007-01-01") & (p.date < "2020-01-01")]
    new, oldr = q[~q.ticker.isin(old_t)], q[q.ticker.isin(old_t)]
    fc = {}
    for c in FACTORS7:
        rn, ro = float(new[c].notna().mean()), float(oldr[c].notna().mean())
        fc[c] = {"new_rows": rn, "old_rows": ro, "ratio": rn / ro if ro else None,
                 "pass": bool(ro and rn / ro >= 0.90)}
    out["C_factor_coverage"] = fc
    out["C_rows_new_vs_old"] = [int(len(new)), int(len(oldr))]
    out["C_pass"] = bool(out["C_row_coverage_all"] >= 0.95 and out["C_row_coverage_2007_2019"] >= 0.95
                         and all(v["pass"] for v in fc.values()))
    out["KILL"] = bool(out["C_row_coverage_all"] < 0.90)

    # ---------- A1 ----------
    exp = {"ANIK": 668.1, "NGS": 412.0, "WTBA": 243.5, "NRIM": 174.6, "ACHN": 732.7}
    a1 = rd(R26 / "composite_panel_v2.parquet", cols=["ticker", "date", "market_cap", "eligible_cap150"],
            filters=[("date", "=", "2014-06-30"), ("ticker", "in", list(exp))]).set_index("ticker")
    A1 = {}
    for t, mc in exp.items():
        if t not in a1.index:
            A1[t] = {"present": False, "pass": False}
            continue
        g = float(a1.loc[t, "market_cap"]) / 1e6
        ok = bool(a1.loc[t, "eligible_cap150"]) and abs(g / mc - 1) <= 0.30 and t not in old_t
        A1[t] = {"present": True, "eligible_cap150": bool(a1.loc[t, "eligible_cap150"]),
                 "grid_mcap_M": round(g, 1), "sharadar_mcap_M": mc,
                 "rel_diff": round(g / mc - 1, 3), "in_old_grid": t in old_t, "pass": ok}
    out["A1"] = A1

    # ---------- A2 ----------
    dead = {"ACHN": "2020-01-27", "HNR": "2017-05-04", "GCAP": "2020-07-30"}
    A2 = {}
    pd_ = rd(R26 / "composite_panel_v2.parquet", cols=["ticker", "date"], filters=[("ticker", "in", list(dead))])
    oc = rd(R26 / "outcome_cache_v2.parquet", filters=[("ticker", "in", list(dead))])
    for t, last in dead.items():
        g = oc[oc.ticker == t].sort_values("date")
        tr = g["truncated"].to_numpy()
        ok_tr = len(tr) > 41 and tr[-40:].all() and not tr[:-40].any()
        lp = pd_[pd_.ticker == t].date.max()
        A2[t] = {"grid_last_date": lp, "expected": last, "truncated_last40_only": bool(ok_tr),
                 "pass": bool(lp == last and ok_tr)}
    out["A2"] = A2

    # ---------- A3 ----------
    exp3 = {"2008-06-30": (2953, 1993), "2014-06-30": (3213, 2449), "2017-06-30": (3100, 2418)}
    A3 = {}
    for d, (e150, e500) in exp3.items():
        g = rd(R26 / "composite_panel_v2.parquet", cols=["ticker", "date", "eligible_cap150", "eligible_cap500"],
               filters=[("date", "=", d)])
        n150, n500 = int(g.eligible_cap150.sum()), int(g.eligible_cap500.sum())
        A3[d] = {"cap150": n150, "exp150": e150, "cap500": n500, "exp500": e500,
                 "pass": bool(n150 >= 0.99 * e150 and n500 >= 0.99 * e500 and n150 <= e150 and n500 <= e500)}
    out["A3"] = A3
    out["A_pass"] = all(v["pass"] for blk in ("A1", "A2", "A3") for v in out[blk].values())
    out["BUILD_SUCCESS"] = bool(out["R_pass"] and out["C_pass"] and out["A_pass"])

    (V2 / "acceptance.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
