"""
WO-61: the WO-58 Stage-1 frame (133 dates) with base and variant pick rows, plus the CRSP 40-day label
(a re-implementation of WO-51 phase3.crsp_labels, checked against WO-51's stored r_C before use).
Research code only; never trades.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import ta_common as A
import common as K     # wrds_crsp/common.py (WO-51)

B, log = A.B, A.log
H = 40
DAY0 = np.datetime64("1990-01-01", "D")


def wo58_frame():
    """WO-58 Stage-1 frame exactly as run_book.run_stage builds it (cb_core), labels attached."""
    b, pool, dates, info = B.load_book(1)
    D, uniq = B.prep(b)
    base = [B.picks_for(dd) for dd in D]
    var = [B.picks_for(dd, ~dd["bottom"]) for dd in D]
    D = B.attach_labels(D, b, dates, 1)
    return b, D, uniq, dates, base, var, info


def pick_rows(D, uniq, picks, b):
    """One row per realised pick (NaN-label picks dropped, weights renormalised, as cb_core.evaluate)."""
    rows = []
    for i, dd in enumerate(D):
        idx, w = picks[i]
        if len(idx) == 0:
            continue
        r = dd["ret"][idx]
        ok = np.isfinite(r)
        if not ok.any():
            continue
        wn = w[ok] / w[ok].sum()
        ii = idx[ok]
        rows.append(pd.DataFrame({"i": i, "date": dd["date"], "pos": ii, "ticker": uniq[dd["tick"][ii]],
                                  "wn": wn, "r_S": r[ok], "closeunadj": dd["close"][ii],
                                  "seas_nan": ~np.isfinite(dd["F"][:, list(B.FT).index("seas")][ii])}))
    pr = pd.concat(rows, ignore_index=True)
    pr["date"] = pd.to_datetime(pr.date).astype("datetime64[ns]")
    return pr


def crsp_labels(pr, cal, dsf, dl):
    """WO-51 phase3.crsp_labels, re-implemented (same rule): r_C retx basis, r_C_ret ret basis; fallback -> r_S."""
    pr = pr.reset_index(drop=True)
    dates = pr.date.values.astype("datetime64[ns]")
    ci = np.searchsorted(cal, dates)
    assert (cal[np.minimum(ci, len(cal) - 1)] == dates).all(), "pick date not on calendar"
    assert (ci + H < len(cal)).all(), "calendar too short"
    e, x = cal[ci + 1], cal[ci + H]
    pr = pr.assign(e=e, x=x)
    key = dsf.permno.values.astype(np.int64) * 100000 + (dsf.date.values.astype("datetime64[D]") - DAY0).astype(np.int64)
    assert np.all(np.diff(key) > 0)
    rx = dsf.retx.to_numpy(np.float64); rt = dsf.ret.to_numpy(np.float64)
    Lx = np.cumsum(np.log1p(np.where(np.isfinite(rx), rx, 0.0)))
    Lt = np.cumsum(np.log1p(np.where(np.isfinite(rt), rt, 0.0)))
    Nx = np.cumsum(~np.isfinite(rx)); Nt = np.cumsum(~np.isfinite(rt))
    prc = np.abs(dsf.prc.to_numpy(np.float64)); opn = dsf.openprc.to_numpy(np.float64)
    perm = dsf.permno.to_numpy(np.int64); ddate = dsf.date.values.astype("datetime64[ns]")
    mapped = pr.permno.notna().to_numpy()
    pm = np.where(mapped, pr.permno.fillna(0).to_numpy(), 0).astype(np.int64)
    ke = pm * 100000 + (e.astype("datetime64[D]") - DAY0).astype(np.int64)
    kx = pm * 100000 + (x.astype("datetime64[D]") - DAY0).astype(np.int64)
    ie = np.clip(np.searchsorted(key, ke), 0, len(key) - 1)
    has_e = mapped & (key[ie] == ke)
    ix = np.clip(np.searchsorted(key, kx, side="right") - 1, 0, len(key) - 1)
    ok = has_e & (perm[ix] == pm) & (ix >= ie)
    chain_x = np.exp(Lx[ix] - Lx[ie]); chain_t = np.exp(Lt[ix] - Lt[ie])
    nan_x = (Nx[ix] - Nx[ie]) > 0; nan_t = (Nt[ix] - Nt[ie]) > 0
    open_ok = np.isfinite(opn[ie]) & (opn[ie] > 0)
    prc_ok = np.isfinite(prc[ie]) & (prc[ie] > 0)
    entry = np.where(open_ok & prc_ok, prc[ie] / np.where(open_ok, opn[ie], 1.0), np.nan)
    need = np.flatnonzero(ok & ~open_ok & prc_ok)
    if len(need):
        ohlc = K.load_ohlc(sorted(set(pr.ticker.values[need])), A.READ_CAP)
        for j in need:
            g = ohlc.get(pr.ticker.values[j])
            if g is None:
                continue
            m = g[g.date.values == e[j]]
            if len(m) and m.open.iloc[0] > 0 and np.isfinite(m.close.iloc[0]):
                entry[j] = m.close.iloc[0] / m.open.iloc[0]
    exit_short = ok & (ddate[ix] < x)
    dlm = dl.reindex(pm)
    dlstdt = dlm.dlstdt.values.astype("datetime64[ns]")
    dl_in = mapped & (dlstdt > e) & (dlstdt <= x)
    apply_dl = exit_short & dl_in
    dlr = dlm.dlret.to_numpy(np.float64); dlrx = dlm.dlretx.to_numpy(np.float64)
    dl_use = np.where(np.isfinite(dlr), dlr, np.where(np.isfinite(dlrx), dlrx, np.nan))
    dl_base = np.where(apply_dl & np.isfinite(dl_use), dl_use, 0.0)
    good_x = ok & np.isfinite(entry) & ~nan_x
    good_t = ok & np.isfinite(entry) & ~nan_t
    r_C = np.where(good_x, entry * chain_x * (1 + dl_base) - 1, np.nan)
    r_Ct = np.where(good_t, entry * chain_t * (1 + dl_base) - 1, np.nan)
    reason = np.where(~mapped, "unmapped", np.where(~has_e, "no_crsp_row_on_e",
                      np.where(~ok, "no_crsp_rows", np.where(~np.isfinite(entry), "entry_leg_nan",
                               np.where(nan_x, "nan_retx_in_window", "")))))
    pr = pr.assign(r_C=r_C, r_C_ret=r_Ct, fallback=~good_x, fallback_t=~good_t, fb_reason=reason,
                   delist_applied=good_x & apply_dl, exit_short=good_x & exit_short,
                   last_crsp_date=np.where(ok, ddate[ix], np.datetime64("NaT")))
    pr["r_C"] = pr["r_C"].where(~pr.fallback, pr.r_S)
    pr["r_C_ret"] = pr["r_C_ret"].where(~pr.fallback_t, pr.r_S)
    return pr


def crsp_inputs(permnos):
    cal = K.market_calendar(A.READ_CAP)
    dsf = K.load_dsf(years=range(2008, 2020), permnos=permnos, cutoff=A.READ_CAP)
    return cal, dsf, K.load_delist()


def attach_permno(pr):
    pr = pr.copy()
    pr["permno"] = K.attach(pr, K.crosswalk())
    return pr


def evaluate_with(D, picks, pr, col, cost_bps=15.0):
    """cb_core.evaluate with the pick rows' labels replaced by pr[col] (same picks, weights, dates)."""
    D2 = []
    for i, dd in enumerate(D):
        d2 = dict(dd)
        d2["ret"] = dd["ret"].copy()
        D2.append(d2)
    for i, pos, v in zip(pr.i.to_numpy(), pr.pos.to_numpy(), pr[col].to_numpy(np.float64)):
        D2[i]["ret"][pos] = v
    ev, _ = B.evaluate(D2, picks, cost_bps)
    return B.level(ev), B.level(ev, "gx"), ev
