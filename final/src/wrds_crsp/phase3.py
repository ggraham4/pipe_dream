"""WO-51 Phase 3 (pre-registered, final/models/2026-10-08-crsp-sharadar-audit.md, hash-frozen).

icw8, v2 column c, cap150, net 15bp, h=40, 40 offsets, 2007-01-02..2019-12-31.
Run S = WO-6 harness (Sharadar labels). Run C = identical picks, each pick's 40-day return rebuilt
from CRSP on the market calendar:
  entry leg = |prc|/openprc on e (Sharadar close/open on e if openprc missing/0, counted),
  then prod(1+retx) over CRSP rows with e < date <= x (any NaN in the product -> CRSP label NaN),
  if the permno's CRSP rows stop before x: exit at the last CRSP price, and x(1+dlret) only if the
  CRSP delisting date lies in (e, x] (dlret, else dlretx, else 0 counted).
  Fallback to the Sharadar label (counted, share of pick weight): unmapped on t, no CRSP row on e,
  or CRSP label NaN.

  python phase3.py --anchors   anchor windows only (smoke test + independent hand check)
  python phase3.py             full run

Writes final/out/wrds_crsp/phase3.json / phase3_anchors.json (aggregates only) and
final/data/wrds/crsp/derived/phase3_pickrows.parquet (per pick-row CRSP values; never committed).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as K  # noqa: E402

HARNESS = Path("/tmp/wo51_src/final/src")  # read-only `git archive origin/integration final/src`
sys.path.insert(0, str(HARNESS / "reset2026"))
sys.path.insert(0, str(HARNESS))
import composite as C  # noqa: E402
import run_backtest as RB  # noqa: E402
import ic_weighted_composite as ICW  # noqa: E402

TIER = "cap150"
COST_BPS = 15.0
LABEL = "forward_return_tradable_40"
WO6_ICW8_C_CAP150 = 0.028541632641009042   # readout.json columns.c.cap150.icw8 excess_cagr_vs_spy_mean40
H = 40
DAY0 = np.datetime64("1990-01-01", "D")

assert dict(K.ICW8) == dict(ICW.PRODUCTION_WEIGHTS), "extracted harness no longer holds icw8"
assert RB.HORIZON == H


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def load_column_c():
    cols = ["ticker", "date", LABEL] + C.FACTOR_COLS + [f"eligible_{TIER}"]
    filt = [("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")]
    old_t = set(pd.read_parquet(K.R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].unique())
    p = pd.read_parquet(K.R26 / "composite_panel_v2.parquet", columns=cols, filters=filt)
    tm = pd.read_csv(K.FINAL / "data/sharadar/tickers_master.csv", dtype=str,
                     usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    p = p[p["ticker"].isin(old_t) | ~p["ticker"].isin(spac)]
    p["date"] = pd.to_datetime(p["date"])
    p["ticker"] = p["ticker"].astype(str)
    p = p[(p.date >= K.START) & (p.date <= K.END)]
    assert p.date.max() < K.HOLDOUT
    oc = load_oc()
    spy = oc[oc.ticker == "SPY"].set_index("date")["gross_return_40"]
    n = len(p)
    p = p.merge(oc[~oc.ticker.isin(["SPY", "USMV"])], on=["ticker", "date"], how="left")
    assert len(p) == n
    log(f"column c: {len(p):,} rows, {p.ticker.nunique():,} tickers")
    return p, spy


def load_oc(tickers=None):
    filt = [("date", ">=", K.START), ("date", "<=", K.END)]
    if tickers is not None:
        filt.append(("ticker", "in", list(tickers)))
    oc = pd.read_parquet(K.R26 / "outcome_cache_v2.parquet", columns=["ticker", "date", "gross_return_40"],
                         filters=filt)
    oc["date"] = pd.to_datetime(oc["date"])
    oc["ticker"] = oc["ticker"].astype(str)
    assert oc.date.max() < K.HOLDOUT
    return oc


def pick_rows(p):
    """Per date: the icw8 decile_volq picks with a non-NaN Sharadar label (exactly as the harness)."""
    rows = []
    all_dates = sorted(p.date.unique())
    for d, g in p.groupby("date", sort=True):
        elig = g[g[f"eligible_{TIER}"]]
        if len(elig) < C.N_VOL_QUINTILES * 4:
            continue
        elig = elig.reset_index(drop=True)
        ret = dict(zip(elig.ticker, elig.gross_return_40))
        picks = C.pick_decile_volq(elig, ICW.compute_composite_ic_weighted(elig, weights=dict(K.ICW8)))
        picks = [(t, w) for t, w in picks if pd.notna(ret.get(t))]
        if not picks:
            continue
        ws = sum(w for _, w in picks)
        for t, w in picks:
            rows.append((d, t, w / ws, ret[t]))
    pr = pd.DataFrame(rows, columns=["date", "ticker", "wn", "r_S"])
    pr["date"] = pd.to_datetime(pr["date"]).astype("datetime64[ns]")
    return pr, all_dates


def crsp_labels(pr, cal, dsf, dl):
    """Vectorised CRSP 40-day label per pick-row. r_C (retx basis, primary), r_C_ret (ret basis),
    r_C_shum (retx + Shumway -30% for missing-dlret 5xx). Fallback rows carry r_S."""
    pr = pr.reset_index(drop=True)
    dates = pr.date.values.astype("datetime64[ns]")
    ci = np.searchsorted(cal, dates)
    assert (ci < len(cal)).all() and (cal[np.minimum(ci, len(cal) - 1)] == dates).all(), "pick date not on calendar"
    assert (ci + H < len(cal)).all(), "calendar too short for exit legs"
    e, x = cal[ci + 1], cal[ci + H]
    pr = pr.assign(e=e, x=x)
    dkey = (dsf.date.values.astype("datetime64[D]") - DAY0).astype(np.int64)
    key = dsf.permno.values.astype(np.int64) * 100000 + dkey
    assert np.all(np.diff(key) > 0)
    rx = dsf.retx.to_numpy(np.float64)
    rt = dsf.ret.to_numpy(np.float64)
    Lx = np.cumsum(np.log1p(np.where(np.isfinite(rx), rx, 0.0)))
    Lt = np.cumsum(np.log1p(np.where(np.isfinite(rt), rt, 0.0)))
    Nx = np.cumsum(~np.isfinite(rx))
    Nt = np.cumsum(~np.isfinite(rt))
    prc = np.abs(dsf.prc.to_numpy(np.float64))
    opn = dsf.openprc.to_numpy(np.float64)
    perm = dsf.permno.to_numpy(np.int64)
    ddate = dsf.date.values.astype("datetime64[ns]")

    mapped = pr.permno.notna().to_numpy()
    pm = np.where(mapped, pr.permno.fillna(0).to_numpy(), 0).astype(np.int64)
    ke = pm * 100000 + (e.astype("datetime64[D]") - DAY0).astype(np.int64)
    kx = pm * 100000 + (x.astype("datetime64[D]") - DAY0).astype(np.int64)
    ie = np.clip(np.searchsorted(key, ke), 0, len(key) - 1)
    has_e = mapped & (key[ie] == ke)
    ix = np.clip(np.searchsorted(key, kx, side="right") - 1, 0, len(key) - 1)
    ok = has_e & (perm[ix] == pm) & (ix >= ie)
    chain_x = np.exp(Lx[ix] - Lx[ie])
    chain_t = np.exp(Lt[ix] - Lt[ie])
    nan_x = (Nx[ix] - Nx[ie]) > 0          # a NaN retx in (e, x] -> CRSP label NaN (pre-reg)
    nan_t = (Nt[ix] - Nt[ie]) > 0
    open_ok = np.isfinite(opn[ie]) & (opn[ie] > 0)
    prc_ok = np.isfinite(prc[ie]) & (prc[ie] > 0)
    entry = np.where(open_ok & prc_ok, prc[ie] / np.where(open_ok, opn[ie], 1.0), np.nan)
    need = np.flatnonzero(ok & ~open_ok & prc_ok)
    n_open_fb_ok = 0
    if len(need):
        ohlc = K.load_ohlc(sorted(set(pr.ticker.values[need])), K.EXIT_CUTOFF)
        for j in need:
            g = ohlc.get(pr.ticker.values[j])
            if g is None:
                continue
            m = g[g.date.values == e[j]]
            if len(m) and m.open.iloc[0] > 0 and np.isfinite(m.close.iloc[0]):
                entry[j] = m.close.iloc[0] / m.open.iloc[0]
                n_open_fb_ok += 1
    exit_short = ok & (ddate[ix] < x)
    dlm = dl.reindex(pm)
    dlstdt = dlm.dlstdt.values.astype("datetime64[ns]")
    dl_in = mapped & (dlstdt > e) & (dlstdt <= x)          # (e, x]
    apply_dl = exit_short & dl_in
    dlr = dlm.dlret.to_numpy(np.float64)
    dlrx = dlm.dlretx.to_numpy(np.float64)
    dl_use = np.where(np.isfinite(dlr), dlr, np.where(np.isfinite(dlrx), dlrx, np.nan))
    dl_missing = apply_dl & ~np.isfinite(dl_use)
    dl_base = np.where(apply_dl & np.isfinite(dl_use), dl_use, 0.0)
    code = dlm.dlstcd.fillna(100).to_numpy()
    dl_shum = np.where(dl_missing & (code >= 500) & (code < 600), -0.30, dl_base)
    good_x = ok & np.isfinite(entry) & ~nan_x
    good_t = ok & np.isfinite(entry) & ~nan_t
    r_C = np.where(good_x, entry * chain_x * (1 + dl_base) - 1, np.nan)
    r_Ct = np.where(good_t, entry * chain_t * (1 + dl_base) - 1, np.nan)
    r_Cs = np.where(good_x, entry * chain_x * (1 + dl_shum) - 1, np.nan)
    fb = ~good_x
    reason = np.where(~mapped, "unmapped", np.where(~has_e, "no_crsp_row_on_e",
                      np.where(~ok, "no_crsp_rows", np.where(~np.isfinite(entry), "entry_leg_nan",
                               np.where(nan_x, "nan_retx_in_window", "")))))
    pr = pr.assign(r_C=r_C, r_C_ret=r_Ct, r_C_shum=r_Cs, fallback=fb, fallback_t=~good_t, fb_reason=reason,
                   open_fallback=good_x & ~open_ok, exit_short=good_x & exit_short, delist_applied=good_x & apply_dl,
                   delist_missing=good_x & dl_missing,
                   dl_in_not_short=good_x & dl_in & ~exit_short,
                   dl_on_e=mapped & (dlstdt == e), last_crsp_date=np.where(ok, ddate[ix], np.datetime64("NaT")))
    pr["r_C"] = pr["r_C"].where(~pr.fallback, pr.r_S)
    pr["r_C_shum"] = pr["r_C_shum"].where(~pr.fallback, pr.r_S)
    pr["r_C_ret"] = pr["r_C_ret"].where(~pr.fallback_t, pr.r_S)
    pr.attrs["n_open_fb_ok"] = n_open_fb_ok
    return pr


def book(pr, all_dates, spy, col):
    g = pr.groupby("date")
    gross = g.apply(lambda d: float((d.wn * (1 + d[col])).sum() - 1), include_groups=False)
    sets = g.ticker.apply(set)
    ann = 252.0 / RB.HORIZON
    per_off, loyo_acc, ndates = [], {}, {}
    for off in range(H):
        prev, recs = set(), []
        for tp in all_dates[off::RB.HORIZON]:
            if tp not in gross.index:
                continue
            cur = sets[tp]
            f_new = sum(1 for t in cur if t not in prev) / len(cur)
            prev = cur
            recs.append({"date": tp, "gross": gross[tp], "f_new": f_new, "spy": spy.get(tp, np.nan)})
        net = RB.turnover_net_return(recs, COST_BPS)
        s = np.array([r["spy"] for r in recs], dtype=np.float64)
        yrs = np.array([pd.Timestamp(r["date"]).year for r in recs])
        okk = np.isfinite(s)
        exc, yrs = net[okk] - s[okk], yrs[okk]
        per_off.append(float(exc.mean() * ann))
        h = (COST_BPS / 1e4) / 2.0
        for r, o in zip(recs, okk):
            if o:
                ndates[pd.Timestamp(r["date"])] = (off, int(okk.sum()), (1 - h * r["f_new"]) / (1 + h * r["f_new"]))
        for y in np.unique(yrs):
            loyo_acc.setdefault(int(y), []).append(float(exc[yrs != y].mean() * ann))
    loyo = {y: float(np.mean(v)) for y, v in loyo_acc.items()}
    ymin = min(loyo, key=loyo.get)
    return {"mean40": float(np.mean(per_off)), "sd40": float(np.std(per_off)), "min40": float(np.min(per_off)),
            "max40": float(np.max(per_off)), "offsets_positive": int(sum(v > 0 for v in per_off)),
            "loyo_min": loyo[ymin], "loyo_min_year": ymin, "loyo_max": max(loyo.values()), "loyo": loyo,
            "per_offset": per_off}, ndates


# ---------------------------------------------------------------- anchors (smoke test + hand check)
ANCHORS = [("AAPL 2008", "AAPL", 14593), ("Lehman", "LEHMQ", 80599), ("Bear Stearns", "BSC1", 68304),
           ("Washington Mutual", "WAMUQ", 81593), ("old GM", "MTLQQ", 12079), ("HIH1", "HIH1", 89953),
           ("PLNR", "PLNR", 80012), ("RSHCQ", "RSHCQ", 15560), ("BTUUQ", "BTUUQ", 88991), ("MAXY", "MAXY", 87499)]


def hand_label(dsf_p, dl, permno, e, x, ticker):
    """Independent, row-by-row CRSP label (the pre-reg rule written out longhand)."""
    w = dsf_p[(dsf_p.date >= e) & (dsf_p.date <= x)].sort_values("date")
    if w.empty or w.date.iloc[0] != e:
        return np.nan, "no row on e"
    r0 = w.iloc[0]
    note0 = ""
    if np.isfinite(r0.openprc) and r0.openprc > 0:
        v = abs(r0.prc) / r0.openprc
    else:
        g = K.load_ohlc([ticker], K.EXIT_CUTOFF)[ticker]
        m = g[g.date == e]
        v = m.close.iloc[0] / m.open.iloc[0]
        note0 = "entry leg from Sharadar close/open (openprc missing); "
    for rr in w.iloc[1:].itertuples():
        if not np.isfinite(rr.retx):
            return np.nan, "NaN retx"
        v *= 1 + rr.retx
    note = note0 + "full window"
    if w.date.iloc[-1] < x:
        note = note0 + f"CRSP rows stop {w.date.iloc[-1].date()} < x"
        if permno in dl.index:
            d = dl.loc[permno]
            if e < d.dlstdt <= x:
                r = d.dlret if np.isfinite(d.dlret) else (d.dlretx if np.isfinite(d.dlretx) else 0.0)
                v *= 1 + r
                note += f"; x(1+dlret {r:+.4f}) code {int(d.dlstcd)} on {d.dlstdt.date()}"
    return v - 1, note


def anchor_check(cal, dl, xw):
    rows = []
    perms = [a[2] for a in ANCHORS]
    dsf = K.load_dsf(permnos=perms)
    for name, tic, perm in ANCHORS:
        dp = dsf[dsf.permno == perm]
        valid = dp[np.isfinite(dp.prc)]
        if name == "AAPL 2008":
            cases = [("mid-2008 window", np.datetime64("2008-06-02", "ns"))]
        else:
            if name == "Washington Mutual":
                ev = np.datetime64("2008-09-26", "ns")   # FDIC seizure; no CRSP delisting in 2008
            else:
                ev = valid.date.values[valid.date.values <= dl.loc[perm].dlstdt.to_datetime64()].max()
            k = np.searchsorted(cal, ev)
            cases = [("t = 20 trading days before last CRSP trade", cal[k - 20])]
            if name != "Washington Mutual":
                kd = np.searchsorted(cal, dl.loc[perm].dlstdt.to_datetime64())
                cases += [("dlstdt on e (boundary)", cal[kd - 1]), ("dlstdt on x (boundary)", cal[kd - H])]
        for lab, t in cases:
            rows.append({"anchor": name, "ticker": tic, "case": lab, "date": t, "expect_permno": perm})
    pr = pd.DataFrame(rows)
    pr["date"] = pd.to_datetime(pr.date).astype("datetime64[ns]")
    pr["permno"] = K.attach(pr, xw)
    oc = load_oc(set(pr.ticker))
    pr = pr.merge(oc.rename(columns={"gross_return_40": "r_S"}), on=["ticker", "date"], how="left")
    pr["wn"] = 1.0
    lab = crsp_labels(pr, cal, dsf, dl)
    out = []
    for r in lab.itertuples():
        hv, note = hand_label(dsf[dsf.permno == r.expect_permno], dl, r.expect_permno, pd.Timestamp(r.e), pd.Timestamp(r.x), r.ticker)
        rc = None if r.fallback else float(r.r_C)
        out.append({"anchor": r.anchor, "ticker": r.ticker, "case": r.case, "t": str(pd.Timestamp(r.date).date()),
                    "e": str(pd.Timestamp(r.e).date()), "x": str(pd.Timestamp(r.x).date()),
                    "permno": None if pd.isna(r.permno) else int(r.permno), "permno_ok": bool(r.permno == r.expect_permno),
                    "r_S_sharadar": None if pd.isna(r.r_S) else round(float(r.r_S), 6),
                    "r_C_vectorised": None if rc is None else round(rc, 6),
                    "r_C_hand": None if not np.isfinite(hv) else round(float(hv), 6),
                    "vector_eq_hand": bool((rc is None and not np.isfinite(hv)) or (rc is not None and np.isfinite(hv) and abs(rc - hv) < 1e-9)),
                    "fallback": bool(r.fallback), "fb_reason": r.fb_reason, "delist_applied": bool(r.delist_applied),
                    "exit_short": bool(r.exit_short), "open_fallback": bool(r.open_fallback),
                    "last_crsp_date": None if pd.isna(r.last_crsp_date) else str(pd.Timestamp(r.last_crsp_date).date()),
                    "hand_note": note})
    return out


def main():
    t0 = time.time()
    xw = K.crosswalk()
    cal = K.market_calendar()
    dl = K.load_delist()
    anchors = anchor_check(cal, dl, xw)
    K.OUTDIR.mkdir(parents=True, exist_ok=True)
    (K.OUTDIR / "phase3_anchors.json").write_text(json.dumps(anchors, indent=1, default=str))
    for a in anchors:
        log(f"{a['anchor']:<18} {a['case']:<42} t={a['t']} S={a['r_S_sharadar']} C={a['r_C_vectorised']} "
            f"hand={a['r_C_hand']} eq={a['vector_eq_hand']} fb={a['fb_reason']} | {a['hand_note']}")
    assert all(a["vector_eq_hand"] and a["permno_ok"] for a in anchors), "anchor smoke test failed"
    if "--anchors" in sys.argv:
        return
    p, spy = load_column_c()
    pdates = np.sort(p.date.unique()).astype("datetime64[ns]")
    cal_era = cal[(cal >= np.datetime64(K.START)) & (cal <= np.datetime64(K.END))]
    cal_match = bool(len(pdates) == len(cal_era) and (pdates == cal_era).all())
    log(f"market calendar (SPY) == union of column-c panel dates 2007-2019: {cal_match} "
        f"({len(cal_era)} vs {len(pdates)}; only in panel {len(np.setdiff1d(pdates, cal_era))}, "
        f"only in SPY {len(np.setdiff1d(cal_era, pdates))})")
    pr, all_dates = pick_rows(p)
    del p
    log(f"pick-rows {len(pr):,} on {pr.date.nunique():,} dates ({time.time()-t0:.0f}s)")
    pr["permno"] = K.attach(pr, xw)
    dsf = K.load_dsf(permnos=pr.permno.dropna().unique())
    log(f"dsf rows for {pr.permno.nunique():,} pick permnos: {len(dsf):,}")
    pr = crsp_labels(pr, cal, dsf, dl)
    del dsf
    log("labels built")
    resS, nd = book(pr, all_dates, spy, "r_S")
    rec_ok = abs(resS["mean40"] - WO6_ICW8_C_CAP150) <= 0.001
    log(f"S mean40 {resS['mean40']:+.4%}  reconcile vs WO-6 {WO6_ICW8_C_CAP150:+.4%}: {'OK' if rec_ok else 'FAIL'}")
    out = {"calendar_equals_panel_dates": cal_match, "S": resS, "reconcile_ref": WO6_ICW8_C_CAP150,
           "reconcile_diff": resS["mean40"] - WO6_ICW8_C_CAP150, "reconcile_ok": bool(rec_ok)}
    w = pr.wn
    fbw = lambda m: float((w * m).sum() / w.sum())  # noqa: E731
    out["counts"] = {
        "pick_rows": int(len(pr)), "dates": int(pr.date.nunique()),
        "fallback_rows": int(pr.fallback.sum()), "fallback_weight_share": fbw(pr.fallback),
        "fallback_reasons_rows": {k: int(v) for k, v in pr.loc[pr.fallback, "fb_reason"].value_counts().items()},
        "fallback_reasons_weight_share": {k: fbw(pr.fallback & (pr.fb_reason == k)) for k in pr.loc[pr.fallback, "fb_reason"].unique()},
        "ret_basis_fallback_rows": int(pr.fallback_t.sum()),
        "open_leg_sharadar_fallback_rows": int(pr.open_fallback.sum()),
        "exit_before_x_rows": int(pr.exit_short.sum()),
        "delist_applied_rows": int(pr.delist_applied.sum()),
        "delist_applied_missing_dlret_rows": int(pr.delist_missing.sum()),
        "dlstdt_in_window_but_rows_reach_x": int(pr.dl_in_not_short.sum()),
        "dlstdt_equals_e_rows": int(pr.dl_on_e.sum()),
        "pick_level_share_abs_diff_lt_10bp_40day (not the Phase 2 bar)":
            float(((pr.r_C - pr.r_S).abs() < 1e-3)[~pr.fallback].mean()),
        "pick_level_mean_rC_minus_rS_weighted": float((w * (pr.r_C - pr.r_S)).sum() / w.sum()),
    }
    if rec_ok:
        for nm, col in [("C_retx", "r_C"), ("C_ret", "r_C_ret"), ("C_retx_shumway", "r_C_shum")]:
            r, _ = book(pr, all_dates, spy, col)
            out[nm] = r
            out[f"delta_{nm}"] = r["mean40"] - resS["mean40"]
            log(f"{nm} mean40 {r['mean40']:+.4%}  delta {r['mean40']-resS['mean40']:+.4%}")
        ann = 252.0 / RB.HORIZON
        meta = [nd.get(pd.Timestamp(d), (np.nan, np.nan, np.nan)) for d in pr.date]
        nn = np.array([m[1] for m in meta], dtype=float)
        kk = np.array([m[2] for m in meta], dtype=float)
        pr["contrib"] = pr.wn * (pr.r_C - pr.r_S) * kk * ann / (H * nn)
        out["contrib_sum_check"] = float(np.nansum(pr.contrib))
        assert abs(out["contrib_sum_check"] - out["delta_C_retx"]) < 1e-9, (out["contrib_sum_check"], out["delta_C_retx"])
        top = pr.reindex(pr.contrib.abs().sort_values(ascending=False).index).head(20)
        out["top20_contributors"] = [
            {"ticker": r.ticker, "date": str(pd.Timestamp(r.date).date()),
             "permno": None if pd.isna(r.permno) else int(r.permno), "w": round(float(r.wn), 5),
             "r_S": round(float(r.r_S), 4), "r_C": round(float(r.r_C), 4), "contrib_pp": round(float(r.contrib) * 100, 4),
             "delist_applied": bool(r.delist_applied), "exit_short": bool(r.exit_short),
             "open_fallback": bool(r.open_fallback), "fallback": bool(r.fallback)} for r in top.itertuples()]
        out["delta_within_0p5pp"] = bool(abs(out["delta_C_retx"]) <= 0.005)
    out["per_offset_note"] = "per_offset arrays are annualised excess vs SPY for offsets 0..39"
    (K.OUTDIR / "phase3.json").write_text(json.dumps(out, indent=1, default=str))
    K.DERIVED.mkdir(parents=True, exist_ok=True)
    pr.drop(columns=["e", "x"]).to_parquet(K.DERIVED / "phase3_pickrows.parquet", index=False)
    log(f"done ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
