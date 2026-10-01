"""
WO-42 S3: unfitted 2020+ read of the frozen EAR factor. HOLD-OUT READ #19
(Gabe's standing 2026-09-27 OK for unfitted 2020-26 reads).
Pre-registration: final/models/2026-10-01-stabilizer-rule-ear.md (3c6a321),
committed before any 2020+ EAR value was computed.

No fitting: every weight is a constant frozen from 2007-2019.
  without = icw9_seas, ic_weighted_composite.PRODUCTION_WEIGHTS_V9_SEAS (live)
  with    = icw10_ear, frozen rule on the 8 full-era t's + seas t + EAR's
            in-era pooled t (3.2572), 4dp, written in the pre-registration
Loader/books: audit/model_audit_wo23.load_theo and insider/screen_insider_v2grid
(imported, never edited). EAR comes from build_ear_ext.py, whose pre-2020 rows
are asserted identical to WO-29's frozen factor.

Period A (2007-2019) runs first as the reconcile: EAR pooled IC t must equal
the screen's, frozen icw9_seas must equal WO-23. Then period B
(2020-01-02..2026-07-30): base must equal the WO-31/WO-40 value, then the
S3 gate and the descriptive books.
Output: final/out/stabilizer/s3_ear_holdout.json
"""
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.path.insert(0, str(SRC / "audit"))
import model_audit_wo23 as A            # noqa: E402

V, SI, ICW, DR = A.V, A.SI, A.ICW, A.DR
LABEL, ANN = A.LABEL, A.ANN
COL = "ear"
WT = Path("/Users/ggraham/pipe_dream/.claude/worktrees")
A.SEAS_EXT = WT / "wo23-model-audit" / "final" / "out" / "audit" / "seas_factor_ext.parquet"
OUT = SRC.parent / "out" / "stabilizer"
EXT = OUT / "ear_factor_ext.parquet"
EXT_META = OUT / "build_ear_ext_meta.json"
REPORT = OUT / "s3_ear_holdout.json"
SCREEN = SRC.parent / "out" / "ear" / "ear_screen_report.json"
WO23_A = SRC.parent / "out" / "audit" / "model_audit_wo23_A.json"
REF_B_ICW9_SEAS = -0.020163649457176646          # WO-31 / WO-40 period B, current panel
T_BAR_S3 = 1.0

W9 = dict(ICW.PRODUCTION_WEIGHTS_V9_SEAS)
W10 = {"momentum_12_1": 0.0325, "pct_from_high_252": 0.0085, "volatility_60": -0.0085,
       "gross_profitability": 0.3886, "accruals": -0.1062, "net_issuance_pct": -0.0913,
       "days_to_next_filing_seasonal": -0.0085, "short_interest_days_to_cover": -0.0085,
       "seas": 0.1558, "ear": 0.1916}
log = V.log


def dump(rep):
    REPORT.write_text(json.dumps(rep, indent=1, default=float))


def weight_rule_check():
    t8 = {k: v["t"] for k, v in A._T_FULL.items()}
    ear_t = json.loads(SCREEN.read_text())["ic"]["pooled"]["t"]
    w = SI.fit_weights({**t8, "seas": ICW.SEAS_T, COL: ear_t}, {**V.SIGNS8, "seas": +1, COL: +1})
    r = {k: round(v, 4) for k, v in w.items()}
    assert r == W10, f"WEIGHT RULE FAIL icw10_ear {r}"
    log("frozen weight rule reproduces the pre-registered icw10_ear dict to 4dp")
    return {"ear_t_in_era": ear_t, "seas_t": ICW.SEAS_T, "icw10_ear": W10, "icw9_seas": W9, "pass": True}


def load_period(per, ext):
    U, all_dates, spy = A.load_theo(per, "cap150")
    lo, hi = A.PERIODS[per]
    f = ext[(ext["date"] >= lo) & (ext["date"] <= hi)]
    kt, kd = U["ticker"].to_numpy().copy(), U["date"].to_numpy().copy()
    n = len(U)
    U = U.merge(f, on=["ticker", "date"], how="left")
    assert len(U) == n and (U["ticker"].to_numpy() == kt).all() and (U["date"].to_numpy() == kd).all(), "merge changed rows"
    # signed rank over live rows of this universe, everything else neutral 0 (WO-29 definition)
    U["ear_live"] = SI.rank_z(U, "ear_raw")
    U[COL] = U["ear_live"].fillna(0.0)
    V.add_ranks(U, A.FT)
    U[f"rz_{COL}"] = U[COL]                 # never re-ranked
    return U, all_dates, spy, V.Book(U, all_dates, spy)


def offset_series(pk, all_dates, spy):
    out = []
    for off in range(40):
        prev, recs = set(), []
        for tp in all_dates[off::40]:
            if tp not in pk:
                continue
            gross, cur = pk[tp]
            f_new = sum(1 for t in cur if t not in prev) / len(cur)
            prev = cur
            recs.append({"date": tp, "gross": gross, "f_new": f_new, "spy": spy.get(tp, np.nan), "n": len(cur)})
        net = DR.RB.turnover_net_return(recs, DR.COST_BPS)
        s = np.array([r["spy"] for r in recs], dtype=np.float64); ok = np.isfinite(s)
        gross = np.array([r["gross"] for r in recs]); f = np.array([r["f_new"] for r in recs])
        out.append({"dates": pd.DatetimeIndex(np.array([r["date"] for r in recs])[ok]), "ex": (net - s)[ok],
                    "cost": (gross - net)[ok], "f_new": f[ok], "n": np.array([r["n"] for r in recs])[ok]})
    return out


def book_run(book, weights, U, all_dates, spy):
    pk = book.picks(SI.composite_score(U, weights).to_numpy())
    r = DR.backtest(pk, all_dates, spy)
    ser = offset_series(pk, all_dates, spy)
    per_off = np.array([o["ex"].mean() * ANN for o in ser])
    assert abs(per_off.mean() - r["excess_cagr_vs_spy_mean40"]) < 1e-12
    r["per_offset"] = per_off.tolist()
    r["turnover_mean_f_new"] = float(np.mean([o["f_new"].mean() for o in ser]))
    r["turnover_mean_f_new_ex_first_window"] = float(np.mean([o["f_new"][1:].mean() for o in ser if len(o["f_new"]) > 1]))
    r["cost_drag_ann_15bp"] = float(np.mean([o["cost"].mean() * ANN for o in ser]))
    r["mean_names_held"] = float(np.mean([o["n"].mean() for o in ser]))
    return r, ser


def paired(sa, sb):
    diff, yrs = [], []
    for a, b in zip(sa, sb):
        assert a["dates"].equals(b["dates"]), "paired books have different window dates"
        diff.append(a["ex"] - b["ex"]); yrs.append(a["dates"].year.to_numpy())
    per_off = np.array([d.mean() * ANN for d in diff])
    years = sorted(set(np.concatenate(yrs).tolist()))
    per_year = {int(y): float(np.mean([d[yy == y].mean() * ANN for d, yy in zip(diff, yrs) if (yy == y).any()])) for y in years}
    return {"mean40": float(per_off.mean()), "sd40": float(per_off.std()), "offsets_positive": int((per_off > 0).sum()),
            "min40": float(per_off.min()), "max40": float(per_off.max()), "per_year": per_year,
            "per_offset": per_off.tolist()}


def ic_block(U):
    ic, _ = V.ic_gates(U, xcol=COL)
    s = SI.daily_corr(U, COL, LABEL)
    live = U.loc[U["ear_live"].notna(), ["date", "ear_live", LABEL]]
    return {"pooled": ic["pooled"], "sector_both_sides": ic["sector_both_sides"],
            "sector_factor_only": ic["sector_factor_only"], "offset_sign_flips": ic["offsets"]["sign_flips"],
            "year_share": ic["year_share"],
            "per_year": {int(y): float(v) for y, v in s.groupby(s.index.year).mean().items()},
            "per_year_n_dates": {int(y): int(v) for y, v in s.groupby(s.index.year).size().items()},
            "live_rows_only": V.nw(SI.daily_corr(live, "ear_live", LABEL).to_numpy()),
            "live_share": float(U["ear_live"].notna().mean()),
            "live_share_by_year": {int(k): float(v) for k, v in U["ear_live"].notna().groupby(U["date"].dt.year).mean().items()}}


KEEP = ("excess_cagr_vs_spy_mean40", "sd40", "min40", "max40", "offsets_positive", "loyo_min", "loyo_min_dropped_year",
        "turnover_mean_f_new", "turnover_mean_f_new_ex_first_window", "cost_drag_ann_15bp", "mean_names_held", "per_offset")


def main():
    t0 = time.time()
    meta = json.loads(EXT_META.read_text())
    assert meta["identity_pre2020"]["pass"], "extended EAR build did not pass the pre-2020 identity"
    h = hashlib.sha256()
    with open(EXT, "rb") as fh:
        while b := fh.read(1 << 24):
            h.update(b)
    assert h.hexdigest() == meta["ext_sha256"], "ext parquet changed since the identity build"
    rep = {"prereg": "final/models/2026-10-01-stabilizer-rule-ear.md @ 3c6a321", "holdout_read": 19,
           "unfitted": True, "ext_sha256": meta["ext_sha256"], "weight_rule_check": weight_rule_check()}
    ext = pd.read_parquet(EXT, columns=["ticker", "date", "ear_raw"])
    ext["date"] = pd.to_datetime(ext["date"]); ext["ticker"] = ext["ticker"].astype(str)
    screen = json.loads(SCREEN.read_text())
    ref_a = json.loads(WO23_A.read_text())["theoretical"]["icw9_seas"]["excess_cagr_vs_spy_mean40"]
    res = {}
    for per in ("A", "B"):
        tp = time.time()
        U, all_dates, spy, book = load_period(per, ext)
        r = {"rows": int(len(U)), "tickers": int(U["ticker"].nunique()), "dates": len(all_dates),
             "first": str(pd.Timestamp(all_dates[0]).date()), "last": str(pd.Timestamp(all_dates[-1]).date())}
        # ---- reconcile the base BEFORE any EAR outcome number of this period
        b9, s9 = book_run(book, W9, U, all_dates, spy)
        want = ref_a if per == "A" else REF_B_ICW9_SEAS
        got = b9["excess_cagr_vs_spy_mean40"]
        assert abs(got - want) < 1e-6, f"BASE RECONCILE FAIL [{per}] icw9_seas {got} vs {want}"
        r["reconcile_base_icw9_seas"] = [got, want]
        log(f"[{per}] base icw9_seas frozen reconcile OK {got:+.7f} == {want:+.7f}")
        ic = ic_block(U)
        if per == "A":
            g, w = ic["pooled"]["t"], screen["ic"]["pooled"]["t"]
            assert abs(g - w) < 1e-6, f"IN-ERA IC RECONCILE FAIL t {g} vs {w}"
            assert abs(ic["pooled"]["mean"] - screen["ic"]["pooled"]["mean"]) < 1e-9
            r["reconcile_screen_ic_t"] = [g, w]
            log(f"[A] in-era EAR IC t reproduces the screen ({g:+.6f})")
        r["ic"] = ic
        log(f"[{per}] EAR IC {ic['pooled']['mean']:+.5f} NW t {ic['pooled']['t']:+.3f} n {ic['pooled']['n_dates']} | "
            f"sector both {ic['sector_both_sides']['t']:+.2f} | live-only t {ic['live_rows_only']['t']:+.2f}")
        b10, s10 = book_run(book, W10, U, all_dates, spy)
        r["books"] = {"icw9_seas_without": {k: b9[k] for k in KEEP}, "icw10_ear_with": {k: b10[k] for k in KEEP}}
        r["increment_with_minus_without"] = paired(s10, s9)
        v = r["increment_with_minus_without"]
        log(f"[{per}] without {b9['excess_cagr_vs_spy_mean40']:+.5f} sd40 {b9['sd40']:.5f} min {b9['min40']:+.5f} | "
            f"with {b10['excess_cagr_vs_spy_mean40']:+.5f} sd40 {b10['sd40']:.5f} min {b10['min40']:+.5f} | "
            f"inc {v['mean40']:+.5f} offsets>0 {v['offsets_positive']}/40")
        r["runtime_s"] = time.time() - tp
        res[per] = r
        rep["periods"] = res
        dump(rep)
        del U, book
    icB = res["B"]["ic"]["pooled"]
    rep["S3"] = {"period": "2020-01-02..2026-07-30", "ic_mean": icB["mean"], "nw39_t": icB["t"], "n_dates": icB["n_dates"],
                 "bar": "mean IC > 0 and t >= +1.0", "pass": bool(icB["mean"] > 0 and icB["t"] >= T_BAR_S3)}
    log(f"S3 {rep['S3']}")
    rep["runtime_s"] = time.time() - t0
    dump(rep)
    log(f"wrote {REPORT} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    main()
