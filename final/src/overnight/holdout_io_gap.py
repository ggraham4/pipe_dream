"""
WO-26-io (COO): unfitted 2020+ hold-out read of the frozen `io_gap` factor.
Hold-out read #9 (Gabe's standing 2026-09-27 OK for unfitted 2020-26 reads).
Pre-registration: final/models/2026-09-29-io-gap-holdout-read.md (committed
and pushed before any 2020+ io_gap value was computed).

The frozen builder build_io_gap.py is imported, never edited, and its main()
is never called (it would overwrite frozen outputs). This wrapper reuses its
functions and changes only the module bounds LAST_YM / HOLDOUT at run time.
The theoretical loader is WO-23's model_audit_wo23.load_theo (imported).

Stages
  --stage identity   panel/SEP hashes; wrapper(frozen bounds) == frozen parquet;
                     extended build (SEP 2005-01..2026-07) == frozen parquet on
                     every row <= 2019-12-31; writes io_gap_factor_ext.parquet.
                     No label-joined number is computed.
  --stage read       weight-rule check, WO-23 reconcile (A and B) and in-era
                     IC reconcile, then PRIMARY and SECONDARY.
Output: final/out/overnight/io_gap_holdout_report.json
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
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SRC / "audit"))
import build_io_gap as B                 # noqa: E402  (frozen builder, functions only)
import model_audit_wo23 as A             # noqa: E402  (WO-23 loaders/books; sets V for seas)

V, SI, ICW, DR, C = A.V, A.SI, A.ICW, A.DR, A.C
LABEL = A.LABEL
ANN = A.ANN
COL = "io_gap"
LEGS = ["io_intraday", "io_overnight"]
FACTOR_COLS = [COL] + LEGS

WT = Path("/Users/ggraham/pipe_dream/.claude/worktrees")
FROZEN = WT / "overnight-intraday" / "final" / "out" / "overnight" / "io_gap_factor_v2.parquet"
FROZEN_META = WT / "overnight-intraday" / "final" / "out" / "overnight" / "build_io_gap_meta.json"
A.SEAS_EXT = WT / "wo23-model-audit" / "final" / "out" / "audit" / "seas_factor_ext.parquet"
OUT = SRC.parent / "out" / "overnight"
EXT = OUT / "io_gap_factor_ext.parquet"
REPORT = OUT / "io_gap_holdout_report.json"
SCREEN = OUT / "io_gap_screen_report.json"
AUDIT = SRC.parent / "out" / "audit"
WO23 = {"A": AUDIT / "model_audit_wo23_A.json", "B": AUDIT / "model_audit_wo23_B.json"}

FROZEN_HI = pd.Timestamp("2019-12-31")
EXT_LAST_YM, EXT_HI = "2026-07", pd.Timestamp("2026-07-30")
TOL = 1e-12

FC8 = list(ICW.PRODUCTION_WEIGHTS)
SIGNS8 = {k: C.FACTOR_SIGNS[k] for k in FC8}
W8 = dict(ICW.PRODUCTION_WEIGHTS)
W9 = dict(ICW.PRODUCTION_WEIGHTS_V9_SEAS)
# frozen before the read (WO-26-io work order; from 2007-2019 t's only)
W10 = {"momentum_12_1": 0.0305, "pct_from_high_252": 0.0080, "volatility_60": -0.0080,
       "gross_profitability": 0.3657, "accruals": -0.0999, "net_issuance_pct": -0.0859,
       "days_to_next_filing_seasonal": -0.0080, "short_interest_days_to_cover": -0.0080,
       "seas": 0.1467, "io_gap": 0.2393}
W9IO = {"momentum_12_1": 0.0358, "pct_from_high_252": 0.0094, "volatility_60": -0.0094,
        "gross_profitability": 0.4286, "accruals": -0.1171, "net_issuance_pct": -0.1006,
        "days_to_next_filing_seasonal": -0.0094, "short_interest_days_to_cover": -0.0094,
        "io_gap": 0.2804}
log = V.log


def dump(rep):
    REPORT.write_text(json.dumps(rep, indent=1, default=float))


def load_report():
    return json.loads(REPORT.read_text()) if REPORT.exists() else {}


# ------------------------------------------------------------------ identity
def build(last_ym, q_hi):
    """build_io_gap.main()'s factor steps with LAST_YM/HOLDOUT moved; nothing written."""
    B.LAST_YM = last_ym
    B.HOLDOUT = (pd.Period(last_ym, "M") + 1).to_timestamp()
    files = B.sep_files()
    s = B.load_sep(files)
    s, _ = B.daily_components(s)
    cal = B.market_calendar(s)
    q = pd.read_parquet(B.PANEL_V2, columns=["ticker", "date"],
                        filters=[("date", ">=", str(B.START.date())), ("date", "<=", str(q_hi.date()))])
    q["date"] = pd.to_datetime(q["date"]); q["ticker"] = q["ticker"].astype(str)
    assert q["date"].max() <= q_hi
    q = q.drop_duplicates(["ticker", "date"]).reset_index(drop=True)
    v, nv, first_used, last_used, vid = B.io_gap_for(s[["ticker", "date", "r_id", "r_on", "valid"]], cal, q)
    q[COL] = v; q["io_nvalid"] = nv
    q["io_intraday"] = vid; q["io_overnight"] = vid - v
    fin = np.isfinite(v)
    assert (last_used[fin] <= q["date"].to_numpy()[fin]).all(), "PIT FAIL: price after t"
    info = {"sep_files": f"{files[0].stem}..{files[-1].stem}", "sep_rows": int(len(s)),
            "market_calendar_days": int(len(cal)), "rows": int(len(q)), "pit_rows_checked": int(fin.sum()),
            "window_first_price_min": str(pd.Timestamp(first_used[fin].min()).date())}
    del s
    return q, info


def compare(got, ref, tag):
    """got/ref frames keyed by (ticker, date); every row of ref must match."""
    a = ref.merge(got, on=["ticker", "date"], how="left", suffixes=("_ref", "_got"), indicator=True)
    assert (a["_merge"] == "both").all(), f"{tag}: {int((a['_merge'] != 'both').sum())} frozen rows missing"
    assert len(a) == len(ref)
    out = {"rows": int(len(a))}
    for c in FACTOR_COLS:
        x, y = a[f"{c}_got"].to_numpy(np.float64), a[f"{c}_ref"].to_numpy(np.float64)
        nan_same = np.isnan(x) == np.isnan(y)
        assert nan_same.all(), f"{tag} {c}: NaN pattern differs on {int((~nan_same).sum())} rows"
        d = np.abs(x - y)[~np.isnan(y)]
        mx = float(d.max()) if len(d) else 0.0
        assert mx <= TOL, f"IDENTITY FAIL {tag} {c}: max abs diff {mx}"
        out[f"{c}_max_abs_diff"] = mx; out[f"{c}_finite"] = int((~np.isnan(y)).sum())
    assert (a["io_nvalid_got"].to_numpy() == a["io_nvalid_ref"].to_numpy()).all(), f"{tag} io_nvalid differs"
    out["io_nvalid_exact"] = True
    return out


def stage_identity():
    t0 = time.time()
    rep = load_report()
    meta = json.loads(FROZEN_META.read_text())
    ide = {"frozen_parquet": str(FROZEN)}
    ide["panel_sha256"] = B.sha256(B.PANEL_V2)
    assert ide["panel_sha256"] == meta["composite_panel_v2_sha256"], "panel changed since the frozen build"
    B.LAST_YM = "2019-12"
    ide["sep_digest_2005_2019"] = B.files_digest(B.sep_files())
    assert ide["sep_digest_2005_2019"] == meta["sep_digest"], "SEP 2005-01..2019-12 changed since the frozen build"
    log(f"hashes OK: panel {ide['panel_sha256'][:16]} sep {ide['sep_digest_2005_2019'][:16]}")
    ref = pd.read_parquet(FROZEN, columns=["ticker", "date", "io_nvalid"] + FACTOR_COLS)
    ref["date"] = pd.to_datetime(ref["date"]); ref["ticker"] = ref["ticker"].astype(str)
    assert ref["date"].max() <= FROZEN_HI and len(ref) == meta["factor_rows"]

    q, info = build("2019-12", FROZEN_HI)
    assert info["market_calendar_days"] == meta["market_calendar_days"]
    assert info["pit_rows_checked"] == meta["pit_rows_checked"]
    ide["frozen_bounds_build"] = {**info, **compare(q, ref, "frozen-bounds")}
    log(f"identity 1 (frozen bounds) OK {ide['frozen_bounds_build']}")
    del q

    q, info = build(EXT_LAST_YM, EXT_HI)
    pre = q[q["date"] <= FROZEN_HI]
    ide["extended_build"] = {**info, "pre2020": compare(pre, ref, "extended-pre2020")}
    log(f"identity 2 (extended build, rows <= 2019-12-31) OK {ide['extended_build']['pre2020']}")
    ide["extended_build"]["rows_2020plus"] = int((q["date"] > FROZEN_HI).sum())
    q.to_parquet(EXT, index=False)
    ide["ext_parquet"] = str(EXT); ide["ext_sha256"] = B.sha256(EXT)
    ide["pass"] = True; ide["runtime_s"] = time.time() - t0
    rep["identity"] = ide
    dump(rep)
    log(f"wrote {EXT} ({len(q):,} rows) in {time.time()-t0:.0f}s")


# ------------------------------------------------------------------ read helpers
def weight_rule_check():
    t8 = {k: v["t"] for k, v in A._T_FULL.items()}
    io_t = json.loads(SCREEN.read_text())["ic"]["pooled"]["t"]
    w10 = SI.fit_weights({**t8, "seas": ICW.SEAS_T, COL: io_t}, {**SIGNS8, "seas": +1, COL: +1})
    w9io = SI.fit_weights({**t8, COL: io_t}, {**SIGNS8, COL: +1})
    r10 = {k: round(v, 4) for k, v in w10.items()}; r9 = {k: round(v, 4) for k, v in w9io.items()}
    assert r10 == W10, f"WEIGHT RULE FAIL icw10 {r10}"
    assert r9 == W9IO, f"WEIGHT RULE FAIL icw9_io {r9}"
    log("frozen weight rule reproduces the WO-26-io icw10 / icw9_io dicts to 4dp")
    return {"io_gap_t_in_era": io_t, "seas_t": ICW.SEAS_T, "icw10": W10, "icw9_io": W9IO, "pass": True}


def load_period(per, ext):
    U, all_dates, spy = A.load_theo(per, "cap150")
    lo, hi = A.PERIODS[per]
    f = ext[(ext["date"] >= lo) & (ext["date"] <= hi)]
    key_t, key_d = U["ticker"].to_numpy().copy(), U["date"].to_numpy().copy()
    n = len(U)
    U = U.merge(f, on=["ticker", "date"], how="left")
    assert len(U) == n and (U["ticker"].to_numpy() == key_t).all() and (U["date"].to_numpy() == key_d).all(), \
        "io_gap merge changed rows/order"
    V.add_ranks(U, A.FT + [COL])
    book = V.Book(U, all_dates, spy)
    return U, all_dates, spy, book


def offset_series(pk, all_dates, spy):
    """downcap_v2_readout.backtest's per-offset excess series (dates, excess)."""
    out = []
    for off in range(40):
        prev, recs = set(), []
        for tp in all_dates[off::40]:
            if tp not in pk:
                continue
            gross, cur = pk[tp]
            f_new = sum(1 for t in cur if t not in prev) / len(cur)
            prev = cur
            recs.append({"date": tp, "gross": gross, "f_new": f_new, "spy": spy.get(tp, np.nan)})
        net = DR.RB.turnover_net_return(recs, DR.COST_BPS)
        s = np.array([r["spy"] for r in recs], dtype=np.float64); ok = np.isfinite(s)
        d = np.array([r["date"] for r in recs])[ok]
        out.append((pd.DatetimeIndex(d), (net[ok] - s[ok])))
    return out


def book_run(book, weights, U, all_dates, spy):
    pk = book.picks(SI.composite_score(U, weights).to_numpy())
    r = DR.backtest(pk, all_dates, spy)
    ser = offset_series(pk, all_dates, spy)
    per_off = np.array([e.mean() * ANN for _, e in ser])
    assert abs(per_off.mean() - r["excess_cagr_vs_spy_mean40"]) < 1e-12
    return r, ser


def paired(ser_a, ser_b):
    diff, yrs = [], []
    for (da, ea), (db, eb) in zip(ser_a, ser_b):
        assert da.equals(db), "paired books have different window dates"
        diff.append(ea - eb); yrs.append(da.year.to_numpy())
    per_off = np.array([d.mean() * ANN for d in diff])
    years = sorted(set(np.concatenate(yrs).tolist()))
    loyo = {int(y): float(np.mean([d[yy != y].mean() * ANN for d, yy in zip(diff, yrs) if (yy != y).any()]))
            for y in years}
    per_year = {int(y): float(np.mean([d[yy == y].mean() * ANN for d, yy in zip(diff, yrs) if (yy == y).any()]))
                for y in years}
    ymin = min(loyo, key=loyo.get)
    return {"mean40": float(per_off.mean()), "sd40": float(per_off.std()),
            "offsets_positive": int((per_off > 0).sum()), "min40": float(per_off.min()), "max40": float(per_off.max()),
            "loyo_by_year": loyo, "loyo_min": loyo[ymin], "loyo_min_dropped_year": ymin,
            "per_year": per_year}


def resid_ic(U):
    x, m = U[f"rz_{COL}"], U["rz_momentum_12_1"]
    ok = x.notna() & m.notna()
    g = pd.DataFrame({"date": U["date"][ok], "x": x[ok], "m": m[ok]})
    gx = g.groupby("date")
    xc = g["x"] - gx["x"].transform("mean"); mc = g["m"] - gx["m"].transform("mean")
    beta = (xc * mc).groupby(g["date"]).transform("sum") / (mc * mc).groupby(g["date"]).transform("sum")
    res = pd.Series(np.nan, index=U.index); res[ok] = (xc - beta * mc).to_numpy()
    t = pd.DataFrame({"date": U["date"], "_r": res, LABEL: U[LABEL]})
    s = SI.daily_corr(t, "_r", LABEL)
    return {**V.nw(s.to_numpy()), "n_dates": int(len(s)),
            "median_beta": float(beta.groupby(g["date"]).first().median())}


def ic_block(U):
    ic, _ = V.ic_gates(U, xcol=COL)
    s = SI.daily_corr(U, COL, LABEL)
    out = {"pooled": ic["pooled"], "odd": ic["odd"], "even": ic["even"],
           "sector_both_sides": ic["sector_both_sides"], "sector_factor_only": ic["sector_factor_only"],
           "offset_sign_flips": ic["offsets"]["sign_flips"], "offsets_min": ic["offsets"]["min"],
           "offsets_max": ic["offsets"]["max"], "year_share": ic["year_share"], "loyo_t": ic["loyo_t"],
           "per_year": {int(y): float(v) for y, v in s.groupby(s.index.year).mean().items()},
           "per_year_n_dates": {int(y): int(v) for y, v in s.groupby(s.index.year).size().items()}}
    for leg in LEGS:
        sl = SI.daily_corr(U, leg, LABEL)
        out[f"leg_{leg}"] = {**V.nw(sl.to_numpy()), "n_dates": int(len(sl))}
    out["resid_on_momentum_12_1"] = resid_ic(U)
    out["median_spearman_vs_momentum_12_1"] = float(SI.daily_corr(U, COL, "momentum_12_1").median())
    out["coverage_by_year"] = A.coverage_by_year(U, COL)
    return out


def verdict(ic):
    m, t = ic["pooled"]["mean"], ic["pooled"]["t"]
    if t <= 0:
        return "KILL"
    if m > 0 and t >= 1.0:
        return "SUCCESS"
    return "MIDDLE"


def stage_read():
    t0 = time.time()
    rep = load_report()
    assert rep.get("identity", {}).get("pass"), "run --stage identity first"
    assert B.sha256(EXT) == rep["identity"]["ext_sha256"], "ext parquet changed since identity stage"
    rep["prereg"] = "final/models/2026-09-29-io-gap-holdout-read.md"
    rep["holdout_read"] = 9
    rep["weight_rule_check"] = weight_rule_check()
    ext = pd.read_parquet(EXT, columns=["ticker", "date"] + FACTOR_COLS)
    ext["date"] = pd.to_datetime(ext["date"]); ext["ticker"] = ext["ticker"].astype(str)
    screen = json.loads(SCREEN.read_text())
    res = {}
    for per in ("A", "B"):
        tp = time.time()
        U, all_dates, spy, book = load_period(per, ext)
        ref = json.loads(WO23[per].read_text())["theoretical"]
        r = {"rows": int(len(U)), "tickers": int(U["ticker"].nunique()), "dates": len(all_dates),
             "first": str(pd.Timestamp(all_dates[0]).date()), "last": str(pd.Timestamp(all_dates[-1]).date())}
        # ---- reconcile BEFORE any io_gap outcome number
        b8, s8 = book_run(book, W8, U, all_dates, spy)
        b9, s9 = book_run(book, W9, U, all_dates, spy)
        rec = {"icw8": [b8["excess_cagr_vs_spy_mean40"], ref["icw8"]["excess_cagr_vs_spy_mean40"]],
               "icw9_seas": [b9["excess_cagr_vs_spy_mean40"], ref["icw9_seas"]["excess_cagr_vs_spy_mean40"]]}
        for k, (g, w) in rec.items():
            assert abs(g - w) < 1e-6, f"WO-23 RECONCILE FAIL [{per}] {k} {g} vs {w}"
        r["reconcile_wo23"] = rec
        log(f"[{per}] WO-23 reconcile OK {rec}")
        ic = ic_block(U)
        if per == "A":
            g, w = ic["pooled"]["t"], screen["ic"]["pooled"]["t"]
            assert abs(g - w) < 1e-6, f"IN-ERA IC RECONCILE FAIL t {g} vs {w}"
            r["reconcile_screen_ic_t"] = [g, w]
            log(f"[A] in-era io_gap IC t reproduces the screen ({g:+.6f})")
        r["ic"] = ic
        log(f"[{per}] io_gap IC {ic['pooled']['mean']:+.5f} NW t {ic['pooled']['t']:+.3f} n {ic['pooled']['n_dates']} | "
            f"sector both {ic['sector_both_sides']['t']:+.2f} | resid-mom t {ic['resid_on_momentum_12_1']['t']:+.2f} | "
            f"legs intra t {ic['leg_io_intraday']['t']:+.2f} over t {ic['leg_io_overnight']['t']:+.2f}")
        b10, s10 = book_run(book, W10, U, all_dates, spy)
        b9io, s9io = book_run(book, W9IO, U, all_dates, spy)
        r["books"] = {"icw10": b10, "icw9_seas": b9, "icw9_io": b9io, "icw8": b8}
        r["paired"] = {"icw10_minus_icw9_seas": paired(s10, s9), "icw9_io_minus_icw8": paired(s9io, s8)}
        for k, v in r["paired"].items():
            log(f"[{per}] {k}: mean40 {v['mean40']:+.5f} sd40 {v['sd40']:.5f} offsets>0 {v['offsets_positive']}/40 "
                f"LOYO min {v['loyo_min']:+.5f} ({v['loyo_min_dropped_year']})")
        r["runtime_s"] = time.time() - tp
        res[per] = r
        rep["periods"] = res
        dump(rep)
        del U, book
    icB = res["B"]["ic"]["pooled"]
    rep["primary"] = {"period": "B", "ic": icB["mean"], "nw_t": icB["t"], "n_dates": icB["n_dates"],
                      "first_date": res["B"]["first"], "last_matured_date": res["B"]["last"],
                      "verdict": verdict(res["B"]["ic"]),
                      "bars": "SUCCESS IC>0 and t>=+1.0; MIDDLE 0<t<1.0; KILL t<=0"}
    log(f"PRIMARY {rep['primary']}")
    rep["runtime_s"] = time.time() - t0
    dump(rep)
    log(f"wrote {REPORT} ({time.time()-t0:.0f}s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["identity", "read"])
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    stage_identity() if args.stage == "identity" else stage_read()


if __name__ == "__main__":
    main()
