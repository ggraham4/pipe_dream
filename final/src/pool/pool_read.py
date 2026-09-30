"""
WO-31 (COO): descriptive pool and hedge read. NO trial, NO decision, no gate.
Any pool or hedge choice made after this read is in-sample for 2020+ (09-27
rule); this read does not choose. Period B is hold-out read #11 (unfitted,
frozen live weights; nothing fit or chosen on B).

Grid: v2 grid column c (composite_panel_v2 eligible_<pool>), pools cap150 /
cap500 / cap2000, models icw9_seas (ICW.PRODUCTION_WEIGHTS_V9_SEAS, frozen
live Theoretical) and icw8 (ICW.PRODUCTION_WEIGHTS, reconcile), decile_volq,
net 15 bp, 40 offsets, h=40, label close[t+40]/open[t+1] (outcome_cache_v2).

Books per pool x period (all via the WO-21/WO-24 harness, imported read-only):
  book     V.Book.picks on the model score (loader = model_audit_wo23.load_theo)
  pool     drag_decomp.noscore_picks (the WO-7 no-score construction)
  selection = book - pool, per offset
Hedged book (WO-9 ITERATE #1 / WO-10 arithmetic, tradable total-return basis):
  hedged_k = book_net_price + book_div - k*(ETF_price40 + ETF_div40) - k*10bp
  implemented as DD.chains(book, bench = k*(etf_px + etf_div + 10bp) - book_div)
  book_div per name = close[x]/open[e] * (f[x]/f[e] - 1), f = SEP closeadj/close,
  e = t+1, x = t+40 on the name's own bars (last bar if the series ends first).
  ETF div = ret40(total) - ret40(price) from the fresh yfinance pull
  (final/out/pool/bench/, pull_bench.py). SPY price leg = outcome_cache_v2 SPY
  (the "book vs SPY" basis); IWM price leg = pull.
  Variants: SPY k=1, IWM k=1, IWM k=0.8 (0.8 pre-set from WO-21's era-A beta ~0.82).

Usage (one process per job; screen_seas sets harness globals at import):
  python pool_read.py --period A --pool cap150     -> final/out/pool/parts/A_cap150.json
  python pool_read.py --aggregate                  -> final/out/pool/pool_hedge_read.json
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
OUT = FINAL / "out" / "pool"
PARTS = OUT / "parts"
BENCH = OUT / "bench"
MAIN = Path("/Users/ggraham/pipe_dream/final")
SEP_DIR = MAIN / "data" / "sharadar" / "panel" / "stocks"
SEAS_EXT_RO = Path("/Users/ggraham/pipe_dream/.claude/worktrees/wo24-construction-drag/final/out/audit/seas_factor_ext.parquet")
IWM_OLD = MAIN / "data" / "benchmarks" / "IWM.csv"
CUT = pd.Timestamp("2011-10-01")
WO9_COMMON = pd.Timestamp("2011-10-20")
SHORT = 0.0010
TOL = 1e-4                    # 0.01pp, as the work order
POOLS = ["cap150", "cap500", "cap2000"]
HEDGES = {"spy_1x": ("SPY", 1.0), "iwm_1x": ("IWM", 1.0), "iwm_0.8x": ("IWM", 0.8)}


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


# ------------------------------------------------------------------ helpers
def picks_w(book, score):
    """V.Book.picks, also keeping (tickers, renormalised weights)."""
    import composite as C
    score = np.asarray(score, dtype=np.float64)
    out = {}
    for d, s, e in book.sl:
        if e - s < C.N_VOL_QUINTILES * 4:
            continue
        g = pd.DataFrame({"volatility_60": book.vol[s:e]})
        sc = pd.DataFrame({"ticker": book.tick[s:e], "composite": score[s:e]})
        pk = C.pick_decile_volq(g, sc)
        ret = dict(zip(book.tick[s:e], book.ret[s:e]))
        pk = [(t, w) for t, w in pk if pd.notna(ret.get(t))]
        if not pk:
            continue
        ws = sum(w for _, w in pk)
        gross = sum((w / ws) * (1.0 + ret[t]) for t, w in pk) - 1.0
        out[d] = (gross, {t for t, _ in pk}, [t for t, _ in pk], [w / ws for _, w in pk], [ret[t] for t, _ in pk])
    return out


def load_sep(tickers, lo_month, hi_month):
    files = sorted(f for f in SEP_DIR.glob("*.parquet") if lo_month <= f.stem <= hi_month)
    parts = [pd.read_parquet(f, columns=["ticker", "date", "open", "close", "closeadj"],
                             filters=[("ticker", "in", sorted(tickers))]) for f in files]
    px = pd.concat(parts, ignore_index=True)
    px["date"] = pd.to_datetime(px["date"])
    px = px.drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"])
    out = {}
    for t, g in px.groupby("ticker", sort=False):
        out[t] = {"date": g["date"].to_numpy(), "open": g["open"].to_numpy(np.float64),
                  "close": g["close"].to_numpy(np.float64),
                  "f": (g["closeadj"] / g["close"]).to_numpy(np.float64)}
    return out


def book_divs(pkw, px, H):
    """hedged_tradable.main's per-name dividend arithmetic; returns
    ({date: book_div}, stats). Basis check: sum w*close[x]/open[e]-1 vs gross.
    A name whose SEP series ends before the label's exit (SEP floor at its last
    bar) while the outcome-cache label has later bars is listed as a
    name-label mismatch; the adjusted basis check uses the label for it."""
    bdiv, st = {}, {"dates": 0, "names": 0, "missing_in_sep": 0, "series_end_floor": 0,
                    "gross_max_abs_diff": 0.0, "worst": None, "gross_adj_max_abs_diff": 0.0,
                    "mismatch_not_floor": 0, "name_label_mismatch": []}
    for d, v in pkw.items():
        dv, gr, ga = 0.0, 0.0, 0.0
        for t, wi, rl in zip(v[2], v[3], v[4]):
            s = px.get(t)
            if s is None:
                st["missing_in_sep"] += 1
                continue
            i = int(np.searchsorted(s["date"], np.datetime64(d)))
            assert i < len(s["date"]) and s["date"][i] == np.datetime64(d), f"{t} {d} not in SEP"
            n = len(s["date"])
            e, x = i + 1, i + H
            floor = x > n - 1
            if floor:
                x = n - 1
                st["series_end_floor"] += 1
            pr = s["close"][x] / s["open"][e]
            ga += wi * pr
            if abs(pr - 1.0 - rl) > 1e-6:
                st["name_label_mismatch"].append([t, str(pd.Timestamp(d).date()), float(wi), float(rl), float(pr - 1.0),
                                                  bool(floor), str(pd.Timestamp(s["date"][-1]).date())])
                st["mismatch_not_floor"] += int(not floor)
                ga += wi * (1.0 + rl - pr)
            gr += wi * pr
            dv += wi * pr * (s["f"][x] / s["f"][e] - 1.0)
            st["names"] += 1
        st["dates"] += 1
        diff = abs((gr - 1.0) - v[0])
        if diff > st["gross_max_abs_diff"]:
            st["gross_max_abs_diff"], st["worst"] = diff, str(pd.Timestamp(d).date())
        st["gross_adj_max_abs_diff"] = max(st["gross_adj_max_abs_diff"], abs((ga - 1.0) - v[0]))
        bdiv[d] = dv
    return bdiv, st


def etf_legs(sym, dates):
    import hedged_composite as HC
    g = pd.read_parquet(BENCH / f"{sym}.parquet")
    pr, tr = HC.ret40(g), HC.ret40(g, total_return=True)
    DI = pd.DatetimeIndex(dates)
    return pr.reindex(DI), (tr - pr).reindex(DI)


def stats(ch, DD, years_drop=None):
    po = DD.per_offset(ch)
    years, lm = DD.loyo_vec(ch)
    gl = lm.mean(axis=0)
    r = {"mean40": float(po.mean()), "sd40": float(po.std()), "offsets_positive": int((po > 0).sum()),
         "loyo_min": float(gl.min()), "loyo_min_dropped_year": int(years[int(gl.argmin())]),
         "loyo_by_dropped_year": {int(y): float(v) for y, v in zip(years, gl)}}
    return r, po, (years, lm)


def diff_stats(po_a, po_b, loyo_a, loyo_b):
    assert loyo_a[0] == loyo_b[0]
    d = po_a - po_b
    gl = (loyo_a[1] - loyo_b[1]).mean(axis=0)
    ys = loyo_a[0]
    return {"mean40": float(d.mean()), "sd40": float(d.std()), "offsets_positive": int((d > 0).sum()),
            "loyo_min": float(gl.min()), "loyo_min_dropped_year": int(ys[int(gl.argmin())]),
            "loyo_by_dropped_year": {int(y): float(v) for y, v in zip(ys, gl)}}


# ------------------------------------------------------------------ job
def job(period, pool):
    sys.path.insert(0, str(SRC / "audit"))
    sys.path.insert(0, str(SRC / "construction"))
    import model_audit_wo23 as MA           # imports screen_seas (V.COL/SIGNS9), as WO-23/WO-24
    import drag_decomp as DD
    V, SI, DR, ICW = MA.V, MA.SI, MA.DR, MA.ICW
    import run_backtest as RB
    MA.SEAS_EXT = SEAS_EXT_RO               # gitignored ext file, read-only from the WO-24 worktree
    assert SEAS_EXT_RO.exists()
    T0 = time.time()
    W = {"icw9_seas": dict(ICW.PRODUCTION_WEIGHTS_V9_SEAS), "icw8": dict(ICW.PRODUCTION_WEIGHTS)}
    assert W["icw9_seas"] == MA.W9 and W["icw8"] == MA.W8

    U, all_dates, spy = MA.load_theo(period, pool)
    all_dates = [pd.Timestamp(d) for d in all_dates]
    V.add_ranks(U, MA.FT)
    book = V.Book(U, all_dates, spy)
    pkw = {m: picks_w(book, SI.composite_score(U, w).to_numpy()) for m, w in W.items()}
    pk = {m: {d: (v[0], v[1]) for d, v in p.items()} for m, p in pkw.items()}
    pk["pool"] = DD.noscore_picks(book)
    # oracle: picks_w == Book.picks on icw8
    ref8 = book.picks(SI.composite_score(U, W["icw8"]).to_numpy())
    assert ref8.keys() == pk["icw8"].keys() and all(ref8[d][1] == pk["icw8"][d][1] and ref8[d][0] == pk["icw8"][d][0] for d in ref8)
    info = {"rows": int(len(U)), "tickers": int(U["ticker"].nunique()), "calendar_dates": len(all_dates),
            "first": str(all_dates[0].date()), "last": str(all_dates[-1].date()),
            "mean_pool_names_per_date": float(U.groupby("date").size().mean()),
            "mean_book_names_per_date": {m: float(np.mean([len(v[1]) for v in pk[m].values()])) for m in W}}
    del U
    log(f"[{period} {pool}] books built {info} ({time.time()-T0:.0f}s)")

    # ---- reconcile first (hard assert, cap150; tol 0.01pp) before anything new
    if pool == "cap150":
        C_ = FINAL / "out" / "construction"
        bt = lambda p_, lo=None, hi=None: DR.backtest(*DD.window(p_, all_dates, lo, hi), spy)["excess_cagr_vs_spy_mean40"]
        if period == "A":
            wo21 = json.loads((C_ / "drag_decomp.json").read_text())
            early = {"icw8_full": (bt(pk["icw8"]), wo21["reconcile"]["score"]["full"]),
                     "icw8_full_vs_0.0285416": (bt(pk["icw8"]), 0.0285416),
                     "pool_post": (bt(pk["pool"], CUT, None), wo21["windows"]["post"]["books"]["noscore_net"])}
        else:
            mb = json.loads((C_ / "drag_decomp_b.json").read_text())["models"]["icw8"]
            b8, bp = bt(pk["icw8"]), bt(pk["pool"])
            early = {"icw8_book": (b8, mb["books"]["score_net"]), "pool": (bp, mb["books"]["noscore_net"]),
                     "selection": (b8 - bp, mb["selection"]["vs_noscore_net"]["mean40"]),
                     "icw8_book_vs_-1.99": (b8, -0.0199), "pool_vs_-4.85": (bp, -0.0485), "sel_vs_+2.85": (b8 - bp, 0.0285)}
        for k, (g, r) in early.items():
            log(f"[{period} cap150] reconcile {k}: {g:+.7f} vs {r:+.7f} diff {g - r:+.1e}")
            assert abs(g - r) < TOL, f"RECONCILE FAIL {k}: stop"
        info["early_reconcile"] = {k: {"got": g, "ref": r} for k, (g, r) in early.items()}

    # ---- dividends (SEP closeadj/close) for the two score books
    tick = set()
    for m in W:
        for v in pkw[m].values():
            tick |= set(v[2])
    lo_m = (all_dates[0] - pd.offsets.MonthBegin(2)).strftime("%Y-%m")
    hi_m = (all_dates[-1] + pd.offsets.MonthEnd(3)).strftime("%Y-%m")
    px = load_sep(tick, lo_m, hi_m)
    log(f"[{period} {pool}] SEP {len(px)} tickers {lo_m}..{hi_m} ({time.time()-T0:.0f}s)")
    bdiv, bstat = {}, {}
    for m in W:
        bdiv[m], bstat[m] = book_divs(pkw[m], px, RB.HORIZON)
        mm = bstat[m].get("name_label_mismatch", [])
        log(f"[{period} {pool}] {m} div basis { {k: v for k, v in bstat[m].items() if k != 'name_label_mismatch'} }; "
            f"{len(mm)} name-label mismatches > 1e-6, first {mm[:10]}")
        assert bstat[m]["missing_in_sep"] == 0, "names missing in SEP"
        assert bstat[m]["mismatch_not_floor"] == 0 and len(mm) <= 50, "name-label mismatch outside SEP series-end floor"
        assert bstat[m]["gross_adj_max_abs_diff"] < 1e-5, "BOOK GROSS BASIS RECONCILE FAIL"
    del px, pkw

    DI = pd.DatetimeIndex(all_dates)
    spy_s = spy.astype(np.float64).reindex(DI)
    spy_pr_pull, spy_dv = etf_legs("SPY", all_dates)
    iwm_pr, iwm_dv = etf_legs("IWM", all_dates)
    assert spy_pr_pull[spy_s.notna()].notna().all()
    assert iwm_pr[spy_s.notna()].notna().all() and spy_dv[spy_s.notna()].notna().all()
    etf = {"SPY": (spy_s, spy_dv), "IWM": (iwm_pr, iwm_dv)}

    wins = {"A": {"full": (None, None), "pre": (None, CUT), "post": (CUT, None)}, "B": {"full": (None, None)}}[period]
    res = {"period": period, "pool": pool, "info": info, "div_basis": bstat, "windows": {}}
    cost = DR.COST_BPS
    for wn, (lo, hi) in wins.items():
        sub = {b: DD.window(p_, all_dates, lo, hi) for b, p_ in pk.items()}
        ds = sub["pool"][1]
        mask = pd.Series(True, index=DI)
        if lo is not None:
            mask &= DI >= lo
        if hi is not None:
            mask &= DI < hi
        wres = {}
        ch_pool = DD.chains(sub["pool"][0], ds, spy, cost)
        s_pool, po_pool, ly_pool = stats(ch_pool, DD)
        assert abs(s_pool["mean40"] - DR.backtest(sub["pool"][0], ds, spy)["excess_cagr_vs_spy_mean40"]) < 1e-12
        wres["pool_vs_spy"] = s_pool
        for m in W:
            p_, _ = sub[m]
            ch = DD.chains(p_, ds, spy, cost)
            s_b, po_b, ly_b = stats(ch, DD)
            assert abs(s_b["mean40"] - DR.backtest(p_, ds, spy)["excess_cagr_vs_spy_mean40"]) < 1e-12, "oracle"
            mr = {"book_vs_spy": s_b, "selection_over_pool": diff_stats(po_b, po_pool, ly_b, ly_pool)}
            bd = pd.Series(bdiv[m]).reindex(DI)
            live = mask & spy_s.notna() & bd.notna()
            mr["div_yield_ann"] = {"book": float(bd[live].mean() * DD.ANN), "spy": float(spy_dv[live].mean() * DD.ANN),
                                   "iwm": float(iwm_dv[live].mean() * DD.ANN), "n_dates": int(live.sum())}
            mr["hedged"] = {}
            for hn, (sym, k) in HEDGES.items():
                px_, dv_ = etf[sym]
                bench = (k * (px_ + dv_ + SHORT) - bd).where(spy_s.notna())
                chh = DD.chains(p_, ds, bench.to_dict(), cost)
                s_h, po_h, _ = stats(chh, DD)
                assert sum(len(c["date"]) for c in chh) == sum(len(c["date"]) for c in ch), "hedge date coverage differs"
                mr["hedged"][hn] = s_h
                if hn == "spy_1x":   # oracle: hedged_spy - book_vs_spy == -(spy_div + 10bp - book_div), per offset
                    gap = (spy_dv + SHORT - bd).where(spy_s.notna()).to_dict()
                    chg = DD.chains(p_, ds, gap, cost)
                    ident = po_h - po_b
                    exp = np.array([(c["exc"] - c["net"]).mean() * DD.ANN for c in chg])
                    assert np.allclose(ident, exp, atol=1e-12), "SPY hedge identity fail"
                    mr["hedged"][hn]["minus_book_vs_spy"] = float(ident.mean())
            wres[m] = mr
            if period == "B":
                for key in ("book_vs_spy",):
                    mr[key]["drop_2020"] = mr[key]["loyo_by_dropped_year"][2020]
                for hn in HEDGES:
                    mr["hedged"][hn]["drop_2020"] = mr["hedged"][hn]["loyo_by_dropped_year"][2020]
                mr["selection_over_pool"]["drop_2020"] = mr["selection_over_pool"]["loyo_by_dropped_year"][2020]
            log(f"[{period} {pool} {wn}] {m}: book {s_b['mean40']:+.4f} ({s_b['offsets_positive']}/40) pool {s_pool['mean40']:+.4f} "
                f"sel {mr['selection_over_pool']['mean40']:+.4f} | SPYh {mr['hedged']['spy_1x']['mean40']:+.4f} "
                f"IWMh {mr['hedged']['iwm_1x']['mean40']:+.4f} IWM.8h {mr['hedged']['iwm_0.8x']['mean40']:+.4f}")
        res["windows"][wn] = wres

    # ---- WO-9 reproduction (A, icw8): old IWM.csv, WO-9 end-of-era mask, 2011-10-20 common
    if period == "A":
        import hedged_composite as HC
        old = pd.read_csv(IWM_OLD, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
        ip, it = HC.ret40(old).reindex(DI), HC.ret40(old, total_return=True).reindex(DI)
        bd = pd.Series(bdiv["icw8"]).reindex(DI)
        sb = HC.SHORT_BPS / 1e4
        com = DI >= WO9_COMMON
        wo9 = {}
        for vn, bench in (("price_only_15bp", ip + sb), ("tradable_15bp", ip + sb - (bd - (it - ip)))):
            for wn, b in (("full", bench), ("common", bench.where(com))):
                ch = DD.chains(pk["icw8"], all_dates, b.to_dict(), cost)
                wo9[f"{vn}_{wn}"] = float(DD.per_offset(ch).mean())
        res["wo9_reproduce_icw8"] = wo9
    res["runtime_s"] = time.time() - T0
    PARTS.mkdir(parents=True, exist_ok=True)
    (PARTS / f"{period}_{pool}.json").write_text(json.dumps(res, indent=2, default=float))
    log(f"wrote {PARTS / f'{period}_{pool}.json'} ({res['runtime_s']:.0f}s)")


# ------------------------------------------------------------------ aggregate
def aggregate():
    C = FINAL / "out" / "construction"
    R26 = MAIN / "out" / "reset2026" / "downcap_v2"
    wo21 = json.loads((C / "drag_decomp.json").read_text())
    wo24 = json.loads((C / "drag_decomp_b.json").read_text())
    wo23 = json.loads((FINAL / "out" / "audit" / "model_audit_wo23.json").read_text())
    readout = json.loads((R26 / "readout.json").read_text())["columns"]["c"]
    wo7 = json.loads((R26 / "noscore_control.json").read_text())["tiers"]
    hc = json.loads((R26 / "hedged_composite.json").read_text())["tiers"]
    ht = json.loads((R26 / "hedged_tradable.json").read_text())["tiers"]
    P = {(p, t): json.loads((PARTS / f"{p}_{t}.json").read_text()) for p in "AB" for t in POOLS}

    def chk(name, got, ref, blocking=True):
        return {"name": name, "got": got, "ref": ref, "diff": got - ref, "ok": bool(abs(got - ref) < TOL), "blocking": blocking}

    A150, B150 = P[("A", "cap150")]["windows"], P[("B", "cap150")]["windows"]["full"]
    rec = [chk("WO-21 A cap150 icw8 full", A150["full"]["icw8"]["book_vs_spy"]["mean40"], wo21["reconcile"]["score"]["full"]),
           chk("WO-21 A cap150 icw8 pre", A150["pre"]["icw8"]["book_vs_spy"]["mean40"], wo21["reconcile"]["score"]["pre"]),
           chk("WO-21 A cap150 icw8 post", A150["post"]["icw8"]["book_vs_spy"]["mean40"], wo21["reconcile"]["score"]["post"]),
           chk("WO-21 A cap150 pool post", A150["post"]["pool_vs_spy"]["mean40"], wo21["windows"]["post"]["books"]["noscore_net"]),
           chk("WO-21 A cap150 pool pre", A150["pre"]["pool_vs_spy"]["mean40"], wo21["windows"]["pre"]["books"]["noscore_net"]),
           chk("WO-23 A cap150 icw9_seas full", A150["full"]["icw9_seas"]["book_vs_spy"]["mean40"],
               wo23["A"]["theoretical"]["icw9_seas"]["excess_cagr_vs_spy_mean40"])]
    for m in ("icw8", "icw9_seas"):
        mb = wo24["models"][m]
        rec += [chk(f"WO-24 B cap150 {m} book", B150[m]["book_vs_spy"]["mean40"], mb["books"]["score_net"]),
                chk(f"WO-24 B cap150 {m} selection over pool", B150[m]["selection_over_pool"]["mean40"],
                    mb["selection"]["vs_noscore_net"]["mean40"])]
    rec.append(chk("WO-24 B cap150 pool", B150["pool_vs_spy"]["mean40"], wo24["models"]["icw8"]["books"]["noscore_net"]))
    for t in POOLS:
        Aw = P[("A", t)]["windows"]["full"]
        rec.append(chk(f"readout col c A {t} icw8", Aw["icw8"]["book_vs_spy"]["mean40"], readout[t]["icw8"]["excess_cagr_vs_spy_mean40"], False))
        rec.append(chk(f"WO-7 A {t} pool", Aw["pool_vs_spy"]["mean40"], wo7[t]["books"]["vs_spy_full"]["noscore"]["mean40"], False))
        w9 = P[("A", t)]["wo9_reproduce_icw8"]
        for vn, src in (("price_only_15bp", hc[t]["hedged"]["primary_15bp"]), ("tradable_15bp", ht[t]["variants"]["tradable_15bp"])):
            for wn in ("full", "common"):
                rec.append(chk(f"WO-9 A {t} icw8 {vn} {wn}", w9[f"{vn}_{wn}"], src[wn]["mean40"], t == "cap150"))
    for r in rec:
        log(f"reconcile {r['name']}: {r['got']:+.7f} vs {r['ref']:+.7f} diff {r['diff']:+.1e} {'OK' if r['ok'] else 'MISS'}"
            f"{'' if r['blocking'] else ' (non-blocking)'}")
    all_block = all(r["ok"] for r in rec if r["blocking"])

    def row(p, t, w, m="icw9_seas"):
        W_ = P[(p, t)]["windows"][w]
        x = W_[m]
        r = {"book_vs_spy": x["book_vs_spy"]["mean40"], "book_offsets_pos": x["book_vs_spy"]["offsets_positive"],
             "book_loyo_min": x["book_vs_spy"]["loyo_min"], "book_loyo_min_year": x["book_vs_spy"]["loyo_min_dropped_year"],
             "pool_vs_spy": W_["pool_vs_spy"]["mean40"], "pool_offsets_pos": W_["pool_vs_spy"]["offsets_positive"],
             "selection": x["selection_over_pool"]["mean40"], "selection_offsets_pos": x["selection_over_pool"]["offsets_positive"],
             "selection_loyo_min": x["selection_over_pool"]["loyo_min"]}
        for hn in HEDGES:
            h = x["hedged"][hn]
            r[f"hedged_{hn}"] = h["mean40"]; r[f"hedged_{hn}_offsets_pos"] = h["offsets_positive"]
            r[f"hedged_{hn}_loyo_min"] = h["loyo_min"]
            if p == "B":
                r[f"hedged_{hn}_drop2020"] = h["drop_2020"]
        if p == "B":
            r["book_drop2020"] = x["book_vs_spy"]["drop_2020"]
            r["selection_drop2020"] = x["selection_over_pool"]["drop_2020"]
        for hn in HEDGES:
            r[f"hedged_{hn}_loyo_min_year"] = x["hedged"][hn]["loyo_min_dropped_year"]
        r["div_yield_ann"] = x["div_yield_ann"]
        return r

    tables = {m: {f"{p}_{w}": {t: row(p, t, w, m) for t in POOLS}
                  for p, ws in (("A", ("full", "pre", "post")), ("B", ("full",))) for w in ws} for m in ("icw9_seas", "icw8")}
    out = {"work_order": "WO-31", "kind": "descriptive read; no trial, no gate, no decision",
           "rule_0927": "Any pool or hedge choice made after this read is in-sample for 2020+ (09-27 rule); this read does not choose.",
           "holdout_read": 11, "period_A": "2007-01-02..2019-12-31 (pre < 2011-10-01 <= post, sub-calendars as WO-21)",
           "period_B": "2020-01-02..2026-07-30 (last matured label)", "cost_bps": 15.0, "short_leg_cost_per_rebalance": SHORT,
           "hedges": {k: {"etf": v[0], "k": v[1]} for k, v in HEDGES.items()},
           "units": "annualised (x252/40) mean over 40 offsets of per-rebalance excess; fractions (0.01 = 1%/yr)",
           "reconcile": {"tol": TOL, "checks": rec, "all_blocking_pass": all_block},
           "bench_pull": json.loads((BENCH / "pull_meta.json").read_text()),
           "tables": tables,
           "parts": {f"{p}_{t}": P[(p, t)] for (p, t) in P}}
    gate = OUT / "gate_a.json"
    if gate.exists():
        out["gate_a"] = json.loads(gate.read_text())
    (OUT / "pool_hedge_read.json").write_text(json.dumps(out, indent=2, default=float))
    log(f"wrote {OUT / 'pool_hedge_read.json'}; blocking reconcile {'PASS' if all_block else 'FAIL'}")
    assert all_block, "RECONCILE FAIL"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", choices=["A", "B"])
    ap.add_argument("--pool", choices=POOLS)
    ap.add_argument("--aggregate", action="store_true")
    a = ap.parse_args()
    aggregate() if a.aggregate else job(a.period, a.pool)


if __name__ == "__main__":
    main()
