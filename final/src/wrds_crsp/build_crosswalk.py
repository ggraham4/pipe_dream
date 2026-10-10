"""WO-51 Phase 1: CRSP permno <-> Sharadar (v2 grid) crosswalk.

Output: final/data/wrds/link/permno_sharadar.parquet (main checkout, gitignored), columns
  permno, permaticker, ticker (as used in the v2 grid), valid_from, valid_to,
  match_method ('cusip8' | 'ticker_date'), match_quality ('A' | 'B' | 'C'), n_candidates
plus final/out/wrds_crsp/crosswalk_summary.json (coverage + anchors; no return statistic).

Method
  Sharadar side: TICKERS (tickers_master.csv, table 'stocks'), one row per permaticker; the v2
  grid's ticker column is Sharadar's ticker, which is unique per permaticker (Sharadar renames the
  old entity of a reused symbol to S1, S2 ...; WO-47). Each ticker's span is
  [firstpricedate, lastpricedate]. WO-47 segmentation: a later segment `S__postYYYYMMDD` is a
  different entity; it is matched on ticker+date only inside its own segment (none in 2007-2019).
  1. cusip8: every historical CUSIP in TICKERS.cusips (first 8 chars) is joined to CRSP
     stocknames.ncusip (fallback: stocknames.cusip when ncusip is null). The valid interval is
     CRSP [namedt, nameenddt] intersected with the Sharadar span.
  2. ticker_date: for grid name-dates still unmapped, CRSP stocknames.ticker equal to the Sharadar
     ticker or one of its TICKERS.relatedtickers, with the CRSP name interval covering the date,
     accepted only when exactly one permno qualifies.
  Overlaps (one Sharadar ticker, several permnos on the same date) are resolved by preferring
  a permno whose CRSP ticker on that interval equals the Sharadar ticker/related ticker, then
  shrcd 10/11, then the longest total overlap; n_candidates records the ambiguity.
  match_quality: A = cusip8 and the CRSP ticker agrees with the Sharadar ticker or a related ticker
  somewhere in the interval; B = cusip8 only; C = ticker_date.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wrdsdb import CRSP_DIR, LINK_DIR, MAIN  # noqa: E402

TICKERS = MAIN / "final/data/sharadar/tickers_master.csv"
GRID = MAIN / "final/out/reset2026/downcap_v2/grid_tickers_v2.parquet"
UNIV = MAIN / "final/data/sharadar/downcap_universe_v2.parquet"
OUT = LINK_DIR / "permno_sharadar.parquet"
REPO = Path(__file__).resolve().parents[3]
SUMMARY = REPO / "final/out/wrds_crsp/crosswalk_summary.json"


def base_ticker(t: str) -> str:
    return t.split("__post")[0]


def load_sharadar(grid: set[str]) -> pd.DataFrame:
    t = pd.read_csv(TICKERS, low_memory=False,
                    usecols=["permaticker", "ticker", "name", "cusips", "relatedtickers",
                             "firstpricedate", "lastpricedate", "category"])
    t = t[t.ticker.isin({base_ticker(x) for x in grid})].copy()
    t["firstpricedate"] = pd.to_datetime(t.firstpricedate)
    t["lastpricedate"] = pd.to_datetime(t.lastpricedate)
    return t


def load_crsp_names() -> pd.DataFrame:
    n = pd.read_parquet(CRSP_DIR / "stocknames.parquet")
    n["namedt"] = pd.to_datetime(n.namedt)
    n["nameenddt"] = pd.to_datetime(n.nameenddt)
    n["key8"] = n.ncusip.where(n.ncusip.notna() & (n.ncusip.str.len() == 8), n.cusip)
    return n


def cusip_candidates(s: pd.DataFrame, n: pd.DataFrame) -> pd.DataFrame:
    ex = s[["permaticker", "ticker", "relatedtickers", "cusips", "firstpricedate", "lastpricedate"]].copy()
    ex["cusip8"] = ex.cusips.fillna("").str.split()
    ex = ex.explode("cusip8").dropna(subset=["cusip8"])
    ex["cusip8"] = ex.cusip8.str[:8]
    m = ex.merge(n[["permno", "namedt", "nameenddt", "key8", "ticker", "shrcd"]].rename(columns={"ticker": "crsp_ticker"}),
                 left_on="cusip8", right_on="key8")
    m["valid_from"] = m[["namedt", "firstpricedate"]].max(axis=1)
    m["valid_to"] = m[["nameenddt", "lastpricedate"]].min(axis=1)
    m = m[m.valid_from <= m.valid_to].copy()
    rel = m.relatedtickers.fillna("").str.split()
    m["tick_agree"] = [ct == t or ct in r for ct, t, r in zip(m.crsp_ticker, m.ticker, rel)]
    m["match_method"] = "cusip8"
    return m[["permaticker", "ticker", "permno", "valid_from", "valid_to", "tick_agree", "shrcd", "match_method"]]


def resolve(cands: pd.DataFrame) -> pd.DataFrame:
    """Per Sharadar ticker, split the timeline at every candidate boundary and keep one permno per piece."""
    out = []
    tot = cands.assign(days=(cands.valid_to - cands.valid_from).dt.days).groupby(["ticker", "permno"]).days.sum()
    for tk, g in cands.groupby("ticker", sort=False):
        if g.permno.nunique() == 1 and len(g) >= 1:
            g = g.sort_values("valid_from")
            out.append(pd.DataFrame({
                "ticker": tk, "permaticker": g.permaticker.iloc[0], "permno": g.permno.iloc[0],
                "valid_from": g.valid_from.values, "valid_to": g.valid_to.values,
                "tick_agree": g.tick_agree.values, "n_candidates": 1, "match_method": g.match_method.values}))
            continue
        bps = np.unique(np.concatenate([g.valid_from.values, (g.valid_to + pd.Timedelta(days=1)).values]))
        for a, b in zip(bps[:-1], bps[1:]):
            b1 = b - np.timedelta64(1, "D")
            c = g[(g.valid_from <= a) & (g.valid_to >= b1)]
            if c.empty:
                continue
            c = c.assign(tot=[tot[(tk, p)] for p in c.permno], sh=c.shrcd.isin([10, 11]))
            # identity continuity first: the permno this Sharadar entity overlaps longest
            # (ATLS1 lists Atlas America's CUSIP for 2006-09; its own security is AHD/ATLS LP)
            c = c.sort_values(["tot", "tick_agree", "sh"], ascending=False)
            r = c.iloc[0]
            out.append(pd.DataFrame({"ticker": [tk], "permaticker": [r.permaticker], "permno": [r.permno],
                                     "valid_from": [a], "valid_to": [b1], "tick_agree": [bool(c.tick_agree.any() and r.tick_agree)],
                                     "n_candidates": [c.permno.nunique()], "match_method": [r.match_method]}))
    x = pd.concat(out, ignore_index=True)
    return merge_runs(x)


def merge_runs(x: pd.DataFrame) -> pd.DataFrame:
    x = x.sort_values(["ticker", "valid_from"]).reset_index(drop=True)
    same = ((x.ticker == x.ticker.shift()) & (x.permno == x.permno.shift())
            & (x.match_method == x.match_method.shift())
            & (x.valid_from <= x.valid_to.shift() + pd.Timedelta(days=1)))
    x["run"] = (~same).cumsum()
    agg = x.groupby("run").agg(ticker=("ticker", "first"), permaticker=("permaticker", "first"),
                               permno=("permno", "first"), valid_from=("valid_from", "min"),
                               valid_to=("valid_to", "max"), tick_agree=("tick_agree", "max"),
                               n_candidates=("n_candidates", "max"), match_method=("match_method", "first"))
    return agg.reset_index(drop=True)


def ticker_date_fill(s, n, unmapped: pd.DataFrame, claimed: pd.DataFrame | None = None) -> pd.DataFrame:
    """unmapped: (ticker, date) grid rows without a cusip8 permno. Match CRSP ticker on date."""
    rel = s.set_index("ticker").relatedtickers.fillna("").str.split().to_dict()
    pt = s.set_index("ticker").permaticker.to_dict()
    keys = []
    for tk in unmapped.ticker.unique():
        b = base_ticker(tk)
        for k in {b, *rel.get(b, [])}:
            keys.append((tk, k))
    kk = pd.DataFrame(keys, columns=["ticker", "crsp_ticker"])
    nn = n[["permno", "namedt", "nameenddt", "ticker", "shrcd"]].rename(columns={"ticker": "crsp_ticker"})
    cand = kk.merge(nn, on="crsp_ticker")
    u = unmapped.merge(cand, on="ticker")
    u = u[(u.date >= u.namedt) & (u.date <= u.nameenddt)]
    # never give a permno-date to a ticker_date match when a cusip8 match from another
    # Sharadar ticker already owns it (ROSEQ/BVH related-ticker collisions)
    if claimed is not None and not u.empty:
        cl = claimed.rename(columns={"ticker": "owner"})
        u = u.merge(cl, on=["date", "permno"], how="left")
        u = u[u.owner.isna()].drop(columns="owner")
    k = u.groupby(["ticker", "date"]).permno.nunique()
    ok = k[k == 1].index
    u = u.set_index(["ticker", "date"]).loc[ok].reset_index()[["ticker", "date", "permno"]].drop_duplicates()
    if u.empty:
        return pd.DataFrame(columns=["ticker", "permaticker", "permno", "valid_from", "valid_to", "tick_agree",
                                     "n_candidates", "match_method"])
    u = u.sort_values(["ticker", "date"])
    # runs of consecutive grid rows with the same permno
    brk = (u.ticker != u.ticker.shift()) | (u.permno != u.permno.shift())
    u["run"] = brk.cumsum()
    r = u.groupby("run").agg(ticker=("ticker", "first"), permno=("permno", "first"),
                             valid_from=("date", "min"), valid_to=("date", "max")).reset_index(drop=True)
    r["permaticker"] = [pt.get(base_ticker(t)) for t in r.ticker]
    r["tick_agree"] = True
    r["n_candidates"] = 1
    r["match_method"] = "ticker_date"
    return r


def attach(univ: pd.DataFrame, xw: pd.DataFrame) -> pd.Series:
    """permno for each (ticker, date) row of univ (NaN if none)."""
    u = univ[["ticker", "date"]].reset_index().sort_values("date")
    x = xw[["ticker", "permno", "valid_from", "valid_to"]].sort_values("valid_from")
    m = pd.merge_asof(u, x, left_on="date", right_on="valid_from", by="ticker", direction="backward")
    m.loc[m.date > m.valid_to, "permno"] = np.nan
    return m.set_index("index").permno.reindex(univ.index)


def main():
    grid = set(pd.read_parquet(GRID).ticker)
    s = load_sharadar(grid)
    n = load_crsp_names()
    c = cusip_candidates(s, n)
    xw = resolve(c)
    print("cusip8 intervals", len(xw), "tickers", xw.ticker.nunique(), "of grid", len(grid))

    univ = pd.read_parquet(UNIV, columns=["date", "ticker", "eligible_cap2000", "eligible_cap150"])
    univ["date"] = pd.to_datetime(univ.date)
    univ = univ[univ.ticker.isin(grid)].reset_index(drop=True)
    univ["permno"] = attach(univ, xw)
    um = univ.loc[univ.permno.isna(), ["ticker", "date"]]
    claimed = univ.loc[univ.permno.notna(), ["ticker", "date", "permno"]]
    fill = ticker_date_fill(s, n, um, claimed)
    print("ticker_date runs", len(fill), "tickers", fill.ticker.nunique())
    xw = pd.concat([xw, fill], ignore_index=True)
    xw["match_quality"] = np.where(xw.match_method == "ticker_date", "C", np.where(xw.tick_agree, "A", "B"))
    xw = xw.drop(columns="tick_agree")
    xw["permno"] = xw.permno.astype("int64")
    xw["permaticker"] = xw.permaticker.astype("Int64")
    xw = xw[["permno", "permaticker", "ticker", "valid_from", "valid_to", "match_method", "match_quality",
             "n_candidates"]].sort_values(["ticker", "valid_from"]).reset_index(drop=True)
    # sanity: no overlapping intervals within a ticker
    xs = xw.sort_values(["ticker", "valid_from"])
    ov = ((xs.ticker == xs.ticker.shift()) & (xs.valid_from <= xs.valid_to.shift())).sum()
    print("overlapping intervals within ticker:", int(ov))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    xw.to_parquet(OUT, index=False)
    print("wrote", OUT, xw.shape)

    univ["permno"] = attach(univ, xw)
    ins = univ[(univ.date >= "2007-01-01") & (univ.date <= "2019-12-31")]
    cov = {}
    for col in ["eligible_cap150", "eligible_cap2000"]:
        e = ins[ins[col]]
        byyr = e.groupby(e.date.dt.year).permno.apply(lambda v: float(v.notna().mean()))
        cov[col] = {"name_dates": int(len(e)), "mapped_share": float(e.permno.notna().mean()),
                    "min_year_share": float(byyr.min()), "by_year": {int(k): round(v, 4) for k, v in byyr.items()},
                    "unmapped_names": int(e.loc[e.permno.isna(), "ticker"].nunique())}
    # unmapped worst names (cap150)
    e = ins[ins.eligible_cap150 & ins.permno.isna()]
    worst = e.ticker.value_counts().head(25).to_dict()
    # many-to-one: one permno mapped from >1 ticker on the same date (cap2000, in-era)
    e2 = ins[ins.eligible_cap2000 & ins.permno.notna()]
    dup = e2.groupby(["date", "permno"]).ticker.nunique()
    qmix = xw.merge(ins[ins.eligible_cap2000][["ticker"]].drop_duplicates(), on="ticker").match_quality.value_counts().to_dict()
    summ = {"crosswalk": str(OUT), "rows": int(len(xw)), "tickers": int(xw.ticker.nunique()),
            "grid_tickers": len(grid), "method_counts": xw.match_method.value_counts().to_dict(),
            "quality_counts_incap2000": {k: int(v) for k, v in qmix.items()},
            "coverage_2007_2019": cov, "unmapped_cap150_top": {k: int(v) for k, v in worst.items()},
            "permno_dates_with_2plus_tickers_cap2000": int((dup > 1).sum()),
            "ambiguous_intervals": int((xw.n_candidates > 1).sum())}
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summ, indent=1, default=str))
    print(json.dumps({k: v for k, v in summ.items() if k != "coverage_2007_2019"}, default=str)[:1500])
    for col, v in cov.items():
        print(col, v["name_dates"], round(v["mapped_share"], 4), "min yr", round(v["min_year_share"], 4), "unmapped names", v["unmapped_names"])


if __name__ == "__main__":
    main()
