"""WO-60 per-row prep (pre-reg final/models/2026-10-10-short-book-prereg.md, frozen c8f32d1).

For each tier: eligible universe rows 2007-01-03..2019-10-24 with
  score (icw5_seas), volatility_60, sector, entry_open (open[t+1]), stock total return over the
  40d hold incl. dividends and the CRSP delisting adjustment, delisting class, B1 fee, days_to_cover,
  DTC quintile (cap150 universe, within date), beta_252.
Writes (gitignored, main checkout) final/out/shortbook/rows_<tier>.parquet and
(worktree) final/out/shortbook/b1_tiermap.json.

OUTCOME CUT: signal rows with date > 2019-10-24 are dropped (load_features asserts it) BEFORE any
return column is read; the outcome cache's gross_return_40 is read with a date <= 2019-10-24 filter;
no price after 2019-12-31 is read.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sb_common as K  # noqa: E402
import build_si as BS  # noqa: E402
import prechecks as PC  # noqa: E402

MAX_DIV = 0.25


def sep_prices():
    p = K.OUT_BIG / "sep_2007_2019.parquet"
    if p.exists():
        return pd.read_parquet(p)
    files = sorted(f for f in K.SEP_DIR.glob("*.parquet") if "2006-12" <= f.stem <= "2019-12")
    parts = [pd.read_parquet(f, columns=["ticker", "date", "open", "close", "closeadj"]) for f in files]
    s = pd.concat(parts, ignore_index=True)
    s = K._dt(s)
    s = s[s["date"] <= K.PRICE_HI].drop_duplicates(["ticker", "date"])
    s["f"] = s["closeadj"] / s["close"]
    s = s[["ticker", "date", "open", "close", "f"]]
    K.OUT_BIG.mkdir(parents=True, exist_ok=True)
    s.to_parquet(p)
    return s


def series_frame():
    """Outcome-cache date structure (no return column) <= PRICE_HI: per row the entry date (i+1),
    exit date (min(i+40, n-1)) and series last date."""
    o = pd.read_parquet(K.OUTCOME, columns=["ticker", "date"], filters=[("date", "<=", K.PRICE_HI)])
    o = K._dt(o)
    o = o[~o["ticker"].isin(["SPY", "USMV"])].sort_values(["ticker", "date"]).reset_index(drop=True)
    g = o.groupby("ticker", sort=False)
    i = g.cumcount().to_numpy()
    n = g["date"].transform("size").to_numpy()
    start = np.arange(len(o)) - i
    d = o["date"].to_numpy()
    e = np.minimum(i + 1, n - 1) + start
    x = np.minimum(i + K.H, n - 1) + start
    o["d_e"] = d[e]
    o["has_next"] = (i + 1) <= (n - 1)
    o["d_x"] = d[x]
    o["d_last"] = d[start + n - 1]
    return o


def labels():
    oc = pd.read_parquet(K.OUTCOME, columns=["ticker", "date", "gross_return_40", "truncated"],
                         filters=[("date", ">=", K.ERA_LO), ("date", "<=", K.SIG_HI)])
    oc = K._dt(oc)
    assert oc["date"].max() <= K.SIG_HI, "HOLD-OUT BREACH (labels)"
    return oc


def delist_table():
    dl = pd.read_parquet(K.WRDS / "crsp" / "dsedelist.parquet", columns=["permno", "dlstdt", "dlstcd", "dlret"])
    dl["dlstdt"] = pd.to_datetime(dl["dlstdt"]).astype("datetime64[ns]")
    dl = dl[dl["dlstcd"] >= 200]
    ln = pd.read_parquet(K.WRDS / "link" / "permno_sharadar.parquet")
    ln["valid_from"] = pd.to_datetime(ln["valid_from"]).astype("datetime64[ns]")
    ln["valid_to"] = pd.to_datetime(ln["valid_to"]).astype("datetime64[ns]").fillna(pd.Timestamp("2099-12-31"))
    return dl, ln


def delist_adjust(R):
    """Rows needing the delisting rule: truncated or no next bar. Adds dl, dl_class, permno."""
    dl, ln = delist_table()
    need = R[R["trunc"] | ~R["has_next"]][["ticker", "d_last"]].drop_duplicates()
    need["base"] = need["ticker"].str.split("__").str[0]
    m = need.merge(ln[["permno", "ticker", "valid_from", "valid_to"]].rename(columns={"ticker": "base"}), on="base", how="left")
    m = m[m["permno"].isna() | ((m["d_last"] >= m["valid_from"] - pd.Timedelta(days=31)) & (m["d_last"] <= m["valid_to"] + pd.Timedelta(days=31)))]
    m = m.merge(dl, on="permno", how="left")
    ok = (m["dlstdt"] >= m["d_last"] - pd.Timedelta(days=5)) & (m["dlstdt"] <= m["d_last"] + pd.Timedelta(days=60))
    m["dlstcd"] = m["dlstcd"].where(ok); m["dlret"] = m["dlret"].where(ok)
    m["has_dl"] = ok
    m = m.sort_values(["ticker", "d_last", "has_dl"], ascending=[True, True, False]).drop_duplicates(["ticker", "d_last"])
    cd = m["dlstcd"]
    dlv = m["dlret"].copy()
    miss = dlv.isna() & cd.notna()
    dlv[miss & (cd >= 400) & (cd < 600)] = -0.30
    dlv = dlv.fillna(0.0)
    cls = np.select([cd.between(200, 299), cd.between(300, 399), cd.between(400, 499), cd.between(500, 599),
                     m["permno"].notna()], ["merger_2xx", "exchange_3xx", "liquidation_4xx", "drop_5xx", "crsp_active_or_nomatch"],
                    default="unlinked")
    m["dl"] = dlv.to_numpy(); m["dl_class"] = cls
    m["dl_imputed"] = miss.to_numpy()
    R = R.merge(m[["ticker", "d_last", "dl", "dl_class", "dl_imputed", "permno", "dlstcd"]], on=["ticker", "d_last"], how="left")
    need_mask = R["trunc"] | ~R["has_next"]
    R.loc[~need_mask, ["dl"]] = 0.0
    R.loc[~need_mask, "dl_class"] = "full_window"
    R["dl"] = R["dl"].fillna(0.0)
    R["dl_class"] = R["dl_class"].fillna("unlinked")
    return R


def b1_tiermap(U150):
    """Fit on Markit 2011-03-21 x cap150 universe: cells (DTC quintile within date) x (close < 5)."""
    _, x = PC.markit_linked()
    x = x.dropna(subset=["ticker"]).drop_duplicates("ticker")
    g = U150[U150["date"] == PC.MARKIT_DATE][["ticker", "dtcq", "close"]].copy()
    g = g.merge(x[["ticker", "indicativefee", "dcbs", "utilisation"]], on="ticker", how="left")
    g["lt5"] = g["close"] < 5
    fit = g.dropna(subset=["indicativefee"])
    cells = {}
    for q in [0, 1, 2, 3, 4]:
        for lt5 in (False, True):
            s = fit[(fit["dtcq"] == q) & (fit["lt5"] == lt5)]["indicativefee"]
            cells[f"q{q+1}_lt5{int(lt5)}"] = {"n": int(len(s)), "median": float(s.median()) if len(s) else None}
    meds = [c["median"] for c in cells.values() if c["median"] is not None]
    fmax = max(meds)
    for c in cells.values():
        if c["median"] is None:
            c["median"] = fmax; c["note"] = "empty cell -> max tier (conservative)"
    tm = {"fit_date": "2011-03-21", "universe": "cap150 eligible", "n_universe": int(len(g)),
          "n_linked_fee": int(len(fit)), "link_rate": float(len(fit) / len(g)), "cells": cells,
          "missing_si_fee": fmax, "units": "annual fraction"}
    return tm, g


def fee_of(dtcq, close, tm):
    fee = np.full(len(dtcq), tm["missing_si_fee"])
    for q in range(5):
        for lt5 in (False, True):
            m = (dtcq == q) & ((close < 5) == lt5)
            fee[m] = tm["cells"][f"q{q+1}_lt5{int(lt5)}"]["median"]
    return fee


def main():
    sep = sep_prices()
    K.log(f"SEP {len(sep):,} rows")
    sf = series_frame()
    K.log(f"series {len(sf):,} rows")
    lab = labels()
    # cap150 DTC quintiles within date (used by both tiers' fees)
    U150, _ = K.load_features("cap150")
    U150["dtc"] = BS.attach(U150)
    U150["dtcq"] = U150.groupby("date")["dtc"].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False))
    tm, g11 = b1_tiermap(U150)
    K.OUT.mkdir(parents=True, exist_ok=True)
    (K.OUT / "b1_tiermap.json").write_text(json.dumps(tm, indent=1))
    g11.to_parquet(K.OUT_BIG / "markit_2011_cap150.parquet")
    K.log(f"B1 tier map {json.dumps(tm)}")
    dq = U150[["ticker", "date", "dtc", "dtcq"]]
    beta = pd.read_parquet(K.BETA, columns=["ticker", "date", "beta_252"], filters=K.filt(K.BETA, K.ERA_LO, K.SIG_HI))
    beta = K._dt(beta)
    sep_e = sep.rename(columns={"ticker": "base", "date": "d_e", "open": "open_e", "f": "f_e"})[["base", "d_e", "open_e", "f_e"]]
    sep_x = sep.rename(columns={"ticker": "base", "date": "d_x", "close": "close_x", "f": "f_x"})[["base", "d_x", "close_x", "f_x"]]
    for tier in ("cap2000", "cap150"):
        U, all_dates = K.load_features(tier)
        U["score"] = K.score_icw5(U)
        n0 = len(U)
        U = U.merge(dq, on=["ticker", "date"], how="left").merge(beta, on=["ticker", "date"], how="left")
        U = U.merge(sf, on=["ticker", "date"], how="left")
        U["base"] = U["ticker"].str.split("__").str[0]
        U = U.merge(sep_e, on=["base", "d_e"], how="left").merge(sep_x, on=["base", "d_x"], how="left")
        U = U.merge(lab, on=["ticker", "date"], how="left")
        assert len(U) == n0, "merge changed rows"
        assert U["date"].max() <= K.SIG_HI
        U["has_next"] = U["has_next"].fillna(False).astype(bool)
        U["trunc"] = U["truncated"].fillna(True).astype(bool)
        r_px = U["gross_return_40"].astype(np.float64)
        # NaN label (no next bar or bad price): price return 0 to last close
        U["label_nan"] = r_px.isna()
        r_px = r_px.fillna(0.0)
        div = (U["close_x"] / U["open_e"]) * (U["f_x"] / U["f_e"] - 1.0)
        bad = ~np.isfinite(div) | (div.abs() > MAX_DIV)
        U["div_zeroed"] = bad & U["open_e"].notna()
        U["div"] = div.where(~bad, 0.0)
        U["r_px"] = r_px
        U = delist_adjust(U)
        U["r_tot"] = (1.0 + U["r_px"] + U["div"]) * (1.0 + U["dl"]) - 1.0
        U["fee"] = fee_of(U["dtcq"].to_numpy(), U["close"].to_numpy(), tm)
        U["entry_open"] = U["open_e"].where(U["has_next"])
        U["px_chk"] = U["close_x"] / U["open_e"] - 1.0 - U["r_px"]
        keep = ["date", "ticker", "score", "volatility_60", "sector", "close", "entry_open", "market_cap",
                "dtc", "dtcq", "beta_252", "r_px", "div", "dl", "r_tot", "trunc", "label_nan", "has_next",
                "dl_class", "dl_imputed", "dlstcd", "permno", "d_e", "d_x", "d_last", "fee", "div_zeroed", "px_chk"]
        U = U[keep].sort_values(["date", "ticker"]).reset_index(drop=True)
        U.to_parquet(K.OUT_BIG / f"rows_{tier}.parquet")
        pd.Series([str(d.date()) for d in all_dates]).to_csv(K.OUT_BIG / f"all_dates_{tier}.csv", index=False)
        K.log(f"[{tier}] rows {len(U):,}; trunc {U['trunc'].mean():.4f}; label_nan {U['label_nan'].sum()}; "
              f"div_zeroed {U['div_zeroed'].sum()}; px_chk |.|>1e-4 {(U['px_chk'].abs() > 1e-4).mean():.4f}; "
              f"dl_class {U['dl_class'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
