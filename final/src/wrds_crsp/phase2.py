"""WO-51 Phase 2 (pre-registered, final/models/2026-10-08-crsp-sharadar-audit.md, hash-frozen).

Name-day agreement of daily returns, Sharadar vs CRSP, 2007-01-02..2019-12-31 (nothing later is read).
  primary   = mapped, cap150-eligible, column-c (ticker, date) where a Sharadar close-to-close return
              (consecutive rows of the ticker's OHLC CSV) and CRSP retx both exist on the same date for the
              mapped permno, and the CRSP previous trading day equals the Sharadar previous row.
  secondary = the same over all mapped column-c name-days (any eligibility).
Metrics: share |retx - ret_S| < 1bp and < 10bp (secondary basis: CRSP ret); worst 20; how many >10bp
misses fall inside Sharadar's 3-decimal rounding bound (report only).
Delisting check: every grid permno with a CRSP delisting (dlstdt 2007-2019, dlstcd >= 200) vs Sharadar's
terminal treatment (OTC tail from the CRSP delist date's close to Sharadar's last close <= 2019-12-31).

Writes final/out/wrds_crsp/phase2.json (aggregates + worst-20 summary) and, under
final/data/wrds/crsp/derived/ (never committed), phase2_misses.parquet and phase2_delistings.parquet.
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

TIER = "cap150"
BLOCK = 500
CUT = K.P2_CUTOFF
YEARS = range(2007, 2020)


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def column_c_keys():
    filt = [("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")]
    old_t = set(pd.read_parquet(K.R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].unique())
    p = pd.read_parquet(K.R26 / "composite_panel_v2.parquet", columns=["ticker", "date", f"eligible_{TIER}"],
                        filters=filt)
    tm = pd.read_csv(K.FINAL / "data/sharadar/tickers_master.csv", dtype=str,
                     usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    p = p[p["ticker"].isin(old_t) | ~p["ticker"].isin(spac)]
    p["date"] = pd.to_datetime(p["date"]).astype("datetime64[ns]")
    p["ticker"] = p["ticker"].astype(str)
    p = p[(p.date >= K.START) & (p.date <= K.END)].rename(columns={f"eligible_{TIER}": "elig"})
    assert p.date.max() <= K.END
    return p.reset_index(drop=True)


def sharadar_block(tickers):
    ohlc = K.load_ohlc(tickers, CUT, cols=("date", "close"))
    parts = []
    for t, g in ohlc.items():
        if g.empty:
            continue
        g = g.copy()
        g["ticker"] = t
        g["prev_S"] = g.date.shift(1)
        g["close_prev"] = g.close.shift(1)
        with np.errstate(divide="ignore", invalid="ignore"):
            g["ret_S"] = g.close / g.close_prev - 1.0
        parts.append(g)
    s = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    return s


def explain(r, bound):
    q = (1 + r.retx) / (1 + r.ret_S) if (1 + r.ret_S) != 0 else np.nan
    if np.isfinite(r.cf_prev) and r.cfacpr != r.cf_prev:
        return f"CRSP adjustment-factor change on this date (cfacpr {r.cf_prev:g}->{r.cfacpr:g}); Sharadar's split adjustment differs"
    for f in (2, 3, 4, 5, 10, 1.5, 20, 15, 8, 6, 1 / 0.75):
        for ff, lab in ((f, f"x{f:g}"), (1 / f, f"/{f:g}")):
            if np.isfinite(q) and abs(np.log(q / ff)) < 0.02:
                return f"ratio CRSP/Sharadar gross = {q:.3f} (~{lab}): split-adjustment date mismatch"
    if abs(r.retx - r.ret_S) <= bound:
        return "inside Sharadar 3-decimal rounding bound"
    if r.prc < 0 or r.prc_prev < 0:
        return "CRSP price is a bid/ask midpoint (no trade) on this or the previous day"
    return "price level disagrees (no split/factor/rounding/midpoint explanation)"


def main():
    t0 = time.time()
    xw = K.crosswalk()
    keys = column_c_keys()
    log(f"column c keys {len(keys):,} ({int(keys.elig.sum()):,} cap150-eligible), {keys.ticker.nunique():,} tickers")
    tickers = sorted(keys.ticker.unique())
    agg = {s: {k: 0 for k in ("n_total", "n_mapped", "n_sharadar_ret", "n_crsp_row", "n_crsp_retx",
                               "n_prev_match", "n_eval", "lt1bp_retx", "lt10bp_retx", "n_eval_ret",
                               "lt1bp_ret", "lt10bp_ret", "miss10_retx", "miss10_in_rounding_bound")}
           for s in ("primary", "secondary")}
    by_year = {}
    worst, misses, no_csv = [], [], 0
    for b in range(0, len(tickers), BLOCK):
        tb = tickers[b:b + BLOCK]
        k = keys[keys.ticker.isin(tb)].copy()
        k["permno"] = K.attach(k, xw)
        s = sharadar_block(tb)
        no_csv += len(set(tb) - set(s.ticker.unique() if len(s) else []))
        k = k.merge(s[["ticker", "date", "prev_S", "close", "close_prev", "ret_S"]], on=["ticker", "date"], how="left")
        dsf = K.load_dsf(years=YEARS, cols=("permno", "date", "ret", "retx", "prc", "cfacpr"),
                         permnos=k.permno.dropna().unique(), cutoff=CUT)
        dsf["prev_C"] = dsf.groupby("permno").date.shift(1)
        dsf["prc_prev"] = dsf.groupby("permno").prc.shift(1)
        dsf["cf_prev"] = dsf.groupby("permno").cfacpr.shift(1)
        k["pk"] = k.permno.fillna(-1).astype(np.int64)
        m = k.merge(dsf.rename(columns={"permno": "pk"}), on=["pk", "date"], how="left")
        assert len(m) == len(k)
        m["mapped"] = m.permno.notna()
        m["has_S"] = np.isfinite(m.ret_S)
        m["has_retx"] = m.mapped & np.isfinite(m.retx)
        m["prev_ok"] = m.prev_C.notna() & (m.prev_C == m.prev_S)
        m["eval"] = m.mapped & m.has_S & m.has_retx & m.prev_ok
        m["d"] = m.retx - m.ret_S
        m["dt"] = m.ret - m.ret_S
        with np.errstate(divide="ignore", invalid="ignore"):
            m["bound"] = 0.0005 * (1 + m.close / m.close_prev) / m.close_prev
        for sname, sel in (("primary", m.elig.astype(bool)), ("secondary", pd.Series(True, index=m.index))):
            a, mm = agg[sname], m[sel]
            ev = mm[mm["eval"]]
            evt = ev[np.isfinite(ev.dt)]
            a["n_total"] += len(mm)
            a["n_mapped"] += int(mm.mapped.sum())
            a["n_sharadar_ret"] += int((mm.mapped & mm.has_S).sum())
            a["n_crsp_row"] += int((mm.mapped & mm.has_S & mm.prc.notna()).sum())
            a["n_crsp_retx"] += int((mm.mapped & mm.has_S & mm.has_retx).sum())
            a["n_prev_match"] += int((mm.mapped & mm.has_S & mm.has_retx & mm.prev_ok).sum())
            a["n_eval"] += int(len(ev))
            a["lt1bp_retx"] += int((ev.d.abs() < 1e-4).sum())
            a["lt10bp_retx"] += int((ev.d.abs() < 1e-3).sum())
            a["n_eval_ret"] += int(len(evt))
            a["lt1bp_ret"] += int((evt.dt.abs() < 1e-4).sum())
            a["lt10bp_ret"] += int((evt.dt.abs() < 1e-3).sum())
            miss = ev[ev.d.abs() >= 1e-3]
            a["miss10_retx"] += int(len(miss))
            a["miss10_in_rounding_bound"] += int((miss.d.abs() <= miss.bound).sum())
            if sname == "primary":
                yy = ev.date.dt.year
                for y, grp in ev.groupby(yy):
                    by = by_year.setdefault(int(y), [0, 0])
                    by[0] += len(grp)
                    by[1] += int((grp.d.abs() < 1e-3).sum())
                misses.append(miss[["ticker", "date", "permno", "close_prev", "close", "ret_S", "retx", "ret", "prc",
                                    "prc_prev", "cfacpr", "cf_prev", "bound"]])
                worst.append(miss.reindex(miss.d.abs().sort_values(ascending=False).index).head(40))
        log(f"block {b // BLOCK + 1}/{-(-len(tickers) // BLOCK)}: primary eval {agg['primary']['n_eval']:,} "
            f"10bp {agg['primary']['lt10bp_retx'] / max(agg['primary']['n_eval'], 1):.5f} ({time.time() - t0:.0f}s)")
        del dsf, m, k, s
    out = {"era": "2007-01-02..2019-12-31", "basis_primary": "CRSP retx vs Sharadar close-to-close (split-adjusted)"}
    for sname, a in agg.items():
        a = dict(a)
        a["share_lt1bp_retx"] = a["lt1bp_retx"] / a["n_eval"]
        a["share_lt10bp_retx"] = a["lt10bp_retx"] / a["n_eval"]
        a["share_lt1bp_ret"] = a["lt1bp_ret"] / a["n_eval_ret"]
        a["share_lt10bp_ret"] = a["lt10bp_ret"] / a["n_eval_ret"]
        a["retention_eval_over_total"] = a["n_eval"] / a["n_total"]
        a["retention_eval_over_mapped"] = a["n_eval"] / a["n_mapped"]
        a["miss10_share_in_rounding_bound"] = a["miss10_in_rounding_bound"] / max(a["miss10_retx"], 1)
        out[sname] = a
    out["primary_10bp_share_by_year"] = {y: v[1] / v[0] for y, v in sorted(by_year.items())}
    out["tickers_without_ohlc_csv"] = no_csv
    out["pass_10bp_bar_99pct"] = bool(out["primary"]["share_lt10bp_retx"] >= 0.99)
    W = pd.concat(worst, ignore_index=True)
    W = W.reindex(W.d.abs().sort_values(ascending=False).index).head(20)
    out["worst20_primary"] = [
        {"ticker": r.ticker, "date": str(r.date.date()), "permno": int(r.permno),
         "sharadar_ret": round(float(r.ret_S), 5), "crsp_retx": round(float(r.retx), 5),
         "sharadar_close_prev_close": [float(r.close_prev), float(r.close)],
         "explanation": explain(r, r.bound)} for r in W.itertuples()]
    M = pd.concat(misses, ignore_index=True)
    K.DERIVED.mkdir(parents=True, exist_ok=True)
    M.to_parquet(K.DERIVED / "phase2_misses.parquet", index=False)
    # coarse classification of all primary misses (counts only)
    M["absd"] = (M.retx - M.ret_S).abs()
    cls = {
        "in_rounding_bound": int((M.absd <= M.bound).sum()),
        "cfacpr_change_on_date": int(((M.cfacpr != M.cf_prev) & M.cf_prev.notna()).sum()),
        "crsp_midpoint_price": int(((M.prc < 0) | (M.prc_prev < 0)).sum()),
        "abs_diff_ge_1pct": int((M.absd >= 0.01).sum()),
        "abs_diff_ge_10pct": int((M.absd >= 0.10).sum()),
    }
    out["primary_miss_classes_overlapping"] = cls
    log(f"phase 2 agreement done ({time.time() - t0:.0f}s)")
    out["delisting_check"] = delisting_check(xw)
    K.OUTDIR.mkdir(parents=True, exist_ok=True)
    (K.OUTDIR / "phase2.json").write_text(json.dumps(out, indent=1, default=str))
    log(f"done ({time.time() - t0:.0f}s)")


def delisting_check(xw):
    dl = K.load_delist().reset_index()
    dl = dl[(dl.dlstdt >= K.START) & (dl.dlstdt <= K.END) & (dl.dlstcd >= 200)]
    x = xw.sort_values("valid_to").drop_duplicates("permno", keep="last")[["permno", "ticker", "valid_to"]]
    d = dl.merge(x, on="permno", how="inner")
    dsf = K.load_dsf(years=YEARS, cols=("permno", "date", "prc"), permnos=d.permno.unique(), cutoff=CUT)
    lastc = dsf[np.isfinite(dsf.prc)].groupby("permno").date.max()
    ohlc = K.load_ohlc(sorted(d.ticker.unique()), CUT, cols=("date", "close"))
    rows = []
    for r in d.itertuples():
        g = ohlc.get(r.ticker)
        lc = lastc.get(r.permno, pd.NaT)
        rec = {"permno": r.permno, "ticker": r.ticker, "dlstdt": r.dlstdt, "dlstcd": r.dlstcd,
               "dlret": r.dlret, "dlretx": r.dlretx, "crsp_last_trade": lc}
        if g is None or g.empty:
            rec.update(sharadar_last=pd.NaT, sh_tail=np.nan, tail_alt=np.nan, truncated=False)
        else:
            last = g.date.iloc[-1]
            b = g[g.date <= r.dlstdt]
            ba = g[g.date <= lc] if pd.notna(lc) else g.iloc[0:0]
            tail = g.close.iloc[-1] / b.close.iloc[-1] - 1 if len(b) and b.close.iloc[-1] > 0 else np.nan
            tail_alt = g.close.iloc[-1] / ba.close.iloc[-1] - 1 if len(ba) and ba.close.iloc[-1] > 0 else np.nan
            rec.update(sharadar_last=last, sh_tail=tail, tail_alt=tail_alt, truncated=bool(last >= pd.Timestamp("2019-12-31")))
        rows.append(rec)
    D = pd.DataFrame(rows)
    D["dl_use"] = D.dlret.where(D.dlret.notna(), D.dlretx)
    D["sharadar_keeps_tail"] = D.sharadar_last > D.dlstdt
    D["gap"] = D.sh_tail - D.dl_use
    D["gap_alt"] = D.tail_alt - D.dl_use
    D.to_parquet(K.DERIVED / "phase2_delistings.parquet", index=False)
    v = D[np.isfinite(D.gap)]
    va = D[np.isfinite(D.gap_alt)]
    q = lambda s: {k: float(s.quantile(p)) for k, p in (("p05", .05), ("p25", .25), ("median", .5), ("p75", .75), ("p95", .95))}  # noqa: E731
    fam = D.dlstcd // 100
    res = {
        "n_delisted_grid_permnos": int(len(D)),
        "by_code_family": {f"{int(k)}xx": int(c) for k, c in fam.value_counts().sort_index().items()},
        "sharadar_keeps_otc_tail": int(D.sharadar_keeps_tail.sum()),
        "sharadar_ends_on_or_before_dlstdt": int((D.sharadar_last <= D.dlstdt).sum()),
        "no_sharadar_csv": int(D.sharadar_last.isna().sum()),
        "tail_truncated_at_2019_12_31": int(D.truncated.sum()),
        "dlret_and_dlretx_missing": int(D.dl_use.isna().sum()),
        "dlret_missing_5xx": int((D.dl_use.isna() & (fam == 5)).sum()),
        "gap_tail_minus_dlret": {"n": int(len(v)), "share_abs_le_1pp": float((v.gap.abs() <= 0.01).mean()),
                                 "share_abs_le_10pp": float((v.gap.abs() <= 0.10).mean()), **q(v.gap)},
        "gap_alt_base_crsp_last_trade": {"n": int(len(va)), "share_abs_le_1pp": float((va.gap_alt.abs() <= 0.01).mean()),
                                         "share_abs_le_10pp": float((va.gap_alt.abs() <= 0.10).mean()), **q(va.gap_alt)},
        "by_family": {},
        "anchors": [],
    }
    for f in sorted(fam.unique()):
        s = D[(fam == f) & np.isfinite(D.gap_alt)]
        res["by_family"][f"{int(f)}xx"] = {"n": int((fam == f).sum()), "n_gap": int(len(s)),
                                           "keeps_tail": int(D[fam == f].sharadar_keeps_tail.sum()),
                                           "median_gap_alt": float(s.gap_alt.median()) if len(s) else None,
                                           "share_abs_gap_alt_le_10pp": float((s.gap_alt.abs() <= 0.10).mean()) if len(s) else None}
    for perm in (80599, 68304, 12079, 89953, 80012, 15560, 88991, 87499):
        a = D[D.permno == perm]
        if len(a):
            a = a.iloc[0]
            res["anchors"].append({"ticker": a.ticker, "permno": perm, "dlstdt": str(a.dlstdt.date()), "dlstcd": int(a.dlstcd),
                                   "crsp_last_trade": str(pd.Timestamp(a.crsp_last_trade).date()) if pd.notna(a.crsp_last_trade) else None,
                                   "dlret": None if pd.isna(a.dl_use) else round(float(a.dl_use), 4),
                                   "sharadar_last": str(a.sharadar_last.date()) if pd.notna(a.sharadar_last) else None,
                                   "sharadar_tail_from_dlstdt": None if pd.isna(a.sh_tail) else round(float(a.sh_tail), 4),
                                   "sharadar_tail_from_crsp_last_trade": None if pd.isna(a.tail_alt) else round(float(a.tail_alt), 4)})
        else:
            res["anchors"].append({"permno": perm, "note": "not in delisting set"})
    res["wamu"] = ("WAMUQ (permno 81593) has no CRSP delisting in 2007-2019 (dsedelist: code 100, dlstdt 2024-12-31). "
                   "CRSP's last priced day is 2008-09-26 (0.1604), then rows with no price; Sharadar continues OTC "
                   "(0.16 through 2008-10-15, 0.06 by 2008-10-30, last price 2008-10-30).")
    return res


if __name__ == "__main__":
    main()
