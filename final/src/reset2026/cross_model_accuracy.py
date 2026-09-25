"""
Cross-model rank-accuracy comparison -- icw8 (split-half, genuinely OOS)
vs. q75, xrank, and simple baselines, on their common pre-2020
intersection. Pre-registered 2026-09-23 in
final/models/2026-09-22-composite-model-corrections.md section 19 --
read that BEFORE this file; every design decision here (which return
decides the outcome, which t-stat, how split-half weights are fit, why
row 8 is dropped) is committed there in advance, not decided here.

HOLD-OUT GUARD: every read below is filtered to strictly before
2020-01-01 at load time (parquet predicate pushdown / query strings), not
by loading everything and dropping rows after. A final assert enforces
this on the assembled row set regardless.

Usage: python3 cross_model_accuracy.py
Output: prints the comparison tables; writes
    out/reset2026/cross_model_accuracy_report.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C                    # noqa: E402
import ic_weighted_composite as ICW       # noqa: E402  (per_factor_t, fit_weights, compute_composite_ic_weighted, PRODUCTION_WEIGHTS)

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
PANEL_PATH = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
BETA_PATH = MAIN_ROOT / "out" / "reset2026" / "beta_feature.parquet"
OUTCOME_PATH = MAIN_ROOT / "out" / "reset2026" / "outcome_cache.parquet"
Q75_PATH = MAIN_ROOT / "out" / "sweep" / "scores" / "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40.parquet"
XRANK_PATH = MAIN_ROOT / "out" / "sweep" / "scores" / "price_fund_h40_xrank_trd_xgb_reg_d3e01r100_expanding_cap500k_pit_s40.parquet"
OUT_JSON = Path(__file__).resolve().parent.parent.parent / "out" / "reset2026" / "cross_model_accuracy_report.json"

HOLDOUT_CUTOFF = pd.Timestamp("2020-01-01")
HOLDOUT_CUTOFF_STR = "2020-01-01"  # composite_panel.parquet / beta_feature.parquet store `date` as ISO strings
NOMINATE_START = pd.Timestamp("2007-01-02")
NOMINATE_END = pd.Timestamp("2019-12-31")
LABEL = "forward_return_tradable_40"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def plain_t(x):
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        return {"mean": np.nan, "t": np.nan, "n": n}
    mean = x.mean()
    se = x.std(ddof=1) / np.sqrt(n)
    t = mean / se if se > 0 else np.nan
    return {"mean": float(mean), "t": float(t), "n": int(n)}


def pooled_spearman_by_date(df, xcol, ycol, date_col="date"):
    g = df[[date_col, xcol, ycol]].dropna()
    out = {}
    for d, gd in g.groupby(date_col):
        if len(gd) < 20:
            continue
        c = gd[xcol].corr(gd[ycol], method="spearman")
        if pd.notna(c):
            out[d] = float(c)
    return out


def fama_macbeth_r2_by_date(df, xcol, ycol, date_col="date"):
    """Reused verbatim from model_audit.py's fama_macbeth_r2 (per-date OLS,
    R^2 = 1 - SS_res/SS_tot), per the pre-registration's citation."""
    out = {}
    for d, g in df.dropna(subset=[xcol, ycol]).groupby(date_col):
        if len(g) < 30:
            continue
        x = g[xcol].to_numpy(np.float64)
        y = g[ycol].to_numpy(np.float64)
        X = np.column_stack([np.ones(len(x)), x])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        yhat = X @ beta
        ss_res = np.sum((y - yhat) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        if ss_tot > 0:
            out[d] = float(1 - ss_res / ss_tot)
    return out


def summarize_series(d_by_date, years):
    """d_by_date: {date: value}. Returns overall/odd/even plain-t summaries."""
    dates = sorted(d_by_date)
    vals = np.array([d_by_date[d] for d in dates])
    yrs = np.array([years[d] for d in dates])
    overall = plain_t(vals)
    odd = plain_t(vals[yrs % 2 == 1])
    even = plain_t(vals[yrs % 2 == 0])
    return {"overall": overall, "odd_years": odd, "even_years": even, "n_dates": len(dates)}


def main():
    t0 = time.time()

    log("loading composite panel (pre-2020, cap150-eligible) ...")
    need = list(dict.fromkeys(
        ["ticker", "date", "eligible_cap150", LABEL] + C.FACTOR_COLS))
    panel = pd.read_parquet(
        PANEL_PATH, columns=need,
        filters=[("date", "<", HOLDOUT_CUTOFF_STR)],
    )
    panel["date"] = pd.to_datetime(panel["date"])
    panel["ticker"] = panel["ticker"].astype(str)
    panel = panel[panel["eligible_cap150"]].copy()
    log(f"  {len(panel):,} cap150-eligible pre-2020 rows, "
        f"{panel['date'].nunique()} dates")

    log("loading beta + outcome (SPY) for beta-adjustment, pre-2020 ...")
    beta = pd.read_parquet(BETA_PATH, columns=["ticker", "date", "beta_252"],
                            filters=[("date", "<", HOLDOUT_CUTOFF_STR)])
    beta["date"] = pd.to_datetime(beta["date"])
    beta["ticker"] = beta["ticker"].astype(str)

    outcomes = pd.read_parquet(OUTCOME_PATH, filters=[("date", "<", HOLDOUT_CUTOFF)])
    outcomes["date"] = pd.to_datetime(outcomes["date"])
    spy_fwd = outcomes[outcomes["ticker"] == "SPY"].set_index("date")["gross_return_40"]

    panel = panel.merge(beta, on=["ticker", "date"], how="left")
    panel["spy_fwd_40"] = panel["date"].map(spy_fwd)
    panel["abnormal_return"] = panel[LABEL] - panel["beta_252"] * panel["spy_fwd_40"]

    log("loading q75 / xrank score caches, pre-2020 ...")
    q75 = pd.read_parquet(Q75_PATH, columns=["timepoint", "ticker", "score"],
                           filters=[("timepoint", "<", HOLDOUT_CUTOFF)])
    q75 = q75.rename(columns={"timepoint": "date", "score": "q75_score"})
    q75["date"] = pd.to_datetime(q75["date"])
    q75["ticker"] = q75["ticker"].astype(str)

    xrank = pd.read_parquet(XRANK_PATH, columns=["timepoint", "ticker", "score"],
                             filters=[("timepoint", "<", HOLDOUT_CUTOFF)])
    xrank = xrank.rename(columns={"timepoint": "date", "score": "xrank_score"})
    xrank["date"] = pd.to_datetime(xrank["date"])
    xrank["ticker"] = xrank["ticker"].astype(str)

    assert panel["date"].max() < HOLDOUT_CUTOFF
    assert q75["date"].max() < HOLDOUT_CUTOFF
    assert xrank["date"].max() < HOLDOUT_CUTOFF
    log("hold-out guard OK: all three sources strictly pre-2020")

    # -----------------------------------------------------------------
    # Score every model on its OWN native cap150 cross-section first.
    # -----------------------------------------------------------------
    log("fitting icw8 split-half weights (odd/even nomination years, full cap150 panel) ...")
    years = panel["date"].dt.year
    odd_panel = panel[years % 2 == 1]
    even_panel = panel[years % 2 == 0]
    t_odd = ICW.per_factor_t(odd_panel, C.FACTOR_COLS)
    t_even = ICW.per_factor_t(even_panel, C.FACTOR_COLS)
    w_odd = ICW.fit_weights(t_odd, C.FACTOR_COLS)
    w_even = ICW.fit_weights(t_even, C.FACTOR_COLS)
    log(f"  w_odd (scores even years): {w_odd}")
    log(f"  w_even (scores odd years): {w_even}")

    log("scoring icw8 split-half (odd-fit -> even dates, even-fit -> odd dates) ...")
    parts = []
    for d, g in panel.groupby("date"):
        gg = g.reset_index(drop=True)
        w = w_odd if d.year % 2 == 0 else w_even  # OOS: score with the OTHER half's fit
        sc = ICW.compute_composite_ic_weighted(gg, weights=w)
        sc["date"] = d
        parts.append(sc)
    icw8_split = pd.concat(parts, ignore_index=True).rename(columns={"composite": "icw8_split"})

    log("scoring icw8 full-era PRODUCTION_WEIGHTS (context only) ...")
    parts = []
    for d, g in panel.groupby("date"):
        gg = g.reset_index(drop=True)
        sc = ICW.compute_composite_ic_weighted(gg, weights=ICW.PRODUCTION_WEIGHTS)
        sc["date"] = d
        parts.append(sc)
    icw8_full = pd.concat(parts, ignore_index=True).rename(columns={"composite": "icw8_full"})

    log("scoring ew8 (equal-weight, corrected 8-factor composite.py) ...")
    parts = []
    for d, g in panel.groupby("date"):
        gg = g.reset_index(drop=True)
        sc = C.compute_composite(gg, neutral=False)
        sc["date"] = d
        parts.append(sc)
    ew8 = pd.concat(parts, ignore_index=True).rename(columns={"composite": "ew8"})

    log("scoring gross_profitability-alone and low-vol baselines ...")
    panel["gp_alone"] = C.rank_z(panel["gross_profitability"])
    panel["low_vol"] = -C.rank_z(panel["volatility_60"])

    # -----------------------------------------------------------------
    # Assemble: intersection of (panel rows with a return) x q75 x xrank.
    # -----------------------------------------------------------------
    log("assembling intersection ...")
    base = panel[["ticker", "date", LABEL, "abnormal_return", "gp_alone", "low_vol"]].dropna(
        subset=[LABEL])
    base = base.merge(icw8_split[["ticker", "date", "icw8_split"]], on=["ticker", "date"], how="inner")
    base = base.merge(icw8_full[["ticker", "date", "icw8_full"]], on=["ticker", "date"], how="inner")
    base = base.merge(ew8[["ticker", "date", "ew8"]], on=["ticker", "date"], how="inner")
    base = base.merge(q75, on=["ticker", "date"], how="inner")
    base = base.merge(xrank, on=["ticker", "date"], how="inner")

    assert base["date"].max() < HOLDOUT_CUTOFF, "hold-out guard violated post-merge"

    n_per_date = base.groupby("date").size()
    log(f"  intersection: {len(base):,} rows, {base['date'].nunique()} dates, "
        f"N/date min={n_per_date.min()} median={n_per_date.median():.0f} max={n_per_date.max()}")

    years_by_date = {d: d.year for d in base["date"].unique()}

    models = {
        "icw8_split_half": "icw8_split",
        "icw8_full_era_PRODUCTION_WEIGHTS": "icw8_full",
        "ew8": "ew8",
        "gross_profitability_alone": "gp_alone",
        "q75": "q75_score",
        "xrank": "xrank_score",
        "low_vol_neg_volatility_60": "low_vol",
    }

    report = {"generated": pd.Timestamp.now().isoformat(),
              "n_rows": int(len(base)), "n_dates": int(base["date"].nunique()),
              "n_per_date": {"min": int(n_per_date.min()), "median": float(n_per_date.median()),
                             "max": int(n_per_date.max())},
              "models": {}}

    log("\n=== Per-model rank accuracy (raw and beta-adjusted) ===")
    rho_raw_by_model = {}
    for name, col in models.items():
        rho_raw = pooled_spearman_by_date(base, col, LABEL)
        rho_abn = pooled_spearman_by_date(base, col, "abnormal_return")
        r2_raw = fama_macbeth_r2_by_date(base, col, LABEL)
        r2_abn = fama_macbeth_r2_by_date(base, col, "abnormal_return")
        rho_raw_by_model[name] = rho_raw
        summ = {
            "rho_raw": summarize_series(rho_raw, years_by_date),
            "rho_beta_adjusted": summarize_series(rho_abn, years_by_date),
            "fm_r2_raw_mean": float(np.mean(list(r2_raw.values()))) if r2_raw else None,
            "fm_r2_beta_adjusted_mean": float(np.mean(list(r2_abn.values()))) if r2_abn else None,
        }
        report["models"][name] = summ
        log(f"  {name:32s} rho_raw={summ['rho_raw']['overall']['mean']:+.4f} "
            f"t={summ['rho_raw']['overall']['t']:+.2f}  "
            f"FM-R2_raw={summ['fm_r2_raw_mean']:.4f}" if summ['fm_r2_raw_mean'] is not None else "")

    log("\n=== PRIMARY COMPARISON: paired diff rho(icw8_split_half) - rho(q75), raw returns ===")
    common_dates = sorted(set(rho_raw_by_model["icw8_split_half"]) & set(rho_raw_by_model["q75"]))
    diffs = {d: rho_raw_by_model["icw8_split_half"][d] - rho_raw_by_model["q75"][d] for d in common_dates}
    diff_summary = summarize_series(diffs, years_by_date)
    report["primary_comparison"] = diff_summary

    mean_diff = diff_summary["overall"]["mean"]
    t_diff = diff_summary["overall"]["t"]
    odd_mean = diff_summary["odd_years"]["mean"]
    even_mean = diff_summary["even_years"]["mean"]
    same_sign = pd.notna(odd_mean) and pd.notna(even_mean) and (np.sign(odd_mean) == np.sign(even_mean))

    if mean_diff > 0 and t_diff >= 2 and same_sign:
        outcome = "SUCCESS"
    elif mean_diff <= 0:
        outcome = "KILL"
    else:
        outcome = "MIDDLE"

    report["outcome"] = outcome
    report["required_labels"] = [
        "Intersection is roughly q75's large-cap-leaning pool (cap500k+), not cap150's full breadth.",
        "Single s40 grid (one rebalance-offset cadence), not this project's usual 40-offset average.",
        "Descriptive -- the running trial count in PREREGISTRATION.md is unchanged by this analysis.",
    ]

    log(f"\n  mean diff={mean_diff:+.4f}  t={t_diff:+.2f}  odd={odd_mean:+.4f}  even={even_mean:+.4f}  "
        f"same_sign={same_sign}")
    log(f"\n  OUTCOME: {outcome}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log(f"\n-> {OUT_JSON} ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
