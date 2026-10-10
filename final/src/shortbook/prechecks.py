"""WO-60 pre-freeze checks (NO outcome data): Markit fee units and link rate, in-era SI coverage,
and Gate A5 (live scorer vs backtest scorer on 3 dates).

Writes final/out/shortbook/prechecks.json (worktree).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "wrds_crsp"))
sys.path.insert(0, str(HERE.parent / "seasonality"))
import sb_common as K  # noqa: E402
import build_si as BS  # noqa: E402

MARKIT_DATE = pd.Timestamp("2011-03-21")
MARKIT_P = K.WRDS / "markit" / "amereqty2011.parquet"
A5_DATES = [pd.Timestamp("2015-03-19"), pd.Timestamp("2017-06-15"), pd.Timestamp("2019-03-21")]  # >= 2015: seas_live reads SEP from 2005-01 only


def markit_raw():
    if not MARKIT_P.exists():
        from wrdsdb import q
        MARKIT_P.parent.mkdir(parents=True, exist_ok=True)
        m = q("select datadate, cusip, isin, instrumentname, marketarea, indicativefee, indicativerebate, dcbs, "
              "utilisation, shortloanquantity, bb_ticker from mrktsamp_msf.amereqty2011")
        m.to_parquet(MARKIT_P)
    return pd.read_parquet(MARKIT_P)


def markit_linked():
    """US Equity rows linked CUSIP(8) -> CRSP stocknames.ncusip valid on MARKIT_DATE -> permno -> ticker."""
    m = markit_raw()
    m = m[m["marketarea"].str.startswith("US Equity")].copy()
    m["c8"] = m["cusip"].astype(str).str[:8]
    sn = pd.read_parquet(K.WRDS / "crsp" / "stocknames.parquet")
    for c in ("namedt", "nameenddt"):
        sn[c] = pd.to_datetime(sn[c])
    sn = sn[(sn["namedt"] <= MARKIT_DATE) & (sn["nameenddt"] >= MARKIT_DATE)][["ncusip", "permno"]].drop_duplicates("ncusip")
    x = m.merge(sn, left_on="c8", right_on="ncusip", how="left")
    ln = pd.read_parquet(K.WRDS / "link" / "permno_sharadar.parquet")
    ln["valid_from"] = pd.to_datetime(ln["valid_from"]); ln["valid_to"] = pd.to_datetime(ln["valid_to"]).fillna(pd.Timestamp("2099-12-31"))
    ln = ln[(ln["valid_from"] <= MARKIT_DATE + pd.Timedelta(days=31)) & (ln["valid_to"] >= MARKIT_DATE - pd.Timedelta(days=31))]
    x = x.merge(ln[["permno", "ticker"]].drop_duplicates("permno"), on="permno", how="left")
    return m, x


def a5(tier):
    import ic_weighted_composite as ICW
    import composite as C
    import seas_live as SL
    U, _ = K.load_features(tier)
    U["score_bt"] = K.score_icw5(U)
    res = []
    for d in A5_DATES:
        g = U[U["date"] == d].reset_index(drop=True)
        sf, info = SL.seas_asof(g["ticker"], d)
        g2 = g.copy()
        g2["seas"] = sf["seas"].to_numpy(np.float64)
        live = ICW.compute_composite_ic_weighted(g2, weights=ICW.PRODUCTION_WEIGHTS_V5_SEAS)["composite"].to_numpy()
        bt = g["score_bt"].to_numpy()
        seas_diff = np.abs(g2["seas"].to_numpy() - g["seas"].to_numpy())
        # bottom decile within vol quintile (live picker on the NEGATED score = lowest scores)
        def bottom(sc):
            pk = C.pick_decile_volq(g, pd.DataFrame({"ticker": g["ticker"], "composite": -sc}))
            return {t for t, _ in pk}
        bl, bb = bottom(live), bottom(bt)
        res.append({"date": str(d.date()), "n": int(len(g)), "max_abs_score_diff": float(np.nanmax(np.abs(live - bt))),
                    "score_nan_mismatch": int((np.isnan(live) != np.isnan(bt)).sum()),
                    "seas_max_abs_diff": float(np.nanmax(seas_diff)), "seas_nan_mismatch": int((np.isnan(g2["seas"]) != np.isnan(g["seas"])).sum()),
                    "seas_live_coverage": float(info["coverage"]),
                    "bottom_decile_n_live": len(bl), "bottom_decile_n_bt": len(bb),
                    "bottom_decile_overlap": float(len(bl & bb) / max(len(bl), 1))})
        K.log(f"A5 {tier} {res[-1]}")
    return res


def main():
    out = {}
    m, x = markit_linked()
    x["dcbs_i"] = x["dcbs"].round()
    out["markit"] = {"rows_all": int(len(markit_raw())), "rows_us_equity": int(len(m)),
                     "fee_nonnull_us": int(m["indicativefee"].notna().sum()),
                     "linked_permno": int(x["permno"].notna().sum()), "linked_ticker": int(x["ticker"].notna().sum()),
                     "median_fee_by_dcbs": {str(int(k)): float(v) for k, v in x.groupby("dcbs_i")["indicativefee"].median().items()},
                     "n_by_dcbs": {str(int(k)): int(v) for k, v in x.groupby("dcbs_i").size().items()},
                     "fee_quantiles_us": {str(qq): float(m["indicativefee"].quantile(qq)) for qq in (0.1, 0.5, 0.75, 0.9, 0.99)}}
    K.log(f"markit {out['markit']}")
    cov = {}
    for tier in ("cap2000", "cap150"):
        U, _ = K.load_features(tier)
        U["dtc"] = BS.attach(U)
        cov[tier] = {str(k): float(v) for k, v in U["dtc"].notna().groupby(U["date"].dt.year).mean().items()}
        cov[tier + "_close_lt5_share"] = float((U["close"] < 5).mean())
        K.log(f"SI coverage {tier}: {cov[tier]}")
    out["si_coverage_by_year"] = cov
    out["a5"] = {t: a5(t) for t in ("cap2000", "cap150")}
    K.OUT.mkdir(parents=True, exist_ok=True)
    (K.OUT / "prechecks.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
