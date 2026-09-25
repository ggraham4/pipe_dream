"""
WO-13 data validation (runs before the pre-registration commit; computes no
IC or portfolio number). Checks:
  - datekey: AAPL / MSFT 2015-2016 ARQ `date` vs reportperiod
  - filings per name per year among cap150 column-c names (median in [3.5, 4.5])
  - median |SUE| (pre-winsor) among those filings (roughly [0.5, 1.5])
  - coverage of finite `sue` among eligible cap150 column-c rows by year and by
    calendar month, old-grid vs added tickers
  - split proximity of |sue_raw| >= 10 filings (actions.csv)
Output: final/out/sue/validate_sue.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_sue as B  # noqa: E402

SH = B.MAIN / "data" / "sharadar"
R26 = B.MAIN / "out" / "reset2026"


def column_c_cap150():
    p = pd.read_parquet(B.PANEL_V2, columns=["ticker", "date", "eligible_cap150"],
                        filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    p = p[p["eligible_cap150"]].drop(columns="eligible_cap150")
    p["date"] = pd.to_datetime(p["date"]); p["ticker"] = p["ticker"].astype(str)
    old_t = set(pd.read_parquet(R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].astype(str).unique())
    tm = pd.read_csv(SH / "tickers_master.csv", dtype=str, usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    p = p[p["ticker"].isin(old_t) | ~p["ticker"].isin(spac)]
    p["added"] = ~p["ticker"].isin(old_t)
    assert p["date"].max() < B.HOLDOUT
    return p.reset_index(drop=True)


def main():
    r = {}
    fil = pd.read_parquet(B.OUT / "sue_filings.parquet")
    fac = pd.read_parquet(B.OUT / "sue_factor_v2.parquet", columns=["ticker", "date", "sue", "sue_age_days"])

    # datekey
    dk = fil[fil["ticker"].isin(["AAPL", "MSFT"]) & (fil["rp"] >= "2014-12-01") & (fil["rp"] <= "2016-12-31")]
    r["datekey"] = [{"ticker": t, "reportperiod": str(a.date()), "date": str(b.date()), "lag_days": int((b - a).days)}
                    for t, a, b in zip(dk["ticker"], dk["rp"], dk["date"])]
    lag = (fil["date"] - fil["rp"]).dt.days
    r["filing_lag_days_quantiles"] = {str(q): float(lag.quantile(q)) for q in (.01, .05, .25, .5, .75, .95, .99)}

    p = column_c_cap150()
    r["cap150_rows"] = int(len(p)); r["cap150_tickers"] = int(p["ticker"].nunique())
    r["cap150_tickers_added"] = int(p.loc[p["added"], "ticker"].nunique())
    arq_t = set(fil["ticker"])
    tk = p.drop_duplicates("ticker")
    r["cap150_tickers_without_any_arq"] = {
        "old": int((~tk.loc[~tk["added"], "ticker"].isin(arq_t)).sum()),
        "added": int((~tk.loc[tk["added"], "ticker"].isin(arq_t)).sum()),
        "examples": sorted(tk.loc[~tk["ticker"].isin(arq_t), "ticker"])[:30]}

    # filings per name-year among cap150 names (name eligible in that year)
    ny = p.assign(year=p["date"].dt.year)[["ticker", "year"]].drop_duplicates()
    f = fil.assign(year=fil["date"].dt.year)
    f = f[(f["year"] >= 2007) & (f["year"] <= 2019)]
    cnt = f.groupby(["ticker", "year"]).size().rename("n").reset_index()
    ny = ny.merge(cnt, on=["ticker", "year"], how="left").fillna({"n": 0})
    r["filings_per_name_year"] = {"median": float(ny["n"].median()), "mean": float(ny["n"].mean()),
                                  "median_given_any": float(ny.loc[ny["n"] > 0, "n"].median()),
                                  "share_zero": float((ny["n"] == 0).mean()),
                                  "dist": {int(k): int(v) for k, v in ny["n"].clip(upper=8).value_counts().sort_index().items()}}
    fc = f.merge(ny[["ticker", "year"]], on=["ticker", "year"])
    a = fc["sue_raw"].abs()
    r["abs_sue"] = {"median_raw": float(a.median()), "median_winsor": float(fc["sue"].abs().median()),
                    "n_finite": int(a.notna().sum()), "share_abs_ge_10": float((a >= 10).mean()),
                    "mean_winsor": float(fc["sue"].mean()), "share_positive": float((fc["sue"] > 0).mean())}

    # coverage
    p = p.merge(fac, on=["ticker", "date"], how="left")
    p["fin"] = p["sue"].notna()
    by = p.groupby([p["date"].dt.year, "added"])["fin"].mean().unstack()
    r["coverage_by_year"] = {int(y): {"all": float(p.loc[p["date"].dt.year == y, "fin"].mean()),
                                      "old": float(row.get(False, np.nan)), "added": float(row.get(True, np.nan))}
                             for y, row in by.iterrows()}
    r["coverage_by_month"] = {int(m): float(v) for m, v in p.groupby(p["date"].dt.month)["fin"].mean().items()}
    post = p[p["date"] >= "2009-01-01"]
    r["coverage_2009plus"] = {"all": float(post["fin"].mean()), "old": float(post.loc[~post["added"], "fin"].mean()),
                              "added": float(post.loc[post["added"], "fin"].mean())}
    # why missing (post-2009): no filing at all / stale / latest filing SUE NaN
    miss = post[~post["fin"]]
    r["missing_reasons_2009plus"] = {
        "no_filing_yet": float(miss["sue_age_days"].isna().mean()),
        "stale_gt_100d": float((miss["sue_age_days"] > B.STALE_DAYS).mean()),
        "latest_filing_sue_nan": float((miss["sue_age_days"] <= B.STALE_DAYS).mean())}

    # split proximity for extreme filings
    act = pd.read_csv(SH / "actions.csv", usecols=["date", "action", "ticker"], dtype=str)
    act = act[act["action"].str.contains("split", case=False, na=False)]
    act["date"] = pd.to_datetime(act["date"])
    sp = act.groupby("ticker")["date"].apply(list).to_dict()

    def near_split(t, d, days=3 * 365 + 30):
        return any(0 <= (d - s).days <= days for s in sp.get(t, []))
    ext = fc[fc["sue_raw"].abs() >= 10]
    nonext = fc[fc["sue_raw"].abs() < 10].sample(min(20000, len(fc)), random_state=0)
    r["split_check"] = {
        "extreme_n": int(len(ext)),
        "extreme_share_split_within_3y_before": float(np.mean([near_split(t, d) for t, d in zip(ext["ticker"], ext["date"])])) if len(ext) else None,
        "nonextreme_share_split_within_3y_before": float(np.mean([near_split(t, d) for t, d in zip(nonext["ticker"], nonext["date"])]))}
    out = B.OUT / "validate_sue.json"
    out.write_text(json.dumps(r, indent=2, default=str))
    print(json.dumps({k: v for k, v in r.items() if k not in ("datekey",)}, indent=1, default=str))


if __name__ == "__main__":
    main()
