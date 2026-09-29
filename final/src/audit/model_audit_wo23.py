"""
WO-23 (COO): descriptive audit of the live models' weights and variables,
plus the seasonality removal check S1. Pre-registration (committed 8a58c88
before any period-B number): final/models/2026-09-27-model-audit.md.

NO fitting, NO weight changes: every weight is the frozen live constant.
Hold-out read #5 (Gabe's standing OK 2026-09-27 for unfitted 2020-2026 reads).

Periods
  A = 2007-01-02 .. 2019-12-31  (WO-18 harness; hard-reconciled first)
  B = 2020-01-02 .. 2026-07-30  (last matured 40d label)

Models
  Theoretical icw9_seas: PRODUCTION_WEIGHTS_V9_SEAS, v2 col c, cap150,
      decile_volq, 40 offsets, net 15bp (screen_insider_v2grid.Book).
  Blend: 50/50 rank_z of q75 and the 10-factor EW composite leg
      (current_signal_blend._compute_composite_frozen_v10_seas), cap2000,
      q75's single grid (port of wo20_blend_seas_backtest.py).

Harness modules are imported, never edited. Period B uses loaders in this
file that are identical to the period-A ones except for date bounds; the
period-A output of the generic loader is asserted equal to
screen_seas.load_universe before anything else runs.

Usage: python final/src/audit/model_audit_wo23.py [--stage A|B|all]
Output: final/out/audit/model_audit_wo23.json (+ per-stage json)
"""
import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.path.insert(0, str(SRC / "seasonality"))
sys.path.insert(0, str(SRC / "insider"))
sys.path.insert(0, str(SRC / "reset2026"))
import screen_seas as S                 # noqa: E402  (sets V.COL = "seas", V.SIGNS9)
import blend_q75 as BQ                  # noqa: E402
import composite as C                   # noqa: E402
import working_panel as W               # noqa: E402

V, SI, ICW, DR = S.V, S.SI, S.ICW, S.DR
spec = importlib.util.spec_from_file_location("csb_wo23", SRC / "current_signal_blend.py")
CSB = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CSB)

OUT = HERE.parents[1] / "out" / "audit"
SEAS_EXT = OUT / "seas_factor_ext.parquet"
WO18_SEAS_DIR = Path("/Users/ggraham/pipe_dream/.claude/worktrees/agent-a790eb27c4530aa0a/final/out/seasonality")
LABEL = "forward_return_tradable_40"
PERIODS = {"A": (pd.Timestamp("2007-01-02"), pd.Timestamp("2019-12-31")),
           "B": (pd.Timestamp("2020-01-02"), pd.Timestamp("2026-07-30"))}
POST = pd.Timestamp("2011-10-01")
ANN = 252.0 / 40

W9 = dict(ICW.PRODUCTION_WEIGHTS_V9_SEAS)           # live Theoretical
W8 = dict(ICW.PRODUCTION_WEIGHTS)                   # icw8
SIGNS_T = dict(ICW.SIGNS_V9_SEAS)
FT = list(W9)                                       # 9 Theoretical factors
SIGNS_B = dict(CSB._BLEND_FACTOR_SIGNS_V10_SEAS)
FB = list(SIGNS_B)                                  # 10 blend factors

REF_A = {"icw8": 0.0285416, "icw9_seas": 0.0348710}           # 40-offset mean, tol 1e-6
SEAS_OUT = HERE.parents[1] / "out" / "seasonality"          # committed WO-20 outputs (merged 56afb05)
REF_BLEND_A = json.loads((SEAS_OUT / "wo20_blend_seas_backtest.json").read_text())["v2c"]
REF_FROZEN = json.loads((SEAS_OUT / "wo20_frozen_backtest.json").read_text())
# COO's +0.0348710 is icw9_seas at FULL precision (SI.fit_weights on the 8 full-era t's + SEAS_T);
# the live constant is its 4-dp rounding (WO-20 recorded the gap, -5.85e-6).
_T_FULL = json.loads(S.ICW_REPORT.read_text())["per_factor_t"]["full"]
W9_FULL = SI.fit_weights({**{k: v["t"] for k, v in _T_FULL.items()}, "seas": ICW.SEAS_T}, V.SIGNS9)
assert {k: round(v, 4) for k, v in W9_FULL.items()} == W9
log = V.log


# ------------------------------------------------------------------ loaders
def _filt(path, lo, hi):
    t = str(pq.read_schema(path).field("date").type)
    if "string" in t:
        return [("date", ">=", lo.date().isoformat()), ("date", "<=", hi.date().isoformat())]
    return [("date", ">=", lo), ("date", "<=", hi)]


def load_theo(period, tier="cap150"):
    """DR.load_column('c') + screen_seas.load_universe, date bounds from PERIODS,
    seas from the WO-23 extension (== WO-18 on every pre-2020 row)."""
    lo, hi = PERIODS[period]
    cols = list(dict.fromkeys(["ticker", "date", LABEL, "sector", f"eligible_{tier}", "asset_growth"] + C.FACTOR_COLS))
    old_t = set(pd.read_parquet(DR.R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].astype(str).unique())
    p = pd.read_parquet(DR.R26 / "composite_panel_v2.parquet", columns=cols, filters=_filt(DR.R26 / "composite_panel_v2.parquet", lo, hi))
    p["date"] = pd.to_datetime(p["date"]); p["ticker"] = p["ticker"].astype(str)
    tm = pd.read_csv(DR.SH / "tickers_master.csv", dtype=str, usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    p = p[p["ticker"].isin(old_t) | ~p["ticker"].isin(spac)]
    p = p[(p["date"] >= lo) & (p["date"] <= hi)]
    oc_p = DR.R26 / "outcome_cache_v2.parquet"
    oc = pd.read_parquet(oc_p, columns=["ticker", "date", "gross_return_40"], filters=[("date", ">=", lo), ("date", "<=", hi)])
    oc["date"] = pd.to_datetime(oc["date"]); oc["ticker"] = oc["ticker"].astype(str)
    spy = oc[oc["ticker"] == "SPY"].set_index("date")["gross_return_40"]
    all_dates = sorted(p["date"].unique())
    p = p[p[f"eligible_{tier}"].astype(bool)].drop(columns=[f"eligible_{tier}"])
    n = len(p)
    p = p.merge(oc[~oc["ticker"].isin(["SPY", "USMV"])], on=["ticker", "date"], how="left")
    fac = pd.read_parquet(SEAS_EXT, columns=["ticker", "date", "seas"], filters=[("date", ">=", lo), ("date", "<=", hi)])
    fac["date"] = pd.to_datetime(fac["date"]); fac["ticker"] = fac["ticker"].astype(str)
    p = p.merge(fac, on=["ticker", "date"], how="left")
    assert len(p) == n, "merge changed row count"
    assert p["date"].max() <= hi and spy.index.max() <= hi
    U = p.sort_values(["date", "ticker"]).reset_index(drop=True)
    log(f"[{period}] {tier}: {len(U):,} rows, {U['ticker'].nunique():,} tickers, {len(all_dates)} dates "
        f"{pd.Timestamp(all_dates[0]).date()}..{pd.Timestamp(all_dates[-1]).date()}")
    return U, all_dates, spy


def check_loader_A(U):
    """Generic loader (period A) == screen_seas.load_universe on every column the audit uses."""
    S.B.OUT = WO18_SEAS_DIR
    R, rd, rspy = S.load_universe()
    cols = ["ticker", "date", LABEL, "sector", "gross_return_40", "seas"] + C.FACTOR_COLS
    a = U[cols].reset_index(drop=True); b = R[cols].reset_index(drop=True)
    assert len(a) == len(b), (len(a), len(b))
    for c in cols:
        if a[c].dtype.kind == "f":
            x, y = a[c].to_numpy(np.float64), b[c].to_numpy(np.float64)
            assert ((x == y) | (np.isnan(x) & np.isnan(y))).all(), f"loader mismatch {c}"
        else:
            assert (a[c].astype(str).to_numpy() == b[c].astype(str).to_numpy()).all(), f"loader mismatch {c}"
    return {"rows": int(len(a)), "equal_to_screen_seas_load_universe": True}, rd, rspy


# ------------------------------------------------------------------ book
def backtest_detail(picks_by_date, all_dates, spy):
    """downcap_v2_readout.backtest, also returning the 40 per-offset means and
    per-year excess (offset-averaged)."""
    per_off, yearly = [], {}
    for off in range(40):
        prev, recs = set(), []
        for tp in all_dates[off::40]:
            if tp not in picks_by_date:
                continue
            gross, cur = picks_by_date[tp]
            f_new = sum(1 for t in cur if t not in prev) / len(cur)
            prev = cur
            recs.append({"date": tp, "gross": gross, "f_new": f_new, "spy": spy.get(tp, np.nan)})
        net = DR.RB.turnover_net_return(recs, DR.COST_BPS)
        s = np.array([r["spy"] for r in recs], dtype=np.float64)
        yrs = np.array([r["date"].year for r in recs]); ok = np.isfinite(s)
        exc, yrs = net[ok] - s[ok], yrs[ok]
        per_off.append(float(exc.mean() * ANN))
        for y in np.unique(yrs):
            yearly.setdefault(int(y), []).append(float(exc[yrs == y].mean() * ANN))
    return np.array(per_off), {y: float(np.mean(v)) for y, v in yearly.items()}


def run_book(book, score, all_dates, spy, post=False):
    pk = book.picks(score)
    r = DR.backtest(pk, all_dates, spy)
    per_off, yearly = backtest_detail(pk, all_dates, spy)
    assert abs(per_off.mean() - r["excess_cagr_vs_spy_mean40"]) < 1e-12
    r["yearly_excess_ann"] = yearly
    if post:
        r["post2011_10"] = DR.backtest({d: v for d, v in pk.items() if d >= POST},
                                       [d for d in all_dates if d >= POST], spy)["excess_cagr_vs_spy_mean40"]
    return r, per_off


# ------------------------------------------------------------------ per-factor IC
def factor_ic(U, col):
    ic, _ = V.ic_gates(U, xcol=col)
    s = SI.daily_corr(U, col, LABEL)
    return {"mean": ic["pooled"]["mean"], "t": ic["pooled"]["t"], "n_dates": ic["pooled"]["n_dates"],
            "sector_both_sides_t": ic["sector_both_sides"]["t"], "sector_both_sides_mean": ic["sector_both_sides"]["mean"],
            "per_year": {int(y): float(v) for y, v in s.groupby(s.index.year).mean().items()},
            "per_year_n_dates": {int(y): int(v) for y, v in s.groupby(s.index.year).size().items()},
            "offset_sign_flips": ic["offsets"]["sign_flips"]}


def implied_weights(ts, signs):
    return SI.fit_weights({k: ts[k] for k in signs}, signs)


def coverage_by_year(U, col="seas"):
    g = U[col].notna().groupby(U["date"].dt.year).mean()
    return {int(k): float(v) for k, v in g.items()}


# ------------------------------------------------------------------ Theoretical
def theoretical(period):
    t0 = time.time()
    U, all_dates, spy = load_theo(period, "cap150")
    res = {"rows": int(len(U)), "tickers": int(U["ticker"].nunique()), "dates": len(all_dates),
           "first": str(pd.Timestamp(all_dates[0]).date()), "last": str(pd.Timestamp(all_dates[-1]).date()),
           "seas_coverage_by_year_cap150": coverage_by_year(U)}
    if period == "A":
        res["loader_check"], rd, rspy = check_loader_A(U)
        assert [pd.Timestamp(x) for x in rd] == [pd.Timestamp(x) for x in all_dates] and rspy.equals(spy)
        log(f"[A] generic loader == screen_seas.load_universe")
    V.add_ranks(U, FT)
    book = V.Book(U, all_dates, spy)
    post = period == "A"
    full, full_off = run_book(book, SI.composite_score(U, W9).to_numpy(), all_dates, spy, post)
    icw8, icw8_off = run_book(book, SI.composite_score(U, W8).to_numpy(), all_dates, spy, post)
    res["icw9_seas"], res["icw8"] = full, icw8
    res["icw9_minus_icw8"] = {"mean40": float((full_off - icw8_off).mean()), "sd40": float((full_off - icw8_off).std())}
    log(f"[{period}] icw9_seas {full['excess_cagr_vs_spy_mean40']:+.7f} (sd40 {full['sd40']:.5f})  "
        f"icw8 {icw8['excess_cagr_vs_spy_mean40']:+.7f}")
    if period == "A":
        fp, _ = run_book(book, SI.composite_score(U, W9_FULL).to_numpy(), all_dates, spy, post)
        res["icw9_seas_full_precision"] = fp
        chk = {"icw8": (icw8["excess_cagr_vs_spy_mean40"], REF_A["icw8"]),
               "icw9_seas_full_precision": (fp["excess_cagr_vs_spy_mean40"], REF_A["icw9_seas"])}
        for k, (got, ref) in chk.items():
            assert abs(got - ref) < 1e-6, f"RECONCILE FAIL {k} {got} vs {ref}"
        got4 = full["excess_cagr_vs_spy_mean40"]
        ref4 = REF_FROZEN["icw9_seas_frozen_4dp"]["excess_cagr_vs_spy_mean40"]
        assert abs(got4 - ref4) < 1e-9, f"RECONCILE FAIL icw9_seas 4dp {got4} vs WO-20 {ref4}"
        chk["icw9_seas_live_4dp_vs_wo20"] = (got4, ref4)
        res["reconcile"] = {k: list(v) for k, v in chk.items()}
        log(f"[A] RECONCILE OK {res['reconcile']}")
    fac = {}
    for k in FT:
        f = factor_ic(U, k)
        w_minus = {c: w for c, w in W9.items() if c != k}
        r_k, off_k = run_book(book, SI.composite_score(U, w_minus).to_numpy(), all_dates, spy, post)
        d = full_off - off_k
        f["loo"] = {"excess_without": r_k["excess_cagr_vs_spy_mean40"], "delta_mean40": float(d.mean()),
                    "delta_sd40": float(d.std()), "without_sd40": r_k["sd40"], "without_loyo_min": r_k["loyo_min"]}
        f["sign"] = SIGNS_T[k]; f["current_weight"] = W9[k]
        f["wrong_signed"] = bool(np.isfinite(f["mean"]) and np.sign(f["mean"]) != SIGNS_T[k])
        fac[k] = f
        log(f"[{period}] {k:32s} IC {f['mean']:+.4f} t {f['t']:+.2f} sec-t {f['sector_both_sides_t']:+.2f} "
            f"LOO delta {d.mean():+.5f} (sd {d.std():.5f}) ({time.time()-t0:.0f}s)")
    iw = implied_weights({k: fac[k]["t"] for k in FT}, SIGNS_T)
    for k in FT:
        fac[k]["implied_weight"] = iw[k]
    res["factors"] = fac
    # cross-check: the rule is proportional and the scorer renormalises, so
    # icw9_seas minus seas == icw8 up to 4-dp rounding -> delta_seas ~= icw9 - icw8
    res["loo_crosscheck_seas_vs_icw9_minus_icw8"] = [fac["seas"]["loo"]["delta_mean40"], res["icw9_minus_icw8"]["mean40"]]
    res["runtime_s"] = time.time() - t0
    return res


# ------------------------------------------------------------------ blend
def ew_composite(elig, signs):
    sc = pd.DataFrame(index=elig.index)
    for c, s in signs.items():
        sc[c] = C.rank_z(elig[c]) * s
    cov = sc.notna().sum(axis=1)
    return sc.mean(axis=1, skipna=True).where(cov > 0)


def load_blend(period):
    """wo20_blend_seas_backtest.load('v2c') with q75 timepoints in the period."""
    lo, hi = PERIODS[period]
    path, outc = W.WORKING_PANEL, W.WORKING_OUTCOME
    cols = list(dict.fromkeys(["ticker", "date", "sector", "volatility_60", "eligible_cap2000"] + CSB._ORIGINAL_FACTOR_COLS))
    q75 = pd.read_parquet(BQ.Q75_SCORES, columns=["timepoint", "ticker", "score"])
    q75["timepoint"] = pd.to_datetime(q75["timepoint"]); q75["ticker"] = q75["ticker"].astype(str)
    q75 = q75[(q75["timepoint"] >= lo) & (q75["timepoint"] <= hi)]
    dates = [pd.Timestamp(d) for d in sorted(q75["timepoint"].unique())]
    import wo20_blend_seas_backtest as WB
    p = pd.read_parquet(path, columns=cols, filters=WB._in_dates(path, dates))
    p["date"] = pd.to_datetime(p["date"]); p["ticker"] = p["ticker"].astype(str)
    assert p["date"].max() <= hi
    p = p[W.universe_keep(p["ticker"])]
    o = pd.read_parquet(outc, columns=["ticker", "date", "gross_return_40"], filters=WB._in_dates(outc, dates))
    o["date"] = pd.to_datetime(o["date"]); o["ticker"] = o["ticker"].astype(str)
    spy = o[o["ticker"] == "SPY"].set_index("date")["gross_return_40"].to_dict()
    p = p.merge(o[~o["ticker"].isin(["SPY", "USMV"])], on=["ticker", "date"], how="left")
    s = pd.read_parquet(SEAS_EXT, columns=["ticker", "date", "seas"], filters=WB._in_dates(SEAS_EXT, dates))
    s["date"] = pd.to_datetime(s["date"]); s["ticker"] = s["ticker"].astype(str)
    n = len(p)
    p = p.merge(s, on=["ticker", "date"], how="left")
    assert len(p) == n
    e = p["eligible_cap2000"].astype(bool)
    info = {"timepoints": len(dates), "first": str(dates[0].date()), "last": str(dates[-1].date()),
            "eligible_rows": int(e.sum()), "seas_coverage_eligible": float(p.loc[e, "seas"].notna().mean())}
    q75_by = {d: g.set_index("ticker")["score"] for d, g in q75.groupby("timepoint")}
    return p, dates, q75_by, spy, info


def blend_run(p, dates, q75_by, spy, variants):
    """variants: {name: signs dict for the EW composite leg}. Returns {name: records}."""
    recs = {k: [] for k in variants}; prev = {k: set() for k in variants}
    by_date = dict(tuple(p.groupby("date")))
    checked = 0
    for tp in dates:
        g = by_date.get(tp)
        if g is None:
            continue
        elig = g[g["eligible_cap2000"].astype(bool)].reset_index(drop=True)
        if len(elig) < 20 or tp not in q75_by:
            continue
        ret = dict(zip(elig["ticker"], elig["gross_return_40"]))
        qr = C.rank_z(pd.Series(elig["ticker"].map(q75_by[tp]).to_numpy(np.float64), index=elig.index))
        if checked < 3:   # generic EW leg == the live frozen functions
            a = ew_composite(elig, SIGNS_B).to_numpy(np.float64)
            b = CSB._compute_composite_frozen_v10_seas(elig)["composite"].to_numpy(np.float64)
            a9 = ew_composite(elig, dict(CSB._ORIGINAL_FACTOR_SIGNS)).to_numpy(np.float64)
            b9 = CSB._compute_composite_frozen(elig)["composite"].to_numpy(np.float64)
            for x, y in ((a, b), (a9, b9)):
                assert ((np.abs(x - y) < 1e-12) | (np.isnan(x) & np.isnan(y))).all()
            checked += 1
        for key, signs in variants.items():
            cr = C.rank_z(ew_composite(elig, signs))
            b = pd.concat([cr, qr], axis=1).mean(axis=1, skipna=True)
            b[cr.isna() & qr.isna()] = np.nan
            pk = C.pick_decile_volq(elig, pd.DataFrame({"ticker": elig["ticker"].to_numpy(), "composite": b.to_numpy()}))
            pk = [(t, w) for t, w in pk if pd.notna(ret.get(t))]
            if not pk:
                continue
            ws = sum(w for _, w in pk)
            gross = sum((w / ws) * (1.0 + ret[t]) for t, w in pk) - 1.0
            cur = {t for t, _ in pk}
            f_new = len(cur - prev[key]) / len(cur); prev[key] = cur
            recs[key].append({"date": tp, "gross": gross, "f_new": f_new, "spy": spy.get(tp, np.nan)})
    return recs


def blend_summary(records):
    df = pd.DataFrame(records).sort_values("date")
    net = BQ.turnover_net(df["gross"].to_numpy(), df["f_new"].to_numpy(), BQ.COST_BPS)
    s = df["spy"].to_numpy(np.float64); ok = np.isfinite(s)
    ex = (net - s)[ok]
    d = pd.DatetimeIndex(pd.to_datetime(df["date"]).to_numpy()[ok]); yrs = d.year.to_numpy()
    loyo = {int(y): float(np.mean(ex[yrs != y]) * ANN) for y in np.unique(yrs)}
    ymin = min(loyo, key=loyo.get); post = d >= POST
    return {"_dates": d, "n_windows": int(ok.sum()), "excess_cagr_vs_spy": float(np.mean(ex) * ANN),
            "loyo_min": loyo[ymin], "loyo_min_dropped_year": ymin,
            "post2011_10": float(np.mean(ex[post]) * ANN) if post.any() else None,
            "yearly_mean_excess_ann": {int(y): float(np.mean(ex[yrs == y]) * ANN) for y in np.unique(yrs)},
            "_ex": ex}


def blend(period):
    t0 = time.time()
    p, dates, q75_by, spy, info = load_blend(period)
    variants = {"blend_seas10": SIGNS_B, "blend_prev9": dict(CSB._ORIGINAL_FACTOR_SIGNS)}
    for k in FB:
        variants[f"blend10_minus_{k}"] = {c: s for c, s in SIGNS_B.items() if c != k}
    recs = blend_run(p, dates, q75_by, spy, variants)
    sm = {k: blend_summary(r) for k, r in recs.items()}
    res = {"info": info}
    for k in ("blend_seas10", "blend_prev9"):
        res[k] = {kk: vv for kk, vv in sm[k].items() if kk not in ("_ex", "_dates")}
    for k in variants:
        assert sm[k]["_dates"].equals(sm["blend_seas10"]["_dates"]), f"window dates differ: {k}"
    if period == "A":
        for k in ("blend_prev9", "blend_seas10"):
            got, ref = res[k]["excess_cagr_vs_spy"], REF_BLEND_A[k]["excess_cagr_vs_spy"]
            assert abs(got - ref) < 1e-9, f"RECONCILE FAIL blend {k} {got} vs {ref}"
        res["reconcile"] = {k: [res[k]["excess_cagr_vs_spy"], REF_BLEND_A[k]["excess_cagr_vs_spy"]]
                            for k in ("blend_prev9", "blend_seas10")}
        log(f"[A] BLEND RECONCILE OK {res['reconcile']}")
    full = sm["blend_seas10"]["_ex"]
    res["blend10_minus_blend9"] = float((full - sm["blend_prev9"]["_ex"]).mean() * ANN)
    res["loo"] = {}
    for k in FB:
        d = full - sm[f"blend10_minus_{k}"]["_ex"]
        res["loo"][k] = {"excess_without": sm[f"blend10_minus_{k}"]["excess_cagr_vs_spy"],
                         "delta": float(d.mean() * ANN)}
    log(f"[{period}] blend10 {res['blend_seas10']['excess_cagr_vs_spy']:+.5f} blend9 "
        f"{res['blend_prev9']['excess_cagr_vs_spy']:+.5f} ({time.time()-t0:.0f}s)")
    # per-factor IC on the cap2000 column-c universe, all panel dates of the period
    lo, hi = PERIODS[period]
    U, _, _ = load_theo(period, "cap2000")
    res["rows_cap2000_daily"] = int(len(U))
    res["seas_coverage_by_year_cap2000"] = coverage_by_year(U)
    fac = {}
    for k in FB:
        f = factor_ic(U, k)
        f["sign"] = SIGNS_B[k]; f["current_weight"] = SIGNS_B[k] / len(FB)
        f["wrong_signed"] = bool(np.isfinite(f["mean"]) and np.sign(f["mean"]) != SIGNS_B[k])
        f["loo_single_grid"] = res["loo"][k]
        fac[k] = f
        log(f"[{period}] blend {k:32s} IC {f['mean']:+.4f} t {f['t']:+.2f} sec-t {f['sector_both_sides_t']:+.2f} "
            f"LOO(1 grid) {res['loo'][k]['delta']:+.5f}")
    iw = implied_weights({k: fac[k]["t"] for k in FB}, SIGNS_B)
    for k in FB:
        fac[k]["implied_weight"] = iw[k]
    res["factors"] = fac
    res["runtime_s"] = time.time() - t0
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["A", "B", "all"])
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for per in (["A", "B"] if args.stage == "all" else [args.stage]):
        out = {"period": per, "bounds": [str(x.date()) for x in PERIODS[per]],
               "weights_icw9_seas": W9, "weights_icw8": W8, "blend_signs": SIGNS_B,
               "prereg": "final/models/2026-09-27-model-audit.md @ 8a58c88"}
        out["theoretical"] = theoretical(per)
        (OUT / f"model_audit_wo23_{per}.json").write_text(json.dumps(out, indent=1, default=float))
        out["blend"] = blend(per)
        (OUT / f"model_audit_wo23_{per}.json").write_text(json.dumps(out, indent=1, default=float))
        log(f"wrote {OUT / f'model_audit_wo23_{per}.json'}")


if __name__ == "__main__":
    main()
