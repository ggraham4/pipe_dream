"""
WO-13 pre-registered screen of `sue` (standardized unexpected earnings,
seasonal random walk) on the v2 grid, column c, cap150, h = 40,
forward_return_tradable_40, nomination era 2007-01-02..2019-12-31.
Registration: models/2026-09-25-sue-drift-screen.md (committed before this ran).
Family "earnings surprise / PEAD", NEW, k = 1, bar pooled NW(39) IC t >= +1.96, sign +1.

Harness: insider/screen_insider_v2grid.py imported as a module (gates 1-6,
Book, reconcile, shuffle null) with COL/SIGN/SIGNS9/T_BAR overridden. Primary
universe only. Its main() is never called.

Output: final/out/sue/sue_screen_report.json
Usage: python screen_sue.py [--null-draws 20]
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
import build_sue as B                  # noqa: E402
import screen_insider_v2grid as V      # noqa: E402
import screen_insider as SI            # noqa: E402
import downcap_v2_readout as DR        # noqa: E402
import ic_weighted_composite as ICW    # noqa: E402

COL = "sue"
V.COL = COL
V.SIGN = +1
V.SIGNS9 = {**V.SIGNS8, COL: +1}
V.T_BAR = 1.96
OUT_JSON = B.OUT / "sue_screen_report.json"
HOLDOUT = pd.Timestamp("2020-01-01")
log = V.log


def h20_label():
    """close[t+h]/open[t+1]-1 from composite_panel_v2's own open/close, h=20 and 40."""
    q = pd.read_parquet(B.PANEL_V2, columns=["ticker", "date", "open", "close"],
                        filters=[("date", ">=", "2006-12-01"), ("date", "<=", "2020-03-31")])
    q["date"] = pd.to_datetime(q["date"]); q["ticker"] = q["ticker"].astype(str)
    q = q.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = q.groupby("ticker", sort=False)
    o1 = g["open"].shift(-1)
    q["lab20"] = g["close"].shift(-20) / o1 - 1.0
    q["lab40"] = g["close"].shift(-40) / o1 - 1.0
    q = q[q["date"] < HOLDOUT]
    return q[["ticker", "date", "lab20", "lab40"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--null-draws", type=int, default=20)
    args = ap.parse_args()
    t0 = time.time()
    rep = {"spec": "models/2026-09-25-sue-drift-screen.md", "family": "earnings surprise / PEAD",
           "k": 1, "t_bar": V.T_BAR, "sign": +1, "column": COL, "label": V.LABEL,
           "null_draws": args.null_draws}
    rep["composite_panel_v2_sha256_at_start"] = B.sha256(B.PANEL_V2)
    rep["composite_panel_v2_sha256_prereg"] = json.loads((B.OUT / "build_sue_meta.json").read_text())["composite_panel_v2_sha256"]
    log(f"panel hash {rep['composite_panel_v2_sha256_at_start'][:16]} (prereg {rep['composite_panel_v2_sha256_prereg'][:16]})")

    p, spy = DR.load_column("c")
    all_dates = sorted(p["date"].unique())
    p = p[p["eligible_cap150"]].drop(columns=["eligible_cap500", "eligible_cap2000"])
    sec = pd.read_parquet(DR.R26 / "composite_panel_v2.parquet", columns=["ticker", "date", "sector"],
                          filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    sec["date"] = pd.to_datetime(sec["date"]); sec["ticker"] = sec["ticker"].astype(str)
    fac = pd.read_parquet(B.OUT / "sue_factor_v2.parquet", columns=["ticker", "date", COL])
    n = len(p)
    p = p.merge(sec, on=["ticker", "date"], how="left").merge(fac, on=["ticker", "date"], how="left")
    assert len(p) == n, "merge changed row count"
    assert p["date"].max() < HOLDOUT and spy.index.max() < HOLDOUT, "HOLD-OUT BREACH"
    del sec, fac
    old_t = set(pd.read_parquet(DR.R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].astype(str).unique())
    p["added"] = ~p["ticker"].isin(old_t)
    U = p.sort_values(["date", "ticker"]).reset_index(drop=True)
    del p
    V.add_ranks(U, V.FC8)
    book = V.Book(U, all_dates, spy)
    rep["rows"] = int(len(U)); rep["tickers"] = int(U["ticker"].nunique())
    rep["added_rows"] = int(U["added"].sum())

    # reconcile BEFORE any sue number
    ref = json.loads(V.READOUT.read_text())["columns"]["c"]["cap150"]
    rep["harness_reconcile"] = V.reconcile(U, book, ref)
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=float))

    rep["nonnull"] = float(U[COL].notna().mean())
    rep["nonnull_old"] = float(U.loc[~U["added"], COL].notna().mean())
    rep["nonnull_added"] = float(U.loc[U["added"], COL].notna().mean())
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
    rep["gates"] = g
    failed = [k for k, v in g.items() if not v]
    rep["verdict"] = "PASS-nomination" if not failed else "DEAD"
    rep["failed_gates"] = failed
    log(f"gates {g} -> {rep['verdict']}")
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=float))

    # ---------------- descriptive only (not gates)
    desc = {}
    U["_icw8"] = SI.composite_score(U, ICW.PRODUCTION_WEIGHTS)
    for c in ["_icw8", "momentum_12_1", "gross_profitability", "volatility_60"]:
        s = SI.daily_corr(U, COL, c)
        desc[f"median_spearman_sue_vs_{c.lstrip('_')}"] = float(s.median())
    lab = h20_label()
    n = len(U)
    U = U.merge(lab, on=["ticker", "date"], how="left")
    assert len(U) == n
    both = U[["lab40", V.LABEL]].dropna()
    desc["h40_reconstruction"] = {"rows_compared": int(len(both)),
                                  "share_within_1e-6": float((both["lab40"] - both[V.LABEL]).abs().lt(1e-6).mean()),
                                  "label_coverage_ratio": float(U["lab40"].notna().sum() / max(1, U[V.LABEL].notna().sum()))}
    s20 = SI.daily_corr(U, COL, "lab20")
    assert s20.index.max() < HOLDOUT
    y = s20.index.year
    desc["ic_h20_DESCRIPTIVE_NOT_A_TRIAL"] = {
        "pooled": {**SI.newey_west_mean_t(s20.to_numpy(), lag=19), "n_dates": int(len(s20))},
        "odd": SI.newey_west_mean_t(s20[y % 2 == 1].to_numpy(), lag=19),
        "even": SI.newey_west_mean_t(s20[y % 2 == 0].to_numpy(), lag=19)}
    s40 = SI.daily_corr(U, COL, V.LABEL)
    desc["ic_h40_same_rows_for_comparison"] = SI.newey_west_mean_t(s40.to_numpy())
    rep["descriptive"] = desc
    log(f"descriptive {json.dumps(desc, default=float)}")
    rep["runtime_s"] = time.time() - t0
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=float))
    log(f"wrote {OUT_JSON} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
