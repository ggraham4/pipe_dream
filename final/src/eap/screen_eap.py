"""
WO-5 pre-registered screen of `days_to_next_announce_8k_seasonal` (8-K Item
2.02 seasonal announcement-date estimate), earnings-timing family trial 6.
Registration: models/2026-09-23-earnings-announcement-premium-8k.md Part 1.
Nomination era 2007-2019 ONLY, cap150-eligible, forward_return_tradable_40.

Machinery (vectorized rank_z / per-date Spearman / NW lag 39 / composite
score / fit-weights rule) is copied from insider/screen_insider.py. The 8
composite factors are hardcoded from ic_weighted_composite.PRODUCTION_WEIGHTS
(post-2026-09-22 set, no asset_growth) and asserted against composite.py.

Tests 1-7 as registered; see the doc. Portfolio (test 6) is NET of 15bp per
unit turnover with f_new tracked per offset exactly as
correction_variants.run_offset does, and must reconcile ew8 to
correction_variants_report.json's asset_growth_dropped (0.04321 +/- 0.0010).

Usage: python3.11 screen_eap.py [--null-draws 20]
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
FINAL_WT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent / "reset2026"))
import composite as C  # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
PANEL_PATH = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
BETA_PATH = MAIN_ROOT / "out" / "reset2026" / "beta_feature.parquet"
OUTCOME_PATH = MAIN_ROOT / "out" / "reset2026" / "outcome_cache.parquet"
SIGNAL_PATH = MAIN_ROOT / "out" / "eap" / "eap_signal.parquet"
CV_REPORT = MAIN_ROOT / "out" / "reset2026" / "correction_variants_report.json"
OUT_JSON = MAIN_ROOT / "out" / "eap" / "eap_screen_report.json"
DOC = FINAL_WT / "models" / "2026-09-23-earnings-announcement-premium-8k.md"

NOMINATE_START = pd.Timestamp("2007-01-02")
NOMINATE_END = pd.Timestamp("2019-12-31")
HOLDOUT_START = pd.Timestamp("2020-01-01")
LABEL = "forward_return_tradable_40"
NEW = "days_to_next_announce_8k_seasonal"
OLD = "days_to_next_filing_seasonal"
SIGN = -1
NW_LAG = 39
FLOOR = 0.1
HORIZON = 40
T_BAR = 2.64
COST_BPS = 15.0
RECON_TOL = 0.0010
# ic_weighted_composite.PRODUCTION_WEIGHTS (frozen, full nomination-era fit)
PRODUCTION_WEIGHTS = {
    "momentum_12_1": 0.0497, "pct_from_high_252": 0.0130, "volatility_60": -0.0130,
    "gross_profitability": 0.5956, "accruals": -0.1627, "net_issuance_pct": -0.1399,
    "days_to_next_filing_seasonal": -0.0130, "short_interest_days_to_cover": -0.0130,
}
SIGNS8 = {c: int(np.sign(w)) for c, w in PRODUCTION_WEIGHTS.items()}
F8 = list(SIGNS8)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def newey_west_mean_t(x, lag=NW_LAG):
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return {"mean": np.nan, "t": np.nan, "n": n}
    xc = x - x.mean()
    L = min(lag, n - 1)
    var = np.dot(xc, xc) / n
    for l in range(1, L + 1):
        w = 1.0 - l / (L + 1.0)
        var += 2.0 * w * (np.dot(xc[l:], xc[:-l]) / n)
    var = max(var, 1e-12)
    return {"mean": float(x.mean()), "t": float(x.mean() / np.sqrt(var / n)), "n": int(n)}


def rank_z(df, col):
    r = df.groupby("date")[col].rank(method="average")
    n = df[col].notna().groupby(df["date"]).transform("sum")
    out = (r - 1.0) / (n - 1.0) - 0.5
    return out.where(n >= 2)


def daily_corr(df, x, y, min_n=20):
    g = df[["date", x, y]].replace([np.inf, -np.inf], np.nan).dropna()
    rx = g.groupby("date")[x].rank(); ry = g.groupby("date")[y].rank()
    t = pd.DataFrame({"date": g["date"], "a": rx, "b": ry})
    t["a"] -= t.groupby("date")["a"].transform("mean")
    t["b"] -= t.groupby("date")["b"].transform("mean")
    t["ab"] = t["a"] * t["b"]; t["aa"] = t["a"] ** 2; t["bb"] = t["b"] ** 2
    s = t.groupby("date")[["ab", "aa", "bb"]].sum()
    n = t.groupby("date").size()
    c = s["ab"] / np.sqrt(s["aa"] * s["bb"])
    return c[(n >= min_n) & np.isfinite(c)]


def ic_stats(df, x, y):
    s = daily_corr(df, x, y)
    yrs = s.index.year
    return {"pooled": {**newey_west_mean_t(s.to_numpy()), "n_dates": int(len(s))},
            "odd": newey_west_mean_t(s[yrs % 2 == 1].to_numpy()),
            "even": newey_west_mean_t(s[yrs % 2 == 0].to_numpy())}


def composite_score(df, weights):
    num = pd.Series(0.0, index=df.index); den = pd.Series(0.0, index=df.index)
    cov = pd.Series(0, index=df.index)
    for c, w in weights.items():
        rz = df[f"rz_{c}"]
        num += (rz * w).fillna(0.0); den += np.where(rz.notna(), abs(w), 0.0); cov += rz.notna()
    out = num / den.replace(0, np.nan)
    return out.where(cov > 0)


def fit_weights(t_stats, signs):
    raw = {c: signs[c] * (max(FLOOR, abs(t_stats[c]) - 1.0) if np.isfinite(t_stats[c]) else FLOOR)
           for c in signs}
    tot = sum(abs(v) for v in raw.values())
    return {c: v / tot for c, v in raw.items()}


# ---------------------------------------------------------------- portfolio (net)
SLICES = {}


def build_slices(df):
    d = df["date"].to_numpy()
    starts = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
    ends = np.r_[starts[1:], len(d)]
    SLICES.clear()
    SLICES.update({pd.Timestamp(d[s]): (s, e) for s, e in zip(starts, ends)})


def book_for_date(vol, sc, ret, tick):
    """composite.pick_decile_volq + drop NaN-return picks, returns (gross, set)."""
    ok = np.isfinite(vol) & np.isfinite(sc)
    if ok.sum() < C.N_VOL_QUINTILES * 4:
        return None
    idx = np.flatnonzero(ok)
    q = pd.qcut(vol[idx], C.N_VOL_QUINTILES, labels=False, duplicates="drop")
    picks = []
    for b in np.unique(q):
        bi = idx[q == b]
        k = max(1, int(round(len(bi) * 0.10)))
        picks.extend(bi[np.argsort(-sc[bi])][:k])      # default kind, as pick_decile_volq
    picks = np.array([i for i in picks if np.isfinite(ret[i])], dtype=np.int64)
    if len(picks) == 0:
        return None
    w = 1.0 / np.maximum(vol[picks], 1e-4); w /= w.sum()
    return float(np.sum(w * (1.0 + ret[picks])) - 1.0), set(tick[picks].tolist())


def portfolio_net_excess(df, score_col, dates, spy, cost_bps=COST_BPS):
    """Mean over 40 offsets of annualized mean per-window NET excess vs SPY."""
    h = (cost_bps / 1e4) / 2.0
    vol_all = df["volatility_60"].to_numpy(np.float64)
    sc_all = df[score_col].to_numpy(np.float64)
    ret_all = df["gross_return_40"].to_numpy(np.float64)
    tick_all = df["ticker"].to_numpy()
    per_off, gross_off = [], []
    for off in range(HORIZON):
        prev = set(); ex = []; exg = []
        for d in dates[off::HORIZON]:
            lo, hi = SLICES[d]
            b = book_for_date(vol_all[lo:hi], sc_all[lo:hi], ret_all[lo:hi], tick_all[lo:hi])
            if b is None:
                continue
            g, cur = b
            f_new = sum(1 for t in cur if t not in prev) / len(cur)
            prev = cur
            net = (1.0 + g) * (1.0 - h * f_new) / (1.0 + h * f_new) - 1.0
            s = spy.get(d, np.nan)
            if np.isfinite(s):
                ex.append(net - s); exg.append(g - s)
        per_off.append(np.mean(ex) * 252.0 / HORIZON)
        gross_off.append(np.mean(exg) * 252.0 / HORIZON)
    per_off = np.array(per_off)
    return {"net_mean": float(per_off.mean()), "net_sd": float(per_off.std()),
            "gross_mean": float(np.mean(gross_off)), "n_offsets_positive": int((per_off > 0).sum())}


def prereg_hash():
    txt = DOC.read_text()
    a = txt.index("## Part 1: pre-registration"); b = txt.index("## Part 2: results")
    return hashlib.sha256(txt[a:b].encode()).hexdigest()


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--null-draws", type=int, default=20)
    args = ap.parse_args()
    t0 = time.time()
    assert set(C.FACTOR_SIGNS) - {"asset_growth"} == set(SIGNS8), "composite factor set drifted"
    assert all(C.FACTOR_SIGNS[c] == s for c, s in SIGNS8.items()), "composite sign drifted"
    rep = {"trial": "earnings-timing family 6/6", "signal": NEW, "sign": SIGN, "t_bar": T_BAR,
           "cost_bps": COST_BPS, "prereg_sha256_part1": prereg_hash()}
    log(f"prereg Part 1 sha256 {rep['prereg_sha256_part1']}")

    cols = list(dict.fromkeys(["ticker", "date", "eligible_cap150", "sector", LABEL, "volatility_60"] + F8))
    df = pd.read_parquet(PANEL_PATH, columns=cols)
    df["date"] = pd.to_datetime(df["date"]); df["ticker"] = df["ticker"].astype(str)
    df = df[(df["date"] >= NOMINATE_START) & (df["date"] <= NOMINATE_END) & df["eligible_cap150"]]
    assert df["date"].max() < HOLDOUT_START, "hold-out leak"
    n0 = len(df)
    sig = pd.read_parquet(SIGNAL_PATH); sig["date"] = pd.to_datetime(sig["date"]); sig["ticker"] = sig["ticker"].astype(str)
    sig = sig[(sig["date"] >= NOMINATE_START) & (sig["date"] <= NOMINATE_END)]
    df = df.merge(sig, on=["ticker", "date"], how="left", validate="one_to_one")
    beta = pd.read_parquet(BETA_PATH, columns=["ticker", "date", "beta_252"])
    beta["ticker"] = beta["ticker"].astype(str); beta["date"] = pd.to_datetime(beta["date"])
    beta = beta[(beta["date"] >= NOMINATE_START) & (beta["date"] <= NOMINATE_END)]
    df = df.merge(beta, on=["ticker", "date"], how="left", validate="one_to_one")
    oc = pd.read_parquet(OUTCOME_PATH, columns=["ticker", "date", "gross_return_40"])
    oc["date"] = pd.to_datetime(oc["date"])
    oc = oc[(oc["date"] >= NOMINATE_START) & (oc["date"] <= NOMINATE_END)]
    assert oc["date"].max() < HOLDOUT_START, "hold-out leak (outcomes)"
    spy = oc[oc["ticker"] == "SPY"].set_index("date")["gross_return_40"]
    df = df.merge(oc[~oc["ticker"].isin(["SPY", "USMV"])], on=["ticker", "date"], how="left", validate="one_to_one")
    assert len(df) == n0, "merge changed row count"
    df = df.sort_values(["date", "ticker"]).reset_index(drop=True)
    df["abnormal"] = df[LABEL] - df["beta_252"] * df["date"].map(spy)
    log(f"nomination cap150 rows {len(df):,}, dates {df['date'].nunique():,}, "
        f"{NEW} coverage {df[NEW].notna().mean():.3f}")
    rep["coverage_nonnull"] = float(df[NEW].notna().mean())

    # ---------------- test 1
    t1 = {"raw": ic_stats(df, NEW, LABEL), "beta_adj": ic_stats(df, NEW, "abnormal")}
    rep["test1_ic"] = t1
    log(f"T1 raw IC {t1['raw']['pooled']['mean']:+.4f} t {t1['raw']['pooled']['t']:+.2f} | odd "
        f"{t1['raw']['odd']['mean']:+.4f} (t {t1['raw']['odd']['t']:+.2f}) even {t1['raw']['even']['mean']:+.4f} "
        f"(t {t1['raw']['even']['t']:+.2f}) | beta-adj {t1['beta_adj']['pooled']['mean']:+.4f} "
        f"t {t1['beta_adj']['pooled']['t']:+.2f}")

    # ---------------- test 2
    sec = df["sector"].fillna("Unknown")
    df["_sn_x"] = df[NEW] - df.groupby(["date", sec])[NEW].transform("mean")
    df["_sn_y"] = df[LABEL] - df.groupby(["date", sec])[LABEL].transform("mean")
    t2a = ic_stats(df, "_sn_x", "_sn_y")
    fo = np.full(len(df), np.nan)
    build_slices(df)
    for d, (lo, hi) in SLICES.items():
        g = df.iloc[lo:hi]
        fo[lo:hi] = C.neutralize_on_sector(g[["sector", NEW]], [NEW])[NEW].to_numpy()
    df["_fo_x"] = fo
    t2b = ic_stats(df, "_fo_x", LABEL)
    rep["test2_sector_neutral"] = {"both_sides": t2a, "factor_only_neutralize_on_sector": t2b}
    log(f"T2 both-sides t {t2a['pooled']['t']:+.2f} (IC {t2a['pooled']['mean']:+.4f}) | factor-only t "
        f"{t2b['pooled']['t']:+.2f} (IC {t2b['pooled']['mean']:+.4f})")

    # ---------------- test 3
    s = daily_corr(df, NEW, LABEL)
    grids = []
    for o in range(HORIZON):
        x = s.iloc[o::HORIZON].to_numpy()
        grids.append({"offset": o, "mean": float(x.mean()), "t": float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))),
                      "n": int(len(x))})
    flips = sum(1 for g in grids if np.sign(g["mean"]) != SIGN)
    rep["test3_grid_offsets"] = {"n_sign_flips": flips, "min_mean": min(g["mean"] for g in grids),
                                 "max_mean": max(g["mean"] for g in grids), "grids": grids}
    log(f"T3 grid sign flips {flips}/40, mean range {rep['test3_grid_offsets']['min_mean']:+.4f}.."
        f"{rep['test3_grid_offsets']['max_mean']:+.4f}")

    # ---------------- test 4
    com = df[df[NEW].notna() & df[OLD].notna() & df[LABEL].notna()]
    sn = daily_corr(com, NEW, LABEL); so = daily_corr(com, OLD, LABEL)
    j = sn.index.intersection(so.index)
    diff = (sn[j] - so[j]).to_numpy()
    rep["test4_head_to_head"] = {"n_rows_common": int(len(com)), "ic_new_common": newey_west_mean_t(sn[j].to_numpy()),
                                 "ic_old_common": newey_west_mean_t(so[j].to_numpy()),
                                 "diff_new_minus_old": newey_west_mean_t(diff),
                                 "ic_old_all_rows": newey_west_mean_t(daily_corr(df, OLD, LABEL).to_numpy()),
                                 "corr_new_old_daily_spearman": newey_west_mean_t(daily_corr(com, NEW, OLD).to_numpy())["mean"]}
    h4 = rep["test4_head_to_head"]
    log(f"T4 common rows {h4['n_rows_common']:,}: new {h4['ic_new_common']['mean']:+.4f} (t {h4['ic_new_common']['t']:+.2f}) "
        f"old {h4['ic_old_common']['mean']:+.4f} (t {h4['ic_old_common']['t']:+.2f}) diff t "
        f"{h4['diff_new_minus_old']['t']:+.2f}; rank corr {h4['corr_new_old_daily_spearman']:+.3f}")

    # ---------------- ranks + weight reproduction check
    for c in F8 + [NEW]:
        df[f"rz_{c}"] = rank_z(df, c)
    t_full = {c: newey_west_mean_t(daily_corr(df, c, LABEL).to_numpy())["t"] for c in F8 + [NEW]}
    w8_full = fit_weights({c: t_full[c] for c in F8}, SIGNS8)
    maxdev = max(abs(w8_full[c] - PRODUCTION_WEIGHTS[c]) for c in F8)
    rep["weights_reproduction"] = {"full_t": t_full, "w8_refit": w8_full, "max_abs_dev_vs_production": maxdev}
    log(f"PRODUCTION_WEIGHTS reproduction max |dev| {maxdev:.5f}")
    assert maxdev < 1e-3, f"cannot reproduce PRODUCTION_WEIGHTS (max dev {maxdev})"
    signs9 = {**SIGNS8, NEW: SIGN}
    w9_full = fit_weights(t_full, signs9)
    rep["icw9_full_weights"] = w9_full

    # ---------------- test 5
    yrs = df["date"].dt.year
    oos = {}
    for name, fm, tm in (("fit_odd_test_even", yrs % 2 == 1, yrs % 2 == 0),
                         ("fit_even_test_odd", yrs % 2 == 0, yrs % 2 == 1)):
        fit = df[fm]
        t9 = {k: newey_west_mean_t(daily_corr(fit, k, LABEL).to_numpy())["t"] for k in signs9}
        t8 = {k: t9[k] for k in SIGNS8}
        test = df[tm].copy()
        w9 = fit_weights(t9, signs9); w8 = fit_weights(t8, SIGNS8)
        test["_w9"] = composite_score(test, w9); test["_w8"] = composite_score(test, w8)
        oos[name] = {"w9_weight_on_new": w9[NEW], "t_new_in_fit": t9[NEW],
                     "icw9_raw": newey_west_mean_t(daily_corr(test, "_w9", LABEL).to_numpy()),
                     "icw8_raw": newey_west_mean_t(daily_corr(test, "_w8", LABEL).to_numpy()),
                     "icw9_beta_adj": newey_west_mean_t(daily_corr(test, "_w9", "abnormal").to_numpy()),
                     "icw8_beta_adj": newey_west_mean_t(daily_corr(test, "_w8", "abnormal").to_numpy())}
        o = oos[name]
        log(f"T5 {name}: w_new {o['w9_weight_on_new']:+.4f}; icw9 {o['icw9_raw']['mean']:+.5f} vs icw8 "
            f"{o['icw8_raw']['mean']:+.5f} raw; {o['icw9_beta_adj']['mean']:+.5f} vs {o['icw8_beta_adj']['mean']:+.5f} beta-adj")
    rep["test5_ablation_oos"] = oos

    # ---------------- test 6
    dates = [pd.Timestamp(x) for x in sorted(df["date"].unique())]
    df["comp_ew8"] = composite_score(df, {c: SIGNS8[c] / len(F8) for c in F8})
    df["comp_icw8"] = composite_score(df, PRODUCTION_WEIGHTS)
    df["comp_icw9"] = composite_score(df, w9_full)
    port = {}
    port["ew8"] = portfolio_net_excess(df, "comp_ew8", dates, spy)
    cv = json.loads(CV_REPORT.read_text())["backtest_variants"]["asset_growth_dropped"]["mean_excess_cagr_vs_spy"]
    port["reconciliation"] = {"ew8_net": port["ew8"]["net_mean"], "correction_variants_asset_growth_dropped": cv,
                              "abs_diff": abs(port["ew8"]["net_mean"] - cv), "tol": RECON_TOL}
    log(f"T6 ew8 net {port['ew8']['net_mean']:+.5f} vs correction_variants {cv:+.5f}")
    assert abs(port["ew8"]["net_mean"] - cv) <= RECON_TOL, "ew8 book does not reconcile -- harness bug"
    port["icw8"] = portfolio_net_excess(df, "comp_icw8", dates, spy)
    port["icw9"] = portfolio_net_excess(df, "comp_icw9", dates, spy)
    log(f"T6 icw8 net {port['icw8']['net_mean']:+.5f} | icw9 net {port['icw9']['net_mean']:+.5f}")
    rng = np.random.default_rng(20260923)
    saved = df[f"rz_{NEW}"].copy()
    raw = df[NEW].to_numpy()
    nulls = []
    for i in range(args.null_draws):
        perm = raw.copy()
        for lo, hi in SLICES.values():
            perm[lo:hi] = rng.permutation(perm[lo:hi])
        df["_perm"] = perm
        df[f"rz_{NEW}"] = rank_z(df, "_perm")
        df["_s"] = composite_score(df, w9_full)
        nulls.append(portfolio_net_excess(df, "_s", dates, spy)["net_mean"])
        log(f"  null draw {i+1}/{args.null_draws}: {nulls[-1]:+.5f}")
    df[f"rz_{NEW}"] = saved
    nulls = np.array(nulls)
    port["null"] = {"draws": nulls.tolist(), "p50": float(np.percentile(nulls, 50)),
                    "p80": float(np.percentile(nulls, 80)), "mean": float(nulls.mean()), "sd": float(nulls.std()),
                    "percentile_of_real": float((nulls < port["icw9"]["net_mean"]).mean())}
    rep["test6_portfolio"] = port
    log(f"T6 icw9 {port['icw9']['net_mean']:+.5f} vs null p50 {port['null']['p50']:+.5f} p80 {port['null']['p80']:+.5f}")

    # ---------------- test 7
    ys = s.index.year
    tot = float((SIGN * s).sum())
    loyo = {}
    for y in sorted(set(ys)):
        loyo[int(y)] = {"t_without": newey_west_mean_t(s[ys != y].to_numpy())["t"],
                        "share": float((SIGN * s[ys == y]).sum()) / tot if tot != 0 else np.nan,
                        "year_mean_ic": float(s[ys == y].mean())}
    rep["test7_loyo"] = {"by_year": loyo, "min_abs_t": float(min(abs(v["t_without"]) for v in loyo.values())),
                         "max_share": float(max(v["share"] for v in loyo.values())),
                         "total_signed_sum": tot}
    log(f"T7 LOYO min |t| {rep['test7_loyo']['min_abs_t']:.2f}, max share {rep['test7_loyo']['max_share']:.3f}")

    # ---------------- verdict
    p = t1["raw"]["pooled"]
    conds = {
        "t1_sign_and_t": bool(np.sign(p["t"]) == SIGN and abs(p["t"]) >= T_BAR),
        "t1_both_halves_negative": bool(t1["raw"]["odd"]["mean"] < 0 and t1["raw"]["even"]["mean"] < 0),
        "t2_both_sides_t_le_-1": bool(t2a["pooled"]["t"] <= -1.0),
        "t3_zero_flips": bool(flips == 0),
        "t6_beats_null_p80": bool(port["icw9"]["net_mean"] > port["null"]["p80"]),
        "t6_beats_icw8": bool(port["icw9"]["net_mean"] > port["icw8"]["net_mean"]),
        "t7_max_share_le_45pct": bool(rep["test7_loyo"]["max_share"] <= 0.45),
    }
    rep["verdict"] = {**conds, "NOMINATED": bool(all(conds.values()))}
    log(f"VERDICT {rep['verdict']}")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=float))
    log(f"wrote {OUT_JSON} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
