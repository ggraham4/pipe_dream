"""
WO-55 Phase 1: link OptionMetrics secids to Sharadar tickers point in time for the 80 dates
2019-01-16 .. 2025-08-20 and write the AV-shaped store + pull log the WO-37 harness reads.
Same as final/src/wrds_optionm/build_store.py (WO-52 amendment sections 2-3) except the link
repair fixed in the pre-reg (section 3), which only touches name-dates that the WO-52 chain leaves
`unlinked`:

  L1  A WO-51 crosswalk row whose valid_to equals 2024-12-31 (the end of the legacy crsp.stocknames
      vintage, i.e. a right-censored nameenddt) gets valid_to = Sharadar lastpricedate when that is
      later. This is WO-51's own rule valid_to = min(nameenddt, lastpricedate) with the censored
      nameenddt dropped.
  L2  Fallback, only for a name-date still unlinked after L1: Sharadar TICKERS.cusips (every listed
      CUSIP, first 8 chars) -> OptionMetrics secnmd.cusip -> secid (non index/ETF in securd).
      Several secids: the one with most rows on d, then the lowest secid. Rows on d -> ok,
      none -> no_data. No secid -> stays unlinked (non-terminal, as in WO-52).
  Every ok chain still has to pass av_keep's 5% secprd-vs-Sharadar close check downstream.

The log also carries status_frozen: the WO-52 chain with the WO-51 crosswalk unmodified (no L1/L2),
so the gate can be reported under both.

    /opt/anaconda3/envs/pipe_dream/bin/python final/src/cwspread_oos/build_store_oos.py

Presence only: no forward return is read.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
import pandas as pd

import oos_paths as P
from wo25_io import read_on_dates  # noqa: E402


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def sharadar_tickers():
    tmf = sorted((P.MAIN / "data" / "sharadar").glob("tickers_master*.csv"))[-1]
    tm = pd.read_csv(tmf, usecols=["ticker", "cusips", "lastpricedate"], low_memory=False)
    tm["lastpricedate"] = pd.to_datetime(tm.lastpricedate)
    tm = tm.sort_values("lastpricedate").drop_duplicates("ticker", keep="last")
    tm["ticker"] = tm.ticker.astype(str)
    return tm


def load_links(tm):
    X = pd.read_parquet(P.XWALK, columns=["permno", "ticker", "valid_from", "valid_to", "match_quality"])
    X["ticker"] = X.ticker.astype(str)
    XF = X.copy()                                         # frozen (WO-52) crosswalk
    cen = X.valid_to == pd.Timestamp(P.CRSP_LEGACY_END)   # L1
    lp = X.ticker.map(tm.set_index("ticker").lastpricedate)
    ext = cen & lp.notna() & (lp > X.valid_to)
    X.loc[ext, "valid_to"] = lp[ext]
    O = pd.read_parquet(P.OPCRSP)
    O = O[O.permno.notna() & O.sdate.notna()].copy()
    O["sdate"] = pd.to_datetime(O.sdate); O["edate"] = pd.to_datetime(O.edate)
    O["permno"] = O.permno.astype("int64")
    return X, XF, O, int(ext.sum())


def cusip_map(tm):
    """L2: Sharadar ticker -> set of OptionMetrics secids sharing any 8-char CUSIP (non index/ETF)."""
    sn = pd.read_parquet(P.SECNMD, columns=["secid", "cusip"]).dropna()
    sn["c8"] = sn.cusip.astype(str).str[:8]
    sd = pd.read_parquet(P.SECURD, columns=["secid", "issue_type"])
    bad = set(sd.secid[sd.issue_type.fillna("").isin(["A", "%"])])
    sn = sn[~sn.secid.isin(bad)].drop_duplicates(["c8", "secid"])
    ex = tm[["ticker", "cusips"]].dropna().copy()
    ex["c8"] = ex.cusips.str.split()
    ex = ex.explode("c8").dropna(subset=["c8"])
    ex["c8"] = ex.c8.str[:8]
    m = ex.merge(sn[["c8", "secid"]], on="c8").drop_duplicates(["ticker", "secid"])
    return m.groupby("ticker").secid.apply(lambda s: sorted(int(x) for x in s)).to_dict()


def chain_status(ud, x, O, nrows, dt):
    m = ud.merge(x[["ticker", "permno"]], on="ticker", how="left")
    o = O[(O.sdate <= dt) & (O.edate.isna() | (O.edate >= dt))][["permno", "secid", "score"]].copy()
    o["rows"] = o.secid.map(nrows).fillna(0)
    o = o.sort_values(["permno", "score", "rows"], ascending=[True, True, False]).drop_duplicates("permno")
    m = m.merge(o, on="permno", how="left")
    m["status"] = np.where(m.permno.isna(), "unlinked", np.where(m.secid.notna() & (m.rows > 0), "ok", "no_data"))
    return m


def main():
    t0 = time.time()
    P.MONTHLY.mkdir(parents=True, exist_ok=True)
    dates = sorted(p.stem.split("=")[1] for p in P.RAW.glob("date=*.parquet"))
    assert dates == P.entry_dates(), (len(dates), P.N_DATES)
    tm = sharadar_tickers()
    X, XF, O, n_ext = load_links(tm)
    cmap = cusip_map(tm)
    px = pd.read_parquet(P.SECPRD)
    px["date"] = pd.to_datetime(px.date).dt.strftime("%Y-%m-%d")
    px["close"] = px.close.abs()
    pxd = {d: g.set_index("secid").close for d, g in px.groupby("date")}
    u = read_on_dates(P.UNIVERSE, ["date", "ticker", "closeunadj", "eligible_cap2000", "eligible_cap150"], dates)
    u["ticker"] = u.ticker.astype(str)
    u = u[u.eligible_cap150 | u.eligible_cap2000]
    logs, linkstats = [], []
    for d in dates:
        dt = pd.Timestamp(d)
        ud = u[u.date == dt][["ticker", "closeunadj"]].drop_duplicates("ticker")
        raw = pd.read_parquet(P.RAW / f"date={d}.parquet")
        nrows = raw.groupby("secid").size()
        live = lambda XX: XX[(XX.valid_from <= dt) & (XX.valid_to >= dt)].sort_values("match_quality").drop_duplicates("ticker")  # noqa: E731
        mf = chain_status(ud, live(XF), O, nrows, dt)               # frozen WO-52 chain
        m = chain_status(ud, live(X), O, nrows, dt)                 # + L1
        m["link_path"] = np.where(m.permno.notna(), "crsp", None)
        # L2 fallback for the still-unlinked
        un = m.status == "unlinked"
        for i in np.where(un)[0]:
            cands = cmap.get(m.ticker.iat[i])
            if not cands:
                continue
            best = sorted(cands, key=lambda s: (-int(nrows.get(s, 0)), s))[0]
            r = int(nrows.get(best, 0))
            m.loc[m.index[i], ["secid", "rows", "link_path"]] = [best, r, "om_cusip"]
            m.loc[m.index[i], "status"] = "ok" if r > 0 else "no_data"
        cl = pxd.get(d, pd.Series(dtype=float))
        m["spot_parity"] = m.secid.map(cl)
        m["identity"] = np.where((m.status == "ok") & m.spot_parity.notna(), "verified", "unverified")
        m["symbol"] = np.where(m.secid.notna(), m.secid.fillna(-1).astype("int64").astype(str), None)
        m.loc[m.status != "ok", "symbol"] = None
        m["n"] = m.rows.fillna(0).astype(int)
        m = m.merge(mf[["ticker", "status"]].rename(columns={"status": "status_frozen"}), on="ticker", how="left")
        logs.append(pd.DataFrame({"pass": "monthly", "date": d, "ticker": m.ticker, "status": m.status, "symbol": m.symbol,
                                  "identity": m.identity, "spot_parity": m.spot_parity, "closeunadj": m.closeunadj,
                                  "n": m.n, "permno": m.permno, "secid": m.secid, "link_score": m.score,
                                  "link_path": m.link_path, "status_frozen": m.status_frozen}))
        ok = m[m.status == "ok"][["ticker", "secid", "closeunadj"]]
        a = raw.merge(ok, on="secid")
        mid = (a.best_bid + a.best_offer) / 2
        out = pd.DataFrame({
            "sharadar_ticker": a.ticker.astype(str), "av_symbol": a.secid.astype("int64").astype(str),
            "contractID": a.optionid.astype("int64").astype(str), "symbol": a.secid.astype("int64").astype(str),
            "expiration": pd.to_datetime(a.exdate).dt.strftime("%Y-%m-%d"), "strike": a.strike_price / 1000.0,
            "type": np.where(a.cp_flag == "C", "call", "put"), "last": np.nan, "mark": mid,
            "bid": a.best_bid.astype(float), "bid_size": 0, "ask": a.best_offer.astype(float), "ask_size": 0,
            "volume": a.volume.fillna(0).astype("int64"), "open_interest": a.open_interest.fillna(0).astype("int64"),
            "date": d, "om_iv": a.impl_volatility, "om_delta": a.delta,
            "om_last_date": pd.to_datetime(a.last_date).dt.strftime("%Y-%m-%d"), "closeunadj": a.closeunadj})
        dst = P.MONTHLY / f"date={d}.parquet"
        tmp = dst.with_suffix(".tmp"); out.to_parquet(tmp, index=False); os.replace(tmp, dst)
        linkstats.append({"date": d, "names": len(m), "unlinked": int((m.status == "unlinked").sum()),
                          "unlinked_frozen": int((m.status_frozen == "unlinked").sum()),
                          "ok": int((m.status == "ok").sum()), "no_data": int((m.status == "no_data").sum()),
                          "l2_used": int((m.link_path == "om_cusip").sum()), "rows": len(out)})
    L = pd.concat(logs, ignore_index=True)
    L.to_parquet(P.CALLS, index=False)
    S = pd.DataFrame(linkstats)
    okL = L[L.status == "ok"]
    rep = {"dates": len(S), "name_dates": int(S.names.sum()), "l1_rows_extended": n_ext,
           "unlinked_share": float(S.unlinked.sum() / S.names.sum()),
           "unlinked_share_frozen_chain": float(S.unlinked_frozen.sum() / S.names.sum()),
           "ok_share": float(S.ok.sum() / S.names.sum()), "no_data_share": float(S.no_data.sum() / S.names.sum()),
           "l2_name_dates": int(S.l2_used.sum()),
           "l2_ok_name_dates": int((okL.link_path == "om_cusip").sum()),
           "link_score_counts_ok": okL.link_score.value_counts(dropna=False).to_dict(),
           "identity_err_lt_5pct_share_of_ok": float(((okL.spot_parity / okL.closeunadj - 1).abs() < 0.05).mean()),
           "identity_err_lt_5pct_share_of_l2_ok": float(((okL.spot_parity / okL.closeunadj - 1).abs() < 0.05)[okL.link_path == "om_cusip"].mean())
           if (okL.link_path == "om_cusip").any() else None}
    P.OUT.mkdir(parents=True, exist_ok=True)
    (P.OUT / "store_build_report.json").write_text(json.dumps(rep, indent=1, default=str))
    log(f"store: {rep} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
