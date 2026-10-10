"""WO-60 B2: option-implied borrow (put-call parity), cross-check of the B1 tiers ONLY.
Cost input, NOT a factor test; does NOT count toward the options tally.

WO-37 grid dates (final/data/wrds/optionm/opprcd/, 2008-01-02..2018-12-19). For each cap2000 and
cap150 bottom-decile name (engine base picks, shortable) on a grid date that is a panel date:
  pairs: same exdate & strike, 30 <= T(days) <= 120, |K/S - 1| <= 0.10, call & put bid > 0, mid prices
  q_impl = -ln((C - P + K e^{-rT}) / S) / T      (r = OptionMetrics zerocd interpolated at T)
  borrow = median_pairs(q_impl) - trailing 252d dividend yield (SEP closeadj/close)
American puts carry early-exercise value -> q_impl biased UP -> borrow overstated (conservative for
"are the B1 tiers too low?"). Reported: median B2 vs B1 fee by year, bottom decile and universe.
Writes final/out/shortbook/b2_implied_borrow.json.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "wrds_crsp"))
import engine as E  # noqa: E402
import sb_common as K  # noqa: E402

OM = K.WRDS / "optionm"


def zero_curve(dates):
    p = OM / "zerocd_wo60.parquet"
    if not p.exists():
        from wrdsdb import q
        ds = ",".join(f"'{d.date()}'" for d in dates)
        z = q(f"select date, days, rate from optionm.zerocd where date in ({ds})")
        z.to_parquet(p)
    z = pd.read_parquet(p)
    z["date"] = pd.to_datetime(z["date"])
    return z


def main():
    dates = sorted(pd.Timestamp(f.stem.split("=")[1]) for f in (OM / "opprcd").glob("date=*.parquet"))
    dates = [d for d in dates if d <= K.SIG_HI]
    z = zero_curve(dates)
    lk = pd.read_parquet(K.WRDS / "link" / "opcrsphist.parquet")
    lk["sdate"] = pd.to_datetime(lk["sdate"]); lk["edate"] = pd.to_datetime(lk["edate"])
    lk = lk[lk["score"] == 1]
    ln = pd.read_parquet(K.WRDS / "link" / "permno_sharadar.parquet")
    ln["valid_from"] = pd.to_datetime(ln["valid_from"]); ln["valid_to"] = pd.to_datetime(ln["valid_to"]).fillna(pd.Timestamp("2099-12-31"))
    spx = pd.read_parquet(OM / "secprd.parquet"); spx["date"] = pd.to_datetime(spx["date"])
    sep = pd.read_parquet(K.OUT_BIG / "sep_2007_2019.parquet", columns=["ticker", "date", "f"])
    sep = sep.sort_values(["ticker", "date"])
    sep["f_lag"] = sep.groupby("ticker")["f"].shift(252)
    sep["dy"] = (sep["f"] / sep["f_lag"] - 1.0).clip(lower=0, upper=0.2)
    res = {}
    rows_all = []
    for tier in ("cap2000", "cap150"):
        E.load(tier)
        R = E.G["R"]; base = np.load(K.OUT_BIG / f"pick_base_{tier}.npy") & E.G["shortable"]
        R = R.assign(book=base)
        for d in dates:
            g = R[R["date"] == d][["ticker", "book", "fee"]]
            if g.empty:
                continue
            o = pd.read_parquet(OM / "opprcd" / f"date={d.date()}.parquet",
                                columns=["secid", "exdate", "cp_flag", "strike_price", "best_bid", "best_offer"])
            l = lk[(lk["sdate"] <= d) & (lk["edate"] >= d)][["secid", "permno"]]
            t = ln[(ln["valid_from"] <= d) & (ln["valid_to"] >= d)][["permno", "ticker"]]
            m = l.merge(t, on="permno").drop_duplicates("ticker")
            g = g.assign(base=g["ticker"].str.split("__").str[0]).merge(m.rename(columns={"ticker": "base"}), on="base", how="inner")
            if g.empty:
                continue
            o = o[o["secid"].isin(g["secid"])]
            o["exdate"] = pd.to_datetime(o["exdate"])
            o["T"] = (o["exdate"] - d).dt.days
            o = o[(o["T"] >= 30) & (o["T"] <= 120) & (o["best_bid"] > 0)]
            o["mid"] = (o["best_bid"] + o["best_offer"]) / 2
            o["K"] = o["strike_price"] / 1000.0
            c = o[o["cp_flag"] == "C"][["secid", "exdate", "K", "T", "mid"]]
            p = o[o["cp_flag"] == "P"][["secid", "exdate", "K", "mid"]]
            pr = c.merge(p, on=["secid", "exdate", "K"], suffixes=("_c", "_p"))
            S = spx[spx["date"] == d][["secid", "close"]]
            pr = pr.merge(S, on="secid")
            pr = pr[(pr["K"] / pr["close"] - 1).abs() <= 0.10]
            zd = z[z["date"] == d].sort_values("days")
            pr["r"] = np.interp(pr["T"], zd["days"], zd["rate"]) / 100.0 if len(zd) else 0.0
            Ty = pr["T"] / 365.0
            arg = (pr["mid_c"] - pr["mid_p"] + pr["K"] * np.exp(-pr["r"] * Ty)) / pr["close"]
            pr["q"] = -np.log(arg.where(arg > 0)) / Ty
            qn = pr.groupby("secid")["q"].median().rename("q_impl").reset_index()
            g = g.merge(qn, on="secid", how="inner")
            dy = sep[sep["date"] == d][["ticker", "dy"]].rename(columns={"ticker": "base"})
            g = g.merge(dy, on="base", how="left")
            g["b2"] = g["q_impl"] - g["dy"].fillna(0.0)
            g["date"] = d; g["tier"] = tier
            rows_all.append(g[["tier", "date", "ticker", "book", "fee", "q_impl", "dy", "b2"]])
        K.log(f"[{tier}] done")
    A = pd.concat(rows_all, ignore_index=True)
    A.to_parquet(K.OUT_BIG / "b2_rows.parquet")
    A["year"] = A["date"].dt.year
    for tier in ("cap2000", "cap150"):
        for nm, msk in (("bottom_decile", A["book"]), ("universe", A["book"] | ~A["book"])):
            s = A[(A["tier"] == tier) & msk]
            by = s.groupby("year").agg(n=("b2", "size"), b2_median=("b2", "median"), b1_median=("fee", "median"))
            by["b2_p75"] = s.groupby("year")["b2"].quantile(0.75)
            by["b2_p90"] = s.groupby("year")["b2"].quantile(0.9)
            res[f"{tier}_{nm}"] = {"by_year": {int(y): {k: float(v) for k, v in r.items()} for y, r in by.iterrows()},
                                   "all": {"n": int(len(s)), "b2_median": float(s["b2"].median()), "b2_mean_trim": float(s["b2"].clip(-0.2, 0.5).mean()),
                                           "b2_p90": float(s["b2"].quantile(0.9)), "b1_median": float(s["fee"].median()),
                                           "share_b2_gt_b1_plus_3pct": float((s["b2"] > s["fee"] + 0.03).mean()),
                                           "share_b2_gt_10pct": float((s["b2"] > 0.10).mean())}}
    (K.OUT / "b2_implied_borrow.json").write_text(json.dumps(res, indent=1))
    for k, v in res.items():
        print(k, v["all"])


if __name__ == "__main__":
    main()
