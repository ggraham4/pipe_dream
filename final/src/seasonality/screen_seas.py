"""
WO-18 pre-registered screen of `seas` (Heston-Sadka 2008 return seasonality)
on the v2 grid, column c, cap150, h = 40, forward_return_tradable_40,
nomination era 2007-01-02..2019-12-31.
Registration: models/2026-09-26-seasonality-screen.md (committed before the IC run).
Family "return seasonality", NEW, k = 1, bar pooled NW(39) IC t >= +1.96, sign +1.

Harness: insider/screen_insider_v2grid.py imported as a module (gates 1-6,
Book, reconcile, shuffle null) with COL/SIGN/SIGNS9/T_BAR overridden, exactly
as sue/screen_sue.py (WO-13). Primary universe only; its main() is never called.

Modes
  --validate   pre-registration checks only: harness reconcile, frozen weight
               rule reproduces PRODUCTION_WEIGHTS to 4dp, coverage, mapping
               agreement. NO IC / portfolio number for seas.
               -> out/seasonality/validate_seas.json
  (default)    the registered screen -> out/seasonality/seas_screen_report.json
Usage: python screen_seas.py [--validate] [--null-draws 20]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "insider"))
sys.path.insert(0, str(HERE.parent / "reset2026"))
import build_seas as B                 # noqa: E402
import screen_insider_v2grid as V      # noqa: E402
import screen_insider as SI            # noqa: E402
import downcap_v2_readout as DR        # noqa: E402
import ic_weighted_composite as ICW    # noqa: E402

COL = "seas"
V.COL = COL
V.SIGN = +1
V.SIGNS9 = {**V.SIGNS8, COL: +1}
V.T_BAR = 1.96
OUT_JSON = B.OUT / "seas_screen_report.json"
VAL_JSON = B.OUT / "validate_seas.json"
V.OUT_JSON = OUT_JSON                  # never let the harness write under MAIN
HOLDOUT = pd.Timestamp("2020-01-01")
ICW_REPORT = B.MAIN / "out" / "reset2026" / "ic_weighted_composite_report.json"
log = V.log


def weight_rule_check():
    """Frozen rule w_k = s_k*max(0.1,|t_k|-1)/sum on the stored full-era t's must
    reproduce PRODUCTION_WEIGHTS to 4dp (ICW rule and the 9-factor SI rule)."""
    t_full = json.loads(ICW_REPORT.read_text())["per_factor_t"]["full"]
    w_icw = ICW.fit_weights(t_full, V.FC8)
    w_si = SI.fit_weights({k: v["t"] for k, v in t_full.items()}, V.SIGNS8)
    out = {k: [round(w_icw[k], 4), round(w_si[k], 4), ICW.PRODUCTION_WEIGHTS[k]] for k in V.FC8}
    for k, (a, b, c) in out.items():
        assert a == c and b == c, f"WEIGHT RULE FAIL {k}: {a} {b} vs {c}"
    log("frozen weight rule reproduces PRODUCTION_WEIGHTS to 4dp")
    return {"t_source": str(ICW_REPORT), "weights_icw_si_production": out, "pass": True}


def load_universe():
    p, spy = DR.load_column("c")
    all_dates = sorted(p["date"].unique())
    p = p[p["eligible_cap150"]].drop(columns=["eligible_cap500", "eligible_cap2000"])
    sec = pd.read_parquet(DR.R26 / "composite_panel_v2.parquet", columns=["ticker", "date", "sector"],
                          filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    sec["date"] = pd.to_datetime(sec["date"]); sec["ticker"] = sec["ticker"].astype(str)
    fac = pd.read_parquet(B.OUT / "seas_factor_v2.parquet", columns=["ticker", "date", COL, "seas_nyears", "in_sep"])
    n = len(p)
    p = p.merge(sec, on=["ticker", "date"], how="left").merge(fac, on=["ticker", "date"], how="left")
    assert len(p) == n, "merge changed row count"
    # hold-out: no rebalance (label) date >= 2020-01-01. Late-2019 rows whose 40d
    # label ends in early 2020 are kept unmasked (Gabe's ruling, as WO-13).
    assert p["date"].max() < HOLDOUT and spy.index.max() < HOLDOUT, "HOLD-OUT BREACH"
    del sec, fac
    old_t = set(pd.read_parquet(DR.R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].astype(str).unique())
    p["added"] = ~p["ticker"].isin(old_t)
    U = p.sort_values(["date", "ticker"]).reset_index(drop=True)
    return U, all_dates, spy


def mapping_agreement():
    """Share of rows where month(t + 28 calendar days) == month(trading day t+20 on the
    union v2 calendar); only t whose t+20 is <= 2019-12-31 (no 2020 date is read)."""
    d = pd.read_parquet(B.PANEL_V2, columns=["date"], filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    cal = np.sort(pd.to_datetime(d["date"].unique()))
    t = pd.DatetimeIndex(cal[:-20]); t20 = pd.DatetimeIndex(cal[20:])
    m28 = (t + pd.Timedelta(days=28)).month
    same = (m28 == t20.month)
    return {"dates_compared": int(len(t)), "share_same_month": float(same.mean())}


def coverage(U):
    y = U["date"].dt.year
    fin = U[COL].notna()
    by = pd.DataFrame({"y": y, "fin": fin, "added": U["added"], "in_sep": U["in_sep"].fillna(False)})
    tab = {}
    for yr, g in by.groupby("y"):
        tab[int(yr)] = {"all": float(g["fin"].mean()), "old": float(g.loc[~g["added"], "fin"].mean()),
                        "added": float(g.loc[g["added"], "fin"].mean())}
    tick = U.groupby("ticker").agg(added=("added", "first"), in_sep=("in_sep", "max"))
    tick["in_sep"] = tick["in_sep"].fillna(False).astype(bool)
    return {"nonnull": float(fin.mean()), "nonnull_old": float(fin[~U["added"]].mean()),
            "nonnull_added": float(fin[U["added"]].mean()), "by_year": tab,
            "tickers_in_sep_share_old": float(tick.loc[~tick["added"], "in_sep"].mean()),
            "tickers_in_sep_share_added": float(tick.loc[tick["added"], "in_sep"].mean()),
            "tickers_not_in_sep": sorted(tick.index[~tick["in_sep"]].tolist())[:100],
            "nyears_quantiles_finite": {q: float(U.loc[fin, "seas_nyears"].quantile(q)) for q in (0.05, 0.5, 0.95)},
            "seas_quantiles": {q: float(U[COL].quantile(q)) for q in (0.01, 0.05, 0.5, 0.95, 0.99)}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--null-draws", type=int, default=20)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    meta = json.loads((B.OUT / "build_seas_meta.json").read_text())
    rep = {"spec": "models/2026-09-26-seasonality-screen.md", "family": "return seasonality",
           "k": 1, "t_bar": V.T_BAR, "sign": +1, "column": COL, "label": V.LABEL,
           "null_draws": args.null_draws}
    rep["composite_panel_v2_sha256_at_start"] = B.sha256(B.PANEL_V2)
    rep["composite_panel_v2_sha256_build"] = meta["composite_panel_v2_sha256"]
    assert rep["composite_panel_v2_sha256_at_start"] == rep["composite_panel_v2_sha256_build"], "panel changed since build"
    log(f"panel hash {rep['composite_panel_v2_sha256_at_start'][:16]}")
    rep["weight_rule_check"] = weight_rule_check()

    U, all_dates, spy = load_universe()
    V.add_ranks(U, V.FC8)
    book = V.Book(U, all_dates, spy)
    rep["rows"] = int(len(U)); rep["tickers"] = int(U["ticker"].nunique())
    rep["added_rows"] = int(U["added"].sum())
    ref = json.loads(V.READOUT.read_text())["columns"]["c"]["cap150"]
    rep["harness_reconcile"] = V.reconcile(U, book, ref)      # hard asserts, before any seas number
    rep["coverage"] = coverage(U)

    if args.validate:
        rep["mapping_agreement_t28_vs_td20"] = mapping_agreement()
        rep["runtime_s"] = time.time() - t0
        VAL_JSON.write_text(json.dumps(rep, indent=2, default=float))
        log(f"wrote {VAL_JSON} (validate only; no IC computed)")
        return

    prereg = json.loads(VAL_JSON.read_text())
    assert prereg["composite_panel_v2_sha256_at_start"] == rep["composite_panel_v2_sha256_at_start"], "panel != prereg"
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=float))
    ic, g = V.ic_gates(U, xcol=COL)
    rep["ic"] = ic
    log(f"IC {ic['pooled']['mean']:+.5f} t {ic['pooled']['t']:+.2f} | odd {ic['odd']['mean']:+.5f} "
        f"(t {ic['odd']['t']:+.2f}) even {ic['even']['mean']:+.5f} (t {ic['even']['t']:+.2f}) | "
        f"sector both {ic['sector_both_sides']['t']:+.2f} factor-only {ic['sector_factor_only']['t']:+.2f} | "
        f"offset flips {ic['offsets']['sign_flips']}/40 | max year share {ic['year_share']['max_share']} "
        f"({ic['year_share']['max_year']})")
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=float))

    rep["portfolio"] = V.gate6(U, book, args.null_draws, "primary")
    g["g6_beats_null_p80"] = rep["portfolio"]["g6_beats_null_p80"]
    g["g7_weight_rule_reproduces_production_4dp"] = rep["weight_rule_check"]["pass"]
    rep["gates"] = g
    failed = [k for k, v in g.items() if not v]
    rep["verdict"] = "PASS-nomination" if not failed else "DEAD"
    rep["failed_gates"] = failed
    log(f"gates {g} -> {rep['verdict']}")
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=float))

    # ---------------- descriptive only (not gates)
    desc = {}
    U["_icw8"] = SI.composite_score(U, ICW.PRODUCTION_WEIGHTS)
    for c in ["_icw8", "momentum_12_1", "volatility_60"]:
        s = SI.daily_corr(U, COL, c)
        desc[f"median_spearman_seas_vs_{c.lstrip('_')}"] = float(s.median())
    t_full = json.loads(ICW_REPORT.read_text())["per_factor_t"]["full"]
    w_full9 = SI.fit_weights({**{k: v["t"] for k, v in t_full.items()}, COL: ic["pooled"]["t"]}, V.SIGNS9)
    desc["full_era_icw9_weight_of_seas_DESCRIPTIVE"] = w_full9[COL]
    rep["descriptive"] = desc
    log(f"descriptive {json.dumps(desc, default=float)}")
    rep["runtime_s"] = time.time() - t0
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=float))
    log(f"wrote {OUT_JSON} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
