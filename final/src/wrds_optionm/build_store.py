"""
WO-52 Phase 1: link OptionMetrics secids to Sharadar tickers point in time and
write the AV-shaped store + pull log the WO-37 harness reads. Spec:
final/models/2026-10-08-thinliq-optionmetrics-amendment.md sections 2-3.

    /opt/anaconda3/envs/pipe_dream/bin/python final/src/wrds_optionm/build_store.py

Link chain on date d: Sharadar ticker -> permno (WO-51 permno_sharadar, valid_from <= d <= valid_to)
-> secid (opcrsphist, sdate <= d <= edate; lowest score, then most rows on d).
Statuses: unlinked (no permno; NOT terminal) / no_data (no secid or no rows) / ok.
Presence only: no forward return is read.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import om_paths as P  # noqa: E402

from wo25_io import read_on_dates  # noqa: E402  (from integration's options_wo25 via om_paths)


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def load_links():
    X = pd.read_parquet(P.XWALK, columns=["permno", "ticker", "valid_from", "valid_to", "match_quality"])
    X["ticker"] = X.ticker.astype(str)
    O = pd.read_parquet(P.OPCRSP)
    O = O[O.permno.notna() & O.sdate.notna()].copy()
    O["sdate"] = pd.to_datetime(O.sdate); O["edate"] = pd.to_datetime(O.edate)
    O["permno"] = O.permno.astype("int64")
    return X, O


def main():
    t0 = time.time()
    P.MONTHLY.mkdir(parents=True, exist_ok=True)
    dates = sorted(p.stem.split("=")[1] for p in P.RAW.glob("date=*.parquet"))
    assert len(dates) == 133, len(dates)
    X, O = load_links()
    px = pd.read_parquet(P.ROOT / "secprd.parquet")
    px["date"] = pd.to_datetime(px.date).dt.strftime("%Y-%m-%d")
    px["close"] = px.close.abs()
    pxd = {d: g.set_index("secid").close for d, g in px.groupby("date")}
    u = read_on_dates(P.UNIVERSE, ["date", "ticker", "closeunadj", "eligible_cap2000", "eligible_cap150"], dates)
    u["ticker"] = u.ticker.astype(str)
    u = u[u.eligible_cap150 | u.eligible_cap2000]
    logs = []
    linkstats = []
    for d in dates:
        dt = pd.Timestamp(d)
        ud = u[u.date == dt][["ticker", "closeunadj"]].drop_duplicates("ticker")
        raw = pd.read_parquet(P.RAW / f"date={d}.parquet")
        nrows = raw.groupby("secid").size()
        # ticker -> permno on d
        x = X[(X.valid_from <= dt) & (X.valid_to >= dt)].sort_values("match_quality").drop_duplicates("ticker")
        m = ud.merge(x[["ticker", "permno"]], on="ticker", how="left")
        # permno -> secid on d
        o = O[(O.sdate <= dt) & (O.edate.isna() | (O.edate >= dt))][["permno", "secid", "score"]].copy()
        o["rows"] = o.secid.map(nrows).fillna(0)
        o = o.sort_values(["permno", "score", "rows"], ascending=[True, True, False]).drop_duplicates("permno")
        m = m.merge(o, on="permno", how="left")
        m["status"] = np.where(m.permno.isna(), "unlinked",
                               np.where(m.secid.notna() & (m.rows > 0), "ok", "no_data"))
        cl = pxd.get(d, pd.Series(dtype=float))
        m["spot_parity"] = m.secid.map(cl)
        m["identity"] = np.where((m.status == "ok") & m.spot_parity.notna(), "verified", "unverified")
        m["symbol"] = np.where(m.secid.notna(), m.secid.fillna(-1).astype("int64").astype(str), None)
        m.loc[m.status != "ok", "symbol"] = None
        m["n"] = m.rows.fillna(0).astype(int)
        logs.append(pd.DataFrame({"pass": "monthly", "date": d, "ticker": m.ticker, "status": m.status, "symbol": m.symbol,
                                  "identity": m.identity, "spot_parity": m.spot_parity, "closeunadj": m.closeunadj,
                                  "n": m.n, "permno": m.permno, "secid": m.secid, "link_score": m.score}))
        # AV-shaped chain: every ok (ticker, secid) pair; av_keep decides identity downstream
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
                          "ok": int((m.status == "ok").sum()), "no_data": int((m.status == "no_data").sum()),
                          "rows": len(out)})
    L = pd.concat(logs, ignore_index=True)
    L.to_parquet(P.CALLS, index=False)
    S = pd.DataFrame(linkstats)
    rep = {"dates": len(S), "name_dates": int(S.names.sum()), "unlinked_share": float(S.unlinked.sum() / S.names.sum()),
           "ok_share": float(S.ok.sum() / S.names.sum()), "no_data_share": float(S.no_data.sum() / S.names.sum()),
           "link_score_counts_ok": L[L.status == "ok"].link_score.value_counts().to_dict(),
           "identity_err_lt_5pct_share_of_ok": float(((L.spot_parity / L.closeunadj - 1).abs() < 0.05)[L.status == "ok"].mean())}
    P.OUT.mkdir(parents=True, exist_ok=True)
    (P.OUT / "store_build_report.json").write_text(json.dumps(rep, indent=1, default=str))
    log(f"store: {rep} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
