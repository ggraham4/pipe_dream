"""
WO-25 (COO): backtests of live icw9_seas vs the re-derived icw9_v2.
Method pinned in final/models/2026-09-29-icw-v2-reweight.md (commit 0aa87b4,
before this ran). Hold-out read #7 (SI weight FIT on 2020-2026, Gabe-approved).

Harness: WO-23's final/src/audit/model_audit_wo23.py (load_theo, run_book,
factor_ic), imported, not edited. cap150, v2 col c, decile_volq, 40 offsets,
net 15bp.

Steps
  0. Recompute the t's: 8 non-SI factors on A, SI on B; must equal WO-23's to 1e-6.
  1. Reconcile: live icw9_seas 4dp mean40 == WO-23 A and B to 1e-9.
  2. A in-sample: live vs icw9_v2 (4dp, + full precision).
  3. A split-half OOS for icw9_v2 (odd/even by date.year%2; stitched + each half).
  4. B: live vs icw9_v2 vs icw9_v2_si_floor (SI-fit contribution per offset).
  5. Pick overlap on the latest working-panel date.

Usage: python final/src/reweight/backtest_reweight.py [--stage A|B|picks|all]
Output: final/out/reweight/backtest_reweight_{A,B,picks}.json
"""
import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.path.insert(0, str(SRC / "audit"))
import model_audit_wo23 as MA            # noqa: E402

V, SI, ICW, DR, C = MA.V, MA.SI, MA.ICW, MA.DR, MA.C
ROOT = HERE.parents[1]
OUT = ROOT / "out" / "reweight"
WJ = json.loads((OUT / "icw9_v2_weights.json").read_text())
AUD = {p: json.loads((ROOT / "out" / "audit" / f"model_audit_wo23_{p}.json").read_text())["theoretical"]
       for p in ("A", "B")}

FT, SIGNS, SI_COL = MA.FT, MA.SIGNS_T, "short_interest_days_to_cover"
NON_SI = [k for k in FT if k != SI_COL]
W_LIVE = dict(ICW.PRODUCTION_WEIGHTS_V9_SEAS)
W_V2 = WJ["icw9_v2_4dp"]
W_V2_FULL = WJ["icw9_v2_full_precision"]
W_V2_FLOOR = WJ["icw9_v2_si_floor_4dp"]
T_SI_B = WJ["t_used"][SI_COL]
LABEL = MA.LABEL
log = MA.log


def summ(r, off):
    keys = ("excess_cagr_vs_spy_mean40", "sd40", "min40", "max40", "offsets_positive",
            "loyo_min", "loyo_min_dropped_year", "post2011_10", "yearly_excess_ann")
    out = {k: r[k] for k in keys if k in r}
    out["per_offset"] = [float(x) for x in off]
    return out


def diff(a_off, b_off):
    d = np.asarray(a_off) - np.asarray(b_off)
    return {"mean40": float(d.mean()), "sd40": float(d.std()), "offsets_positive": int((d > 0).sum())}


def half_book(book, score, all_dates, spy, keep_years):
    """Book on the full A grid, with picks only on dates in keep_years (the test half)."""
    pk = book.picks(score)
    pk = {d: v for d, v in pk.items() if d.year % 2 in keep_years}
    r = DR.backtest(pk, all_dates, spy)
    per_off, _ = MA.backtest_detail(pk, all_dates, spy)
    return r, per_off


def stage_A():
    t0 = time.time()
    U, all_dates, spy = MA.load_theo("A", "cap150")
    # 0. t reproduction (8 non-SI factors) + halves from the SAME daily IC series
    t_full, t_odd, t_even, rep = {}, {}, {}, {}
    for k in FT:
        s = SI.daily_corr(U, k, LABEL)
        yrs = s.index.year
        t_full[k] = V.nw(s.to_numpy())["t"]
        t_odd[k] = V.nw(s[yrs % 2 == 1].to_numpy())["t"]
        t_even[k] = V.nw(s[yrs % 2 == 0].to_numpy())["t"]
        ref = AUD["A"]["factors"][k]["t"]
        if k in NON_SI:
            rep[k] = {"got": t_full[k], "wo23": ref, "abs_diff": abs(t_full[k] - ref)}
            assert abs(t_full[k] - ref) < 1e-6, f"t REPRODUCTION FAIL {k}: {t_full[k]} vs {ref}"
        log(f"[A] {k:32s} t full {t_full[k]:+.6f} odd {t_odd[k]:+.4f} even {t_even[k]:+.4f}")
    log("[A] t reproduction PASS (8 non-SI factors, 1e-6)")
    w_recomp = SI.fit_weights({**{k: t_full[k] for k in NON_SI}, SI_COL: T_SI_B}, SIGNS)
    assert all(abs(w_recomp[k] - W_V2_FULL[k]) < 1e-9 for k in FT)
    # split-half weights: 8 non-SI from the half; SI at its B-fit t (no effect in A)
    w_odd = SI.fit_weights({**{k: t_odd[k] for k in NON_SI}, SI_COL: T_SI_B}, SIGNS)
    w_even = SI.fit_weights({**{k: t_even[k] for k in NON_SI}, SI_COL: T_SI_B}, SIGNS)

    V.add_ranks(U, FT)
    assert U["rz_" + SI_COL].notna().sum() == 0, "SI has coverage in A?"
    book = V.Book(U, all_dates, spy)
    res = {"rows": int(len(U)), "dates": len(all_dates), "t_reproduction": rep,
           "t_full": t_full, "t_odd": t_odd, "t_even": t_even,
           "weights_split_odd_fit": w_odd, "weights_split_even_fit": w_even}
    live, live_off = MA.run_book(book, SI.composite_score(U, W_LIVE).to_numpy(), all_dates, spy, True)
    ref = AUD["A"]["icw9_seas"]["excess_cagr_vs_spy_mean40"]
    assert abs(live["excess_cagr_vs_spy_mean40"] - ref) < 1e-9, (live["excess_cagr_vs_spy_mean40"], ref)
    res["reconcile_live_vs_wo23"] = [live["excess_cagr_vs_spy_mean40"], ref]
    log(f"[A] RECONCILE OK live icw9_seas {ref:+.10f}")
    v2, v2_off = MA.run_book(book, SI.composite_score(U, W_V2).to_numpy(), all_dates, spy, True)
    v2f, v2f_off = MA.run_book(book, SI.composite_score(U, W_V2_FULL).to_numpy(), all_dates, spy, True)
    fl, fl_off = MA.run_book(book, SI.composite_score(U, W_V2_FLOOR).to_numpy(), all_dates, spy, True)
    # SI no-op check in A: icw9_v2 and SI-at-floor give identical books (up to 4dp rounding of the 8)
    res["si_noop_check_v2_minus_floor"] = diff(v2_off, fl_off)
    res["live_icw9_seas"], res["icw9_v2"] = summ(live, live_off), summ(v2, v2_off)
    res["icw9_v2_full_precision"] = summ(v2f, v2f_off)
    res["icw9_v2_minus_live"] = diff(v2_off, live_off)
    log(f"[A] live {live['excess_cagr_vs_spy_mean40']:+.5f} icw9_v2 {v2['excess_cagr_vs_spy_mean40']:+.5f} "
        f"(full prec {v2f['excess_cagr_vs_spy_mean40']:+.5f}); SI no-op diff {res['si_noop_check_v2_minus_floor']['mean40']:+.2e}")
    # split-half OOS
    odd_mask = (U["date"].dt.year % 2 == 1).to_numpy()
    stitched = V.oos_score(U, (w_odd, w_even), pd.Series(odd_mask, index=U.index))
    oos, oos_off = MA.run_book(book, stitched.to_numpy(), all_dates, spy, True)
    res["icw9_v2_splithalf_oos_stitched"] = summ(oos, oos_off)
    h_even, h_even_off = half_book(book, SI.composite_score(U, w_odd).to_numpy(), all_dates, spy, {0})
    h_odd, h_odd_off = half_book(book, SI.composite_score(U, w_even).to_numpy(), all_dates, spy, {1})
    res["splithalf_fit_odd_test_even"] = summ(h_even, h_even_off)
    res["splithalf_fit_even_test_odd"] = summ(h_odd, h_odd_off)
    # in-sample comparators on the same restricted halves (context)
    for nm, w in (("live", W_LIVE), ("icw9_v2", W_V2)):
        sc = SI.composite_score(U, w).to_numpy()
        a, ao = half_book(book, sc, all_dates, spy, {0})
        b, bo = half_book(book, sc, all_dates, spy, {1})
        res[f"{nm}_restricted_even_years"] = summ(a, ao)
        res[f"{nm}_restricted_odd_years"] = summ(b, bo)
    log(f"[A] split-half OOS stitched {oos['excess_cagr_vs_spy_mean40']:+.5f} (sd40 {oos['sd40']:.5f}); "
        f"fit-odd/test-even {h_even['excess_cagr_vs_spy_mean40']:+.5f}; fit-even/test-odd "
        f"{h_odd['excess_cagr_vs_spy_mean40']:+.5f} ({time.time()-t0:.0f}s)")
    return res


def stage_B():
    t0 = time.time()
    U, all_dates, spy = MA.load_theo("B", "cap150")
    s = SI.daily_corr(U, SI_COL, LABEL)
    t_si = V.nw(s.to_numpy())["t"]
    ref = AUD["B"]["factors"][SI_COL]["t"]
    assert abs(t_si - ref) < 1e-6, f"SI t REPRODUCTION FAIL {t_si} vs {ref}"
    assert abs(t_si - T_SI_B) < 1e-12
    log(f"[B] SI t {t_si:+.8f} == WO-23 {ref:+.8f} PASS")
    V.add_ranks(U, FT)
    book = V.Book(U, all_dates, spy)
    res = {"rows": int(len(U)), "dates": len(all_dates), "si_t_reproduction": {"got": t_si, "wo23": ref}}
    runs = {}
    for nm, w in (("live_icw9_seas", W_LIVE), ("icw9_v2", W_V2), ("icw9_v2_full_precision", W_V2_FULL),
                  ("icw9_v2_si_floor", W_V2_FLOOR)):
        r, off = MA.run_book(book, SI.composite_score(U, w).to_numpy(), all_dates, spy, False)
        runs[nm] = off
        res[nm] = summ(r, off)
        log(f"[B] {nm:24s} {r['excess_cagr_vs_spy_mean40']:+.5f} sd40 {r['sd40']:.5f} "
            f"pos {r['offsets_positive']}/40 LOYO min {r['loyo_min']:+.5f} ({r['loyo_min_dropped_year']})")
    refB = AUD["B"]["icw9_seas"]["excess_cagr_vs_spy_mean40"]
    assert abs(res["live_icw9_seas"]["excess_cagr_vs_spy_mean40"] - refB) < 1e-9
    res["reconcile_live_vs_wo23"] = [res["live_icw9_seas"]["excess_cagr_vs_spy_mean40"], refB]
    log("[B] RECONCILE OK")
    res["icw9_v2_minus_live"] = diff(runs["icw9_v2"], runs["live_icw9_seas"])
    res["si_fit_contribution_v2_minus_floor"] = diff(runs["icw9_v2"], runs["icw9_v2_si_floor"])
    res["floor_minus_live"] = diff(runs["icw9_v2_si_floor"], runs["live_icw9_seas"])
    res["runtime_s"] = time.time() - t0
    return res


def stage_picks():
    spec = importlib.util.spec_from_file_location("csc_wo25", SRC / "current_signal_composite.py")
    CSC = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CSC)
    needed = list(dict.fromkeys(["ticker", "date", "sector", "close", "market_cap", "volatility_60",
                                 f"eligible_{CSC.TIER}"] + C.FACTOR_COLS))
    df_date, _ = CSC.W.working_cross_section(needed, path=CSC.PANEL)
    as_of = df_date["date"].max()
    elig = df_date[df_date[f"eligible_{CSC.TIER}"]].reset_index(drop=True).copy()
    sf, seas_info = CSC.SL.seas_asof(elig["ticker"], as_of)
    assert (sf["ticker"].to_numpy() == elig["ticker"].astype(str).to_numpy()).all()
    elig["seas"] = sf["seas"].to_numpy(np.float64)
    picks = {}
    for nm, w in (("live_icw9_seas", W_LIVE), ("icw9_v2", W_V2), ("icw9_v2_si_floor", W_V2_FLOOR)):
        picks[nm] = dict(C.pick_decile_volq(elig, ICW.compute_composite_ic_weighted(elig, weights=w)))
    a = picks["live_icw9_seas"]

    def ov(b):
        sh = set(a) & set(b)
        return {"n_live": len(a), "n_other": len(b), "shared": len(sh),
                "share_of_live": round(len(sh) / max(len(a), 1), 4),
                "weight_overlap": round(float(sum(min(a[t], b[t]) for t in sh)), 4)}
    res = {"as_of": str(pd.Timestamp(as_of).date()), "n_eligible": int(len(elig)),
           "seas_coverage": seas_info["coverage"], "si_coverage": float(elig[SI_COL].notna().mean()),
           "icw9_v2_vs_live": ov(picks["icw9_v2"]), "icw9_v2_si_floor_vs_live": ov(picks["icw9_v2_si_floor"])}
    meta_p = CSC.OUT_META
    try:
        meta = json.loads(meta_p.read_text())
        m_asof = meta.get("as_of") or meta.get("as_of_date") or meta.get("date")
        m_ver = meta.get("model_version")
    except Exception as e:  # noqa: BLE001
        m_asof, m_ver = None, f"unreadable: {e}"
    res["main_checkout_meta"] = {"as_of": m_asof, "model_version": m_ver,
                                 "factor_weights": meta.get("factor_weights") if isinstance(meta, dict) else None}
    if m_asof == res["as_of"] and meta.get("factor_weights") == W_LIVE:
        live_csv = pd.read_csv(CSC.OUT_CSV)
        res["live_csv_match"] = bool(set(live_csv["ticker"].astype(str)) == set(a))
    elif m_asof == res["as_of"] and meta.get("factor_weights") == dict(ICW.PRODUCTION_WEIGHTS):
        # main checkout still serves icw8 (WO-20-seas not deployed): check the replication on icw8
        p8 = dict(C.pick_decile_volq(elig, ICW.compute_composite_ic_weighted(elig, weights=ICW.PRODUCTION_WEIGHTS)))
        live_csv = pd.read_csv(CSC.OUT_CSV)
        res["live_csv_match"] = {"main_checkout_serves": "icw8 PRODUCTION_WEIGHTS",
                                 "replicated_icw8_picks_equal_csv": bool(set(live_csv["ticker"].astype(str)) == set(p8)),
                                 "icw9_v2_vs_icw8_shared": len(set(p8) & set(picks["icw9_v2"]))}
    else:
        res["live_csv_match"] = "not compared: main-checkout meta as_of/weights differ (file in flux)"
    log(f"[picks] {res}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["A", "B", "picks", "all"])
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    fns = {"A": stage_A, "B": stage_B, "picks": stage_picks}
    for st in (["A", "B", "picks"] if a.stage == "all" else [a.stage]):
        r = fns[st]()
        r["prereg"] = "final/models/2026-09-29-icw-v2-reweight.md @ 0aa87b4"
        (OUT / f"backtest_reweight_{st}.json").write_text(json.dumps(r, indent=1, default=float))
        log(f"wrote backtest_reweight_{st}.json")


if __name__ == "__main__":
    main()
