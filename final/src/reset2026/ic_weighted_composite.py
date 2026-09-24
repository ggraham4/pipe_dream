"""
IC-shrinkage weighting -- see PREREGISTRATION.md's "IC-shrinkage weighting
(2026-09-22)" section, written before this ran. Objective is rank
prediction (Gabe's explicit reframe), so pooled IC is the target metric
directly, not a diagnostic on the way to a portfolio number.

w_k_raw = max(FLOOR, |t_k| - 1), w_k = sign_k * w_k_raw / sum(w_raw).
t_k is each factor's pooled Spearman-IC NW t-stat. Genuinely
out-of-sample: weights fit on odd years, IC measured on even years, and
vice versa -- never fit and measured on the same data. Also reports the
full-period (in-sample) number for context, clearly labeled.

Metrics: pooled Spearman IC and Kendall tau, NW t, on both raw and
beta-adjusted returns. No portfolio/CAGR computation -- rank accuracy is
the target this round, not dollars.

Usage: python3 ic_weighted_composite.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kendalltau

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C  # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
PANEL_PATH = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
BETA_PATH = MAIN_ROOT / "out" / "reset2026" / "beta_feature.parquet"
OUTCOME_PATH = MAIN_ROOT / "out" / "reset2026" / "outcome_cache.parquet"
OUT_JSON = MAIN_ROOT / "out" / "reset2026" / "ic_weighted_composite_report.json"

NOMINATE_START = pd.Timestamp("2007-01-02")
NOMINATE_END = pd.Timestamp("2019-12-31")
LABEL = "forward_return_tradable_40"
NW_LAG = 39
FLOOR = 0.1


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
    t = x.mean() / np.sqrt(var / n) if var > 0 else np.nan
    return {"mean": float(x.mean()), "t": float(t), "n": int(n)}


def pooled_corr(df, xcol, ycol, date_col="date", method="spearman"):
    g = df[[date_col, xcol, ycol]].dropna()
    out = {}
    for d, gd in g.groupby(date_col):
        if len(gd) < 20:
            continue
        if method == "spearman":
            c = gd[xcol].corr(gd[ycol], method="spearman")
        else:
            c, _ = kendalltau(gd[xcol].to_numpy(), gd[ycol].to_numpy())
        if pd.notna(c):
            out[d] = float(c)
    s = pd.Series(out)
    stats = newey_west_mean_t(s.to_numpy())
    stats["n_dates"] = int(len(s))
    return stats


def per_factor_t(nom, factor_cols):
    """Pooled Spearman-IC NW t-stat per factor, raw sign (not yet
    multiplied by FACTOR_SIGNS) -- matches model_audit.py's convention."""
    out = {}
    for c in factor_cols:
        stats = pooled_corr(nom, c, LABEL)
        out[c] = stats
    return out


def fit_weights(t_stats, factor_cols):
    raw = {}
    for c in factor_cols:
        t = t_stats[c]["t"]
        mag = max(FLOOR, abs(t) - 1.0) if np.isfinite(t) else FLOOR
        raw[c] = C.FACTOR_SIGNS[c] * mag
    total = sum(abs(v) for v in raw.values())
    return {c: raw[c] / total for c in factor_cols}


# Frozen, not recomputed on each import -- a specific, reviewed artifact
# (full nomination-era fit, w_k = sign_k * max(0.1, |t_k|-1) / normalizer),
# same status as FACTOR_SIGNS itself: a fixed constant, not something that
# silently drifts if the panel is refreshed. See corrections doc section 12
# for the full derivation and the out-of-sample validation this rests on.
PRODUCTION_WEIGHTS = {
    "momentum_12_1": 0.0497,
    "pct_from_high_252": 0.0130,
    "volatility_60": -0.0130,
    "gross_profitability": 0.5956,
    "accruals": -0.1627,
    "net_issuance_pct": -0.1399,
    "days_to_next_filing_seasonal": -0.0130,
    "short_interest_days_to_cover": -0.0130,
}


def compute_composite_ic_weighted(df_date, weights=None):
    """Drop-in analog to composite.compute_composite(), using
    PRODUCTION_WEIGHTS (or a supplied override) instead of equal weights.
    Returns a frame with `ticker`, `composite` (the weighted score), same
    shape/contract as compute_composite()'s output.

    Renormalizes by the sum of |weight| actually available per row --
    without this, a row missing `gross_profitability` (~60% of the total
    weight) would have its score computed off the remaining ~40% only,
    silently changing scale and distorting rank for exactly the rows
    equal-weighting's `.mean(skipna=True)` handles gracefully. This is the
    weighted analog of that same coverage-aware averaging, not new
    behavior."""
    weights = weights or PRODUCTION_WEIGHTS
    factor_cols = list(weights)
    weighted = pd.DataFrame(index=df_date.index)
    avail_weight = pd.DataFrame(index=df_date.index)
    for c in factor_cols:
        rz = C.rank_z(df_date[c])
        weighted[c] = rz * weights[c]
        avail_weight[c] = np.where(rz.notna(), abs(weights[c]), 0.0)
    out = pd.DataFrame(index=df_date.index)
    out["ticker"] = df_date["ticker"].values
    out["coverage"] = weighted.notna().sum(axis=1).values
    total_avail_weight = avail_weight.sum(axis=1)
    raw_sum = weighted.sum(axis=1, skipna=True)
    out["composite"] = np.where(total_avail_weight > 0, raw_sum / total_avail_weight, np.nan)
    out.loc[out["coverage"] == 0, "composite"] = np.nan
    return out


def compute_weighted_score(df_date, weights, factor_cols):
    """Renormalizes by available |weight| per row -- see
    compute_composite_ic_weighted's docstring for why this matters (a row
    missing gross_profitability, ~60% of the weight, would otherwise be
    scored off the remaining ~40% only). Found and fixed 2026-09-22 after
    this exact function had already produced the first reported results
    below -- re-run afterward to confirm the fix doesn't move them; see
    the corrections doc section 12 for the verification."""
    weighted = pd.DataFrame(index=df_date.index)
    avail_weight = pd.DataFrame(index=df_date.index)
    for c in factor_cols:
        rz = C.rank_z(df_date[c])
        weighted[c] = rz * weights[c]
        avail_weight[c] = np.where(rz.notna(), abs(weights[c]), 0.0)
    coverage = weighted.notna().sum(axis=1)
    total_avail_weight = avail_weight.sum(axis=1)
    raw_sum = weighted.sum(axis=1, skipna=True)
    out = pd.Series(np.where(total_avail_weight > 0, raw_sum / total_avail_weight, np.nan),
                     index=df_date.index)
    out[coverage == 0] = np.nan
    return out


def score_variant(nom, weights, factor_cols, beta_lookup, spy_lookup, label_out):
    parts = []
    for d, g in nom.groupby("date"):
        gg = g.reset_index(drop=True)
        s = compute_weighted_score(gg, weights, factor_cols)
        parts.append(pd.DataFrame({"date": d, "ticker": gg["ticker"], "score": s.to_numpy(),
                                    "label": gg[LABEL].to_numpy()}))
    scored = pd.concat(parts, ignore_index=True)
    ic_raw = pooled_corr(scored, "score", "label", method="spearman")
    tau_raw = pooled_corr(scored, "score", "label", method="kendall")

    scored["beta_252"] = list(zip(scored["ticker"], scored["date"]))
    scored["beta_252"] = scored["beta_252"].map(beta_lookup)
    scored["spy_fwd"] = scored["date"].map(spy_lookup)
    scored["abnormal"] = scored["label"] - scored["beta_252"] * scored["spy_fwd"]
    ic_ab = pooled_corr(scored, "score", "abnormal", method="spearman")
    tau_ab = pooled_corr(scored, "score", "abnormal", method="kendall")

    log(f"  [{label_out}] IC_raw={ic_raw['mean']:+.4f}(t={ic_raw['t']:+.2f})  "
        f"tau_raw={tau_raw['mean']:+.4f}(t={tau_raw['t']:+.2f})  "
        f"IC_beta_adj={ic_ab['mean']:+.4f}(t={ic_ab['t']:+.2f})  "
        f"tau_beta_adj={tau_ab['mean']:+.4f}(t={tau_ab['t']:+.2f})")
    return {"ic_raw": ic_raw, "tau_raw": tau_raw, "ic_beta_adjusted": ic_ab, "tau_beta_adjusted": tau_ab}


def main():
    t0 = time.time()
    need = list(dict.fromkeys(["ticker", "date", "eligible_cap150", LABEL] + C.FACTOR_COLS))
    panel = pd.read_parquet(PANEL_PATH, columns=need)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["ticker"] = panel["ticker"].astype(str)
    nom = panel[(panel["date"] >= NOMINATE_START) & (panel["date"] <= NOMINATE_END)
                & panel["eligible_cap150"]].copy()
    log(f"nomination-era cap150-eligible rows: {len(nom):,}")

    beta = pd.read_parquet(BETA_PATH, columns=["ticker", "date", "beta_252"])
    beta["date"] = pd.to_datetime(beta["date"])
    beta["ticker"] = beta["ticker"].astype(str)
    beta_lookup = dict(zip(zip(beta["ticker"], beta["date"]), beta["beta_252"]))

    outcomes = pd.read_parquet(OUTCOME_PATH, columns=["ticker", "date", "gross_return_40"])
    outcomes["date"] = pd.to_datetime(outcomes["date"])
    spy_lookup = outcomes[outcomes["ticker"] == "SPY"].set_index("date")["gross_return_40"]

    factor_cols = C.FACTOR_COLS
    years = nom["date"].dt.year
    odd = nom[years % 2 == 1]
    even = nom[years % 2 == 0]

    log("\n=== Per-factor pooled IC + t, each half (for weight-fitting) ===")
    t_odd = per_factor_t(odd, factor_cols)
    t_even = per_factor_t(even, factor_cols)
    t_full = per_factor_t(nom, factor_cols)
    for c in factor_cols:
        log(f"  {c:32s} odd t={t_odd[c]['t']:+.2f}  even t={t_even[c]['t']:+.2f}  full t={t_full[c]['t']:+.2f}")

    w_odd = fit_weights(t_odd, factor_cols)
    w_even = fit_weights(t_even, factor_cols)
    w_full = fit_weights(t_full, factor_cols)
    w_equal = {c: (1.0 / len(factor_cols)) * C.FACTOR_SIGNS[c] for c in factor_cols}

    log("\n=== Weights fit on ODD years vs EQUAL ===")
    for c in factor_cols:
        log(f"  {c:32s} odd-fit={w_odd[c]:+.4f}  equal={w_equal[c]:+.4f}")

    report = {"per_factor_t": {"odd": t_odd, "even": t_even, "full": t_full},
              "weights": {"odd": w_odd, "even": w_even, "full": w_full, "equal": w_equal}}

    log("\n=== OUT-OF-SAMPLE: weights fit on ODD, IC measured on EVEN ===")
    report["oos_fit_odd_test_even_weighted"] = score_variant(even, w_odd, factor_cols, beta_lookup, spy_lookup,
                                                              "weighted, fit-odd/test-even")
    report["oos_fit_odd_test_even_equalweight"] = score_variant(even, w_equal, factor_cols, beta_lookup, spy_lookup,
                                                                 "equal-weight, tested on even (same data)")

    log("\n=== OUT-OF-SAMPLE: weights fit on EVEN, IC measured on ODD ===")
    report["oos_fit_even_test_odd_weighted"] = score_variant(odd, w_even, factor_cols, beta_lookup, spy_lookup,
                                                              "weighted, fit-even/test-odd")
    report["oos_fit_even_test_odd_equalweight"] = score_variant(odd, w_equal, factor_cols, beta_lookup, spy_lookup,
                                                                 "equal-weight, tested on odd (same data)")

    log("\n=== IN-SAMPLE (context only, not a forecasting claim): full-period fit, full-period test ===")
    report["insample_full_weighted"] = score_variant(nom, w_full, factor_cols, beta_lookup, spy_lookup,
                                                       "weighted, full-period (IN-SAMPLE)")
    report["insample_full_equalweight"] = score_variant(nom, w_equal, factor_cols, beta_lookup, spy_lookup,
                                                          "equal-weight, full-period")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log(f"\nwrote {OUT_JSON} ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
