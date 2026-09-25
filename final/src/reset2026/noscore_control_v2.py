"""
WO-7: decompose the v2-grid composite's nomination-era excess into
selection (ranking), concentration/construction, and holding the eligible
universe. Descriptive, NOT a new trial, no kill. Pre-registration:
final/models/2026-09-24-noscore-control-v2.md (frozen before this ran).

Books per tier (column c, 2007-01-02..2019-12-31):
  icw8     ICW.compute_composite_ic_weighted -> C.pick_decile_volq
  noscore  no_exclusion_control.pick_full_universe_volq (every eligible name,
           inverse-vol, no score)
  null_k   icw8 composite permuted WITHIN date among pick_decile_volq-valid
           rows (finite vol & finite composite), same pick_decile_volq;
           k = 0..19, rng = default_rng([k, date.toordinal(), tier_index])

Imports downcap_v2_readout (load_column, backtest) and no_exclusion_control;
edits neither. `backtest_vectors` copies `backtest`'s arithmetic and is
asserted equal to it on every icw8 book.

Output: /Users/ggraham/pipe_dream/final/out/reset2026/downcap_v2/noscore_control.json
Usage:  /opt/anaconda3/envs/pipe_dream/bin/python noscore_control_v2.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C                      # noqa: E402
import run_backtest as RB                  # noqa: E402
import ic_weighted_composite as ICW        # noqa: E402
import downcap_v2_readout as R             # noqa: E402
import no_exclusion_control as NX          # noqa: E402

OUT = R.V2 / "noscore_control.json"
TIERS = ["cap150", "cap500", "cap2000"]
N_DRAWS = 20
COMMON_START = pd.Timestamp("2011-10-20")
REF_NOSCORE_A_CAP150 = 0.0240          # corrections doc §2a, 2 d.p. published
TOL_NOSCORE = 0.0005                   # 0.05pp
ANN = 252.0 / RB.HORIZON
log = R.log


# ---------------------------------------------------------------- backtest
def backtest_vectors(picks_by_date, all_dates, bench, fnew_override=None, cost_bps=None, gidx=0):
    """Same arithmetic as downcap_v2_readout.backtest, but returns the
    per-offset vector and per-(offset, year) LOYO values. `bench` may carry
    NaN (masked after costing, exactly as backtest does). fnew_override:
    dict date->turnover fraction per offset chain (callable(off, tp))."""
    per_off, loyo = [], []
    for off in range(40):
        prev, recs = set(), []
        for tp in all_dates[off::RB.HORIZON]:
            if tp not in picks_by_date:
                continue
            gross, cur = picks_by_date[tp][gidx], picks_by_date[tp][1]
            f_new = sum(1 for t in cur if t not in prev) / len(cur)
            if fnew_override is not None:
                f_new = fnew_override(off, tp)
            prev = cur
            recs.append({"date": tp, "gross": gross, "f_new": f_new, "b": bench.get(tp, np.nan)})
        net = RB.turnover_net_return(recs, R.COST_BPS if cost_bps is None else cost_bps)
        s = np.array([r["b"] for r in recs], dtype=np.float64)
        yrs = np.array([r["date"].year for r in recs])
        ok = np.isfinite(s)
        exc, yrs = net[ok] - s[ok], yrs[ok]
        per_off.append(float(exc.mean() * ANN))
        loyo.append({int(y): float(exc[yrs != y].mean() * ANN) for y in np.unique(yrs)})
    return np.array(per_off), loyo


def summarize(per_off, loyo):
    years = sorted(loyo[0])
    ly = {y: float(np.mean([lo[y] for lo in loyo])) for y in years}
    ymin, ymax = min(ly, key=ly.get), max(ly, key=ly.get)
    return {"mean40": float(per_off.mean()), "sd40": float(per_off.std()),
            "min40": float(per_off.min()), "max40": float(per_off.max()),
            "offsets_positive": int((per_off > 0).sum()),
            "loyo_min": ly[ymin], "loyo_min_dropped_year": ymin,
            "loyo_max": ly[ymax], "loyo_max_dropped_year": ymax}


def loyo_matrix(loyo):
    years = sorted(loyo[0])
    for lo in loyo:
        assert sorted(lo) == years, "offsets cover different years"
    return years, np.array([[lo[y] for y in years] for lo in loyo])  # (40, Y)


def gap_stats(a_off, b_off, a_loyo, b_loyo, years):
    g = a_off - b_off
    gl = (a_loyo - b_loyo).mean(axis=0)              # mean over offsets, per dropped year
    return {"mean40": float(g.mean()), "sd40": float(g.std()),
            "offsets_positive": int((g > 0).sum()),
            "loyo_min": float(gl.min()), "loyo_min_dropped_year": int(years[int(gl.argmin())]),
            "loyo_max": float(gl.max()), "loyo_max_dropped_year": int(years[int(gl.argmax())]),
            "per_offset": [float(x) for x in g]}


# ---------------------------------------------------------------- picks
def realise(picks, ret, drops, key, d):
    """Drop NaN-return picks (recording pre-renorm weight), renormalise,
    return (gross, set, tickers, weights)."""
    kept, dropped_w = [], 0.0
    for t, w in picks:
        r = ret.get(t)
        if r is None or not np.isfinite(r):
            dropped_w += w
            drops["names"].append((key, d, t, float(w)))
        else:
            kept.append((t, w))
    drops["n_dates"] += 1
    drops["n_picks"] += len(picks)
    drops["n_dropped"] += len(picks) - len(kept)
    drops["w_sum"] += dropped_w
    drops["w_max"] = max(drops["w_max"], dropped_w)
    if not kept:
        return None
    tk = np.array([t for t, _ in kept], dtype=object)
    w = np.array([w for _, w in kept], dtype=np.float64)
    r = np.array([ret[t] for t in tk], dtype=np.float64)
    w = w / w.sum()
    # supplementary worst case: dropped names held at their pre-renorm weight and lose 100%
    wtot = sum(wi for _, wi in picks)
    gross_worst = float((w * (1.0 - dropped_w / wtot) * (1.0 + r)).sum() - 1.0)
    gross = float((w * (1.0 + r)).sum() - 1.0)
    return gross, set(tk), tk, w, gross_worst


def new_drops():
    return {"n_dates": 0, "n_picks": 0, "n_dropped": 0, "w_sum": 0.0, "w_max": 0.0, "names": []}


def build_books(p, tiers, with_null=True):
    books = {t: {"icw8": {}, "noscore": {}, **({f"null{k}": {} for k in range(N_DRAWS)} if with_null else {})}
             for t in tiers}
    drops = {t: {b: new_drops() for b in books[t]} for t in tiers}
    t0 = time.time()
    for i, (d, g) in enumerate(p.groupby("date", sort=True)):
        for ti, tier in enumerate(tiers):
            elig = g[g[f"eligible_{tier}"]]
            if len(elig) < C.N_VOL_QUINTILES * 4:
                continue
            elig = elig.reset_index(drop=True)
            ret = dict(zip(elig["ticker"], elig["gross_return_40"].astype(np.float64)))
            sc = ICW.compute_composite_ic_weighted(elig)
            out = {"icw8": C.pick_decile_volq(elig, sc), "noscore": NX.pick_full_universe_volq(elig)}
            if with_null:
                comp = sc["composite"].to_numpy(np.float64)
                valid = np.isfinite(comp) & np.isfinite(elig["volatility_60"].to_numpy(np.float64))
                vidx = np.flatnonzero(valid)
                for k in range(N_DRAWS):
                    rng = np.random.default_rng([k, d.toordinal(), ti])
                    c2 = comp.copy()
                    c2[vidx] = comp[rng.permutation(vidx)]
                    s2 = sc.copy()
                    s2["composite"] = c2
                    out[f"null{k}"] = C.pick_decile_volq(elig, s2)
            for b, picks in out.items():
                if not picks:
                    continue
                res = realise(picks, ret, drops[tier][b], b, d)
                if res is not None:
                    books[tier][b][d] = res
        if i % 500 == 0:
            log(f"    date {i} {d.date()} ({time.time()-t0:.0f}s)")
    return books, drops


# ---------------------------------------------------------------- pool integrity
def classify_drops(drops, oc_last, oc_keys, lastprice):
    out = {}
    for b, dr in drops.items():
        cats = {"absent_from_cache": 0, "in_cache_nan": 0,
                "in_cache_nan_last_bar_in_cache": 0, "in_cache_nan_other_bad_price": 0,
                "pick_date_equals_lastpricedate": 0}
        near_delist_w, near_delist_n = 0.0, 0
        for _, d, t, w in dr["names"]:
            if (t, d) not in oc_keys:
                cats["absent_from_cache"] += 1
            else:
                cats["in_cache_nan"] += 1
                cats["in_cache_nan_last_bar_in_cache" if oc_last.get(t) == d
                     else "in_cache_nan_other_bad_price"] += 1
            lp = lastprice.get(t)
            if lp is not None and pd.notna(lp) and lp == pd.Timestamp(d):
                cats["pick_date_equals_lastpricedate"] += 1
            if lp is not None and pd.notna(lp) and pd.Timestamp(d) <= lp <= pd.Timestamp(d) + pd.Timedelta(days=60):
                near_delist_n += 1
                near_delist_w += w
        nd = max(dr["n_dates"], 1)
        out[b] = {"n_dates": dr["n_dates"], "n_picks": dr["n_picks"], "n_dropped": dr["n_dropped"],
                  "dropped_weight_mean_per_date": dr["w_sum"] / nd, "dropped_weight_max_date": dr["w_max"],
                  "dropped_weight_total": dr["w_sum"], **cats,
                  "n_dropped_lastpricedate_within_60d": near_delist_n,
                  "weight_dropped_lastpricedate_within_60d_mean_per_date": near_delist_w / nd}
    return out


# ---------------------------------------------------------------- main
def common_dates(books):
    ds = None
    for b, pk in books.items():
        ds = set(pk) if ds is None else ds & set(pk)
    return ds


def weight_turnover_fn(pk, all_dates):
    """0.5 * sum|w_t - w_{t-1}| along each offset chain (drift ignored)."""
    cache = {}
    for off in range(40):
        prev = None
        for tp in all_dates[off::RB.HORIZON]:
            if tp not in pk:
                continue
            tk, w = pk[tp][2], pk[tp][3]
            cur = pd.Series(w, index=tk)
            if prev is None:
                cache[(off, tp)] = 1.0
            else:
                u = cur.index.union(prev.index)
                cache[(off, tp)] = float(0.5 * np.abs(cur.reindex(u, fill_value=0.0)
                                                      - prev.reindex(u, fill_value=0.0)).sum())
            prev = cur
    return cache


def main():
    T0 = time.time()
    out = {"work_order": "WO-7", "era": "2007-01-02..2019-12-31", "cost_bps": R.COST_BPS,
           "common_window": "2011-10-20..2019-12-31", "n_null_draws": N_DRAWS,
           "prereg": "final/models/2026-09-24-noscore-control-v2.md"}

    # ---- gate 1: column a, cap150, no-score == +2.40%/yr
    pa_, spy_a = R.load_column("a")
    assert "volatility_60" in pa_.columns
    all_a = sorted(pa_["date"].unique())
    bk_a, _ = build_books(pa_, ["cap150"], with_null=False)
    ns_a = R.backtest({d: v[:2] for d, v in bk_a["cap150"]["noscore"].items()}, all_a, spy_a)
    ic_a = R.backtest({d: v[:2] for d, v in bk_a["cap150"]["icw8"].items()}, all_a, spy_a)
    out["reconcile_noscore_col_a_cap150"] = {"got": ns_a, "ref": REF_NOSCORE_A_CAP150, "tol": TOL_NOSCORE}
    log(f"gate1 no-score col a cap150 {ns_a['excess_cagr_vs_spy_mean40']:+.5f} (ref +0.0240) "
        f"sd {ns_a['sd40']:.4f} pos {ns_a['offsets_positive']}")
    assert abs(ns_a["excess_cagr_vs_spy_mean40"] - REF_NOSCORE_A_CAP150) <= TOL_NOSCORE, "GATE 1 FAIL"
    ref_readout = json.loads((R.V2 / "readout.json").read_text())["columns"]
    ra = ref_readout["a"]["cap150"]["icw8"]
    assert abs(ic_a["excess_cagr_vs_spy_mean40"] - ra["excess_cagr_vs_spy_mean40"]) < 1e-9, "col a icw8 mismatch"
    log("gate1 OK (and col a icw8 == readout)")
    del pa_, bk_a

    # ---- column c
    p, spy = R.load_column("c")
    assert "volatility_60" in p.columns
    all_dates = sorted(p["date"].unique())
    usmv = pd.read_parquet(R.R26 / "outcome_cache_v2.parquet", columns=["ticker", "date", "gross_return_40"],
                           filters=[("ticker", "==", "USMV"), ("date", ">=", R.START), ("date", "<=", R.END)])
    usmv["date"] = pd.to_datetime(usmv["date"])
    usmv = R.guard(usmv).set_index("date")["gross_return_40"].astype(np.float64)
    usmv = usmv.reindex(pd.DatetimeIndex(all_dates))
    spy_s = spy.astype(np.float64).reindex(pd.DatetimeIndex(all_dates))
    common_mask = pd.DatetimeIndex(all_dates) >= COMMON_START
    assert usmv[common_mask].notna().all(), "USMV NaN inside common window"
    assert usmv[~common_mask].isna().all()
    spy_common = spy_s.where(common_mask)
    benches = {"vs_spy_full": spy_s, "vs_spy_common": spy_common, "vs_usmv_common": usmv}

    books, drops = build_books(p, TIERS, with_null=True)
    log(f"books built ({time.time()-T0:.0f}s)")

    # pool-integrity metadata
    dropped_pairs = {(t, d) for tier in TIERS for b in drops[tier] for _, d, t, _ in drops[tier][b]["names"]}
    dt = sorted({t for t, _ in dropped_pairs})
    if dt:
        ocd = pd.read_parquet(R.R26 / "outcome_cache_v2.parquet", columns=["ticker", "date"],
                              filters=[("ticker", "in", dt), ("date", ">=", R.START), ("date", "<=", R.END)])
        ocd["date"] = pd.to_datetime(ocd["date"])
        R.guard(ocd)
        oc_keys = set(zip(ocd["ticker"].astype(str), ocd["date"]))
        oc_last = ocd.assign(ticker=ocd["ticker"].astype(str)).groupby("ticker")["date"].max().to_dict()
    else:
        oc_keys, oc_last = set(), {}
    tm = pd.read_csv(R.SH / "tickers_master.csv", dtype=str, usecols=["ticker", "lastpricedate"])
    tm["lastpricedate"] = pd.to_datetime(tm["lastpricedate"], errors="coerce")
    lastprice = tm.groupby("ticker")["lastpricedate"].max().to_dict()

    out["tiers"] = {}
    for tier in TIERS:
        bk = books[tier]
        tres = {"readout_reconcile": {}, "books": {}, "pool_integrity": {}}
        # gate 2: icw8 unrestricted == readout
        full = R.backtest({d: v[:2] for d, v in bk["icw8"].items()}, all_dates, spy)
        ref = ref_readout["c"][tier]["icw8"]
        for k in ("excess_cagr_vs_spy_mean40", "sd40", "loyo_min", "offsets_positive"):
            assert abs(full[k] - ref[k]) < 1e-6, f"GATE 2 FAIL {tier} {k} {full[k]} vs {ref[k]}"
        tres["readout_reconcile"] = {"got": full, "ref": ref, "ok": True}
        # oracle: backtest_vectors == backtest
        po, lo = backtest_vectors(bk["icw8"], all_dates, spy)
        sm = summarize(po, lo)
        assert abs(sm["mean40"] - full["excess_cagr_vs_spy_mean40"]) < 1e-12
        assert abs(sm["sd40"] - full["sd40"]) < 1e-12
        assert abs(sm["loyo_min"] - full["loyo_min"]) < 1e-12 and sm["loyo_min_dropped_year"] == full["loyo_min_dropped_year"]
        log(f"{tier}: gate2 OK icw8 {full['excess_cagr_vs_spy_mean40']:+.5f}; oracle OK")

        # alignment
        cd = common_dates(bk)
        n_drop = {b: len(set(pk) - cd) for b, pk in bk.items()}
        tres["alignment"] = {"common_dates": len(cd), "dates_removed_per_book": n_drop}
        bk_al = {b: {d: v for d, v in pk.items() if d in cd} for b, pk in bk.items()}

        names = list(bk_al)
        specs = [(k, v, None, 0) for k, v in benches.items()] + [
            ("supp_vs_spy_full_gross_0bp", spy_s, 0.0, 0),
            ("supp_vs_spy_full_dropped_as_minus100pct", spy_s, None, 4)]
        for bname, bench, cost, gidx in specs:
            vec, lmat, years = {}, {}, None
            for b in names:
                po, lo = backtest_vectors(bk_al[b], all_dates, bench, cost_bps=cost, gidx=gidx)
                years, lm = loyo_matrix(lo)
                vec[b], lmat[b] = po, lm
            nulls = np.array([vec[f"null{k}"] for k in range(N_DRAWS)])        # (20, 40)
            null_lm = np.array([lmat[f"null{k}"] for k in range(N_DRAWS)])      # (20, 40, Y)
            nmed, nmed_l = np.median(nulls, axis=0), np.median(null_lm, axis=0)
            null_means = nulls.mean(axis=1)
            ic_mean = float(vec["icw8"].mean())

            def book_sum(po, lm):
                ly = lm.mean(axis=0)
                return {"mean40": float(po.mean()), "sd40": float(po.std()), "min40": float(po.min()),
                        "max40": float(po.max()), "offsets_positive": int((po > 0).sum()),
                        "loyo_min": float(ly.min()), "loyo_min_dropped_year": int(years[int(ly.argmin())]),
                        "loyo_max": float(ly.max()), "loyo_max_dropped_year": int(years[int(ly.argmax())]),
                        "per_offset": [float(x) for x in po]}
            res = {"icw8": book_sum(vec["icw8"], lmat["icw8"]),
                   "noscore": book_sum(vec["noscore"], lmat["noscore"]),
                   "null_median": book_sum(nmed, nmed_l),
                   "null_draw_means": [float(x) for x in null_means],
                   "null_draws_per_offset": [[float(x) for x in r] for r in nulls],
                   "null_p50": float(np.percentile(null_means, 50)),
                   "null_p80": float(np.percentile(null_means, 80)),
                   "null_p95": float(np.percentile(null_means, 95)),
                   "icw8_rank_of_21": int((null_means < ic_mean).sum()) + 1,
                   "icw8_draws_beaten": int((null_means < ic_mean).sum()),
                   "gaps": {
                       "selection_icw8_minus_nullmed": gap_stats(vec["icw8"], nmed, lmat["icw8"], nmed_l, years),
                       "concentration_nullmed_minus_noscore": gap_stats(nmed, vec["noscore"], nmed_l, lmat["noscore"], years),
                       "total_icw8_minus_noscore": gap_stats(vec["icw8"], vec["noscore"], lmat["icw8"], lmat["noscore"], years)},
                   "years": [int(y) for y in years]}
            tres["books"][bname] = res
            g = res["gaps"]
            log(f"  {tier} {bname}: icw8 {ic_mean:+.4f} null p50 {res['null_p50']:+.4f} p95 {res['null_p95']:+.4f} "
                f"noscore {res['noscore']['mean40']:+.4f} | sel {g['selection_icw8_minus_nullmed']['mean40']:+.4f} "
                f"({g['selection_icw8_minus_nullmed']['offsets_positive']}/40) conc "
                f"{g['concentration_nullmed_minus_noscore']['mean40']:+.4f} tot {g['total_icw8_minus_noscore']['mean40']:+.4f}")

        # turnover caveat on the no-score book (aligned chain)
        wt = weight_turnover_fn(bk_al["noscore"], all_dates)
        fn_counts = []
        for off in range(40):
            prev = set()
            for tp in all_dates[off::RB.HORIZON]:
                if tp in bk_al["noscore"]:
                    cur = bk_al["noscore"][tp][1]
                    fn_counts.append(sum(1 for t in cur if t not in prev) / len(cur))
                    prev = cur
        po_w, lo_w = backtest_vectors(bk_al["noscore"], all_dates, spy_s, fnew_override=lambda o, tp: wt[(o, tp)])
        wt_vals = np.array(list(wt.values()))
        tres["turnover_caveat_noscore"] = {
            "mean_f_new_name_count": float(np.mean(fn_counts)),
            "mean_weight_turnover_estimate": float(wt_vals.mean()),
            "mean_weight_turnover_excl_first_window": float(np.mean([v for (o, tp), v in wt.items()
                                                                     if tp != min(t for (oo, t) in wt if oo == o)])),
            "noscore_vs_spy_full_with_weight_turnover": summarize(po_w, lo_w),
            "note": "estimate: drift ignored; headline numbers use name-count f_new as specified"}

        # icw8 f_new vs weight turnover, for reference
        wt_i = weight_turnover_fn(bk_al["icw8"], all_dates)
        tres["turnover_caveat_icw8_mean_weight_turnover_estimate"] = float(np.mean(list(wt_i.values())))

        tres["pool_integrity"] = classify_drops(drops[tier], oc_last, oc_keys, lastprice)
        pi = tres["pool_integrity"]
        agg_null_w = float(np.mean([pi[f"null{k}"]["dropped_weight_mean_per_date"] for k in range(N_DRAWS)]))
        log(f"  {tier} drops: icw8 {pi['icw8']['n_dropped']} (w/date {pi['icw8']['dropped_weight_mean_per_date']:.2e}), "
            f"noscore {pi['noscore']['n_dropped']} (w/date {pi['noscore']['dropped_weight_mean_per_date']:.2e}), "
            f"null mean w/date {agg_null_w:.2e}")
        out["tiers"][tier] = tres
        OUT.write_text(json.dumps(out, indent=2, default=str))

    # ---- frozen reading
    def reading(tier):
        r = out["tiers"][tier]["books"]["vs_spy_full"]
        sel = r["gaps"]["selection_icw8_minus_nullmed"]
        tot = r["gaps"]["total_icw8_minus_noscore"]
        icm = r["icw8"]["mean40"]
        c = {"sel_ge_1pp": sel["mean40"] >= 0.010, "icw8_ge_p95": icm >= r["null_p95"],
             "sel_pos_ge_36": sel["offsets_positive"] >= 36, "sel_loyo_min_pos": sel["loyo_min"] > 0,
             "total_lt_0p5pp": tot["mean40"] < 0.005, "icw8_lt_p80": icm < r["null_p80"]}
        sm = c["sel_ge_1pp"] and c["icw8_ge_p95"] and c["sel_pos_ge_36"] and c["sel_loyo_min_pos"]
        ub = c["total_lt_0p5pp"] or c["icw8_lt_p80"]
        v = ("SELECTION MATERIAL + MOSTLY UNIVERSE BETA (both triggered)" if sm and ub else
             "SELECTION MATERIAL" if sm else "MOSTLY UNIVERSE BETA" if ub else "MIDDLE")
        return {"conditions": c, "verdict": v}
    out["frozen_reading"] = {t: reading(t) for t in TIERS}
    out["verdict_cap150"] = out["frozen_reading"]["cap150"]["verdict"]
    OUT.write_text(json.dumps(out, indent=2, default=str))
    log(f"VERDICT cap150: {out['verdict_cap150']}  ({time.time()-T0:.0f}s total)")


if __name__ == "__main__":
    main()
