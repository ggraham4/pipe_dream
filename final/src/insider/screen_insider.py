"""
Pre-registered screen of the SEC Form 4 insider columns against the
composite (models/2026-09-23-insider-congress-preregistration.md, k = 2).
Nomination era 2007-2019 only, cap150-eligible, forward_return_tradable_40.

Tests (numbering follows the pre-registration):
  1 IC screen, raw and beta-adjusted, pooled / odd / even, NW lag 39
  2 sector-neutral IC (per-date sector demeaning == OLS on sector dummies)
  3 incremental (partial) IC after residualizing on the composite score
  4 composite ablation: 8 vs 9 factors, equal-weight and IC-weighted (OOS halves)
  5 decile_volq portfolio, 40 offsets, vs 20 within-date shuffles of the factor
  6 event study at the first panel date on/after each new-buyer filing
    (t: Newey-West lag 2 on monthly means, since 40d windows overlap months)

The newey_west_mean_t and fit-weights rule are copied from
reset2026/ic_weighted_composite.py (audit worktree, uncommitted at the time)
so this file does not depend on unlanded code. The composite itself is
recomputed vectorized and asserted equal to composite.compute_composite on
sampled dates before anything is scored.

Usage: python3 screen_insider.py [--null-draws 20]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "reset2026"))
import composite as C  # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
PANEL_PATH = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
BETA_PATH = MAIN_ROOT / "out" / "reset2026" / "beta_feature.parquet"
OUTCOME_PATH = MAIN_ROOT / "out" / "reset2026" / "outcome_cache.parquet"
INSIDER_PATH = MAIN_ROOT / "out" / "insider" / "insider_features.parquet"
EVENTS_PATH = MAIN_ROOT / "out" / "insider" / "insider_events.parquet"
TICKERS_MASTER = MAIN_ROOT / "data" / "sharadar" / "tickers_master.csv"
OUT_JSON = MAIN_ROOT / "out" / "insider" / "insider_screen_report.json"

NOMINATE_START = pd.Timestamp("2007-01-02")
NOMINATE_END = pd.Timestamp("2019-12-31")
LABEL = "forward_return_tradable_40"
NW_LAG = 39
FLOOR = 0.1
HORIZON = 40
TRIALS = {"ins_buyers_90": +1, "ins_sellers_90": -1}
T_BAR = 2.24  # two-sided 0.05, Bonferroni k=2
# ic_weighted_composite.PRODUCTION_WEIGHTS (frozen, full nomination-era fit)
PRODUCTION_WEIGHTS = {
    "momentum_12_1": 0.0497, "pct_from_high_252": 0.0130, "volatility_60": -0.0130,
    "gross_profitability": 0.5956, "accruals": -0.1627, "net_issuance_pct": -0.1399,
    "days_to_next_filing_seasonal": -0.0130, "short_interest_days_to_cover": -0.0130,
}


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


# ---------------------------------------------------------------- vectorized helpers
def rank_z(df, col):
    """composite.rank_z per date, vectorized."""
    r = df.groupby("date")[col].rank(method="average")
    n = df[col].notna().groupby(df["date"]).transform("sum")
    out = (r - 1.0) / (n - 1.0) - 0.5
    return out.where(n >= 2)


def daily_corr(df, x, y, min_n=20):
    """Per-date Spearman corr of x,y (rows with both finite). Returns Series by date."""
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


def resid_on(df, ycol, xcol):
    """Per-date OLS residual of ycol on [1, xcol]."""
    g = df[["date", ycol, xcol]]
    ok = g[ycol].notna() & g[xcol].notna()
    y = g[ycol].where(ok); x = g[xcol].where(ok)
    ym = y.groupby(g["date"]).transform("mean"); xm = x.groupby(g["date"]).transform("mean")
    cov = ((x - xm) * (y - ym)).groupby(g["date"]).transform("sum")
    var = ((x - xm) ** 2).groupby(g["date"]).transform("sum")
    b = cov / var.replace(0, np.nan)
    return (y - ym) - b * (x - xm)


def composite_score(df, weights):
    """Coverage-aware weighted mean of signed rank_z. Equal weights ==
    composite.compute_composite(neutral=False); PRODUCTION_WEIGHTS ==
    ic_weighted_composite.compute_composite_ic_weighted."""
    num = pd.Series(0.0, index=df.index); den = pd.Series(0.0, index=df.index)
    cov = pd.Series(0, index=df.index)
    for c, w in weights.items():
        rz = df[f"rz_{c}"]
        num += (rz * w).fillna(0.0); den += np.where(rz.notna(), abs(w), 0.0); cov += rz.notna()
    out = num / den.replace(0, np.nan)
    return out.where(cov > 0)


def equal_weights(cols, signs):
    return {c: signs[c] / len(cols) for c in cols}


def fit_weights(t_stats, signs):
    raw = {c: signs[c] * (max(FLOOR, abs(t_stats[c]) - 1.0) if np.isfinite(t_stats[c]) else FLOOR)
           for c in signs}
    tot = sum(abs(v) for v in raw.values())
    return {c: v / tot for c, v in raw.items()}


# ---------------------------------------------------------------- portfolio
SLICES = {}


def build_slices(df):
    """df is sorted by date; row range per date for O(1) per-date access."""
    d = df["date"].to_numpy()
    starts = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
    ends = np.r_[starts[1:], len(d)]
    SLICES.clear()
    SLICES.update({pd.Timestamp(d[s]): (s, e) for s, e in zip(starts, ends)})


def decile_volq_windows(df, score_col, rebal_dates):
    """Same construction as composite.pick_decile_volq, returns per-window gross."""
    out = []
    for d in rebal_dates:
        lo, hi = SLICES[d]
        g = df.iloc[lo:hi]
        vol = g["volatility_60"].to_numpy(np.float64)
        sc = g[score_col].to_numpy(np.float64)
        ret = g["gross_return_40"].to_numpy(np.float64)
        ok = np.isfinite(vol) & np.isfinite(sc)
        if ok.sum() < C.N_VOL_QUINTILES * 4:
            continue
        idx = np.flatnonzero(ok)
        q = pd.qcut(vol[idx], C.N_VOL_QUINTILES, labels=False, duplicates="drop")
        picks = []
        for b in np.unique(q):
            bi = idx[q == b]
            k = max(1, int(round(len(bi) * 0.10)))
            picks.extend(bi[np.argsort(-sc[bi], kind="stable")][:k])
        picks = np.array([i for i in picks if np.isfinite(ret[i])])
        if len(picks) == 0:
            continue
        w = 1.0 / np.maximum(vol[picks], 1e-4); w /= w.sum()
        out.append((d, float(np.sum(w * ret[picks]))))
    return out


def portfolio_excess(df, score_col, dates, spy):
    """Mean over 40 offsets of annualized mean per-window excess vs SPY."""
    per_off = []
    for off in range(HORIZON):
        w = decile_volq_windows(df, score_col, dates[off::HORIZON])
        ex = [g - spy.get(d, np.nan) for d, g in w]
        ex = np.array([e for e in ex if np.isfinite(e)])
        per_off.append(ex.mean() * 252.0 / HORIZON)
    per_off = np.array(per_off)
    return float(per_off.mean()), float(per_off.std())


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--null-draws", type=int, default=20)
    args = ap.parse_args()
    t0 = time.time()
    rep = {"trials": TRIALS, "t_bar": T_BAR}

    cols = list(dict.fromkeys(["ticker", "date", "eligible_cap150", "sector", LABEL, "volatility_60"]
                              + C.FACTOR_COLS))
    df = pd.read_parquet(PANEL_PATH, columns=cols)
    df["date"] = pd.to_datetime(df["date"]); df["ticker"] = df["ticker"].astype(str)
    df = df[(df["date"] >= NOMINATE_START) & (df["date"] <= NOMINATE_END) & df["eligible_cap150"]]
    n0 = len(df)
    ins = pd.read_parquet(INSIDER_PATH); ins["ticker"] = ins["ticker"].astype(str); ins["date"] = pd.to_datetime(ins["date"])
    df = df.merge(ins, on=["ticker", "date"], how="left")
    beta = pd.read_parquet(BETA_PATH, columns=["ticker", "date", "beta_252"]); beta["ticker"] = beta["ticker"].astype(str); beta["date"] = pd.to_datetime(beta["date"])
    df = df.merge(beta, on=["ticker", "date"], how="left")
    oc = pd.read_parquet(OUTCOME_PATH, columns=["ticker", "date", "gross_return_40"])
    oc["date"] = pd.to_datetime(oc["date"])
    spy = oc[oc["ticker"] == "SPY"].set_index("date")["gross_return_40"]
    df = df.merge(oc[~oc["ticker"].isin(["SPY", "USMV"])], on=["ticker", "date"], how="left")
    assert len(df) == n0, "merge changed row count"
    df = df.sort_values(["date", "ticker"]).reset_index(drop=True)
    df["abnormal"] = df[LABEL] - df["beta_252"] * df["date"].map(spy)
    log(f"nomination cap150 rows {len(df):,}, dates {df['date'].nunique():,}")

    # --- coverage / zero mass
    cov = {}
    for c in list(TRIALS) + ["ins_cluster_buy_90"]:
        cov[c] = {"nonnull": float(df[c].notna().mean()), "fire_rate": float((df[c] > 0).mean())}
    for c in TRIALS:
        df[f"rz_{c}"] = rank_z(df, c)
        cov[c]["rank_z_of_zero_median"] = float(df.loc[df[c] == 0, f"rz_{c}"].median())
    rep["coverage"] = cov
    log(f"coverage {json.dumps(cov)}")

    for c in C.FACTOR_COLS:
        df[f"rz_{c}"] = rank_z(df, c)
    ew8 = equal_weights(C.FACTOR_COLS, C.FACTOR_SIGNS)
    df["comp_ew"] = composite_score(df, ew8)
    df["comp_icw"] = composite_score(df, PRODUCTION_WEIGHTS)

    # harness check: vectorized == composite.compute_composite on sampled dates
    dates = [pd.Timestamp(x) for x in sorted(df["date"].unique())]
    for d in dates[:: max(1, len(dates) // 12)]:
        g = df[df["date"] == d].reset_index(drop=True)
        ref = C.compute_composite(g, neutral=False)["composite"].to_numpy()
        assert np.allclose(ref, g["comp_ew"].to_numpy(), equal_nan=True, atol=1e-12), f"composite mismatch {d}"
    log("harness check passed: vectorized composite == composite.compute_composite")

    # --- test 1..3 for each trial
    rep["tests"] = {}
    for c, sign in TRIALS.items():
        r = {}
        r["ic_raw"] = ic_stats(df, c, LABEL)
        r["ic_beta_adj"] = ic_stats(df, c, "abnormal")
        # sector-neutral: demean within (date, sector)
        sn = f"{c}_sn"
        df[sn] = df[c] - df.groupby(["date", df["sector"].fillna("Unknown")])[c].transform("mean")
        r["ic_sector_neutral_raw"] = ic_stats(df, sn, LABEL)
        # partial IC on each composite (ranks residualized on the composite rank)
        for comp in ("comp_ew", "comp_icw"):
            tmp = df[["date", c, LABEL, "abnormal", comp]].copy()
            tmp["rx"] = tmp.groupby("date")[c].rank(); tmp["rc"] = tmp.groupby("date")[comp].rank()
            tmp["ry"] = tmp.groupby("date")[LABEL].rank(); tmp["ra"] = tmp.groupby("date")["abnormal"].rank()
            tmp["ex"] = resid_on(tmp, "rx", "rc"); tmp["ey"] = resid_on(tmp, "ry", "rc")
            tmp["ea"] = resid_on(tmp, "ra", "rc")
            r[f"partial_ic_raw_given_{comp}"] = ic_stats(tmp, "ex", "ey")
            r[f"partial_ic_beta_adj_given_{comp}"] = ic_stats(tmp, "ex", "ea")
            r[f"corr_with_{comp}"] = newey_west_mean_t(daily_corr(df, c, comp).to_numpy())["mean"]
        rep["tests"][c] = r
        p = r["ic_raw"]["pooled"]
        log(f"{c}: IC raw {p['mean']:+.4f} t {p['t']:+.2f} | odd {r['ic_raw']['odd']['t']:+.2f} "
            f"even {r['ic_raw']['even']['t']:+.2f} | beta-adj t {r['ic_beta_adj']['pooled']['t']:+.2f} | "
            f"sector-neutral t {r['ic_sector_neutral_raw']['pooled']['t']:+.2f} | "
            f"partial|ew t {r['partial_ic_raw_given_comp_ew']['pooled']['t']:+.2f} "
            f"partial|icw t {r['partial_ic_raw_given_comp_icw']['pooled']['t']:+.2f}")

    # --- test 4: composite ablation
    yrs = df["date"].dt.year
    abl = {}
    abl["ew8"] = {"raw": ic_stats(df, "comp_ew", LABEL), "beta_adj": ic_stats(df, "comp_ew", "abnormal")}
    abl["icw8_production"] = {"raw": ic_stats(df, "comp_icw", LABEL),
                              "beta_adj": ic_stats(df, "comp_icw", "abnormal")}
    for c, sign in TRIALS.items():
        signs9 = {**C.FACTOR_SIGNS, c: sign}
        df["_s"] = composite_score(df, equal_weights(list(signs9), signs9))
        abl[f"ew9_{c}"] = {"raw": ic_stats(df, "_s", LABEL), "beta_adj": ic_stats(df, "_s", "abnormal")}
        # IC-weighted, out of sample on halves: fit on one half, score the other
        oos = {}
        for fit_name, fit_mask, test_mask in (("fit_odd_test_even", yrs % 2 == 1, yrs % 2 == 0),
                                              ("fit_even_test_odd", yrs % 2 == 0, yrs % 2 == 1)):
            fit = df[fit_mask]
            t9 = {k: newey_west_mean_t(daily_corr(fit, k, LABEL).to_numpy())["t"] for k in signs9}
            t8 = {k: t9[k] for k in C.FACTOR_SIGNS}
            test = df[test_mask].copy()
            test["_w9"] = composite_score(test, fit_weights(t9, signs9))
            test["_w8"] = composite_score(test, fit_weights(t8, C.FACTOR_SIGNS))
            oos[fit_name] = {
                "w9_weight_on_new": fit_weights(t9, signs9)[c],
                "icw9_raw": newey_west_mean_t(daily_corr(test, "_w9", LABEL).to_numpy()),
                "icw8_raw": newey_west_mean_t(daily_corr(test, "_w8", LABEL).to_numpy()),
                "icw9_beta_adj": newey_west_mean_t(daily_corr(test, "_w9", "abnormal").to_numpy()),
                "icw8_beta_adj": newey_west_mean_t(daily_corr(test, "_w8", "abnormal").to_numpy()),
            }
        abl[f"icw_oos_{c}"] = oos
    rep["ablation"] = abl
    for k, v in abl.items():
        if "raw" in v:
            log(f"ablation {k:26s} IC raw {v['raw']['pooled']['mean']:+.4f} (t {v['raw']['pooled']['t']:+.2f})  "
                f"beta-adj {v['beta_adj']['pooled']['mean']:+.4f} (t {v['beta_adj']['pooled']['t']:+.2f})")
        else:
            for h, o in v.items():
                log(f"ablation {k} {h}: w_new {o['w9_weight_on_new']:+.3f}  "
                    f"icw9 {o['icw9_raw']['mean']:+.4f} vs icw8 {o['icw8_raw']['mean']:+.4f} (raw); "
                    f"{o['icw9_beta_adj']['mean']:+.4f} vs {o['icw8_beta_adj']['mean']:+.4f} (beta-adj)")

    # --- test 5: portfolio vs within-date shuffle null
    build_slices(df)
    port = {}
    base_mean, base_sd = portfolio_excess(df, "comp_ew", dates, spy)
    port["ew8"] = {"excess_cagr_mean_over_offsets": base_mean, "sd_over_offsets": base_sd}
    log(f"portfolio ew8 decile_volq excess {base_mean:+.4f}/yr (offset sd {base_sd:.4f})")
    rng = np.random.default_rng(20260923)
    for c, sign in TRIALS.items():
        signs9 = {**C.FACTOR_SIGNS, c: sign}
        w9 = equal_weights(list(signs9), signs9)
        df["_s"] = composite_score(df, w9)
        real, real_sd = portfolio_excess(df, "_s", dates, spy)
        nulls = []
        saved = df[f"rz_{c}"].copy()
        for i in range(args.null_draws):
            # permute the raw column within each date, then re-rank (same marginals)
            perm = df.groupby("date")[c].transform(lambda s: s.sample(frac=1.0, random_state=int(rng.integers(1 << 31))).to_numpy())
            df["_perm"] = perm
            df[f"rz_{c}"] = rank_z(df, "_perm")
            df["_s"] = composite_score(df, w9)
            nulls.append(portfolio_excess(df, "_s", dates, spy)[0])
            log(f"  {c} null draw {i+1}/{args.null_draws}: {nulls[-1]:+.4f}")
        df[f"rz_{c}"] = saved
        nulls = np.array(nulls)
        port[f"ew9_{c}"] = {"excess_cagr_mean_over_offsets": real, "sd_over_offsets": real_sd,
                            "null_p50": float(np.percentile(nulls, 50)), "null_p80": float(np.percentile(nulls, 80)),
                            "null_mean": float(nulls.mean()), "null_sd": float(nulls.std()),
                            "percentile_of_real": float((nulls < real).mean()), "nulls": nulls.tolist()}
        log(f"portfolio ew9+{c}: {real:+.4f}/yr vs null p50 {np.percentile(nulls,50):+.4f} "
            f"p80 {np.percentile(nulls,80):+.4f} -> pctile {(nulls < real).mean():.2f}")
    rep["portfolio"] = port

    # --- test 6: event study (first panel date on/after a filing adding a new O/D buyer)
    ev = pd.read_parquet(EVENTS_PATH)
    ev = ev[ev["is_od"] & (ev["code"] == "P") & ev["filing_date"].between(NOMINATE_START, NOMINATE_END)]
    tm = pd.read_csv(TICKERS_MASTER, usecols=["ticker", "secfilings"])
    tm["cik"] = pd.to_numeric(tm["secfilings"].str.extract(r"CIK=0*(\d+)")[0], errors="coerce")
    ev = ev.assign(cik=ev["issuer_cik"].astype("int64")).merge(
        tm[["ticker", "cik"]].dropna().astype({"cik": "int64"}), on="cik")
    evd = ev.groupby(["ticker", "filing_date"]).agg(n_owners=("owner_cik", "nunique"),
                                                   value=("value", "sum")).reset_index()
    base = df[["ticker", "date", LABEL, "abnormal"]].copy()
    for y in (LABEL, "abnormal"):
        base[f"x_{y}"] = base[y] - base.groupby("date")[y].transform("mean")
    base = base.sort_values("date")
    evd = evd.sort_values("filing_date")
    hit = pd.merge_asof(evd, base, left_on="filing_date", right_on="date", by="ticker",
                        direction="forward", tolerance=pd.Timedelta(days=5))
    hit = hit.dropna(subset=["x_" + LABEL])
    es = {"n_events": int(len(hit))}
    for name, sub in (("all", hit), ("cluster_2plus", hit[hit["n_owners"] >= 2]),
                      ("value_ge_100k", hit[hit["value"] >= 1e5])):
        row = {"n": int(len(sub))}
        for y in (LABEL, "abnormal"):
            m = sub.groupby(sub["date"].dt.to_period("M"))["x_" + y].mean()
            row[y] = {"mean_excess_40d": float(sub["x_" + y].mean()),
                      # monthly means overlap (40d ~ 2 months): NW lag 2, not iid
                      "month_nw2_t": newey_west_mean_t(m.to_numpy(), lag=2)["t"],
                      "n_months": int(len(m))}
        es[name] = row
        log(f"event study {name:14s} n={row['n']:6d} excess40 {row[LABEL]['mean_excess_40d']:+.4f} "
            f"(t {row[LABEL]['month_nw2_t']:+.2f})  beta-adj {row['abnormal']['mean_excess_40d']:+.4f} "
            f"(t {row['abnormal']['month_nw2_t']:+.2f})")
    rep["event_study"] = es

    # --- verdicts per the registered pass rule
    ver = {}
    for c, sign in TRIALS.items():
        r = rep["tests"][c]
        p = r["ic_raw"]["pooled"]
        conds = {
            "sign_and_t": np.sign(p["mean"]) == sign and abs(p["t"]) >= T_BAR,
            "both_halves_sign": np.sign(r["ic_raw"]["odd"]["mean"]) == sign and np.sign(r["ic_raw"]["even"]["mean"]) == sign,
            "sector_neutral_sign": np.sign(r["ic_sector_neutral_raw"]["pooled"]["mean"]) == sign,
            "beats_null_p80": port[f"ew9_{c}"]["excess_cagr_mean_over_offsets"] > port[f"ew9_{c}"]["null_p80"],
        }
        ver[c] = {**{k: bool(v) for k, v in conds.items()}, "nominated": bool(all(conds.values()))}
        log(f"VERDICT {c}: {ver[c]}")
    rep["verdicts"] = ver

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(rep, f, indent=2, default=float)
    log(f"wrote {OUT_JSON} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
