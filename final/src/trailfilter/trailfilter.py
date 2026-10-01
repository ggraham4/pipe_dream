"""
WO-40 (COO; issued as WO-36 and renumbered; Gabe's heuristic 2026-10-01): trailing-40-day return filter on the
model's picks. Pre-registration: final/models/2026-10-01-trailing-return-filter.md
(committed before any filtered-vs-unfiltered number).

r40(t) = closeadj[t]/closeadj[t-40] - 1 on the name's own SEP bars, data <= t.
F0: exclude r40 < 0. F10: exclude r40 < -10%. Undefined r40 -> kept.
Primary (iteration 2, matches the work order): vol quintiles and per-bucket
pick counts come from the full eligible set; within each bucket the top-ranked
SURVIVORS fill the k slots (book stays full-size). Iteration 1 (excluded names
get a NaN score, so the book is a decile of the survivors and holds fewer
names) is kept as a descriptive row. Descriptive: drop excluded names AFTER selection
and renormalise. Empty filtered book -> cash for that window (gross 0).
Era B = hold-out read #18 (unfitted; rule fixed in advance).

Harness (read-only imports): model_audit_wo23.load_theo, screen_insider_v2grid.Book,
pool_read.picks_w, drag_decomp. v2 col c, cap150, net 15 bp, 40 offsets, h=40.

Usage (one process per step):
  python trailfilter.py --period A          reconcile (hard assert) + Gate A + exclusion shares
                                            -> out/trailfilter/parts/A_prep.json  (no performance)
  python trailfilter.py --period A --run    the above + filtered vs unfiltered -> parts/A_run.json
  python trailfilter.py --aggregate         verdicts -> out/trailfilter/trailfilter.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
FINAL = HERE.parents[1]
OUT = FINAL / "out" / "trailfilter"
PARTS = OUT / "parts"
MAIN = Path("/Users/ggraham/pipe_dream/final")
SEP_DIR = MAIN / "data" / "sharadar" / "panel" / "stocks"
TM = MAIN / "data" / "sharadar" / "tickers_master.csv"
SEAS_EXT_RO = Path("/Users/ggraham/pipe_dream/.claude/worktrees/wo24-construction-drag/final/out/audit/seas_factor_ext.parquet")
POOL_READ = FINAL / "out" / "pool" / "pool_hedge_read.json"
CUT = pd.Timestamp("2011-10-01")
LAG = 40
ARMS = {"F0": 0.0, "F10": -0.10}
ANN = 252.0 / 40
TOL_SPEC = 1e-4      # 0.01 pp
TOL_EXACT = 1e-10
SPEC = {("A", "full", "icw9_seas"): 0.0349, ("A", "post", "icw9_seas"): 0.0051, ("B", "full", "icw9_seas"): -0.0202,
        ("A", "full", "icw8"): 0.0285, ("A", "post", "icw8"): 0.0001, ("B", "full", "icw8"): -0.0199}
WINS = {"A": {"full": (None, None), "post": (CUT, None)}, "B": {"full": (None, None)}}
DROP_YEAR = {"A": 2008, "B": 2020}
MODELS = ("icw9_seas", "icw8")
CASH = (0.0, set(), [], [], [])


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


# ------------------------------------------------------------------ r40
def load_closeadj(tickers, lo, hi):
    lo_m = (pd.Timestamp(lo) - pd.DateOffset(months=4)).strftime("%Y-%m")
    hi_m = pd.Timestamp(hi).strftime("%Y-%m")
    files = sorted(f for f in SEP_DIR.glob("*.parquet") if lo_m <= f.stem <= hi_m)
    tl = sorted(tickers)
    parts = [pd.read_parquet(f, columns=["ticker", "date", "closeadj"], filters=[("ticker", "in", tl)]) for f in files]
    px = pd.concat(parts, ignore_index=True)
    del parts
    px["date"] = pd.to_datetime(px["date"])
    px["ticker"] = px["ticker"].astype(str)
    px = px.drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"]).reset_index(drop=True)
    px = px[px["date"] <= pd.Timestamp(hi)].reset_index(drop=True)
    return px


def r40_of(px):
    """closeadj[t]/closeadj[t-40 own bars] - 1; px sorted by ticker, date."""
    prev = px.groupby("ticker", sort=False)["closeadj"].shift(LAG)
    return (px["closeadj"] / prev - 1.0).to_numpy(np.float64)


def gate_a(px, period, U):
    """PIT append-invariance, AAPL split check, dead name present."""
    res = {}
    rng = np.random.default_rng(36)
    ok = np.flatnonzero(np.isfinite(px["r40"].to_numpy()))
    samp = rng.choice(ok, size=300, replace=False)
    tk = px["ticker"].to_numpy(); dt = px["date"].to_numpy(); ca = px["closeadj"].to_numpy(np.float64)
    r = px["r40"].to_numpy()
    starts = pd.Series(np.arange(len(px))).groupby(px["ticker"].to_numpy(), sort=False).agg(["min", "max"])
    mx = 0.0
    for i in samp:
        s0, s1 = int(starts.loc[tk[i], "min"]), int(starts.loc[tk[i], "max"])
        # truncate the name's series at t and recompute from scratch
        sub = ca[s0:i + 1]
        a = sub[-1] / sub[-1 - LAG] - 1.0
        # fake future adjustment: every bar <= t+k (k = up to 10 bars later) rescaled by 0.97,
        # and every bar after that by 1.25 -> r40(t) unchanged
        full = ca[s0:s1 + 1].copy()
        j = i - s0
        k = min(j + 10, len(full) - 1)
        full[:k + 1] *= 0.97
        full[k + 1:] *= 1.25
        b = full[j] / full[j - LAG] - 1.0
        mx = max(mx, abs(a - r[i]), abs(b - r[i]))
    assert mx < 1e-9, f"PIT FAIL: max abs diff {mx}"
    res["pit"] = {"n_sampled": int(len(samp)), "max_abs_diff_truncate_or_rescale": float(mx), "tol": 1e-9}
    log(f"[{period}] Gate A PIT: {res['pit']}")
    if period == "A":
        f = sorted(SEP_DIR.glob("*.parquet"))
        aa = pd.concat([pd.read_parquet(x, columns=["ticker", "date", "close", "closeadj", "closeunadj"],
                                        filters=[("ticker", "==", "AAPL")])
                        for x in f if "2014-02" <= x.stem <= "2014-06"])
        aa["date"] = pd.to_datetime(aa["date"]); aa = aa.sort_values("date").reset_index(drop=True)
        i = int(np.flatnonzero(aa["date"] == pd.Timestamp("2014-06-09"))[0])
        adj = float(aa["closeadj"][i] / aa["closeadj"][i - LAG] - 1.0)
        raw = float(aa["closeunadj"][i] / aa["closeunadj"][i - LAG] - 1.0)
        mine = px[(px["ticker"] == "AAPL") & (px["date"] == pd.Timestamp("2014-06-09"))]["r40"]
        res["aapl_2014_06_09"] = {"r40_closeadj": adj, "r40_closeunadj_raw": raw,
                                  "r40_in_table": float(mine.iloc[0]) if len(mine) else None}
        log(f"[A] Gate A AAPL split: {res['aapl_2014_06_09']}")
        assert adj > -0.5, "AAPL split check FAIL"
        if len(mine):
            assert abs(float(mine.iloc[0]) - adj) < 1e-9
    tm = pd.read_csv(TM, dtype=str, usecols=["ticker", "isdelisted", "lastpricedate"]).drop_duplicates("ticker")
    dead = set(tm.loc[tm["isdelisted"] == "Y", "ticker"])
    ud = U[U["ticker"].isin(dead) & np.isfinite(U["r40"])]
    assert len(ud) > 0, "no dead name with finite r40"
    ex = ud.iloc[len(ud) // 2]
    res["dead_names"] = {"n_dead_tickers_with_finite_r40": int(ud["ticker"].nunique()), "rows": int(len(ud)),
                         "example": [str(ex["ticker"]), str(pd.Timestamp(ex["date"]).date()), float(ex["r40"])]}
    log(f"[{period}] Gate A dead names: {res['dead_names']}")
    return res


# ------------------------------------------------------------------ books
def noscore_masked(book, keep, DD_mod):
    """drag_decomp.noscore_picks restricted to rows with keep=True."""
    import composite as C
    import no_exclusion_control as NXC
    out = {}
    for d, s, e in book.sl:
        k = keep[s:e]
        if k.sum() < C.N_VOL_QUINTILES * 4:
            continue
        g = pd.DataFrame({"volatility_60": book.vol[s:e][k], "ticker": book.tick[s:e][k]})
        pk = NXC.pick_full_universe_volq(g)
        ret = dict(zip(book.tick[s:e], book.ret[s:e]))
        pk = [(t, w) for t, w in pk if pd.notna(ret.get(t))]
        if not pk:
            continue
        ws = sum(w for _, w in pk)
        gross = sum((w / ws) * (1.0 + ret[t]) for t, w in pk) - 1.0
        out[d] = (gross, {t for t, _ in pk})
    return out


def picks_fullsize(book, score, excl):
    """composite.pick_decile_volq + pool_read.picks_w, but excluded names are
    skipped when filling each vol bucket's k slots. Quintiles and k come from
    the full valid set, so the book keeps the unfiltered name count unless a
    bucket has fewer than k survivors (counted)."""
    import composite as C
    score = np.asarray(score, dtype=np.float64)
    out, short = {}, {"buckets": 0, "buckets_short": 0, "dates_short": 0}
    for d, s, e in book.sl:
        if e - s < C.N_VOL_QUINTILES * 4:
            continue
        vol, comp, tick, ex = book.vol[s:e], score[s:e], book.tick[s:e], excl[s:e]
        valid = np.isfinite(vol) & np.isfinite(comp)
        if valid.sum() < C.N_VOL_QUINTILES * 4:
            continue
        idx = np.flatnonzero(valid)
        vol_v, comp_v, tick_v, ex_v = vol[idx], comp[idx], tick[idx], ex[idx]
        q = pd.qcut(vol_v, C.N_VOL_QUINTILES, labels=False, duplicates="drop")
        picks, any_short = [], False
        for bucket in np.unique(q):
            b_idx = np.flatnonzero(q == bucket)
            k = max(1, int(round(len(b_idx) * 0.10)))
            order = b_idx[np.argsort(-comp_v[b_idx])]
            order = order[~ex_v[order]][:k]
            short["buckets"] += 1
            if len(order) < k:
                short["buckets_short"] += 1
                any_short = True
            for i in order:
                picks.append((tick_v[i], vol_v[i]))
        short["dates_short"] += int(any_short)
        if not picks:
            continue
        inv_vol = np.array([1.0 / max(v, 1e-4) for _, v in picks])
        w = inv_vol / inv_vol.sum()
        pk = [(t, float(wi)) for (t, _), wi in zip(picks, w)]
        ret = dict(zip(tick, book.ret[s:e]))
        pk = [(t, w_) for t, w_ in pk if pd.notna(ret.get(t))]
        if not pk:
            continue
        ws = sum(w_ for _, w_ in pk)
        gross = sum((w_ / ws) * (1.0 + ret[t]) for t, w_ in pk) - 1.0
        out[d] = (gross, {t for t, _ in pk}, [t for t, _ in pk], [w_ / ws for _, w_ in pk], [ret[t] for t, _ in pk])
    return out, short


def cash_fill(pk, ref):
    """Dates in the unfiltered book that the filtered book lacks -> cash."""
    n = 0
    for d in ref:
        if d not in pk:
            pk[d] = CASH
            n += 1
    assert set(pk) == set(ref)
    return n


def post_select(pkw_u, excl_by):
    out = {}
    for d, v in pkw_u.items():
        ex = excl_by[d]
        keep = [i for i, t in enumerate(v[2]) if not ex[t]]
        if not keep:
            out[d] = CASH
            continue
        w = np.array([v[3][i] for i in keep]); w = w / w.sum()
        r = np.array([v[4][i] for i in keep])
        out[d] = (float((w * (1.0 + r)).sum() - 1.0), {v[2][i] for i in keep})
    return out


def chains2(pk, dates, bench, cost, RB):
    """drag_decomp.chains, tolerant of an empty (cash) book; also keeps gross and n."""
    res = []
    for off in range(40):
        prev, recs = set(), []
        for tp in dates[off::RB.HORIZON]:
            if tp not in pk:
                continue
            gross, cur = pk[tp][0], pk[tp][1]
            f_new = (sum(1 for t in cur if t not in prev) / len(cur)) if cur else 0.0
            prev = cur
            recs.append({"date": tp, "gross": gross, "f_new": f_new, "b": bench.get(tp, np.nan), "n": len(cur)})
        net = RB.turnover_net_return(recs, cost)
        b = np.array([r["b"] for r in recs], dtype=np.float64)
        ok = np.isfinite(b)
        res.append({"date": np.array([r["date"] for r in recs])[ok], "net": net[ok], "exc": net[ok] - b[ok],
                    "f_new": np.array([r["f_new"] for r in recs])[ok],
                    "gross": np.array([r["gross"] for r in recs])[ok], "n": np.array([r["n"] for r in recs])[ok]})
    return res


def book_stats(ch):
    """turnover, cost, drawdown, worst window (net)."""
    mdd = []
    for c in ch:
        eq = np.r_[1.0, np.cumprod(1.0 + c["net"])]
        mdd.append(float((eq / np.maximum.accumulate(eq) - 1.0).min()))
    return {"f_new_mean40": float(np.mean([c["f_new"].mean() for c in ch])),
            "cost_drag_ann": float(np.mean([(c["gross"] - c["net"]).mean() for c in ch]) * ANN),
            "names_mean": float(np.mean([c["n"].mean() for c in ch])),
            "maxdd_mean40": float(np.mean(mdd)), "maxdd_worst40": float(np.min(mdd)),
            "worst_40d_window_net": float(min(c["net"].min() for c in ch)),
            "net_ann_mean40": float(np.mean([c["net"].mean() for c in ch]) * ANN)}


def diff_stats(DD, ch_u, ch_f, drop_year, per_year=False):
    assert all(np.array_equal(a["date"], b["date"]) for a, b in zip(ch_u, ch_f)), "chains not date-aligned"
    po_u, po_f = DD.per_offset(ch_u), DD.per_offset(ch_f)
    d = po_f - po_u
    ys, lu = DD.loyo_vec(ch_u)
    ys2, lf = DD.loyo_vec(ch_f)
    assert ys == ys2
    dl = (lf - lu).mean(axis=0)
    r = {"unfiltered": float(po_u.mean()), "filtered": float(po_f.mean()), "diff": float(d.mean()),
         "diff_offsets_pos": int((d > 0).sum()), "diff_sd40": float(d.std()), "diff_min40": float(d.min()),
         "diff_max40": float(d.max()), "filtered_offsets_pos": int((po_f > 0).sum()),
         "unfiltered_offsets_pos": int((po_u > 0).sum()),
         "diff_loyo_by_dropped_year": {int(y): float(v) for y, v in zip(ys, dl)},
         f"diff_drop{drop_year}": float(dl[ys.index(drop_year)]) if drop_year in ys else None}
    if per_year:
        pu, pf = DD.per_year(ch_u), DD.per_year(ch_f)
        r["per_year"] = {y: {"unfiltered": pu[y], "filtered": pf[y], "diff": pf[y] - pu[y]} for y in pu}
    return r


# ------------------------------------------------------------------ job
def job(period, run):
    sys.path.insert(0, str(SRC / "audit"))
    sys.path.insert(0, str(SRC / "construction"))
    sys.path.insert(0, str(SRC / "pool"))
    import model_audit_wo23 as MA
    import drag_decomp as DD
    import pool_read as PR
    import run_backtest as RB
    V, SI, DR, ICW = MA.V, MA.SI, MA.DR, MA.ICW
    MA.SEAS_EXT = SEAS_EXT_RO
    assert DD.ANN == ANN
    T0 = time.time()
    PARTS.mkdir(parents=True, exist_ok=True)
    W = {"icw9_seas": dict(ICW.PRODUCTION_WEIGHTS_V9_SEAS), "icw8": dict(ICW.PRODUCTION_WEIGHTS)}
    assert W["icw9_seas"] == MA.W9 and W["icw8"] == MA.W8
    U, all_dates, spy = MA.load_theo(period, "cap150")
    all_dates = [pd.Timestamp(d) for d in all_dates]
    lo, hi = MA.PERIODS[period]
    out = {"work_order": "WO-40 trailing-return filter (issued as WO-36)", "period": period, "holdout_read": 18 if period == "B" else None,
           "n_dates": len(all_dates), "first_date": str(all_dates[0].date()), "last_date": str(all_dates[-1].date())}

    # ---- r40 (data <= t), merged on (ticker, date)
    px = load_closeadj(set(U["ticker"].unique()), lo, hi)
    px["r40"] = r40_of(px)
    n = len(U)
    U = U.merge(px[["ticker", "date", "r40"]], on=["ticker", "date"], how="left")
    assert len(U) == n and (U["date"].diff().dropna() >= pd.Timedelta(0)).all(), "r40 merge changed rows/order"
    r40 = U["r40"].to_numpy(np.float64)
    out["r40"] = {"rows": int(n), "undefined_rows_kept": int((~np.isfinite(r40)).sum()),
                  "undefined_share": float((~np.isfinite(r40)).mean()),
                  "quantiles": {str(q): float(np.nanquantile(r40, q)) for q in (0.01, 0.25, 0.5, 0.75, 0.99)}}
    log(f"[{period}] r40: {out['r40']} ({time.time()-T0:.0f}s)")
    out["gate_a"] = gate_a(px, period, U)
    del px

    # ---- unfiltered books + reconcile
    V.add_ranks(U, MA.FT)
    book = V.Book(U, all_dates, spy)
    score = {m: SI.composite_score(U, w).to_numpy(np.float64) for m, w in W.items()}
    pkw_u = {m: PR.picks_w(book, score[m]) for m in MODELS}
    ref = json.loads(POOL_READ.read_text())["tables"]
    out["reconcile"] = []
    ch_u = {}
    for wn, (wl, wh) in WINS[period].items():
        for m in MODELS:
            p_, ds = DD.window(pkw_u[m], all_dates, wl, wh)
            ch = DD.chains({d: (v[0], v[1]) for d, v in p_.items()}, ds, spy, DR.COST_BPS)
            ch2 = chains2(p_, ds, spy, DR.COST_BPS, RB)
            assert all(np.array_equal(a["exc"], b["exc"]) and np.array_equal(a["date"], b["date"]) for a, b in zip(ch, ch2))
            po = DD.per_offset(ch)
            bt = DR.backtest({d: (v[0], v[1]) for d, v in p_.items()}, ds, spy)["excess_cagr_vs_spy_mean40"]
            assert abs(po.mean() - bt) < 1e-12, "chains vs DR.backtest oracle"
            r_exact = ref[m][f"{period}_{wn}"]["cap150"]["book_vs_spy"]
            rec = {"name": f"{period} {wn} {m}", "got": float(po.mean()), "wo31_exact": r_exact,
                   "diff_exact": float(po.mean() - r_exact), "spec": SPEC[(period, wn, m)],
                   "diff_spec": float(po.mean() - SPEC[(period, wn, m)])}
            log(f"reconcile {rec}")
            assert abs(rec["diff_exact"]) < TOL_EXACT, f"RECONCILE FAIL (WO-31 exact) {rec}"
            assert abs(rec["diff_spec"]) < TOL_SPEC, f"RECONCILE FAIL (spec) {rec}"
            out["reconcile"].append(rec)
            ch_u[(wn, m)] = ch2

    # ---- exclusion shares (no performance)
    vol_ok = np.isfinite(book.vol)
    excl = {a: (r40 < thr) for a, thr in ARMS.items()}       # NaN r40 -> False -> kept
    excl_by = {a: {} for a in ARMS}
    sh = {a: {wn: {"elig": [], "picks_n": [], "picks_w": []} for wn in WINS[period]} for a in ARMS}
    for d, s, e in book.sl:
        for a in ARMS:
            ex = dict(zip(book.tick[s:e], excl[a][s:e]))
            excl_by[a][d] = ex
            valid = vol_ok[s:e] & np.isfinite(score["icw9_seas"][s:e])
            v = pkw_u["icw9_seas"].get(d)
            if v is None or valid.sum() == 0:
                continue
            pe = np.array([ex[t] for t in v[2]])
            for wn, (wl, wh) in WINS[period].items():
                if (wl is None or d >= wl) and (wh is None or d < wh):
                    sh[a][wn]["elig"].append(float(excl[a][s:e][valid].mean()))
                    sh[a][wn]["picks_n"].append(float(pe.mean()))
                    sh[a][wn]["picks_w"].append(float(np.dot(pe, v[3])))
    out["share_excluded"] = {a: {wn: {"eligible_names": float(np.mean(x["elig"])), "would_be_picks_count": float(np.mean(x["picks_n"])),
                                      "would_be_picks_weight": float(np.mean(x["picks_w"])),
                                      "eligible_share_max_date": float(np.max(x["elig"])), "n_dates": len(x["elig"])}
                                 for wn, x in sh[a].items()} for a in ARMS}
    log(f"[{period}] share excluded {json.dumps(out['share_excluded'])}")
    (PARTS / f"{period}_prep.json").write_text(json.dumps(out, indent=2, default=float))
    log(f"[{period}] wrote prep ({time.time()-T0:.0f}s)")
    if not run:
        return

    # ================================================================ filtered vs unfiltered
    keep_all = np.ones(len(U), dtype=bool)
    pool_u = noscore_masked(book, keep_all, DD)
    pool_ref = DD.noscore_picks(book)
    assert set(pool_u) == set(pool_ref) and all(abs(pool_u[d][0] - pool_ref[d][0]) < 1e-14 for d in pool_ref), "noscore oracle"
    ret = book.ret
    for m in MODELS:      # oracle: no exclusions -> picks_fullsize == pool_read.picks_w exactly
        o, sh0 = picks_fullsize(book, score[m], np.zeros(len(U), dtype=bool))
        assert set(o) == set(pkw_u[m]) and sh0["buckets_short"] == 0
        assert all(o[d][0] == pkw_u[m][d][0] and o[d][2] == pkw_u[m][d][2] and o[d][3] == pkw_u[m][d][3] for d in o), "fullsize oracle"
    out["short_buckets"] = {}
    out["results"], out["excluded_vs_kept"], out["empty_book_dates"] = {}, {}, {}
    for a in ARMS:
        pool_f = noscore_masked(book, ~excl[a], DD)
        n_cash_pool = cash_fill(pool_f, pool_u)
        # excluded vs kept: would-be picks (icw9_seas) and eligible names, forward 40d gross label
        for wn, (wl, wh) in WINS[period].items():
            pe_, pk_, ee_, ek_ = [], [], [], []
            for d, s, e in book.sl:
                if not ((wl is None or d >= wl) and (wh is None or d < wh)):
                    continue
                v = pkw_u["icw9_seas"].get(d)
                if v is None:
                    continue
                ex = excl_by[a][d]
                m_ = np.array([ex[t] for t in v[2]]); rr = np.array(v[4])
                if m_.any() and (~m_).any():
                    pe_.append(rr[m_].mean()); pk_.append(rr[~m_].mean())
                xr, xe = ret[s:e], excl[a][s:e]
                okr = np.isfinite(xr)
                if (xe & okr).any() and (~xe & okr).any():
                    ee_.append(xr[xe & okr].mean()); ek_.append(xr[~xe & okr].mean())
            out["excluded_vs_kept"][f"{a}|{wn}"] = {
                "picks_excluded_fwd40": float(np.mean(pe_)), "picks_kept_fwd40": float(np.mean(pk_)),
                "picks_excl_minus_kept": float(np.mean(pe_) - np.mean(pk_)), "picks_n_dates": len(pe_),
                "picks_share_dates_excl_gt_kept": float(np.mean(np.array(pe_) > np.array(pk_))),
                "eligible_excluded_fwd40": float(np.mean(ee_)), "eligible_kept_fwd40": float(np.mean(ek_)),
                "eligible_excl_minus_kept": float(np.mean(ee_) - np.mean(ek_)), "eligible_n_dates": len(ee_)}
            log(f"[{period} {a} {wn}] excluded vs kept {out['excluded_vs_kept'][f'{a}|{wn}']}")
        for m in MODELS:
            sf = np.where(excl[a], np.nan, score[m])
            pk_f = PR.picks_w(book, sf)
            n_cash = cash_fill(pk_f, pkw_u[m])
            for d, v in pk_f.items():        # no excluded name may be held
                assert not any(excl_by[a][d][t] for t in v[1])
            pk_fs, short = picks_fullsize(book, score[m], excl[a])
            n_cash_fs = cash_fill(pk_fs, pkw_u[m])
            for d, v in pk_fs.items():
                assert not any(excl_by[a][d][t] for t in v[1])
            out["short_buckets"][f"{a}|{m}"] = short
            pk_post = post_select(pkw_u[m], excl_by[a])
            out["empty_book_dates"][f"{a}|{m}"] = {"pre_selection_fullsize": n_cash_fs, "pre_selection_survivor_decile": n_cash, "post_selection": int(sum(1 for v in pk_post.values() if not v[1])),
                                                  "pool": n_cash_pool}
            for wn, (wl, wh) in WINS[period].items():
                _, ds = DD.window(pkw_u[m], all_dates, wl, wh)
                dset = set(ds)
                w_ = lambda pk: {d: v for d, v in pk.items() if d in dset}   # noqa: E731
                cu = ch_u[(wn, m)]
                cf = chains2(w_(pk_fs), ds, spy, DR.COST_BPS, RB)
                c1 = chains2(w_(pk_f), ds, spy, DR.COST_BPS, RB)
                cp = chains2(w_(pk_post), ds, spy, DR.COST_BPS, RB)
                cpu = chains2(w_(pool_u), ds, spy, DR.COST_BPS, RB)
                cpf = chains2(w_(pool_f), ds, spy, DR.COST_BPS, RB)
                py = (period == "B") or wn == "full"
                r = diff_stats(DD, cu, cf, DROP_YEAR[period], per_year=py)
                r["stats_unfiltered"], r["stats_filtered"] = book_stats(cu), book_stats(cf)
                r["iter1_survivor_decile"] = diff_stats(DD, cu, c1, DROP_YEAR[period])
                r["iter1_survivor_decile"]["stats_filtered"] = book_stats(c1)
                r["post_selection_variant"] = diff_stats(DD, cu, cp, DROP_YEAR[period])
                r["post_selection_variant"]["stats_filtered"] = book_stats(cp)
                pd_ = diff_stats(DD, cpu, cpf, DROP_YEAR[period])
                sel_u = DD.per_offset(cu) - DD.per_offset(cpu)
                sel_f = DD.per_offset(cf) - DD.per_offset(cpf)
                r["pool_decomp"] = {"pool_unfiltered_vs_spy": pd_["unfiltered"], "pool_filtered_vs_spy": pd_["filtered"],
                                    "pool_change": pd_["diff"], "pool_change_offsets_pos": pd_["diff_offsets_pos"],
                                    "selection_unfiltered": float(sel_u.mean()), "selection_filtered": float(sel_f.mean()),
                                    "selection_change": float((sel_f - sel_u).mean()),
                                    "selection_change_offsets_pos": int(((sel_f - sel_u) > 0).sum())}
                assert abs(r["pool_decomp"]["pool_change"] + r["pool_decomp"]["selection_change"] - r["diff"]) < 1e-12
                out["results"][f"{a}|{wn}|{m}"] = r
                log(f"[{period} {wn} {m} {a}] unf {r['unfiltered']:+.4f} filt {r['filtered']:+.4f} diff {r['diff']:+.4f} "
                    f"({r['diff_offsets_pos']}/40) drop{DROP_YEAR[period]} {r[f'diff_drop{DROP_YEAR[period]}']} "
                    f"post-sel diff {r['post_selection_variant']['diff']:+.4f} pool {pd_['diff']:+.4f} "
                    f"sel {r['pool_decomp']['selection_change']:+.4f} names {r['stats_filtered']['names_mean']:.0f} vs "
                    f"{r['stats_unfiltered']['names_mean']:.0f} short {short} iter1 diff {r['iter1_survivor_decile']['diff']:+.4f} cash {n_cash_fs}")
            (PARTS / f"{period}_run.json").write_text(json.dumps(out, indent=2, default=float))
    (PARTS / f"{period}_run.json").write_text(json.dumps(out, indent=2, default=float))
    log(f"[{period}] wrote {PARTS / f'{period}_run.json'} ({time.time()-T0:.0f}s)")


def aggregate():
    P = {p: json.loads((PARTS / f"{p}_run.json").read_text()) for p in "AB"}
    res = {"work_order": "WO-40 trailing-return filter (issued as WO-36)", "family": "short-term trend filter, k=2 arms scored independently",
           "holdout_read": 18, "iteration": "2: full-size book (primary); iteration 1 survivor-decile book kept under iter1_survivor_decile", "units": "fractions per year (0.01 = 1%/yr), 40-offset mean of annualised excess vs SPY",
           "arms": ARMS, "eras": {p: P[p] for p in "AB"}, "decision": {}}
    for m in MODELS:
        for a in ARMS:
            A, B = P["A"]["results"][f"{a}|full|{m}"], P["B"]["results"][f"{a}|full|{m}"]
            chk = {"A_full": A["diff"], "A_full_offsets_pos": A["diff_offsets_pos"], "B": B["diff"],
                   "B_offsets_pos": B["diff_offsets_pos"], "A_drop2008": A["diff_drop2008"], "B_drop2020": B["diff_drop2020"],
                   "A_post": P["A"]["results"][f"{a}|post|{m}"]["diff"],
                   "A_post_offsets_pos": P["A"]["results"][f"{a}|post|{m}"]["diff_offsets_pos"]}
            if chk["A_full"] <= 0 or chk["B"] <= 0:
                v = "KILL"
            elif (chk["A_full_offsets_pos"] >= 30 and chk["B_offsets_pos"] >= 30
                  and chk["A_drop2008"] > 0 and chk["B_drop2020"] > 0):
                v = "SUCCESS"
            else:
                v = "MIDDLE"
            res["decision"][f"{a}|{m}"] = {"checks": chk, "verdict": v,
                                           "scored": m == "icw9_seas"}
            log(f"decision {a} {m}: {chk} -> {v}")
    (OUT / "trailfilter.json").write_text(json.dumps(res, indent=2, default=float))
    log(f"wrote {OUT / 'trailfilter.json'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", choices=["A", "B"])
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--aggregate", action="store_true")
    a = ap.parse_args()
    if a.aggregate:
        aggregate()
    else:
        job(a.period, a.run)


if __name__ == "__main__":
    main()
