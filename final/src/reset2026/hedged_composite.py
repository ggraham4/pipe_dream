"""
WO-9: the universe-hedged composite. Pre-registration (frozen before any
result): final/models/2026-09-25-hedged-composite.md.

hedged = (icw8 decile_volq net-15bp book return) - (IWM 40d return) - 10bp
per rebalance, per offset chain; excess annualised x252/40. ETF borrow ~0.

IWM basis = SPY's basis in outcome_cache_v2: yfinance auto_adjust=False
(split-adjusted, price-only), gross_return_40[i] = close[i+40]/open[i+1]-1.
IWM is pulled only to 2019-12-31, so dates with i+40 > n-1 are NaN (not
truncated) -- clarification C2.

Imports downcap_v2_readout (R) and noscore_control_v2 (NX); edits neither.
Era 2007-01-02..2019-12-31; every frame asserts max(date) < 2020-01-01.

Output: /Users/ggraham/pipe_dream/final/out/reset2026/downcap_v2/hedged_composite.json
Usage:  /opt/anaconda3/envs/pipe_dream/bin/python hedged_composite.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_backtest as RB                  # noqa: E402
import downcap_v2_readout as R             # noqa: E402
import noscore_control_v2 as NX            # noqa: E402

OUT = R.V2 / "hedged_composite.json"
IWM_CSV = R.MAIN / "data" / "benchmarks" / "IWM.csv"
SPY_CSV = R.MAIN / "scripts" / "td_data_local" / "SPY.csv"
TIERS = ["cap150", "cap500", "cap2000"]
H = RB.HORIZON
ANN = 252.0 / H
SHORT_BPS = 10.0
COMMON_START = pd.Timestamp("2011-10-20")
NW_LAG = 39
log = R.log


# ---------------------------------------------------------------- data
def guard(df, col="date"):
    assert df[col].max() < R.HOLDOUT, "HOLD-OUT BREACH: date >= 2020-01-01"
    return df


def yf_pull(sym, start, end="2020-01-01"):
    import yfinance as yf
    d = yf.download(sym, start=start, end=end, progress=False, auto_adjust=False, actions=False)
    if d is None or d.empty:
        raise SystemExit(f"BLOCKED: yfinance returned nothing for {sym}")
    d = d.reset_index()
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d = d.rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low",
                          "Close": "close", "Adj Close": "adj_close", "Volume": "volume"})
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None)
    return guard(d[["date", "open", "high", "low", "close", "adj_close", "volume"]])


def load_iwm():
    if not IWM_CSV.exists():
        d = yf_pull("IWM", "2006-06-01")
        d.to_csv(IWM_CSV, index=False)      # new file; gitignored data
        log(f"pulled IWM -> {IWM_CSV} ({len(d)} rows)")
    d = pd.read_csv(IWM_CSV, parse_dates=["date"])
    return guard(d.sort_values("date").reset_index(drop=True))


def ret40(g, total_return=False):
    """close[i+40]/open[i+1]-1, NaN where i+40 > n-1 (no end-of-series floor)."""
    n = len(g)
    o, c = g["open"].to_numpy(np.float64), g["close"].to_numpy(np.float64)
    if total_return:
        f = g["adj_close"].to_numpy(np.float64) / c
        o, c = o * f, c * f
    idx = np.arange(n)
    ok = idx + H <= n - 1
    out = np.full(n, np.nan)
    out[ok] = c[idx[ok] + H] / o[idx[ok] + 1] - 1.0
    return pd.Series(out, index=pd.DatetimeIndex(g["date"]))


def cal_year(g, y, col):
    s = g.set_index("date")[col]
    return float(s[s.index.year == y].iloc[-1] / s[s.index.year == y - 1].iloc[-1] - 1.0)


def data_checks(iwm):
    chk = {"iwm_rows": len(iwm), "iwm_first": str(iwm["date"].min().date()),
           "iwm_last": str(iwm["date"].max().date())}
    # name-check (total return on adj_close), price-only alongside
    nc = {}
    for y, tgt in ((2008, -0.34), (2017, 0.146)):
        tr, pr = cal_year(iwm, y, "adj_close"), cal_year(iwm, y, "close")
        nc[y] = {"total_return": tr, "price_return": pr, "target_total": tgt, "ok": abs(tr - tgt) <= 0.02}
        log(f"name-check IWM {y}: total {tr:+.4f} (target {tgt:+.3f}) price-only {pr:+.4f}")
        assert nc[y]["ok"], f"NAME-CHECK FAIL IWM {y}: {tr:+.4f} vs {tgt:+.3f}"
    chk["name_check"] = nc
    # sanity: no split in window, open/close coherent
    assert (iwm[["open", "close"]] > 0).all().all()
    jumps = iwm["close"].pct_change().abs()
    chk["max_abs_daily_close_move"] = float(jumps.max())
    chk["max_abs_daily_close_move_date"] = str(iwm.loc[jumps.idxmax(), "date"].date())

    # pull-method check: same yfinance call on SPY vs SPY.csv
    spy_file = pd.read_csv(SPY_CSV, usecols=["date", "open", "high", "low", "close"], parse_dates=["date"])
    spy_file = guard(spy_file[spy_file["date"] <= R.END].sort_values("date").reset_index(drop=True))
    if True:
        spy_yf = yf_pull("SPY", "2006-01-01")
        m = spy_file.merge(spy_yf[["date", "open", "close"]], on="date", suffixes=("_file", "_yf"))
        rng = np.random.default_rng(9)
        s = m.iloc[np.sort(rng.choice(len(m), 50, replace=False))]
        rel_c = np.abs(s["close_yf"] / s["close_file"] - 1.0)
        rel_o = np.abs(s["open_yf"] / s["open_file"] - 1.0)
        rel_all = np.abs(m["close_yf"] / m["close_file"] - 1.0)
        chk["pull_method_check_spy"] = {"n_sampled": 50, "max_rel_close": float(rel_c.max()),
                                        "max_rel_open": float(rel_o.max()),
                                        "max_rel_close_all_dates": float(rel_all.max()),
                                        "n_dates_matched": len(m), "n_file_dates": len(spy_file)}
        log(f"pull-method SPY: max rel close {rel_c.max():.2e} open {rel_o.max():.2e} (all dates {rel_all.max():.2e})")
        assert rel_c.max() < 1e-4 and rel_o.max() < 1e-4, "PULL-METHOD CHECK FAIL"

    # method reconcile: ret40 on SPY.csv (to 2019-12-31) vs outcome_cache_v2 SPY
    oc = pd.read_parquet(R.R26 / "outcome_cache_v2.parquet", columns=["ticker", "date", "gross_return_40"],
                         filters=[("ticker", "==", "SPY"), ("date", ">=", pd.Timestamp("2006-01-01")),
                                  ("date", "<=", R.END)])
    oc["date"] = pd.to_datetime(oc["date"])
    oc = guard(oc).set_index("date")["gross_return_40"].astype(np.float64)
    mine = ret40(spy_file)
    cand = mine.dropna().index.intersection(oc.dropna().index)
    rng = np.random.default_rng(40)
    samp = pd.DatetimeIndex(np.sort(rng.choice(cand.to_numpy(), 50, replace=False)))
    diff = np.abs(mine[samp].to_numpy() - oc[samp].to_numpy())
    diff_all = np.abs(mine[cand].to_numpy() - oc[cand].to_numpy())
    chk["spy_method_reconcile"] = {"n_sampled": 50, "max_abs_diff": float(diff.max()),
                                   "max_abs_diff_all_eligible_dates": float(diff_all.max()),
                                   "n_eligible": len(cand), "tol": 1e-6}
    log(f"SPY method reconcile: 50 sampled max |diff| {diff.max():.2e}; all {len(cand)} dates {diff_all.max():.2e}")
    assert diff.max() < 1e-6, "SPY METHOD RECONCILE FAIL"
    return chk


# ---------------------------------------------------------------- per-date series
def chain_series(pk, all_dates, bench, cost_bps):
    """Per-(offset, date) excess exactly as NX.backtest_vectors builds it."""
    rows = []
    for off in range(40):
        prev, recs = set(), []
        for tp in all_dates[off::H]:
            if tp not in pk:
                continue
            cur = pk[tp][1]
            f_new = sum(1 for t in cur if t not in prev) / len(cur)
            prev = cur
            recs.append({"date": tp, "gross": pk[tp][0], "f_new": f_new, "b": bench.get(tp, np.nan)})
        net = RB.turnover_net_return(recs, cost_bps)
        for r, nv in zip(recs, net):
            if np.isfinite(r["b"]):
                rows.append((off, r["date"], float(nv - r["b"])))
    return pd.DataFrame(rows, columns=["off", "date", "h"])


def nw_ols(y, x, lag=NW_LAG):
    X = np.column_stack([np.ones_like(x), x])
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    u = y - X @ b
    Xu = X * u[:, None]
    S = Xu.T @ Xu
    for l in range(1, lag + 1):
        w = 1.0 - l / (lag + 1.0)
        G = Xu[l:].T @ Xu[:-l]
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(V))
    return {"alpha_per_rebalance": float(b[0]), "beta": float(b[1]), "beta_t_nw": float(b[1] / se[1]),
            "beta_se_nw": float(se[1]), "n": int(len(y)), "nw_lag": lag,
            "r2": float(1 - (u @ u) / ((y - y.mean()) @ (y - y.mean())))}


def extras(df, spy_s):
    """per-year, MDD, beta for a per-date hedged frame."""
    df = df.sort_values(["off", "date"])
    df["year"] = df["date"].dt.year
    py = df.groupby(["off", "year"])["h"].mean().groupby("year").mean() * ANN
    mdd = []
    for _, g in df.groupby("off"):
        w = np.cumprod(1.0 + g["h"].to_numpy())
        w = np.concatenate([[1.0], w])
        mdd.append(float((w / np.maximum.accumulate(w) - 1.0).min()))
    d2 = df.sort_values("date")
    x = spy_s.reindex(pd.DatetimeIndex(d2["date"])).to_numpy(np.float64)
    ok = np.isfinite(x)
    beta = nw_ols(d2["h"].to_numpy()[ok], x[ok])
    return {"per_year": {int(k): float(v) for k, v in py.items()},
            "mdd_median_over_offsets": float(np.median(mdd)), "mdd_worst_over_offsets": float(np.min(mdd)),
            "beta_to_spy": beta}


def run_vec(pk, all_dates, bench, cost):
    po, lo = NX.backtest_vectors(pk, all_dates, bench, cost_bps=cost)
    years, lm = NX.loyo_matrix(lo)
    s = NX.summarize(po, lo)
    s["per_offset"] = [float(v) for v in po]
    return s, po, lm, years


def gates(full, common, ext):
    b = ext["beta_to_spy"]["beta"]
    c = {"full_mean40_gt_1pp": full["mean40"] > 0.010, "common_mean40_gt_1pp": common["mean40"] > 0.010,
         "full_offsets_pos_ge_36": full["offsets_positive"] >= 36, "full_loyo_min_gt_0": full["loyo_min"] > 0,
         "abs_beta_lt_0p3": abs(b) < 0.3}
    kill = full["mean40"] <= 0 or common["mean40"] <= 0 or full["loyo_min"] <= 0
    v = "PASS (nomination)" if all(c.values()) else "KILL" if kill else "MIDDLE"
    return {"conditions": c, "kill_triggered": bool(kill), "verdict": v}


# ---------------------------------------------------------------- main
def main():
    T0 = time.time()
    out = {"work_order": "WO-9", "era": "2007-01-02..2019-12-31", "book_cost_bps": R.COST_BPS,
           "short_leg_bps_per_rebalance": SHORT_BPS, "etf_borrow": "assumed ~0",
           "windows": {"full": "2007-01-02..2019-12-31", "common": "2011-10-20..2019-12-31"},
           "prereg": "final/models/2026-09-25-hedged-composite.md",
           "trial": "14th nomination-era trial of the composite family"}

    iwm = load_iwm()
    out["data_checks"] = data_checks(iwm)
    OUT.write_text(json.dumps(out, indent=2, default=str))

    p, spy = R.load_column("c")
    guard(p)
    all_dates = sorted(p["date"].unique())
    DI = pd.DatetimeIndex(all_dates)
    spy_s = spy.astype(np.float64).reindex(DI)
    iwm_p = ret40(iwm).reindex(DI)
    iwm_t = ret40(iwm, total_return=True).reindex(DI)
    assert iwm_p.notna().sum() > 0
    n_masked = int((spy_s.notna() & iwm_p.isna()).sum())
    first_nan = str(iwm_p[iwm_p.isna()].index.min().date()) if iwm_p.isna().any() else None
    out["data_checks"]["iwm40_nan_dates_in_era_where_spy_finite"] = n_masked
    out["data_checks"]["iwm40_first_nan_date"] = first_nan
    assert iwm_p[DI < pd.Timestamp("2019-10-01")].notna().all(), "IWM40 NaN before the end-of-era mask"
    log(f"IWM40 NaN on {n_masked} era dates (end-of-era mask, first {first_nan})")
    common = DI >= COMMON_START
    sb = SHORT_BPS / 1e4
    benches = {
        "primary_15bp": {"full": iwm_p + sb, "common": (iwm_p + sb).where(common), "cost": None},
        "supp_total_return_iwm_15bp": {"full": iwm_t + sb, "common": (iwm_t + sb).where(common), "cost": None},
        "supp_0bp": {"full": iwm_p, "common": iwm_p.where(common), "cost": 0.0},
    }
    spy_masked = spy_s.where(iwm_p.notna())

    books, _ = NX.build_books(p, TIERS, with_null=False)
    log(f"books built ({time.time()-T0:.0f}s)")
    ref_readout = json.loads((R.V2 / "readout.json").read_text())["columns"]["c"]

    out["tiers"] = {}
    for tier in TIERS:
        bk = books[tier]
        tr = {}
        # gate: machinery reproduces readout c/tier/icw8 vs SPY
        s_spy, _, _, _ = run_vec(bk["icw8"], all_dates, spy_s, None)
        ref = ref_readout[tier]["icw8"]
        for k_mine, k_ref in (("mean40", "excess_cagr_vs_spy_mean40"), ("sd40", "sd40"),
                              ("loyo_min", "loyo_min"), ("offsets_positive", "offsets_positive")):
            assert abs(s_spy[k_mine] - ref[k_ref]) < 1e-6, f"READOUT RECONCILE FAIL {tier} {k_mine}"
        tr["readout_reconcile_icw8_vs_spy"] = {"mean40": s_spy["mean40"], "ref": ref["excess_cagr_vs_spy_mean40"], "ok": True}
        log(f"{tier}: readout reconcile OK icw8 vs SPY {s_spy['mean40']:+.5f}")

        # like-for-like: icw8 vs SPY on the IWM-available dates
        tr["icw8_vs_spy"] = {"full_masked": run_vec(bk["icw8"], all_dates, spy_masked, None)[0],
                             "common_masked": run_vec(bk["icw8"], all_dates, spy_masked.where(common), None)[0]}
        for k in ("full_masked", "common_masked"):
            tr["icw8_vs_spy"][k].pop("per_offset")

        tr["hedged"] = {}
        for vname, bd in benches.items():
            full, po_f, _, _ = run_vec(bk["icw8"], all_dates, bd["full"], bd["cost"])
            comm, po_c, _, _ = run_vec(bk["icw8"], all_dates, bd["common"], bd["cost"])
            cost = R.COST_BPS if bd["cost"] is None else bd["cost"]
            ser_f = chain_series(bk["icw8"], all_dates, bd["full"], cost)
            ser_c = chain_series(bk["icw8"], all_dates, bd["common"], cost)
            # oracle: per-date series reproduces backtest_vectors per offset
            chk = ser_f.groupby("off")["h"].mean().reindex(range(40)).to_numpy() * ANN
            assert np.allclose(chk, po_f, atol=1e-12), "chain_series oracle fail"
            ex_f, ex_c = extras(ser_f, spy_s), extras(ser_c, spy_s)
            g = gates(full, comm, ex_f)
            tr["hedged"][vname] = {"full": {**full, **ex_f}, "common": {**comm, **ex_c}, "gates": g}
            log(f"  {tier} {vname}: full {full['mean40']:+.4f} ({full['offsets_positive']}/40, "
                f"LOYO min {full['loyo_min']:+.4f} drop {full['loyo_min_dropped_year']}) common {comm['mean40']:+.4f} "
                f"beta {ex_f['beta_to_spy']['beta']:+.3f} (t {ex_f['beta_to_spy']['beta_t_nw']:+.2f}) "
                f"MDD med {ex_f['mdd_median_over_offsets']:+.3f} -> {g['verdict']}")

        # attribution (not tradable): aligned icw8/noscore dates, IWM-price bench (dates masked identically)
        cd = set(bk["icw8"]) & set(bk["noscore"])
        al = {b: {d: v for d, v in bk[b].items() if d in cd} for b in ("icw8", "noscore")}
        attr = {"aligned_dates": len(cd), "dates_removed": {b: len(set(bk[b]) - cd) for b in al}}
        for wname, bench in (("full", iwm_p), ("common", iwm_p.where(common))):
            _, pi, li, yrs = run_vec(al["icw8"], all_dates, bench, None)
            _, pn, ln, yrs2 = run_vec(al["noscore"], all_dates, bench, None)
            assert yrs == yrs2
            a1 = NX.gap_stats(pi, pn, li, ln, yrs)
            a2 = NX.gap_stats(-pn, np.zeros(40), -ln, np.zeros_like(ln), yrs)
            s_ns_spy = run_vec(al["noscore"], all_dates, spy_masked if wname == "full" else spy_masked.where(common), None)[0]
            s_ns_spy.pop("per_offset")
            attr[wname] = {"icw8_minus_noscore": a1, "iwm_minus_noscore": a2, "noscore_vs_spy_masked": s_ns_spy}
            log(f"  {tier} attribution {wname}: icw8-noscore {a1['mean40']:+.4f} ({a1['offsets_positive']}/40) "
                f"IWM-noscore {a2['mean40']:+.4f} noscore-SPY {s_ns_spy['mean40']:+.4f}")
        tr["attribution"] = attr
        out["tiers"][tier] = tr
        OUT.write_text(json.dumps(out, indent=2, default=str))

    out["verdict_cap150"] = out["tiers"]["cap150"]["hedged"]["primary_15bp"]["gates"]["verdict"]
    OUT.write_text(json.dumps(out, indent=2, default=str))
    log(f"VERDICT cap150: {out['verdict_cap150']} ({time.time()-T0:.0f}s)")


if __name__ == "__main__":
    main()
