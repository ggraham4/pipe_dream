"""
Diagnostic for theoretical model addition #1 (market-beta term): does the
composite implicitly load on beta already (plausible, given the physics
audit's own finding that the model's edge is "a low-volatility tilt" --
volatility_60 and beta are correlated but distinct), and does scoring
against beta-ADJUSTED (market-model abnormal) returns instead of raw
returns change the measured IC?

abnormal_return_i,t = forward_return_tradable_40_i,t
                       - beta_252_i,t * spy_forward_return_40_t

beta_252 from build_beta_feature.py (mechanical, trailing 252d, causal).
spy_forward_return_40 from outcome_cache.parquet's own SPY row (the same
survivorship-correct, same-convention 40-day return used as the benchmark
everywhere else in this package).

Nomination era only (2007-2019), cap150, pooled Spearman IC with
Newey-West t at lag 39 -- identical methodology to model_audit.py, so the
raw-return IC here should reproduce that document's +0.0262 as a sanity
check before trusting the beta-adjusted number.

Usage: python3 beta_diagnostic.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C  # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
PANEL_PATH = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
BETA_PATH = MAIN_ROOT / "out" / "reset2026" / "beta_feature.parquet"
OUTCOME_PATH = MAIN_ROOT / "out" / "reset2026" / "outcome_cache.parquet"

NOMINATE_START = pd.Timestamp("2007-01-02")
NOMINATE_END = pd.Timestamp("2019-12-31")
LABEL = "forward_return_tradable_40"
NW_LAG = 39


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


def pooled_ic(df, xcol, ycol, date_col="date"):
    g = df[[date_col, xcol, ycol]].dropna()
    out = {}
    for d, gd in g.groupby(date_col):
        if len(gd) < 20:
            continue
        c = gd[xcol].corr(gd[ycol], method="spearman")
        if pd.notna(c):
            out[d] = float(c)
    s = pd.Series(out)
    stats = newey_west_mean_t(s.to_numpy())
    stats["n_dates"] = int(len(s))
    return stats


def main():
    t0 = time.time()
    need = list(dict.fromkeys(["ticker", "date", "sector", "volatility_60",
                                "eligible_cap150", LABEL] + C.FACTOR_COLS))
    panel = pd.read_parquet(PANEL_PATH, columns=need)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["ticker"] = panel["ticker"].astype(str)

    beta = pd.read_parquet(BETA_PATH, columns=["ticker", "date", "beta_252"])
    beta["date"] = pd.to_datetime(beta["date"])
    beta["ticker"] = beta["ticker"].astype(str)

    outcomes = pd.read_parquet(OUTCOME_PATH)
    outcomes["date"] = pd.to_datetime(outcomes["date"])
    spy = outcomes[outcomes["ticker"] == "SPY"].set_index("date")["gross_return_40"]

    log("merging beta onto panel ...")
    panel = panel.merge(beta, on=["ticker", "date"], how="left")
    panel["spy_fwd_40"] = panel["date"].map(spy)
    panel["abnormal_return"] = panel[LABEL] - panel["beta_252"] * panel["spy_fwd_40"]

    nom = panel[(panel["date"] >= NOMINATE_START) & (panel["date"] <= NOMINATE_END)
                & panel["eligible_cap150"]].copy()
    log(f"nomination-era cap150-eligible rows: {len(nom):,}, "
        f"beta coverage {nom['beta_252'].notna().mean():.1%}")

    log("computing composite scores (adopted, asset_growth-dropped) ...")
    parts = []
    for d, g in nom.groupby("date"):
        gg = g.reset_index(drop=True)
        scored = C.compute_composite(gg, neutral=False)
        scored["date"] = d
        parts.append(scored)
    scores = pd.concat(parts, ignore_index=True)
    scores = scores.merge(nom[["ticker", "date", LABEL, "abnormal_return", "beta_252"]],
                           on=["ticker", "date"], how="left")

    log(f"\n=== Does the composite implicitly load on beta? ===")
    beta_corr = pooled_ic(scores.rename(columns={"beta_252": "__beta__"}), "composite", "__beta__")
    print(f"  pooled Spearman corr(composite, beta_252): {beta_corr['mean']:+.4f}  t={beta_corr['t']:+.2f}  "
          f"n={beta_corr['n_dates']} dates")

    log(f"\n=== IC vs RAW forward_return_tradable_40 (sanity check vs model_audit.py's +0.0262) ===")
    raw_ic = pooled_ic(scores, "composite", LABEL)
    print(f"  IC={raw_ic['mean']:+.4f}  t={raw_ic['t']:+.2f}  n={raw_ic['n_dates']} dates")

    log(f"\n=== IC vs BETA-ADJUSTED (market-model abnormal) return ===")
    ab_ic = pooled_ic(scores, "composite", "abnormal_return")
    print(f"  IC={ab_ic['mean']:+.4f}  t={ab_ic['t']:+.2f}  n={ab_ic['n_dates']} dates")

    log(f"\ndone ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
